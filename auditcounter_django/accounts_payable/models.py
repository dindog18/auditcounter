"""Simple Django models for AP document matching and payment allocation."""

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


class Supplier(models.Model):
    """Supplier identity, contact information, and payment terms."""

    supplier_no = models.AutoField(primary_key=True)
    supplier_code = models.CharField(max_length=50, unique=True)
    supplier_name = models.CharField(max_length=255)
    tax_identification_no = models.CharField(max_length=30, blank=True)
    billing_address = models.TextField(blank=True)
    contact_person = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    payment_terms_days = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    llm_context = models.TextField(blank=True)

    def __str__(self):
        return f"{self.supplier_code} - {self.supplier_name}"

    class Meta:
        ordering = ["supplier_name"]
        verbose_name = "Supplier"
        verbose_name_plural = "Suppliers"


class CompanyPurchaseOrder(models.Model):
    """Company order sent to a supplier. Its lines describe the agreed quantities and prices."""

    # Django creates these IDs and reverse relations; annotations help the editor.
    if TYPE_CHECKING:
        source_table_id: int | None
        source_database_id: int | None
        source_document_id: int | None
        reconciliation_cases: models.Manager["Transaction"]
        lines: models.Manager["CompanyPurchaseOrderLine"]
        supplier_id: int | None

    class Status:
        DRAFT = "draft"
        OPEN = "open"
        CANCELLED = "cancelled"
        CLOSED = "closed"
        choices = [(DRAFT, "Draft"), (OPEN, "Open"), (CANCELLED, "Cancelled"), (CLOSED, "Closed")]

    company_purchase_order = models.AutoField(primary_key=True)
    supplier = models.ForeignKey(
        "Supplier", on_delete=models.PROTECT, related_name="purchase_orders"
    )
    po_reference_no = models.CharField(max_length=100, unique=True)
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
    other_charges = models.DecimalField(
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
        related_name="%(app_label)s_%(class)s_records",
    )
    # External row identity, including composite keys; this is not a line-item payload.
    source_record_key = models.JSONField(default=dict, blank=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    source_llm_log = models.ForeignKey(
        "document_extraction.LLMExtractionLog",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_records",
    )
    source_text_log = models.ForeignKey(
        "document_extraction.DocExtractionLog",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_records",
    )
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)
    source_document = models.ForeignKey(
        "document_extraction.Document",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="company_purchase_orders",
    )
    source_database = models.ForeignKey(
        "db_extraction.DatabaseSource",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="company_purchase_orders",
    )
    # Optional document notes and context; matching uses the structured fields and lines.
    purchase_order_metadata = models.TextField(blank=True)
    purchase_order_context = models.TextField(blank=True)

    def clean(self):
        # Validate business rules as well as individual field values.
        super().clean()
        services.validate_source(self)

    def save(self, *args, **kwargs):
        self.source_record_key = services.normalize_source_key(self.source_record_key)
        self.full_clean()
        with transaction.atomic():
            result = super().save(*args, **kwargs)
            services.refresh_document_cases(self)
            return result

    def __str__(self):
        return f"{self.po_reference_no} - {self.supplier}"

    class Meta:
        ordering = ["-order_date"]
        verbose_name = "Company Purchase Order"
        verbose_name_plural = "Company Purchase Orders"
        constraints = [
            models.UniqueConstraint(
                fields=["source_table", "source_record_key"],
                condition=Q(source_table__isnull=False),
                name="ap_po_source_record_uq",
            )
        ]


