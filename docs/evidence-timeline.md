# Evidence Timeline

The existing AP/AR case detail page now combines automatic accounting observations, finding lifecycle events, preserved evidence, linked document/payment references and existing investigation activity. It uses existing case workflows and calculations; no authentication, AI, ERP writes, dependencies, broker or background worker was added.

## Storage and identity

`CaseTimelineEvent` is new because membership, logical matching and source transitions were not previously retained as an automatic journal. Exactly one protected AP/AR case FK is required. Conditional uniqueness enforces one event key per case. Both case FKs have `(case, recorded_at, id)` indexes. Model saves/deletes and the existing append-only queryset conventions reject overwriting/deleting history. As with CaseActivity, direct SQL/private ORM APIs are outside this supported write contract.

`discrepancies.0003_casetimelineevent` creates only the new table, constraints and indexes. It does not backfill or modify old financial records. Apply with `python auditcounter_django/manage.py migrate`.

`record_transition` runs atomically, locks the case, validates bounded structured JSON, type/source/description and timezone-aware business timestamps, and compares the latest meaningful source state. Keys incorporate the predecessor event, so A → B → A is preserved. Explicit idempotency keys deduplicate retries; reuse with different evidence is rejected. Refresh-only clocks and recreated allocation row IDs are excluded. Decimal amounts are serialized as strings. Recorded details contain whitelisted accounting observations, not credentials, PDFs, full ERP datasets or LLM prompts. Product descriptions in new automatic source observations are bounded to 2,000 characters; original source records and existing evidence snapshots remain intact.

## Event categories and sources

- **Documents:** case_created, documents_changed, source_changed; linked document business-date references.
- **Matching:** matches_changed, using sorted logical invoice/PO/DR/quantity/status tuples.
- **Discrepancies:** finding_detected, finding_changed, finding_cleared, finding_reopened, reconciliation_changed. Finding fingerprints and financial formulas remain unchanged.
- **Payments / Credits:** payments_changed and linked payment references. Observations include allocation components, payment amount/status and invoice settlement status, currency and dates. Allocation is not proof of recovery. This branch has no credit-note/application model or service; no parallel credit workflow was created.
- **Investigations:** original CaseActivity rows (opened, note, status change, review, resolution, reopening, evidence changed). They are never copied into the automatic journal. Staff labels remain explicitly unverified.

FindingEvidence is grouped under relevant finding events with original captured values, finding snapshots, hashes, provenance and available accounting/document/database links. Existing source-link serialization is reused and cached per source reference. Historical evidence is retained after later source changes.

## Write integration

- `records.save_case`: captures creation inside the existing transaction. Its transient pending reset is excluded from reconciliation-change history by preserving and consuming the pre-operation state once.
- Existing deferred `refresh_transaction`: captures final membership, logical matches, whitelisted linked source headers/lines and relevant payment state. This covers save_matches, source model saves/deletes and approved database imports through their existing refresh callbacks.
- `synchronize_findings` / `clear_resolved_findings`: record first detection, material changes, clears and reopens after evidence capture; unchanged recalculation does not append events.
- `database_updates.apply` already uses atomic/deferred reconciliation. Its existing `write_candidate` source saves feed the same observation path, once final source changes are available. No provider transport or external SQL was changed.
- `save_allocations` defers observations until complete replacement. AP/AR payment saves and invoice payment-status refreshes cover direct allocation saves/deletes, settlement status, supporting payment changes and reversals. These payment paths reuse the account-first lock before payment/invoice/case locks to avoid introducing an inverted lock order.
- All event writes share the accounting transaction. Failure rolls back both accounting changes and events.

## Read API and history

GET `/discrepancies/api/cases/<ap|ar>/<case_id>/timeline/`

Query parameters: `category` (empty/all, documents, matching, discrepancies, payments, investigations), `page` (1–1,000,000), `page_size` (1–100, default 25). Unknown/repeated parameters or invalid filters return 400; missing cases return 404; other methods return 405.

Response: `case` (module, id, reference), `results`, `page`, `page_size`, `total`, `historyMayBeIncomplete`. Events include stable ID (`event:`, `activity:`, `legacy:` or business-record prefix), type/category/title/description, occurredAt, recordedAt, source reference/link, evidence and before/after details. Ordering is descending observation time with a deterministic ID tie break. Business dates are displayed separately; date-only references are not converted into invented times.

Reads do not invoke evaluation/persistence. Existing genuine timestamps and snapshots remain accessible when a case has no automatic events. Older findings use clearly marked historical lifecycle references, without assigning current explanations to an earlier observation. New baseline observations have recorded time now and explicitly say baseline; no fabricated backdated rows are inserted. The feature cannot reconstruct every transition that occurred before tracking existed.

