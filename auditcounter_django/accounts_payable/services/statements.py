"""Structured statement evidence; exact matching never manufactures ledger entries."""
import csv
import io
from decimal import Decimal,InvalidOperation
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from accounts_receivable.services.catalog import revision,check_revision
from accounts_receivable.services.financial import body,text,amount,date_value
from ..models import Supplier,SupplierStatement,SupplierStatementLine,SupplierStatementMatch,SupplierStatementEvaluation,SupplierSalesInvoice,CompanyPayment,SupplierCreditNote,Transaction

TARGETS={'invoice':(SupplierSalesInvoice,'invoice_reference_no','invoice_date'),'payment':(CompanyPayment,'payment_reference_no','payment_date'),'credit':(SupplierCreditNote,'reference','issue_date')}


def balance(value):
    try:
        if isinstance(value,(bool,float)):raise ValueError
        result=Decimal(value)
        if not result.is_finite() or abs(result)>=Decimal('10000000000000') or result!=result.quantize(Decimal('.01')):raise ValueError
        return result.quantize(Decimal('.01'))
    except (TypeError,ValueError,InvalidOperation):raise ValidationError('Statement balances must be decimal amounts with at most two fractional digits.') from None


@transaction.atomic
def create_statement(data):
    body(data,('supplier_id','reference','statement_date','period_start','currency','opening_balance','closing_balance','source_document_id','case_id','csv'))
    supplier=get_object_or_404(Supplier.objects.select_for_update(),pk=data.get('supplier_id'))
    statement=SupplierStatement(supplier=supplier,reference=text(data.get('reference'),'statement reference',100),statement_date=date_value(data.get('statement_date')),
        period_start=date_value(data.get('period_start')),currency=data.get('currency'),opening_balance=balance(data.get('opening_balance')),closing_balance=balance(data.get('closing_balance')),source_document_id=data.get('source_document_id'))
    if statement.period_start>statement.statement_date:raise ValidationError('The statement period begins after its closing date.')
    if data.get('case_id'):
        statement.ap_transaction=get_object_or_404(Transaction,pk=data['case_id'],supplier=supplier,currency=statement.currency)
    source=text(data.get('csv'),'CSV data',1000000)
    reader=csv.DictReader(io.StringIO(source))
    if set(reader.fieldnames or [])!={'reference','date','type','amount'}:raise ValidationError('CSV columns must be reference,date,type,amount.')
    statement.full_clean();statement.save()
    count=0
    for index,row in enumerate(reader,1):
        if index>500 or None in row:raise ValidationError('Use at most 500 well-formed statement lines.')
        line=SupplierStatementLine(statement=statement,line_no=index,reference=text(row.get('reference'),'line reference',100),transaction_date=date_value(row.get('date')),kind=row.get('type'),amount=amount(row.get('amount')))
        if not statement.period_start<=line.transaction_date<=statement.statement_date:raise ValidationError('Statement line dates must be within its period.')
        line.full_clean();line.save();count+=1
    if not count:raise ValidationError('Include at least one statement line.')
    reconcile(statement.pk,{'revision':revision(statement)})
    statement.refresh_from_db();return statement


def target_amount(row,kind):
    return row.total_amount if kind=='invoice' else row.amount_paid+row.withholding_tax_amount+row.discount_taken if kind=='payment' else row.credit_amount


def target_valid(row,kind,statement):
    state=row.invoice_status if kind=='invoice' else row.payment_status if kind=='payment' else row.status
    business_date=getattr(row,TARGETS[kind][2])
    return bool(business_date and business_date<=statement.statement_date) and row.supplier_id==statement.supplier_id and row.currency==statement.currency and state in (('posted','disputed') if kind=='invoice' else ('cleared',) if kind=='payment' else ('verified',))


