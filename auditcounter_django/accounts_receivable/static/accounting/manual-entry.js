/* Manual document entry uses server-owned field definitions and string decimals. */
window.BizmaticManualEntry = (() => {
  const esc = (value = '') => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));
  const names = {'purchase-orders':'purchase order', 'delivery-receipts':'delivery receipt', invoices:'invoice', payments:'payment', deductions:'deduction'};
  const scaled = (value, places) => {
    const text = String(value || '0');
    if (!/^\d*(\.\d*)?$/.test(text)) throw new Error('Enter positive decimal amounts.');
    const [whole, fraction = ''] = text.split('.');
    if (fraction.length > places) throw new Error(`Use at most ${places} decimal places.`);
    return BigInt(whole || '0') * 10n ** BigInt(places) + BigInt(fraction.padEnd(places, '0') || '0');
  };
  const amount = cents => `${cents < 0n ? '-' : ''}${(cents < 0n ? -cents : cents) / 100n}.${String((cents < 0n ? -cents : cents) % 100n).padStart(2, '0')}`;
  const gross = (quantity, price) => (scaled(quantity, 4) * scaled(price, 4) + 500000n) / 1000000n;

  function render({config, data, root, url, heading, card, breadcrumb, button}) {
    const definition = config.manualEntry;
    const existing = definition.values;
    const editing = Boolean(config.recordId);
    const title = names[config.resource];
    if (definition.readOnly) {
      root.innerHTML = breadcrumb('Source record') + heading('Review the source record', 'This document has an extraction source. Open its source workflow to update it.', button(url(config.resource, config.recordId), 'Back to record'));
      return;
    }
    let lineCounter = 0, dirty = false, saving = false;
    const beforeUnload = event => { if (dirty && !saving) { event.preventDefault(); event.returnValue = ''; } };
    window.addEventListener('beforeunload', beforeUnload);
    const query = new URLSearchParams(location.search);
    const relationChoices = (field, selected) => {
      const account = root.querySelector('#manual-header [data-field="'+(config.mode==='ap'?'supplier':'customer')+'"]')?.value || existing?.record[config.mode==='ap'?'supplier':'customer'] || query.get('party');
      const order = root.querySelector('#manual-header [data-field="purchase_order"]')?.value || existing?.record.purchase_order || query.get('purchase_order');
      const kind = field.type === 'purchase_order' ? 'purchase-orders' : 'invoices';
      return data[kind].filter(row => (!account || String(row.partyId)===String(account)) &&
        (field.type!=='invoice' || !order || String(row.purchaseOrderId)===String(order)))
        .map(row => [row.id, row.reference]);
    };
    const input = (field, value, prefix, index = '') => {
      const id = `manual-${prefix}-${index}-${field.key}`;
      const required = field.required ? ' required' : '';
      const attrs = `id="${id}" data-field="${esc(field.key)}"${required}`;
      const selected = String(value ?? '');
      let control;
      if (['party', 'select', 'boolean', 'purchase_order', 'invoice'].includes(field.type)) {
        const choices = field.type === 'party' ? data.parties.filter(row => row.status === 'active' || String(row.id) === selected).map(row => [row.id, row.name + (row.status !== 'active' ? ' (inactive)' : '')]) : ['purchase_order','invoice'].includes(field.type) ? relationChoices(field, selected) : field.type === 'boolean' ? [[true, 'Yes'], [false, 'No']] : field.choices;
        control = `<select class="form-select" ${attrs}>${field.type === 'boolean' ? '' : `<option value="">Choose ${esc(field.label.toLowerCase())}</option>`}${choices.map(([key, label]) => `<option value="${esc(key)}" ${String(key) === selected ? 'selected' : ''}>${esc(label)}</option>`).join('')}</select>`;
      } else if (field.type === 'textarea') {
        control = `<textarea class="form-control" rows="3" ${attrs}>${esc(value)}</textarea>`;
      } else {
        const display = field.type === 'datetime-local' && value ? String(value).slice(0, 19) : value;
        control = `<input class="form-control" type="${field.type}" ${attrs} value="${esc(display)}"${field.type === 'number' ? ` min="${field.key === 'line_no' ? '1' : '0'}" step="${field.step}"` : ''}${field.maxLength ? ` maxlength="${field.maxLength}"` : ''}${field.key === 'currency' ? ' pattern="[A-Z]{3}" placeholder="PHP"' : ''}${field.key === 'line_total' ? ' readonly aria-describedby="manual-line-help"' : ''}>`;
      }
      return `<div class="finance-field${field.type === 'textarea' ? ' full' : ''}"><label for="${id}">${esc(field.label)}${field.required ? ' <span class="text-danger" aria-hidden="true">*</span>' : ''}</label>${control}${field.type === 'datetime-local' ? `<small>Time zone: ${esc(definition.timeZone)}</small>` : ''}</div>`;
    };
    const primaryDate = {'purchase-orders':'order_date', 'delivery-receipts':'delivery_date', invoices:'invoice_date', payments:'payment_date', deductions:'deduction_date'}[config.resource];
    const defaultValue = field => field.type === 'party' ? query.get('party') || field.initial : ['purchase_order','invoice'].includes(field.key) ? query.get(field.key) || field.initial : field.key === primaryDate ? data.today : field.key === 'currency' ? 'PHP' : field.initial;
    const headerFields = definition.fields.map(field => input(field, existing ? existing.record[field.key] : defaultValue(field), 'record')).join('');
    const lineSection = definition.lineFields.length ? card('Line items', `<div class="finance-card-body"><p class="text-600" id="manual-line-help">Line items are optional. Amounts use quantity × unit price − discount + tax, rounded to cents. Adding items calculates the document totals.</p><div id="manual-lines"></div><p id="manual-no-lines" class="text-600">No line items added.</p><button type="button" class="btn btn-falcon-default" id="manual-add-line"><span class="fas fa-plus me-1" aria-hidden="true"></span>Add line item</button></div>`) : '';
    root.innerHTML = breadcrumb(editing ? `Edit manual ${title}` : `New manual ${title}`) + heading(editing ? `Edit manual ${title}` : `New manual ${title}`, `Enter the ${config.party.toLowerCase()} and document details. Fields marked * are required.`) +
      `<form id="manual-entry-form"><div id="manual-error" class="finance-form-error" role="alert" tabindex="-1" hidden></div>${card('Document details', `<div class="finance-card-body"><span class="finance-source mb-3">Manual entry</span><div class="finance-form-grid" id="manual-header">${headerFields}</div></div>`)}${lineSection}<div class="finance-form-footer"><span class="text-600 fs-10">The document and its line items are saved together.</span><div class="finance-actions">${button(url(config.resource, editing ? config.recordId : ''), 'Cancel')}<button class="btn btn-primary" type="submit">${editing ? 'Save changes' : 'Create ' + title}</button></div></div></form>`;
    const form = root.querySelector('#manual-entry-form');
    const header = key => form.querySelector(`#manual-header [data-field="${key}"]`);
    const lineRows = () => [...form.querySelectorAll('[data-manual-line]')];
    const showError = message => {
      const box = form.querySelector('#manual-error');
      box.textContent = message; box.hidden = false; box.focus(); box.scrollIntoView({block:'nearest'});
    };
    const values = element => Object.fromEntries([...element.querySelectorAll('[data-field]')].map(control => [control.dataset.field, control.value]));
    const updateAmounts = () => {
      try {
        const rows = lineRows();
        const quantity = config.resource === 'purchase-orders' ? 'quantity_ordered' : 'quantity_invoiced';
        if (header('subtotal')) {
          let subtotal = 0n, discount = 0n, tax = 0n;
          for (const row of rows) {
            const v = values(row);
            const base = gross(v[quantity], v.unit_price);
            const lineDiscount = scaled(v.discount_amount, 2), lineTax = scaled(v.tax_amount, 2);
            row.querySelector('[data-field="line_total"]').value = amount(base - lineDiscount + lineTax);
            subtotal += base; discount += lineDiscount; tax += lineTax;
          }
          if (rows.length) {
            header('subtotal').value = amount(subtotal);
            header('discount_amount').value = amount(discount);
            header('tax_amount').value = amount(tax);
          }
          header('total_amount').value = amount(scaled(header('subtotal').value, 2) - scaled(header('discount_amount').value, 2) + scaled(header('tax_amount').value, 2) + scaled(header('other_charges')?.value, 2));
        }
      } catch { /* Native field validation and server validation explain invalid inputs on save. */ }
    };
    const addLine = (row = {}, focus = true) => {
      if (lineRows().length >= 1000) return showError('A document supports up to 1,000 lines.');
      const index = ++lineCounter;
      const usedNumbers = new Set(lineRows().map(line => Number(values(line).line_no)));
      let nextNumber = 1;
      while (usedNumbers.has(nextNumber)) nextNumber++;
      const element = document.createElement('fieldset');
      element.className = 'manual-entry-line';
      element.dataset.manualLine = String(index);
      if (row.id) element.dataset.lineId = String(row.id);
      element.innerHTML = `<legend>Line item ${index}</legend><div class="finance-form-grid">${definition.lineFields.map(field => input(field, row[field.key] ?? (field.key === 'line_no' ? nextNumber : field.initial), 'line', index)).join('')}</div><button type="button" class="btn btn-outline-danger mt-3" data-remove-line aria-label="Remove line item ${index}">Remove line</button>`;
      form.querySelector('#manual-lines').append(element);
      form.querySelector('#manual-no-lines').hidden = true;
      if (focus) { element.querySelector('input').focus(); dirty = true; }
    };
    for (const row of existing?.lines || []) addLine(row, false);
    form.querySelector('#manual-add-line')?.addEventListener('click', () => addLine());
    form.addEventListener('click', event => {
      const remove = event.target.closest('[data-remove-line]');
      if (!remove) return;
      remove.closest('[data-manual-line]').remove(); dirty = true;
      form.querySelector('#manual-no-lines').hidden = Boolean(lineRows().length);
      if (!lineRows().length && header('subtotal')) {
        for (const key of ['subtotal', 'discount_amount', 'tax_amount']) header(key).value = '0.00';
      }
      updateAmounts(); form.querySelector('#manual-add-line').focus();
    });
    form.addEventListener('input', event => {
      dirty = true;
      if (event.target.closest('[data-manual-line]') || ['subtotal','discount_amount','tax_amount','other_charges'].includes(event.target.dataset.field)) updateAmounts();
    });
    form.addEventListener('change', event => {
      dirty = true;
      if (['supplier','customer','purchase_order'].includes(event.target.dataset.field)) {
        for (const field of definition.fields.filter(field=>['purchase_order','invoice'].includes(field.type))) {
          const control = header(field.key), selected = control.value;
          const choices = relationChoices(field, selected);
          control.innerHTML = `<option value="">Choose ${esc(field.label.toLowerCase())}</option>` + choices.map(([key,text])=>`<option value="${key}" ${String(key)===selected?'selected':''}>${esc(text)}</option>`).join('');
        }
      }
    });
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (saving) return;
      if (!form.reportValidity()) return;
      const payload = {resource:config.resource, record:values(form.querySelector('#manual-header')),
        lines:lineRows().map(row => ({...values(row), ...(row.dataset.lineId ? {id:Number(row.dataset.lineId)} : {})})),
        ...(existing ? {revision:existing.revision} : {})};
      // Blank optional dates are represented by null, while text keeps its empty string.
      for (const field of definition.fields) if (['date','datetime-local'].includes(field.type) && !payload.record[field.key]) payload.record[field.key] = null;
      saving = true;
      try {
        const result = await window.BizmaticAccounting.post('manual-entry', config.recordId, payload);
        dirty = false; location.href = url(config.resource, result.id);
      } catch (error) { saving = false; showError(error.message); }
    });
  }
  return {render};
})();
