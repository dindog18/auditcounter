"""Confirm model formatting and missing-unit differences within a PO case."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from accounts_receivable.services.catalog import check_revision, model, party_key

from .references import same_reference


def identity(line):
    return [line.item_code, line.unit_of_measure]


def evidence(order_line, receipt_line):
    return {'order': identity(order_line), 'delivery': identity(receipt_line)}


def can_confirm(order_line, receipt_line):
    order_code, order_unit = identity(order_line)
    receipt_code, receipt_unit = identity(receipt_line)
    units = {unit.strip().casefold() for unit in (order_unit, receipt_unit)} - {''}
    return (identity(order_line) != identity(receipt_line)
            and same_reference(order_code, receipt_code) and len(units) <= 1
            and order_line.quantity_ordered > 0 and receipt_line.quantity_accepted > 0)


@transaction.atomic
def save_delivery_review(mode, case_id, data):
    from .reconciliation import receipt_accepts_lines

    Case = model(mode, 'POReconciliation')
    case = get_object_or_404(Case, pk=case_id)
    order = case.purchase_order
    party = party_key(mode)
    account_id = getattr(order, party + '_id')
    if not account_id:
        raise ValidationError('Set the PO account before confirming delivery matches.')
    model(mode, party).objects.select_for_update().get(pk=account_id)
    receipt_id, order_id = data.get('receiptLineId'), data.get('orderLineId')
    reason = data.get('reason', '')
    if type(receipt_id) is not int or (order_id is not None and type(order_id) is not int):
        raise ValidationError('Choose a delivery line and a PO line.')
    if order_id is not None and (not isinstance(reason, str) or len(reason.strip()) > 500):
        raise ValidationError('The review note must be text of up to 500 characters.')

    # Lock line records before the PO, in the same order as invoice reviews.
    order_line = None
    if order_id is not None:
        OrderLine = model(mode, type(order).__name__ + 'Line')
        order_line = get_object_or_404(OrderLine.objects.select_for_update(), pk=order_id, purchase_order=order)
        ReceiptLine = model(mode, model(mode, 'delivery_receipt').__name__ + 'Line')
        receipt_line = get_object_or_404(ReceiptLine.objects.select_for_update(),
                                         pk=receipt_id, delivery_receipt__purchase_order=order)
    order = type(order).objects.select_for_update().get(pk=order.pk)
    case = Case.objects.select_for_update().get(pk=case_id)
    check_revision(case, data.get('revision'))

    if order.status == 'cancelled' or getattr(order, party + '_id') != account_id:
        raise ValidationError('Confirm delivery matches on an active PO for this account.')
    key = str(receipt_id)
    if order_line is None:
        case.delivery_reviews.pop(key, None)
    else:
        receipt = receipt_line.delivery_receipt
        if (receipt.purchase_order_id != order.pk or getattr(receipt, party + '_id') != account_id
                or not receipt_accepts_lines(receipt) or not can_confirm(order_line, receipt_line)):
            raise ValidationError('Choose an accepted delivery and a PO line with the same model and compatible units.')
        case.delivery_reviews[key] = {
            'orderLineId': order_id, 'evidence': evidence(order_line, receipt_line),
            'reason': reason.strip(), 'reviewedAt': timezone.now().isoformat(),
        }
    case.save(update_fields=['delivery_reviews'])
    case.refresh()
    return case
