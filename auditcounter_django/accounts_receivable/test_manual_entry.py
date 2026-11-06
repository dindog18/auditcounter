"""Manual entry exercises every document owner and its existing business rules."""

from decimal import Decimal

from django.test import Client, TestCase

from accounting_documents.manual_entry import initial_values, is_manual
from accounts_receivable.services.catalog import RESOURCES, model, party_key
from accounts_receivable.services.pages import document
from document_extraction.models import Document


class ManualEntryTests(TestCase):
    def setUp(self):
        self.accounts = {}
        for mode in ('ap', 'ar'):
            key = party_key(mode)
            self.accounts[mode] = model(mode, key).objects.create(**{key+'_code': mode, key+'_name': 'Manual account'})

    def url(self, mode, record=None):
        slug = 'accounts-payable' if mode == 'ap' else 'accounts-receivable'
        return f'/{slug}/api/manual-entry/' + (f'{record.pk}/' if record else '')

    def payload(self, mode, resource, suffix='1'):
        fields = {party_key(mode): self.accounts[mode].pk}
        target = RESOURCES[resource]
        line = {'line_no': 1, 'item_code': 'ITEM', 'description': 'Manual item', 'unit_of_measure': 'ea'}
        if target in ('purchase_order', 'sales_invoice'):
            quantity = 'quantity_ordered' if target == 'purchase_order' else 'quantity_invoiced'
            fields.update(currency='PHP', subtotal='20.00', discount_amount='1.00', tax_amount='2.00', total_amount='21.00')
            line.update(**{quantity: '2.0000'}, unit_price='10.0000', discount_amount='1.00', tax_amount='2.00', line_total='21.00')
        if target == 'purchase_order':
            fields.update(po_reference_no='PO-'+suffix, order_date='2026-11-05')
        elif target == 'sales_invoice':
            fields.update(invoice_reference_no='INV-'+suffix, invoice_date='2026-11-05', invoice_status='posted')
        elif target == 'delivery_receipt':
            fields.update(dr_reference_no='DR-'+suffix, delivery_date='2026-11-05')
            line.update(quantity_stated='2', quantity_received='2', quantity_accepted='1', quantity_rejected='1')
        else:
            fields.update(payment_reference_no='PAY-'+suffix, payment_date='2026-11-05', currency='PHP',
                          **{'amount_received' if mode == 'ar' else 'amount_paid': '21.00'})
        return {'resource': resource, 'record': fields, 'lines': [] if target == 'payment' else [line]}

    def create(self, mode, resource, suffix='1'):
        payload = self.payload(mode, resource, suffix)
        response = self.client.post(self.url(mode), payload, content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        return model(mode, RESOURCES[resource]).objects.get(pk=response.json()['id'])

    def test_extracted_deduction_links_to_the_invoice_by_reference(self):
        from .services.extraction import save_result

        for mode in ('ap', 'ar'):
            with self.subTest(mode=mode):
                order = self.create(mode, 'purchase-orders')
                invoice = self.create(mode, 'invoices')
                invoice.purchase_order = order
                invoice.save()
                config = model(mode, 'ExtractionConfiguration')(
                    target_entity='deduction', source_type='document',
                )
                deduction = save_result(mode, config, {'record': {
                    party_key(mode): mode, 'purchase_order': order.po_reference_no,
                    'invoice': invoice.invoice_reference_no, 'reference_no': 'CM-1',
                    'deduction_date': '2026-11-05', 'amount': '2.00', 'currency': 'PHP',
                    'category': 'credit_memo', 'status': 'applied',
                }, 'lines': []})
                self.assertEqual(deduction.invoice_id, invoice.pk)
                self.assertEqual(invoice.net_amount, Decimal('19.00'))

    def test_create_edit_and_render_all_eight_document_apps(self):
        for mode in ('ap', 'ar'):
            slug = 'accounts-payable' if mode == 'ap' else 'accounts-receivable'
            for resource, target in RESOURCES.items():
                if target == "deduction":
                    continue
                with self.subTest(mode=mode, target=target):
                    row = self.create(mode, resource)
                    self.assertTrue(is_manual(row))
                    self.assertEqual(document(row, target, mode)['source'], 'manual')
                    payload = initial_values(row, mode, target)
                    payload['resource'] = resource
                    if target == 'payment':
                        payload['record']['payment_method'] = 'Bank transfer'
                    else:
                        old_line_id = row.lines.get().pk
                        payload['lines'][0]['description'] = 'Edited manually'
                    response = self.client.post(self.url(mode, row), payload, content_type='application/json')
                    self.assertEqual(response.status_code, 200, response.content)
                    row.refresh_from_db()
                    if target == 'payment':
                        self.assertEqual(row.payment_method, 'Bank transfer')
                    else:
                        self.assertEqual(row.lines.get().pk, old_line_id)
                        self.assertEqual(row.lines.get().description, 'Edited manually')
                    page = self.client.get(f'/{slug}/{resource}/{row.pk}/edit/')
                    self.assertEqual(page.status_code, 200)
                    self.assertEqual(page.context['finance_config']['manualEntry']['values']['record'][party_key(mode)], self.accounts[mode].pk)
                    self.assertEqual(model(mode, 'LLMExtractionLog').objects.count(), 0)

    def test_invalid_lines_totals_and_receipt_quantities_roll_back_the_whole_entry(self):
        for mode in ('ap', 'ar'):
            for resource in ('purchase-orders', 'invoices', 'delivery-receipts'):
                bad = self.payload(mode, resource)
                if resource == 'delivery-receipts':
                    bad['lines'][0]['quantity_accepted'] = '4'
                else:
                    bad['lines'][0]['line_total'] = '900'
                response = self.client.post(self.url(mode), bad, content_type='application/json')
                self.assertEqual(response.status_code, 400, response.content)
                self.assertEqual(model(mode, RESOURCES[resource]).objects.count(), 0)
            bad = self.payload(mode, 'invoices')
            bad['record']['total_amount'] = '999'
            self.assertEqual(self.client.post(self.url(mode), bad, content_type='application/json').status_code, 400)

    def test_stale_header_and_line_edits_are_rejected(self):
        for mode in ('ap', 'ar'):
            row = self.create(mode, 'invoices')
            payload = dict(initial_values(row, mode, 'sales_invoice'), resource='invoices')
            line = row.lines.get()
            line.description = 'Another editor'
            line.save()
            response = self.client.post(self.url(mode, row), payload, content_type='application/json')
            self.assertEqual(response.status_code, 409)
            self.assertEqual(row.lines.get().description, 'Another editor')

    def test_source_fields_foreign_lines_and_cross_workflow_fields_are_rejected(self):
        for mode in ('ap', 'ar'):
            for field in ('source_document', 'source_record_key', 'id', 'customer' if mode == 'ap' else 'supplier', 'payment_status'):
                bad = self.payload(mode, 'invoices')
                bad['record'][field] = 1
                self.assertEqual(self.client.post(self.url(mode), bad, content_type='application/json').status_code, 400, field)
            first = self.create(mode, 'invoices')
            second = self.create(mode, 'invoices', '2')
            payload = dict(initial_values(first, mode, 'sales_invoice'), resource='invoices')
            payload['lines'][0]['id'] = second.lines.get().pk
            self.assertEqual(self.client.post(self.url(mode, first), payload, content_type='application/json').status_code, 400)
            self.assertEqual(first.lines.count(), 1)

    def test_extracted_records_remain_source_owned(self):
        source = Document.objects.create(file_name='source.txt', document_type='text', storage_path='/tmp/source.txt')
        for mode in ('ap', 'ar'):
            for resource, target in RESOURCES.items():
                if target == "deduction":
                    continue
                row = self.create(mode, resource)
                row.source_document = source
                row.save()
                payload = dict(initial_values(row, mode, target), resource=resource)
                response = self.client.post(self.url(mode, row), payload, content_type='application/json')
                self.assertEqual(response.status_code, 400)
                slug = 'accounts-payable' if mode == 'ap' else 'accounts-receivable'
                page = self.client.get(f'/{slug}/{resource}/{row.pk}/edit/')
                self.assertTrue(page.context['finance_config']['manualEntry']['readOnly'])
                self.assertNotIn('values', page.context['finance_config']['manualEntry'])

    def test_duplicate_references_and_invalid_shapes_do_not_write_partial_records(self):
        for mode in ('ap', 'ar'):
            self.create(mode, 'invoices')
            self.assertIn(self.client.post(self.url(mode), self.payload(mode, 'invoices'), content_type='application/json').status_code, (400, 409))
            for value in ({'resource': 'parties'}, {'resource': []}, {'resource': 'invoices', 'record': [], 'lines': []},
                          {'resource': 'invoices', 'record': {}, 'lines': [None]}, {'resource': 'invoices', 'record': {}, 'lines': [{}] * 1001}):
                self.assertEqual(self.client.post(self.url(mode), value, content_type='application/json').status_code, 400)
            self.assertEqual(model(mode, 'sales_invoice').objects.count(), 1)

    def test_create_requires_account_reference_date_and_currency_and_positive_line_quantity(self):
        for mode in ('ap', 'ar'):
            for field in (party_key(mode), 'invoice_reference_no', 'invoice_date', 'currency'):
                payload = self.payload(mode, 'invoices')
                payload['record'][field] = ''
                self.assertEqual(self.client.post(self.url(mode), payload, content_type='application/json').status_code, 400, field)
            payload = self.payload(mode, 'invoices')
            payload['lines'][0].update(quantity_invoiced='0', unit_price='0', discount_amount='0', tax_amount='0', line_total='0')
            self.assertEqual(self.client.post(self.url(mode), payload, content_type='application/json').status_code, 400)

    def test_manual_payments_can_be_cleared_after_allocating_without_reducing_reserved_amounts(self):
        for mode in ('ap', 'ar'):
            invoice = self.create(mode, 'invoices')
            payment = self.create(mode, 'payments')
            model(mode, 'PaymentAllocation').objects.create(payment=payment, invoice=invoice, cash_amount='21')
            payment.refresh_from_db()
            payload = dict(initial_values(payment, mode, 'payment'), resource='payments')
            payload['record']['payment_status'] = 'cleared'
            response = self.client.post(self.url(mode, payment), payload, content_type='application/json')
            self.assertEqual(response.status_code, 200, response.content)
            invoice.refresh_from_db()
            self.assertEqual(invoice.payment_status, 'paid')
            payment.refresh_from_db()
            payload = dict(initial_values(payment, mode, 'payment'), resource='payments')
            payload['record']['amount_received' if mode == 'ar' else 'amount_paid'] = '10'
            self.assertEqual(self.client.post(self.url(mode, payment), payload, content_type='application/json').status_code, 400)
            payment.refresh_from_db()
            self.assertEqual(getattr(payment, 'amount_received' if mode == 'ar' else 'amount_paid'), Decimal('21'))

    def test_csrf_and_post_are_required(self):
        for mode in ('ap', 'ar'):
            payload = self.payload(mode, 'invoices')
            self.assertEqual(self.client.get(self.url(mode)).status_code, 405)
            self.assertEqual(Client(enforce_csrf_checks=True).post(self.url(mode), payload, content_type='application/json').status_code, 403)
            self.assertEqual(model(mode, 'sales_invoice').objects.count(), 0)
