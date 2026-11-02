"""Only explicit scoped approvals establish new product identities."""
from contextlib import contextmanager

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts_receivable.services.catalog import model,party_key,revision
from discrepancies.services import digest
from ..models import SKUAlias
from .normalization import normalize_sku,normalize_unit,incompatible_specs
from .products import mode_for,product,parent_for,party_filter,get_line,known_lines,case_lines


@contextmanager
def resolver_session(case):
    previous=getattr(case,'_sku_resolution_cache',None)
    case._sku_resolution_cache={'aliases':list(SKUAlias.objects.filter(**party_filter(case),status='approved')),'targets':{}}
    try:
        yield
    finally:
        if previous is None:
            del case._sku_resolution_cache
        else:
            case._sku_resolution_cache=previous


def context_for(line,case):
    data=product(line)
    data.update(party_filter(case))
    return data


def alias_snapshot(alias):
    return dict(id=alias.pk,scope=alias.scope,source_system=alias.source_system,source_code=alias.source_item_code,
        canonical_code=alias.canonical_item_code,unit=alias.unit_of_measure,status=alias.status,
        approval_notes=alias.approval_notes,approved_at=alias.approved_at.isoformat() if alias.approved_at else None,
        canonical_reference=alias.canonical_reference,canonical_snapshot=alias.canonical_snapshot)


def target_is_current(alias,case):
    cache=getattr(case,'_sku_resolution_cache',None)
    if cache is not None and alias.pk in cache['targets']:
        return cache['targets'][alias.pk]
    try:
        valid=product(get_line(case,alias.canonical_reference))==alias.canonical_snapshot
    except ValidationError:
        valid=False
    if cache is not None:
        cache['targets'][alias.pk]=valid
    return valid


def find_approved_mapping(source_code,context):
    filters={key:context[key] for key in ('scope','supplier_id','customer_id') if key in context}
    if not filters or not any(filters.get(key) for key in ('supplier_id','customer_id')):
        return None
    cache=getattr(context.get('case'),'_sku_resolution_cache',None)
    if cache is not None:
        rows=[alias for alias in cache['aliases'] if alias.source_system==context['source_system'] and alias.normalized_source_code==normalize_sku(source_code) and alias.normalized_unit==normalize_unit(context['unit']) and all(getattr(alias,key)==value for key,value in filters.items())]
    else:
        rows=list(SKUAlias.objects.filter(**filters,source_system=context['source_system'],
            normalized_source_code=normalize_sku(source_code),normalized_unit=normalize_unit(context['unit']),status='approved')[:2])
    return rows[0] if len(rows)==1 else None


def resolve_product_identity(source_code,context):
    code=normalize_sku(source_code)
    result=dict(code=code,mapping=None,resolved=False,valid=bool(code),reason='No approved equivalence; different codes remain unresolved.')
    alias=find_approved_mapping(source_code,context)
    if alias:
        case=context['case']
        if not target_is_current(alias,case):
            return dict(code=code,mapping=None,resolved=False,valid=False,reason='Approved canonical source changed or was removed; review the mapping.')
        result.update(code=alias.normalized_canonical_code,mapping=alias_snapshot(alias),resolved=True,reason='Approved scoped SKU equivalence')
    return result


def compare_products(left,right,case):
    a,b=product(left),product(right)
    result=dict(equivalent=False,mappings=[],reason='Unknown or incompatible product identifiers.')
    if not a['normalized_code'] or not b['normalized_code']:
        return result
    if a['normalized_unit']!=b['normalized_unit']:
        return dict(result,reason='Units of measure differ; no conversion is assumed.')
    conflicts=incompatible_specs(a,b)
    if conflicts:
        return dict(result,reason=' '.join(conflicts))
    if a['normalized_code']==b['normalized_code']:
        return dict(result,equivalent=True,reason='Exact normalized SKU and compatible unit')
    contexts=[dict(context_for(line,case),case=case) for line in (left,right)]
    identities=[resolve_product_identity(item['code'],context) for item,context in zip((a,b),contexts)]
    if all(item['valid'] for item in identities) and identities[0]['code']==identities[1]['code'] and any(item['mapping'] for item in identities):
        return dict(equivalent=True,mappings=[item['mapping'] for item in identities if item['mapping']],reason='Approved supplier/customer and source-namespace SKU equivalence')
    return dict(result,reason='; '.join(dict.fromkeys(item['reason'] for item in identities if not item['resolved'])) or 'Different SKUs require an approved scoped mapping.')


