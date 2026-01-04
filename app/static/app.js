let currentConversationId = '';

const meEl = document.getElementById('me');
const conversationsEl = document.getElementById('conversations');
const statusEl = document.getElementById('status');
const statusTextEl = statusEl?.querySelector('.status-text');
const debugEl = document.getElementById('debug');

const emailTextEl = document.getElementById('emailText');
const summarizeBtn = document.getElementById('summarize');
const newConversationBtn = document.getElementById('newConversation');
const caseIdEl = document.getElementById('caseId');
const fetchFromPleasanterBtn = document.getElementById('fetchFromPleasanter');

const causeEl = document.getElementById('cause');
const solutionEl = document.getElementById('solution');
const detailsEl = document.getElementById('details');
const includeCauseEl = document.getElementById('includeCause');
const includeSolutionEl = document.getElementById('includeSolution');
const includeDetailsEl = document.getElementById('includeDetails');
const saveFormBtn = document.getElementById('saveForm');

const chatWidgetEl = document.getElementById('chatWidget');
const sidebarToggleEl = document.getElementById('sidebarToggle');
const sidebarBackdropEl = document.getElementById('sidebarBackdrop');
const tabMailBtn = document.getElementById('tabMail');
const tabSummaryBtn = document.getElementById('tabSummary');
const tabMailContent = document.getElementById('tabMailContent');
const tabSummaryContent = document.getElementById('tabSummaryContent');
const mailModeEl = document.getElementById('mailMode');
const pleasanterPanelEl = document.getElementById('pleasanterPanel');
const manualPanelEl = document.getElementById('manualPanel');
const caseSearchPanelEl = document.getElementById('caseSearchPanel');
const caseSearchEl = document.getElementById('caseSearch');
const caseResultsEl = document.getElementById('caseResults');
const caseCountEl = document.getElementById('caseCount');
const caseUrlEl = document.getElementById('caseUrl');
const caseUrlApplyEl = document.getElementById('caseUrlApply');
const caseInfoEl = document.getElementById('caseInfo');

function setStatus(msg, state = 'idle') {
  if (statusEl) statusEl.dataset.state = state;
  if (statusTextEl) {
    statusTextEl.textContent = msg || '';
  }
}

function clearChat() {
  if (chatWidgetEl) {
    chatWidgetEl.removeAttribute('api-endpoint');
  }
}

function setDebug(obj) {
  if (!debugEl) return;
  try {
    debugEl.textContent = obj ? JSON.stringify(obj, null, 2) : '';
  } catch {
    debugEl.textContent = String(obj ?? '');
  }
}

function setTab(name) {
  const isMail = name === 'mail';
  if (tabMailBtn) tabMailBtn.classList.toggle('active', isMail);
  if (tabSummaryBtn) tabSummaryBtn.classList.toggle('active', !isMail);
  if (tabMailContent) tabMailContent.classList.toggle('active', isMail);
  if (tabSummaryContent) tabSummaryContent.classList.toggle('active', !isMail);
}

function setMailMode(mode) {
  const isPleasanter = mode === 'pleasanter';
  if (caseSearchPanelEl) caseSearchPanelEl.style.display = isPleasanter ? 'block' : 'none';
  if (pleasanterPanelEl) pleasanterPanelEl.style.display = isPleasanter ? 'block' : 'none';
  if (manualPanelEl) manualPanelEl.style.display = isPleasanter ? 'none' : 'block';
}

function setBusy(isBusy) {
  summarizeBtn.disabled = isBusy;
  newConversationBtn.disabled = isBusy;
  fetchFromPleasanterBtn.disabled = isBusy;
  saveFormBtn.disabled = isBusy;
  if (caseUrlApplyEl) caseUrlApplyEl.disabled = isBusy;
}

async function api(path, options = {}) {
  const method = options.method || 'GET';
  const bodyText = typeof options.body === 'string' ? options.body : '';
  const started = Date.now();

  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options
  });
  const text = await res.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    data = { raw: text };
  }

  const meta = {
    at: new Date().toISOString(),
    ms: Date.now() - started,
    method,
    path,
    status: res.status,
    request_id: res.headers.get('x-request-id') || undefined,
    request_body_preview: bodyText ? bodyText.slice(0, 600) + (bodyText.length > 600 ? '…' : '') : undefined
  };

  // 開発者ツールでの切り分けをしやすくするため、
  // 1) オブジェクト形式（展開して見やすい）
  // 2) JSON文字列（そのままコピペしやすい）
  // の両方を出す。最後のレスポンスは window.__lastApi に保存する。
  const last = { meta, data };
  window.__lastApi = last;
  console.debug('[api]', meta, data);
  try {
    const json = JSON.stringify(last);
    console.log('[api-json]', json.length > 12000 ? json.slice(0, 12000) + '…' : json);
  } catch {
    // ignore
  }
  setDebug(last);

  if (!res.ok) {
    const detail = data?.error || data?.detail || JSON.stringify(data);
    const err = new Error(`${res.status} ${detail}`);
    err.meta = meta;
    err.data = data;
    throw err;
  }
  return data;
}

