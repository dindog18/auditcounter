const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(__dirname+'/../static/accounting/workspace.js','utf8');
const fn=source.slice(source.indexOf('  function settlementPanel('),source.indexOf('  function discrepancyFindings('));
function render(record){return vm.runInNewContext(fn+';settlementPanel(record)',{record,card:(title,html)=>title+html,badge:s=>s,esc:v=>String(v).replaceAll('<','&lt;').replaceAll('>','&gt;')});}
for(const mode of ['ap','ar'])test(`${mode}: settlement shows backend components without changing matching or computing recovery`,()=>{
 const record={status:'exception',settlement:{invoices:[{invoice_id:1,reference:'<unsafe>',currency:'PHP',invoice_total:'100000.00',cash:'80000.00',withholding:'0.00',discount:'0.00',credits:'20000.00',adjustments:'0.00',outstanding_balance:'0.00',pending_payment_reservations:'0.00',status:'settled',url:`/accounts-${mode==='ap'?'payable':'receivable'}/invoices/1/`,reasons:[],payments:[],credit_applications:[]}],unapplied_credits:[]}};
 const html=render(record);assert.match(html,/80000.00/);assert.match(html,/20000.00/);assert.match(html,/not cash recovery/);assert.match(html,/&lt;unsafe&gt;/);assert.equal(record.status,'exception');
});
test('legacy case without settlement remains renderable',()=>assert.equal(render({}),''));
