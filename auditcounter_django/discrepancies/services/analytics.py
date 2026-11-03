"""Reviewed causes and read-only aggregates. Money is grouped by module/currency."""
from decimal import Decimal
from django import forms
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Avg, Count, F, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from accounts_receivable.services.catalog import model, party_key
from ..models import DiscrepancyFinding, FindingRootCause, CaseInvestigation, SupplierClaim
from . import case_filter
from .dashboard import DashboardFilters, case_query
from .investigation import locked_workflow, validate_body, text, finding_basis, append_activity, CLOSED


class AnalyticsFilters(DashboardFilters):
    party_id = forms.IntegerField(min_value=1, required=False)
    finding_type = forms.ChoiceField(required=False, choices=[('','All'), *DiscrepancyFinding.Code.choices])
    root_cause = forms.ChoiceField(required=False, choices=[('','All'), *FindingRootCause.Category.choices])

    def clean(self):
        values=super().clean()
        if values.get('party_id') and not values.get('module'):
            raise forms.ValidationError('Select AP or AR when filtering a numeric party identifier.')
        return values


def parse_filters(params):
    form=AnalyticsFilters(params)
    form.is_valid()
    unknown=set(params)-set(form.fields)
    repeated=hasattr(params,'getlist') and any(len(params.getlist(key))!=1 for key in params)
    if unknown or repeated:
        form.add_error(None,'Unknown or repeated analytics parameters.')
    return (None,form.errors.get_json_data()) if form.errors else (form.cleaned_data,None)


def review_root_cause(case, data):
    validate_body(data,('finding_id','category','explanation','evidence_ids'))
    with locked_workflow(case,data) as (case,investigation):
        if investigation.workflow_status in CLOSED:
            raise ValidationError('Reopen the investigation before classifying a root cause.')
        finding=get_object_or_404(DiscrepancyFinding.objects.select_for_update(),pk=data.get('finding_id'),**case_filter(case))
        basis=finding_basis(finding)
        if finding.review_decision!='confirmed' or finding.review_basis!=basis:
            raise ValidationError('Confirm the finding against its current evidence before identifying a cause.')
        category=data.get('category')
        if category not in FindingRootCause.Category.values:
            raise ValidationError('Choose a supported root cause.')
        ids=data.get('evidence_ids')
        if not isinstance(ids,list) or not 1<=len(ids)<=100 or any(type(pk) is not int for pk in ids) or len(ids)!=len(set(ids)):
            raise ValidationError('Select 1–100 distinct supporting evidence snapshots.')
        if finding.evidence.filter(pk__in=ids).count()!=len(ids):
            raise ValidationError('Root-cause evidence must belong to this finding.')
        explanation=text(data,'explanation',required=True)
        actor=text(data,'actor_label',limit=150)
        old=FindingRootCause.objects.filter(finding=finding).first()
        before=serialize_root_cause(old) if old else None
        if old and old.category==category and old.explanation==explanation and old.actor_label==actor and old.finding_basis==basis and old.review_status=='confirmed' and set(old.evidence.values_list('pk',flat=True))==set(ids):
            return old
        root=old or FindingRootCause(finding=finding)
        root.category=category;root.explanation=explanation;root.actor_label=actor;root.finding_basis=basis
        root.review_status='confirmed';root.reviewed_at=timezone.now();root.full_clean(exclude=['evidence']);root.save();root.evidence.set(ids)
        append_activity(investigation,'review',data,notes=explanation,finding=finding,
            details={'review_kind':'root_cause','previous':before,'current':serialize_root_cause(root)})
        investigation.save(update_fields=['updated_at'])
        return root


def serialize_root_cause(root):
    if root is None:return None
    return dict(id=root.pk,category=root.category,explanation=root.explanation,status=root.review_status,
        evidence_ids=list(root.evidence.order_by('pk').values_list('pk',flat=True)),reviewed_at=root.reviewed_at.isoformat(),actor_label=root.actor_label)