class SupplierDeliveryReceipt(models.Model):
    """Goods received from the supplier. Accepted quantities are recorded on its lines."""

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
        Supplier, on_delete=models.PROTECT, null=True, blank=True, related_name="delivery_receipts"
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
        related_name="%(app_label)s_%(class)s_records",
    )
    # External row identity, including composite keys; this is not a line-item payload.
    source_record_key = models.JSONField(default=dict, blank=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    source_llm_log = models.ForeignKey(
        "document_extraction.LLMExtractionLog",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_records",
    )
    source_text_log = models.ForeignKey(
        "document_extraction.DocExtractionLog",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_records",
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


class SupplierSalesInvoice(models.Model):
    """Supplier bill payable by the company. Allocations determine its outstanding balance."""

    # Django creates these IDs and reverse relations; annotations help the editor.
    if TYPE_CHECKING:
        source_table_id: int | None
        source_database_id: int | None
        source_document_id: int | None
        reconciliation_cases: models.Manager["Transaction"]
        lines: models.Manager["SupplierSalesInvoiceLine"]
        payment_allocations: models.Manager["PaymentAllocation"]
        supplier_id: int | None

    class InvoiceStatus:
        PENDING = "pending"
        POSTED = "posted"
        DISPUTED = "disputed"
        VOID = "void"
        choices = [(PENDING, "Pending"), (POSTED, "Posted"), (DISPUTED, "Disputed"), (VOID, "Void")]

    class PaymentStatus:
        UNPAID = "unpaid"
        PARTIALLY_PAID = "partially_paid"
        PAID = "paid"
        choices = [(UNPAID, "Unpaid"), (PARTIALLY_PAID, "Partially paid"), (PAID, "Paid")]

    supplier_sales_invoice_no = models.AutoField(primary_key=True)
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, null=True, blank=True, related_name="sales_invoices"
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
    other_charges = models.DecimalField(
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
    invoice_status = models.CharField(
        max_length=20, choices=InvoiceStatus.choices, default=InvoiceStatus.PENDING
    )
    payment_status = models.CharField(
        max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID
    )
    notes = models.TextField(blank=True)
    # Provenance links to the extracted file or external database record.
    source_table = models.ForeignKey(
        "db_extraction.DatabaseTable",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_records",
    )
    # External row identity, including composite keys; this is not a line-item payload.
    source_record_key = models.JSONField(default=dict, blank=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    source_llm_log = models.ForeignKey(
        "document_extraction.LLMExtractionLog",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_records",
    )
    source_text_log = models.ForeignKey(
        "document_extraction.DocExtractionLog",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_records",
    )
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)
    source_document = models.ForeignKey(
        "document_extraction.Document",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="supplier_sales_invoices",
    )
    source_database = models.ForeignKey(
        "db_extraction.DatabaseSource",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="supplier_sales_invoices",
    )
    # Optional document notes and context; matching uses the structured fields and lines.
    invoice_metadata = models.TextField(blank=True)
    invoice_context = models.TextField(blank=True)

    def clean(self):
        # Validate business rules as well as individual field values.
        super().clean()
        services.validate_source(self)
        services.validate_invoice_allocations(self)

    def save(self, *args, **kwargs):
        self.source_record_key = services.normalize_source_key(self.source_record_key)
        with transaction.atomic():
            from discrepancies.services.timeline import lock_account
            lock_account(self)
            self.full_clean()
            result = super().save(*args, **kwargs)
            services.refresh_document_cases(self)
            return result

    @property
    def settled_amount(self) -> Decimal:
        return services.settled_amount(self)

    @property
    def outstanding_balance(self) -> Decimal:
        return max(Decimal("0"), self.total_amount - self.settled_amount)

    @transaction.atomic
    def refresh_payment_status(self):
        from discrepancies.services.timeline import lock_account
        lock_account(self)
        # Keep the stored payment status in step with cleared allocations.
        settled = self.settled_amount
        if settled >= self.total_amount > Decimal("0"):
            status = "paid"
        elif settled > Decimal("0"):
            status = "partially_paid"
        else:
            status = "unpaid"
        type(self).objects.filter(pk=self.pk).update(payment_status=status)
        self.payment_status = status
        from discrepancies.services.timeline import observe_invoice_cases
        for linked_case in self.reconciliation_cases.order_by("pk"):
            observe_invoice_cases(linked_case)

    def __str__(self):
        return f"{self.invoice_reference_no} - {self.supplier}"

    class Meta:
        ordering = ["-invoice_date"]
        verbose_name = "Supplier Sales Invoice"
        verbose_name_plural = "Supplier Sales Invoices"
        constraints = [
            models.UniqueConstraint(
                fields=["source_table", "source_record_key"],
                condition=Q(source_table__isnull=False),
                name="ap_invoice_source_record_uq",
            ),
            models.UniqueConstraint(
                fields=["supplier", "invoice_reference_no"],
                name="unique_supplier_invoice_reference",
            ),
        ]


class CompanyPayment(models.Model):
    """Money paid to a supplier. One payment may settle several invoices."""

    # Django creates these IDs and reverse relations; annotations help the editor.
    if TYPE_CHECKING:
        source_table_id: int | None
        source_database_id: int | None
        source_document_id: int | None
        invoice_allocations: models.Manager["PaymentAllocation"]
        supplier_id: int | None
        proof_of_payment_id: int | None

    class Status:
        PENDING = "pending"
        CLEARED = "cleared"
        REVERSED = "reversed"
        choices = [(PENDING, "Pending"), (CLEARED, "Cleared"), (REVERSED, "Reversed")]

    company_payment_no = models.AutoField(primary_key=True)
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, null=True, blank=True, related_name="payments"
    )
    payment_reference_no = models.CharField(max_length=100, null=True, blank=True)
    payment_date = models.DateField(null=True, blank=True)
    posting_date = models.DateField(null=True, blank=True)
    payment_method = models.CharField(max_length=50, blank=True)
    bank_reference_no = models.CharField(max_length=100, blank=True)
    currency = models.CharField(
        max_length=3,
        blank=True,
        validators=[
            RegexValidator(regex="^[A-Z]{3}$", message="Use a three-letter ISO currency code.")
        ],
    )
    amount_paid = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    withholding_tax_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    discount_taken = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    payment_status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    cleared_at = models.DateTimeField(null=True, blank=True)
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversal_reason = models.TextField(blank=True)
    proof_of_payment = models.ForeignKey(
        "document_extraction.Document",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="company_payment_proofs",
    )
    # Provenance links to the extracted file or external database record.
    source_table = models.ForeignKey(
        "db_extraction.DatabaseTable",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_records",
    )
    # External row identity, including composite keys; this is not a line-item payload.
    source_record_key = models.JSONField(default=dict, blank=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    source_llm_log = models.ForeignKey(
        "document_extraction.LLMExtractionLog",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_records",
    )
    source_text_log = models.ForeignKey(
        "document_extraction.DocExtractionLog",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_records",
    )
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)
    source_document = models.ForeignKey(
        "document_extraction.Document",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="company_payments",
    )
    source_database = models.ForeignKey(
        "db_extraction.DatabaseSource",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="company_payments",
    )
    # Optional document notes and context; matching uses the structured fields and lines.
    payment_metadata = models.TextField(blank=True)
    payment_context = models.TextField(blank=True)

    def clean(self):
        # Validate business rules as well as individual field values.
        super().clean()
        services.validate_source(self)
        services.validate_payment_amounts(self)

    @transaction.atomic
    def save(self, *args, **kwargs):
        from discrepancies.services.timeline import lock_account
        lock_account(self)
        self.source_record_key = services.normalize_source_key(self.source_record_key)
        self.full_clean()
        with transaction.atomic():
            result = super().save(*args, **kwargs)
            for allocation in self.invoice_allocations.select_related("invoice"):
                allocation.invoice.refresh_payment_status()
            from discrepancies.services.timeline import observe_payment
            observe_payment(self)
            from .services.statements import refresh_related
            refresh_related(self)
            return result

    @property
    def unallocated_amount(self) -> Decimal:
        return services.unallocated_cash(self)

    def __str__(self):
        return f"{self.payment_reference_no} - {self.supplier}"

    class Meta:
        ordering = ["-payment_date"]
        verbose_name = "Company Payment"
        verbose_name_plural = "Company Payments"
        constraints = [
            models.UniqueConstraint(
                fields=["source_table", "source_record_key"],
                condition=Q(source_table__isnull=False),
                name="ap_payment_source_record_uq",
            ),
            models.UniqueConstraint(
                fields=["supplier", "payment_reference_no"],
                name="unique_supplier_payment_reference",
            ),
        ]


class Transaction(models.Model):
    """One AP reconciliation case grouping orders, receipts, and invoices for the same supplier and currency."""

    # Django creates these IDs and reverse relations; annotations help the editor.
    if TYPE_CHECKING:
        supplier_id: int | None
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
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, null=True, blank=True, related_name="transactions"
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
        CompanyPurchaseOrder, blank=True, related_name="reconciliation_cases"
    )
    delivery_receipts = models.ManyToManyField(
        SupplierDeliveryReceipt, blank=True, related_name="reconciliation_cases"
    )
    sales_invoices = models.ManyToManyField(
        SupplierSalesInvoice, blank=True, related_name="reconciliation_cases"
    )

    def calculate_reconciliation(self) -> tuple[str, Decimal]:
        return services.calculate_reconciliation(self)

    def refresh_reconciliation_status(self):
        # Store the result calculated from current documents and line matches.
        if not self.pk:
            return
        from discrepancies.services import refresh_transaction
        refresh_transaction(self)

    def clean(self):
        # Validate business rules as well as individual field values.
        super().clean()
        services.validate_case(self)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"AP transaction {self.transaction_no} - {self.supplier}"

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "AP Transaction"
        verbose_name_plural = "AP Transactions"


class CompanyPurchaseOrderLine(models.Model):
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
        CompanyPurchaseOrder, on_delete=models.PROTECT, related_name="lines"
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
        ordering = ["line_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["purchase_order", "line_no"], name="ap_po_line_number_uq"
            )
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
        SupplierDeliveryReceipt, on_delete=models.PROTECT, related_name="lines"
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
        ordering = ["line_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["delivery_receipt", "line_no"], name="ap_dr_line_number_uq"
            )
        ]


