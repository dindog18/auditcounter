from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase
from django.core.exceptions import ValidationError
from accounts_receivable.matching_test_support import PartialDeliveryFixture
from accounts_receivable.services.catalog import revision
from accounts_payable.services import credits
from document_extraction.models import Document
from .services import investigation,claims
from .models import SupplierClaim


class ClaimTests(PartialDeliveryFixture,TestCase):
    mode='ap'
    def setUp(self):
        super().setUp();self.fixture(receipts=(48,),invoiced=50)
        self.order_line.quantity_ordered=50;self.order_line.line_total=Decimal('900000');self.order_line.save()
        order=self.order_line.purchase_order;order.subtotal=order.total_amount=Decimal('900000');order.save()
        self.save()
        self.invoice=self.invoice_line.invoice;self.invoice.invoice_status='posted';self.invoice.save()
        self.case.refresh_from_db()
        investigation.start_investigation(self.case,dict(revision=investigation.investigation_revision(self.case)))
        self.finding=self.case.discrepancy_findings.get(finding_code='QUANTITY_SHORTAGE',status='open')
        investigation.review_finding(self.case,dict(revision=investigation.investigation_revision(self.case),finding_id=self.finding.pk,decision='confirmed',notes='Verified two unsupported units.'))
        self.payload=dict(revision=investigation.investigation_revision(self.case),reference='CL-1',category='quantity',claimed_amount='36000',finding_ids=[self.finding.pk],evidence_ids=list(self.finding.evidence.values_list('pk',flat=True)))

    def accepted(self):
        claim=claims.create_claim(self.case.pk,self.payload)
        claim=claims.transition(claim.pk,dict(revision=revision(claim),status='submitted',notes='Submitted manually.'))
        return claims.transition(claim.pk,dict(revision=revision(claim),status='accepted',notes='Supplier confirmed correction.',accepted_amount='36000'))

    def test_appliance_claim_credit_and_verified_resolution(self):
        claim=self.accepted()
        doc=Document.objects.create(file_name='credit.pdf',storage_path='synthetic.pdf',document_type='credit')
        credit=credits.create_credit(dict(supplier_id=self.party.pk,reference='CN-36',issue_date='2026-11-02',currency='PHP',credit_amount='36000',source_document_id=doc.pk))
        credit=credits.verify_credit(credit.pk,dict(revision=credits.credit_revision(credit),notes='Supplier credit verified.'))
        application=credits.apply_credit(credit.pk,dict(revision=credits.credit_revision(credit),invoice_id=self.invoice.pk,amount='36000',request_key='claim',application_date='2026-11-02',notes='Claim credit.'))
        claim=claims.resolve(claim.pk,dict(revision=revision(claim),resolution_type='credit_verified',notes='Verified applied correction.',application_id=application.pk))
        self.assertEqual(claim.status,'resolved');self.assertEqual(self.invoice.outstanding_balance,Decimal('864000'))
        self.finding.refresh_from_db();self.assertEqual(self.finding.status,'open')
        self.assertTrue(self.case.timeline_events.filter(event_type='claim_changed').exists())
        credits.reverse_application(application.pk,dict(revision=credits.credit_revision(credit),reason='Credit was issued for the wrong invoice.'))
        claim.refresh_from_db();self.assertTrue(claim.review_required)
        self.assertEqual(claim.status,'resolved');self.assertEqual(self.invoice.outstanding_balance,Decimal('900000'))

    def test_invalid_closure_and_duplicate_claim_are_atomic(self):
        claim=self.accepted()
        with self.assertRaises(ValidationError):claims.resolve(claim.pk,dict(revision=revision(claim),resolution_type='no_recovery',notes='Unsupported'))
        with self.assertRaises(ValidationError):claims.create_claim(self.case.pk,{**self.payload,'reference':'CL-2','revision':investigation.investigation_revision(self.case)})
        self.assertEqual(SupplierClaim.objects.count(),1);claim.refresh_from_db();self.assertEqual(claim.status,'accepted')

    def test_correspondence_is_not_sent_and_is_preserved(self):
        claim=self.accepted();before=self.case.investigation.activities.count()
        claim=claims.correspond(claim.pk,dict(revision=revision(claim),direction='incoming',subject='Credit',message='Correction accepted',occurred_at='2026-11-02T10:00:00+08:00',actor_label='Unverified label'))
        self.assertEqual(claim.correspondence.count(),1);self.assertEqual(self.case.investigation.activities.count(),before)
        item=claim.correspondence.get()
        with self.assertRaises(ValidationError):item.delete()
        self.assertIn('has not been sent',claims.serialize(claim)['draft'])

    def test_stale_transition_and_failed_timeline_do_not_change_claim(self):
        claim=claims.create_claim(self.case.pk,self.payload)
        with self.assertRaises(ValidationError):claims.transition(claim.pk,dict(revision='stale',status='submitted',notes='Submit'))
        with patch('discrepancies.services.claims.record_transition',side_effect=ValidationError('interrupted')):
            with self.assertRaises(ValidationError):claims.transition(claim.pk,dict(revision=revision(claim),status='submitted',notes='Submit'))
        claim.refresh_from_db();self.assertEqual(claim.status,'draft')

    def test_claim_currency_cannot_be_rewritten_through_case(self):
        claim=self.accepted()
        self.case.currency='USD'
        with self.assertRaises(ValidationError):self.case.save()
        claim.refresh_from_db();self.assertEqual(claim.currency,'PHP')
