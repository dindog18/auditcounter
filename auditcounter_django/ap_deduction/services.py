"""AP deduction validation uses the supplier workflow."""
from accounting_documents.deductions import lock_deduction, validate_deduction


def lock(record):
    return lock_deduction(record, 'ap')


def validate(record):
    return validate_deduction(record, 'ap')
