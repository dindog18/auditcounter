# Persistent, explainable discrepancy findings

AP and AR now share a `discrepancies` application. Existing source records, matching services, financial aggregation, and public `(status, Decimal amount)` reconciliation contract are retained. Evaluation adds `discrepancy_findings` to its read-only result; a separate synchronization service persists those findings and supporting observations.

## Database and deployment

`discrepancies/migrations/0001_initial.py` creates two models:

- **DiscrepancyFinding:** exactly one protected AP/AR case FK; stable fingerprint; code, severity, open/cleared status, summary, expected/actual JSON, signed nullable Decimal amount, currency, rule version, stable identity, details, first/last detection and clearance timestamps.
- **FindingEvidence:** finding FK, content hash, source model/record/line identity, document/database FKs, ERP record key, provenance, observed financial fields, finding state at capture, and capture timestamp.

Database constraints enforce exactly one case, unique fingerprint within each AP/AR case, consistent cleared status/timestamp, and unique evidence snapshot within each finding. Monetary storage supports 38 digits with 8 decimal places. No accounting source model or source value is migrated or recreated.

Apply the migration before running the updated application:

```sh
python auditcounter_django/manage.py migrate
```

Existing cases can be backfilled explicitly:

```sh
python auditcounter_django/manage.py reconcile_findings
python auditcounter_django/manage.py reconcile_findings --mode ap --case 42
```

Backfill uses the same case refresh service, is idempotent, and updates reconciliation results/findings without changing financial source values. Schema and backfill verification used disposable SQLite and PostgreSQL databases; the existing workspace database was not migrated automatically.

## Finding rules

| Code | Evaluation and evidence |
| --- | --- |
| `QUANTITY_SHORTAGE` | Invoiced quantity exceeds valid allocated receiving support. Captures invoiced/supported quantities, SKU/UOM, PO, receipt, invoice and allocation observations. A coherent invoice line's value, including discount/tax, is prorated for a potential unsupported amount when some support is verified. Awaiting matching is information-only, with no invented finding amount. |
| `PRICE_VARIANCE` | Groups supported allocations by invoice line and PO line. Records signed unit-price variance and discount/tax components; the finding amount is net variance including those components. All supporting receipts and allocation quantities are captured. Aggregate tolerance breaches still produce specific findings even if individual lines are below tolerance. Existing supported header-charge differences also use this code with an `other_charges` component. |
| `LINE_TOTAL_MISMATCH` | Recorded line total differs from the shared rounded quantity × price − discount + tax calculation. Stores the actual line fields and expected/recorded totals. |
| `HEADER_TOTAL_MISMATCH` | Recorded header total differs from component arithmetic or summed lines. One finding retains both comparisons and all required header/line observations. |
| `MISSING_PO` | An invoice line lacks compatible, identified PO evidence in the case. An information finding with no monetary amount. |
| `MISSING_DR` | An invoice line lacks compatible, identified receiving evidence in the case. An information finding with no monetary amount. |

Findings explain potential discrepancies, not confirmed recoverable claims. Inconsistent source amounts do not generate invented quantity/price exposure. A fully supported partial invoice does not become a financial claim because its PO remains open.

Finding amounts are **not additive**. Header and line findings can explain overlapping manifestations of one source error. The existing evaluator remains authoritative for the case aggregate, including its per-document arithmetic deduplication. The frontend never sums finding amounts. Clearance retains the last discrepant values, which are labelled historical.

Only the six initial persistent codes are implemented. Other existing validation notices, such as invalid/void source status, remain available through the existing live evaluation and exception display; no fraud or claims rules were added.

## Identity, evidence and history

Finding fingerprints hash case scope/ID, finding code and stable source identity. Changing prices, quantities, monetary amounts, summaries or detection times does not change the finding identity.

Evidence captures only bounded accounting fields: document reference/date/party/currency/status and financial components; line number/SKU/UOM/quantities/pricing/discount/tax/total; allocation line relationships and matched quantity; uploaded-document identity/name; database source/catalog/table identity and external record key. Allocation evidence uses its logical invoice/PO/DR triple and case provenance. Files, credentials, OCR coordinates and ERP datasets are not copied.

