"""Deterministic, read-only matching proposals shared by AP and AR."""

from decimal import Decimal
from importlib import import_module

from django.core.exceptions import ValidationError
from django.db.models import Q

from .catalog import model, party_key, revision, check_revision
from .records import case_membership, matches, prepare_matches, merge_match_rows

ZERO = Decimal('0')


def normalize_item_code(value):
    """Casefold and collapse whitespace; never infer product equivalence."""
    from sku_matching.services.normalization import normalize_sku
    return normalize_sku(value)


def mode_for(case):
    return 'ap' if case._meta.app_label == 'accounts_payable' else 'ar'


def reconciliation_service(case):
    return import_module(f'{case._meta.app_label}.services.reconciliation')


def source_revision(case, *, lock=False):
    """Fingerprint source evidence and allocations, beyond the existing case revision.

    Confirmation locks the same source line types/order used by save_matches before
    comparing this fingerprint. Source edits and competing saves must then wait.
    """
    case = type(case).objects.get(pk=case.pk)
    snapshot, query = {}, Q(pk__in=[])
    for relation, header, match_field in (
        ('sales_invoices', 'invoice', 'invoice_line_id'),
        ('purchase_orders', 'purchase_order', 'purchase_order_line_id'),
        ('delivery_receipts', 'delivery_receipt', 'delivery_receipt_line_id'),
    ):
        documents = getattr(case, relation).order_by('pk')
        if lock:
            documents = documents.select_for_update()
        documents = list(documents)
        snapshot[relation] = []
        line_ids = []
        if documents:
            Line = documents[0].lines.model
            lines = Line.objects.filter(**{header+'__in': documents}).order_by('pk')
            if lock:
                lines = lines.select_for_update()
            lines = list(lines)
            line_ids = [line.pk for line in lines]
            snapshot[relation] = [[revision(document) for document in documents],
                                  [revision(line) for line in lines]]
        query |= Q(**{match_field+'__in': line_ids})
    snapshot['allocations'] = list(model(mode_for(case), 'DocumentMatch').objects.filter(query).order_by('pk').values())
    from sku_matching.services.mapping import approved_catalog_state
    snapshot['sku_mappings'] = approved_catalog_state(case)
    snapshot['membership'] = case_membership(case)
    return revision(case, snapshot)


def get_available_quantities(case, current=None):
    """Saved allocations in every case reserve capacity; current may replace this case's draft."""
    available = {}
    for relation, field, capacity in (
        ('sales_invoices', 'invoice_line', 'quantity_invoiced'),
        ('purchase_orders', 'purchase_order_line', 'quantity_ordered'),
        ('delivery_receipts', 'delivery_receipt_line', 'quantity_accepted'),
    ):
        available[field] = {}
        for document in getattr(case, relation).order_by('pk'):
            for line in document.lines.order_by('pk'):
                saved = line.matches.all()
                if current is not None:
                    saved = saved.exclude(transaction=case)
                used = sum((row.matched_quantity for row in saved
                            if row.purchase_order_line_id and row.delivery_receipt_line_id), ZERO)
                if current is not None:
                    used += sum((row.matched_quantity for row in current if getattr(row, field+'_id') == line.pk), ZERO)
                available[field][line.pk] = max(getattr(line, capacity) - used, ZERO)
    return available


def document_issues(case, document, kind):
    key = party_key(mode_for(case))
    issues = []
    if not getattr(case, key+'_id') or getattr(document, key+'_id') != getattr(case, key+'_id'):
        issues.append('Document party differs from the case.')
    if hasattr(document, 'currency') and document.currency != case.currency:
        issues.append('Document currency differs from the case.')
    reference, date, status, allowed = {
        'invoice': ('invoice_reference_no', 'invoice_date', 'invoice_status', {'posted', 'disputed'} if mode_for(case) == 'ap' else {'posted'}),
        'order': ('po_reference_no', 'order_date', 'status', {'open', 'closed'}),
        'receipt': ('dr_reference_no', 'delivery_date', 'receipt_status' if mode_for(case) == 'ap' else 'delivery_status',
                    {'accepted', 'partial'} if mode_for(case) == 'ap' else {'delivered', 'partially_accepted'}),
    }[kind]
    if not (getattr(document, reference) or '').strip() or not getattr(document, date):
        issues.append(f'{kind.title()} reference and date are required.')
    if getattr(document, status) not in allowed:
        issues.append(f'{kind.title()} status requires review: {getattr(document, status)}.')
    return issues


def find_candidate_lines(case, invoice_line):
    """Only linked documents; return all same-code candidates, never choose by ordering."""
    from sku_matching.services.mapping import compare_products
    code = normalize_item_code(invoice_line.item_code)
    return {
        'orders': [line for doc in case.purchase_orders.order_by('pk') for line in doc.lines.order_by('pk')
                   if code and (normalize_item_code(line.item_code)==code or compare_products(invoice_line,line,case)['equivalent'])],
        'receipts': [line for doc in case.delivery_receipts.order_by('pk') for line in doc.lines.order_by('pk')
                     if code and (normalize_item_code(line.item_code)==code or compare_products(invoice_line,line,case)['equivalent'])],
    }


