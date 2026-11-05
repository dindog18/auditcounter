"""Small AP/AR model map shared by the two workspaces."""

import hashlib
import json

from django.apps import apps
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder

MODULES = {"ap": "accounts_payable", "ar": "accounts_receivable"}
TARGETS = {
    "ap": {"supplier": "Supplier", "purchase_order": "CompanyPurchaseOrder",
           "delivery_receipt": "SupplierDeliveryReceipt", "sales_invoice": "SupplierSalesInvoice", "payment": "CompanyPayment", "deduction": "Deduction"},
    "ar": {"customer": "Customer", "purchase_order": "CustomerPurchaseOrder",
           "delivery_receipt": "CompanyDeliveryReceipt", "sales_invoice": "CompanySalesInvoice", "payment": "CustomerPayment", "deduction": "Deduction"},
}
DOCUMENT_APPS = {
    "CompanyPurchaseOrder": "company_purchase_order",
    "CompanyPurchaseOrderLine": "company_purchase_order",
    "SupplierDeliveryReceipt": "supplier_delivery_receipt",
    "SupplierDeliveryReceiptLine": "supplier_delivery_receipt",
    "SupplierSalesInvoice": "supplier_sales_invoice",
    "SupplierSalesInvoiceLine": "supplier_sales_invoice",
    "CompanyPayment": "company_payment",
    "CustomerPurchaseOrder": "customer_purchase_order",
    "CustomerPurchaseOrderLine": "customer_purchase_order",
    "CompanyDeliveryReceipt": "company_delivery_receipt",
    "CompanyDeliveryReceiptLine": "company_delivery_receipt",
    "CompanySalesInvoice": "company_sales_invoice",
    "CompanySalesInvoiceLine": "company_sales_invoice",
    "CustomerPayment": "customer_payment",
}

RESOURCES = {"purchase-orders": "purchase_order", "delivery-receipts": "delivery_receipt",
             "invoices": "sales_invoice", "payments": "payment", "deductions": "deduction"}


def model(mode, name):
    if name in {'deduction', 'Deduction'}:
        return apps.get_model(mode + '_deduction', 'Deduction')
    if name == 'POReconciliation':
        return apps.get_model(mode + '_recon', 'Reconciliation')
    model_name = TARGETS[mode].get(name, name)
    app_label = DOCUMENT_APPS.get(model_name, MODULES[mode])
    # Reject a document from the other workflow even when requested by class name.
    allowed = set(TARGETS[mode].values())
    if model_name in DOCUMENT_APPS and model_name.removesuffix("Line") not in allowed:
        raise LookupError(f"{model_name} does not belong to {mode.upper()}.")
    return apps.get_model(app_label, model_name)


def accounting_mode(app_label, model_name=None):
    """Resolve document owners and the persisted AP/AR workflow names."""
    for mode, workflow in MODULES.items():
        if app_label == workflow or (app_label == mode + "_deduction" and model_name in (None, "Deduction")):
            return mode
        for name in TARGETS[mode].values():
            if DOCUMENT_APPS.get(name) == app_label and model_name in (None, name):
                return mode
    return None


def party_key(mode):
    return "customer" if mode == "ar" else "supplier"


def fields(mode, target, lines=False):
    """Only user-configurable values; provenance and parent IDs are server-owned."""
    record = model(mode, target)
    if lines:
        record = model(mode, record.__name__ + "Line")
    excluded = {"created_at", "updated_at", "imported_at", "llm_context", "received_items",
                "proof_of_delivery", "proof_of_payment", "receiving_evidence", "payment_status"}
    if target == "payment":
        excluded.remove("payment_status")
    return [field for field in record._meta.fields if not field.primary_key
            and field.name not in excluded and not field.name.startswith("source_")
            and not field.name.endswith(("_context", "_metadata"))
            and not (lines and field.is_relation)]


def required_fields(mode, target, lines=False):
    """One source of mandatory fields for setup guidance, imports and extraction."""
    if lines:
        return set()  # Items and their source fields are optional; IDs are generated.
    required = {field.name for field in fields(mode, target, lines)
                if not field.blank and not field.null and not field.has_default()}
    if not lines and target not in {'customer', 'supplier'}:
        essential = {
            'deduction': {'reference_no', 'deduction_date', 'purchase_order', 'currency', 'amount', 'category'},
            'purchase_order': {'po_reference_no', 'order_date', 'currency', 'total_amount'},
            'delivery_receipt': {'dr_reference_no', 'delivery_date'},
            'sales_invoice': {'invoice_reference_no', 'invoice_date', 'currency', 'total_amount'},
            'payment': {'payment_reference_no', 'payment_date', 'currency', 'amount_received' if mode == 'ar' else 'amount_paid'},
        }
        required.update({party_key(mode), *essential[target]})
    return required


def revision(record, extra=None):
    values = {field.name: field.value_from_object(record) for field in record._meta.fields}
    return hashlib.sha256(json.dumps([values, extra], cls=DjangoJSONEncoder, sort_keys=True).encode()).hexdigest()


def check_revision(record, value, extra=None):
    if value != revision(record, extra):
        raise ValidationError("This record changed. Reload before saving.", code="conflict")


def error_text(error):
    if isinstance(error, ValidationError):
        return "; ".join(error.messages)
    return str(error)
