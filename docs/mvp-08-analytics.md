# Reviewed root causes and outcomes

The existing case finding panel now supports human root-cause classification after
current finding confirmation. A protected one-to-one FindingRootCause stores the
current category, explanation, evidence snapshots, review basis, timestamp and
optional explicitly unverified staff label. Existing append-only CaseActivity holds
all prior classifications. Material evidence or review changes mark an attribution
as needing renewed review; unchanged recalculation does not. Rules never infer causes.

Shared accounting action `root-cause-review/<case>` reuses investigation account/case
locks and revisions, validates finding/evidence membership and rolls back atomically.
Migration discrepancies 0010 adds the classification and evidence relation only.

The existing discrepancy dashboard includes a read-only outcomes section backed by
GET `/discrepancies/api/analytics/`. Filters: module, party_id (requires module), currency,
date_from/date_to, finding_type, root_cause, investigation_status, page/page_size
(maximum 100). Existing dashboard filter conventions are accepted. Party aggregation
is paginated; category counts and other top lists are bounded. Database aggregates
compute case differences once per case, not summed individual finding amounts.
Application totals select invoice IDs through subqueries to avoid shared-case join
multiplication; reversed applications are excluded. AP/AR and currencies stay separate.

Measures: finding frequency and recorded confirmations, current confirmed causes,
confirmed findings by party, repeated reviewed invoice SKU codes, closed investigation/claim
durations, unresolved claim age buckets, potential case differences, accepted claims,
applied credits and applied deductions. There is no cash-refund ledger; verified cash
recoveries are explicitly zero, never inferred from adjustments. Recorded finding
confirmations describe historical human reviews, while root-cause aggregates require
current confirmed attribution. Operational register counts also include unlinked
records and explicitly use only module/party/currency/source-date filters.

Tests cover AP/AR classification, repeat/no-op writes, renewed review, atomic rollback,
stale revisions, evidence membership, read-only APIs, filters, separate currency buckets,
overlapping finding amounts, reversed credits and a PostgreSQL concurrent-review race.
Frontend tests cover safe text, currency strings, pagination and AP/AR classification.
SKU counts require selected invoice-line evidence and count distinct findings rather than repeated snapshots. Original codes are retained; missing product evidence is not inferred. Final executed counts are in the implementation verification document.

Integrated verification results and exact commands: [implementation report](mvp-implementation-report.md). Exact created/modified files by milestone: [file inventory](mvp-file-inventory.md).
