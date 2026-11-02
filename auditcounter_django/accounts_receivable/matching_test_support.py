"""Shared AP/AR scenarios exercise the same workspace contract in both directions."""
from decimal import Decimal
from importlib import import_module
from django.core.exceptions import ValidationError
from .services import records, pages
from .services.catalog import model, party_key, revision


class PartialDeliveryFixture:
    def setUp(self):
        key = party_key(self.mode)
        self.party = model(self.mode, key).objects.create(**{key+'_code': 'PARTIAL', key+'_name': 'Partial deliveries'})

    def fixture(self, receipts=(60, 40), invoiced=100, invoice_price=18000, order_price=18000, currency='PHP'):
        mode, key = self.mode, party_key(self.mode)
        party = {key: self.party}
        order = model(mode, 'purchase_order').objects.create(**party, po_reference_no='PO', order_date='2026-11-02', currency=currency, subtotal=100*order_price, total_amount=100*order_price)
        invoice = model(mode, 'sales_invoice').objects.create(**party, invoice_reference_no='INV', invoice_date='2026-11-02', currency=currency, subtotal=invoiced*invoice_price, total_amount=invoiced*invoice_price)
        self.order_line = model(mode, type(order).__name__+'Line').objects.create(purchase_order=order, line_no=1, item_code='A', unit_of_measure='pc', quantity_ordered=100, unit_price=order_price, line_total=100*order_price)
        self.invoice_line = model(mode, type(invoice).__name__+'Line').objects.create(invoice=invoice, line_no=1, item_code='A', unit_of_measure='pc', quantity_invoiced=invoiced, unit_price=invoice_price, line_total=invoiced*invoice_price)
        self.receipt_lines = []
        for index, quantity in enumerate(receipts):
            receipt = model(mode, 'delivery_receipt').objects.create(**party, dr_reference_no=f'DR-{index}', delivery_date='2026-11-02')
            self.receipt_lines.append(model(mode, type(receipt).__name__+'Line').objects.create(delivery_receipt=receipt, line_no=1, item_code='A', unit_of_measure='pc', quantity_stated=quantity, quantity_received=quantity, quantity_accepted=quantity))
        self.case = records.save_case(mode, dict(partyId=self.party.pk, currency=currency, date='2026-11-02', orderIds=[order.pk], invoiceIds=[invoice.pk], receiptIds=[line.delivery_receipt_id for line in self.receipt_lines]))
        self.service = import_module(model(mode, 'Transaction').__module__.rsplit('.', 1)[0]+'.services.reconciliation')

    def payload(self, quantities=None):
        self.case.refresh_from_db()
        quantities = quantities if quantities is not None else [line.quantity_accepted for line in self.receipt_lines]
        return dict(revision=revision(self.case, [records.case_membership(self.case), records.matches(self.case)]), matches=[dict(invoiceLineId=self.invoice_line.pk, orderLineId=self.order_line.pk, receiptLineId=line.pk, quantity=str(quantity)) for line, quantity in zip(self.receipt_lines, quantities)])

    def save(self, payload=None):
        return records.save_matches(self.mode, self.case.pk, payload or self.payload())



