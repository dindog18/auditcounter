(() => {
  const dialog = document.querySelector('#help-assistant');
  if (!dialog) return;
  const menu = document.querySelector('#workspace-help-menu');
  const form = dialog.querySelector('form');
  const question = form.querySelector('#help-question');
  const messages = dialog.querySelector('[role="log"]');
  const status = dialog.querySelector('[data-help-status]');
  const send = form.querySelector('[type="submit"]');
  const clear = form.querySelector('[data-help-clear]');
  let history = [];

  function showStatus(message) {
    status.textContent = message;
    status.hidden = !message;
  }

  function addMessage(label, text, sources = []) {
    const message = document.createElement('article');
    const author = document.createElement('strong');
    author.textContent = label;
    const body = document.createElement('p');
    body.textContent = text;
    message.append(author, body);
    if (sources.length) {
      const links = document.createElement('ul');
      links.className = 'mb-0 mt-2';
      for (const source of sources) {
        const item = document.createElement('li');
        const link = document.createElement('a');
        link.href = source.url;
        link.textContent = source.label;
        item.append(link);
        links.append(item);
      }
      message.append(links);
    }
    messages.append(message);
    messages.scrollTop = messages.scrollHeight;
  }

  document.querySelector('[data-help-ask]').addEventListener('click', () => {
    dialog.showModal();
    question.focus();
  });
  dialog.querySelector('[data-help-close]').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => menu.focus({preventScroll: true}));
  clear.addEventListener('click', () => {
    history = [];
    messages.replaceChildren();
    question.value = '';
    showStatus('');
    clear.disabled = true;
    question.focus();
  });

  form.addEventListener('submit', async event => {
    event.preventDefault();
    const text = question.value.trim();
    if (!text || send.disabled) return;
    send.disabled = true;
    clear.disabled = true;
    question.readOnly = true;
    showStatus('Looking up AuditCounter guidance…');
    try {
      const response = await fetch(form.action, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': form.elements.csrfmiddlewaretoken.value,
        },
        body: JSON.stringify({
          page: dialog.dataset.page, workspace: dialog.dataset.workspace,
          question: text, history,
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        showStatus(data.error || 'The assistant is unavailable. Try again.');
        return;
      }
      addMessage('You', text);
      addMessage('AuditCounter', data.answer, data.sources);
      history = [...history, {question: text, answer: data.answer}].slice(-3);
      question.value = '';
      showStatus('');
    } catch {
      showStatus('Couldn’t reach the assistant. Try again or use the guided tour.');
    } finally {
      send.disabled = false;
      clear.disabled = !history.length && !question.value;
      question.readOnly = false;
      if (dialog.open && document.activeElement === dialog) question.focus();
    }
  });
})();
