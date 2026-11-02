const {test}=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm');const fs=require('node:fs');const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/accounting/workspace.js'),'utf8');const helper=source.slice(source.indexOf('  function timelinePanel('),source.indexOf('  function caseDetail('));
function setup(mode='ap',empty=false,fail=false){
 const status={textContent:''},error={hidden:true,textContent:''},rows={innerHTML:'',insertAdjacentHTML(_,html){this.innerHTML+=html;}},select={value:'',addEventListener(_,fn){this.change=fn;}},more={hidden:false,disabled:false,addEventListener(_,fn){this.click=fn;}};
 const panel={querySelector:s=>({'select':select,'button':more,'[data-timeline-status]':status,'[data-timeline-error]':error,'[data-timeline-rows]':rows}[s])};const calls=[];
 const event={title:'<script>untrusted</script>',category:'documents',description:'Original evidence',recordedAt:'2026-11-02T00:00:00Z',occurredAt:'2026-10-31',source:{type:'Invoice',id:1,url:'/invoice/1/'},details:{before:{price:'18.00'},after:{price:'19.00'}},evidence:[{documentUrl:'/documents/1/',observed:{code:'<unsafe>'}}]};
 const ctx={config:{mode},record:{id:3},root:{querySelector:()=>panel},esc:v=>String(v??'').replaceAll('<','&lt;').replaceAll('>','&gt;'),label:String,a:(url,text)=>`<a href="${url}">${text}</a>`,card:(title,html)=>title+html,fetch:async url=>{calls.push(url);if(fail)throw new Error('Unavailable');return {ok:true,json:async()=>({results:empty?[]:[event],total:empty?0:26})};}};
 vm.runInNewContext(helper+'\nbindTimeline(record);',ctx);
 return {ctx,calls,status,error,rows,select,more};
}
for(const mode of ['ap','ar'])test(`${mode}: renders safe history/evidence and separates business date`,async()=>{
 const ui=setup(mode);await new Promise(setImmediate);assert.match(ui.calls[0],new RegExp('/'+mode+'/3/timeline/'));assert.match(ui.rows.innerHTML,/&lt;script&gt;/);assert.doesNotMatch(ui.rows.innerHTML,/<script>/);assert.match(ui.rows.innerHTML,/Supporting document/);assert.match(ui.rows.innerHTML,/Business date\/time/);assert.match(ui.rows.innerHTML,/18.00/);
 await ui.more.click();await new Promise(setImmediate);assert.match(ui.calls[1],/page=2/);
 ui.select.value='investigations';await ui.select.change();await new Promise(setImmediate);assert.match(ui.calls[2],/category=investigations&page=1/);
});
test('empty state and errors are readable and allow retry',async()=>{
 const empty=setup('ap',true);await new Promise(setImmediate);assert.match(empty.status.textContent,/No timeline events/);assert.equal(empty.more.hidden,true);
 const failed=setup('ar',false,true);await new Promise(setImmediate);assert.equal(failed.error.hidden,false);assert.match(failed.error.textContent,/Unavailable/);assert.equal(failed.more.disabled,false);
});