def evaluate_match_candidate(invoice_line, po_line, dr_line, *, case, quantity):
    """Use the manual relationship validator and the existing financial evaluator."""
    match = model(mode_for(case), 'DocumentMatch')(
        transaction=case, invoice_line=invoice_line, purchase_order_line=po_line,
        delivery_receipt_line=dr_line, matched_quantity=quantity, match_status='matched')
    issues = []
    for document, kind in ((invoice_line.invoice, 'invoice'), (po_line.purchase_order, 'order'), (dr_line.delivery_receipt, 'receipt')):
        issues.extend(document_issues(case, document, kind))
    from sku_matching.services.mapping import identity_for_match
    from sku_matching.services.normalization import normalize_unit
    codes = [normalize_item_code(line.item_code) for line in (invoice_line, po_line, dr_line)]
    units = [normalize_unit(line.unit_of_measure) for line in (invoice_line, po_line, dr_line)]
    identity = identity_for_match(match)
    if not all(codes) or not identity['equivalent']:
        issues.extend(identity['reasons'])
    if not all(units) or len(set(units)) != 1:
        issues.append('Compatible explicit units are required; no unit conversion is assumed.')
    service = reconciliation_service(case)
    try:
        match.clean_fields()
        service.validate_match(match, check_amounts=False, check_capacity=False)
    except ValidationError as error:
        issues.extend(error.messages)
    result = dict(invoice_line_id=invoice_line.pk, purchase_order_line_id=po_line.pk,
                  delivery_receipt_line_id=dr_line.pk, matched_quantity=str(quantity),
                  eligible=not issues, status='needs_review', reasons=list(dict.fromkeys(issues)))
    if issues:
        return result
    evaluation = service.evaluate_reconciliation(case, [match])
    result['sku_identity'] = identity
    result['price_variance'] = str(evaluation['priceVariance'])
    result['financial_variance'] = str(evaluation['financialVariance'])
    result['findings'] = evaluation['findings']
    result['status'] = 'needs_review' if evaluation['status'] == 'exception' else 'suggested'
    result['reasons'] = ['Same case and party', 'Compatible currency', 'Valid document references and statuses',
                         'Approved scoped SKU equivalence' if identity['mappings'] else 'Exact normalized SKU', 'Compatible unit of measure', 'Ordered and accepted quantity available']
    if result['status'] == 'needs_review':
        result['reasons'].extend(finding['message'] for finding in evaluation['findings']
                                 if finding['kind'] not in {'unsupported_quantity', 'outstanding_order', 'receiving_shortage'})
    else:
        result['reasons'].append('Price, discount and tax within tolerance; document arithmetic valid')
    return result


def generate_match_suggestions(case, *, current_rows=None):
    from sku_matching.services.mapping import resolver_session
    case = type(case).objects.get(pk=case.pk)
    with resolver_session(case):
        return _generate_match_suggestions(case, current_rows=current_rows)