class SupplierSalesInvoiceLine(models.Model):
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
    invoice = models.ForeignKey(
        SupplierSalesInvoice, on_delete=models.PROTECT, related_name="lines"
    )

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
        ordering = ["line_no"]
        constraints = [
            models.UniqueConstraint(fields=["invoice", "line_no"], name="ap_invoice_line_number_uq")
        ]


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
    sku_identity_snapshot = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    transaction = models.ForeignKey(
        Transaction, on_delete=models.PROTECT, related_name="line_matches"
    )
    purchase_order_line = models.ForeignKey(
        CompanyPurchaseOrderLine,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="matches",
    )
    delivery_receipt_line = models.ForeignKey(
        SupplierDeliveryReceiptLine,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="matches",
    )
    invoice_line = models.ForeignKey(
        SupplierSalesInvoiceLine, on_delete=models.PROTECT, related_name="matches"
    )

    def clean(self):
        # Validate business rules as well as individual field values.
        super().clean()
        services.validate_match(self)

    def save(self, *args, **kwargs):
        # Lock the affected rows so concurrent matches or allocations cannot reuse them.
        with transaction.atomic():
            if self.transaction_id:
                case = Transaction.objects.get(pk=self.transaction_id)
                if case.supplier_id:
                    Supplier.objects.select_for_update().get(pk=case.supplier_id)
                Transaction.objects.select_for_update().get(pk=self.transaction_id)
            if self.invoice_line_id:
                SupplierSalesInvoiceLine.objects.select_for_update().get(pk=self.invoice_line_id)
            if self.purchase_order_line_id:
                CompanyPurchaseOrderLine.objects.select_for_update().get(
                    pk=self.purchase_order_line_id
                )
            if self.delivery_receipt_line_id:
                SupplierDeliveryReceiptLine.objects.select_for_update().get(
                    pk=self.delivery_receipt_line_id
                )
            self.full_clean()
            from sku_matching.services.mapping import identity_for_match
            self.sku_identity_snapshot = identity_for_match(self)
            if kwargs.get('update_fields') is not None:
                kwargs['update_fields'] = set(kwargs['update_fields']) | {'sku_identity_snapshot'}
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
        return f"AP match {self.pk} for invoice line {self.invoice_line_id}"

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
        CompanyPayment, on_delete=models.PROTECT, related_name="invoice_allocations"
    )
    invoice = models.ForeignKey(
        SupplierSalesInvoice, on_delete=models.PROTECT, related_name="payment_allocations"
    )

    def clean(self):
        # Validate business rules as well as individual field values.
        super().clean()
        services.validate_allocation(self)

    def save(self, *args, **kwargs):
        # Lock the affected rows so concurrent matches or allocations cannot reuse them.
        with transaction.atomic():
            from discrepancies.services.timeline import lock_account
            if self.invoice_id:lock_account(self.invoice)
            if self.payment_id:
                CompanyPayment.objects.select_for_update().get(pk=self.payment_id)
            if self.invoice_id:
                SupplierSalesInvoice.objects.select_for_update().get(pk=self.invoice_id)
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
                SupplierSalesInvoice.objects.get(pk=old_invoice_id).refresh_payment_status()
            return result

    def delete(self, *args, **kwargs):
        invoice = self.invoice
        with transaction.atomic():
            from discrepancies.services.timeline import lock_account
            lock_account(invoice)
            result = super().delete(*args, **kwargs)
            invoice.refresh_payment_status()
            return result

    def __str__(self):
        return f"{self.payment} → {self.invoice}"

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["payment", "invoice"], name="ap_payment_invoice_uq")
        ]


