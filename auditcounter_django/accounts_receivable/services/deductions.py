"""Human-reviewed AR disputes, separate from cash, withholding and discounts."""
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.urls import reverse
from .catalog import revision, check_revision
from .financial import body, text, amount
from ..models import Customer, CompanySalesInvoice, CustomerPayment, CustomerDeduction, DeductionApplication, DeductionReversal, DeductionObservation

ZERO = Decimal('0')


def applied_amount(invoice):
    return DeductionApplication.objects.filter(deduction__invoice=invoice, deduction__status='accepted', reversal__isnull=True).aggregate(total=Sum('amount'))['total'] or ZERO


def used_amount(deduction):
    return deduction.applications.filter(reversal__isnull=True).aggregate(total=Sum('amount'))['total'] or ZERO


def deduction_revision(deduction):
    return revision(deduction, list(deduction.applications.order_by('pk').values('id','amount','reversal__id')))


def lock(record_id, token):
    record = get_object_or_404(CustomerDeduction, pk=record_id)
    Customer.objects.select_for_update().get(pk=record.customer_id)
    record = CustomerDeduction.objects.select_for_update().select_related('invoice').get(pk=record_id)
    if token != deduction_revision(record):
        raise ValidationError('Deduction changed. Reload before reviewing or applying.', code='conflict')
    return record


def snapshot(record):
    return dict(reference=record.reference, invoice_id=record.invoice_id, payment_id=record.payment_id, source_document_id=record.source_document_id,
        reason_code=record.reason_code, claimed_amount=str(record.claimed_amount), accepted_amount=str(record.accepted_amount), currency=record.currency,
        status=record.status, notes=record.resolution_notes, applications=[dict(id=a.pk, amount=str(a.amount), notes=a.notes,
        reversed=hasattr(a,'reversal'), reversal_reason=a.reversal.reason if hasattr(a,'reversal') else '') for a in record.applications.select_related('reversal').order_by('pk')])


def observe(record):
    state = snapshot(record)
    previous = record.observations.order_by('-pk').first()
    if not previous or previous.state != state:
        DeductionObservation.objects.create(deduction=record, state=state)
    record.invoice.refresh_payment_status()


@transaction.atomic
def create_deduction(data):
    body(data, ('invoice_id','payment_id','reference','reason_code','claimed_amount','source_document_id','revision'))
    invoice = get_object_or_404(CompanySalesInvoice, pk=data.get('invoice_id'))
    Customer.objects.select_for_update().get(pk=invoice.customer_id)
    invoice = CompanySalesInvoice.objects.select_for_update().get(pk=invoice.pk)
    check_revision(invoice, data.get('revision'))
    if invoice.invoice_status not in ('posted','disputed'):
        raise ValidationError('Record deductions against posted or disputed invoices.')
    value = amount(data.get('claimed_amount'))
    # Multiple disputes cannot reserve the same collectible balance.
    pending = invoice.deductions.exclude(status='rejected').aggregate(total=Sum('claimed_amount'))['total'] or ZERO
    if value + pending > invoice.outstanding_balance + applied_amount(invoice):
        raise ValidationError('Claimed deductions exceed the remaining collectible balance.')
    payment = None
    if data.get('payment_id'):
        payment = get_object_or_404(CustomerPayment, pk=data['payment_id'], customer_id=invoice.customer_id, currency=invoice.currency)
        if not payment.invoice_allocations.filter(invoice=invoice).exists():
            raise ValidationError('The referenced payment must have an allocation on this invoice.')
    record = CustomerDeduction(customer=invoice.customer, invoice=invoice, payment=payment, reference=text(data.get('reference'),'deduction reference',100),
        reason_code=data.get('reason_code'), claimed_amount=value, currency=invoice.currency, source_document_id=data.get('source_document_id'))
    record.save(); observe(record)
    return record


@transaction.atomic
def review(record_id, data):
    body(data, ('revision','decision','accepted_amount','notes'))
    record = lock(record_id, data.get('revision'))
    if data.get('decision') not in ('pending','accepted','rejected'):
        raise ValidationError('Choose pending, accepted or rejected.')
    if used_amount(record):
        raise ValidationError('Reverse active applications before reassessing the deduction.')
    record.status = data['decision']
    record.accepted_amount = amount(data.get('accepted_amount')) if record.status=='accepted' else ZERO
    record.resolution_notes = text(data.get('notes'),'review explanation')
    record.save(); observe(record)
    return record


