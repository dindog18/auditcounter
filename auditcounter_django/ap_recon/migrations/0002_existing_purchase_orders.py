from django.db import migrations


def create_cases(apps, schema_editor):
    Order = apps.get_model('company_purchase_order', 'CompanyPurchaseOrder')
    Case = apps.get_model('ap_recon', 'Reconciliation')
    alias = schema_editor.connection.alias
    for order in Order.objects.using(alias).iterator():
        Case.objects.using(alias).get_or_create(purchase_order_id=order.pk,
            defaults={'status': 'cancelled' if order.status == 'cancelled' else 'awaiting_delivery'})


class Migration(migrations.Migration):
    dependencies = [('ap_recon', '0001_initial'), ('ap_deduction', '0001_initial'),
                    ('supplier_delivery_receipt', '0002_supplierdeliveryreceipt_purchase_order'),
                    ('supplier_sales_invoice', '0002_suppliersalesinvoice_purchase_order')]
    operations = [migrations.RunPython(create_cases, migrations.RunPython.noop)]