class ExtractionConfiguration(models.Model):
    """User-reviewed instructions for entering one kind of accounting record.

    A profile describes either database mapping or document extraction, scoped
    to the module or an existing Supplier. It never imports or encodes a record
    by itself. Drafts are saved through the workspace; only explicitly submitted snapshots
    are used by extraction.
    Existing per-record context/provenance fields retain their current meaning.
    """

    class TargetEntity(models.TextChoices):
        SUPPLIER = "supplier", "Supplier"
        PURCHASE_ORDER = "purchase_order", "Purchase order"
        DELIVERY_RECEIPT = "delivery_receipt", "Delivery receipt"
        SALES_INVOICE = "sales_invoice", "Sales invoice"
        PAYMENT = "payment", "Payment"

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
    supplier = models.ForeignKey(
        "Supplier", on_delete=models.PROTECT, null=True, blank=True,
        related_name="extraction_configurations",
        help_text="Blank applies module-wide; otherwise use this account's layout or mapping.",
    )

    # Schema metadata identifies external fields; no credentials or SQL are stored.
    database_source = models.ForeignKey(
        "db_extraction.DatabaseSource", on_delete=models.PROTECT, null=True,
        blank=True, related_name="ap_extraction_configurations",
    )
    source_table = models.ForeignKey(
        "db_extraction.DatabaseTable", on_delete=models.PROTECT, null=True,
        blank=True, related_name="ap_header_configurations",
    )
    line_source_table = models.ForeignKey(
        "db_extraction.DatabaseTable", on_delete=models.PROTECT, null=True,
        blank=True, related_name="ap_line_configurations",
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
        related_name="ap_submitted_extraction_configurations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["target_entity", "name", "pk"]
        verbose_name = "AP extraction configuration"
        verbose_name_plural = "AP extraction configurations"

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
        related_name="ap_extraction_logs",
    )
    configuration_revision = models.PositiveIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1)],
    )
    target_entity = models.CharField(max_length=30, choices=ExtractionConfiguration.TargetEntity.choices)
    source_type = models.CharField(max_length=20, choices=ExtractionConfiguration.SourceType.choices)
    purpose = models.CharField(max_length=20, choices=Purpose.choices, default=Purpose.EXTRACTION)
    # Optional destination links allow attempts before a record exists.
    supplier = models.ForeignKey(
        "Supplier", on_delete=models.PROTECT, null=True, blank=True, related_name="llm_logs",
    )
    purchase_order = models.ForeignKey(
        "CompanyPurchaseOrder", on_delete=models.PROTECT, null=True, blank=True, related_name="llm_logs",
    )
    delivery_receipt = models.ForeignKey(
        "SupplierDeliveryReceipt", on_delete=models.PROTECT, null=True, blank=True, related_name="llm_logs",
    )
    sales_invoice = models.ForeignKey(
        "SupplierSalesInvoice", on_delete=models.PROTECT, null=True, blank=True, related_name="llm_logs",
    )
    payment = models.ForeignKey(
        "CompanyPayment", on_delete=models.PROTECT, null=True, blank=True, related_name="llm_logs",
    )
    fk_document_no = models.ForeignKey(
        "document_extraction.Document", on_delete=models.PROTECT, null=True,
        blank=True, related_name="ap_llm_logs",
    )
    source_llm_log = models.ForeignKey(
        "document_extraction.LLMExtractionLog", on_delete=models.PROTECT,
        null=True, blank=True, related_name="ap_accounting_logs",
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
        related_name="ap_reviewed_llm_logs",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-llm_log_no"]
        indexes = [
            models.Index(fields=["status", "-created_at"], name="ap_llm_status_created"),
            models.Index(fields=["configuration", "-created_at"], name="ap_llm_config_created"),
        ]
        verbose_name = "AP LLM extraction log"

    def __str__(self):
        return f"AP LLM #{self.llm_log_no} · {self.get_status_display()}"


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


class CreditHistoryQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError('Use the reviewed credit service; financial history cannot be bulk rewritten.')

    def delete(self):
        raise ValidationError('Credit history cannot be deleted.')


class SupplierCreditNote(models.Model):
    """A supplier correction, distinct from cash and requiring explicit verification."""
    objects = CreditHistoryQuerySet.as_manager()
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='credit_notes')
    reference = models.CharField(max_length=100)
    issue_date = models.DateField()
    currency = models.CharField(max_length=3, validators=[RegexValidator(r'^[A-Z]{3}$')])
    credit_amount = models.DecimalField(max_digits=15, decimal_places=2, validators=[MinValueValidator(Decimal('.01'))])
    status = models.CharField(max_length=12, choices=[('draft','Draft'),('verified','Verified'),('cancelled','Cancelled')], default='draft')
    source_document = models.ForeignKey('document_extraction.Document', null=True, blank=True, on_delete=models.PROTECT, related_name='supplier_credits')
    source_database = models.ForeignKey('db_extraction.DatabaseSource', null=True, blank=True, on_delete=models.PROTECT, related_name='supplier_credits')
    source_table = models.ForeignKey('db_extraction.DatabaseTable', null=True, blank=True, on_delete=models.PROTECT, related_name='supplier_credits')
    source_record_key = models.JSONField(default=dict, blank=True)
    verification_notes = models.TextField(blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['supplier','reference'], name='ap_credit_supplier_ref'),
            models.UniqueConstraint(fields=['source_table','source_record_key'], condition=Q(source_table__isnull=False), name='ap_credit_source_key'),
            models.CheckConstraint(condition=Q(credit_amount__gt=0), name='ap_credit_positive')]
        ordering = ['-issue_date','-pk']

    def clean(self):
        super().clean()
        services.validate_source(self)
        if self.status=='verified' and (not self.verified_at or not self.verification_notes.strip() or not (self.source_document_id or self.source_database_id and self.source_record_key)):
            raise ValidationError('Credit verification requires supporting evidence, notes and a verification timestamp.')
        if self.pk:
            old = type(self).objects.get(pk=self.pk)
            if old.status=='verified' and any(getattr(old, name)!=getattr(self, name) for name in ('supplier_id','reference','currency','credit_amount','issue_date','source_document_id','source_database_id','source_table_id','source_record_key','status','verified_at','verification_notes')):
                raise ValidationError('Verified credit evidence cannot be rewritten. Reverse applications and record a corrective document.')

    def save(self, *args, **kwargs):
        with transaction.atomic():
            Supplier.objects.select_for_update().get(pk=self.supplier_id)
            self.full_clean()
            result = super().save(*args, **kwargs)
            from .services.statements import refresh_related
            refresh_related(self)
            return result

    def delete(self, *args, **kwargs):
        raise ValidationError('Preserve credit history; credits cannot be deleted.')


