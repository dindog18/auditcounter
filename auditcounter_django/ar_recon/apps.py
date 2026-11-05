from django.apps import AppConfig


class ArReconConfig(AppConfig):
    name = 'ar_recon'

    def ready(self):
        from accounting_documents.reconciliation import connect_signals
        connect_signals('ar')
