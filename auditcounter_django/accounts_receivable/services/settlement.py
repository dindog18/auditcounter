"""Read-only settlement evaluation, separate from physical document matching."""
from decimal import Decimal
from django.urls import reverse
from discrepancies.evaluation import json_value, finding, source_evidence
from .catalog import party_key

ZERO=Decimal('0')


def evaluate_invoice(invoice):
    mode='ap' if invoice._meta.app_label=='accounts_payable' else 'ar'
    party=party_key(mode)+'_id'
    namespace='ACCOUNTS_PAYABLE' if mode=='ap' else 'ACCOUNTS_RECEIVABLE'
    cash=withholding=discount=credit_total=ZERO
    reasons=[]; payments=[]; credits=[]; reserved=ZERO
    reliable=bool(invoice.currency and getattr(invoice,party) and invoice.invoice_reference_no and invoice.total_amount is not None and invoice.total_amount.is_finite() and invoice.total_amount>=0)
    if not reliable:reasons.append('Invoice identity, currency or recorded total is incomplete.')
    for allocation in invoice.payment_allocations.select_related('payment').order_by('pk'):
        payment=allocation.payment
        values=(allocation.cash_amount,allocation.withholding_tax_amount,allocation.discount_amount)
        valid=payment.currency==invoice.currency and getattr(payment,party)==getattr(invoice,party) and all(v.is_finite() and v>=0 for v in values)
        if not valid:reasons.append(f'Payment {payment.payment_reference_no} has inconsistent account, currency or amounts; review the allocation.')
        if valid and payment.payment_status!='reversed':reserved+=sum(values,ZERO)
        if valid and payment.payment_status=='cleared':
            cash+=values[0];withholding+=values[1];discount+=values[2]
        payments.append(dict(id=payment.pk,reference=payment.payment_reference_no,status=payment.payment_status,cash=str(values[0]),withholding=str(values[1]),discount=str(values[2]),
            included=valid and payment.payment_status=='cleared',url=reverse(namespace+':payment_detail',args=[payment.pk])))
    if mode=='ap':
        for application in invoice.credit_applications.select_related('credit','reversal').order_by('pk'):
            credit=application.credit
            active=not hasattr(application,'reversal') and credit.status=='verified'
            valid=credit.supplier_id==invoice.supplier_id and credit.currency==invoice.currency and application.amount>0
            if active and not valid:reasons.append(f'Credit {credit.reference} requires account/currency/amount review.')
            if active and valid:credit_total+=application.amount
            credits.append(dict(id=credit.pk,application_id=application.pk,reference=credit.reference,amount=str(application.amount),included=active and valid,
                reversed=hasattr(application,'reversal'),url=reverse(namespace+':credit_detail',args=[credit.pk])))
    adjustments=ZERO
    deductions=[]
    if mode=='ar':
        from .deductions import applied_amount,serialize
        adjustments=applied_amount(invoice)
        deductions=[serialize(row) for row in invoice.deductions.select_related('invoice').order_by('pk')]
    settled=cash+withholding+discount+credit_total+adjustments
    balance=invoice.total_amount-settled if reliable else None
    if reliable and (balance<0 or reserved+credit_total+adjustments>invoice.total_amount):reasons.append('Active payment reservations and credits exceed the recorded invoice total.')
    status='needs_review' if reasons else 'settled' if balance==0 else 'partial' if settled else 'outstanding'
    pending=reserved-(cash+withholding+discount)
    return dict(invoice_id=invoice.pk,reference=invoice.invoice_reference_no,currency=invoice.currency,invoice_total=str(invoice.total_amount) if reliable else None,
        cash=str(cash),withholding=str(withholding),discount=str(discount),credits=str(credit_total),adjustments=str(adjustments),deductions=deductions,settled_amount=str(settled),
        outstanding_balance=str(balance) if balance is not None else None,pending_payment_reservations=str(pending),status=status,reasons=reasons,
        payments=payments,credit_applications=credits,url=reverse(namespace+':invoice_detail',args=[invoice.pk]))


def settlement_evidence(invoice, result=None):
    evidence=source_evidence(invoice)
    evidence['field_name']='settlement'
    evidence['observed_value']={'invoice':evidence['observed_value'],'settlement':result or evaluate_invoice(invoice)}
    return evidence


def evaluate_case(case):
    invoices=[]; findings=[]
    for invoice in case.sales_invoices.order_by('pk'):
        result=evaluate_invoice(invoice);invoices.append(result)
        if result['status']=='needs_review':
            findings.append(finding('SETTLEMENT_MISMATCH',{'invoice_id':invoice.pk},' '.join(result['reasons']),
                {'invoice_total':result['invoice_total'],'currency':invoice.currency},
                {'settled_amount':result['settled_amount'],'pending':result['pending_payment_reservations']},
                [settlement_evidence(invoice,result)],currency=invoice.currency,
                details={'settlement':result,'financial_classification':'validation_issue_not_confirmed_loss'}))
    unapplied=[]
    if case._meta.app_label=='accounts_payable' and case.supplier_id:
        from accounts_payable.models import SupplierCreditNote
        from accounts_payable.services.credits import available_credit
        for credit in SupplierCreditNote.objects.filter(supplier_id=case.supplier_id,currency=case.currency,status='verified').order_by('pk')[:200]:
            available=available_credit(credit)
            if available>0:unapplied.append(dict(id=credit.pk,reference=credit.reference,currency=credit.currency,amount=str(available),url=reverse('ACCOUNTS_PAYABLE:credit_detail',args=[credit.pk])))
    return dict(invoices=invoices,unapplied_credits=unapplied,findings=findings)
