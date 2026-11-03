"""Shared reconciliation findings and immutable, content-addressed source snapshots."""
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class DiscrepancyFinding(models.Model):
    class Code(models.TextChoices):
        QUANTITY_SHORTAGE = 'QUANTITY_SHORTAGE', 'Unsupported invoiced quantity'
        PRICE_VARIANCE = 'PRICE_VARIANCE', 'Price variance'
        LINE_TOTAL_MISMATCH = 'LINE_TOTAL_MISMATCH', 'Line total mismatch'
        HEADER_TOTAL_MISMATCH = 'HEADER_TOTAL_MISMATCH', 'Header total mismatch'
        MISSING_PO = 'MISSING_PO', 'Missing purchase-order evidence'
        MISSING_DR = 'MISSING_DR', 'Missing receiving evidence'
        POSSIBLE_DUPLICATE_INVOICE = 'POSSIBLE_DUPLICATE_INVOICE', 'Possible duplicate invoice'
        CUSTOMER_DEDUCTION = 'CUSTOMER_DEDUCTION', 'Customer deduction review'
        STATEMENT_MISMATCH = 'STATEMENT_MISMATCH', 'Supplier statement mismatch'
        SETTLEMENT_MISMATCH = 'SETTLEMENT_MISMATCH', 'Settlement evidence requires review'

    ap_transaction = models.ForeignKey('accounts_payable.Transaction', null=True, blank=True, on_delete=models.PROTECT, related_name='discrepancy_findings')
    ar_transaction = models.ForeignKey('accounts_receivable.Transaction', null=True, blank=True, on_delete=models.PROTECT, related_name='discrepancy_findings')
    fingerprint = models.CharField(max_length=64)
    finding_code = models.CharField(max_length=30, choices=Code.choices)
    severity = models.CharField(max_length=12, choices=[('information','Information'),('warning','Warning'),('critical','Critical')])
    status = models.CharField(max_length=10, choices=[('open','Open'),('cleared','Cleared')], default='open')
    summary = models.TextField()
    expected_value = models.JSONField(default=dict)
    actual_value = models.JSONField(default=dict)
    difference_amount = models.DecimalField(max_digits=38, decimal_places=8, null=True, blank=True)
    currency = models.CharField(max_length=3, blank=True)
    rule_version = models.CharField(max_length=20, default='1')
    identity = models.JSONField(default=dict)
    details = models.JSONField(default=dict)
    first_detected_at = models.DateTimeField()
    last_detected_at = models.DateTimeField()
    cleared_at = models.DateTimeField(null=True, blank=True)

    class Review(models.TextChoices):
        UNREVIEWED = 'unreviewed', 'Unreviewed'
        CONFIRMED = 'confirmed', 'Confirmed'
        DISMISSED = 'dismissed', 'Dismissed'
        NEEDS_MORE_EVIDENCE = 'needs_more_evidence', 'Needs more evidence'

    review_decision = models.CharField(max_length=25, choices=Review.choices, default=Review.UNREVIEWED)
    review_notes = models.TextField(blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_basis = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ['-status', 'first_detected_at', 'pk']
        constraints = [
            models.CheckConstraint(condition=(Q(ap_transaction__isnull=False, ar_transaction__isnull=True) | Q(ap_transaction__isnull=True, ar_transaction__isnull=False)), name='finding_exactly_one_case'),
            models.UniqueConstraint(fields=['ap_transaction','fingerprint'], condition=Q(ap_transaction__isnull=False), name='finding_ap_fingerprint_uq'),
            models.UniqueConstraint(fields=['ar_transaction','fingerprint'], condition=Q(ar_transaction__isnull=False), name='finding_ar_fingerprint_uq'),
            models.CheckConstraint(condition=(Q(status='open', cleared_at__isnull=True) | Q(status='cleared', cleared_at__isnull=False)), name='finding_clear_time_consistent'),
        ]


class FindingEvidence(models.Model):
    finding = models.ForeignKey(DiscrepancyFinding, on_delete=models.PROTECT, related_name='evidence')
    snapshot_hash = models.CharField(max_length=64)
    evidence_type = models.CharField(max_length=20)
    source_model = models.CharField(max_length=150)
    source_record_id = models.CharField(max_length=100)
    source_line_id = models.CharField(max_length=100, blank=True)
    source_document = models.ForeignKey('document_extraction.Document', null=True, blank=True, on_delete=models.SET_NULL, related_name='finding_evidence')
    source_database = models.ForeignKey('db_extraction.DatabaseSource', null=True, blank=True, on_delete=models.SET_NULL, related_name='finding_evidence')
    source_record_key = models.JSONField(default=dict)
    provenance = models.JSONField(default=dict)
    field_name = models.CharField(max_length=100)
    observed_value = models.JSONField(default=dict)
    # Include the evaluated finding state so history remains independently interpretable.
    finding_snapshot = models.JSONField(default=dict)
    captured_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['captured_at', 'pk']
        constraints = [models.UniqueConstraint(fields=['finding','snapshot_hash'], name='finding_evidence_snapshot_uq')]


class CaseInvestigation(models.Model):
    class Status(models.TextChoices):
        NEEDS_REVIEW = 'needs_review', 'Needs review'
        INVESTIGATING = 'investigating', 'Investigating'
        WAITING = 'waiting', 'Waiting'
        RESOLVED = 'resolved', 'Resolved'
        DISMISSED = 'dismissed', 'Dismissed'

    class Resolution(models.TextChoices):
        SOURCE_CORRECTION_VERIFIED = 'source_correction_verified', 'Source correction verified'
        CORRECTIVE_DOCUMENT_VERIFIED = 'corrective_document_verified', 'Corrective document verified'
        BUSINESS_EXCEPTION_ACCEPTED = 'business_exception_accepted', 'Business exception accepted'
        FALSE_POSITIVE = 'false_positive', 'False positive'
        OTHER = 'other', 'Other documented resolution'

    ap_transaction = models.OneToOneField('accounts_payable.Transaction', null=True, blank=True, on_delete=models.PROTECT, related_name='investigation')
    ar_transaction = models.OneToOneField('accounts_receivable.Transaction', null=True, blank=True, on_delete=models.PROTECT, related_name='investigation')
    workflow_status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEEDS_REVIEW)
    responsible_department = models.CharField(max_length=120, blank=True)
    next_action = models.TextField(blank=True)
    resolution_type = models.CharField(max_length=35, choices=Resolution.choices, blank=True)
    resolution_notes = models.TextField(blank=True)
    resolution_evidence = models.JSONField(default=list, blank=True)
    resolution_basis = models.CharField(max_length=64, blank=True)
    review_required = models.BooleanField(default=False)
    review_reason = models.TextField(blank=True)
    opened_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=(Q(ap_transaction__isnull=False, ar_transaction__isnull=True)|Q(ap_transaction__isnull=True, ar_transaction__isnull=False)), name='investigation_exactly_one_case'),
            models.CheckConstraint(condition=(Q(workflow_status__in=['needs_review','investigating','waiting'],closed_at__isnull=True)|Q(workflow_status__in=['resolved','dismissed'],closed_at__isnull=False)), name='investigation_closure_consistent'),
        ]


class ActivityQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError('Investigation activity is append-only.')

    def delete(self):
        raise ValidationError('Investigation activity cannot be deleted.')

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError('Investigation activity is append-only.')

    def bulk_create(self, objs, **kwargs):
        if kwargs.get('update_conflicts') or kwargs.get('ignore_conflicts'):
            raise ValidationError('Investigation activity cannot overwrite or silently ignore history.')
        objs = list(objs)
        for obj in objs:
            obj.full_clean()
        return super().bulk_create(objs, **kwargs)


class CaseActivity(models.Model):
    investigation = models.ForeignKey(CaseInvestigation, on_delete=models.PROTECT, related_name='activities')
    activity_type = models.CharField(max_length=25, choices=[(value,value.replace('_',' ').title()) for value in ('opened','note','status_change','update','review','resolution','reopening','evidence_changed')])
    finding = models.ForeignKey(DiscrepancyFinding, null=True, blank=True, on_delete=models.PROTECT, related_name='review_activities')
    previous_status = models.CharField(max_length=20, blank=True)
    new_status = models.CharField(max_length=20, blank=True)
    notes = models.TextField(blank=True)
    actor_label = models.CharField(max_length=150, blank=True, help_text='Manually supplied, unverified staff label.')
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = ActivityQuerySet.as_manager()

    class Meta:
        ordering = ['created_at','pk']

    def clean(self):
        super().clean()
        if self.finding_id and self.investigation_id:
            finding = DiscrepancyFinding.objects.filter(pk=self.finding_id).values_list('ap_transaction_id','ar_transaction_id').first()
            investigation = CaseInvestigation.objects.filter(pk=self.investigation_id).values_list('ap_transaction_id','ar_transaction_id').first()
            if finding is not None and investigation is not None and finding != investigation:
                raise ValidationError('A finding review must belong to the same investigation case.')

    def save(self, *args, **kwargs):
        if not self._state.adding or (self.pk and type(self).objects.filter(pk=self.pk).exists()):
            raise ValidationError('Investigation activity is append-only.')
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Investigation activity cannot be deleted.')


