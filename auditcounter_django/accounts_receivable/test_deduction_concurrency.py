from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import connection, connections
from django.test import TransactionTestCase
from document_extraction.models import Document
from .models import Customer, CompanySalesInvoice, CustomerPayment, PaymentAllocation
from .services import deductions
from .services.catalog import revision

@skipUnless(connection.vendor=='postgresql','Requires PostgreSQL row locks')
class DeductionLocks(TransactionTestCase):
    def setUp(self):
        self.customer=Customer.objects.create(customer_code='D',customer_name='Deduction race')
        self.invoice=CompanySalesInvoice.objects.create(customer=self.customer,invoice_reference_no='I',invoice_date='2026-11-02',currency='PHP',total_amount=Decimal('100000'),invoice_status='posted')
        doc=Document.objects.create(file_name='d.pdf',storage_path='synthetic/d.pdf',document_type='deduction')
        self.invoice.refresh_from_db()
        row=deductions.create_deduction(dict(invoice_id=self.invoice.pk,revision=revision(self.invoice),reference='D',reason_code='other',claimed_amount='5000',source_document_id=doc.pk))
        self.row=deductions.review(row.pk,dict(revision=deductions.deduction_revision(row),decision='accepted',accepted_amount='5000',notes='Verified evidence'))
        self.payload=dict(revision=deductions.deduction_revision(self.row),amount='5000',request_key='a',notes='Apply accepted adjustment')

    def race(self,operations):
        barrier=Barrier(2)
        def run(operation):
            connections.close_all()
            try:
                barrier.wait(timeout=10);operation();return 'saved'
            except ValidationError:return 'rejected'
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs=[pool.submit(run,op) for op in operations]
            return [j.result(timeout=30) for j in jobs]

    def test_competing_applications(self):
        self.assertCountEqual(self.race([lambda:deductions.apply(self.row.pk,self.payload),lambda:deductions.apply(self.row.pk,{**self.payload,'request_key':'b'})]),['saved','rejected'])
        self.assertEqual(self.row.applications.count(),1)

    def test_payment_competes_for_same_invoice_capacity(self):
        payment=CustomerPayment.objects.create(customer=self.customer,payment_reference_no='P',payment_date='2026-11-02',currency='PHP',amount_received=Decimal('100000'),payment_status='cleared')
        self.assertCountEqual(self.race([lambda:deductions.apply(self.row.pk,self.payload),lambda:PaymentAllocation.objects.create(payment=payment,invoice=self.invoice,cash_amount=Decimal('100000'))]),['saved','rejected'])
        self.assertLessEqual(self.invoice.settled_amount,self.invoice.total_amount)
