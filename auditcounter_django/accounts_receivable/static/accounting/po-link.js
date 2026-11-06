/* Reconciliation links can be maintained independently of extraction-owned fields. */
window.BizmaticPOLink = {
  mount({root, record, data, resource, card, esc}) {
    const orders = data['purchase-orders'].filter(order => order.partyId === record.partyId &&
      (!record.currency || order.currency === record.currency) &&
      (order.status !== 'cancelled' || order.id === record.purchaseOrderId));
    root.insertAdjacentHTML('beforeend', card('Purchase order for reconciliation', `<form id="po-link-form" class="finance-card-body"><p class="text-600">Select the PO this document belongs to. Saving this link updates reconciliation and preserves the document amounts and source history.</p>${record.reportedPO ? `<p>PO reference on the document <strong>${esc(record.reportedPO)}</strong></p>` : ''}<div id="po-link-error" class="finance-form-error" role="alert" tabindex="-1" hidden></div><div class="finance-form-grid"><div class="finance-field"><label for="po-link-order">Purchase order</label><select class="form-select" id="po-link-order"><option value="">Not linked to a PO</option>${orders.map(order=>`<option value="${order.id}" ${order.id===record.purchaseOrderId?'selected':''}>${esc(order.reference)} · ${esc(order.currency)}</option>`).join('')}</select></div></div><button type="submit" class="btn btn-primary mt-3">Save PO link</button></form>`));
    const form = root.querySelector('#po-link-form');
    let saving = false;
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (saving) return;
      const selected = form.querySelector('#po-link-order').value;
      saving = true;
      try {
        await window.BizmaticAccounting.post('document-po', record.id, {
          resource, purchaseOrderId: selected ? Number(selected) : null, revision: record.revision,
        });
        location.reload();
      } catch (error) {
        saving = false;
        const box = form.querySelector('#po-link-error');
        box.textContent = error.message; box.hidden = false; box.focus();
      }
    });
  },
};
