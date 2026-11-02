# Automatic rule-based matching

Auto Match is a read-only, deterministic case-level assistant for both AP and AR. It builds on the existing partial-delivery allocation service. No database migrations, dependencies, authentication, background workers, AI, ERP updates or source-value corrections are introduced.

## Matching rules

1. Only the case's linked documents are considered. Party, currency, references, dates and document statuses are checked. PO status must be open or closed; AP invoices must be posted/disputed and AR invoices posted; AP receipts must be accepted/partial and AR receipts delivered/partially accepted. Pending, draft, rejected or incomplete evidence requires review.
2. SKU and UOM comparison trims surrounding whitespace, collapses repeated whitespace and casefolds. Different codes or units are never inferred equivalent. Automatic matching requires explicit SKU/UOM values. The manual validator uses the same normalization while preserving legacy compatibility for uniformly blank fields.
3. Available invoice, PO and accepted DR quantities subtract saved allocations across all cases and the current manual draft. Arithmetic-exception allocations also reserve their source capacity. Multiple receipts can support a single invoice line.
4. Prices do not disambiguate competing orders. Multiple plausible PO lines, competing invoice lines and receipt subsets with multiple plausible choices require human selection. Stable primary-key ordering only makes output repeatable. Multiple receipts are proposed together when all available receipts are needed, so ordering cannot decide the business relationship.
5. The existing relationship validator and reconciliation evaluator supply validation and financial findings. Price, discount, tax and source-arithmetic issues require review without discarding receiving support. Combined proposals are evaluated again to catch aggregate tolerances.
6. Suggestions never write records. Ambiguous alternatives expose individual maximum quantities, not jointly allocated quantities. A reviewer must explicitly choose an alternative and preview it. Cases with more than 1,000 candidate relationships for a line require narrower evidence or manual matching.

Results separate `suggestions`, `needs_review`, and `unmatched`. Suggestions include line IDs, decimal quantities as strings, reasons, and signed financial variances. Line summaries distinguish unallocated quantity before proposals from remaining quantity after proposed allocations. There are no confidence scores.

## API and confirmation

New POST actions:

- `/accounts-payable/api/match-suggestions/<case_id>/`
- `/accounts-receivable/api/match-suggestions/<case_id>/`

Request example:

```json
{"revision": "existing matchRevision token", "matches": []}
```

`matches` is optional; when present it contains the current manual draft in the existing `invoiceLineId`, `orderLineId`, `receiptLineId`, `quantity` format. Saved manual rows are merged into that draft. Editing their quantities must be saved separately before using Auto Match.

The response contains `case_id`, `revision`, `suggestion_revision`, `suggestions`, `needs_review`, `unmatched`, and `lines`. Generation checks source fingerprints before and after evaluation and returns a conflict if evidence changed during generation.

Confirmation continues to use the existing POST `matches/<case_id>/` action:

```json
{
  "revision": "response revision",
  "suggestionRevision": "response suggestion_revision",
  "preserveExisting": true,
  "matches": [
    {"invoiceLineId": 101, "orderLineId": 201, "receiptLineId": 301, "quantity": "60.0000"}
  ]
}
```

The case revision protects case/membership/current allocations. The source fingerprint additionally covers linked headers, source lines, and allocations touching those lines in every case. Confirmation locks source records, rejects stale fingerprints, merges existing manual allocations, validates the complete result, and inserts only new allocations. Saved allocation IDs, notes and timestamps are preserved. Duplicate submissions and over-allocation fail atomically. Editing proposed quantities is allowed, subject to all normal validations. The normal manual replacement operation remains available without Auto Match confirmation fields.

All actions retain the existing CSRF protection and POST-only handling. Preview and generation do not reserve capacity; confirmation revalidates it under locks.

## Frontend workflow

Open an existing case's matching workspace → Auto Match → inspect outcomes and explanations → accept/reject a suggestion or explicitly choose an ambiguous alternative → edit the added allocation if needed → Preview reconciliation → Save matches.

Auto Match leaves current manual rows in place. Saved rows are preserved and locked during automatic confirmation; Return to manual editing restores their normal editing controls. Accepting only adds a draft row. Rejected suggestions add nothing. Every draft edit requires another backend preview. The case's actual currency is used for financial results. Reopening shows the persisted allocations using the existing workspace serializer; no additional serialization changes were necessary.

## File/function inventory for this feature

