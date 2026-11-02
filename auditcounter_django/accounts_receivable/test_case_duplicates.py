from io import StringIO
from unittest import skipUnless
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.core.exceptions import ValidationError
from django.db import connection,connections
from django.test import TestCase,TransactionTestCase
from django.core.management import call_command
from .matching_test_support import PartialDeliveryFixture
from .services import records
from .services.catalog import model,party_key,revision
from .services.case_duplicates import find_exact_duplicate_case,find_overlapping_cases,historical_duplicates
from discrepancies.models import DiscrepancyFinding,FindingEvidence,CaseActivity,CaseInvestigation
from discrepancies.services.investigation import start_investigation,investigation_revision

class DuplicateScenarios(PartialDeliveryFixture):
    def case_data(self,**changes):
        data=dict(partyId=self.party.pk,currency='PHP',date='2026-11-02',orderIds=[self.order_line.purchase_order_id],receiptIds=[line.delivery_receipt_id for line in self.receipt_lines],invoiceIds=[self.invoice_line.invoice_id])
        data.update(changes)
        return data

    def test_exact_ordering_notes_and_api_conflict(self):
        self.fixture()
        body=self.case_data(receiptIds=list(reversed(self.case_data()['receiptIds'])),notes='Different notes',date='2026-12-01')
        with self.assertRaises(ValidationError) as error: records.save_case(self.mode,body)
        self.assertEqual(error.exception.code,'conflict')
        base='/accounts-payable/' if self.mode=='ap' else '/accounts-receivable/'
        response=self.client.post(base+'api/reconciliation/',body,content_type='application/json')
        self.assertEqual(response.status_code,409,response.content)
        self.assertEqual(response.json()['existing_case_id'],self.case.pk)
        self.assertEqual(response.json()['existing_case_url'],base+f'reconciliation/{self.case.pk}/')
        self.assertEqual(type(self.case).objects.count(),1)

    def test_unchanged_edit_and_legitimate_partial_overlap(self):
        self.fixture()
        body=self.case_data(revision=revision(self.case,records.case_membership(self.case)))
        records.save_case(self.mode,body,self.case.pk)
        partial=records.save_case(self.mode,self.case_data(receiptIds=[self.receipt_lines[0].delivery_receipt_id]))
        overlap=find_overlapping_cases(self.mode,self.party.pk,'PHP',records.case_membership(partial),partial.pk)
        self.assertEqual(overlap[0]['existing_case_id'],self.case.pk)
        self.assertFalse(overlap[0]['exact'])
        self.assertTrue(overlap[0]['overlapping_documents']['sales_invoices'])
        self.assertEqual(type(self.case).objects.count(),2)

    def test_rejected_edit_preserves_allocations_findings_evidence_history(self):
        self.fixture()
        partial=records.save_case(self.mode,self.case_data(receiptIds=[self.receipt_lines[0].delivery_receipt_id]))
        data=dict(revision=revision(partial,[records.case_membership(partial),records.matches(partial)]),matches=[dict(invoiceLineId=self.invoice_line.pk,orderLineId=self.order_line.pk,receiptLineId=self.receipt_lines[0].pk,quantity='60')])
        records.save_matches(self.mode,partial.pk,data)
        partial.refresh_from_db()
        start_investigation(partial,{'revision':investigation_revision(partial)})
        before=(records.matches(partial),records.case_membership(partial),*[list(cls.objects.values()) for cls in (DiscrepancyFinding,FindingEvidence,CaseInvestigation,CaseActivity)])
        with self.assertRaises(ValidationError):records.save_case(self.mode,self.case_data(revision=revision(partial,records.case_membership(partial))),partial.pk)
        after=(records.matches(partial),records.case_membership(partial),*[list(cls.objects.values()) for cls in (DiscrepancyFinding,FindingEvidence,CaseInvestigation,CaseActivity)])
        self.assertEqual(before,after)

    def test_different_invoices_multiple_invoices_and_missing_evidence(self):
        self.fixture()
        invoice=self.invoice_line.invoice
        invoice.pk=None;invoice.invoice_reference_no='SECOND';invoice.save()
        other=records.save_case(self.mode,self.case_data(invoiceIds=[invoice.pk]))
        multiple=records.save_case(self.mode,self.case_data(invoiceIds=[invoice.pk,self.invoice_line.invoice_id]))
        gap=records.save_case(self.mode,self.case_data(orderIds=[],receiptIds=[],invoiceIds=[invoice.pk]))
        self.assertNotEqual(other.pk,multiple.pk)
        self.assertIsNotNone(find_exact_duplicate_case(self.mode,self.party.pk,'PHP',records.case_membership(gap)))
        with self.assertRaises(ValidationError):records.save_case(self.mode,self.case_data(orderIds=[],receiptIds=[],invoiceIds=[invoice.pk]))
        with self.assertRaises(ValidationError):records.save_case(self.mode,self.case_data(invoiceIds=[]))

    def test_historical_diagnostic_read_only_and_scope(self):
        self.fixture()
        legacy=type(self.case).objects.create(**{party_key(self.mode):self.party},currency='PHP')
        for key,ids in records.case_membership(self.case).items():getattr(legacy,key).set(ids)
        before=records.case_membership(legacy)
        def guard(execute,sql,params,many,context):
            self.assertTrue(sql.lstrip().upper().startswith('SELECT'),sql)
            return execute(sql,params,many,context)
        with connection.execute_wrapper(guard):
            groups=list(historical_duplicates(self.mode))
            out=StringIO();call_command('verify_duplicate_cases',module=self.mode,stdout=out)
        self.assertEqual(groups[0]['case_ids'],[self.case.pk,legacy.pk])
        self.assertEqual(before,records.case_membership(legacy))
        self.assertIsNone(find_exact_duplicate_case(self.mode,self.party.pk,'USD',before))
        self.assertIsNone(find_exact_duplicate_case('ar' if self.mode=='ap' else 'ap',self.party.pk,'PHP',before))

