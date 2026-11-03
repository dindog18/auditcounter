"""Plain functions for AR matching and settlement; models remain ordinary models.Model classes."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Sum

from .amounts import line_amount_issues

if TYPE_CHECKING:
    from ..models import (
        CustomerPurchaseOrder,
        CompanyDeliveryReceipt,
        CompanySalesInvoice,
        CustomerPayment,
        CustomerPurchaseOrderLine,
        CompanyDeliveryReceiptLine,
        CompanySalesInvoiceLine,
        Transaction,
        DocumentMatch,
        PaymentAllocation,
    )

    type SourceRecord = (
        CustomerPurchaseOrder | CompanyDeliveryReceipt | CompanySalesInvoice | CustomerPayment
    )
    type CaseDocument = CustomerPurchaseOrder | CompanyDeliveryReceipt | CompanySalesInvoice
    type DocumentLine = CustomerPurchaseOrderLine | CompanyDeliveryReceiptLine | CompanySalesInvoiceLine

ZERO = Decimal("0")
PRICE_TOLERANCE = Decimal(str(getattr(settings, "RECONCILIATION_PRICE_TOLERANCE", "0.01")))


def normalize_source_key(key):
    # Sorting composite keys ensures repeat imports use the same stored identity.
    return json.loads(json.dumps(key, sort_keys=True)) if key else key


def refresh_document_cases(document: CaseDocument) -> None:
    # Changing a source document can invalidate an existing match.
    for case in document.reconciliation_cases.all():
        case.refresh_reconciliation_status()


def validate_source(record: SourceRecord) -> None:
    """Ensure the database table and extraction logs belong to the chosen sources."""
    errors = {}
    if record.source_table_id:
        if (
            not record.source_database_id
            or record.source_table.schema.run.source_id != record.source_database_id
        ):
            errors["source_table"] = "Source table must belong to the selected database."
        if not record.source_record_key:
            errors["source_record_key"] = "Record key is required for a database table source."
        elif (
            type(record)
            .objects.filter(
                source_table_id=record.source_table_id, source_record_key=record.source_record_key
            )
            .exclude(pk=record.pk)
            .exists()
        ):
            errors["source_record_key"] = "This source record was imported already."
    for field in ("source_llm_log", "source_text_log"):
        log = getattr(record, field)
        if log and (
            not record.source_document_id or log.fk_document_no_id != record.source_document_id
        ):
            errors[field] = "Extraction log must belong to the source document."
    if errors:
        raise ValidationError(errors)


def validate_line(line: DocumentLine) -> None:
    """Keep quantities and prices stable while a line participates in a completed match."""
    if not line.pk or not line.matches.filter(match_status="matched").exists():
        return
    previous = type(line).objects.get(pk=line.pk)
    protected = (
        "purchase_order_id",
        "delivery_receipt_id",
        "invoice_id",
        "line_no",
        "item_code",
        "unit_of_measure",
        "quantity_ordered",
        "quantity_accepted",
        "quantity_invoiced",
        "unit_price",
        "discount_amount",
        "tax_amount",
        "line_total",
    )
    if any(
        (
            hasattr(line, name) and getattr(line, name) != getattr(previous, name)
            for name in protected
        )
    ):
        raise ValidationError("Remove existing matches before changing matched line values.")


def validate_match(match: DocumentMatch, *, check_amounts=True, check_capacity=True) -> None:
    """Check three-way matching rules and prevent reuse of ordered or accepted quantities."""
    errors = {}
    if not match.transaction_id or not match.invoice_line_id:
        return
    case = match.transaction
    invoice = match.invoice_line.invoice
    if not case.customer_id:
        errors["transaction"] = "Set the case customer or supplier before matching."
    if invoice.customer_id != case.customer_id or invoice.currency != case.currency:
        errors["invoice_line"] = "Invoice party and currency must match the case."
    if not case.sales_invoices.filter(pk=invoice.pk).exists():
        errors["invoice_line"] = "Add the invoice to the case first."
    for field, collection, header in (
        ("purchase_order_line", "purchase_orders", "purchase_order"),
        ("delivery_receipt_line", "delivery_receipts", "delivery_receipt"),
    ):
        line = getattr(match, field)
        if line is None:
            continue
        document = getattr(line, header)
        if document.customer_id != case.customer_id:
            errors[field] = "Document party must match the case."
        elif hasattr(document, "currency") and document.currency != case.currency:
            errors[field] = "Document currency must match the case."
        elif not getattr(case, collection).filter(pk=document.pk).exists():
            errors[field] = "Add this document to the case first."
    if match.match_status == match.Status.MATCHED and (
        not match.purchase_order_line_id
        or not match.delivery_receipt_line_id
        or match.matched_quantity <= ZERO
    ):
        errors["match_status"] = (
            "A matched line needs an order, an accepted receipt, and a positive quantity."
        )
    order_line = match.purchase_order_line
    receipt_line = match.delivery_receipt_line
    if (
        match.match_status == match.Status.MATCHED
        and order_line is not None
        and (receipt_line is not None)
    ):
        invoice_line = match.invoice_line
        for line, quantity_field, field in (
            (invoice_line, "quantity_invoiced", "invoice_line"),
            (order_line, "quantity_ordered", "purchase_order_line"),
        ):
            issues = line_amount_issues(line, quantity_field, PRICE_TOLERANCE)
            if issues and check_amounts:
                errors[field] = "; ".join(issues)
        if not invoice.invoice_reference_no or not invoice.invoice_date or (not invoice.currency):
            errors["invoice_line"] = (
                "Invoice reference, date, and currency are required for matching."
            )
        if (
            not receipt_line.delivery_receipt.dr_reference_no
            or not receipt_line.delivery_receipt.delivery_date
        ):
            errors["delivery_receipt_line"] = (
                "Delivery reference and date are required for matching."
            )
        if order_line.purchase_order.status == "cancelled":
            errors["purchase_order_line"] = "A cancelled purchase order cannot be matched."
        from sku_matching.services.normalization import normalize_sku, normalize_unit
        from sku_matching.services.mapping import identity_for_match
        units = [normalize_unit(line.unit_of_measure) for line in (invoice_line, order_line, receipt_line)]
        if len(set(units)) > 1:
            errors["delivery_receipt_line"] = "Unit of measure differs; SKU mappings cannot convert units."
        codes = [normalize_sku(line.item_code) for line in (invoice_line, order_line, receipt_line)]
        if any(codes):
            identity = identity_for_match(match)
            if not identity['equivalent']:
                errors["invoice_line"] = "; ".join(identity['reasons'])
    if check_capacity and match.matched_quantity > ZERO and match.purchase_order_line_id and match.delivery_receipt_line_id:
        for field, capacity in (
            ("invoice_line", "quantity_invoiced"),
            ("purchase_order_line", "quantity_ordered"),
            ("delivery_receipt_line", "quantity_accepted"),
        ):
            line = getattr(match, field)
            if line is None:
                continue
            used = (
                type(match)
                .objects.filter(**{field: line}, purchase_order_line__isnull=False, delivery_receipt_line__isnull=False)
                .exclude(pk=match.pk)
                .aggregate(total=Sum("matched_quantity"))["total"]
                or ZERO
            )
            if used + match.matched_quantity > getattr(line, capacity):
                errors[field] = "Matched quantity exceeds the available quantity."
    if check_capacity and type(match).objects.filter(
        invoice_line_id=match.invoice_line_id,
        purchase_order_line_id=match.purchase_order_line_id,
        delivery_receipt_line_id=match.delivery_receipt_line_id,
    ).exclude(pk=match.pk).exists():
        errors["invoice_line"] = "Duplicate invoice/order/receipt allocation."
    if errors:
        raise ValidationError(errors)


def validate_allocation(allocation: PaymentAllocation) -> None:
    """Keep allocations within the payment components and invoice total."""
    if not allocation.payment_id or not allocation.invoice_id:
        return
    payment, invoice = (allocation.payment, allocation.invoice)
    errors = {}
    if payment.payment_status == "reversed":
        errors["payment"] = "A reversed payment cannot be allocated."
    if (
        allocation.cash_amount + allocation.withholding_tax_amount + allocation.discount_amount
        <= ZERO
    ):
        errors["cash_amount"] = "Allocate a positive amount."
    if payment.customer_id != invoice.customer_id or payment.currency != invoice.currency:
        errors["invoice"] = "Invoice party and currency must match the payment."
    if not payment.payment_reference_no or not payment.currency or (not payment.customer_id):
        errors["payment"] = "Payment reference, party, and currency are required for allocation."
    if not invoice.invoice_reference_no or not invoice.currency or (not invoice.customer_id):
        errors["invoice"] = "Invoice reference, party, and currency are required for allocation."
    others = type(allocation).objects.filter(payment=payment).exclude(pk=allocation.pk)
    for field, limit in (
        ("cash_amount", payment.amount_received),
        ("withholding_tax_amount", payment.withholding_tax_amount),
        ("discount_amount", payment.discount_taken),
    ):
        used = others.aggregate(total=Sum(field))["total"] or ZERO
        if used + getattr(allocation, field) > limit:
            errors[field] = "Allocated amount exceeds the payment amount."
    from .deductions import applied_amount
    invoice_others = (
        type(allocation)
        .objects.filter(invoice=invoice)
        .exclude(pk=allocation.pk)
        .exclude(payment__payment_status="reversed")
    )
    allocated = sum(
        (
            row.cash_amount + row.withholding_tax_amount + row.discount_amount
            for row in invoice_others
        )
    )
    if (
        allocated + applied_amount(invoice)
        + allocation.cash_amount
        + allocation.withholding_tax_amount
        + allocation.discount_amount
        > invoice.total_amount
    ):
        errors["invoice"] = "Total allocations exceed the invoice amount."
    if errors:
        raise ValidationError(errors)


def validate_invoice_allocations(invoice: CompanySalesInvoice) -> None:
    """Prevent reducing an invoice below the amounts already allocated to it."""
    if invoice.pk:
        allocations = invoice.payment_allocations.exclude(payment__payment_status="reversed")
        allocated = sum(
            (
                row.cash_amount + row.withholding_tax_amount + row.discount_amount
                for row in allocations
            ),
            ZERO,
        )
        from .deductions import applied_amount
        for deduction in invoice.deductions.all():
            if deduction.customer_id != invoice.customer_id or deduction.currency != invoice.currency:
                raise ValidationError('Invoice identity is retained by deduction evidence.')
            if deduction.applications.filter(reversal__isnull=True).exists() and invoice.invoice_status not in ('posted','disputed'):
                raise ValidationError('Reverse deductions before changing invoice posting state.')
        if allocated + applied_amount(invoice) > invoice.total_amount:
            raise ValidationError({"total_amount": "Invoice total is below its allocations."})


def settled_amount(invoice: CompanySalesInvoice) -> Decimal:
    """Total the cash, withholding tax, and discounts from cleared payments."""
    from .deductions import applied_amount
    return applied_amount(invoice) + sum(
        (
            allocation.cash_amount + allocation.withholding_tax_amount + allocation.discount_amount
            for allocation in invoice.payment_allocations.select_related("payment")
            if allocation.payment.payment_status == "cleared"
        ),
        ZERO,
    )


def validate_payment_amounts(payment: CustomerPayment) -> None:
    """Prevent reducing payment amounts below their existing allocations."""
    if not payment.pk:
        return
    if payment.payment_status != 'reversed':
        for allocation in payment.invoice_allocations.select_related('invoice'):
            allocation.payment = payment
            validate_allocation(allocation)
    for allocation_field, payment_field in (
        ("cash_amount", "amount_received"),
        ("withholding_tax_amount", "withholding_tax_amount"),
        ("discount_amount", "discount_taken"),
    ):
        allocated = (
            payment.invoice_allocations.aggregate(total=Sum(allocation_field))["total"] or ZERO
        )
        if allocated > getattr(payment, payment_field):
            raise ValidationError({payment_field: "Payment amount is below its allocations."})


def unallocated_cash(payment: CustomerPayment) -> Decimal:
    """Return the cash remaining for allocation to other invoices."""
    allocated = payment.invoice_allocations.aggregate(total=Sum("cash_amount"))["total"] or ZERO
    return max(ZERO, payment.amount_received - allocated)


def evaluate_reconciliation(case, allocations=None):
    """Read-only status, amounts and evidence-backed discrepancy findings."""
    from accounts_receivable.services.evaluation import evaluate
    return evaluate(case, validate_match, PRICE_TOLERANCE, allocations)


def calculate_reconciliation(case: Transaction) -> tuple[str, Decimal]:
    """Keep the public tuple contract; detailed findings are available to the workspace."""
    result = evaluate_reconciliation(case)
    return result["status"], result["discrepancy"]


def validate_case(case: Transaction) -> None:
    """Prevent manually marking an incomplete or discrepant case as matched."""
    if (
        case.pk
        and case.reconciliation_status == "matched"
        and (case.calculate_reconciliation()[0] != "matched")
    ):
        raise ValidationError(
            {"reconciliation_status": "The case still has unmatched or discrepant invoice lines."}
        )
