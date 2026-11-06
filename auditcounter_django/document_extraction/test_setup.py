"""Checklist checks use local configuration only, never provider requests."""
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from auditcounter_django.onboarding import checklist, provider_check
from router.models import RoutingDestination, RoutingRule
from accounts_receivable.models import ExtractionConfiguration


class SetupTests(TestCase):
    def setUp(self):
        self.environment = patch('auditcounter_django.onboarding.get_env', side_effect=lambda key, default='': default)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_empty_setup_has_actions_and_workspace_alert(self):
        response = self.client.get('/setup/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Application setup')
        self.assertContains(response, 'Needs setup')
        for route in ['ROUTER:destination_create', 'ACCOUNTS_PAYABLE:configuration_list', 'ACCOUNTS_RECEIVABLE:configuration_list', 'DB_EXTRACTION:source_create']:
            self.assertContains(response, reverse(route))
        response = self.client.get('/router/rules/new/')
        self.assertContains(response, 'Document routing needs setup.')
        self.assertContains(response, 'page-tour-data')
        self.assertContains(response, 'Only active rules for active destinations are used.')

    def test_destination_needs_rule_and_target_specific_submitted_profile(self):
        destination = RoutingDestination.objects.create(name='Invoices', module_name='accounts_receivable', target_model='CompanySalesInvoice')
        groups = {group['key']: group for group in checklist()}
        self.assertFalse(groups['ROUTER']['steps'][-1]['ready'])
        self.assertFalse(groups['ACCOUNTS_RECEIVABLE']['steps'][-1]['ready'])
        RoutingRule.objects.create(name='Invoices', destination=destination, instructions='Match customer invoices')
        profile = ExtractionConfiguration.objects.create(name='Invoices', target_entity='sales_invoice', source_type='document', status='draft')
        self.assertFalse({g['key']: g for g in checklist()}['ACCOUNTS_RECEIVABLE']['steps'][-1]['ready'])
        profile.status = 'submitted'
        profile.submitted_snapshot = {'configuration': {'target_entity': 'sales_invoice'}}
        profile.save()
        groups = {group['key']: group for group in checklist()}
        self.assertTrue(groups['ROUTER']['steps'][-1]['ready'])
        self.assertTrue(groups['ACCOUNTS_RECEIVABLE']['steps'][-1]['ready'])
        destination.is_active = False
        destination.save()
        self.assertFalse({g['key']: g for g in checklist()}['ROUTER']['steps'][1]['ready'])

    def test_settings_detect_placeholders_and_do_not_expose_credentials(self):
        values = {'ACCOUNTS_PAYABLE_LLM_PROVIDER': 'openai', 'ACCOUNTS_PAYABLE_OPENAI_MODEL': 'ap-model', 'ACCOUNTS_PAYABLE_OPENAI_API_KEY': 'replace-with-your-key'}
        with patch('auditcounter_django.onboarding.get_env', side_effect=lambda key, default='': values.get(key, default)):
            self.assertFalse(provider_check('ACCOUNTS_PAYABLE')[0])
            values['ACCOUNTS_PAYABLE_OPENAI_API_KEY'] = 'private-test-value'
            self.assertTrue(provider_check('ACCOUNTS_PAYABLE')[0])
            response = self.client.get('/setup/')
            self.assertNotContains(response, 'private-test-value')
            values['ACCOUNTS_PAYABLE_MAX_OUTPUT_TOKENS'] = '-1'
            self.assertFalse(provider_check('ACCOUNTS_PAYABLE')[0])

    def test_help_on_each_workspace_and_setup_is_read_only(self):
        for url, title in [('/documents/', 'Documents'), ('/batches/', 'Batches'), ('/databases/', 'Database metadata'), ('/accounts-payable/configuration/', 'Extraction setup'), ('/accounts-receivable/payments/', 'Payments')]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context['page_guide']['title'], title)
        self.assertEqual(self.client.post('/setup/').status_code, 405)

    def test_task_routes_have_specific_guides(self):
        from django.test import RequestFactory
        from django.urls import resolve
        from auditcounter_django.page_help import for_page

        for path, title in [('/guided-setup/', 'Guided setup'),
                            ('/documents/123/', 'Review a document'),
                            ('/documents/', 'Documents'),
                            ('/accounts-payable/payments/123/allocate/', 'Allocate a payment'),
                            ('/accounts-receivable/reconciliation/123/match/', 'Match document lines'),
                            ('/accounts-receivable/configuration/new/', 'Configure extraction'),
                            ('/accounts-receivable/configuration/', 'Extraction setup')]:
            request = RequestFactory().get(path)
            request.resolver_match = resolve(path)
            self.assertEqual(for_page(request)['title'], title)
        response = self.client.get('/documents/')
        self.assertContains(response, 'id="help-tour-back"')
        self.assertContains(response, 'id="help-tour-next"')
        self.assertContains(response, 'id="help-tour-close"')
        self.assertContains(response, 'Route selected')

    def test_guided_setup_checks_saved_configuration_and_rule_for_each_record(self):
        url = reverse("guided_setup")
        self.assertRedirects(self.client.get(reverse("setup_preview")), url, fetch_redirect_response=False)

        target = "Accounts Receivable|Sales invoice"

        def readiness():
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertIn("no-store", response.headers["Cache-Control"])
            self.assertEqual(response.context["page_guide"]["title"], "Guided setup")
            self.assertContains(response, "Recheck and continue")
            self.assertContains(response, "Resume in this browser")
            return response.context["setup_preview_routes"][target]

        profile = ExtractionConfiguration.objects.create(
            name="Invoice draft", target_entity="sales_invoice", source_type="document", status="draft",
        )
        destination = RoutingDestination.objects.create(
            name="Invoices", module_name="company_sales_invoice", target_model="CompanySalesInvoice",
        )
        rule = RoutingRule.objects.create(name="Invoices", destination=destination, instructions="Customer invoices", is_active=False)
        initial = readiness()
        self.assertFalse(initial["document_ready"])
        self.assertFalse(initial["routing_ready"])
        profile.status = "submitted"
        profile.submitted_snapshot = {"configuration": {"target_entity": "sales_invoice"}}
        profile.save()
        rule.is_active = True
        rule.save()
        ready = readiness()
        self.assertTrue(ready["document_ready"])
        self.assertTrue(ready["routing_ready"])
        destination.is_deleted = True
        destination.save()
        self.assertFalse(readiness()["routing_ready"])

    def test_home_guides_fresh_workspace_even_with_reminder_preferences(self):
        from document_extraction.models import WorkspaceSetupPreferences

        WorkspaceSetupPreferences.objects.create(pk=1, active_modules=[])
        response = self.client.get(reverse("DOC_EXTRACTION:home"))
        self.assertRedirects(response, reverse("guided_setup"), fetch_redirect_response=False)
        self.assertIn("no-store", response.headers["Cache-Control"])

        self.client.cookies["auditcounter_guided_setup_finished"] = "1"
        self.assertRedirects(
            self.client.get(reverse("DOC_EXTRACTION:home")),
            reverse("DOC_EXTRACTION:document_list"),
            fetch_redirect_response=False,
        )

    def test_home_uses_saved_setup_for_an_existing_workspace(self):
        ExtractionConfiguration.objects.create(
            name="Customer import", target_entity="customer", source_type="document",
            status="submitted", submitted_snapshot={"configuration": {"target_entity": "customer"}},
        )
        self.assertRedirects(
            self.client.get(reverse("DOC_EXTRACTION:home")),
            reverse("DOC_EXTRACTION:document_list"),
            fetch_redirect_response=False,
        )
