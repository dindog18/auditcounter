const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/accounting/workspace.js'),'utf8');
const helper=source.slice(source.indexOf('  function skuAssistance(state)'),source.indexOf('  function matching(record)'));
const esc=value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
function setup({action='sku-suggest',alias=false,fail=false}={}) {
  const ref={kind:'sales_invoice',record_id:1,line_id:11};
  const canonical={kind:'purchase_order',record_id:2,line_id:21};
  const sku={revision:'catalog-v1',sources:[{key:'source',reference:ref,code:'WW80T',description:'Samsung 8kg <untrusted>',unit:'PCS',record_reference:'INV',record_url:'/invoice/1/',needs_mapping:true}],targets:[{key:'target',reference:canonical,code:'SAMSUNG-WW80T',description:'Samsung 8kg',unit:'PCS',record_reference:'PO'}],aliases:[{id:4,revision:'alias-v1',source_code:'WW80T',canonical_code:'SAMSUNG-WW80T',source_description:'Washer',canonical_description:'Washer',unit:'PCS',status:action==='sku-deactivate'?'approved':'pending',target_current:true,reason:'Unverified AI proposal',approval_notes:'',history:[]}],attempts:[]};
  const fields={'#sku-source':{value:'source',addEventListener(){}},'#sku-target':{value:'target',addEventListener(){}},'#sku-approval-note':{value:'Verified model and source records'},'#sku-source-detail':{innerHTML:''},'#sku-target-detail':{innerHTML:''},'[data-sku-error]':{hidden:true,textContent:''},'[data-sku-progress]':{textContent:''}};
  const aliasNode={dataset:{skuAlias:'4'},querySelector:()=>({value:'Verified source model'})};
  const button={dataset:{skuAction:action},disabled:false,closest:()=>alias?aliasNode:null,addEventListener:(_,fn)=>{button.click=fn;}};
  const panel={innerHTML:'',querySelector:selector=>fields[selector],querySelectorAll:()=>[button]};
  const root={querySelector:()=>panel};
  const calls=[];let changes=0;
  const record={id:9,sku};
  const response={matchRevision:'matching-v2',sku:{...sku,revision:'catalog-v2',attempts:[{source:{code:'WW80T'},status:'failed',provider:'ollama',model:'test',suggestion:{},errors:['Provider unavailable. Manual mapping remains available.']} ]}};
  const draft=[{invoiceLineId:11,quantity:'60'}];
  const context={root,record,esc,badge:esc,card:(title,body)=>title+body,a:(href,label)=>`<a href="${href}">${label}</a>`,api:{post:async(...args)=>{calls.push(args);if(fail)throw new Error('Products changed; reload');return response;}},changed:result=>{changes++;record.matchRevision=result.matchRevision;}};
  vm.runInNewContext(helper+'\nbindSkuAssistance(record,changed);',context);
  return {button,fields,panel,record,calls,draft,ref,canonical,changes:()=>changes};
}
test('SKU proposals show original descriptions, explicit review controls, statuses and escaped untrusted text',()=>{
  const ui=setup();
  assert.match(ui.panel.innerHTML,/Request AI suggestion/);
  assert.match(ui.panel.innerHTML,/Approve proposal/);
  assert.match(ui.panel.innerHTML,/Reject proposal/);
  assert.match(ui.panel.innerHTML,/Unverified AI proposal/);
  assert.match(ui.fields['#sku-source-detail'].innerHTML,/&lt;untrusted>/);
  assert.doesNotMatch(ui.fields['#sku-source-detail'].innerHTML,/<untrusted>/);
});
test('AI requests preserve drafts and never approve; failure response retains manual mapping',async()=>{
  const ui=setup();await ui.button.click();
  assert.equal(ui.calls[0][0],'sku-suggest');
  assert.deepEqual(JSON.parse(JSON.stringify(ui.calls[0][2])),{revision:'catalog-v1',source_reference:ui.ref});
  assert.equal(ui.draft[0].quantity,'60');
  assert.equal(ui.changes(),0);
  assert.match(ui.panel.innerHTML,/Provider unavailable. Manual mapping remains available/);
  assert.match(ui.panel.innerHTML,/Approve selected equivalence/);
});
test('manual approval sends selected existing product references and written explanation',async()=>{
  const ui=setup({action:'sku-approve'});await ui.button.click();
  assert.deepEqual(JSON.parse(JSON.stringify(ui.calls[0][2])),{revision:'catalog-v1',source_reference:ui.ref,canonical_reference:ui.canonical,approval_notes:'Verified model and source records'});
  assert.equal(ui.changes(),1);
  assert.equal(ui.record.matchRevision,'matching-v2');
  assert.equal(ui.draft.length,1);
});
for(const action of ['sku-approve','sku-reject','sku-deactivate']) test(`${action} sends mapping and catalog revisions; only identity changes invalidate previews`,async()=>{
  const ui=setup({action,alias:true});await ui.button.click();
  const body=ui.calls[0][2];
  assert.equal(body.alias_id,4);assert.equal(body.alias_revision,'alias-v1');assert.equal(body.revision,'catalog-v1');
  assert.equal(body[action==='sku-approve'?'approval_notes':'reason'],'Verified source model');
  assert.equal(ui.changes(),action==='sku-reject'?0:1);
});
test('stale errors preserve the review and allocation draft for correction',async()=>{
  const ui=setup({action:'sku-approve',fail:true});await ui.button.click();
  assert.equal(ui.fields['[data-sku-error]'].hidden,false);
  assert.match(ui.fields['[data-sku-error]'].textContent,/Products changed/);
  assert.equal(ui.button.disabled,false);
  assert.equal(ui.record.sku.revision,'catalog-v1');
  assert.equal(ui.changes(),0);
});
