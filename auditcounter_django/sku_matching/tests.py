import json
from unittest.mock import AsyncMock, patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, SimpleTestCase, Client

from accounts_receivable.matching_test_support import PartialDeliveryFixture
from accounts_receivable.services import records, pages
from accounts_receivable.services.auto_matching import generate_match_suggestions, source_revision, allocation_row
from accounts_receivable.services.catalog import model, party_key, revision
from .models import SKUAlias, SKUSuggestionAttempt
from .services import mapping, suggestions
from .services.normalization import normalize_sku, normalize_description, normalize_unit
from .services.products import product, reference, parent_for, party_filter
from .services.presentation import workspace_state


class NormalizationTests(SimpleTestCase):
    def test_formatting_preserves_identity(self):
        self.assertEqual(normalize_sku('  WM-8KG\t  002 '),'wm-8kg 002')
        self.assertEqual(normalize_sku('e\u0301'),'é')
        self.assertEqual(normalize_description(' Samsung  Washer '),'samsung washer')
        for left,right in [('WM-8KG','WM-9KG'),('0001','1'),('WM-8KG','WM8KG'),('A-220V','A-110V')]:
            self.assertNotEqual(normalize_sku(left),normalize_sku(right))

    def test_only_explicit_unit_formatting(self):
        self.assertEqual(normalize_unit(' PCS. '),normalize_unit('pieces'))
        self.assertEqual(normalize_unit('KGS'),'kg')
        self.assertNotEqual(normalize_unit('pcs'),normalize_unit('box'))
        self.assertNotEqual(normalize_unit('kg'),normalize_unit('g'))
        self.assertNotEqual(normalize_unit('ea'),normalize_unit('pc'))