| File | Changes |
| --- | --- |
| `auditcounter_django/accounts_receivable/services/auto_matching.py` | New `normalize_item_code`, `find_candidate_lines`, `get_available_quantities`, `evaluate_match_candidate`, `generate_match_suggestions`; source fingerprint, document eligibility, mode/service and allocation-format helpers |
| `auditcounter_django/accounts_payable/services/reconciliation.py` | `validate_match`: use shared deterministic SKU/UOM normalization |
| `auditcounter_django/accounts_receivable/services/reconciliation.py` | `validate_match`: same normalization for manual/automatic compatibility |
| `auditcounter_django/accounts_receivable/services/records.py` | `save_matches`: locked source-revision checks and insert-only merge confirmation; new `merge_match_rows` |
| `auditcounter_django/accounts_receivable/services/http.py` | `perform`: read-only `match-suggestions` action |
| `auditcounter_django/accounts_receivable/static/accounting/workspace.js` | `matching`: Auto Match review/accept/reject/edit controls, draft handling and merge confirmation; `badge`: new outcome colors |
| `auditcounter_django/accounts_receivable/auto_matching_test_support.py` | Shared AP/AR automatic-matching scenarios |
| `auditcounter_django/accounts_payable/tests.py` | `PayablesAutoMatchingTests` |
| `auditcounter_django/accounts_receivable/tests.py` | `ReceivablesAutoMatchingTests` |
| `auditcounter_django/accounts_receivable/test_matching_concurrency.py` | Concurrent automatic confirmation test on PostgreSQL |
| `auditcounter_django/accounts_receivable/frontend_tests/matching.test.cjs` | Auto Match read-only generation, explicit acceptance, merge-token propagation, rejection and existing manual frontend regressions |
| `docs/automatic-rule-based-matching.md` | Implementation handoff |

The prior partial-delivery implementation remains in the working tree. Its existing models, detailed financial evaluator, manual persistence, preview API, and workspace state are reused.

## Compatibility and deliberate limitations

Manual AP/AR reconciliation and split allocations remain supported. Financial findings continue to use the existing public reconciliation return contract. Automatic confirmation preserves saved manual records and their metadata. Source documents and imported ERP records are not changed.

The schema has no explicit invoice-to-PO or DR-to-PO reference to resolve competing orders. These cases require a human choice. No fuzzy SKU matching, inferred unit conversion, price-based tie breaking, automatic claims, financial correction, background processing or ERP write-back is performed. Existing incomplete/invalid allocations may need manual correction before using Auto Match. Increasing the quantity of an already allocated identical invoice/PO/DR triple is a manual edit, not a duplicate automatic allocation. Source fingerprints intentionally reject confirmation after any relevant evidence/allocation change, even if an edited allocation might still fit; rerun Auto Match.

## Verification commands

```sh
# Repository root
.venv/bin/python auditcounter_django/manage.py test accounts_payable accounts_receivable --noinput
node --test auditcounter_django/accounts_receivable/frontend_tests/*.test.cjs
.venv/bin/python auditcounter_django/manage.py makemigrations --check --dry-run

# Django project directory, so discovery includes the full suite
../.venv/bin/python manage.py test --noinput
```

AP/AR tests also run against disposable PostgreSQL 17, including real concurrent manual allocations and automatic confirmations. SQLite explicitly skips those locking tests.

Browser QA used a disposable SQLite database on `http://127.0.0.1:8765`, with desktop 1440×1000 and mobile 390×844 viewports. Browser plugin was not available, so connected Playwright tools were used. Verified split suggestions, no allocations before acceptance, quantity editing, backend preview, saving/reopening, rejection, price review with 100 supported units and a 50,000 variance, and explicit selection from two ambiguous POs. Page identity, meaningful content, absence of error overlays, console health, screenshots and interactions passed. Mobile tables retain the existing horizontal scrolling behavior. No public service or production data was used.

Final executed results:

| Check | Result |
| --- | --- |
| Full Django suite | 391 run: 389 passed, 2 PostgreSQL-only locking tests skipped on SQLite |
| AP/AR SQLite suite | 184 run: 182 passed, 2 PostgreSQL-only skips |
| AP/AR PostgreSQL suite | 184 passed, no skips; includes concurrent Auto Match confirmation and manual over-allocation contention |
| Existing and new Node frontend tests | 48 passed |
| Migration check | No changes detected |
| JavaScript syntax and `git diff --check` | Passed |
| Browser interaction and responsive checks | Passed; no console errors |

The disposable Django and PostgreSQL services were stopped after verification. No changes were pushed and no pull request was created.
