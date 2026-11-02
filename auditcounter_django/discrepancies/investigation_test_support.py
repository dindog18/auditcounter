from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import Client
from accounts_receivable.matching_test_support import PartialDeliveryFixture
from accounts_receivable.services import records, pages
from accounts_receivable.services.catalog import model, party_key
from .models import CaseInvestigation, CaseActivity
from .services import investigation as workflow
from .presentation import serialize_findings, serialize_investigation


class InvestigationScenarios(PartialDeliveryFixture):
    def setup_case(self):
        self.fixture(receipts=(100,),invoice_price=18500)
        self.save()
        self.finding=self.case.discrepancy_findings.get(finding_code='PRICE_VARIANCE')

    def data(self, **values):
        self.case.refresh_from_db()
        return dict(revision=workflow.investigation_revision(self.case),**values)

    def start(self):
        return workflow.start_investigation(self.case,self.data(actor_label='Finance desk'))

    def investigating(self):
        self.start()
        return workflow.update_investigation(self.case,self.data(workflow_status='investigating',responsible_department='Accounting',next_action='Verify PO pricing.'))

    def review(self, decision='confirmed', notes='Compared invoice against the PO.'):
        return workflow.review_finding(self.case,self.data(finding_id=self.finding.pk,decision=decision,notes=notes,actor_label='Reviewer label'))

    def close(self, **values):
        values=dict(resolution_type='business_exception_accepted',resolution_notes='Commercial variance documented and accepted.',**values)
        return workflow.resolve_investigation(self.case,self.data(**values))

    def correct_price(self, price=18000):
        type(self.invoice_line).objects.filter(pk=self.invoice_line.pk).update(unit_price=price,line_total=price*100)
        invoice=type(self.invoice_line.invoice).objects.get(pk=self.invoice_line.invoice_id)
        invoice.subtotal=invoice.total_amount=price*100
        invoice.save()

    def test_creation_and_repeat_start_are_idempotent(self):
        self.setup_case()
        request=self.data()
        first=workflow.start_investigation(self.case,request)
        second=workflow.start_investigation(self.case,request)
        self.assertEqual(first.pk,second.pk)
        self.assertEqual(CaseInvestigation.objects.count(),1)
        self.assertEqual(first.activities.count(),1)
        self.assertEqual(first.workflow_status,'needs_review')
        self.assertEqual(first.ap_transaction_id if self.mode=='ap' else first.ar_transaction_id,self.case.pk)

    def test_status_transitions_and_routing_history(self):
        self.setup_case()
        investigation=self.start()
        with self.assertRaises(ValidationError):
            workflow.update_investigation(self.case,self.data(workflow_status='waiting'))
        for status in ('investigating','waiting','investigating'):
            investigation=workflow.update_investigation(self.case,self.data(workflow_status=status,responsible_department='Warehouse',next_action='Confirm receiving evidence.'))
        self.assertEqual(investigation.workflow_status,'investigating')
        self.assertEqual(investigation.responsible_department,'Warehouse')
        self.assertEqual(list(investigation.activities.values_list('activity_type',flat=True)),['opened','status_change','status_change','status_change'])
        with self.assertRaises(ValidationError):
            workflow.update_investigation(self.case,self.data(workflow_status='resolved',responsible_department='Changed'))
        investigation.refresh_from_db()
        self.assertEqual(investigation.responsible_department,'Warehouse')

    def test_notes_append_and_stale_writes_are_rejected(self):
        self.setup_case()
        investigation=self.start()
        stale=self.data(notes='Duplicate client action')
        workflow.add_investigation_note(self.case,self.data(notes='First observation',actor_label='Unverified staff'))
        with self.assertRaises(ValidationError) as error:
            workflow.add_investigation_note(self.case,stale)
        self.assertEqual(error.exception.code,'conflict')
        workflow.add_investigation_note(self.case,self.data(notes='Second observation'))
        self.assertEqual(list(investigation.activities.filter(activity_type='note').values_list('notes',flat=True)),['First observation','Second observation'])
        self.assertEqual(investigation.activities.filter(activity_type='note').first().actor_label,'Unverified staff')

    def test_finding_reviews_persist_separately_from_calculated_state(self):
        self.setup_case()
        self.investigating()
        initial=self.case.calculate_reconciliation()
        for decision in ('needs_more_evidence','confirmed','dismissed'):
            self.review(decision,'Documented review reason.')
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.review_decision,'dismissed')
        self.assertEqual(self.finding.status,'open')
        self.assertEqual(self.case.calculate_reconciliation(),initial)
        investigation=CaseInvestigation.objects.get()
        self.assertEqual(investigation.activities.filter(activity_type='review').count(),3)
        entry=investigation.activities.filter(activity_type='review').first()
        self.assertEqual(Decimal(entry.details['finding']['difference_amount']),50000)
        self.assertEqual(entry.details['decision'],'needs_more_evidence')
        self.assertTrue(entry.details['evidence_ids'])
        self.case.refresh_reconciliation_status()
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.review_decision,'dismissed')
        self.assertEqual(investigation.activities.filter(activity_type='review').count(),3)

    def test_dismissal_requires_explanation(self):
        self.setup_case()
        investigation=self.start()
        count=investigation.activities.count()
        with self.assertRaises(ValidationError):
            self.review('dismissed',' ')
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.review_decision,'unreviewed')
        self.assertEqual(investigation.activities.count(),count)

    def test_resolution_validates_state_details_and_current_reviews(self):
        self.setup_case()
        investigation=self.investigating()
        count=investigation.activities.count()
        for payload in ({},{'resolution_type':'other'},{'resolution_type':'other','resolution_notes':' '},
                        {'resolution_type':'business_exception_accepted','resolution_notes':'Accept without reviews.'}):
            with self.assertRaises(ValidationError):
                workflow.resolve_investigation(self.case,self.data(**payload))
        self.review('needs_more_evidence','Need a corrected invoice.')
        with self.assertRaises(ValidationError):
            self.close()
        investigation.refresh_from_db()
        self.assertEqual(investigation.workflow_status,'investigating')
        self.assertEqual(investigation.activities.filter(activity_type='resolution').count(),0)
        self.assertGreaterEqual(investigation.activities.count(),count)

    def test_resolution_and_reopening_preserve_history_and_accounting(self):
        self.setup_case()
        investigation=self.investigating()
        self.review()
        original_status=self.case.calculate_reconciliation()
        evidence_count=self.finding.evidence.count()
        investigation=self.close()
        closed_at=investigation.closed_at
        self.assertEqual(investigation.workflow_status,'resolved')
        self.assertEqual(self.case.calculate_reconciliation(),original_status)
        self.case.refresh_from_db()
        self.assertEqual(self.case.reconciliation_status,original_status[0])
        self.invoice_line.refresh_from_db()
        self.assertEqual(self.invoice_line.unit_price,Decimal('18500'))
        self.finding.refresh_from_db()
        self.assertEqual(self.finding.status,'open')
        self.assertEqual(self.finding.evidence.count(),evidence_count)
        with self.assertRaises(ValidationError):
            workflow.reopen_investigation(self.case,self.data(reason=' '))
        reopened=workflow.reopen_investigation(self.case,self.data(reason='New receiving information needs review.'))
        self.assertEqual(reopened.pk,investigation.pk)
        self.assertEqual(reopened.workflow_status,'needs_review')
        self.assertIsNone(reopened.closed_at)
        self.assertEqual(reopened.resolution_notes,'Commercial variance documented and accepted.')
        self.assertEqual(reopened.activities.filter(activity_type='resolution').count(),1)
        self.assertEqual(reopened.activities.filter(activity_type='reopening').count(),1)
        previous=reopened.activities.filter(activity_type='reopening').get().details['previous_resolution']
        self.assertEqual(previous['closed_at'],closed_at.isoformat())
        self.assertEqual(previous['resolution_type'],'business_exception_accepted')

    def test_direct_documented_dismissal_and_closed_edit_guards(self):
        self.setup_case()
        self.start()
        self.review('dismissed','Extraction mapping requires investigation outside this case.')
        investigation=workflow.resolve_investigation(self.case,self.data(workflow_status='dismissed',resolution_type='false_positive',resolution_notes='False-positive mapping documented.'))
        self.assertEqual(investigation.workflow_status,'dismissed')
        with self.assertRaises(ValidationError):
            self.review()
        with self.assertRaises(ValidationError):
            workflow.update_investigation(self.case,self.data(next_action='Edit closed case'))
        workflow.add_investigation_note(self.case,self.data(notes='Additional closure context.'))
        self.assertEqual(investigation.activities.filter(activity_type='note').count(),1)

    def test_correction_resolution_requires_current_evidence_and_matched_calculation(self):
        self.setup_case()
        self.investigating()
        historical=self.finding.evidence.filter(evidence_type='SI').first()
        payload=dict(resolution_type='source_correction_verified',resolution_notes='Source correction verified.')
        with self.assertRaises(ValidationError):
            workflow.resolve_investigation(self.case,self.data(**payload,document_references=[{'kind':'sales_invoice','record_id':self.invoice_line.invoice_id}]))
        self.correct_price()
        with self.assertRaises(ValidationError):
            workflow.resolve_investigation(self.case,self.data(**payload))
        with self.assertRaises(ValidationError):
            workflow.resolve_investigation(self.case,self.data(**payload,evidence_ids=[historical.pk]))
        investigation=workflow.resolve_investigation(self.case,self.data(**payload,document_references=[{'kind':'sales_invoice','record_id':self.invoice_line.invoice_id}]))
        self.assertEqual(investigation.workflow_status,'resolved')
        self.assertTrue(investigation.resolution_evidence)
        snapshot=investigation.activities.get(activity_type='resolution').details['evidence'][0]
        self.assertEqual(snapshot['source']['source_record_id'],str(self.invoice_line.invoice_id))
        self.assertEqual(Decimal(snapshot['lines'][0]['observed_value']['line']['unit_price']),18000)

    def test_cross_case_finding_and_evidence_references_rejected(self):
        self.setup_case()
        investigation=self.start()
        other=model(self.mode,'Transaction').objects.create(**{party_key(self.mode):self.party},currency='PHP')
        other.sales_invoices.add(self.invoice_line.invoice)
        other_finding=other.discrepancy_findings.filter(status='open').first()
        with self.assertRaises(ValidationError):
            workflow.review_finding(self.case,self.data(finding_id=other_finding.pk,decision='confirmed',notes='Wrong case'))
        with self.assertRaises(ValidationError):
            CaseActivity.objects.create(investigation=investigation,finding=other_finding,activity_type='review')
        with self.assertRaises(ValidationError):
            CaseActivity.objects.bulk_create([CaseActivity(investigation=investigation,finding=other_finding,activity_type='review')])
        setattr(other_finding, 'ap_transaction' if self.mode=='ap' else 'ar_transaction', self.case)
        with self.assertRaises(ValidationError):
            CaseActivity.objects.create(investigation=investigation,finding=other_finding,activity_type='review')
        other_evidence=other_finding.evidence.first()
        with self.assertRaises(ValidationError):
            workflow.resolve_references(self.case,{'evidence_ids':[other_evidence.pk]},require_current=False)
        self.assertEqual(investigation.activities.count(),1)

    def test_review_and_workflow_updates_roll_back_when_activity_capture_fails(self):
        self.setup_case()
        investigation=self.start()
        before=investigation.activities.count()
        with patch('discrepancies.services.investigation.append_activity',side_effect=RuntimeError('Interrupted')):
            with self.assertRaises(RuntimeError):
                self.review()
            with self.assertRaises(RuntimeError):
                workflow.update_investigation(self.case,self.data(workflow_status='investigating',responsible_department='Should roll back'))
        self.finding.refresh_from_db()
        investigation.refresh_from_db()
        self.assertEqual(self.finding.review_decision,'unreviewed')
        self.assertEqual(investigation.workflow_status,'needs_review')
        self.assertEqual(investigation.responsible_department,'')
        self.assertEqual(investigation.activities.count(),before)

    def test_changed_evidence_flags_closed_resolution_and_stales_review(self):
        self.setup_case()
        investigation=self.investigating()
        self.review()
        investigation=self.close()
        count=investigation.activities.count()
        self.case.refresh_reconciliation_status()
        investigation.refresh_from_db()
        self.assertFalse(investigation.review_required)
        self.assertEqual(investigation.activities.count(),count)
        self.correct_price(18600)
        investigation.refresh_from_db()
        self.assertTrue(investigation.review_required)
        self.assertEqual(investigation.workflow_status,'resolved')
        self.assertEqual(investigation.resolution_type,'business_exception_accepted')
        self.assertEqual(investigation.activities.filter(activity_type='evidence_changed').count(),1)
        self.case.refresh_reconciliation_status()
        self.assertEqual(investigation.activities.filter(activity_type='evidence_changed').count(),1)
        finding=next(row for row in serialize_findings(self.case) if row['id']==self.finding.pk)
        self.assertTrue(finding['reviewStale'])
        review=investigation.activities.get(activity_type='review')
        self.assertEqual(Decimal(review.details['finding']['difference_amount']),50000)

    def test_source_change_invalidates_workflow_revision(self):
        self.setup_case()
        self.start()
        payload=self.data(notes='Based on old evidence.')
        self.correct_price(18600)
        with self.assertRaises(ValidationError) as error:
            workflow.add_investigation_note(self.case,payload)
        self.assertEqual(error.exception.code,'conflict')

    def test_activity_is_append_only(self):
        self.setup_case()
        investigation=self.start()
        activity=investigation.activities.get()
        for mutation in (lambda:activity.save(),lambda:activity.delete(),
                         lambda:CaseActivity.objects.filter(pk=activity.pk).update(notes='Changed'),
                         lambda:CaseActivity.objects.filter(pk=activity.pk).delete(),
                         lambda:CaseActivity.objects.bulk_update([activity],['notes'])):
            with self.assertRaises(ValidationError):
                mutation()
        activity.refresh_from_db()
        self.assertEqual(activity.notes,'Investigation opened.')

    def test_api_csrf_revision_and_reload(self):
        self.setup_case()
        base='/accounts-payable/' if self.mode=='ap' else '/accounts-receivable/'
        endpoint=f'{base}api/investigation-start/{self.case.pk}/'
        payload=self.data(actor_label='Optional label')
        self.assertEqual(Client(enforce_csrf_checks=True).post(endpoint,payload,content_type='application/json').status_code,403)
        response=self.client.post(endpoint,payload,content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(self.client.get(endpoint).status_code,405)
        note_endpoint=f'{base}api/investigation-note/{self.case.pk}/'
        response=self.client.post(note_endpoint,{'revision':'old','notes':'Stale'},content_type='application/json')
        self.assertEqual(response.status_code,409)
        self.assertEqual(self.client.post(note_endpoint,self.data(notes='Saved through API'),content_type='application/json').status_code,200)
        for _ in range(2):
            response=self.client.get(f'{base}reconciliation/{self.case.pk}/')
            self.assertEqual(response.status_code,200)
            row=response.context['finance_state']['reconciliation'][0]
            self.assertEqual(row['investigation']['workflowStatus'],'needs_review')
            self.assertEqual(row['investigation']['history'][-1]['notes'],'Saved through API')
            self.assertTrue(row['investigationRevision'])
