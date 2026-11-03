from decimal import Decimal
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse
from document_extraction.models import Document
from .matching_test_support import PartialDeliveryFixture
from .models import CustomerPayment, PaymentAllocation, CustomerDeduction
from .services import deductions
from .services.catalog import revision
from .services.settlement import evaluate_invoice


class DeductionTests(PartialDeliveryFixture, TestCase):
    mode='ar'

    def setUp(self):
        super().setUp()
        self.fixture(receipts=(100,),invoiced=100,invoice_price=1000,order_price=1000)
        self.invoice=self.invoice_line.invoice
        self.invoice.invoice_status='posted';self.invoice.save()
        self.payment=CustomerPayment.objects.create(customer=self.party,payment_reference_no='PAY',payment_date='2026-11-02',currency='PHP',amount_received=Decimal('95000'),payment_status='cleared')
        PaymentAllocation.objects.create(payment=self.payment,invoice=self.invoice,cash_amount=Decimal('95000'))
        self.doc=Document.objects.create(file_name='deduction.pdf',storage_path='synthetic/deduction.pdf',document_type='deduction')

    def create(self):
        self.invoice.refresh_from_db()
        return deductions.create_deduction(dict(invoice_id=self.invoice.pk,payment_id=self.payment.pk,reference='D-1',reason_code='shortage',claimed_amount='5000',source_document_id=self.doc.pk,revision=revision(self.invoice)))

    def accept(self,row):
        return deductions.review(row.pk,dict(revision=deductions.deduction_revision(row),decision='accepted',accepted_amount='5000',notes='Compared signed customer evidence'))

    def apply(self,row,amount='5000',key='first'):
        return deductions.apply(row.pk,dict(revision=deductions.deduction_revision(row),amount=amount,request_key=key,notes='Apply reviewed adjustment'))

    def test_95k_payment_5k_dispute_only_explicit_application_settles(self):
        row=self.create();self.assertEqual(self.invoice.outstanding_balance,Decimal('5000'))
        self.assertTrue(self.case.discrepancy_findings.filter(finding_code='CUSTOMER_DEDUCTION',status='open').exists())
        with self.assertRaises(ValidationError):self.apply(row)
        row=self.accept(row);self.assertEqual(self.invoice.outstanding_balance,Decimal('5000'))
        row=self.apply(row,'2000');self.assertEqual(self.invoice.outstanding_balance,Decimal('3000'))
        row=self.apply(row,'3000','second');self.assertEqual(self.invoice.outstanding_balance,0)
        result=evaluate_invoice(self.invoice)
        self.assertEqual(Decimal(result['cash']),Decimal('95000'));self.assertEqual(Decimal(result['adjustments']),Decimal('5000'))
        self.assertEqual(self.case.discrepancy_findings.get(finding_code='CUSTOMER_DEDUCTION').status,'cleared')
        row=deductions.reverse_application(row.pk,dict(revision=deductions.deduction_revision(row),application_id=row.applications.first().pk,reason='Evidence superseded'))
        self.assertEqual(self.invoice.outstanding_balance,Decimal('2000'))
        self.assertGreaterEqual(row.observations.count(),5)
        self.assertTrue(self.case.timeline_events.filter(event_type='deductions_changed').exists())
        self.assertEqual(self.payment.invoice_allocations.count(),1)

    def test_rejection_remains_collectible_and_review_does_not_change_matching(self):
        row=self.create();self.case.refresh_from_db();before=(self.case.reconciliation_status,self.case.total_discrepancy_amount)
        row=deductions.review(row.pk,dict(revision=deductions.deduction_revision(row),decision='rejected',notes='Unsupported claim'))
        with self.assertRaises(ValidationError):self.apply(row)
        self.case.refresh_from_db();self.assertEqual((self.case.reconciliation_status,self.case.total_discrepancy_amount),before)
        self.assertEqual(self.invoice.outstanding_balance,Decimal('5000'))
        with self.assertRaises(ValidationError):row.observations.first().delete()

    def test_capacity_currency_and_payment_reactivation(self):
        row=self.accept(self.create());self.apply(row)
        with self.assertRaises(ValidationError):self.apply(row,'1','over')
        self.invoice.currency='USD'
        with self.assertRaises(ValidationError):self.invoice.save()
        self.invoice.refresh_from_db()
        self.payment.payment_status='reversed';self.payment.save()
        extra=CustomerPayment.objects.create(customer=self.party,payment_reference_no='EXTRA',payment_date='2026-11-02',currency='PHP',amount_received=Decimal('95000'),payment_status='cleared')
        PaymentAllocation.objects.create(payment=extra,invoice=self.invoice,cash_amount=Decimal('95000'))
        self.payment.payment_status='cleared'
        with self.assertRaises(ValidationError):self.payment.save()

    def test_stale_review_rollback_and_csrf(self):
        row=self.create();token=deductions.deduction_revision(row);row=self.accept(row)
        with self.assertRaises(ValidationError):deductions.review(row.pk,dict(revision=token,decision='rejected',notes='Old request'))
        with patch('discrepancies.services.timeline.record_transition',side_effect=ValidationError('interrupted')):
            with self.assertRaises(ValidationError):self.apply(row)
        self.assertFalse(row.applications.exists())
        self.assertEqual(self.client.get(reverse('ACCOUNTS_RECEIVABLE:deduction_detail',args=[row.pk])).status_code,200)
        self.assertEqual(Client(enforce_csrf_checks=True).post(reverse('ACCOUNTS_RECEIVABLE:api',args=['deduction-create']),{},content_type='application/json').status_code,403)
