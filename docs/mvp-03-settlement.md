# Explainable settlement alongside document matching

`accounts_receivable.services.settlement` evaluates AP and AR invoices without
writing records. It preserves the existing three-way document evaluator and
statuses. Each invoice result separately returns recorded total, cleared cash,
withholding tax, payment discounts, verified active credits, pending payment
reservations, outstanding balance, status, reasons and source links. Applied
credits are never represented as payments or verified cash recovery. Unapplied
credits are bounded to 200 matching supplier/currency records.

Statuses are `outstanding`, `partial`, `settled`, `needs_review`. Ordinary outstanding
balances and expected partial payments do not create discrepancy findings.
Inconsistent settlement identity/currency/amount or over-reservation produces a
SETTLEMENT_MISMATCH validation finding, with no automatic monetary loss claim.
Reconciliation refresh synchronizes it alongside document findings. Corrected
settlement snapshots remain in FindingEvidence; existing review state and timeline
history are preserved. Payment changes now use that refresh path as well.

Migration discrepancies/0005 adds only the finding choice. Existing data is
unchanged. No new endpoint is needed: existing workspace serialization includes
`settlement` on invoices/cases. The case detail has a separate Payment / credit
settlement panel showing backend decimal strings and links to source records.

Verification: 7 new AP/AR settlement tests pass; 18 credit/timeline tests pass;
AP/AR/discrepancy regression 303 tests, 13 PostgreSQL-only skips. Frontend suite
85 pass. PostgreSQL combined results and final browser checks are recorded in the
execution checkpoint. System/migration checks pass. Tests cover withholding and
discounts, pending/reversed payments, credits/reversals, missing/inconsistent
settlement evidence, read-only evaluation and unchanged matching status.

Limitations: no currency conversion or cash-recovery inference. Header totals are
recorded invoice totals, not corrections inferred from line discrepancies.
Supplier claims and customer deductions integrate through milestones 5 and 7; accepted applied deductions appear as adjustments, independently of cash.

Integrated verification results and exact commands: [implementation report](mvp-implementation-report.md). Exact created/modified files by milestone: [file inventory](mvp-file-inventory.md).
