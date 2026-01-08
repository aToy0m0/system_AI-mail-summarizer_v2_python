// ========== ログユーティリティ ==========
const LOG_LEVELS = {
  debug: 0,
  info: 1,
  warn: 2,
  error: 3,
  none: 999
};

const currentLogLevel = LOG_LEVELS[window.__LOG_LEVEL__ || 'info'] ?? LOG_LEVELS.info;

function createLogger(module) {
  const log = (level, levelName, ...args) => {
    if (LOG_LEVELS[level] < currentLogLevel) return;

    const timestamp = new Date().toISOString().substring(11, 23); // HH:mm:ss.SSS
    const prefix = `[${timestamp}] [${module}] [${levelName.toUpperCase()}]`;

    const consoleMethod = level === 'error' ? console.error :
                         level === 'warn' ? console.warn :
                         level === 'debug' ? console.debug :
                         console.log;

    consoleMethod(prefix, ...args);
  };

  return {
    debug: (...args) => log('debug', 'debug', ...args),
    info: (...args) => log('info', 'info', ...args),
    warn: (...args) => log('warn', 'warn', ...args),
    error: (...args) => log('error', 'error', ...args),
  };
}

// モジュールごとのロガー
const loggers = {
  app: createLogger('app'),
  api: createLogger('api'),
  chat: createLogger('chat'),
  form: createLogger('form'),
  pleasanter: createLogger('pleasanter'),
  ui: createLogger('ui'),
};

// ========== アプリケーションコード ==========
let currentConversationId = '';

const meEl = document.getElementById('me');
const conversationsEl = document.getElementById('conversations');
const statusEl = document.getElementById('status');
const statusTextEl = statusEl?.querySelector('.status-text');
const statusDetailEl = document.getElementById('statusDetail');
const progressBarEl = document.getElementById('progressBar');
const progressFillEl = document.getElementById('progressFill');
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

const chatMessagesEl = document.getElementById('chatMessages');
const chatInputEl = document.getElementById('chatInput');
const chatSendBtn = document.getElementById('chatSend');
const clearChatBtn = document.getElementById('clearChat');
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

function setStatus(msg, state = 'idle', detail = '', progress = null) {
  if (statusEl) statusEl.dataset.state = state;
  if (statusTextEl) {
    statusTextEl.textContent = msg || '';
  }
  if (statusDetailEl) {
    statusDetailEl.textContent = detail || '';
  }

  // プログレスバーの表示・非表示
  if (progressBarEl && progressFillEl) {
    if (progress !== null && progress >= 0) {
      progressBarEl.style.display = 'block';
      progressFillEl.style.width = `${Math.min(100, Math.max(0, progress))}%`;
    } else {
      progressBarEl.style.display = 'none';
      progressFillEl.style.width = '0%';
    }
  }
}

// ステータスのヘルパー関数
const Status = {
  idle: (msg = '準備完了', detail = '') => setStatus(msg, 'idle', detail),
  loading: (msg, detail = '', progress = null) => setStatus(msg, 'loading', detail, progress),
  success: (msg, detail = '') => setStatus(msg, 'success', detail),
  error: (msg, detail = '') => setStatus(msg, 'error', detail),
  warning: (msg, detail = '') => setStatus(msg, 'warning', detail),
  info: (msg, detail = '') => setStatus(msg, 'info', detail),
};

// チャット機能
function clearChat() {
  if (chatMessagesEl) {
    chatMessagesEl.innerHTML = `
      <div class="chat-empty">
        <span class="material-icons">chat_bubble_outline</span>
        <p>AIと会話を開始します</p>
      </div>
    `;
  }
  if (chatInputEl) {
    chatInputEl.value = '';
    chatInputEl.disabled = true;
  }
  if (chatSendBtn) {
    chatSendBtn.disabled = true;
  }
}

function scrollChatToBottom() {
  if (chatMessagesEl) {
    chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
  }
}

