"""Serialize persisted findings without recalculating or writing on page reads."""
from django.apps import apps
from django.urls import reverse


def source_url(evidence):
    if evidence.evidence_type == 'ALLOCATION':
        label = evidence.provenance.get('transaction_model','')
        app, _, _ = label.partition('.')
        record_id = evidence.provenance.get('transaction_id')
        resource = 'reconciliation'
    else:
        app, _, _ = evidence.source_model.partition('.')
        record_id = evidence.source_record_id
        resource = {'PO':'purchase_order','DR':'delivery_receipt','SI':'invoice'}.get(evidence.evidence_type)
    namespace = {'accounts_payable':'ACCOUNTS_PAYABLE','accounts_receivable':'ACCOUNTS_RECEIVABLE'}.get(app)
    if not namespace or not resource or not str(record_id).isdigit():
        return None
    if evidence.evidence_type != 'ALLOCATION':
        try:
            if not apps.get_model(evidence.source_model).objects.filter(pk=record_id).exists():
                return None
        except LookupError:
            return None
    return reverse(f'{namespace}:{resource}_detail', args=[record_id])


def serialize_findings(case):
    from .services.investigation import finding_basis
    output = []
    for finding in case.discrepancy_findings.prefetch_related('evidence').order_by('-status','first_detected_at','pk'):
        evidence = []
        for item in finding.evidence.all():
            evidence.append(dict(id=item.pk, type=item.evidence_type, sourceModel=item.source_model,
                recordId=item.source_record_id, lineId=item.source_line_id, recordUrl=source_url(item),
                reference=next((item.observed_value[field] for field in ('invoice_reference_no','po_reference_no','dr_reference_no') if item.observed_value.get(field)), 'Allocation' if item.evidence_type=='ALLOCATION' else item.source_record_id),
                lineNo=item.observed_value.get('line',{}).get('line_no'),
                documentUrl=f'/documents/{item.source_document_id}/' if item.source_document_id else None,
                databaseUrl=f'/databases/{item.source_database_id}/' if item.source_database_id else None,
                sourceKey=item.source_record_key, provenance=item.provenance, field=item.field_name,
                observed=item.observed_value, findingSnapshot=item.finding_snapshot, capturedAt=item.captured_at.isoformat()))
        output.append(dict(id=finding.pk, code=finding.finding_code, severity=finding.severity, status=finding.status,
            reviewDecision=finding.review_decision,reviewNotes=finding.review_notes,
            reviewedAt=finding.reviewed_at.isoformat() if finding.reviewed_at else None,
            reviewStale=finding.review_decision!='unreviewed' and finding.review_basis!=finding_basis(finding),
            summary=finding.summary, expected=finding.expected_value, actual=finding.actual_value,
            difference=str(finding.difference_amount) if finding.difference_amount is not None else None,
            currency=finding.currency, ruleVersion=finding.rule_version, details=finding.details,
            firstDetectedAt=finding.first_detected_at.isoformat(), lastDetectedAt=finding.last_detected_at.isoformat(),
            clearedAt=finding.cleared_at.isoformat() if finding.cleared_at else None, evidence=evidence))
    return output


def serialize_investigation(case):
    from .models import CaseInvestigation
    from .services import case_filter
    from .services.investigation import investigation_revision, TRANSITIONS, CLOSED
    investigation=CaseInvestigation.objects.filter(**case_filter(case)).first()
    token=investigation_revision(case,investigation)
    if investigation is None:
        return None,token
    closed=investigation.workflow_status in CLOSED
    history=[dict(id=activity.pk,type=activity.activity_type,findingId=activity.finding_id,
        previousStatus=activity.previous_status,newStatus=activity.new_status,notes=activity.notes,
        actorLabel=activity.actor_label,details=activity.details,createdAt=activity.created_at.isoformat())
        for activity in investigation.activities.order_by('created_at','pk')]
    return dict(id=investigation.pk,workflowStatus=investigation.workflow_status,
        responsibleDepartment=investigation.responsible_department,nextAction=investigation.next_action,
        resolutionType=investigation.resolution_type,resolutionNotes=investigation.resolution_notes,
        resolutionEvidence=investigation.resolution_evidence,openedAt=investigation.opened_at.isoformat(),
        updatedAt=investigation.updated_at.isoformat(),closedAt=investigation.closed_at.isoformat() if investigation.closed_at else None,
        reviewRequired=investigation.review_required,reviewReason=investigation.review_reason,closed=closed,
        availableStatuses=[investigation.workflow_status]+sorted(TRANSITIONS[investigation.workflow_status]-CLOSED-{'needs_review'}),
        closureStatuses=sorted(TRANSITIONS[investigation.workflow_status]&CLOSED) if not closed else [],
        resolutionTypes=[{'value':value,'label':label} for value,label in CaseInvestigation.Resolution.choices],history=history),token
