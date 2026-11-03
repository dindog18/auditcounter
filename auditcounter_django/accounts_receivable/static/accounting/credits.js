/* AP supplier credits: proposals do not affect balances until explicitly verified/applied. */
(() => {
  'use strict';
  const config=JSON.parse(document.getElementById('finance-config').textContent);
  if(config.resource!=='credits'||config.mode!=='ap')return;
  const api=window.BizmaticAccounting,state=api.state,root=document.getElementById('finance-root');
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const options=(rows,key,label)=>rows.map(row=>`<option value="${esc(row[key])}">${esc(label(row))}</option>`).join('');
  const field=(label,name,type='text',value='')=>`<label class="d-block mb-3">${esc(label)}<input class="form-control" name="${name}" type="${type}" value="${esc(value)}" required></label>`;
  const select=(label,name,html)=>`<label class="d-block mb-3">${esc(label)}<select class="form-select" name="${name}" required><option value="">Choose…</option>${html}</select></label>`;
  const card=(title,content)=>`<section class="card mb-4"><div class="finance-card-head"><h2>${esc(title)}</h2></div><div class="finance-card-body">${content}</div></section>`;
  const credit=state.credits.find(row=>row.id===config.recordId);
  root.innerHTML=`<header class="finance-heading"><div><h1>Supplier credits</h1><p>Verified credits are invoice adjustments, not cash payments or automatically recovered money.</p></div><a class="btn btn-falcon-default" href="${esc(config.routes.credits)}">All credits</a></header><div id="credit-error" class="alert alert-danger" role="alert" hidden></div>`;
  if(!credit){
    root.insertAdjacentHTML('beforeend',card('Credit register',`<p>Showing up to 500 recent credits. Open a credit to inspect its applications and reversals.</p><div class="table-responsive"><table class="table finance-table"><thead><tr><th>Reference</th><th>Supplier</th><th>Status</th><th>Amount</th><th>Available</th></tr></thead><tbody>${state.credits.map(row=>`<tr><td><a href="${esc(config.routes.credits+row.id+'/')}">${esc(row.reference)}</a></td><td>${esc(state.parties.find(p=>p.id===row.supplier_id)?.name)}</td><td>${esc(row.status)}</td><td>${esc(row.currency)} ${esc(row.credit_amount)}</td><td>${esc(row.currency)} ${esc(row.available_amount)}</td></tr>`).join('')||'<tr><td colspan="5">No supplier credits recorded.</td></tr>'}</tbody></table></div>`)+card('Record a draft credit',`<p>Manual entry with an existing uploaded supporting document. Extraction/import of credit notes is not enabled.</p><form data-credit="create">${select('Supplier','supplier_id',options(state.parties,'id',p=>p.name))}${field('Credit reference','reference')}${field('Issue date','issue_date','date',state.today)}${field('Currency','currency','text','PHP')}${field('Credit amount (decimal)','credit_amount')}${select('Supporting document','source_document_id',options(state.documents,'pk',d=>d.file_name))}<button class="btn btn-primary">Save draft</button></form>`));
  }else{
    root.insertAdjacentHTML('beforeend',card(credit.reference,`<p>${esc(credit.status)} · ${esc(credit.currency)} ${esc(credit.credit_amount)} · Available ${esc(credit.available_amount)}</p><p>${esc(credit.verification_notes)}</p>${credit.document_url?`<a href="${esc(credit.document_url)}">Supporting document</a>`:''}`));
    if(credit.status==='draft')root.insertAdjacentHTML('beforeend',card('Verify supporting evidence',`<form data-credit="verify">${field('Verification explanation','notes')}<button class="btn btn-primary">Verify credit</button></form>`));
    if(credit.status==='verified')root.insertAdjacentHTML('beforeend',card('Apply credit',`<form data-credit="apply">${select('Invoice','invoice_id',options(state.invoices.filter(i=>i.supplier_id===credit.supplier_id&&i.currency===credit.currency),'id',i=>i.reference+' · '+i.currency+' '+i.balance+' outstanding'))}${field('Amount to apply','amount')}${field('Application date','application_date','date',state.today)}${field('Application explanation','notes')}<button class="btn btn-primary">Apply verified credit</button></form>`));
    root.insertAdjacentHTML('beforeend',card('Application history',credit.applications.map(row=>`<article class="border-top py-3"><a href="${esc(config.routes.invoices+row.invoice_id+'/')}">${esc(row.invoice_reference)}</a> · ${esc(credit.currency)} ${esc(row.amount)} · ${esc(row.date)}<p>${esc(row.notes)}</p>${row.reversed?`<strong>Reversed</strong><p>${esc(row.reversal_reason)}</p>`:`<form data-credit="reverse" data-id="${row.id}">${field('Reason for reversal','reason')}<button class="btn btn-falcon-default">Reverse application</button></form>`}</article>`).join('')||'<p>No applications.</p>'));
  }
  root.addEventListener('submit',async event=>{
    const form=event.target;if(!form.dataset.credit)return;event.preventDefault();
    const action=form.dataset.credit,values=Object.fromEntries(new FormData(form));
    for(const key of ['supplier_id','source_document_id','invoice_id'])if(values[key])values[key]=Number(values[key]);
    if(credit)values.revision=credit.revision;
    if(action==='apply'){form.dataset.requestKey ||= crypto.randomUUID();values.request_key=form.dataset.requestKey;}
    try{const result=await api.post('credit-'+action,action==='reverse'?Number(form.dataset.id):credit?.id,values);location.href=config.routes.credits+(action==='create'?result.id:credit.id)+'/';}
    catch(error){const box=root.querySelector('#credit-error');box.textContent=error.message;box.hidden=false;box.scrollIntoView({block:'nearest'});}
  });
})();
