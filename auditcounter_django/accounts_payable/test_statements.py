from decimal import Decimal
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse
from accounts_receivable.matching_test_support import PartialDeliveryFixture
from accounts_receivable.services.catalog import revision
from document_extraction.models import Document
from .models import SupplierStatement, SupplierCreditNote, SupplierStatementEvaluation
from .services import statements, credits


class StatementTests(PartialDeliveryFixture, TestCase):
    mode='ap'

    def setUp(self):
        super().setUp()
        self.fixture(receipts=(100,),invoiced=100,invoice_price=1000,order_price=1000)
        self.invoice=self.invoice_line.invoice
        self.invoice.invoice_status='posted';self.invoice.save()
        self.document=Document.objects.create(file_name='statement.csv',storage_path='synthetic/statement.csv',document_type='statement')

    def payload(self):
        return dict(supplier_id=self.party.pk,reference='ST-1',statement_date='2026-11-02',period_start='2020-01-01',currency='PHP',opening_balance='0',closing_balance='95000',source_document_id=self.document.pk,case_id=self.case.pk,
            csv=f'reference,date,type,amount\n{self.invoice.invoice_reference_no},{self.invoice.invoice_date},invoice,100000\nCN-MISSING,2026-11-02,credit,5000')

    def test_missing_credit_is_finding_not_fabricated_money(self):
        statement=statements.create_statement(self.payload())
        result=statements.serialize(statement)['result']
        self.assertEqual(result['lines'][1]['code'],'MISSING_STATEMENT_CREDIT')
        self.assertFalse(SupplierCreditNote.objects.exists())
        self.assertEqual(self.case.discrepancy_findings.filter(finding_code='STATEMENT_MISMATCH',status='open').count(),1)
        self.assertEqual(statement.matches.count(),1)
        count=SupplierStatementEvaluation.objects.count()
        statements.reconcile(statement.pk,{'revision':revision(statement)})
        self.assertEqual(SupplierStatementEvaluation.objects.count(),count)
        credit=credits.create_credit(dict(supplier_id=self.party.pk,reference='CN-MISSING',issue_date='2026-11-02',currency='PHP',credit_amount='5000',source_document_id=self.document.pk))
        credits.verify_credit(credit.pk,dict(revision=credits.credit_revision(credit),notes='Verified original credit'))
        statement.refresh_from_db()
        self.assertEqual(statement.reconciliation_status,'matched')
        self.assertEqual(self.case.discrepancy_findings.get(finding_code='STATEMENT_MISMATCH').status,'cleared')
        self.assertEqual(statement.matches.count(),2)
        self.assertEqual(self.invoice.settled_amount,0)
        self.assertGreater(statement.evaluations.count(),1)

    def test_invalid_csv_and_event_failure_rollback(self):
        for csv in ('reference,date,type,amount\nx,2026-11-02,credit,-1','bad,columns\na,b'):
            with self.assertRaises(ValidationError):statements.create_statement({**self.payload(),'csv':csv})
        self.assertFalse(SupplierStatement.objects.exists())
        with patch('discrepancies.services.timeline.record_transition',side_effect=ValidationError('interrupted')):
            with self.assertRaises(ValidationError):statements.create_statement(self.payload())
        self.assertFalse(SupplierStatement.objects.exists())

    def test_review_history_stale_and_source_preservation(self):
        statement=statements.create_statement(self.payload());token=revision(statement)
        line=statement.lines.last()
        statement=statements.review_line(statement.pk,dict(revision=token,line_id=line.pk,decision='dismissed',notes='Awaiting supplier confirmation'))
        self.assertEqual(statement.reconciliation_status,'exception')
        self.assertEqual(statement.evaluations.count(),2)
        with self.assertRaises(ValidationError):statements.reconcile(statement.pk,{'revision':token})
        line.amount=Decimal('1')
        with self.assertRaises(ValidationError):line.save()
        statement.closing_balance=Decimal('1')
        with self.assertRaises(ValidationError):statement.save()

    def test_readonly_workspace_and_csrf(self):
        statement=statements.create_statement(self.payload());before=statement.evaluations.count()
        url=reverse('ACCOUNTS_PAYABLE:statement_detail',args=[statement.pk])
        self.assertEqual(self.client.get(url).status_code,200)
        self.assertEqual(statement.evaluations.count(),before)
        self.assertEqual(Client(enforce_csrf_checks=True).post(reverse('ACCOUNTS_PAYABLE:api',args=['statement-create']),{},content_type='application/json').status_code,403)
        self.assertEqual(self.client.get('/accounts-receivable/statements/').status_code,404)

    def test_ambiguous_references_require_explicit_review(self):
        from .models import SupplierSalesInvoice
        SupplierSalesInvoice.objects.create(supplier=self.party,invoice_reference_no=self.invoice.invoice_reference_no.lower(),invoice_date=self.invoice.invoice_date,currency='PHP',total_amount=Decimal('100000'),invoice_status='posted')
        statement=statements.create_statement(self.payload())
        line=statement.lines.get(kind='invoice')
        self.assertEqual(statements.evaluate(statement)['lines'][0]['code'],'AMBIGUOUS_STATEMENT_MATCH')
        self.assertFalse(statement.matches.exists())
        statement=statements.review_line(statement.pk,dict(revision=revision(statement),line_id=line.pk,decision='confirmed',target_id=self.invoice.pk,notes='Original document identifies the invoice'))
        self.assertEqual(statement.matches.get().invoice_id,self.invoice.pk)
        self.assertTrue(statements.evaluate(statement)['lines'][0]['target_url'])

    def test_statement_payment_credit_match_does_not_apply_credit(self):
        from .models import CompanyPayment,PaymentAllocation
        payment=CompanyPayment.objects.create(supplier=self.party,payment_reference_no='PAY',payment_date='2026-11-02',currency='PHP',amount_paid=Decimal('95000'),payment_status='cleared')
        PaymentAllocation.objects.create(payment=payment,invoice=self.invoice,cash_amount=Decimal('95000'))
        credit=credits.create_credit(dict(supplier_id=self.party.pk,reference='CN-MISSING',issue_date='2026-11-02',currency='PHP',credit_amount='5000',source_document_id=self.document.pk))
        credits.verify_credit(credit.pk,dict(revision=credits.credit_revision(credit),notes='Verified source'))
        payload=self.payload();payload['closing_balance']='0';payload['csv']+='\nPAY,2026-11-02,payment,95000'
        statement=statements.create_statement(payload)
        self.assertEqual(statement.reconciliation_status,'matched')
        self.assertEqual(statement.matches.count(),3)
        self.assertEqual(self.invoice.outstanding_balance,Decimal('5000'))
        payment.payment_status='reversed';payment.save()
        statement.refresh_from_db();self.assertEqual(statement.reconciliation_status,'exception')
        self.assertGreater(statement.evaluations.count(),1)
