from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from django.core.exceptions import ValidationError
from django.db import connection,connections
from django.test import TransactionTestCase
from accounts_receivable.matching_test_support import PartialDeliveryFixture
from .services import investigation,analytics
from .models import FindingRootCause

@skipUnless(connection.vendor=='postgresql','Requires PostgreSQL row locks')
class RootCauseLocks(PartialDeliveryFixture,TransactionTestCase):
    mode='ap'
    def test_competing_attributions_use_case_revision(self):
        self.fixture(receipts=(90,));self.save();self.case.refresh_from_db()
        investigation.start_investigation(self.case,{'revision':investigation.investigation_revision(self.case)})
        finding=self.case.discrepancy_findings.get(finding_code='QUANTITY_SHORTAGE')
        investigation.review_finding(self.case,dict(revision=investigation.investigation_revision(self.case),finding_id=finding.pk,decision='confirmed',notes='Confirmed evidence'))
        payload=dict(revision=investigation.investigation_revision(self.case),finding_id=finding.pk,category='receiving',explanation='Reviewed cause',evidence_ids=[finding.evidence.first().pk])
        barrier=Barrier(2)
        def run(category):
            connections.close_all()
            try:
                barrier.wait(timeout=10);analytics.review_root_cause(self.case,{**payload,'category':category});return 'saved'
            except ValidationError:return 'rejected'
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,['receiving','documentation']))
        self.assertCountEqual(results,['saved','rejected']);self.assertEqual(FindingRootCause.objects.count(),1)
