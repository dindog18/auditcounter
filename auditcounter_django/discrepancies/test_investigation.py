from datetime import datetime, timezone
from django.db import IntegrityError, transaction
from django.test import TestCase
from accounts_payable.models import Transaction as APTransaction
from accounts_receivable.models import Transaction as ARTransaction
from .models import CaseInvestigation


class InvestigationIntegrityTests(TestCase):
    def test_database_ownership_uniqueness_and_closure_constraints(self):
        ap,ar=APTransaction.objects.create(),ARTransaction.objects.create()
        for fields in ({},{'ap_transaction':ap,'ar_transaction':ar},
                       {'ap_transaction':ap,'workflow_status':'resolved'},
                       {'ap_transaction':ap,'workflow_status':'investigating','closed_at':datetime.now(timezone.utc)}):
            with self.assertRaises(IntegrityError),transaction.atomic():
                CaseInvestigation.objects.create(**fields)
        CaseInvestigation.objects.create(ap_transaction=ap)
        with self.assertRaises(IntegrityError),transaction.atomic():
            CaseInvestigation.objects.create(ap_transaction=ap)
        CaseInvestigation.objects.create(ar_transaction=ar)
        self.assertEqual(CaseInvestigation.objects.count(),2)
