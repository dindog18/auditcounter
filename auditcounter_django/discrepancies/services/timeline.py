"""Append-only observations and read-only aggregation of existing evidence/history."""
import json
from datetime import datetime
from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from ..models import CaseTimelineEvent,CaseActivity,DiscrepancyFinding
from ..evaluation import json_value,source_evidence
from . import case_filter,digest

CATEGORIES={'case_created':'documents','documents_changed':'documents','source_changed':'documents','matches_changed':'matching','payments_changed':'payments','reconciliation_changed':'discrepancies'}
CATEGORIES.update({key:'discrepancies' for key in ('finding_detected','finding_changed','finding_cleared','finding_reopened')})

@transaction.atomic
def record_transition(case,event_type,description,source_model,source_record_id,after,*,occurred_at=None,evidence_hash='',idempotency_key=None,before=None):
    if event_type not in CATEGORIES or not isinstance(description,str) or not description or len(description)>500:
        raise ValidationError('Invalid timeline event type or description.')
    if not isinstance(source_model,str) or not source_model or len(source_model)>150 or source_record_id is None or not str(source_record_id) or len(str(source_record_id))>100:
        raise ValidationError('Invalid timeline source.')
    if occurred_at is not None and (not isinstance(occurred_at,datetime) or timezone.is_naive(occurred_at)):
        raise ValidationError('Business timestamps must include a timezone.')
    if evidence_hash and (len(evidence_hash)!=64 or any(c not in '0123456789abcdef' for c in evidence_hash)):
        raise ValidationError('Invalid evidence hash.')
    if case._meta.label not in ('accounts_payable.Transaction','accounts_receivable.Transaction') or not case.pk:
        raise ValidationError('Choose an existing AP/AR case.')
    after=json_value(after)
    before=json_value(before)
    try:
        valid=isinstance(after,dict) and len(json.dumps(after,allow_nan=False))<=262144 and (before is None or isinstance(before,dict) and len(json.dumps(before,allow_nan=False))<=262144)
    except (TypeError,ValueError):valid=False
    if not valid:raise ValidationError('Timeline details must be bounded, valid structured JSON.')
    type(case).objects.select_for_update().get(pk=case.pk)
    rows=CaseTimelineEvent.objects.filter(**case_filter(case))
    if idempotency_key is not None:
        key=digest(['request',event_type,source_model,str(source_record_id),idempotency_key])
        existing=rows.filter(event_key=key).first()
        if existing:
            if existing.details['after']!=after:raise ValidationError('Idempotency key reused with different evidence.',code='conflict')
            return existing
    previous=rows.filter(source_model=source_model,source_record_id=str(source_record_id),event_type__in=[event_type] if not event_type.startswith('finding_') else [key for key in CATEGORIES if key.startswith('finding_')]).order_by('-pk').first()
    if previous and previous.details['after']==after:return previous
    if idempotency_key is None:key=digest([event_type,source_model,str(source_record_id),previous.pk if previous else None,after])
    return CaseTimelineEvent.objects.create(**case_filter(case),event_type=event_type,event_key=key,description=description,source_model=source_model,source_record_id=str(source_record_id),occurred_at=occurred_at,details={'before':json_value(before) if before is not None else previous.details['after'] if previous else None,'after':after},evidence_snapshot_hash=evidence_hash)


def lock_account(record):
    """Reuse accounting's account-first order before payment/invoice/case row locks."""
    from accounts_receivable.services.catalog import model,party_key
    mode='ap' if record._meta.app_label=='accounts_payable' else 'ar'
    key=party_key(mode)
    account_id=getattr(record,key+'_id')
    if account_id:model(mode,key).objects.select_for_update().filter(pk=account_id).first()


