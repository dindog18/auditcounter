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


class CompanySalesInvoice(models.Model):
    """Company bill payable by the customer. Allocations determine its outstanding balance."""

    reported_po_reference = models.CharField("PO reference printed on the document", max_length=100, blank=True)
    purchase_order = models.ForeignKey(
        "customer_purchase_order.CustomerPurchaseOrder", on_delete=models.PROTECT, null=True, blank=True,
        related_name="sales_invoices",
        help_text="Select the PO this document belongs to.",
    )

    # Django creates these IDs and reverse relations; annotations help the editor.
    if TYPE_CHECKING:
        source_table_id: int | None
        source_database_id: int | None
        source_document_id: int | None
        reconciliation_cases: models.Manager["Transaction"]
        lines: models.Manager["CompanySalesInvoiceLine"]
        payment_allocations: models.Manager["PaymentAllocation"]
        customer_id: int | None

    class PaymentStatus:
        UNPAID = "unpaid"
        PARTIALLY_PAID = "partially_paid"
        PAID = "paid"
        choices = [(UNPAID, "Unpaid"), (PARTIALLY_PAID, "Partially paid"), (PAID, "Paid")]

    class InvoiceStatus:
        DRAFT = "draft"
        POSTED = "posted"
        VOID = "void"
        choices = [(DRAFT, "Draft"), (POSTED, "Posted"), (VOID, "Void")]

    company_sales_invoice_no = models.AutoField(primary_key=True)
    customer = models.ForeignKey(
        'accounts_receivable.Customer', on_delete=models.PROTECT, null=True, blank=True, related_name="sales_invoices"
    )
    invoice_reference_no = models.CharField(max_length=100, null=True, blank=True)
    invoice_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    currency = models.CharField(
        max_length=3,
        blank=True,
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
    payment_status = models.CharField(
        max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID
    )
    invoice_status = models.CharField(
        max_length=20, choices=InvoiceStatus.choices, default=InvoiceStatus.DRAFT
    )
    notes = models.TextField(blank=True)
    # Provenance links to the extracted file or external database record.
    source_table = models.ForeignKey(
        "db_extraction.DatabaseTable",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="accounts_receivable_companysalesinvoice_records",
    )
    # External row identity, including composite keys; this is not a line-item payload.
    source_record_key = models.JSONField(default=dict, blank=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    source_llm_log = models.ForeignKey(
        "document_extraction.LLMExtractionLog",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="accounts_receivable_companysalesinvoice_records",
    )
    source_text_log = models.ForeignKey(
        "document_extraction.DocExtractionLog",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="accounts_receivable_companysalesinvoice_records",
    )
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)
    source_document = models.ForeignKey(
        "document_extraction.Document",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="company_sales_invoices",
    )
    source_database = models.ForeignKey(
        "db_extraction.DatabaseSource",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="company_sales_invoices",
    )
    # Optional document notes and context; matching uses the structured fields and lines.
    invoice_metadata = models.TextField(blank=True)
    invoice_context = models.TextField(blank=True)

    def clean(self):
        # Validate business rules as well as individual field values.
        super().clean()
        services.validate_source(self)
        from accounting_documents.reconciliation import validate_purchase_order
        validate_purchase_order(self, "ar")
        services.validate_invoice_allocations(self)

    def save(self, *args, **kwargs):
        with transaction.atomic():
            # Serialize deduction limits, invoice changes and restored payments.
            if self.customer_id:
                self._meta.get_field('customer').remote_field.model.objects.select_for_update().get(pk=self.customer_id)
            if self.pk:
                type(self).objects.select_for_update().filter(pk=self.pk).first()
            self.source_record_key = services.normalize_source_key(self.source_record_key)
            self.full_clean()
            result = super().save(*args, **kwargs)
            services.refresh_document_cases(self)
            self.refresh_payment_status()
            return result

    @property
    def settled_amount(self) -> Decimal:
        return services.settled_amount(self)

    @property
    def deduction_amount(self) -> Decimal:
        from accounting_documents.deductions import invoice_deductions
        return invoice_deductions(self)

    @property
    def net_amount(self) -> Decimal:
        return self.total_amount - self.deduction_amount

    @property
    def outstanding_balance(self) -> Decimal:
        return max(Decimal("0"), self.net_amount - self.settled_amount)

    def refresh_payment_status(self):
        # Keep the stored payment status in step with cleared allocations.
        settled = self.settled_amount
        if (self.total_amount > Decimal("0") and settled >= self.net_amount):
            status = "paid"
        elif settled > Decimal("0"):
            status = "partially_paid"
        else:
            status = "unpaid"
        type(self).objects.filter(pk=self.pk).update(payment_status=status)
        self.payment_status = status

    def __str__(self):
        return f"{self.invoice_reference_no} - {self.customer}"

    class Meta:
        db_table = "accounts_receivable_companysalesinvoice"
        ordering = ["-invoice_date"]
        verbose_name = "Company Sales Invoice"
        verbose_name_plural = "Company Sales Invoices"
        constraints = [
            models.UniqueConstraint(
                fields=["source_table", "source_record_key"],
                condition=Q(source_table__isnull=False),
                name="ar_invoice_source_record_uq",
            ),
            models.UniqueConstraint(
                fields=["customer", "invoice_reference_no"],
                name="unique_customer_invoice_reference",
            ),
        ]


class CompanySalesInvoiceLine(models.Model):
    """One billed item whose quantity and price are compared with order and receipt lines."""

    # Django creates these IDs and reverse relations; annotations help the editor.
    if TYPE_CHECKING:
        matches: models.Manager["DocumentMatch"]
        invoice_id: int | None

    # A stable line number identifies the item within its parent document.
    line_no = models.PositiveIntegerField()
    item_code = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    unit_of_measure = models.CharField(max_length=30, blank=True)
    quantity_invoiced = models.DecimalField(
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
    invoice = models.ForeignKey('company_sales_invoice.CompanySalesInvoice', on_delete=models.PROTECT, related_name="lines")

    def clean(self):
        # Validate business rules as well as individual field values.
        super().clean()
        services.validate_line(self)

    def save(self, *args, **kwargs):
        self.full_clean()
        with transaction.atomic():
            result = super().save(*args, **kwargs)
            services.refresh_document_cases(self.invoice)
            return result

    def delete(self, *args, **kwargs):
        document = self.invoice
        with transaction.atomic():
            result = super().delete(*args, **kwargs)
            services.refresh_document_cases(document)
            return result

    def __str__(self):
        return f"{self.invoice} line {self.line_no}"

    class Meta:
        db_table = "accounts_receivable_companysalesinvoiceline"
        ordering = ["line_no"]
        constraints = [
            models.UniqueConstraint(fields=["invoice", "line_no"], name="ar_invoice_line_number_uq")
        ]
