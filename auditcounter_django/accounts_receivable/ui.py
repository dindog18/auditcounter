"""Shared AP/AR navigation and model field descriptions."""

from django.shortcuts import render, get_object_or_404, redirect
from django.middleware.csrf import get_token
from .services import pages
from .services.catalog import model, party_key, RESOURCES as RECORD_RESOURCES, fields as extraction_fields, required_fields
from django.urls import path, reverse


RESOURCES = (
    ("parties", "party", "Parties", "address-book"),
    ("purchase-orders", "purchase_order", "Purchase orders", "shopping-cart"),
    ("delivery-receipts", "delivery_receipt", "Delivery receipts", "truck"),
    ("invoices", "invoice", "Invoices", "file-invoice-dollar"),
    ("payments", "payment", "Payments", "credit-card"),
    ("deductions", "deduction", "Deductions", "minus-circle"),
    ("po-reconciliation", "po_reconciliation", "Reconciliation", "check-double"),
)

EDITABLE_RESOURCES = {"parties", "reconciliation", *RECORD_RESOURCES}


def configuration_catalog(mode):
    """Describe destination fields for the form, without querying any records."""
    ar = mode == "ar"
    app = "accounts_receivable" if ar else "accounts_payable"
    definitions = [
        ("customer" if ar else "supplier", "Customers" if ar else "Suppliers", "Customer" if ar else "Supplier", None),
        ("purchase_order", "Purchase orders", "CustomerPurchaseOrder" if ar else "CompanyPurchaseOrder", "CustomerPurchaseOrderLine" if ar else "CompanyPurchaseOrderLine"),
        ("delivery_receipt", "Delivery receipts", "CompanyDeliveryReceipt" if ar else "SupplierDeliveryReceipt", "CompanyDeliveryReceiptLine" if ar else "SupplierDeliveryReceiptLine"),
        ("sales_invoice", "Sales invoices", "CompanySalesInvoice" if ar else "SupplierSalesInvoice", "CompanySalesInvoiceLine" if ar else "SupplierSalesInvoiceLine"),
        ("payment", "Payments", "CustomerPayment" if ar else "CompanyPayment", None),
        ("deduction", "Deductions", "Deduction", None),
    ]

    def fields(model_name, lines=False):
        result = []
        excluded = {"created_at", "updated_at", "imported_at", "llm_context", "received_items", "proof_of_delivery", "proof_of_payment", "receiving_evidence"}
        target = next(key for key, _, record, line in definitions if model_name in {record, line})
        mandatory = required_fields(mode, target, lines)
        for field in extraction_fields(mode, target, lines):
            if field.primary_key or field.name in excluded or field.name.startswith("source_") or field.name.endswith(("_context", "_metadata")):
                continue
            if lines and field.is_relation:
                continue  # Parent relationships are configured through the line join.
            result.append({
                "key": field.name, "label": str(field.verbose_name).capitalize(),
                "type": "lookup" if field.is_relation else field.get_internal_type(),
                "required": field.name in mandatory,
                "choices": list(field.flatchoices) if field.choices else [],
            })
        return result

    return [{"key": key, "label": label, "model": model, "fields": fields(model), "lineModel": line_model, "lineFields": fields(line_model, True) if line_model else []} for key, label, model, line_model in definitions]


def workspace_patterns(view, party_slug, api):
    """Keep AR/AP route names parallel while using customer/supplier URLs."""
    patterns = [path("api/<str:action>/", api, name="api"), path("api/<str:action>/<int:record_id>/", api, name="api_record"), path("", view, name="overview"), path("aging/", view, {"resource": "aging"}, name="aging")]
    for resource, name, _label, _icon in (*RESOURCES, ("reconciliation", "reconciliation", "Saved line matching cases", "list")):
        slug = party_slug if resource == "parties" else resource
        patterns.extend([
            path(f"{slug}/", view, {"resource": resource}, name=f"{name}_list"),
            path(f"{slug}/<int:record_id>/", view, {"resource": resource, "screen": "detail"}, name=f"{name}_detail"),
        ])
        if resource in {"parties", *RECORD_RESOURCES}:
            for suffix, action in (("", "list"), ("new/", "create"), ("<int:record_id>/", "detail")):
                patterns.append(path(f"{slug}/configuration/{suffix}", view, {
                    "resource": resource, "screen": "list" if action == "list" else "configuration", "setup": True,
                }, name=f"configuration_{name}_{action}"))
        if resource in EDITABLE_RESOURCES:
            patterns.extend([
                path(f"{slug}/new/", view, {"resource": resource, "screen": "form"}, name=f"{name}_create"),
                path(f"{slug}/<int:record_id>/edit/", view, {"resource": resource, "screen": "form"}, name=f"{name}_edit"),
            ])
    patterns.extend([
        path("llm-logs/", view, {"resource": "llm-logs"}, name="llm_log_list"),
        path("llm-logs/<int:record_id>/", view, {"resource": "llm-logs", "screen": "detail"}, name="llm_log_detail"),
        path("configuration/", view, {"resource": "configuration"}, name="configuration_list"),
        path("configuration/new/", view, {"resource": "configuration", "screen": "configuration"}, name="configuration_create"),
        path("configuration/<int:record_id>/", view, {"resource": "configuration", "screen": "configuration"}, name="configuration_detail"),
        path("payments/<int:record_id>/allocate/", view, {"resource": "payments", "screen": "allocate"}, name="payment_allocate"),
        path("reconciliation/<int:record_id>/match/", view, {"resource": "reconciliation", "screen": "match"}, name="reconciliation_match"),
    ])
    return patterns


