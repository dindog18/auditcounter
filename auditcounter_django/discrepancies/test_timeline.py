from django.test import TestCase
from django.db import transaction,connection
from django.core.exceptions import ValidationError
from accounts_receivable.matching_test_support import PartialDeliveryFixture
from accounts_receivable.services import records
from .models import CaseTimelineEvent,CaseActivity
from .services.timeline import record_transition,timeline
from .services.investigation import start_investigation,investigation_revision

class TimelineScenarios(PartialDeliveryFixture):
    def test_lifecycle_idempotency_and_returning_states(self):
        self.fixture()
        self.assertFalse(hasattr(self.case,'_timeline_before_result'))
        self.case.refresh_reconciliation_status()
        count=self.case.timeline_events.count()
        self.case.refresh_reconciliation_status()
        self.assertEqual(self.case.timeline_events.count(),count)
        self.save()
        cleared=self.case.timeline_events.filter(event_type='finding_cleared').count()
        self.assertGreater(cleared,0)
        body=self.payload();body['matches']=[];self.save(body)
        self.assertTrue(self.case.timeline_events.filter(event_type='finding_reopened').exists())
        self.save()
        self.assertGreater(self.case.timeline_events.filter(event_type='finding_cleared').count(),cleared)
        self.assertTrue(self.case.timeline_events.filter(event_type='matches_changed').count()>2)

    def test_append_only_rollback_and_repeat_transitions(self):
        self.fixture()
        count=self.case.timeline_events.count()
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                record_transition(self.case,'matches_changed','Test',self.case._meta.label,'test',{'v':1})
                raise RuntimeError()
        self.assertEqual(self.case.timeline_events.count(),count)
        for value in (1,1,2,1):record_transition(self.case,'matches_changed','Test',self.case._meta.label,'test',{'v':value})
        self.assertEqual(self.case.timeline_events.filter(source_record_id='test').count(),3)
        event=self.case.timeline_events.last()
        with self.assertRaises(ValidationError):event.save()
        with self.assertRaises(ValidationError):CaseTimelineEvent.objects.filter(pk=event.pk).delete()

    def test_api_read_only_scope_filters_history_and_evidence(self):
        self.fixture()
        start_investigation(self.case,{'revision':investigation_revision(self.case)})
        base=f'/discrepancies/api/cases/{self.mode}/{self.case.pk}/timeline/'
        def guard(execute,sql,params,many,context):
            self.assertTrue(sql.lstrip().upper().startswith('SELECT'),sql)
            return execute(sql,params,many,context)
        with connection.execute_wrapper(guard):response=self.client.get(base)
        self.assertEqual(response.status_code,200,response.content)
        self.assertTrue(any(row['id'].startswith('activity:') for row in response.json()['results']))
        self.assertTrue(any(row['evidence'] for row in timeline(self.case)['results']))
        data=self.client.get(base,{'category':'investigations','page_size':1}).json()
        self.assertEqual(data['total'],1)
        self.assertEqual(data['results'][0]['category'],'investigations')
        for params in ({'page':0},{'page_size':101},{'category':'bad'},{'x':'y'}):self.assertEqual(self.client.get(base,params).status_code,400)
        self.assertEqual(self.client.get('/discrepancies/api/cases/no/1/timeline/').status_code,400)
        self.assertEqual(self.client.get(f'/discrepancies/api/cases/{self.mode}/99999/timeline/').status_code,404)
        self.assertEqual(self.client.post(base).status_code,405)
        self.assertEqual(self.client.get(base).json(),self.client.get(base).json())

    def test_legacy_activity_without_automatic_events(self):
        self.fixture()
        legacy=type(self.case).objects.create(**{self.case._meta.get_field('supplier' if self.mode=='ap' else 'customer').name:self.party},currency='PHP')
        start_investigation(legacy,{'revision':investigation_revision(legacy)})
        self.assertEqual(legacy.timeline_events.count(),0)
        events=timeline(legacy)['results']
        self.assertEqual(len(events),1)
        self.assertTrue(events[0]['id'].startswith('activity:'))
        self.assertEqual(legacy.timeline_events.count(),0)

    def test_payment_changes_are_case_scoped(self):
        from accounts_receivable.services.catalog import model,party_key
        self.fixture()
        payment=model(self.mode,'payment').objects.create(**{party_key(self.mode):self.party},payment_reference_no='TIMELINE-PAY',payment_date='2026-11-02',currency='PHP',**({'amount_paid':100} if self.mode=='ap' else {'amount_received':100}))
        from .services.timeline import observe_payment
        count=self.case.timeline_events.count();observe_payment(payment)
        self.assertEqual(self.case.timeline_events.count(),count)
        invoice=self.invoice_line.invoice
        type(invoice).objects.filter(pk=invoice.pk).update(invoice_status='posted')
        invoice.refresh_from_db()
        allocation=model(self.mode,'PaymentAllocation').objects.create(payment=payment,invoice=invoice,cash_amount=100)
        self.assertEqual(self.case.timeline_events.filter(event_type='payments_changed').count(),1)
        payment.payment_status='reversed';payment.save()
        self.assertEqual(self.case.timeline_events.filter(event_type='payments_changed').count(),2)
        self.assertTrue(any(event['type']=='payment_reference' for event in timeline(self.case,'payments')['results']))
        allocation.delete()
        self.assertEqual(self.case.timeline_events.filter(event_type='payments_changed').count(),3)

class APTimelineTests(TimelineScenarios,TestCase):mode='ap'
class ARTimelineTests(TimelineScenarios,TestCase):mode='ar'
