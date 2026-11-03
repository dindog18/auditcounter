const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync(__dirname+'/../../discrepancies/static/discrepancies/duplicate-invoices.js','utf8');
test('duplicate review renders escaped source evidence and does not send a review on load',async()=>{
 const results={innerHTML:'',addEventListener(){}},status={textContent:''},buttons={addEventListener(){}};
 const form={elements:{module:{value:'ap'},decision:{value:''}},addEventListener(){}};
 const root={dataset:{url:'/discrepancies/api/duplicate-invoices/'},querySelector:selector=>selector==='form'?form:selector==='#duplicate-results'?results:selector==='#duplicate-status'?status:buttons};
 const calls=[];const row={id:1,module:'ap',active:true,decision:'unreviewed',revision:'x',review_stale:false,first_url:'/ap/invoices/1/',second_url:'/ap/invoices/2/',details:{first:{reference:'<script>'},second:{reference:'INV'},reasons:['Same reference'],conflicts:[]},history:[{created_at:'2026-11-02',decision:'detected',notes:'<img>'}]};
 vm.runInNewContext(source,{document:{getElementById:()=>root},URLSearchParams,fetch:async(url,options)=>{calls.push([url,options]);return {ok:true,json:async()=>({results:[row],total:1})}}});
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(calls.length,1);assert.equal(calls[0][1],undefined);assert.match(calls[0][0],/module=ap/);
 assert.match(results.innerHTML,/&lt;script&gt;/);assert.doesNotMatch(results.innerHTML,/<script>|<img>/);assert.match(results.innerHTML,/Human decision: unreviewed/);assert.match(results.innerHTML,/Save review/);
});
