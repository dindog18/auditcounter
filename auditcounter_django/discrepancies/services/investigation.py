"""Human workflow writes; deterministic accounting state is never assigned here."""
from contextlib import contextmanager
from importlib import import_module

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts_receivable.services.catalog import party_key, model, revision
from accounts_receivable.services.records import case_membership, matches
from accounts_receivable.services.auto_matching import mode_for, source_revision
from ..models import CaseInvestigation, CaseActivity, DiscrepancyFinding, FindingEvidence
from ..evaluation import json_value, source_evidence, allocation_evidence
from . import case_filter, digest

CLOSED = {'resolved','dismissed'}
TRANSITIONS = {'needs_review':{'investigating','dismissed'}, 'investigating':{'waiting','resolved','dismissed'},
               'waiting':{'investigating'}, 'resolved':{'needs_review'}, 'dismissed':{'needs_review'}}
CORRECTIONS = {'source_correction_verified','corrective_document_verified'}


def text(data, name, *, required=False, limit=10000):
    value = data.get(name,'')
    if name=='actor_label' and value is None:
        value=''
    if not isinstance(value,str) or len(value)>limit:
        raise ValidationError(f'{name.replace("_"," ").title()} must be text of at most {limit} characters.')
    value = value.strip()
    if required and not value:
        raise ValidationError(f'{name.replace("_"," ").title()} is required.')
    return value


def validate_body(data, allowed):
    if not isinstance(data,dict) or set(data)-set(allowed)-{'revision','actor_label'}:
        raise ValidationError('Unsupported investigation fields.')
    text(data,'actor_label',limit=150)


def finding_state(finding):
    return json_value({field:getattr(finding,field) for field in ('fingerprint','finding_code','summary','status','severity','expected_value','actual_value','difference_amount','currency','rule_version','identity','details')})


def finding_basis(finding):
    return digest({'finding':finding_state(finding),'evidence':list(finding.evidence.order_by('snapshot_hash').values_list('snapshot_hash',flat=True))})


def evidence_state(case):
    """Financial/receiving evidence, excluding clock-only refreshes and human decisions."""
    documents = []
    for relation in ('purchase_orders','delivery_receipts','sales_invoices'):
        for document in getattr(case,relation).order_by('pk'):
            documents.append(source_evidence(document))
            documents.extend(source_evidence(document,line) for line in document.lines.order_by('pk'))
    allocations = matches(case)
    allocations.sort(key=lambda row:(row['invoice_line_id'],row['purchase_order_line_id'] or 0,row['delivery_receipt_line_id'] or 0))
    from sku_matching.services.mapping import approved_catalog_state
    return digest(dict(sku_mappings=approved_catalog_state(case),scope=case._meta.label,case_id=case.pk,currency=case.currency,documents=documents,allocations=allocations,
        findings=[finding_state(finding) for finding in case.discrepancy_findings.order_by('fingerprint')]))


def investigation_revision(case, investigation=None):
    if investigation is None:
        investigation = CaseInvestigation.objects.filter(**case_filter(case)).first()
    findings = [dict(id=finding.pk,basis=finding_basis(finding),decision=finding.review_decision,notes=finding.review_notes,
                     reviewed_at=finding.reviewed_at,review_basis=finding.review_basis) for finding in case.discrepancy_findings.order_by('pk')]
    return digest(dict(case_revision=revision(case,[case_membership(case),matches(case)]),source_revision=source_revision(case),
                       investigation_revision=revision(investigation) if investigation else None,findings=findings,
                       latest_activity=investigation.activities.order_by('-pk').values_list('pk',flat=True).first() if investigation else None))


@contextmanager
def locked_workflow(case, data, *, allow_missing=False, lock_sources=False):
    with transaction.atomic():
        # Same lock order as existing matching: account -> case -> source evidence.
        Case = type(case)
        account_id = getattr(case,party_key(mode_for(case))+'_id')
        if account_id:
            model(mode_for(case),party_key(mode_for(case))).objects.select_for_update().get(pk=account_id)
        case = Case.objects.select_for_update().get(pk=case.pk)
        if lock_sources:
            source_revision(case,lock=True)
        investigation = CaseInvestigation.objects.select_for_update().filter(**case_filter(case)).first()
        if not (allow_missing and investigation is not None) and data.get('revision') != investigation_revision(case,investigation):
            raise ValidationError('This investigation or its evidence changed. Reload before saving.',code='conflict')
        if investigation is None and not allow_missing:
            raise ValidationError('Start an investigation first.')
        yield case,investigation


