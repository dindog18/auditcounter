"""The document split preserves records, relationships and permission identity."""

from datetime import date
from decimal import Decimal

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TransactionTestCase

from accounts_receivable.services.catalog import DOCUMENT_APPS, TARGETS, model


class DocumentOwnershipTests(SimpleTestCase):
    def test_documents_and_lines_have_independent_owners_and_legacy_tables(self):
        for mode, workflow in (("ap", "accounts_payable"), ("ar", "accounts_receivable")):
            for target, name in TARGETS[mode].items():
                record = model(mode, target)
                if target == "deduction":
                    self.assertIs(record, apps.get_model(mode + "_deduction", name))
                    continue
                if name not in DOCUMENT_APPS:
                    self.assertEqual(record._meta.app_label, workflow)
                    continue
                with self.subTest(mode=mode, target=target):
                    self.assertEqual(record._meta.app_label, DOCUMENT_APPS[name])
                    self.assertEqual(record._meta.db_table, f"{workflow}_{name.lower()}")
                    self.assertIs(record, apps.get_model(DOCUMENT_APPS[name], name))
                    self.assertEqual(record.__module__, DOCUMENT_APPS[name] + ".models")
                    self.assertEqual(record._meta.get_field("supplier" if mode == "ap" else "customer").related_model._meta.app_label, workflow)
                    if target != "payment":
                        line = model(mode, name + "Line")
                        self.assertEqual(line._meta.app_label, record._meta.app_label)
                        self.assertEqual(line._meta.db_table, f"{workflow}_{name.lower()}line")

    def test_cross_workflow_documents_cannot_be_resolved(self):
        for mode, other in (("ap", "ar"), ("ar", "ap")):
            for target, name in TARGETS[other].items():
                if name in DOCUMENT_APPS:
                    with self.subTest(mode=mode, name=name), self.assertRaises(LookupError):
                        model(mode, name)


class DocumentAppMigrationTests(TransactionTestCase):
    def test_forward_and_reverse_preserve_rows_links_content_types_and_permissions(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        after = [('accounts_payable', '0013_document_apps'), ('accounts_receivable', '0012_document_apps')]
        before = [
            ("accounts_payable", "0012_preserve_configuration_history"),
            ("accounts_receivable", "0011_preserve_configuration_history"),
        ]
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest))
        executor.migrate(before + [(app, None) for app in set(DOCUMENT_APPS.values())])
        historical = executor.loader.project_state(before).apps
        # Current content types were moved back by the reverse migration above.
        saved = []
        for mode, workflow, party_name in (("ap", "accounts_payable", "Supplier"), ("ar", "accounts_receivable", "Customer")):
            key = party_name.lower()
            party = historical.get_model(workflow, party_name).objects.create(**{
                key + "_code": mode, key + "_name": mode.upper(),
            })
            records = {}
            for target, name in TARGETS[mode].items():
                if name not in DOCUMENT_APPS:
                    continue
                values = {key: party}
                if target == "purchase_order":
                    values.update(po_reference_no=mode + "-PO", order_date=date(2026, 11, 5), currency="PHP", total_amount=Decimal("100"))
                elif target == "sales_invoice":
                    values.update(invoice_reference_no=mode + "-INV", invoice_date=date(2026, 11, 5), currency="PHP", total_amount=Decimal("100"))
                elif target == "delivery_receipt":
                    values.update(dr_reference_no=mode + "-DR", delivery_date=date(2026, 11, 5))
                else:
                    values.update(payment_reference_no=mode + "-PAY", currency="PHP", **{"amount_paid" if mode == "ap" else "amount_received": Decimal("50")})
                record = historical.get_model(workflow, name).objects.create(**values)
                records[target] = record
                ct = ContentType.objects.get(app_label=workflow, model=name.lower())
                saved.append((workflow, name, record.pk, ct.pk))
                if target != "payment":
                    parent = {"purchase_order": "purchase_order", "delivery_receipt": "delivery_receipt", "sales_invoice": "invoice"}[target]
                    historical.get_model(workflow, name + "Line").objects.create(**{parent: record, "line_no": 1})
            case = historical.get_model(workflow, "Transaction").objects.create(**{key: party, "currency": "PHP"})
            for field, target in (("purchase_orders", "purchase_order"), ("delivery_receipts", "delivery_receipt"), ("sales_invoices", "sales_invoice")):
                getattr(case, field).add(records[target])
            historical.get_model(workflow, "PaymentAllocation").objects.create(payment=records["payment"], invoice=records["sales_invoice"], cash_amount=Decimal("25"))
            historical.get_model(workflow, "DocumentMatch").objects.create(
                transaction=case, invoice_line=records["sales_invoice"].lines.get(),
                purchase_order_line=records["purchase_order"].lines.get(),
                delivery_receipt_line=records["delivery_receipt"].lines.get(),
            )
            historical.get_model(workflow, "LLMExtractionLog").objects.create(purchase_order=records["purchase_order"], delivery_receipt=records["delivery_receipt"], sales_invoice=records["sales_invoice"], payment=records["payment"])
        tables = set(connection.introspection.table_names())
        from django.contrib.auth.models import Permission
        permissions = set(Permission.objects.values_list("pk", "content_type_id", "codename"))

        executor = MigrationExecutor(connection)
        executor.migrate(after)
        current = executor.loader.project_state(after).apps
        self.assertEqual(set(connection.introspection.table_names()), tables)
        for workflow, name, pk, ct_pk in saved:
            self.assertTrue(current.get_model(DOCUMENT_APPS[name], name).objects.filter(pk=pk).exists())
            self.assertEqual(ContentType.objects.get(pk=ct_pk).app_label, DOCUMENT_APPS[name])
        self.assertEqual(set(Permission.objects.values_list("pk", "content_type_id", "codename")), permissions)
        for mode, workflow in (("ap", "accounts_payable"), ("ar", "accounts_receivable")):
            case = current.get_model(workflow, "Transaction").objects.get()
            for field in ("purchase_orders", "delivery_receipts", "sales_invoices"):
                self.assertEqual(getattr(case, field).count(), 1)
            allocation = current.get_model(workflow, "PaymentAllocation").objects.get()
            self.assertEqual(allocation.cash_amount, Decimal("25"))
            self.assertEqual(allocation.invoice.lines.count(), 1)
            match = current.get_model(workflow, "DocumentMatch").objects.get()
            self.assertEqual(match.purchase_order_line.line_no, 1)
            log = current.get_model(workflow, "LLMExtractionLog").objects.get()
            self.assertEqual(log.sales_invoice_id, allocation.invoice_id)
        MigrationExecutor(connection).migrate(before + [(app, None) for app in set(DOCUMENT_APPS.values())])
        self.assertEqual(set(connection.introspection.table_names()), tables)
        for workflow, name, pk, ct_pk in saved:
            self.assertTrue(historical.get_model(workflow, name).objects.filter(pk=pk).exists())
            self.assertEqual(ContentType.objects.get(pk=ct_pk).app_label, workflow)
