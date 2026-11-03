from decimal import Decimal
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from document_extraction.models import Document
from accounts_receivable.matching_test_support import PartialDeliveryFixture
from accounts_receivable.services.catalog import revision
from .models import SupplierCreditNote, SupplierCreditApplication, SupplierCreditReversal, CompanyPayment, PaymentAllocation
from .services import credits


class CreditTests(PartialDeliveryFixture, TestCase):
    mode='ap'

    def setUp(self):
        super().setUp()
        self.fixture(receipts=(100,),invoiced=100,invoice_price=1000,order_price=1000)
        self.invoice=self.invoice_line.invoice
        self.invoice.invoice_status='posted'
        self.invoice.save()
        self.document=Document.objects.create(file_name='synthetic-credit.pdf',storage_path='synthetic/credit.pdf',document_type='credit')

    def credit(self, value='20000.00'):
        return credits.create_credit(dict(supplier_id=self.party.pk,reference='CN-'+str(SupplierCreditNote.objects.count()),
            issue_date='2026-11-02',currency='PHP',credit_amount=value,source_document_id=self.document.pk))

    def verify(self, credit):
        return credits.verify_credit(credit.pk,dict(revision=credits.credit_revision(credit),notes='Compared with the uploaded supplier credit.'))

    def payload(self, credit, amount='20000.00', key='request-1'):
        return dict(revision=credits.credit_revision(credit),invoice_id=self.invoice.pk,amount=amount,request_key=key,
            application_date='2026-11-02',notes='Apply verified supplier correction.')

    def test_verified_partial_credit_separate_from_cash_and_reversible(self):
        credit=self.verify(self.credit())
        application=credits.apply_credit(credit.pk,self.payload(credit,'12000.00'))
        self.assertEqual(self.invoice.settled_amount,Decimal('12000'))
        self.assertEqual(credits.available_credit(credit),Decimal('8000'))
        self.assertEqual(self.invoice.payment_allocations.count(),0)
        credits.reverse_application(application.pk,dict(revision=credits.credit_revision(credit),reason='Correction applies to another invoice.'))
        self.assertEqual(self.invoice.settled_amount,0)
        self.assertEqual(credits.available_credit(credit),Decimal('20000'))
        self.assertEqual(SupplierCreditApplication.objects.count(),1)
        self.assertEqual(SupplierCreditReversal.objects.count(),1)
        self.assertGreaterEqual(self.case.timeline_events.filter(event_type='credits_changed').count(),2)

    def test_draft_and_overapplication_rejected(self):
        credit=self.credit()
        with self.assertRaises(ValidationError):credits.apply_credit(credit.pk,self.payload(credit))
        credit=self.verify(credit)
        with self.assertRaises(ValidationError):credits.apply_credit(credit.pk,self.payload(credit,'20000.01'))
        self.assertEqual(credit.applications.count(),0)

    def test_idempotency_stale_revision_and_conflicting_key(self):
        credit=self.verify(self.credit())
        payload=self.payload(credit,'10000')
        row=credits.apply_credit(credit.pk,payload)
        self.assertEqual(credits.apply_credit(credit.pk,payload).pk,row.pk)
        with self.assertRaises(ValidationError):credits.apply_credit(credit.pk,{**payload,'amount':'9000'})
        with self.assertRaises(ValidationError):credits.apply_credit(credit.pk,{**payload,'request_key':'other'})

    def test_payment_reservations_and_credit_capacity_cannot_overlap(self):
        payment=CompanyPayment.objects.create(supplier=self.party,payment_reference_no='P',payment_date='2026-11-02',currency='PHP',amount_paid=Decimal('80000'),payment_status='cleared')
        PaymentAllocation.objects.create(payment=payment,invoice=self.invoice,cash_amount=Decimal('80000'))
        credit=self.verify(self.credit('25000'))
        with self.assertRaises(ValidationError):credits.apply_credit(credit.pk,self.payload(credit,'25000'))
        credits.apply_credit(credit.pk,self.payload(credit,'20000'))
        self.assertEqual(self.invoice.outstanding_balance,0)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.payment_status,'paid')
        payment.payment_status='reversed';payment.save()
        self.assertEqual(self.invoice.outstanding_balance,Decimal('80000'))
        credits.apply_credit(credit.pk,self.payload(credit,'5000','second'))
        payment.payment_status='cleared'
        with self.assertRaises(ValidationError):payment.save()
        payment.refresh_from_db();self.assertEqual(payment.payment_status,'reversed')

    def test_foreign_currency_and_invoice_changes_rejected(self):
        credit=self.verify(self.credit())
        self.invoice.currency='USD';self.invoice.save()
        with self.assertRaises(ValidationError):credits.apply_credit(credit.pk,self.payload(credit))
        self.invoice.currency='PHP';self.invoice.save()
        credits.apply_credit(credit.pk,self.payload(credit))
        self.invoice.currency='USD'
        with self.assertRaises(ValidationError):self.invoice.save()
        credit.credit_amount=Decimal('1')
        with self.assertRaises(ValidationError):credit.save()

    def test_event_failure_rolls_back_application_and_balance(self):
        credit=self.verify(self.credit())
        with patch('discrepancies.services.timeline.record_transition',side_effect=ValidationError('interrupted')):
            with self.assertRaises(ValidationError):credits.apply_credit(credit.pk,self.payload(credit))
        self.assertFalse(credit.applications.exists())
        self.assertEqual(self.invoice.settled_amount,0)

    def test_credit_api_ui_and_csrf(self):
        credit=self.credit()
        url=reverse('ACCOUNTS_PAYABLE:credit_detail',args=[credit.pk])
        self.assertEqual(self.client.get(url).status_code,200)
        response=self.client.post(reverse('ACCOUNTS_PAYABLE:api_record',args=['credit-verify',credit.pk]),
            dict(revision='stale',notes='Reviewed'),content_type='application/json')
        self.assertEqual(response.status_code,409)
        from django.test import Client
        self.assertEqual(Client(enforce_csrf_checks=True).post(reverse('ACCOUNTS_PAYABLE:api',args=['credit-create']),{},content_type='application/json').status_code,403)
        self.assertEqual(self.client.get('/accounts-receivable/credits/').status_code,404)

    def test_validation_requires_evidence_and_decimal_precision(self):
        for amount in ('NaN','0','-1','1.001',1.1,True):
            with self.assertRaises(ValidationError):self.credit(amount)
        credit=self.credit();credit.source_document=None;credit.save()
        with self.assertRaises(ValidationError):self.verify(credit)
