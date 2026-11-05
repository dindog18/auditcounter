"""Validation and lifecycle helpers for this document."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import CompanyPayment

from accounting_documents.services import (
    normalize_source_key, refresh_document_cases, validate_line, validate_source,
)

from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db.models import Sum

ZERO = Decimal("0")


def validate_payment_amounts(payment: CompanyPayment) -> None:
    """Prevent reducing payment amounts below their existing allocations."""
    if not payment.pk:
        return
    from accounting_documents.deductions import validate_payment_reactivation
    validate_payment_reactivation(payment)
    for allocation_field, payment_field in (
        ("cash_amount", "amount_paid"),
        ("withholding_tax_amount", "withholding_tax_amount"),
        ("discount_amount", "discount_taken"),
    ):
        allocated = (
            payment.invoice_allocations.aggregate(total=Sum(allocation_field))["total"] or ZERO
        )
        if allocated > getattr(payment, payment_field):
            raise ValidationError({payment_field: "Payment amount is below its allocations."})


def unallocated_cash(payment: CompanyPayment) -> Decimal:
    """Return the cash remaining for allocation to other invoices."""
    allocated = payment.invoice_allocations.aggregate(total=Sum("cash_amount"))["total"] or ZERO
    return max(ZERO, payment.amount_paid - allocated)
