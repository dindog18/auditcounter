# Company payments

Outgoing payments to suppliers, with separate cash, withholding tax and discount amounts and optional proof of payment. Open `/accounts-payable/payments/` in the [AP workspace](../accounts_payable/README.md).

## Flow

Save the payment and open **Allocate payment** in AP. Allocations apply to eligible supplier invoices in the same currency and use the AP `PaymentAllocation` model. Only cleared payments contribute to invoice settlement and [AP reconciliation](../ap_recon/README.md).

The register supports manual entry. Routed extraction and database imports resolve this target through the shared accounting catalog and retain source links on imported records.

## Structure

- [models.py](models.py) owns `CompanyPayment`.
- [services.py](services.py) supports model validation. Checks component amounts against saved allocations, validates reactivation and computes remaining allocatable cash.
- The register, detail pages and write endpoints live in the [shared accounting workspace](../accounts_receivable/README.md). [migrations/](migrations/) records this app’s schema history.
