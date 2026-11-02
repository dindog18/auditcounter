from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from django.db import connection,connections
from django.test import TransactionTestCase
from django.core.exceptions import ValidationError
from accounts_receivable.matching_test_support import PartialDeliveryFixture
from accounts_receivable.services import records
from .services.timeline import record_transition

@skipUnless(connection.vendor=='postgresql','Requires PostgreSQL row locking')
class TimelineConcurrencyTests(PartialDeliveryFixture,TransactionTestCase):
    mode='ap'
    def race(self,operation):
        barrier=Barrier(2)
        def worker():
            connections.close_all()
            try:
                case=type(self.case).objects.get(pk=self.case.pk)
                barrier.wait(timeout=10)
                operation(case)
                return 'saved'
            except ValidationError:return 'conflict'
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(worker) for _ in range(2)]
            return [future.result(timeout=30) for future in futures]
    def test_repeated_event_attempts(self):
        for mode in ('ap','ar'):
            self.mode=mode
            if mode=='ar':self.setUp()
            self.fixture()
            self.assertEqual(self.race(lambda case:record_transition(case,'matches_changed','Concurrent observation',case._meta.label,'race',{'value':'1'},idempotency_key='same-operation')),['saved','saved'])
            self.assertEqual(self.case.timeline_events.filter(source_record_id='race').count(),1)
    def test_concurrent_matching_updates(self):
        for mode in ('ap','ar'):
            self.mode=mode
            if mode=='ar':self.setUp()
            self.fixture()
            payload=self.payload()
            self.assertCountEqual(self.race(lambda case:records.save_matches(mode,case.pk,payload)),['saved','conflict'])
            self.assertEqual(self.case.timeline_events.filter(event_type='matches_changed').count(),1)
            self.assertEqual(self.case.line_matches.count(),2)

    def test_payment_allocation_and_matching_share_lock_order(self):
        from accounts_receivable.services.catalog import model,party_key
        for mode in ('ap','ar'):
            self.mode=mode
            if mode=='ar':self.setUp()
            self.fixture()
            invoice=self.invoice_line.invoice
            type(invoice).objects.filter(pk=invoice.pk).update(invoice_status='posted')
            payment=model(mode,'payment').objects.create(**{party_key(mode):self.party},payment_reference_no='CONCURRENT-PAY',payment_date='2026-11-02',currency='PHP',**{'amount_paid' if mode=='ap' else 'amount_received':100})
            payload=self.payload();barrier=Barrier(2)
            def work(kind):
                connections.close_all()
                try:
                    barrier.wait(timeout=10)
                    if kind=='matching':records.save_matches(mode,self.case.pk,payload)
                    else:model(mode,'PaymentAllocation').objects.create(payment_id=payment.pk,invoice_id=invoice.pk,cash_amount=100)
                finally:connections.close_all()
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures=[pool.submit(work,kind) for kind in ('matching','payment')]
                for future in futures:future.result(timeout=30)
            self.assertEqual(self.case.line_matches.count(),2)
            self.assertEqual(invoice.payment_allocations.count(),1)
            self.assertEqual(self.case.timeline_events.filter(event_type='payments_changed').count(),1)