def append_activity(investigation, kind, data, *, notes='', finding=None, previous=None, details=None):
    return CaseActivity.objects.create(investigation=investigation,activity_type=kind,finding=finding,
        previous_status=previous if previous is not None else investigation.workflow_status,
        new_status=investigation.workflow_status,notes=notes,actor_label=text(data,'actor_label',limit=150),details=json_value(details or {}))


def start_investigation(case, data):
    validate_body(data,())
    with locked_workflow(case,data,allow_missing=True) as (case,investigation):
        if investigation is not None:
            return investigation
        investigation=CaseInvestigation.objects.create(**case_filter(case))
        append_activity(investigation,'opened',data,notes='Investigation opened.',previous='')
        return investigation


def update_investigation(case, data):
    validate_body(data,('workflow_status','responsible_department','next_action','notes'))
    with locked_workflow(case,data) as (case,investigation):
        if investigation.workflow_status in CLOSED:
            raise ValidationError('Reopen this investigation before changing its workflow.')
        previous = investigation.workflow_status
        requested = data.get('workflow_status',previous)
        if not isinstance(requested,str) or (requested!=previous and requested not in TRANSITIONS[previous]):
            raise ValidationError('Unsupported investigation status transition.')
        if requested in CLOSED:
            raise ValidationError('Use a documented resolution to close the investigation.')
        old = dict(workflow_status=previous,responsible_department=investigation.responsible_department,next_action=investigation.next_action)
        investigation.workflow_status=requested
        if 'responsible_department' in data:
            investigation.responsible_department=text(data,'responsible_department',limit=120)
        if 'next_action' in data:
            investigation.next_action=text(data,'next_action',limit=2000)
        new = {field:getattr(investigation,field) for field in old}
        if old!=new:
            investigation.full_clean()
            investigation.save()
            append_activity(investigation,'status_change' if requested!=previous else 'update',data,
                notes=text(data,'notes'),previous=previous,details={'previous':old,'current':new})
        return investigation


def add_investigation_note(case, data):
    validate_body(data,('notes',))
    note=text(data,'notes',required=True)
    with locked_workflow(case,data) as (case,investigation):
        append_activity(investigation,'note',data,notes=note)
        investigation.save(update_fields=['updated_at'])
        return investigation


def review_finding(case, data):
    validate_body(data,('finding_id','decision','notes'))
    decision=data.get('decision')
    if not isinstance(decision,str) or decision not in DiscrepancyFinding.Review.values:
        raise ValidationError('Choose a valid finding review decision.')
    if type(data.get('finding_id')) is not int:
        raise ValidationError('Choose a valid finding ID.')
    notes=text(data,'notes',required=decision=='dismissed')
    with locked_workflow(case,data) as (case,investigation):
        if investigation.workflow_status in CLOSED:
            raise ValidationError('Reopen this investigation before reviewing findings.')
        finding=DiscrepancyFinding.objects.select_for_update().filter(**case_filter(case),pk=data['finding_id']).first()
        if finding is None:
            raise ValidationError('The finding does not belong to this investigation case.')
        previous=finding.review_decision
        finding.review_decision, finding.review_notes, finding.reviewed_at=decision,notes,timezone.now()
        finding.review_basis=finding_basis(finding) if decision!='unreviewed' else ''
        finding.save(update_fields=['review_decision','review_notes','reviewed_at','review_basis'])
        from .analytics import flag_stale_causes
        flag_stale_causes(case)
        append_activity(investigation,'review',data,notes=notes,finding=finding,details=dict(previous_decision=previous,
            decision=decision,finding=finding_state(finding),review_basis=finding.review_basis,
            evidence_ids=list(finding.evidence.values_list('pk',flat=True))))
        investigation.save(update_fields=['updated_at'])
        return investigation


