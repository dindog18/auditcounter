# Company sales invoices

Invoices issued to customers. The header stores customer, currency, amounts, invoice status, printed PO reference and optional PO link. Lines hold billed quantities and values. Open `/accounts-receivable/invoices/` in the [AR workspace](../accounts_receivable/README.md).

## Flow

Save the invoice and verify its customer PO link. Review document differences in [AR reconciliation](../ar_recon/README.md). Applied [AR deductions](../ar_deduction/README.md) reduce net due, and cleared allocations from [customer payments](../customer_payment/README.md) reduce the outstanding balance.

The register supports manual entry. Routed extraction and database imports resolve this target through the shared accounting catalog and retain source links on imported records.

## Structure

- [models.py](models.py) owns `CompanySalesInvoice` and `CompanySalesInvoiceLine`.
- [services.py](services.py) supports model validation. Checks that invoice changes remain compatible with existing allocations and calculates cleared settlement.
- The register, detail pages and write endpoints live in the [shared accounting workspace](../accounts_receivable/README.md). [migrations/](migrations/) records this app’s schema history.
