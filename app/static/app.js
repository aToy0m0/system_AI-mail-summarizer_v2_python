let currentConversationId = '';

const meEl = document.getElementById('me');
const adminLinkFormEl = document.getElementById('adminLinkForm');
const conversationsEl = document.getElementById('conversations');

const statusEl = document.getElementById('status');
const statusTextEl = statusEl?.querySelector('.status-text');

const sidebarToggleEl = document.getElementById('sidebarToggle');
const sidebarBackdropEl = document.getElementById('sidebarBackdrop');

const tabMailBtn = document.getElementById('tabMail');
const tabSummaryBtn = document.getElementById('tabSummary');
const tabMailContent = document.getElementById('tabMailContent');
const tabSummaryContent = document.getElementById('tabSummaryContent');

const mailModeEl = document.getElementById('mailMode');
const caseSearchPanelEl = document.getElementById('caseSearchPanel');
const pleasanterPanelEl = document.getElementById('pleasanterPanel');
const manualPanelEl = document.getElementById('manualPanel');

const caseSearchEl = document.getElementById('caseSearch');
const caseResultsEl = document.getElementById('caseResults');
const caseCountEl = document.getElementById('caseCount');
const caseUrlEl = document.getElementById('caseUrl');
const caseUrlApplyEl = document.getElementById('caseUrlApply');
const caseInfoEl = document.getElementById('caseInfo');

const caseIdEl = document.getElementById('caseId');
const fetchFromPleasanterBtn = document.getElementById('fetchFromPleasanter');

const emailTextEl = document.getElementById('emailText');
const summarizeBtn = document.getElementById('summarize');

const newConversationBtn = document.getElementById('newConversation');

const summaryEl = document.getElementById('summary');
const causeEl = document.getElementById('cause');
const actionEl = document.getElementById('action');
const bodyEl = document.getElementById('body');

const includeSummaryEl = document.getElementById('includeSummary');
const includeCauseEl = document.getElementById('includeCause');
const includeActionEl = document.getElementById('includeAction');
const includeBodyEl = document.getElementById('includeBody');

const saveFormBtn = document.getElementById('saveForm');
const saveToCaseBtn = document.getElementById('saveToCase');

const clearChatBtn = document.getElementById('clearChat');
const chatContainerEl = document.getElementById('chatContainer');
const chatMessagesEl = document.getElementById('chatMessages');
const chatInputEl = document.getElementById('chatInput');
const chatSendBtn = document.getElementById('chatSend');

function setStatus(msg, state = 'idle') {
  if (statusEl) statusEl.dataset.state = state;
  if (statusTextEl) statusTextEl.textContent = msg || '';
}

function setBusy(isBusy) {
  if (newConversationBtn) newConversationBtn.disabled = isBusy;
  if (fetchFromPleasanterBtn) fetchFromPleasanterBtn.disabled = isBusy;
  if (summarizeBtn) summarizeBtn.disabled = isBusy;
  if (saveFormBtn) saveFormBtn.disabled = isBusy;
  if (saveToCaseBtn) saveToCaseBtn.disabled = isBusy;
  if (caseUrlApplyEl) caseUrlApplyEl.disabled = isBusy;
  if (isBusy) {
    if (chatSendBtn) chatSendBtn.disabled = true;
    if (chatInputEl) chatInputEl.disabled = true;
    return;
  }
  if (!currentConversationId) {
    if (chatSendBtn) chatSendBtn.disabled = true;
    if (chatInputEl) chatInputEl.disabled = true;
    return;
  }
  if (chatInputEl) chatInputEl.disabled = false;
  updateChatSendButton();
}

async function api(path, options = {}) {
  const method = options.method || 'GET';
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
    request_id: res.headers.get('x-request-id') || undefined
  };
  console.debug('[api]', meta, data);

  if (!res.ok) {
    const detail = data?.error || data?.detail || JSON.stringify(data);
    const err = new Error(`${res.status} ${typeof detail === 'string' ? detail : JSON.stringify(detail)}`);
    err.meta = meta;
    err.data = data;
    throw err;
  }
  return data;
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

