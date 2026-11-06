const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

for (const mode of ['ap', 'ar']) for (const resource of ['delivery-receipts', 'invoices']) {
  test(`${mode} ${resource}: PO link changes are scoped and preserve source fields`, async () => {
    let submit, html = '', reloads = 0;
    const requests = [];
    const select = {value:'2'};
    const error = {hidden:true,focus(){}};
    const form = {addEventListener(_, handler){submit=handler;},querySelector(selector){return selector==='#po-link-order'?select:error;}};
    const root = {insertAdjacentHTML(_,value){html+=value;},querySelector(){return form;}};
    const window = {BizmaticAccounting:{post:async(...args)=>{requests.push(args);}}};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/accounting/po-link.js'),'utf8'),{window,location:{reload(){reloads++;}}});
    window.BizmaticPOLink.mount({root,resource,record:{id:7,partyId:1,currency:resource==='invoices'?'PHP':'',revision:'latest',source:'database'},
      data:{'purchase-orders':[{id:2,partyId:1,reference:'PO & Co',currency:'PHP',status:'open'},
        {id:3,partyId:99,reference:'Wrong account',currency:'PHP',status:'open'},
        {id:4,partyId:1,reference:'Cancelled',currency:'PHP',status:'cancelled'}]},
      card:(_,body)=>body,esc:value=>String(value).replaceAll('&','&amp;')});
    assert.match(html,/Save PO link/);
    assert.match(html,/PO &amp; Co/);
    assert.doesNotMatch(html,/Wrong account|Cancelled/);
    await submit({preventDefault(){}});
    assert.equal(requests[0][0],'document-po');assert.equal(requests[0][1],7);
    assert.deepEqual(JSON.parse(JSON.stringify(requests[0][2])),{resource,purchaseOrderId:2,revision:'latest'});
    assert.equal(reloads,1);
  });
}

test('a failed PO link keeps the selection visible and allows retry', async () => {
  let submit, reloads=0;
  const error = {hidden:true,focus(){}};
  const select = {value:'2'};
  const form = {addEventListener(_,handler){submit=handler;},querySelector(selector){return selector==='#po-link-order'?select:error;}};
  const window={BizmaticAccounting:{post:async()=>{throw new Error('The record changed.');}}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/accounting/po-link.js'),'utf8'),{window,location:{reload(){reloads++;}}});
  window.BizmaticPOLink.mount({root:{insertAdjacentHTML(){},querySelector(){return form;}},record:{id:1,partyId:1},resource:'invoices',
    data:{'purchase-orders':[]},card:(_,body)=>body,esc:String});
  await submit({preventDefault(){}});
  assert.equal(error.hidden,false);assert.match(error.textContent,/record changed/);assert.equal(select.value,'2');assert.equal(reloads,0);
});
