"""Rule-based proposal scenarios run against both AP and AR models."""
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import Client

from .matching_test_support import PartialDeliveryFixture
from .services import records
from .services.auto_matching import generate_match_suggestions, allocation_row, source_revision, normalize_item_code
from .services.catalog import model, party_key, revision


class AutoMatchingScenarios(PartialDeliveryFixture):
    def ready_fixture(self, **kwargs):
        self.fixture(**kwargs)
        type(self.order_line.purchase_order).objects.filter(pk=self.order_line.purchase_order_id).update(status='open')
        type(self.invoice_line.invoice).objects.filter(pk=self.invoice_line.invoice_id).update(invoice_status='posted')
        for line in self.receipt_lines:
            receipt = line.delivery_receipt
            type(receipt).objects.filter(pk=receipt.pk).update(**{'receipt_status' if self.mode=='ap' else 'delivery_status': 'accepted' if self.mode=='ap' else 'delivered'})
        self.case.refresh_from_db()

    def confirmation(self, result, candidates=None):
        return dict(revision=result['revision'], suggestionRevision=result['suggestion_revision'], preserveExisting=True,
                    matches=[allocation_row(row) for row in (candidates if candidates is not None else result['suggestions'])])

    def test_exact_and_repeatable_read_only_suggestion(self):
        self.ready_fixture(receipts=(100,))
        before = source_revision(self.case)
        result = generate_match_suggestions(self.case)
        self.assertEqual(result, generate_match_suggestions(self.case))
        self.assertEqual(source_revision(self.case), before)
        self.assertFalse(self.case.line_matches.exists())
        self.assertEqual(len(result['suggestions']), 1)
        self.assertEqual(result['needs_review'], [])
        candidate = result['suggestions'][0]
        self.assertEqual(candidate['status'], 'suggested')
        self.assertEqual(Decimal(candidate['matched_quantity']), 100)
        self.assertIn('Exact normalized SKU', candidate['reasons'])
        records.save_matches(self.mode, self.case.pk, self.confirmation(result))
        self.assertEqual(self.case.calculate_reconciliation(), ('matched', Decimal('0.00')))
        self.assertEqual(generate_match_suggestions(self.case)['suggestions'], [])

    def test_split_deliveries_are_proposed_and_saveable(self):
        self.ready_fixture()
        result = generate_match_suggestions(self.case)
        self.assertEqual(len(result['suggestions']), 2)
        self.assertEqual(sum(Decimal(row['matched_quantity']) for row in result['suggestions']), 100)
        records.save_matches(self.mode, self.case.pk, self.confirmation(result))
        self.assertEqual(self.case.line_matches.count(), 2)
        self.assertEqual(self.case.calculate_reconciliation()[0], 'matched')

    def test_insufficient_receiving_capacity(self):
        self.ready_fixture(receipts=(80,))
        result = generate_match_suggestions(self.case)
        self.assertEqual(Decimal(result['suggestions'][0]['matched_quantity']), 80)
        self.assertEqual(Decimal(result['lines'][0]['remaining_unmatched_quantity']), 20)
        self.assertEqual(Decimal(result['unmatched'][0]['quantity']), 20)

    def test_different_party_cannot_be_suggested(self):
        self.ready_fixture(receipts=(100,))
        key = party_key(self.mode)
        other = model(self.mode, key).objects.create(**{key+'_code':'OTHER', key+'_name':'Other party'})
        receipt = self.receipt_lines[0].delivery_receipt
        type(receipt).objects.filter(pk=receipt.pk).update(**{key:other})
        result = generate_match_suggestions(self.case)
        self.assertEqual(result['suggestions'], [])
        self.assertFalse(result['needs_review'][0]['candidates'][0]['eligible'])
        self.assertIn('party', ' '.join(result['needs_review'][0]['candidates'][0]['reasons']))

    def test_different_sku_requires_review(self):
        self.ready_fixture(receipts=(100,))
        type(self.order_line).objects.filter(pk=self.order_line.pk).update(item_code='B')
        result = generate_match_suggestions(self.case)
        self.assertFalse(result['suggestions'])
        self.assertIn('SKU', ' '.join(result['needs_review'][0]['reasons']))

    def test_ambiguous_purchase_order_is_not_selected_by_price_or_sort(self):
        self.ready_fixture(receipts=(100,))
        order = self.order_line.purchase_order
        order.pk = None
        order.po_reference_no = 'PO2'
        order.status = 'open'
        order.save()
        other_line = type(self.order_line).objects.create(purchase_order=order, line_no=1, item_code='A', unit_of_measure='pc', quantity_ordered=100, unit_price=18000, line_total=1800000)
        self.case.purchase_orders.add(order)
        result = generate_match_suggestions(self.case)
        self.assertFalse(result['suggestions'])
        review = result['needs_review'][0]
        self.assertIn('Multiple plausible PO', ' '.join(review['reasons']))
        self.assertEqual({candidate['purchase_order_line_id'] for candidate in review['candidates']}, {self.order_line.pk, other_line.pk})
        self.assertTrue(all('matched_quantity' not in candidate for candidate in review['candidates']))

    def test_price_difference_retains_supported_relationship(self):
        self.ready_fixture(receipts=(100,), invoice_price=18500)
        result = generate_match_suggestions(self.case)
        self.assertFalse(result['suggestions'])
        candidate = result['needs_review'][0]
        self.assertTrue(candidate['eligible'])
        self.assertEqual(Decimal(candidate['matched_quantity']), 100)
        self.assertEqual(Decimal(candidate['price_variance']), 50000)
        records.save_matches(self.mode, self.case.pk, self.confirmation(result, [candidate]))
        evaluation = self.service.evaluate_reconciliation(self.case)
        self.assertEqual(evaluation['status'], 'exception')
        self.assertEqual(evaluation['unsupportedAmount'], 0)
        self.assertEqual(evaluation['priceVariance'], 50000)

    def test_existing_manual_matches_are_merged_not_overwritten(self):
        self.ready_fixture()
        self.save(self.payload([60]))
        original = records.matches(self.case)
        saved = self.case.line_matches.get()
        self.case.line_matches.filter(pk=saved.pk).update(notes='Manual evidence retained')
        result = generate_match_suggestions(self.case)
        self.assertEqual(len(result['suggestions']), 1)
        self.assertEqual(Decimal(result['suggestions'][0]['matched_quantity']), 40)
        self.assertEqual(records.matches(self.case), original)
        records.save_matches(self.mode, self.case.pk, self.confirmation(result))
        self.assertEqual(self.case.line_matches.count(), 2)
        self.assertEqual(self.case.line_matches.get(pk=saved.pk).notes, 'Manual evidence retained')
        self.assertEqual(sum(row.matched_quantity for row in self.case.line_matches.all()), 100)

    def test_already_used_quantities_from_other_cases(self):
        self.ready_fixture(receipts=(100,))
        # A different invoice consumes 60 units of this order and receipt.
        invoice = self.invoice_line.invoice
        invoice.pk = None
        invoice.invoice_reference_no = 'OTHER-INV'
        invoice.save()
        other_line = type(self.invoice_line).objects.create(invoice=invoice, line_no=1, item_code='A', unit_of_measure='pc', quantity_invoiced=100, unit_price=18000, line_total=1800000)
        other = model(self.mode,'Transaction').objects.create(**{party_key(self.mode):self.party}, currency='PHP')
        other.purchase_orders.add(self.order_line.purchase_order)
        other.delivery_receipts.add(self.receipt_lines[0].delivery_receipt)
        other.sales_invoices.add(invoice)
        model(self.mode,'DocumentMatch').objects.create(transaction=other, invoice_line=other_line, purchase_order_line=self.order_line, delivery_receipt_line=self.receipt_lines[0], matched_quantity=60, match_status='matched')
        result = generate_match_suggestions(self.case)
        self.assertEqual(Decimal(result['suggestions'][0]['matched_quantity']), 40)
        self.assertEqual(Decimal(result['lines'][0]['remaining_unmatched_quantity']), 60)

    def test_stale_source_and_case_revisions_are_rejected_without_changes(self):
        self.ready_fixture(receipts=(100,))
        result = generate_match_suggestions(self.case)
        type(self.receipt_lines[0]).objects.filter(pk=self.receipt_lines[0].pk).update(quantity_accepted=80)
        with self.assertRaises(ValidationError) as error:
            records.save_matches(self.mode, self.case.pk, self.confirmation(result))
        self.assertEqual(error.exception.code, 'conflict')
        self.assertFalse(self.case.line_matches.exists())
        result = generate_match_suggestions(self.case)
        data = self.confirmation(result)
        data['revision'] = 'old'
        with self.assertRaises(ValidationError):
            records.save_matches(self.mode, self.case.pk, data)
        self.assertFalse(self.case.line_matches.exists())

    def test_normalized_codes_and_units_persist_through_manual_validator(self):
        self.ready_fixture(receipts=(100,))
        for line, code, unit in ((self.invoice_line, '  WM-10KG  ', 'PCS'), (self.order_line, 'wm-10kg', ' pcs '), (self.receipt_lines[0], 'WM-10KG', 'Pcs')):
            type(line).objects.filter(pk=line.pk).update(item_code=code, unit_of_measure=unit)
        self.assertEqual(normalize_item_code('  WM   10KG '), 'wm 10kg')
        result = generate_match_suggestions(self.case)
        self.assertEqual(len(result['suggestions']), 1)
        records.save_matches(self.mode, self.case.pk, self.confirmation(result))
        self.assertEqual(self.case.calculate_reconciliation()[0], 'matched')

    def test_units_and_pending_status_require_review(self):
        self.ready_fixture(receipts=(100,))
        receipt = self.receipt_lines[0]
        type(receipt).objects.filter(pk=receipt.pk).update(unit_of_measure='box')
        result = generate_match_suggestions(self.case)
        self.assertFalse(result['suggestions'])
        self.assertFalse(result['needs_review'][0]['candidates'][0]['eligible'])
        type(receipt).objects.filter(pk=receipt.pk).update(unit_of_measure='pc')
        invoice = self.invoice_line.invoice
        type(invoice).objects.filter(pk=invoice.pk).update(invoice_status='pending')
        self.assertFalse(generate_match_suggestions(self.case)['suggestions'])

    def test_multiple_receipts_with_surplus_need_review(self):
        self.ready_fixture(receipts=(60, 60))
        result = generate_match_suggestions(self.case)
        self.assertFalse(result['suggestions'])
        self.assertEqual(len(result['needs_review'][0]['candidates']), 2)
        self.assertIn('subset', ' '.join(result['needs_review'][0]['reasons']))

    def test_api_read_only_csrf_and_revision(self):
        self.ready_fixture(receipts=(100,))
        base = '/accounts-payable/' if self.mode == 'ap' else '/accounts-receivable/'
        endpoint = f'{base}api/match-suggestions/{self.case.pk}/'
        data = {'revision':self.payload()['revision']}
        response = self.client.post(endpoint, data, content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsInstance(response.json()['suggestions'][0]['matched_quantity'], str)
        self.assertFalse(self.case.line_matches.exists())
        self.assertEqual(Client(enforce_csrf_checks=True).post(endpoint, data, content_type='application/json').status_code, 403)
        self.assertEqual(self.client.get(endpoint).status_code, 405)
        self.assertEqual(self.client.post(endpoint, {'revision':'old'}, content_type='application/json').status_code, 409)

    def test_manual_draft_capacity_is_respected(self):
        self.ready_fixture()
        result = generate_match_suggestions(self.case, current_rows=self.payload([60])['matches'])
        self.assertEqual(len(result['suggestions']), 1)
        self.assertEqual(Decimal(result['suggestions'][0]['matched_quantity']), 40)
        self.assertFalse(self.case.line_matches.exists())

    def test_saved_rows_cannot_be_changed_during_auto_confirmation(self):
        self.ready_fixture()
        self.save(self.payload([60]))
        result = generate_match_suggestions(self.case)
        data = self.confirmation(result)
        data['matches'] += self.payload([50])['matches']
        original = records.matches(self.case)
        with self.assertRaises(ValidationError):
            records.save_matches(self.mode, self.case.pk, data)
        self.assertEqual(records.matches(self.case), original)

    def test_source_change_during_generation_returns_conflict(self):
        self.ready_fixture()
        actual = source_revision(self.case)
        with patch('accounts_receivable.services.auto_matching.source_revision', side_effect=[actual,'changed']):
            with self.assertRaises(ValidationError):
                generate_match_suggestions(self.case)
        self.assertFalse(self.case.line_matches.exists())
