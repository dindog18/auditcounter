from django.db import migrations


def create_cases(apps, schema_editor):
    Order = apps.get_model('customer_purchase_order', 'CustomerPurchaseOrder')
    Case = apps.get_model('ar_recon', 'Reconciliation')
    alias = schema_editor.connection.alias
    for order in Order.objects.using(alias).iterator():
        Case.objects.using(alias).get_or_create(purchase_order_id=order.pk,
            defaults={'status': 'cancelled' if order.status == 'cancelled' else 'awaiting_delivery'})


class Migration(migrations.Migration):
    dependencies = [('ar_recon', '0001_initial'), ('ar_deduction', '0001_initial'),
                    ('company_delivery_receipt', '0002_companydeliveryreceipt_purchase_order'),
                    ('company_sales_invoice', '0002_companysalesinvoice_purchase_order')]
    operations = [migrations.RunPython(create_cases, migrations.RunPython.noop)]