class CaseTimelineEvent(models.Model):
    TYPES=[(v,v.replace('_',' ').title()) for v in ('case_created','documents_changed','matches_changed','source_changed','payments_changed','credits_changed','duplicate_reviewed','claim_changed','claim_correspondence','statement_changed','deductions_changed','finding_detected','finding_changed','finding_cleared','finding_reopened','reconciliation_changed')]
    ap_transaction=models.ForeignKey('accounts_payable.Transaction',null=True,blank=True,on_delete=models.PROTECT,related_name='timeline_events')
    ar_transaction=models.ForeignKey('accounts_receivable.Transaction',null=True,blank=True,on_delete=models.PROTECT,related_name='timeline_events')
    event_type=models.CharField(max_length=30,choices=TYPES)
    event_key=models.CharField(max_length=64)
    description=models.CharField(max_length=500)
    occurred_at=models.DateTimeField(null=True,blank=True)
    recorded_at=models.DateTimeField(auto_now_add=True)
    source_model=models.CharField(max_length=150)
    source_record_id=models.CharField(max_length=100)
    details=models.JSONField(default=dict,blank=True)
    evidence_snapshot_hash=models.CharField(max_length=64,blank=True)
    objects=ActivityQuerySet.as_manager()
    class Meta:
        constraints=[models.CheckConstraint(condition=(Q(ap_transaction__isnull=False,ar_transaction__isnull=True)|Q(ap_transaction__isnull=True,ar_transaction__isnull=False)),name='timeline_one_case'),models.UniqueConstraint(fields=['ap_transaction','event_key'],condition=Q(ap_transaction__isnull=False),name='timeline_ap_key'),models.UniqueConstraint(fields=['ar_transaction','event_key'],condition=Q(ar_transaction__isnull=False),name='timeline_ar_key')]
        indexes=[models.Index(fields=['ap_transaction','recorded_at','id'],name='timeline_ap_chrono'),models.Index(fields=['ar_transaction','recorded_at','id'],name='timeline_ar_chrono')]
    def save(self,*args,**kwargs):
        if not self._state.adding or (self.pk and type(self).objects.filter(pk=self.pk).exists()):
            raise ValidationError('Timeline events are append-only.')
        self.full_clean()
        return super().save(*args,**kwargs)
    def delete(self,*args,**kwargs):
        raise ValidationError('Timeline events cannot be deleted.')


class DuplicateInvoiceCandidate(models.Model):
    """Reviewable pairs also exist without fabricating reconciliation cases."""
    ap_first = models.ForeignKey('accounts_payable.SupplierSalesInvoice', null=True, blank=True, on_delete=models.PROTECT, related_name='duplicate_candidates_first')
    ap_second = models.ForeignKey('accounts_payable.SupplierSalesInvoice', null=True, blank=True, on_delete=models.PROTECT, related_name='duplicate_candidates_second')
    ar_first = models.ForeignKey('accounts_receivable.CompanySalesInvoice', null=True, blank=True, on_delete=models.PROTECT, related_name='duplicate_candidates_first')
    ar_second = models.ForeignKey('accounts_receivable.CompanySalesInvoice', null=True, blank=True, on_delete=models.PROTECT, related_name='duplicate_candidates_second')
    active = models.BooleanField(default=True)
    details = models.JSONField(default=dict)
    review_decision = models.CharField(max_length=20, choices=[('unreviewed','Unreviewed'),('confirmed','Confirmed'),('dismissed','Dismissed')], default='unreviewed')
    review_notes = models.TextField(blank=True)
    review_basis = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=(Q(ap_first__isnull=False,ap_second__isnull=False,ar_first__isnull=True,ar_second__isnull=True,ap_first__lt=models.F('ap_second'))|Q(ar_first__isnull=False,ar_second__isnull=False,ap_first__isnull=True,ap_second__isnull=True,ar_first__lt=models.F('ar_second'))),name='duplicate_pair_scope_order'),
            models.UniqueConstraint(fields=['ap_first','ap_second'],condition=Q(ap_first__isnull=False),name='duplicate_ap_pair'),
            models.UniqueConstraint(fields=['ar_first','ar_second'],condition=Q(ar_first__isnull=False),name='duplicate_ar_pair')]


class DuplicateInvoiceReview(models.Model):
    candidate = models.ForeignKey(DuplicateInvoiceCandidate,on_delete=models.PROTECT,related_name='reviews')
    decision = models.CharField(max_length=20)
    notes = models.TextField()
    evidence_snapshot = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = ActivityQuerySet.as_manager()

    def save(self,*args,**kwargs):
        if not self._state.adding:raise ValidationError('Duplicate invoice review history is immutable.')
        return super().save(*args,**kwargs)

    def delete(self,*args,**kwargs):
        raise ValidationError('Duplicate invoice review history cannot be deleted.')


