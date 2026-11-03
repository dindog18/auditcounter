# Supplier credit tracking

Supplier credits are separate from cash payments. Manual drafts reference an
existing uploaded document. Verification requires evidence and written notes;
only verified credits can be applied to posted/disputed invoices of the same
supplier and currency. Credit-note extraction, database and spreadsheet imports
are deliberately not exposed in this milestone: original accounting extraction
allowlists and routes retain their existing targets.

Models: SupplierCreditNote, immutable SupplierCreditApplication and one-to-one
SupplierCreditReversal. Migration accounts_payable/0014 adds protected references,
positive-amount checks and unique supplier/reference, source identity and request
keys. discrepancies/0004 adds the credits_changed event classification. No existing
rows are rewritten. Verified source values cannot be edited; corrections use
reversals and new evidence. Supported model/queryset paths prohibit destructive
history updates.

`accounts_payable.services.credits` creates, verifies, applies and reverses credits.
Amounts are Decimal with two-digit financial precision. Supplier-first row locks
serialize payments and credits before credit/invoice locks. Non-reversed pending
payments reserve capacity but only cleared payments settle it. Reusing an application
request key with identical values returns the original record; different values
conflict. Revisions include application/reversal history. Failed operations roll
back balances and timeline writes together.

Existing AP invoice settlement properties include active verified credits.
Payment validation, invoice changes and payment reactivation cannot overconsume
credited balances. Credit events appear under Payments / Credits in linked cases;
standalone credit records retain actual creation/verification/application timestamps
without inventing a reconciliation case or historical observation.

API: existing CSRF-protected AP POST actions `credit-create`, `credit-verify/<id>`,
`credit-apply/<id>`, `credit-reverse/<application_id>`. Read-only register/detail:
`/accounts-payable/credits/` and `/accounts-payable/credits/<id>/`. There is no AR
credit route. The register is bounded to 500 recent credits, 1,000 invoice choices
and 200 documents; direct detail URLs still retrieve older credits. This MVP does
not claim that verified credit application proves cash recovery.

Verification: 8 credit tests pass; PostgreSQL ran those plus 3 independent-connection
race tests (11 pass), covering simultaneous applications, identical retries and
payment/credit balance races. AP/AR/discrepancy regression: 293 tests, 10 expected
PostgreSQL-only skips at that checkpoint. Frontend suite: 82 pass. Migrations applied
to disposable SQLite/PostgreSQL databases; system and drift checks pass. Browser
workflow results are recorded in the execution checkpoint after final validation.

Integrated verification results and exact commands: [implementation report](mvp-implementation-report.md). Exact created/modified files by milestone: [file inventory](mvp-file-inventory.md).
