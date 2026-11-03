# Mapping and data-quality validation

Milestone 1 extends the existing AP/AR setup, signed review receipts, streamed
read-only source queries and atomic local updates. It does not create another
mapping assistant or product catalog.

## Behavior

`db_extraction.services.schema_comparison` compares mapped snapshot tables with
the latest completed snapshot of the same connection. Removed tables/columns,
changed types/precision, nullability, primary-key order, and recorded database
identity require review. A rename is reported as a missing column; no replacement
is guessed. Failed snapshots are ignored. Query source projections are checked
conservatively, including source fields used by intermediate transformation steps.

`accounts_receivable.services.setup.data_quality` reuses accounting field conversion,
account lookup, model validation, line normalization and arithmetic checks. Results
identify missing fields/parties, invalid quantities, money/precision/dates/currency,
invalid mappings, duplicate source identities and arithmetic errors. Missing or
unresolved SKU identities are nonblocking warnings; no alias is approved by a test.
Known products are inspected within the account and bounded to 2,000 lines; absence
from that bound is a review warning, never proof of a mismatch.

Existing setup-test and setup-migration-review/setup-update-review POST actions
include `quality` with blocking/warning counts and at most 200 issues. Each issue
contains code, severity, field, bounded observed value, explanation, next action
and blocking flag. Structured observed values are redacted. Source imports recheck
validation. Signed confirmation identities include the latest schema snapshot ID.
Schema failures produce no migration token and no accounting writes.

Both the transformation builder and older database editor display the same escaped
quality report. Full migration review includes it. Configuration assistants receive
schema issues as context; proposals still require explicit review and confirmation.
No provider calls are made by deterministic validation.

## Storage and compatibility

No migration or new model is required. Existing DatabaseImportRun summaries retain
bounded quality outcomes. Original schema snapshots, source values, matching and
investigation histories remain intact. External queries remain READ ONLY.
Read-only metadata refresh is still explicit; drift after the last completed
snapshot can only be caught by live query validation/failure until refreshed.

## Verification

Baseline: full Django suite 527 tests, 11 PostgreSQL-only skips; 78 frontend tests;
system and migration checks clean. Milestone: 535 Django tests, 11 PostgreSQL-only
skips; 38 focused setup/quality tests pass; 80 frontend tests pass. System and
migration checks pass. PostgreSQL AP/AR/discrepancy suite: 285 passed without skips. Browser verification
on loopback using synthetic schema snapshots: field matching → validate mapped
records → removed-column/changed-key report. Desktop and 390px mobile layouts
rendered without console errors or page overflow. Screenshots were captured in temporary storage during that milestone; temporary artifacts may be cleaned between sessions. No new dependencies or authentication.

Integrated verification results and exact commands: [implementation report](mvp-implementation-report.md). Exact created/modified files by milestone: [file inventory](mvp-file-inventory.md).