class SupplierCreditApplication(models.Model):
    objects = CreditHistoryQuerySet.as_manager()
    credit = models.ForeignKey(SupplierCreditNote, on_delete=models.PROTECT, related_name='applications')
    invoice = models.ForeignKey(SupplierSalesInvoice, on_delete=models.PROTECT, related_name='credit_applications')
    amount = models.DecimalField(max_digits=15, decimal_places=2, validators=[MinValueValidator(Decimal('.01'))])
    request_key = models.CharField(max_length=100)
    application_date = models.DateField()
    notes = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['credit','request_key'], name='ap_credit_request_key'),
                       models.CheckConstraint(condition=Q(amount__gt=0), name='ap_credit_application_positive')]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError('Credit applications are immutable; use a reversal.')
        from .services.credits import validate_application
        with transaction.atomic():
            Supplier.objects.select_for_update().get(pk=self.credit.supplier_id)
            self.credit = SupplierCreditNote.objects.select_for_update().get(pk=self.credit_id)
            self.invoice = SupplierSalesInvoice.objects.select_for_update().get(pk=self.invoice_id)
            self.full_clean()
            validate_application(self)
            result = super().save(*args, **kwargs)
            self.invoice.refresh_payment_status()
            return result

    def delete(self, *args, **kwargs):
        raise ValidationError('Credit applications are immutable; use a reversal.')


