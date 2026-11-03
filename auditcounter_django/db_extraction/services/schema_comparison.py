"""Compare reviewed metadata with the latest completed snapshot; never query ERP rows."""
from django.core.exceptions import ValidationError

from db_extraction.models import DatabaseTable


def issue(code, field, explanation, observed=None, *, blocking=True):
    return {'code': code, 'severity': 'error' if blocking else 'warning',
            'field': field, 'observed_value': str(observed)[:200] if observed is not None else None,
            'explanation': explanation, 'suggested_action': 'Refresh the schema, explicitly correct the mapping, and revalidate.',
            'blocking': blocking}


def key_columns(table):
    constraint = table.constraints.filter(constraint_type='primary_key').first()
    return list(constraint.columns.order_by('position').values_list('column__name', flat=True)) if constraint else []


def compare_tables(tables):
    """Check the complete source projections, including keys and join columns.

    A removed column may have been renamed, but names are never inferred. New
    columns are safe; altered source columns require an explicit mapping review.
    """
    results, latest_by_source = [], {}
    for table in {table.pk: table for table in tables}.values():
        source = table.schema.run.source
        if source.pk not in latest_by_source:
            latest_by_source[source.pk] = source.extraction_runs.filter(status='completed').order_by('-created_at', '-pk').first()
        latest = latest_by_source[source.pk]
        if latest is None:
            results.append(issue('MISSING_SCHEMA', str(table), 'No completed source schema is available.'))
            continue
        if latest.database_name and latest.database_name != source.database_name:
            results.append(issue('SOURCE_IDENTITY_CHANGED', str(table), 'The connection now refers to a different database.'))
        if latest.pk == table.schema.run_id:
            continue
        if table.schema.run.database_name and latest.database_name != table.schema.run.database_name:
            results.append(issue('SOURCE_IDENTITY_CHANGED', str(table), 'The source database identity changed since mapping review.'))
        current = DatabaseTable.objects.filter(schema__run=latest, schema__name=table.schema.name, name=table.name).prefetch_related('columns').first()
        if current is None:
            results.append(issue('REMOVED_TABLE', str(table), 'The mapped table is absent from the latest completed schema.'))
            continue
        columns = {column.name: column for column in current.columns.all()}
        for old in table.columns.all():
            field = f'{table}.{old.name}'
            new = columns.get(old.name)
            if new is None:
                results.append(issue('REMOVED_COLUMN', field, 'The column is missing or renamed; no replacement is assumed.'))
                continue
            if (old.formatted_type, old.type_name, old.numeric_precision, old.numeric_scale) != (new.formatted_type, new.type_name, new.numeric_precision, new.numeric_scale):
                results.append(issue('COLUMN_TYPE_CHANGED', field, 'The source type or financial precision changed.', new.formatted_type))
            if old.nullable != new.nullable:
                results.append(issue('NULLABILITY_CHANGED', field, 'The source nullability contract changed.', new.nullable))
        if key_columns(table) != key_columns(current):
            results.append(issue('SOURCE_IDENTIFIER_CHANGED', str(table), 'The primary-key columns or their order changed.'))
    return results


def configuration_issues(config):
    query = (config.setup_data or {}).get('database', {})
    ids = {value for value in [config.source_table_id, config.line_source_table_id, query.get('table')] if value}
    ids.update(item.get('table') for item in query.get('joins', []) if item.get('table'))
    ids.update(item.get('table') for item in query.get('pipeline', {}).get('steps', []) if item.get('table'))
    tables = list(DatabaseTable.objects.filter(pk__in=ids, schema__run__source_id=config.database_source_id).select_related('schema__run__source').prefetch_related('columns'))
    results = compare_tables(tables)
    if len(tables) != len({str(value) for value in ids}):
        results.append(issue('INVALID_MAPPING', 'table', 'A mapped table is unavailable in the selected source.'))
    return results


def require_current_schema(tables):
    issues = compare_tables(tables)
    if any(item['blocking'] for item in issues):
        raise ValidationError([f"{item['code']}: {item['field']}: {item['explanation']} {item['suggested_action']}" for item in issues if item['blocking']])


def schema_revision(source):
    return source.extraction_runs.filter(status='completed').order_by('-created_at', '-pk').values_list('pk', flat=True).first()
