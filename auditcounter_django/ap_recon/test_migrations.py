"""Existing purchase orders receive one case during deployment in AP and AR."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class ExistingOrderMigrationTests(TransactionTestCase):
    def test_backfill_creates_missing_cases_and_keeps_existing_case_ids(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        before = [(mode+'_recon', '0001_initial') for mode in ('ap','ar')]
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest))
        executor.migrate(before)
        historical = executor.loader.project_state(before).apps
        saved = []
        for mode,workflow,key,party,app,name in [
            ('ap','accounts_payable','supplier','Supplier','company_purchase_order','CompanyPurchaseOrder'),
            ('ar','accounts_receivable','customer','Customer','customer_purchase_order','CustomerPurchaseOrder'),
        ]:
            account = historical.get_model(workflow,party).objects.create(**{key+'_code':'BACKFILL',key+'_name':'Existing'})
            order = historical.get_model(app,name).objects.create(**{key:account},po_reference_no='EXISTING',order_date='2026-11-05',currency='PHP')
            existing = historical.get_model(app,name).objects.create(**{key:account},po_reference_no='CASE-EXISTS',order_date='2026-11-05',currency='PHP')
            case = historical.get_model(mode+'_recon','Reconciliation').objects.create(purchase_order=existing)
            saved.append((mode,order.pk,existing.pk,case.pk))
        executor = MigrationExecutor(connection)
        executor.migrate(latest)
        current = executor.loader.project_state(latest).apps
        for mode,order_id,existing_id,case_id in saved:
            Case = current.get_model(mode+'_recon','Reconciliation')
            self.assertEqual(Case.objects.filter(purchase_order_id=order_id).count(),1)
            self.assertEqual(Case.objects.get(purchase_order_id=existing_id).pk,case_id)
