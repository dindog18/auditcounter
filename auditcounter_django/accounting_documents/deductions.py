"""Deductions reduce an invoice's net due without changing its original total."""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Sum

from accounts_receivable.services.catalog import model, party_key

ZERO = Decimal('0')


def invoice_deductions(invoice):
    return invoice.deductions.filter(status='applied').aggregate(total=Sum('amount'))['total'] or ZERO


def lock_deduction(record, mode):
    key = party_key(mode)
    previous = type(record).objects.filter(pk=record.pk).first() if record.pk else None
    record._previous_invoice_id = previous.invoice_id if previous else None
    record._previous_po_id = previous.purchase_order_id if previous else None
    account_ids = {getattr(record, key+'_id'), getattr(previous, key+'_id', None)} - {None}
    list(model(mode, key).objects.select_for_update().filter(pk__in=account_ids).order_by('pk'))
    ids = {record.invoice_id, record._previous_invoice_id} - {None}
    list(model(mode, 'sales_invoice').objects.select_for_update().filter(pk__in=ids).order_by('pk'))


def validate_deduction(record, mode):
    key = party_key(mode)
    errors = {}
    order = record.purchase_order if record.purchase_order_id else None
    if order and (getattr(order, key+'_id') != getattr(record, key+'_id') or order.currency != record.currency):
        errors['purchase_order'] = 'The PO must have the same account and currency as this deduction.'
    invoice = record.invoice if record.invoice_id else None
    if invoice and (invoice.purchase_order_id != record.purchase_order_id or getattr(invoice, key+'_id') != getattr(record, key+'_id') or invoice.currency != record.currency):
        errors['invoice'] = 'Choose an invoice linked to this PO, account and currency.'
    if record.status == 'applied' and not invoice:
        errors['invoice'] = 'Select an invoice before applying a deduction.'
    if record.status == 'applied' and invoice and invoice.invoice_status in {'draft', 'pending', 'void'}:
        errors['invoice'] = 'Apply deductions only to posted or disputed invoices.'
    if invoice and record.amount is not None:
        others = invoice.deductions.filter(status='applied').exclude(pk=record.pk).aggregate(total=Sum('amount'))['total'] or ZERO
        amount = record.amount if record.status == 'applied' else ZERO
        allocations = sum((row.cash_amount + row.withholding_tax_amount + row.discount_amount
                           for row in invoice.payment_allocations.exclude(payment__payment_status='reversed')), ZERO)
        if others + amount + allocations > invoice.total_amount:
            errors['amount'] = 'Deductions and existing payment allocations exceed the invoice total.'
    if errors:
        raise ValidationError(errors)


def validate_payment_reactivation(payment):
    """A reversed payment cannot be restored over a subsequently reduced net due."""
    if not payment.pk or payment.payment_status == 'reversed':
        return
    amounts = {}
    invoices = {}
    for allocation in payment.invoice_allocations.select_related('invoice'):
        invoices[allocation.invoice_id] = allocation.invoice
        amounts[allocation.invoice_id] = amounts.get(allocation.invoice_id, ZERO) + allocation.cash_amount + allocation.withholding_tax_amount + allocation.discount_amount
    for invoice_id, invoice in invoices.items():
        others = sum((allocation.cash_amount + allocation.withholding_tax_amount + allocation.discount_amount
                      for allocation in invoice.payment_allocations.exclude(payment_id=payment.pk)
                      .exclude(payment__payment_status='reversed')), ZERO)
        if others + amounts[invoice_id] > invoice.net_amount:
            raise ValidationError({'payment_status': 'Existing allocations exceed an invoice’s net due. Adjust them before restoring this payment.'})
