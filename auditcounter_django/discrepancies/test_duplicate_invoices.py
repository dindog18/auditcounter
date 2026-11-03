from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import connection,connections
from django.test import TestCase,TransactionTestCase
from accounts_receivable.services.catalog import model,party_key,revision
from accounts_receivable.services.records import save_case
from .models import DuplicateInvoiceCandidate
from .services import duplicate_invoices as duplicates


class DuplicateFixture:
    def setup_mode(self,mode):
        self.mode=mode;key=party_key(mode)
        self.party=model(mode,key).objects.create(**{key+'_code':'DUP',key+'_name':'Duplicate examples'})
        def invoice(reference,**values):
            return model(mode,'sales_invoice').objects.create(**{key:self.party,'invoice_reference_no':reference,'invoice_date':'2026-11-02','currency':'PHP','total_amount':Decimal('100'),**values})
        self.invoice=invoice
        self.a=invoice('INV-001');self.b=invoice('inv 001')


class DuplicateTests(DuplicateFixture,TestCase):
    def test_normalized_pair_idempotent_and_no_automatic_case_or_loss(self):
        for mode in ('ap','ar'):
            self.setup_mode(mode)
            row=duplicates.detect(self.a)[0]
            self.assertEqual(duplicates.detect(self.b)[0].pk,row.pk)
            self.assertEqual(row.reviews.count(),1)
            self.assertFalse(model(mode,'Transaction').objects.exists())
            self.assertEqual(row.review_decision,'unreviewed')
            self.assertEqual(row.details['classification'],'possible_duplicate_not_confirmed_loss')
        self.assertEqual(DuplicateInvoiceCandidate.objects.count(),2)

    def test_other_supplier_currency_date_and_partial_invoices_are_excluded(self):
        self.setup_mode('ap')
        self.b.invoice_date='2026-12-01';self.b.save()
        self.invoice('INV_001',currency='USD')
        self.invoice('INV.001',total_amount=Decimal('50'))
        party=model('ap','supplier').objects.create(supplier_code='OTHER',supplier_name='Other')
        self.invoice('INV/001',supplier=party)
        self.assertEqual(duplicates.detect(self.a),[])

    def test_review_history_survives_changes_and_stale_reviews_rejected(self):
        self.setup_mode('ar');row=duplicates.detect(self.a)[0]
        payload=dict(revision=revision(row),decision='dismissed',notes='Separate recurring invoices confirmed by supporting evidence.')
        row=duplicates.review(row.pk,payload)
        self.assertEqual(row.reviews.count(),2)
        with self.assertRaises(ValidationError):duplicates.review(row.pk,payload)
        duplicates.detect(self.a);row.refresh_from_db();self.assertEqual(row.review_decision,'dismissed')
        self.b.total_amount=Decimal('200');self.b.save()
        duplicates.detect(self.b);row.refresh_from_db()
        self.assertFalse(row.active);self.assertEqual(row.reviews.count(),3)
        self.assertEqual(row.review_decision,'dismissed')

    def test_case_findings_are_nonmonetary_and_reads_do_not_create_candidates(self):
        self.setup_mode('ap')
        case=save_case('ap',dict(partyId=self.party.pk,currency='PHP',date='2026-11-02',orderIds=[],receiptIds=[],invoiceIds=[self.a.pk]))
        duplicates.detect(self.a)
        finding=case.discrepancy_findings.get(finding_code='POSSIBLE_DUPLICATE_INVOICE')
        self.assertIsNone(finding.difference_amount)
        self.assertEqual(finding.evidence.count(),2)
        before=DuplicateInvoiceCandidate.objects.count()
        response=self.client.get('/discrepancies/api/duplicate-invoices/?module=ap')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['total'],1)
        self.assertEqual(DuplicateInvoiceCandidate.objects.count(),before)
        self.assertEqual(self.client.get('/discrepancies/api/duplicate-invoices/?page=0').status_code,400)

    def test_review_requires_notes_and_csrf(self):
        self.setup_mode('ap');row=duplicates.detect(self.a)[0]
        with self.assertRaises(ValidationError):duplicates.review(row.pk,dict(revision=revision(row),decision='dismissed',notes=''))
        self.assertEqual(row.reviews.count(),1)
        from django.test import Client
        self.assertEqual(Client(enforce_csrf_checks=True).post(f'/discrepancies/api/duplicate-invoices/{row.pk}/review/',{},content_type='application/json').status_code,403)


@skipUnless(connection.vendor=='postgresql','Requires PostgreSQL independent connections')
class DuplicateConcurrencyTests(DuplicateFixture,TransactionTestCase):
    def test_concurrent_detection_preserves_one_pair(self):
        self.setup_mode('ap');barrier=Barrier(2)
        def run(pk):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                return duplicates.detect(model('ap','sales_invoice').objects.get(pk=pk))[0].pk
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs=[pool.submit(run,pk) for pk in (self.a.pk,self.b.pk)]
            self.assertEqual(jobs[0].result(timeout=30),jobs[1].result(timeout=30))
        self.assertEqual(DuplicateInvoiceCandidate.objects.count(),1)
        self.assertEqual(DuplicateInvoiceCandidate.objects.get().reviews.count(),1)
