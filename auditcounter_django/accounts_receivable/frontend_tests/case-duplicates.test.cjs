const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../static/accounting/workspace.js'),'utf8');
const context={};vm.runInNewContext(source.slice(source.indexOf('  function caseOverlapWarnings('),source.indexOf('  function form(record)')),context);
const row={id:1,partyId:2,currency:'PHP',orderIds:[10,11],receiptIds:[20,21],invoiceIds:[30]};
test('exact identity is independent of document order and current case is excluded',()=>{
 const selected={...row,orderIds:[11,10],receiptIds:[21,20]};
 assert.equal(context.caseOverlapWarnings([row],selected)[0].exact,true);
 assert.equal(context.caseOverlapWarnings([row],selected,1).length,0);
});
test('shared PO or receiving evidence gives an advisory partial warning',()=>{
 const result=context.caseOverlapWarnings([row],{...row,receiptIds:[20],invoiceIds:[31]});
 assert.equal(result[0].exact,false);assert.equal(result[0].shared.length,2);
});
test('different accounts and currencies do not expose unrelated cases',()=>{
 assert.equal(context.caseOverlapWarnings([row],{...row,partyId:3}).length,0);
 assert.equal(context.caseOverlapWarnings([row],{...row,currency:'USD'}).length,0);
});
test('overlap detection does not mutate selections or saved case arrays',()=>{
 const before=JSON.stringify(row);context.caseOverlapWarnings([row],row);assert.equal(JSON.stringify(row),before);
});