def identity_for_match(match):
    if not match.purchase_order_line_id or not match.delivery_receipt_line_id:
        return dict(equivalent=False,mappings=[],reason='Order and receipt evidence are required.')
    comparisons=[compare_products(match.invoice_line,line,match.transaction) for line in (match.purchase_order_line,match.delivery_receipt_line)]
    aliases={item['id']:item for comparison in comparisons for item in comparison['mappings']}
    return dict(equivalent=all(item['equivalent'] for item in comparisons),mappings=[aliases[key] for key in sorted(aliases)],
                reasons=list(dict.fromkeys(item['reason'] for item in comparisons)))


def approved_catalog_state(case):
    keys={(data['source_system'],data['normalized_code'],data['normalized_unit']) for data in (product(line) for line in case_lines(case))}
    return [dict(id=alias.pk,source=alias.normalized_source_code,canonical=alias.normalized_canonical_code,unit=alias.normalized_unit,
                 source_system=alias.source_system,updated_at=alias.updated_at.isoformat(),status=alias.status)
            for alias in SKUAlias.objects.filter(**party_filter(case),status='approved').order_by('pk')
            if (alias.source_system,alias.normalized_source_code,alias.normalized_unit) in keys]


def catalog_revision(case):
    return digest(dict(scope=mode_for(case),party=party_filter(case),case_lines=[product(line) for line in case_lines(case)],
        known=[product(line) for line in known_lines(case)],aliases=[revision(alias) for alias in SKUAlias.objects.filter(**party_filter(case)).order_by('pk')]))


@contextmanager
def locked_catalog(case,data):
    with transaction.atomic():
        key=party_key(mode_for(case))
        account_id=getattr(case,key+'_id')
        if not account_id:
            raise ValidationError('Set the supplier/customer before managing SKU mappings.')
        model(mode_for(case),key).objects.select_for_update().get(pk=account_id)
        list(type(case).objects.select_for_update().filter(**{key+'_id':account_id}).order_by('pk'))
        case=type(case).objects.get(pk=case.pk)
        if data.get('revision')!=catalog_revision(case):
            raise ValidationError('Products or mappings changed. Reload SKU assistance before saving.',code='conflict')
        yield case


def validate_body(data,allowed):
    if not isinstance(data,dict) or set(data)-set(allowed)-{'revision'}:
        raise ValidationError('Unsupported SKU mapping fields.')


def note(data,key):
    value=data.get(key,'')
    if not isinstance(value,str) or not value.strip() or len(value)>10000:
        raise ValidationError('A written review explanation of at most 10,000 characters is required.')
    return value.strip()


def event(alias,action,notes):
    alias.history=[*alias.history,dict(action=action,notes=notes,at=timezone.now().isoformat(),
        source=alias.source_snapshot,canonical=alias.canonical_snapshot,status=alias.status)]


def validate_pair(source,target):
    a,b=product(source),product(target)
    if not a['normalized_unit'] or a['normalized_unit']!=b['normalized_unit']:
        raise ValidationError('Mappings require the same explicit unit; unit conversions are not supported.')
    if a['normalized_code']==b['normalized_code']:
        raise ValidationError('These codes already normalize identically; use deterministic matching.')
    conflicts=incompatible_specs(a,b)
    if conflicts:
        raise ValidationError(conflicts)
    return a,b


