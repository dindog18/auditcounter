"""Real PostgreSQL contention tests; SQLite cannot prove row locking."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless

from django.core.exceptions import ValidationError
from django.db import connection, connections
from django.test import TransactionTestCase

from .matching_test_support import PartialDeliveryFixture
from .services import records
from .services.catalog import model, revision


@skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL row locks')
class AllocationLockTests(PartialDeliveryFixture, TransactionTestCase):
    mode = 'ap'

    def test_concurrent_receipt_consumption(self):
        for mode in ('ap', 'ar'):
            self.mode = mode
            if mode != 'ap':
                self.setUp()
            self.fixture(receipts=(100,))
            first = self.payload([60])
            invoice = self.invoice_line.invoice
            invoice.pk = None
            invoice.invoice_reference_no = 'INV-concurrent'
            invoice.save()
            second_line = type(self.invoice_line).objects.create(invoice=invoice, line_no=1, item_code='A', unit_of_measure='pc', quantity_invoiced=100, unit_price=18000, line_total=1800000)
            second_case = records.save_case(mode, dict(partyId=self.party.pk, currency='PHP', date='2026-11-02', orderIds=[self.order_line.purchase_order_id], receiptIds=[self.receipt_lines[0].delivery_receipt_id], invoiceIds=[invoice.pk]))
            second = dict(revision=revision(second_case, [records.case_membership(second_case), records.matches(second_case)]), matches=[dict(first['matches'][0], invoiceLineId=second_line.pk)])
            barrier = Barrier(2)

            def allocate(case_id, data):
                connections.close_all()
                try:
                    barrier.wait(timeout=10)
                    records.save_matches(mode, case_id, data)
                    return 'saved'
                except ValidationError:
                    return 'rejected'
                finally:
                    connections.close_all()

            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(allocate, case_id, data) for case_id, data in ((self.case.pk, first), (second_case.pk, second))]
                outcomes = [future.result(timeout=30) for future in futures]
            self.assertCountEqual(outcomes, ['saved', 'rejected'])
            matches = model(mode, 'DocumentMatch').objects.filter(delivery_receipt_line=self.receipt_lines[0])
            self.assertEqual(sum(match.matched_quantity for match in matches), 60)

    def test_concurrent_auto_confirmations_reject_stale_source_snapshot(self):
        from .services.auto_matching import generate_match_suggestions, allocation_row
        from .services.catalog import party_key
        for mode in ('ap', 'ar'):
            self.mode = mode
            if mode != 'ap':
                self.setUp()
            self.fixture(receipts=(100,))
            type(self.order_line.purchase_order).objects.filter(pk=self.order_line.purchase_order_id).update(status='open')
            type(self.invoice_line.invoice).objects.filter(pk=self.invoice_line.invoice_id).update(invoice_status='posted')
            receipt = self.receipt_lines[0].delivery_receipt
            type(receipt).objects.filter(pk=receipt.pk).update(**{'receipt_status' if mode=='ap' else 'delivery_status':'accepted' if mode=='ap' else 'delivered'})
            invoice = self.invoice_line.invoice
            invoice.pk = None
            invoice.invoice_reference_no = 'AUTO-OTHER'
            invoice.invoice_status = 'posted'
            invoice.save()
            type(self.invoice_line).objects.create(invoice=invoice, line_no=1, item_code='A', unit_of_measure='pc', quantity_invoiced=100, unit_price=18000, line_total=1800000)
            other = records.save_case(mode, dict(partyId=self.party.pk, currency='PHP', date='2026-11-02', orderIds=[self.order_line.purchase_order_id], receiptIds=[receipt.pk], invoiceIds=[invoice.pk]))
            requests = []
            for case in (self.case, other):
                result = generate_match_suggestions(case)
                row = allocation_row(result['suggestions'][0])
                row['quantity'] = '60'
                requests.append((case.pk, dict(revision=result['revision'], suggestionRevision=result['suggestion_revision'], preserveExisting=True, matches=[row])))
            barrier = Barrier(2)

            def confirm(case_id, data):
                connections.close_all()
                try:
                    barrier.wait(timeout=10)
                    records.save_matches(mode, case_id, data)
                    return 'saved'
                except ValidationError as error:
                    return error.code
                finally:
                    connections.close_all()

            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(confirm, case_id, data) for case_id, data in requests]
                outcomes = [future.result(timeout=30) for future in futures]
            self.assertCountEqual(outcomes, ['saved', 'conflict'])
            saved = model(mode,'DocumentMatch').objects.filter(delivery_receipt_line=receipt.lines.get())
            self.assertEqual(sum(row.matched_quantity for row in saved), 60)
