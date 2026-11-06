# Shared accounting document services

This Python package holds common accounting rules used by AP and AR. Concrete document and reconciliation models live in their owning Django apps. Callers select the workflow explicitly with `ap` or `ar`.

## Flow

1. [manual_entry.py](manual_entry.py) resolves the target through the AP/AR catalog, validates the header and optional lines, and saves them together. [services.py](services.py) validates provenance and protects linked records. [amounts.py](amounts.py) checks line arithmetic.
2. Document changes trigger [reconciliation.py](reconciliation.py) to refresh the affected purchase order case. The calculation uses linked receipts and invoices, review evidence, applied deductions and cleared allocations.
3. [references.py](references.py), [delivery_review.py](delivery_review.py) and [line_review.py](line_review.py) save review decisions against the current case. [unserved.py](unserved.py) records or clears closure of eligible remaining PO quantities.
4. [deductions.py](deductions.py) validates deduction scope and the available invoice balance. The invoice and payment apps apply their own settlement and allocation rules.

See the [accounting model ownership map](../../docs/accounting-document-apps.md) and [PO reconciliation workflow](../../docs/accounting-reconciliation.md).
