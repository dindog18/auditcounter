"""Conservative, bounded candidate detection; never blocks, deletes or merges invoices."""
import re
import unicodedata
from datetime import timedelta
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.urls import reverse
from accounts_receivable.services.catalog import model,party_key,revision,check_revision
from accounts_receivable.services.financial import body,text
from ..models import DuplicateInvoiceCandidate,DuplicateInvoiceReview
from ..evaluation import source_evidence,finding
from . import digest


def normalize_reference(value):
    return re.sub(r'[^\w]', '', unicodedata.normalize('NFKC', value or '').casefold()).replace('_','')


def snapshot(invoice):
    return dict(id=invoice.pk,reference=invoice.invoice_reference_no,date=invoice.invoice_date.isoformat() if invoice.invoice_date else None,
        currency=invoice.currency,total=str(invoice.total_amount),source_document_id=invoice.source_document_id,
        lines=[dict(code=line.item_code,quantity=str(line.quantity_invoiced),total=str(line.line_total)) for line in invoice.lines.order_by('line_no')[:100]],
        payments=[dict(payment_id=row.payment_id,status=row.payment.payment_status,cash=str(row.cash_amount)) for row in invoice.payment_allocations.select_related('payment').order_by('pk')[:100]])


def compare(left,right):
    if not left.invoice_date or not right.invoice_date:return None
    same_reference=bool(normalize_reference(left.invoice_reference_no)) and normalize_reference(left.invoice_reference_no)==normalize_reference(right.invoice_reference_no)
    if not same_reference or left.currency!=right.currency or left.total_amount!=right.total_amount or abs((left.invoice_date-right.invoice_date).days)>3:return None
    first,second=sorted((left,right),key=lambda row:row.pk)
    a,b=snapshot(first),snapshot(second)
    return dict(first=a,second=b,reasons=['Same account and currency','Same normalized invoice reference','Equal recorded totals','Invoice dates within three days'],
        conflicts=['Line evidence differs; investigate whether these are legitimate separate invoices.'] if a['lines'] and b['lines'] and a['lines']!=b['lines'] else [],
        classification='possible_duplicate_not_confirmed_loss')


@transaction.atomic
def detect(invoice):
    mode='ap' if invoice._meta.app_label=='accounts_payable' else 'ar'
    party=party_key(mode)
    if not getattr(invoice,party+'_id'):return []
    model(mode,party).objects.select_for_update().get(pk=getattr(invoice,party+'_id'))
    invoice=type(invoice).objects.get(pk=invoice.pk)
    pair_fields=(mode+'_first',mode+'_second')
    prior=DuplicateInvoiceCandidate.objects.filter(Q(**{pair_fields[0]:invoice})|Q(**{pair_fields[1]:invoice}))
    prior_ids=set(prior.values_list(pair_fields[0]+'_id',flat=True))|set(prior.values_list(pair_fields[1]+'_id',flat=True))
    candidates=type(invoice).objects.filter(**{party+'_id':getattr(invoice,party+'_id')},currency=invoice.currency,total_amount=invoice.total_amount)
    if invoice.invoice_date:
        candidates=candidates.filter(invoice_date__range=(invoice.invoice_date-timedelta(days=3),invoice.invoice_date+timedelta(days=3)))
    else:candidates=candidates.none()
    ids=set(candidates.exclude(pk=invoice.pk).order_by('pk').values_list('pk',flat=True)[:200])|prior_ids
    outcomes=[]; changed_invoices=set()
    for other in type(invoice).objects.filter(pk__in=ids).exclude(pk=invoice.pk).order_by('pk'):
        details=compare(invoice,other) if getattr(other,party+'_id')==getattr(invoice,party+'_id') else None
        a,b=sorted((invoice.pk,other.pk))
        key={pair_fields[0]+'_id':a,pair_fields[1]+'_id':b}
        row=DuplicateInvoiceCandidate.objects.filter(**key).first()
        changed = row is None or row.details!=details or not row.active if details else bool(row and row.active)
        if details:
            if row is None:row=DuplicateInvoiceCandidate.objects.create(**key,details=details)
            elif row.details!=details or not row.active:row.details=details;row.active=True;row.save()
            outcomes.append(row)
        elif row and row.active:row.active=False;row.save()
        if row and changed:
            changed_invoices.update((a,b))
            DuplicateInvoiceReview.objects.create(candidate=row,decision='detected' if details else 'cleared',notes='Deterministic duplicate evidence changed.',evidence_snapshot=details or {'previous':row.details,'active':False})
    for case in model(mode,'Transaction').objects.filter(sales_invoices__pk__in=changed_invoices).distinct().order_by('pk'):
        case.refresh_reconciliation_status()
    return outcomes


