from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from django.db import connection, connections
from django.test import TransactionTestCase
from accounts_receivable.matching_test_support import PartialDeliveryFixture
from .models import DiscrepancyFinding


@skipUnless(connection.vendor=='postgresql','Requires PostgreSQL row locking')
class FindingConcurrencyTests(PartialDeliveryFixture,TransactionTestCase):
    mode='ap'

    def test_concurrent_refresh_creates_one_finding_and_deduplicates_evidence(self):
        for mode in ('ap','ar'):
            self.mode=mode
            if mode=='ar':
                self.setUp()
            self.fixture(receipts=(98,))
            self.save()
            invoice=self.invoice_line.invoice
            type(invoice).objects.filter(pk=invoice.pk).update(total_amount=1800010)
            Case=type(self.case)
            barrier=Barrier(2)

            def refresh(case_id):
                connections.close_all()
                try:
                    barrier.wait(timeout=10)
                    Case.objects.get(pk=case_id).refresh_reconciliation_status()
                finally:
                    connections.close_all()

            with ThreadPoolExecutor(max_workers=2) as pool:
                futures=[pool.submit(refresh,self.case.pk) for _ in range(2)]
                for future in futures:
                    future.result(timeout=30)
            finding=self.case.discrepancy_findings.get(finding_code='HEADER_TOTAL_MISMATCH')
            self.assertEqual(finding.difference_amount,10)
            self.assertEqual(finding.evidence.count(),2)
            self.assertEqual(finding.evidence.values('snapshot_hash').distinct().count(),2)
            self.assertEqual(self.case.discrepancy_findings.filter(finding_code='QUANTITY_SHORTAGE').count(),1)