def flag_stale_causes(case):
    """Source changes invalidate current attribution, retaining the prior human history."""
    for root in FindingRootCause.objects.filter(finding__in=case.discrepancy_findings.all(),review_status='confirmed').select_related('finding'):
        if root.finding.review_decision!='confirmed' or root.finding_basis!=finding_basis(root.finding):
            root.review_status='needs_review';root.save(update_fields=['review_status','updated_at'])
            investigation=CaseInvestigation.objects.filter(**case_filter(case)).first()
            if investigation:
                append_activity(investigation,'evidence_changed',{},finding=root.finding,notes='Root-cause classification requires renewed review after finding evidence changed.',details={'root_cause':serialize_root_cause(root)})


def case_queryset(mode, filters):
    query=case_query(mode,filters)
    if filters.get('party_id'):query=query.filter(**{party_key(mode)+'_id':filters['party_id']})
    finding_filters={}
    if filters.get('finding_type'):finding_filters['finding_code']=filters['finding_type']
    if filters.get('root_cause'):
        finding_filters.update(root_cause__category=filters['root_cause'],root_cause__review_status='confirmed')
    if finding_filters:
        query=query.filter(pk__in=DiscrepancyFinding.objects.filter(**finding_filters).values(mode+'_transaction_id'))
    return query


def seconds(value):
    return str(Decimal(str(value.total_seconds())).quantize(Decimal('.01'))) if value is not None else None


