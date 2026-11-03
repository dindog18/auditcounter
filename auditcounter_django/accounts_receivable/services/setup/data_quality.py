"""Bounded, deterministic explanations around the existing accounting validators."""
from django.core.exceptions import ValidationError

from ..catalog import fields, party_key, required_fields
from ..extraction import convert, values_for
from ..catalog import model
from .configuration import clean_output


def finding(code, field, value, explanation, *, blocking=True, source=None):
    # Structured values may contain whole source documents: never retain them.
    observed = '[structured value]' if isinstance(value, (dict, list)) else str(value)[:200] if value is not None else None
    return dict(code=code, severity='error' if blocking else 'warning', source=source,
                field=field, observed_value=observed, explanation=explanation[:500],
                suggested_action='Review the source and field mapping, explicitly accept corrections, then revalidate.', blocking=blocking)


def summary(issues):
    blocking = sum(item['blocking'] for item in issues)
    return dict(passed=not blocking, blocking_count=blocking, warning_count=len(issues)-blocking,
                issues=issues[:200], truncated=len(issues)>200)


def validate_record(mode, config, parsed):
    issues = []
    if not isinstance(parsed, dict) or not isinstance(parsed.get('record'), dict):
        return [finding('INVALID_MAPPING', 'record', None, 'Expected an object containing mapped accounting fields.')]
    line_rows = parsed.get('lines') or []
    if not isinstance(line_rows, list) or any(not isinstance(row, dict) for row in line_rows) or len(line_rows)>1000:
        return [finding('INVALID_MAPPING', 'lines', None, 'Expected at most 1,000 mapped line objects.')]
    rows = [('header', parsed['record'], False)] + [(f'line:{index}', row, True) for index, row in enumerate(line_rows, 1)]
    for prefix, values, is_line in rows:
        allowed = {field.name: field for field in fields(mode, config.target_entity, is_line)}
        required = required_fields(mode, config.target_entity, is_line)
        for key in sorted(required):
            if values.get(key) in (None, '') and not (key=='currency' and config.encoding_rules.get('default_currency')):
                issues.append(finding('MISSING_PARTY' if key==party_key(mode) else 'MISSING_REQUIRED_FIELD', f'{prefix}.{key}', None, 'A required accounting value is missing.'))
        for key, value in values.items():
            field = allowed.get(key)
            path = f'{prefix}.{key}'
            if field is None:
                issues.append(finding('INVALID_MAPPING', path, None, 'The destination field is not supported.'))
                continue
            if value in (None, '') or field.is_relation:
                continue
            try:
                converted = convert(field, value, config.encoding_rules, canonical=config.source_type=='document')
                field.clean(converted, None)
                if key=='currency' and (not isinstance(converted, str) or len(converted)!=3 or not converted.isascii() or not converted.isalpha() or converted!=converted.upper()):
                    raise ValidationError('Use an uppercase three-letter currency code.')
            except (ValidationError, ValueError, TypeError, OverflowError):
                code = ('INVALID_CURRENCY' if key=='currency' else 'INVALID_QUANTITY' if 'quantity' in key else
                        'INVALID_AMOUNT' if field.get_internal_type()=='DecimalField' else 'INVALID_DATE' if 'Date' in field.get_internal_type() else 'INVALID_VALUE')
                issues.append(finding(code, path, value, 'The value is incompatible with the destination field, configured format, or precision.'))
        if is_line and not values.get('item_code'):
            issues.append(finding('UNRESOLVED_SKU', prefix+'.item_code', None, 'Product identity is incomplete; matching requires an exact identity or an explicitly approved alias.', blocking=False))
    try:
        messages = clean_output(mode, config, parsed)
    except (ValidationError, ValueError, TypeError) as error:
        messages = error.messages if isinstance(error, ValidationError) else ['The mapped record could not be validated.']
    for message in messages:
        code = ('ARITHMETIC_MISMATCH' if 'total' in message.lower() else 'MISSING_PARTY' if 'account' in message.lower() else
                'DUPLICATE_SOURCE_KEY' if 'identifier' in message.lower() else 'ACCOUNTING_VALIDATION')
        # Explanations may name account identifiers but are bounded; raw rows are never copied.
        issues.append(finding(code, 'record', None, message))
    if line_rows and config.target_entity in {'purchase_order', 'delivery_receipt', 'sales_invoice'}:
        try:
            header = values_for(mode, config, parsed['record'], canonical=config.source_type=='document')
            party = header.get(party_key(mode))
            if party:
                from sku_matching.services.normalization import normalize_sku
                from sku_matching.services.products import known_lines
                from sku_matching.services.mapping import resolve_product_identity
                context = model(mode, 'Transaction')(**{party_key(mode): party})
                # Per-scan cache avoids repeating a catalog read for every source row.
                cache = getattr(config, '_quality_products', {})
                if party.pk not in cache:
                    cache[party.pk] = {normalize_sku(line.item_code) for line in known_lines(context)}
                config._quality_products = cache
                for index, row in enumerate(line_rows, 1):
                    code = row.get('item_code')
                    if not code or normalize_sku(code) in cache[party.pk]:
                        continue
                    identity = resolve_product_identity(code, dict(scope=mode, **{party_key(mode)+'_id': party.pk},
                        source_system=f'erp:{config.database_source_id}' if config.source_type=='database' else 'document',
                        unit=row.get('unit_of_measure', ''), case=context))
                    if not identity['resolved'] or not identity['valid']:
                        issues.append(finding('UNRESOLVED_SKU', f'line:{index}.item_code', code,
                            'No known exact SKU or current approved mapping was found in the bounded account catalog. Review product identity before matching.', blocking=False))
        except (ValidationError, ValueError, TypeError):
            pass  # Account/field errors were already reported above; never infer identity.
    return issues


def require_valid(mode, config, parsed):
    issues = validate_record(mode, config, parsed)
    errors = [item['explanation'] for item in issues if item['blocking']]
    if errors:
        raise ValidationError(errors)
    return issues
