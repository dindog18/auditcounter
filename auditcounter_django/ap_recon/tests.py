"""PO-to-delivery-to-invoice-to-deduction-to-payment workflows, in AP and AR."""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from accounting_documents.manual_entry import initial_values
from accounts_receivable.services.catalog import model, party_key
from accounts_receivable.services.extraction import values_for


class POReconciliationTests(TestCase):
    def setUp(self):
        self.accounts = {}
        for mode in ('ap', 'ar'):
            key = party_key(mode)
            self.accounts[mode] = model(mode, key).objects.create(**{key+'_code': mode, key+'_name': 'Example'})

    def order(self, mode, suffix='1'):
        order = model(mode, 'purchase_order').objects.create(**{party_key(mode): self.accounts[mode]},
            po_reference_no='PO-'+suffix, order_date='2026-11-05', currency='PHP', subtotal=100, total_amount=100)
        model(mode, type(order).__name__+'Line').objects.create(purchase_order=order, line_no=1,
            item_code='ITEM', unit_of_measure='ea', quantity_ordered=10, unit_price=10, line_total=100)
        return order

    def receipt(self, mode, order, accepted=8, reference="DR"):
        receipt = model(mode, 'delivery_receipt').objects.create(**{party_key(mode): self.accounts[mode]},
            purchase_order=order, dr_reference_no=reference, delivery_date='2026-11-05',
            **{'receipt_status' if mode == 'ap' else 'delivery_status': 'accepted' if mode == 'ap' else 'delivered'})
        model(mode, type(receipt).__name__+'Line').objects.create(delivery_receipt=receipt, line_no=1,
            item_code='ITEM', unit_of_measure='ea', quantity_stated=10, quantity_received=10,
            quantity_accepted=accepted, quantity_rejected=10-accepted)
        return receipt

    def invoice(self, mode, order, reference="INV"):
        invoice = model(mode, 'sales_invoice').objects.create(**{party_key(mode): self.accounts[mode]},
            purchase_order=order, invoice_reference_no=reference, invoice_date='2026-11-05', currency='PHP',
            subtotal=100, total_amount=100, invoice_status='posted')
        model(mode, type(invoice).__name__+'Line').objects.create(invoice=invoice, line_no=1,
            item_code='ITEM', unit_of_measure='ea', quantity_invoiced=10, unit_price=10, line_total=100)
        return invoice

    def deduction(self, mode, order, invoice, amount=20, status='applied', category='defective'):
        return model(mode, 'deduction').objects.create(**{party_key(mode): self.accounts[mode]},
            purchase_order=order, invoice=invoice, reference_no='DED', deduction_date='2026-11-05',
            currency='PHP', amount=amount, category=category, status=status)

    def case(self, mode, order):
        return model(mode, 'POReconciliation').objects.get(purchase_order=order)

    def test_all_stages_and_deductions_match_net_cleared_payments_in_both_workflows(self):
        for mode in ('ap', 'ar'):
            with self.subTest(mode=mode):
                order = self.order(mode)
                self.assertEqual(self.case(mode, order).status, 'awaiting_delivery')
                order.save()
                self.assertEqual(model(mode, 'POReconciliation').objects.count(), 1)
                self.receipt(mode, order)
                self.assertEqual(self.case(mode, order).status, 'awaiting_invoice')
                invoice = self.invoice(mode, order)
                self.assertEqual(self.case(mode, order).status, 'partial')
                self.deduction(mode, order, invoice)
                self.assertEqual(self.case(mode, order).status, 'awaiting_payment')
                self.assertEqual(invoice.net_amount, Decimal('80'))
                payment = model(mode, 'payment').objects.create(**{party_key(mode): self.accounts[mode]},
                    payment_reference_no='PAY', currency='PHP', **{'amount_paid' if mode=='ap' else 'amount_received': 80})
                model(mode, 'PaymentAllocation').objects.create(payment=payment, invoice=invoice, cash_amount=80)
                self.assertEqual(self.case(mode, order).status, 'awaiting_payment')
                payment.payment_status = 'cleared'
                payment.save()
                case = self.case(mode, order)
                self.assertEqual(case.status, 'matched')
                self.assertEqual((case.invoice_total, case.deduction_total, case.net_due, case.payment_total, case.difference),
                                 (Decimal('100'), Decimal('20'), Decimal('80'), Decimal('80'), Decimal('0')))
                invoice.refresh_from_db()
                self.assertEqual(invoice.payment_status, 'paid')
                self.assertEqual(invoice.outstanding_balance, Decimal('0'))
                payment.payment_status = 'reversed'
                payment.save()
                self.assertEqual(self.case(mode, order).status, 'awaiting_payment')
                invoice.refresh_from_db()
                self.assertEqual(invoice.payment_status, 'unpaid')

    def test_draft_cancelled_and_overlapping_deductions_and_overpayments(self):
        for mode in ('ap', 'ar'):
            order = self.order(mode)
            self.receipt(mode, order, accepted=10)
            invoice = self.invoice(mode, order)
            deduction = self.deduction(mode, order, invoice, status='draft')
            self.assertEqual(invoice.net_amount, Decimal('100'))
            deduction.status = 'applied'
            deduction.save()
            self.assertEqual(invoice.net_amount, Decimal('80'))
            payment = model(mode, 'payment').objects.create(**{party_key(mode): self.accounts[mode]},
                payment_reference_no='PAY', currency='PHP', **{'amount_paid' if mode=='ap' else 'amount_received': 100})
            with self.assertRaises(ValidationError):
                model(mode, 'PaymentAllocation').objects.create(payment=payment, invoice=invoice, cash_amount=81)
            model(mode, 'PaymentAllocation').objects.create(payment=payment, invoice=invoice, cash_amount=80)
            deduction.amount = Decimal('21')
            with self.assertRaises(ValidationError):
                deduction.save()
            deduction.amount = Decimal('20')
            deduction.status = 'cancelled'
            deduction.save()
            self.assertEqual(invoice.net_amount, Decimal('100'))

    def test_explicit_links_isolate_orders_accounts_and_currencies(self):
        for mode in ('ap', 'ar'):
            order = self.order(mode)
            other = self.order(mode, '2')
            receipt = self.receipt(mode, order, accepted=10)
            invoice = self.invoice(mode, order)
            self.assertEqual(self.case(mode, other).status, 'awaiting_delivery')
            invoice.purchase_order = other
            invoice.save()
            self.assertEqual(self.case(mode, order).status, 'awaiting_invoice')
            self.assertEqual(self.case(mode, other).status, 'awaiting_delivery')
            invoice.currency = 'USD'
            with self.assertRaises(ValidationError):
                invoice.save()
            deduction = model(mode, 'deduction')(**{party_key(mode): self.accounts[mode]}, purchase_order=order,
                invoice=invoice, currency='PHP', amount=1, reference_no='WRONG', deduction_date='2026-11-05', category='support', status='applied')
            with self.assertRaises(ValidationError):
                deduction.save()
            receipt.lines.all().delete()
            receipt.delete()
            self.assertEqual(self.case(mode, order).status, 'awaiting_delivery')

    def test_full_credit_memo_can_settle_without_cash_and_cancel_reopens_balance(self):
        for mode in ('ap', 'ar'):
            order = self.order(mode)
            self.receipt(mode, order)
            invoice = self.invoice(mode, order)
            deduction = self.deduction(mode, order, invoice, amount=100, category='credit_memo')
            invoice.refresh_from_db()
            self.assertEqual(invoice.payment_status, 'paid')
            self.assertEqual(self.case(mode, order).status, 'matched')
            deduction.status = 'cancelled'
            deduction.save()
            invoice.refresh_from_db()
            self.assertEqual(invoice.outstanding_balance, Decimal('100'))
            self.assertEqual(self.case(mode, order).status, 'partial')

    def test_extraction_resolves_po_reference_under_the_selected_account(self):
        for mode in ('ap', 'ar'):
            order = self.order(mode)
            config = model(mode, 'ExtractionConfiguration')(target_entity='sales_invoice')
            key = party_key(mode)
            values = {key: mode, 'purchase_order': order.po_reference_no, 'invoice_reference_no':'INV',
                      'invoice_date':'2026-11-05', 'currency':'PHP', 'total_amount':'100'}
            self.assertEqual(values_for(mode, config, values)['purchase_order'], order)
            values['purchase_order'] = 'DOES-NOT-EXIST'
            with self.assertRaises(ValidationError):
                values_for(mode, config, values)

    def test_manual_deduction_forms_persist_categories_and_reject_stale_edits(self):
        for mode in ('ap','ar'):
            order = self.order(mode)
            invoice = self.invoice(mode, order)
            slug = 'accounts-payable' if mode=='ap' else 'accounts-receivable'
            for index, category in enumerate(('defective','pull_out','support','credit_memo','other')):
                response = self.client.post(f'/{slug}/api/manual-entry/', {'resource':'deductions', 'record':{
                    party_key(mode): self.accounts[mode].pk, 'purchase_order':order.pk, 'invoice':invoice.pk,
                    'reference_no':f'DED-{index}', 'deduction_date':'2026-11-05', 'currency':'PHP',
                    'amount':'1.00', 'category':category, 'status':'applied'}, 'lines':[]}, content_type='application/json')
                self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(invoice.net_amount, Decimal('95'))
            deduction = model(mode,'deduction').objects.first()
            payload = dict(initial_values(deduction, mode, 'deduction'), resource='deductions')
            payload['revision'] = 'old'
            self.assertEqual(self.client.post(f'/{slug}/api/manual-entry/{deduction.pk}/',payload,content_type='application/json').status_code,409)
            for path in ('deductions/','deductions/new/',f'deductions/{deduction.pk}/',f'deductions/{deduction.pk}/edit/', 'po-reconciliation/',f'po-reconciliation/{self.case(mode,order).pk}/'):
                self.assertEqual(self.client.get(f'/{slug}/{path}').status_code,200,path)

    def test_reversed_payment_cannot_be_restored_above_new_invoice_net_due(self):
        for mode in ('ap', 'ar'):
            order = self.order(mode)
            self.receipt(mode, order, accepted=10)
            invoice = self.invoice(mode, order)
            payment = model(mode, 'payment').objects.create(**{party_key(mode): self.accounts[mode]},
                payment_reference_no='PAY', currency='PHP', **{'amount_paid' if mode=='ap' else 'amount_received':80})
            model(mode, 'PaymentAllocation').objects.create(payment=payment, invoice=invoice, cash_amount=80)
            payment.payment_status = 'reversed'
            payment.save()
            self.deduction(mode, order, invoice, amount=40)
            payment.payment_status = 'cleared'
            with self.assertRaises(ValidationError):
                payment.save()
            payment.refresh_from_db()
            self.assertEqual(payment.payment_status, 'reversed')
            self.assertEqual(self.case(mode, order).payment_total, Decimal('0'))

    def test_source_backed_documents_can_be_linked_relinked_and_unlinked_without_reencoding(self):
        from document_extraction.models import Document
        from db_extraction.models import DatabaseSource, ExtractionRun, DatabaseSchema, DatabaseTable
        from accounts_receivable.services.catalog import revision
        for mode in ('ap', 'ar'):
            slug = 'accounts-payable' if mode == 'ap' else 'accounts-receivable'
            key = party_key(mode)
            first, second = self.order(mode), self.order(mode, '2')
            source = Document.objects.create(file_name=f'{mode}.txt', document_type='text', storage_path=f'/tmp/{mode}.txt')
            database = DatabaseSource.objects.create(name=mode, host='source.test', database_name='business', username='reader')
            run = ExtractionRun.objects.create(source=database, status='completed')
            schema = DatabaseSchema.objects.create(run=run, name='public')
            table = DatabaseTable.objects.create(schema=schema, name='documents')
            for source_type in ('document', 'database'):
                for resource, target in (('delivery-receipts', 'delivery_receipt'), ('invoices', 'sales_invoice')):
                    reference = f'{source_type}-{resource}'
                    fields = ({'dr_reference_no': reference, 'delivery_date': '2026-11-05'} if target == 'delivery_receipt' else
                              {'invoice_reference_no': reference, 'invoice_date': '2026-11-05', 'currency': 'PHP', 'subtotal': 100, 'total_amount': 100, 'invoice_status': 'posted'})
                    provenance = {'source_document': source} if source_type == 'document' else {
                        'source_database': database, 'source_table': table, 'source_record_key': {'id': reference}}
                    record = model(mode, target).objects.create(**{key: self.accounts[mode]}, **fields, **provenance)
                    record.refresh_from_db()
                    preserved = {field.name: field.value_from_object(record) for field in record._meta.fields
                                 if field.name not in {'purchase_order', 'updated_at', 'payment_status'}}
                    endpoint = f'/{slug}/api/document-po/{record.pk}/'
                    for order in (first, second, None):
                        response = self.client.post(endpoint, {'resource': resource,
                            'purchaseOrderId': order.pk if order else None, 'revision': revision(record)}, content_type='application/json')
                        self.assertEqual(response.status_code, 200, response.content)
                        record.refresh_from_db()
                        self.assertEqual(record.purchase_order_id, order.pk if order else None)
                        self.assertEqual({name: record._meta.get_field(name).value_from_object(record) for name in preserved}, preserved)
                        old_relation = first.delivery_receipts if target == 'delivery_receipt' else first.sales_invoices
                        new_relation = second.delivery_receipts if target == 'delivery_receipt' else second.sales_invoices
                        self.assertEqual(old_relation.filter(pk=record.pk).exists(), order == first)
                        self.assertEqual(new_relation.filter(pk=record.pk).exists(), order == second)
                    self.assertEqual(model(mode, 'LLMExtractionLog').objects.count(), 0)

    def test_po_link_action_checks_revision_scope_csrf_and_running_extraction(self):
        from django.test import Client
        from accounts_receivable.services.catalog import revision
        for mode in ('ap', 'ar'):
            slug = 'accounts-payable' if mode == 'ap' else 'accounts-receivable'
            key = party_key(mode)
            order = self.order(mode)
            invoice = self.invoice(mode, order)
            endpoint = f'/{slug}/api/document-po/{invoice.pk}/'
            invoice.refresh_from_db()
            base = {'resource': 'invoices', 'purchaseOrderId': None, 'revision': revision(invoice)}
            self.assertEqual(self.client.get(endpoint).status_code, 405)
            self.assertEqual(Client(enforce_csrf_checks=True).post(endpoint, base, content_type='application/json').status_code, 403)
            self.assertEqual(self.client.post(endpoint, {**base, 'revision': 'old'}, content_type='application/json').status_code, 409)
            for extra in ({'purchaseOrderId': True}, {'purchaseOrderId': -1}, {'resource': 'payments'}, {'source_document': 1}):
                self.assertEqual(self.client.post(endpoint, {**base, **extra}, content_type='application/json').status_code, 400)
            account = model(mode, key).objects.create(**{key+'_code': 'OTHER', key+'_name': 'Other account'})
            wrong = model(mode, 'purchase_order').objects.create(**{key: account}, po_reference_no='OTHER', order_date='2026-11-05', currency='PHP')
            other_currency = model(mode, 'purchase_order').objects.create(**{key: self.accounts[mode]}, po_reference_no='USD', order_date='2026-11-05', currency='USD')
            for other in (wrong, other_currency):
                self.assertEqual(self.client.post(endpoint, {**base, 'purchaseOrderId': other.pk}, content_type='application/json').status_code, 400)
            log = model(mode, 'LLMExtractionLog').objects.create(sales_invoice=invoice, status='processing')
            self.assertEqual(self.client.post(endpoint, base, content_type='application/json').status_code, 400)
            log.status = 'completed'
            log.save()
            self.assertEqual(self.client.post(endpoint, base, content_type='application/json').status_code, 200)
            invoice.refresh_from_db()
            self.assertIsNone(invoice.purchase_order_id)

    def test_invoice_with_deductions_cannot_be_relinked_or_unlinked(self):
        from accounts_receivable.services.catalog import revision
        for mode in ('ap', 'ar'):
            slug = 'accounts-payable' if mode == 'ap' else 'accounts-receivable'
            first, second = self.order(mode), self.order(mode, '2')
            invoice = self.invoice(mode, first)
            self.deduction(mode, first, invoice)
            invoice.refresh_from_db()
            for order_id in (second.pk, None):
                response = self.client.post(f'/{slug}/api/document-po/{invoice.pk}/', {
                    'resource': 'invoices', 'purchaseOrderId': order_id, 'revision': revision(invoice)}, content_type='application/json')
                self.assertEqual(response.status_code, 400, response.content)
                invoice.refresh_from_db()
                self.assertEqual(invoice.purchase_order_id, first.pk)

    def test_pending_or_rejected_receipt_cannot_supply_accepted_delivery_for_matching(self):
        for mode in ('ap', 'ar'):
            order = self.order(mode)
            receipt = self.receipt(mode, order, accepted=10)
            status = 'receipt_status' if mode == 'ap' else 'delivery_status'
            setattr(receipt, status, 'pending')
            receipt.save()
            invoice = self.invoice(mode, order)
            payment = model(mode, 'payment').objects.create(**{party_key(mode): self.accounts[mode]},
                payment_reference_no='PAY', currency='PHP', payment_status='cleared',
                **{'amount_paid' if mode == 'ap' else 'amount_received': 100})
            model(mode, 'PaymentAllocation').objects.create(payment=payment, invoice=invoice, cash_amount=100)
            self.assertEqual(self.case(mode, order).status, 'awaiting_delivery')
            setattr(receipt, status, 'accepted' if mode == 'ap' else 'delivered')
            receipt.save()
            self.assertEqual(self.case(mode, order).status, 'matched')
            setattr(receipt, status, 'rejected')
            receipt.save()
            self.assertEqual(self.case(mode, order).status, 'partial')

    def test_closing_unserved_quantity_reconciles_only_the_served_units(self):
        from accounting_documents.reconciliation import calculate
        from accounts_receivable.services.catalog import revision

        for mode, slug in (('ap', 'accounts-payable'), ('ar', 'accounts-receivable')):
            with self.subTest(mode=mode):
                order = self.order(mode)
                po_line = order.lines.get()
                receipt_line = self.receipt(mode, order, accepted=8).lines.get()
                case = self.case(mode, order)
                url = f'/{slug}/api/po-close-unserved/{case.pk}/'

                def close(quantity):
                    case.refresh_from_db()
                    return self.client.post(url, {
                        'orderLineId': po_line.pk, 'quantity': quantity, 'revision': revision(case),
                    }, content_type='application/json')

                self.assertEqual(close('3').status_code, 400)
                response = close('2')
                self.assertEqual(response.status_code, 200, response.content)
                invoice = self.invoice(mode, order)
                invoice_line = invoice.lines.get()
                invoice_line.quantity_invoiced = 8
                invoice_line.line_total = 80
                invoice_line.save()
                invoice.subtotal = invoice.total_amount = 80
                invoice.save()
                summary = calculate(order, mode, details=True)
                self.assertEqual(summary['documentStatus'], 'matched')
                self.assertEqual(summary['expectedOrderTotal'], 80)
                row = summary['quantityChecks'][0]
                self.assertEqual((row['ordered'], row['closedUnserved'], row['expected']), (10, 2, 8))
                self.assertEqual(order.lines.get().quantity_ordered, 10)

                receipt_line.quantity_accepted = 10
                receipt_line.quantity_rejected = 0
                receipt_line.save()
                self.assertEqual(self.case(mode, order).status, 'exception')
                self.assertEqual(close(None).status_code, 200)
                self.assertEqual(self.case(mode, order).status, 'partial')

    def test_entire_po_can_close_unserved_without_delivery_or_invoice(self):
        from accounting_documents.reconciliation import calculate
        from accounts_receivable.services.catalog import revision

        order = self.order('ar')
        case = self.case('ar', order)
        url = f'/accounts-receivable/api/po-close-unserved/{case.pk}/'
        payload = {'orderLineId': order.lines.get().pk, 'quantity': '10', 'revision': revision(case)}
        response = self.client.post(url, payload, content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.case('ar', order).status, 'closed_unserved')
        summary = calculate(order, 'ar', details=True)
        self.assertEqual(summary['paymentStatus'], 'not_required')
        self.assertEqual(summary['pendingChecks'], [])
        self.assertEqual(self.client.post(url, payload, content_type='application/json').status_code, 409)

        self.invoice('ar', order)
        summary = calculate(order, 'ar', details=True)
        self.assertEqual(summary['documentStatus'], 'exception')
        self.assertTrue(summary['quantityChecks'][0]['hasDifference'])

    def test_delivery_matches_can_be_confirmed_before_an_invoice(self):
        from accounts_receivable.services.catalog import revision

        examples = [('GR-RT303WE-PMH(52)', 'GRRT303WEPMH(52)'), ('MT02W90', 'MT02W90')]
        for mode in ('ap', 'ar'):
            for index, (po_code, delivery_code) in enumerate(examples):
                with self.subTest(mode=mode, model=po_code):
                    slug = 'accounts-payable' if mode == 'ap' else 'accounts-receivable'
                    order = self.order(mode, str(index))
                    po_line = order.lines.get()
                    po_line.item_code, po_line.unit_of_measure = po_code, ''
                    po_line.save()
                    receipt_line = self.receipt(mode, order, accepted=10, reference=f'DR-{index}').lines.get()
                    receipt_line.item_code, receipt_line.unit_of_measure = delivery_code, 'PCS'
                    receipt_line.save()
                    case = self.case(mode, order)
                    endpoint = f'/{slug}/api/po-delivery-review/{case.pk}/'
                    detail_url = f'/{slug}/po-reconciliation/{case.pk}/'

                    def detail():
                        state = self.client.get(detail_url).context['finance_state']
                        return next(row for row in state['po-reconciliation'] if row['id'] == case.pk)

                    before = detail()
                    suggestion = next(row['deliveryChecks'][0] for row in before['quantityChecks'] if row['deliveryChecks'])
                    self.assertEqual([line['id'] for line in suggestion['candidates']], [po_line.pk])
                    payload = {'receiptLineId': receipt_line.pk, 'orderLineId': po_line.pk,
                               'revision': before['revision']}
                    response = self.client.post(endpoint, payload, content_type='application/json')
                    self.assertEqual(response.status_code, 200, response.content)
                    after = detail()
                    self.assertEqual(after['documentStatus'], 'awaiting_invoice')
                    self.assertEqual(len(after['quantityChecks']), 1)
                    row = after['quantityChecks'][0]
                    self.assertEqual((row['ordered'], row['accepted'], row['invoiced']), (10, 10, 0))
                    self.assertTrue(row['deliveryChecks'][0]['review'])
                    self.assertFalse(row['hasDifference'])
                    self.assertEqual(self.client.post(endpoint, payload, content_type='application/json').status_code, 409)

                    invoice = self.invoice(mode, order, reference=f'INV-{index}')
                    invoice_line = invoice.lines.get()
                    invoice_line.item_code, invoice_line.unit_of_measure = delivery_code, 'PCS'
                    invoice_line.save()
                    case.refresh_from_db()
                    response = self.client.post(f'/{slug}/api/po-line-review/{case.pk}/', {
                        'invoiceLineId': invoice_line.pk, 'revision': revision(case),
                        'matches': [{'orderLineId': po_line.pk, 'receiptLineId': receipt_line.pk,
                                     'quantity': '10', 'note': 'Verified against the confirmed delivery.'}],
                    }, content_type='application/json')
                    self.assertEqual(response.status_code, 200, response.content)
                    self.assertEqual(detail()['documentStatus'], 'matched')
                    case.refresh_from_db()
                    response = self.client.post(endpoint, {
                        'receiptLineId': receipt_line.pk, 'orderLineId': None, 'revision': revision(case),
                    }, content_type='application/json')
                    self.assertEqual(response.status_code, 200, response.content)
                    case.refresh_from_db()
                    self.assertFalse(case.delivery_reviews)

    def test_po_line_review_uses_legacy_matches_and_recalculates_the_same_case(self):
        from accounts_receivable.services.catalog import revision

        for mode in ('ap', 'ar'):
            with self.subTest(mode=mode):
                slug = 'accounts-payable' if mode == 'ap' else 'accounts-receivable'
                order = self.order(mode)
                receipt_line = self.receipt(mode, order, accepted=10).lines.get()
                receipt_line.item_code = ''
                receipt_line.save()
                invoice = self.invoice(mode, order)
                invoice_line = invoice.lines.get()
                invoice_line.item_code = ''
                invoice_line.save()
                case = self.case(mode, order)
                self.assertEqual(case.status, 'exception')

                legacy = model(mode, 'Transaction').objects.create(
                    **{party_key(mode): self.accounts[mode]}, currency='PHP')
                legacy.purchase_orders.add(order)
                legacy.delivery_receipts.add(receipt_line.delivery_receipt)
                legacy.sales_invoices.add(invoice)
                model(mode, 'DocumentMatch').objects.create(
                    transaction=legacy, invoice_line=invoice_line, purchase_order_line=order.lines.get(),
                    delivery_receipt_line=receipt_line, matched_quantity=10, match_status='matched')
                case.refresh_from_db()
                self.assertEqual(case.status, 'awaiting_payment')

                page = self.client.get(f'/{slug}/po-reconciliation/{case.pk}/')
                self.assertNotIn('reconciliation', [item['key'] for item in page.context['finance_navigation']])
                detail = next(row for row in page.context['finance_state']['po-reconciliation'] if row['id'] == case.pk)
                self.assertEqual(detail['documentStatus'], 'matched')
                self.assertEqual(detail['paymentStatus'], 'awaiting_payment')
                self.assertEqual(detail['lineReviews'][invoice_line.pk]['reviewedQuantity'], Decimal('10'))

                endpoint = f'/{slug}/api/po-line-review/{case.pk}/'
                payload = {'invoiceLineId': invoice_line.pk, 'matches': [], 'revision': detail['revision']}
                self.assertEqual(self.client.post(endpoint, payload, content_type='application/json').status_code, 200)
                case.refresh_from_db()
                self.assertEqual(case.status, 'exception')
                self.assertEqual(self.client.post(endpoint, payload, content_type='application/json').status_code, 409)
                row = {'orderLineId': order.lines.get().pk, 'receiptLineId': receipt_line.pk, 'quantity': '10',
                       'note': 'Verified uncoded items against the PO.'}
                payload.update(matches=[row], revision=revision(case))
                response = self.client.post(endpoint, payload, content_type='application/json')
                self.assertEqual(response.status_code, 200, response.content)
                case.refresh_from_db()
                self.assertEqual(case.status, 'awaiting_payment')
                payload.update(matches=[{**row, 'quantity': '11'}], revision=revision(case))
                self.assertEqual(self.client.post(endpoint, payload, content_type='application/json').status_code, 400)
                self.assertEqual(legacy.line_matches.get().matched_quantity, Decimal('10'))

    def test_reported_po_variant_requires_a_link_and_review_in_both_workflows(self):
        from accounting_documents.reconciliation import calculate
        from accounts_receivable.services.catalog import revision
        from accounts_receivable.services.extraction import save_result

        for mode, slug in (('ap', 'accounts-payable'), ('ar', 'accounts-receivable')):
            with self.subTest(mode=mode):
                order = self.order(mode)
                self.receipt(mode, order, accepted=10)
                config = model(mode, 'ExtractionConfiguration')(target_entity='sales_invoice')
                invoice = save_result(mode, config, {'record': {
                    party_key(mode): mode, 'purchase_order': 'PO1', 'invoice_reference_no': 'INV',
                    'invoice_date': '2026-11-05', 'currency': 'PHP', 'subtotal': '100',
                    'total_amount': '100', 'invoice_status': 'posted',
                }, 'lines': [{'item_code': 'ITEM', 'unit_of_measure': 'ea', 'quantity_invoiced': '10',
                              'unit_price': '10', 'line_total': '100'}]})
                self.assertIsNone(invoice.purchase_order_id)
                self.assertEqual(invoice.reported_po_reference, 'PO1')
                summary = calculate(order, mode, details=True)
                self.assertEqual(summary['unlinkedCandidates'][0]['id'], invoice.pk)
                invoice.refresh_from_db()
                response = self.client.post(f'/{slug}/api/document-po/{invoice.pk}/', {
                    'resource': 'invoices', 'purchaseOrderId': order.pk, 'revision': revision(invoice),
                }, content_type='application/json')
                self.assertEqual(response.status_code, 200, response.content)
                case = self.case(mode, order)
                self.assertEqual(case.status, 'exception')
                endpoint = f'/{slug}/api/po-reference-review/{case.pk}/'
                review = {'resource': 'invoices', 'documentId': invoice.pk,
                          'reason': 'Confirmed against the original PO', 'revision': revision(case)}
                response = self.client.post(endpoint, review, content_type='application/json')
                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(response.json()['status'], 'awaiting_payment')
                self.assertEqual(self.client.post(endpoint, review, content_type='application/json').status_code, 409)
                case.refresh_from_db()
                page = self.client.get(f'/{slug}/po-reconciliation/{case.pk}/')
                row = next(row for row in page.context['finance_state']['po-reconciliation'] if row['id'] == case.pk)
                self.assertEqual(row['documentStatus'], 'matched')
                self.assertEqual(row['referenceChecks'][-1]['reason'], review['reason'])
                order.po_reference_no = 'PO--1'
                order.save()
                self.assertEqual(self.case(mode, order).status, 'exception')

    def test_model_variance_needs_explicit_allocation_and_remains_visible(self):
        from accounting_documents.reconciliation import calculate
        from accounts_receivable.services.catalog import revision

        for mode, slug in (('ap', 'accounts-payable'), ('ar', 'accounts-receivable')):
            with self.subTest(mode=mode):
                order = self.order(mode)
                receipt_line = self.receipt(mode, order, accepted=10).lines.get()
                invoice_line = self.invoice(mode, order).lines.get()
                order_line = order.lines.get()
                order_line.item_code = 'MODEL-1'
                order_line.save()
                receipt_line.item_code = invoice_line.item_code = 'MODEL1'
                receipt_line.save()
                invoice_line.save()
                case = self.case(mode, order)
                self.assertEqual(case.status, 'exception')
                summary = calculate(order, mode, details=True)
                self.assertIn('Possible PO model: MODEL-1', str(summary['lineReviews']))
                endpoint = f'/{slug}/api/po-line-review/{case.pk}/'
                match = {'orderLineId': order_line.pk, 'receiptLineId': receipt_line.pk, 'quantity': '10'}
                payload = {'invoiceLineId': invoice_line.pk, 'revision': revision(case), 'matches': [match]}
                self.assertEqual(self.client.post(endpoint, payload, content_type='application/json').status_code, 400)
                match['note'] = 'Verified the manufacturer model'
                result = self.client.post(endpoint, payload, content_type='application/json')
                self.assertEqual(result.status_code, 200, result.content)
                summary = calculate(order, mode, details=True)
                self.assertEqual(summary['documentStatus'], 'matched')
                reviewed = summary['lineReviews'][invoice_line.pk]['reviewedDifferences']
                self.assertIn('MODEL-1', reviewed[0]['evidence'])
                self.assertEqual(reviewed[0]['note'], 'Verified the manufacturer model')
                receipt_line.item_code = 'MODEL2'
                with self.assertRaises(ValidationError):
                    receipt_line.save()
                case.refresh_from_db()
                result = self.client.post(f'/{slug}/api/po-line-review/{case.pk}/', {
                    'invoiceLineId': invoice_line.pk, 'revision': revision(case), 'matches': [],
                }, content_type='application/json')
                self.assertEqual(result.status_code, 200, result.content)
                self.assertEqual(self.case(mode, order).status, 'exception')

    def test_header_totals_cannot_hide_unbilled_quantities_or_missing_lines(self):
        from accounting_documents.reconciliation import calculate

        for mode in ('ap', 'ar'):
            with self.subTest(mode=mode):
                order = self.order(mode)
                self.receipt(mode, order, accepted=10)
                invoice = self.invoice(mode, order)
                # A free item carries quantity but has no effect on the order total.
                model(mode, type(order).__name__ + 'Line').objects.create(
                    purchase_order=order, line_no=2, item_code='FREE', unit_of_measure='ea',
                    quantity_ordered=1, unit_price=0, line_total=0,
                )
                summary = calculate(order, mode, details=True)
                self.assertEqual(summary['documentStatus'], 'partial')
                free = next(row for row in summary['quantityChecks'] if row['model'] == 'FREE')
                self.assertEqual((free['ordered'], free['accepted'], free['invoiced']), (1, 0, 0))
                invoice.lines.all().delete()
                summary = calculate(order, mode, details=True)
                self.assertEqual(summary['documentStatus'], 'partial')
                self.assertIn('INV has no line items.', summary['missingLines'])