function renderConversations(items) {
  conversationsEl.innerHTML = '';
  for (const it of items) {
    const div = document.createElement('div');
    div.className = 'item' + (it.dify_conversation_id === currentConversationId ? ' active' : '');
    div.textContent = it.title ? `${it.title}` : it.dify_conversation_id;
    div.addEventListener('click', async () => {
      currentConversationId = it.dify_conversation_id;
      await loadForm();
      await refreshConversations();
      updateChatEndpoint();
    });
    conversationsEl.appendChild(div);
  }
}

async function refreshConversations() {
  const items = await api('/api/conversations');
  renderConversations(items);
}

async function loadMe() {
  const me = await api('/api/me');
  meEl.textContent = `ログイン中: ${me.username}`;
}

async function loadForm() {
  if (!currentConversationId) return;
  const f = await api(`/api/form?conversation_id=${encodeURIComponent(currentConversationId)}`, { method: 'GET' });
  causeEl.value = f.cause || '';
  solutionEl.value = f.solution || '';
  detailsEl.value = f.details || '';
  includeCauseEl.checked = !!f.include_cause;
  includeSolutionEl.checked = !!f.include_solution;
  includeDetailsEl.checked = !!f.include_details;
}

function clearForm() {
  causeEl.value = '';
  solutionEl.value = '';
  detailsEl.value = '';
  includeCauseEl.checked = true;
  includeSolutionEl.checked = true;
  includeDetailsEl.checked = true;
}

function updateChatEndpoint() {
  if (!chatWidgetEl) return;
  if (!currentConversationId) {
    chatWidgetEl.removeAttribute('api-endpoint');
    return;
  }
  chatWidgetEl.setAttribute('api-endpoint', `/api/chat-ui?conversation_id=${encodeURIComponent(currentConversationId)}`);
}

function setCaseInfo(item) {
  if (!caseInfoEl) return;
  if (!item) {
    caseInfoEl.textContent = '';
    return;
  }
  const title = item.title ? ` ${item.title}` : '';
  caseInfoEl.textContent = `選択中: ${item.result_id}${title}`;
}

function renderCaseList(items) {
  if (!caseResultsEl) return;
  caseResultsEl.innerHTML = '';
  for (const it of items) {
    const div = document.createElement('div');
    div.className = 'item';
    div.textContent = `${it.result_id ?? ''} ${it.title ?? ''}`.trim();
    div.addEventListener('click', () => {
      caseIdEl.value = it.result_id ?? '';
      setCaseInfo(it);
    });
    caseResultsEl.appendChild(div);
  }
  if (caseCountEl) caseCountEl.textContent = `件数: ${items.length}`;
}

async function loadCases(query = '') {
  const q = String(query || '').trim();
  const data = await api(`/api/pleasanter/cases?query=${encodeURIComponent(q)}&limit=50`);
  renderCaseList(data.items || []);
}

function extractCaseIdFromUrl(text) {
  if (!text) return '';
  const m = String(text).match(/\/items\/(\d+)/);
  return m ? m[1] : '';
}

async function validateCaseId(caseId) {
  return api(`/api/pleasanter/case_lookup?case_result_id=${encodeURIComponent(caseId)}`);
}

async function saveForm() {
  if (!currentConversationId) throw new Error('会話を選択してください');
  await api('/api/form/update', {
    method: 'POST',
    body: JSON.stringify({
      conversation_id: currentConversationId,
      cause: causeEl.value,
      solution: solutionEl.value,
      details: detailsEl.value,
      include_cause: includeCauseEl.checked,
      include_solution: includeSolutionEl.checked,
      include_details: includeDetailsEl.checked
    })
  });
}

async function createConversation() {
  // Difyに通知せず、クライアント側の情報だけを初期化する
  currentConversationId = '';
  clearForm();
  clearChat();
  await refreshConversations();
  setStatus('新規会話を開始しました', 'success');
}

async function summarizeEmail() {
  const email_text = String(emailTextEl.value || '').trim();
  if (!email_text) return;
  setTab('summary');
  const data = await api('/api/summarize_email', {
    method: 'POST',
    body: JSON.stringify({ email_text, conversation_id: currentConversationId || '' })
  });
  currentConversationId = data.conversation_id;
  if (data.parsed) {
    causeEl.value = data.parsed.cause || '';
    solutionEl.value = data.parsed.solution || '';
    detailsEl.value = data.parsed.details || '';
  }
  await refreshConversations();
  await loadForm();
  updateChatEndpoint();
  setStatus(`要約しました: ${currentConversationId}`);
}