def observe_case(case):
    """Called only by existing atomic write/refresh paths, never by timeline reads."""
    from accounts_receivable.services.records import case_membership,matches
    memberships=case_membership(case)
    record_transition(case,'documents_changed','Linked document membership observed',case._meta.label,str(case.pk),memberships)
    logical=matches(case)
    logical.sort(key=lambda row:json.dumps(json_value(row),sort_keys=True))
    if logical or case.timeline_events.filter(event_type='matches_changed').exists():
        record_transition(case,'matches_changed','Line matching allocations observed',case._meta.label,str(case.pk),{'allocations':logical})
    for relation in memberships:
        for document in getattr(case,relation).order_by('pk'):
            for line in [None,*document.lines.order_by('pk')]:
                observed=source_evidence(document,line)
                if line:observed['observed_value']['line']['description']=line.description[:2000]
                else:observed['observed_value']['line_numbers']=list(document.lines.order_by('line_no').values_list('line_no',flat=True))
                record_transition(case,'source_changed','Accounting source evidence observed',document._meta.label,f'{document.pk}:{line.pk if line else "header"}',{'values':observed['observed_value'],'document_id':document.source_document_id,'database_id':document.source_database_id})
    payments=[]
    for invoice in case.sales_invoices.order_by('pk'):
        for allocation in invoice.payment_allocations.select_related('payment').order_by('payment_id'):
            payment=allocation.payment
            payments.append(dict(invoice_id=invoice.pk,payment_id=payment.pk,reference=payment.payment_reference_no,status=payment.payment_status,invoice_payment_status=invoice.payment_status,currency=payment.currency,date=payment.payment_date,payment_amount=getattr(payment,'amount_paid',getattr(payment,'amount_received',None)),payment_withholding=payment.withholding_tax_amount,payment_discount=payment.discount_taken,source_document_id=payment.source_document_id,cash=allocation.cash_amount,withholding=allocation.withholding_tax_amount,discount=allocation.discount_amount))
    if payments or case.timeline_events.filter(event_type='payments_changed').exists():
        record_transition(case,'payments_changed','Payment allocation and supporting payment state observed',case._meta.label,str(case.pk),{'allocations':payments})


def observe_payment(payment):
    from accounts_receivable.services.catalog import model
    mode='ap' if payment._meta.app_label=='accounts_payable' else 'ar'
    for case in model(mode,'Transaction').objects.filter(sales_invoices__payment_allocations__payment=payment).distinct().order_by('pk'):
        observe_invoice_cases(case)


def observe_invoice_cases(case):
    from . import _pending
    pending=_pending.get()
    if pending is not None:pending[(case._meta.label,case.pk)]=case
    else:observe_case(case)


def finding_state(finding):
    return json_value({name:getattr(finding,name) for name in ('finding_code','status','severity','summary','expected_value','actual_value','difference_amount','currency','rule_version','identity','details')})


def finding_event(case,finding,kind,before=None):
    latest=finding.evidence.order_by('-pk').first()
    return record_transition(case,kind,finding.summary[:500],finding._meta.label,finding.pk,finding_state(finding),evidence_hash=latest.snapshot_hash if latest else '',before=before)


