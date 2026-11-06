"""Validation and lifecycle helpers for this document."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import CompanySalesInvoice

from accounting_documents.services import (
    normalize_source_key, refresh_document_cases, validate_line, validate_source,
)

from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db.models import Sum

ZERO = Decimal("0")


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
        if allocated > invoice.net_amount:
            raise ValidationError({"total_amount": "Invoice total is below its allocations."})


def settled_amount(invoice: CompanySalesInvoice) -> Decimal:
    """Total the cash, withholding tax, and discounts from cleared payments."""
    return sum(
        (
            allocation.cash_amount + allocation.withholding_tax_amount + allocation.discount_amount
            for allocation in invoice.payment_allocations.select_related("payment")
            if allocation.payment.payment_status == "cleared"
        ),
        ZERO,
    )