class APDuplicateTests(DuplicateScenarios,TestCase): mode='ap'
class ARDuplicateTests(DuplicateScenarios,TestCase): mode='ar'

@skipUnless(connection.vendor=='postgresql','Requires PostgreSQL row locking')
class DuplicateConcurrencyTests(PartialDeliveryFixture,TransactionTestCase):
    mode='ap'
    def run_race(self,requests):
        barrier=Barrier(2);mode=self.mode
        def save(request):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                records.save_case(mode,request[0],request[1])
                return 'saved'
            except ValidationError as error:return error.code
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(save,row) for row in requests]
            return [future.result(timeout=30) for future in futures]
    def exercise(self,kind):
        for mode in ('ap','ar'):
            self.mode=mode
            if mode=='ar':self.setUp()
            self.fixture()
            data=dict(partyId=self.party.pk,currency='PHP',date='2026-11-02',orderIds=[self.order_line.purchase_order_id],receiptIds=[self.receipt_lines[0].delivery_receipt_id],invoiceIds=[self.invoice_line.invoice_id])
            other=dict(data)
            case_id=None
            if kind=='different':other['receiptIds']=[self.receipt_lines[1].delivery_receipt_id]
            if kind=='edit':
                self.save();self.case.refresh_from_db()
                start_investigation(self.case,{'revision':investigation_revision(self.case)})
                data.update(receiptIds=[line.delivery_receipt_id for line in self.receipt_lines],revision=revision(self.case,records.case_membership(self.case)),notes='first')
                other=dict(data,notes='second');case_id=self.case.pk
            before=records.matches(self.case);history=list(CaseActivity.objects.values())
            outcomes=self.run_race([(data,case_id),(other,case_id)])
            self.assertCountEqual(outcomes,['saved','saved'] if kind=='different' else ['saved','conflict'])
            self.assertEqual(type(self.case).objects.filter(**{party_key(mode):self.party}).count(),3 if kind=='different' else 1 if kind=='edit' else 2)
            self.assertEqual(records.matches(self.case),before)
            self.assertEqual(list(CaseActivity.objects.values()),history)
            self.assertFalse(list(historical_duplicates(mode)))
    def test_identical_creation(self):self.exercise('identical')
    def test_different_creation(self):self.exercise('different')
    def test_conflicting_edits(self):self.exercise('edit')
