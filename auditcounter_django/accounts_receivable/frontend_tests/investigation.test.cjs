const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/accounting/workspace.js'),'utf8');
const helpers=source.slice(source.indexOf('  function investigationActor('),source.indexOf('  function matchSummary('));
const esc=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const finding={id:7,code:'PRICE_VARIANCE',status:'open',reviewDecision:'confirmed',reviewNotes:'Compared PO pricing.',reviewStale:false,evidence:[]};
function record(){return {id:9,status:'exception',currency:'USD',investigationRevision:'revision',orderIds:[1],receiptIds:[2],invoiceIds:[3],findings:[finding],
  evaluation:{exposureComplete:true,unsupportedAmount:'12.34',overcharge:'56.78',undercharge:'9.00'},
  investigation:{id:1,workflowStatus:'investigating',responsibleDepartment:'Finance',nextAction:'Verify the delivery.',closed:false,reviewRequired:false,
    resolutionType:'',resolutionNotes:'',resolutionEvidence:[],openedAt:'2026-11-02T00:00:00Z',updatedAt:'2026-11-02T01:00:00Z',closedAt:null,
    availableStatuses:['investigating','waiting'],closureStatuses:['resolved','dismissed'],resolutionTypes:[{value:'other',label:'Other documented resolution'}],history:[]}};}
function context(row,extra={}){return {record:row,finding:row.findings[0],esc,money:value=>Number(value).toFixed(2),label:value=>String(value).replaceAll('_',' '),card:(title,body)=>title+body,a:(href,text)=>`<a href="${esc(href)}">${esc(text)}</a>`,find:()=>({reference:'DOC'}),...extra};}
function render(row,expression){return vm.runInNewContext(helpers+'\n'+expression,context(row));}

test('overview distinguishes workflow from accounting and uses backend exposure components without summing',()=>{
  const row=record();const html=render(row,'investigationOverview(record)');
  assert.match(html,/Investigation Overview/);assert.match(html,/Finance/);assert.match(html,/Verify the delivery/);
  assert.match(html,/USD 12.34/);assert.match(html,/56.78/);assert.match(html,/9.00/);assert.doesNotMatch(html,/69.12/);
  assert.match(html,/not recovered funds/);assert.match(html,/unverified/);assert.equal(row.status,'exception');
  const fresh={...row,investigation:null};assert.match(render(fresh,'investigationOverview(record)'),/Start investigation/);
});

test('review controls show stale human decisions separately and safely render user notes',()=>{
  const row=record();row.findings=[{...finding,reviewStale:true,reviewNotes:'<script>unsafe</script>'}];
  const html=render(row,'findingReview(record,finding)');
  assert.match(html,/Human review: confirmed/);assert.match(html,/Evidence changed since this review/);
  assert.match(html,/needs_more_evidence/);assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<script>/);
  assert.match(html,/required for dismissal/);assert.match(html,/Save finding review/);
});

test('closed investigation exposes reopening and preserved history without allowing review edits',()=>{
  const row=record();Object.assign(row.investigation,{closed:true,workflowStatus:'resolved',closureStatuses:[],resolutionType:'business_exception_accepted',resolutionNotes:'Original resolution.',reviewRequired:true,reviewReason:'Evidence changed.'});
  row.investigation.history=[{type:'resolution',previousStatus:'investigating',newStatus:'resolved',notes:'Original resolution.',actorLabel:'<img>',details:{resolution_type:'business_exception_accepted'},createdAt:'2026-11-02T01:00:00Z'}];
  const html=render(row,'investigationOverview(record)+findingReview(record,finding)+investigationHistory(record)');
  assert.match(html,/Reopen investigation/);assert.match(html,/Original resolution/);assert.match(html,/Renewed review required/);
  assert.doesNotMatch(html,/Save finding review/);assert.match(html,/Investigation History/);assert.match(html,/Staff label \(unverified\): &lt;img&gt;/);
});

test('workflow forms submit current revision and validated reference shapes through existing API',async()=>{
  const row=record();let handler,call,reloaded=false;
  const form={dataset:{investigationAction:'investigation-resolve'},values:[['workflow_status','resolved'],['resolution_type','other'],['resolution_notes','Documented.'],['evidence_ids','4'],['document_references','sales_invoice:3'],['actor_label','Staff label']],addEventListener:(_,fn)=>handler=fn};
  class FormData {constructor(form){this.values=form.values;}[Symbol.iterator](){return this.values[Symbol.iterator]();}getAll(key){return this.values.filter(row=>row[0]===key).map(row=>row[1]);}}
  vm.runInNewContext(helpers+'\nbindInvestigation(record);',context(row,{FormData,root:{querySelectorAll:()=>[form]},api:{post:async(...args)=>{call=args;}},location:{reload(){reloaded=true;}},showError:error=>{throw new Error(error);}}));
  await handler({preventDefault(){}});
  assert.equal(call[0],'investigation-resolve');assert.equal(call[1],9);assert.equal(call[2].revision,'revision');
  assert.equal(call[2].evidence_ids[0],4);assert.equal(call[2].document_references[0].kind,'sales_invoice');assert.equal(call[2].document_references[0].record_id,3);assert.equal(reloaded,true);
});