async function summarizeFromPleasanter(caseIdOverride = '') {
  const case_result_id = String(caseIdOverride || caseIdEl.value || '').trim();
  if (!case_result_id) throw new Error('案件IDを入力してください');
  caseIdEl.value = case_result_id;
  setTab('summary');
  const data = await api('/api/pleasanter/summarize_case', {
    method: 'POST',
    body: JSON.stringify({ case_result_id })
  });
  currentConversationId = data.conversation_id;
  if (data.parsed) {
    causeEl.value = data.parsed.cause || '';
    solutionEl.value = data.parsed.solution || '';
    detailsEl.value = data.parsed.details || '';
  }
  await refreshConversations();
  await loadForm();
  updateChatEndpoint();
  setStatus(`Pleasanterから要約しました: 案件 ${data.case_result_id} / ${currentConversationId}`);
}

newConversationBtn.addEventListener('click', async () => {
  setBusy(true);
  setStatus('新規会話作成中…', 'loading');
  try {
    await createConversation();
  } catch (e) {
    setStatus(`エラー: ${e.message}`, 'error');
  } finally {
    setBusy(false);
  }
});

summarizeBtn.addEventListener('click', async () => {
  setBusy(true);
  setStatus('要約中…', 'loading');
  try {
    await summarizeEmail();
  } catch (e) {
    setStatus(`エラー: ${e.message}`, 'error');
  } finally {
    setBusy(false);
  }
});

saveFormBtn.addEventListener('click', async () => {
  setBusy(true);
  setStatus('保存中…', 'loading');
  try {
    await saveForm();
    setStatus('保存しました', 'success');
  } catch (e) {
    setStatus(`エラー: ${e.message}`, 'error');
  } finally {
    setBusy(false);
  }
});

fetchFromPleasanterBtn.addEventListener('click', async () => {
  setBusy(true);
  setStatus('Pleasanter取得中…', 'loading');
  try {
    await summarizeFromPleasanter();
  } catch (e) {
    setStatus(`エラー: ${e.message}`, 'error');
  } finally {
    setBusy(false);
  }
});

(async function init() {
  try {
    await loadMe();
    await refreshConversations();
    setStatus('準備OK', 'success');
    setTab('mail');
    setMailMode('pleasanter');
    try {
      await loadCases();
    } catch (err) {
      setStatus(`案件一覧の取得に失敗しました: ${err.message}`, 'error');
    }
  } catch (e) {
    setStatus(`初期化エラー: ${e.message}`, 'error');
  }
})();

if (sidebarToggleEl) {
  sidebarToggleEl.addEventListener('click', () => {
    document.body.classList.toggle('sidebar-collapsed');
  });
}

if (sidebarBackdropEl) {
  sidebarBackdropEl.addEventListener('click', () => {
    document.body.classList.add('sidebar-collapsed');
  });
}

if (tabMailBtn && tabSummaryBtn) {
  tabMailBtn.addEventListener('click', () => setTab('mail'));
  tabSummaryBtn.addEventListener('click', () => setTab('summary'));
}

if (mailModeEl) {
  mailModeEl.addEventListener('change', (e) => {
    setMailMode(e.target.value);
  });
}

if (caseSearchEl) {
  let timer = null;
  caseSearchEl.addEventListener('input', (e) => {
    const value = e.target.value;
    if (timer) clearTimeout(timer);
    timer = setTimeout(async () => {
      try {
        await loadCases(value);
      } catch (err) {
        setStatus(`案件検索エラー: ${err.message}`, 'error');
      }
    }, 300);
  });
}

if (caseUrlApplyEl) {
  caseUrlApplyEl.addEventListener('click', async () => {
    const raw = String(caseUrlEl?.value || '').trim();
    const caseId = extractCaseIdFromUrl(raw);
    if (!caseId) {
      setStatus('案件URLからIDを抽出できませんでした', 'error');
      return;
    }
    setBusy(true);
    setStatus('案件URLを確認中…', 'loading');
    try {
      const item = await validateCaseId(caseId);
      setCaseInfo(item);
      await summarizeFromPleasanter(String(item.result_id || caseId));
    } catch (e) {
      setStatus(`案件URLエラー: ${e.message}`, 'error');
    } finally {
      setBusy(false);
    }
  });
}

if (chatWidgetEl) {
  chatWidgetEl.addEventListener('message-received', async () => {
    try {
      await refreshConversations();
    } catch {
      // ignore
    }
  });
}
