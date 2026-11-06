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


class CustomerPayment(models.Model):
    """Money received from a customer. One payment may settle several invoices."""

    # Django creates these IDs and reverse relations; annotations help the editor.
    if TYPE_CHECKING:
        source_table_id: int | None
        source_database_id: int | None
        source_document_id: int | None
        invoice_allocations: models.Manager["PaymentAllocation"]
        customer_id: int | None
        proof_of_payment_id: int | None

    class Status:
        PENDING = "pending"
        CLEARED = "cleared"
        REVERSED = "reversed"
        choices = [(PENDING, "Pending"), (CLEARED, "Cleared"), (REVERSED, "Reversed")]

    customer_payment_no = models.AutoField(primary_key=True)
    customer = models.ForeignKey(
        'accounts_receivable.Customer', on_delete=models.PROTECT, null=True, blank=True, related_name="payments"
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
    amount_received = models.DecimalField(
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
        related_name="customer_payment_proofs",
    )
    # Provenance links to the extracted file or external database record.
    source_table = models.ForeignKey(
        "db_extraction.DatabaseTable",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="accounts_receivable_customerpayment_records",
    )
    # External row identity, including composite keys; this is not a line-item payload.
    source_record_key = models.JSONField(default=dict, blank=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    source_llm_log = models.ForeignKey(
        "document_extraction.LLMExtractionLog",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="accounts_receivable_customerpayment_records",
    )
    source_text_log = models.ForeignKey(
        "document_extraction.DocExtractionLog",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="accounts_receivable_customerpayment_records",
    )
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)
    source_document = models.ForeignKey(
        "document_extraction.Document",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="customer_payments",
    )
    source_database = models.ForeignKey(
        "db_extraction.DatabaseSource",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="customer_payments",
    )
    # Optional document notes and context; matching uses the structured fields and lines.
    payment_metadata = models.TextField(blank=True)
    payment_context = models.TextField(blank=True)

    def clean(self):
        # Validate business rules as well as individual field values.
        super().clean()
        services.validate_source(self)
        services.validate_payment_amounts(self)

    def save(self, *args, **kwargs):
        with transaction.atomic():
            # Serialize deduction limits, invoice changes and restored payments.
            if self.customer_id:
                self._meta.get_field('customer').remote_field.model.objects.select_for_update().get(pk=self.customer_id)
            if self.pk:
                type(self).objects.select_for_update().filter(pk=self.pk).first()
                invoice_ids = list(self.invoice_allocations.values_list('invoice_id', flat=True))
                Invoice = self.invoice_allocations.model._meta.get_field('invoice').remote_field.model
                list(Invoice.objects.select_for_update().filter(pk__in=invoice_ids).order_by('pk'))
            self.source_record_key = services.normalize_source_key(self.source_record_key)
            self.full_clean()
            result = super().save(*args, **kwargs)
            for allocation in self.invoice_allocations.select_related("invoice"):
                allocation.invoice.refresh_payment_status()
            return result

    @property
    def unallocated_amount(self) -> Decimal:
        return services.unallocated_cash(self)

    def __str__(self):
        return f"{self.payment_reference_no} - {self.customer}"

    class Meta:
        db_table = "accounts_receivable_customerpayment"
        ordering = ["-payment_date"]
        verbose_name = "Customer Payment"
        verbose_name_plural = "Customer Payments"
        constraints = [
            models.UniqueConstraint(
                fields=["source_table", "source_record_key"],
                condition=Q(source_table__isnull=False),
                name="ar_payment_source_record_uq",
            ),
            models.UniqueConstraint(
                fields=["customer", "payment_reference_no"],
                name="unique_customer_payment_reference",
            ),
        ]
