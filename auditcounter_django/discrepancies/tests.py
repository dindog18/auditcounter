from datetime import datetime, timezone
from django.db import IntegrityError, transaction
from django.test import TestCase
from accounts_payable.models import Transaction as APTransaction
from accounts_receivable.models import Transaction as ARTransaction
from .models import DiscrepancyFinding
from .services import build_finding_fingerprint


class FindingIntegrityTests(TestCase):
    def values(self):
        return dict(fingerprint='stable',finding_code='MISSING_PO',severity='information',summary='Missing PO',first_detected_at=datetime.now(timezone.utc),last_detected_at=datetime.now(timezone.utc))

    def test_exactly_one_case_and_unique_identity_enforced_by_database(self):
        ap, ar = APTransaction.objects.create(), ARTransaction.objects.create()
        for parents in ({},{'ap_transaction':ap,'ar_transaction':ar}):
            with self.assertRaises(IntegrityError), transaction.atomic():
                DiscrepancyFinding.objects.create(**parents,**self.values())
        first = DiscrepancyFinding.objects.create(ap_transaction=ap,**self.values())
        with self.assertRaises(IntegrityError), transaction.atomic():
            DiscrepancyFinding.objects.create(ap_transaction=ap,**self.values())
        DiscrepancyFinding.objects.create(ar_transaction=ar,**self.values())
        self.assertTrue(DiscrepancyFinding.objects.filter(pk=first.pk).exists())

    def test_fingerprint_ignores_changing_amounts(self):
        case = APTransaction.objects.create()
        finding = dict(finding_code='PRICE_VARIANCE',identity={'invoice_line_id':1,'purchase_order_line_id':2},difference_amount='10')
        fingerprint = build_finding_fingerprint(finding,case)
        finding['difference_amount']='50'
        self.assertEqual(build_finding_fingerprint(finding,case),fingerprint)
        finding['identity']['purchase_order_line_id']=3
        self.assertNotEqual(build_finding_fingerprint(finding,case),fingerprint)
