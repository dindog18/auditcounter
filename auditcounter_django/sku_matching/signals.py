"""Canonical product changes can affect cases beyond the document's own membership."""
from django.db.models.signals import post_save,post_delete


def canonical_changed(sender,instance,**kwargs):
    from accounts_receivable.services.catalog import model,party_key
    from .models import SKUAlias
    from .services.products import parent_for
    from .services.mapping import target_is_current

    mode='ap' if sender._meta.app_label=='accounts_payable' else 'ar'
    document=parent_for(instance) if sender.__name__.endswith('Line') else instance
    kind='purchase_order' if hasattr(document,'po_reference_no') else 'delivery_receipt' if hasattr(document,'dr_reference_no') else 'sales_invoice'
    aliases=SKUAlias.objects.filter(scope=mode,status='approved',canonical_reference__kind=kind,canonical_reference__record_id=document.pk)
    key=party_key(mode)+'_id'
    accounts=set()
    for alias in aliases:
        case=model(mode,'Transaction').objects.filter(**{key:getattr(alias,key)}).first()
        if case and not target_is_current(alias,case):
            accounts.add(getattr(alias,key))
    for case in model(mode,'Transaction').objects.filter(**{key+'__in':accounts}).order_by('pk'):
        case.refresh_reconciliation_status()


for app in ('accounts_payable','accounts_receivable'):
    for source in ('purchase_order','delivery_receipt','sales_invoice'):
        from accounts_receivable.services.catalog import model
        header=model('ap' if app=='accounts_payable' else 'ar',source)
        for sender in (header,header._meta.get_field('lines').related_model):
            post_save.connect(canonical_changed,sender=sender,dispatch_uid=f'sku_canonical_save_{sender._meta.label}')
            post_delete.connect(canonical_changed,sender=sender,dispatch_uid=f'sku_canonical_delete_{sender._meta.label}')
