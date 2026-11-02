const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/accounting/workspace.js'),'utf8');
const helper=source.slice(source.indexOf('  function discrepancyFindings('),source.indexOf('  function matchSummary('));
const escape=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const finding={code:'PRICE_VARIANCE',severity:'warning',status:'open',summary:'100 supported units; price differs.',
  expected:{unit_price:'18000'},actual:{unit_price:'18500'},difference:'50000.00000000',currency:'EUR',ruleVersion:'1',
  firstDetectedAt:'2026-11-02T01:00:00Z',lastDetectedAt:'2026-11-02T02:00:00Z',clearedAt:null,
  evidence:[{type:'SI',sourceModel:'accounts_receivable.CompanySalesInvoice',recordId:'12',lineId:'20',
    recordUrl:'/accounts-receivable/invoices/12/',documentUrl:'/documents/8/',databaseUrl:'/databases/3/',
    provenance:{file_name:'invoice.pdf',table_name:'public.invoices'},sourceKey:{invoice_id:42},field:'line_values',
    observed:{line:{unit_price:'18500',description:'<script>bad</script>'}},findingSnapshot:{actual_value:{unit_price:'18500'}},capturedAt:'2026-11-02T01:00:00Z'}]};
function context(record){return {record,esc:escape,money:value=>Number(value).toFixed(2),label:value=>String(value).replaceAll('_',' '),card:(title,body,actions='')=>title+actions+body,a:(href,text)=>`<a href="${escape(href)}">${escape(text)}</a>`};}
function render(record){return vm.runInNewContext(helper+'\ndiscrepancyFindings(record);',context(record));}

test('findings render backend amounts, comparisons, dates and existing source links',()=>{
  const html=render({findings:[finding]});
  assert.match(html,/Discrepancy Findings/);
  assert.match(html,/EUR 50000.00/);
  assert.match(html,/18000/);assert.match(html,/18500/);
  assert.match(html,/First detected:/);assert.match(html,/Latest detection:/);
  assert.match(html,/\/accounts-receivable\/invoices\/12\//);
  assert.match(html,/\/documents\/8\//);assert.match(html,/\/databases\/3\//);
  assert.match(html,/ERP record key/);assert.match(html,/42/);
  assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<script>/);
  assert.match(html,/amounts can overlap/i);
});

test('cleared history remains visible and missing evidence never displays a fabricated amount',()=>{
  const html=render({findings:[{...finding,status:'cleared',clearedAt:'2026-11-02T03:00:00Z'},
    {...finding,code:'MISSING_DR',severity:'information',difference:null,status:'open',evidence:[]}]});
  assert.match(html,/finance-status success/);assert.match(html,/Cleared:/);
  assert.match(html,/Evidence gap or amount not sufficiently supported/);
  assert.doesNotMatch(html,/EUR 0.00/);
});

test('legacy cases without saved findings offer explicit recalculation',()=>{
  const html=render({});assert.match(html,/No persisted findings/);assert.match(html,/Recalculate findings/);
});

test('case recalculation sends the revision through the existing API then reloads',async()=>{
  const segment=source.slice(source.indexOf('  function caseDetail('),source.indexOf('  function matchSummary('));
  let handler,call,reloaded=false;
  const record={id:3,status:'matched',discrepancy:0,currency:'EUR',matches:[],orderIds:[],receiptIds:[],invoiceIds:[],findings:[],matchRevision:'revision'};
  const ctx={...context(record),root:{insertAdjacentHTML(){},querySelector:()=>({addEventListener:(_,fn)=>handler=fn})},
    kpi:()=>'',icon:()=>'',matchSummary:()=>'',url:()=>'',meta:()=>'',date:()=>'',partyName:()=>'',config:{party:'Customer'},
    location:{reload(){reloaded=true;}},showError:message=>{throw new Error(message);},api:{post:async(...args)=>{call=args;}}};
  vm.runInNewContext(segment+'\ncaseDetail(record);',ctx);
  await handler();
  assert.equal(call[0],'recalculate');assert.equal(call[1],3);assert.equal(call[2].revision,'revision');assert.equal(reloaded,true);
});
