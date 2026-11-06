"""Close unserved PO quantities while preserving the source documents."""
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from accounts_receivable.services.catalog import check_revision, model, party_key

from .delivery_review import identity
from .references import same_reference

ZERO = Decimal('0')


def apply_closures(order_lines, closures, ordered, accepted, billed, allocated, confirmed_delivery, issues,
                   *, details, active):
    closed = defaultdict(lambda: ZERO)
    controls = defaultdict(list)
    closed_value = ZERO
    for line in order_lines:
        key = tuple(identity(line))
        saved = closures.get(str(line.pk))
        quantity = Decimal(saved['quantity']) if saved else ZERO
        valid = not saved or (saved['identity'] == list(key) and quantity <= line.quantity_ordered)
        if not valid:
            issues.append(f'PO line {line.line_no}: the item or quantity changed after closing. Reopen and review the line.')
            continue
        closed[key] += quantity
        if quantity:
            closed_value += line.line_total * quantity / line.quantity_ordered

    if details:
        unmatched = {key for quantities in (accepted, billed) for key, qty in quantities.items()
                     if qty > ZERO and key not in ordered}
        for line in order_lines:
            key = tuple(identity(line))
            saved = closures.get(str(line.pk))
            quantity = Decimal(saved['quantity']) if saved else ZERO
            valid = not saved or (saved['identity'] == list(key) and quantity <= line.quantity_ordered)
            available = ZERO
            if active and valid and not any(same_reference(key[0], other[0]) for other in unmatched):
                line_remaining = line.quantity_ordered - (allocated[line.pk] + confirmed_delivery[line.pk])
                group_remaining = ordered[key] - closed[key] - max(accepted[key], billed[key], ZERO)
                available = max(ZERO, min(line_remaining - quantity, group_remaining))
            if available or (active and saved):
                controls[key].append({
                    'lineId': line.pk, 'lineNumber': line.line_no, 'available': available,
                    'closed': quantity, 'stale': not valid,
                })

    return closed, controls, closed_value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


@transaction.atomic
def save_unserved(mode, case_id, data):
    from .reconciliation import calculate

    Case = model(mode, 'POReconciliation')
    case = get_object_or_404(Case, pk=case_id)
    order = case.purchase_order
    party = party_key(mode)
    account_id = getattr(order, party + '_id')
    if not account_id:
        raise ValidationError('Set the PO account before closing unserved quantities.')
    model(mode, party).objects.select_for_update().get(pk=account_id)

    line_id = data.get('orderLineId')
    raw_quantity = data.get('quantity')
    if (type(line_id) is not int or 'quantity' not in data
            or (raw_quantity is not None and not isinstance(raw_quantity, str))):
        raise ValidationError('Choose a PO line and enter a quantity.')
    line = get_object_or_404(order.lines.select_for_update(), pk=line_id)
    order = type(order).objects.select_for_update().get(pk=order.pk)
    case = Case.objects.select_for_update().get(pk=case_id)
    check_revision(case, data.get('revision'))
    if order.status == 'cancelled' or getattr(order, party + '_id') != account_id:
        raise ValidationError('Choose an active PO for this account.')

    key = str(line_id)
    if raw_quantity is None:
        case.unserved_closures.pop(key, None)
    else:
        quantity = line._meta.get_field('quantity_ordered').clean(raw_quantity, line)
        result = calculate(order, mode, details=True, unserved_closures=case.unserved_closures)
        control = next((item for check in result['quantityChecks'] for item in check['unservedControls']
                        if item['lineId'] == line_id), None)
        if not control or quantity <= ZERO or quantity > control['available']:
            raise ValidationError('Close only the remaining unserved quantity. Review any unmatched delivery or invoice first.')
        case.unserved_closures[key] = {
            'identity': identity(line), 'quantity': str(control['closed'] + quantity),
            'closedAt': timezone.now().isoformat(),
        }

    case.save(update_fields=['unserved_closures'])
    case.refresh()
    return case
