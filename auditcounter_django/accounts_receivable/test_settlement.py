from decimal import Decimal
from django.test import TestCase
from accounts_receivable.matching_test_support import PartialDeliveryFixture
from accounts_receivable.services.catalog import model, party_key
from accounts_receivable.services.settlement import evaluate_case, evaluate_invoice
from accounts_payable.services import credits
from document_extraction.models import Document


class SettlementScenarios(PartialDeliveryFixture):
    def setup_invoice(self):
        self.fixture(receipts=(100,),invoiced=100,invoice_price=1000,order_price=1000)
        self.save()
        self.invoice=self.invoice_line.invoice
        self.invoice.invoice_status='posted';self.invoice.save()

    def payment(self, cash='80000', withholding='0', discount='0'):
        payment=model(self.mode,'payment').objects.create(**{party_key(self.mode):self.party,'payment_reference_no':'P','payment_date':'2026-11-02','currency':'PHP',
            'amount_paid' if self.mode=='ap' else 'amount_received':Decimal(cash),'withholding_tax_amount':Decimal(withholding),'discount_taken':Decimal(discount),'payment_status':'cleared'})
        model(self.mode,'PaymentAllocation').objects.create(payment=payment,invoice=self.invoice,cash_amount=Decimal(cash),withholding_tax_amount=Decimal(withholding),discount_amount=Decimal(discount))
        return payment

    def test_settlement_is_read_only_and_independent_of_document_match(self):
        self.setup_invoice()
        payment=self.payment('80000','10000','5000')
        before=self.case.timeline_events.count()
        result=evaluate_invoice(self.invoice)
        self.assertEqual(Decimal(result['outstanding_balance']),5000)
        self.assertEqual(result['status'],'partial')
        self.assertEqual(Decimal(result['withholding']),10000)
        self.assertEqual(self.case.timeline_events.count(),before)
        self.case.refresh_from_db();self.assertEqual(self.case.reconciliation_status,'matched')
        payment.payment_status='reversed';payment.save()
        self.assertEqual(Decimal(evaluate_invoice(self.invoice)['outstanding_balance']),100000)
        self.assertEqual(self.case.reconciliation_status,'matched')

    def test_pending_payments_reserve_but_do_not_settle(self):
        self.setup_invoice();payment=self.payment('100000')
        payment.payment_status='pending';payment.save()
        result=evaluate_invoice(self.invoice)
        self.assertEqual(result['status'],'outstanding')
        self.assertEqual(Decimal(result['pending_payment_reservations']),100000)
        self.assertEqual(Decimal(result['outstanding_balance']),100000)
        self.assertEqual(evaluate_case(self.case)['findings'],[])

    def test_unreliable_allocations_need_review_without_false_loss(self):
        self.setup_invoice();payment=self.payment()
        # Simulate legacy inconsistent data outside supported validated write paths.
        type(payment).objects.filter(pk=payment.pk).update(currency='USD')
        self.case.refresh_reconciliation_status()
        finding=self.case.discrepancy_findings.get(finding_code='SETTLEMENT_MISMATCH')
        self.assertIsNone(finding.difference_amount)
        self.assertEqual(finding.evidence.count(),1)
        self.assertEqual(self.case.reconciliation_status,'matched')
        type(payment).objects.filter(pk=payment.pk).update(currency='PHP')
        self.case.refresh_reconciliation_status()
        finding.refresh_from_db();self.assertEqual(finding.status,'cleared')
        self.assertGreater(finding.evidence.count(),1)


class APSettlementTests(SettlementScenarios,TestCase):
    mode='ap'

    def test_payment_and_credit_complete_settlement_without_changing_matching(self):
        self.setup_invoice();self.payment()
        doc=Document.objects.create(file_name='credit.pdf',document_type='credit',storage_path='synthetic.pdf')
        credit=credits.create_credit(dict(supplier_id=self.party.pk,reference='CN',issue_date='2026-11-02',currency='PHP',credit_amount='20000',source_document_id=doc.pk))
        credit=credits.verify_credit(credit.pk,dict(revision=credits.credit_revision(credit),notes='Supplier correction verified.'))
        application=credits.apply_credit(credit.pk,dict(revision=credits.credit_revision(credit),request_key='one',invoice_id=self.invoice.pk,amount='20000',application_date='2026-11-02',notes='Apply credit'))
        result=evaluate_invoice(self.invoice)
        self.assertEqual(result['status'],'settled')
        self.assertEqual(Decimal(result['cash']),80000)
        self.assertEqual(Decimal(result['credits']),20000)
        self.assertEqual(Decimal(result['outstanding_balance']),0)
        self.case.refresh_from_db();self.assertEqual(self.case.reconciliation_status,'matched')
        credits.reverse_application(application.pk,dict(revision=credits.credit_revision(credit),reason='Reassess correction'))
        self.assertEqual(Decimal(evaluate_invoice(self.invoice)['outstanding_balance']),20000)


class ARSettlementTests(SettlementScenarios,TestCase):
    mode='ar'
