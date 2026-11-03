/* Aggregation is authoritative on the server; no financial arithmetic here. */
(() => {
  'use strict';
  const host=document.getElementById('root-cause-analytics');if(!host)return;
  const form=document.getElementById('analytics-filters'),output=document.getElementById('analytics-results'),status=document.getElementById('analytics-status'),prev=document.getElementById('analytics-prev'),next=document.getElementById('analytics-next');
  const esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const label=v=>String(v).replaceAll('_',' ');
  const table=(title,rows,columns)=>`<h3 class="fs-9 mt-4">${esc(title)}</h3>${rows.length?`<div class="table-responsive"><table class="table finance-table"><thead><tr>${columns.map(([key,title])=>`<th>${esc(title||label(key))}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${columns.map(([key])=>`<td>${esc(row[key])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`:'<p>No records match these filters.</p>'}`;
  let page=1,generation=0;
  async function load(){const request=++generation;status.textContent='Loading reviewed outcomes…';prev.disabled=next.disabled=true;const params=new URLSearchParams();for(const [key,value] of new FormData(form))if(value)params.set(key,value);params.set('page',page);
    try{const response=await fetch(host.dataset.url+'?'+params);const result=await response.json();if(request!==generation)return;if(!response.ok)throw Error(result.message||'Unable to load analytics.');
      output.innerHTML=table('Financial measures by module and currency',result.financial,[['module'],['currency'],['case_count','Cases'],['potential_exposure','Potential case differences'],['validated_claims','Validated claims'],['applied_credits','Applied credits'],['applied_adjustments','Applied deductions'],['verified_cash_recoveries','Verified cash recoveries']])+
        table('Finding frequency and recorded human confirmations',result.frequency,[['module'],['finding_code'],['count','Findings'],['confirmed','Recorded confirmations']])+
        table('Current confirmed root causes',result.root_causes,[['module'],['category'],['count']])+
        table('Confirmed findings by supplier / customer',result.confirmed_parties,[['module'],['party_id'],['party_name'],['count']])+
        table('Repeated reviewed SKU codes',result.sku_mismatches,[['module'],['party_id'],['sku','Original invoice SKU'],['count']])+
        table('Closed investigation and claim durations',result.durations,[['module'],['currency'],['closed_investigations'],['average_investigation_seconds','Average investigation duration (seconds)'],['closed_claims'],['average_claim_seconds','Average claim duration (seconds)']])+
        table('Unresolved claim aging',result.claim_aging,[['currency'],['bucket','Age in days'],['count'],['claimed_amount']])+
        '<h3 class="fs-9 mt-4">Operational registers</h3><p>These counts include unlinked records and use only module, party, currency and source-date filters.</p>'+result.workflows.map(w=>`<p><strong>${esc(label(w.register))}</strong> · ${w.counts.map(c=>esc(c.status||c.reconciliation_status)+': '+esc(c.count)).join(' · ')}</p>`).join('')+
        '<p><a href="/accounts-payable/credits/">Supplier credits</a> · <a href="/accounts-payable/statements/">Supplier statements</a> · <a href="/accounts-receivable/deductions/">Customer deductions</a> · Supplier claims are inside AP case investigations.</p>'+result.limitations.map(t=>`<p class="text-600">${esc(t)}</p>`).join('');
      status.textContent=`Confirmed parties: ${result.total_parties} · Page ${result.page}`;prev.disabled=page<=1;next.disabled=page*result.page_size>=result.total_parties;
    }catch(error){if(request!==generation)return;output.innerHTML='';status.textContent=error.message;}
  }
  form.addEventListener('submit',e=>{e.preventDefault();page=1;load();});prev.addEventListener('click',()=>{page--;load();});next.addEventListener('click',()=>{page++;load();});load();
})();
