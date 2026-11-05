# PO reconciliation and deductions

AP and AR have separate deduction and reconciliation apps:

| Workflow | Deductions | PO reconciliation |
| --- | --- | --- |
| Accounts payable | `ap_deduction.Deduction` | `ap_recon.Reconciliation` |
| Accounts receivable | `ar_deduction.Deduction` | `ar_recon.Reconciliation` |

## Workflow

1. Create or import a PO. A unique reconciliation case is created in the same
   transaction, even before the PO has invoices or delivery receipts.
2. Select that PO when entering its DR or SI. Extraction and database mappings
   may supply `purchase_order` as the PO reference number. The account and
   currency must match; the application never infers a PO just from the account.
   Existing manual or source-backed DRs/SIs have a **Purchase order for
   reconciliation** form on their detail page. **Save PO link** links, reassigns,
   or clears the PO independently of extraction. It preserves the document
   amounts, line items, source file/database identity, and extraction history.
   The sidebar shows the corresponding automatic case.
3. In **Deductions**, create a deduction with its reference, date, category,
   account, PO, currency and positive amount. Categories are Defective, Pull Out,
   Support, Credit Memo, and Other. Description and notes retain supporting details.
4. Choose the invoice and mark the deduction **Applied** to reduce its amount
   due. Draft deductions can be recorded against the PO before an invoice exists.
   Draft and cancelled deductions do not reduce amounts. Applied deductions
   require a posted or disputed invoice linked to that PO.
5. Allocate a payment to the invoice. Clear the payment when appropriate.
   The reconciliation case and invoice balance update automatically.

For an invoice of 100.00 with an applied deduction of 20.00, the net due is 80.00.
Cleared allocations totaling 80.00 match the payment requirement. Cash,
withholding tax and payment discounts are included in allocation totals.
Deductions remain separate records and are not also counted as payment discounts.
The original invoice and PO totals remain unchanged.

## Status and evidence

The case stores invoice totals, applied deductions, net due, cleared payment
allocations, outstanding amount, signed payment difference, status, and issues.
It updates when a PO, linked DR/SI, their lines, deduction, payment, or allocation
is saved or deleted using the application/model methods. A database uniqueness
constraint prevents duplicate cases for the same PO. PO row locks serialize
snapshot updates in the source transaction.

A case waits for delivery, invoice, or payment evidence as needed. Pending
receipts cannot establish accepted delivery. Rejected receipts do not contribute
accepted quantities, even if their stored item rows contain accepted values. Partial
invoicing/delivery or payment leaves it partial. Quantity, unit-price and header
arithmetic inconsistencies are checked; exceptions explain mismatches. Split
receipts and invoices aggregate by item code and unit of measure. For uncoded
items the line number and unit identify the item, so retain the PO line number
when entering those documents. Ambiguous item prices remain exceptions.

Applied deductions may account for rejected/short deliveries by covering their
value at the PO's unit price. A case is matched only when the documents cover the
PO and the cleared allocations equal invoice totals less applied deductions,
within the configured reconciliation tolerance. A full credit memo can settle an
invoice without cash. Cancelling a deduction or reversing a payment reopens the
remaining balance.

Use **Reconciliation** to see document matching and payment settlement for the
same PO. Open an invoice line in **Document matching and line review** to allocate
its quantity across PO lines and accepted delivery lines. A saved review counts
toward document matching immediately. Removing the allocations returns the line
to automatic checking. Eligible saved line matches are used when their invoice,
PO, and delivery lines belong to the case. The reconciliation register links to
older line matching cases for records that need their historical grouping.

## Protection and updates

Account/currency mismatches, deductions larger than the invoice's unallocated
balance, and allocations exceeding the invoice's net due are rejected. Existing
allocation reservations count even when their payment is pending. Only cleared
payments reduce the outstanding balance. An invoice with deductions cannot be
moved to another PO until its deductions are resolved.

Manual entry remains available for all eight original documents and for
deductions. Forms and JSON writes share model validation, CSRF protection,
atomic saves, and stale-edit checks. The deduction endpoint uses the existing
`manual-entry` action with `resource: "deductions"`. Reconciliation snapshots are
read-only and cannot be marked matched by an API caller.

Model saves and application imports run the synchronization hooks. Direct SQL,
`QuerySet.update()` and `bulk_create()` bypass Django save signals; external
writers must use the application/model workflow.

## Deployment and verification

Run `python manage.py migrate` from `auditcounter_django` and restart the server.
Migrations add the explicit PO links and the deduction/reconciliation tables,
and create missing cases for existing POs without replacing existing case IDs.
Historical DRs and invoices stay unlinked until their PO is explicitly selected
using **Save PO link** on their detail page. This action requires the record's
current revision, rejects account/currency mismatches and running extraction,
and preserves deduction restrictions when moving an invoice between POs.

Tests use an isolated SQLite database and mocked external providers:

```sh
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test accounts_payable accounts_receivable ap_deduction ar_deduction ap_recon ar_recon db_extraction router encoder document_extraction
node --test accounts_receivable/frontend_tests/*.test.cjs
```

Browser checks exercise both AP and AR through PO → DR → SI → applied deduction
→ payment allocation → clearing → matched case, including desktop and mobile
layouts. The manual-entry checks also cover all eight original document types,
editing, and an invalid-total response that preserves form values.
