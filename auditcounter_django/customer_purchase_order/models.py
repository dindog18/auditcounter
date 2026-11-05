"""Document models and persistence rules owned by this app."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from django.core.validators import MinValueValidator, RegexValidator
from django.db import models, transaction
from django.db.models import Q


from . import services

if TYPE_CHECKING:
    from accounts_receivable.models import DocumentMatch, PaymentAllocation, Transaction


class CustomerPurchaseOrder(models.Model):
    """Customer order received by the company. Its lines describe the agreed quantities and prices."""

    # Django creates these IDs and reverse relations; annotations help the editor.
    if TYPE_CHECKING:
        source_table_id: int | None
        source_database_id: int | None
        source_document_id: int | None
        reconciliation_cases: models.Manager["Transaction"]
        lines: models.Manager["CustomerPurchaseOrderLine"]
        customer_id: int | None

    class Status:
        DRAFT = "draft"
        OPEN = "open"
        CANCELLED = "cancelled"
        CLOSED = "closed"
        choices = [(DRAFT, "Draft"), (OPEN, "Open"), (CANCELLED, "Cancelled"), (CLOSED, "Closed")]

    customer_purchase_order_no = models.AutoField(primary_key=True)
    customer = models.ForeignKey(
        'accounts_receivable.Customer', on_delete=models.PROTECT, related_name="purchase_orders"
    )
    po_reference_no = models.CharField(max_length=100)
    order_date = models.DateField()
    expected_delivery_date = models.DateField(null=True, blank=True)
    currency = models.CharField(
        max_length=3,
        validators=[
            RegexValidator(regex="^[A-Z]{3}$", message="Use a three-letter ISO currency code.")
        ],
    )
    subtotal = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    discount_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    tax_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    total_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    # Provenance links to the extracted file or external database record.
    source_table = models.ForeignKey(
        "db_extraction.DatabaseTable",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="accounts_receivable_customerpurchaseorder_records",
    )
    # External row identity, including composite keys; this is not a line-item payload.
    source_record_key = models.JSONField(default=dict, blank=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    source_llm_log = models.ForeignKey(
        "document_extraction.LLMExtractionLog",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="accounts_receivable_customerpurchaseorder_records",
    )
    source_text_log = models.ForeignKey(
        "document_extraction.DocExtractionLog",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="accounts_receivable_customerpurchaseorder_records",
    )
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)
    source_document = models.ForeignKey(
        "document_extraction.Document",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="customer_purchase_orders",
    )
    source_database = models.ForeignKey(
        "db_extraction.DatabaseSource",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="customer_purchase_orders",
    )
    # Optional document notes and context; matching uses the structured fields and lines.
    purchase_order_metadata = models.TextField(blank=True)
    purchase_order_context = models.TextField(blank=True)

    def clean(self):
        # Validate business rules as well as individual field values.
        super().clean()
        services.validate_source(self)
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            key = 'supplier_id' if hasattr(self, 'supplier_id') else 'customer_id'
            if (getattr(previous, key) != getattr(self, key) or previous.currency != self.currency) and (
                self.delivery_receipts.exists() or self.sales_invoices.exists() or self.deductions.exists()
            ):
                from django.core.exceptions import ValidationError
                raise ValidationError('Remove linked documents and deductions before changing the PO account or currency.')

    def save(self, *args, **kwargs):
        self.source_record_key = services.normalize_source_key(self.source_record_key)
        self.full_clean()
        with transaction.atomic():
            result = super().save(*args, **kwargs)
            services.refresh_document_cases(self)
            return result

    def __str__(self):
        return f"{self.po_reference_no} - {self.customer}"

    class Meta:
        db_table = "accounts_receivable_customerpurchaseorder"
        ordering = ["-order_date"]
        verbose_name = "Customer Purchase Order"
        verbose_name_plural = "Customer Purchase Orders"
        constraints = [
            models.UniqueConstraint(
                fields=["source_table", "source_record_key"],
                condition=Q(source_table__isnull=False),
                name="ar_po_source_record_uq",
            ),
            models.UniqueConstraint(
                fields=["customer", "po_reference_no"], name="unique_customer_po_reference"
            ),
        ]


class CustomerPurchaseOrderLine(models.Model):
    """One ordered item: its quantity, unit price, discount, tax, and total."""

    # Django creates these IDs and reverse relations; annotations help the editor.
    if TYPE_CHECKING:
        matches: models.Manager["DocumentMatch"]
        purchase_order_id: int | None

    # A stable line number identifies the item within its parent document.
    line_no = models.PositiveIntegerField()
    item_code = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    unit_of_measure = models.CharField(max_length=30, blank=True)
    quantity_ordered = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    unit_price = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    discount_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    tax_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    line_total = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    purchase_order = models.ForeignKey(
        'customer_purchase_order.CustomerPurchaseOrder', on_delete=models.PROTECT, related_name="lines"
    )

    def clean(self):
        # Validate business rules as well as individual field values.
        super().clean()
        services.validate_line(self)

    def save(self, *args, **kwargs):
        self.full_clean()
        with transaction.atomic():
            result = super().save(*args, **kwargs)
            services.refresh_document_cases(self.purchase_order)
            return result

    def delete(self, *args, **kwargs):
        document = self.purchase_order
        with transaction.atomic():
            result = super().delete(*args, **kwargs)
            services.refresh_document_cases(document)
            return result

    def __str__(self):
        return f"{self.purchase_order} line {self.line_no}"

    class Meta:
        db_table = "accounts_receivable_customerpurchaseorderline"
        ordering = ["line_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["purchase_order", "line_no"], name="ar_po_line_number_uq"
            )
        ]
