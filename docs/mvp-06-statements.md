# Supplier statements

AP Supplier statements accepts up to 500 structured CSV rows, associated with an
existing uploaded source document. Columns are `reference,date,type,amount`; types
are invoice/payment/credit, amounts positive and decimal-safe. Signed opening and
closing balances preserve statement arithmetic. Manual CSV input is supported;
Excel/PDF extraction and database statement import are intentionally not exposed.

The shared accounting API provides `statement-create`, `statement-reconcile/<id>`
and `statement-review/<id>`. Writes lock the supplier then statement and require a
current revision. Exact reference, party, currency, amount and eligible posting
state establish matches. Ambiguous records require explicit selection. One ledger
record cannot be represented twice within a statement. Payments use their cash,
withholding and discount components; credits require verification. Matching a
statement never applies a credit or creates a financial ledger record.

Original statement values cannot be rewritten through supported paths. Match
references are protected; changed observations remain in append-only evaluation
snapshots. Repeated unchanged reconciliation is idempotent. Local invoice, payment
and credit changes refresh related statements. Linked AP cases receive nonmonetary
STATEMENT_MISMATCH findings, original document evidence and timeline transitions.
Unlinked statements remain reviewable without manufacturing a reconciliation case.

Migrations: AP 0015 adds four statement tables and match uniqueness/target constraints;
discrepancies 0008 adds finding/event choices. No original accounting records change.
Tests cover missing-credit detection and subsequent correction, idempotency, immutable
source values, stale reviews, rollback, read-only GETs and CSRF; an independent-
connection PostgreSQL test covers competing reviews. Existing findings, payment,
matching and investigation rules remain independent.

Final focused checks also cover ambiguous references, explicit ledger selection, payment/credit matching without credit application, reversed-payment refresh and original ledger links. Statement timeline events reference bounded observation summaries; complete line evidence stays in preserved statement observations.

Integrated verification results and exact commands: [implementation report](mvp-implementation-report.md). Exact created/modified files by milestone: [file inventory](mvp-file-inventory.md).
