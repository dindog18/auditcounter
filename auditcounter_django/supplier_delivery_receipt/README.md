# Supplier delivery receipts

Receipts for deliveries from suppliers. The header keeps the printed PO reference, optional PO link and receiving evidence. Lines capture delivered and accepted quantities. Open `/accounts-payable/delivery-receipts/` in the [AP workspace](../accounts_payable/README.md).

## Flow

Save the receipt, then verify its linked company PO. **Save PO link** lets a reviewer link, reassign or clear the PO from the detail page. The [AP case](../ap_recon/README.md) uses eligible accepted quantities and displays receipt review issues.

The register supports manual entry. Routed extraction and database imports resolve this target through the shared accounting catalog and retain source links on imported records.

## Structure

- [models.py](models.py) owns `SupplierDeliveryReceipt` and `SupplierDeliveryReceiptLine`.
- [services.py](services.py) supports model validation. Validates the receipt, its source and line changes. The printed reference stays available for comparison with the linked PO.
- The register, detail pages and write endpoints live in the [shared accounting workspace](../accounts_receivable/README.md). [migrations/](migrations/) records this app’s schema history.
