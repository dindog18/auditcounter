"""SQLite cannot establish that supplier/customer locks serialize approvals."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless

from django.core.exceptions import ValidationError
from django.db import connection,connections
from django.test import TransactionTestCase

from accounts_receivable.matching_test_support import PartialDeliveryFixture
from .models import SKUAlias
from .services.mapping import approve_mapping,catalog_revision
from .services.products import reference,party_filter


@skipUnless(connection.vendor=='postgresql','Requires PostgreSQL row locks')
class ApprovalConcurrencyTests(PartialDeliveryFixture,TransactionTestCase):
    mode='ap'

    def test_concurrent_conflicting_approvals(self):
        for mode in ('ap','ar'):
            self.mode=mode
            if mode!='ap':
                self.setUp()
            self.fixture(receipts=(100,))
            type(self.invoice_line).objects.filter(pk=self.invoice_line.pk).update(item_code='SOURCE')
            self.invoice_line.refresh_from_db()
            other=type(self.order_line).objects.create(purchase_order=self.order_line.purchase_order,line_no=2,item_code='OTHER',unit_of_measure='pc',quantity_ordered=100,unit_price=18000,line_total=1800000)
            token=catalog_revision(self.case)
            requests=[dict(revision=token,source_reference=reference(self.invoice_line),canonical_reference=reference(line),approval_notes='Reviewed corresponding known product documents') for line in (self.order_line,other)]
            barrier=Barrier(2)
            def approve(data):
                connections.close_all()
                try:
                    case=type(self.case).objects.get(pk=self.case.pk)
                    barrier.wait(timeout=10)
                    approve_mapping(case,data)
                    return 'approved'
                except ValidationError as error:
                    return error.code
                finally:
                    connections.close_all()
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures=[pool.submit(approve,request) for request in requests]
                outcomes=[future.result(timeout=30) for future in futures]
            self.assertCountEqual(outcomes,['approved','conflict'])
            self.assertEqual(SKUAlias.objects.filter(**party_filter(self.case),status='approved').count(),1)
            self.assertEqual(SKUAlias.objects.filter(**party_filter(self.case)).count(),1)
