from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from django.core.exceptions import ValidationError
from django.db import connection, connections
from django.test import TransactionTestCase
from document_extraction.models import Document
from .models import Supplier
from .services import statements
from accounts_receivable.services.catalog import revision

@skipUnless(connection.vendor=='postgresql','Requires PostgreSQL row locks')
class StatementLocks(TransactionTestCase):
    def test_conflicting_reviews_preserve_one_current_observation(self):
        supplier=Supplier.objects.create(supplier_code='ST',supplier_name='Statement')
        doc=Document.objects.create(file_name='s.csv',storage_path='synthetic/s.csv',document_type='statement')
        statement=statements.create_statement(dict(supplier_id=supplier.pk,reference='ST',statement_date='2026-11-02',period_start='2026-11-01',currency='PHP',opening_balance='100',closing_balance='90',source_document_id=doc.pk,csv='reference,date,type,amount\nC,2026-11-02,credit,10'))
        payload=dict(revision=revision(statement),line_id=statement.lines.get().pk,decision='confirmed',notes='Reviewed source')
        barrier=Barrier(2)
        def run(decision):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                statements.review_line(statement.pk,{**payload,'decision':decision})
                return 'saved'
            except ValidationError:return 'rejected'
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(run,['confirmed','dismissed']))
        self.assertCountEqual(results,['saved','rejected'])
        self.assertEqual(statement.evaluations.count(),2)
