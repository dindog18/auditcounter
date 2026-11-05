"""Recalculate the AP case from its explicitly linked documents."""
from accounting_documents.reconciliation import refresh_case


def refresh(case):
    return refresh_case(case, 'ap')
