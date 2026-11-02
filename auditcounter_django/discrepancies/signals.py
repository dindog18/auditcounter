"""Cover queryset deletions that bypass accounting models' instance delete hooks."""
from django.apps import apps
from django.db.models import QuerySet
from django.db.models.signals import post_delete


def deleted(sender, instance, origin=None, **kwargs):
    if not isinstance(origin, QuerySet):
        return  # Instance delete methods already refresh inside their atomic operation.
    if sender.__name__ == 'DocumentMatch':
        Case = sender._meta.get_field('transaction').related_model
        for case in Case.objects.filter(pk=instance.transaction_id):
            case.refresh_reconciliation_status()
    else:
        field = next(name for name in ('purchase_order','delivery_receipt','invoice') if hasattr(instance,name+'_id'))
        Header = sender._meta.get_field(field).related_model
        for document in Header.objects.filter(pk=getattr(instance,field+'_id')):
            for case in document.reconciliation_cases.all():
                case.refresh_reconciliation_status()


for app in ('accounts_payable','accounts_receivable'):
    for model in apps.get_app_config(app).get_models():
        if model.__name__ == 'DocumentMatch' or (model.__name__.endswith('Line') and any(field.name in ('purchase_order','delivery_receipt','invoice') for field in model._meta.fields)):
            post_delete.connect(deleted, sender=model, dispatch_uid=f'finding_delete_{model._meta.label}')
