"""Focused regression tests for the AP/AR three-way reconciliation MVP."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from .services import records
from .services.catalog import model, party_key, revision


class SplitDeliveryReconciliationTests(TestCase):
    def create_case(self, mode):
        key = party_key(mode)
        party = model(mode, key).objects.create(
            **{key + "_code": "ACCT", key + "_name": "Example account"}
        )
        order = model(mode, "purchase_order").objects.create(
            **{key: party}, po_reference_no="PO-1", order_date="2026-11-05",
            currency="PHP", subtotal="100", total_amount="100", status="open",
        )
        invoice = model(mode, "sales_invoice").objects.create(
            **{key: party}, invoice_reference_no="INV-1", invoice_date="2026-11-05",
            currency="PHP", subtotal="100", total_amount="100", invoice_status="posted",
        )
        order_line = model(mode, type(order).__name__ + "Line").objects.create(
            purchase_order=order, line_no=1, item_code="SKU-1", unit_of_measure="pc",
            quantity_ordered="4", unit_price="25", line_total="100",
        )
        invoice_line = model(mode, type(invoice).__name__ + "Line").objects.create(
            invoice=invoice, line_no=1, item_code="SKU-1", unit_of_measure="pc",
            quantity_invoiced="4", unit_price="25", line_total="100",
        )
        receipts = []
        for number in (1, 2):
            receipt = model(mode, "delivery_receipt").objects.create(
                **{key: party}, dr_reference_no=f"DR-{number}", delivery_date="2026-11-05",
                **({"delivery_status": "delivered"} if mode == "ar" else {"receipt_status": "accepted"}),
            )
            line = model(mode, type(receipt).__name__ + "Line").objects.create(
                delivery_receipt=receipt, line_no=1, item_code="SKU-1", unit_of_measure="pc",
                quantity_stated="2", quantity_received="2", quantity_accepted="2",
            )
            receipts.append((receipt, line))
        case = records.save_case(mode, {
            "partyId": party.pk, "date": "2026-11-05", "currency": "PHP",
            "orderIds": [order.pk], "receiptIds": [receipt.pk for receipt, _ in receipts],
            "invoiceIds": [invoice.pk],
        })
        return case, invoice_line, order_line, [line for _, line in receipts]

    def payload(self, case, invoice_line, order_line, receipt_lines, quantities):
        return {
            "revision": revision(case, [records.case_membership(case), records.matches(case)]),
            "matches": [
                {
                    "invoiceLineId": invoice_line.pk,
                    "orderLineId": order_line.pk,
                    "receiptLineId": receipt.pk,
                    "quantity": str(quantity),
                }
                for receipt, quantity in zip(receipt_lines, quantities)
            ],
        }

    def test_multiple_deliveries_reconcile_one_invoice_in_both_modules(self):
        for mode in ("ar", "ap"):
            with self.subTest(mode=mode):
                case, invoice, order, receipts = self.create_case(mode)
                first = self.payload(case, invoice, order, receipts[:1], [2])
                records.save_matches(mode, case.pk, first)
                case.refresh_from_db()
                self.assertEqual(case.reconciliation_status, "partial")
                self.assertEqual(case.total_discrepancy_amount, Decimal("50.00"))

                complete = self.payload(case, invoice, order, receipts, [2, 2])
                records.save_matches(mode, case.pk, complete)
                case.refresh_from_db()
                self.assertEqual(case.reconciliation_status, "matched")
                self.assertEqual(case.total_discrepancy_amount, Decimal("0.00"))
                self.assertEqual(case.line_matches.filter(match_status="matched").count(), 2)

    def test_duplicate_or_excess_allocation_rolls_back_existing_matches(self):
        for mode in ("ar", "ap"):
            with self.subTest(mode=mode):
                case, invoice, order, receipts = self.create_case(mode)
                records.save_matches(mode, case.pk, self.payload(case, invoice, order, receipts[:1], [2]))
                case.refresh_from_db()
                duplicate = self.payload(case, invoice, order, receipts[:1] * 2, [1, 1])
                with self.assertRaisesMessage(ValidationError, "only once"):
                    records.save_matches(mode, case.pk, duplicate)
                excess = self.payload(case, invoice, order, receipts, [2, 3])
                with self.assertRaisesMessage(ValidationError, "exceed the invoice"):
                    records.save_matches(mode, case.pk, excess)
                case.refresh_from_db()
                self.assertEqual(case.line_matches.count(), 1)
                self.assertEqual(case.reconciliation_status, "partial")

    def test_mismatched_receipt_is_reported_as_exception(self):
        for mode in ("ar", "ap"):
            with self.subTest(mode=mode):
                case, invoice, order, receipts = self.create_case(mode)
                receipts[1].item_code = "OTHER-SKU"
                receipts[1].save()
                records.save_matches(mode, case.pk, self.payload(case, invoice, order, receipts, [2, 2]))
                case.refresh_from_db()
                self.assertEqual(case.reconciliation_status, "exception")
                self.assertEqual(case.line_matches.filter(match_status="exception").count(), 1)

    def test_empty_allocation_set_clears_existing_matches(self):
        for mode in ("ar", "ap"):
            with self.subTest(mode=mode):
                case, invoice, order, receipts = self.create_case(mode)
                records.save_matches(mode, case.pk, self.payload(case, invoice, order, receipts, [2, 2]))
                case.refresh_from_db()
                records.save_matches(mode, case.pk, {
                    "revision": revision(case, [records.case_membership(case), records.matches(case)]),
                    "matches": [],
                })
                case.refresh_from_db()
                self.assertEqual(case.line_matches.count(), 0)
                self.assertEqual(case.reconciliation_status, "pending")
