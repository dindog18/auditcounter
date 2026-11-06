# Customer purchase orders

Purchase orders received from customers. The header identifies the customer, currency, status and totals. Optional lines hold ordered quantities and prices. Open `/accounts-receivable/purchase-orders/` in the [AR workspace](../accounts_receivable/README.md).

## Flow

Save the PO through manual entry, routed extraction or a configured database import. The save creates or refreshes its [AR reconciliation case](../ar_recon/README.md). Company receipts and invoices join that case through their explicit PO links.

The register supports manual entry. Routed extraction and database imports resolve this target through the shared accounting catalog and retain source links on imported records.

## Structure

- [models.py](models.py) owns `CustomerPurchaseOrder` and `CustomerPurchaseOrderLine`.
- [services.py](services.py) supports model validation. Validates PO consistency and protects line changes that would conflict with saved matching evidence.
- The register, detail pages and write endpoints live in the [shared accounting workspace](../accounts_receivable/README.md). [migrations/](migrations/) records this app’s schema history.
