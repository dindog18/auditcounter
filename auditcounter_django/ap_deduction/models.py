"""AP deductions against explicitly selected purchase orders and invoices."""
from decimal import Decimal

from django.core.validators import MinValueValidator, RegexValidator
from django.db import models, transaction

from . import services


class Deduction(models.Model):
    class Category(models.TextChoices):
        DEFECTIVE = 'defective', 'Defective'
        PULL_OUT = 'pull_out', 'Pull Out'
        SUPPORT = 'support', 'Support'
        CREDIT_MEMO = 'credit_memo', 'Credit Memo'
        OTHER = 'other', 'Other'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        APPLIED = 'applied', 'Applied'
        CANCELLED = 'cancelled', 'Cancelled'

    supplier = models.ForeignKey('accounts_payable.Supplier', on_delete=models.PROTECT, related_name='deductions')
    purchase_order = models.ForeignKey('company_purchase_order.CompanyPurchaseOrder', on_delete=models.PROTECT, related_name='deductions')
    invoice = models.ForeignKey('supplier_sales_invoice.SupplierSalesInvoice', on_delete=models.PROTECT, null=True, blank=True, related_name='deductions')
    reference_no = models.CharField(max_length=100)
    deduction_date = models.DateField()
    category = models.CharField(max_length=20, choices=Category.choices)
    description = models.TextField(blank=True)
    currency = models.CharField(max_length=3, validators=[RegexValidator(r'^[A-Z]{3}$', 'Use a three-letter ISO currency code.')])
    amount = models.DecimalField(max_digits=15, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField(blank=True)
    source_document = models.ForeignKey('document_extraction.Document', on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    source_text_log = models.ForeignKey('document_extraction.DocExtractionLog', on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    source_llm_log = models.ForeignKey('document_extraction.LLMExtractionLog', on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    source_database = models.ForeignKey('db_extraction.DatabaseSource', on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    source_table = models.ForeignKey('db_extraction.DatabaseTable', on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    source_record_key = models.JSONField(default=dict, blank=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()
        services.validate(self)

    def save(self, *args, **kwargs):
        with transaction.atomic():
            services.lock(self)
            self.full_clean()
            return super().save(*args, **kwargs)

    def __str__(self):
        return self.reference_no

    class Meta:
        ordering = ['-deduction_date', '-pk']
        constraints = [models.UniqueConstraint(fields=['supplier', 'reference_no'], name='ap_deduction_reference_uq')]
