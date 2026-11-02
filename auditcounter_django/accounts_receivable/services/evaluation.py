"""Shared, read-only AP/AR evaluation. Findings are evidence, not supplier debts."""

from decimal import Decimal, localcontext
from django.core.exceptions import ValidationError
from .amounts import expected_line_total, line_amount_difference, line_amount_issues

ZERO = Decimal('0')


def evaluate(case, validate_match, tolerance, allocations=None):
    from sku_matching.services.mapping import resolver_session
    with localcontext() as context, resolver_session(case):
        context.prec = 40
        return _evaluate(case, validate_match, tolerance, allocations)


def _evaluate(case, validate_match, tolerance, allocations):
    from discrepancies.evaluation import finding as structured, source_evidence, compatible_evidence, allocation_evidence
    findings, summaries, persistent = [], [], []
    result = dict(status='pending', discrepancy=ZERO, unsupportedAmount=ZERO,
                  priceVariance=ZERO, financialVariance=ZERO, overcharge=ZERO, undercharge=ZERO,
                  arithmeticDifference=ZERO, exposureComplete=True, findings=findings, lines=summaries, discrepancy_findings=persistent)
    if not case.pk:
        return result
    invoices = list(case.sales_invoices.all())
    orders = list(case.purchase_orders.all())
    inconsistent = set()
    material = False

    def finding(kind, message, amount=None, **details):
        findings.append(dict(kind=kind, message=message, amount=amount, **details))

    for kind, documents, quantity_field in (
        ('order', orders, 'quantity_ordered'), ('invoice', invoices, 'quantity_invoiced'),
    ):
        for document in documents:
            lines = list(document.lines.all())
            charges = getattr(document, 'other_charges', ZERO)
            header = abs(document.total_amount - (document.subtotal - document.discount_amount + document.tax_amount + charges))
            line_difference = abs(document.total_amount - (sum((line.line_total for line in lines), ZERO) + charges))
            line_errors = ZERO
            invalid = False
            for line in lines:
                issues = line_amount_issues(line, quantity_field, tolerance)
                if issues:
                    invalid = True
                    difference = line_amount_difference(line, quantity_field)
                    line_errors += difference
                    if difference > tolerance:
                        expected_line = expected_line_total(line, quantity_field)
                        persistent.append(structured('LINE_TOTAL_MISMATCH', dict(document_model=document._meta.label, document_id=document.pk, line_id=line.pk),
                            f'{kind.title()} line {line.line_no} records {line.line_total}; quantity × price − discount + tax gives {expected_line}.',
                            {'total':expected_line}, {'total':line.line_total}, [source_evidence(document,line)], amount=difference, currency=case.currency,
                            details={'overlap_group':f'{document._meta.label}:{document.pk}', 'amounts_are_not_additive':True}))
                    finding('line_arithmetic', ' '.join(issues), difference, documentType=kind, documentId=document.pk, lineId=line.pk)
            for code, difference in (('header_arithmetic', header), ('line_total_arithmetic', line_difference)):
                if difference > tolerance:
                    finding(code, f'{kind.title()} recorded total disagrees with {"header arithmetic" if code == "header_arithmetic" else "line totals"}.', difference, documentType=kind, documentId=document.pk)
            if header > tolerance or line_difference > tolerance:
                expected_header = document.subtotal-document.discount_amount+document.tax_amount+charges
                summed_lines = sum((line.line_total for line in lines), ZERO)+charges
                persistent.append(structured('HEADER_TOTAL_MISMATCH', dict(document_model=document._meta.label,document_id=document.pk),
                    f'{kind.title()} total {document.total_amount} differs from component total {expected_header} or line total {summed_lines}; these checks may describe the same error.',
                    {'component_total':expected_header, 'line_total':summed_lines}, {'recorded_total':document.total_amount},
                    [source_evidence(document)]+[source_evidence(document,line) for line in lines], amount=max(header,line_difference), currency=case.currency,
                    details={'overlap_group':f'{document._meta.label}:{document.pk}', 'amounts_are_not_additive':True}))
            # Alternative manifestations of the same document inconsistency overlap.
            difference = max(header, line_difference, line_errors)
            if invalid or difference > tolerance:
                inconsistent.add((kind, document.pk))
                material = True
                result['arithmeticDifference'] += difference if difference > tolerance else ZERO
            if kind == 'invoice' and document.invoice_status == 'void':
                material = True
                inconsistent.add((kind, document.pk))
                finding('void_invoice', 'Void invoice requires review.', documentId=document.pk)

    result['exposureComplete'] = not inconsistent
    saved = allocations is None
    allocations = list(case.line_matches.all()) if saved else allocations
    valid = []
    for match in allocations:
        match.transaction = case
        if not match.purchase_order_line_id or not match.delivery_receipt_line_id or match.matched_quantity <= ZERO:
            if match.match_status == 'exception':
                material = True
                finding('invalid_evidence', 'Saved exception needs review.', lineId=match.invoice_line_id)
            continue
        try:
            # Financial differences never erase physical receiving evidence.
            original = match.match_status
            match.match_status = 'matched'
            try:
                validate_match(match, check_amounts=False, check_capacity=saved)
            finally:
                match.match_status = original
        except ValidationError as error:
            material = True
            finding('invalid_evidence', '; '.join(error.messages), lineId=match.invoice_line_id)
        else:
            valid.append(match)

    if not orders or not case.delivery_receipts.exists():
        finding('missing_evidence', 'Linked purchase order or delivery evidence is unavailable; review source documents.')
    for receipt in case.delivery_receipts.all():
        for line in receipt.lines.all():
            shortage = max(line.quantity_stated - line.quantity_received, ZERO) + line.quantity_rejected
            if shortage > ZERO:
                finding('receiving_shortage', 'Receipt records missing or rejected units. Investigate receiving evidence; this is not automatically a recoverable amount.', documentId=receipt.pk, lineId=line.pk, quantity=shortage)
    component_magnitudes = {'price_difference': ZERO, 'discount_difference': ZERO, 'tax_difference': ZERO}
    pricing = {}
    covered_any = False
    all_covered = bool(invoices)
    for invoice in invoices:
        lines = list(invoice.lines.all())
        all_covered = all_covered and bool(lines)
        for line in lines:
            matches = [match for match in valid if match.invoice_line_id == line.pk]
            supported = sum((match.matched_quantity for match in matches), ZERO)
            unmatched = max(line.quantity_invoiced - supported, ZERO)
            covered_any |= supported > ZERO
            all_covered &= line.quantity_invoiced > ZERO and supported == line.quantity_invoiced
            summary = dict(invoiceLineId=line.pk, invoiced=line.quantity_invoiced,
                           allocated=sum((match.matched_quantity for match in allocations if match.invoice_line_id == line.pk), ZERO), supported=supported,
                           unmatched=unmatched, unsupportedAmount=None, priceVariance=ZERO)
            summaries.append(summary)
            related_orders = [item for document in orders for item in document.lines.all()]
            related_receipts = [item for document in case.delivery_receipts.all() for item in document.lines.all()]
            has_po = any(compatible_evidence(case,line,item,'PO') for item in related_orders)
            has_dr = any(compatible_evidence(case,line,item,'DR') for item in related_receipts)
            invoice_evidence = [source_evidence(invoice,line)]
            for code, present, items, parent, description in (
                ('MISSING_PO', has_po, related_orders, 'purchase_order', 'purchase-order'),
                ('MISSING_DR', has_dr, related_receipts, 'delivery_receipt', 'receiving'),
            ):
                if not present:
                    evidence = invoice_evidence+[source_evidence(getattr(item,parent),item) for item in items]
                    persistent.append(structured(code, dict(invoice_line_id=line.pk),
                        f'Invoice {invoice.invoice_reference_no or invoice.pk} line {line.line_no} lacks compatible identified {description} evidence; review linked documents before assessing a monetary discrepancy.',
                        {'evidence':description, 'sku':line.item_code, 'unit':line.unit_of_measure}, {'compatible_evidence':False}, evidence,
                        currency=case.currency, severity='information', details={'classification':'evidence_gap'}))
            reliable = ('invoice', invoice.pk) not in inconsistent and line.quantity_invoiced > ZERO
            if unmatched:
                amount = unmatched * line.line_total / line.quantity_invoiced if reliable else None
                summary['unsupportedAmount'] = amount
                if amount is not None:
                    result['unsupportedAmount'] += amount
                if has_po and has_dr:
                    shortage_evidence = invoice_evidence + [source_evidence(item.purchase_order,item) for item in related_orders if compatible_evidence(case,line,item,'PO')] + [source_evidence(item.delivery_receipt,item) for item in related_receipts if compatible_evidence(case,line,item,'DR')]
                    persistent.append(structured('QUANTITY_SHORTAGE', dict(invoice_line_id=line.pk),
                        f'Invoice {invoice.invoice_reference_no or invoice.pk} line {line.line_no} invoices {line.quantity_invoiced} {line.unit_of_measure}; verified allocations support {supported}, leaving {unmatched} awaiting investigation. This is not a confirmed recoverable amount.',
                        {'quantity':supported,'unit':line.unit_of_measure}, {'quantity':line.quantity_invoiced,'unit':line.unit_of_measure}, shortage_evidence+[allocation_evidence(match) for match in matches],
                        amount=amount if supported > ZERO else None, currency=case.currency, severity='warning' if supported > ZERO else 'information',
                        details={'classification':'unsupported_quantity' if supported > ZERO else 'awaiting_matching', 'quantity_difference':str(unmatched)}))
                finding('unsupported_quantity', 'Invoiced quantity lacks allocated order and accepted receiving evidence; investigate outstanding deliveries before treating this as a loss.', amount, lineId=line.pk, quantity=unmatched)
            for match in matches:
                order = match.purchase_order_line
                if not reliable or ('order', order.purchase_order_id) in inconsistent:
                    continue
                quantity = match.matched_quantity
                price = (line.unit_price - order.unit_price) * quantity
                discount = (order.discount_amount / order.quantity_ordered - line.discount_amount / line.quantity_invoiced) * quantity
                tax = (line.tax_amount / line.quantity_invoiced - order.tax_amount / order.quantity_ordered) * quantity
                summary['priceVariance'] += price
                result['priceVariance'] += price
                key = (line.pk,order.pk)
                group = pricing.setdefault(key, dict(line=line, order=order, quantity=ZERO, price=ZERO, discount=ZERO, tax=ZERO, receipts={}, allocations=[]))
                group['quantity'] += quantity
                group['price'] += price
                group['discount'] += discount
                group['tax'] += tax
                group['receipts'][match.delivery_receipt_line_id] = match.delivery_receipt_line
                group['allocations'].append(allocation_evidence(match))
                net = price + discount + tax
                result['financialVariance'] += net
                result['overcharge' if net > ZERO else 'undercharge'] += abs(net)
                for code, amount in (('price_difference', price), ('discount_difference', discount), ('tax_difference', tax)):
                    component_magnitudes[code] += abs(amount)
                    if amount != ZERO:
                        finding(code, f'{code.replace("_", " ").title()}: {"overcharge" if amount > ZERO else "undercharge"}; requires investigation.', amount, lineId=line.pk, quantity=quantity)
    for (line_id,order_id), group in pricing.items():
        if any(component_magnitudes[code] > tolerance and group[field] != ZERO for code,field in (('price_difference','price'),('discount_difference','discount'),('tax_difference','tax'))):
            line, order = group['line'], group['order']
            net = group['price']+group['discount']+group['tax']
            evidence = [source_evidence(line.invoice,line), source_evidence(order.purchase_order,order)]
            evidence += [source_evidence(receipt.delivery_receipt,receipt) for receipt in group['receipts'].values()]
            persistent.append(structured('PRICE_VARIANCE', dict(invoice_line_id=line_id, purchase_order_line_id=order_id),
                f'Invoice line {line.line_no} price {line.unit_price} differs from PO price {order.unit_price} or its discount/tax on {group["quantity"]} supported units. Signed price variance: {group["price"]:.2f}; net variance including discounts and tax: {net:.2f}. Investigate before treating it as recoverable.',
                {'unit_price':order.unit_price,'discount_per_unit':order.discount_amount/order.quantity_ordered,'tax_per_unit':order.tax_amount/order.quantity_ordered},
                {'unit_price':line.unit_price,'discount_per_unit':line.discount_amount/line.quantity_invoiced,'tax_per_unit':line.tax_amount/line.quantity_invoiced},
                evidence+group['allocations'], amount=net, currency=case.currency,
                details={'supported_quantity':str(group['quantity']), 'price_variance':str(group['price']), 'discount_variance':str(group['discount']), 'tax_variance':str(group['tax']), 'direction':'overcharge' if net>ZERO else 'undercharge' if net<ZERO else 'offsetting_components'}))
    # An open order balance is informational and does not make a supported invoice partial.
    for order in orders:
        for line in order.lines.all():
            external = line.matches.exclude(transaction=case)
            allocated = sum((match.matched_quantity for match in external
                             if match.purchase_order_line_id and match.delivery_receipt_line_id), ZERO)
            allocated += sum((match.matched_quantity for match in valid if match.purchase_order_line_id == line.pk), ZERO)
            balance = max(line.quantity_ordered - allocated, ZERO)
            if balance:
                finding('outstanding_order', 'Unallocated order balance may represent an expected partial delivery or uninvoiced goods; it is not an invoice loss.', documentId=order.pk, lineId=line.pk, quantity=balance)
    if all_covered and not inconsistent:
        charge_difference = sum((getattr(i, 'other_charges', ZERO) for i in invoices), ZERO) - sum((getattr(o, 'other_charges', ZERO) for o in orders), ZERO)
        if charge_difference > tolerance:
            material = True
            result['overcharge'] += charge_difference
            persistent.append(structured('PRICE_VARIANCE', {'component':'other_charges'},
                f'Invoice charges exceed linked PO charges by {charge_difference}; review before treating this as recoverable.',
                {'other_charges':sum((getattr(order,'other_charges',ZERO) for order in orders),ZERO)},
                {'other_charges':sum((getattr(invoice,'other_charges',ZERO) for invoice in invoices),ZERO)},
                [source_evidence(document) for document in orders+invoices], amount=charge_difference, currency=case.currency, details={'component':'other_charges'}))
            finding('other_charges', 'Invoice charges exceed linked order charges; review.', charge_difference)
    material |= any(amount > tolerance for amount in component_magnitudes.values())
    result['status'] = 'exception' if material else 'matched' if all_covered else 'partial' if covered_any else 'pending'
    result['discrepancy'] = (result['arithmeticDifference'] + result['unsupportedAmount'] + result['overcharge'] + result['undercharge']).quantize(Decimal('0.01'))
    case._meta.get_field('total_discrepancy_amount').clean(result['discrepancy'], case)
    return result
