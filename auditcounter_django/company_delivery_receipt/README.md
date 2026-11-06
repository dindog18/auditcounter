# Company delivery receipts

Receipts for deliveries to customers. The header keeps the printed PO reference, optional PO link and proof of delivery. Lines capture delivered and accepted quantities. Open `/accounts-receivable/delivery-receipts/` in the [AR workspace](../accounts_receivable/README.md).

## Flow

Save the receipt, then verify its linked customer PO. **Save PO link** lets a reviewer link, reassign or clear the PO from the detail page. The [AR case](../ar_recon/README.md) uses eligible accepted quantities and displays receipt review issues.

The register supports manual entry. Routed extraction and database imports resolve this target through the shared accounting catalog and retain source links on imported records.

## Structure

- [models.py](models.py) owns `CompanyDeliveryReceipt` and `CompanyDeliveryReceiptLine`.
- [services.py](services.py) supports model validation. Validates the receipt, its source and line changes. The printed reference stays available for comparison with the linked PO.
- The register, detail pages and write endpoints live in the [shared accounting workspace](../accounts_receivable/README.md). [migrations/](migrations/) records this app’s schema history.
