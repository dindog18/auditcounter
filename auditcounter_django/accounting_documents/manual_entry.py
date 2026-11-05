"""Validated manual entry for document models owned by the AP and AR apps."""

from django.core.exceptions import ValidationError
from django.conf import settings
from django.utils import timezone
from django.db import models, transaction
from django.db.models.deletion import ProtectedError
from django.forms import modelform_factory
from django.shortcuts import get_object_or_404

from accounts_receivable.services.catalog import (
    RESOURCES, fields, model, party_key, required_fields, revision,
)

PARENTS = {'purchase_order': 'purchase_order', 'delivery_receipt': 'delivery_receipt', 'sales_invoice': 'invoice'}


def is_manual(record):
    return not any(getattr(record, name, None) for name in (
        'source_document_id', 'source_database_id', 'source_table_id',
        'source_text_log_id', 'source_llm_log_id', 'source_record_key', 'imported_at',
    ))


def editable_fields(mode, target, lines=False):
    result = fields(mode, target, lines)
    if not lines and not any(field.name == 'notes' for field in result):
        # Free text context is a document's notes, independent of extraction setup.
        result += [field for field in model(mode, target)._meta.fields
                   if field.name.endswith('_context')]
    return result


def document_form(mode, target, *, lines=False, data=None, instance=None):
    Record = model(mode, target)
    if lines:
        Record = model(mode, Record.__name__ + 'Line')
    names = [field.name for field in editable_fields(mode, target, lines)]
    form = modelform_factory(Record, fields=names)(data=data, instance=instance)
    for name in required_fields(mode, target, lines):
        form.fields[name].required = True
    if not lines:
        form.fields[party_key(mode)].queryset = model(mode, party_key(mode)).objects.filter(is_active=True)
        # Keep an existing inactive account selectable when editing its document.
        current = getattr(instance, party_key(mode) + '_id', None) if instance else None
        if current:
            form.fields[party_key(mode)].queryset = model(mode, party_key(mode)).objects.filter(
                models.Q(is_active=True) | models.Q(pk=current))
    return form


def schema(mode, target):
    def describe(lines=False):
        form = document_form(mode, target, lines=lines)
        result = []
        for field in editable_fields(mode, target, lines):
            bound = form.fields[field.name]
            initial = form.get_initial_for_field(bound, field.name)
            choices = list(field.flatchoices) if field.choices else []
            kind = (('party' if field.name == party_key(mode) else field.name) if field.is_relation else 'boolean' if isinstance(field, models.BooleanField) else 'select' if choices else
                    'datetime-local' if isinstance(field, models.DateTimeField) else
                    'date' if isinstance(field, models.DateField) else
                    'number' if isinstance(field, (models.DecimalField, models.IntegerField)) else
                    'textarea' if isinstance(field, models.TextField) else 'text')
            result.append({
                'key': field.name, 'label': 'Notes' if field.name.endswith('_context') else str(bound.label),
                'type': kind, 'required': bound.required, 'choices': choices,
                'initial': initial, 'maxLength': getattr(field, 'max_length', None),
                'step': '0.0001' if getattr(field, 'decimal_places', 0) == 4 else '0.01' if isinstance(field, models.DecimalField) else '1',
            })
        return result
    return {'fields': describe(), 'lineFields': describe(True) if target in PARENTS else [], 'timeZone': settings.TIME_ZONE}


def manual_revision(record, target):
    extra = [revision(line) for line in record.lines.order_by('line_no', 'pk')] if target in PARENTS else list(
        record.invoice_allocations.order_by('pk').values('pk', 'invoice_id', 'cash_amount', 'withholding_tax_amount', 'discount_amount')) if target == 'payment' else []
    return revision(record, extra)


def initial_values(record, mode, target):
    def values(row, lines=False):
        result = {}
        for field in editable_fields(mode, target, lines):
            value = field.value_from_object(row)
            if isinstance(field, models.DateTimeField) and value and timezone.is_aware(value):
                value = timezone.localtime(value)
            # Send decimals as strings so editing never rounds saved values through JS floats.
            result[field.name] = str(value) if isinstance(field, models.DecimalField) else value
        return result
    return {'record': values(record), 'lines': [dict(values(line, True), id=line.pk)
            for line in record.lines.order_by('line_no', 'pk')] if target in PARENTS else [],
            'revision': manual_revision(record, target)}


def _clean_form(mode, target, values, instance, *, lines=False):
    if not isinstance(values, dict):
        raise ValidationError('Document fields and each line must be objects.')
    template = document_form(mode, target, lines=lines, instance=instance)
    if set(values) - set(template.fields):
        raise ValidationError('The entry contains unknown or system-managed fields.')
    merged = {name: template.get_initial_for_field(field, name) for name, field in template.fields.items()}
    merged.update(values)
    form = document_form(mode, target, lines=lines, data=merged, instance=instance)
    if not form.is_valid():
        raise ValidationError(form.errors.as_text())
    return form.save(commit=False)


