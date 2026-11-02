"""Persistent finding contracts, shared by the actual AP and AR tests."""
from decimal import Decimal
from unittest.mock import patch

from django.db import transaction
from django.test import Client
from document_extraction.models import Document
from db_extraction.models import DatabaseSource, DatabaseSchema, DatabaseTable, ExtractionRun
from accounts_receivable.matching_test_support import PartialDeliveryFixture
from accounts_receivable.services import records, pages
from accounts_receivable.services.catalog import model
from .models import DiscrepancyFinding, FindingEvidence


class FindingScenarios(PartialDeliveryFixture):
    def current_finding(self, code):
        return self.case.discrepancy_findings.get(finding_code=code)

    def update_invoice_price(self, price):
        line = self.invoice_line
        type(line).objects.filter(pk=line.pk).update(unit_price=price, line_total=price*100)
        invoice = type(line.invoice).objects.get(pk=line.invoice_id)
        invoice.subtotal = invoice.total_amount = Decimal(price)*100
        invoice.save()  # Source header refreshes this case inside the same transaction.

    def test_quantity_finding_has_persisted_po_dr_si_and_allocation_evidence(self):
        self.fixture(receipts=(98,))
        self.save()
        finding = self.current_finding('QUANTITY_SHORTAGE')
        self.assertEqual(finding.status, 'open')
        self.assertEqual(finding.severity, 'warning')
        self.assertEqual(Decimal(finding.expected_value['quantity']),98)
        self.assertEqual(Decimal(finding.actual_value['quantity']),100)
        self.assertEqual(finding.difference_amount,Decimal('36000'))
        self.assertEqual(set(finding.evidence.values_list('evidence_type',flat=True)),{'PO','DR','SI','ALLOCATION'})
        self.assertEqual(finding.ap_transaction_id if self.mode=='ap' else finding.ar_transaction_id,self.case.pk)
        self.assertTrue(all(item.source_model.startswith('accounts_') for item in finding.evidence.all()))
        allocation = finding.evidence.filter(evidence_type='ALLOCATION').first()
        self.assertEqual(Decimal(allocation.observed_value['matched_quantity']),98)
        self.assertIn('not a confirmed recoverable',finding.summary)

    def test_idempotency_and_pure_preview(self):
        self.fixture(receipts=(98,))
        self.save()
        count = FindingEvidence.objects.count()
        finding = self.current_finding('QUANTITY_SHORTAGE')
        first = finding.first_detected_at
        for _ in range(3):
            self.case.refresh_reconciliation_status()
        self.assertEqual(self.case.discrepancy_findings.filter(finding_code='QUANTITY_SHORTAGE').count(),1)
        self.assertEqual(FindingEvidence.objects.count(),count)
        finding.refresh_from_db()
        self.assertEqual(finding.first_detected_at,first)
        self.assertGreaterEqual(finding.last_detected_at,first)
        before = list(DiscrepancyFinding.objects.values())
        records.preview_matches(self.mode,self.case.pk,self.payload())
        self.case.calculate_reconciliation()
        self.assertEqual(before,list(DiscrepancyFinding.objects.values()))
        self.assertEqual(count,FindingEvidence.objects.count())

    def test_modified_corrected_and_recurring_price_finding_keeps_history(self):
        self.fixture(receipts=(100,),invoice_price=18500)
        self.save()
        finding = self.current_finding('PRICE_VARIANCE')
        original_id, first, initial_evidence = finding.pk, finding.first_detected_at, finding.evidence.count()
        self.assertEqual(finding.difference_amount,50000)
        self.update_invoice_price(18600)
        finding.refresh_from_db()
        self.assertEqual(finding.pk,original_id)
        self.assertEqual(finding.difference_amount,60000)
        self.assertGreater(finding.evidence.count(),initial_evidence)
        self.assertTrue(any(Decimal(item.observed_value['line']['unit_price'])==18500 for item in finding.evidence.filter(evidence_type='SI')))
        self.update_invoice_price(18000)
        finding.refresh_from_db()
        self.assertEqual(finding.status,'cleared')
        self.assertIsNotNone(finding.cleared_at)
        self.assertEqual(finding.first_detected_at,first)
        self.assertTrue(any(item.finding_snapshot['status']=='cleared' and Decimal(item.observed_value['line']['unit_price'])==18000 for item in finding.evidence.filter(evidence_type='SI')))
        self.update_invoice_price(18500)
        finding.refresh_from_db()
        self.assertEqual(finding.status,'open')
        self.assertIsNone(finding.cleared_at)
        self.assertEqual(finding.pk,original_id)
        self.assertEqual(finding.first_detected_at,first)

    def test_header_double_counting_and_line_arithmetic(self):
        self.fixture(receipts=(100,),invoice_price=1,order_price=1)
        self.save()
        invoice = type(self.invoice_line.invoice).objects.get(pk=self.invoice_line.invoice_id)
        invoice.total_amount = Decimal('110')
        invoice.save()
        self.assertEqual(self.case.calculate_reconciliation(),('exception',Decimal('10.00')))
        self.assertEqual(self.current_finding('HEADER_TOTAL_MISMATCH').difference_amount,10)
        self.assertEqual(self.case.discrepancy_findings.filter(status='open').count(),1)
        type(self.invoice_line).objects.filter(pk=self.invoice_line.pk).update(line_total=150)
        invoice.subtotal = invoice.total_amount = Decimal('150')
        invoice.save()
        self.assertEqual(self.case.calculate_reconciliation()[1],50)
        line = self.current_finding('LINE_TOTAL_MISMATCH')
        self.assertEqual(line.difference_amount,50)
        self.assertEqual(Decimal(line.expected_value['total']),100)
        self.assertEqual(self.current_finding('HEADER_TOTAL_MISMATCH').status,'cleared')

    def test_partial_invoice_is_not_a_financial_claim(self):
        self.fixture(receipts=(60,),invoiced=60)
        self.save()
        self.assertEqual(self.case.calculate_reconciliation(),('matched',Decimal('0.00')))
        self.assertFalse(self.case.discrepancy_findings.filter(status='open').exists())
        self.assertFalse(self.case.discrepancy_findings.exclude(difference_amount=None).exists())

    def test_missing_documents_clear_on_membership_add_without_claims(self):
        self.fixture(receipts=(100,))
        self.case.purchase_orders.clear()
        self.case.delivery_receipts.clear()
        for code in ('MISSING_PO','MISSING_DR'):
            finding = self.current_finding(code)
            self.assertEqual(finding.status,'open')
            self.assertIsNone(finding.difference_amount)
            self.assertEqual(finding.details['classification'],'evidence_gap')
        self.case.purchase_orders.add(self.order_line.purchase_order)
        self.case.delivery_receipts.add(self.receipt_lines[0].delivery_receipt)
        self.assertEqual(self.current_finding('MISSING_PO').status,'cleared')
        self.assertEqual(self.current_finding('MISSING_DR').status,'cleared')

    def test_matching_batch_does_not_persist_temporary_shortages(self):
        self.fixture()
        finding = self.current_finding('QUANTITY_SHORTAGE')
        self.assertEqual(finding.severity,'information')
        self.assertIsNone(finding.difference_amount)
        self.save()
        finding.refresh_from_db()
        self.assertEqual(finding.status,'cleared')
        self.assertIsNone(finding.difference_amount)
        self.assertTrue(all(item.finding_snapshot['difference_amount'] is None for item in finding.evidence.all()))
        self.assertFalse(self.case.discrepancy_findings.filter(finding_code__in=['MISSING_PO','MISSING_DR']).exists())

    def test_synchronization_failure_rolls_back_allocations_and_findings(self):
        self.fixture(receipts=(98,))
        before = list(self.case.discrepancy_findings.values())
        evidence_count = FindingEvidence.objects.count()
        with patch('discrepancies.services.capture_finding_evidence',side_effect=RuntimeError('Interrupted capture')):
            with self.assertRaises(RuntimeError):
                self.save()
        self.assertFalse(self.case.line_matches.exists())
        self.assertEqual(list(self.case.discrepancy_findings.values()),before)
        self.assertEqual(FindingEvidence.objects.count(),evidence_count)

    def test_queryset_match_removal_synchronizes_findings(self):
        self.fixture(receipts=(100,),invoice_price=18500)
        self.save()
        finding = self.current_finding('PRICE_VARIANCE')
        self.case.line_matches.all().delete()
        finding.refresh_from_db()
        self.assertEqual(finding.status,'cleared')
        self.assertEqual(self.current_finding('QUANTITY_SHORTAGE').status,'open')
        self.case.refresh_from_db()
        self.assertEqual(self.case.reconciliation_status,'pending')

    def test_uploaded_and_erp_provenance_survive_source_deletion(self):
        self.fixture(receipts=(100,),invoice_price=18500)
        document = Document.objects.create(file_name='invoice.pdf',storage_path='/private/tmp/invoice.pdf',document_type='invoice')
        source = DatabaseSource.objects.create(name='ERP',host='localhost',database_name='erp',username='reader')
        run = ExtractionRun.objects.create(source=source)
        schema = DatabaseSchema.objects.create(run=run,name='public')
        table = DatabaseTable.objects.create(schema=schema,name='invoices')
        invoice = type(self.invoice_line.invoice).objects.get(pk=self.invoice_line.invoice_id)
        invoice.source_document, invoice.source_database, invoice.source_table = document, source, table
        invoice.source_record_key = {'invoice_id':42}
        invoice.save()
        self.save()
        finding = self.current_finding('PRICE_VARIANCE')
        evidence = finding.evidence.filter(evidence_type='SI').first()
        self.assertEqual(evidence.source_document_id,document.pk)
        self.assertEqual(evidence.source_database_id,source.pk)
        self.assertEqual(evidence.source_record_key,{'invoice_id':42})
        self.assertEqual(evidence.provenance['table_name'],'public.invoices')
        self.case.line_matches.all().delete()
        self.case.sales_invoices.remove(invoice)
        invoice.lines.all().delete()
        invoice.delete()
        document.delete()
        evidence.refresh_from_db()
        self.assertIsNone(evidence.source_document_id)
        self.assertEqual(evidence.provenance['file_name'],'invoice.pdf')
        self.assertEqual(evidence.observed_value['line']['unit_price'],'18500.0000')
        self.assertTrue(DiscrepancyFinding.objects.filter(pk=finding.pk).exists())

    def test_reload_and_explicit_recalculation_api(self):
        self.fixture(receipts=(98,))
        self.save()
        base = '/accounts-payable/' if self.mode=='ap' else '/accounts-receivable/'
        for _ in range(2):
            response = self.client.get(f'{base}reconciliation/{self.case.pk}/')
            self.assertEqual(response.status_code,200,response.content)
            row = response.context['finance_state']['reconciliation'][0]
            finding = next(item for item in row['findings'] if item['code']=='QUANTITY_SHORTAGE')
            self.assertEqual(Decimal(finding['difference']),36000)
            self.assertTrue(any(item['recordUrl'] for item in finding['evidence']))
        payload = {'revision':self.payload()['revision']}
        endpoint = f'{base}api/recalculate/{self.case.pk}/'
        self.assertEqual(Client(enforce_csrf_checks=True).post(endpoint,payload,content_type='application/json').status_code,403)
        self.assertEqual(self.client.post(endpoint,payload,content_type='application/json').status_code,200)
        self.assertEqual(self.client.post(endpoint,{'revision':'old'},content_type='application/json').status_code,409)
        self.assertEqual(self.client.get(endpoint).status_code,405)

    def test_aggregate_price_tolerance_still_produces_specific_findings(self):
        self.fixture(receipts=(100,),invoice_price=1,order_price=1)
        order=self.order_line.purchase_order
        receipt=self.receipt_lines[0].delivery_receipt
        invoice=self.invoice_line.invoice
        other_order=type(self.order_line).objects.create(purchase_order=order,line_no=2,item_code='B',unit_of_measure='pc',quantity_ordered=100,unit_price=1,line_total=100)
        other_receipt=type(self.receipt_lines[0]).objects.create(delivery_receipt=receipt,line_no=2,item_code='B',unit_of_measure='pc',quantity_stated=100,quantity_received=100,quantity_accepted=100)
        other_invoice=type(self.invoice_line).objects.create(invoice=invoice,line_no=2,item_code='B',unit_of_measure='pc',quantity_invoiced=100,unit_price=Decimal('1.0006'),line_total=Decimal('100.06'))
        type(self.invoice_line).objects.filter(pk=self.invoice_line.pk).update(unit_price=Decimal('1.0006'),line_total=Decimal('100.06'))
        type(invoice).objects.filter(pk=invoice.pk).update(subtotal=Decimal('200.12'),total_amount=Decimal('200.12'))
        type(order).objects.filter(pk=order.pk).update(subtotal=200,total_amount=200)
        data=self.payload()
        data['matches'].append(dict(invoiceLineId=other_invoice.pk,orderLineId=other_order.pk,receiptLineId=other_receipt.pk,quantity='100'))
        with patch(self.case._meta.app_label+'.services.reconciliation.PRICE_TOLERANCE',Decimal('0.10')):
            self.save(data)
        active=self.case.discrepancy_findings.filter(finding_code='PRICE_VARIANCE',status='open')
        self.assertEqual(active.count(),2)
        self.assertEqual(sum(item.difference_amount for item in active),Decimal('0.12'))

    def test_backfill_command_is_idempotent(self):
        from io import StringIO
        from django.core.management import call_command
        self.fixture(receipts=(98,))
        self.save()
        findings=list(self.case.discrepancy_findings.values_list('pk',flat=True))
        evidence_count=FindingEvidence.objects.count()
        output=StringIO()
        for _ in range(2):
            call_command('reconcile_findings',mode=self.mode,case_id=self.case.pk,stdout=output)
        self.assertEqual(list(self.case.discrepancy_findings.values_list('pk',flat=True)),findings)
        self.assertEqual(FindingEvidence.objects.count(),evidence_count)
        self.assertIn('Reconciled 1 cases.',output.getvalue())
