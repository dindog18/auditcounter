from django.apps import AppConfig


class ApReconConfig(AppConfig):
    name = 'ap_recon'

    def ready(self):
        from accounting_documents.reconciliation import connect_signals
        connect_signals('ap')
