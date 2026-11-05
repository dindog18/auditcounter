"""SupplierDeliveryReceipt and its document-specific persistence rules."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Q


from . import services

if TYPE_CHECKING:
    from accounts_payable.models import DocumentMatch, PaymentAllocation, Transaction


class SupplierDeliveryReceipt(models.Model):
    """Goods received from the supplier. Accepted quantities are recorded on its lines."""

    purchase_order = models.ForeignKey(
        "company_purchase_order.CompanyPurchaseOrder", on_delete=models.PROTECT, null=True, blank=True,
        related_name="delivery_receipts",
        help_text="Select the PO this document belongs to.",
    )

    # Django creates these IDs and reverse relations; annotations help the editor.
    if TYPE_CHECKING:
        source_table_id: int | None
        source_database_id: int | None
        source_document_id: int | None
        reconciliation_cases: models.Manager["Transaction"]
        lines: models.Manager["SupplierDeliveryReceiptLine"]
        supplier_id: int | None
        receiving_evidence_id: int | None

    class Status:
        PENDING = "pending"
        PARTIAL = "partial"
        ACCEPTED = "accepted"
        REJECTED = "rejected"
        choices = [
            (PENDING, "Pending"),
            (PARTIAL, "Partial"),
            (ACCEPTED, "Accepted"),
            (REJECTED, "Rejected"),
        ]

    supplier_delivery_receipt_no = models.AutoField(primary_key=True)
    supplier = models.ForeignKey(
        'accounts_payable.Supplier', on_delete=models.PROTECT, null=True, blank=True, related_name="delivery_receipts"
    )
    dr_reference_no = models.CharField(max_length=100, null=True, blank=True)
    delivery_date = models.DateField(null=True, blank=True)
    received_date = models.DateField(null=True, blank=True)
    received_by = models.CharField(max_length=255, blank=True)
    receiving_evidence = models.ForeignKey(
        "document_extraction.Document",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="supplier_receiving_evidence",
    )
    delivery_location = models.CharField(max_length=255, blank=True)
    receipt_status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    has_discrepancy = models.BooleanField(default=False)
    # Provenance links to the extracted file or external database record.
    source_table = models.ForeignKey(
        "db_extraction.DatabaseTable",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="accounts_payable_supplierdeliveryreceipt_records",
    )
    # External row identity, including composite keys; this is not a line-item payload.
    source_record_key = models.JSONField(default=dict, blank=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    source_llm_log = models.ForeignKey(
        "document_extraction.LLMExtractionLog",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="accounts_payable_supplierdeliveryreceipt_records",
    )
    source_text_log = models.ForeignKey(
        "document_extraction.DocExtractionLog",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="accounts_payable_supplierdeliveryreceipt_records",
    )
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)
    source_document = models.ForeignKey(
        "document_extraction.Document",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="supplier_delivery_receipts",
    )
    source_database = models.ForeignKey(
        "db_extraction.DatabaseSource",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="supplier_delivery_receipts",
    )
    # Optional receiving notes from import; matching uses the receipt line quantities.
    received_items = models.JSONField(default=list, blank=True)
    # Optional document notes and context; matching uses the structured fields and lines.
    delivery_receipt_metadata = models.TextField(blank=True)
    delivery_receipt_context = models.TextField(blank=True)

    def clean(self):
        # Validate business rules as well as individual field values.
        super().clean()
        services.validate_source(self)
        from accounting_documents.reconciliation import validate_purchase_order
        validate_purchase_order(self, "ap")

    def save(self, *args, **kwargs):
        self.source_record_key = services.normalize_source_key(self.source_record_key)
        self.full_clean()
        with transaction.atomic():
            result = super().save(*args, **kwargs)
            services.refresh_document_cases(self)
            return result

    def __str__(self):
        return f"{self.dr_reference_no} - {self.supplier}"

    class Meta:
        db_table = "accounts_payable_supplierdeliveryreceipt"
        ordering = ["-delivery_date"]
        verbose_name = "Supplier Delivery Receipt"
        verbose_name_plural = "Supplier Delivery Receipts"
        constraints = [
            models.UniqueConstraint(
                fields=["source_table", "source_record_key"],
                condition=Q(source_table__isnull=False),
                name="ap_dr_source_record_uq",
            ),
            models.UniqueConstraint(
                fields=["supplier", "dr_reference_no"], name="unique_supplier_dr_reference"
            ),
        ]


class SupplierDeliveryReceiptLine(models.Model):
    """One delivered item with stated, received, accepted, and rejected quantities."""

    # Django creates these IDs and reverse relations; annotations help the editor.
    if TYPE_CHECKING:
        matches: models.Manager["DocumentMatch"]
        delivery_receipt_id: int | None

    # A stable line number identifies the item within its parent document.
    line_no = models.PositiveIntegerField()
    item_code = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    unit_of_measure = models.CharField(max_length=30, blank=True)
    # Keep the document claim separate from what was actually received and accepted.
    quantity_stated = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    quantity_received = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    quantity_accepted = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    quantity_rejected = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    delivery_receipt = models.ForeignKey(
        'supplier_delivery_receipt.SupplierDeliveryReceipt', on_delete=models.PROTECT, related_name="lines"
    )

    def clean(self):
        # Validate business rules as well as individual field values.
        super().clean()
        services.validate_line(self)
        if self.quantity_accepted + self.quantity_rejected > self.quantity_received:
            raise ValidationError("Accepted and rejected quantities exceed the received quantity.")

    def save(self, *args, **kwargs):
        self.full_clean()
        with transaction.atomic():
            result = super().save(*args, **kwargs)
            services.refresh_document_cases(self.delivery_receipt)
            return result

    def delete(self, *args, **kwargs):
        document = self.delivery_receipt
        with transaction.atomic():
            result = super().delete(*args, **kwargs)
            services.refresh_document_cases(document)
            return result

    def __str__(self):
        return f"{self.delivery_receipt} line {self.line_no}"

    class Meta:
        db_table = "accounts_payable_supplierdeliveryreceiptline"
        ordering = ["line_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["delivery_receipt", "line_no"], name="ap_dr_line_number_uq"
            )
        ]
