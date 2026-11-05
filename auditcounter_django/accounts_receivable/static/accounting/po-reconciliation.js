/* PO-led cases and deduction registers share the AP/AR workspace. */
window.BizmaticPOReconciliation = (() => {
  function render({config, data, root, url, heading, card, breadcrumb, button, esc, money, badge, a}) {
    const deductions = config.resource === 'deductions';
    const rows = data[config.resource];
    const partyName = row => data.parties.find(p => p.id === row.partyId)?.name || 'Unassigned';
    const currency = row => esc(row.currency);
    const find = (kind, id) => data[kind].find(row => row.id === id);
    const link = (kind, id) => {
      const record = find(kind, id);
      return record ? a(url(kind, id), esc(record.reference)) : 'Unlinked';
    };
    const addQuery = row => `?party=${row.partyId}&purchase_order=${row.orderId || row.purchaseOrderId}`;
    const record = config.recordId ? rows.find(row => row.id === config.recordId) : null;
    if (config.recordId && !record) {
      root.innerHTML = heading('Record unavailable', 'Reload this register.', button(url(config.resource), 'Back to register'));
      return;
    }
    if (record && deductions) {
      root.innerHTML = breadcrumb(record.reference) + heading(record.reference, `${record.category} · ${partyName(record)}`, record.isManual ? button(url('deductions', record.id, 'edit'), 'Edit deduction', true, 'pen') : '') +
        card('Deduction details', `<div class="finance-card-body"><dl class="finance-meta"><div><dt>Amount</dt><dd>${currency(record)} ${money(record.amount)}</dd></div><div><dt>Status</dt><dd>${badge(record.status)}</dd></div><div><dt>PO</dt><dd>${link('purchase-orders', record.purchaseOrderId)}</dd></div><div><dt>Invoice</dt><dd>${link('invoices', record.invoiceId)}</dd></div><div><dt>Date</dt><dd>${esc(record.date)}</dd></div><div><dt>Category</dt><dd>${esc(record.category)}</dd></div></dl><p>${esc(record.description)}</p><p>${esc(record.notes)}</p><p class="text-600 mb-0">Applied deductions reduce the selected invoice’s net due. Draft and cancelled deductions have no effect on payments.</p></div>`);
      return;
    }
    function lineReview(record) {
      const order = find('purchase-orders', record.orderId);
      const receipts = record.receiptIds.map(id => find('delivery-receipts', id))
        .filter(row => row && ['accepted', 'delivered', 'partial', 'partially_accepted'].includes(row.status));
      const options = (documents, selected, quantity) => '<option value="">Choose a line</option>' +
        documents.flatMap(doc => doc.lines.filter(line => quantity(line) > 0).map((line, index) =>
          `<option value="${line.id}" ${line.id === selected ? 'selected' : ''}>${esc(doc.reference)} · ${esc(line.code || line.description || `Line ${index + 1}`)} · ${quantity(line)}</option>`
        )).join('');
      const row = (match = {}) => `<div class="finance-form-grid border rounded p-2 mb-2" data-match-row>
        <label>PO line<select class="form-select" name="orderLineId" required>${options([order], match.orderLineId, line => line.quantity)}</select></label>
        <label>Delivery line<select class="form-select" name="receiptLineId" required>${options(receipts, match.receiptLineId, line => line.accepted)}</select></label>
        <label>Matched quantity<input class="form-control" type="number" name="quantity" min="0.0001" step="0.0001" value="${esc(match.quantity ?? '')}" required></label>
        <div><button class="btn btn-sm btn-falcon-default" type="button" data-remove-match>Remove allocation</button></div>
      </div>`;
      const reviews = record.lineReviews || {};
      const lines = record.invoiceIds.map(id => find('invoices', id)).filter(Boolean)
        .flatMap(invoice => invoice.lines.filter(line => reviews[line.id]).map((line, index) => {
          const review = reviews[line.id];
          const status = review.messages.length ? 'Needs review' : Number(review.reviewedQuantity) >= line.quantity ? 'Reviewed' : 'Automatic check';
          return `<details class="mb-3" ${review.messages.length ? 'open' : ''}>
            <summary>${esc(invoice.reference)} · ${esc(line.code || line.description || `Line ${index + 1}`)} · Qty ${line.quantity} · ${status}</summary>
            ${review.messages.map(message => `<p class="text-600 mt-2 mb-1">${esc(message)}</p>`).join('')}
            <form data-invoice-line="${line.id}" class="mt-2">
              <div data-match-rows>${review.matches.map(match => row(match)).join('')}</div>
              <div class="d-flex flex-wrap gap-2">
                <button type="button" class="btn btn-falcon-default" data-add-match ${receipts.length && order.lines.length ? '' : 'disabled'}>Add allocation</button>
                <button type="submit" class="btn btn-primary" ${review.matches.length ? '' : 'disabled'}>Save line review</button>
              </div>
              <p class="text-danger mt-2 mb-0" role="alert" data-review-error hidden></p>
            </form>
          </details>`;
        })).join('');
      return {
        html: card('Document matching and line review', `<div class="finance-card-body">
          <div class="mb-3">${badge(record.documentStatus || record.status)}</div>
          <p class="text-600">Straightforward quantities and prices are checked automatically. Open an invoice line to choose its PO and accepted delivery quantities. Remove saved allocations and save to return a line to automatic checking.</p>
          ${(record.documentIssues || []).map(issue => `<p class="text-600">${esc(issue)}</p>`).join('')}
          ${lines || '<p class="mb-0">Link an invoice with line items to review its matches.</p>'}
        </div>`),
        bind() {
          root.querySelectorAll('form[data-invoice-line]').forEach(form => {
            const rows = form.querySelector('[data-match-rows]');
            const submit = form.querySelector('[type="submit"]');
            form.addEventListener('click', event => {
              if (event.target.closest('[data-add-match]')) {
                rows.insertAdjacentHTML('beforeend', row());
                rows.lastElementChild.querySelector('select').focus();
                submit.disabled = false;
              }
              if (event.target.closest('[data-remove-match]')) {
                event.target.closest('[data-match-row]').remove();
                form.querySelector('[data-add-match]').focus();
                submit.disabled = false;
              }
            });
            form.addEventListener('submit', async event => {
              event.preventDefault();
              const error = form.querySelector('[data-review-error]');
              const matches = Array.from(rows.children, item => ({
                orderLineId: Number(item.querySelector('[name="orderLineId"]').value),
                receiptLineId: Number(item.querySelector('[name="receiptLineId"]').value),
                quantity: item.querySelector('[name="quantity"]').value,
              }));
              error.hidden = true;
              submit.disabled = true;
              try {
                await window.BizmaticAccounting.post('po-line-review', record.id, {
                  invoiceLineId: Number(form.dataset.invoiceLine), matches, revision: record.revision,
                });
                location.reload();
              } catch (failure) {
                error.textContent = failure.message;
                error.hidden = false;
                submit.disabled = false;
              }
            });
          });
        },
      };
    }
    if (record) {
      const review = lineReview(record);
      const paymentIds = new Set(data.allocations.filter(allocation => record.invoiceIds.includes(allocation.invoiceId))
        .map(allocation => allocation.paymentId));
      const linkedPayments = [...paymentIds].map(id => {
        const payment = find('payments', id);
        if (!payment) return '';
        return `<div class="d-flex flex-wrap align-items-center gap-2 mb-2">
          ${link('payments', id)} ${badge(payment.status)}
          ${payment.status === 'reversed' ? '' : a(url('payments', id, 'allocate'), 'Review allocations')}
        </div>`;
      }).join('');
      const stages = [['delivery-receipts','receiptIds','Delivery receipts'],['invoices','invoiceIds','Invoices'],['deductions','deductionIds','Deductions']];
      root.innerHTML = breadcrumb(record.reference) + heading(`Reconciliation · ${record.reference}`, `${partyName(record)} · ${record.currency}`, button(url('purchase-orders',record.orderId),'View PO') + button(url('deductions','','new')+addQuery(record),'New deduction',false,'minus-circle')) +
        review.html + card('Payment settlement', `<div class="finance-card-body"><div class="mb-3">${badge(record.paymentStatus || record.status)}</div><dl class="finance-meta"><div><dt>Invoice total</dt><dd>${currency(record)} ${money(record.invoice_total)}</dd></div><div><dt>Applied deductions</dt><dd>−${money(record.deduction_total)}</dd></div><div><dt>Net due</dt><dd>${currency(record)} ${money(record.net_due)}</dd></div><div><dt>Cleared payment allocations</dt><dd>${money(record.payment_total)}</dd></div><div><dt>Outstanding</dt><dd>${money(record.outstanding)}</dd></div><div><dt>Payment difference</dt><dd>${money(record.difference)}</dd></div></dl><p class="text-600">Net due = invoices − applied deductions. Payment matching includes cash, withholding tax and discounts from cleared payments only.</p>${(record.paymentIssues || []).length ? `<div class="finance-callout warning" role="alert">${record.paymentIssues.map(issue=>`<p>${esc(issue)}</p>`).join('')}</div>` : ''}</div>`) +
        stages.map(([kind,key,title]) => card(title, `<div class="finance-card-body">${record[key].length ? record[key].map(id=>`<p>${link(kind,id)}</p>`).join('') : '<p class="text-600">No documents linked yet.</p>'}</div>`, button(url(kind,'','new')+addQuery(record), 'Add '+title.toLowerCase()))).join('') +
        card('Payments', `<div class="finance-card-body">${linkedPayments}<p>Allocate a payment to an invoice linked to this PO. Clearing or reversing the payment updates this case automatically.</p>${button(url('payments')+'?party='+record.partyId,'Open payments',true,'credit-card')}</div>`);
      review.bind();
      return;
    }
    root.innerHTML = heading(deductions ? 'Deductions' : 'Reconciliation', deductions ? 'Track Defective, Pull Out, Support, Credit Memo, and other deductions.' : 'Each PO creates a case automatically. Linked deliveries, invoices, deductions and payments update it.', deductions ? button(url('deductions','','new'),'New deduction',true,'plus') + button(config.extractionSetup,'Extraction setup',false,'sliders-h') : button(url('purchase-orders','','new'),'New purchase order',true,'plus')) +
      card(deductions ? 'All deductions' : 'PO reconciliation cases', `<div class="finance-card-body"><label for="po-register-search" class="form-label">Search reference or ${esc(config.party.toLowerCase())}</label><input id="po-register-search" class="form-control" type="search"><div id="po-register-table" class="mt-3"></div></div>`);
    if (!deductions) root.insertAdjacentHTML('beforeend', `<p class="text-600">${a(url('reconciliation'), 'View saved line matching cases')}</p>`);
    const draw = () => {
      const query = root.querySelector('#po-register-search').value.toLowerCase();
      const selectedParty = new URLSearchParams(location.search).get('party');
      const filtered = rows.filter(row=>(!selectedParty || row.partyId===Number(selectedParty)) && `${row.reference} ${partyName(row)} ${row.category || ''}`.toLowerCase().includes(query));
      root.querySelector('#po-register-table').innerHTML = filtered.length ? `<div class="table-responsive"><table class="table finance-table"><caption class="visually-hidden">${deductions ? 'Deduction register' : 'PO reconciliation register'}</caption><thead><tr><th>Reference</th><th>${esc(config.party)}</th>${deductions?'<th>Status</th>':'<th>Documents</th><th>Payment settlement</th>'}${deductions?'<th>Category</th><th class="text-end">Amount</th>':'<th class="text-end">Net due</th><th class="text-end">Cleared payments</th><th class="text-end">Outstanding</th>'}</tr></thead><tbody>${filtered.map(row=>`<tr><td>${a(url(config.resource,row.id),esc(row.reference))}</td><td>${esc(partyName(row))}</td>${deductions?`<td>${badge(row.status)}</td>`:`<td>${badge(row.documentStatus || row.status)}</td><td>${badge(row.paymentStatus || row.status)}</td>`}${deductions?`<td>${esc(row.category)}</td><td class="amount">${currency(row)} ${money(row.amount)}</td>`:`<td class="amount">${currency(row)} ${money(row.net_due)}</td><td class="amount">${money(row.payment_total)}</td><td class="amount">${money(row.outstanding)}</td>`}</tr>`).join('')}</tbody></table></div>` : `<p class="text-600 mt-3">${rows.length ? 'No matching records.' : deductions ? 'No deductions yet. Add a deduction against a PO and select its invoice to apply it.' : 'Create a PO to start reconciliation.'}</p>`;
    };
    root.querySelector('#po-register-search').addEventListener('input',draw);draw();
  }
  return {render};
})();