class PartialDeliveryScenarios(PartialDeliveryFixture):
    def test_complete_split_deliveries_and_reopen(self):
        self.fixture(currency='USD')
        preview = records.preview_matches(self.mode, self.case.pk, self.payload())
        self.assertFalse(self.case.line_matches.exists())
        self.save()
        result = self.service.evaluate_reconciliation(self.case)
        self.assertEqual(result, preview)
        self.assertEqual(result['status'], 'matched')
        self.assertEqual(result['discrepancy'], 0)
        self.assertEqual(result['lines'][0]['supported'], 100)
        self.assertEqual(result['lines'][0]['unmatched'], 0)
        state = pages.workspace_state(self.mode, 'reconciliation')['reconciliation'][0]
        self.assertEqual(len(state['matches']), 2)
        self.assertEqual(state['currency'], 'USD')
        self.assertEqual(state['evaluation'], result)
        self.save(self.payload())  # Replacing unchanged allocations remains supported.
        self.assertEqual(self.case.line_matches.count(), 2)

    def test_incomplete_split_delivery(self):
        self.fixture(receipts=(60, 30))
        self.save()
        result = self.service.evaluate_reconciliation(self.case)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['lines'][0]['supported'], 90)
        self.assertEqual(result['lines'][0]['unmatched'], 10)
        self.assertEqual(result['unsupportedAmount'], Decimal('180000'))
        self.assertEqual(result['discrepancy'], Decimal('180000'))

    def test_partial_invoice_has_no_invoice_shortage(self):
        self.fixture(receipts=(60,), invoiced=60)
        self.save()
        result = self.service.evaluate_reconciliation(self.case)
        self.assertEqual(result['status'], 'matched')
        self.assertEqual(result['discrepancy'], 0)
        self.assertEqual(next(f for f in result['findings'] if f['kind']=='outstanding_order')['quantity'], 40)

    def test_overallocation_and_duplicate_roll_back(self):
        self.fixture(receipts=(100,))
        self.save()
        original = records.matches(self.case)
        for quantities in ([120],):
            with self.assertRaises(ValidationError):
                self.save(self.payload(quantities))
            self.assertEqual(records.matches(self.case), original)
        payload = self.payload([50])
        payload['matches'] *= 2
        with self.assertRaises(ValidationError):
            self.save(payload)
        self.assertEqual(records.matches(self.case), original)

    def test_price_variance_keeps_receiving_support(self):
        self.fixture(receipts=(100,), invoice_price=18500)
        self.save()
        result = self.service.evaluate_reconciliation(self.case)
        self.assertEqual(result['status'], 'exception')
        self.assertEqual(result['lines'][0]['unmatched'], 0)
        self.assertEqual(result['unsupportedAmount'], 0)
        self.assertEqual(result['priceVariance'], 50000)
        self.assertEqual(result['overcharge'], 50000)
        self.assertEqual(result['undercharge'], 0)
        self.assertEqual(result['discrepancy'], 50000)

    def test_undercharge_direction(self):
        self.fixture(receipts=(100,), invoice_price=17500)
        self.save()
        result = self.service.evaluate_reconciliation(self.case)
        self.assertEqual(result['priceVariance'], -50000)
        self.assertEqual(result['overcharge'], 0)
        self.assertEqual(result['undercharge'], 50000)
        self.assertEqual(result['lines'][0]['unmatched'], 0)

    def test_overlapping_header_findings_count_once(self):
        self.fixture(receipts=(100,), order_price=1, invoice_price=1)
        invoice = self.invoice_line.invoice
        type(invoice).objects.filter(pk=invoice.pk).update(total_amount=110)
        self.save()
        result = self.service.evaluate_reconciliation(self.case)
        self.assertEqual(result['status'], 'exception')
        self.assertEqual(result['arithmeticDifference'], 10)
        self.assertEqual(result['discrepancy'], 10)
        self.assertEqual(len([f for f in result['findings'] if f['kind'] in ('header_arithmetic', 'line_total_arithmetic')]), 2)

    def test_incompatible_receipt_unit_is_rejected(self):
        self.fixture(receipts=(100,))
        line = self.receipt_lines[0]
        type(line).objects.filter(pk=line.pk).update(unit_of_measure='box')
        with self.assertRaises(ValidationError):
            self.save()
        self.assertFalse(self.case.line_matches.exists())

    def test_other_cases_reserve_receipt_quantity(self):
        self.fixture(receipts=(100,))
        self.save(self.payload([60]))
        invoice = self.invoice_line.invoice
        invoice.pk = None
        invoice.invoice_reference_no = 'INV2'
        invoice.save()
        invoice_line = type(self.invoice_line).objects.create(invoice=invoice, line_no=1, item_code='A', unit_of_measure='pc', quantity_invoiced=100, unit_price=18000, line_total=1800000)
        other = records.save_case(self.mode, dict(partyId=self.party.pk, currency='PHP', date='2026-11-02', orderIds=[self.order_line.purchase_order_id], invoiceIds=[invoice.pk], receiptIds=[self.receipt_lines[0].delivery_receipt_id]))
        data = self.payload([50])
        data['matches'][0]['invoiceLineId'] = invoice_line.pk
        data['revision'] = revision(other, [records.case_membership(other), records.matches(other)])
        with self.assertRaises(ValidationError):
            records.save_matches(self.mode, other.pk, data)
        self.assertFalse(other.line_matches.exists())
        self.assertEqual(self.case.line_matches.get().matched_quantity, 60)

    def test_discount_and_tax_exposure_uses_line_value(self):
        self.fixture(receipts=(90,), order_price=10, invoice_price=10)
        for line, field in ((self.order_line, 'quantity_ordered'), (self.invoice_line, 'quantity_invoiced')):
            type(line).objects.filter(pk=line.pk).update(discount_amount=100, tax_amount=180, line_total=1080)
            header = line.purchase_order if field == 'quantity_ordered' else line.invoice
            type(header).objects.filter(pk=header.pk).update(discount_amount=100, tax_amount=180, total_amount=1080)
        self.save()
        result = self.service.evaluate_reconciliation(self.case)
        self.assertEqual(result['unsupportedAmount'], 108)
        self.assertEqual(result['discrepancy'], 108)

    def test_preview_endpoint_is_read_only_and_checks_revision(self):
        self.fixture(receipts=(100,))
        slug = 'accounts-payable' if self.mode == 'ap' else 'accounts-receivable'
        response = self.client.post(f'/{slug}/api/matches-preview/{self.case.pk}/', self.payload(), content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['status'], 'matched')
        self.assertEqual(response.json()['discrepancy'], '0.00')
        self.assertFalse(self.case.line_matches.exists())
        data = self.payload()
        data['revision'] = 'old'
        response = self.client.post(f'/{slug}/api/matches-preview/{self.case.pk}/', data, content_type='application/json')
        self.assertEqual(response.status_code, 409)

    def test_discount_offsets_price_without_inflating_exposure(self):
        self.fixture(receipts=(100,), order_price=10, invoice_price=11)
        invoice = self.invoice_line.invoice
        type(self.invoice_line).objects.filter(pk=self.invoice_line.pk).update(discount_amount=100, line_total=1000)
        type(invoice).objects.filter(pk=invoice.pk).update(discount_amount=100, total_amount=1000)
        self.save()
        result = self.service.evaluate_reconciliation(self.case)
        self.assertEqual(result['priceVariance'], 100)
        self.assertEqual(result['financialVariance'], 0)
        self.assertEqual(result['overcharge'], 0)
        self.assertEqual(result['undercharge'], 0)
        self.assertEqual(result['discrepancy'], 0)
        self.assertEqual(result['status'], 'exception')
