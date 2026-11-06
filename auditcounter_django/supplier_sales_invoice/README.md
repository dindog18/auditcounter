# Supplier sales invoices

Invoices received from suppliers. The header stores supplier, currency, amounts, invoice status, printed PO reference and optional PO link. Lines hold billed quantities and values. Open `/accounts-payable/invoices/` in the [AP workspace](../accounts_payable/README.md).

## Flow

Save the invoice and verify its company PO link. Review document differences in [AP reconciliation](../ap_recon/README.md). Applied [AP deductions](../ap_deduction/README.md) reduce net due, and cleared allocations from [company payments](../company_payment/README.md) reduce the outstanding balance.

The register supports manual entry. Routed extraction and database imports resolve this target through the shared accounting catalog and retain source links on imported records.

## Structure

- [models.py](models.py) owns `SupplierSalesInvoice` and `SupplierSalesInvoiceLine`.
- [services.py](services.py) supports model validation. Checks that invoice changes remain compatible with existing allocations and calculates cleared settlement.
- The register, detail pages and write endpoints live in the [shared accounting workspace](../accounts_receivable/README.md). [migrations/](migrations/) records this app’s schema history.