The merger is scoped to one case and filters automatic event queries by category. It currently merges that case's history in memory before slicing the page; very large single-case histories may eventually need SQL-union/cursor pagination and separate evidence pagination. No high-level event is emitted for every unchanged evidence capture.

## Frontend

The shared caseDetail panel replaces the standalone Investigation History display with Evidence Timeline. Investigation forms and existing controls remain intact. Category filtering, expandable evidence and before/after details, load-more, loading, empty and retryable error states use the existing UI helpers. Source text and JSON are escaped. Script and stylesheet versions were updated. Timeline data is fetched separately from existing accounting workspace state.

## Complete file inventory

Created:
- `auditcounter_django/discrepancies/services/timeline.py`
- `auditcounter_django/discrepancies/migrations/0003_casetimelineevent.py`
- `auditcounter_django/discrepancies/test_timeline.py`
- `auditcounter_django/discrepancies/test_timeline_concurrency.py`
- `auditcounter_django/accounts_receivable/frontend_tests/timeline.test.cjs`
- `docs/evidence-timeline.md`

Modified:
- `auditcounter_django/discrepancies/models.py`: CaseTimelineEvent and constraints.
- `auditcounter_django/discrepancies/services/__init__.py`: material finding/reconciliation transitions and final source observations.
- `auditcounter_django/discrepancies/presentation.py`: common timeline case reference.
- `auditcounter_django/discrepancies/views.py`, `urls.py`: validated GET-only timeline endpoint.
- `auditcounter_django/accounts_receivable/services/records.py`: creation, real pre-operation state, complete allocation observation/defer integration.
- `auditcounter_django/accounts_payable/models.py`, `accounts_receivable/models.py`: account-first payment/settlement capture hooks.
- `auditcounter_django/accounts_receivable/static/accounting/workspace.js`, `workspace.css`: unified timeline rendering and controls.
- `auditcounter_django/accounts_receivable/templates/accounting/workspace.html`: asset versions.
- `auditcounter_django/accounts_receivable/frontend_tests/findings.test.cjs`: isolate the existing recalculation test from the new independent panel; dedicated timeline tests exercise that panel.

## Verification

Final full Django run: **527 tests, 516 passed, 11 PostgreSQL-only skips**. PostgreSQL AP/AR/discrepancy regression: **277 passed, no skips**. Frontend regression: **78 passed**. Final targeted timeline tests: **10 passed**. System checks, migration drift, JavaScript syntax and whitespace checks passed. The new migration applied successfully to disposable SQLite and PostgreSQL test databases. No unresolved new or unrelated regression failures remained.

Commands use the existing virtualenv:
- From auditcounter_django: `../.venv/bin/python manage.py test --noinput`.
- PostgreSQL: set DB_ENGINE=django.db.backends.postgresql and the disposable local DB settings, then `python auditcounter_django/manage.py test discrepancies accounts_payable accounts_receivable --noinput`.
- `node --test auditcounter_django/accounts_receivable/frontend_tests/*.test.cjs auditcounter_django/router/frontend_tests/*.test.cjs`.
- `python auditcounter_django/manage.py check` and `makemigrations --check --dry-run`.

Tests cover AP/AR lifecycle/idempotency, clear/reopen cycles, rollback, append-only protection, logical matching snapshots, payment allocation/reversal/removal, legacy activity without automatic rows, scoped read-only GETs, filters/pagination and links. PostgreSQL tests use independent connections for duplicate event attempts, matching updates and simultaneous payment allocation/matching; existing concurrent case-edit, duplicate prevention and finding tests also run. Frontend tests cover both modes, safe escaping, evidence links, filters, pagination, empty/error states and retry.

Browser QA uses connected Playwright (Browser plugin unavailable), loopback-only server and a disposable migrated SQLite database. Verified historical case display, category empty state, explicit recalculation followed by newly observed matching baseline, expandable values, no duplicate standalone Investigation History, desktop 1440×1000 and mobile 390×844 layout. Mobile width remained 390px. Screenshots are outside the repo: `/private/tmp/evidence-timeline-desktop.png`, `/private/tmp/evidence-timeline-mobile.png`. No live ERP or external LLM was contacted.

No credit-note/N-way credit integration exists to hook into. Direct SQL or bulk updates outside existing refresh pathways require explicit recalculation to observe changes. Historical reconstruction is incomplete by design. No automatic recovery classification, accounting correction or new investigation workflow is provided. No commits or pushes were made.
