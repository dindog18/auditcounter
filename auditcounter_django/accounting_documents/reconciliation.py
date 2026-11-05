"""PO-led reconciliation with explicit document links and net payment matching."""
from collections import defaultdict
from decimal import Decimal

from django.apps import apps
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.utils import timezone

ZERO = Decimal('0')


def validate_purchase_order(record, mode):
    if record.pk:
        record._previous_po_id = type(record).objects.filter(pk=record.pk).values_list('purchase_order_id', flat=True).first()
        if record._previous_po_id != record.purchase_order_id and hasattr(record, 'deductions') and record.deductions.exists():
            raise ValidationError('Resolve this invoice’s deductions before changing its PO.')
    if not record.purchase_order_id:
        return
    from accounts_receivable.services.catalog import party_key
    key = party_key(mode)
    order = record.purchase_order
    errors = {}
    if getattr(order, key+'_id') != getattr(record, key+'_id'):
        errors['purchase_order'] = 'The PO must belong to the same account.'
    if hasattr(record, 'currency') and order.currency != record.currency:
        errors['purchase_order'] = 'The PO and invoice must use the same currency.'
    if order.status == 'cancelled':
        errors['purchase_order'] = 'A cancelled PO cannot receive documents.'
    if errors:
        raise ValidationError(errors)


def _line_key(line):
    # Item codes identify split deliveries; line number is the fallback for uncoded items.
    return (line.item_code.strip().casefold() or f'line:{line.line_no}', line.unit_of_measure.strip().casefold())


def receipt_status(receipt):
    return getattr(receipt, 'receipt_status', getattr(receipt, 'delivery_status', ''))


def receipt_accepts_lines(receipt):
    return receipt_status(receipt) in {'accepted', 'delivered', 'partial', 'partially_accepted'}


def calculate(order, mode, *, details=False):
    from accounts_receivable.services.extraction import validate_totals
    tolerance = Decimal(str(getattr(settings, 'RECONCILIATION_PRICE_TOLERANCE', '0.01')))
    receipts = list(order.delivery_receipts.all())
    confirmed_receipts = [row for row in receipts if receipt_accepts_lines(row) or receipt_status(row) == 'rejected']
    invoices = list(order.sales_invoices.exclude(invoice_status='void'))
    applied = list(order.deductions.filter(status='applied').select_related('invoice'))
    invoice_total = sum((row.total_amount for row in invoices), ZERO)
    deductions = sum((row.amount for row in applied), ZERO)
    net_due = invoice_total - deductions
    payments = sum((row.settled_amount for row in invoices), ZERO)
    issues = []
    payment_issues = []
    from .amounts import line_amount_issues
    from .line_review import scoped_matches, validate_units
    reviews = defaultdict(list)
    for match in scoped_matches(mode, order):
        reviews[match.invoice_line_id].append(match)
    line_results = {}
    billed_lines = defaultdict(list)
    order_lines = list(order.lines.all())
    ordered, accepted, billed = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    prices = defaultdict(set)
    for line in order_lines:
        ordered[_line_key(line)] += line.quantity_ordered
        prices[_line_key(line)].add(line.unit_price)
    for receipt in confirmed_receipts:
        if not receipt_accepts_lines(receipt):
            continue
        for line in receipt.lines.all():
            accepted[_line_key(line)] += line.quantity_accepted
    shortage = ZERO
    for invoice in invoices:
        lines = list(invoice.lines.all())
        try:
            validate_totals('sales_invoice', invoice, lines)
        except ValidationError as error:
            issues.extend(f'{invoice.invoice_reference_no}: {message}' for message in error.messages)
        for line in lines:
            key = _line_key(line)
            result = {'messages': line_amount_issues(line, 'quantity_invoiced', tolerance),
                      'reviewedQuantity': ZERO, 'matches': []}
            line_results[line.pk] = result
            for match in reviews[line.pk]:
                result['matches'].append({
                    'orderLineId': match.purchase_order_line_id,
                    'receiptLineId': match.delivery_receipt_line_id,
                    'quantity': match.matched_quantity,
                })
                try:
                    if match.match_status != 'matched' or not match.delivery_receipt_line_id:
                        raise ValidationError('Review this saved line match.')
                    receipt = match.delivery_receipt_line.delivery_receipt
                    if receipt.purchase_order_id != order.pk or not receipt_accepts_lines(receipt):
                        raise ValidationError('The selected delivery line no longer supplies accepted quantity for this PO.')
                    validate_units(line, match.purchase_order_line, match.delivery_receipt_line)
                    match.clean()
                except ValidationError as error:
                    result['messages'].extend(error.messages)
                    continue
                quantity = match.matched_quantity
                result['reviewedQuantity'] += quantity
                ordered[_line_key(match.purchase_order_line)] -= quantity
                accepted[_line_key(match.delivery_receipt_line)] -= quantity
            remaining = line.quantity_invoiced - result['reviewedQuantity']
            if remaining > ZERO:
                billed[key] += remaining
                billed_lines[key].append(result)
                if key not in ordered:
                    result['messages'].append(f'Item {line.item_code or line.line_no} is not on the PO.')
                elif len(prices[key]) > 1 or any(abs(price-line.unit_price) > tolerance for price in prices[key]):
                    result['messages'].append('Review the PO line because prices differ or more than one price is possible.')
            issues.extend(f'{invoice.invoice_reference_no}, line {line.line_no} — {message}'
                          for message in result['messages'])
    try:
        validate_totals('purchase_order', order, order_lines)
    except ValidationError as error:
        issues.extend(error.messages)
    for key, quantity in billed.items():
        if quantity > ordered[key]:
            issues.append(f'Invoiced quantity exceeds the PO for {key[0]}.')
            for result in billed_lines[key]:
                result['messages'].append('Billed quantity exceeds the remaining ordered quantity.')
        if quantity > accepted[key]:
            shortage += (quantity-accepted[key]) * max(prices[key] or {ZERO})
            for result in billed_lines[key]:
                result['shortDelivery'] = True
    for key, quantity in accepted.items():
        if quantity > ordered.get(key, ZERO):
            issues.append(f'Accepted delivery exceeds the remaining PO quantity for {key[0]}.')
    if invoice_total > order.total_amount + tolerance:
        issues.append('Invoice totals exceed the PO amount.')
    if payments > net_due + tolerance:
        payment_issues.append('Cleared payments exceed the invoice total less deductions.')
    if net_due < ZERO:
        payment_issues.append('Deductions exceed the invoice total.')
    if order.status == 'cancelled':
        document_status = 'cancelled'
    elif issues:
        document_status = 'exception'
    elif not confirmed_receipts:
        document_status = 'awaiting_delivery'
    elif not invoices or any(row.invoice_status in {'draft', 'pending'} for row in invoices):
        document_status = 'awaiting_invoice'
    elif abs(invoice_total-order.total_amount) > tolerance or shortage > deductions + tolerance:
        document_status = 'partial'
    else:
        document_status = 'matched'

    if payment_issues:
        payment_status = 'exception'
    elif not invoices or any(row.invoice_status in {'draft', 'pending'} for row in invoices):
        payment_status = 'awaiting_invoice'
    elif abs(net_due-payments) <= tolerance:
        payment_status = 'settled'
    else:
        payment_status = 'partial' if payments > ZERO else 'awaiting_payment'

    status = document_status
    if payment_issues and status != 'cancelled':
        status = 'exception'
    elif status == 'matched' and payment_status != 'settled':
        status = payment_status
    values = {'status': status, 'invoice_total': invoice_total, 'deduction_total': deductions,
              'net_due': net_due, 'payment_total': payments, 'outstanding': max(ZERO, net_due-payments),
              'difference': net_due-payments, 'issues': issues + payment_issues,
              'documentStatus': document_status, 'paymentStatus': payment_status}
    if details:
        for result in line_results.values():
            if result.pop('shortDelivery', False):
                message = ('Applied deductions cover the delivery shortfall.'
                           if ZERO < shortage <= deductions + tolerance and deductions > ZERO
                           else 'Accepted delivery quantity is short.')
                result['messages'].append(message)
        values.update(lineReviews=line_results, documentIssues=issues, paymentIssues=payment_issues)
    return values