def _generate_match_suggestions(case, *, current_rows=None):
    """Propose only unambiguous relationships; ambiguous alternatives reserve nothing."""
    before = source_revision(case)
    mode = mode_for(case)
    existing = list(case.line_matches.order_by('pk'))
    current = prepare_matches(mode, case, merge_match_rows(case, current_rows)) if current_rows is not None else existing
    available = get_available_quantities(case, current)
    response = dict(case_id=case.pk, revision=revision(case, [case_membership(case), matches(case)]),
                    suggestion_revision=before, suggestions=[], needs_review=[], unmatched=[], lines=[])
    invoice_lines = [line for doc in case.sales_invoices.order_by('pk') for line in doc.lines.order_by('pk')]
    existing_keys = {(row.invoice_line_id, row.purchase_order_line_id, row.delivery_receipt_line_id) for row in current}
    external_keys = set(model(mode, 'DocumentMatch').objects.filter(invoice_line_id__in=[line.pk for line in invoice_lines]).exclude(transaction=case).values_list('invoice_line_id', 'purchase_order_line_id', 'delivery_receipt_line_id'))
    planned = []
    # A shared source with competing invoice lines is a business ambiguity, not a sorting problem.
    candidates = {line.pk: find_candidate_lines(case, line) for line in invoice_lines}
    for line in invoice_lines:
        needed = available['invoice_line'][line.pk]
        summary = dict(invoice_line_id=line.pk, quantity_to_allocate=str(needed), remaining_unmatched_quantity=str(needed))
        response['lines'].append(summary)
        if needed <= ZERO:
            continue
        found = candidates[line.pk]
        if not found['orders'] or not found['receipts']:
            linked = case.purchase_orders.exists() and case.delivery_receipts.exists()
            target = 'needs_review' if linked else 'unmatched'
            response[target].append(dict(invoice_line_id=line.pk, status='needs_review' if linked else 'unmatched',
                reasons=['Missing or different SKU in linked PO/DR lines; review source evidence.' if linked else 'Linked order or receiving evidence is unavailable.'], candidates=[]))
            continue
        if len(found['orders']) * len(found['receipts']) > 1000:
            response['needs_review'].append(dict(invoice_line_id=line.pk, status='needs_review',
                reasons=['More than 1,000 candidate relationships; narrow the linked documents or match manually.'], candidates=[]))
            continue
        options = []
        blocked = []
        for order in found['orders']:
            for receipt in found['receipts']:
                key = (line.pk, order.pk, receipt.pk)
                quantity = min(needed, available['purchase_order_line'][order.pk], available['delivery_receipt_line'][receipt.pk])
                if (key in existing_keys or key in external_keys) and quantity > ZERO:
                    blocked.append(dict(invoice_line_id=line.pk, purchase_order_line_id=order.pk,
                        delivery_receipt_line_id=receipt.pk, maximum_quantity=str(quantity), eligible=False, status='needs_review',
                        reasons=['This relationship already has a saved or draft allocation. Edit it manually to increase its quantity; Auto Match will not duplicate or overwrite it.']))
                    continue
                if quantity <= ZERO:
                    continue
                candidate = evaluate_match_candidate(line, order, receipt, case=case, quantity=quantity)
                (options if candidate['eligible'] else blocked).append(candidate)
        if not options:
            response['needs_review' if blocked else 'unmatched'].append(dict(invoice_line_id=line.pk,
                status='needs_review' if blocked else 'unmatched', candidates=blocked,
                reasons=['Candidate documents require review.'] if blocked else ['No unused compatible allocation has available quantity.']))
            continue
        order_ids = {row['purchase_order_line_id'] for row in options}
        receipt_ids = {row['delivery_receipt_line_id'] for row in options}
        competing = any(other.pk != line.pk and available['invoice_line'][other.pk] > ZERO and (
            order_ids.intersection(order.pk for order in candidates[other.pk]['orders']) or
            receipt_ids.intersection(receipt.pk for receipt in candidates[other.pk]['receipts'])) for other in invoice_lines)
        capacity = sum((available['delivery_receipt_line'][pk] for pk in receipt_ids), ZERO)
        order_capacity = available['purchase_order_line'][next(iter(order_ids))] if len(order_ids) == 1 else ZERO
        target_quantity = min(needed, order_capacity, capacity)
        ambiguous = len(order_ids) > 1 or competing or (len(receipt_ids) > 1 and capacity > target_quantity)
        if ambiguous:
            reasons = []
            if len(order_ids) > 1:
                reasons.append('Multiple plausible PO lines; no explicit document reference distinguishes them.')
            if competing:
                reasons.append('Multiple invoice lines compete for the same order or receipt evidence.')
            if len(receipt_ids) > 1 and capacity > target_quantity:
                reasons.append('Several receipts could supply the quantity; selecting a subset requires review.')
            alternatives = []
            for candidate in options:
                alternative = dict(candidate)
                alternative['maximum_quantity'] = alternative.pop('matched_quantity')
                alternative['status'] = 'needs_review'
                alternatives.append(alternative)
            response['needs_review'].append(dict(invoice_line_id=line.pk, status='needs_review', reasons=reasons, candidates=alternatives))
            continue
        allocated = ZERO
        for candidate in options:
            # With one PO and all receipts needed, allocation is independent of iteration order.
            quantity = Decimal(candidate['matched_quantity'])
            allocated += quantity
            planned.append(candidate)
            response['suggestions' if candidate['status'] == 'suggested' else 'needs_review'].append(candidate)
        summary['remaining_unmatched_quantity'] = str(max(needed - allocated, ZERO))
        if allocated < needed:
            response['unmatched'].append(dict(invoice_line_id=line.pk, status='unmatched',
                quantity=str(needed-allocated), reasons=['Accepted receiving or ordered capacity is insufficient for the remaining invoice quantity.']))
    # Evaluate the combined proposal, including manual rows, to catch aggregate tolerances.
    combined_rows = [dict(invoiceLineId=row.invoice_line_id, orderLineId=row.purchase_order_line_id,
                          receiptLineId=row.delivery_receipt_line_id, quantity=str(row.matched_quantity)) for row in current]
    combined_rows += [allocation_row(candidate) for candidate in planned]
    if planned:
        prepared = prepare_matches(mode, case, combined_rows)
        evaluation = reconciliation_service(case).evaluate_reconciliation(case, prepared)
        response['evaluation'] = evaluation
        if evaluation['status'] == 'exception':
            for candidate in list(response['suggestions']):
                candidate['status'] = 'needs_review'
                candidate['reasons'].append('Combined reconciliation contains financial or source-data findings; preview and review before saving.')
                response['needs_review'].append(candidate)
            response['suggestions'] = []
    if source_revision(case) != before:
        raise ValidationError('Source evidence or allocations changed. Run Auto Match again.', code='conflict')
    return response


def allocation_row(candidate):
    return dict(invoiceLineId=candidate['invoice_line_id'], orderLineId=candidate['purchase_order_line_id'],
                receiptLineId=candidate['delivery_receipt_line_id'], quantity=candidate['matched_quantity'])
