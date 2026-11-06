# AP purchase order reconciliation

Open **Reconciliation** at `/accounts-payable/po-reconciliation/`. Each [purchase order](../company_purchase_order/README.md) has one automatic case for its supplier. The case reports document matching and settlement together.

## Flow

1. Save a PO and link its receipts and [invoices](../supplier_sales_invoice/README.md). Document saves refresh the case. The case flags missing evidence and differences in references, quantities, prices and amounts.
2. Review reference and delivery evidence and allocate invoice lines where needed. Close eligible unserved quantities from the case when an outstanding quantity will not be fulfilled. The closure applies to the case’s quantity checks.
3. Compare invoice totals, applied [deductions](../ap_deduction/README.md) and cleared payment allocations. The case calculates the outstanding amount and status from those records and the review evidence.

## Structure

- [models.py](models.py) owns the one-to-one `Reconciliation` snapshot, status, totals, issues and review data.
- [services.py](services.py) delegates refreshes to the [shared calculation](../accounting_documents/reconciliation.py) in AP mode.
- The [accounting workspace](../accounts_payable/README.md) serves the register and review actions. Older saved line matching cases are available through the separate legacy register.

See the [full reconciliation workflow](../../docs/accounting-reconciliation.md).