def evaluate(statement):
    results=[];running=statement.opening_balance;used=set()
    for line in statement.lines.order_by('line_no'):
        running+=line.amount if line.kind=='invoice' else -line.amount
        Model,ref,date_field=TARGETS[line.kind]
        candidates=list(Model.objects.filter(supplier_id=statement.supplier_id,currency=statement.currency,**{ref+'__iexact':line.reference,date_field+'__lte':statement.statement_date}).order_by('pk')[:20])
        active=line.matches.filter(active=True).first()
        chosen=getattr(active,line.kind) if active else candidates[0] if len(candidates)==1 else None
        status='unmatched';code='MISSING_STATEMENT_'+line.kind.upper();reason='No corresponding local ledger record was found.'
        if len(candidates)>1 and not active:status='needs_review';code='AMBIGUOUS_STATEMENT_MATCH';reason='Several records have this reference; select supporting evidence explicitly.'
        if chosen:
            key=(line.kind,chosen.pk)
            if key in used:status='needs_review';code='REPEATED_STATEMENT_TARGET';reason='This ledger record is already represented by another statement line.'
            elif not target_valid(chosen,line.kind,statement):status='needs_review';code='UNVERIFIED_STATEMENT_TARGET';reason='Ledger account, currency or posting/verification state needs review.'
            elif target_amount(chosen,line.kind)!=line.amount:status='needs_review';code='STATEMENT_AMOUNT_MISMATCH';reason='The statement amount differs from the supported ledger amount.'
            else:status='matched';code='';reason='Reference relationship and amount supported by an eligible ledger record.';used.add(key)
        namespace='ACCOUNTS_PAYABLE'
        target_snapshot=dict(id=chosen.pk,reference=getattr(chosen,ref),date=str(getattr(chosen,date_field)),amount=str(target_amount(chosen,line.kind)),currency=chosen.currency,supplier_id=chosen.supplier_id) if chosen else None
        target_url=reverse(namespace+':'+line.kind+'_detail',args=[chosen.pk]) if chosen else None
        results.append(dict(target=target_snapshot,target_url=target_url,line_id=line.pk,line_no=line.line_no,reference=line.reference,kind=line.kind,amount=str(line.amount),status=status,code=code,reason=reason,
            target_id=chosen.pk if chosen else None,candidates=[dict(id=row.pk,reference=getattr(row,ref),amount=str(target_amount(row,line.kind))) for row in candidates],review_decision=line.review_decision,review_notes=line.review_notes))
    difference=running-statement.closing_balance
    return dict(status='matched' if difference==0 and all(row['status']=='matched' for row in results) else 'exception',calculated_closing=str(running),recorded_closing=str(statement.closing_balance),balance_difference=str(difference),currency=statement.currency,lines=results)


@transaction.atomic
def reconcile(record_id,data):
    body(data,('revision',))
    statement=get_object_or_404(SupplierStatement,pk=record_id)
    Supplier.objects.select_for_update().get(pk=statement.supplier_id)
    statement=SupplierStatement.objects.select_for_update().get(pk=record_id);check_revision(statement,data.get('revision'))
    result=evaluate(statement)
    for item in result['lines']:
        if item['status']=='matched' and not SupplierStatementMatch.objects.filter(line_id=item['line_id'],active=True).exists():
            SupplierStatementMatch.objects.create(statement=statement,line_id=item['line_id'],**{item['kind']+'_id':item['target_id']},notes='Exact reference, amount, account and currency.')
    previous=statement.evaluations.order_by('-pk').first()
    if previous is None or previous.result!=result:
        observation=SupplierStatementEvaluation.objects.create(statement=statement,result=result)
        statement.reconciliation_status=result['status'];statement.save()
        if statement.ap_transaction_id:
            from discrepancies.services.timeline import record_transition
            record_transition(statement.ap_transaction,'statement_changed','Supplier statement reconciliation observed',statement._meta.label,statement.pk,dict(observation_id=observation.pk,status=result['status'],balance_difference=result['balance_difference'],currency=statement.currency,unmatched_lines=sum(row['status']!='matched' for row in result['lines'])))
            statement.ap_transaction.refresh_reconciliation_status()
    return statement


