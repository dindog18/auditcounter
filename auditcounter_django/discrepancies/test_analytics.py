from decimal import Decimal
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.test import TestCase,Client
from django.urls import reverse
from accounts_receivable.matching_test_support import PartialDeliveryFixture
from accounts_receivable.services.records import save_matches
from .models import FindingRootCause,CaseActivity
from .services import analytics,investigation


class AnalyticsTests(PartialDeliveryFixture,TestCase):
    mode='ap'

    def setUp(self):
        super().setUp()
        self.fixture(receipts=(90,),invoiced=100,invoice_price=18000,order_price=18000)
        save_matches(self.mode,self.case.pk,self.payload([90]))
        self.case.refresh_from_db()
        investigation.start_investigation(self.case,dict(revision=investigation.investigation_revision(self.case)))
        self.finding=self.case.discrepancy_findings.get(finding_code='QUANTITY_SHORTAGE')
        investigation.review_finding(self.case,dict(revision=investigation.investigation_revision(self.case),finding_id=self.finding.pk,decision='confirmed',notes='Verified receiving evidence'))
        self.data=dict(revision=investigation.investigation_revision(self.case),finding_id=self.finding.pk,category='receiving',explanation='Receiving shortage confirmed against signed evidence',evidence_ids=[self.finding.evidence.first().pk])

    def test_root_cause_preserves_human_history_and_invalidates_changed_basis(self):
        root=analytics.review_root_cause(self.case,self.data)
        self.assertEqual(root.review_status,'confirmed')
        count=CaseActivity.objects.count()
        analytics.review_root_cause(self.case,{**self.data,'revision':investigation.investigation_revision(self.case)})
        self.assertEqual(CaseActivity.objects.count(),count)
        self.case.refresh_reconciliation_status()
        root.refresh_from_db();self.assertEqual(root.review_status,'confirmed')
        save_matches(self.mode,self.case.pk,self.payload([80]))
        root.refresh_from_db();self.assertEqual(root.review_status,'needs_review')
        self.assertEqual(root.explanation,self.data['explanation'])
        self.assertTrue(CaseActivity.objects.filter(activity_type='evidence_changed',finding=self.finding).exists())

    def test_invalid_and_rollback_do_not_create_classification(self):
        with self.assertRaises(ValidationError):analytics.review_root_cause(self.case,{**self.data,'evidence_ids':[99999]})
        with patch('discrepancies.services.analytics.append_activity',side_effect=ValidationError('interrupted')):
            with self.assertRaises(ValidationError):analytics.review_root_cause(self.case,self.data)
        self.assertFalse(FindingRootCause.objects.exists())
        analytics.review_root_cause(self.case,self.data)
        with self.assertRaises(ValidationError):analytics.review_root_cause(self.case,self.data)

    def test_case_exposure_not_sum_of_findings_and_filters(self):
        analytics.review_root_cause(self.case,self.data)
        self.case.refresh_from_db()
        report=analytics.report({})
        self.assertEqual(Decimal(report['financial'][0]['potential_exposure']),self.case.total_discrepancy_amount)
        self.assertEqual(report['financial'][0]['verified_cash_recoveries'],'0.00')
        self.assertEqual(report['root_causes'],[dict(module='ap',category='receiving',count=1)])
        self.assertEqual(analytics.report({'currency':'USD'})['financial'],[])
        self.assertEqual(analytics.report({'module':'ar'})['financial'],[])
        self.assertEqual(analytics.report({'root_cause':'pricing'})['financial'],[])
        self.assertEqual(analytics.report({'date_from':'2099-01-01'})['financial'],[])

    def test_api_readonly_filters_and_csrf(self):
        before=CaseActivity.objects.count();url=reverse('DISCREPANCIES:analytics')
        self.assertEqual(self.client.get(url).status_code,200)
        self.assertEqual(self.client.get(url,{'party_id':1}).status_code,400)
        self.assertEqual(self.client.get(url,{'page_size':101}).status_code,400)
        self.assertEqual(self.client.get(url,{'root_cause':'invented'}).status_code,400)
        self.assertEqual(CaseActivity.objects.count(),before)
        self.assertEqual(Client(enforce_csrf_checks=True).post(reverse('ACCOUNTS_PAYABLE:api_record',args=['root-cause-review',self.case.pk]),self.data,content_type='application/json').status_code,403)


