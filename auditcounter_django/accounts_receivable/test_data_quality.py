"""Data-quality gates preserve existing review, import and schema histories."""
from copy import deepcopy
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts_receivable import test_record_setup as fixtures
from accounts_receivable.services import database_updates
from accounts_receivable.services.catalog import model, party_key
from accounts_receivable.services.setup import database, data_quality
from db_extraction.models import ExtractionRun, DatabaseSchema, DatabaseTable, DatabaseColumn
from db_extraction.services.schema_comparison import compare_tables, schema_revision


class DataQualityTests(TestCase):
    def setup_query(self, mode='ap'):
        return fixtures.RecordSetupTests().query(mode)

    def new_snapshot(self, table, *, omit=(), altered=None):
        run = ExtractionRun.objects.create(source=table.schema.run.source, status='completed')
        schema = DatabaseSchema.objects.create(run=run, name=table.schema.name)
        new = DatabaseTable.objects.create(schema=schema, name=table.name)
        for column in table.columns.all():
            if column.name not in omit:
                DatabaseColumn.objects.create(table=new, name=column.name, ordinal_position=column.ordinal_position,
                    formatted_type=altered or column.formatted_type, nullable=column.nullable)
        return run, new

    def test_missing_columns_block_test_and_stream_before_connecting(self):
        for mode in ('ap', 'ar'):
            config, query = self.setup_query(mode)
            old = config.source_table
            self.new_snapshot(old, omit=(party_key(mode)+'_code',))
            with patch('accounts_receivable.services.setup.database.psycopg.connect') as connect:
                report = database.test(mode, config, 5)
                self.assertFalse(report['passed'])
                self.assertIn('REMOVED_COLUMN', [item['code'] for item in report['quality']['issues']])
                with self.assertRaises(ValidationError):
                    list(database.stream_records(mode, config))
                connect.assert_not_called()
            self.assertTrue(old.columns.filter(name=party_key(mode)+'_code').exists())

    def test_type_nullability_and_identifier_changes(self):
        config, _ = self.setup_query()
        _, latest = self.new_snapshot(config.source_table, altered='numeric(12,2)')
        latest.columns.filter(name='id').update(nullable=False)
        codes = {item['code'] for item in compare_tables([config.source_table])}
        self.assertTrue({'COLUMN_TYPE_CHANGED', 'NULLABILITY_CHANGED', 'SOURCE_IDENTIFIER_CHANGED'} <= codes)

    def test_removed_tables_and_failed_snapshots(self):
        config, _ = self.setup_query()
        ExtractionRun.objects.create(source=config.database_source, status='failed')
        self.assertEqual(compare_tables([config.source_table]), [])
        run = ExtractionRun.objects.create(source=config.database_source, status='completed')
        self.assertEqual(schema_revision(config.database_source), run.pk)
        self.assertEqual(compare_tables([config.source_table])[0]['code'], 'REMOVED_TABLE')

    def test_full_review_no_token_when_schema_drifted(self):
        config, _ = self.setup_query()
        self.new_snapshot(config.source_table, omit=('supplier_code',))
        with patch('accounts_receivable.services.database_updates.stream_records') as stream:
            result = database_updates.review('ap', config, None, 'migrate')
        stream.assert_not_called()
        self.assertFalse(result['passed'])
        self.assertNotIn('migration_token', result)

    def test_duplicate_source_keys_and_atomic_apply_validation(self):
        config, _ = self.setup_query()
        parsed = {'record': {'supplier_code': 'X', 'supplier_name': 'Example'}, 'lines': [], 'issues': []}
        rows = [({'id': 1}, parsed), ({'id': 1}, parsed)]
        with patch('accounts_receivable.services.database_updates.stream_records', return_value=iter(rows)):
            result = database_updates.scan('ap', config)
        self.assertFalse(result['passed'])
        self.assertIn('DUPLICATE_SOURCE_KEY', [item['code'] for item in result['quality']['issues']])
        self.assertFalse(model('ap', 'supplier').objects.exists())

    def test_invalid_values_and_optional_partial_lines(self):
        for mode in ('ap', 'ar'):
            config = model(mode, 'ExtractionConfiguration')(target_entity='sales_invoice', source_type='database', encoding_rules={})
            parsed = {'record': {'total_amount': 'NaN', 'invoice_date': 'not a date', 'currency': 'php'},
                      'lines': [{'quantity_invoiced': '-1', 'description': '<script>untrusted</script>'}], 'issues': []}
            issues = data_quality.validate_record(mode, config, parsed)
            codes = {item['code'] for item in issues}
            self.assertTrue({'INVALID_AMOUNT', 'INVALID_DATE', 'INVALID_CURRENCY', 'MISSING_PARTY', 'UNRESOLVED_SKU'} <= codes)
            self.assertFalse(next(item for item in issues if item['code']=='UNRESOLVED_SKU')['blocking'])
            self.assertTrue(all(len(item['explanation'])<=500 for item in issues))

    def test_structured_values_are_redacted(self):
        item = data_quality.finding('INVALID_AMOUNT', 'total', {'password': 'secret'}, 'Invalid')
        self.assertEqual(item['observed_value'], '[structured value]')
        report = data_quality.summary([item]*250)
        self.assertEqual(report['blocking_count'], 250)
        self.assertEqual(len(report['issues']), 200)
        self.assertTrue(report['truncated'])

    def test_review_receipt_changes_when_schema_refreshes(self):
        config, _ = self.setup_query()
        before = database_updates.identity('ap', config, None)
        self.new_snapshot(config.source_table)
        self.assertNotEqual(before, database_updates.identity('ap', config, None))
