from django.apps import AppConfig


class SkuMatchingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'sku_matching'

    def ready(self):
        from . import signals  # noqa: F401