class ARAnalyticsTests(AnalyticsTests):
    mode='ar'
    def test_case_exposure_not_sum_of_findings_and_filters(self):
        analytics.review_root_cause(self.case,self.data)
        result=analytics.report({'module':'ar'})
        self.assertEqual(result['root_causes'][0]['module'],'ar')
        self.assertEqual(Decimal(result['financial'][0]['potential_exposure']),self.case.total_discrepancy_amount)
        self.assertEqual(analytics.report({'module':'ap'})['financial'],[])


class FinancialAnalyticsTests(PartialDeliveryFixture,TestCase):
    mode='ap'
    def test_currency_and_reversed_credit_are_separate_without_duplicate_case_joins(self):
        from document_extraction.models import Document
        from accounts_payable.services import credits
        from accounts_payable.models import Transaction
        from .models import DiscrepancyFinding
        from django.utils import timezone
        self.fixture(receipts=(90,),invoiced=100,invoice_price=1000,order_price=1000)
        self.save()
        invoice=self.invoice_line.invoice;invoice.invoice_status='posted';invoice.save()
        doc=Document.objects.create(file_name='c.pdf',storage_path='synthetic/c.pdf',document_type='credit')
        credit=credits.create_credit(dict(supplier_id=self.party.pk,reference='C',currency='PHP',credit_amount='10000',issue_date='2026-11-02',source_document_id=doc.pk))
        credit=credits.verify_credit(credit.pk,dict(revision=credits.credit_revision(credit),notes='Verified supplier credit'))
        app=credits.apply_credit(credit.pk,dict(revision=credits.credit_revision(credit),invoice_id=invoice.pk,amount='10000',request_key='one',application_date='2026-11-02',notes='Corrective credit'))
        # A second finding must not multiply the case amount or applied credit.
        now=timezone.now()
        DiscrepancyFinding.objects.create(ap_transaction=self.case,fingerprint='synthetic-other',finding_code='MISSING_PO',severity='warning',summary='Historical gap',first_detected_at=now,last_detected_at=now)
        usd=Transaction.objects.create(supplier=self.party,currency='USD',transaction_date='2026-11-02')
        Transaction.objects.filter(pk=usd.pk).update(reconciliation_status='exception',total_discrepancy_amount=Decimal('20'))
        results=analytics.report({})['financial']
        php=next(r for r in results if r['currency']=='PHP');dollar=next(r for r in results if r['currency']=='USD')
        self.assertEqual(Decimal(php['potential_exposure']),Decimal('10000'))
        self.assertEqual(Decimal(php['applied_credits']),Decimal('10000'))
        self.assertEqual(Decimal(dollar['potential_exposure']),Decimal('20'))
        credits.reverse_application(app.pk,dict(revision=credits.credit_revision(credit),reason='Correction cancelled'))
        self.assertEqual(Decimal(analytics.report({'currency':'PHP'})['financial'][0]['applied_credits']),0)

    def test_repeated_sku_counts_findings_not_evidence_snapshots(self):
        from .models import DiscrepancyFinding,FindingEvidence,FindingRootCause
        from django.utils import timezone
        self.fixture(receipts=(90,));self.save()
        first=self.case.discrepancy_findings.get(finding_code='QUANTITY_SHORTAGE')
        original=first.evidence.filter(evidence_type='SI',source_line_id=str(self.invoice_line.pk)).first()
        now=timezone.now()
        second=DiscrepancyFinding.objects.create(ap_transaction=self.case,fingerprint='sku-second',finding_code='PRICE_VARIANCE',severity='warning',summary='Reviewed SKU identity',first_detected_at=now,last_detected_at=now)
        for finding in (first,second):
            cause=FindingRootCause.objects.create(finding=finding,category='sku_identity',explanation='Confirmed code mismatch',review_status='confirmed',reviewed_at=now,finding_basis='synthetic')
            for i in range(2):
                item=FindingEvidence.objects.create(finding=finding,snapshot_hash=f'synthetic-{finding.pk}-{i}',evidence_type='SI',source_model=original.source_model,source_record_id=original.source_record_id,source_line_id=original.source_line_id,field_name='line',observed_value=original.observed_value)
                cause.evidence.add(item)
        result=analytics.report({})['sku_mismatches']
        self.assertEqual(result,[dict(module='ap',party_id=self.party.pk,sku='A',count=2)])
