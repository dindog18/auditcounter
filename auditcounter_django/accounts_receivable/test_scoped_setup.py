from django.test import TestCase

from .services.catalog import RESOURCES, model


class ScopedSetupTests(TestCase):
    def test_document_registers_open_only_their_own_setup(self):
        for mode, slug in (('ap', 'accounts-payable'), ('ar', 'accounts-receivable')):
            deduction = model(mode, 'ExtractionConfiguration').objects.create(
                name='Deduction setup', target_entity='deduction', source_type='document',
            )
            for resource, target in RESOURCES.items():
                with self.subTest(mode=mode, resource=resource):
                    register = f'/{slug}/{resource}/'
                    setup = register + 'configuration/'
                    response = self.client.get(register)
                    self.assertEqual(response.context['finance_config']['extractionSetup'], setup)
                    response = self.client.get(setup)
                    self.assertEqual([entry['key'] for entry in response.context['finance_config']['configurationCatalog']], [target])
                    self.assertEqual([entry['id'] for entry in response.context['finance_state']['profiles']],
                                     [deduction.pk] if target == 'deduction' else [])
                    self.assertEqual(self.client.get(setup + f'{deduction.pk}/').status_code,
                                     200 if target == 'deduction' else 404)
            self.assertRedirects(self.client.get(f'/{slug}/configuration/{deduction.pk}/'),
                                 f'/{slug}/deductions/configuration/{deduction.pk}/')
