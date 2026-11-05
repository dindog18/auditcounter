const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

test('AP and AR display and save multiple deliveries for one invoice line', async () => {
  for(const mode of ['ap','ar']) {
    const receipt = id => ({id, reference:`DR-${id}`, lines:[{id:id+100,code:'SKU-1',accepted:2}]});
    const state = {
      today:'2026-11-05',
      parties:[{id:1,name:'Example'}],
      'purchase-orders':[{id:10,reference:'PO-1',lines:[{id:101,code:'SKU-1',quantity:4}]}],
      'delivery-receipts':[receipt(20),receipt(21)],
      invoices:[{id:30,reference:'INV-1',lines:[{id:301,code:'SKU-1',unit:'pc',quantity:4,price:25}]}],
      payments:[],allocations:[],
      reconciliation:[{
        id:1,partyId:1,reference:'CASE-1',currency:'PHP',matchRevision:'revision-1',
        invoiceIds:[30],orderIds:[10],receiptIds:[20,21],
        matches:[
          {invoiceId:30,invoiceLine:0,orderId:10,orderLine:0,receiptId:20,receiptLine:0,quantity:2},
          {invoiceId:30,invoiceLine:0,orderId:10,orderLine:0,receiptId:21,receiptLine:0,quantity:2},
        ],
      }],
    };
    const callbacks={};
    const save={disabled:false}, summary={textContent:''}, lineSummary={textContent:''};
    const row = (receiptId) => ({
      dataset:{invoiceLine:'301'},
      querySelector:selector=>({
        '[data-order]':{value:'10:0'},
        '[data-receipt]':{value:`${receiptId}:0`},
        '[data-quantity]':{value:'2'},
      }[selector]),
    });
    const form = {
      querySelector:selector=>({
        '#save-matches':save,'#match-summary':summary,'[data-line-summary="301"]':lineSummary,
      }[selector]),
      querySelectorAll:selector=>selector==='[data-allocation]'?[row(20),row(21)]:[],
      addEventListener:(event,callback)=>{callbacks[event]=callback;},
      reportValidity:()=>true,
    };
    const root={innerHTML:'',querySelector:selector=>selector==='#match-form'?form:undefined};
    const calls=[];
    const location={search:'',href:'http://localhost/test'};
    const config={
      mode,resource:'reconciliation',recordId:1,screen:'match',
      party:mode==='ar'?'Customer':'Supplier',
      routes:{overview:'/overview/',reconciliation:'/reconciliation/'},
    };
    vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/accounting/workspace.js'),'utf8'), {
      window:{BizmaticAccounting:{state,post:async(...args)=>{calls.push(args);return {id:1};}}},
      document:{getElementById:id=>id==='finance-config'?{textContent:JSON.stringify(config)}:root},
      location,URLSearchParams,
    });
    assert.equal((root.innerHTML.match(/data-allocation data-invoice-line="301"/g)||[]).length,2);
    assert.match(root.innerHTML,/Add allocation/);
    assert.match(lineSummary.textContent,/Allocated 4.0000 \/ 4/);
    assert.equal(save.disabled,false);
    await callbacks.submit({preventDefault(){}});
    assert.equal(calls[0][0],'matches');
    assert.equal(calls[0][2].matches.length,2);
    assert.deepEqual(Array.from(calls[0][2].matches,row=>row.receiptLineId),[120,121]);
  }
});
