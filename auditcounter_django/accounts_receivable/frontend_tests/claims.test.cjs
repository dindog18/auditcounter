const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const script=fs.readFileSync(__dirname+'/../static/accounting/claims.js','utf8');
test('AP claim panel distinguishes drafts, correspondence and verified settlement',()=>{
 let html='';const host={appendChild:node=>html=node.innerHTML};const record={id:1,findings:[],investigation:null,claims:[{id:1,reference:'<unsafe>',status:'accepted',currency:'PHP',claimed_amount:'36000.00',accepted_amount:'36000.00',resolution_notes:'<img>',revision:'current',draft:'Not sent',correspondence:[]}],settlement:{invoices:[]}};
 vm.runInNewContext(script,{document:{getElementById:()=>({textContent:JSON.stringify({mode:'ap',resource:'reconciliation',screen:'detail',recordId:1})}),querySelector:()=>host,createElement:()=>({addEventListener(){}})},window:{BizmaticAccounting:{state:{reconciliation:[record]}}}});
 assert.match(html,/&lt;unsafe&gt;/);assert.doesNotMatch(html,/<img>/);assert.match(html,/records only/);assert.match(html,/unverified/);assert.match(html,/Verify closure/);assert.match(html,/Verified applied credit/);
});