def validate_application(application):
    deduction = application.deduction
    invoice = CompanySalesInvoice.objects.select_for_update().get(pk=deduction.invoice_id)
    if deduction.status != 'accepted' or invoice.invoice_status not in ('posted','disputed') or deduction.customer_id != invoice.customer_id or deduction.currency != invoice.currency:
        raise ValidationError('Only accepted deductions with valid invoice identity may be applied.')
    if used_amount(deduction) + application.amount > deduction.accepted_amount:
        raise ValidationError('Application exceeds the accepted deduction.')
    reserved = sum((p.cash_amount+p.withholding_tax_amount+p.discount_amount for p in invoice.payment_allocations.exclude(payment__payment_status='reversed')), ZERO)
    if reserved + applied_amount(invoice) + application.amount > invoice.total_amount:
        raise ValidationError('Payment reservations and deductions exceed the invoice balance.')


@transaction.atomic
def apply(record_id, data):
    body(data, ('revision','amount','request_key','notes'))
    # Account lock serializes the retry lookup with the original application.
    record = get_object_or_404(CustomerDeduction, pk=record_id)
    Customer.objects.select_for_update().get(pk=record.customer_id)
    value = amount(data.get('amount')); key = text(data.get('request_key'),'request key',100); notes = text(data.get('notes'),'application explanation')
    old = record.applications.filter(request_key=key).first()
    if old:
        if (old.amount,old.notes)!=(value,notes):
            raise ValidationError('Request key already used with different values.', code='conflict')
        return record
    record = lock(record_id, data.get('revision'))
    DeductionApplication.objects.create(deduction=record, amount=value, request_key=key, notes=notes)
    observe(record)
    return record


@transaction.atomic
def reverse_application(record_id, data):
    body(data, ('revision','application_id','reason'))
    record = lock(record_id, data.get('revision'))
    application = get_object_or_404(DeductionApplication, pk=data.get('application_id'), deduction=record)
    reason = text(data.get('reason'),'reversal reason')
    old = DeductionReversal.objects.filter(application=application).first()
    if old:
        if old.reason != reason: raise ValidationError('Application already reversed with another reason.')
    else:
        DeductionReversal.objects.create(application=application, reason=reason)
        observe(record)
    return record


def serialize(record):
    return dict(id=record.pk, **snapshot(record), customer_id=record.customer_id, revision=deduction_revision(record),
        applied_amount=format(used_amount(record),'.2f'), outstanding_balance=format(record.invoice.outstanding_balance,'.2f'),
        document_url=reverse('DOC_EXTRACTION:document_detail', args=[record.source_document_id]),
        invoice_url=reverse('ACCOUNTS_RECEIVABLE:invoice_detail', args=[record.invoice_id]),
        history=list(record.observations.order_by('-pk').values('created_at','state')[:50]))


def case_findings(case):
    if case._meta.app_label != 'accounts_receivable': return []
    from discrepancies.evaluation import finding, source_evidence
    results=[]
    for deduction in CustomerDeduction.objects.filter(invoice__in=case.sales_invoices.all()).select_related('invoice'):
        if deduction.status=='rejected' or deduction.status=='accepted' and used_amount(deduction)==deduction.accepted_amount:
            continue
        evidence=deduction_evidence(deduction)
        results.append(finding('CUSTOMER_DEDUCTION', {'deduction_id':deduction.pk},
            f'Customer deduction {deduction.reference} requires review or verified application; it is not cash received.',
            {'review':'documented decision and application'}, {'status':deduction.status,'applied_amount':str(used_amount(deduction))}, [evidence], currency=deduction.currency))
    return results


def deduction_evidence(deduction):
    from discrepancies.evaluation import source_evidence
    evidence=source_evidence(deduction.invoice)
    evidence.update(evidence_type='DEDUCTION', field_name='deduction', observed_value=snapshot(deduction), source_model=deduction._meta.label,
        source_record_id=str(deduction.pk), source_document_id=deduction.source_document_id)
    return evidence
