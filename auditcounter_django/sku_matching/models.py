from django.db import models
from django.db.models import Q


class SKUAlias(models.Model):
    scope = models.CharField(max_length=2, choices=[('ap','AP'),('ar','AR')])
    supplier = models.ForeignKey('accounts_payable.Supplier',null=True,blank=True,on_delete=models.PROTECT,related_name='sku_aliases')
    customer = models.ForeignKey('accounts_receivable.Customer',null=True,blank=True,on_delete=models.PROTECT,related_name='sku_aliases')
    source_system = models.CharField(max_length=120)
    source_item_code = models.CharField(max_length=100)
    normalized_source_code = models.CharField(max_length=300)
    canonical_item_code = models.CharField(max_length=100)
    normalized_canonical_code = models.CharField(max_length=300)
    source_description = models.TextField(blank=True)
    canonical_description = models.TextField(blank=True)
    unit_of_measure = models.CharField(max_length=30)
    normalized_unit = models.CharField(max_length=90)
    source_reference = models.JSONField(default=dict)
    canonical_reference = models.JSONField(default=dict)
    source_snapshot = models.JSONField(default=dict)
    canonical_snapshot = models.JSONField(default=dict)
    status = models.CharField(max_length=15,choices=[(value,value.title()) for value in ('pending','approved','rejected','deactivated')],default='pending')
    suggestion_reason = models.TextField(blank=True)
    approval_notes = models.TextField(blank=True)
    approved_at = models.DateTimeField(null=True,blank=True)
    history = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['pk']
        constraints = [
            models.CheckConstraint(condition=(Q(scope='ap',supplier__isnull=False,customer__isnull=True)|Q(scope='ar',supplier__isnull=True,customer__isnull=False)),name='sku_alias_party_scope'),
            models.UniqueConstraint(fields=['supplier','source_system','normalized_source_code','normalized_unit'],condition=Q(scope='ap',status='approved'),name='sku_alias_ap_active_uq'),
            models.UniqueConstraint(fields=['customer','source_system','normalized_source_code','normalized_unit'],condition=Q(scope='ar',status='approved'),name='sku_alias_ar_active_uq'),
            models.CheckConstraint(condition=(~Q(status='approved')|Q(approved_at__isnull=False)),name='sku_alias_approval_time'),
        ]


class SKUSuggestionAttempt(models.Model):
    scope = models.CharField(max_length=2,choices=[('ap','AP'),('ar','AR')])
    supplier = models.ForeignKey('accounts_payable.Supplier',null=True,blank=True,on_delete=models.PROTECT)
    customer = models.ForeignKey('accounts_receivable.Customer',null=True,blank=True,on_delete=models.PROTECT)
    alias = models.ForeignKey(SKUAlias,null=True,blank=True,on_delete=models.PROTECT,related_name='attempts')
    source_system = models.CharField(max_length=120)
    source_reference = models.JSONField(default=dict)
    input_product = models.JSONField(default=dict)
    candidates = models.JSONField(default=list)
    provider = models.CharField(max_length=30,blank=True)
    model_name = models.CharField(max_length=150,blank=True)
    request_payload = models.JSONField(default=dict)
    response_payload = models.JSONField(default=dict)
    suggested_target = models.JSONField(default=dict)
    status = models.CharField(max_length=20,default='processing',choices=[(value,value.replace('_',' ').title()) for value in ('processing','completed','failed','no_candidates','no_suggestion','not_needed')])
    validation_errors = models.JSONField(default=list)
    processing_time_ms = models.PositiveIntegerField(default=0)
    usage = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at','-pk']
        constraints = [models.CheckConstraint(condition=(Q(scope='ap',supplier__isnull=False,customer__isnull=True)|Q(scope='ar',supplier__isnull=True,customer__isnull=False)),name='sku_attempt_party_scope')]
