"""Save accounts, reconciliation cases, matches, and allocations atomically."""

from decimal import Decimal

from discrepancies.services import defer_reconciliation
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404

from .catalog import check_revision, model, party_key, revision, RESOURCES


@transaction.atomic
def delete_document(mode, resource, record_id, data):
    """Delete a standalone accounting record while preserving extraction history."""
    if resource not in RESOURCES:
        raise ValidationError('Choose a purchase order, invoice, delivery receipt, or payment.')
    target = RESOURCES[resource]
    Target = model(mode, target)
    initial = get_object_or_404(Target, pk=record_id)
    account_id = getattr(initial, party_key(mode)+'_id')
    if account_id:
        model(mode, party_key(mode)).objects.select_for_update().get(pk=account_id)
    record = get_object_or_404(Target.objects.select_for_update(), pk=record_id)
    if getattr(record, party_key(mode)+'_id') != account_id:
        raise ValidationError('This record changed. Reload before deleting.', code='conflict')
    check_revision(record, data.get('revision'), allocations(record) if target == 'payment' else None)
    if data.get('confirmed') is not True:
        raise ValidationError('Confirm the record deletion first.')
    for relation in ('reconciliation_cases', 'payment_allocations', 'invoice_allocations'):
        if hasattr(record, relation) and getattr(record, relation).exists():
            raise ValidationError('This record is linked to reconciliation or payment allocations. Remove those links before deleting.')
    logs = model(mode, 'LLMExtractionLog').objects.select_for_update().filter(**{target: record})
    if any(log.status in {'queued', 'processing'} for log in logs):
        raise ValidationError('Extraction is still running for this record. Wait before deleting.')
    try:
        # Nullable protected references preserve attempts and their original
        # provider output when the resulting accounting record is removed.
        logs.update(**{target: None})
        if target != 'payment':
            record.lines.all().delete()
        record.delete()
    except ProtectedError as error:
        raise ValidationError('This record has linked accounting records. Remove those links before deleting.') from error


def case_membership(case):
    return {name: list(getattr(case, name).order_by("pk").values_list("pk", flat=True))
            for name in ("purchase_orders", "delivery_receipts", "sales_invoices")}


def allocations(payment):
    return list(payment.invoice_allocations.order_by("pk").values("invoice_id", "cash_amount", "withholding_tax_amount", "discount_amount"))


def matches(case):
    return list(case.line_matches.order_by("pk").values("invoice_line_id", "purchase_order_line_id", "delivery_receipt_line_id", "matched_quantity", "match_status"))


@transaction.atomic
def save_party(mode, data, record_id=None):
    record = get_object_or_404(model(mode, party_key(mode)).objects.select_for_update(), pk=record_id) if record_id else model(mode, party_key(mode))()
    if record_id:
        check_revision(record, data.get("revision"))
    mapping = {"reference": party_key(mode)+"_code", "name": party_key(mode)+"_name", "taxId": "tax_identification_no",
               "address": "billing_address", "contact": "contact_person", "email": "email", "phone": "phone",
               "terms": "payment_terms_days", "notes": "llm_context"}
    if mode == "ar":
        mapping.update(shippingAddress="shipping_address", creditLimit="credit_limit")
    for key, field in mapping.items():
        if key in data:
            setattr(record, field, data[key])
    if data.get("status") not in {"active", "inactive"}:
        raise ValidationError("Choose an account status.")
    record.is_active = data["status"] == "active"
    record.full_clean()
    record.save()
    return record


@transaction.atomic
@defer_reconciliation()
def save_case(mode, data, record_id=None):
    account = get_object_or_404(model(mode, party_key(mode)).objects.select_for_update(), pk=data.get("partyId"))
    case = get_object_or_404(model(mode, "Transaction").objects.select_for_update(), pk=record_id) if record_id else model(mode, "Transaction")()
    if record_id:
        check_revision(case, data.get("revision"), case_membership(case))
        if getattr(case, party_key(mode)+"_id") != account.pk:
            raise ValidationError("Create a new case to change the account.")
    case._timeline_before_result=(case.reconciliation_status,case.total_discrepancy_amount)
    selected = {}
    for key, relation, target in [("orderIds", "purchase_orders", "purchase_order"), ("receiptIds", "delivery_receipts", "delivery_receipt"), ("invoiceIds", "sales_invoices", "sales_invoice")]:
        ids = data.get(key, [])
        if not isinstance(ids, list) or any(type(pk) is not int for pk in ids) or len(ids) != len(set(ids)):
            raise ValidationError("Choose valid document IDs without duplicates.")
        rows = list(model(mode, target).objects.select_for_update().filter(pk__in=ids).order_by("pk"))
        if len(rows) != len(ids) or any(getattr(row, party_key(mode)+"_id") != account.pk or (hasattr(row, "currency") and row.currency != data.get("currency")) for row in rows):
            raise ValidationError("Case documents must have the same account and currency.")
        selected[relation] = rows
    if not selected["sales_invoices"]:
        raise ValidationError("Link at least one invoice.")
    from .case_duplicates import find_exact_duplicate_case, DuplicateCaseError
    duplicate=find_exact_duplicate_case(mode,account.pk,data.get('currency'),
        {key:[row.pk for row in rows] for key,rows in selected.items()},exclude_case_id=case.pk)
    if duplicate:
        raise DuplicateCaseError(mode,duplicate)
    if case.pk:
        # Membership edits invalidate saved comparisons; they must be reviewed again.
        changed = any(set(getattr(case, key).values_list("pk", flat=True)) != {row.pk for row in rows} for key, rows in selected.items())
        if changed:
            case.line_matches.all().delete()
    setattr(case, party_key(mode), account)
    case.transaction_date = data.get("date")
    case.currency = data.get("currency")
    case.notes = data.get("notes", "")
    case.reconciliation_status = "pending"
    creating=case.pk is None
    case.save()
    if creating:
        from discrepancies.services.timeline import record_transition
        record_transition(case,'case_created','Reconciliation case created',case._meta.label,case.pk,{'currency':case.currency,'party_id':account.pk})
    for key, rows in selected.items():
        getattr(case, key).set(rows)
    case.refresh_reconciliation_status()
    return case


