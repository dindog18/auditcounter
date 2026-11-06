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
    # Exact source values only. Formatting variants require explicit review.
    return (line.item_code, line.unit_of_measure)


def receipt_status(receipt):
    return getattr(receipt, 'receipt_status', getattr(receipt, 'delivery_status', ''))


def receipt_accepts_lines(receipt):
    return receipt_status(receipt) in {'accepted', 'delivered', 'partial', 'partially_accepted'}


def calculate(order, mode, *, details=False, reference_reviews=None, delivery_reviews=None):
    from accounts_receivable.services.catalog import party_key
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
    from .amounts import line_amount_issues
    from .delivery_review import can_confirm, evidence
    from .line_review import scoped_matches, model_variance, validate_identity
    from .references import document_references, same_reference, unlinked_candidates

    if reference_reviews is None or delivery_reviews is None:
        case = getattr(order, 'automatic_reconciliation', None)
        if reference_reviews is None:
            reference_reviews = case.reference_reviews if case else {}
        if delivery_reviews is None:
            delivery_reviews = case.delivery_reviews if case else {}
    references = document_references(order, receipts, invoices, reference_reviews)
    issues = [
        f'{row["reference"]}: reported PO “{row["reported"]}” differs from “{row["expected"]}”. '
        + ('Review the formatting difference.' if row['canReview'] else 'Check the selected PO link.')
        for row in references if row['status'] in {'format', 'conflict'}
    ]
    account = party_key(mode) + '_id'
    if not getattr(order, account):
        issues.append('The PO is missing its account.')
    for row in [*receipts, *invoices, *applied]:
        if getattr(row, account) != getattr(order, account) or getattr(row, 'currency', order.currency) != order.currency:
            issues.append(f'{row}: linked document has a different account or currency.')
    payment_issues = []
    invoice_ids = {row.pk for row in invoices}
    if any(row.invoice_id not in invoice_ids for row in applied):
        payment_issues.append('An applied deduction refers to an invoice outside the active case.')
    reviews = defaultdict(list)
    for match in scoped_matches(mode, order):
        reviews[match.invoice_line_id].append(match)
    line_results = {}
    billed_lines = defaultdict(list)
    order_lines = list(order.lines.all())
    order_lines_by_id = {line.pk: line for line in order_lines}
    delivery_keys = {}
    delivery_checks = defaultdict(list)
    ordered, accepted, billed, reviewed = (defaultdict(lambda: ZERO) for _ in range(4))
    terms = defaultdict(set)
    for line in order_lines:
        key = _line_key(line)
        ordered[key] += line.quantity_ordered
        issues.extend(f'PO: {message}' for message in line_amount_issues(line, 'quantity_ordered', tolerance))
        if line.quantity_ordered > ZERO:
            terms[key].add((line.unit_price, line.discount_amount / line.quantity_ordered,
                            line.tax_amount / line.quantity_ordered))
    missing_lines = []
    receipt_observations = []
    pending_receipts = len(receipts) > len(confirmed_receipts)
    if not order_lines:
        missing_lines.append('The purchase order has no line items.')
    for receipt in confirmed_receipts:
        lines = list(receipt.lines.all())
        if not lines:
            missing_lines.append(f'{receipt.dr_reference_no or "Delivery receipt"} has no line items.')
        if not receipt.dr_reference_no or not receipt.delivery_date:
            issues.append('A linked delivery receipt is missing its reference or date.')
        for line in lines:
            if line.quantity_stated and line.quantity_stated != line.quantity_received:
                receipt_observations.append(
                    f'{receipt.dr_reference_no}, line {line.line_no}: stated {line.quantity_stated}, received {line.quantity_received}.'
                )
            if line.quantity_rejected > ZERO:
                receipt_observations.append(f'{receipt.dr_reference_no}, line {line.line_no}: {line.quantity_rejected} rejected.')
            if line.quantity_accepted + line.quantity_rejected != line.quantity_received:
                issues.append(f'{receipt.dr_reference_no}, line {line.line_no}: received quantity is not fully accounted for as accepted or rejected.')
            if receipt_accepts_lines(receipt):
                source_key = _line_key(line)
                saved_review = delivery_reviews.get(str(line.pk), {})
                target = order_lines_by_id.get(saved_review.get('orderLineId'))
                same_account = getattr(receipt, account) == getattr(order, account)
                confirmed = (order.status != 'cancelled' and same_account and target
                             and can_confirm(target, line) and saved_review.get('evidence') == evidence(target, line))
                key = _line_key(target) if confirmed else source_key
                delivery_keys[line.pk] = key
                accepted[key] += line.quantity_accepted
                if details and order.status != 'cancelled' and same_account and line.quantity_accepted > ZERO:
                    candidates = [] if confirmed or source_key in ordered else [
                        {'id': item.pk, 'number': item.line_no, 'model': item.item_code, 'unit': item.unit_of_measure,
                         'quantity': item.quantity_ordered}
                        for item in order_lines if can_confirm(item, line)
                    ]
                    if confirmed or candidates:
                        delivery_checks[key].append({
                            'receiptLineId': line.pk, 'receiptId': receipt.pk, 'reference': receipt.dr_reference_no,
                            'lineNumber': line.line_no, 'model': line.item_code, 'unit': line.unit_of_measure,
                            'quantity': line.quantity_accepted, 'candidates': candidates,
                            'review': saved_review if confirmed else None,
                        })

    for invoice in invoices:
        lines = list(invoice.lines.all())
        if not lines:
            missing_lines.append(f'{invoice.invoice_reference_no or "Invoice"} has no line items.')
        if invoice.invoice_status == 'disputed':
            issues.append(f'{invoice.invoice_reference_no or "Invoice"} is disputed.')
        if not invoice.invoice_reference_no or not invoice.invoice_date:
            issues.append('A linked invoice is missing its reference or date.')
        try:
            validate_totals('sales_invoice', invoice, lines)
        except ValidationError as error:
            issues.extend(f'{invoice.invoice_reference_no}: {message}' for message in error.messages)
        for line in lines:
            key = _line_key(line)
            result = {'messages': line_amount_issues(line, 'quantity_invoiced', tolerance),
                      'reviewedQuantity': ZERO, 'matches': [], 'reviewedDifferences': []}
            line_results[line.pk] = result
            for match in reviews[line.pk]:
                result['matches'].append({
                    'orderLineId': match.purchase_order_line_id,
                    'receiptLineId': match.delivery_receipt_line_id,
                    'quantity': match.matched_quantity, 'note': match.notes,
                })
                try:
                    if match.match_status != 'matched' or not match.delivery_receipt_line_id:
                        raise ValidationError('Review this saved line match.')
                    receipt = match.delivery_receipt_line.delivery_receipt
                    if receipt.purchase_order_id != order.pk or not receipt_accepts_lines(receipt):
                        raise ValidationError('The selected delivery line no longer supplies accepted quantity for this PO.')
                    validate_identity(line, match.purchase_order_line, match.delivery_receipt_line)
                    match.clean()
                except ValidationError as error:
                    result['messages'].extend(error.messages)
                    continue
                quantity = match.matched_quantity
                order_key = _line_key(match.purchase_order_line)
                result['reviewedQuantity'] += quantity
                ordered[order_key] -= quantity
                accepted[delivery_keys[match.delivery_receipt_line_id]] -= quantity
                reviewed[order_key] += quantity
                variance = model_variance(line, match.purchase_order_line, match.delivery_receipt_line)
                if variance:
                    result['reviewedDifferences'].append({'evidence': variance, 'note': match.notes})
            remaining = line.quantity_invoiced - result['reviewedQuantity']
            if remaining > ZERO:
                billed[key] += remaining
                billed_lines[key].append((invoice, line, result))
                if not all(value.strip() for value in key):
                    result['messages'].append('Model and unit are needed for automatic matching. Review this line manually.')
                elif key not in ordered:
                    variants = [candidate for candidate, unit in ordered if same_reference(candidate, key[0])]
                    result['messages'].append(
                        f'Model or unit differs from the PO. Possible PO model: {", ".join(dict.fromkeys(variants))}.'
                        if variants else f'Model {key[0]} is not on the PO.')
                elif len(terms[key]) > 1:
                    result['messages'].append('More than one set of price, discount or tax terms is possible. Select the PO line.')
                elif terms[key]:
                    price, discount, tax = next(iter(terms[key]))
                    actual = (line.unit_price, line.discount_amount / line.quantity_invoiced,
                              line.tax_amount / line.quantity_invoiced)
                    for label, expected, value in zip(('unit price', 'discount', 'tax'), (price, discount, tax), actual):
                        if abs(expected - value) * remaining > tolerance:
                            result['messages'].append(f'Invoiced {label} differs from the PO.')
            issues.extend(f'{invoice.invoice_reference_no}, line {line.line_no} — {message}'
                          for message in result['messages'])
    try:
        validate_totals('purchase_order', order, order_lines)
    except ValidationError as error:
        issues.extend(error.messages)

    deductions_by_invoice = defaultdict(lambda: ZERO)
    for row in applied:
        deductions_by_invoice[row.invoice_id] += row.amount
    shortages = defaultdict(lambda: ZERO)
    unassigned_shortage = False
    open_quantities = False
    quantity_checks = []
    for key in sorted(ordered.keys() | accepted.keys() | billed.keys()):
        expected, delivered, invoiced = ordered[key], accepted[key], billed[key]
        manual = reviewed[key]
        if expected == delivered == invoiced == manual == ZERO:
            continue
        label = key[0] or 'Missing model'
        messages = []
        if invoiced > expected:
            messages.append('Invoiced quantity exceeds the PO.')
            issues.append(f'{label}: {messages[-1]}')
        if delivered > expected:
            messages.append('Accepted delivery exceeds the PO or uses a different model or unit.')
            # A formatting difference is explicit even if a likely model is found.
            variants = [candidate for candidate, unit in terms if same_reference(candidate, key[0]) and (candidate, unit) != key]
            if variants:
                messages.append(f'Possible PO model: {", ".join(dict.fromkeys(variants))}. Review the line manually.')
            issues.append(f'{label}: {messages[-2] if variants else messages[-1]}')
        has_difference = invoiced > expected or delivered > expected or delivered < invoiced
        if invoiced < expected:
            open_quantities = True
            messages.append('Ordered quantity remains to be invoiced.')
        if delivered < invoiced:
            messages.append('Accepted quantity is lower than invoiced quantity.')
            candidates = billed_lines[key]
            invoice_ids = {invoice.pk for invoice, _, _ in candidates}
            # Use the invoiced amount per unit, including line discounts and tax.
            price = max((line.line_total / line.quantity_invoiced for _, line, _ in candidates), default=ZERO)
            if len(invoice_ids) != 1 or price <= ZERO:
                unassigned_shortage = True
            else:
                shortages[next(iter(invoice_ids))] += (invoiced - delivered) * price
            for _, _, result in candidates:
                result['messages'].append(messages[-1])
        if details:
            quantity_checks.append({'model': key[0], 'unit': key[1], 'ordered': expected + manual,
                                    'accepted': delivered + manual, 'invoiced': invoiced + manual,
                                    'reviewed': manual, 'messages': messages, 'hasDifference': has_difference,
                                    'deliveryChecks': delivery_checks[key]})
    shortage_covered = bool(shortages) and not unassigned_shortage and all(
        amount <= deductions_by_invoice[invoice_id] + tolerance and deductions_by_invoice[invoice_id] > ZERO
        for invoice_id, amount in shortages.items()
    )
    shortage_open = unassigned_shortage or bool(shortages) and not shortage_covered
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
    elif (missing_lines or pending_receipts or open_quantities or shortage_open
          or abs(invoice_total-order.total_amount) > tolerance):
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
        pending_checks = []
        if not confirmed_receipts:
            pending_checks.append('No completed delivery receipt is linked.')
        elif pending_receipts:
            pending_checks.append('One or more linked delivery receipts still need a delivery decision.')
        if not invoices:
            pending_checks.append('No active invoice is linked.')
        elif any(row.invoice_status in {'draft', 'pending'} for row in invoices):
            pending_checks.append('One or more linked invoices still need to be posted.')
        if invoices and invoice_total < order.total_amount - tolerance:
            pending_checks.append(f'Invoice totals are below the PO amount by {order.total_amount-invoice_total:.2f} {order.currency}.')
        values.update(pendingChecks=pending_checks, receiptObservations=receipt_observations, lineReviews=line_results, documentIssues=issues, paymentIssues=payment_issues,
                      referenceChecks=references, unlinkedCandidates=list(unlinked_candidates(order, mode)), quantityChecks=quantity_checks, missingLines=missing_lines,
                      deductionCoversShortage=shortage_covered)
    return values


def refresh_case(case, mode):
    values = calculate(case.purchase_order, mode, reference_reviews=case.reference_reviews,
                       delivery_reviews=case.delivery_reviews)
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
