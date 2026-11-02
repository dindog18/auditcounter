(()=>{
  'use strict';
  const root=document.querySelector('#discrepancy-dashboard');if(!root)return;
  const form=root.querySelector('form'),get=id=>root.querySelector('#dashboard-'+id);
  const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const label=value=>String(value??'None').replaceAll('_',' ');
  let page=1,controller;
  const initial=new URLSearchParams(location.search);for(const [key,value] of initial){if(form.elements[key])form.elements[key].value=value;}page=Number(initial.get('page'))||1;
  async function load(){
    controller?.abort();const current=new AbortController();controller=current;
    const params=new URLSearchParams(new FormData(form));for(const [key,value] of [...params])if(!value)params.delete(key);params.set('page',page);
    get('status').textContent='Loading discrepancy cases…';get('error').hidden=true;get('rows').innerHTML='';get('metrics').innerHTML='';get('financial').innerHTML='';get('prev').disabled=get('next').disabled=true;
    try{
      const read=async url=>{const response=await fetch(url+'?'+params,{signal:current.signal,headers:{Accept:'application/json'}});const body=await response.json();if(!response.ok)throw new Error(body.message+' '+Object.entries(body.errors||{}).map(([key,errors])=>key+': '+errors.map(error=>error.message).join(' ')).join(' '));return body;};
      const [cases,summary]=await Promise.all([read(root.dataset.cases),read(root.dataset.summary)]);if(controller!==current)return;
      history.replaceState(null,'','?'+params);
      get('metrics').innerHTML=[['total','Relevant cases'],['needs_review','Needs review'],['in_progress','Investigating'],['waiting','Waiting for action'],['resolved','Resolved'],['renewed_review','Renewed review']].map(([key,title])=>`<div class="card p-3"><span>${title}</span><strong>${esc(summary[key])}</strong></div>`).join('');
      get('financial').innerHTML=summary.financial.map(row=>`<div class="card p-3">${esc(row.module.toUpperCase())} · ${esc(row.currency||'Unspecified currency')} · Reconciliation differences: <strong>${esc(row.amount??'Unavailable')}</strong></div>`).join('');
      get('rows').innerHTML=cases.results.map(row=>`<tr><td><a href="${esc(row.detail_url)}">${esc(row.reference)}</a>${row.review_required?'<div class="text-warning">Renewed review required</div>':''}</td><td>${esc(row.module.toUpperCase())}</td><td>${esc(row.party_name)}</td><td>${esc(row.transaction_date||'Not recorded')}</td><td>${esc(label(row.reconciliation_status))}</td><td>${esc(label(row.investigation_status))}</td><td>${esc(row.open_findings_count)}</td><td>${esc(label(row.highest_severity))}</td><td>${esc(row.currency||'Unspecified')} ${esc(row.discrepancy_amount??'Unavailable')}</td><td><a href="${esc(row.detail_url)}">Open case</a></td></tr>`).join('')||'<tr><td colspan="10">No discrepancy cases match these filters. Adjust or reset the filters.</td></tr>';
      get('status').textContent=cases.count+' relevant cases';get('page').textContent=`Page ${cases.page} of ${cases.pages}`;get('prev').disabled=page<=1;get('next').disabled=page>=cases.pages;
    }catch(error){if(error.name==='AbortError'||controller!==current)return;get('status').textContent='';get('error').textContent='Could not load discrepancy cases. '+error.message;get('error').hidden=false;}
  }
  form.addEventListener('submit',event=>{event.preventDefault();page=1;load();});form.addEventListener('reset',()=>{setTimeout(()=>{page=1;load();},0);});get('prev').onclick=()=>{page--;load();};get('next').onclick=()=>{page++;load();};load();
})();
