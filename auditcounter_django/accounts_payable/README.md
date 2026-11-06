# Accounts payable

Open `/accounts-payable/` for supplier accounts, outgoing payments, aging and
reconciliation. AP owns suppliers, extraction profiles and logs, payment
allocations, and saved line matching cases. Each AP document has its own Django
app and validation rules.

## Flow

1. Create a supplier and enter records manually, or configure extraction from
   routed documents or PostgreSQL in [Record First setup](../accounts_receivable/SETUP.md).
2. Save a [company purchase order](../company_purchase_order/README.md) and link
   [supplier receipts](../supplier_delivery_receipt/README.md) and
   [supplier invoices](../supplier_sales_invoice/README.md) to it.
3. Apply [deductions](../ap_deduction/README.md) and allocate
   [company payments](../company_payment/README.md) as appropriate.
4. Open [Reconciliation](../ap_recon/README.md) for the automatic PO case. Review
   document evidence and check which balances remain outstanding.

## Structure

- [urls.py](urls.py) and [views.py](views.py) mount the workspace and dispatch shared operations in AP mode.
- [models.py](models.py) owns suppliers, allocations, legacy cases and extraction history. Document model imports here are compatibility aliases.
- [services/reconciliation.py](services/reconciliation.py) handles AP-specific matching and settlement rules. [signals.py](signals.py) connects updates to the shared automatic case calculation.
- The [shared AP/AR backend](../accounts_receivable/README.md) owns the workspace UI and extraction/import orchestration.

See the [accounting model ownership map](../../docs/accounting-document-apps.md).