def render_workspace(request, mode, resource="overview", screen="list", record_id=None, setup=False):
    receivable = mode == "ar"
    namespace = "ACCOUNTS_RECEIVABLE" if receivable else "ACCOUNTS_PAYABLE"
    title = "Accounts receivable" if receivable else "Accounts payable"
    party = "Customer" if receivable else "Supplier"
    navigation = [{"key": "overview", "label": "Overview", "icon": "chart-pie", "url": reverse(f"{namespace}:overview")}]
    for key, name, label, icon in RESOURCES:
        navigation.append({"key": key, "label": party + "s" if key == "parties" else label, "icon": icon, "url": reverse(f"{namespace}:{name}_list")})
    navigation.append({"key": "aging", "label": "Aging report", "icon": "clock", "url": reverse(f"{namespace}:aging")})
    navigation.append({"key": "llm-logs", "label": "LLM activity", "icon": "history", "url": reverse(f"{namespace}:llm_log_list")})
    label = next((item["label"] for item in navigation if item["key"] == resource), title)
    if resource == "configuration":
        label = "Extraction setup"
    setup_resources = {"parties": party_key(mode), **RECORD_RESOURCES}
    setup_urls = {key: reverse(f"{namespace}:configuration_{name}_list")
                  for key, name, _, _ in RESOURCES if key in setup_resources}
    if resource == "configuration" and record_id is not None:
        profile = get_object_or_404(model(mode, "ExtractionConfiguration"), pk=record_id)
        destination = next(key for key, target in setup_resources.items() if target == profile.target_entity)
        return redirect(f"{setup_urls[destination]}{record_id}/")
    setup_target = setup_resources[resource] if setup else None
    config = {
        "mode": mode, "title": title, "party": party, "resource": "configuration" if setup else resource,
        "screen": screen, "recordId": record_id,
        "canEncode": resource in EDITABLE_RESOURCES,
        "api": reverse(f"{namespace}:api", args=["action"]), "csrfToken": get_token(request),
        "routes": {item["key"]: item["url"] for item in navigation},
        "configurationCreate": reverse(f"{namespace}:configuration_create"),
        "sources": {
            "documents": reverse("DOC_EXTRACTION:document_list"),
            "upload": reverse("DOC_EXTRACTION:document_upload"),
            "databases": reverse("DB_EXTRACTION:source_list"),
        },
    }
    config["routes"]["reconciliation"] = reverse(f"{namespace}:reconciliation_list")
    config["routes"]["configuration"] = reverse(f"{namespace}:configuration_list")
    config["extractionSetup"] = setup_urls.get(resource)
    config["setupRoutes"] = {target: setup_urls[key] for key, target in setup_resources.items()}
    if setup:
        label += " extraction setup"
        config["routes"]["configuration"] = setup_urls[resource]
        config["configurationCreate"] = setup_urls[resource] + "new/"
        config["recordRegister"] = next(item["url"] for item in navigation if item["key"] == resource)
        if record_id is not None:
            get_object_or_404(model(mode, "ExtractionConfiguration"), pk=record_id, target_entity=setup_target)
    if resource in RECORD_RESOURCES and not setup:
        from accounting_documents import manual_entry
        target = RECORD_RESOURCES[resource]
        config['manualEntry'] = manual_entry.schema(mode, target)
        if record_id is not None and screen == 'form':
            record = get_object_or_404(model(mode, target), pk=record_id)
            if manual_entry.is_manual(record):
                config['manualEntry']['values'] = manual_entry.initial_values(record, mode, target)
            else:
                config['manualEntry']['readOnly'] = True
    if setup or resource == "configuration":
        config["configurationCatalog"] = [item for item in configuration_catalog(mode) if not setup_target or item["key"] == setup_target]
    if record_id is not None and not setup:
        target = {"parties": party_key(mode), "reconciliation": "Transaction", "configuration": "ExtractionConfiguration", "llm-logs": "LLMExtractionLog", "po-reconciliation": "POReconciliation", **RECORD_RESOURCES}[resource]
        get_object_or_404(model(mode, target), pk=record_id)
    return render(request, "accounting/setup.html" if screen == "configuration" else "accounting/workspace.html", {
        "finance_state": pages.workspace_state(mode, config["resource"], record_id, setup_target),
        "page_title": f"{label} · {title}", "section": "receivables" if receivable else "payables",
        "workspace_name": title, "finance_navigation": navigation, "finance_resource": resource,
        "finance_config": config,
    })