def report(filters):
    """Case-based financial sums avoid multiplying totals by the number of findings."""
    from accounts_payable.models import SupplierCreditNote, SupplierCreditApplication, SupplierStatement
    from accounts_receivable.models import CustomerDeduction, DeductionApplication
    result=dict(financial=[],frequency=[],root_causes=[],confirmed_parties=[],sku_mismatches=[],durations=[],claim_aging=[],workflows=[])
    parts=[]
    for mode in ('ap','ar'):
        if filters.get('module') and filters['module']!=mode:continue
        cases=case_queryset(mode,filters);case_ids=cases.values('pk')
        findings=DiscrepancyFinding.objects.filter(**{mode+'_transaction_id__in':case_ids})
        if filters.get('finding_type'):findings=findings.filter(finding_code=filters['finding_type'])
        if filters.get('root_cause'):findings=findings.filter(root_cause__category=filters['root_cause'],root_cause__review_status='confirmed')
        for row in findings.values('finding_code').annotate(count=Count('pk'),confirmed=Count('pk',filter=Q(review_decision='confirmed'))).order_by('finding_code'):
            result['frequency'].append(dict(module=mode,**row))
        roots=FindingRootCause.objects.filter(finding__in=findings,review_status='confirmed')
        for row in roots.values('category').annotate(count=Count('pk')).order_by('category'):
            result['root_causes'].append(dict(module=mode,**row))
        # A reviewed SKU cause represents a validated business mismatch, not an AI proposal.
        sku=roots.filter(category='sku_identity',evidence__evidence_type='SI').annotate(sku=F('evidence__observed_value__line__item_code')).exclude(sku__isnull=True).exclude(sku='').values('sku',party_id=F('finding__'+mode+'_transaction__'+party_key(mode)+'_id')).annotate(count=Count('finding_id',distinct=True)).filter(count__gt=1).order_by('-count','party_id','sku')[:25]
        result['sku_mismatches'] += [dict(module=mode,**row) for row in sku]
        parties=findings.filter(review_decision='confirmed').values(party_id=F(mode+'_transaction__'+party_key(mode)+'_id'),party_name=F(mode+'_transaction__'+party_key(mode)+'__'+party_key(mode)+'_name')).annotate(count=Count('pk')).order_by()
        from django.db.models import Value,CharField
        parts.append(parties.annotate(module=Value(mode,output_field=CharField())).values('module','party_id','party_name','count'))
        investigations=CaseInvestigation.objects.filter(**{mode+'_transaction_id__in':case_ids},closed_at__isnull=False)
        duration=investigations.aggregate(value=Avg(F('closed_at')-F('opened_at')))['value']
        result['durations'].append(dict(module=mode,closed_investigations=investigations.count(),average_investigation_seconds=seconds(duration)))
        for row in cases.values('currency').annotate(potential_exposure=Sum('total_discrepancy_amount'),case_count=Count('pk')).order_by('currency'):
            currency=row['currency'];currency_cases=cases.filter(currency=currency).values('pk')
            invoices=model(mode,'sales_invoice').objects.filter(reconciliation_cases__in=currency_cases).values('pk')
            values=dict(module=mode,currency=currency,case_count=row['case_count'],potential_exposure=str(row['potential_exposure']) if row['potential_exposure'] is not None else None,
                validated_claims='0.00',applied_credits='0.00',applied_adjustments='0.00',verified_cash_recoveries='0.00')
            if mode=='ap':
                claims=SupplierClaim.objects.filter(ap_transaction_id__in=currency_cases,currency=currency)
                validated=claims.filter(status__in=['accepted','resolved'],review_required=False).exclude(resolution_type='no_recovery')
                values['validated_claims']=str(validated.aggregate(value=Sum('accepted_amount'))['value'] or Decimal('0.00'))
                applications=SupplierCreditApplication.objects.filter(invoice_id__in=invoices,credit__currency=currency,credit__status='verified',reversal__isnull=True)
                values['applied_credits']=str(applications.aggregate(value=Sum('amount'))['value'] or Decimal('0.00'))
                closed=claims.filter(status='resolved',closed_at__isnull=False)
                result['durations'].append(dict(module=mode,currency=currency,closed_claims=closed.count(),average_claim_seconds=seconds(closed.aggregate(value=Avg(F('closed_at')-F('created_at')))['value'])))
                unresolved=claims.exclude(status__in=['resolved','rejected'])
                now=timezone.now()
                from datetime import timedelta
                for label,lower,upper in [('0–30',0,30),('31–60',30,60),('61+',60,None)]:
                    aged=unresolved.filter(created_at__lte=now-timedelta(days=lower))
                    if upper is not None:aged=aged.filter(created_at__gt=now-timedelta(days=upper))
                    result['claim_aging'].append(dict(currency=currency,bucket=label,count=aged.count(),claimed_amount=str(aged.aggregate(value=Sum('claimed_amount'))['value'] or Decimal('0.00'))))
            else:
                apps=DeductionApplication.objects.filter(deduction__invoice_id__in=invoices,deduction__status='accepted',reversal__isnull=True)
                values['applied_adjustments']=str(apps.aggregate(value=Sum('amount'))['value'] or Decimal('0.00'))
            result['financial'].append(values)
    if parts:
        combined=parts[0].union(*parts[1:],all=True) if len(parts)>1 else parts[0]
        pager=Paginator(combined.order_by('-count','module','party_id'),filters.get('page_size') or 25)
        number=filters.get('page') or 1
        result['confirmed_parties']=list(pager.page(number)) if number<=max(1,pager.num_pages) else []
        result.update(page=number,page_size=pager.per_page,total_parties=pager.count)
    # Operational registers also expose records not linked to a case. These have their
    # own party/currency/date scope, explicitly separated from case-filtered analytics.
    for mode,Model,label,date_field in [('ap',SupplierClaim,'supplier_claims','created_at__date'),('ap',SupplierCreditNote,'supplier_credits','issue_date'),('ap',SupplierStatement,'supplier_statements','statement_date'),('ar',CustomerDeduction,'customer_deductions','created_at__date')]:
        if filters.get('module') and filters['module']!=mode:continue
        rows=Model.objects.all()
        if filters.get('party_id'):rows=rows.filter(**{party_key(mode)+'_id':filters['party_id']})
        if filters.get('currency'):rows=rows.filter(currency=filters['currency'])
        if filters.get('date_from'):rows=rows.filter(**{date_field+'__gte':filters['date_from']})
        if filters.get('date_to'):rows=rows.filter(**{date_field+'__lte':filters['date_to']})
        status='reconciliation_status' if Model==SupplierStatement else 'status'
        result['workflows'].append(dict(module=mode,register=label,counts=list(rows.values(status).annotate(count=Count('pk')).order_by(status))))
    result['limitations']=['Cash refund/recovery records are not implemented; applied credits and deductions are adjustments, not cash recoveries.',
        'Dates filter case transaction dates for case analytics and source dates for operational registers. Registers do not use finding/root-cause/investigation filters.',
        'Confirmed finding counts describe recorded human reviews; root-cause counts include only current confirmed attributions. Repeated SKU counts require reviewed SKU causes and selected invoice-line code evidence; absent evidence is not inferred.']
    return result
