from django.urls import reverse
from accounts_receivable.services.catalog import revision
from ..models import SKUAlias,SKUSuggestionAttempt
from .products import mode_for,product,parent_for,case_lines,known_lines,party_filter
from .mapping import catalog_revision,target_is_current,compare_products,resolver_session


def record_url(ref,case):
    routes={'purchase_order':'purchase_order','delivery_receipt':'delivery_receipt','sales_invoice':'invoice'}
    if not isinstance(ref,dict) or ref.get('kind') not in routes or type(ref.get('record_id')) is not int:
        return None
    namespace='ACCOUNTS_PAYABLE' if mode_for(case)=='ap' else 'ACCOUNTS_RECEIVABLE'
    return reverse(f"{namespace}:{routes[ref['kind']]}_detail",args=[ref['record_id']])


def present_product(line,case):
    data=product(line)
    document=parent_for(line)
    namespace='ACCOUNTS_PAYABLE' if mode_for(case)=='ap' else 'ACCOUNTS_RECEIVABLE'
    route={'purchase_order':'purchase_order','delivery_receipt':'delivery_receipt','sales_invoice':'invoice'}[data['reference']['kind']]
    data.update(key=f"{data['reference']['kind']}:{document.pk}:{line.pk}",
        record_reference=next(getattr(document,field) for field in ('po_reference_no','dr_reference_no','invoice_reference_no') if hasattr(document,field)),
        record_url=reverse(f'{namespace}:{route}_detail',args=[document.pk]),
        document_url=f'/documents/{document.source_document_id}/' if document.source_document_id else None,
        database_url=f'/databases/{document.source_database_id}/' if document.source_database_id else None)
    return data


def workspace_state(case):
    with resolver_session(case):
        lines=[line for line in case_lines(case) if line.item_code]
        sources=[]
        for line in lines:
            info=present_product(line,case)
            groups={'purchase_order','delivery_receipt','sales_invoice'}-{info['reference']['kind']}
            info['needs_mapping']=any(not any(product(other)['reference']['kind']==kind and compare_products(line,other,case)['equivalent'] for other in lines) for kind in groups)
            sources.append(info)
        sources.sort(key=lambda row:(not row['needs_mapping'],row['reference']['kind']!='sales_invoice',row['key']))
        aliases=[dict(id=alias.pk,source_code=alias.source_item_code,canonical_code=alias.canonical_item_code,
            source_description=alias.source_description,canonical_description=alias.canonical_description,unit=alias.unit_of_measure,
            source_system=alias.source_system,status=alias.status,source_url=record_url(alias.source_reference,case),canonical_url=record_url(alias.canonical_reference,case),reason=alias.suggestion_reason,approval_notes=alias.approval_notes,
            target_current=target_is_current(alias,case),history=alias.history,revision=revision(alias),
            approved_at=alias.approved_at.isoformat() if alias.approved_at else None)
            for alias in SKUAlias.objects.filter(**party_filter(case)).order_by('-created_at','-pk')]
        keys={row['key'] for row in sources}
        attempts=[]
        for attempt in SKUSuggestionAttempt.objects.filter(**party_filter(case)).order_by('-pk')[:50]:
            ref=attempt.source_reference
            if f"{ref['kind']}:{ref['record_id']}:{ref['line_id']}" in keys:
                attempts.append(dict(id=attempt.pk,status=attempt.status,source=attempt.input_product,provider=attempt.provider,model=attempt.model_name,
                    suggestion=attempt.suggested_target,errors=attempt.validation_errors,alias_id=attempt.alias_id,created_at=attempt.created_at.isoformat()))
        return dict(revision=catalog_revision(case),sources=sources,targets=[present_product(line,case) for line in known_lines(case)],aliases=aliases,attempts=attempts[:10])
