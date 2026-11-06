from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ar_recon", "0003_reconciliation_reference_reviews")]

    operations = [
        migrations.AddField(
            model_name="reconciliation",
            name="delivery_reviews",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
