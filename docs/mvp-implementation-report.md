# AuditCounter MVP implementation and verification

Baseline: `1431943a321c16077e9968db60dfa77c0abab370` (Evidence Timeline), on the existing
local `codex/matching-improvments` checkout. No reset, migration rewrite, deployment or external ERP write was performed during implementation. The user subsequently requested a commit and push with app README updates. Pre-existing `output/` and
`outputs/` remain untouched. This report and [the exact file inventory](mvp-file-inventory.md)
cover the complete patch.

## Status

| Milestone | Status | Implemented behavior |
|---|---|---|
| 1. Mapping/data quality | Implemented | Schema-drift gates, bounded validation explanations, approved mapping corrections, signed source review receipts |
| 2. Supplier credits | Implemented | Manual credits, evidence verification, partial applications, shared balance locks, explicit reversals |
| 3. Explainable N-way settlement | Implemented | Independent document matching and payment/credit/adjustment settlement, supported amounts and reasons |
| 4. Duplicate invoices | Implemented | Bounded deterministic candidates, independent review, historical evidence, no automatic deletion |
| 5. Supplier claims | Implemented | Reviewed findings/evidence, copyable drafts, manual correspondence, accepted amounts, verified closure and renewed-review flags |
| 6. Supplier statements | Implemented | Structured CSV input, ledger references, ambiguity review, missing credits, balance checks, source-change refresh |
| 7. AR deductions | Implemented | Dispute entry, review, explicit accepted applications, reversals, collectible balance and history |
| 8. Root-cause analytics | Implemented | Human attribution with evidence, current-basis validation, filtered aggregates and separate financial measures |

See `mvp-01-data-quality.md` through `mvp-08-analytics.md` for models, services,
API actions, validations, frontend integration and milestone-specific verification.

## Accounting and history compatibility

Existing N-way document matching, source-capacity allocation, duplicate-case identity,
approved SKU aliases, payment components and investigation transitions are reused.
Credits and deductions reduce eligible settlement balances only after explicit verified
application. They are not cash receipts or confirmed recoveries. Finding amounts are
never added together for analytics; authoritative persisted case differences are summed
once per case, while credits and adjustments are selected once per invoice application.
Modules and currencies remain separate. Shared invoices are not duplicated by case joins.

The combined pure finding evaluator is reused by refresh and investigation validation.
New findings include settlement validation, possible duplicates, statement mismatches
and unresolved deductions. Their financial exposure is not fabricated. Existing finding
fingerprints, snapshots, human decisions and original documents remain preserved.
Source changes can clear findings and require root-cause/claim review without erasing
history. Timeline events and financial writes commit or roll back together.

## Database changes

Ten additive migrations:

- AP `0014_suppliercreditnote_suppliercreditapplication_and_more`: credits,
  applications, reversals, positive amount and unique reference/idempotency constraints.
- AP `0015_supplierstatement_supplierstatementevaluation_and_more`: statements,
  original lines, explicit one-target matches and append-only observations; active
  line/target uniqueness constraints.
- AR `0013_customerdeduction_deductionapplication_and_more`: deductions,
  applications, reversals, observations and amount/reference/idempotency constraints.
- Discrepancies `0004`: credit timeline event choice.
- Discrepancies `0005`: settlement finding choice.
- Discrepancies `0006`: ordered AP/AR duplicate candidate pairs and review history.
- Discrepancies `0007`: supplier claims, protected settlement references and correspondence.
- Discrepancies `0008`: statement finding and timeline choices.
- Discrepancies `0009`: deduction finding and timeline choices.
- Discrepancies `0010`: reviewed finding root causes and evidence links.

Migrations were applied in disposable SQLite and PostgreSQL test databases and the
loopback-only UI test database. The ordinary workspace database was not migrated.
Apply `python auditcounter_django/manage.py migrate` with the intended local database
configuration before using these features. No historical observations are invented
and no existing financial data is transformed by migrations.

## Import modes and MVP limits

| Record | Supported entry | Intentionally not exposed |
|---|---|---|
| Existing PO/DR/SI/payments | Existing extraction and read-only database import, now quality-gated | Autonomous correction |
| Supplier credits | Manual entry + original uploaded evidence | Credit PDF/ERP/CSV extraction |
| Statements | Structured CSV text + original uploaded source | Excel/PDF parsing, ERP statement import |
| Customer deductions | Manual entry + invoice and original uploaded evidence | Automatic short-payment acceptance or extraction |
| Claims/correspondence | Manual case workflow and copyable draft | Automatic email sending |

Statements support up to 500 lines; detail histories show 20 recent statement and 50
recent deduction observations, retaining older rows. Registers show bounded recent
records; direct detail URLs remain available. Duplicate detection narrows to at most
200 comparable invoices plus prior candidate pairs. Schema drift is checked against
the latest completed snapshot, not an automatically refreshed external schema.