@transaction.atomic
def save(mode, resource, data, record_id=None):
    if resource not in RESOURCES:
        raise ValidationError('Choose a purchase order, delivery receipt, invoice, or payment.')
    if set(data) - {'resource', 'record', 'lines', 'revision'}:
        raise ValidationError('The entry contains unknown or system-managed fields.')
    target, key = RESOURCES[resource], party_key(mode)
    Record = model(mode, target)
    values, raw_lines = data.get('record'), data.get('lines', [])
    if not isinstance(values, dict) or not isinstance(raw_lines, list) or len(raw_lines) > 1000:
        raise ValidationError('Provide document fields and up to 1,000 line items.')
    if record_id and target in PARENTS and 'lines' not in data:
        raise ValidationError('Send the complete line items when editing this document.')
    if target not in PARENTS and raw_lines:
        raise ValidationError('Payments do not have document line items.')
    initial = get_object_or_404(Record, pk=record_id) if record_id else Record()
    try:
        account_id = int(values.get(key) or getattr(initial, key + '_id', None))
    except (TypeError, ValueError, OverflowError):
        raise ValidationError(f'Choose an existing {key}.') from None
    if isinstance(values.get(key), bool) or str(account_id) != str(values.get(key, account_id)):
        raise ValidationError(f'Choose a valid {key}.')
    # Follow the same account-first lock order as matching and allocation writes.
    account_ids = {account_id, getattr(initial, key + '_id', None)} - {None}
    list(model(mode, key).objects.select_for_update().filter(pk__in=account_ids).order_by('pk'))
    record = get_object_or_404(Record.objects.select_for_update(), pk=record_id) if record_id else initial
    if not is_manual(record):
        raise ValidationError('This record has an extraction source. Review and update it through its source workflow.')
    previous = list(record.lines.select_for_update().order_by('line_no', 'pk')) if record_id and target in PARENTS else []
    if record_id and data.get('revision') != manual_revision(record, target):
        raise ValidationError('This record or its lines changed. Reload before saving.', code='conflict')
    old_account, old_currency = getattr(record, key + '_id'), getattr(record, 'currency', None)
    record = _clean_form(mode, target, values, record)
    if record_id and (old_account != getattr(record, key + '_id') or old_currency != getattr(record, 'currency', None)):
        if any(getattr(record, name).exists() for name in ('reconciliation_cases', 'payment_allocations', 'invoice_allocations') if hasattr(record, name)):
            raise ValidationError('Remove reconciliation and payment allocation links before changing the account or currency.')
    lines, used_ids, used_numbers = [], set(), set()
    if target in PARENTS:
        Line = model(mode, Record.__name__ + 'Line')
        previous_by_id = {line.pk: line for line in previous}
        # Save the parent inside this transaction so normal model/line constraints apply.
        record.save()
        for index, raw in enumerate(raw_lines, start=1):
            if not isinstance(raw, dict):
                raise ValidationError(f'Line {index} must be an object.')
            raw = dict(raw)
            line_id = raw.pop('id', None)
            if line_id is not None and (type(line_id) is not int or line_id not in previous_by_id or line_id in used_ids):
                raise ValidationError('Choose each existing line once, from this document only.')
            if line_id:
                used_ids.add(line_id)
            line = previous_by_id[line_id] if line_id else Line()
            setattr(line, PARENTS[target], record)
            if raw.get('line_no') in (None, ''):
                raw['line_no'] = index
            try:
                line = _clean_form(mode, target, raw, line, lines=True)
            except ValidationError as error:
                raise ValidationError(f'Line {index}: {"; ".join(error.messages)}') from error
            if line.line_no in used_numbers:
                raise ValidationError('Line numbers must be unique within the document.')
            used_numbers.add(line.line_no)
            quantity = 'quantity_ordered' if target == 'purchase_order' else 'quantity_invoiced' if target == 'sales_invoice' else None
            if quantity and getattr(line, quantity) <= 0:
                raise ValidationError(f'Line {index} needs a positive quantity.')
            lines.append(line)
        from accounts_receivable.services.extraction import validate_totals
        validate_totals(target, record, lines)
        try:
            for line in previous:
                if line.pk not in used_ids:
                    line.delete()
            for line in lines:
                line.save()
        except ProtectedError as error:
            raise ValidationError('Remove existing line matches before removing these line items.') from error
    else:
        record.save()
    return record