@transaction.atomic
@defer_reconciliation()
def save_allocations(mode, record_id, data):
    payment = get_object_or_404(model(mode, "payment"), pk=record_id)
    # Account lock serializes all allocations for this account before invoice locks.
    model(mode, party_key(mode)).objects.select_for_update().get(pk=getattr(payment, party_key(mode)+"_id"))
    payment = model(mode, "payment").objects.select_for_update().get(pk=record_id)
    check_revision(payment, data.get("revision"), allocations(payment))
    if payment.payment_status == "reversed":
        raise ValidationError("Reversed payments cannot be allocated.")
    rows = data.get("allocations")
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValidationError("Provide up to 1,000 allocations.")
    if any(not isinstance(row, dict) for row in rows):
        raise ValidationError("Each allocation must be an object containing its field values.")
    old_ids = set(payment.invoice_allocations.values_list("invoice_id", flat=True))
    seen = set()
    payment.invoice_allocations.all().delete()
    for row in rows:
        invoice_id = row.get("invoiceId")
        if type(invoice_id) is not int or invoice_id in seen:
            raise ValidationError("Choose each invoice once.")
        seen.add(invoice_id)
        invoice = get_object_or_404(model(mode, "sales_invoice").objects.select_for_update(), pk=invoice_id)
        if invoice.invoice_status in {"draft", "pending", "void"}:
            raise ValidationError("Only posted or disputed invoices can receive allocations.")
        allocation = model(mode, "PaymentAllocation")(
            payment=payment, invoice=invoice, cash_amount=row.get("cash", "0"),
            withholding_tax_amount=row.get("withholding", "0"), discount_amount=row.get("discount", "0"))
        allocation.save()  # Existing model validates account, currency and component limits.
    from discrepancies.services.timeline import observe_invoice_cases
    for linked_case in model(mode,'Transaction').objects.filter(sales_invoices__pk__in=old_ids | seen).distinct().order_by('pk'):
        observe_invoice_cases(linked_case)
    for invoice in model(mode, "sales_invoice").objects.filter(pk__in=old_ids | seen):
        invoice.refresh_payment_status()
    return payment


@transaction.atomic
@defer_reconciliation()
def save_matches(mode, record_id, data):
    case = get_object_or_404(model(mode, "Transaction"), pk=record_id)
    model(mode, party_key(mode)).objects.select_for_update().get(pk=getattr(case, party_key(mode)+"_id"))
    case = model(mode, "Transaction").objects.select_for_update().get(pk=record_id)
    check_revision(case, data.get("revision"), [case_membership(case), matches(case)])
    if data.get('preserveExisting') or data.get('suggestionRevision'):
        from .auto_matching import source_revision
        if not data.get('preserveExisting') or not data.get('suggestionRevision'):
            raise ValidationError("Auto Match confirmation requires its source revision and merge mode.")
        if source_revision(case, lock=True) != data['suggestionRevision']:
            raise ValidationError("Source evidence or allocations changed. Run Auto Match again.", code='conflict')
    rows = data.get("matches")
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValidationError("Provide up to 1,000 line matches.")
    if any(not isinstance(row, dict) for row in rows):
        raise ValidationError("Each line match must be an object containing its field values.")
    if data.get('preserveExisting'):
        rows = merge_match_rows(case, rows)
    prepared = prepare_matches(mode, case, rows, lock=True)
    if data.get('preserveExisting'):
        saved_keys = set(case.line_matches.values_list('invoice_line_id', 'purchase_order_line_id', 'delivery_receipt_line_id'))
        for match in prepared:
            identity = (match.invoice_line_id, match.purchase_order_line_id, match.delivery_receipt_line_id)
            if identity not in saved_keys:
                match.save()
    else:
        case.line_matches.all().delete()
        for match in prepared:
            match.save()
    case.refresh_reconciliation_status()
    return case