Claim credit closure currently uses one verified application; split applications when
supporting independent claims. No cash-refund ledger, foreign exchange conversion,
background processing, production deployment/scaling, organization isolation, roles
or authentication is added. Cash recoveries are explicitly zero because no supporting
cash-recovery workflow exists. Root causes are human-reviewed, never AI-inferred.
Operational register counts explicitly use module/party/currency/source dates; case
analytics additionally use finding/root-cause/investigation filters. Recorded finding
confirmation counts describe historical human decisions; root-cause counts require
current confirmed attribution.

## Verification

Commands executed from the repository root unless otherwise specified:

```bash
.venv/bin/python auditcounter_django/manage.py check
.venv/bin/python auditcounter_django/manage.py makemigrations --check --dry-run
.venv/bin/python auditcounter_django/manage.py test accounts_payable accounts_receivable discrepancies --noinput
# Full discovery uses the Django project directory; repository-root discovery finds zero tests.
(cd auditcounter_django && ../.venv/bin/python manage.py test --noinput)
env DB_ENGINE=django.db.backends.postgresql DB_NAME=postgres DB_USER=aladinyu DB_HOST=127.0.0.1 DB_PORT=55432 .venv/bin/python auditcounter_django/manage.py test accounts_payable accounts_receivable discrepancies sku_matching --noinput
node --test auditcounter_django/accounts_receivable/frontend_tests/*.test.cjs auditcounter_django/router/frontend_tests/*.test.cjs
```

PostgreSQL was a disposable local PostgreSQL 17 cluster, never the ERP database.
Additional focused commands used the same test command with milestone test modules.
Migrations were applied by the test runners and by `manage.py migrate --noinput`
against `/private/tmp/auditcounter-mvp-ui.sqlite3`.

| Executed verification | Result |
|---|---|
| Django system check | No issues |
| Migration drift check | No changes detected |
| AP/AR/discrepancies milestone regression | 335 tests, 316 passed, 19 PostgreSQL-only skips |
| PostgreSQL AP/AR/discrepancies/SKU regression after final statement/claim safeguards | 381 passed; no failures or skips |
| Focused final financial/investigation regression | 40 passed on SQLite |
| Focused final financial/concurrency regression | 43 passed on PostgreSQL |
| Final SKU/root-cause analytics regression | 10 passed on SQLite; 11 passed on PostgreSQL including concurrency |
| Frontend unit tests | 93 passed; no failures or skips |
| Whitespace/diff check | Clean |

Final full Django discovery: **589 tests run; 569 passed, 20 PostgreSQL-only skips; zero failures or errors** (150.743 seconds). SQLite locking skips are
intentional; the equivalent PostgreSQL tests were executed successfully. No unrelated
pre-existing failures remain. Earlier development failures (decimal representation
in fresh test-fixture revision tokens, attempted mutation of protected matched lines,
and an overly broad frontend test mock) were corrected and rerun successfully.

Browser plugin not available: reused installed Playwright with local headless Chrome,
no new browser dependencies. All browser work targeted `127.0.0.1:8765` with disposable
synthetic data. Tested statement import → missing-credit evidence; deduction entry →
acceptance → application → reversal; root-cause confirmation; claim draft → submission
→ acceptance → verified credit application → closure; analytics filtering. All passed.
Desktop 1440×1000 and mobile 390×844 pages were inspected. No page errors or horizontal
page overflow in the four final mobile flows. Initial full-page smoke checks had no
console errors. Browser harness navigation/body-read timing and omitted required
selects were corrected; these were test-harness failures, not application failures.
Temporary screenshots and test logs are outside the repository under `/private/tmp/`.

Mandatory acceptance scenarios A–E are automated in `test_claims.py` (50/48 units,
36,000 credit), `test_duplicate_invoices.py`, `test_statements.py` (missing credit),
`test_deductions.py` (95,000 cash / 5,000 dispute), and `test_data_quality.py`
(removed mapped column). PG tests use independent connections and account-first locks.

## Completion and remaining actions

All eight implementation milestones are complete within the import modes and limits
above. No known failing tests or unresolved implementation regressions remain. The
ordinary local application database still needs the ten additive migrations before
running this checkout. No migrations were applied to external ERP data.

The disposable PostgreSQL and loopback Django servers were stopped after verification.
The user subsequently authorized committing and pushing the completed implementation together with per-app README documentation to `matching-improvements`. No pull request is requested.

## App README follow-up

All eight project Django apps now have a README containing application flowcharts,
logical model ERDs, service boundaries, operational instructions and tests. Existing
operating guides are retained and updated for credit/deduction settlement and reviewed
source updates. The root README links every app guide. Static documentation validation
checked 74 owned model entities, all forward FK/one-to-one/many-to-many relationships,
21 Mermaid blocks, balanced Markdown fences and 35 app-local links. Django system
checks and migration-drift checks were rerun successfully for this documentation task.
The diagrams are logical model documentation; implicit M2M tables and every scalar
field are intentionally omitted, and no new schema migration is needed for README edits.
