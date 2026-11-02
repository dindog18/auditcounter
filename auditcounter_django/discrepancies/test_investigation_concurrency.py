from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from django.core.exceptions import ValidationError
from django.db import connection, connections
from django.test import TransactionTestCase
from accounts_receivable.services.catalog import model
from .models import CaseInvestigation
from .services import investigation as workflow


@skipUnless(connection.vendor=='postgresql','Requires PostgreSQL row locking')
class InvestigationConcurrencyTests(TransactionTestCase):
    def test_concurrent_start_is_unique_and_conflicting_updates_are_rejected(self):
        for mode in ('ap','ar'):
            Case=model(mode,'Transaction')
            case=Case.objects.create(currency='PHP')
            revision=workflow.investigation_revision(case)
            barrier=Barrier(2)

            def start():
                connections.close_all()
                try:
                    barrier.wait(timeout=10)
                    return workflow.start_investigation(Case.objects.get(pk=case.pk),{'revision':revision}).pk
                finally:
                    connections.close_all()

            with ThreadPoolExecutor(max_workers=2) as pool:
                ids=[future.result(timeout=30) for future in [pool.submit(start) for _ in range(2)]]
            self.assertEqual(ids[0],ids[1])
            investigation=CaseInvestigation.objects.get(pk=ids[0])
            self.assertEqual(investigation.activities.count(),1)
            revision=workflow.investigation_revision(case)
            barrier=Barrier(2)

            def update(department):
                connections.close_all()
                try:
                    barrier.wait(timeout=10)
                    workflow.update_investigation(Case.objects.get(pk=case.pk),{'revision':revision,'workflow_status':'investigating','responsible_department':department})
                    return 'saved'
                except ValidationError as error:
                    return error.code
                finally:
                    connections.close_all()

            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes=[future.result(timeout=30) for future in [pool.submit(update,name) for name in ('Accounting','Warehouse')]]
            self.assertCountEqual(outcomes,['saved','conflict'])
            self.assertEqual(investigation.activities.count(),2)
            investigation.refresh_from_db()
            self.assertEqual(investigation.workflow_status,'investigating')
