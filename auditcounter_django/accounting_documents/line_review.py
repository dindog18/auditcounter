"""Review invoice lines within a PO case using the existing match records."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404

from accounts_receivable.services.catalog import check_revision, model, party_key


def validate_units(invoice_line, order_line, receipt_line):
    units = {line.unit_of_measure.strip().casefold() for line in (invoice_line, order_line, receipt_line)}
    if len(units - {''}) > 1:
        raise ValidationError('The invoice, PO, and delivery lines must use the same unit of measure.')


def scoped_matches(mode, order):
    return model(mode, 'DocumentMatch').objects.filter(
        invoice_line__invoice__purchase_order=order,
        purchase_order_line__purchase_order=order,
    ).select_related('transaction', 'invoice_line__invoice', 'purchase_order_line__purchase_order',
                     'delivery_receipt_line__delivery_receipt').order_by('pk')


@transaction.atomic
def save_review(mode, case_id, data):
    from .reconciliation import receipt_accepts_lines

    case = get_object_or_404(model(mode, 'POReconciliation'), pk=case_id)
    order = case.purchase_order
    party = party_key(mode)
    account_id = getattr(order, party + '_id')
    model(mode, party).objects.select_for_update().get(pk=account_id)

    invoice_id = data.get('invoiceLineId')
    rows = data.get('matches')
    if type(invoice_id) is not int or not isinstance(rows, list) or len(rows) > 1000:
        raise ValidationError('Choose an invoice line and provide up to 1,000 matches.')
    Match = model(mode, 'DocumentMatch')
    quantity_field = Match._meta.get_field('matched_quantity')
    order_ids, receipt_ids, pairs = set(), set(), set()
    quantities = []
    for row in rows:
        if not isinstance(row, dict) or any(type(row.get(key)) is not int for key in ('orderLineId', 'receiptLineId')):
            raise ValidationError('Choose a purchase order line and an accepted delivery line for each match.')
        pair = (row['orderLineId'], row['receiptLineId'])
        if pair in pairs:
            raise ValidationError('Use one allocation per PO and delivery line pair.')
        pairs.add(pair)
        quantity = quantity_field.clean(row.get('quantity'), None)
        if quantity <= 0:
            raise ValidationError('Matched quantity must be positive.')
        quantities.append(quantity)
        order_ids.add(row['orderLineId'])
        receipt_ids.add(row['receiptLineId'])

    def lock_lines(target, ids):
        header = model(mode, target)
        Line = model(mode, header.__name__ + 'Line')
        return Line.objects.select_for_update().filter(pk__in=ids).order_by('pk').in_bulk()

    # Match writes take line locks before refreshing the PO snapshot.
    invoices = lock_lines('sales_invoice', [invoice_id])
    orders = lock_lines('purchase_order', order_ids)
    receipts = lock_lines('delivery_receipt', receipt_ids)
    order = type(order).objects.select_for_update().get(pk=order.pk)
    case.refresh_from_db()
    check_revision(case, data.get('revision'))
    invoice_line = invoices.get(invoice_id)
    if (order.status == 'cancelled' or not invoice_line or invoice_line.invoice.purchase_order_id != order.pk
            or invoice_line.invoice.invoice_status == 'void'):
        raise ValidationError('Choose an active invoice line linked to this purchase order.')
    if len(orders) != len(order_ids) or any(line.purchase_order_id != order.pk for line in orders.values()):
        raise ValidationError('Choose lines from this purchase order.')
    if len(receipts) != len(receipt_ids) or any(
        line.delivery_receipt.purchase_order_id != order.pk or not receipt_accepts_lines(line.delivery_receipt)
        for line in receipts.values()
    ):
        raise ValidationError('Choose accepted delivery lines linked to this purchase order.')

    existing = scoped_matches(mode, order).filter(invoice_line=invoice_line)
    # Replace only this invoice line's reviews for the current PO.
    existing.delete()
    if rows:
        Transaction = model(mode, 'Transaction')
        review_case = (Transaction.objects.filter(**{party + '_id': account_id}, currency=order.currency)
                       .annotate(order_count=Count('purchase_orders')).filter(order_count=1, purchase_orders=order)
                       .order_by('pk').first())
        if review_case is None:
            review_case = Transaction.objects.create(**{party + '_id': account_id}, currency=order.currency,
                                                     transaction_date=order.order_date)
            review_case.purchase_orders.add(order)
        review_case.sales_invoices.add(invoice_line.invoice)
        review_case.delivery_receipts.add(*(line.delivery_receipt_id for line in receipts.values()))
        for row, quantity in zip(rows, quantities):
            validate_units(invoice_line, orders[row['orderLineId']], receipts[row['receiptLineId']])
            Match.objects.create(transaction=review_case, invoice_line=invoice_line,
                                 purchase_order_line=orders[row['orderLineId']],
                                 delivery_receipt_line=receipts[row['receiptLineId']],
                                 matched_quantity=quantity, match_status='matched')
    case.refresh()
    return case
