"""Source provenance and matched-line protections shared by document apps."""

from __future__ import annotations

import json
from django.core.exceptions import ValidationError


def normalize_source_key(key):
    # Sorting composite keys ensures repeat imports use the same stored identity.
    return json.loads(json.dumps(key, sort_keys=True)) if key else key


def refresh_document_cases(document) -> None:
    # Changing a source document can invalidate an existing match.
    for case in document.reconciliation_cases.all():
        case.refresh_reconciliation_status()


def validate_source(record) -> None:
    """Ensure the database table and extraction logs belong to the chosen sources."""
    errors = {}
    if record.source_table_id:
        if (
            not record.source_database_id
            or record.source_table.schema.run.source_id != record.source_database_id
        ):
            errors["source_table"] = "Source table must belong to the selected database."
        if not record.source_record_key:
            errors["source_record_key"] = "Record key is required for a database table source."
        elif (
            type(record)
            .objects.filter(
                source_table_id=record.source_table_id, source_record_key=record.source_record_key
            )
            .exclude(pk=record.pk)
            .exists()
        ):
            errors["source_record_key"] = "This source record was imported already."
    for field in ("source_llm_log", "source_text_log"):
        log = getattr(record, field)
        if log and (
            not record.source_document_id or log.fk_document_no_id != record.source_document_id
        ):
            errors[field] = "Extraction log must belong to the source document."
    if errors:
        raise ValidationError(errors)


def validate_line(line) -> None:
    """Keep quantities and prices stable while a line participates in a completed match."""
    if not line.pk or not line.matches.filter(match_status="matched").exists():
        return
    previous = type(line).objects.get(pk=line.pk)
    protected = (
        "purchase_order_id",
        "delivery_receipt_id",
        "invoice_id",
        "line_no",
        "item_code",
        "unit_of_measure",
        "quantity_ordered",
        "quantity_accepted",
        "quantity_invoiced",
        "unit_price",
        "discount_amount",
        "tax_amount",
        "line_total",
    )
    if any(
        (
            hasattr(line, name) and getattr(line, name) != getattr(previous, name)
            for name in protected
        )
    ):
        raise ValidationError("Remove existing matches before changing matched line values.")
