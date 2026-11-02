"""Case identity verification; no allocation or financial decisions."""
from collections import defaultdict
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.urls import reverse
from .catalog import model,party_key

RELATIONS=('purchase_orders','delivery_receipts','sales_invoices')


def normalized_membership(document_ids):
    result={}
    for key in RELATIONS:
        values=document_ids.get(key,[])
        if not isinstance(values,(list,tuple,set)) or any(type(value) is not int for value in values):
            raise ValidationError('Choose valid document ID collections.')
        result[key]=tuple(sorted(set(values)))
    return result


def membership(case):
    # Use prefetched memberships rather than per-case queries.
    return {key:tuple(sorted(row.pk for row in getattr(case,key).all())) for key in RELATIONS}


def case_link(mode,case):
    return dict(existing_case_id=case.pk,existing_case_reference=f'{mode.upper()}-{case.pk}',
        existing_case_url=reverse(f"{'ACCOUNTS_PAYABLE' if mode=='ap' else 'ACCOUNTS_RECEIVABLE'}:reconciliation_detail",args=[case.pk]))


def candidates(mode,party_id,currency,exclude_case_id):
    rows=model(mode,'Transaction').objects.filter(**{party_key(mode)+'_id':party_id},currency=currency)
    if exclude_case_id is not None: rows=rows.exclude(pk=exclude_case_id)
    return rows.order_by('pk')


def find_exact_duplicate_case(mode,party_id,currency,document_ids,exclude_case_id=None):
    selected=normalized_membership(document_ids)
    rows=candidates(mode,party_id,currency,exclude_case_id)
    anchor=next((key for key in reversed(RELATIONS) if selected[key]),None)
    if anchor: rows=rows.filter(**{anchor+'__pk':selected[anchor][0]})
    else:
        for key in RELATIONS: rows=rows.filter(**{key+'__isnull':True})
    for case in rows.prefetch_related(*RELATIONS):
        if membership(case)==selected: return case
    return None


def find_overlapping_cases(mode,party_id,currency,document_ids,exclude_case_id=None):
    selected=normalized_membership(document_ids)
    overlap=Q(pk__in=[])
    for key in RELATIONS:
        if selected[key]: overlap|=Q(**{key+'__pk__in':selected[key]})
    output=[]
    for case in candidates(mode,party_id,currency,exclude_case_id).filter(overlap).distinct().prefetch_related(*RELATIONS):
        existing=membership(case)
        shared={key:sorted(set(selected[key])&set(existing[key])) for key in RELATIONS}
        output.append(dict(**case_link(mode,case),overlapping_documents=shared,exact=existing==selected))
    return sorted(output,key=lambda row:(not bool(row['overlapping_documents']['sales_invoices']),row['existing_case_id']))


class DuplicateCaseError(ValidationError):
    def __init__(self,mode,case):
        super().__init__('An identical reconciliation case already exists.',code='conflict')
        self.existing_case=case_link(mode,case)


def historical_duplicates(mode):
    """Read-only diagnostic, including legacy empty groups; never repair history."""
    groups=defaultdict(list)
    for case in model(mode,'Transaction').objects.order_by('pk').prefetch_related(*RELATIONS):
        selected=membership(case)
        key=(getattr(case,party_key(mode)+'_id'),case.currency,*(selected[name] for name in RELATIONS))
        groups[key].append(case.pk)
    for key,ids in groups.items():
        if len(ids)>1:
            yield dict(module=mode,case_ids=ids,party_id=key[0],currency=key[1],documents=dict(zip(RELATIONS,key[2:])))