def refresh_case(case, mode):
    values = calculate(case.purchase_order, mode)
    values.pop('documentStatus')
    values.pop('paymentStatus')
    values['updated_at'] = timezone.now()
    for name, value in values.items():
        if name != 'issues':
            case._meta.get_field(name).clean(value, case)
    type(case).objects.filter(pk=case.pk).update(**values)
    for name, value in values.items():
        setattr(case, name, value)
    return case


@transaction.atomic
def synchronize(mode, order_ids):
    from accounts_receivable.services.catalog import model
    Reconciliation = apps.get_model(mode+'_recon', 'Reconciliation')
    for order in model(mode, 'purchase_order').objects.select_for_update().filter(pk__in=set(order_ids)-{None}).order_by('pk'):
        case, _ = Reconciliation.objects.get_or_create(purchase_order=order)
        case.refresh()


def document_changed(sender, instance, *, mode, target, deleted=False, **kwargs):
    from accounts_receivable.services.catalog import model
    if kwargs.get("raw"):
        return
    order_ids = set()
    if target == 'purchase_order':
        if not deleted:
            order_ids.add(instance.pk)
    elif target in {'delivery_receipt', 'sales_invoice', 'deduction'}:
        order_ids.update([instance.purchase_order_id, getattr(instance, '_previous_po_id', None)])
        if target == 'deduction':
            for invoice in model(mode, 'sales_invoice').objects.filter(pk__in={instance.invoice_id, getattr(instance, '_previous_invoice_id', None)}-{None}):
                invoice.refresh_payment_status()
    elif target == 'payment':
        order_ids.update(instance.invoice_allocations.values_list('invoice__purchase_order_id', flat=True))
    elif target == 'allocation':
        order_ids.add(instance.invoice.purchase_order_id)
    elif target == 'line_match':
        if instance.purchase_order_line_id:
            order_ids.add(instance.purchase_order_line.purchase_order_id)
    elif target == 'order_line':
        order_ids.add(instance.purchase_order_id)
    else:
        document = instance.invoice if target == 'invoice_line' else instance.delivery_receipt
        order_ids.add(document.purchase_order_id)
    synchronize(mode, order_ids)


def connect_signals(mode):
    from functools import partial
    from accounts_receivable.services.catalog import model
    targets = {'purchase_order': model(mode, 'purchase_order'), 'delivery_receipt': model(mode, 'delivery_receipt'),
               'sales_invoice': model(mode, 'sales_invoice'), 'payment': model(mode, 'payment'),
               'deduction': apps.get_model(mode+'_deduction', 'Deduction'), 'allocation': model(mode, 'PaymentAllocation'),
               'line_match': model(mode, 'DocumentMatch')}
    for target, name in [('order_line', 'purchase_order'), ('receipt_line', 'delivery_receipt'), ('invoice_line', 'sales_invoice')]:
        targets[target] = model(mode, model(mode, name).__name__+'Line')
    for target, sender in targets.items():
        for signal, deleted in ((post_save, False), (post_delete, True)):
            signal.connect(partial(document_changed, mode=mode, target=target, deleted=deleted), sender=sender,
                           weak=False, dispatch_uid=f'{mode}_po_reconciliation_{target}_{deleted}')