def prepare_matches(mode, case, rows, *, lock=False):
    """Validate the whole replacement before deleting anything; shared with read-only preview."""
    from importlib import import_module
    from django.db.models import Sum
    validate = import_module(model(mode, "Transaction").__module__.rsplit('.', 1)[0] + '.services.reconciliation').validate_match
    Match = model(mode, "DocumentMatch")
    if not isinstance(rows, list) or len(rows) > 1000 or any(not isinstance(row, dict) for row in rows):
        raise ValidationError("Provide up to 1,000 allocation objects.")
    fields = (("invoiceLineId", "invoice_line", "quantity_invoiced"),
              ("orderLineId", "purchase_order_line", "quantity_ordered"),
              ("receiptLineId", "delivery_receipt_line", "quantity_accepted"))
    sources = {}
    for key, field, capacity in fields:
        ids = {row.get(key) for row in rows if type(row.get(key)) is int}
        if any(row.get(key) is not None and type(row.get(key)) is not int for row in rows):
            raise ValidationError("Choose valid source line IDs.")
        query = Match._meta.get_field(field).related_model.objects.filter(pk__in=ids).order_by('pk')
        if lock:
            query = query.select_for_update()
        sources[field] = {line.pk: line for line in query}
        if len(sources[field]) != len(ids):
            raise ValidationError("A selected source line no longer exists.")
    seen, prepared, totals = set(), [], {}
    for row in rows:
        identity = tuple(row.get(key) for key, _, _ in fields)
        if identity[0] is None or identity in seen:
            raise ValidationError("Choose an invoice line and avoid duplicate invoice/order/receipt allocations.")
        seen.add(identity)
        match = Match(transaction=case, matched_quantity=row.get('quantity', '0'))
        for key, field, capacity in fields:
            setattr(match, field, sources[field].get(row.get(key)))
        match.clean_fields()
        if match.matched_quantity > 0:
            if not match.purchase_order_line_id or not match.delivery_receipt_line_id:
                raise ValidationError("Positive allocations require an order and accepted receipt line.")
            match.match_status = 'matched'
        validate(match, check_amounts=False, check_capacity=False)
        for key, field, capacity in fields:
            line = getattr(match, field)
            if line is None:
                continue
            total_key = (field, line.pk)
            totals[total_key] = totals.get(total_key, Decimal('0')) + match.matched_quantity
            external = Match.objects.filter(**{field: line}, purchase_order_line__isnull=False,
                                            delivery_receipt_line__isnull=False).exclude(transaction=case)
            used = external.aggregate(total=Sum('matched_quantity'))['total'] or Decimal('0')
            if used + totals[total_key] > getattr(line, capacity):
                raise ValidationError("Matched quantity exceeds the available quantity, including other cases.")
            if external.filter(invoice_line_id=identity[0], purchase_order_line_id=identity[1], delivery_receipt_line_id=identity[2]).exists():
                raise ValidationError("Duplicate invoice/order/receipt allocation in another case.")
        try:
            validate(match, check_capacity=False)
        except ValidationError:
            # Only arithmetic remains: retain evidence and visibly flag its source data.
            match.match_status = 'exception'
        prepared.append(match)
    return prepared


def preview_matches(mode, record_id, data):
    from importlib import import_module
    case = get_object_or_404(model(mode, "Transaction"), pk=record_id)
    check_revision(case, data.get('revision'), [case_membership(case), matches(case)])
    prepared = prepare_matches(mode, case, data.get('matches'))
    service = import_module(model(mode, "Transaction").__module__.rsplit('.', 1)[0] + '.services.reconciliation')
    return service.evaluate_reconciliation(case, prepared)


def merge_match_rows(case, rows):
    """Auto confirmation adds to saved manual matches; it cannot silently replace them."""
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValidationError("Provide allocation objects.")
    existing = {(row['invoice_line_id'], row['purchase_order_line_id'], row['delivery_receipt_line_id']):
                dict(invoiceLineId=row['invoice_line_id'], orderLineId=row['purchase_order_line_id'],
                     receiptLineId=row['delivery_receipt_line_id'], quantity=str(row['matched_quantity']))
                for row in matches(case)}
    seen, additions = set(), []
    for row in rows:
        identity = tuple(row.get(key) for key in ('invoiceLineId', 'orderLineId', 'receiptLineId'))
        if any(value is not None and type(value) is not int for value in identity):
            raise ValidationError("Choose valid source line IDs.")
        if identity in seen:
            raise ValidationError("Duplicate invoice/order/receipt allocation.")
        seen.add(identity)
        if identity in existing:
            # Validate decimals through the existing model field before comparing.
            field = case.line_matches.model._meta.get_field('matched_quantity')
            quantity = field.clean(row.get('quantity', '0'), None)
            if quantity != Decimal(existing[identity]['quantity']):
                raise ValidationError("Save edits to existing allocations separately before using Auto Match.")
        else:
            additions.append(row)
    return list(existing.values()) + additions
