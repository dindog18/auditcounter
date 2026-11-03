# Supplier claims and correspondence

The existing AP case now contains a Supplier claims panel. Claims require current,
confirmed finding reviews and evidence belonging to those findings. A claim is a
manual request, never an automatic debt or recovered amount. Active/settled claims
cannot reuse the same finding or exceed the case's recorded discrepancy capacity.

`SupplierClaim` protects its case, supplier, findings and evidence. A credit closure
uses a unique protected credit application, preventing reuse by another claim.
`ClaimCorrespondence` is append-only and distinct from internal CaseActivity notes.
Optional staff labels are unverified. Migration discrepancies/0007 adds these tables
and claim timeline event types without changing existing accounting records.

`discrepancies.services.claims` implements creation, validated transitions,
correspondence and closure with account-first locks and stale revisions. States:
draft → submitted → waiting/accepted/rejected; accepted/rejected/resolved may return
to waiting with explanation. Closure requires an accepted amount and active verified
credit application on a case invoice, or cleared claimed findings and a linked
replacement receiving document. Rejected claims may close with documented no-recovery.
Credit reversal flags a closed claim for renewed review and preserves its resolution.

Shared AP API actions: claim-create/<case>, claim-transition/<claim>,
claim-correspondence/<claim>, claim-resolve/<claim>. Existing CSRF protection remains.
Case serialization provides claims; the panel offers a copyable draft, status controls,
manual correspondence logging, evidence selection and closure. No email is sent.

Tests: 4 focused scenarios cover the 50-unit/48-accepted appliance case and 36,000
credit, closure and reversal, invalid/duplicate claims, immutable correspondence,
stale writes and rollback. A PostgreSQL independent-connection test checks concurrent
status transitions. Frontend suite: 87 passed. Final regression and PostgreSQL
counts are recorded in the milestone execution checkpoint.

MVP limits: one supporting credit application per claim closure; split a verified
credit into applications when documenting independent claims. No refunds, credit-note
extraction, email delivery, automated collection or cash-recovery inference.

Integrated verification results and exact commands: [implementation report](mvp-implementation-report.md). Exact created/modified files by milestone: [file inventory](mvp-file-inventory.md).
