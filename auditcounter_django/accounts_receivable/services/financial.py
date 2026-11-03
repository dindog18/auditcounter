"""Small shared input helpers for explicit financial workflows."""
from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError


def amount(value, *, positive=True):
    try:
        if isinstance(value, (bool, float)):
            raise ValueError
        number = Decimal(value)
        if not number.is_finite() or number < 0 or positive and number == 0 or number >= Decimal('10000000000000') or number != number.quantize(Decimal('.01')):
            raise ValueError
        return number.quantize(Decimal('.01'))
    except (TypeError, ValueError, InvalidOperation):
        raise ValidationError('Enter a finite decimal amount with at most two decimal places, within the supported balance.') from None


def text(value, label, maximum=2000, *, required=True):
    if not isinstance(value, str) or len(value)>maximum or required and not value.strip():
        raise ValidationError(f'Provide {label} of up to {maximum} characters.')
    return value.strip()


def date_value(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValidationError('Provide a valid ISO date.') from None


def body(data, allowed):
    if not isinstance(data, dict) or set(data)-set(allowed):
        raise ValidationError('The request contains unsupported fields.')
