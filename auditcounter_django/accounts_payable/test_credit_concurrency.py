from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import connection, connections
from django.test import TransactionTestCase
from document_extraction.models import Document
from .models import Supplier, SupplierSalesInvoice, CompanyPayment, PaymentAllocation
from .services import credits


@skipUnless(connection.vendor=='postgresql','Requires PostgreSQL row locks')
class CreditLockTests(TransactionTestCase):
    def setUp(self):
        self.supplier=Supplier.objects.create(supplier_code='CREDIT',supplier_name='Credit concurrency')
        self.invoice=SupplierSalesInvoice.objects.create(supplier=self.supplier,invoice_reference_no='INV',invoice_date='2026-11-02',currency='PHP',total_amount=Decimal('100000'),invoice_status='posted')
        doc=Document.objects.create(file_name='synthetic.pdf',storage_path='synthetic.pdf',document_type='credit')
        credit=credits.create_credit(dict(supplier_id=self.supplier.pk,reference='CN',issue_date='2026-11-02',currency='PHP',credit_amount='30000',source_document_id=doc.pk))
        self.credit=credits.verify_credit(credit.pk,dict(revision=credits.credit_revision(credit),notes='Verified against evidence.'))
        self.payload=dict(revision=credits.credit_revision(self.credit),invoice_id=self.invoice.pk,amount='20000',request_key='a',application_date='2026-11-02',notes='Approved application')

    def race(self, operations):
        barrier=Barrier(2)
        def run(operation):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                operation()
                return 'saved'
            except ValidationError:return 'rejected'
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            tasks=[pool.submit(run,op) for op in operations]
            return [task.result(timeout=30) for task in tasks]

    def test_same_credit_cannot_be_consumed_twice(self):
        result=self.race([lambda:credits.apply_credit(self.credit.pk,self.payload),lambda:credits.apply_credit(self.credit.pk,{**self.payload,'request_key':'b'})])
        self.assertCountEqual(result,['saved','rejected'])
        self.assertEqual(credits.available_credit(self.credit),Decimal('10000'))

    def test_identical_application_retries_are_idempotent(self):
        self.assertEqual(self.race([lambda:credits.apply_credit(self.credit.pk,self.payload)]*2),['saved','saved'])
        self.assertEqual(self.credit.applications.count(),1)

    def test_payment_and_credit_share_invoice_capacity(self):
        payment=CompanyPayment.objects.create(supplier=self.supplier,payment_reference_no='PAY',payment_date='2026-11-02',currency='PHP',amount_paid=Decimal('90000'),payment_status='cleared')
        result=self.race([lambda:credits.apply_credit(self.credit.pk,self.payload),lambda:PaymentAllocation.objects.create(payment=payment,invoice=self.invoice,cash_amount=Decimal('90000'))])
        self.assertCountEqual(result,['saved','rejected'])
        self.assertLessEqual(self.invoice.settled_amount,self.invoice.total_amount)