function clearForm() {
  if (summaryEl) summaryEl.value = '';
  if (causeEl) causeEl.value = '';
  if (actionEl) actionEl.value = '';
  if (bodyEl) bodyEl.value = '';
  if (includeSummaryEl) includeSummaryEl.checked = true;
  if (includeCauseEl) includeCauseEl.checked = true;
  if (includeActionEl) includeActionEl.checked = true;
  if (includeBodyEl) includeBodyEl.checked = true;
}

function clearChatInput() {
  if (chatInputEl) chatInputEl.value = '';
}

function formatTime(timestamp) {
  if (!timestamp) return '';
  const d = typeof timestamp === 'number' ? new Date(timestamp * 1000) : new Date(timestamp);
  return d.toLocaleString('ja-JP');
}

function scrollChatToBottom() {
  if (!chatMessagesEl) return;
  chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
}

function clearChat() {
  if (!chatMessagesEl) return;
  chatMessagesEl.innerHTML = `
    <div class="chat-empty">
      <span class="material-icons">chat_bubble_outline</span>
      <p>AIと会話を開始します</p>
    </div>
  `;
  if (chatInputEl) chatInputEl.disabled = true;
  if (chatSendBtn) chatSendBtn.disabled = true;
}

function addChatMessage(role, content, timestamp) {
  if (!chatMessagesEl) return;

  const emptyEl = chatMessagesEl.querySelector('.chat-empty');
  if (emptyEl) emptyEl.remove();

  const messageDiv = document.createElement('div');
  messageDiv.className = `chat-message ${role}`;

  const avatarDiv = document.createElement('div');
  avatarDiv.className = 'chat-avatar';
  avatarDiv.textContent = role === 'user' ? 'U' : 'AI';

  const contentDiv = document.createElement('div');
  contentDiv.className = 'chat-message-content';

  const metaDiv = document.createElement('div');
  metaDiv.className = 'chat-message-meta';
  metaDiv.textContent = formatTime(timestamp);

  const bubbleDiv = document.createElement('div');
  bubbleDiv.className = 'chat-message-bubble';
  bubbleDiv.textContent = content;

  contentDiv.appendChild(metaDiv);
  contentDiv.appendChild(bubbleDiv);
  messageDiv.appendChild(avatarDiv);
  messageDiv.appendChild(contentDiv);
  chatMessagesEl.appendChild(messageDiv);

  scrollChatToBottom();
}

function addTypingIndicator() {
  if (!chatMessagesEl) return;

  const emptyEl = chatMessagesEl.querySelector('.chat-empty');
  if (emptyEl) emptyEl.remove();

  const messageDiv = document.createElement('div');
  messageDiv.className = 'chat-message assistant typing';
  messageDiv.id = 'typing-indicator';

  const avatarDiv = document.createElement('div');
  avatarDiv.className = 'chat-avatar';
  avatarDiv.textContent = 'AI';

  const contentDiv = document.createElement('div');
  contentDiv.className = 'chat-message-content';

  const bubbleDiv = document.createElement('div');
  bubbleDiv.className = 'chat-message-bubble';
  bubbleDiv.innerHTML = `
    <div class="typing-indicator">
      <div class="typing-dot"></div>
      <div class="typing-dot"></div>
      <div class="typing-dot"></div>
    </div>
  `;

  contentDiv.appendChild(bubbleDiv);
  messageDiv.appendChild(avatarDiv);
  messageDiv.appendChild(contentDiv);
  chatMessagesEl.appendChild(messageDiv);

  scrollChatToBottom();
}

function removeTypingIndicator() {
  const el = document.getElementById('typing-indicator');
  if (el) el.remove();
}