class SupplierCreditReversal(models.Model):
    objects = CreditHistoryQuerySet.as_manager()
    application = models.OneToOneField(SupplierCreditApplication, on_delete=models.PROTECT, related_name='reversal')
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError('Credit reversals are immutable.')
        with transaction.atomic():
            Supplier.objects.select_for_update().get(pk=self.application.credit.supplier_id)
            self.full_clean()
            result = super().save(*args, **kwargs)
            self.application.invoice.refresh_payment_status()
            return result

    def delete(self, *args, **kwargs):
        raise ValidationError('Credit reversals are immutable.')


class SupplierStatement(models.Model):
    objects = CreditHistoryQuerySet.as_manager()
    supplier = models.ForeignKey(Supplier,on_delete=models.PROTECT,related_name='statements')
    reference = models.CharField(max_length=100)
    statement_date = models.DateField()
    period_start = models.DateField()
    currency = models.CharField(max_length=3,validators=[RegexValidator(r'^[A-Z]{3}$')])
    opening_balance = models.DecimalField(max_digits=15,decimal_places=2)
    closing_balance = models.DecimalField(max_digits=15,decimal_places=2)
    source_document = models.ForeignKey('document_extraction.Document',on_delete=models.PROTECT,related_name='supplier_statements')
    ap_transaction = models.ForeignKey(Transaction,null=True,blank=True,on_delete=models.PROTECT,related_name='supplier_statements')
    reconciliation_status = models.CharField(max_length=12,default='pending',choices=[('pending','Pending'),('matched','Matched'),('exception','Exception')])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=['supplier','reference'],name='ap_statement_reference')]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            old = type(self).objects.get(pk=self.pk)
            if any(getattr(old, field) != getattr(self, field) for field in ('supplier_id', 'reference', 'statement_date', 'period_start', 'currency', 'opening_balance', 'closing_balance', 'source_document_id', 'ap_transaction_id')):
                raise ValidationError('Original statement evidence cannot be rewritten; import a corrective statement.')
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Preserve statement evidence and review history.')