def pending_alias(case,source,target,reason):
    a,b=validate_pair(source,target)
    rows=SKUAlias.objects.filter(**party_filter(case),source_system=a['source_system'],normalized_source_code=a['normalized_code'],
        normalized_unit=a['normalized_unit'],normalized_canonical_code=b['normalized_code'],status='pending').order_by('pk')
    existing=next((row for row in rows if row.source_reference==a['reference'] and row.source_snapshot==a and row.canonical_reference==b['reference'] and row.canonical_snapshot==b),None)
    if existing:
        return existing
    alias=SKUAlias(**party_filter(case),source_system=a['source_system'],source_item_code=a['code'],normalized_source_code=a['normalized_code'],
        canonical_item_code=b['code'],normalized_canonical_code=b['normalized_code'],source_description=a['description'],canonical_description=b['description'],
        unit_of_measure=a['unit'],normalized_unit=a['normalized_unit'],source_reference=a['reference'],canonical_reference=b['reference'],source_snapshot=a,canonical_snapshot=b,
        suggestion_reason=reason)
    event(alias,'proposed',reason)
    alias.save()
    return alias


def get_alias(case,data):
    if type(data.get('alias_id')) is not int:
        raise ValidationError('Choose a valid mapping ID.')
    alias=SKUAlias.objects.select_for_update().filter(**party_filter(case),pk=data['alias_id']).first()
    if alias is None:
        raise ValidationError('The mapping does not belong to this supplier/customer and scope.')
    if data.get('alias_revision')!=revision(alias):
        raise ValidationError('This mapping changed. Reload before reviewing.',code='conflict')
    return alias


def refresh_cases(case):
    key=party_key(mode_for(case))+'_id'
    for row in type(case).objects.filter(**{key:getattr(case,key)}).order_by('pk'):
        row.refresh_reconciliation_status()


def approve_mapping(case,data):
    validate_body(data,('alias_id','alias_revision','source_reference','canonical_reference','approval_notes'))
    notes=note(data,'approval_notes')
    with locked_catalog(case,data) as case:
        if 'alias_id' in data:
            alias=get_alias(case,data)
            if alias.status!='pending':
                raise ValidationError('Only pending mappings can be approved; deactivate an incorrect approval before replacing it.')
            source=get_line(case,alias.source_reference,lock=True)
            target=get_line(case,alias.canonical_reference,lock=True)
            if product(source)!=alias.source_snapshot or product(target)!=alias.canonical_snapshot:
                raise ValidationError('The proposal source or target changed. Request a fresh proposal or select the known products manually.',code='conflict')
        else:
            source=get_line(case,data.get('source_reference'),linked=True,lock=True)
            target=get_line(case,data.get('canonical_reference'),lock=True)
            alias=pending_alias(case,source,target,'Manually selected known equivalent; approval requested explicitly.')
        a,b=validate_pair(source,target)
        active=SKUAlias.objects.filter(**party_filter(case),normalized_unit=a['normalized_unit'],status='approved')
        if active.filter(source_system=a['source_system'],normalized_source_code=a['normalized_code']).exclude(pk=alias.pk).exists():
            raise ValidationError('An approved mapping already exists for this source code, namespace and unit. Deactivate it explicitly before replacing it.')
        if active.filter(normalized_source_code=b['normalized_code']).exists() or active.filter(normalized_canonical_code=a['normalized_code']).exists():
            raise ValidationError('Alias chains or cycles are not supported. Select a known canonical code that is not itself an alias.')
        alias.status,alias.approval_notes,alias.approved_at='approved',notes,timezone.now()
        event(alias,'approved',notes)
        alias.save()
        refresh_cases(case)
        return alias


def reject_mapping(case,data):
    validate_body(data,('alias_id','alias_revision','reason'))
    reason=note(data,'reason')
    with locked_catalog(case,data) as case:
        alias=get_alias(case,data)
        if alias.status!='pending':
            raise ValidationError('Only pending proposals can be rejected.')
        alias.status,alias.approval_notes='rejected',reason
        event(alias,'rejected',reason)
        alias.save()
        return alias


def deactivate_mapping(case,data):
    validate_body(data,('alias_id','alias_revision','reason'))
    reason=note(data,'reason')
    with locked_catalog(case,data) as case:
        alias=get_alias(case,data)
        if alias.status!='approved':
            raise ValidationError('Only approved mappings can be deactivated.')
        alias.status,alias.approval_notes='deactivated',reason
        event(alias,'deactivated',reason)
        alias.save()
        refresh_cases(case)
        return alias