def resolve_references(case, data, *, require_current):
    ids=data.get('evidence_ids',[])
    refs=data.get('document_references',[])
    if not isinstance(ids,list) or not isinstance(refs,list) or len(ids)+len(refs)>100 or any(type(pk) is not int for pk in ids) or len(set(ids))!=len(ids):
        raise ValidationError('Choose up to 100 valid evidence/document references without duplicates.')
    resolved=[]
    for pk in ids:
        item=FindingEvidence.objects.select_related('finding').filter(pk=pk,**{'finding__'+field:case for field in case_filter(case)}).first()
        if item is None:
            raise ValidationError('Resolution evidence must belong to this case.')
        if require_current and not evidence_is_current(case,item):
            raise ValidationError('A correction requires current evidence; the selected snapshot is historical or no longer linked.')
        resolved.append(dict(kind='finding_evidence',evidence_id=pk,finding_id=item.finding_id,snapshot_hash=item.snapshot_hash,
            source=dict(source_model=item.source_model,source_record_id=item.source_record_id,source_line_id=item.source_line_id,
                provenance=item.provenance,observed_value=item.observed_value,source_record_key=item.source_record_key)))
    seen=set()
    for ref in refs:
        if not isinstance(ref,dict) or set(ref)-{'kind','record_id','line_id'} or not isinstance(ref.get('kind'),str) or ref.get('kind') not in {'purchase_order','delivery_receipt','sales_invoice'} or type(ref.get('record_id')) is not int or ('line_id' in ref and type(ref['line_id']) is not int):
            raise ValidationError('Choose valid linked PO, DR or SI document references.')
        key=(ref['kind'],ref['record_id'],ref.get('line_id'))
        if key in seen:
            raise ValidationError('Duplicate resolution document reference.')
        seen.add(key)
        relation={'purchase_order':'purchase_orders','delivery_receipt':'delivery_receipts','sales_invoice':'sales_invoices'}[ref['kind']]
        document=getattr(case,relation).filter(pk=ref['record_id']).first()
        if document is None:
            raise ValidationError('Resolution documents must be linked to this reconciliation case.')
        party=party_key(mode_for(case))+'_id'
        if getattr(document,party)!=getattr(case,party) or (hasattr(document,'currency') and document.currency!=case.currency):
            raise ValidationError('Resolution document party and currency must match the case.')
        line=document.lines.filter(pk=ref['line_id']).first() if 'line_id' in ref else None
        if 'line_id' in ref and line is None:
            raise ValidationError('Resolution line must belong to the selected document.')
        resolved.append(dict(kind='document',reference=ref,source=source_evidence(document,line),
            lines=[source_evidence(document,item) for item in document.lines.order_by('pk')] if line is None else []))
    return resolved


def evidence_is_current(case, item):
    if item.finding_snapshot.get('status')!=item.finding.status:
        return False
    if item.field_name in ('statement','deduction','settlement'):
        from . import current_evidence
        return any(row['source_model']==item.source_model and row['source_record_id']==item.source_record_id and row['observed_value']==item.observed_value for row in current_evidence(case,item.finding))
    if item.evidence_type=='ALLOCATION':
        fields={field:item.observed_value[field] for field in ('invoice_line_id','purchase_order_line_id','delivery_receipt_line_id')}
        match=case.line_matches.filter(**fields).first()
        return match is not None and allocation_evidence(match)['observed_value']==item.observed_value
    relation={'PO':'purchase_orders','DR':'delivery_receipts','SI':'sales_invoices'}.get(item.evidence_type)
    document=getattr(case,relation).filter(pk=item.source_record_id).first() if relation else None
    if document is None or document._meta.label!=item.source_model:
        return False
    line=document.lines.filter(pk=item.source_line_id).first() if item.source_line_id else None
    if item.source_line_id and line is None:
        return False
    current=source_evidence(document,line)
    return all(current[field]==getattr(item,field) for field in ('observed_value','provenance','source_record_key'))