class SupplierStatementLine(models.Model):
    statement = models.ForeignKey(SupplierStatement,on_delete=models.PROTECT,related_name='lines')
    line_no = models.PositiveIntegerField()
    reference = models.CharField(max_length=100)
    transaction_date = models.DateField()
    kind = models.CharField(max_length=10,choices=[('invoice','Invoice'),('payment','Payment'),('credit','Credit')])
    amount = models.DecimalField(max_digits=15,decimal_places=2)
    review_decision = models.CharField(max_length=20,default='unreviewed',choices=[('unreviewed','Unreviewed'),('confirmed','Confirmed'),('dismissed','Dismissed')])
    review_notes = models.TextField(blank=True)
    reviewed_at = models.DateTimeField(null=True,blank=True)
    objects = CreditHistoryQuerySet.as_manager()

    class Meta:
        constraints=[models.UniqueConstraint(fields=['statement','line_no'],name='ap_statement_line_no'),models.CheckConstraint(condition=Q(amount__gt=0),name='ap_statement_line_positive')]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            old = type(self).objects.get(pk=self.pk)
            if any(getattr(old, field) != getattr(self, field) for field in ('statement_id', 'line_no', 'reference', 'transaction_date', 'kind', 'amount')):
                raise ValidationError('Original statement evidence cannot be rewritten; import a corrective statement.')
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Preserve statement evidence and review history.')


