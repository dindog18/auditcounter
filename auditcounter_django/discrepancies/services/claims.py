"""Explicit supplier claims; no email transport or automatic accounting correction."""
from contextlib import contextmanager
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from accounts_payable.models import Supplier,Transaction,SupplierCreditApplication
from accounts_receivable.services.catalog import revision,check_revision
from accounts_receivable.services.financial import amount,text,body,date_value
from ..models import SupplierClaim,ClaimCorrespondence,FindingEvidence
from ..evaluation import json_value
from .investigation import finding_basis,investigation_revision
from .timeline import record_transition

TRANSITIONS={'draft':{'submitted'},'submitted':{'waiting','accepted','rejected'},'waiting':{'submitted','accepted','rejected'},'accepted':{'waiting'},'rejected':{'waiting'},'resolved':{'waiting'}}


def claim_state(claim):
    return json_value({field.name:field.value_from_object(claim) for field in claim._meta.fields if field.name not in ('created_at','updated_at')})


def observe(claim,description):
    record_transition(claim.ap_transaction,'claim_changed',description,claim._meta.label,claim.pk,claim_state(claim))


@contextmanager
def locked(record_id,data):
    with transaction.atomic():
        claim=get_object_or_404(SupplierClaim,pk=record_id)
        Supplier.objects.select_for_update().get(pk=claim.supplier_id)
        Transaction.objects.select_for_update().get(pk=claim.ap_transaction_id)
        claim=SupplierClaim.objects.select_for_update().get(pk=record_id)
        check_revision(claim,data.get('revision'))
        yield claim


@transaction.atomic
def create_claim(case_id,data):
    body(data,('revision','reference','category','claimed_amount','finding_ids','evidence_ids'))
    case=get_object_or_404(Transaction,pk=case_id)
    Supplier.objects.select_for_update().get(pk=case.supplier_id)
    case=Transaction.objects.select_for_update().get(pk=case_id)
    if data.get('revision')!=investigation_revision(case):raise ValidationError('Case evidence changed. Reload before preparing a claim.',code='conflict')
    if not hasattr(case,'investigation'):raise ValidationError('Start an investigation and review the findings first.')
    ids=data.get('finding_ids');evidence_ids=data.get('evidence_ids')
    for values in (ids,evidence_ids):
        if not isinstance(values,list) or not 1<=len(values)<=100 or any(type(v)is not int or v<=0 for v in values) or len(set(values))!=len(values):raise ValidationError('Choose 1–100 distinct finding and evidence IDs.')
    findings=list(case.discrepancy_findings.filter(pk__in=ids))
    if len(findings)!=len(ids) or any(f.review_decision!='confirmed' or f.review_basis!=finding_basis(f) or f.currency!=case.currency for f in findings):raise ValidationError('Claims require confirmed findings with current review evidence in this case and currency.')
    evidence=list(FindingEvidence.objects.filter(pk__in=evidence_ids,finding__in=findings))
    if len(evidence)!=len(evidence_ids):raise ValidationError('Claim evidence must belong to the selected case findings.')
    value=amount(data.get('claimed_amount'))
    existing=case.supplier_claims.exclude(status='rejected').exclude(status='resolved',resolution_type='no_recovery')
    if existing.filter(findings__in=findings).exists():raise ValidationError('These findings already support another active or settled claim.')
    reserved=sum((item.claimed_amount for item in existing),amount('0',positive=False))
    if value+reserved>case.total_discrepancy_amount:raise ValidationError('Claim requests exceed the current case discrepancy; review the accounting evidence first.')
    claim=SupplierClaim(ap_transaction=case,supplier_id=case.supplier_id,currency=case.currency,
        reference=text(data.get('reference'),'claim reference',100),category=text(data.get('category'),'claim category',60),claimed_amount=value)
    claim.full_clean();claim.save();claim.findings.set(findings);claim.evidence.set(evidence)
    observe(claim,'Supplier claim draft prepared from reviewed findings')
    return claim


def transition(record_id,data):
    body(data,('revision','status','notes','accepted_amount','follow_up_date'))
    with locked(record_id,data) as claim:
        status=data.get('status');notes=text(data.get('notes'),'status explanation')
        if status not in TRANSITIONS[claim.status]:raise ValidationError('Unsupported supplier claim transition.')
        if status=='accepted':claim.accepted_amount=amount(data.get('accepted_amount'))
        if status=='submitted' and not claim.submission_date:claim.submission_date=timezone.localdate()
        if data.get('follow_up_date'):claim.follow_up_date=date_value(data['follow_up_date'])
        claim.status=status;claim.resolution_notes=notes
        if status=='waiting':claim.closed_at=None
        claim.full_clean();claim.save();observe(claim,'Supplier claim status changed')
        return claim