Every evidence row includes the finding's expected/actual values, amount, explanation, status, rule version and details at capture. Content-addressed snapshots deduplicate unchanged observations and finding states. Changed observations create new snapshots without overwriting old values. Repeated reconciliation updates latest detection time without inserting identical evidence.

When a finding clears, available corrected source observations and current allocations are captured too. Old evidence remains. Deleted source records lose their live link but retain identifiers and observations. Uploaded-document/database FKs may become null on deletion; their original identity remains in captured provenance. Findings/cases with retained history are protected from destructive parent deletion.

A recurring discrepancy reopens the same fingerprint, preserves first detection, updates latest detection and clears the current `cleared_at`. Captured cleared observations remain accessible. This is source-observation history, not a full workflow-event log.

## Synchronization and integration

`refresh_transaction()` locks the case and evaluates current evidence, synchronizes findings and updates reconciliation status/amount inside one atomic transaction. New findings are created, existing ones updated, absent ones marked cleared. Synchronization cannot recursively trigger source refreshes.

The existing model refresh pathways cover instance matching changes, source header/line saves and membership changes. Queryset deletion signals cover match/line removals that bypass instance delete methods. Shared deferred refresh contexts ensure case creation/editing, allocation replacement, reviewed extraction saves and database-update batches persist only their final state. Failure in evidence capture rolls the entire operation back, including matching allocations.

Calculations, previews, Auto Match suggestion generation and GET page serialization do not persist findings. Explicit POST `recalculate/<case_id>/` actions in both existing accounting APIs retain CSRF, POST-only handling and revision validation. No login is required or introduced.

## Frontend

The existing case detail page contains **Discrepancy Findings**, with open findings first and cleared history retained. It displays code, severity, status, explanation, expected/actual values, signed or historical difference, currency, rule version and first/latest/clearance dates.

Expandable evidence/history shows each captured observation separately, original accounting record/document/database links, ERP keys and captured financial fields. Nested finding-at-capture details allow independent review of old comparisons. Existing record views and document preview routes are reused. **Recalculate findings** explicitly refreshes and reloads the case. No assignment, approval or manual claims-resolution workflow was added.

## Exact file/function inventory

| File | Added or changed |
| --- | --- |
| `auditcounter_django/discrepancies/__init__.py` | App package |
| `auditcounter_django/discrepancies/apps.py` | `DiscrepanciesConfig.ready` registers deletion hooks |
| `auditcounter_django/discrepancies/models.py` | `DiscrepancyFinding`, `FindingEvidence`, database integrity constraints |
| `auditcounter_django/discrepancies/migrations/__init__.py` | Migration package |
| `auditcounter_django/discrepancies/migrations/0001_initial.py` | New schema and constraints |
| `auditcounter_django/discrepancies/evaluation.py` | `json_value`, `finding`, `source_evidence`, `allocation_evidence`, `compatible_evidence` |
| `auditcounter_django/discrepancies/services.py` | `build_finding_fingerprint`, `synchronize_findings`, `capture_finding_evidence`, `clear_resolved_findings`, `current_evidence`, `refresh_transaction`, `defer_reconciliation`, hash/case helpers |
| `auditcounter_django/discrepancies/signals.py` | Queryset match/line deletion refresh integration |
| `auditcounter_django/discrepancies/presentation.py` | `serialize_findings`, safe original-source URL generation |
| `auditcounter_django/discrepancies/management/__init__.py`, `management/commands/__init__.py` | Management command packages |
| `auditcounter_django/discrepancies/management/commands/reconcile_findings.py` | Explicit idempotent backfill command |
| `auditcounter_django/discrepancies/tests.py` | Database constraints and stable fingerprint tests |
| `auditcounter_django/discrepancies/test_support.py` | Shared AP/AR persistence, evidence, source-change, clear/reopen, rollback, batch, API, tolerance and backfill scenarios |
| `auditcounter_django/discrepancies/test_concurrency.py` | PostgreSQL concurrent refresh/uniqueness test |
| `auditcounter_django/auditcounter_django/settings.py` | Registers the shared discrepancies app |
| `auditcounter_django/accounts_payable/models.py`, `accounts_receivable/models.py` | `Transaction.refresh_reconciliation_status` delegates to atomic synchronization |
| `auditcounter_django/accounts_payable/services/reconciliation.py`, `accounts_receivable/services/reconciliation.py` | Documents read-only structured evaluation; public tuple contract preserved |
| `auditcounter_django/accounts_receivable/services/evaluation.py` | Generates six structured finding types and evidence alongside existing financial calculations |
| `auditcounter_django/accounts_receivable/services/amounts.py` | Reusable `expected_line_total`; retains Decimal precision and rounding in `line_amount_difference` |
| `auditcounter_django/accounts_receivable/services/records.py` | Defers refresh in `save_case` and `save_matches` until final batch state |
| `auditcounter_django/accounts_receivable/services/extraction.py` | Defers refresh during `save_result` |
| `auditcounter_django/accounts_receivable/services/database_updates.py` | Atomic/deferred `write_candidate` and deferred database `apply` batch |
| `auditcounter_django/accounts_receivable/services/http.py` | Existing API `perform`: explicit recalculation action |
| `auditcounter_django/accounts_receivable/services/pages.py` | `workspace_state` serializes persisted findings without writes |
| `auditcounter_django/accounts_receivable/static/accounting/workspace.js` | `caseDetail`, new `discrepancyFindings` evidence/history rendering and recalculation control |
| `auditcounter_django/accounts_payable/tests.py`, `accounts_receivable/tests.py` | Shared findings scenarios executed against both model sets |
| `auditcounter_django/accounts_payable/test_migrations.py` | Migration test restores all leaf migrations, including the new dependent app |
| `auditcounter_django/accounts_receivable/frontend_tests/findings.test.cjs` | Findings/history/source links, escaping, evidence-gap amounts, legacy cases and recalculation tests |
| `docs/persistent-discrepancy-findings.md` | Implementation/deployment handoff |