def timeline(case,category='',page=1,page_size=25):
    """Historical observations retain their real timestamps; no backfill or writes."""
    mode='ap' if case._meta.app_label=='accounts_payable' else 'ar'
    namespace='ACCOUNTS_PAYABLE' if mode=='ap' else 'ACCOUNTS_RECEIVABLE'
    detail=reverse(namespace+':reconciliation_detail',args=[case.pk])
    events=[]
    findings={str(f.pk):f for f in case.discrepancy_findings.prefetch_related('evidence')} if category in ('','discrepancies') else {}
    source_links={}
    def evidence_link(evidence):
        from ..presentation import source_url
        key=(evidence.evidence_type,evidence.source_model,evidence.source_record_id)
        if key not in source_links:source_links[key]=source_url(evidence)
        return source_links[key]
    def evidence_for(finding,recorded=None):
        return [dict(id=e.pk,hash=e.snapshot_hash,recordedAt=e.captured_at,observed=e.observed_value,findingSnapshot=e.finding_snapshot,documentUrl=reverse('DOC_EXTRACTION:document_detail',args=[e.source_document_id]) if e.source_document_id else None,databaseUrl=reverse('DB_EXTRACTION:source_detail',args=[e.source_database_id]) if e.source_database_id else None,sourceModel=e.source_model,sourceRecordId=e.source_record_id,sourceLineId=e.source_line_id,recordUrl=evidence_link(e),sourceRecordKey=e.source_record_key,provenance=e.provenance) for e in finding.evidence.all() if recorded is None or e.captured_at<=recorded]
    automatic=case.timeline_events.order_by('recorded_at','pk')
    if category:automatic=automatic.filter(event_type__in=[kind for kind,group in CATEGORIES.items() if group==category])
    for event in automatic:
        finding=findings.get(event.source_record_id) if event.source_model==DiscrepancyFinding._meta.label else None
        source_url=detail+(f'#finding-{finding.pk}' if finding else '')
        evidence=evidence_for(finding,event.recorded_at) if finding else []
        if event.event_type=='source_changed':
            name=event.source_model.rsplit('.',1)[-1].lower()
            route='purchase_order' if 'purchaseorder' in name else 'delivery_receipt' if 'deliveryreceipt' in name else 'invoice'
            source_url=reverse(namespace+':'+route+'_detail',args=[int(event.source_record_id.split(':')[0])])
            doc_id=event.details['after'].get('document_id')
            if doc_id:evidence=[{'documentUrl':reverse('DOC_EXTRACTION:document_detail',args=[doc_id]),'observed':event.details['after']}]
        if event.event_type=='payments_changed':
            linked={row['payment_id']:row for state in (event.details['before'] or {},event.details['after']) for row in state.get('allocations',[])}
            evidence=[dict(recordUrl=reverse(namespace+':payment_detail',args=[pk]),observed=row) for pk,row in linked.items()]
        events.append(dict(id=f'event:{event.pk}',type=event.event_type,category=CATEGORIES[event.event_type],title=(CATEGORIES[event.event_type].title()+' baseline observed') if event.details['before'] is None and event.event_type in ('source_changed','matches_changed','documents_changed','payments_changed') else event.get_event_type_display(),description=event.description,occurredAt=event.occurred_at,recordedAt=event.recorded_at,source=dict(type=event.source_model,id=event.source_record_id,url=source_url),details=event.details,evidence=evidence))
    investigation=getattr(case,'investigation',None)
    if investigation and category in ('','investigations'):
        for activity in investigation.activities.order_by('created_at','pk'):
            events.append(dict(id=f'activity:{activity.pk}',type=activity.activity_type,category='investigations',title=activity.get_activity_type_display(),description=activity.notes,occurredAt=None,recordedAt=activity.created_at,source=dict(type='CaseActivity',id=activity.pk,url=detail+(f'#finding-{activity.finding_id}' if activity.finding_id else '')),details=dict(findingId=activity.finding_id,previousStatus=activity.previous_status,newStatus=activity.new_status,actorLabel=activity.actor_label,actorVerified=False,**activity.details),evidence=[]))
    tracked={(str(row.source_record_id),row.event_type) for row in case.timeline_events.filter(event_type__startswith='finding_')}
    for finding in findings.values():
        for kind,stamp in [('finding_detected',finding.first_detected_at),('finding_cleared',finding.cleared_at)]:
            if stamp and (str(finding.pk),kind) not in tracked:events.append(dict(id=f'legacy:{finding.pk}:{kind}',type=kind,category='discrepancies',title='Historical finding '+kind.split('_')[1],description='Historical finding lifecycle recorded; preserved snapshots show the available observations.',occurredAt=None,recordedAt=stamp,source=dict(type='DiscrepancyFinding',id=finding.pk,url=detail+f'#finding-{finding.pk}'),details={'historical':True,'findingCode':finding.finding_code},evidence=evidence_for(finding)))
    for relation,field,ref,route in [('purchase_orders','order_date','po_reference_no','purchase_order'),('delivery_receipts','delivery_date','dr_reference_no','delivery_receipt'),('sales_invoices','invoice_date','invoice_reference_no','invoice')]:
        for document in (getattr(case,relation).all() if category in ('','documents') else []):
            events.append(dict(id=f'document:{relation}:{document.pk}',type='document_reference',category='documents',title='Linked document business date',description=getattr(document,ref),occurredAt=str(getattr(document,field)) if getattr(document,field) else None,recordedAt=document.created_at,source=dict(type=document._meta.label,id=document.pk,url=reverse(namespace+':'+route+'_detail',args=[document.pk])),details={'historical':True,'businessDateOnly':True},evidence=[]))
    payments={}
    for invoice in (case.sales_invoices.prefetch_related('payment_allocations__payment') if category in ('','payments') else []):
        for allocation in invoice.payment_allocations.all():payments[allocation.payment_id]=allocation.payment
    for payment in payments.values():
        events.append(dict(id=f'payment:{payment.pk}',type='payment_reference',category='payments',title='Linked payment record',description=payment.payment_reference_no,occurredAt=str(payment.payment_date) if payment.payment_date else None,recordedAt=payment.created_at,source=dict(type=payment._meta.label,id=payment.pk,url=reverse(namespace+':payment_detail',args=[payment.pk])),details={'historical':True,'currentRecordedStatus':payment.payment_status,'currency':payment.currency,'notRecoveryEvidence':True},evidence=[]))
    if category:events=[event for event in events if event['category']==category]
    events.sort(key=lambda event:(event['recordedAt'].isoformat() if event['recordedAt'] else '',event['id']),reverse=True)
    total=len(events)
    from ..presentation import timeline_case_reference
    return dict(case=timeline_case_reference(case),results=events[(page-1)*page_size:page*page_size],page=page,page_size=page_size,total=total,historyMayBeIncomplete=True)
