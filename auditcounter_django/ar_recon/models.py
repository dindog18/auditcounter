"""A reconciliation case is created automatically for each AR PO."""
from django.db import models


class Reconciliation(models.Model):
    purchase_order = models.OneToOneField('customer_purchase_order.CustomerPurchaseOrder', on_delete=models.CASCADE, related_name='automatic_reconciliation')
    status = models.CharField(max_length=24, default='awaiting_delivery', choices=[
        ('awaiting_delivery', 'Awaiting delivery'), ('awaiting_invoice', 'Awaiting invoice'),
        ('awaiting_payment', 'Awaiting payment'), ('partial', 'Partial'),
        ('matched', 'Matched'), ('exception', 'Exception'), ('cancelled', 'Cancelled'),
        ('closed_unserved', 'Closed unserved'),
    ])
    invoice_total = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    deduction_total = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    net_due = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    payment_total = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    outstanding = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    difference = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    issues = models.JSONField(default=list, blank=True)
    reference_reviews = models.JSONField(default=dict, blank=True)
    delivery_reviews = models.JSONField(default=dict, blank=True)
    unserved_closures = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def refresh(self):
        from .services import refresh
        return refresh(self)

    def __str__(self):
        return str(self.purchase_order)

    class Meta:
        ordering = ['-updated_at', '-pk']
