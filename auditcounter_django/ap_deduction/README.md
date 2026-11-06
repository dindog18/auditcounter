# AP deductions

Open `/accounts-payable/deductions/` in the [AP workspace](../accounts_payable/README.md) to record adjustments such as defective items, pull outs, support and credit memos against a [purchase order](../company_purchase_order/README.md).

## Flow

1. Enter the reference, date, category, supplier, currency, order and positive amount. A draft can be recorded before the invoice arrives.
2. Link an eligible [invoice](../supplier_sales_invoice/README.md) for the same account, order and currency, then mark the deduction **Applied**. Validation checks the remaining unallocated invoice balance.
3. Applied deductions reduce net due in the invoice and [AP reconciliation](../ap_recon/README.md). Draft and cancelled deductions leave the amount due unchanged.

## Structure

[models.py](models.py) owns the `Deduction` record and its source links.
[services.py](services.py) binds shared [locking and validation rules](../accounting_documents/deductions.py) to AP.
The accounting workspace handles manual entry and configured extraction. See the [reconciliation and deductions guide](../../docs/accounting-reconciliation.md).
