# Customer payments

Incoming payments from customers, with separate cash, withholding tax and discount amounts and optional proof of payment. Open `/accounts-receivable/payments/` in the [AR workspace](../accounts_receivable/README.md).

## Flow

Save the payment and open **Allocate payment** in AR. Allocations apply to eligible customer invoices in the same currency and use the AR `PaymentAllocation` model. Only cleared payments contribute to invoice settlement and [AR reconciliation](../ar_recon/README.md).

The register supports manual entry. Routed extraction and database imports resolve this target through the shared accounting catalog and retain source links on imported records.

## Structure

- [models.py](models.py) owns `CustomerPayment`.
- [services.py](services.py) supports model validation. Checks component amounts against saved allocations, validates reactivation and computes remaining allocatable cash.
- The register, detail pages and write endpoints live in the [shared accounting workspace](../accounts_receivable/README.md). [migrations/](migrations/) records this app’s schema history.
