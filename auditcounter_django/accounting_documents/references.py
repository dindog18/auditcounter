"""Preserve and review the PO reference supplied on a receipt or invoice."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from accounts_receivable.services.catalog import check_revision, model, party_key

DOCUMENTS = {'delivery-receipts': 'delivery_receipt', 'invoices': 'sales_invoice'}


def comparable(value):
    return ''.join(character for character in value.casefold() if character.isalnum())


def same_reference(expected, reported):
    return bool(comparable(expected)) and comparable(expected) == comparable(reported)


def document_references(order, receipts, invoices, reviews):
    checks = []
    for resource, rows, reference_field in (
        ('delivery-receipts', receipts, 'dr_reference_no'),
        ('invoices', invoices, 'invoice_reference_no'),
    ):
        for row in rows:
            key = f'{resource}:{row.pk}'
            reported = row.reported_po_reference
            expected = order.po_reference_no
            evidence = {'expected': expected, 'reported': reported}
            can_review = bool(reported and expected != reported and same_reference(expected, reported))
            review = reviews.get(key, {})
            reason = review.get('reason', '') if can_review and review.get('evidence') == evidence else ''
            checks.append({
                'key': key, 'resource': resource, 'id': row.pk,
                'reference': getattr(row, reference_field) or f'#{row.pk}',
                **evidence, 'canReview': can_review, 'reason': reason,
                'status': 'linked' if not reported else 'exact' if reported == expected else
                          'reviewed' if reason else 'format' if can_review else 'conflict',
            })
    return checks


def unlinked_candidates(order, mode):
    """Surface similar references only within the account and currency scope."""
    account_id = getattr(order, party_key(mode) + '_id')
    if not account_id:
        return
    account = {party_key(mode) + '_id': account_id}
    for resource, target in DOCUMENTS.items():
        rows = model(mode, target).objects.filter(purchase_order__isnull=True, **account)
        if target == 'sales_invoice':
            rows = rows.filter(currency=order.currency).exclude(invoice_status='void')
        reference_field = 'dr_reference_no' if target == 'delivery_receipt' else 'invoice_reference_no'
        for pk, reference, reported in rows.exclude(reported_po_reference='').values_list(
            'pk', reference_field, 'reported_po_reference',
        ):
            if same_reference(order.po_reference_no, reported):
                yield {'resource': resource, 'id': pk, 'reference': reference or f'#{pk}', 'reported': reported}


@transaction.atomic
def save_reference_review(mode, case_id, data):
    Case = model(mode, 'POReconciliation')
    initial = get_object_or_404(Case.objects.select_related('purchase_order'), pk=case_id)
    order = initial.purchase_order
    party = party_key(mode)
    account_id = getattr(order, party + '_id')
    if not account_id:
        raise ValidationError('Set the PO account before reviewing references.')
    model(mode, party).objects.select_for_update().get(pk=account_id)

    resource, record_id, reason = data.get('resource'), data.get('documentId'), data.get('reason')
    if not isinstance(resource, str) or resource not in DOCUMENTS or type(record_id) is not int:
        raise ValidationError('Choose a delivery receipt or invoice linked to this PO.')
    if not isinstance(reason, str) or len(reason.strip()) > 500:
        raise ValidationError('Enter a review note of up to 500 characters.')
    row = get_object_or_404(model(mode, DOCUMENTS[resource]).objects.select_for_update(),
                            pk=record_id, purchase_order=order)
    order = type(order).objects.select_for_update().get(pk=order.pk)
    case = Case.objects.select_for_update().get(pk=case_id)
    check_revision(case, data.get('revision'))
    reported = row.reported_po_reference
    if (order.status == 'cancelled' or getattr(row, 'invoice_status', '') == 'void'
            or getattr(row, party + '_id') != getattr(order, party + '_id')
            or getattr(row, 'currency', order.currency) != order.currency
            or reported == order.po_reference_no or not same_reference(order.po_reference_no, reported)):
        raise ValidationError('Only formatting differences on active linked documents can be accepted.')
    key = f'{resource}:{row.pk}'
    if reason.strip():
        case.reference_reviews[key] = {
            'evidence': {'expected': order.po_reference_no, 'reported': reported},
            'reason': reason.strip(), 'reviewedAt': timezone.now().isoformat(),
        }
    else:
        case.reference_reviews.pop(key, None)
    case.save(update_fields=['reference_reviews'])
    case.refresh()
    return case
