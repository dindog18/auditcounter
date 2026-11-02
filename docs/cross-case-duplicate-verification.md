# Cross-case duplicate verification

Exact identity is `(AP/AR module, supplier/customer ID, currency, sorted PO ID set, sorted DR ID set, sorted invoice ID set)`. Dates, notes, workflow status and financial amounts are excluded. AP and AR are separate namespaces. Existing request validation still rejects malformed/repeated document IDs and requires at least one invoice; empty PO/DR sets are valid.

## Backend and concurrency

`records.save_case` retains its existing atomic transaction, account lock, case lock, source-document locks, membership validation and revision check. After validation, it checks duplicates before deleting matches, saving the case or changing memberships. Same-account/same-currency candidates are narrowed by one selected invoice (or another nonempty collection for diagnostic callers). Three prefetched memberships support full set comparison without per-case membership queries. Editing excludes the current case. The deterministic first existing duplicate is reported.

DuplicateCaseError uses the existing conflict convention and returns HTTP 409 with message, existing_case_id, existing_case_reference and reverse-generated existing_case_url. The lookup is inside the same account lock and transaction as creation, so concurrent same-account requests serialize. No new lock, schema, financial calculation or reconciliation rule was introduced. Direct ORM/M2M/SQL writes outside save_case can bypass this service-level safeguard; historical diagnostics remain available.

## Frontend

The existing create/edit form compares selected documents with its existing same-module/account/currency case state. It shows linked exact or partial overlap warnings with overlapping PO/DR/invoice references. Warnings do not disable saving or alter selections. The backend remains authoritative. Conflict errors retain the form draft and show a link to the existing case without redirecting. References are escaped; conflict links are constructed from the local route and validated numeric ID. The API error client retains existing extraction-log metadata and now carries the duplicate case identity. Versioned script assets ensure existing browsers load the new handling.

## Historical diagnostic

Run `python auditcounter_django/manage.py verify_duplicate_cases` (optionally `--module ap` or `--module ar`). Output is JSON lines containing module, case IDs, party ID, currency and document membership. `historical_duplicates(mode)` is also callable directly. Both are read-only; no merges, deletes, financial adjustments, findings or investigation changes occur. Legacy duplicates remain stored and usable by existing workflows.

## Created files

- `auditcounter_django/accounts_receivable/services/case_duplicates.py`: normalized membership, narrowed candidate lookup, exact and partial overlap detection, conflict metadata, historical groups.
- `auditcounter_django/accounts_receivable/test_case_duplicates.py`: shared AP/AR functional tests and PostgreSQL TransactionTestCase concurrency tests with separate connections.
- `auditcounter_django/accounts_receivable/frontend_tests/case-duplicates.test.cjs`: ordering, partial-overlap, scope and nonmutation tests.
- `auditcounter_django/discrepancies/management/commands/verify_duplicate_cases.py`: read-only diagnostic.
- `docs/cross-case-duplicate-verification.md`: implementation/verification notes.

## Modified files

- `auditcounter_django/accounts_receivable/services/records.py`: duplicate check in save_case before destructive membership edits.
- `auditcounter_django/accounts_receivable/services/http.py`: structured duplicate conflict response.
- `auditcounter_django/accounts_receivable/static/accounting/api.js`: preserve duplicate error identity.
- `auditcounter_django/accounts_receivable/static/accounting/workspace.js`: advisory overlap helper, form warnings and conflict link.
- `auditcounter_django/accounts_receivable/templates/accounting/workspace.html`: script version updates.
- `auditcounter_django/accounts_receivable/frontend_tests/api-errors.test.cjs`: conflict metadata/controls regression.

Earlier uncommitted unified-dashboard changes and existing output directories were preserved.

## Executed verification

- Full Django suite from auditcounter_django using the existing virtualenv Python, `manage.py test --noinput`: **514 run, 506 passed, 8 PostgreSQL-only skips**.
- PostgreSQL, `manage.py test accounts_receivable accounts_payable discrepancies --noinput`: **264 passed, no skips**. Includes concurrent identical creation (one saved/one conflict), concurrent distinct overlapping creation (both saved), and conflicting edits (one saved/one stale conflict), each exercised in AP and AR. Existing allocations/activity remain intact on rejected writes; no historical duplicate groups remain after races.
- Node frontend regression suite (accounting and router): **75 passed**.
- Django check, migration drift check, JavaScript syntax and git diff whitespace checks passed. No migrations or dependencies added.
- Functional coverage includes unordered IDs, distinct invoices, multiple invoices, shared orders/receipts, empty PO/DR sets, unchanged editing, failed-edit rollback for matches/findings/evidence/investigation/activity, structured API errors and read-only historical diagnostics.
- Browser QA: connected Playwright (Browser plugin unavailable), loopback-only server, disposable SQLite DB, mobile viewport. Exact duplicate returned 409, displayed “Open AP-1”, retained two selected DRs and the written note, and stayed on the form. Selecting one DR showed a partial warning and created the distinct case successfully. Expected HTTP 409 network-console entries occurred. An initially cached API asset lacked the new link; versioned assets fixed it. Screenshot: `/private/tmp/case-duplicate-conflict.png` outside the repository.

No unresolved new test failures, unrelated regressions or environment problems remained. Matching, quantity capacity checks, SKU matching, financial evaluation, fingerprints, findings/evidence persistence and human investigation transitions were not changed. No authentication, ERP writes, commits, pushes or pull requests were introduced. No historical repair or automatic merging is provided. Advisory browser warnings may be stale after another client saves; locked backend validation remains authoritative.