@transaction.atomic
def review_line(record_id,data):
    body(data,('revision','line_id','decision','notes','target_id'))
    statement=get_object_or_404(SupplierStatement,pk=record_id)
    Supplier.objects.select_for_update().get(pk=statement.supplier_id)
    statement=SupplierStatement.objects.select_for_update().get(pk=record_id);check_revision(statement,data.get('revision'))
    line=get_object_or_404(SupplierStatementLine,pk=data.get('line_id'),statement=statement)
    if data.get('decision') not in ('confirmed','dismissed'):raise ValidationError('Confirm or dismiss the statement review.')
    line.review_decision=data['decision'];line.review_notes=text(data.get('notes'),'review explanation');line.reviewed_at=timezone.now()
    if data.get('target_id'):
        Model,ref,date_field=TARGETS[line.kind]
        target=get_object_or_404(Model,pk=data['target_id'],supplier_id=statement.supplier_id,currency=statement.currency)
        if not target_valid(target,line.kind,statement) or target_amount(target,line.kind)!=line.amount or not getattr(target,date_field) or getattr(target,date_field)>statement.statement_date:raise ValidationError('The selected ledger evidence does not support this statement line.')
        if statement.matches.filter(active=True,**{line.kind:target}).exclude(line=line).exists():raise ValidationError('The ledger record is already matched within this statement.')
        current=line.matches.filter(active=True).first()
        if current and getattr(current,line.kind+'_id')!=target.pk:
            current.active=False;current.superseded_at=timezone.now();current.save()
        if not current or not current.active:SupplierStatementMatch.objects.create(statement=statement,line=line,**{line.kind:target},notes=line.review_notes)
    line.save();reconcile(statement.pk,{'revision':revision(statement)})
    return SupplierStatement.objects.get(pk=statement.pk)


def serialize(statement):
    latest=statement.evaluations.order_by('-pk').first()
    return dict(id=statement.pk,supplier_id=statement.supplier_id,reference=statement.reference,currency=statement.currency,date=statement.statement_date.isoformat(),
        status=statement.reconciliation_status,revision=revision(statement),result=latest.result if latest else None,
        document_url=reverse('DOC_EXTRACTION:document_detail',args=[statement.source_document_id]),
        history=list(statement.evaluations.order_by('-pk').values('id','created_at','result')[:20]))


def statement_evidence(statement,report=None):
    return dict(evidence_type='STATEMENT',source_model=statement._meta.label,source_record_id=str(statement.pk),source_line_id='',source_document_id=statement.source_document_id,source_database_id=None,source_record_key={},provenance={},field_name='statement',observed_value=report or evaluate(statement))


def case_findings(case):
    if case._meta.app_label!='accounts_payable':return []
    from discrepancies.evaluation import finding
    from discrepancies.services import digest
    findings=[]
    for statement in case.supplier_statements.select_related('source_document').order_by('pk'):
        report=evaluate(statement)
        evidence=statement_evidence(statement,report)
        if report['status']=='exception':findings.append(finding('STATEMENT_MISMATCH',{'statement_id':statement.pk},f'Supplier statement {statement.reference} has unmatched or inconsistent ledger evidence.',{'closing_balance':str(statement.closing_balance)},{'status':report['status'],'balance_difference':report['balance_difference'],'unmatched_lines':sum(row['status']!='matched' for row in report['lines']),'report_hash':digest(report)},[evidence],currency=statement.currency))
    return findings


def refresh_related(record):
    """Called after local ledger writes; never queries or writes external ERP rows."""
    from django.db.models import Q
    kind='invoice' if isinstance(record,SupplierSalesInvoice) else 'payment' if isinstance(record,CompanyPayment) else 'credit' if isinstance(record,SupplierCreditNote) else None
    if not kind:return
    ref=TARGETS[kind][1]
    related=SupplierStatement.objects.filter(Q(matches__active=True,**{'matches__'+kind:record})|Q(supplier_id=record.supplier_id,currency=record.currency,lines__kind=kind,lines__reference__iexact=getattr(record,ref))).distinct().order_by('pk')
    for statement in related:
        reconcile(statement.pk,{'revision':revision(statement)})
