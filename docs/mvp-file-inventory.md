# Exact implementation file inventory

Paths are relative to the repository root. Shared integration files identify every applicable milestone. Pre-existing `output/` and `outputs/` directories are excluded and preserved. No existing migration was rewritten.

| Milestone | Change | File |
|---|---|---|
| 1 | Created | `auditcounter_django/accounts_receivable/frontend_tests/data-quality.test.cjs` |
| 1 | Modified | `auditcounter_django/accounts_receivable/services/configuration_chat.py` |
| 1 | Modified | `auditcounter_django/accounts_receivable/services/imports.py` |
| 1 | Modified | `auditcounter_django/accounts_receivable/services/setup/actions.py` |
| 1 | Created | `auditcounter_django/accounts_receivable/services/setup/data_quality.py` |
| 1 | Modified | `auditcounter_django/accounts_receivable/services/setup/database.py` |
| 1 | Modified | `auditcounter_django/accounts_receivable/services/setup/pipeline.py` |
| 1 | Created | `auditcounter_django/accounts_receivable/static/accounting/setup/data-quality.js` |
| 1 | Modified | `auditcounter_django/accounts_receivable/static/accounting/setup/database.js` |
| 1 | Modified | `auditcounter_django/accounts_receivable/static/accounting/setup/power-query.js` |
| 1 | Modified | `auditcounter_django/accounts_receivable/static/accounting/setup/workspace.js` |
| 1 | Modified | `auditcounter_django/accounts_receivable/templates/accounting/setup.html` |
| 1 | Created | `auditcounter_django/accounts_receivable/test_data_quality.py` |
| 1 | Created | `auditcounter_django/db_extraction/services/schema_comparison.py` |
| 1 | Created | `docs/mvp-01-data-quality.md` |
| 1, 4 | Modified | `auditcounter_django/accounts_receivable/services/extraction.py` |
| 1, 4, 6, 7 | Modified | `auditcounter_django/accounts_receivable/services/database_updates.py` |
| 2 | Created | `auditcounter_django/accounts_payable/migrations/0014_suppliercreditnote_suppliercreditapplication_and_more.py` |
| 2 | Created | `auditcounter_django/accounts_payable/services/credits.py` |
| 2 | Created | `auditcounter_django/accounts_payable/test_credit_concurrency.py` |
| 2 | Created | `auditcounter_django/accounts_payable/test_credits.py` |
| 2 | Created | `auditcounter_django/accounts_receivable/frontend_tests/credits.test.cjs` |
| 2 | Created | `auditcounter_django/accounts_receivable/static/accounting/credits.js` |
| 2 | Created | `auditcounter_django/discrepancies/migrations/0004_alter_casetimelineevent_event_type.py` |
| 2 | Created | `docs/mvp-02-supplier-credits.md` |
| 2, 4–8 | Modified | `auditcounter_django/accounts_receivable/services/http.py` |
| 2, 5–8 | Created | `auditcounter_django/accounts_receivable/services/financial.py` |
| 2, 6 | Modified | `auditcounter_django/accounts_payable/models.py` |
| 2, 6 | Modified | `auditcounter_django/accounts_payable/services/reconciliation.py` |
| 2, 6, 7 | Modified | `auditcounter_django/accounts_receivable/ui.py` |
| 2–4, 7 | Modified | `auditcounter_django/accounts_receivable/static/accounting/workspace.js` |
| 2–7 | Modified | `auditcounter_django/discrepancies/services/timeline.py` |
| 2–8 | Modified | `auditcounter_django/accounts_receivable/services/pages.py` |
| 2–8 | Modified | `auditcounter_django/accounts_receivable/templates/accounting/workspace.html` |
| 2–8 | Modified | `auditcounter_django/discrepancies/models.py` |
| 3 | Created | `auditcounter_django/accounts_receivable/frontend_tests/settlement.test.cjs` |
| 3 | Created | `auditcounter_django/accounts_receivable/services/settlement.py` |
| 3 | Created | `auditcounter_django/accounts_receivable/test_settlement.py` |
| 3 | Created | `auditcounter_django/discrepancies/migrations/0005_alter_discrepancyfinding_finding_code.py` |
| 3 | Created | `docs/mvp-03-settlement.md` |
| 3, 6–8 | Modified | `auditcounter_django/discrepancies/services/investigation.py` |
| 3–8 | Modified | `auditcounter_django/discrepancies/services/__init__.py` |
| 4 | Created | `auditcounter_django/accounts_receivable/frontend_tests/duplicate-invoices.test.cjs` |
| 4 | Created | `auditcounter_django/discrepancies/migrations/0006_alter_casetimelineevent_event_type_and_more.py` |
| 4 | Created | `auditcounter_django/discrepancies/services/duplicate_invoices.py` |
| 4 | Created | `auditcounter_django/discrepancies/static/discrepancies/duplicate-invoices.js` |
| 4 | Created | `auditcounter_django/discrepancies/test_duplicate_invoices.py` |
| 4 | Created | `docs/mvp-04-duplicate-invoices.md` |
| 4 (selector-scoped test harness) | Modified | `auditcounter_django/accounts_receivable/frontend_tests/record-delete.test.cjs` |
| 4, 8 | Modified | `auditcounter_django/discrepancies/templates/discrepancies/dashboard.html` |
| 4, 8 | Modified | `auditcounter_django/discrepancies/urls.py` |
| 4, 8 | Modified | `auditcounter_django/discrepancies/views.py` |
| 5 | Created | `auditcounter_django/accounts_receivable/frontend_tests/claims.test.cjs` |
| 5 | Created | `auditcounter_django/accounts_receivable/static/accounting/claims.js` |
| 5 | Created | `auditcounter_django/discrepancies/migrations/0007_alter_casetimelineevent_event_type_supplierclaim_and_more.py` |
| 5 | Created | `auditcounter_django/discrepancies/services/claims.py` |
| 5 | Created | `auditcounter_django/discrepancies/test_claim_concurrency.py` |
| 5 | Created | `auditcounter_django/discrepancies/test_claims.py` |
| 5 | Created | `docs/mvp-05-supplier-claims.md` |
| 6 | Created | `auditcounter_django/accounts_payable/migrations/0015_supplierstatement_supplierstatementevaluation_and_more.py` |
| 6 | Created | `auditcounter_django/accounts_payable/services/statements.py` |
| 6 | Created | `auditcounter_django/accounts_payable/test_statement_concurrency.py` |
| 6 | Created | `auditcounter_django/accounts_payable/test_statements.py` |
| 6 | Created | `auditcounter_django/accounts_receivable/frontend_tests/statements.test.cjs` |
| 6 | Created | `auditcounter_django/accounts_receivable/static/accounting/statements.js` |
| 6 | Created | `auditcounter_django/discrepancies/migrations/0008_alter_casetimelineevent_event_type_and_more.py` |
| 6 | Created | `docs/mvp-06-statements.md` |
| 6–8 | Modified | `auditcounter_django/discrepancies/presentation.py` |
| 7 | Created | `auditcounter_django/accounts_receivable/frontend_tests/deductions.test.cjs` |
| 7 | Created | `auditcounter_django/accounts_receivable/migrations/0013_customerdeduction_deductionapplication_and_more.py` |
| 7 | Modified | `auditcounter_django/accounts_receivable/models.py` |
| 7 | Created | `auditcounter_django/accounts_receivable/services/deductions.py` |
| 7 | Modified | `auditcounter_django/accounts_receivable/services/reconciliation.py` |
| 7 | Created | `auditcounter_django/accounts_receivable/static/accounting/deductions.js` |
| 7 | Created | `auditcounter_django/accounts_receivable/test_deduction_concurrency.py` |
| 7 | Created | `auditcounter_django/accounts_receivable/test_deductions.py` |
| 7 | Created | `auditcounter_django/discrepancies/migrations/0009_alter_casetimelineevent_event_type_and_more.py` |
| 7 | Created | `docs/mvp-07-deductions.md` |
| 8 | Created | `auditcounter_django/accounts_receivable/frontend_tests/analytics.test.cjs` |
| 8 | Created | `auditcounter_django/accounts_receivable/static/accounting/root-causes.js` |
| 8 | Created | `auditcounter_django/discrepancies/migrations/0010_findingrootcause.py` |
| 8 | Created | `auditcounter_django/discrepancies/services/analytics.py` |
| 8 | Created | `auditcounter_django/discrepancies/static/discrepancies/analytics.js` |
| 8 | Created | `auditcounter_django/discrepancies/test_analytics.py` |
| 8 | Created | `auditcounter_django/discrepancies/test_analytics_concurrency.py` |
| 8 | Created | `docs/mvp-08-analytics.md` |
| All milestones | Created | `docs/mvp-file-inventory.md` |
| All milestones | Created | `docs/mvp-implementation-report.md` |

## Per-app README documentation

Added on the user's follow-up documentation request. Existing operating guides are
retained; the root README provides the app documentation index.

| Change | File |
|---|---|
| Modified | `README.md` |
| Modified | `auditcounter_django/accounts_payable/README.md` |
| Modified | `auditcounter_django/accounts_receivable/README.md` |
| Modified | `auditcounter_django/db_extraction/README.md` |
| Created | `auditcounter_django/discrepancies/README.md` |
| Created | `auditcounter_django/document_extraction/README.md` |
| Modified | `auditcounter_django/encoder/README.md` |
| Modified | `auditcounter_django/router/README.md` |
| Created | `auditcounter_django/sku_matching/README.md` |

Total implementation/documentation files including app README updates: 97.
