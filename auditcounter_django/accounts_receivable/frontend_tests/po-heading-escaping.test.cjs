const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const script = fs.readFileSync(path.join(__dirname, '../static/accounting/po-reconciliation.js'), 'utf8');
const esc = value => String(value ?? '').replace(/[&<>"']/g, char =>
  ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));

for (const mode of ['ap', 'ar']) {
  for (const resource of ['deductions', 'po-reconciliation']) {
    test(`${mode} ${resource} escapes saved values in the detail heading`, () => {
      const window = {};
      vm.runInNewContext(script, {window});
      const malicious = '<img src=x onerror=alert(1)>';
      const record = {id: 1, partyId: 2, orderId: 3, reference: 'REF',
        category: malicious, currency: malicious, receiptIds: [], invoiceIds: [], deductionIds: []};
      const data = {parties: [{id: 2, name: malicious}], allocations: [], payments: [],
        'purchase-orders': [{id: 3, lines: []}], 'delivery-receipts': [], invoices: [], deductions: []};
      data[resource] = [record];
      let description;
      const stop = new Error('heading captured');
      assert.throws(() => window.BizmaticPOReconciliation.render({
        config: {mode, resource, recordId: 1}, data, root: {}, esc,
        url: () => '/', breadcrumb: () => '', button: () => '', card: () => '', badge: () => '',
        heading: (_title, value) => {description = value; throw stop;},
      }), error => error === stop);
      assert.equal(description, `${esc(malicious)} · ${esc(malicious)}`);
      assert.doesNotMatch(description, /<img/);
    });
  }
}
