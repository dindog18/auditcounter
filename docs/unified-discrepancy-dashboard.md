# Unified AP/AR discrepancy dashboard

The shared read-only dashboard lives at `/discrepancies/`. It reuses AP/AR Transaction records, DiscrepancyFinding and CaseInvestigation, and links directly to the existing accounting case details. No models, migrations, authentication, dependencies, reconciliation rules, review transitions, fingerprint rules, ERP writes or AI calls were added.

## Query design

`discrepancies.services.dashboard.case_query` normalizes the two transaction models using ORM annotations and correlated finding subqueries. The list uses SQL UNION ALL, deterministic ordering with null dates last and module/ID tie breaks, an SQL count and a bounded SQL page. The default is 25 cases per page; the maximum is 100. A dashboard identity is `ap:<transaction id>` or `ar:<transaction id>`, so matching numeric IDs remain separate. List reads execute two queries, independent of result size. Summaries execute two queries per selected module: metrics and grouped financial amounts. Neither endpoint loads document lines, evidence snapshots or activity history.

Include cases with any persisted finding (open or cleared), any investigation, or reconciliation status `exception`. An ordinary partial delivery with none of these is excluded. Historical cases remain visible. Highest severity is the highest across all findings, including cleared historical findings; the UI explicitly filters by highest severity. Finding counts show open and total counts separately in the API. No investigation is represented by `not_started`.

Reconciliation, finding and investigation status remain separate. Resolved investigations may still have exceptions and monetary differences. Renewed review is the existing investigation `review_required` flag. Needs review counts investigations in `needs_review` plus unstarted cases with open findings or a reconciliation exception. Investigating, waiting and resolved counts use their existing workflow statuses. Renewed review can overlap another metric.

Financial totals sum only persisted Transaction.total_discrepancy_amount, once per case, grouped by module and currency. Finding amounts are never summed. Unknown currencies remain a separate blank-currency group; missing serializer amounts remain null. These are differences requiring investigation, not confirmed losses or recovered amounts. Dashboard results reflect persisted state; existing refresh/recalculate pathways remain responsible for accounting updates.

## Routes and filters

- GET `/discrepancies/`: shared-template dashboard.
- GET `/discrepancies/api/cases/`: `results`, `count`, `page`, `page_size`, `pages`.
- GET `/discrepancies/api/summary/`: filtered metrics and `financial` module/currency groups.

Both API endpoints accept `module`, `reconciliation_status`, `investigation_status`, `severity`, `currency`, `q`, `date_from`, `date_to`, `sort`, `page`, `page_size`. Empty filters mean all. Search matches supplier/customer name or the AP-/AR- reference. Dates are inclusive; currency requires three uppercase letters. Invalid, unknown or repeated parameters return JSON HTTP 400. Unsupported HTTP methods return 405. Beyond-last pages return an empty result list with accurate counts.

Sort choices: transaction_date, -transaction_date (default), created_at, -created_at, party_name, -party_name, discrepancy_amount, -discrepancy_amount, reconciliation_status, investigation_status, highest_severity, open_findings_count, reference. Financial sorting across currencies is numeric ordering only, without currency conversion.

The UI supports explicit Apply/Reset, server pagination, loading, empty and error states, URL filter persistence, cancellation of superseded requests, and original case navigation. Amounts are rendered from backend strings without client financial calculations. The existing Financial Operations sidebar has an active Discrepancies entry.

## Complete file inventory

Created:
- `auditcounter_django/discrepancies/services/dashboard.py`: filter validation, shared annotated queries, pagination, metrics and financial aggregation.
- `auditcounter_django/discrepancies/views.py`: GET-only template and JSON views.
- `auditcounter_django/discrepancies/urls.py`: namespaced dashboard/API routes.
- `auditcounter_django/discrepancies/templates/discrepancies/dashboard.html`: shared-layout filters, cards, table and pagination.
- `auditcounter_django/discrepancies/static/discrepancies/dashboard.js`: API loading, rendering, search/filter/sort/page interactions and error handling.
- `auditcounter_django/discrepancies/static/discrepancies/dashboard.css`: responsive additions to existing accounting styles.
- `auditcounter_django/discrepancies/test_dashboard.py`: aggregation, collision, financial, filter, validation, pagination, missing metadata, read-only/query-budget and existing detail-link tests.
- `docs/unified-discrepancy-dashboard.md`: implementation and verification notes.

Modified:
- `auditcounter_django/discrepancies/presentation.py`: add serialize_case_summary; existing finding and investigation serializers retained.
- `auditcounter_django/auditcounter_django/urls.py`: include shared discrepancy URLs.
- `auditcounter_django/document_extraction/templates/document_extraction/base.html`: Financial Operations navigation link and active state.

## Verification

Full Django suite: 501 tests run, 496 passed, 5 PostgreSQL-only skips. Command: from auditcounter_django, run the existing virtualenv Python with `manage.py test --noinput`.
PostgreSQL regression: `manage.py test discrepancies accounts_payable accounts_receivable --noinput`: 251 passed, no skips.
Existing frontend tests: `node --test auditcounter_django/accounts_receivable/frontend_tests/*.test.cjs auditcounter_django/router/frontend_tests/*.test.cjs`: 70 passed.
Django check, migration drift check, JavaScript syntax check and git diff whitespace check passed. No migrations needed.

Initial PostgreSQL failures were in the new test fixtures/guard: assuming generated IDs and rejecting PostgreSQL's parenthesized SELECT UNION as a non-read. Both were corrected, retaining the read-only guard and using deliberately identical explicit AP/AR IDs. Final PostgreSQL regressions passed. No unrelated failures or missing dependencies were found.

Browser QA used connected Playwright because the Browser plugin was unavailable. Loopback-only QA server and disposable SQLite database; desktop 1440×1000 and mobile 390×844. Verified title, meaningful content, active sidebar, search/empty state, reset, correct case navigation, financial cards and responsive layout. Mobile document width equals viewport width (390px). Intentionally aborted a summary request to verify error display, then retried successfully. That simulated failure produced an expected network-console entry; ordinary navigation had no application errors. Screenshots are outside the repository at `/private/tmp/discrepancy-dashboard-desktop.png` and `/private/tmp/discrepancy-dashboard-mobile.png`.

Limits: persisted-state monitoring with explicit refresh through existing case workflows; no live currency conversion, new investigation detail view, background workers or recovery analytics. Large-production-volume load testing is outside this MVP. No commits, pushes or pull requests were made.
