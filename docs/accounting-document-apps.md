# Accounting document apps

Each AP and AR document has a concrete Django app. A header and its lines stay
in the same app; AP and AR never share document models.

| Workflow | Django app | Document model | Line model |
| --- | --- | --- | --- |
| AP | `company_purchase_order` | `CompanyPurchaseOrder` | `CompanyPurchaseOrderLine` |
| AP | `supplier_delivery_receipt` | `SupplierDeliveryReceipt` | `SupplierDeliveryReceiptLine` |
| AP | `supplier_sales_invoice` | `SupplierSalesInvoice` | `SupplierSalesInvoiceLine` |
| AP | `company_payment` | `CompanyPayment` | — |
| AR | `customer_purchase_order` | `CustomerPurchaseOrder` | `CustomerPurchaseOrderLine` |
| AR | `company_delivery_receipt` | `CompanyDeliveryReceipt` | `CompanyDeliveryReceiptLine` |
| AR | `company_sales_invoice` | `CompanySalesInvoice` | `CompanySalesInvoiceLine` |
| AR | `customer_payment` | `CustomerPayment` | — |

Company purchase orders are issued to suppliers; customer purchase orders are
received from customers. Supplier receipts and invoices belong to AP; company
receipts and invoices belong to AR. Company payments are outgoing AP payments;
customer payments are incoming AR payments.

## Ownership and imports

Each document app owns `models.py` and `services.py`. Persistence, source
validation, line edits, invoice settlement and payment amount validation run
through that document's models and services. Invoice and payment business rules
live in the invoice and payment apps respectively. `accounting_documents` is a
plain Python package containing shared provenance checks, matched-line protection,
and amount arithmetic. It has no models or app registration.

`accounts_payable` retains suppliers, reconciliation cases, line matches, payment
allocations, extraction configuration, LLM logs, and database import history.
`accounts_receivable` retains the corresponding customer workflow. Their
`services/reconciliation.py` files own the rules that span multiple documents.
The workspace, configuration, extraction and database import orchestration remain
shared through services that receive an explicit `ap` or `ar` mode.

New code should import a document from its owning app:

```python
from supplier_sales_invoice.models import SupplierSalesInvoice
from company_sales_invoice.models import CompanySalesInvoice
```

Existing imports from `accounts_payable.models` and `accounts_receivable.models`
remain compatibility aliases to these same classes. They do not register extra
models. Django's `apps.get_model()` must use the owning document app label.
The accounting `services/catalog.py` resolver handles both document targets and
internal workflow models, and rejects document classes belonging to the other
workflow.

## Integrations

The router's destination catalog exposes the owning document apps, with AP/AR
labels explaining the workflow. Existing destinations saved with
`accounts_payable` or `accounts_receivable` continue to validate and process;
existing routing history and rule snapshots are unchanged. Both destination
styles resolve to the same extraction configuration, record and attempt links.
Onboarding checks include destinations using either style.

Database imports resolve headers and lines through the same accounting catalog.
Their source metadata, import keys, configuration snapshots and transaction
boundaries remain intact. Database-source and extraction-log reverse accessors
retain their original names for connected modules.

Workspace URLs and namespaces remain `/accounts-payable/` and
`/accounts-receivable/`; these are workflow screens spanning several documents.

## Applying the change

From `auditcounter_django`, run the complete migration graph:

```sh
python manage.py migrate
```

The document apps' initial migrations adopt the existing tables using
`SeparateDatabaseAndState`. The AP/AR migrations retarget relationships and remove
only the former model state. Explicit `db_table` values retain the existing
`accounts_payable_*` and `accounts_receivable_*` physical tables, including line
and reconciliation membership tables. No document rows are copied or deleted.

Content types move to the owning app while retaining their IDs. Existing
permissions, user/group assignments, and references to content types retain their
identity. The migrations also reverse these moves when rolling back. Original
historical migrations remain unchanged, allowing both existing installations and
fresh databases to use the same graph.

For migration-aware integrations, permission labels now use the owning app, for
example `supplier_sales_invoice.view_suppliersalesinvoice`. Existing permission
assignments remain attached to the same permissions.

## Validation

```sh
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test accounts_payable accounts_receivable db_extraction router encoder document_extraction
```

`accounts_payable.test_document_apps` verifies ownership, AP/AR isolation, and
forward/reverse preservation of headers, lines, case membership, line matches,
payment allocations, LLM record links, physical tables, content types and
permissions. The existing accounting and router suites exercise document
extraction, database import, deletion, reconciliation and workspace endpoints
against the new document classes.

## Manual entry

Every document register offers **New manual entry**. Select the supplier/customer,
enter the document details and optionally add line items. The form calculates
amounts using decimal arithmetic, and the backend validates the complete header
and line collection atomically. Payments use their cash, withholding and discount
components. Manual records appear in the register's source filter and can be
edited from their detail page. Source-backed records keep their extraction flow.

The CSRF-protected endpoint is `POST /accounts-payable/api/manual-entry/` or
`POST /accounts-receivable/api/manual-entry/`, with `{resource, record, lines}`.
Edits append the record ID and require the revision returned in the edit-page
configuration. Line IDs must belong to that document; omitted or stale revisions
are rejected. System-managed provenance fields cannot be supplied.

PO links, deduction apps and automatic reconciliation extend this architecture.
See [PO reconciliation and deductions](accounting-reconciliation.md).