class SupplierStatementMatch(models.Model):
    objects = CreditHistoryQuerySet.as_manager()
    statement = models.ForeignKey(SupplierStatement,on_delete=models.PROTECT,related_name='matches')
    line = models.ForeignKey(SupplierStatementLine,on_delete=models.PROTECT,related_name='matches')
    invoice = models.ForeignKey(SupplierSalesInvoice,null=True,blank=True,on_delete=models.PROTECT,related_name='statement_matches')
    payment = models.ForeignKey(CompanyPayment,null=True,blank=True,on_delete=models.PROTECT,related_name='statement_matches')
    credit = models.ForeignKey(SupplierCreditNote,null=True,blank=True,on_delete=models.PROTECT,related_name='statement_matches')
    active = models.BooleanField(default=True)
    notes = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    superseded_at = models.DateTimeField(null=True,blank=True)

    class Meta:
        constraints=[models.CheckConstraint(condition=(Q(invoice__isnull=False,payment__isnull=True,credit__isnull=True)|Q(invoice__isnull=True,payment__isnull=False,credit__isnull=True)|Q(invoice__isnull=True,payment__isnull=True,credit__isnull=False)),name='statement_match_one_target'),
            models.UniqueConstraint(fields=['line'],condition=Q(active=True),name='statement_line_active_match'),
            *[models.UniqueConstraint(fields=['statement',kind],condition=Q(active=True,**{kind+'__isnull':False}),name='statement_active_'+kind) for kind in ('invoice','payment','credit')]]

    def save(self, *args, **kwargs):
        self.full_clean()
        if self.line.statement_id != self.statement_id:
            raise ValidationError('A statement match must reference a line on that statement.')
        target = getattr(self, self.line.kind)
        if target is None or target.supplier_id != self.statement.supplier_id or target.currency != self.statement.currency:
            raise ValidationError('Match type, supplier and currency must agree with the statement.')
        if not self._state.adding:
            old = type(self).objects.get(pk=self.pk)
            if any(getattr(old, name) != getattr(self, name) for name in ('statement_id','line_id','invoice_id','payment_id','credit_id','notes')) or not old.active or self.active or not self.superseded_at:
                raise ValidationError('Statement matches may only be explicitly superseded.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Preserve statement matching history.')


class SupplierStatementEvaluation(models.Model):
    statement = models.ForeignKey(SupplierStatement,on_delete=models.PROTECT,related_name='evaluations')
    result = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = CreditHistoryQuerySet.as_manager()

    def save(self,*args,**kwargs):
        if not self._state.adding:raise ValidationError('Statement observations are append-only.')
        return super().save(*args,**kwargs)

    def delete(self,*args,**kwargs):
        raise ValidationError('Statement observations cannot be deleted.')