class SKUScenarios(PartialDeliveryFixture):
    def ready(self,**kwargs):
        self.fixture(**kwargs)
        for line in [self.invoice_line,*self.receipt_lines]:
            type(line).objects.filter(pk=line.pk).update(item_code='WW80T',description='Samsung model WW80T 8kg 220V',unit_of_measure='PCS')
            line.refresh_from_db()
        type(self.order_line).objects.filter(pk=self.order_line.pk).update(item_code='SAMSUNG-WW80T-8KG',description='Samsung model WW80T 8kg 220V',unit_of_measure='pcs')
        self.order_line.refresh_from_db()
        type(self.order_line.purchase_order).objects.filter(pk=self.order_line.purchase_order_id).update(status='open')
        type(self.invoice_line.invoice).objects.filter(pk=self.invoice_line.invoice_id).update(invoice_status='posted')
        for line in self.receipt_lines:
            type(line.delivery_receipt).objects.filter(pk=line.delivery_receipt_id).update(**{'receipt_status' if self.mode=='ap' else 'delivery_status':'accepted' if self.mode=='ap' else 'delivered'})
        self.case.refresh_from_db()

    def approval(self,**changes):
        return dict(revision=mapping.catalog_revision(self.case),source_reference=reference(self.invoice_line),canonical_reference=reference(self.order_line),approval_notes='Verified model, capacity and source product documents.',**changes)

    def review(self,alias,**changes):
        return dict(revision=mapping.catalog_revision(self.case),alias_id=alias.pk,alias_revision=revision(alias),**changes)

    def ai_request(self):
        return dict(revision=mapping.catalog_revision(self.case),source_reference=reference(self.invoice_line))

    def ai_output(self,**changes):
        candidate=suggestions.find_product_candidates(self.invoice_line,self.case)[0]
        return dict(source_sku='WW80T',candidate_id=candidate['candidate_id'],suggested_sku=candidate['product']['code'],matched_attributes=candidate['shared_attributes'],reason='Known model, capacity and voltage agree; review the source documents.',requires_review=True,**changes)

    def request_ai(self,response=None,error=None):
        env={f'ACCOUNTS_{"PAYABLE" if self.mode=="ap" else "RECEIVABLE"}_OLLAMA_MODEL':'sku-test'}
        transport=AsyncMock(side_effect=error,return_value={'message':{'content':json.dumps(response if response is not None else self.ai_output())}})
        with patch.object(suggestions,'get_env',side_effect=lambda key,default='':env.get(key,default)),patch.object(suggestions,'invoke_with_llm',transport):
            attempt=suggestions.suggest_sku_equivalence(self.case,self.ai_request())
        return attempt,transport

    def test_exact_normalized_skus_without_ai(self):
        self.ready()
        type(self.order_line).objects.filter(pk=self.order_line.pk).update(item_code=' ww80t ')
        self.order_line.refresh_from_db()
        with patch.object(suggestions,'invoke_with_llm') as transport:
            self.assertTrue(mapping.compare_products(self.invoice_line,self.order_line,self.case)['equivalent'])
            self.save()
            self.assertEqual(self.case.calculate_reconciliation()[0],'matched')
            transport.assert_not_called()

    def test_unknown_pending_and_rejected_are_not_identity(self):
        self.ready()
        self.assertFalse(mapping.compare_products(self.invoice_line,self.order_line,self.case)['equivalent'])
        with self.assertRaises(ValidationError):
            self.save()
        alias=mapping.pending_alias(self.case,self.invoice_line,self.order_line,'Unverified proposal')
        self.assertFalse(mapping.compare_products(self.invoice_line,self.order_line,self.case)['equivalent'])
        mapping.reject_mapping(self.case,self.review(alias,reason='Insufficient evidence'))
        alias.refresh_from_db()
        self.assertEqual(alias.status,'rejected')
        self.assertEqual(len(alias.history),2)
        self.assertFalse(mapping.compare_products(self.invoice_line,self.order_line,self.case)['equivalent'])

    def test_approval_split_deliveries_reuse_and_evidence(self):
        self.ready()
        alias=mapping.approve_mapping(self.case,self.approval())
        self.assertEqual(alias.status,'approved')
        with patch.object(suggestions,'invoke_with_llm') as provider:
            result=generate_match_suggestions(self.case)
            self.assertEqual(len(result['suggestions']),2)
            self.assertIn('Approved scoped SKU equivalence',' '.join(result['suggestions'][0]['reasons']))
            self.save()
            provider.assert_not_called()
        self.assertEqual(self.case.calculate_reconciliation()[0],'matched')
        for match in self.case.line_matches.all():
            self.assertEqual(match.sku_identity_snapshot['mappings'][0]['id'],alias.pk)
            self.assertEqual(match.sku_identity_snapshot['mappings'][0]['canonical_reference'],reference(self.order_line))
        self.invoice_line.refresh_from_db()
        self.assertEqual(self.invoice_line.item_code,'WW80T')
        self.assertEqual(self.order_line.item_code,'SAMSUNG-WW80T-8KG')
        # Future source lines reuse the scoped approval, without any proposal or new product.
        invoice=self.invoice_line.invoice
        invoice.pk=None;invoice.invoice_reference_no='FUTURE';invoice.save()
        future=type(self.invoice_line).objects.create(invoice=invoice,line_no=1,item_code=' ww80t ',description=self.invoice_line.description,unit_of_measure='pieces',quantity_invoiced=1,unit_price=18000,line_total=18000)
        self.assertTrue(mapping.compare_products(future,self.order_line,self.case)['equivalent'])

    def test_identity_never_bypasses_financial_or_quantity_validation(self):
        self.ready(receipts=(100,),invoice_price=18500)
        mapping.approve_mapping(self.case,self.approval())
        with self.assertRaises(ValidationError):
            self.save(self.payload([120]))
        self.assertFalse(self.case.line_matches.exists())
        self.save()
        result=self.service.evaluate_reconciliation(self.case)
        self.assertEqual(result['lines'][0]['unmatched'],0)
        self.assertEqual(result['priceVariance'],50000)
        self.assertEqual(result['status'],'exception')
        self.assertEqual(result,records.preview_matches(self.mode,self.case.pk,self.payload()))
        # Unit equivalence cannot bypass currency and party relationships.
        invoice=self.invoice_line.invoice
        type(invoice).objects.filter(pk=invoice.pk).update(currency='USD')
        with self.assertRaises(ValidationError):
            self.save()

    def test_deactivation_recalculates_preserves_proof_and_stales_auto(self):
        self.ready()
        alias=mapping.approve_mapping(self.case,self.approval())
        proposed=generate_match_suggestions(self.case)
        before=source_revision(self.case)
        self.save()
        proof=self.case.line_matches.first().sku_identity_snapshot
        mapping.deactivate_mapping(self.case,self.review(alias,reason='Equivalence needs renewed verification.'))
        alias.refresh_from_db();self.case.refresh_from_db()
        self.assertEqual(alias.status,'deactivated')
        self.assertNotEqual(source_revision(self.case),before)
        self.assertEqual(self.case.line_matches.first().sku_identity_snapshot,proof)
        self.assertFalse(mapping.compare_products(self.invoice_line,self.order_line,self.case)['equivalent'])
        self.assertNotEqual(self.case.reconciliation_status,'matched')
        self.assertEqual([e['action'] for e in alias.history],['proposed','approved','deactivated'])
        with self.assertRaises(ValidationError):
            records.save_matches(self.mode,self.case.pk,dict(revision=self.payload()['revision'],suggestionRevision=proposed['suggestion_revision'],preserveExisting=True,matches=[allocation_row(row) for row in proposed['suggestions']]))

    def test_target_changes_disable_mapping_without_overwriting_history(self):
        self.ready()
        alias=mapping.approve_mapping(self.case,self.approval())
        snapshot=alias.canonical_snapshot
        type(self.order_line).objects.filter(pk=self.order_line.pk).update(description='Different product information')
        self.order_line.refresh_from_db()
        self.assertFalse(mapping.compare_products(self.invoice_line,self.order_line,self.case)['equivalent'])
        alias.refresh_from_db()
        self.assertEqual(alias.canonical_snapshot,snapshot)
        self.assertFalse(workspace_state(self.case)['aliases'][0]['target_current'])

    def test_canonical_source_outside_case_refreshes_dependent_case(self):
        self.ready()
        document=self.order_line.purchase_order
        document.pk=None;document.po_reference_no='CATALOG-REFERENCE';document.save()
        target=type(self.order_line).objects.create(purchase_order=document,line_no=1,item_code=self.order_line.item_code,description=self.order_line.description,unit_of_measure='PCS',quantity_ordered=100,unit_price=18000,line_total=1800000)
        body=self.approval();body['canonical_reference']=reference(target)
        alias=mapping.approve_mapping(self.case,body)
        self.save()
        self.case.refresh_from_db()
        self.assertEqual(self.case.reconciliation_status,'matched')
        self.assertFalse(document.reconciliation_cases.exists())
        target.description='Samsung model WW80T 8kg 220V revised information'
        target.save()
        self.case.refresh_from_db()
        self.assertNotEqual(self.case.reconciliation_status,'matched')
        alias.refresh_from_db()
        self.assertNotEqual(alias.canonical_snapshot['description'],target.description)

    def test_original_provenance_is_retained_and_changed_target_requires_review(self):
        self.ready()
        order=self.order_line.purchase_order
        type(order).objects.filter(pk=order.pk).update(source_record_key={'product':'original-reference'})
        alias=mapping.approve_mapping(self.case,self.approval())
        self.assertEqual(alias.canonical_snapshot['provenance']['source_record_key'],{'product':'original-reference'})
        type(order).objects.filter(pk=order.pk).update(source_record_key={'product':'changed-reference'})
        self.assertFalse(mapping.target_is_current(alias,self.case))
        alias.refresh_from_db()
        self.assertEqual(alias.canonical_snapshot['provenance']['source_record_key'],{'product':'original-reference'})

    def test_mapping_scope_party_namespace_and_units(self):
        self.ready()
        mapping.approve_mapping(self.case,self.approval())
        context=dict(mapping.context_for(self.invoice_line,self.case),case=self.case)
        self.assertIsNotNone(mapping.find_approved_mapping('WW80T',context))
        self.assertIsNone(mapping.find_approved_mapping('WW80T',dict(context,source_system='erp:999')))
        self.assertIsNone(mapping.find_approved_mapping('WW80T',dict(context,unit='BOX')))
        key=party_key(self.mode)
        other=model(self.mode,key).objects.create(**{key+'_code':'OTHER-SKU',key+'_name':'Other supplier/customer'})
        self.assertIsNone(mapping.find_approved_mapping('WW80T',dict(context,**{key+'_id':other.pk})))
        self.assertIsNone(mapping.find_approved_mapping('WW80T',dict(context,scope='ar' if self.mode=='ap' else 'ap')))

    def test_conflicting_approvals_are_atomic_and_db_constrained(self):
        self.ready()
        alias=mapping.approve_mapping(self.case,self.approval())
        with self.assertRaises(ValidationError):
            mapping.approve_mapping(self.case,self.approval())
        self.assertEqual(SKUAlias.objects.filter(**party_filter(self.case)).count(),1)
        values={field.name:getattr(alias,field.name) for field in SKUAlias._meta.fields if not field.primary_key and field.name not in ('created_at','updated_at')}
        with self.assertRaises(IntegrityError),transaction.atomic():
            SKUAlias.objects.create(**values)
        with self.assertRaises(IntegrityError),transaction.atomic():
            SKUAlias.objects.create(**dict(values,scope='ar' if self.mode=='ap' else 'ap'))

    def test_stale_unknown_foreign_references_and_missing_notes_rejected(self):
        self.ready()
        request=self.approval();request['revision']='old'
        with self.assertRaises(ValidationError) as error:
            mapping.approve_mapping(self.case,request)
        self.assertEqual(error.exception.code,'conflict')
        for changes in ({'canonical_reference':{'kind':'purchase_order','record_id':9999,'line_id':9999}},{'approval_notes':''},{'canonical_reference':{'kind':'invented','record_id':1,'line_id':1}},{'status':'approved'}):
            body=self.approval();body.update(changes)
            with self.assertRaises(ValidationError):
                mapping.approve_mapping(self.case,body)
        self.assertEqual(SKUAlias.objects.count(),0)

    def test_capacity_voltage_model_and_unit_conflicts(self):
        self.ready()
        for description,unit in [('Samsung model WW80T 9kg 220V','PCS'),('Samsung model WW80T 8kg 110V','PCS'),('Samsung model WW90T 8kg 220V','PCS'),('Samsung model WW80T 8kg 220V','BOX')]:
            type(self.order_line).objects.filter(pk=self.order_line.pk).update(description=description,unit_of_measure=unit)
            self.order_line.refresh_from_db()
            self.assertFalse(mapping.compare_products(self.invoice_line,self.order_line,self.case)['equivalent'])
            self.assertEqual(suggestions.find_product_candidates(self.invoice_line,self.case),[])
            with self.assertRaises(ValidationError):
                mapping.approve_mapping(self.case,self.approval())
        self.assertFalse(SKUAlias.objects.exists())

    def test_ai_is_pending_bounded_and_repeatable_until_human_approval(self):
        self.ready()
        attempt,transport=self.request_ai()
        self.assertEqual(attempt.status,'completed',attempt.validation_errors)
        alias=attempt.alias
        self.assertEqual(alias.status,'pending')
        self.assertFalse(mapping.compare_products(self.invoice_line,self.order_line,self.case)['equivalent'])
        self.assertLessEqual(len(attempt.candidates),10)
        self.assertNotIn('unit_price',json.dumps(attempt.request_payload))
        self.assertFalse(model(self.mode,'ExtractionConfiguration').objects.exists())
        self.assertEqual(attempt.request_payload['format'],suggestions.SCHEMA)
        self.assertIn('untrusted',attempt.request_payload['messages'][0]['content'])
        transport.assert_awaited_once()
        second,_=self.request_ai()
        self.assertEqual(second.alias_id,alias.pk)
        self.assertEqual(SKUAlias.objects.count(),1)
        self.assertEqual(SKUSuggestionAttempt.objects.count(),2)
        approved=mapping.approve_mapping(self.case,self.review(alias,approval_notes='Verified the source model and specifications'))
        self.assertEqual(approved.status,'approved')
        third,provider=self.request_ai()
        self.assertEqual(third.status,'not_needed')
        provider.assert_not_called()

    def test_changed_source_proposals_preserve_original_and_require_fresh_review(self):
        self.ready()
        first,_=self.request_ai()
        original=first.alias.source_snapshot
        type(self.invoice_line).objects.filter(pk=self.invoice_line.pk).update(description='Samsung model WW80T 8kg 220V revised product description')
        self.invoice_line.refresh_from_db()
        second,_=self.request_ai()
        self.assertEqual(second.status,'completed',second.validation_errors)
        self.assertNotEqual(first.alias_id,second.alias_id)
        first.alias.refresh_from_db()
        self.assertEqual(first.alias.source_snapshot,original)
        with self.assertRaises(ValidationError):
            mapping.approve_mapping(self.case,self.review(first.alias,approval_notes='Reviewed original proposal'))
        approved=mapping.approve_mapping(self.case,self.review(second.alias,approval_notes='Reviewed current original source product'))
        self.assertEqual(approved.source_snapshot['description'],self.invoice_line.description)

    def test_missing_party_cannot_request_ai_or_approve(self):
        self.ready()
        type(self.case).objects.filter(pk=self.case.pk).update(**{party_key(self.mode)+'_id':None})
        self.case.refresh_from_db()
        with patch.object(suggestions,'invoke_with_llm') as provider:
            with self.assertRaises(ValidationError):
                suggestions.suggest_sku_equivalence(self.case,self.ai_request())
            provider.assert_not_called()
        with self.assertRaises(ValidationError):
            mapping.approve_mapping(self.case,self.approval())
        self.assertFalse(SKUSuggestionAttempt.objects.exists())
        self.assertFalse(SKUAlias.objects.exists())

    def test_ai_hallucination_and_schema_claims_are_rejected(self):
        self.ready()
        valid=self.ai_output()
        for changes in ({'suggested_sku':'INVENTED'},{'candidate_id':'unknown'},{'requires_review':False},{'matched_attributes':['fictional']},{'source_sku':'changed'},{'confidence':99}):
            response=dict(valid);response.update(changes)
            attempt,_=self.request_ai(response)
            self.assertEqual(attempt.status,'failed')
            self.assertTrue(attempt.validation_errors)
        self.assertFalse(SKUAlias.objects.exists())

    def test_ai_timeout_malformed_and_refusal_preserve_matching(self):
        self.ready()
        attempt,_=self.request_ai(error=TimeoutError('Provider secret must not be displayed'))
        self.assertEqual(attempt.status,'failed')
        self.assertNotIn('secret',str(attempt.validation_errors))
        attempt,_=self.request_ai(response=['malformed'])
        self.assertEqual(attempt.status,'failed')
        refusal=dict(self.ai_output(),candidate_id=None,suggested_sku=None,matched_attributes=[],reason='Insufficient identity evidence')
        attempt,_=self.request_ai(refusal)
        self.assertEqual(attempt.status,'no_suggestion')
        self.assertFalse(SKUAlias.objects.exists())
        mapping.approve_mapping(self.case,self.approval())
        self.save()
        self.assertEqual(self.case.calculate_reconciliation()[0],'matched')

    def test_no_candidates_makes_no_provider_call(self):
        self.ready()
        type(self.order_line).objects.filter(pk=self.order_line.pk).update(item_code='UNRELATED',description='Whirlpool model OTHER9 9kg 110V')
        attempt,provider=self.request_ai(response={})
        self.assertEqual(attempt.status,'no_candidates')
        provider.assert_not_called()
        self.assertFalse(SKUAlias.objects.exists())

    def test_source_changes_during_provider_call_discard_proposal(self):
        self.ready()
        response=self.ai_output()
        async def mutate(*args,**kwargs):
            from asgiref.sync import sync_to_async
            await sync_to_async(lambda:type(self.order_line).objects.filter(pk=self.order_line.pk).update(description='Changed source'))()
            return {'message':{'content':json.dumps(response)}}
        prefix='ACCOUNTS_PAYABLE' if self.mode=='ap' else 'ACCOUNTS_RECEIVABLE'
        with patch.object(suggestions,'get_env',side_effect=lambda key,default='':'sku-test' if key==prefix+'_OLLAMA_MODEL' else default),patch.object(suggestions,'invoke_with_llm',mutate):
            attempt=suggestions.suggest_sku_equivalence(self.case,self.ai_request())
        self.assertEqual(attempt.status,'failed')
        self.assertFalse(SKUAlias.objects.exists())

    def test_api_scope_csrf_revision_serialization_and_reopen(self):
        self.ready()
        base='/accounts-payable/' if self.mode=='ap' else '/accounts-receivable/'
        endpoint=f'{base}api/sku-approve/{self.case.pk}/'
        body=self.approval()
        self.assertEqual(Client(enforce_csrf_checks=True).post(endpoint,body,content_type='application/json').status_code,403)
        self.assertEqual(self.client.get(endpoint).status_code,405)
        response=self.client.post(endpoint,body,content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(response.json()['sku']['aliases'][0]['status'],'approved')
        self.assertIn('matchRevision',response.json())
        self.assertEqual(self.client.post(endpoint,body,content_type='application/json').status_code,409)
        state=pages.workspace_state(self.mode,'reconciliation',record_id=self.case.pk,screen='match')
        record=next(row for row in state['reconciliation'] if row['id']==self.case.pk)
        self.assertEqual(record['sku']['aliases'][0]['status'],'approved')
        source=next(row for row in record['sku']['sources'] if row['reference']==reference(self.invoice_line))
        self.assertIn(base,source['record_url'])
        self.assertFalse(source['needs_mapping'])
        self.assertIsNone(pages.workspace_state(self.mode,'reconciliation')['reconciliation'][0]['sku'])
        response=self.client.post(f'{base}api/sku-mappings/{self.case.pk}/',{},content_type='application/json')
        self.assertEqual(response.status_code,200)


class APMatchingTests(SKUScenarios,TestCase):
    mode='ap'


class ARMatchingTests(SKUScenarios,TestCase):
    mode='ar'