def correspond(record_id,data):
    body(data,('revision','direction','subject','message','occurred_at','actor_label','source_document_id'))
    with locked(record_id,data) as claim:
        occurred=parse_datetime(data.get('occurred_at',''))
        if occurred is None or timezone.is_naive(occurred):raise ValidationError('Provide the correspondence time with a timezone.')
        item=ClaimCorrespondence(claim=claim,direction=data.get('direction'),subject=text(data.get('subject'),'subject',200),
            message=text(data.get('message'),'correspondence',10000),occurred_at=occurred,actor_label=text(data.get('actor_label',''),'unverified staff label',150,required=False),source_document_id=data.get('source_document_id'))
        item.save();claim.save()  # advances the shared stale-update token
        record_transition(claim.ap_transaction,'claim_correspondence','Supplier correspondence logged (not sent)',item._meta.label,item.pk,
            dict(claim_id=claim.pk,direction=item.direction,subject=item.subject,message=item.message,actor_label=item.actor_label,source_document_id=item.source_document_id),occurred_at=occurred)
        return claim


def resolve(record_id,data):
    body(data,('revision','resolution_type','notes','application_id','document_id'))
    with locked(record_id,data) as claim:
        kind=data.get('resolution_type');notes=text(data.get('notes'),'resolution explanation')
        if kind=='credit_verified':
            if claim.status!='accepted' or not claim.accepted_amount:raise ValidationError('Record supplier acceptance before verifying a credit settlement.')
            application=get_object_or_404(SupplierCreditApplication.objects.select_related('credit'),pk=data.get('application_id'))
            if (hasattr(application,'reversal') or application.credit.status!='verified' or application.credit.supplier_id!=claim.supplier_id or application.credit.currency!=claim.currency or application.amount<claim.accepted_amount or not claim.ap_transaction.sales_invoices.filter(pk=application.invoice_id).exists()):raise ValidationError('Choose an active verified credit application covering the accepted amount on a case invoice.')
            claim.settlement_application=application
        elif kind=='replacement_verified':
            if claim.status!='accepted' or claim.findings.filter(status='open').exists():raise ValidationError('Verify the source correction and clear the claimed discrepancies before closing with replacement evidence.')
            if not claim.ap_transaction.delivery_receipts.filter(source_document_id=data.get('document_id')).exists() or not data.get('document_id'):raise ValidationError('Choose a current linked receiving document.')
            claim.replacement_document_id=data['document_id']
        elif kind=='no_recovery':
            if claim.status!='rejected':raise ValidationError('Record rejection before closing without recovery.')
        else:raise ValidationError('Choose a supported documented resolution.')
        claim.status='resolved';claim.resolution_type=kind;claim.resolution_notes=notes;claim.closed_at=timezone.now();claim.review_required=False
        claim.full_clean();claim.save();observe(claim,'Supplier claim closed with documented evidence')
        return claim


def flag_reversed_application(application):
    claim=SupplierClaim.objects.select_for_update().filter(settlement_application=application,status='resolved',review_required=False).first()
    if claim:
        claim.review_required=True;claim.save();observe(claim,'Claim settlement evidence was reversed; renewed review required')


def serialize(claim):
    return {**claim_state(claim),'revision':revision(claim),'findings':list(claim.findings.values_list('pk',flat=True)),
        'evidence_ids':list(claim.evidence.values_list('pk',flat=True)),
        'correspondence':list(claim.correspondence.order_by('pk').values('direction','subject','message','occurred_at','actor_label','source_document_id')),
        'draft':f'Claim {claim.reference}\nSupplier: {claim.supplier.supplier_name}\nCase: AP-{claim.ap_transaction_id}\nCategory: {claim.category}\nRequested amount: {claim.currency} {claim.claimed_amount}\nPlease review the referenced findings and supporting documents. This draft has not been sent.'}


def flag_changed_claim_resolutions(case):
    """Retain closure records while flagging lost or contradictory settlement evidence."""
    if case._meta.app_label != 'accounts_payable':
        return
    for claim in case.supplier_claims.filter(status='resolved',review_required=False).select_related('settlement_application__credit'):
        valid=True
        if claim.resolution_type=='credit_verified':
            application=claim.settlement_application
            valid=bool(application and not hasattr(application,'reversal') and application.credit.status=='verified'
                and application.credit.currency==claim.currency and application.credit.supplier_id==claim.supplier_id
                and application.amount >= claim.accepted_amount and case.sales_invoices.filter(pk=application.invoice_id).exists())
        elif claim.resolution_type=='replacement_verified':
            valid=not claim.findings.filter(status='open').exists() and case.delivery_receipts.filter(source_document_id=claim.replacement_document_id).exists()
        if not valid:
            claim.review_required=True;claim.save();observe(claim,'Claim resolution evidence changed; renewed review required')
