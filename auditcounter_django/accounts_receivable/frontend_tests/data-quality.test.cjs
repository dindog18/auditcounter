const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = {window: {}};
vm.runInNewContext(fs.readFileSync(__dirname+'/../static/accounting/setup/data-quality.js','utf8'), context);
test('quality reports distinguish blocking issues, warnings and safely escaped evidence', () => {
  const html = context.window.AccountingDataQuality.render({blocking_count:1,warning_count:1,truncated:true,issues:[{
    blocking:true,code:'INVALID_AMOUNT',field:'<script>',observed_value:'<img onerror="bad">',explanation:'Review & retry',suggested_action:'Correct mapping'
  }]});
  assert.match(html,/1 blocking errors · 1 warnings/);
  assert.match(html,/&lt;script&gt;/);
  assert.doesNotMatch(html,/<img|<script/);
  assert.match(html,/first 200/);
});
test('quality report handles empty and absent reports in both shared workspaces', () => {
  assert.equal(context.window.AccountingDataQuality.render(null),'');
  assert.match(context.window.AccountingDataQuality.render({blocking_count:0,warning_count:0,issues:[]}),/No quality issues/);
});
