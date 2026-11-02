"""Observed accounting lines, not a new inventory/product master."""
from django.core.exceptions import ValidationError
from accounts_receivable.services.catalog import model, party_key
from .normalization import normalize_sku, normalize_unit

KINDS={'purchase_order':('purchase_orders','purchase_order'),'delivery_receipt':('delivery_receipts','delivery_receipt'),'sales_invoice':('sales_invoices','invoice')}


def mode_for(case):
    return 'ap' if case._meta.app_label=='accounts_payable' else 'ar'


def parent_for(line):
    return next(getattr(line,field) for field in ('purchase_order','delivery_receipt','invoice') if hasattr(line,field+'_id'))


def namespace(document):
    return f'erp:{document.source_database_id}' if document.source_database_id else 'document' if document.source_document_id else 'local'


def reference(line):
    parent=parent_for(line)
    kind='purchase_order' if hasattr(line,'purchase_order_id') else 'delivery_receipt' if hasattr(line,'delivery_receipt_id') else 'sales_invoice'
    return dict(kind=kind,record_id=parent.pk,line_id=line.pk)


def product(line):
    document=parent_for(line)
    return dict(reference=reference(line),code=line.item_code,description=line.description,unit=line.unit_of_measure,
                normalized_code=normalize_sku(line.item_code),normalized_unit=normalize_unit(line.unit_of_measure),
                source_system=namespace(document),
                provenance=dict(source_document_id=document.source_document_id,source_database_id=document.source_database_id,
                    source_table_id=document.source_table_id,source_record_key=document.source_record_key or {}))


def party_filter(case):
    return {'scope':mode_for(case),party_key(mode_for(case))+'_id':getattr(case,party_key(mode_for(case))+'_id')}


def get_line(case, ref, *, linked=False, lock=False):
    if not isinstance(ref,dict) or set(ref)-{'kind','record_id','line_id'} or not isinstance(ref.get('kind'),str) or ref['kind'] not in KINDS or any(type(ref.get(field)) is not int for field in ('record_id','line_id')):
        raise ValidationError('Choose an existing product line reference.')
    mode=mode_for(case)
    relation,parent=KINDS[ref['kind']]
    Header=model(mode,ref['kind'])
    query=Header.objects.filter(pk=ref['record_id'],**{party_key(mode)+'_id':getattr(case,party_key(mode)+'_id')})
    if linked:
        query=query.filter(pk__in=getattr(case,relation).values('pk'))
    if lock:
        query=query.select_for_update()
    document=query.first()
    if document is None:
        raise ValidationError('Product references must belong to this supplier/customer and selected scope.')
    lines=document.lines.filter(pk=ref['line_id'])
    if lock:
        lines=lines.select_for_update()
    line=lines.first()
    if line is None or not normalize_sku(line.item_code):
        raise ValidationError('The referenced product line is unavailable or has no SKU.')
    return line


def known_lines(case, *, limit=2000):
    mode=mode_for(case)
    remaining=limit
    for kind,(relation,parent) in KINDS.items():
        Header=model(mode,kind)
        Line=Header._meta.get_field('lines').related_model
        rows=Line.objects.filter(**{parent+'__'+party_key(mode)+'_id':getattr(case,party_key(mode)+'_id')}).exclude(item_code='').select_related(parent).order_by('pk')[:remaining]
        for line in rows:
            yield line
            remaining-=1
        if remaining<=0:
            break


def case_lines(case):
    for relation,parent in KINDS.values():
        for document in getattr(case,relation).order_by('pk'):
            yield from document.lines.order_by('pk')
