"""Simple Django models for AR document matching and payment allocation."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models, transaction
from django.db.models import Q

from document_extraction.models import LLMRunStatus

from . import services


# Compatibility imports for existing integrations; ownership lives in document apps.
from customer_purchase_order.models import CustomerPurchaseOrder, CustomerPurchaseOrderLine
from company_delivery_receipt.models import CompanyDeliveryReceipt, CompanyDeliveryReceiptLine
from company_sales_invoice.models import CompanySalesInvoice, CompanySalesInvoiceLine
from customer_payment.models import CustomerPayment


class Customer(models.Model):
    """Customer identity, contact information, credit limit, and payment terms."""

    customer_no = models.AutoField(primary_key=True)
    customer_code = models.CharField(max_length=50, unique=True)
    customer_name = models.CharField(max_length=255)
    tax_identification_no = models.CharField(max_length=30, blank=True)
    billing_address = models.TextField(blank=True)
    shipping_address = models.TextField(blank=True)
    contact_person = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    credit_limit = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    payment_terms_days = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    llm_context = models.TextField(blank=True)

    def __str__(self):
        return f"{self.customer_code} - {self.customer_name}"

    class Meta:
        ordering = ["customer_name"]
        verbose_name = "Customer"
        verbose_name_plural = "Customers"


class Transaction(models.Model):
    """One AR reconciliation case grouping orders, receipts, and invoices for the same customer and currency."""

    # Django creates these IDs and reverse relations; annotations help the editor.
    if TYPE_CHECKING:
        customer_id: int | None
        line_matches: models.Manager["DocumentMatch"]

    class Status:
        PENDING = "pending"
        MATCHED = "matched"
        PARTIAL = "partial"
        EXCEPTION = "exception"
        choices = [
            (PENDING, "Pending"),
            (MATCHED, "Matched"),
            (PARTIAL, "Partial"),
            (EXCEPTION, "Exception"),
        ]

    transaction_no = models.AutoField(primary_key=True)
    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, null=True, blank=True, related_name="transactions"
    )
    transaction_date = models.DateField(null=True, blank=True)
    currency = models.CharField(
        max_length=3,
        blank=True,
        validators=[
            RegexValidator(regex="^[A-Z]{3}$", message="Use a three-letter ISO currency code.")
        ],
    )
    reconciliation_status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    total_discrepancy_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    reconciled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)
    notes = models.TextField(blank=True)
    # A case can include split deliveries, multiple orders, and multiple invoices.
    purchase_orders = models.ManyToManyField(
        CustomerPurchaseOrder, blank=True, related_name="reconciliation_cases"
    )
    delivery_receipts = models.ManyToManyField(
        CompanyDeliveryReceipt, blank=True, related_name="reconciliation_cases"
    )
    sales_invoices = models.ManyToManyField(
        CompanySalesInvoice, blank=True, related_name="reconciliation_cases"
    )

    def calculate_reconciliation(self) -> tuple[str, Decimal]:
        return services.calculate_reconciliation(self)

    def refresh_reconciliation_status(self):
        # Store the result calculated from current documents and line matches.
        if not self.pk:
            return
        status, discrepancy = self.calculate_reconciliation()
        type(self).objects.filter(pk=self.pk).update(
            reconciliation_status=status, total_discrepancy_amount=discrepancy
        )
        self.reconciliation_status = status
        self.total_discrepancy_amount = discrepancy

    def clean(self):
        # Validate business rules as well as individual field values.
        super().clean()
        services.validate_case(self)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"AR transaction {self.transaction_no} - {self.customer}"

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "AR Transaction"
        verbose_name_plural = "AR Transactions"


class DocumentMatch(models.Model):
    """Links a portion of an invoice line to an order line and an accepted receipt line."""

    # Django creates these IDs and reverse relations; annotations help the editor.
    if TYPE_CHECKING:
        transaction_id: int | None
        purchase_order_line_id: int | None
        delivery_receipt_line_id: int | None
        invoice_line_id: int | None

    class Status:
        PENDING = "pending"
        MATCHED = "matched"
        EXCEPTION = "exception"
        choices = [(PENDING, "Pending"), (MATCHED, "Matched"), (EXCEPTION, "Exception")]

    # A partial quantity allows one order or receipt line to cover several invoice lines.
    matched_quantity = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    match_status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    transaction = models.ForeignKey(
        Transaction, on_delete=models.PROTECT, related_name="line_matches"
    )
    purchase_order_line = models.ForeignKey(
        CustomerPurchaseOrderLine,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="matches",
    )
    delivery_receipt_line = models.ForeignKey(
        CompanyDeliveryReceiptLine,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="matches",
    )
    invoice_line = models.ForeignKey(
        CompanySalesInvoiceLine, on_delete=models.PROTECT, related_name="matches"
    )

    def clean(self):
        # Validate business rules as well as individual field values.
        super().clean()
        services.validate_match(self)

    def save(self, *args, **kwargs):
        # Lock the affected rows so concurrent matches or allocations cannot reuse them.
        with transaction.atomic():
            if self.invoice_line_id:
                CompanySalesInvoiceLine.objects.select_for_update().get(pk=self.invoice_line_id)
            if self.purchase_order_line_id:
                CustomerPurchaseOrderLine.objects.select_for_update().get(
                    pk=self.purchase_order_line_id
                )
            if self.delivery_receipt_line_id:
                CompanyDeliveryReceiptLine.objects.select_for_update().get(
                    pk=self.delivery_receipt_line_id
                )
            self.full_clean()
            result = super().save(*args, **kwargs)
            self.transaction.refresh_reconciliation_status()
            return result

    def delete(self, *args, **kwargs):
        case = self.transaction
        with transaction.atomic():
            result = super().delete(*args, **kwargs)
            case.refresh_reconciliation_status()
            return result

    def __str__(self):
        return f"AR match {self.pk} for invoice line {self.invoice_line_id}"

    class Meta:
        ordering = ["-created_at"]


class PaymentAllocation(models.Model):
    """Applies cash, withholding tax, and discounts from one payment to one invoice."""

    # Django creates these IDs and reverse relations; annotations help the editor.
    if TYPE_CHECKING:
        payment_id: int | None
        invoice_id: int | None
    # Cash, withholding tax, and discounts together settle the invoice amount.
    cash_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    withholding_tax_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    discount_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    payment = models.ForeignKey(
        CustomerPayment, on_delete=models.PROTECT, related_name="invoice_allocations"
    )
    invoice = models.ForeignKey(
        CompanySalesInvoice, on_delete=models.PROTECT, related_name="payment_allocations"
    )

    def clean(self):
        # Validate business rules as well as individual field values.
        super().clean()
        services.validate_allocation(self)

    def save(self, *args, **kwargs):
        # Lock the affected rows so concurrent matches or allocations cannot reuse them.
        with transaction.atomic():
            if self.payment_id:
                CustomerPayment.objects.select_for_update().get(pk=self.payment_id)
            if self.invoice_id:
                CompanySalesInvoice.objects.select_for_update().get(pk=self.invoice_id)
            old_invoice_id = None
            if self.pk:
                old_invoice_id = (
                    type(self)
                    .objects.filter(pk=self.pk)
                    .values_list("invoice_id", flat=True)
                    .first()
                )
            self.full_clean()
            result = super().save(*args, **kwargs)
            self.invoice.refresh_payment_status()
            if old_invoice_id and old_invoice_id != self.invoice_id:
                CompanySalesInvoice.objects.get(pk=old_invoice_id).refresh_payment_status()
            return result

    def delete(self, *args, **kwargs):
        invoice = self.invoice
        with transaction.atomic():
            result = super().delete(*args, **kwargs)
            invoice.refresh_payment_status()
            return result

    def __str__(self):
        return f"{self.payment} → {self.invoice}"

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["payment", "invoice"], name="ar_payment_invoice_uq")
        ]


class ExtractionConfiguration(models.Model):
    """User-reviewed instructions for entering one kind of accounting record.

    A profile describes either database mapping or document extraction, scoped
    to the module or an existing Customer. It never imports or encodes a record
    by itself. Drafts are saved through the workspace; only explicitly submitted snapshots
    are used by extraction.
    Existing per-record context/provenance fields retain their current meaning.
    """

    class TargetEntity(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        PURCHASE_ORDER = "purchase_order", "Purchase order"
        DELIVERY_RECEIPT = "delivery_receipt", "Delivery receipt"
        SALES_INVOICE = "sales_invoice", "Sales invoice"
        PAYMENT = "payment", "Payment"
        DEDUCTION = "deduction", "Deduction"

    class SourceType(models.TextChoices):
        DATABASE = "database", "Database extraction"
        DOCUMENT = "document", "Document extraction"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted by user"

    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    target_entity = models.CharField(max_length=30, choices=TargetEntity.choices)
    source_type = models.CharField(max_length=20, choices=SourceType.choices)
    customer = models.ForeignKey(
        "Customer", on_delete=models.PROTECT, null=True, blank=True,
        related_name="extraction_configurations",
        help_text="Blank applies module-wide; otherwise use this account's layout or mapping.",
    )

    # Schema metadata identifies external fields; no credentials or SQL are stored.
    database_source = models.ForeignKey(
        "db_extraction.DatabaseSource", on_delete=models.PROTECT, null=True,
        blank=True, related_name="ar_extraction_configurations",
    )
    source_table = models.ForeignKey(
        "db_extraction.DatabaseTable", on_delete=models.PROTECT, null=True,
        blank=True, related_name="ar_header_configurations",
    )
    line_source_table = models.ForeignKey(
        "db_extraction.DatabaseTable", on_delete=models.PROTECT, null=True,
        blank=True, related_name="ar_line_configurations",
    )
    source_schema_snapshot = models.JSONField(
        default=dict, blank=True,
        help_text="Connection/table labels and inspected columns at configuration time; not business rows.",
    )
    source_key_fields = models.JSONField(
        default=list, blank=True, help_text="External header key column names, including composite keys.",
    )
    # {target_field: {source: column_name, transform: name, default: value}}
    field_mappings = models.JSONField(default=dict, blank=True)
    line_item_mappings = models.JSONField(default=dict, blank=True)
    # [{header_column: 'id', line_column: 'invoice_id'}]
    line_join_fields = models.JSONField(default=list, blank=True)
    # Resolve external account codes to local records instead of copying raw IDs.
    relation_lookups = models.JSONField(
        default=dict, blank=True,
        help_text="Target relation, matching account field, and missing-account review policy.",
    )

    document_type = models.CharField(max_length=100, blank=True)
    extraction_context = models.TextField(blank=True)
    field_instructions = models.JSONField(
        default=dict, blank=True, help_text="Instructions keyed by destination model field name.",
    )
    line_field_instructions = models.JSONField(
        default=dict, blank=True, help_text="Line-field guidance, separate from identically named header fields.",
    )
    line_item_context = models.TextField(blank=True)
    sample_text = models.TextField(blank=True, help_text="Optional user-supplied example for assisted configuration.")
    # Dates, decimal separators, default currency, required fields and duplicates.
    encoding_rules = models.JSONField(default=dict, blank=True)

    # Record-first source choices, annotations and structured query; never executable SQL.
    setup_data = models.JSONField(default=dict, blank=True)

    # Assistant output is a proposal. Only a later explicit user submission may
    # set submitted_at/by and capture the exact reviewed configuration snapshot.
    assistant_messages = models.JSONField(default=list, blank=True)
    assistant_proposal = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    revision = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    submitted_snapshot = models.JSONField(default=dict, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ar_submitted_extraction_configurations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["target_entity", "name", "pk"]
        verbose_name = "AR extraction configuration"
        verbose_name_plural = "AR extraction configurations"

    def __str__(self):
        return f"{self.name} ({self.get_target_entity_display()} · {self.get_source_type_display()})"


class LLMExtractionLog(models.Model):
    """One accounting LLM attempt, including its original input and output.

    Existing source_llm_log fields still identify document-extraction evidence.
    This history covers accounting extraction and configuration assistance.
    Attempts preserve provider inputs, outputs, errors, and the configuration
    snapshot used to create the accounting record.
    """

    class Purpose(models.TextChoices):
        EXTRACTION = "extraction", "Record extraction"
        CONFIGURATION = "configuration", "Configuration assistance"

    llm_log_no = models.AutoField(primary_key=True)
    configuration = models.ForeignKey(
        "ExtractionConfiguration", on_delete=models.SET_NULL, null=True,
        blank=True, related_name="llm_logs",
    )
    routing_route = models.ForeignKey(
        "router.DocumentRoute", on_delete=models.PROTECT, null=True, blank=True,
        related_name="ar_extraction_logs",
    )
    configuration_revision = models.PositiveIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1)],
    )
    target_entity = models.CharField(max_length=30, choices=ExtractionConfiguration.TargetEntity.choices)
    source_type = models.CharField(max_length=20, choices=ExtractionConfiguration.SourceType.choices)
    purpose = models.CharField(max_length=20, choices=Purpose.choices, default=Purpose.EXTRACTION)
    # Optional destination links allow attempts before a record exists.
    customer = models.ForeignKey(
        "Customer", on_delete=models.PROTECT, null=True, blank=True, related_name="llm_logs",
    )
    purchase_order = models.ForeignKey(
        "customer_purchase_order.CustomerPurchaseOrder", on_delete=models.PROTECT, null=True, blank=True, related_name="llm_logs",
    )
    delivery_receipt = models.ForeignKey(
        "company_delivery_receipt.CompanyDeliveryReceipt", on_delete=models.PROTECT, null=True, blank=True, related_name="llm_logs",
    )
    sales_invoice = models.ForeignKey(
        "company_sales_invoice.CompanySalesInvoice", on_delete=models.PROTECT, null=True, blank=True, related_name="llm_logs",
    )
    payment = models.ForeignKey(
        "customer_payment.CustomerPayment", on_delete=models.PROTECT, null=True, blank=True, related_name="llm_logs",
    )
    deduction = models.ForeignKey(
        "ar_deduction.Deduction", on_delete=models.SET_NULL, null=True, blank=True, related_name="llm_logs",
    )
    fk_document_no = models.ForeignKey(
        "document_extraction.Document", on_delete=models.PROTECT, null=True,
        blank=True, related_name="ar_llm_logs",
    )
    source_llm_log = models.ForeignKey(
        "document_extraction.LLMExtractionLog", on_delete=models.PROTECT,
        null=True, blank=True, related_name="ar_accounting_logs",
    )
    provider = models.CharField(max_length=100, null=True, blank=True)
    model_name = models.CharField(max_length=150, null=True, blank=True)
    status = models.CharField(max_length=20, choices=LLMRunStatus.choices, default=LLMRunStatus.QUEUED)
    # Snapshots preserve the context used by this attempt, even if the draft changes.
    configuration_snapshot = models.JSONField(default=dict, blank=True)
    request_payload = models.JSONField(default=dict, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)
    markdown_text = models.TextField(null=True, blank=True)
    input_tokens = models.PositiveIntegerField(null=True, blank=True)
    output_tokens = models.PositiveIntegerField(null=True, blank=True)
    processing_time_ms = models.PositiveIntegerField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    is_simulated = models.BooleanField(default=False)
    # Accuracy review is independent of applying changes or submitting a profile.
    user_selected_accurate = models.BooleanField(default=False)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ar_reviewed_llm_logs",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-llm_log_no"]
        indexes = [
            models.Index(fields=["status", "-created_at"], name="ar_llm_status_created"),
            models.Index(fields=["configuration", "-created_at"], name="ar_llm_config_created"),
        ]
        verbose_name = "AR LLM extraction log"

    def __str__(self):
        return f"AR LLM #{self.llm_log_no} · {self.get_status_display()}"


class DatabaseImportRun(models.Model):
    """Audit history for committed database migrations, updates and legacy imports."""

    configuration = models.ForeignKey(ExtractionConfiguration, on_delete=models.SET_NULL, null=True, blank=True, related_name="import_runs")
    request_id = models.UUIDField(unique=True)
    configuration_snapshot = models.JSONField(default=dict)
    status = models.CharField(max_length=20, default="processing")
    result = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