def case_findings(case):
    mode='ap' if case._meta.app_label=='accounts_payable' else 'ar'
    ids=case.sales_invoices.values('pk')
    rows=DuplicateInvoiceCandidate.objects.filter(Q(**{mode+'_first_id__in':ids})|Q(**{mode+'_second_id__in':ids}),active=True).select_related(mode+'_first',mode+'_second')
    result=[]
    for row in rows:
        # Human dismissal remains separate from whether the rule detects the pair.
        left,right=getattr(row,mode+'_first'),getattr(row,mode+'_second')
        result.append(finding('POSSIBLE_DUPLICATE_INVOICE',{'candidate_id':row.pk},
            f'Invoices {left.invoice_reference_no} and {right.invoice_reference_no} have similar identity, dates and totals; investigate before payment.',
            {'distinct_invoice_evidence':'required'},{'candidate_id':row.pk},[source_evidence(left),source_evidence(right)],
            currency=left.currency,details={'candidate_id':row.pk,'classification':'possible_duplicate_not_confirmed_loss'}))
    return result


@transaction.atomic
def review(record_id,data):
    body(data,('revision','decision','notes'))
    row=get_object_or_404(DuplicateInvoiceCandidate,pk=record_id)
    mode='ap' if row.ap_first_id else 'ar'
    invoice=getattr(row,mode+'_first')
    model(mode,party_key(mode)).objects.select_for_update().get(pk=getattr(invoice,party_key(mode)+'_id'))
    row=DuplicateInvoiceCandidate.objects.select_for_update().get(pk=record_id)
    check_revision(row,data.get('revision'))
    if data.get('decision') not in ('confirmed','dismissed'):raise ValidationError('Confirm or dismiss the duplicate candidate.')
    row.review_decision=data['decision'];row.review_notes=text(data.get('notes'),'review explanation')
    row.review_basis=digest(row.details);row.save()
    DuplicateInvoiceReview.objects.create(candidate=row,decision=row.review_decision,notes=row.review_notes,evidence_snapshot=row.details)
    from .timeline import record_transition
    for case in model(mode,'Transaction').objects.filter(sales_invoices__pk__in=[getattr(row,mode+'_first_id'),getattr(row,mode+'_second_id')]).distinct().order_by('pk'):
        record_transition(case,'duplicate_reviewed','Possible duplicate invoice reviewed',row._meta.label,row.pk,dict(decision=row.review_decision,notes=row.review_notes,basis=row.review_basis))
    return row


def serialize(row):
    mode='ap' if row.ap_first_id else 'ar'
    namespace='ACCOUNTS_PAYABLE' if mode=='ap' else 'ACCOUNTS_RECEIVABLE'
    return dict(id=row.pk,module=mode,active=row.active,details=row.details,decision=row.review_decision,notes=row.review_notes,
        review_stale=bool(row.review_basis and row.review_basis!=digest(row.details)),revision=revision(row),
        first_url=reverse(namespace+':invoice_detail',args=[getattr(row,mode+'_first_id')]),second_url=reverse(namespace+':invoice_detail',args=[getattr(row,mode+'_second_id')]),
        history=list(row.reviews.order_by('pk').values('decision','notes','created_at','evidence_snapshot')))