def resolve_investigation(case, data):
    validate_body(data,('workflow_status','resolution_type','resolution_notes','evidence_ids','document_references'))
    resolution_type=data.get('resolution_type')
    if not isinstance(resolution_type,str) or resolution_type not in CaseInvestigation.Resolution.values:
        raise ValidationError('Choose a resolution type.')
    notes=text(data,'resolution_notes',required=True)
    requested=data.get('workflow_status','resolved')
    if not isinstance(requested,str) or requested not in CLOSED:
        raise ValidationError('Choose resolved or dismissed for closure.')
    with locked_workflow(case,data,lock_sources=True) as (case,investigation):
        previous=investigation.workflow_status
        if previous in CLOSED or requested not in TRANSITIONS[previous]:
            raise ValidationError('Unsupported investigation closure transition.')
        service=import_module(f'{case._meta.app_label}.services.reconciliation')
        evaluation=service.evaluate_reconciliation(case)  # Read-only: human decisions never assign accounting statuses.
        active=list(case.discrepancy_findings.filter(status='open'))
        from . import evaluate_findings
        live={digest({'code':item['finding_code'],'identity':item['identity']}):item for item in evaluate_findings(case,evaluation)}
        stored={digest({'code':item.finding_code,'identity':item.identity}):item for item in active}
        comparison_fields=('finding_code','summary','severity','expected_value','actual_value','difference_amount','currency','rule_version','identity','details')
        stale=set(live)!=set(stored)
        if not stale:
            stale=any(json_value({field:live[key][field] for field in comparison_fields}) !=
                      json_value({field:getattr(stored[key],field) for field in comparison_fields}) for key in live)
        if stale:
            raise ValidationError('Findings are not current. Recalculate this case before closing the investigation.',code='conflict')
        correction=resolution_type in CORRECTIONS
        references=resolve_references(case,data,require_current=correction)
        if correction:
            if not references:
                raise ValidationError('Correction-based resolutions require supporting evidence references.')
            if evaluation['status']!='matched' or active:
                raise ValidationError('A verified correction requires current reconciliation to match with no open findings.')
        else:
            if any(item.review_decision not in {'confirmed','dismissed'} or item.review_basis!=finding_basis(item) for item in active):
                raise ValidationError('Review every open finding using current evidence before closing.')
            if resolution_type=='false_positive' and any(item.review_decision!='dismissed' for item in active):
                raise ValidationError('A false-positive resolution requires open findings to be dismissed with explanations.')
        investigation.workflow_status=requested
        investigation.resolution_type=resolution_type
        investigation.resolution_notes=notes
        investigation.resolution_evidence=references
        investigation.resolution_basis=evidence_state(case)
        investigation.closed_at=timezone.now()
        investigation.review_required,investigation.review_reason=False,''
        investigation.full_clean()
        investigation.save()
        append_activity(investigation,'resolution',data,notes=notes,previous=previous,details=dict(resolution_type=resolution_type,
            resolution_notes=notes,evidence=references,resolution_basis=investigation.resolution_basis,
            closed_at=investigation.closed_at,findings=[dict(finding=finding_state(item),review_decision=item.review_decision,review_notes=item.review_notes) for item in case.discrepancy_findings.order_by('pk')]))
        return investigation


def reopen_investigation(case, data):
    validate_body(data,('reason',))
    reason=text(data,'reason',required=True)
    with locked_workflow(case,data) as (case,investigation):
        previous=investigation.workflow_status
        if previous not in CLOSED:
            raise ValidationError('Only closed investigations can be reopened.')
        resolution=dict(resolution_type=investigation.resolution_type,resolution_notes=investigation.resolution_notes,
                        evidence=investigation.resolution_evidence,closed_at=investigation.closed_at)
        investigation.workflow_status='needs_review'
        investigation.closed_at=None
        investigation.review_required,investigation.review_reason=False,''
        investigation.save(update_fields=['workflow_status','closed_at','review_required','review_reason','updated_at'])
        append_activity(investigation,'reopening',data,notes=reason,previous=previous,details={'previous_resolution':resolution})
        return investigation


def flag_changed_resolution(case):
    """Called after deterministic synchronization, never changes automatic finding/reconciliation state."""
    investigation=CaseInvestigation.objects.select_for_update().filter(**case_filter(case),workflow_status__in=CLOSED,review_required=False).first()
    if investigation is None or not investigation.resolution_basis:
        return
    current=evidence_state(case)
    if current!=investigation.resolution_basis:
        investigation.review_required=True
        investigation.review_reason='Reconciliation evidence changed after closure. Review the findings and reopen if needed.'
        investigation.save(update_fields=['review_required','review_reason','updated_at'])
        append_activity(investigation,'evidence_changed',{},notes=investigation.review_reason,
                        details={'previous_basis':investigation.resolution_basis,'current_basis':current})
