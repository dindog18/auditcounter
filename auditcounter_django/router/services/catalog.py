"""Independent document apps supported as routing destinations.

Lines, matches, allocations, and logs remain part of the parent workflow and
are not independent routing destinations. Existing AP/AR destinations continue
to resolve through the accounting catalog for compatibility.
"""

from django.apps import apps

MODULES = (
    ("encoder", "MCP Encoder", ("EncoderJob",)),
    ("accounts_payable", "AP · Suppliers", ("Supplier",)),
    ("company_purchase_order", "AP · Company purchase orders", ("CompanyPurchaseOrder",)),
    ("supplier_delivery_receipt", "AP · Supplier delivery receipts", ("SupplierDeliveryReceipt",)),
    ("supplier_sales_invoice", "AP · Supplier sales invoices", ("SupplierSalesInvoice",)),
    ("company_payment", "AP · Company payments", ("CompanyPayment",)),
    ("accounts_receivable", "AR · Customers", ("Customer",)),
    ("customer_purchase_order", "AR · Customer purchase orders", ("CustomerPurchaseOrder",)),
    ("company_delivery_receipt", "AR · Company delivery receipts", ("CompanyDeliveryReceipt",)),
    ("company_sales_invoice", "AR · Company sales invoices", ("CompanySalesInvoice",)),
    ("ap_deduction", "AP · Deductions", ("Deduction",)),
    ("ar_deduction", "AR · Deductions", ("Deduction",)),
    ("customer_payment", "AR · Customer payments", ("CustomerPayment",)),
)


def destination_catalog():
    """Use real model names and display labels, without reading business records."""
    modules = []
    for app_label, label, model_names in MODULES:
        targets = []
        for model_name in model_names:
            model = apps.get_model(app_label, model_name)
            targets.append({"value": model.__name__, "label": str(model._meta.verbose_name)})
        modules.append({"value": app_label, "label": label, "targets": targets})
    return modules