async function loadChatMessages() {
  if (!currentConversationId || !chatMessagesEl) {
    clearChat();
    return;
  }

  try {
    const data = await api(`/api/chat-ui?conversation_id=${encodeURIComponent(currentConversationId)}`);
    chatMessagesEl.innerHTML = '';

    const msgs = Array.isArray(data?.messages) ? data.messages : [];
    if (msgs.length === 0) {
      chatMessagesEl.innerHTML = `
        <div class="chat-empty">
          <span class="material-icons">chat_bubble_outline</span>
          <p>AIと会話を開始します</p>
        </div>
      `;
    } else {
      for (const msg of msgs) {
        addChatMessage(msg.role, msg.content, msg.created_at);
      }
    }

    if (chatInputEl) chatInputEl.disabled = false;
    updateChatSendButton();
  } catch (e) {
    clearChat();
  }
}

function updateChatSendButton() {
  if (chatSendBtn && chatInputEl) {
    chatSendBtn.disabled = !currentConversationId || chatInputEl.value.trim() === '' || chatInputEl.disabled;
  }
}

function extractCaseIdFromUrl(text) {
  if (!text) return '';
  const m = String(text).match(/\/items\/(\d+)/);
  return m ? m[1] : '';
}

async function loadMe() {
  const me = await api('/api/me');
  if (meEl) meEl.textContent = me?.is_admin ? `ログイン中: ${me.username} (管理者)` : `ログイン中: ${me.username}`;
  if (adminLinkFormEl) adminLinkFormEl.hidden = !me?.is_admin;
}

function renderConversations(items) {
  if (!conversationsEl) return;
  conversationsEl.innerHTML = '';
  for (const it of items) {
    const div = document.createElement('div');
    div.className = 'item' + (it.dify_conversation_id === currentConversationId ? ' active' : '');
    div.textContent = it.title ? `${it.title}` : it.dify_conversation_id;
    div.addEventListener('click', async () => {
      currentConversationId = it.dify_conversation_id;
      await loadForm();
      await refreshConversations();
      await loadChatMessages();
      setTab('summary');
      document.body.classList.add('sidebar-collapsed');
    });
    conversationsEl.appendChild(div);
  }
}

async function refreshConversations() {
  const items = await api('/api/conversations');
  renderConversations(items);
}

async function loadForm() {
  if (!currentConversationId) return;
  const f = await api(`/api/form?conversation_id=${encodeURIComponent(currentConversationId)}`);
  if (summaryEl) summaryEl.value = f.summary || '';
  if (causeEl) causeEl.value = f.cause || '';
  if (actionEl) actionEl.value = f.action || '';
  if (bodyEl) bodyEl.value = f.body || '';
  if (includeSummaryEl) includeSummaryEl.checked = !!f.include_summary;
  if (includeCauseEl) includeCauseEl.checked = !!f.include_cause;
  if (includeActionEl) includeActionEl.checked = !!f.include_action;
  if (includeBodyEl) includeBodyEl.checked = !!f.include_body;
}

async function saveForm() {
  if (!currentConversationId) throw new Error('会話を選択してください');
  await api('/api/form/update', {
    method: 'POST',
    body: JSON.stringify({
      conversation_id: currentConversationId,
      summary: summaryEl?.value || '',
      cause: causeEl?.value || '',
      action: actionEl?.value || '',
      body: bodyEl?.value || '',
      include_summary: includeSummaryEl?.checked ?? true,
      include_cause: includeCauseEl?.checked ?? true,
      include_action: includeActionEl?.checked ?? true,
      include_body: includeBodyEl?.checked ?? true
    })
  });
}

async function saveToCase() {
  if (!currentConversationId) throw new Error('会話を選択してください');
  await saveForm();
  await api('/api/pleasanter/save_summary', {
    method: 'POST',
    body: JSON.stringify({ conversation_id: currentConversationId })
  });
}

async function createConversation() {
  currentConversationId = '';
  clearForm();
  clearChatInput();
  clearChat();
  await refreshConversations();
  setStatus('新規会話を開始しました', 'success');
}

