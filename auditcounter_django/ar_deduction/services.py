"""AR deduction validation uses the customer workflow."""
from accounting_documents.deductions import lock_deduction, validate_deduction


def lock(record):
    return lock_deduction(record, 'ar')


def validate(record):
    return validate_deduction(record, 'ar')
