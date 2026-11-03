(() => {
  'use strict';
  const root=document.getElementById('duplicate-invoices');if(!root)return;
  const form=root.querySelector('form'),results=root.querySelector('#duplicate-results'),status=root.querySelector('#duplicate-status');let page=1,serial=0;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  async function load(){const version=++serial;status.textContent='Loading duplicate candidates…';const params=new URLSearchParams({module:form.elements.module.value,decision:form.elements.decision.value,page});
    try{const response=await fetch(root.dataset.url+'?'+params);const data=await response.json();if(version!==serial)return;if(!response.ok)throw Error(data.message||'Unable to load candidates.');status.textContent=`${data.total} candidates · Page ${page}`;
      results.innerHTML=data.results.map(row=>`<article class="border-top py-3"><h3 class="fs-9">${esc(row.module.toUpperCase())} · <a href="${esc(row.first_url)}">${esc(row.details.first.reference)}</a> / <a href="${esc(row.second_url)}">${esc(row.details.second.reference)}</a></h3><p>${row.active?'Rule still detects similarity':'No longer detected'} · Human decision: ${esc(row.decision)} ${row.review_stale?'· Evidence changed since review':''}</p><ul>${[...row.details.reasons,...row.details.conflicts].map(text=>`<li>${esc(text)}</li>`).join('')}</ul><details><summary>Compared fields and source references</summary><pre>${esc(JSON.stringify(row.details,null,2))}</pre></details><details><summary>Detection and review history</summary>${row.history.map(entry=>`<p>${esc(entry.created_at)} · ${esc(entry.decision)} · ${esc(entry.notes)}</p>`).join('')}</details><form data-review="${row.id}" data-revision="${esc(row.revision)}"><label>Decision<select name="decision" class="form-select"><option value="confirmed">Confirm possible duplicate</option><option value="dismissed">Dismiss candidate</option></select></label><label>Explanation<textarea name="notes" class="form-control" required maxlength="2000"></textarea></label><button class="btn btn-primary mt-2">Save review</button></form></article>`).join('')||'<p>No candidates match. Check an invoice for duplicates from its existing detail page.</p>';
      root.querySelector('#duplicate-prev').disabled=page===1;root.querySelector('#duplicate-next').disabled=page*25>=data.total;
    }catch(error){status.textContent=error.message;}
  }
  form.addEventListener('submit',e=>{e.preventDefault();page=1;load();});
  root.querySelector('#duplicate-prev').addEventListener('click',()=>{page--;load();});root.querySelector('#duplicate-next').addEventListener('click',()=>{page++;load();});
  results.addEventListener('submit',async e=>{const f=e.target;if(!f.dataset.review)return;e.preventDefault();const button=f.querySelector('button');button.disabled=true;
    try{const response=await fetch(root.dataset.url+f.dataset.review+'/review/',{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':form.elements.csrfmiddlewaretoken.value},body:JSON.stringify({revision:f.dataset.revision,decision:f.elements.decision.value,notes:f.elements.notes.value})});const data=await response.json();if(!response.ok)throw Error(data.message);await load();}catch(error){status.textContent=error.message;button.disabled=false;}
  });load();
})();
