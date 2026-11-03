# Evidence-backed possible duplicate invoices

DuplicateInvoiceCandidate holds an ordered protected AP or AR invoice pair;
DuplicateInvoiceReview preserves detection snapshots and human review history.
Migration discrepancies/0006 adds the tables, scope/order/unique-pair constraints
and finding/timeline choices. No invoice or case identity constraint is removed.

Detection narrows by account, currency, exact recorded total and invoice dates
within three days, then compares Unicode-normalized case-insensitive references
without formatting punctuation. Leading digits/zeros are retained. At most 200
new candidate invoices are evaluated per scan, plus previously detected pairs.
Line conflicts and payment observations are preserved for investigation, never
used to choose between ambiguous invoices. Recurring invoices outside the date
window, partial invoices with different totals, different parties and currencies
are not flagged by this MVP rule.

Database/document accounting imports call detection after saving the invoice/lines.
Existing invoice details expose Check possible duplicates through the shared
CSRF-protected `duplicate-scan/<invoice_id>` POST action with invoice revision.
Case recalculation also refreshes candidates. Cases receive nonmonetary
POSSIBLE_DUPLICATE_INVOICE findings; invoices without cases retain independent
reviewable pairs. No case is fabricated. Candidate amounts never enter exposure.

The existing Discrepancies dashboard includes candidate review, field comparisons,
source-record links, detection/review history and paginated module/decision filters.
GET `/discrepancies/api/duplicate-invoices/` is read-only; POST
`/discrepancies/api/duplicate-invoices/<id>/review/` validates revision, decision and
explanation. Reviews do not change invoice values or deterministic finding status.
Detection snapshots remain when evidence changes or similarity ceases. Human
reviews are flagged stale when their source basis changes. Supplier/customer locks
and unique constraints prevent duplicate pairs under races.

Known limits: bounded conservative detection may omit other kinds of duplicates;
this is review assistance, not proof of fraud, duplicate payment or recoverable
loss. Users review findings and candidate decisions separately. Existing invoices
are scanned explicitly or during case recalculation; GET requests never backfill.

Verification: five functional tests pass (AP/AR, idempotency, recurring/partial
invoice exclusions, historical review, nonmonetary findings, read-only API and
CSRF). PostgreSQL runs the same plus independent-connection duplicate races.
Full regression/frontend results are recorded in the execution checkpoint.

Integrated verification results and exact commands: [implementation report](mvp-implementation-report.md). Exact created/modified files by milestone: [file inventory](mvp-file-inventory.md).
