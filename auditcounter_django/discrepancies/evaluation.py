"""Pure data builders: deterministic finding descriptions and bounded source evidence."""
from datetime import date, datetime
from decimal import Decimal, localcontext, ROUND_HALF_UP


def json_value(value):
    if isinstance(value, (Decimal, date, datetime)):
        return format(value,'f') if isinstance(value, Decimal) else value.isoformat()
    if isinstance(value, dict):
        return {str(key):json_value(item) for key,item in value.items()}
    if isinstance(value, (tuple,list)):
        return [json_value(item) for item in value]
    return value


def source_evidence(document, line=None):
    """Only accounting fields/provenance; never copy files, credentials or ERP datasets."""
    header_fields = ('po_reference_no','dr_reference_no','invoice_reference_no','order_date','delivery_date','invoice_date',
                     'supplier_id','customer_id','currency','status','receipt_status','delivery_status','invoice_status',
                     'subtotal','discount_amount','tax_amount','other_charges','total_amount')
    line_fields = ('line_no','description','item_code','unit_of_measure','quantity_ordered','quantity_stated','quantity_received',
                   'quantity_accepted','quantity_rejected','quantity_invoiced','unit_price','discount_amount','tax_amount','line_total')
    observed = {name:getattr(document,name) for name in header_fields if hasattr(document,name)}
    if line is not None:
        observed['line'] = {name:getattr(line,name) for name in line_fields if hasattr(line,name)}
    provenance = dict(source_document_id=document.source_document_id, source_database_id=document.source_database_id,
                      source_table_id=document.source_table_id)
    if document.source_document_id:
        provenance['file_name'] = document.source_document.file_name
    if document.source_database_id:
        provenance['source_name'] = document.source_database.name
        provenance['database_name'] = document.source_database.database_name
    if document.source_table_id:
        provenance['table_name'] = f'{document.source_table.schema.name}.{document.source_table.name}'
    return json_value(dict(
        evidence_type='PO' if hasattr(document,'po_reference_no') else 'DR' if hasattr(document,'dr_reference_no') else 'SI',
        source_model=document._meta.label, source_record_id=str(document.pk), source_line_id=str(line.pk) if line else '',
        source_document_id=document.source_document_id, source_database_id=document.source_database_id,
        source_record_key=document.source_record_key or {}, provenance=provenance,
        field_name='line_values' if line else 'header_values', observed_value=observed))


def finding(code, identity, summary, expected, actual, evidence, *, amount=None, currency='', severity='warning', details=None):
    with localcontext() as context:
        context.prec = 40
        monetary = amount.quantize(Decimal('0.00000001'), rounding=ROUND_HALF_UP) if amount is not None else None
    return json_value(dict(finding_code=code, identity=identity, summary=summary, expected_value=expected,
        actual_value=actual, difference_amount=monetary, currency=currency, severity=severity, rule_version='1',
        details=details or {}, evidence=evidence))


def compatible_evidence(case, invoice_line, source_line, kind):
    from accounts_receivable.services.auto_matching import normalize_item_code, mode_for
    from accounts_receivable.services.catalog import party_key
    document = source_line.purchase_order if kind == 'PO' else source_line.delivery_receipt
    party = party_key(mode_for(case))+'_id'
    if getattr(document,party) != getattr(case,party) or (hasattr(document,'currency') and document.currency != case.currency):
        return False
    reference, date_field = ('po_reference_no','order_date') if kind == 'PO' else ('dr_reference_no','delivery_date')
    if not getattr(document,reference) or not getattr(document,date_field) or getattr(document,'status',None) == 'cancelled':
        return False
    from sku_matching.services.mapping import compare_products
    from sku_matching.services.normalization import normalize_unit
    if normalize_unit(invoice_line.unit_of_measure) != normalize_unit(source_line.unit_of_measure):
        return False
    if invoice_line.item_code or source_line.item_code:
        if not compare_products(invoice_line,source_line,case)['equivalent']:
            return False
    return True


def allocation_evidence(match):
    from sku_matching.services.mapping import identity_for_match
    return json_value(dict(evidence_type='ALLOCATION', source_model=match._meta.label,
        source_record_id=f'{match.invoice_line_id}:{match.purchase_order_line_id}:{match.delivery_receipt_line_id}',
        source_line_id=str(match.invoice_line_id), source_document_id=None, source_database_id=None,
        source_record_key={}, provenance={'transaction_model':match.transaction._meta.label,'transaction_id':match.transaction_id},
        field_name='allocation_values', observed_value={'invoice_line_id':match.invoice_line_id,
        'purchase_order_line_id':match.purchase_order_line_id, 'delivery_receipt_line_id':match.delivery_receipt_line_id,
        'matched_quantity':match.matched_quantity, 'sku_identity':identity_for_match(match)}))
