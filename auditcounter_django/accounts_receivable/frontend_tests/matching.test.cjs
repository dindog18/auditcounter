const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../static/accounting/workspace.js'), 'utf8');
const matching = source.slice(source.indexOf('  function matching(record)'), source.indexOf('  function aging()'));

function setup(reject = false, automatic = false) {
  const listeners = {};
  const form = {addEventListener: (event, fn) => {const previous=listeners[event];listeners[event]=previous?event=>{previous(event);fn(event);}:fn;}, reportValidity: () => true};
  const preview = {addEventListener: (_, fn) => listeners.preview = fn};
  const auto = {addEventListener: (_, fn) => listeners.auto = fn};
  const autoResults = {innerHTML:''};
  const save = {disabled: true};
  const summary = {innerHTML: '', textContent: ''};
  const lineSummary = {textContent: ''};
  const rows = (automatic?[]:[60, 40]).map((quantity, index) => ({dataset:{invoiceLine:'11'}, querySelector:selector=>({value: selector==='[data-order]'?'21':selector==='[data-receipt]'?String(31+index):String(quantity)})}));
  const tbody={insertAdjacentHTML:(_,html)=>{const order=html.match(/data-order[\s\S]*?<option value="(\d+)" selected/)[1];const receipt=html.match(/data-receipt[\s\S]*?<option value="(\d+)" selected/)[1];const quantity=html.match(/value="([^"]*)" data-quantity/)[1];rows.push({dataset:{invoiceLine:'11'},querySelector:selector=>({value:selector==='[data-order]'?order:selector==='[data-receipt]'?receipt:quantity}),querySelectorAll:()=>[]});}};
  const root = {innerHTML:'',querySelector:selector=>({'#auto-match':auto,'#auto-results':autoResults,'[data-allocations="11"]':tbody,'#match-form':form,'#match-save':save,'#match-preview':preview,'#match-summary':summary,'[data-line-summary="11"]':lineSummary}[selector]),querySelectorAll:selector=>selector==='[data-line-summary]'?[lineSummary]:rows};
  const documents = {
    invoices:[{id:1,reference:'INV',lines:[{id:11,code:'A',unit:'pc',quantity:100,price:18500}]}],
    'purchase-orders':[{id:2,reference:'PO',lines:[{id:21,code:'A',quantity:100}]}],
    'delivery-receipts':[{id:3,reference:'DR1',lines:[{id:31,code:'A',accepted:60}]},{id:4,reference:'DR2',lines:[{id:32,code:'A',accepted:40}]}],
  };
  const record = {id:9,reference:'AR-9',currency:'USD',matchRevision:'revision',invoiceIds:[1],orderIds:[2],receiptIds:[3,4],matches:(automatic?[]:[60,40]).map((quantity,index)=>({invoiceId:1,invoiceLine:0,orderId:2,orderLine:0,receiptId:3+index,receiptLine:0,quantity}))};
  const calls = [], errors = [];
  const autoResult={suggestion_revision:'source-revision',suggestions:[{invoice_line_id:11,purchase_order_line_id:21,delivery_receipt_line_id:31,matched_quantity:'60.0000',status:'suggested',eligible:true,reasons:['Exact normalized SKU']}],needs_review:[],unmatched:[],lines:[{invoice_line_id:11,quantity_to_allocate:'100',remaining_unmatched_quantity:'40'}]};
  const result = {status:'exception',discrepancy:'1234.56',unsupportedAmount:'0',priceVariance:'-50000',findings:[{message:'Server finding',amount:'-50000'}],lines:[{invoiceLineId:11,allocated:'100',supported:'100',unmatched:'0'}]};
  const location = {};
  vm.runInNewContext(matching+'\nmatching(record);', {root,record,data:documents,find:(kind,id)=>documents[kind]?.find(row=>row.id===Number(id)),esc:String,money:value=>Number(value).toFixed(2),badge:value=>value,card:(title,body)=>title+body,breadcrumb:()=>'',heading:()=>'',button:()=>'',url:()=>'/case/',partyName:()=>'',location,showError:message=>errors.push(message),api:{post:async(...args)=>{calls.push(args);if(reject) throw new Error('Over allocation');return args[0]==='match-suggestions'?autoResult:result;}}});
  return {root,listeners,summary,lineSummary,save,calls,errors,location,autoResults,rows};
}

test('reopens every allocation and uses the actual case currency',()=>{
  const {root,save}=setup();
  assert.equal((root.innerHTML.match(/<tr data-allocation /g)||[]).length,2);
  assert.match(root.innerHTML,/USD/);
  assert.doesNotMatch(root.innerHTML,/PHP/);
  assert.equal(save.disabled,true);
});

test('preview renders authoritative backend amounts and status; edits require another preview',async()=>{
  const ui=setup();
  await ui.listeners.preview();
  assert.equal(ui.calls[0][0],'matches-preview');
  assert.equal(ui.calls[0][2].matches.length,2);
  assert.equal(ui.calls[0][2].matches[1].receiptLineId,32);
  assert.match(ui.summary.innerHTML,/exception/);
  assert.match(ui.summary.innerHTML,/1234.56/);
  assert.match(ui.summary.innerHTML,/-50000.00/);
  assert.match(ui.lineSummary.textContent,/Total allocated: 100 · Supported: 100 · Remaining unmatched: 0/);
  assert.equal(ui.save.disabled,false);
  ui.listeners.input();
  assert.equal(ui.save.disabled,true);
});

test('invalid preview cannot enable saving',async()=>{
  const ui=setup(true);
  await ui.listeners.preview();
  assert.equal(ui.save.disabled,true);
  assert.equal(ui.errors[0],'Over allocation');
});


test('Auto Match is read only until explicit acceptance; accepted allocations remain editable and need preview',async()=>{
  const ui=setup(false,true);
  await ui.listeners.auto();
  assert.equal(ui.calls[0][0],'match-suggestions');
  assert.equal(ui.rows.length,0);
  assert.match(ui.autoResults.innerHTML,/Accept suggested match/);
  assert.match(ui.autoResults.innerHTML,/Exact normalized SKU/);
  const group={querySelectorAll:()=>[],insertAdjacentHTML() {}};
  const accept={dataset:{autoAccept:'0'},closest:()=>group};
  ui.listeners.click({target:{closest:selector=>selector==='[data-auto-accept]'?accept:null}});
  assert.equal(ui.rows.length,1);
  assert.equal(ui.rows[0].querySelector('[data-quantity]').value,'60.0000');
  assert.equal(ui.save.disabled,true);
  await ui.listeners.preview();
  assert.equal(ui.calls[1][2].preserveExisting,true);
  assert.equal(ui.calls[1][2].suggestionRevision,'source-revision');
  await ui.listeners.submit({preventDefault(){}});
  assert.equal(ui.calls[2][0],'matches');
  assert.equal(ui.calls[2][2].matches[0].quantity,'60.0000');
});

test('rejecting an Auto Match suggestion creates no draft allocation',async()=>{
  const ui=setup(false,true);
  await ui.listeners.auto();
  let removed=false;
  const reject={closest:()=>({remove(){removed=true;}})};
  ui.listeners.click({target:{closest:selector=>selector==='[data-auto-reject]'?reject:null}});
  assert.equal(removed,true);
  assert.equal(ui.rows.length,0);
});
