"""Read-only, bounded queries over persisted AP/AR case state."""
from django import forms
from django.core.paginator import Paginator
from django.db.models import Q, F, Value, Count, Max, Sum, Case, When, IntegerField, OuterRef, Subquery, CharField
from django.db.models.functions import Coalesce, Concat, Cast
from accounts_receivable.services.catalog import model, party_key
from discrepancies.models import DiscrepancyFinding
from discrepancies.presentation import serialize_case_summary

SORTS = ('transaction_date','-transaction_date','created_at','-created_at','party_name','-party_name','discrepancy_amount','-discrepancy_amount','reconciliation_status','investigation_status','highest_severity','open_findings_count','reference')

class DashboardFilters(forms.Form):
    module = forms.ChoiceField(required=False, choices=[('', 'All'),('ap','AP'),('ar','AR')])
    reconciliation_status = forms.ChoiceField(required=False, choices=[(v,v) for v in ('','pending','partial','matched','exception')])
    investigation_status = forms.ChoiceField(required=False, choices=[(v,v) for v in ('','not_started','needs_review','investigating','waiting','resolved','dismissed')])
    severity = forms.ChoiceField(required=False, choices=[(v,v) for v in ('','information','warning','critical')])
    currency = forms.RegexField(r'^[A-Z]{3}$',required=False)
    q = forms.CharField(max_length=200,required=False)
    date_from = forms.DateField(required=False)
    date_to = forms.DateField(required=False)
    sort = forms.ChoiceField(required=False,choices=[(v,v) for v in SORTS])
    page = forms.IntegerField(min_value=1,max_value=1000000,required=False)
    page_size = forms.IntegerField(min_value=1,max_value=100,required=False)

    def clean(self):
        data=super().clean()
        if data.get('date_from') and data.get('date_to') and data['date_from']>data['date_to']:
            raise forms.ValidationError('Start date must be on or before end date.')
        return data


def parse_filters(params):
    form=DashboardFilters(params)
    valid=form.is_valid()
    unknown=set(params)-set(form.fields)
    repeated=[key for key in params if hasattr(params,'getlist') and len(params.getlist(key))>1]
    if unknown or repeated:
        form.add_error(None,'Unknown or repeated query parameters.')
    if not valid or form.errors:
        return None,form.errors.get_json_data()
    return form.cleaned_data,None


def case_query(module,filters):
    party=party_key(module)
    findings=DiscrepancyFinding.objects.filter(**{module+'_transaction_id':OuterRef('pk')}).order_by()
    counts=findings.values(module+'_transaction_id')
    query=model(module,'Transaction').objects.order_by().annotate(
        module=Value(module,output_field=CharField()),case_id=F('pk'),
        reference=Concat(Value(module.upper()+'-'),Cast('pk',CharField())),
        party_name=Coalesce(F(party+'__'+party+'_name'),Value('Unknown party')),
        investigation_status=Coalesce(F('investigation__workflow_status'),Value('not_started')),
        review_required=Coalesce(F('investigation__review_required'),Value(False)),
        total_findings_count=Coalesce(Subquery(counts.annotate(n=Count('pk')).values('n')),0),
        open_findings_count=Coalesce(Subquery(counts.filter(status='open').annotate(n=Count('pk')).values('n')),0),
        severity_rank=Coalesce(Subquery(counts.annotate(n=Max(Case(When(severity='critical',then=3),When(severity='warning',then=2),default=1,output_field=IntegerField()))).values('n')),0),
        discrepancy_amount=F('total_discrepancy_amount'),
    ).filter(Q(total_findings_count__gt=0)|Q(investigation__isnull=False)|Q(reconciliation_status='exception'))
    for name in ('reconciliation_status','investigation_status','currency'):
        if filters.get(name): query=query.filter(**{name:filters[name]})
    if filters.get('severity'): query=query.filter(severity_rank={'information':1,'warning':2,'critical':3}[filters['severity']])
    if filters.get('q'): query=query.filter(Q(party_name__icontains=filters['q'])|Q(reference__icontains=filters['q']))
    if filters.get('date_from'): query=query.filter(transaction_date__gte=filters['date_from'])
    if filters.get('date_to'): query=query.filter(transaction_date__lte=filters['date_to'])
    return query


def queries(filters):
    return [case_query(module,filters) for module in ('ap','ar') if not filters.get('module') or filters['module']==module]

FIELDS=('module','case_id','reference','party_name','transaction_date','currency','reconciliation_status','investigation_status','open_findings_count','total_findings_count','severity_rank','discrepancy_amount','review_required','created_at','updated_at')


def cases(filters):
    parts=[query.values(*FIELDS) for query in queries(filters)]
    combined=parts[0].union(*parts[1:],all=True) if len(parts)>1 else parts[0]
    sort=filters.get('sort') or '-transaction_date'
    sort={'highest_severity':'severity_rank'}.get(sort,sort)
    # Explicit null placement and module/id tie breaks are stable on SQLite and PostgreSQL.
    combined=combined.order_by(F(sort.lstrip('-')).desc(nulls_last=True) if sort.startswith('-') else F(sort).asc(nulls_last=True),'module','case_id')
    pager=Paginator(combined,filters.get('page_size') or 25)
    page_number=filters.get('page') or 1
    if page_number>max(1,pager.num_pages):
        return dict(results=[],count=pager.count,page=page_number,page_size=pager.per_page,pages=pager.num_pages)
    page=pager.page(page_number)
    return dict(results=[serialize_case_summary(row) for row in page],count=pager.count,page=page_number,page_size=pager.per_page,pages=pager.num_pages)


def summary(filters):
    result=dict(total=0,needs_review=0,in_progress=0,waiting=0,resolved=0,renewed_review=0,financial=[])
    for query in queries(filters):
        values=query.aggregate(total=Count('pk'),needs_review=Count('pk',filter=Q(investigation_status='needs_review')|Q(investigation_status='not_started',open_findings_count__gt=0)|Q(investigation_status='not_started',reconciliation_status='exception')),
            in_progress=Count('pk',filter=Q(investigation_status='investigating')),waiting=Count('pk',filter=Q(investigation_status='waiting')),
            resolved=Count('pk',filter=Q(investigation_status='resolved')),renewed_review=Count('pk',filter=Q(review_required=True)))
        for key,value in values.items(): result[key]+=value
        for row in query.values('module','currency').annotate(amount=Sum('total_discrepancy_amount'),case_count=Count('pk')).order_by('module','currency'):
            row['amount']=str(row['amount']) if row['amount'] is not None else None
            result['financial'].append(row)
    return result