class SupplierClaim(models.Model):
    objects = ActivityQuerySet.as_manager()
    ap_transaction = models.ForeignKey('accounts_payable.Transaction',on_delete=models.PROTECT,related_name='supplier_claims')
    supplier = models.ForeignKey('accounts_payable.Supplier',on_delete=models.PROTECT,related_name='claims')
    reference = models.CharField(max_length=100)
    category = models.CharField(max_length=60)
    currency = models.CharField(max_length=3)
    claimed_amount = models.DecimalField(max_digits=15,decimal_places=2)
    accepted_amount = models.DecimalField(max_digits=15,decimal_places=2,null=True,blank=True)
    status = models.CharField(max_length=20,choices=[(s,s.title()) for s in ('draft','submitted','waiting','accepted','rejected','resolved')],default='draft')
    findings = models.ManyToManyField(DiscrepancyFinding,related_name='supplier_claims')
    evidence = models.ManyToManyField(FindingEvidence,related_name='supplier_claims')
    submission_date = models.DateField(null=True,blank=True)
    follow_up_date = models.DateField(null=True,blank=True)
    resolution_type = models.CharField(max_length=30,blank=True)
    resolution_notes = models.TextField(blank=True)
    settlement_application = models.OneToOneField('accounts_payable.SupplierCreditApplication',null=True,blank=True,on_delete=models.PROTECT,related_name='supplier_claim')
    replacement_document = models.ForeignKey('document_extraction.Document',null=True,blank=True,on_delete=models.PROTECT,related_name='resolved_claims')
    review_required = models.BooleanField(default=False)
    closed_at = models.DateTimeField(null=True,blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def delete(self,*args,**kwargs):
        raise ValidationError('Supplier claims cannot be deleted; record a documented outcome.')

    class Meta:
        constraints=[models.UniqueConstraint(fields=['supplier','reference'],name='claim_supplier_reference'),models.CheckConstraint(condition=Q(claimed_amount__gt=0),name='claim_positive'),models.CheckConstraint(condition=Q(accepted_amount__isnull=True)|Q(accepted_amount__gte=0,accepted_amount__lte=models.F('claimed_amount')),name='claim_acceptance_limit')]


class ClaimCorrespondence(models.Model):
    claim = models.ForeignKey(SupplierClaim,on_delete=models.PROTECT,related_name='correspondence')
    direction = models.CharField(max_length=12,choices=[('outgoing','Outgoing'),('incoming','Incoming'),('draft','Draft')])
    subject = models.CharField(max_length=200)
    message = models.TextField()
    occurred_at = models.DateTimeField()
    actor_label = models.CharField(max_length=150,blank=True)
    source_document = models.ForeignKey('document_extraction.Document',null=True,blank=True,on_delete=models.PROTECT,related_name='claim_correspondence')
    created_at = models.DateTimeField(auto_now_add=True)
    objects = ActivityQuerySet.as_manager()

    def save(self,*args,**kwargs):
        if not self._state.adding:raise ValidationError('Correspondence is append-only.')
        self.full_clean()
        return super().save(*args,**kwargs)

    def delete(self,*args,**kwargs):
        raise ValidationError('Correspondence cannot be deleted.')


class FindingRootCause(models.Model):
    objects = ActivityQuerySet.as_manager()
    class Category(models.TextChoices):
        RECEIVING = 'receiving', 'Receiving process'
        PRICING = 'pricing', 'Pricing or commercial terms'
        DOCUMENTATION = 'documentation', 'Missing or incorrect documentation'
        SOURCE_DATA = 'source_data', 'Source data or extraction'
        SKU = 'sku_identity', 'Product identifier inconsistency'
        DUPLICATION = 'duplication', 'Duplicate recording'
        SETTLEMENT = 'settlement', 'Payment or adjustment processing'
        OTHER = 'other', 'Other documented cause'

    finding = models.OneToOneField(DiscrepancyFinding, on_delete=models.PROTECT, related_name='root_cause')
    category = models.CharField(max_length=25, choices=Category.choices)
    explanation = models.TextField()
    evidence = models.ManyToManyField(FindingEvidence, related_name='root_causes')
    review_status = models.CharField(max_length=15, choices=[('confirmed','Confirmed'),('needs_review','Needs renewed review')])
    reviewed_at = models.DateTimeField()
    actor_label = models.CharField(max_length=150, blank=True, help_text='Manually supplied, unverified staff label.')
    finding_basis = models.CharField(max_length=64)
    updated_at = models.DateTimeField(auto_now=True)

    def delete(self, *args, **kwargs):
        raise ValidationError('Preserve reviewed root-cause history.')