Earlier partial-delivery and Auto Match changes remain in the working tree and are preserved.

## Verification

Final backend execution:

| Check | Result |
| --- | --- |
| Full Django suite, run from Django project directory | 420 run: 417 passed, 3 PostgreSQL-only skips |
| Findings + AP/AR suite on PostgreSQL 17 | 213 passed, no skips |
| Targeted new finding scenarios/integrity tests | 29 run: 28 passed, 1 PostgreSQL-only skip |
| Existing/new frontend Node suite | 52 passed |
| `manage.py check` | No issues |
| `makemigrations --check --dry-run` | No changes detected |
| JavaScript syntax and `git diff --check` | Passed |

PostgreSQL coverage includes concurrent refresh creating one finding with unique evidence, existing manual over-allocation contention and stale Auto Match confirmation. Migration compatibility is included in the full suite.

Browser QA used disposable fixture data at `http://127.0.0.1:8765`, desktop 1440×1000 and mobile 390×844. Browser plugin was unavailable, so connected Playwright was used. Page identity/content, absence of overlays, console health, responsive layout, evidence expansion, source-record navigation, recalculation/reload and retained cleared history were checked. The quantity example displayed 98 supported versus 100 invoiced units and PHP 36,000 requiring investigation. Correcting the price fixture cleared its existing finding without deleting history and returned the case aggregate to zero. No console errors were observed.

## Remaining limitations and compatibility

- Direct SQL, `QuerySet.update` and bulk writes that bypass existing save hooks require explicit recalculation/backfill. Normal supported source and matching services synchronize automatically.
- Snapshots preserve observed structured values and references; they do not back up original uploaded files or query external ERP systems.
- Clearance means the rule no longer detects the discrepancy. It is not financial settlement or proof of supplier liability; removal of evidence can also change which findings apply.
- Existing source-protection rules, monetary field limits, manual matching, partial deliveries, Auto Match, payments, extraction and routing remain in force and passed regression tests.
- No authentication, organization isolation, AI, fraud rules, supplier communication, approval/assignment workflows, ERP write-back, new frontend framework or dependency was introduced.
- Work remains in the existing `codex/matching-improvments` checkout. No push, merge or PR was performed.

The disposable Django and PostgreSQL verification services were stopped after QA. Browser/log artifacts were kept outside the repository. The existing workspace database and pre-existing output folders were not changed.
