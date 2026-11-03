const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(__dirname+'/../../discrepancies/static/discrepancies/analytics.js','utf8');
test('analytics renders authoritative currency buckets and paginates without write requests',async()=>{
 const handlers={},nodes={};for(const id of ['root-cause-analytics','analytics-filters','analytics-results','analytics-status','analytics-prev','analytics-next'])nodes[id]={dataset:{url:'/discrepancies/api/analytics/'},addEventListener:(kind,fn)=>handlers[id+kind]=fn};
 const calls=[];const payload={financial:[{module:'ap',currency:'USD',potential_exposure:'10.00'}],frequency:[],root_causes:[],confirmed_parties:[{module:'ar',party_name:'<script>',count:1}],sku_mismatches:[],durations:[],claim_aging:[],workflows:[],limitations:[],total_parties:30,page:1,page_size:25};
 vm.runInNewContext(source,{document:{getElementById:id=>nodes[id]},URLSearchParams,FormData:class{*[Symbol.iterator](){yield ['currency','USD']}},fetch:async url=>{calls.push(url);return {ok:true,json:async()=>payload}}});
 await new Promise(r=>setImmediate(r));assert.match(calls[0],/currency=USD/);assert.match(nodes['analytics-results'].innerHTML,/10.00/);assert.match(nodes['analytics-results'].innerHTML,/&lt;script&gt;/);assert.equal(nodes['analytics-next'].disabled,false);handlers['analytics-nextclick']();await new Promise(r=>setImmediate(r));assert.match(calls[1],/page=2/);
});
test('root causes remain human-reviewed and preserve unverified labels in AP and AR',()=>{
 const script=fs.readFileSync(__dirname+'/../static/accounting/root-causes.js','utf8');
 for(const mode of ['ap','ar']){let html='';const config={mode,resource:'reconciliation',screen:'detail',recordId:1};const record={id:1,investigation:{closed:false},findings:[{id:2,reviewDecision:'confirmed',reviewStale:false,evidence:[],rootCause:{category:'receiving',status:'confirmed',explanation:'<img>',actor_label:'<script>'}}]};
 vm.runInNewContext(script,{document:{getElementById:id=>id==='finance-config'?{textContent:JSON.stringify(config)}:{appendChild:node=>html=node.innerHTML},createElement:()=>({addEventListener(){}})},window:{BizmaticAccounting:{state:{reconciliation:[record]}}}});
 assert.match(html,/unverified/);assert.match(html,/Record reviewed cause/);assert.doesNotMatch(html,/<img>|<script>/);}
});
