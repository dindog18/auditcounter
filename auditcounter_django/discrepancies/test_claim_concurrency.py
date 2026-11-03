from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from django.core.exceptions import ValidationError
from django.db import connection,connections
from django.test import TransactionTestCase
from accounts_payable.models import Supplier,Transaction
from accounts_receivable.services.catalog import revision
from .models import SupplierClaim
from .services.claims import transition


@skipUnless(connection.vendor=='postgresql','Requires PostgreSQL independent connections')
class ClaimLockTests(TransactionTestCase):
    def test_conflicting_transitions_are_serialized(self):
        supplier=Supplier.objects.create(supplier_code='CL',supplier_name='Claims')
        case=Transaction.objects.create(supplier=supplier,currency='PHP',transaction_date='2026-11-02')
        claim=SupplierClaim.objects.create(ap_transaction=case,supplier=supplier,reference='CL-1',category='quantity',currency='PHP',claimed_amount='10.00')
        claim.refresh_from_db();payload=dict(revision=revision(claim),status='submitted',notes='Submitted manually')
        barrier=Barrier(2)
        def run():
            connections.close_all()
            try:
                barrier.wait(timeout=10);transition(claim.pk,payload);return 'saved'
            except ValidationError:return 'rejected'
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            tasks=[pool.submit(run) for _ in range(2)]
            self.assertCountEqual([task.result(timeout=30) for task in tasks],['saved','rejected'])
        self.assertEqual(case.timeline_events.filter(event_type='claim_changed').count(),1)
