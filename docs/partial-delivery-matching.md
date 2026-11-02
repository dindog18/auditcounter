# Partial-delivery matching implementation

One invoice line can now have several allocations, each retaining its invoice, PO, receipt line and quantity. No model or schema changes are required.

## Save and concurrency behavior

Both AP and AR use the existing shared `save_matches()` service. It preserves account/case locks and revision checks, locks selected source lines in a stable order, validates the entire replacement before deleting saved matches, and commits atomically. Duplicate invoice/PO/receipt triples are rejected. Invoice, ordered and accepted capacities include complete saved allocations from other cases, including allocations with arithmetic findings. Invalid requests preserve previous matches.

The preview action validates proposed allocations and calls the same evaluator without writing records. Preview does not reserve capacity; saving checks capacity again under database locks.

## Evaluation and accounting

`calculate_reconciliation()` retains its `(status, Decimal amount)` interface. The new detailed evaluator supplies findings, allocated/supported/unmatched quantities, signed unit-price variance, net financial variance, separate overcharge/undercharge amounts and arithmetic inconsistencies.

- Supported quantities aggregate valid evidence across all allocations on an invoice line.
- Party, currency, case membership, document identifiers, cancelled orders, SKU and UOM are checked independently of financial differences.
- Prices, discounts and taxes can differ without erasing accepted receiving support.
- Unsupported invoice value uses the coherent invoice line value, prorated by quantity, including its discount and tax.
- Unit-price variance is `(invoice price - PO price) × supported quantity`. Net financial variance additionally includes prorated discount and tax differences. Offsetting components do not inflate monetary exposure; individual findings remain visible.
- Arithmetic findings use the maximum of header difference, total-versus-lines difference and summed line arithmetic differences for each document. These alternative manifestations are retained as findings but are not added together. This is a conservative inconsistency measure, not a diagnosis of independent source errors.
- Exposure from inconsistent source amounts is withheld and marked incomplete. Void invoices require review; their full value is not automatically counted as a loss.
- `total_discrepancy_amount` remains a compatibility measure combining non-overlapping arithmetic inconsistencies and potential unsupported/net financial differences. It is not a supplier debt or a recoverable-loss balance.
- Outstanding PO balances and receipt shortages/rejections are separate informational findings. A fully supported partial invoice can be matched even when the PO remains open.

Statuses remain `pending`, `partial`, `matched`, and `exception`. Financial and data-quality findings can make a fully supported invoice an exception. Quantity coverage alone can produce partial status while an expected delivery remains unresolved.

## Frontend behavior

The existing workspace supports adding/removing allocations and selecting different PO/receipt lines. Reopening displays every saved allocation. Preview displays authoritative backend quantities, status, signed price differences, net variance and explanatory findings in the case currency. Editing requires another successful preview before saving. Invalid previews keep saving disabled; saving also validates on the server.

The layout uses the existing cards and responsive tables. Mobile tables scroll horizontally.

## Exact implementation inventory

| File | Functions/classes changed or added |
| --- | --- |
| `auditcounter_django/accounts_payable/services/reconciliation.py` | `validate_match`, `evaluate_reconciliation`, `calculate_reconciliation` |
| `auditcounter_django/accounts_receivable/services/reconciliation.py` | `validate_match`, `evaluate_reconciliation`, `calculate_reconciliation` |
| `auditcounter_django/accounts_receivable/services/evaluation.py` | `evaluate`, `_evaluate` (new shared evaluation module) |
| `auditcounter_django/accounts_receivable/services/records.py` | `save_matches`, `prepare_matches`, `preview_matches` |
| `auditcounter_django/accounts_receivable/services/http.py` | `perform`: CSRF-protected `matches-preview` action |
| `auditcounter_django/accounts_receivable/services/pages.py` | `workspace_state`: detailed evaluation and all saved allocations |
| `auditcounter_django/accounts_receivable/static/accounting/workspace.js` | `matching` and its allocation/preview/event helpers |
| `auditcounter_django/accounts_payable/tests.py` | `PayablesPartialDeliveryTests` |
| `auditcounter_django/accounts_receivable/tests.py` | `ReceivablesPartialDeliveryTests` |
| `auditcounter_django/accounts_receivable/matching_test_support.py` | Shared fixtures and AP/AR partial-delivery scenarios |
| `auditcounter_django/accounts_receivable/test_matching_concurrency.py` | `AllocationLockTests.test_concurrent_receipt_consumption` |
| `auditcounter_django/accounts_receivable/test_backend.py` | Two existing endpoint tests now use actual primary keys instead of assuming ID 1; required for PostgreSQL sequence behavior |
| `auditcounter_django/accounts_receivable/frontend_tests/matching.test.cjs` | Reopening, currency, authoritative preview, edit invalidation and invalid-save prevention tests |
| `docs/partial-delivery-matching.md` | Implementation and verification handoff |

## Compatibility and limitations

Existing source records, ERP data and database relationships are preserved. Saved allocations are evaluated again when read without rewriting source values or cached decisions. Existing complete arithmetic-exception allocations retain receiving support. Legacy records with all three UOMs blank remain compatible; conflicting or partially missing SKU/UOM values require review. Legacy invalid or duplicate allocations can require manual correction.

No authentication, AI matching, ERP write-back, supplier messaging, inventory functionality, new Django app or dependency was added. Database bulk writes that bypass existing model/service validation remain outside the supported save workflow. Outstanding delivery versus confirmed loss still requires human investigation. Header-level amounts that cannot be reconciled to lines are flagged rather than allocated using invented rules.

## Verification

Commands run from `auditcounter_django/`, using the existing project virtual environment:

```sh
../.venv/bin/python manage.py test --noinput
../.venv/bin/python manage.py makemigrations --check --dry-run
node --test accounts_receivable/frontend_tests/*.test.cjs
```

The complete AP/AR suite was also executed against a disposable PostgreSQL 17 database, including real concurrent requests sharing receiving capacity. The locking test is explicitly skipped on SQLite.

Browser QA used a disposable SQLite database and loopback-only Django server. Browser plugin was unavailable, so the connected Playwright tools were used. Verified AR add → two allocations → preview → save → reopen → remove → partial preview, and AP over-allocation rejection. Desktop 1440×1000 and mobile 390×844 were inspected. The final matching page rendered meaningful content without an error overlay or console errors; the intentional invalid request returned HTTP 400. No public deployment or ERP access was used.

Final results: full Django suite **356 run, 355 passed, 1 PostgreSQL-only skip**; PostgreSQL AP/AR suite **149 passed, zero skipped**; Node frontend suite **46 passed**. Migration check reported **No changes detected**. JavaScript syntax and `git diff --check` passed. All earlier implementation and PostgreSQL test-portability failures were resolved before these final runs.
