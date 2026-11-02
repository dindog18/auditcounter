"""Atomic, idempotent synchronization; evaluation and preview never call persistence."""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
from importlib import import_module

from django.core.exceptions import ValidationError
from django.db import transaction as db_transaction
from django.utils import timezone

from ..evaluation import json_value

_pending = ContextVar('deferred_reconciliation', default=None)


def digest(value):
    return hashlib.sha256(json.dumps(json_value(value), sort_keys=True, separators=(',',':')).encode()).hexdigest()


def case_filter(case):
    return {'ap_transaction':case} if case._meta.app_label == 'accounts_payable' else {'ar_transaction':case}


def build_finding_fingerprint(finding, case=None):
    identity = dict(finding_code=finding['finding_code'], identity=finding['identity'])
    if case is not None:
        identity.update(scope=case._meta.app_label, case_id=case.pk)
    return digest(identity)


@contextmanager
def defer_reconciliation():
    """Flush each affected case once, inside the caller's atomic write operation."""
    if _pending.get() is not None:
        yield
        return
    pending = {}
    token = _pending.set(pending)
    try:
        yield
    except BaseException:
        _pending.reset(token)
        raise
    else:
        _pending.reset(token)
        for key in sorted(pending):
            pending[key].refresh_reconciliation_status()


@db_transaction.atomic
def refresh_transaction(case):
    pending = _pending.get()
    if pending is not None:
        pending[(case._meta.label,case.pk)] = case
        return
    locked = type(case).objects.select_for_update().get(pk=case.pk)
    service = import_module(f'{case._meta.app_label}.services.reconciliation')
    evaluation = service.evaluate_reconciliation(locked)
    from .timeline import record_transition,observe_case
    old_status,old_amount=getattr(case,'_timeline_before_result',(locked.reconciliation_status,locked.total_discrepancy_amount))
    if hasattr(case,'_timeline_before_result'):del case._timeline_before_result
    synchronize_findings(locked, evaluation['discrepancy_findings'])
    if (old_status,old_amount)!=(evaluation['status'],evaluation['discrepancy']):
        record_transition(locked,'reconciliation_changed','Reconciliation result changed',locked._meta.label,locked.pk,
            {'status':evaluation['status'],'amount':evaluation['discrepancy']},before={'status':old_status,'amount':old_amount})
    observe_case(locked)
    type(case).objects.filter(pk=case.pk).update(reconciliation_status=evaluation['status'], total_discrepancy_amount=evaluation['discrepancy'])
    case.reconciliation_status = evaluation['status']
    case.total_discrepancy_amount = evaluation['discrepancy']


@db_transaction.atomic
def capture_finding_evidence(finding, evidence):
    from ..models import FindingEvidence
    snapshot = json_value(dict(finding_code=finding.finding_code, status=finding.status, summary=finding.summary,
        expected_value=finding.expected_value, actual_value=finding.actual_value,
        difference_amount=finding.difference_amount, currency=finding.currency,
        rule_version=finding.rule_version, details=finding.details))
    # Canonicalize DecimalField values independently of the in-memory Decimal scale.
    if snapshot['difference_amount'] is not None:
        snapshot['difference_amount'] = format(finding.difference_amount, '.8f')
    for item in evidence:
        values = json_value(item)
        fingerprint = digest({'evidence':values, 'finding_snapshot':snapshot})
        FindingEvidence.objects.get_or_create(finding=finding, snapshot_hash=fingerprint,
            defaults={**values,'finding_snapshot':snapshot})


@db_transaction.atomic
def clear_resolved_findings(case, active_fingerprints):
    from ..models import DiscrepancyFinding
    type(case).objects.select_for_update().get(pk=case.pk)
    for finding in DiscrepancyFinding.objects.filter(**case_filter(case), status='open').exclude(fingerprint__in=active_fingerprints):
        from .timeline import finding_state
        previous=finding_state(finding)
        finding.status, finding.cleared_at = 'cleared', timezone.now()
        finding.save(update_fields=['status','cleared_at'])
        capture_finding_evidence(finding, current_evidence(case, finding))
        from .timeline import finding_event
        finding_event(case,finding,'finding_cleared',previous)


@db_transaction.atomic
def synchronize_findings(case, findings):
    from ..models import DiscrepancyFinding
    type(case).objects.select_for_update().get(pk=case.pk)
    now, active = timezone.now(), set()
    fields = ('finding_code','severity','summary','expected_value','actual_value','difference_amount','currency','rule_version','identity','details')
    for item in findings:
        fingerprint = build_finding_fingerprint(item, case)
        if fingerprint in active:
            raise ValidationError('Evaluation produced duplicate finding identities.')
        active.add(fingerprint)
        values = {field:item[field] for field in fields}
        finding, created = DiscrepancyFinding.objects.get_or_create(**case_filter(case), fingerprint=fingerprint,
            defaults={**values,'first_detected_at':now,'last_detected_at':now})
        from .timeline import finding_state,finding_event
        previous=finding_state(finding) if not created else None
        if not created:
            for field,value in values.items():
                setattr(finding,field,value)
            finding.status, finding.cleared_at, finding.last_detected_at = 'open', None, now
            finding.save(update_fields=[*fields,'status','cleared_at','last_detected_at'])
        # Convert through the DecimalField before generating canonical evidence state.
        amount_field = finding._meta.get_field('difference_amount')
        finding.difference_amount = amount_field.to_python(finding.difference_amount)
        capture_finding_evidence(finding, item['evidence'])
        if created or previous!=finding_state(finding):
            finding_event(case,finding,'finding_detected' if created else 'finding_reopened' if previous['status']=='cleared' else 'finding_changed',previous)
    clear_resolved_findings(case, active)
    from .investigation import flag_changed_resolution
    flag_changed_resolution(case)


def current_evidence(case, finding):
    """Capture available corrected/removed observations without erasing prior snapshots."""
    from django.apps import apps
    from ..evaluation import source_evidence, allocation_evidence
    captured, seen = [], set()
    for item in finding.evidence.order_by('pk'):
        key = (item.source_model,item.source_record_id,item.source_line_id)
        if key in seen:
            continue
        seen.add(key)
        Source = apps.get_model(item.source_model)
        if item.evidence_type == 'ALLOCATION':
            fields = {field:item.observed_value[field] for field in ('invoice_line_id','purchase_order_line_id','delivery_receipt_line_id')}
            match = Source.objects.filter(transaction=case, **fields).first()
            if match is None:
                match = Source(transaction=case, matched_quantity=0, **fields)
            captured.append(allocation_evidence(match))
        else:
            document = Source.objects.filter(pk=item.source_record_id).first()
            if document is None:
                continue  # Original identifiers/values remain in the historical snapshot.
            line = document.lines.filter(pk=item.source_line_id).first() if item.source_line_id else None
            captured.append(source_evidence(document,line))
    if finding.finding_code in ('MISSING_PO','MISSING_DR'):
        relation = case.purchase_orders if finding.finding_code == 'MISSING_PO' else case.delivery_receipts
        for document in relation.all():
            captured.extend(source_evidence(document,line) for line in document.lines.all())
    invoice_line_id = finding.identity.get('invoice_line_id')
    if invoice_line_id:
        captured.extend(allocation_evidence(match) for match in case.line_matches.filter(invoice_line_id=invoice_line_id))
    return captured