async function summarizeEmail() {
  const email_text = String(emailTextEl?.value || '').trim();
  if (!email_text) throw new Error('メール本文を入力してください');
  const data = await api('/api/summarize_email', {
    method: 'POST',
    body: JSON.stringify({ email_text, conversation_id: currentConversationId || '' })
  });
  currentConversationId = data.conversation_id;
  await refreshConversations();
  await loadForm();
  await loadChatMessages();
  setTab('summary');
  setStatus('要約しました', 'success');
}

async function summarizeFromPleasanter(caseIdOverride = '') {
  const summary_result_id = String(caseIdOverride || caseIdEl?.value || '').trim();
  if (!summary_result_id) throw new Error('案件サマリIDを入力してください');
  if (caseIdEl) caseIdEl.value = summary_result_id;
  const data = await api('/api/pleasanter/summarize_case', {
    method: 'POST',
    body: JSON.stringify({ summary_result_id, conversation_id: currentConversationId || '' })
  });
  currentConversationId = data.conversation_id;
  await refreshConversations();
  await loadForm();
  await loadChatMessages();
  setTab('summary');
  const sid = data.summary_result_id ?? data.case_result_id ?? summary_result_id;
  const cases = Array.isArray(data.target_case_result_ids) ? data.target_case_result_ids.join(',') : '';
  setStatus(`Pleasanterから要約しました: 案件サマリ ${sid}${cases ? `（案件: ${cases}）` : ''}`, 'success');
}

async function sendChatMessage() {
  if (!currentConversationId || !chatInputEl) return;
  const text = chatInputEl.value.trim();
  if (!text) return;

  addChatMessage('user', text, Date.now() / 1000);
  chatInputEl.value = '';
  chatInputEl.disabled = true;
  if (chatSendBtn) chatSendBtn.disabled = true;

  addTypingIndicator();
  try {
    const payload = { conversation_id: currentConversationId, user_comment: text };

    // 4項目フォーム: 修正対象チェックがONのものだけ送る（サンプルに合わせる）
    if (includeSummaryEl?.checked) payload.summary = summaryEl?.value || '';
    if (includeCauseEl?.checked) payload.cause = causeEl?.value || '';
    if (includeActionEl?.checked) payload.action = actionEl?.value || '';
    if (includeBodyEl?.checked) payload.body = bodyEl?.value || '';

    const data = await api('/api/chat-ui', { method: 'POST', body: JSON.stringify(payload) });

    removeTypingIndicator();
    const response = data?.message || data?.answer || '';
    if (response) addChatMessage('assistant', response, Date.now() / 1000);

    await loadForm();
    await refreshConversations();
  } catch (e) {
    removeTypingIndicator();
    addChatMessage('assistant', `エラー: ${e.message}`, Date.now() / 1000);
  } finally {
    if (chatInputEl) chatInputEl.disabled = false;
    if (chatInputEl) chatInputEl.focus();
    updateChatSendButton();
  }
}

function renderCaseList(items) {
  if (!caseResultsEl) return;
  caseResultsEl.innerHTML = '';
  for (const it of items) {
    const div = document.createElement('div');
    div.className = 'item';
    div.textContent = `${it.result_id ?? ''} ${it.title ?? ''}`.trim();
    div.addEventListener('click', () => {
      if (caseIdEl) caseIdEl.value = it.result_id ?? '';
      if (caseInfoEl) caseInfoEl.textContent = `選択中(案件サマリ): ${it.result_id ?? ''} ${it.title ?? ''}`.trim();
    });
    caseResultsEl.appendChild(div);
  }
  if (caseCountEl) caseCountEl.textContent = `件数: ${items.length}`;
}

async function loadCases(query = '') {
  const q = String(query || '').trim();
  const data = await api(`/api/pleasanter/cases?query=${encodeURIComponent(q)}&limit=50`);
  renderCaseList(Array.isArray(data.items) ? data.items : []);
}