function formatTime(timestamp) {
  if (!timestamp) return '';
  const date = new Date(timestamp * 1000);
  const now = new Date();
  const isToday = date.toDateString() === now.toDateString();

  if (isToday) {
    return date.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' });
  }
  return date.toLocaleDateString('ja-JP', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function addChatMessage(role, content, timestamp) {
  if (!chatMessagesEl) return;

  // 空のメッセージ表示を削除
  const emptyEl = chatMessagesEl.querySelector('.chat-empty');
  if (emptyEl) {
    emptyEl.remove();
  }

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
  if (emptyEl) {
    emptyEl.remove();
  }

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
  const indicator = document.getElementById('typing-indicator');
  if (indicator) {
    indicator.remove();
  }
}

async function loadChatMessages() {
  if (!currentConversationId || !chatMessagesEl) {
    clearChat();
    return;
  }

  try {
    const data = await api(`/api/chat-ui?conversation_id=${encodeURIComponent(currentConversationId)}`);

    chatMessagesEl.innerHTML = '';

    if (!data.messages || data.messages.length === 0) {
      chatMessagesEl.innerHTML = `
        <div class="chat-empty">
          <span class="material-icons">chat_bubble_outline</span>
          <p>AIと会話を開始します</p>
        </div>
      `;
    } else {
      for (const msg of data.messages) {
        addChatMessage(msg.role, msg.content, msg.created_at);
      }
    }

    if (chatInputEl) chatInputEl.disabled = false;
    if (chatSendBtn) chatSendBtn.disabled = chatInputEl.value.trim() === '';
  } catch (e) {
    loggers.chat.error('Failed to load chat messages:', e);
    clearChat();
  }
}

async function sendChatMessage() {
  if (!currentConversationId || !chatInputEl) return;

  const text = chatInputEl.value.trim();
  if (!text) return;

  // ユーザーメッセージを表示
  addChatMessage('user', text, Date.now() / 1000);
  chatInputEl.value = '';
  chatInputEl.disabled = true;
  chatSendBtn.disabled = true;

  // タイピングインジケーターを表示
  addTypingIndicator();

  try {
    const data = await api('/api/chat-ui', {
      method: 'POST',
      body: JSON.stringify({
        conversation_id: currentConversationId,
        message: text
      })
    });

    removeTypingIndicator();

    const response = data.message || data.answer || '';
    if (response) {
      addChatMessage('assistant', response, Date.now() / 1000);
    }

    // フォームを再読み込み（AIが更新した可能性があるため）
    await loadForm();
    await refreshConversations();
  } catch (e) {
    removeTypingIndicator();
    addChatMessage('assistant', `エラー: ${e.message}`, Date.now() / 1000);
  } finally {
    chatInputEl.disabled = false;
    chatInputEl.focus();
    updateChatSendButton();
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

  const last = { meta, data };
  window.__lastApi = last;

  loggers.api.debug(`${method} ${path} ${res.status} (${meta.ms}ms)`, meta, data);

  try {
    const json = JSON.stringify(last);
    loggers.api.debug(`Response JSON:`, json.length > 12000 ? json.slice(0, 12000) + '…' : json);
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

async function updateChatEndpoint() {
  await loadChatMessages();
}

function updateChatSendButton() {
  if (chatSendBtn && chatInputEl) {
    chatSendBtn.disabled = !currentConversationId || chatInputEl.value.trim() === '';
  }
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
  Status.success('新規会話を開始しました');
}

async function summarizeEmail() {
  const email_text = String(emailTextEl.value || '').trim();
  if (!email_text) return;
  setTab('summary');
  Status.loading('AI要約中...', 'メール本文を解析しています', 30);
  const data = await api('/api/summarize_email', {
    method: 'POST',
    body: JSON.stringify({ email_text, conversation_id: currentConversationId || '' })
  });
  Status.loading('AI要約中...', 'フォームに反映しています', 80);
  currentConversationId = data.conversation_id;
  if (data.parsed) {
    causeEl.value = data.parsed.cause || '';
    solutionEl.value = data.parsed.solution || '';
    detailsEl.value = data.parsed.details || '';
  }
  await refreshConversations();
  await loadForm();
  updateChatEndpoint();
  Status.success('要約完了', `会話ID: ${currentConversationId.substring(0, 8)}...`);
}

async function summarizeFromPleasanter(caseIdOverride = '') {
  const case_result_id = String(caseIdOverride || caseIdEl.value || '').trim();
  if (!case_result_id) throw new Error('案件IDを入力してください');
  caseIdEl.value = case_result_id;
  setTab('summary');
  Status.loading('Pleasanter取得中...', `案件 ${case_result_id} のメールを取得しています`, 20);
  const data = await api('/api/pleasanter/summarize_case', {
    method: 'POST',
    body: JSON.stringify({ case_result_id })
  });
  Status.loading('AI要約中...', `${data.emails_total || 0}件のメールを解析しています`, 60);
  currentConversationId = data.conversation_id;
  if (data.parsed) {
    causeEl.value = data.parsed.cause || '';
    solutionEl.value = data.parsed.solution || '';
    detailsEl.value = data.parsed.details || '';
  }
  await refreshConversations();
  await loadForm();
  updateChatEndpoint();
  Status.success('Pleasanter要約完了', `案件 ${data.case_result_id} / ${data.emails_total || 0}件のメールを処理`);
}

newConversationBtn.addEventListener('click', async () => {
  setBusy(true);
  Status.loading('新規会話作成中...', '会話データを初期化しています');
  try {
    await createConversation();
  } catch (e) {
    Status.error('新規会話作成エラー', e.message);
  } finally {
    setBusy(false);
  }
});

summarizeBtn.addEventListener('click', async () => {
  setBusy(true);
  Status.loading('要約準備中...', 'メール本文を読み込んでいます', 10);
  try {
    await summarizeEmail();
  } catch (e) {
    Status.error('要約エラー', e.message);
  } finally {
    setBusy(false);
  }
});

saveFormBtn.addEventListener('click', async () => {
  if (!currentConversationId) {
    Status.error('保存エラー', '会話を選択してください');
    return;
  }
  setBusy(true);
  loggers.form.info('Starting save process, conversation_id:', currentConversationId);
  Status.loading('保存中...', 'フォームデータを送信しています', 30);
  try {
    // 1. ローカルDB保存
    loggers.form.info('Step 1: Saving to local DB');
    await saveForm();
    loggers.form.info('Step 1 complete');
    Status.loading('保存中...', 'Pleasanterに書き込んでいます', 70);

    // 2. Pleasanterまとめサイトに保存
    loggers.pleasanter.info('Step 2: Saving to Pleasanter summary site');
    const result = await api('/api/pleasanter/save_summary', {
      method: 'POST',
      body: JSON.stringify({
        conversation_id: currentConversationId
      })
    });
    loggers.pleasanter.info('Step 2 complete, result:', result);

    Status.success('保存完了', result.message || 'まとめサイトに保存しました');
  } catch (e) {
    loggers.form.error('Save error:', e);
    loggers.form.error('Error details:', e.meta, e.data);
    Status.error('保存エラー', e.message);
  } finally {
    setBusy(false);
  }
});

fetchFromPleasanterBtn.addEventListener('click', async () => {
  setBusy(true);
  Status.loading('Pleasanter接続中...', 'APIに接続しています', 5);
  try {
    await summarizeFromPleasanter();
  } catch (e) {
    Status.error('Pleasanter取得エラー', e.message);
  } finally {
    setBusy(false);
  }
});

(async function init() {
  loggers.app.info('Application initializing, log level:', window.__LOG_LEVEL__);
  try {
    Status.loading('初期化中...', 'ユーザー情報を読み込んでいます', 20);
    await loadMe();
    Status.loading('初期化中...', '会話履歴を読み込んでいます', 50);
    await refreshConversations();
    Status.loading('初期化中...', '案件一覧を読み込んでいます', 80);
    setTab('mail');
    setMailMode('pleasanter');
    try {
      await loadCases();
      Status.success('準備完了', 'すべてのデータを読み込みました');
      loggers.app.info('Application initialization complete');
    } catch (err) {
      Status.warning('一部エラー', `案件一覧の取得に失敗: ${err.message}`);
      loggers.app.warn('Failed to load cases:', err);
    }
  } catch (e) {
    Status.error('初期化エラー', e.message);
    loggers.app.error('Application initialization failed:', e);
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
        Status.loading('案件検索中...', `"${value}" で検索しています`, 30);
        await loadCases(value);
        Status.success('検索完了', '案件一覧を更新しました');
      } catch (err) {
        Status.error('案件検索エラー', err.message);
      }
    }, 300);
  });
}

if (caseUrlApplyEl) {
  caseUrlApplyEl.addEventListener('click', async () => {
    const raw = String(caseUrlEl?.value || '').trim();
    const caseId = extractCaseIdFromUrl(raw);
    if (!caseId) {
      Status.error('URL解析エラー', '案件URLからIDを抽出できませんでした');
      return;
    }
    setBusy(true);
    Status.loading('案件URL確認中...', `案件ID ${caseId} を検証しています`, 30);
    try {
      const item = await validateCaseId(caseId);
      setCaseInfo(item);
      await summarizeFromPleasanter(String(item.result_id || caseId));
    } catch (e) {
      Status.error('案件URLエラー', e.message);
    } finally {
      setBusy(false);
    }
  });
}

// チャット入力のイベントリスナー
if (chatInputEl) {
  chatInputEl.addEventListener('input', () => {
    updateChatSendButton();
    // 自動でtextareaの高さを調整
    chatInputEl.style.height = 'auto';
    chatInputEl.style.height = Math.min(chatInputEl.scrollHeight, 120) + 'px';
  });

  chatInputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!chatSendBtn.disabled) {
        sendChatMessage();
      }
    }
  });
}

if (chatSendBtn) {
  chatSendBtn.addEventListener('click', () => {
    sendChatMessage();
  });
}

if (clearChatBtn) {
  clearChatBtn.addEventListener('click', async () => {
    if (confirm('会話履歴をクリアしますか?')) {
      await createConversation();
    }
  });
}

// チェックボックスの変更を自動保存
async function autoSaveCheckboxes() {
  if (!currentConversationId) return;
  try {
    loggers.form.debug('Auto-saving checkbox state');
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
    loggers.form.debug('Auto-save complete');
  } catch (e) {
    loggers.form.error('Failed to auto-save checkboxes:', e);
  }
}

// チェックボックスの変更イベント
if (includeCauseEl) {
  includeCauseEl.addEventListener('change', () => {
    autoSaveCheckboxes();
  });
}

if (includeSolutionEl) {
  includeSolutionEl.addEventListener('change', () => {
    autoSaveCheckboxes();
  });
}

if (includeDetailsEl) {
  includeDetailsEl.addEventListener('change', () => {
    autoSaveCheckboxes();
  });
}
