# Customer deductions

AR Customer deductions records manual customer disputes with an original uploaded
document and posted/disputed invoice. Optional payment references must actually
allocate to that invoice. No automatic short-payment inference or extraction/import
target is exposed. Withholding and discounts remain existing payment components.

Review choices are pending, accepted, rejected. Acceptance records an amount and
explanation but does not settle an invoice. Explicit partial applications adjust the
balance; immutable reversals restore it. Active applications must be reversed before
reassessment. Original dispute fields and prior decisions remain preserved in protected
records and append-only observations. Account-first locks, revisions, application
idempotency keys, accepted-amount capacity and invoice reservation capacity prevent
reuse. Payment reactivation and invoice changes retain those protections.

Shared AR API actions: deduction-create, deduction-review/<id>, deduction-apply/<id>,
deduction-reverse/<id>. The AR-only workspace provides entry, evidence, review,
application/reversal and historical observations. Backend settlement displays cash,
withholding, discount and adjustments separately. CUSTOMER_DEDUCTION findings and
case timeline entries link unresolved disputes to the existing investigation system.
Review decisions never change physical PO/DR/SI calculations.

Migrations: AR 0013 adds deduction, application, reversal and observation tables;
discrepancies 0009 adds finding/event choices. Tests include the 95,000 payment /
5,000 deduction scenario, partial applications, reversal, rejection, stale writes,
rollback, CSRF and two independent-connection PostgreSQL capacity races.

Integrated verification results and exact commands: [implementation report](mvp-implementation-report.md). Exact created/modified files by milestone: [file inventory](mvp-file-inventory.md).