async function validateCaseId(caseId) {
  return api(`/api/pleasanter/case_lookup?case_result_id=${encodeURIComponent(caseId)}`);
}

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
  mailModeEl.addEventListener('change', (e) => setMailMode(e.target.value));
}

if (newConversationBtn) {
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
}

if (summarizeBtn) {
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
}

if (fetchFromPleasanterBtn) {
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
}

if (saveFormBtn) {
  saveFormBtn.addEventListener('click', async () => {
    setBusy(true);
    setStatus('保存中…', 'loading');
    try {
      await saveForm();
      setStatus('フォームを保存しました', 'success');
    } catch (e) {
      setStatus(`エラー: ${e.message}`, 'error');
    } finally {
      setBusy(false);
    }
  });
}

if (saveToCaseBtn) {
  saveToCaseBtn.addEventListener('click', async () => {
    setBusy(true);
    setStatus('案件サマリへ反映中…', 'loading');
    try {
      await saveToCase();
      setStatus('案件サマリへ反映しました', 'success');
    } catch (e) {
      setStatus(`エラー: ${e.message}`, 'error');
    } finally {
      setBusy(false);
    }
  });
}

if (chatSendBtn) {
  chatSendBtn.addEventListener('click', async () => {
    if (!currentConversationId) {
      setStatus('会話を選択してください', 'error');
      return;
    }
    setBusy(true);
    setStatus('送信中…', 'loading');
    try {
      await sendChatMessage();
      setStatus('AIへ追加指示を送信しました', 'success');
    } catch (e) {
      setStatus(`エラー: ${e.message}`, 'error');
    } finally {
      setBusy(false);
    }
  });
}

if (chatInputEl) {
  chatInputEl.addEventListener('keydown', async (e) => {
    if (e.key !== 'Enter') return;
    if (e.shiftKey) return; // 改行
    e.preventDefault();
    if (!currentConversationId) return;
    setBusy(true);
    setStatus('送信中…', 'loading');
    try {
      await sendChatMessage();
      setStatus('AIへ追加指示を送信しました', 'success');
    } catch (err) {
      setStatus(`エラー: ${err.message}`, 'error');
    } finally {
      setBusy(false);
    }
  });
}

if (chatInputEl) {
  chatInputEl.addEventListener('input', () => updateChatSendButton());
}

if (clearChatBtn) {
  clearChatBtn.addEventListener('click', () => {
    clearChat();
    clearChatInput();
    if (chatInputEl) chatInputEl.focus();
    setStatus('表示をクリアしました', 'success');
  });
}

if (caseSearchEl) {
  let timer = null;
  caseSearchEl.addEventListener('input', (e) => {
    const value = e.target.value;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => loadCases(value).catch(() => {}), 250);
  });
}

if (caseUrlApplyEl) {
  caseUrlApplyEl.addEventListener('click', async () => {
    const raw = String(caseUrlEl?.value || '').trim();
    const caseId = extractCaseIdFromUrl(raw);
    if (!caseId) {
      setStatus('案件サマリURLからIDを抽出できませんでした', 'error');
      return;
    }
    setBusy(true);
    setStatus('案件サマリURL確認中…', 'loading');
    try {
      const item = await validateCaseId(caseId);
      if (caseIdEl) caseIdEl.value = item.result_id ?? caseId;
      if (caseInfoEl) caseInfoEl.textContent = `選択中(案件サマリ): ${item.result_id ?? caseId} ${item.title ?? ''}`.trim();
      await summarizeFromPleasanter(String(item.result_id || caseId));
    } catch (e) {
      setStatus(`案件サマリURLエラー: ${e.message}`, 'error');
    } finally {
      setBusy(false);
    }
  });
}

(async function init() {
  try {
    setStatus('初期化中…', 'loading');
    await loadMe();
    await refreshConversations();
    setTab('mail');
    setMailMode('pleasanter');
    await loadCases();
    clearChat();
    setBusy(false);
    setStatus('準備OK', 'success');
  } catch (e) {
    setStatus(`初期化エラー: ${e.message}`, 'error');
  }
})();


