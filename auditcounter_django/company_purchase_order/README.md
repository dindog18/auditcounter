# Company purchase orders

Company-issued purchase orders for suppliers. The header identifies the supplier, currency, status and totals. Optional lines hold ordered quantities and prices. Open `/accounts-payable/purchase-orders/` in the [AP workspace](../accounts_payable/README.md).

## Flow

Save the PO through manual entry, routed extraction or a configured database import. The save creates or refreshes its [AP reconciliation case](../ap_recon/README.md). Supplier receipts and invoices join that case through their explicit PO links.

The register supports manual entry. Routed extraction and database imports resolve this target through the shared accounting catalog and retain source links on imported records.

## Structure

- [models.py](models.py) owns `CompanyPurchaseOrder` and `CompanyPurchaseOrderLine`.
- [services.py](services.py) supports model validation. Validates PO consistency and protects line changes that would conflict with saved matching evidence.
- The register, detail pages and write endpoints live in the [shared accounting workspace](../accounts_receivable/README.md). [migrations/](migrations/) records this app’s schema history.
