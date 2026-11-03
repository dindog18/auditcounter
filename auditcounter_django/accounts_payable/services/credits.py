"""Verified supplier credits, account-first locking, and explicit reversal history."""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone

from accounts_receivable.services.catalog import revision, check_revision
from accounts_receivable.services.financial import amount, body, date_value, text
from ..models import Supplier, SupplierSalesInvoice, SupplierCreditNote, SupplierCreditApplication, SupplierCreditReversal

ZERO = Decimal('0')


def applied_credit(invoice):
    return invoice.credit_applications.filter(reversal__isnull=True, credit__status='verified').aggregate(total=Sum('amount'))['total'] or ZERO


def available_credit(credit):
    return credit.credit_amount - (credit.applications.filter(reversal__isnull=True).aggregate(total=Sum('amount'))['total'] or ZERO)


def credit_revision(credit):
    return revision(credit, list(credit.applications.order_by('pk').values('id','invoice_id','amount','reversal__id')))


def reserved_payments(invoice):
    return sum((row.cash_amount+row.withholding_tax_amount+row.discount_amount for row in invoice.payment_allocations.exclude(payment__payment_status='reversed')), ZERO)


def validate_application(application):
    credit, invoice = application.credit, application.invoice
    if credit.status!='verified' or invoice.invoice_status not in ('posted','disputed'):
        raise ValidationError('Only verified credits and posted or disputed invoices can be applied.')
    if credit.supplier_id!=invoice.supplier_id or credit.currency!=invoice.currency:
        raise ValidationError('Credit and invoice supplier and currency must agree.')
    if application.amount>available_credit(credit):
        raise ValidationError('The application exceeds the remaining verified credit.')
    if reserved_payments(invoice)+applied_credit(invoice)+application.amount>invoice.total_amount:
        raise ValidationError('Payment reservations and credits would exceed the invoice total.')


@transaction.atomic
def create_credit(data):
    body(data, ('supplier_id','reference','issue_date','currency','credit_amount','source_document_id'))
    supplier = get_object_or_404(Supplier.objects.select_for_update(), pk=data.get('supplier_id'))
    record = SupplierCreditNote(supplier=supplier, reference=text(data.get('reference'),'credit reference',100),
        issue_date=date_value(data.get('issue_date')), currency=data.get('currency'),
        credit_amount=amount(data.get('credit_amount')), source_document_id=data.get('source_document_id'))
    record.save()
    return record


@transaction.atomic
def verify_credit(record_id, data):
    body(data, ('revision','notes'))
    credit = get_object_or_404(SupplierCreditNote, pk=record_id)
    Supplier.objects.select_for_update().get(pk=credit.supplier_id)
    credit = SupplierCreditNote.objects.select_for_update().get(pk=record_id)
    check_revision(credit, data.get('revision'), list(credit.applications.order_by('pk').values('id','invoice_id','amount','reversal__id')))
    if credit.status!='draft':
        raise ValidationError('Only a draft credit can be verified.')
    credit.status='verified'
    credit.verified_at=timezone.now()
    credit.verification_notes=text(data.get('notes'),'verification notes')
    credit.save()
    return credit


@transaction.atomic
def apply_credit(record_id, data):
    body(data, ('revision','invoice_id','amount','request_key','application_date','notes'))
    credit = get_object_or_404(SupplierCreditNote, pk=record_id)
    Supplier.objects.select_for_update().get(pk=credit.supplier_id)
    credit = SupplierCreditNote.objects.select_for_update().get(pk=record_id)
    value = amount(data.get('amount'))
    key = text(data.get('request_key'),'request key',100)
    notes = text(data.get('notes'),'application explanation')
    applied_date = date_value(data.get('application_date'))
    old = credit.applications.filter(request_key=key).first()
    if old:
        if (old.invoice_id,old.amount,old.notes,old.application_date)!=(data.get('invoice_id'),value,notes,applied_date):
            raise ValidationError('The request key was reused for a different application.', code='conflict')
        return old
    if data.get('revision')!=credit_revision(credit):
        raise ValidationError('Credit applications changed. Reload before applying.', code='conflict')
    invoice = get_object_or_404(SupplierSalesInvoice.objects.select_for_update(), pk=data.get('invoice_id'), supplier_id=credit.supplier_id)
    application = SupplierCreditApplication(credit=credit,invoice=invoice,amount=value,request_key=key,application_date=applied_date,notes=notes)
    application.save()
    return application


@transaction.atomic
def reverse_application(record_id, data):
    body(data, ('revision','reason'))
    application = get_object_or_404(SupplierCreditApplication.objects.select_related('credit','invoice'), pk=record_id)
    Supplier.objects.select_for_update().get(pk=application.credit.supplier_id)
    credit = SupplierCreditNote.objects.select_for_update().get(pk=application.credit_id)
    reason = text(data.get('reason'),'reversal reason')
    old = SupplierCreditReversal.objects.filter(application=application).first()
    if old:
        if old.reason!=reason:
            raise ValidationError('This application already has a different reversal.',code='conflict')
        return old
    if data.get('revision')!=credit_revision(credit):
        raise ValidationError('Credit changed. Reload before reversing.',code='conflict')
    reversal = SupplierCreditReversal(application=application,reason=reason)
    reversal.save()
    from discrepancies.services.claims import flag_reversed_application
    flag_reversed_application(application)
    return reversal


def serialize_credit(credit):
    from django.urls import reverse
    return dict(id=credit.pk,supplier_id=credit.supplier_id,reference=credit.reference,issue_date=credit.issue_date.isoformat(),currency=credit.currency,
        credit_amount=str(credit.credit_amount),available_amount=str(available_credit(credit)),status=credit.status,verification_notes=credit.verification_notes,
        verified_at=credit.verified_at.isoformat() if credit.verified_at else None,revision=credit_revision(credit),
        source_document_id=credit.source_document_id,document_url=reverse('DOC_EXTRACTION:document_detail',args=[credit.source_document_id]) if credit.source_document_id else None,
        applications=[dict(id=a.pk,invoice_id=a.invoice_id,invoice_reference=a.invoice.invoice_reference_no,amount=str(a.amount),date=a.application_date.isoformat(),notes=a.notes,
            reversed=hasattr(a,'reversal'),reversal_reason=a.reversal.reason if hasattr(a,'reversal') else '') for a in credit.applications.select_related('invoice','reversal').order_by('pk')])
