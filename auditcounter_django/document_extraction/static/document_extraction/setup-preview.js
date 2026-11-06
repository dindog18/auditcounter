(() => {
  'use strict';
  const root = document.querySelector('#setup-preview');
  if (!root) return;
  const find = name => root.querySelector(`[data-${name}]`);
  const panel = find('panel');
  const actions = find('actions');
  const prerequisites = [...find('prerequisites').content.children];
  const documents = ['Delivery receipt', 'Sales invoice', 'Deduction'];
  const selections = {};
  let module = 'Accounts Payable';
  let index = 0;
  let database = 'No';
  let useEncoder = null;
  const routes = JSON.parse(document.getElementById('setup-preview-routes').textContent);
  const readiness = JSON.parse(document.getElementById('guided-setup-readiness').textContent);
  const storageKey = 'auditcounter:guided-setup:v1';
  const answers = {};
  const issued = {};
  const sourceOptions = () => ['Document', ...(database === 'Yes' ? ['PostgreSQL'] : []), 'Manual entry'];
  const passed = {};
  let finished = false;
  const integrations = {
    routing: { label: 'Document routing', group: 'ROUTER', description: 'Create destinations and rules for the documents you want AuditCounter to route.' },
    encoder: { label: 'MCP Encoder', group: 'ENCODER', description: 'Connect an MCP server, approve the tools you intend to use, and prepare a routed document for review.' }
  };
  const accountingModules = ['Accounts Payable', 'Accounts Receivable'];
  const selectedModules = () => module === 'Both' ? accountingModules : accountingModules.filter(name => name === module);
  const workflowOptions = [...accountingModules, 'MCP Encoder'];
  const steps = () => ['workflow', ...(useEncoder === 'Yes' ? ['encoder'] : []), 'database', ...(database === 'Yes' ? ['connection'] : []), ...selectedModules().flatMap(m => [
    `${m}|selection`, `${m}|prerequisites`, `${m}|${m === 'Accounts Payable' ? 'Supplier' : 'Customer'}`, `${m}|Purchase order`, ...documents.filter(d => (selections[m] || []).includes(d)).map(d => `${m}|${d}`), `${m}|Payment`
  ]), 'routing', 'review'];
  const issuedRecords = flow => flow.filter(key =>
    routes[key] && (answers[key] || 'Document') === 'Document' && issued[key]
  );
  const title = key => integrations[key]?.label || (key === 'workflow' ? 'Workflow' : key === 'review' ? 'Review' : key === 'database' ? 'Database choice' : key === 'connection' ? 'Database connection' : key.replace('|prerequisites', '|Environment (.env)').replace('|', ' · '));
  const button = (label, action, primary = false, disabled = false) =>
    `<button type="button" class="btn btn-${primary ? 'primary' : 'outline-secondary'}" data-action="${action}" ${disabled ? 'disabled' : ''}>${label}</button>`;
  function requirements(key, flow) {
    const route = routes[key];
    const source = answers[key] || 'Document';
    if (route && source === 'Document') return [
      [route.document_environment, 'Configure the document extraction, configuration assistant, and accounting AI settings in .env.'],
      [route.document_ready, 'Submit a document extraction configuration for this record type.'],
    ];
    if (route && source === 'PostgreSQL') return [
      [route.database_ready, 'Submit a PostgreSQL extraction configuration for this record type using an enabled connection with a current schema snapshot.'],
    ];
    if (key === 'connection') return [
      [readiness.database, 'Prepare encrypted credential storage and refresh the schema of an enabled PostgreSQL connection. Refresh the schema again after editing the connection.'],
    ];
    if (key === 'encoder') return [
      [readiness.encoder_access, 'Enable local MCP Encoder access and open Guided setup on a trusted loopback development server.'],
      [readiness.encoder_connection, 'Test an MCP connection and approve the operation you intend to use.'],
      [readiness.router, 'Configure the routing AI settings in .env.'],
      [readiness.encoder_rule, 'Create an active MCP Encoder destination and rule linked to a discovered, permitted MCP operation.'],
    ];
    if (key === 'routing' && issuedRecords(flow).length) return [
      [readiness.router, 'Configure the routing AI settings in .env.'],
      ...issuedRecords(flow).map(item => [
        routes[item].document_ready && routes[item].routing_ready,
        `${title(item)} needs a submitted document configuration and an active rule for its routing destination.`,
      ]),
    ];
    return [];
  }

  function needsAttention(key, flow) {
    if (passed[key] === 'skipped') return false;
    if (['workflow', 'database', 'review'].includes(key) || key.endsWith('|selection')) return false;
    if (key === 'routing' && !issuedRecords(flow).length) return false;
    return passed[key] !== true || requirements(key, flow).some(([ready]) => !ready);
  }

  function render(focus = true) {
    const flow = steps();
    const key = flow[index];
    const [current, stage] = key.split('|');
    const checks = requirements(key, flow);
    const ready = checks.every(([configured]) => configured);
    const unfinished = key === 'review' ? flow.filter(item => needsAttention(item, flow)) : [];
    const hasSkipped = flow.some(item => passed[item] === 'skipped' &&
      (item !== 'routing' || issuedRecords(flow).length));
    find('progress').innerHTML = flow.map((item, i) => `<li ${i === index ? 'aria-current="step"' : ''}><span class="setup-preview-number" aria-hidden="true">${i < index && !needsAttention(item, flow) && passed[item] !== 'skipped' ? '✓' : i + 1}</span>${title(item)}</li>`).join('');
    let heading, body;
    let recordAction;
    const route = routes[key];
    const integration = integrations[key];
    const routingRecords = key === 'routing' ? issuedRecords(flow) : [];
    const routingNeeded = key !== 'routing' || routingRecords.length > 0;
    const ungated = ['workflow', 'database', 'review'].includes(key) || stage === 'selection' || !routingNeeded;
    if (key === 'workflow') {
      heading = 'Which workflows would you like to set up?';
      const selected = [...selectedModules(), ...(useEncoder === 'Yes' ? ['MCP Encoder'] : [])];
      body = `<fieldset><legend class="visually-hidden">Select one or more workflows</legend><div class="d-flex flex-wrap gap-3">${workflowOptions.map((value, optionIndex) => `<label class="d-inline-flex align-items-center gap-2"><input type="checkbox" class="form-check-input mt-0" name="workflow" value="${value}" data-workflow-index="${optionIndex}" ${selected.includes(value) ? 'checked' : ''}> ${value}</label>`).join('')}</div></fieldset>
        <p class="mt-3 text-700">Select all that apply. MCP Encoder is set up first when selected. If you use both accounting workflows, Accounts Payable comes before Accounts Receivable.</p>`;
    } else if (key === 'database') {
      heading = 'Will you use a PostgreSQL database?';
      body = `<fieldset><legend class="visually-hidden">Use a database</legend>${['Yes', 'No'].map(value => `<label class="me-3"><input type="radio" name="database" value="${value}" ${database === value ? 'checked' : ''}> ${value}</label>`).join('')}</fieldset><p class="mt-3">${useEncoder === 'Yes' ? 'If MCP Encoder writes to PostgreSQL, connect to that database here so AP or AR can read the encoded records.' : 'Set up one connection now and reuse it for any record you choose to import.'}</p>`;
    } else if (key === 'connection') {
      heading = 'Set up your PostgreSQL connection';
      body = '<p>Open Database Connections to add or select a connection. Test it and refresh its schema, then return here to continue.</p>';
      recordAction = 'Mark connection ready';
    } else if (stage === 'selection') {
      heading = `${current}: which documents do you use?`;
      body = `<p>Purchase orders and payments are required. Select the other documents you want to set up.</p><fieldset><legend class="visually-hidden">Select documents</legend><label class="d-block mb-2"><input type="checkbox" checked disabled> Purchase order (required)</label><label class="d-block mb-2"><input type="checkbox" checked disabled> Payment (required)</label>${documents.map(d => `<label class="d-block mb-2"><input type="checkbox" name="document" value="${d}" ${(selections[current] || []).includes(d) ? 'checked' : ''}> ${d === 'Sales invoice' ? 'Sales invoice (SI)' : d === 'Delivery receipt' ? 'Delivery receipt (DR)' : d}</label>`).join('')}</fieldset>`;
    } else if (stage === 'prerequisites') {
      heading = `${current} environment settings (.env)`;
      body = '<p>These checks show whether the server has the AI settings used for document extraction and routing. If a setting needs attention, ask your administrator to update <code>auditcounter_django/.env</code> or the server environment, restart Django, and refresh this page.</p><p><strong>Present</strong> means the required settings are configured. Provider connectivity and credentials are checked when you run extraction or routing.</p><details open><summary>Current environment status</summary><ul class="mt-2" data-current-settings></ul></details>';
      recordAction = 'Mark environment reviewed';
    } else if (integration) {
      heading = `Set up ${key === 'encoder' ? integration.label : integration.label.toLowerCase()}`;
      body = `<p>${integration.description} Return here after setup and select Mark as done.</p>`;
      if (key === 'routing') {
        body = routingNeeded
          ? `<p>Use a submitted document extraction configuration for each record below. In Router, create or reuse the listed destination, then add an active rule that identifies the issued document and points to that destination.</p>
            <ul>${routingRecords.map(item => `<li><strong>${title(item)}</strong><br>Module: ${routes[item].routing_module} · Record type: ${routes[item].routing_model}</li>`).join('')}</ul>`
          : '<p>There are no issued documents selected for routing. Continue to review, or go back to a Document record and indicate that it has an issued document.</p>';
      }
      recordAction = key === 'encoder' ? 'Mark as done' : 'Mark document routing ready';
    } else if (key === 'review') {
      heading = 'Review your setup';
      if (finished && !unfinished.length) heading = hasSkipped ? 'Setup finished with skipped steps' : 'Setup finished';
      body = unfinished.length
        ? `<p>These steps need attention before you can finish:</p><ul>${unfinished.map(item =>
            `<li><button type="button" class="btn btn-link p-0" data-step-index="${flow.indexOf(item)}">${title(item)}</button></li>`
          ).join('')}</ul>`
        : hasSkipped ? '<p>Review your setup. Skipped integrations are listed below.</p>'
          : '<p>Your selected setup steps are ready.</p>';
      body += `<ul>${flow.filter(item => passed[item] && !unfinished.includes(item) &&
        (item !== 'routing' || issuedRecords(flow).length)).map(item =>
        `<li>${title(item)}${passed[item] === 'skipped' ? ' · skipped' : ''}${routes[item] ? ' · ' + (answers[item] || 'Document') : ''}</li>`
      ).join('')}</ul>`;
    } else {
      heading = `${current}: set up ${stage.toLowerCase()}`;
      const source = answers[key] || 'Document';
      const query = new URLSearchParams({ target: route.target, source: source === 'Document' ? 'document' : 'database' });
      body = `<fieldset><legend>How will this record be supplied?</legend>${sourceOptions().map(value => `<label class="d-inline-flex align-items-center gap-2 me-3"><input type="radio" class="form-check-input mt-0" name="source" value="${value}" ${source === value ? 'checked' : ''}> ${value}</label>`).join('')}</fieldset>`;
      if (source === 'Document') {
        body += `<label class="d-block mt-3"><input type="checkbox" name="issued-document" ${issued[key] ? 'checked' : ''}> This record has an issued document to route</label>`;
      }
      if (source === 'Manual entry') {
        body += `<p class="mt-3">Open the entry form or review existing records in a new tab. Return here when you’re ready to continue.</p>
          <a class="btn btn-outline-primary" href="${route.manual_create}" target="_blank" rel="noopener">Open manual entry form</a>
          <a class="btn btn-link" href="${route.manual_list}" target="_blank" rel="noopener">Open existing records</a>`;
        recordAction = 'Mark manual entry ready';
      } else {
        body += `<p class="mt-3">Open the extraction editor in a new tab. Return here after saving your configuration.</p>
        <a class="btn btn-outline-primary" href="${route.create}?${query}" target="_blank" rel="noopener">Open extraction setup</a>
        <a class="btn btn-link" href="${route.list}" target="_blank" rel="noopener">Open saved configurations</a>`;
        recordAction = 'Mark extraction setup complete';
      }
    }
    if (passed[key] === 'skipped') body += '<p class="text-700">Skipped. You can mark this setup ready if you complete it later.</p>';
    if (passed[key] === true && ready) body += '<div class="alert alert-success">Marked complete. Continue to the next step.</div>';
    if (checks.length) {
      body += ready
        ? '<p class="text-success">Saved configuration checks passed.</p>'
        : `<div class="alert alert-warning"><ul class="mb-0">${checks.filter(([configured]) => !configured).map(([, detail]) =>
            `<li>${detail}</li>`).join('')}</ul></div>`;
    }
    panel.innerHTML = `<h3 class="fs-8 mb-3" tabindex="-1">${heading}</h3>${body}`;
    if (key === 'connection') panel.append(find('database-links').content.cloneNode(true));
    if (integration && routingNeeded) {
      panel.append(root.querySelector(`[data-integration="${integration.group}"]`).content.cloneNode(true));
    }
    if (stage === 'prerequisites') {
      const keys = ['DOC_EXTRACTION', 'ROUTER', 'CONFIG_ASSISTANT', current === 'Accounts Payable' ? 'ACCOUNTS_PAYABLE' : 'ACCOUNTS_RECEIVABLE'];
      panel.querySelector('[data-current-settings]').append(...prerequisites.filter(row => keys.includes(row.dataset.module)).map(row => row.cloneNode(true)));
    }
    const canContinue = key === 'workflow'
      ? selectedModules().length > 0 || useEncoder === 'Yes'
      : ungated || passed[key] === 'skipped' || (ready && passed[key] === true);
    const controls = [];
    if (checks.length || key === 'review') controls.push(button('Recheck setup', 'recheck'));
    if (integration && routingNeeded && !passed[key]) controls.push(button('Skip for now', 'skip'));
    if (!ungated && (passed[key] !== true || !ready)) {
      controls.push(button(recordAction || 'Mark as done', 'pass', false, !ready));
    }
    if (key === 'review') {
      if (finished && !unfinished.length) {
        controls.push(`<a class="btn btn-primary" href="${root.dataset.workspaceUrl}">Open workspace</a>`);
      }
      controls.push(button('Start over', 'reset'));
      if (!finished || unfinished.length) controls.push(button('Finish setup', 'finish', true, unfinished.length > 0));
    } else {
      controls.push(button('Continue', 'next', true, !canContinue));
    }
    actions.innerHTML = `<div>${index ? button('Back', 'back') : ''}</div><div class="d-flex flex-wrap gap-2">${controls.join('')}</div>`;
    saveProgress();
    if (key === 'review' && finished && !unfinished.length) {
      const secure = window.location.protocol === 'https:' ? '; Secure' : '';
      // This cookie only influences the home redirect. It grants no access.
      document.cookie = `auditcounter_guided_setup_finished=1; Path=/; Max-Age=31536000; SameSite=Lax${secure}`;
    }
    if (focus) panel.querySelector('h3').focus();
    find('announcement').textContent = passed[key] === 'skipped' ? 'Skipped.' : passed[key] && ready ? 'Marked complete.' : '';
  }
  panel.addEventListener('click', event => {
    const target = event.target.closest('button[data-step-index]');
    if (!target) return;
    index = Number(target.dataset.stepIndex);
    render();
  });
  root.addEventListener('change', event => {
    finished = false;
    if (event.target.name === 'workflow') {
      const checked = [...panel.querySelectorAll('input[name=workflow]:checked')].map(input => input.value);
      const accounting = accountingModules.filter(name => checked.includes(name));
      module = accounting.length === 2 ? 'Both' : (accounting[0] || '');
      const wasUsingEncoder = useEncoder === 'Yes';
      useEncoder = checked.includes('MCP Encoder') ? 'Yes' : 'No';
      if (!wasUsingEncoder && useEncoder === 'Yes' && !passed.connection) database = 'Yes';
      delete passed.routing;
      const optionIndex = event.target.dataset.workflowIndex;
      render(false);
      panel.querySelector(`[data-workflow-index="${optionIndex}"]`).focus();
    }
    if (event.target.name === 'document') {
      const current = steps()[index].split('|')[0];
      delete passed.routing;
      selections[current] = [...panel.querySelectorAll('input[name=document]:checked')].map(input => input.value);
      Object.keys(passed).filter(k => k.startsWith(current + '|')).forEach(k => delete passed[k]);
      render(false);
    }
    if (event.target.name === 'database') {
      database = event.target.value;
      Object.keys(answers).filter(k => answers[k] === 'PostgreSQL').forEach(k => {
        delete answers[k];
        delete passed[k];
      });
      delete passed.connection;
      delete passed.routing;
      render(false);
    }
    if (event.target.name === 'issued-document') {
      issued[steps()[index]] = event.target.checked;
      delete passed.routing;
      saveProgress();
    }
    if (event.target.name === 'source') {
      const key = steps()[index];
      answers[key] = event.target.value;
      delete passed[key];
      delete passed.routing;
      render(false);
    }
  });
  actions.addEventListener('click', event => {
    const action = event.target.closest('button')?.dataset.action;
    if (action === 'next') {
      if (steps()[index] === 'routing' && !issuedRecords(steps()).length) passed.routing = 'skipped';
      index++;
    }
    else if (action === 'back') index--;
    else if (action === 'recheck') {
      window.location.reload();
      return;
    }
    else if (action === 'pass') {
      const flow = steps();
      const key = flow[index];
      if (!requirements(key, flow).every(([ready]) => ready)) return;
      passed[key] = true;
    }
    else if (action === 'finish') {
      const flow = steps();
      if (flow[index] !== 'review' || flow.some(key => needsAttention(key, flow))) return;
      finished = true;
    }
    else if (action === 'skip' && integrations[steps()[index]]) {
      passed[steps()[index]] = 'skipped';
      index++;
    }
    else if (action === 'reset') {
      index = 0;
      module = 'Accounts Payable';
      database = 'No';
      useEncoder = null;
      finished = false;
      for (const state of [passed, answers, selections, issued]) Object.keys(state).forEach(k => delete state[k]);
    }
    else return;
    render();
  });
  function saveProgress() {
    try {
      localStorage.setItem(storageKey, JSON.stringify({
        module, database, useEncoder, selections, answers, issued, passed, finished, step: steps()[index]
      }));
    } catch {
      find('storage-status').textContent = 'Browser storage is unavailable. Progress will last for this visit.';
    }
  }

  function restoreProgress() {
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey));
      if (!saved) return;
      finished = saved.finished === true;
      if ([...accountingModules, 'Both', ''].includes(saved.module)) module = saved.module;
      useEncoder = ['Yes', 'No'].includes(saved.useEncoder) ? saved.useEncoder : null;
      database = saved.database === 'Yes' ? 'Yes' : 'No';
      for (const name of selectedModules()) {
        const choices = saved.selections?.[name];
        if (Array.isArray(choices)) selections[name] = documents.filter(item => choices.includes(item));
      }
      const flow = steps();
      for (const key of flow) {
        if (routes[key] && sourceOptions().includes(saved.answers?.[key])) answers[key] = saved.answers[key];
        if (routes[key] && saved.issued?.[key] === true) issued[key] = true;
        if (saved.passed?.[key] === true) passed[key] = true;
        if (integrations[key] && saved.passed?.[key] === 'skipped') passed[key] = 'skipped';
      }
      if (!saved.issued) delete passed.routing;
      const nextIntegration = flow.find(key => integrations[key] && !passed[key]);
      let resumeStep = saved.step;
      if (typeof resumeStep === 'string' && resumeStep.endsWith('|matching')) {
        const completedModule = resumeStep.split('|')[0];
        const nextModule = selectedModules()[selectedModules().indexOf(completedModule) + 1];
        resumeStep = nextModule ? `${nextModule}|selection` : 'routing';
      }
      if (resumeStep === 'review' && nextIntegration) resumeStep = nextIntegration;
      index = Math.max(0, flow.indexOf(resumeStep));
    } catch {
      // A missing or unreadable draft starts a fresh wizard.
    }
  }

  restoreProgress();
  render(false);
  root.hidden = false;
})();
