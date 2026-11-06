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
    const assessmentPill = (tone, label) => `<span class="recon-pill recon-${tone}"><span aria-hidden="true">${{good:'✓',bad:'!',waiting:'…',reviewed:'✓',neutral:'—'}[tone]}</span>${esc(label)}</span>`;
    function quantityState(check, record) {
      const expected = Number(check.expected);
      const closed = Number(check.closedUnserved);
      if (check.hasDifference && closed) return ['bad', 'Quantity difference'];
      if (closed && expected === 0) return ['reviewed', 'Closed unserved'];
      const deliveryConfirmed = check.deliveryChecks?.some(item => item.review);
      if (deliveryConfirmed && !check.hasDifference) {
        return Number(check.accepted) === expected
          ? ['reviewed', 'Delivery match confirmed'] : ['waiting', 'Awaiting remaining delivery'];
      }
      if (!check.hasDifference && Number(check.invoiced) < expected && check.unit?.trim()) {
        return ['waiting', Number(check.accepted) < expected ? 'Awaiting delivery' : 'Awaiting invoice'];
      }
      if (closed && Number(check.accepted) === expected && Number(check.invoiced) === expected) return ['reviewed', 'Reconciled after closure'];
      if (!deliveryConfirmed && (!check.model?.trim() || !check.unit?.trim())) return ['waiting', 'Missing identification'];
      if (check.messages.length) return record.documentStatus === 'matched'
        ? ['reviewed', 'Difference accounted for'] : ['bad', 'Quantity difference'];
      return Number(check.reviewed) > 0 ? ['reviewed', 'Reviewed match'] : ['good', 'Quantities match'];
    }
    function deliveryReview(check) {
      return (check.deliveryChecks || []).map(item => {
        const {review} = item;
        const delivery = `${item.model} · ${item.unit || 'Unit missing'} · ${item.quantity} accepted`;
        return `<details class="recon-line recon-${review ? 'reviewed' : 'bad'} mt-2">
          <summary><span>${review ? 'Confirmed delivery match' : 'Confirm delivery match'} · ${esc(item.reference)} / line ${esc(item.lineNumber)}</span></summary>
          <p class="mt-2 mb-2">Delivery line · ${esc(delivery)}</p>
          <form data-delivery-review="${item.receiptLineId}">
            ${review ? `<p>PO model · ${esc(review.evidence.order[0])} · ${esc(review.evidence.order[1] || 'Unit missing')}</p>
              ${review.reason ? `<p class="recon-row-description">${esc(review.reason)}</p>` : ''}
              <button type="submit" class="btn btn-sm btn-falcon-default">Undo confirmation</button>`
            : `<label class="form-label w-100">Matching PO line
                <select name="orderLineId" class="form-select" required>
                  <option value="">Choose the PO line</option>
                  ${item.candidates.map(line => `<option value="${line.id}">Line ${esc(line.number)} · ${esc(line.model)} · ${esc(line.unit || 'Unit missing')} · ${esc(line.quantity)} ordered</option>`).join('')}
                </select>
              </label>
              <button type="submit" class="btn btn-sm btn-primary">Save delivery match</button>`}
            <p class="text-danger mt-2 mb-0" role="alert" data-review-error hidden></p>
          </form>
        </details>`;
      }).join('');
    }

    function unservedControls(check) {
      return check.unservedControls.map(line => {
        const canClose = Number(line.available) > 0;
        const hasClosure = Number(line.closed) > 0;
        return `<details class="recon-line recon-neutral mt-2">
          <summary><span>${canClose ? 'Close unserved quantity' : 'Manage closure'} · PO line ${esc(line.lineNumber)}</span></summary>
          <form data-unserved-line="${line.lineId}" class="mt-2">
            ${hasClosure ? `<p class="mb-2">${esc(line.closed)} units closed unserved.${line.stale ? ' The PO line changed. Reopen it to review the new quantity.' : ''}</p>` : ''}
            ${canClose ? `<label class="form-label w-100">Quantity to close
              <input type="number" class="form-control" name="quantity" min="0.0001" max="${esc(line.available)}" step="0.0001" value="${esc(line.available)}" required>
            </label>
            <p class="recon-row-description mb-2">These units will no longer be expected for delivery or invoicing.</p>
            <button type="submit" class="btn btn-sm btn-primary">Close quantity</button>` : ''}
            ${hasClosure ? '<button type="submit" value="reopen" formnovalidate class="btn btn-sm btn-falcon-default">Reopen closed quantity</button>' : ''}
            <p class="text-danger mt-2 mb-0" role="alert" data-review-error hidden></p>
          </form>
        </details>`;
      }).join('');
    }

    function bindUnservedControls(record) {
      root.querySelectorAll('form[data-unserved-line]').forEach(form => {
        form.addEventListener('submit', async event => {
          event.preventDefault();
          const buttons = form.querySelectorAll('[type="submit"]');
          const error = form.querySelector('[data-review-error]');
          const quantity = event.submitter?.value === 'reopen' ? null : form.elements.quantity.value;
          buttons.forEach(button => { button.disabled = true; });
          error.hidden = true;
          try {
            await window.BizmaticAccounting.post('po-close-unserved', record.id, {
              orderLineId: Number(form.dataset.unservedLine), quantity, revision: record.revision,
            });
            location.hash = 'recon-quantities';
            location.reload();
          } catch (failure) {
            error.textContent = failure.message;
            error.hidden = false;
            buttons.forEach(button => { button.disabled = false; });
          }
        });
      });
    }

    function assessmentOverview(record) {
      const closed = record.documentStatus === 'closed_unserved';
      const references = record.referenceChecks || [];
      const referenceProblems = references.filter(row => ['format', 'conflict'].includes(row.status)).length;
      const candidates = record.unlinkedCandidates || [];
      const missing = [...(record.pendingChecks || []), ...(record.missingLines || [])];
      const quantities = record.quantityChecks || [];
      const quantityProblems = quantities.filter(row => quantityState(row, record)[0] === 'bad').length;
      const quantityWaiting = quantities.filter(row => quantityState(row, record)[0] === 'waiting').length;
      const incompleteReferences = references.filter(row => row.status === 'linked').length;
      const tiles = [
        {href:'recon-references', title:'PO references', tone:referenceProblems || candidates.length ? 'bad' : !references.length || incompleteReferences ? 'waiting' : 'good',
          label:referenceProblems || candidates.length ? 'Review needed' : !references.length || incompleteReferences ? 'Evidence incomplete' : 'References verified',
          detail:referenceProblems || candidates.length ? `${referenceProblems} difference(s) · ${candidates.length} possible link(s)` : incompleteReferences ? `${incompleteReferences} printed reference(s) unavailable` : `${references.length} linked document(s)`},
        {href:'recon-quantities', title:'Item quantities', tone:quantityProblems ? 'bad' : missing.length || quantityWaiting || !quantities.length ? 'waiting' : 'good',
          label:quantityProblems ? 'Review needed' : missing.length || quantityWaiting || !quantities.length ? 'Waiting for evidence' : 'Quantity checks complete',
          detail:quantityProblems ? `${quantityProblems} model / unit group(s) need attention` : `${quantityWaiting} incomplete · ${quantities.length - quantityProblems - quantityWaiting} matched`},
        {href:'recon-lines', title:'Document match', tone:closed || record.documentStatus === 'matched' ? 'good' : record.documentStatus === 'exception' ? 'bad' : 'waiting',
          label:closed ? 'Closed unserved' : record.documentStatus === 'matched' ? 'Match confirmed' : record.documentStatus === 'exception' ? 'Differences found' : 'Incomplete',
          detail:'Models, prices, discounts, tax and document totals'},
        {href:'recon-payments', title:'Payment settlement', tone:record.paymentStatus === 'not_required' || record.paymentStatus === 'settled' ? 'good' : record.paymentStatus === 'exception' ? 'bad' : 'waiting',
          label:record.paymentStatus === 'not_required' ? 'No payment required' : record.paymentStatus === 'settled' ? 'Settled' : record.paymentStatus === 'exception' ? 'Review needed' : record.paymentStatus === 'awaiting_invoice' ? 'Awaiting invoice' : 'Awaiting settlement',
          detail:`${record.currency} ${money(record.outstanding)} outstanding`},
      ];
      const problems = [...new Set([...(record.documentIssues || []), ...(record.paymentIssues || [])])];
      return `<nav class="recon-overview" aria-label="Reconciliation checks">${tiles.map(tile => `<a class="recon-check recon-${tile.tone}" href="#${tile.href}">
        <span class="recon-check-title">${tile.title}</span>${assessmentPill(tile.tone,tile.label)}<span class="recon-check-detail">${esc(tile.detail)}</span><span class="recon-check-action">View check <span aria-hidden="true">→</span></span>
      </a>`).join('')}</nav>${problems.length || missing.length || candidates.length ? `<section class="card recon-attention" aria-labelledby="recon-attention-title">
        <div class="finance-card-head"><h2 id="recon-attention-title">What needs attention</h2>${assessmentPill('bad', `${problems.length + missing.length + candidates.length} finding(s)`)}</div>
        <div class="finance-card-body">
          ${problems.length ? `<details class="recon-findings" open><summary>${problems.length} document or payment difference(s)</summary><ul>${problems.map(message=>`<li>${esc(message)}</li>`).join('')}</ul><p>Use the checks below to review references, allocate line items, or correct the linked records.</p></details>` : ''}
          ${missing.length ? `<div class="recon-notice recon-waiting"><strong>Complete the evidence</strong><ul>${missing.map(message=>`<li>${esc(message)}</li>`).join('')}</ul><a href="#recon-documents">Open linked documents →</a></div>` : ''}
          ${candidates.length ? `<p><a href="#recon-references">Review ${candidates.length} possible unlinked document(s) →</a></p>` : ''}
        </div>
      </section>` : ''}`;
    }

    function documentAssessment(record) {
      const references = record.referenceChecks || [];
      const candidates = record.unlinkedCandidates || [];
      const quantities = record.quantityChecks || [];
      const reviewNeeded = references.some(check => ['format', 'conflict'].includes(check.status));
      const reviewed = references.some(check => check.status === 'reviewed') || quantities.some(check => Number(check.reviewed) > 0 || check.deliveryChecks?.some(item => item.review));
      const closed = record.documentStatus === 'closed_unserved' && !candidates.length;
      const complete = record.documentStatus === 'matched' && !candidates.length;
      const settled = record.paymentStatus === 'settled';
      const paymentException = record.paymentStatus === 'exception';
      const title = closed ? 'PO closed unserved' : complete && paymentException ? 'Three-way match confirmed. Payment settlement needs review.'
        : complete
        ? record.deductionCoversShortage ? 'Documents reconciled with a deduction'
          : reviewed ? 'Three-way match confirmed after review' : 'Three-way match confirmed'
        : record.documentStatus === 'exception' || candidates.length ? 'Reconciliation needs attention' : 'Reconciliation is incomplete';
      const notice = closed ? 'All ordered quantities are closed. No delivery or invoice is expected.' : complete
        ? `${record.deductionCoversShortage ? 'An applied deduction covers the documented delivery shortfall.' : 'The PO, accepted deliveries, and invoices agree on item models, quantities, and amounts based on the supplied records.'} ${settled ? 'Payment settlement is complete.' : 'Payment settlement is tracked separately below.'}`
        : 'Review the differences and any missing evidence below before treating this case as complete.';
      const labels = {
        linked: 'Linked manually or by an existing record. No printed reference captured.',
        exact: 'Exact PO reference match.',
        reviewed: 'Formatting difference accepted.',
        format: 'Formatting difference needs review.',
        conflict: 'Different PO reference. Correct the source or PO link.',
      };
      const referenceTone = {format:'bad', conflict:'bad', exact:'good', reviewed:'reviewed', linked:'waiting'};
      const referenceLabel = {format:'Formatting difference', conflict:'Wrong PO reference', exact:'Exact match', reviewed:'Accepted after review', linked:'Printed reference unavailable'};
      const checks = [...references].sort((a,b) => Number(['format','conflict'].includes(b.status))-Number(['format','conflict'].includes(a.status))).map(check => `<li class="recon-reference recon-${referenceTone[check.status]}">
        <div class="recon-row-title"><strong>${link(check.resource, check.id)}</strong>${assessmentPill(referenceTone[check.status], referenceLabel[check.status])}</div>
        <p class="recon-row-description">${esc(labels[check.status])}</p>
        <div class="recon-compare"><div><span>Expected PO</span><strong>${esc(check.expected)}</strong></div><div><span>Reported PO</span><strong>${esc(check.reported || 'Unavailable')}</strong></div></div>
        ${check.reason ? `<p class="mb-1">Review note: ${esc(check.reason)}</p>` : ''}
        ${check.canReview && record.documentStatus !== 'cancelled' ? `<details class="recon-resolution" ${check.reason ? '' : 'open'}><summary>${check.reason ? 'Manage saved resolution' : 'Resolve this difference'}</summary><form data-reference-review data-resource="${esc(check.resource)}" data-document-id="${check.id}" class="mt-2">
          <label class="form-label d-block">Why do these references identify the same PO?
            <input class="form-control" name="reason" maxlength="500" value="${esc(check.reason)}" required>
          </label>
          <button type="submit" class="btn btn-sm btn-primary">Accept formatting difference</button>
          ${check.reason ? '<button type="submit" class="btn btn-sm btn-falcon-default" value="reopen" formnovalidate>Reopen discrepancy</button>' : ''}
          <p class="text-danger mt-2 mb-0" role="alert" data-review-error hidden></p>
        </form></details>` : ''}
      </li>`).join('');
      const potential = candidates.map(check => `<li>${link(check.resource, check.id)} reports PO <strong>${esc(check.reported)}</strong>. Open the document and confirm its PO link.</li>`).join('');
      return `<div class="alert recon-verdict alert-${(complete || closed) && !paymentException ? 'success' : 'warning'}" role="${(complete || closed) && !paymentException ? 'status' : 'alert'}">
        <strong>${title}</strong> <div>${notice}</div>
      </div>` + assessmentOverview(record) + `<div id="recon-references" class="recon-anchor" tabindex="-1"></div>` + card('PO reference checks', `<div class="finance-card-body">
        ${potential ? `<p class="fw-semibold">Possible unlinked documents</p><ul>${potential}</ul>` : ''}
        ${reviewNeeded ? '<p class="fw-semibold">Resolve each difference before closing the document check.</p>' : ''}
        ${checks ? `<ul class="recon-reference-list">${checks}</ul>` : '<p class="mb-0">Link a delivery receipt or invoice to check its PO reference.</p>'}
      </div>`) + `<div id="recon-quantities" class="recon-anchor" tabindex="-1"></div>` + card('Quantities by model and unit', `<div class="finance-card-body">
        <p>Accepted quantity excludes rejected units. Confirm a suggested delivery match here when you have verified the model and unit against the PO.</p>
        ${Number(record.closedUnservedValue) > 0 ? `<p>Expected PO amount after closures <strong>${currency(record)} ${money(record.expectedOrderTotal)}</strong></p>` : ''}
        ${(record.pendingChecks || []).map(message => `<p class="text-700">${esc(message)}</p>`).join('')}
        ${(record.receiptObservations || []).map(message => `<p class="text-700">${esc(message)}</p>`).join('')}
        ${(record.missingLines || []).map(message => `<p class="text-danger">${esc(message)}</p>`).join('')}
        ${quantities.length ? `<div class="recon-line-filters" role="group" aria-label="Filter quantity checks">${[['all','All items'],['bad','Problems'],['waiting','Missing information'],['good','Okay']].map(([value,label]) => {
          const count = quantities.filter(check => value === 'all' || (value === 'good' ? ['good','reviewed'].includes(quantityState(check,record)[0]) : quantityState(check,record)[0] === value)).length;
          return `<button type="button" class="btn btn-sm btn-falcon-default" data-quantity-filter="${value}" aria-pressed="${value === 'all'}">${label} (${count})</button>`;
        }).join('')}</div><p class="recon-filter-result" data-quantity-result role="status">Showing all ${quantities.length} items · problems first</p><div class="table-responsive"><table class="table finance-table">
          <thead><tr><th scope="col">Model</th><th scope="col">Unit</th><th scope="col">Ordered</th><th scope="col">Accepted</th><th scope="col">Invoiced</th><th scope="col">Quantity assessment</th></tr></thead>
          <tbody>${[...quantities].sort((a,b)=>({bad:0,waiting:1,reviewed:2,good:3}[quantityState(a,record)[0]])-({bad:0,waiting:1,reviewed:2,good:3}[quantityState(b,record)[0]])).map(check => `<tr data-quantity-state="${quantityState(check,record)[0]}" class="recon-quantity recon-${quantityState(check,record)[0]}">
            <th scope="row">${esc(check.model || 'Missing model')}</th><td>${esc(check.unit || 'Missing unit')}</td>
            <td>${esc(check.ordered)}</td><td>${esc(check.accepted)}</td><td>${esc(check.invoiced)}</td>
            <td>${assessmentPill(...quantityState(check,record))}<div class="recon-row-description">${check.messages.map(esc).join(' ')}</div>${deliveryReview(check)}${unservedControls(check)}${record.invoiceIds.length && check.hasDifference ? '<a href="#recon-lines">Review invoice allocations →</a>' : ''}</td>
          </tr>`).join('')}</tbody>
        </table></div>` : '<p class="mb-0">No quantities to compare yet.</p>'}
      </div>`);
    }

    function bindDeliveryReviews(record) {
      root.querySelectorAll('form[data-delivery-review]').forEach(form => {
        form.addEventListener('submit', async event => {
          event.preventDefault();
          const button = form.querySelector('[type="submit"]');
          const error = form.querySelector('[data-review-error]');
          const orderLine = form.elements.orderLineId;
          button.disabled = true;
          error.hidden = true;
          try {
            await window.BizmaticAccounting.post('po-delivery-review', record.id, {
              receiptLineId: Number(form.dataset.deliveryReview),
              orderLineId: orderLine ? Number(orderLine.value) : null,
              revision: record.revision,
            });
            location.hash = 'recon-quantities';
            location.reload();
          } catch (failure) {
            error.textContent = failure.message;
            error.hidden = false;
            button.disabled = false;
          }
        });
      });
    }

    function bindReferenceReviews(record) {
      root.querySelectorAll('form[data-reference-review]').forEach(form => {
        form.addEventListener('submit', async event => {
          event.preventDefault();
          const error = form.querySelector('[data-review-error]');
          const buttons = form.querySelectorAll('[type="submit"]');
          const reason = event.submitter?.value === 'reopen' ? '' : form.elements.reason.value.trim();
          if (!reason && event.submitter?.value !== 'reopen') {
            error.textContent = 'Enter a note explaining the difference.';
            error.hidden = false;
            return;
          }
          buttons.forEach(button => { button.disabled = true; });
          try {
            await window.BizmaticAccounting.post('po-reference-review', record.id, {
              resource: form.dataset.resource, documentId: Number(form.dataset.documentId), reason, revision: record.revision,
            });
            location.reload();
          } catch (failure) {
            error.textContent = failure.message;
            error.hidden = false;
            buttons.forEach(button => { button.disabled = false; });
          }
        });
      });
    }

    function lineReview(record) {
      const order = find('purchase-orders', record.orderId);
      const receipts = record.receiptIds.map(id => find('delivery-receipts', id))
        .filter(row => row && ['accepted', 'delivered', 'partial', 'partially_accepted'].includes(row.status));
      const options = (documents, selected, quantity) => '<option value="">Choose a line</option>' +
        documents.flatMap(doc => doc.lines.filter(line => quantity(line) > 0).map((line, index) =>
          `<option value="${line.id}" ${line.id === selected ? 'selected' : ''}>${esc(doc.reference)} · ${esc(line.code || line.description || `Line ${index + 1}`)} · ${quantity(line)} ${esc(line.unit)}</option>`
        )).join('');
      const row = (match = {}) => `<div class="finance-form-grid border rounded p-2 mb-2" data-match-row>
        <label>PO line<select class="form-select" name="orderLineId" required>${options([order], match.orderLineId, line => line.quantity)}</select></label>
        <label>Delivery line<select class="form-select" name="receiptLineId" required>${options(receipts, match.receiptLineId, line => line.accepted)}</select></label>
        <label>Matched quantity<input class="form-control" type="number" name="quantity" min="0.0001" step="0.0001" value="${esc(match.quantity ?? '')}" required></label>
        <label>Review note<input class="form-control" name="note" maxlength="500" value="${esc(match.note ?? '')}"></label>
        <div><button class="btn btn-sm btn-falcon-default" type="button" data-remove-match>Remove allocation</button></div>
      </div>`;
      const reviews = record.lineReviews || {};
      const lines = record.invoiceIds.map(id => find('invoices', id)).filter(Boolean)
        .flatMap(invoice => invoice.lines.filter(line => reviews[line.id]).map((line, index) => {
          const review = reviews[line.id];
          const status = review.messages.length ? 'Needs review' : Number(review.reviewedQuantity) >= line.quantity ? 'Reviewed' : 'Automatic check';
          const differences = review.reviewedDifferences || [];
          return `<details class="recon-line recon-${review.messages.length ? 'bad' : 'good'}" data-line-problem="${review.messages.length > 0}" ${review.messages.length ? 'open' : ''}>
            <summary><span>${esc(invoice.reference)} · <strong>${esc(line.code || line.description || `Line ${index + 1}`)}</strong> · Qty ${line.quantity}</span>${assessmentPill(review.messages.length ? 'bad' : Number(review.reviewedQuantity) > 0 ? 'reviewed' : 'good', status)}</summary>
            ${review.messages.map(message => `<p class="text-600 mt-2 mb-1">${esc(message)}</p>`).join('')}
            ${differences.map(item => `<p class="mt-2 mb-1">Reviewed difference: ${esc(item.evidence)}${item.note ? ` · ${esc(item.note)}` : ''}</p>`).join('')}
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
        html: `<div id="recon-lines" class="recon-anchor" tabindex="-1"></div>` + card('Document matching and line review', `<div class="finance-card-body">
          <div class="mb-3">${badge(record.documentStatus || record.status)}</div>
          <p class="text-600">Exact models and units are compared automatically with PO quantities, unit prices, discounts, and taxes. Open an invoice line to allocate it across accepted deliveries. For different or missing model or unit values, explain how you verified the match. Remove the saved allocations to return to automatic checking.</p>
          ${(record.documentIssues || []).map(issue => `<p class="text-600">${esc(issue)}</p>`).join('')}
          ${lines ? `<div class="recon-line-filters" role="group" aria-label="Filter invoice lines"><button class="btn btn-sm btn-falcon-default" type="button" data-line-filter="all" aria-pressed="true">All lines</button><button class="btn btn-sm btn-falcon-default" type="button" data-line-filter="problems" aria-pressed="false">Needs review (${Object.values(reviews).filter(review=>review.messages.length).length})</button></div>${lines}<p data-line-empty hidden>No invoice lines need review. Check the other sections for remaining findings.</p>` : '<p class="mb-0">Link an invoice with line items to review its matches.</p>'}
        </div>`),
        bind() {
          root.querySelectorAll('[data-line-filter]').forEach(button => button.addEventListener('click', () => {
            const problemsOnly = button.dataset.lineFilter === 'problems';
            root.querySelectorAll('[data-line-filter]').forEach(control => control.setAttribute('aria-pressed', String(control === button)));
            root.querySelectorAll('[data-line-problem]').forEach(line => { line.hidden = problemsOnly && line.dataset.lineProblem !== 'true'; });
            root.querySelector('[data-line-empty]').hidden = !problemsOnly || Object.values(reviews).some(review=>review.messages.length);
          }));
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
                note: item.querySelector('[name="note"]').value,
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
        documentAssessment(record) + review.html + `<div id="recon-payments" class="recon-anchor" tabindex="-1"></div>` + card('Payment settlement', `<div class="finance-card-body"><div class="mb-3">${badge(record.paymentStatus || record.status)}</div><dl class="finance-meta"><div><dt>Invoice total</dt><dd>${currency(record)} ${money(record.invoice_total)}</dd></div><div><dt>Applied deductions</dt><dd>−${money(record.deduction_total)}</dd></div><div><dt>Net due</dt><dd>${currency(record)} ${money(record.net_due)}</dd></div><div><dt>Cleared payment allocations</dt><dd>${money(record.payment_total)}</dd></div><div><dt>Outstanding</dt><dd>${money(record.outstanding)}</dd></div><div><dt>Payment difference</dt><dd>${money(record.difference)}</dd></div></dl><p class="text-600">Net due = invoices − applied deductions. Payment matching includes cash, withholding tax and discounts from cleared payments only.</p>${(record.paymentIssues || []).length ? `<div class="finance-callout warning" role="alert">${record.paymentIssues.map(issue=>`<p>${esc(issue)}</p>`).join('')}</div>` : ''}</div>`) +
        `<div id="recon-documents" class="recon-anchor" tabindex="-1"></div>` + stages.map(([kind,key,title]) => card(title, `<div class="finance-card-body">${record[key].length ? record[key].map(id=>`<p>${link(kind,id)}</p>`).join('') : '<p class="text-600">No documents linked yet.</p>'}</div>`, button(url(kind,'','new')+addQuery(record), 'Add '+title.toLowerCase()))).join('') +
        card('Payments', `<div class="finance-card-body">${linkedPayments}<p>Allocate a payment to an invoice linked to this PO. Clearing or reversing the payment updates this case automatically.</p>${button(url('payments')+'?party='+record.partyId,'Open payments',true,'credit-card')}</div>`);
      root.classList.add('recon-detail');
      root.querySelectorAll('[data-quantity-filter]').forEach(button => button.addEventListener('click', () => {
        const selected = button.dataset.quantityFilter;
        let visible = 0;
        root.querySelectorAll('[data-quantity-filter]').forEach(control => control.setAttribute('aria-pressed', String(control === button)));
        root.querySelectorAll('[data-quantity-state]').forEach(row => {
          row.hidden = !(selected === 'all' || (selected === 'good' ? ['good', 'reviewed'].includes(row.dataset.quantityState) : row.dataset.quantityState === selected));
          if (!row.hidden) visible += 1;
        });
        root.querySelector('[data-quantity-result]').textContent = visible ? `Showing ${visible} item(s) · ${button.textContent}` : 'No items in this category.';
      }));
      bindReferenceReviews(record);
      bindDeliveryReviews(record);
      bindUnservedControls(record);
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
