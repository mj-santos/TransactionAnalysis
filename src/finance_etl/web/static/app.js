/* =========================================================
   Spendly  —  Web UI  app.js
   ========================================================= */

'use strict';

// ── State ──────────────────────────────────────────────────
const state = {
  uploadedFiles: [],   // [{filename, path, size}]
  pollTimer: null,
  currentRunId: null,
  settings: {
    verbose_logs: false,
    show_logs: false,
  },
};

const REPORT_META = {
  'spend_by_month_category.csv': { icon: '📅', desc: 'Monthly spend by category' },
  'cashflow_by_month.csv':        { icon: '💸', desc: 'Monthly inflow, outflow & net' },
  'spend_by_merchant.csv':        { icon: '🏪', desc: 'Total spend per merchant' },
  'totals_by_account.csv':        { icon: '🏦', desc: 'Net balance per account' },
  'top_merchants.csv':            { icon: '🏆', desc: 'Top 50 merchants by spend' },
};

// ── Navigation ──────────────────────────────────────────────
document.querySelectorAll('.sidebar nav a').forEach(link => {
  link.addEventListener('click', e => {
    e.preventDefault();
    navigate(link.dataset.page);
  });
});

function navigate(page) {
  document.querySelectorAll('.sidebar nav a').forEach(l => l.classList.remove('active'));
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  const link = document.querySelector(`.sidebar nav a[data-page="${page}"]`);
  const section = document.getElementById(`page-${page}`);
  if (link)    link.classList.add('active');
  if (section) section.classList.add('active');

  const titles = {
    dashboard:          'Dashboard',
    import:             'Import Transactions',
    history:            'Import History',
    'credit-cards':     'Credit Card Transactions',
    'bank-transactions':'Bank Transactions',
    cashflow:           'Cash Flow',
    reports:            'Analytics Reports',
    'merchant-rules':   'Merchant Rules & Categories',
    'category-rules':   'Category Rules',
    'recurring-transactions': 'Recurring Transactions',
    accounts:           'Accounts & Liabilities',
    utilities:          'Utilities',
    settings:           'Settings & Logs',
  };
  document.getElementById('topbar-title').textContent = titles[page] || page;

  if (page === 'history')            loadHistory();
  if (page === 'cashflow')           loadCashFlow();
  if (page === 'reports')            loadReports();
  if (page === 'settings')           loadSettings();
  if (page === 'credit-cards')       loadTxnTab('credit_card');
  if (page === 'bank-transactions')  loadTxnTab('bank');
  if (page === 'merchant-rules')     { loadMerchantAnalytics(); loadMerchantRules(); _clearSuggestions(); }
  if (page === 'category-rules')     { loadCategoryRules(); }
  if (page === 'recurring-transactions') { loadRecurringTransactions(); }
  if (page === 'accounts')           { loadAccounts(); }
  if (page === 'utilities')          { loadUtilCategories(); loadUtilMerchants(); loadUtilDuplicates(); loadUtilHealth(); _showImproveStats(); }
}

// ── Toasts ──────────────────────────────────────────────────
function toast(msg, type = 'info', duration = 4000) {
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = msg;
  document.getElementById('toasts').appendChild(el);
  setTimeout(() => el.remove(), duration);
}

// ── Collapsible Card Panels ─────────────────────────────────
// Collapse state is persisted in localStorage so panels stay
// collapsed/expanded across page navigations within a session.
// NOTE: If a DB-backed settings store is added later, consider
// migrating collapse prefs there for cross-device consistency.

function toggleCardCollapse(headerEl) {
  const card = headerEl.closest('.card');
  if (!card || !card.id) return;
  card.classList.toggle('collapsed');
  localStorage.setItem('collapse_' + card.id, card.classList.contains('collapsed'));
}

function restoreCollapseState() {
  document.querySelectorAll('.card[id] .card-header-toggle').forEach(hdr => {
    const card = hdr.closest('.card');
    if (card && card.id && localStorage.getItem('collapse_' + card.id) === 'true') {
      card.classList.add('collapsed');
    }
  });
}

/** Ensure a collapsible card is expanded (e.g. before scrolling to its content). */
function ensureCardExpanded(cardId) {
  const card = document.getElementById(cardId);
  if (card && card.classList.contains('collapsed')) {
    card.classList.remove('collapsed');
    localStorage.setItem('collapse_' + cardId, 'false');
  }
}

/** Update a badge-count element: show count or hide if zero. */
function _updateBadge(id, count) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = count;
  el.style.display = count ? '' : 'none';
}

// ── Global Transaction Search ────────────────────────────────
let _gsTimer = null;
let _gsActiveIdx = -1;   // keyboard-navigated result index

function _debounceGlobalSearch() {
  clearTimeout(_gsTimer);
  _gsTimer = setTimeout(_runGlobalSearch, 300);
}

async function _runGlobalSearch() {
  const input = document.getElementById('global-search-input');
  const panel = document.getElementById('global-search-results');
  const q = (input ? input.value : '').trim();
  if (q.length < 2) {
    panel.style.display = 'none';
    return;
  }
  panel.style.display = '';
  panel.innerHTML = '<div class="gs-status">Searching…</div>';
  _gsActiveIdx = -1;
  try {
    const data = await api('GET', `/transactions/search?q=${encodeURIComponent(q)}&limit=50`);
    if (!data.rows.length) {
      panel.innerHTML = '<div class="gs-status">No results</div>';
      return;
    }
    const header = `<div class="gs-status">${data.total_count} result${data.total_count !== 1 ? 's' : ''} for "${esc(data.query)}"</div>`;
    const rows = data.rows.map((r, i) => {
      const isCC = r.statement_type === 'credit_card';
      const badgeCls = isCC ? 'gs-badge-cc' : 'gs-badge-bank';
      const badgeText = isCC ? 'CC' : 'Bank';
      const desc = r.merchant || r.description || '';
      return `<div class="gs-row" data-idx="${i}" data-fp="${esc(r.transaction_fingerprint)}" data-type="${esc(r.statement_type)}" data-date="${esc(r.transaction_date)}" onclick="_gsClickResult(this)">
        <span class="gs-date">${esc(r.transaction_date)}</span>
        <span class="gs-desc" title="${esc(r.description)}">${esc(desc)}</span>
        <span class="gs-amt">${_fmt$(r.amount)}</span>
        <span class="gs-cat">${esc(r.category_normalized || '')}</span>
        <span class="gs-badge ${badgeCls}">${badgeText}</span>
      </div>`;
    }).join('');
    panel.innerHTML = header + rows;
  } catch (err) {
    panel.innerHTML = `<div class="gs-status">Error: ${esc(err.message)}</div>`;
  }
}

function _gsClickResult(el) {
  const fp = el.dataset.fp;
  const type = el.dataset.type;
  const date = el.dataset.date;
  _closeGlobalSearch();
  // Navigate to the correct tab — derived from per-result statement_type
  const page = type === 'credit_card' ? 'credit-cards' : 'bank-transactions';
  navigate(page);
  // Pre-filter to the transaction's date range and highlight it
  setTimeout(() => {
    const tabType = type === 'credit_card' ? 'credit_card' : 'bank';
    // Set date filters to the transaction's month
    const d = new Date(date);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const firstDay = `${y}-${m}-01`;
    const lastDay = new Date(y, d.getMonth() + 1, 0);
    const lastDayStr = `${y}-${m}-${String(lastDay.getDate()).padStart(2, '0')}`;
    const prefix = type === 'credit_card' ? 'cc' : 'bk';
    const fromEl = document.getElementById(`${prefix}-date-from`);
    const toEl   = document.getElementById(`${prefix}-date-to`);
    if (fromEl) fromEl.value = firstDay;
    if (toEl)   toEl.value   = lastDayStr;
    // Reload tab, then highlight the fingerprint
    loadTxnTab(tabType).then(() => {
      const row = document.querySelector(`tr[data-fp="${fp}"]`);
      if (row) {
        row.style.background = 'rgba(59,130,246,.12)';
        row.scrollIntoView({ behavior: 'smooth', block: 'center' });
        setTimeout(() => { row.style.background = ''; }, 3000);
      }
    });
  }, 100);
}

function _closeGlobalSearch() {
  const panel = document.getElementById('global-search-results');
  if (panel) panel.style.display = 'none';
  _gsActiveIdx = -1;
}

function _globalSearchKeydown(e) {
  const panel = document.getElementById('global-search-results');
  if (!panel || panel.style.display === 'none') return;
  const rows = panel.querySelectorAll('.gs-row');
  if (e.key === 'Escape') {
    e.preventDefault();
    _closeGlobalSearch();
    document.getElementById('global-search-input').blur();
    return;
  }
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    _gsActiveIdx = Math.min(_gsActiveIdx + 1, rows.length - 1);
    rows.forEach((r, i) => r.classList.toggle('gs-active', i === _gsActiveIdx));
    if (rows[_gsActiveIdx]) rows[_gsActiveIdx].scrollIntoView({ block: 'nearest' });
    return;
  }
  if (e.key === 'ArrowUp') {
    e.preventDefault();
    _gsActiveIdx = Math.max(_gsActiveIdx - 1, 0);
    rows.forEach((r, i) => r.classList.toggle('gs-active', i === _gsActiveIdx));
    if (rows[_gsActiveIdx]) rows[_gsActiveIdx].scrollIntoView({ block: 'nearest' });
    return;
  }
  if (e.key === 'Enter' && _gsActiveIdx >= 0 && rows[_gsActiveIdx]) {
    e.preventDefault();
    _gsClickResult(rows[_gsActiveIdx]);
    return;
  }
}

// Close search panel when clicking outside
document.addEventListener('click', e => {
  const wrap = document.getElementById('global-search-wrap');
  if (wrap && !wrap.contains(e.target)) _closeGlobalSearch();
});

// ── API helpers ─────────────────────────────────────────────
async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body && !(body instanceof FormData)) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  } else if (body) {
    opts.body = body;
  }
  const res = await fetch(path, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const detail = err.detail || res.statusText;
    const status = res.status;
    throw new Error(`(${status}) ${detail}`);
  }
  return res.json();
}

function fmt(n) { return n == null ? '—' : Number(n).toLocaleString(); }
function fmtDate(s) {
  if (!s) return '—';
  try { return new Date(s).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' }); }
  catch { return s; }
}

// ── Drop zone ───────────────────────────────────────────────
const dropZone  = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');

dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag-over'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  handleFiles([...e.dataTransfer.files]);
});
fileInput.addEventListener('change', () => handleFiles([...fileInput.files]));

function handleFiles(files) {
  files.forEach(f => {
    if (!f.name.endsWith('.csv')) { toast(`${f.name} is not a CSV file`, 'error'); return; }
    uploadFile(f);
  });
}

async function uploadFile(file) {
  const chipId = `chip-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  addChip(chipId, file.name, file.size, 'uploading');

  const fd = new FormData();
  fd.append('file', file);

  try {
    const data = await api('POST', '/upload', fd);
    state.uploadedFiles.push({ filename: data.filename, path: data.path, size: data.size, chipId });
    updateChip(chipId, 'done');
    toast(`${file.name} uploaded`, 'success', 2500);
    // Open the mapping wizard automatically after upload
    wizardOpen(data);
  } catch (err) {
    updateChip(chipId, 'error');
    toast(`Upload failed: ${err.message}`, 'error');
    maybeShowLogsOnError();
  }
}

function addChip(id, name, size, status) {
  const chips = document.getElementById('file-chips');
  const el = document.createElement('div');
  el.className = `file-chip ${status}`;
  el.id = id;
  const kb = size ? `${(size / 1024).toFixed(1)} KB` : '';
  el.innerHTML = `
    <span class="chip-name" title="${esc(name)}">${esc(name)}</span>
    <span class="chip-size">${kb}</span>
    <button class="chip-rm" title="Remove" onclick="removeChip('${id}')">✕</button>`;
  chips.appendChild(el);
}

function updateChip(id, status) {
  const el = document.getElementById(id);
  if (el) { el.className = `file-chip ${status}`; }
}

function removeChip(id) {
  const el = document.getElementById(id);
  if (el) el.remove();
  state.uploadedFiles = state.uploadedFiles.filter(f => f.chipId !== id);
  // FIX 2: removing the file mid-session also resets the wizard state
  if (state.uploadedFiles.length === 0) {
    _clearImportSession();
  }
}

// ── FIX 2: Clear full import session state ─────────────────────
// Called on wizard exit, chip removal (last file), and explicit reset.
function _clearImportSession() {
  state.uploadedFiles = [];
  document.getElementById('file-chips').innerHTML = '';
  // Reset file input so the same file can be re-uploaded
  const fi = document.getElementById('file-input');
  if (fi) fi.value = '';
  // Hide preview panel
  document.getElementById('preview-container').style.display = 'none';
  // Discard any pending run poll (keeps the run-status display visible)
  clearTimeout(state.pollTimer);
}

function resetImports() {
  _clearImportSession();
  state.currentRunId = null;
  document.getElementById('run-status').className = 'run-status'; // hide
  document.getElementById('rs-counts').innerHTML = '';
  document.getElementById('rs-actions').innerHTML = '';
  toast('Import reset — upload a new file to start again.', 'info', 2500);
}

// ── Poll run status ──────────────────────────────────────────
function pollRun(runId, cb, interval = 1500) {
  clearTimeout(state.pollTimer);
  state.pollTimer = setTimeout(async () => {
    try {
      const s = await api('GET', `/runs/${runId}`);
      const status = s.status;

      if (status === 'pending' || status === 'running') {
        setRunStatus(status, runId, s.counts, status === 'running' ? 'Processing rows…' : 'Starting…');
        pollRun(runId, cb, interval);
      } else if (status === 'staged') {
        setRunStatus('staged', runId, s.counts, 'Preview ready — review and commit or discard.');
        loadPreview(runId);
        if (cb) cb(s);
      } else if (status === 'committing') {
        setRunStatus('running', runId, s.counts, 'Committing to ledger…');
        pollRun(runId, cb, interval);
      } else {
        setRunStatus(status, runId, s.counts, status === 'success' ? 'Import complete!' : (s.error || 'Pipeline failed.'));
        if (cb) cb(s);
      }
    } catch (err) {
      setRunStatus('failed', runId, null, `Polling error: ${err.message}`);
    }
  }, interval);
}

function onRunComplete(run) {
  if (run.status === 'success') {
    toast('Import complete!', 'success');
    // Show duplicate detection banner if any found
    if (run.duplicate_count > 0) {
      _showDuplicateBanner(run.duplicate_count, run.duplicate_reasons || []);
    }
    refreshDupBadge();
  } else if (run.status === 'failed') {
    toast(`Import failed: ${run.error || '(unknown error)'}`, 'error');
    maybeShowLogsOnError();
  }
}

function _showDuplicateBanner(count, reasons) {
  const existing = document.getElementById('dup-banner');
  if (existing) existing.remove();
  const banner = document.createElement('div');
  banner.id = 'dup-banner';
  banner.className = 'dup-banner';

  // Determine banner text based on reason types
  const reasonSet = new Set((reasons || []).map(r => r.reason || ''));
  const hasAmtVar = [...reasonSet].some(r => r.includes('amount_variance'));
  const hasFuzzyDesc = [...reasonSet].some(r => r.includes('fuzzy_description'));
  let bannerText;
  if (hasAmtVar && !hasFuzzyDesc) {
    bannerText = `⚠️ ${count} possible duplicate transaction${count !== 1 ? 's' : ''} found — some may be pending charges that settled at a different amount.`;
  } else if (hasFuzzyDesc && !hasAmtVar) {
    bannerText = `⚠️ ${count} possible duplicate transaction${count !== 1 ? 's' : ''} found — bank descriptions may have changed between exports.`;
  } else {
    bannerText = `⚠️ ${count} possible duplicate transaction${count !== 1 ? 's' : ''} detected.`;
  }

  banner.innerHTML = `${bannerText}
    <a href="#" onclick="event.preventDefault(); navigate('utilities'); ensureCardExpanded('util-card-duplicates');">Review in Utilities → Duplicate Review.</a>
    <button onclick="this.parentElement.remove()" style="background:none; border:none; cursor:pointer; font-size:16px; color:var(--text-muted); margin-left:8px;">×</button>`;
  const statusCard = document.getElementById('run-status');
  if (statusCard) statusCard.parentElement.insertBefore(banner, statusCard.nextSibling);
}

// ── Run status card ──────────────────────────────────────────
function setRunStatus(status, runId, counts, label) {
  const card = document.getElementById('run-status');
  card.className = `run-status visible ${status}`;

  const icons = { pending: '⏳', running: '⚙️', staged: '👁️', committing: '⚙️', success: '✅', failed: '❌' };
  document.getElementById('rs-icon').textContent = icons[status] || '⏳';
  document.getElementById('rs-label').textContent = label || status;
  document.getElementById('rs-id').textContent   = runId ? `#${runId}` : '';

  const countsEl = document.getElementById('rs-counts');
  countsEl.innerHTML = '';
  if (counts) {
    [['rows_in','In'], ['rows_staged','Staged'], ['rows_normalized','Normalised'],
     ['rows_loaded','Loaded'], ['errors_count','Errors']].forEach(([k, l]) => {
      if (counts[k] != null) {
        const chip = document.createElement('span');
        chip.className = 'rs-count';
        chip.textContent = `${l}: ${fmt(counts[k])}`;
        countsEl.appendChild(chip);
      }
    });
  }

  const actionsEl = document.getElementById('rs-actions');
  actionsEl.innerHTML = '';
  if (status === 'staged' && runId) {
    actionsEl.innerHTML = `
      <button class="btn btn-success btn-sm" onclick="commitRun('${runId}')">✓ Commit to ledger</button>
      <button class="btn btn-danger  btn-sm" onclick="discardRun('${runId}')">✕ Discard</button>`;
  }
}

// ── Preview panel (import page) ──────────────────────────────
async function loadPreview(runId) {
  document.getElementById('preview-container').style.display = 'block';
  document.getElementById('preview-tbody').innerHTML =
    '<tr><td colspan="9" class="text-center text-muted" style="padding:20px">Loading…</td></tr>';

  try {
    const data = await api('GET', `/runs/${runId}/preview`);
    renderPreviewRows('preview-tbody', data.rows, 'preview-head');
    document.getElementById('preview-meta').textContent =
      `${data.count} row(s)${data.truncated ? ' (truncated)' : ''}`;
  } catch (err) {
    document.getElementById('preview-tbody').innerHTML =
      `<tr><td colspan="9" class="text-center text-muted">Error: ${esc(err.message)}</td></tr>`;
  }
}

// Ordered column config for preview tables; optional columns shown only when present in data
const _PREVIEW_COL_DEFS = [
  { key: 'source_row',           label: '#',           cls: 'mono text-muted', style: '' },
  { key: 'transaction_date_raw', label: 'Date',        cls: '',                style: '' },
  { key: 'description_raw',      label: 'Description', cls: '',                style: 'max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;' },
  { key: 'amount_raw',           label: 'Amount',      cls: 'mono text-right', style: '' },
  { key: 'currency_raw',         label: 'Currency',    cls: '',                style: '' },
  { key: 'account_name',         label: 'Account',     cls: 'text-muted',      style: '' },
  { key: 'merchant',             label: 'Merchant',    cls: '',                style: '' },
  { key: 'category',             label: 'Category',    cls: '',                style: '' },
  { key: 'notes',                label: 'Notes',       cls: 'text-muted',      style: '' },
];

function renderPreviewRows(tbodyId, rows, theadId) {
  const tbody = document.getElementById(tbodyId);
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="9" class="text-center text-muted" style="padding:20px">No rows found.</td></tr>';
    return;
  }
  // Determine which columns are present (have at least one non-empty value)
  const activeCols = _PREVIEW_COL_DEFS.filter(c =>
    rows.some(r => r[c.key] != null && r[c.key] !== '')
  );
  // Update thead if provided
  if (theadId) {
    const thead = document.getElementById(theadId);
    if (thead) {
      thead.innerHTML = activeCols.map(c => `<th>${esc(c.label)}</th>`).join('');
    }
  }
  const span = activeCols.length || 1;
  tbody.innerHTML = rows.map(r => `
    <tr>${activeCols.map(c => {
      const val = r[c.key] != null ? String(r[c.key]) : '';
      const style = c.style ? ` style="${c.style}"` : '';
      const title = c.style.includes('ellipsis') ? ` title="${esc(val)}"` : '';
      const cls   = c.cls ? ` class="${c.cls}"` : '';
      return `<td${cls}${style}${title}>${esc(val)}</td>`;
    }).join('')}</tr>`).join('');
}

// ── Commit / discard ─────────────────────────────────────────
async function commitRun(runId) {
  try {
    await api('POST', `/runs/${runId}/commit`);
    setRunStatus('committing', runId, null, 'Committing to ledger…');
    document.getElementById('preview-container').style.display = 'none';
    pollRun(runId, onRunComplete);
  } catch (err) {
    toast(`Commit failed: ${err.message}`, 'error');
    maybeShowLogsOnError();
  }
}

function discardRun(runId) {
  setRunStatus('failed', runId, null, 'Import discarded.');
  document.getElementById('preview-container').style.display = 'none';
  document.getElementById('import-btn').disabled = false;
  toast('Import discarded — data was not written to ledger.', 'info');
}

// ── History page ─────────────────────────────────────────────
async function loadHistory() {
  const tbody = document.getElementById('history-tbody');
  tbody.innerHTML = '<tr><td colspan="9" class="text-center text-muted" style="padding:32px">Loading…</td></tr>';

  try {
    const data = await api('GET', '/runs');
    if (!data.runs.length) {
      tbody.innerHTML = '<tr><td colspan="9" class="text-center text-muted" style="padding:32px">No runs yet. Import some transactions first.</td></tr>';
      return;
    }
    tbody.innerHTML = data.runs.map(r => {
      const status = r.status || 'unknown';
      const badge  = `<span class="badge badge-${status}">${status}</span>`;
      const isNorm = r.type === 'normalize';

      // IMPORTED FILE cell
      let importedCell;
      if (isNorm) {
        importedCell = `<span style="font-size:11px; color:var(--text-muted);">↻ Re-normalize</span>`;
      } else {
        importedCell = r.imported_file
          ? `<span style="font-size:12px;" title="${esc(r.imported_file)}">${esc(r.imported_file)}</span>`
          : `<span style="color:var(--text-muted); font-size:11px;">—</span>`;
      }

      // Actions
      const actions = [];
      if (!isNorm) {
        if (status === 'staged') {
          actions.push(`<button class="btn btn-secondary btn-sm" onclick="showHistoryPreview('${r.run_id}')">👁 Preview</button>`);
          actions.push(`<button class="btn btn-success btn-sm" onclick="commitRunFromHistory('${r.run_id}')">Commit</button>`);
        } else {
          actions.push(`<button class="btn btn-secondary btn-sm" onclick="showHistoryPreview('${r.run_id}')">👁 View</button>`);
        }
        actions.push(`<button class="btn btn-danger btn-sm" onclick="showDeleteModal('${r.run_id}')">🗑 Delete</button>`);
      }

      const rowClass = isNorm ? 'style="background:var(--bg-alt, #f8faff);"' : '';
      return `<tr ${rowClass}>
        <td class="mono" style="font-size:11px;">${esc(r.run_id)}</td>
        <td>${importedCell}</td>
        <td>${fmtDate(r.started_at)}</td>
        <td>${badge}</td>
        <td class="text-right">${isNorm ? fmt(r.rows_total) : fmt(r.rows_in)}</td>
        <td class="text-right">${isNorm ? fmt(r.rows_done) : fmt(r.rows_staged)}</td>
        <td class="text-right">${isNorm ? '—' : fmt(r.rows_loaded)}</td>
        <td class="text-right ${!isNorm && r.errors_count > 0 ? 'text-danger' : ''}">${isNorm ? '—' : fmt(r.errors_count)}</td>
        <td><div style="display:flex;gap:6px">${actions.join('')}</div></td>
      </tr>`;
    }).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="9" class="text-center text-muted">Error: ${esc(err.message)}</td></tr>`;
  }
}

async function showHistoryPreview(runId) {
  const container = document.getElementById('history-preview-container');
  const tbody      = document.getElementById('history-preview-tbody');
  document.getElementById('history-preview-id').textContent = runId;
  container.style.display = 'block';
  tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted" style="padding:20px">Loading…</td></tr>';
  container.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

  try {
    const data = await api('GET', `/runs/${runId}/preview`);
    renderPreviewRows('history-preview-tbody', data.rows, 'history-preview-head');
    document.getElementById('history-preview-meta').textContent =
      `${data.count} row(s)${data.truncated ? ' (truncated to 200)' : ''}`;
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="9" class="text-center text-muted">Error: ${esc(err.message)}</td></tr>`;
  }
}

async function commitRunFromHistory(runId) {
  try {
    await api('POST', `/runs/${runId}/commit`);
    toast('Committing…', 'info');
    setTimeout(loadHistory, 2000);
  } catch (err) {
    toast(`Commit failed: ${err.message}`, 'error');
    maybeShowLogsOnError();
  }
}

let _deleteRunId = null;
function showDeleteModal(runId) {
  _deleteRunId = runId;
  document.getElementById('delete-run-modal-id').textContent = runId;
  document.getElementById('delete-keep-tx').checked = false;
  document.getElementById('delete-run-modal').classList.remove('hidden');
}
function hideDeleteModal() {
  _deleteRunId = null;
  document.getElementById('delete-run-modal').classList.add('hidden');
}
async function confirmDeleteRun() {
  if (!_deleteRunId) return;
  const keepTx = document.getElementById('delete-keep-tx').checked;
  const runId  = _deleteRunId;
  hideDeleteModal();
  try {
    await api('DELETE', `/runs/${runId}?keep_transactions=${keepTx}`);
    toast(`Run ${runId} deleted.`, 'success');
    loadHistory();
  } catch (err) {
    toast(`Delete failed: ${err.message}`, 'error');
  }
}

// ── Reports page ──────────────────────────────────────────────
async function loadReports() {
  const grid = document.getElementById('reports-grid');
  grid.innerHTML = '<div class="empty"><div class="empty-icon">⏳</div>Loading…</div>';
  loadSavedReports();

  try {
    const data = await api('GET', '/reports');
    if (!data.reports.length) {
      grid.innerHTML = '<div class="empty"><div class="empty-icon">📊</div>No reports yet. Import data or restore a backup to generate reports.<br><button class="btn btn-primary btn-sm" style="margin-top:12px;" onclick="regenerateReports()">Generate Reports</button></div>';
      return;
    }
    grid.innerHTML = data.reports.map(name => {
      const meta = REPORT_META[name] || { icon: '📄', desc: '' };
      const label = name.replace('.csv', '').replace(/_/g, ' ');
      const menuHtml = `
        <button onclick="event.stopPropagation();editReport('${esc(name)}')">✏ Use as template</button>
        <button onclick="event.stopPropagation();window.location='/reports/${esc(name)}'">⬇ Download CSV</button>`.replace(/"/g, '&quot;');
      return `
        <div class="report-card" onclick="viewChart('${esc(name)}')"
             data-menu-html="${menuHtml}">
          <button class="rc-menu-btn" onclick="_toggleRcMenu('${esc(name)}',event)" title="More options">⋯</button>
          <div class="rc-icon">${meta.icon}</div>
          <div class="rc-name">${esc(label)}</div>
          <div class="rc-desc">${esc(meta.desc)}</div>
          <div class="rc-open-hint">Click to open →</div>
        </div>`;
    }).join('');
  } catch (err) {
    grid.innerHTML = `<div class="empty">Error: ${esc(err.message)}</div>`;
  }
  document.getElementById('chart-area').style.display = 'none';
}

async function loadSavedReports() {
  const section = document.getElementById('saved-reports-section');
  const grid    = document.getElementById('saved-reports-grid');
  if (!section || !grid) return;
  try {
    const data = await api('GET', '/saved-reports');
    const reports = data.reports || [];
    _updateBadge('saved-reports-count', reports.length);
    if (!reports.length) { section.style.display = 'none'; return; }
    section.style.display = '';
    grid.innerHTML = reports.map(r => {
      const typeBadge = r.stmt_type === 'credit_card' ? '💳 CC'
                      : r.stmt_type === 'bank'         ? '🏦 Bank'
                      : '📊 Both';
      const updated = r.updated_at ? new Date(r.updated_at).toLocaleDateString() : '';
      const menuHtml = `
        <button onclick="event.stopPropagation();_editSavedReport(${r.id})">✏ Edit</button>
        <button class="rc-dd-danger" onclick="event.stopPropagation();_deleteSavedReport(${r.id},'${esc(r.name).replace(/'/g,"\\'")}')">🗑 Delete</button>
      `.replace(/"/g, '&quot;');
      return `<div class="report-card" onclick="_runSavedReport(${r.id})"
                   data-menu-html="${menuHtml}">
        <button class="rc-menu-btn" onclick="_toggleRcMenu(${r.id},event)" title="More options">⋯</button>
        <div class="rc-icon">📋</div>
        <div class="rc-name">${esc(r.name)}</div>
        <div class="rc-desc">${esc(r.description || '')}
          <span style="font-size:10px;color:var(--text-muted);display:block;margin-top:3px;">${esc(typeBadge)}${updated ? ' · ' + updated : ''}</span>
        </div>
        <div class="rc-open-hint">Click to run →</div>
      </div>`;
    }).join('');
  } catch (err) {
    if (section) section.style.display = 'none';
  }
}

function _loadSavedReportIntoBuilder(r) {
  const filters  = typeof r.filters_json  === 'string' ? JSON.parse(r.filters_json  || '[]') : (r.filters_json  || []);
  const group_by = typeof r.group_by_json === 'string' ? JSON.parse(r.group_by_json || '[]') : (r.group_by_json || []);
  _loadStateIntoBuilder({
    filters, group_by,
    bucket:    r.bucket    || '',
    date_from: r.date_from || null,
    date_to:   r.date_to   || null,
    stmt_type: r.stmt_type || 'both',
  });
  document.getElementById('custom-report-card')
    ?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

async function _runSavedReport(id) {
  try {
    const data = await api('GET', '/saved-reports');
    const r = (data.reports || []).find(x => x.id === id);
    if (!r) { toast('Report not found.', 'error'); return; }
    _loadSavedReportIntoBuilder(r);
    await runCustomReport();
  } catch (err) { toast(`Failed: ${err.message}`, 'error'); }
}

async function _editSavedReport(id) {
  try {
    const data = await api('GET', '/saved-reports');
    const r = (data.reports || []).find(x => x.id === id);
    if (!r) { toast('Report not found.', 'error'); return; }
    _loadSavedReportIntoBuilder(r);
    document.getElementById('save-report-panel').dataset.editId = id;
    document.getElementById('save-report-name').value = r.name;
    document.getElementById('save-report-desc').value = r.description || '';
    document.getElementById('save-report-panel').style.display = '';
  } catch (err) { toast(`Failed: ${err.message}`, 'error'); }
}

async function _deleteSavedReport(id, name) {
  if (!confirm(`Delete saved report "${name}"?`)) return;
  try {
    await api('DELETE', `/saved-reports/${id}`);
    toast('Report deleted.', 'success');
    loadSavedReports();
  } catch (err) { toast(`Failed: ${err.message}`, 'error'); }
}

async function regenerateReports() {
  try {
    toast('Generating reports…', 'info');
    await api('POST', '/reports/regenerate');
    toast('Reports generated successfully.', 'success');
    loadReports();
  } catch (err) {
    toast(`Report generation failed: ${err.message}`, 'error');
  }
}

async function viewChart(name) {
  const area = document.getElementById('chart-area');
  area.style.display = 'block';
  document.getElementById('chart-title').textContent = name.replace('.csv','').replace(/_/g,' ');
  document.getElementById('chart-head').innerHTML = '';
  document.getElementById('chart-body').innerHTML =
    '<tr><td class="text-center text-muted" style="padding:20px">Loading…</td></tr>';
  document.getElementById('chart-foot').innerHTML = '';
  // Store name for grouping controls and reset their state
  document.getElementById('chart-current-name').value = name;
  document.getElementById('chart-group-field').value  = '';
  document.getElementById('chart-group-bucket').value = '';
  area.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  await _loadChartData(name, '');
}

async function _loadChartData(name, queryParams) {
  const url = `/charts/${encodeURIComponent(name)}` + (queryParams ? `?${queryParams}` : '');
  try {
    const data = await api('GET', url);
    if (!data.rows.length) {
      document.getElementById('chart-body').innerHTML =
        '<tr><td class="text-center text-muted" style="padding:20px">No data.</td></tr>';
      document.getElementById('chart-foot').innerHTML = '';
      return;
    }
    const cols = Object.keys(data.rows[0]);
    const catCol = cols.find(c => /^category/i.test(c));
    document.getElementById('chart-head').innerHTML = cols.map(c => `<th>${esc(c)}</th>`).join('');
    document.getElementById('chart-body').innerHTML = data.rows.map(row => {
      if (catCol && row[catCol]) {
        const dateCol = cols.find(c => /date|month|period/i.test(c));
        let drillFrom = '', drillTo = '';
        if (dateCol && row[dateCol]) {
          const dv = String(row[dateCol]);
          if (/^\d{4}-\d{2}$/.test(dv)) {
            drillFrom = dv + '-01';
            const [y, m] = dv.split('-').map(Number);
            const ld = new Date(y, m, 0).getDate();
            drillTo = dv + '-' + String(ld).padStart(2, '0');
          } else if (/^\d{4}-\d{2}-\d{2}$/.test(dv)) {
            drillFrom = dv; drillTo = dv;
          }
        }
        const jsonCat = JSON.stringify(String(row[catCol])).replace(/'/g, '&#39;').replace(/"/g, '&quot;');
        const onclick = drillFrom
          ? `onclick="openCategoryDrilldown(${jsonCat}, '${drillFrom}', '${drillTo}')" style="cursor:pointer;" onmouseenter="this.style.background='var(--bg,#f1f5f9)'" onmouseleave="this.style.background=''"`
          : `onclick="openCategoryDrilldown(${jsonCat})" style="cursor:pointer;" onmouseenter="this.style.background='var(--bg,#f1f5f9)'" onmouseleave="this.style.background=''"`;
        return `<tr ${onclick}>${cols.map(c => `<td>${esc(String(row[c] ?? ''))}</td>`).join('')}</tr>`;
      }
      return `<tr>${cols.map(c => `<td>${esc(String(row[c] ?? ''))}</td>`).join('')}</tr>`;
    }).join('');
    _renderTotalsRow('chart-foot', cols, data.rows);
  } catch (err) {
    document.getElementById('chart-body').innerHTML =
      `<tr><td class="text-center text-muted">Error: ${esc(err.message)}</td></tr>`;
    document.getElementById('chart-foot').innerHTML = '';
  }
}

function _renderTotalsRow(tfootId, cols, rows) {
  const foot = document.getElementById(tfootId);
  if (!foot) return;
  const totals = {};
  let hasNumeric = false;
  cols.forEach(c => {
    const nums = rows.map(r => { const v = parseFloat(r[c]); return isNaN(v) ? null : v; }).filter(v => v !== null);
    if (nums.length > 0) { totals[c] = nums.reduce((a, b) => a + b, 0); hasNumeric = true; }
  });
  if (!hasNumeric) { foot.innerHTML = ''; return; }
  foot.innerHTML = `<tr style="font-weight:600; border-top:2px solid var(--border); background:var(--surface);">
    ${cols.map((c, i) => {
      if (totals[c] !== undefined) return `<td class="mono text-right">${totals[c].toFixed(2)}</td>`;
      return `<td>${i === 0 ? '<span style="color:var(--text-muted);font-size:11px;">TOTAL</span>' : ''}</td>`;
    }).join('')}
  </tr>`;
}

async function applyChartGrouping() {
  const name   = document.getElementById('chart-current-name').value;
  const field  = document.getElementById('chart-group-field').value;
  const bucket = document.getElementById('chart-group-bucket').value;
  if (!name) return;
  const params = [];
  if (field)  params.push(`group_by=${encodeURIComponent(field)}`);
  if (bucket) params.push(`bucket=${encodeURIComponent(bucket)}`);
  await _loadChartData(name, params.join('&'));
}

async function resetChartGrouping() {
  const name = document.getElementById('chart-current-name').value;
  document.getElementById('chart-group-field').value  = '';
  document.getElementById('chart-group-bucket').value = '';
  if (name) await _loadChartData(name, '');
}

function closeChart() {
  document.getElementById('chart-area').style.display = 'none';
}

function editReport(name) {
  const tmpl = REPORT_TEMPLATES[name] || { group_by: [], bucket: null, filters: [] };
  _loadStateIntoBuilder({
    filters:   tmpl.filters  || [],
    group_by:  tmpl.group_by || [],
    bucket:    tmpl.bucket   || '',
    date_from: null,
    date_to:   null,
    stmt_type: 'both',
  });
  document.getElementById('custom-report-card')
    ?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// ── Custom report builder ──────────────────────────────────────
// Filter chip state — array of {field, op, value} objects
let _reportFilters = [];

const _OP_LABELS = {
  '=':           'equals',
  '!=':          'excludes',
  'contains':    'contains',
  'not_contains':'does not contain',
  '>=':          '≥',
  '<=':          '≤',
  'in':          'is one of',
  'between':     'between',
  'is_null':     'is empty',
  'not_null':    'is not empty',
};

const _FIELD_LABELS = {
  transaction_date:   'Date',
  description:        'Description',
  merchant:           'Merchant',
  category:           'Category',
  category_normalized:'Category (Norm.)',
  category_parent:    'Category (Parent)',
  amount:             'Amount',
  currency:           'Currency',
  bank_name:          'Bank',
  account_name:       'Account',
};

function _renderFilterChips() {
  const bar = document.getElementById('report-filter-chips');
  const clearBtn = document.getElementById('clear-filters-btn');
  if (!bar) return;
  if (!_reportFilters.length) {
    bar.innerHTML = '<span class="filter-chip-empty">No filters — showing all transactions</span>';
    if (clearBtn) clearBtn.style.display = 'none';
    return;
  }
  if (clearBtn) clearBtn.style.display = '';
  bar.innerHTML = _reportFilters.map((f, i) => {
    const fieldLabel = _FIELD_LABELS[f.field] || f.field;
    const opLabel    = _OP_LABELS[f.op] || f.op;
    const isExclude  = f.op === '!=' || f.op === 'not_contains' || f.op === 'not_null';
    const valText    = (f.op === 'is_null' || f.op === 'not_null') ? ''
                     : Array.isArray(f.value) ? f.value.join(', ')
                     : ` "${f.value}"`;
    const cls = isExclude ? 'filter-chip fc-exclude' : 'filter-chip';
    return `<span class="${cls}">
      <span>${esc(fieldLabel)} ${esc(opLabel)}${esc(valText)}</span>
      <button class="fc-remove" onclick="_removeFilterChip(${i})" title="Remove filter">×</button>
    </span>`;
  }).join('');
}

function _removeFilterChip(idx) {
  _reportFilters.splice(idx, 1);
  _renderFilterChips();
}

function _clearAllFilters() {
  _reportFilters = [];
  _renderFilterChips();
}

function _toggleFilterPopover(e) {
  e.stopPropagation();
  const pop = document.getElementById('filter-popover');
  if (!pop) return;
  const isOpen = pop.style.display !== 'none';
  _closeAllPopovers();
  if (!isOpen) {
    pop.style.display = 'flex';
    document.getElementById('fp-val')?.focus();
    _updateFpValVisibility();
  }
}

function _closeFilterPopover() {
  const pop = document.getElementById('filter-popover');
  if (pop) pop.style.display = 'none';
}

function _updateFpValVisibility() {
  const op = document.getElementById('fp-op')?.value;
  const lbl = document.getElementById('fp-val-label');
  if (lbl) lbl.style.display = (op === 'is_null' || op === 'not_null') ? 'none' : '';
}

document.addEventListener('change', e => {
  if (e.target?.id === 'fp-op') _updateFpValVisibility();
});

function _addFilterChip() {
  const field = document.getElementById('fp-field')?.value;
  const op    = document.getElementById('fp-op')?.value;
  const val   = document.getElementById('fp-val')?.value?.trim();
  if (!field || !op) return;
  if (op !== 'is_null' && op !== 'not_null' && !val) {
    document.getElementById('fp-val')?.focus();
    return;
  }
  let value = val;
  if (op === 'in')      value = val.split(',').map(s => s.trim()).filter(Boolean);
  if (op === 'between') value = val.split(',').map(s => s.trim());
  if (op === 'is_null' || op === 'not_null') value = null;
  _reportFilters.push({ field, op, value });
  _renderFilterChips();
  _closeFilterPopover();
  if (document.getElementById('fp-val')) document.getElementById('fp-val').value = '';
}

// Group-by state — array of field strings
let _reportGroupBy = [];

function _toggleGroupByPopover(e) {
  e.stopPropagation();
  const pop = document.getElementById('group-by-popover');
  if (!pop) return;
  const isOpen = pop.style.display !== 'none';
  _closeAllPopovers();
  if (!isOpen) pop.style.display = '';
}

function _onGroupByChange() {
  const pop = document.getElementById('group-by-popover');
  if (!pop) return;
  _reportGroupBy = [...pop.querySelectorAll('input[type=checkbox]:checked')].map(cb => cb.value);
  _renderGroupByChips();
}

function _renderGroupByChips() {
  const el = document.getElementById('group-by-chips');
  if (!el) return;
  el.innerHTML = _reportGroupBy.map(v =>
    `<span class="group-by-chip">${esc(_FIELD_LABELS[v] || v)}</span>`
  ).join('');
}

function _closeAllPopovers() {
  ['filter-popover', 'group-by-popover'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
  });
}

// Close popovers on outside click
document.addEventListener('click', e => {
  if (!e.target?.closest('#filter-popover') && !e.target?.closest('#add-filter-btn'))
    document.getElementById('filter-popover') && (document.getElementById('filter-popover').style.display = 'none');
  if (!e.target?.closest('#group-by-popover') && !e.target?.closest('#group-by-btn'))
    document.getElementById('group-by-popover') && (document.getElementById('group-by-popover').style.display = 'none');
});

function _setReportDatePreset(preset, btn) {
  // Highlight active preset — remove from all, add to clicked
  document.querySelectorAll('.date-preset-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  setReportDatePreset(preset);
}

function _clearDatePresetHighlight() {
  document.querySelectorAll('.date-preset-btn').forEach(b => b.classList.remove('active'));
}

function _getBuilderState() {
  return {
    filters:   _reportFilters.slice(),
    group_by:  _reportGroupBy.slice(),
    bucket:    document.getElementById('report-bucket')?.value || null,
    date_from: document.getElementById('report-date-from')?.value || null,
    date_to:   document.getElementById('report-date-to')?.value   || null,
    stmt_type: document.querySelector('input[name="report-stmt-type"]:checked')?.value || 'both',
  };
}

function _loadStateIntoBuilder(state) {
  // Filters
  _reportFilters = Array.isArray(state.filters) ? state.filters.slice() : [];
  _renderFilterChips();
  // Group by
  _reportGroupBy = Array.isArray(state.group_by) ? state.group_by.slice() : [];
  const pop = document.getElementById('group-by-popover');
  if (pop) {
    pop.querySelectorAll('input[type=checkbox]').forEach(cb => {
      cb.checked = _reportGroupBy.includes(cb.value);
    });
  }
  _renderGroupByChips();
  // Bucket + dates
  if (document.getElementById('report-bucket'))
    document.getElementById('report-bucket').value = state.bucket || '';
  if (state.date_from && document.getElementById('report-date-from'))
    document.getElementById('report-date-from').value = state.date_from;
  if (state.date_to && document.getElementById('report-date-to'))
    document.getElementById('report-date-to').value = state.date_to;
  // Stmt type
  document.querySelectorAll('input[name="report-stmt-type"]').forEach(r => {
    r.checked = r.value === (state.stmt_type || 'both');
  });
  _clearDatePresetHighlight();
}

// Report card ⋯ menu
function _toggleRcMenu(id, e) {
  e.stopPropagation();
  const existing = document.querySelector('.rc-dropdown');
  if (existing && existing.dataset.cardId === String(id)) { existing.remove(); return; }
  document.querySelectorAll('.rc-dropdown').forEach(d => d.remove());
  const card = e.target.closest('.report-card');
  if (!card) return;
  const dd = document.createElement('div');
  dd.className = 'rc-dropdown';
  dd.dataset.cardId = String(id);
  dd.innerHTML = card.dataset.menuHtml || '';
  card.appendChild(dd);
}
document.addEventListener('click', () => document.querySelectorAll('.rc-dropdown').forEach(d => d.remove()));

function toggleCustomReport() { /* kept for backward compat — builder is now always visible */ }
function addReportFilter() { /* kept for backward compat — replaced by chip system */ }
function onFilterAllChange() { /* no-op — filter rows removed */ }
function onReportStmtTypeChange() { /* no-op — read at run time */ }

const REPORT_COL_TOOLTIPS = {
  net_amount:   'Signed total: income minus spend. Positive means net income.',
  row_count:    'Number of transactions counted in this group.',
  total_spend:  'Sum of outflows (negative amounts), displayed as positive.',
  total_income: 'Sum of inflows (positive amounts) for this group.',
};

const REPORT_TEMPLATES = {
  'spend_by_month_category.csv': { group_by: ['transaction_date', 'category'], bucket: 'month',  filters: [] },
  'cashflow_by_month.csv':        { group_by: ['transaction_date'],             bucket: 'month',  filters: [] },
  'spend_by_merchant.csv':        { group_by: ['merchant'],                     bucket: null,     filters: [{ field: 'amount', op: '<=', value: '0' }] },
  'totals_by_account.csv':        { group_by: ['account_name'],                 bucket: null,     filters: [] },
  'top_merchants.csv':            { group_by: ['merchant'],                     bucket: null,     filters: [{ field: 'amount', op: '<=', value: '0' }] },
};

const REPORT_FIELD_LABELS = {
  transaction_date: 'Transaction Date', description: 'Description', merchant: 'Merchant',
  category: 'Category', amount: 'Amount', currency: 'Currency',
  bank_name: 'Bank', account_name: 'Account', account_id: 'Account ID',
};
const REPORT_OPS = ['=','contains','>=','<=','is_null','not_null','in','between'];

function toggleCustomReport() {
  const card = document.getElementById('custom-report-card');
  card.style.display = card.style.display === 'none' ? '' : 'none';
}

function onReportStmtTypeChange() {
  // no-op for now — stmt_type is read at run time from the radio
}

function _toggleSaveReportPanel() {
  const panel = document.getElementById('save-report-panel');
  if (!panel) return;
  const visible = panel.style.display !== 'none';
  panel.style.display = visible ? 'none' : '';
  if (!visible) {
    delete panel.dataset.editId;
    document.getElementById('save-report-name').value = '';
    document.getElementById('save-report-desc').value = '';
    document.getElementById('save-report-name').focus();
  }
}

async function _saveCustomReport() {
  const name = (document.getElementById('save-report-name')?.value || '').trim();
  const desc = (document.getElementById('save-report-desc')?.value || '').trim();
  if (!name) { toast('Report name is required.', 'error'); return; }
  const s = _getBuilderState();
  const panel  = document.getElementById('save-report-panel');
  const editId = panel?.dataset.editId;
  try {
    if (editId) {
      await api('PUT', `/saved-reports/${editId}`, { name, description: desc, ...s });
      toast('Report updated.', 'success');
    } else {
      await api('POST', '/saved-reports', { name, description: desc, ...s });
      toast(`Report "${name}" saved.`, 'success');
    }
    _toggleSaveReportPanel();
    loadSavedReports();
  } catch (err) { toast(`Failed: ${err.message}`, 'error'); }
}

async function runCustomReport() {
  const s = _getBuilderState();
  const resultsEl = document.getElementById('custom-report-results');
  resultsEl.style.display = '';
  document.getElementById('custom-report-body').innerHTML =
    '<tr><td colspan="99" class="text-center text-muted" style="padding:20px">Running…</td></tr>';
  document.getElementById('custom-report-foot').innerHTML = '';
  resultsEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

  try {
    const data = await api('POST', '/reports/query', {
      filters: s.filters, group_by: s.group_by, bucket: s.bucket,
      date_from: s.date_from, date_to: s.date_to, stmt_type: s.stmt_type, limit: 1000,
    });
    const cols = data.columns || (data.rows.length ? Object.keys(data.rows[0]) : []);
    document.getElementById('custom-report-meta').textContent =
      `${(data.count ?? data.rows.length).toLocaleString()} row(s)`;
    document.getElementById('custom-report-head').innerHTML =
      cols.map(c => {
        const tip = REPORT_COL_TOOLTIPS[c];
        if (!tip) return `<th>${esc(c)}</th>`;
        return `<th>${esc(c)} <a href="/metric-docs/${encodeURIComponent(c)}" target="_blank"
          title="${esc(tip)}" style="font-size:10px;opacity:.6;text-decoration:none;cursor:help;"
          onclick="event.stopPropagation()">ℹ</a></th>`;
      }).join('');
    document.getElementById('custom-report-body').innerHTML = data.rows.length
      ? data.rows.map(row =>
          `<tr>${cols.map(c => `<td>${esc(String(row[c] ?? ''))}</td>`).join('')}</tr>`
        ).join('')
      : '<tr><td colspan="99" class="text-center text-muted" style="padding:20px">No results.</td></tr>';
    _renderTotalsRow('custom-report-foot', cols, data.rows);
  } catch (err) {
    document.getElementById('custom-report-body').innerHTML =
      `<tr><td colspan="99" class="text-center text-muted">Error: ${esc(err.message)}</td></tr>`;
  }
}

async function downloadReportResults() {
  const s = _getBuilderState();
  try {
    toast('Preparing export…', 'info', 2000);
    const data = await api('POST', '/reports/query', { ...s, limit: 50000 });
    const cols = data.columns || (data.rows?.length ? Object.keys(data.rows[0]) : []);
    if (!cols.length || !data.rows?.length) { toast('No data to export.', 'info'); return; }
    const csvLines = [cols, ...data.rows.map(row => cols.map(c => row[c] ?? ''))].map(r =>
      r.map(v => `"${String(v).replace(/"/g, '""')}"`).join(',')
    );
    const blob = new Blob([csvLines.join('\r\n')], { type: 'text/csv' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href = url; a.download = `report_export_${new Date().toISOString().slice(0,10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    toast(`Exported ${data.rows.length.toLocaleString()} rows.`, 'success');
  } catch (err) { toast(`Export failed: ${err.message}`, 'error'); }
}

// ── Settings page ──────────────────────────────────────────────
async function loadSettings() {
  try {
    const data = await api('GET', '/settings');
    state.settings = data;
    document.getElementById('verbose-logs-toggle').checked = !!data.verbose_logs;
    document.getElementById('show-logs-toggle').checked = !!data.show_logs;
    document.getElementById('settings-status').textContent = 'Settings loaded';
    if (data.show_logs) {
      await refreshLogs();
      document.getElementById('logs-panel').style.display = 'block';
    } else {
      document.getElementById('logs-panel').style.display = 'none';
    }
  } catch (err) {
    document.getElementById('settings-status').textContent = `Failed to load settings: ${err.message}`;
  }
  // Load backup status and tags in parallel (non-blocking)
  loadBackupStatus();
  loadTags();
}

async function saveSettings() {
  const payload = {
    verbose_logs: document.getElementById('verbose-logs-toggle').checked,
    show_logs: document.getElementById('show-logs-toggle').checked,
  };
  try {
    const data = await api('PATCH', '/settings', payload);
    state.settings = data;
    document.getElementById('settings-status').textContent = 'Settings saved';
    toast('Settings saved', 'success', 1800);
    if (data.show_logs) {
      document.getElementById('logs-panel').style.display = 'block';
      await refreshLogs();
    } else {
      document.getElementById('logs-panel').style.display = 'none';
    }
  } catch (err) {
    document.getElementById('settings-status').textContent = `Save failed: ${err.message}`;
    toast(`Settings save failed: ${err.message}`, 'error');
  }
}

async function refreshLogs() {
  try {
    const data = await api('GET', '/logs?limit=200');
    document.getElementById('logs-file').textContent = data.file ? `Latest: ${data.file}` : 'No log file yet';
    document.getElementById('logs-output').textContent = data.lines && data.lines.length ? data.lines.join('\n') : 'No log lines yet.';
  } catch (err) {
    document.getElementById('logs-output').textContent = `Failed to load logs: ${err.message}`;
  }
}

async function maybeShowLogsOnError() {
  if (!state.settings.show_logs) return;
  // Navigate to Settings so the logs panel (which lives inside that section)
  // is actually visible to the user. Without this the panel would be inside
  // the inactive (hidden) Settings section while the user stays on Import.
  navigate('settings');
  document.getElementById('logs-panel').style.display = 'block';
  await refreshLogs();
}

// ── Recurring Transactions ─────────────────────────────────────

// ── Recurring — data cache & filter state ─────────────────────
let _recurringPatterns = [];   // full active list from last fetch
let _recurringFilterState = {
  query: '',
  frequency: null,   // null = all
  source: null,      // null | 'auto' | 'manual'
  sortCol: 'monthly_net',
  sortDir: 'desc',
};

// Canonical frequency set: weekly | biweekly | monthly | quarterly | annual | irregular
// Must stay in sync with VALID_FREQUENCIES in recurring.py and the pill filter list.
const _freqColors = {
  weekly: '#3b82f6', biweekly: '#6366f1', monthly: '#8b5cf6',
  quarterly: '#f59e0b', annual: '#22c55e', irregular: '#94a3b8',
};

// ── Load ──────────────────────────────────────────────────────

async function loadRecurringTransactions() {
  const statusEl = document.getElementById('recurring-status');
  const listEl   = document.getElementById('recurring-list');
  const totalEl  = document.getElementById('recurring-monthly-total');
  const countEl  = document.getElementById('recurring-count-label');

  if (statusEl) statusEl.textContent = 'Analyzing…';
  try {
    const data = await api('GET', '/recurring');
    if (statusEl) statusEl.textContent = '';

    _recurringPatterns = data.patterns || [];

    // Top-level KPI (net of reimbursements)
    totalEl.textContent = '$' + Number(data.monthly_total).toLocaleString(undefined,
      { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    countEl.textContent = `${data.count} recurring charge${data.count !== 1 ? 's' : ''} detected`;

    const passthroughEl = document.getElementById('recurring-passthrough-label');
    if (passthroughEl) {
      if (data.monthly_passthrough > 0) {
        const pt = Number(data.monthly_passthrough).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        passthroughEl.textContent = `+ $${pt}/mo pass-through (not your cost)`;
        passthroughEl.style.display = '';
      } else {
        passthroughEl.style.display = 'none';
      }
    }

    // Cost breakdown card
    _renderRecurringBreakdown(data.frequency_breakdown || {}, data.monthly_passthrough || 0);

    // Render with current filter state
    _applyRecurringFilters();

    // Paused section
    const pausedCard = document.getElementById('paused-recurring-card');
    const pausedList = document.getElementById('paused-recurring-list');
    if (pausedCard && pausedList) {
      if (data.paused && data.paused.length) {
        pausedCard.style.display = 'block';
        _renderPausedList(data.paused, pausedList);
      } else {
        pausedCard.style.display = 'none';
        pausedList.innerHTML = '';
      }
    }

    loadAnnualSuggestions();
  } catch (err) {
    if (statusEl) statusEl.textContent = `Error: ${err.message}`;
    const listEl2 = document.getElementById('recurring-list');
    if (listEl2) listEl2.innerHTML = `<p style="color:var(--danger);">Failed to load: ${esc(err.message)}</p>`;
  }
}

// ── Filter state setters ──────────────────────────────────────

function _onRecurringFilterChange() {
  _recurringFilterState.query = (document.getElementById('recurring-search')?.value || '').toLowerCase().trim();
  _applyRecurringFilters();
}

function _setRecurringFreqFilter(freq) {
  _recurringFilterState.frequency = freq;
  // Update pill active state
  ['all','weekly','biweekly','monthly','quarterly','annual','irregular'].forEach(f => {
    const el = document.getElementById(`rec-pill-${f}`);
    if (el) el.classList.toggle('rec-pill-active', (freq === null ? f === 'all' : f === freq));
  });
  _applyRecurringFilters();
}

function _setRecurringSourceFilter(src) {
  _recurringFilterState.source = src;
  ['all','auto','manual'].forEach(s => {
    const el = document.getElementById(`rec-pill-src-${s}`);
    if (el) el.classList.toggle('rec-pill-active', (src === null ? s === 'all' : s === src));
  });
  _applyRecurringFilters();
}

function _setRecurringSortCol(col) {
  if (_recurringFilterState.sortCol === col) {
    _recurringFilterState.sortDir = _recurringFilterState.sortDir === 'asc' ? 'desc' : 'asc';
  } else {
    _recurringFilterState.sortCol = col;
    _recurringFilterState.sortDir = 'desc';
  }
  _applyRecurringFilters();
}

// ── Core filter + render pipeline ────────────────────────────

function _applyRecurringFilters() {
  const { query, frequency, source, sortCol, sortDir } = _recurringFilterState;
  const listEl = document.getElementById('recurring-list');
  if (!listEl) return;

  let filtered = _recurringPatterns;

  if (frequency) {
    filtered = filtered.filter(p => p.frequency === frequency);
  }
  if (source === 'auto') {
    filtered = filtered.filter(p => p.is_auto);
  } else if (source === 'manual') {
    filtered = filtered.filter(p => !p.is_auto);
  }
  if (query) {
    filtered = filtered.filter(p => p.merchant.toLowerCase().includes(query));
  }

  // Sort — pass-through items always go to the bottom regardless of sort column
  filtered = [...filtered].sort((a, b) => {
    const aPass = a.reimbursement_type === 'full' ? 1 : 0;
    const bPass = b.reimbursement_type === 'full' ? 1 : 0;
    if (aPass !== bPass) return aPass - bPass;
    let av = a[sortCol] ?? 0;
    let bv = b[sortCol] ?? 0;
    if (typeof av === 'string') av = av.toLowerCase();
    if (typeof bv === 'string') bv = bv.toLowerCase();
    if (av < bv) return sortDir === 'asc' ? -1 : 1;
    if (av > bv) return sortDir === 'asc' ? 1 : -1;
    return 0;
  });

  // Update count label
  const countEl = document.getElementById('recurring-search-count');
  if (countEl) {
    const isFiltered = query || frequency || source;
    countEl.textContent = isFiltered ? `${filtered.length} of ${_recurringPatterns.length}` : '';
  }

  if (!filtered.length) {
    listEl.innerHTML = _recurringPatterns.length
      ? '<p style="color:var(--text-muted); padding:12px 0;">No charges match the current filters.</p>'
      : '<p style="color:var(--text-muted); padding:12px 0;">No recurring charges yet. Click <strong>+ Add Recurring</strong> to add one manually, or import transactions to auto-detect.</p>';
    return;
  }

  _renderRecurringList(filtered, listEl);
}

// ── Breakdown card ────────────────────────────────────────────

function _renderRecurringBreakdown(breakdown, monthlyPassthrough = 0) {
  const el = document.getElementById('recurring-breakdown');
  if (!el) return;
  const order = ['monthly', 'weekly', 'biweekly', 'quarterly', 'annual', 'irregular'];
  const fmt2 = n => '$' + Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const lines = order
    .filter(f => breakdown[f] > 0)
    .map(f => {
      const color = _freqColors[f] || '#94a3b8';
      return `<span style="display:inline-flex; align-items:center; gap:4px; margin-right:10px; margin-bottom:4px;">
        <span style="width:8px; height:8px; border-radius:50%; background:${color}; display:inline-block;"></span>
        <span style="font-weight:600;">${f.charAt(0).toUpperCase() + f.slice(1)}</span>
        <span style="color:var(--text);">${fmt2(breakdown[f])}/mo</span>
      </span>`;
    });
  if (monthlyPassthrough > 0) {
    lines.push(`<span style="display:inline-flex; align-items:center; gap:4px; margin-right:10px; margin-bottom:4px;">
      <span style="width:8px; height:8px; border-radius:50%; background:#0d9488; display:inline-block;"></span>
      <span style="font-weight:600; color:#0d9488;">Pass-through</span>
      <span style="color:var(--text-muted);">${fmt2(monthlyPassthrough)}/mo (not your cost)</span>
    </span>`);
  }
  el.innerHTML = lines.length ? `<div style="display:flex; flex-wrap:wrap;">${lines.join('')}</div>` : '<span style="color:var(--text-muted);">No data</span>';
}

// ── Table renderer ────────────────────────────────────────────

function _renderRecurringList(patterns, container) {
  const { sortCol, sortDir } = _recurringFilterState;
  const arrow = dir => `<span class="rec-sort-arrow">${dir === 'asc' ? '▲' : '▼'}</span>`;
  const th = (label, col) => {
    const active = sortCol === col;
    return `<th class="rec-th-sort" style="padding:8px 10px;" onclick="_setRecurringSortCol('${col}')">${label}${active ? arrow(sortDir) : '<span class="rec-sort-arrow" style="opacity:0.2;">⬍</span>'}</th>`;
  };

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  let html = '<table style="width:100%; border-collapse:collapse;">';
  html += `<thead><tr style="border-bottom:2px solid var(--border); text-align:left;">
    ${th('Merchant', 'merchant')}
    ${th('Amount', 'median_amount')}
    ${th('Mo. Net', 'monthly_net')}
    ${th('Frequency', 'frequency')}
    ${th('Last Charged', 'last_date')}
    ${th('Next Estimated', 'next_estimated')}
    ${th('Hits', 'occurrences')}
    <th style="padding:8px 10px;"></th>
  </tr></thead><tbody>`;

  for (let i = 0; i < patterns.length; i++) {
    const p = patterns[i];
    const color = _freqColors[p.frequency] || '#94a3b8';
    const sourceBadge = p.is_auto
      ? '<span style="font-size:10px; background:#e2e8f0; color:#64748b; padding:1px 6px; border-radius:3px; margin-left:6px;">auto</span>'
      : '<span style="font-size:10px; background:#dbeafe; color:#3b82f6; padding:1px 6px; border-radius:3px; margin-left:6px;">manual</span>';

    // Due-soon badge: next_estimated within 7 days
    let dueSoonBadge = '';
    if (p.next_estimated) {
      const nextDate = new Date(p.next_estimated + 'T00:00:00');
      const diffDays = Math.round((nextDate - today) / 86400000);
      if (diffDays >= 0 && diffDays <= 7) {
        const label = diffDays === 0 ? 'Due today' : `Due in ${diffDays}d`;
        dueSoonBadge = `<span class="rec-due-soon">${label}</span>`;
      }
    }

    const mKey  = p.merchant;
    const mEsc  = esc(mKey).replace(/'/g, "\\'");
    const menuId = `rec-menu-${i}`;
    const moNet = p.monthly_net != null ? '$' + Number(p.monthly_net).toFixed(2) : '—';

    // Reimbursement badge
    let reimbBadge = '';
    if (p.reimbursement_type === 'full') {
      reimbBadge = '<span style="font-size:10px; background:#ccfbf1; color:#0d9488; padding:1px 6px; border-radius:3px; margin-left:6px;">pass-through</span>';
    } else if (p.reimbursement_type === 'partial') {
      reimbBadge = '<span style="font-size:10px; background:#fef3c7; color:#d97706; padding:1px 6px; border-radius:3px; margin-left:6px;">partial</span>';
    }

    // Amount cell — two lines for reimbursed items
    let amountCell;
    if (p.reimbursement_type === 'full') {
      amountCell = `<div style="font-weight:600; font-variant-numeric:tabular-nums; color:var(--text-muted); text-decoration:line-through;">$${Number(p.median_amount).toFixed(2)}</div>
        <div style="font-size:11px; color:#0d9488;">Pass-through · $0.00</div>`;
    } else if (p.reimbursement_type === 'partial' && p.reimbursed_amount != null) {
      const yourShare = Math.max(0, p.median_amount - p.reimbursed_amount).toFixed(2);
      amountCell = `<div style="font-weight:600; font-variant-numeric:tabular-nums;">$${Number(p.median_amount).toFixed(2)}</div>
        <div style="font-size:11px; color:var(--text-muted);">Your share: $${yourShare}</div>`;
    } else {
      amountCell = `<div style="font-weight:600; font-variant-numeric:tabular-nums;">$${Number(p.median_amount).toFixed(2)}</div>`;
    }

    html += `<tr id="rec-row-${CSS.escape(mKey)}" style="border-bottom:1px solid var(--border); cursor:default;">
      <td style="padding:8px 10px; font-weight:500;">${esc(p.label || mKey)}${sourceBadge}${reimbBadge}${dueSoonBadge}</td>
      <td style="padding:8px 10px;">${amountCell}</td>
      <td style="padding:8px 10px; font-variant-numeric:tabular-nums; color:var(--text-muted);">${moNet}</td>
      <td style="padding:8px 10px;">
        <span style="background:${color}; color:#fff; font-size:11px; padding:2px 8px; border-radius:4px;">${esc(p.frequency)}</span>
      </td>
      <td style="padding:8px 10px;">${p.last_date ? esc(p.last_date) : '—'}</td>
      <td style="padding:8px 10px;">${p.next_estimated ? esc(p.next_estimated) : '—'}</td>
      <td style="padding:8px 10px; text-align:center;">${p.occurrences}</td>
      <td style="padding:8px 10px; position:relative;">
        <button class="btn btn-secondary btn-sm" style="font-size:14px; padding:2px 10px; line-height:1;"
          onclick="event.stopPropagation(); _toggleRecMenu('${menuId}')">&#x22EF;</button>
        <div id="${menuId}" style="display:none; position:absolute; right:10px; top:calc(100% - 4px); z-index:50;
          background:var(--card-bg,#fff); border:1px solid var(--border); border-radius:6px; box-shadow:0 4px 12px rgba(0,0,0,.12);
          min-width:120px; overflow:hidden;">
          <button style="display:block; width:100%; text-align:left; padding:8px 14px; font-size:12px; border:none;
            background:none; cursor:pointer; color:var(--text,#1e293b);"
            onmouseover="this.style.background='var(--bg-alt,#f1f5f9)'" onmouseout="this.style.background='none'"
            onclick="_toggleRecMenu('${menuId}'); _openRecEditPanel('${mEsc}')">Edit</button>
          <button style="display:block; width:100%; text-align:left; padding:8px 14px; font-size:12px; border:none;
            background:none; cursor:pointer; color:var(--text,#1e293b);"
            onmouseover="this.style.background='var(--bg-alt,#f1f5f9)'" onmouseout="this.style.background='none'"
            onclick="_toggleRecMenu('${menuId}'); pauseRecurringCharge('${mEsc}')">Pause</button>
          <button style="display:block; width:100%; text-align:left; padding:8px 14px; font-size:12px; border:none;
            background:none; cursor:pointer; color:var(--danger);"
            onmouseover="this.style.background='var(--bg-alt,#f1f5f9)'" onmouseout="this.style.background='none'"
            onclick="_toggleRecMenu('${menuId}'); deleteRecurringCharge('${mEsc}', ${p.is_auto})">Delete</button>
        </div>
      </td>
    </tr>`;
  }
  html += '</tbody></table>';
  container.innerHTML = html;
}

function _renderPausedList(patterns, container) {
  let html = '<table style="width:100%; border-collapse:collapse;">';
  html += `<thead><tr style="border-bottom:2px solid var(--border); text-align:left;">
    <th style="padding:8px 10px;">Merchant</th>
    <th style="padding:8px 10px;">Amount</th>
    <th style="padding:8px 10px;">Frequency</th>
    <th style="padding:8px 10px;"></th>
  </tr></thead><tbody>`;

  for (const p of patterns) {
    const color = _freqColors[p.frequency] || '#94a3b8';
    const mEsc = esc(p.merchant).replace(/'/g, "\\'");
    html += `<tr style="border-bottom:1px solid var(--border); opacity:0.7;">
      <td style="padding:8px 10px; font-weight:500;">${esc(p.merchant)}</td>
      <td style="padding:8px 10px; font-weight:600;">$${Number(p.median_amount).toFixed(2)}</td>
      <td style="padding:8px 10px;">
        <span style="background:${color}; color:#fff; font-size:11px; padding:2px 8px; border-radius:4px;">${esc(p.frequency)}</span>
      </td>
      <td style="padding:8px 10px;">
        <button class="btn btn-secondary btn-sm" style="font-size:11px; padding:2px 8px;"
          onclick="resumeRecurringCharge('${mEsc}')">Resume</button>
        <button class="btn btn-secondary btn-sm" style="font-size:11px; padding:2px 8px; color:var(--danger); margin-left:4px;"
          onclick="deleteRecurringCharge('${mEsc}', ${p.is_auto})">Delete</button>
      </td>
    </tr>`;
  }
  html += '</tbody></table>';
  container.innerHTML = html;
}

// ── Recurring Action Menu ─────────────────────────────────────

function _toggleRecMenu(menuId) {
  document.querySelectorAll('[id^="rec-menu-"]').forEach(el => {
    if (el.id !== menuId) el.style.display = 'none';
  });
  const menu = document.getElementById(menuId);
  if (menu) menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
}

document.addEventListener('click', function(e) {
  if (!e.target.closest('[id^="rec-menu-"]') && !e.target.closest('button')) {
    document.querySelectorAll('[id^="rec-menu-"]').forEach(el => el.style.display = 'none');
  }
});

// Legacy alias — kept so any external callers don't break
function filterRecurringCharges() { _onRecurringFilterChange(); }

// ── Recurring Edit Slide-Over Panel ──────────────────────────

let _recPanelMerchant = null;  // original merchant key for the open panel
let _recPanelIsAuto   = false;

function _openRecEditPanel(merchant) {
  const p = _recurringPatterns.find(x => x.merchant === merchant);
  if (!p) return;

  _recPanelMerchant = p.merchant;
  _recPanelIsAuto   = !!p.is_auto;

  // Populate panel fields
  document.getElementById('rec-panel-title').textContent    = p.label || p.merchant;
  document.getElementById('rec-panel-subtitle').textContent = p.is_auto ? 'Auto-detected' : 'Manually added';
  document.getElementById('rec-panel-label').value    = p.label || p.merchant;
  document.getElementById('rec-panel-amount').value   = p.median_amount != null ? p.median_amount : '';
  document.getElementById('rec-panel-lastdate').value = p.last_date || '';
  document.getElementById('rec-panel-nextest').value  = p.next_estimated || '';
  document.getElementById('rec-panel-notes').value    = p.notes || '';

  const freqEl = document.getElementById('rec-panel-freq');
  freqEl.value = p.frequency || 'monthly';
  _panelFreqChanged();  // disable next-est if irregular

  // Reimbursement fields
  const reimbType = p.reimbursement_type || 'none';
  const reimbRadio = document.getElementById(`rec-panel-reimb-${reimbType}`);
  if (reimbRadio) reimbRadio.checked = true;
  const reimbAmountEl = document.getElementById('rec-panel-reimb-amount');
  if (reimbAmountEl) reimbAmountEl.value = p.reimbursed_amount != null ? p.reimbursed_amount : '';
  _panelReimbChanged();

  // Pause button label
  document.getElementById('rec-panel-pause-btn').textContent = p.paused ? 'Resume' : 'Pause';

  // Reset danger zone
  document.getElementById('rec-panel-danger-confirm').style.display = 'none';
  document.getElementById('rec-panel-danger-delete-btn').style.display = '';

  // Highlight active row (rows are keyed by merchant)
  document.querySelectorAll('tr.rec-row-active').forEach(r => r.classList.remove('rec-row-active'));
  const row = document.getElementById(`rec-row-${CSS.escape(p.merchant)}`);
  if (row) row.classList.add('rec-row-active');

  // Show overlay + panel
  document.getElementById('rec-slideover-overlay').style.display = '';
  const panel = document.getElementById('rec-slideover');
  panel.style.transform = 'translateX(100%)';
  panel.offsetHeight; // force reflow
  panel.classList.add('open');
}

function _closeRecEditPanel() {
  const panel = document.getElementById('rec-slideover');
  panel.classList.remove('open');
  document.getElementById('rec-slideover-overlay').style.display = 'none';
  document.querySelectorAll('tr.rec-row-active').forEach(r => r.classList.remove('rec-row-active'));
  _recPanelMerchant = null;
}

function _panelFreqChanged() {
  const freq   = document.getElementById('rec-panel-freq')?.value;
  const nextEl = document.getElementById('rec-panel-nextest');
  if (nextEl) {
    if (freq === 'irregular') {
      nextEl.value = '';
      nextEl.disabled = true;
      nextEl.title = 'No predictable next date for irregular charges';
    } else {
      nextEl.disabled = false;
      nextEl.title = '';
    }
  }
  const freqLabel = document.getElementById('rec-panel-reimb-freq-label');
  if (freqLabel) freqLabel.textContent = `per ${freq || 'occurrence'}`;
}

function _panelReimbChanged() {
  const type = document.querySelector('input[name="rec-panel-reimb"]:checked')?.value;
  const row = document.getElementById('rec-panel-reimb-amount-row');
  if (row) row.style.display = type === 'partial' ? '' : 'none';
  const pauseBtn = document.getElementById('rec-panel-pause-btn');
  if (pauseBtn) {
    pauseBtn.disabled = type === 'full';
    pauseBtn.title = type === 'full' ? 'Not needed — net cost is already $0' : '';
  }
}

function _panelLastDateChanged() {
  const lastDate = document.getElementById('rec-panel-lastdate')?.value;
  const freq     = document.getElementById('rec-panel-freq')?.value || 'monthly';
  const nextEl   = document.getElementById('rec-panel-nextest');
  if (!nextEl || freq === 'irregular' || !lastDate) return;
  const freqDays = { weekly: 7, biweekly: 14, monthly: 30, quarterly: 90, annual: 365 };
  const d = new Date(lastDate + 'T00:00:00');
  d.setDate(d.getDate() + (freqDays[freq] || 30));
  nextEl.value = d.toISOString().split('T')[0];
}

async function _saveRecEditPanel() {
  if (!_recPanelMerchant) return;
  const label    = document.getElementById('rec-panel-label')?.value?.trim();
  const amtRaw   = document.getElementById('rec-panel-amount')?.value;
  const amount   = amtRaw !== '' ? parseFloat(amtRaw) : null;
  const frequency       = document.getElementById('rec-panel-freq')?.value || 'monthly';
  const last_date       = document.getElementById('rec-panel-lastdate')?.value || null;
  const next_estimated  = document.getElementById('rec-panel-nextest')?.value || null;

  const reimbTypeRaw   = document.querySelector('input[name="rec-panel-reimb"]:checked')?.value || 'none';
  const reimbAmtRaw    = document.getElementById('rec-panel-reimb-amount')?.value;
  const reimbursement_type   = reimbTypeRaw === 'none' ? null : reimbTypeRaw;
  const reimbursed_amount    = (reimbTypeRaw === 'partial' && reimbAmtRaw !== '')
    ? parseFloat(reimbAmtRaw) : null;

  if (!label) { toast('Label is required', 'error', 2000); return; }
  try {
    await api('POST', '/recurring/override', {
      merchant: _recPanelMerchant, is_recurring: true,
      label, amount: (amount !== null && !isNaN(amount)) ? amount : null,
      frequency, last_date, next_estimated,
      reimbursement_type,
      reimbursed_amount: (reimbursed_amount !== null && !isNaN(reimbursed_amount)) ? reimbursed_amount : null,
    });
    toast(`Updated "${label}"`, 'success', 2500);
    _closeRecEditPanel();
    loadRecurringTransactions();
  } catch (err) {
    toast(`Edit failed: ${err.message}`, 'error');
  }
}

async function _panelTogglePause() {
  if (!_recPanelMerchant) return;
  const btn = document.getElementById('rec-panel-pause-btn');
  const pausing = btn.textContent === 'Pause';
  try {
    await api('POST', '/recurring/override', { merchant: _recPanelMerchant, is_recurring: true, paused: pausing });
    toast(pausing ? `Paused "${_recPanelMerchant}"` : `Resumed "${_recPanelMerchant}"`, 'info', 2500);
    _closeRecEditPanel();
    loadRecurringTransactions();
  } catch (err) {
    toast(`Action failed: ${err.message}`, 'error');
  }
}

async function _confirmDeleteFromPanel() {
  if (!_recPanelMerchant) return;
  try {
    if (_recPanelIsAuto) {
      await api('POST', '/recurring/override', { merchant: _recPanelMerchant, is_recurring: false });
    } else {
      await api('DELETE', `/recurring/override/${encodeURIComponent(_recPanelMerchant)}`);
    }
    toast(`Removed "${_recPanelMerchant}" from recurring`, 'success', 2500);
    _closeRecEditPanel();
    loadRecurringTransactions();
  } catch (err) {
    toast(`Delete failed: ${err.message}`, 'error');
  }
}

// ── Add Recurring Modal ───────────────────────────────────────

function _openAddRecurringModal() {
  // Clear fields
  ['add-rec-merchant','add-rec-amount','add-rec-notes'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  document.getElementById('add-rec-lastdate').value = '';
  document.getElementById('add-rec-nextest').value  = '';
  document.getElementById('add-rec-freq').value     = 'monthly';
  document.getElementById('add-rec-nextest').disabled = false;
  document.getElementById('add-rec-nextest-hint').style.display = '';
  document.getElementById('add-rec-merchant-warn').style.display = 'none';

  // Populate merchant datalist from existing patterns (duplicate warning)
  const dl = document.getElementById('add-rec-merchant-suggestions');
  if (dl) {
    dl.innerHTML = _recurringPatterns.map(p => `<option value="${esc(p.merchant)}">`).join('');
  }

  // Wire duplicate warning
  const merchantInput = document.getElementById('add-rec-merchant');
  if (merchantInput) {
    merchantInput.oninput = () => {
      const val = merchantInput.value.trim().toLowerCase();
      const exists = _recurringPatterns.some(p => p.merchant.toLowerCase() === val);
      document.getElementById('add-rec-merchant-warn').style.display = exists ? '' : 'none';
    };
  }

  document.getElementById('add-recurring-modal').classList.remove('hidden');
  document.getElementById('add-rec-merchant').focus();
}

function _closeAddRecurringModal() {
  document.getElementById('add-recurring-modal').classList.add('hidden');
}

function _addRecFreqChanged() {
  const freq   = document.getElementById('add-rec-freq')?.value;
  const nextEl = document.getElementById('add-rec-nextest');
  const hint   = document.getElementById('add-rec-nextest-hint');
  if (!nextEl) return;
  if (freq === 'irregular') {
    nextEl.value = ''; nextEl.disabled = true;
    if (hint) hint.textContent = 'Not applicable for irregular charges';
  } else {
    nextEl.disabled = false;
    if (hint) hint.textContent = 'Auto-filled from last date + frequency';
    _addRecLastDateChanged();
  }
}

function _addRecLastDateChanged() {
  const lastDate = document.getElementById('add-rec-lastdate')?.value;
  const freq     = document.getElementById('add-rec-freq')?.value || 'monthly';
  const nextEl   = document.getElementById('add-rec-nextest');
  if (!nextEl || freq === 'irregular' || !lastDate) return;
  const freqDays = { weekly: 7, biweekly: 14, monthly: 30, quarterly: 90, annual: 365 };
  const d = new Date(lastDate + 'T00:00:00');
  d.setDate(d.getDate() + (freqDays[freq] || 30));
  nextEl.value = d.toISOString().split('T')[0];
}

async function _submitAddRecurring() {
  const merchant = document.getElementById('add-rec-merchant')?.value?.trim();
  if (!merchant) { toast('Merchant name is required', 'error', 2000); return; }

  const amtRaw  = document.getElementById('add-rec-amount')?.value;
  const amount  = amtRaw !== '' ? parseFloat(amtRaw) : null;
  const frequency      = document.getElementById('add-rec-freq')?.value || 'monthly';
  const last_date      = document.getElementById('add-rec-lastdate')?.value || null;
  const next_estimated = document.getElementById('add-rec-nextest')?.value || null;

  try {
    await api('POST', '/recurring/override', {
      merchant, is_recurring: true,
      label: merchant,
      amount: (amount !== null && !isNaN(amount)) ? amount : null,
      frequency, last_date, next_estimated,
    });
    toast(`Added "${merchant}" as recurring`, 'success', 2500);
    _closeAddRecurringModal();
    loadRecurringTransactions();
  } catch (err) {
    toast(`Failed to add: ${err.message}`, 'error');
  }
}

async function pauseRecurringCharge(merchant) {
  try {
    await api('POST', '/recurring/override', { merchant, is_recurring: true, paused: true });
    toast(`Paused "${merchant}"`, 'info', 2500);
    loadRecurringTransactions();
  } catch (err) {
    toast(`Pause failed: ${err.message}`, 'error');
  }
}

async function resumeRecurringCharge(merchant) {
  try {
    await api('POST', '/recurring/override', { merchant, is_recurring: true, paused: false });
    toast(`Resumed "${merchant}"`, 'success', 2500);
    loadRecurringTransactions();
  } catch (err) {
    toast(`Resume failed: ${err.message}`, 'error');
  }
}

async function deleteRecurringCharge(merchant, isAuto) {
  try {
    if (isAuto) {
      // Suppress auto-detected: create is_recurring=false override
      await api('POST', '/recurring/override', { merchant, is_recurring: false });
    } else {
      // Remove manual override entirely
      await api('DELETE', `/recurring/override/${encodeURIComponent(merchant)}`);
    }
    toast(`Removed "${merchant}" from recurring`, 'success', 2500);
    loadRecurringTransactions();
  } catch (err) {
    toast(`Delete failed: ${err.message}`, 'error');
  }
}

/** Legacy stub — replaced by _submitAddRecurring() modal. */
async function manualMarkRecurring() { _openAddRecurringModal(); }

// ── Annual Fee Suggestions ────────────────────────────────────

// Cache suggestions for edit form
let _annualSuggestions = [];

async function loadAnnualSuggestions() {
  const card = document.getElementById('annual-suggestions-card');
  const listEl = document.getElementById('annual-suggestions-list');
  const countEl = document.getElementById('annual-suggestions-count');
  if (!card || !listEl) return;

  try {
    const data = await api('GET', '/recurring/suggestions');
    _annualSuggestions = data.suggestions || [];

    // Always show card so Re-analyze / View Dismissed / View Deleted are accessible
    card.style.display = 'block';
    if (countEl) countEl.textContent = _annualSuggestions.length;

    if (!_annualSuggestions.length) {
      listEl.innerHTML = '<div style="color:var(--text-muted); font-size:12px;">No new suggestions found.</div>';
      return;
    }

    listEl.innerHTML = _annualSuggestions.map(s => {
      const cardFeeIcon = s.is_card_fee ? '<span style="margin-right:4px;">&#x1F4B3;</span>' : '';
      return `<div class="annual-suggestion-row" data-sid="${esc(s.suggestion_id)}" style="border:1px solid var(--border); border-radius:8px; padding:12px 16px;">
        <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:6px;">
          <div>
            <div style="font-weight:600; font-size:14px;">${cardFeeIcon}${esc(s.label)}</div>
            <div style="font-size:12px; color:var(--text-muted); margin-top:2px;">
              "${esc(s.description)}" &middot; ${esc(s.bank_name || '')} ${esc(s.account_name)} &middot; ${esc(s.last_date)}
            </div>
            ${s.next_estimated ? `<div style="font-size:11px; color:var(--text-muted); margin-top:2px;">Next estimated: ${esc(s.next_estimated)}</div>` : ''}
          </div>
          <div style="font-size:18px; font-weight:700; white-space:nowrap;">$${Number(s.amount).toFixed(2)}</div>
        </div>
        <div id="edit-form-${esc(s.suggestion_id)}" style="display:none; margin-top:10px; padding-top:10px; border-top:1px solid var(--border);">
          <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
            <label style="font-size:11px; color:var(--text-muted);">Label</label>
            <input type="text" id="edit-label-${esc(s.suggestion_id)}" value="${esc(s.label)}" style="font-size:12px; padding:4px 8px; border:1px solid var(--border); border-radius:4px; width:200px;" placeholder="Label" />
            <label style="font-size:11px; color:var(--text-muted);">Amount</label>
            <input type="number" id="edit-amount-${esc(s.suggestion_id)}" value="${s.amount}" step="0.01" style="font-size:12px; padding:4px 8px; border:1px solid var(--border); border-radius:4px; width:100px;" placeholder="Amount" />
            <label style="font-size:11px; color:var(--text-muted);">Frequency</label>
            <select id="edit-freq-${esc(s.suggestion_id)}" style="font-size:12px; padding:4px 8px; border:1px solid var(--border); border-radius:4px;"
              onchange="_recalcSuggestionNextEst('${esc(s.suggestion_id)}')">
              <option value="annual"${s.frequency === 'annual' ? ' selected' : ''}>Annual</option>
              <option value="quarterly"${s.frequency === 'quarterly' ? ' selected' : ''}>Quarterly</option>
              <option value="monthly"${s.frequency === 'monthly' ? ' selected' : ''}>Monthly</option>
              <option value="biweekly"${s.frequency === 'biweekly' ? ' selected' : ''}>Biweekly</option>
              <option value="weekly"${s.frequency === 'weekly' ? ' selected' : ''}>Weekly</option>
              <option value="irregular"${s.frequency === 'irregular' ? ' selected' : ''}>Irregular</option>
            </select>
            <label style="font-size:11px; color:var(--text-muted);">Last Charged</label>
            <input type="date" id="edit-lastdate-${esc(s.suggestion_id)}" value="${s.last_date || ''}" style="font-size:12px; padding:4px 8px; border:1px solid var(--border); border-radius:4px; width:140px;"
              onchange="_recalcSuggestionNextEst('${esc(s.suggestion_id)}')" />
            <label style="font-size:11px; color:var(--text-muted);">Next Estimated</label>
            <input type="date" id="edit-nextest-${esc(s.suggestion_id)}" value="${s.next_estimated || ''}" style="font-size:12px; padding:4px 8px; border:1px solid var(--border); border-radius:4px; width:140px;" />
            <button class="btn btn-primary btn-sm" style="font-size:11px;" onclick="submitEditSuggestion('${esc(s.suggestion_id)}')">Save</button>
            <button class="btn btn-secondary btn-sm" style="font-size:11px;" onclick="cancelEditSuggestion('${esc(s.suggestion_id)}')">Cancel</button>
          </div>
        </div>
        <div id="action-bar-${esc(s.suggestion_id)}" style="display:flex; gap:6px; margin-top:10px; justify-content:flex-end;">
          <button class="btn btn-primary btn-sm" style="font-size:11px;" onclick="acceptAnnualSuggestion('${esc(s.suggestion_id)}')">Accept</button>
          <button class="btn btn-secondary btn-sm" style="font-size:11px;" onclick="editAnnualSuggestion('${esc(s.suggestion_id)}')">Edit</button>
          <button class="btn btn-secondary btn-sm" style="font-size:11px; color:var(--text-muted);" onclick="dismissAnnualSuggestion('${esc(s.suggestion_id)}')">Dismiss</button>
        </div>
      </div>`;
    }).join('');
  } catch (err) {
    card.style.display = 'none';
  }
}

async function acceptAnnualSuggestion(sid) {
  const s = _annualSuggestions.find(x => x.suggestion_id === sid);
  if (!s) return;
  try {
    await api('POST', `/recurring/suggestions/${encodeURIComponent(sid)}/accept`, {
      label: s.label,
      amount: s.amount,
      frequency: s.frequency,
      last_date: s.last_date,
      next_estimated: s.next_estimated,
    });
    _removeAnnualSuggestionRow(sid);
    toast(`Added "${s.label}" to recurring charges`, 'success', 3000);
    loadRecurringTransactions();
  } catch (err) {
    toast(`Accept failed: ${err.message}`, 'error');
  }
}

function editAnnualSuggestion(sid) {
  const form = document.getElementById(`edit-form-${sid}`);
  const actions = document.getElementById(`action-bar-${sid}`);
  if (form) form.style.display = 'block';
  if (actions) actions.style.display = 'none';
}

function cancelEditSuggestion(sid) {
  const form = document.getElementById(`edit-form-${sid}`);
  const actions = document.getElementById(`action-bar-${sid}`);
  if (form) form.style.display = 'none';
  if (actions) actions.style.display = 'flex';
}

async function submitEditSuggestion(sid) {
  const label = document.getElementById(`edit-label-${sid}`)?.value?.trim();
  const amount = parseFloat(document.getElementById(`edit-amount-${sid}`)?.value);
  const frequency = document.getElementById(`edit-freq-${sid}`)?.value || 'annual';
  const last_date = document.getElementById(`edit-lastdate-${sid}`)?.value || null;
  const next_estimated = document.getElementById(`edit-nextest-${sid}`)?.value || null;

  if (!label) { toast('Label is required', 'error', 2000); return; }

  try {
    await api('POST', `/recurring/suggestions/${encodeURIComponent(sid)}/accept`, {
      label, amount: isNaN(amount) ? null : amount, frequency,
      last_date, next_estimated,
    });
    _removeAnnualSuggestionRow(sid);
    toast(`Added "${label}" to recurring charges`, 'success', 3000);
    loadRecurringTransactions();
  } catch (err) {
    toast(`Save failed: ${err.message}`, 'error');
  }
}

/** Recalculate Next Estimated in suggestion edit form from Last Charged + frequency. */
function _recalcSuggestionNextEst(sid) {
  const lastDate = document.getElementById(`edit-lastdate-${sid}`)?.value;
  const freq = document.getElementById(`edit-freq-${sid}`)?.value || 'annual';
  const nextEl = document.getElementById(`edit-nextest-${sid}`);
  if (!nextEl) return;
  if (freq === 'irregular') {
    nextEl.value = '';
    nextEl.disabled = true;
    nextEl.title = 'No predictable next date for irregular charges';
    return;
  }
  nextEl.disabled = false;
  nextEl.title = '';
  if (!lastDate) return;
  const freqDays = { weekly: 7, biweekly: 14, monthly: 30, quarterly: 90, annual: 365 };
  const days = freqDays[freq] || 365;
  const d = new Date(lastDate + 'T00:00:00');
  d.setDate(d.getDate() + days);
  nextEl.value = d.toISOString().split('T')[0];
}

/** Remove an annual suggestion row from DOM and update badge/card visibility. */
function _removeAnnualSuggestionRow(sid) {
  const row = document.querySelector(`.annual-suggestion-row[data-sid="${sid}"]`);
  if (row) row.remove();
  _annualSuggestions = _annualSuggestions.filter(s => s.suggestion_id !== sid);
  const countEl = document.getElementById('annual-suggestions-count');
  if (countEl) countEl.textContent = _annualSuggestions.length;
  if (!_annualSuggestions.length) {
    const card = document.getElementById('annual-suggestions-card');
    if (card) card.style.display = 'none';
  }
}

async function dismissAnnualSuggestion(sid) {
  try {
    await api('POST', `/recurring/suggestions/${encodeURIComponent(sid)}/dismiss`);
    _removeAnnualSuggestionRow(sid);
    toast('Suggestion dismissed', 'info', 2000);
  } catch (err) {
    toast(`Dismiss failed: ${err.message}`, 'error');
  }
}

async function reanalyzeAnnualSuggestions() {
  toast('Re-analyzing annual charges...', 'info', 2000);
  // Hide dismissed/deleted sections when re-analyzing
  const dismissedSection = document.getElementById('dismissed-suggestions-section');
  const deletedSection = document.getElementById('deleted-charges-section');
  if (dismissedSection) dismissedSection.style.display = 'none';
  if (deletedSection) deletedSection.style.display = 'none';
  await loadAnnualSuggestions();
}

async function viewDismissedSuggestions() {
  const section = document.getElementById('dismissed-suggestions-section');
  if (!section) return;
  if (section.style.display !== 'none') { section.style.display = 'none'; return; }
  try {
    const data = await api('GET', '/recurring/suggestions/dismissed');
    const items = data.items || [];
    const listEl = document.getElementById('dismissed-suggestions-list');
    if (!items.length) {
      listEl.innerHTML = '<div style="color:var(--text-muted); font-size:12px;">No dismissed suggestions.</div>';
    } else {
      listEl.innerHTML = items.map(s => `
        <div style="display:flex; justify-content:space-between; align-items:center; padding:8px 10px; background:var(--bg-alt,#f8faff); border-radius:6px; border:1px solid var(--border);">
          <div>
            <span style="font-weight:600; font-size:13px;">${esc(s.label)}</span>
            <span style="font-size:12px; color:var(--text-muted); margin-left:8px;">$${Number(s.amount).toFixed(2)} / ${esc(s.frequency || 'annual')}</span>
          </div>
          <button class="btn btn-secondary btn-sm" style="font-size:11px;" onclick="undoDismissSuggestion('${esc(s.suggestion_id)}')">Undo</button>
        </div>`).join('');
    }
    section.style.display = 'block';
  } catch (err) {
    toast(`Failed to load dismissed: ${err.message}`, 'error');
  }
}

async function undoDismissSuggestion(sid) {
  try {
    await api('POST', `/recurring/suggestions/dismissed/${encodeURIComponent(sid)}/undo`);
    toast('Suggestion restored', 'success', 2000);
    viewDismissedSuggestions();
    loadAnnualSuggestions();
  } catch (err) {
    toast(`Undo failed: ${err.message}`, 'error');
  }
}

async function viewDeletedCharges() {
  const section = document.getElementById('deleted-charges-section');
  if (!section) return;
  if (section.style.display !== 'none') { section.style.display = 'none'; return; }
  try {
    const data = await api('GET', '/recurring/deleted');
    const items = data.items || [];
    const listEl = document.getElementById('deleted-charges-list');
    if (!items.length) {
      listEl.innerHTML = '<div style="color:var(--text-muted); font-size:12px;">No deleted charges.</div>';
    } else {
      listEl.innerHTML = items.map(d => `
        <div style="display:flex; justify-content:space-between; align-items:center; padding:8px 10px; background:var(--bg-alt,#f8faff); border-radius:6px; border:1px solid var(--border);">
          <div>
            <span style="font-weight:600; font-size:13px;">${esc(d.merchant)}</span>
            <span style="font-size:11px; color:var(--text-muted); margin-left:8px;">deleted ${esc(d.deleted_at || '')}</span>
          </div>
          <button class="btn btn-secondary btn-sm" style="font-size:11px;" onclick="restoreDeletedCharge('${esc(d.merchant)}')">Restore</button>
        </div>`).join('');
    }
    section.style.display = 'block';
  } catch (err) {
    toast(`Failed to load deleted: ${err.message}`, 'error');
  }
}

async function restoreDeletedCharge(merchant) {
  try {
    await api('POST', `/recurring/deleted/${encodeURIComponent(merchant)}/restore`);
    toast(`Restored "${merchant}"`, 'success', 2000);
    // Re-toggle the deleted section to refresh
    const section = document.getElementById('deleted-charges-section');
    if (section) section.style.display = 'none';
    viewDeletedCharges();
    loadRecurringTransactions();
  } catch (err) {
    toast(`Restore failed: ${err.message}`, 'error');
  }
}

// ── Backup & Restore (v2) ─────────────────────────────────────

// Pending restore file — set by previewBackup(), consumed by confirmRestore()
let _pendingRestoreFile = null;

async function downloadBackup() {
  const statusEl = document.getElementById('backup-export-status');
  const container = document.getElementById('export-progress-container');
  const fill = document.getElementById('export-progress-fill');
  const pctEl = document.getElementById('export-progress-pct');
  const labelEl = document.getElementById('export-progress-label');

  // Show progress bar
  if (container) container.style.display = 'block';
  if (fill) { fill.className = 'progress-bar-fill'; fill.style.width = '0%'; }
  if (pctEl) pctEl.textContent = '0%';
  if (labelEl) labelEl.textContent = 'Preparing export…';
  if (statusEl) statusEl.textContent = '';

  // Simulated progress
  let pct = 0;
  const progressInterval = setInterval(() => {
    if (pct < 30) pct += 5;
    else if (pct < 60) pct += 2;
    else if (pct < 85) pct += 0.5;
    if (fill) fill.style.width = `${Math.round(pct)}%`;
    if (pctEl) pctEl.textContent = `${Math.round(pct)}%`;
  }, 150);

  try {
    const resp = await fetch('/backup/export');
    clearInterval(progressInterval);
    if (!resp.ok) throw new Error(resp.statusText);

    const blob = await resp.blob();
    const cd = resp.headers.get('content-disposition') || '';
    const nameMatch = cd.match(/filename="?([^";\n]+)"?/);
    const filename = nameMatch ? nameMatch[1] : 'spendly-backup.json';

    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    // Success
    if (fill) { fill.style.width = '100%'; fill.classList.add('success'); }
    if (pctEl) pctEl.textContent = '100%';
    if (labelEl) labelEl.textContent = 'Download complete';
    toast('Backup downloaded.', 'success', 3000);
  } catch (err) {
    clearInterval(progressInterval);
    if (fill) { fill.style.width = '100%'; fill.classList.add('error'); }
    if (pctEl) pctEl.textContent = 'Failed';
    if (labelEl) labelEl.textContent = 'Export failed';
    toast(`Export failed: ${err.message}`, 'error');
  } finally {
    setTimeout(() => { if (container) container.style.display = 'none'; }, 6000);
  }
}

/** Read the selected file and show a preview modal before restoring. */
async function previewBackup(input) {
  const statusEl = document.getElementById('backup-restore-status');
  const file = input.files[0];
  if (!file) return;
  if (statusEl) statusEl.textContent = '';

  // Parse the file locally to show a preview
  try {
    const text = await file.text();
    const payload = JSON.parse(text);
    const ver = payload.backup_version || '?';
    const data = payload.data || payload;  // v1 has flat keys, v2 has .data wrapper
    const isV2 = ver >= 2;

    let html = '<div class="restore-modal-meta">';
    html += `<p><span style="color:var(--text-muted);">Backup version</span> <strong>${esc(String(ver))}</strong></p>`;
    if (payload.created_at) html += `<p><span style="color:var(--text-muted);">Created</span> <strong>${esc(payload.created_at)}</strong></p>`;
    if (payload.app_version) html += `<p><span style="color:var(--text-muted);">App version</span> <strong>${esc(payload.app_version)}</strong></p>`;
    html += '</div>';

    html += '<table>';
    html += '<tr><th style="text-align:left;">Table</th><th style="text-align:right;">Rows</th></tr>';

    // Count rows in the backup for each table
    const tables = isV2
      ? ['runs','merchant_rules','merchant_category_map','category_rules','budget_goals','normalization_jobs','transactions_stage','transactions_norm']
      : ['merchant_rules','merchant_categories','category_rules','budget_goals','transactions'];
    for (const t of tables) {
      const arr = (isV2 ? data[t] : payload[t]) || [];
      const cnt = Array.isArray(arr) ? arr.length : '?';
      const cls = cnt === 0 ? ' class="zero-row"' : '';
      html += `<tr${cls}><td>${esc(t)}</td><td style="text-align:right;">${cnt}</td></tr>`;
    }
    html += '</table>';

    // Wizard profiles count
    const wp = payload.wizard_profiles;
    if (wp && typeof wp === 'object') {
      html += `<p style="margin-top:10px; font-size:13px;"><span style="color:var(--text-muted);">Wizard profiles</span> <strong>${Object.keys(wp).length}</strong></p>`;
    }

    html += '<div class="restore-warning-box">This will replace ALL existing data. A snapshot will be saved automatically.</div>';

    document.getElementById('restore-preview-body').innerHTML = html;
    document.getElementById('restore-preview-modal').style.display = 'flex';
    _pendingRestoreFile = file;
  } catch (err) {
    if (statusEl) statusEl.textContent = `Invalid backup file: ${err.message}`;
    input.value = '';
  }
}

function cancelRestore() {
  document.getElementById('restore-preview-modal').style.display = 'none';
  document.getElementById('restore-file-input').value = '';
  _pendingRestoreFile = null;
}

/** Send the pending file to the restore endpoint after user confirmation. */
async function confirmRestore() {
  document.getElementById('restore-preview-modal').style.display = 'none';
  const statusEl = document.getElementById('backup-restore-status');
  if (!_pendingRestoreFile) return;

  // Show progress bar
  const container = document.getElementById('restore-progress-container');
  const fill = document.getElementById('restore-progress-fill');
  const pctEl = document.getElementById('restore-progress-pct');
  const labelEl = document.getElementById('restore-progress-label');
  if (container) container.style.display = 'block';
  if (fill) { fill.className = 'progress-bar-fill'; fill.style.width = '0%'; }
  if (pctEl) pctEl.textContent = '0%';
  if (labelEl) labelEl.textContent = 'Restoring…';
  if (statusEl) statusEl.textContent = '';

  // Simulated progress: fast to 30%, medium to 60%, slow to 85%, then stall
  let pct = 0;
  const progressInterval = setInterval(() => {
    if (pct < 30) pct += 3;
    else if (pct < 60) pct += 1.5;
    else if (pct < 85) pct += 0.5;
    if (fill) fill.style.width = `${Math.round(pct)}%`;
    if (pctEl) pctEl.textContent = `${Math.round(pct)}%`;
  }, 200);

  const formData = new FormData();
  formData.append('file', _pendingRestoreFile);
  try {
    const resp = await fetch('/backup/restore', { method: 'POST', body: formData });
    clearInterval(progressInterval);
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || resp.statusText);

    // Success — fill to 100% green
    if (fill) { fill.style.width = '100%'; fill.classList.add('success'); }
    if (pctEl) pctEl.textContent = '100%';
    if (labelEl) labelEl.textContent = 'Restore complete';

    const parts = [];
    if (data.merchant_rules_restored) parts.push(`${data.merchant_rules_restored} merchant rules`);
    if (data.category_rules_restored) parts.push(`${data.category_rules_restored} category rules`);
    if (data.budget_goals_restored) parts.push(`${data.budget_goals_restored} budget goals`);
    if (data.transactions_norm_restored) parts.push(`${data.transactions_norm_restored} transactions`);
    if (data.runs_restored) parts.push(`${data.runs_restored} runs`);
    if (data.nw_accounts_restored) parts.push(`${data.nw_accounts_restored} net worth accounts`);
    if (data.nw_snapshots_restored) parts.push(`${data.nw_snapshots_restored} net worth snapshots`);
    if (data.annual_reports_restored) parts.push(`${data.annual_reports_restored} annual reports`);
    if (data.wizard_profiles_restored) parts.push(`${data.wizard_profiles_restored} wizard profiles`);
    if (statusEl) statusEl.textContent = `Restored: ${parts.join(', ')}.`;
    toast('Backup restored successfully.', 'success', 6000);
    loadBackupStatus();
  } catch (err) {
    clearInterval(progressInterval);
    if (fill) { fill.style.width = '100%'; fill.classList.add('error'); }
    if (pctEl) pctEl.textContent = 'Failed';
    if (labelEl) labelEl.textContent = 'Restore failed';
    if (statusEl) statusEl.textContent = `Error: ${err.message}`;
    toast(`Restore failed: ${err.message}`, 'error');
  } finally {
    document.getElementById('restore-file-input').value = '';
    _pendingRestoreFile = null;
    // Hide progress bar after 8 seconds
    setTimeout(() => { if (container) container.style.display = 'none'; }, 8000);
  }
}

/** Fetch /backup/status and populate the info section on the Settings page. */
async function loadBackupStatus() {
  try {
    const data = await api('GET', '/backup/status');

    // Last export info
    const infoEl = document.getElementById('backup-info');
    const lastEl = document.getElementById('backup-last-export');
    const autoEl = document.getElementById('backup-auto-count');
    if (data.last_export_at) {
      lastEl.textContent = `Last auto-backup: ${new Date(data.last_export_at).toLocaleString()}`;
      infoEl.style.display = 'block';
    }
    if (data.auto_backups && data.auto_backups.length) {
      autoEl.textContent = `(${data.auto_backups.length} auto-backup${data.auto_backups.length > 1 ? 's' : ''} saved)`;
      infoEl.style.display = 'block';
    }

    // DB table counts grid
    if (data.db_table_counts && Object.keys(data.db_table_counts).length) {
      const grid = document.getElementById('backup-counts-grid');
      grid.innerHTML = '';
      for (const [table, count] of Object.entries(data.db_table_counts)) {
        grid.innerHTML += `<div style="background:var(--bg); padding:4px 8px; border-radius:4px;">${esc(table)}: <strong>${count}</strong></div>`;
      }
      document.getElementById('backup-table-counts').style.display = 'block';
    }
  } catch (err) {
    // Non-fatal — backup status is informational
  }
}

// ── Tag Management ────────────────────────────────────────────

let _allTags = [];  // cached tag list [{id, name, color, ...}]
let _editingTagId = null;

async function loadTags() {
  try {
    const data = await api('GET', '/tags');
    _allTags = data.tags || [];
    _renderTagsList();
    _populateTagDropdowns();
    loadTagTotals();
  } catch (err) {
    console.error('Failed to load tags:', err.message);
  }
}

function _renderTagsList() {
  const el = document.getElementById('tags-list');
  if (!el) return;
  if (!_allTags.length) {
    el.innerHTML = '<span class="text-muted" style="font-size:13px;">No tags created yet.</span>';
    return;
  }
  el.innerHTML = _allTags.map(t => `
    <span class="tag-badge" style="background:${esc(t.color)}20; color:${esc(t.color)}; border:1px solid ${esc(t.color)}60;">
      <span class="tag-dot" style="background:${esc(t.color)};"></span>
      ${esc(t.name)}
      <button class="tag-edit-btn" onclick="_editTag(${t.id})" title="Edit">\u270E</button>
      <button class="tag-del-btn" onclick="deleteTag(${t.id})" title="Delete">&times;</button>
    </span>
  `).join('');
}

function _populateTagDropdowns() {
  ['cc-tag', 'bk-tag'].forEach(id => {
    const sel = document.getElementById(id);
    if (!sel) return;
    const current = sel.value;
    sel.innerHTML = '<option value="">All Tags</option>' +
      _allTags.map(t => `<option value="${t.id}">${esc(t.name)}</option>`).join('');
    sel.value = current;  // preserve selection
  });
}

function openTagForm() {
  _editingTagId = null;
  document.getElementById('tf-name').value = '';
  document.getElementById('tf-color').value = '#3b82f6';
  document.getElementById('tag-form').style.display = 'block';
  document.getElementById('tf-name').focus();
}

function _editTag(id) {
  const tag = _allTags.find(t => t.id === id);
  if (!tag) return;
  _editingTagId = id;
  document.getElementById('tf-name').value = tag.name;
  document.getElementById('tf-color').value = tag.color;
  document.getElementById('tag-form').style.display = 'block';
  document.getElementById('tf-name').focus();
}

function closeTagForm() {
  document.getElementById('tag-form').style.display = 'none';
  _editingTagId = null;
}

async function saveTag() {
  const name = document.getElementById('tf-name').value.trim();
  const color = document.getElementById('tf-color').value;
  if (!name) { toast('Tag name is required', 'error'); return; }
  try {
    if (_editingTagId) {
      await api('PUT', `/tags/${_editingTagId}`, { name, color });
      toast('Tag updated', 'success');
    } else {
      await api('POST', '/tags', { name, color });
      toast('Tag created', 'success');
    }
    closeTagForm();
    await loadTags();
  } catch (err) {
    toast('Failed to save tag: ' + err.message, 'error');
  }
}

async function deleteTag(id) {
  if (!confirm('Delete this tag? It will be removed from all transactions.')) return;
  try {
    await api('DELETE', `/tags/${id}`);
    toast('Tag deleted', 'success');
    await loadTags();
  } catch (err) {
    toast('Failed to delete tag: ' + err.message, 'error');
  }
}

async function loadTagTotals() {
  const panel = document.getElementById('tag-totals-panel');
  const list = document.getElementById('tag-totals-list');
  if (!panel || !list) return;
  try {
    const data = await api('GET', '/tags/totals');
    const totals = data.totals || [];
    if (!totals.length) { panel.style.display = 'none'; return; }
    panel.style.display = 'block';
    list.innerHTML = totals.map(t => `
      <div style="display:flex; justify-content:space-between; align-items:center; padding:4px 8px; background:var(--bg-alt,#f8f9fa); border-radius:4px;">
        <span>
          <span class="tag-dot" style="background:${esc(t.color || '#3b82f6')};"></span>
          ${esc(t.name)}
          <span class="text-muted" style="font-size:11px;">(${t.transaction_count} txns)</span>
        </span>
        <span class="mono" style="font-size:13px;">${Number(t.total_amount || 0).toLocaleString('en-US', {style:'currency',currency:'USD'})}</span>
      </div>
    `).join('');
  } catch (err) {
    panel.style.display = 'none';
  }
}

// ── Tag Popup (assign/remove tags on a transaction) ───────────

let _tagPopupFp = null;

function openTagPopup(fingerprint) {
  _tagPopupFp = fingerprint;
  // Remove any existing popup
  const old = document.getElementById('tag-popup');
  if (old) old.remove();

  const popup = document.createElement('div');
  popup.id = 'tag-popup';
  popup.className = 'tag-popup-overlay';
  popup.innerHTML = `
    <div class="tag-popup-box">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
        <strong style="font-size:13px;">Assign Tags</strong>
        <button onclick="closeTagPopup()" style="background:none; border:none; cursor:pointer; font-size:16px; color:var(--text-muted);">&times;</button>
      </div>
      <div id="tag-popup-list" style="display:flex; flex-direction:column; gap:4px; max-height:200px; overflow-y:auto;">
        Loading...
      </div>
    </div>
  `;
  document.body.appendChild(popup);
  popup.addEventListener('click', e => { if (e.target === popup) closeTagPopup(); });
  _loadTagPopupState(fingerprint);
}

async function _loadTagPopupState(fingerprint) {
  const list = document.getElementById('tag-popup-list');
  if (!list) return;
  try {
    const data = await api('GET', `/transactions/${encodeURIComponent(fingerprint)}/tags`);
    const assigned = new Set((data.tags || []).map(t => t.id));
    if (!_allTags.length) {
      list.innerHTML = '<span class="text-muted" style="font-size:12px;">No tags created. Go to Settings to add tags.</span>';
      return;
    }
    list.innerHTML = _allTags.map(t => {
      const checked = assigned.has(t.id) ? 'checked' : '';
      return `<label style="display:flex; align-items:center; gap:6px; padding:4px 6px; border-radius:4px; cursor:pointer; font-size:13px;" onmouseover="this.style.background='var(--bg)'" onmouseout="this.style.background=''">
        <input type="checkbox" ${checked} onchange="_toggleTag('${esc(fingerprint)}', ${t.id}, this.checked)" style="accent-color:${esc(t.color)};">
        <span class="tag-dot" style="background:${esc(t.color)};"></span>
        ${esc(t.name)}
      </label>`;
    }).join('');
  } catch (err) {
    list.innerHTML = '<span class="text-muted">Failed to load tags</span>';
  }
}

async function _toggleTag(fingerprint, tagId, add) {
  try {
    if (add) {
      await api('POST', '/transactions/tags', { fingerprint: fingerprint, tag_ids: [tagId] });
    } else {
      await api('DELETE', `/transactions/tags?fingerprint=${encodeURIComponent(fingerprint)}&tag_id=${tagId}`);
    }
    _loadTagChips(fingerprint);
  } catch (err) {
    toast('Failed to update tag: ' + err.message, 'error');
  }
}

function closeTagPopup() {
  const el = document.getElementById('tag-popup');
  if (el) el.remove();
  _tagPopupFp = null;
}

// ── Tag Chips (inline per-row display) ────────────────────────

async function _loadTagChips(fingerprint) {
  const el = document.getElementById(`tags-${fingerprint}`);
  if (!el) return;
  try {
    const data = await api('GET', `/transactions/${encodeURIComponent(fingerprint)}/tags`);
    const tags = data.tags || [];
    el.innerHTML = tags.map(t =>
      `<span class="tag-chip" style="background:${esc(t.color)}20; color:${esc(t.color)}; border-color:${esc(t.color)}60;">${esc(t.name)}</span>`
    ).join('');
  } catch {
    // non-critical
  }
}

function _loadVisibleTagChips() {
  document.querySelectorAll('.tag-chips').forEach(el => {
    const id = el.id;  // "tags-<fingerprint>"
    if (!id || !id.startsWith('tags-')) return;
    const fp = id.substring(5);
    if (fp) _loadTagChips(fp);
  });
}

// ── Utilities ─────────────────────────────────────────────────
function esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Boot ───────────────────────────────────────────────────────
(async function loadVersion() {
  try {
    const r = await api('GET', '/version');
    const el = document.getElementById('sidebar-version');
    if (el && r.version) el.textContent = 'v' + r.version;
  } catch (_) { /* ignore */ }
})();
loadSettings();
_loadTxnYears();
loadDashboard();
refreshUnreviewedBadge();
restoreCollapseState();
// FIX 3: ensure custom-headers checkbox is always checked on page load
(function() {
  const tog = document.getElementById('custom-headers-toggle');
  if (tog) tog.checked = true;
})();

// ═══════════════════════════════════════════════════════════════
//  MAPPING WIZARD
// ═══════════════════════════════════════════════════════════════

const wizard = {
  step:                 1,        // current step (1-3)
  files:                [],       // [{filename, path, size, headers, ...}] — one per upload
  headers:              [],       // union of headers from all uploaded files
  suggestions:          {},       // {canonical_field: csv_header}
  matchedProfile:       null,     // matched profile summary or null
  canonicalFields:      [],       // ordered list from /wizard/detect
  canonicalLabels:      {},       // {field: label}
  mapping:              {},       // {canonical_field: selected_csv_header}
  suggestedDateFormat:  null,     // server-inferred date format hint (e.g. '%m/%d/%Y')
  includeCustomHeaders: false,    // whether "Include custom headers" checkbox is ticked
  customHeadersSelected: [],      // CSV headers user has checked for custom persistence
  // CC transaction model
  statementType:        null,     // 'credit_card' | 'bank' | null — now set in step 1
  ccFormat:             null,     // 'two_col' | 'single_col' | null (from upload response)
  bankFormat:           null,     // 'two_col' | 'single_col' | null (from upload response)
  ccPolarity:           null,     // 'format_a' | 'format_b' | null (user confirmed in step 1)
};

// Required canonical fields for UI validation hints
const WIZARD_REQUIRED_FIELDS = new Set(['transaction_date']);

// CC amount groups — scoped to credit_card statement_type
const WIZARD_CC_AMOUNT_GROUPS = [
  ['cc_charge', 'cc_payment'],  // Format C — two-column
  ['cc_amount'],                // Format A / B — single column
];

// Bank amount groups
const WIZARD_BANK_AMOUNT_GROUPS = [
  ['bank_debit', 'bank_credit'],
  ['bank_amount'],
  ['debit_amount', 'credit_amount'],
  ['money_in', 'money_out'],
];

const WIZARD_AMOUNT_GROUPS = [...WIZARD_CC_AMOUNT_GROUPS, ...WIZARD_BANK_AMOUNT_GROUPS];

// Map from each amount field → its group index in WIZARD_AMOUNT_GROUPS
const FIELD_TO_AMOUNT_GROUP = {};
WIZARD_AMOUNT_GROUPS.forEach((grp, idx) => grp.forEach(f => { FIELD_TO_AMOUNT_GROUP[f] = idx; }));

// ── Open / Close ─────────────────────────────────────────────

function wizardOpen(uploadInfo) {
  // uploadInfo: response from POST /upload (extended with headers etc.)
  wizard.files.push(uploadInfo);

  // Union headers across all uploaded files
  const allHeaders = new Set(wizard.headers);
  (uploadInfo.headers || []).forEach(h => allHeaders.add(h));
  wizard.headers = [...allHeaders];

  // Merge suggestions — use first file's suggestions if not yet set
  if (uploadInfo.suggestions) {
    for (const [field, hdr] of Object.entries(uploadInfo.suggestions)) {
      if (hdr && !wizard.suggestions[field]) {
        wizard.suggestions[field] = hdr;
      }
    }
  }

  // Keep best matched profile
  const mp = uploadInfo.matched_profile;
  if (mp && mp.score > (wizard.matchedProfile?.score || 0)) {
    wizard.matchedProfile = mp;
    // Overlay profile's suggested_mapping on top of keyword suggestions
    if (mp.suggested_mapping) {
      for (const [field, hdr] of Object.entries(mp.suggested_mapping)) {
        if (hdr) wizard.suggestions[field] = hdr;
      }
    }
  }

  // Capture the server-inferred date format hint (first file wins)
  if (uploadInfo.suggested_date_format && !wizard.suggestedDateFormat) {
    wizard.suggestedDateFormat = uploadInfo.suggested_date_format;
  }

  // Capture format detections from the upload response (first file wins)
  if (uploadInfo.cc_format && !wizard.ccFormat) {
    wizard.ccFormat = uploadInfo.cc_format;
  }
  if (uploadInfo.bank_format && !wizard.bankFormat) {
    wizard.bankFormat = uploadInfo.bank_format;
  }

  // FIX 3: custom-headers is always on — always include custom headers
  // Ensure the checkbox is also visually checked
  const _tog = document.getElementById('custom-headers-toggle');
  if (_tog) _tog.checked = true;
  wizard.includeCustomHeaders = true;
  const profCustom = uploadInfo.matched_profile?.custom_headers || [];
  if (profCustom.length) {
    const seen = new Set(wizard.customHeadersSelected.map(h => h.toLowerCase()));
    profCustom.forEach(h => { if (!seen.has(h.toLowerCase())) { wizard.customHeadersSelected.push(h); seen.add(h.toLowerCase()); } });
  }

  // Initialize mapping from suggestions
  wizard.mapping = { ...wizard.suggestions };

  wizardGoTo(1);
  document.getElementById('wizard-overlay').classList.remove('hidden');
}

function wizardClose() {
  document.getElementById('wizard-overlay').classList.add('hidden');
  // Re-enable main preview toggle (wizard step 3 may have locked it)
  const mainTog = document.getElementById('preview-toggle');
  if (mainTog) mainTog.disabled = false;
  // Clear the date-format input so the next session always starts with a
  // fresh server-detected value.  Without this, setVal() (which guards on
  // !el.value) would preserve a stale format from the previous run and the
  // auto-detected format for the new file would never be applied — even when
  // a profile is auto-matched.
  const dfEl = document.getElementById('w-date-format');
  if (dfEl) dfEl.value = '';
  // FIX 2: clear all upload session state so the user starts fresh on next open
  _clearImportSession();
  // Reset wizard state for next session
  wizard.files               = [];
  wizard.headers             = [];
  wizard.suggestions         = {};
  wizard.matchedProfile      = null;
  wizard.mapping             = {};
  wizard.canonicalFields     = [];
  wizard.canonicalLabels     = {};
  wizard.suggestedDateFormat = null;
  // FIX 3: always reset to true so next wizard open shows custom-headers panel
  wizard.includeCustomHeaders  = true;
  wizard.customHeadersSelected = [];
  // FIX 3: keep the checkbox checked for the next upload
  const tog = document.getElementById('custom-headers-toggle');
  if (tog) tog.checked = true;
  // CC model
  wizard.statementType = null;
  wizard.ccFormat      = null;
  wizard.bankFormat    = null;
  wizard.ccPolarity    = null;
}

// ── Navigation ────────────────────────────────────────────────

function wizardGoTo(step) {
  wizard.step = step;

  // Update step indicators
  ['1','2','3'].forEach(n => {
    const ind = document.getElementById(`wstep-ind-${n}`);
    ind.classList.remove('active', 'done');
    if (+n < step)  ind.classList.add('done');
    if (+n === step) ind.classList.add('active');
  });

  // Show correct panel
  document.querySelectorAll('.wm-panel').forEach(p => p.classList.remove('active'));
  document.getElementById(`wstep-${step}`).classList.add('active');

  // Back button
  document.getElementById('w-btn-back').style.display = step > 1 ? '' : 'none';

  // Next / Finish button
  const nextBtn = document.getElementById('w-btn-next');
  nextBtn.textContent = step === 3 ? 'Save & Run' : 'Next →';

  // Footer hint
  const hint = document.getElementById('w-footer-hint');
  hint.textContent = step === 1 ? `${wizard.headers.length} columns detected across ${wizard.files.length} file(s)` :
                     step === 2 ? 'Map required fields then click Next' :
                                  'Review your settings and click Save & Run';

  if (step === 1) renderWizardStep1();
  if (step === 2) renderWizardStep2();
  if (step === 3) renderWizardStep3();
}

function wizardBack() {
  if (wizard.step > 1) {
    if (wizard.step === 3) {
      // Re-enable main preview toggle when leaving step 3
      const mainTog = document.getElementById('preview-toggle');
      if (mainTog) mainTog.disabled = false;
    }
    wizardGoTo(wizard.step - 1);
  }
}

async function wizardNext() {
  if (wizard.step === 1) {
    // Validate statement_type is selected in step 1
    const stRadio = document.querySelector('input[name="w-stmt-type-step1"]:checked');
    if (stRadio) {
      wizard.statementType = stRadio.value;
    }
    if (!wizard.statementType) {
      const errEl = document.getElementById('w-step1-type-error');
      if (errEl) { errEl.style.display = ''; errEl.textContent = 'Please select a statement type before continuing.'; }
      return;
    }
    // Hide error if shown
    const errEl1 = document.getElementById('w-step1-type-error');
    if (errEl1) errEl1.style.display = 'none';

    // Polarity is confirmed in step 2 (when cc_amount is mapped) — not required here

    // Fetch canonical fields from server if not yet loaded
    if (!wizard.canonicalFields.length && wizard.files.length) {
      try {
        const info = await api('POST', '/wizard/detect', { file_path: wizard.files[0].path });
        wizard.canonicalFields = info.canonical_fields || [];
        wizard.canonicalLabels = info.canonical_labels || {};
        // Override matched profile if server found a better one
        if (info.matched_profile && info.matched_profile.score > (wizard.matchedProfile?.score || 0)) {
          wizard.matchedProfile = info.matched_profile;
          if (info.matched_profile.suggested_mapping) {
            for (const [f, h] of Object.entries(info.matched_profile.suggested_mapping)) {
              if (h) wizard.suggestions[f] = h;
            }
          }
          wizard.mapping = { ...wizard.suggestions };
        }
        // Merge persisted custom headers from the newly-detected profile
        const detectedCustom = info.matched_profile?.custom_headers || [];
        if (detectedCustom.length) {
          const seen = new Set(wizard.customHeadersSelected.map(h => h.toLowerCase()));
          detectedCustom.forEach(h => { if (!seen.has(h.toLowerCase())) { wizard.customHeadersSelected.push(h); seen.add(h.toLowerCase()); } });
        }
      } catch (err) {
        toast(`Could not fetch field info: ${err.message}`, 'error');
      }
    }
    wizardGoTo(2);
  } else if (wizard.step === 2) {
    // Collect current selections
    collectMappingSelections();
    // Validate
    const errors = validateMappingLocally();

    // For CC single-col (cc_amount), require polarity to be confirmed in step 2
    const ccAmountGroupIdx = FIELD_TO_AMOUNT_GROUP['cc_amount'];
    let activeAmtIdx = null;
    document.querySelectorAll('#w-mapping-rows tr[data-amount-group]').forEach(row => {
      if (activeAmtIdx !== null) return;
      const sel = row.querySelector('select');
      if (sel && sel.value) activeAmtIdx = Number(row.dataset.amountGroup);
    });
    if (wizard.statementType === 'credit_card' && activeAmtIdx === ccAmountGroupIdx) {
      const polRadio = document.querySelector('input[name="w-step2-cc-polarity"]:checked');
      if (!polRadio) {
        errors.push('Amount polarity is required — select which sign convention this credit card uses.');
      } else {
        wizard.ccPolarity = polRadio.value;
      }
    }

    const errEl = document.getElementById('w-validation-errors');
    if (errors.length) {
      errEl.innerHTML = errors.map(e => `<p>• ${esc(e)}</p>`).join('');
      errEl.style.display = 'block';
      return;
    }
    errEl.style.display = 'none';
    wizardGoTo(3);
  } else if (wizard.step === 3) {
    await wizardSaveAndRun();
  }
}

// ── Step 1 render ─────────────────────────────────────────────

function renderWizardStep1() {
  // Pre-processing banner — shown when auto-clean was applied to the CSV
  const ppBannerEl = document.getElementById('w-preprocess-banner');
  if (ppBannerEl) {
    const lastFile = wizard.files[wizard.files.length - 1] || {};
    if (lastFile.preprocess_banner) {
      ppBannerEl.innerHTML = `
        <div class="auto-detect-banner nomatch" id="w-pp-banner-inner" style="background:#f0f9ff; border-color:#7dd3fc; color:#0369a1;">
          <span style="font-size:18px">ℹ️</span>
          <div style="flex:1">${esc(lastFile.preprocess_banner)}</div>
          <button style="background:none;border:none;cursor:pointer;color:#0369a1;font-size:16px;padding:0 4px;"
                  onclick="document.getElementById('w-pp-banner-inner').closest('.auto-detect-banner').remove()">&times;</button>
        </div>`;
    } else {
      ppBannerEl.innerHTML = '';
    }
  }

  // Auto-detect banner
  const banner = document.getElementById('w-detect-banner');
  if (wizard.matchedProfile) {
    const mp = wizard.matchedProfile;
    const score = Math.round(mp.score * 100);
    banner.innerHTML = `
      <div class="auto-detect-banner match">
        <span style="font-size:18px">✅</span>
        <div>
          <strong>Mapping auto-detected</strong> (${score}% match) —
          <em>${esc(mp.bank_name || mp.institution)}</em> /
          <em>${esc(mp.account_name || mp.account_id)}</em>
          (profile: ${esc(mp.profile_name)}).
          Fields are pre-filled below. Review and adjust if needed.
        </div>
      </div>`;
  } else {
    banner.innerHTML = `
      <div class="auto-detect-banner nomatch">
        <span style="font-size:18px">ℹ️</span>
        <div>No saved mapping found for these headers. Complete the wizard to create one.</div>
      </div>`;
  }

  // Info grid
  const firstFile = wizard.files[0] || {};
  document.getElementById('w-info-grid').innerHTML = [
    { label: 'Files',    value: wizard.files.length },
    { label: 'Columns',  value: wizard.headers.length },
    { label: 'Encoding', value: firstFile.encoding || '—' },
    { label: 'Delimiter', value: firstFile.delimiter === '\t' ? 'TAB' : (firstFile.delimiter || '—') },
    { label: 'Est. rows', value: firstFile.row_count_estimate ?? '—' },
  ].map(({ label, value }) => `
    <div class="info-cell">
      <div class="ic-label">${label}</div>
      <div class="ic-value">${esc(String(value))}</div>
    </div>`).join('');

  // ── Statement Type selector (moved from step 3) ──────────────────────────
  const typeContainerEl = document.getElementById('w-step1-stmt-type');
  if (typeContainerEl) {
    const ccChecked  = wizard.statementType === 'credit_card' ? 'checked' : '';
    const bnkChecked = wizard.statementType === 'bank'        ? 'checked' : '';
    typeContainerEl.innerHTML = `
      <div style="margin:12px 0; padding:10px 14px; background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px;">
        <div style="font-size:13px; font-weight:600; margin-bottom:8px; color:var(--text);">
          Statement Type <span style="color:var(--danger)">*</span>
        </div>
        <div style="display:flex; gap:20px; flex-wrap:wrap;">
          <label style="cursor:pointer; display:flex; align-items:center; gap:7px; font-size:13px;">
            <input type="radio" name="w-stmt-type-step1" value="credit_card" ${ccChecked}
                   onchange="wizard.statementType='credit_card'; renderWizardStep1();" />
            💳 Credit Card Statement
          </label>
          <label style="cursor:pointer; display:flex; align-items:center; gap:7px; font-size:13px;">
            <input type="radio" name="w-stmt-type-step1" value="bank" ${bnkChecked}
                   onchange="wizard.statementType='bank'; renderWizardStep1();" />
            🏦 Bank Statement
          </label>
        </div>
        <div id="w-step1-type-error" style="display:none; font-size:12px; color:var(--danger); margin-top:4px;"></div>
      </div>`;
  }

  // ── CC Format Detection & Polarity Confirmation ────────────────────────
  const ccPolarityEl = document.getElementById('w-cc-polarity-panel');
  if (ccPolarityEl) {
    if (wizard.statementType === 'credit_card' && wizard.ccFormat === 'single_col') {
      // Show sample rows from the first file to help user confirm polarity
      const firstFile  = wizard.files[0] || {};
      const samples    = (firstFile.sample_rows || []).slice(0, 5);
      const amtField   = wizard.suggestions.cc_amount || wizard.suggestions.amount;
      const dateField  = wizard.suggestions.transaction_date;
      const descField  = wizard.suggestions.description;
      const sampleRows = samples.filter(r => amtField && r[amtField]);

      const sampleHtml = sampleRows.length
        ? `<table style="margin-top:8px;border-collapse:collapse;font-size:12px;width:100%;">
            <tr style="color:var(--text-muted);">
              ${dateField ? '<th style="text-align:left;padding:3px 8px;">Date</th>' : ''}
              ${descField ? '<th style="text-align:left;padding:3px 8px;">Description</th>' : ''}
              <th style="text-align:right;padding:3px 8px;">Amount</th>
            </tr>
            ${sampleRows.map(r => `<tr>
              ${dateField ? `<td style="padding:3px 8px;">${esc(r[dateField]||'')}</td>` : ''}
              ${descField ? `<td style="padding:3px 8px; max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${esc(r[descField]||'')}</td>` : ''}
              <td class="mono text-right" style="padding:3px 8px;">${esc(r[amtField]||'')}</td>
            </tr>`).join('')}
          </table>`
        : '';

      const faChecked = wizard.ccPolarity === 'format_a' ? 'checked' : '';
      const fbChecked = wizard.ccPolarity === 'format_b' ? 'checked' : '';
      ccPolarityEl.innerHTML = `
        <div style="margin:12px 0; padding:10px 14px; background:#fefce8; border:1px solid #fde047; border-radius:8px;">
          <div style="font-size:13px; font-weight:600; margin-bottom:4px; color:#713f12;">
            ⚠️ Single Amount Column Detected — Confirm Polarity <span style="color:var(--danger)">*</span>
          </div>
          <p style="font-size:12px; color:#92400e; margin:0 0 8px;">
            We detected a single Amount column. Please confirm the sign convention for this statement:
          </p>
          ${sampleHtml}
          <div style="display:flex; gap:20px; flex-wrap:wrap; margin-top:10px;">
            <label style="cursor:pointer; display:flex; align-items:center; gap:7px; font-size:13px;">
              <input type="radio" name="w-cc-polarity" value="format_a" ${faChecked}
                     onchange="wizard.ccPolarity='format_a';" />
              Positive = purchase charged to card <em>(most US cards)</em>
            </label>
            <label style="cursor:pointer; display:flex; align-items:center; gap:7px; font-size:13px;">
              <input type="radio" name="w-cc-polarity" value="format_b" ${fbChecked}
                     onchange="wizard.ccPolarity='format_b';" />
              Positive = payment made to card <em>(some EU/UK banks)</em>
            </label>
          </div>
        </div>`;
    } else if (wizard.statementType === 'credit_card' && wizard.ccFormat === 'two_col') {
      ccPolarityEl.innerHTML = `
        <div style="margin:12px 0; padding:8px 14px; background:#f0fdf4; border:1px solid #86efac; border-radius:8px;">
          <span style="font-size:13px; color:#166534;">
            ✅ <strong>Two-column format detected</strong> — separate charge and payment columns. Subtypes will be assigned automatically.
          </span>
        </div>`;
    } else {
      ccPolarityEl.innerHTML = '';
    }
  }

  // Header chips
  document.getElementById('w-header-chips').innerHTML =
    wizard.headers.map(h => `<span class="header-chip">${esc(h)}</span>`).join('');

  // Sample table — use first file's sample_rows
  const samples = firstFile.sample_rows || [];
  if (samples.length && wizard.headers.length) {
    const sampleBlock = document.getElementById('w-sample-block');
    sampleBlock.style.display = 'block';
    const dispHeaders = wizard.headers;
    document.getElementById('w-sample-head').innerHTML =
      dispHeaders.map(h => `<th>${esc(h)}</th>`).join('');
    document.getElementById('w-sample-body').innerHTML =
      samples.slice(0, 3).map(row =>
        `<tr>${dispHeaders.map(h => `<td>${esc(row[h] || '')}</td>`).join('')}</tr>`
      ).join('');
  }
}

// ── Step 2 render ─────────────────────────────────────────────

function renderWizardStep2() {
  // Scope canonical fields by statement_type (set in step 1)
  const _type = wizard.statementType;

  // Preferred ordered field list based on statement_type
  let _typeFields;
  if (_type === 'credit_card') {
    _typeFields = [
      'transaction_date', 'cc_amount', 'cc_charge', 'cc_payment',
      'description', 'posted_date', 'merchant', 'category', 'account', 'notes', 'currency',
    ];
  } else if (_type === 'bank') {
    _typeFields = [
      'transaction_date',
      'bank_amount', 'bank_debit', 'bank_credit',
      'debit_amount', 'credit_amount',
      'money_in', 'money_out', 'dc_flag',
      'description', 'posted_date', 'merchant', 'category', 'account', 'notes', 'currency',
    ];
  } else {
    _typeFields = [
      'transaction_date',
      'cc_amount', 'cc_charge', 'cc_payment',
      'bank_amount', 'bank_debit', 'bank_credit',
      'debit_amount', 'credit_amount', 'money_in', 'money_out', 'dc_flag',
      'description', 'posted_date', 'merchant', 'category', 'account', 'notes', 'currency',
    ];
  }

  // Format-based hiding: only show the detected amount variant, hide the rest
  const _ccFmt   = wizard.ccFormat;
  const _bankFmt = wizard.bankFormat;
  const _hidden = new Set();

  if (_type === 'credit_card') {
    if (_ccFmt === 'two_col')    { _hidden.add('cc_amount'); }
    if (_ccFmt === 'single_col') { _hidden.add('cc_charge'); _hidden.add('cc_payment'); }
  } else if (_type === 'bank') {
    if (_bankFmt === 'two_col') {
      // Debit + credit columns detected → show bank_debit/bank_credit only
      _hidden.add('bank_amount');
      _hidden.add('debit_amount'); _hidden.add('credit_amount');
      _hidden.add('money_in');     _hidden.add('money_out');
      _hidden.add('dc_flag');
    } else if (_bankFmt === 'single_col') {
      // Single amount column detected → show bank_amount only
      _hidden.add('bank_debit');   _hidden.add('bank_credit');
      _hidden.add('debit_amount'); _hidden.add('credit_amount');
      _hidden.add('money_in');     _hidden.add('money_out');
      _hidden.add('dc_flag');
    }
  }

  const allFields = (wizard.canonicalFields.length
    ? wizard.canonicalFields.filter(f => _typeFields.includes(f))
    : _typeFields
  ).filter(f => !_hidden.has(f));

  // Separate amount fields from non-amount fields to render groups with OR separators
  const amountGroupsForType = _type === 'credit_card' ? WIZARD_CC_AMOUNT_GROUPS
                            : _type === 'bank'        ? WIZARD_BANK_AMOUNT_GROUPS
                            : WIZARD_AMOUNT_GROUPS;
  const amountFieldSet = new Set(amountGroupsForType.flat());
  const nonAmountFields = allFields.filter(f => !amountFieldSet.has(f));
  // Only include groups whose fields appear in allFields (respects format-based hiding)
  const visibleGroups = amountGroupsForType
    .map((grp, idx) => ({ idx, fields: grp.filter(f => allFields.includes(f)) }))
    .filter(g => g.fields.length > 0);

  const labels = wizard.canonicalLabels;
  const isReq  = f => WIZARD_REQUIRED_FIELDS.has(f);

  // Determine which group is currently active (has any mapped field)
  const activeGroupIdx = (() => {
    for (const g of visibleGroups) {
      if (g.fields.some(f => wizard.mapping[f])) return g.idx;
    }
    return null;
  })();

  const makeRow = (field) => {
    const label   = labels[field] || field;
    const current = wizard.mapping[field] || '';
    const isSuggested = !!wizard.suggestions[field] && wizard.suggestions[field] === current;
    const grpIdx  = FIELD_TO_AMOUNT_GROUP[field];
    const isAmountField = grpIdx !== undefined;
    const hidden  = isAmountField && activeGroupIdx !== null && grpIdx !== activeGroupIdx;
    const grpAttr = isAmountField ? ` data-amount-group="${grpIdx}"` : '';
    const opts = ['', ...wizard.headers].map(h =>
      `<option value="${esc(h)}" ${h === current ? 'selected' : ''}>${h ? esc(h) : '(none)'}</option>`
    ).join('');
    return `
      <tr${grpAttr}${hidden ? ' style="display:none"' : ''}>
        <td class="field-label${isReq(field) ? ' required' : ''}">${esc(label)}</td>
        <td>
          <select data-field="${esc(field)}"
                  class="${isSuggested ? 'suggested' : ''}"
                  onchange="onMappingChange(this)">
            ${opts}
          </select>
        </td>
      </tr>`;
  };

  const orSep = (grpIdx) =>
    `<tr data-amount-or-sep="${grpIdx}" style="display:${activeGroupIdx !== null ? 'none' : ''}">
      <td colspan="2" style="text-align:center;color:var(--muted,#888);font-size:11px;padding:2px 0;user-select:none;">── or ──</td>
    </tr>`;

  const tbody = document.getElementById('w-mapping-rows');

  // Build rows: non-amount first (up to transaction_date), then amount groups with OR seps,
  // then remaining non-amount fields
  const dateFields    = nonAmountFields.filter(f => f === 'transaction_date');
  const metaFields    = nonAmountFields.filter(f => f !== 'transaction_date');
  let rows = dateFields.map(makeRow).join('');
  visibleGroups.forEach((g, i) => {
    if (i > 0) rows += orSep(g.idx);
    rows += g.fields.map(makeRow).join('');
  });
  rows += metaFields.map(makeRow).join('');
  tbody.innerHTML = rows;

  // Initialize amount group lock state and polarity panel visibility
  _updateAmountGroupLock();

  // Custom headers panel — only visible when "Include custom headers" is checked
  const panel = document.getElementById('w-custom-headers-panel');
  if (!panel) return;
  if (wizard.includeCustomHeaders) {
    const mappedSet = new Set(Object.values(wizard.mapping).filter(Boolean));
    const unmapped  = wizard.headers.filter(h => !mappedSet.has(h));
    // Union with any profile-persisted custom headers present in the current CSV
    const toShow = [...new Set([
      ...unmapped,
      ...wizard.customHeadersSelected.filter(h => wizard.headers.includes(h)),
    ])];
    if (toShow.length) {
      panel.style.display = '';
      document.getElementById('w-custom-headers-list').innerHTML = toShow.map(h => {
        const chk = wizard.customHeadersSelected.includes(h) ? 'checked' : '';
        return `<label style="display:flex;align-items:center;gap:6px;font-size:13px;cursor:pointer;">
          <input type="checkbox" value="${esc(h)}" ${chk} onchange="onCustomHeaderChange(this)">
          <span class="header-chip" style="margin:0;">${esc(h)}</span>
        </label>`;
      }).join('');
    } else {
      panel.style.display = 'none';
    }
  } else {
    panel.style.display = 'none';
  }
}

function onCustomHeaderChange(el) {
  const h = el.value;
  if (el.checked) {
    if (!wizard.customHeadersSelected.includes(h)) wizard.customHeadersSelected.push(h);
  } else {
    wizard.customHeadersSelected = wizard.customHeadersSelected.filter(x => x !== h);
  }
}

function onMappingChange(sel) {
  const field = sel.dataset.field;
  wizard.mapping[field] = sel.value;
  sel.classList.toggle('suggested', false);

  // If an amount field changed, lock or unlock the group selection
  if (field in FIELD_TO_AMOUNT_GROUP) {
    _updateAmountGroupLock();
  }
}

function _updateAmountGroupLock() {
  // Determine which group (if any) has a mapped field
  let activeIdx = null;
  document.querySelectorAll('#w-mapping-rows tr[data-amount-group]').forEach(row => {
    if (activeIdx !== null) return;
    const sel = row.querySelector('select');
    if (sel && sel.value) activeIdx = Number(row.dataset.amountGroup);
  });

  // Show/hide rows and OR separators based on active group
  document.querySelectorAll('#w-mapping-rows tr[data-amount-group]').forEach(row => {
    const grpIdx = Number(row.dataset.amountGroup);
    const hide = activeIdx !== null && grpIdx !== activeIdx;
    row.style.display = hide ? 'none' : '';
    if (hide) {
      // Clear the hidden field's mapping so it doesn't get submitted
      const sel = row.querySelector('select');
      if (sel) { wizard.mapping[sel.dataset.field] = ''; sel.value = ''; }
    }
  });

  document.querySelectorAll('#w-mapping-rows tr[data-amount-or-sep]').forEach(row => {
    row.style.display = activeIdx !== null ? 'none' : '';
  });

  // Show the step-2 polarity panel when cc_amount (single-col) group is active for CC statements
  const polarityPanel = document.getElementById('w-step2-polarity-panel');
  if (polarityPanel) {
    const ccAmountGroupIdx = FIELD_TO_AMOUNT_GROUP['cc_amount'];
    const showPolarity = wizard.statementType === 'credit_card'
                      && activeIdx === ccAmountGroupIdx;
    polarityPanel.style.display = showPolarity ? '' : 'none';
    // Restore previously selected polarity if switching back
    if (showPolarity && wizard.ccPolarity) {
      const radio = polarityPanel.querySelector(`input[value="${wizard.ccPolarity}"]`);
      if (radio) radio.checked = true;
    }
  }
}

function collectMappingSelections() {
  document.querySelectorAll('#w-mapping-rows select').forEach(sel => {
    wizard.mapping[sel.dataset.field] = sel.value || null;
  });
}

function validateMappingLocally() {
  const errors = [];
  if (!wizard.mapping.transaction_date) {
    errors.push('transaction_date is required — select the column containing the transaction date.');
  }
  const mapped = new Set(Object.entries(wizard.mapping).filter(([,v]) => v).map(([k]) => k));

  // Scope amount groups by statement_type
  const groups = wizard.statementType === 'credit_card' ? WIZARD_CC_AMOUNT_GROUPS
               : wizard.statementType === 'bank'        ? WIZARD_BANK_AMOUNT_GROUPS
               : WIZARD_AMOUNT_GROUPS;
  const ok = groups.some(group => group.every(f => mapped.has(f)));
  if (!ok) {
    const hint = wizard.statementType === 'credit_card'
      ? '(cc_charge + cc_payment) or (cc_amount)'
      : wizard.statementType === 'bank'
        ? '(bank_debit + bank_credit), (bank_amount), (debit_amount + credit_amount), or (money_in + money_out)'
        : 'one of the available amount groups';
    errors.push(`Amount mapping required: map ${hint}.`);
  }
  return errors;
}

// ── Step 3 render ─────────────────────────────────────────────

function renderWizardStep3() {
  // Pre-fill institution / account from matched profile
  const mp = wizard.matchedProfile;
  if (mp) {
    setVal('w-bank-name',       mp.bank_name    || '');
    setVal('w-account-name',    mp.account_name || '');
    setVal('w-institution-key', mp.institution  || '');
    setVal('w-account-id',      mp.account_id   || '');
  }

  // Always write the server-detected date format on the first render of step 3
  // in a session.  The field was cleared in wizardClose(), so on the first
  // render it is empty and setVal() will fill it.  On back/forward navigation
  // within the same session the field already has a value (detected or user-
  // edited) and setVal() leaves it untouched — preserving manual overrides.
  if (wizard.suggestedDateFormat) {
    setVal('w-date-format', wizard.suggestedDateFormat);
  }

  // Statement type was confirmed in step 1; show as read-only badge in step 3
  const typeDisplayEl = document.getElementById('w-step3-stmt-type-display');
  if (typeDisplayEl) {
    if (wizard.statementType === 'credit_card') {
      let extra = '';
      if (wizard.ccFormat === 'two_col') {
        extra = ' · Two-column format (cc_charge / cc_payment)';
      } else if (wizard.ccFormat === 'single_col' && wizard.ccPolarity) {
        const polarityLabel = wizard.ccPolarity === 'format_a'
          ? 'Positive = spending'
          : 'Positive = payment';
        extra = ` · Single-column · <em>${polarityLabel}</em> (saved to profile)`;
      }
      typeDisplayEl.innerHTML = `<span class="chip" style="background:#dbeafe;color:#1e40af;padding:3px 8px;border-radius:4px;font-size:12px;">💳 Credit Card${extra}</span>`;
    } else if (wizard.statementType === 'bank') {
      typeDisplayEl.innerHTML = `<span class="chip" style="background:#dcfce7;color:#166534;padding:3px 8px;border-radius:4px;font-size:12px;">🏦 Bank Statement</span>`;
    } else {
      typeDisplayEl.innerHTML = '';
    }
  }

  // Sync wizard preview toggle with main Configure Mapping toggle and lock main toggle
  const mainTog = document.getElementById('preview-toggle');
  const wizTog  = document.getElementById('w-preview-toggle');
  if (wizTog && mainTog) {
    wizTog.onchange = () => { mainTog.disabled = wizTog.checked; };
    mainTog.disabled = wizTog.checked;
  }

  // Mapping summary — show only mapped fields
  const mapped = Object.entries(wizard.mapping).filter(([,v]) => v);
  document.getElementById('w-mapping-summary').innerHTML = mapped.length
    ? mapped.map(([field, hdr]) => `
        <div class="ms-row">
          <span class="ms-field">${esc(field)}</span>
          <span class="ms-val">${esc(hdr)}</span>
        </div>`).join('')
    : '<em style="color:var(--text-muted)">No fields mapped.</em>';
}

function setVal(id, val) {
  const el = document.getElementById(id);
  if (el && !el.value) el.value = val;
}

// ── Save & Run ────────────────────────────────────────────────

async function wizardSaveAndRun() {
  const btn = document.getElementById('w-btn-next');
  btn.disabled = true;
  btn.textContent = 'Saving…';

  const institution  = document.getElementById('w-institution-key').value.trim() || 'unknown';
  const accountId    = document.getElementById('w-account-id').value.trim()      || 'default';
  const accountName  = document.getElementById('w-account-name').value.trim();
  const bankName     = document.getElementById('w-bank-name').value.trim();
  const dateFormat   = document.getElementById('w-date-format').value.trim() || null;
  const currency     = document.getElementById('w-currency').value;
  const previewOnly  = document.getElementById('w-preview-toggle').checked;

  const filePaths = wizard.files.map(f => f.path);

  // statement_type was confirmed in step 1 and stored in wizard.statementType
  const statementType = wizard.statementType;
  console.log('[Mapping] statement_type submitted as:', statementType);

  if (!statementType) {
    toast('Statement type not selected. Please go back to step 1 and select Credit Card or Bank.', 'error');
    btn.disabled = false;
    btn.textContent = 'Save & Run';
    return;
  }

  try {
    const res = await api('POST', '/wizard/save-and-run', {
      file_paths:       filePaths,
      canonical_map:    wizard.mapping,
      institution,
      account_id:       accountId,
      account_name:     accountName,
      bank_name:        bankName,
      date_format:      dateFormat,
      currency_default: currency,
      preview_only:     previewOnly,
      custom_headers:   wizard.customHeadersSelected,
      statement_type:   statementType,
      // CC polarity for single-col format
      cc_polarity:      wizard.ccPolarity || null,
    });

    wizardClose();
    toast(`Mapping saved. Run ${res.run_id} started.`, 'success');

    // Hand off to existing run-status machinery
    state.currentRunId = res.run_id;
    setRunStatus('pending', res.run_id, null, 'Queued — starting pipeline…');
    navigate('import');
    pollRun(res.run_id, onRunComplete);

  } catch (err) {
    toast(`Save & Run failed: ${err.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Save & Run';
  }
}

// ── Credit Cards & Bank Transactions tabs (Feature 4) ─────────────────────────
// Two tabs backed by GET /transactions and GET /transactions/totals.
// Feature 1: `type` param is HARD-passed to every API call — credit_card ≠ bank.
// Feature 3: tfoot totals use server-computed aggregates (not client-side sums).

/** Per-type pagination/sort state — reset when filters change, advance on Load more. */
const _txnState = {
  credit_card: { offset: 0, sortBy: 'transaction_date', sortDir: 'desc', debounceTimer: null },
  bank:        { offset: 0, sortBy: 'transaction_date', sortDir: 'desc', debounceTimer: null },
};

/** DOM element-id prefix: 'cc' for credit_card, 'bk' for bank. */
function _pfx(type) { return type === 'credit_card' ? 'cc' : 'bk'; }

// ── Source dropdown instances (one per tab type) ────────────────
// makeSourceDropdown is defined in table_controls.js, loaded before app.js.
// Each instance manages its own fetch, radio state, and reset independently.
const _srcCtrl = {
  credit_card: makeSourceDropdown('cc-source-ctrl', 'credit_card', () => loadTxnTab('credit_card')),
  bank:        makeSourceDropdown('bk-source-ctrl', 'bank',        () => loadTxnTab('bank')),
};

/** Account picker for CC and Bank tabs — same pattern as source dropdown */
function _makeAcctDropdown(containerId, type, onChange) {
  const container = document.getElementById(containerId);
  if (!container) return { load: async () => {}, reset: () => {}, value: () => '' };

  let _selected = '';
  const trigger = document.createElement('button');
  trigger.type = 'button';
  trigger.className = 'source-trigger';
  const panel = document.createElement('div');
  panel.className = 'source-panel';
  panel.setAttribute('role', 'listbox');
  panel.style.display = 'none';
  container.appendChild(trigger);
  container.appendChild(panel);

  function _label() { return _selected || 'All Accounts'; }
  function _updateTrigger() {
    trigger.innerHTML = '';
    trigger.appendChild(document.createTextNode(_label()));
    const arrow = document.createElement('span');
    arrow.className = 'source-arrow';
    arrow.textContent = '▼';
    trigger.appendChild(arrow);
  }
  function _close() {
    panel.style.display = 'none';
    trigger.setAttribute('aria-expanded', 'false');
  }
  function _open() {
    panel.style.display = 'block';
    trigger.setAttribute('aria-expanded', 'true');
  }
  function _select(val) {
    _selected = val;
    _close();
    _updateTrigger();
    onChange(val);
  }

  trigger.addEventListener('click', e => {
    e.stopPropagation();
    panel.style.display === 'none' ? _open() : _close();
  });
  document.addEventListener('click', e => {
    if (!container.contains(e.target)) _close();
  });

  function _render(accounts) {
    panel.innerHTML = '';
    const allOpt = document.createElement('label');
    allOpt.className = 'source-option';
    allOpt.innerHTML = `<input type="radio" name="acct-${containerId}" value=""> <span class="source-option-content"><span class="source-option-label">All Accounts</span></span>`;
    allOpt.querySelector('input').checked = (_selected === '');
    allOpt.querySelector('input').addEventListener('change', () => _select(''));
    panel.appendChild(allOpt);

    accounts.forEach(a => {
      const opt = document.createElement('label');
      opt.className = 'source-option';
      opt.innerHTML = `<input type="radio" name="acct-${containerId}" value="${esc(a.account_name)}"> <span class="source-option-content"><span class="source-option-label">${esc(a.account_name)}</span><span class="source-option-meta"><span class="source-option-count">${a.count} txns</span></span></span>`;
      opt.querySelector('input').checked = (a.account_name === _selected);
      opt.querySelector('input').addEventListener('change', () => _select(a.account_name));
      panel.appendChild(opt);
    });
    _updateTrigger();
  }

  async function load() {
    try {
      const data = await api('GET', `/transactions/accounts?type=${encodeURIComponent(type)}`);
      _render(data.accounts || []);
    } catch (e) { _render([]); }
  }
  function reset() { _selected = ''; _updateTrigger(); }
  function value() { return _selected; }
  _updateTrigger();
  return { load, reset, value };
}

const _acctCtrl = {
  credit_card: _makeAcctDropdown('cc-acct-ctrl', 'credit_card', () => loadTxnTab('credit_card')),
  bank:        _makeAcctDropdown('bk-acct-ctrl', 'bank',        () => loadTxnTab('bank')),
};

/** Read current filter values from the DOM for the given tab type. */
function _txnFilters(type) {
  const p = _pfx(type);
  return {
    source:          _srcCtrl[type].value(),                                   // from radio-dropdown
    date_from:       document.getElementById(`${p}-date-from`)?.value || '',
    date_to:         document.getElementById(`${p}-date-to`)?.value   || '',
    account:         (_acctCtrl[type]?.value() || ''),
    amount_min:      document.getElementById(`${p}-amount-min`)?.value || '',
    amount_max:      document.getElementById(`${p}-amount-max`)?.value || '',
    category:        (document.getElementById(`${p}-category`)?.value || '').trim(),
    merchant:        (document.getElementById(`${p}-merchant`)?.value || '').trim(),
    subtype:         document.getElementById(`${p}-subtype`)?.value   || '',  // CC only
    group_by:        document.getElementById(`${p}-group-by`)?.value  || '',
    unreviewed_only: document.getElementById(`${p}-unreviewed-only`)?.checked || false,
    no_merchant:     document.getElementById(`${p}-no-merchant`)?.checked || false,
    no_category:     document.getElementById(`${p}-no-category`)?.checked || false,
    tag:             document.getElementById(`${p}-tag`)?.value       || '',
  };
}

/**
 * Main loader for Credit Cards / Bank Transactions tabs.
 * reset=true (default): reset pagination and replace table contents.
 * reset=false: append the next page of results (Load more).
 *
 * Fetches rows (/transactions) and totals (/transactions/totals) in parallel.
 * Feature 1: `type` is hard-passed to every API call — never merged across types.
 */
async function loadTxnTab(type, reset = true) {
  // Refresh year dropdown to ensure historical years are visible
  await _loadTxnYears();

  const p    = _pfx(type);
  const st   = _txnState[type];
  const PAGE = 50;

  if (reset) st.offset = 0;

  const f = _txnFilters(type);

  // Build query string for /transactions (includes pagination + sort)
  const qs = new URLSearchParams({ type, limit: PAGE, offset: st.offset,
                                   sort_by: st.sortBy, sort_dir: st.sortDir });
  if (f.date_from) qs.set('date_from', f.date_from);
  if (f.date_to)   qs.set('date_to',   f.date_to);
  if (f.account)   qs.set('account',   f.account);
  if (f.category)  qs.set('category',  f.category);
  if (f.merchant)  qs.set('merchant',  f.merchant);
  if (f.subtype)   qs.set('subtype',   f.subtype);
  if (f.group_by)  qs.set('group_by',  f.group_by);
  if (f.source && f.source !== 'all') qs.set('source', f.source);
  if (f.unreviewed_only) qs.set('unreviewed_only', 'true');
  if (f.no_merchant)     qs.set('no_merchant', 'true');
  if (f.no_category)     qs.set('no_category', 'true');
  if (f.tag)       qs.set('tag', f.tag);
  if (f.amount_min) qs.set('amount_min', f.amount_min);
  if (f.amount_max) qs.set('amount_max', f.amount_max);

  // Totals endpoint uses the same filter params (no pagination or sort)
  const tqs = new URLSearchParams({ type });
  if (f.date_from) tqs.set('date_from', f.date_from);
  if (f.date_to)   tqs.set('date_to',   f.date_to);
  if (f.account)   tqs.set('account',   f.account);
  if (f.category)  tqs.set('category',  f.category);
  if (f.merchant)  tqs.set('merchant',  f.merchant);
  if (f.subtype)   tqs.set('subtype',   f.subtype);
  if (f.source && f.source !== 'all') tqs.set('source', f.source);
  if (f.unreviewed_only) tqs.set('unreviewed_only', 'true');
  if (f.no_merchant)     tqs.set('no_merchant', 'true');
  if (f.no_category)     tqs.set('no_category', 'true');
  if (f.tag)       tqs.set('tag', f.tag);
  if (f.amount_min) tqs.set('amount_min', f.amount_min);
  if (f.amount_max) tqs.set('amount_max', f.amount_max);

  if (reset) {
    document.getElementById(`${p}-tbody`).innerHTML =
      `<tr><td colspan="10" class="text-center text-muted" style="padding:32px">Loading\u2026</td></tr>`;
    document.getElementById(`${p}-tfoot`).innerHTML = '';
    document.getElementById(`${p}-meta`).textContent = '';
    document.getElementById(`${p}-load-more`).style.display = 'none';
    // Populate source dropdown (table_controls.js) on every tab switch
    await _srcCtrl[type].load();
    // Load account picker
    await _acctCtrl[type].load();
    // Ensure tag filter dropdown is populated
    _populateTagDropdowns();
    // Load balance card from Accounts module if account filter is active
    _loadBalanceCard(type, f.account);
  }

  try {
    // Fetch rows and totals in parallel — avoids sequential round-trips
    const [data, totals] = await Promise.all([
      api('GET', `/transactions?${qs}`),
      api('GET', `/transactions/totals?${tqs}`),
    ]);

    const rows = data.rows    || [];
    const cols = data.columns || [];

    if (reset) {
      _renderTxnHeaders(p, cols, type);
      _renderTxnBody(p, rows, cols, false, type);
    } else {
      _renderTxnBody(p, rows, cols, true, type);   // append rows for Load more
    }
    // Load tag chips for visible transaction rows
    _loadVisibleTagChips();

    // Pinned tfoot always reflects the full filtered set, not just the current page.
    // renderTxnTotals is defined in table_controls.js (shared utility).
    // Pass optional warnEl for CC legacy/conflict banners.
    renderTxnTotals(
      document.getElementById(`${p}-tfoot`), totals, type, cols.length || 10,
      document.getElementById(`${p}-totals-warn`),
    );
    _renderFilterChips(type);

    // Render Card Financial Summary panel for credit card tab
    if (type === 'credit_card') _renderCcFinancialSummary(totals);

    // Advance pagination cursor and update meta / Load more visibility
    st.offset += rows.length;
    document.getElementById(`${p}-meta`).textContent =
      `${st.offset} row${st.offset !== 1 ? 's' : ''} loaded`;
    document.getElementById(`${p}-load-more`).style.display =
      rows.length >= PAGE ? '' : 'none';

    // Debug: verifiable in browser console per coding standards
    const tabName = type === 'credit_card' ? 'CreditCards' : 'BankTransactions';
    console.log(`[${tabName}] loaded ${rows.length} rows (offset=${st.offset}, total_filtered=${totals.row_count})`);

  } catch (err) {
    document.getElementById(`${p}-tbody`).innerHTML =
      `<tr><td colspan="10" class="text-center text-muted">Error: ${esc(err.message)}</td></tr>`;
    const tabName = type === 'credit_card' ? 'CreditCards' : 'BankTransactions';
    console.error(`[${tabName}] fetch error:`, err.message);
    toast(`Failed to load ${type === 'credit_card' ? 'credit card' : 'bank'} transactions: ${err.message}`, 'error');
  }
}

/**
 * Debounce text-input changes by 400 ms before reloading.
 * Prevents API spam on every keypress in the filter inputs.
 */
function debounceTxn(type) {
  const st = _txnState[type];
  clearTimeout(st.debounceTimer);
  st.debounceTimer = setTimeout(() => loadTxnTab(type), 400);
}

/** Reset all filter controls to defaults and reload from page 1. */
function clearTxnFilters(type) {
  const p = _pfx(type);
  _srcCtrl[type].reset();   // reset radio-dropdown to "All Imports"
  ['date-from', 'date-to', 'account', 'category', 'merchant', 'tag'].forEach(id => {
    const el = document.getElementById(`${p}-${id}`);
    if (el) el.value = '';
  });
  const grp = document.getElementById(`${p}-group-by`);
  if (grp) grp.value = '';
  const unrev = document.getElementById(`${p}-unreviewed-only`);
  if (unrev) unrev.checked = false;
  const noMerch = document.getElementById(`${p}-no-merchant`);
  if (noMerch) noMerch.checked = false;
  const noCat = document.getElementById(`${p}-no-category`);
  if (noCat) noCat.checked = false;
  _txnState[type].sortBy  = 'transaction_date';
  _txnState[type].sortDir = 'desc';
  _acctCtrl[type]?.reset();
  const p2 = _pfx(type);
  ['amount-min','amount-max'].forEach(s => {
    const el = document.getElementById(`${p2}-${s}`); if (el) el.value = '';
  });
  loadTxnTab(type);
}

let _saveTxnReportType = null;

function _saveTxnFilterAsReport(type) {
  _saveTxnReportType = type;
  const modal = document.getElementById('save-txn-report-modal');
  if (!modal) return;
  document.getElementById('strm-name').value = '';
  document.getElementById('strm-desc').value = '';
  modal.classList.remove('hidden');
  document.getElementById('strm-name').focus();
}

function _closeSaveTxnReportModal() {
  document.getElementById('save-txn-report-modal')?.classList.add('hidden');
  _saveTxnReportType = null;
}

async function _confirmSaveTxnReport() {
  const name = (document.getElementById('strm-name')?.value || '').trim();
  const desc = (document.getElementById('strm-desc')?.value || '').trim();
  if (!name) { toast('Report name is required.', 'error'); return; }
  const type = _saveTxnReportType || 'both';
  const f    = _txnFilters(type);

  const filters = [];
  if (f.category)  filters.push({ field: 'category_normalized', op: 'contains', value: f.category });
  if (f.merchant)  filters.push({ field: 'merchant',            op: 'contains', value: f.merchant });
  if (f.subtype)   filters.push({ field: 'transaction_subtype', op: '=',        value: f.subtype });
  if (f.amount_min) filters.push({ field: 'amount', op: '>=', value: f.amount_min });
  if (f.amount_max) filters.push({ field: 'amount', op: '<=', value: f.amount_max });
  if (f.account)   filters.push({ field: 'account_name', op: '=', value: f.account });
  if (f.no_category)  filters.push({ field: 'category_normalized', op: 'is_null', value: null });
  if (f.no_merchant)  filters.push({ field: 'merchant',            op: 'is_null', value: null });
  const group_by = f.group_by ? [f.group_by] : [];

  try {
    await api('POST', '/saved-reports', {
      name, description: desc,
      stmt_type: type,
      filters, group_by,
      bucket: null,
      date_from: f.date_from || null,
      date_to:   f.date_to   || null,
    });
    toast(`Report "${name}" saved. View it in the Reports tab.`, 'success');
    _closeSaveTxnReportModal();
  } catch (err) { toast(`Failed: ${err.message}`, 'error'); }
}

/** Append the next page of results (called by the "Load more" button). */
function loadMoreTxn(type) {
  loadTxnTab(type, false);
}

/**
 * Render <thead> with sort-clickable column headers.
 * The active sort column shows a ▲ or ▼ indicator.
 */
function _renderTxnHeaders(p, cols, type) {
  const thead = document.getElementById(`${p}-thead`);
  if (!thead) return;
  const st = _txnState[type];
  // Hide metadata columns used only for review logic; append a Review header instead
  const HIDDEN_COLS = new Set(['transaction_fingerprint', 'unreviewed', 'notes', 'is_split', 'split_parent_fingerprint', 'category_override']);
  const selectAllCb = `<th style="width:30px;"><input type="checkbox" class="bulk-check" onchange="bulkToggleAll('${type}', this.checked)" title="Select all" /></th>`;
  thead.innerHTML = selectAllCb + cols.filter(c => !HIDDEN_COLS.has(c)).map(c => {
    const isSorted = c === st.sortBy;
    const arrow    = isSorted ? (st.sortDir === 'asc' ? ' \u25b2' : ' \u25bc') : '';
    const facetCols = new Set(['category_normalized','category_parent','merchant','account_name','statement_type','currency']);
    const filterIcon = facetCols.has(c)
      ? ` <span class="col-filter-icon" title="Filter by ${esc(c)}" onclick="event.stopPropagation();_openColFacet('${type}','${c}',this)" style="cursor:pointer;opacity:0.5;font-size:10px;margin-left:2px;">▼</span>`
      : '';
    return `<th style="cursor:pointer;user-select:none;" onclick="_txnSort('${type}','${c}')">${esc(c)}${arrow}${filterIcon}</th>`;
  }).join('') + '<th class="text-center" style="min-width:40px;">Notes</th><th class="text-center" style="min-width:100px;">Tags</th><th class="text-center" style="min-width:90px;">Review</th><th class="text-center" style="min-width:70px;">Split</th>';
}

/**
 * Handle a sort-header click: toggle direction when same column is clicked,
 * default to descending for a newly selected column, then reload from page 1.
 */
function _txnSort(type, col) {
  const st = _txnState[type];
  if (st.sortBy === col) {
    st.sortDir = st.sortDir === 'asc' ? 'desc' : 'asc';
  } else {
    st.sortBy  = col;
    st.sortDir = 'desc';
  }
  loadTxnTab(type);
}

// ── Column facet popovers ─────────────────────────────────────

const _facetCache = {};
const _colFilters = { credit_card: {}, bank: {} };
let   _facetPopoverEl = null;

function _facetCacheKey(type, col, f) {
  return `${type}|${col}|${f.date_from}|${f.date_to}|${f.category}|${f.merchant}|${f.account}|${f.subtype}`;
}

async function _openColFacet(type, col, iconEl) {
  _closeColFacet();

  const f   = _txnFilters(type);
  const key = _facetCacheKey(type, col, f);
  let values;
  if (_facetCache[key]) {
    values = _facetCache[key];
  } else {
    const qs = new URLSearchParams({ type, column: col });
    if (f.date_from) qs.set('date_from', f.date_from);
    if (f.date_to)   qs.set('date_to',   f.date_to);
    if (f.account)   qs.set('account',   f.account);
    if (f.category)  qs.set('category',  f.category);
    if (f.merchant)  qs.set('merchant',  f.merchant);
    if (f.subtype)   qs.set('subtype',   f.subtype);
    try {
      const data = await api('GET', `/transactions/facets?${qs}`);
      values = data.values || [];
      _facetCache[key] = values;
    } catch (e) { toast('Could not load filter values.', 'error'); return; }
  }

  const current = _colFilters[type][col] || '';
  const pop = document.createElement('div');
  pop.id = 'col-facet-popover';
  pop.style.cssText = 'position:absolute;z-index:9999;background:var(--surface,#fff);border:1px solid var(--border);border-radius:8px;box-shadow:0 4px 20px rgba(0,0,0,.15);padding:8px;min-width:200px;max-width:300px;';
  pop.innerHTML = `
    <input id="col-facet-search" type="text" placeholder="Search…" autocomplete="off"
           style="width:100%;padding:4px 8px;border:1px solid var(--border);border-radius:6px;font-size:12px;margin-bottom:6px;box-sizing:border-box;" />
    <div id="col-facet-list" style="max-height:220px;overflow-y:auto;display:flex;flex-direction:column;gap:2px;"></div>
    <div style="display:flex;gap:6px;margin-top:8px;">
      <button class="btn btn-secondary btn-sm" style="font-size:11px;" onclick="_clearColFacet('${type}','${col}')">Clear</button>
      <button class="btn btn-secondary btn-sm" style="font-size:11px;" onclick="_closeColFacet()">Close</button>
    </div>`;

  function _renderFacetList(filter) {
    const list = pop.querySelector('#col-facet-list');
    const filtered = filter ? values.filter(v => v.value.toLowerCase().includes(filter.toLowerCase())) : values;
    list.innerHTML = filtered.map(v =>
      `<label style="display:flex;justify-content:space-between;align-items:center;padding:3px 6px;border-radius:4px;cursor:pointer;font-size:12px;${v.value===current?'background:var(--primary-light,#dbeafe);':''}">
        <span><input type="radio" name="col-facet-${col}" value="${esc(v.value)}" ${v.value===current?'checked':''} style="margin-right:4px;" onchange="_applyColFacet('${type}','${col}','${esc(v.value).replace(/'/g,"\\'")}')"> ${esc(v.value || '(blank)')}</span>
        <span style="font-size:10px;color:var(--text-muted);">${v.count}</span>
      </label>`
    ).join('');
  }
  _renderFacetList('');
  pop.querySelector('#col-facet-search').addEventListener('input', e => _renderFacetList(e.target.value));

  document.body.appendChild(pop);
  _facetPopoverEl = pop;
  const rect = iconEl.getBoundingClientRect();
  pop.style.top  = (rect.bottom + window.scrollY + 4) + 'px';
  pop.style.left = Math.max(0, rect.left + window.scrollX - 60) + 'px';

  setTimeout(() => {
    document.addEventListener('click', _colFacetOutsideClick);
    pop.querySelector('#col-facet-search').focus();
  }, 10);
}

function _colFacetOutsideClick(e) {
  if (_facetPopoverEl && !_facetPopoverEl.contains(e.target)) _closeColFacet();
}

function _closeColFacet() {
  if (_facetPopoverEl) { _facetPopoverEl.remove(); _facetPopoverEl = null; }
  document.removeEventListener('click', _colFacetOutsideClick);
}

function _applyColFacet(type, col, value) {
  _colFilters[type][col] = value;
  _closeColFacet();
  const p = _pfx(type);
  const colToInput = {
    category_normalized: `${p}-category`,
    category_parent:     `${p}-category`,
    merchant:            `${p}-merchant`,
  };
  if (colToInput[col]) {
    const el = document.getElementById(colToInput[col]);
    if (el) { el.value = value; }
  }
  loadTxnTab(type);
}

function _clearColFacet(type, col) {
  delete _colFilters[type][col];
  const p = _pfx(type);
  const colToInput = {
    category_normalized: `${p}-category`,
    category_parent:     `${p}-category`,
    merchant:            `${p}-merchant`,
  };
  if (colToInput[col]) {
    const el = document.getElementById(colToInput[col]);
    if (el) el.value = '';
  }
  _closeColFacet();
  loadTxnTab(type);
}

/**
 * Render (or append to) the <tbody> rows.
 * Numeric columns are right-aligned and monospaced for readability.
 */
function _renderTxnBody(p, rows, cols, append, type) {
  const tbody = document.getElementById(`${p}-tbody`);
  if (!tbody) return;
  const span = cols.length || 10;

  if (!rows.length && !append) {
    tbody.innerHTML =
      `<tr><td colspan="${span}" class="text-center text-muted" style="padding:32px">No transactions found.</td></tr>`;
    return;
  }

  const NUMERIC_COLS = new Set([
    'amount', 'total_spend', 'total_income', 'total_outflow', 'net_amount', 'row_count',
  ]);
  // Columns hidden from the user (used for review logic only)
  const HIDDEN_COLS = new Set(['transaction_fingerprint', 'unreviewed', 'notes', 'is_split', 'split_parent_fingerprint', 'category_override']);

  const visibleCols = cols.filter(c => !HIDDEN_COLS.has(c));

  // If group_by is active, make each row clickable to drill into its transactions
  const groupByVal = document.getElementById(`${p}-group-by`)?.value || '';

  const html = rows.map(row => {
    // DuckDB may serialize booleans as true or 'true' depending on driver version
    const isUnreviewed = row.unreviewed === true || row.unreviewed === 'true';
    const fp = row.transaction_fingerprint || '';
    const isSplitChild = !!row.split_parent_fingerprint;
    const rowCls = isUnreviewed ? ' class="unreviewed-row"' : '';
    // Checkbox cell for bulk selection
    const checkCell = fp
      ? `<td><input type="checkbox" class="bulk-check" data-fp="${esc(fp)}" onchange="bulkToggleRow(this)" /></td>`
      : '<td></td>';
    // Split badge prepended to description
    const splitBadge = isSplitChild ? '<span class="split-badge" title="Split transaction">split</span> ' : '';
    // Group-by drill-down: clicking the row navigates to filtered transactions
    const drillAttrs = groupByVal ? (() => {
      const groupColVal = row[groupByVal] ?? '';
      const groupValEsc = String(groupColVal).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
      return `style="cursor:pointer;" title="Click to filter by this group" onclick="_drillIntoGroup('${type}','${esc(groupByVal)}','${groupValEsc}')"`;
    })() : '';
    const cells = visibleCols.map(c => {
      const val = row[c] != null ? String(row[c]) : '';
      const cls = NUMERIC_COLS.has(c) ? ' class="mono text-right"' : '';
      // Inline category edit: make category cells clickable with pencil icon
      if ((c === 'category_parent' || c === 'category_normalized' || c === 'category') && fp) {
        const isOverride = row.category_override === true || row.category_override === 'true';
        const displayVal = val || '— No category —';
        const displayStyle = val ? '' : ' color:var(--text-muted);';
        const badge = isOverride ? ' <span class="override-badge" onclick="event.stopPropagation(); _resetCategoryOverride(this)" title="Click to reset to rule-based category">edited</span>' : '';
        return `<td${cls} onclick="inlineCategoryEdit(this,'${esc(fp)}')" data-override="${isOverride}" data-col="${c}" title="Click to edit" style="cursor:pointer;${displayStyle}"><span>${esc(displayVal)}</span>${badge}</td>`;
      }
      // Tag merchant column for Fix-for-all lookup
      if (c === 'merchant' && fp) {
        return `<td${cls} data-col="merchant">${esc(val)}</td>`;
      }
      // Prepend split badge to description
      if (c === 'description' && isSplitChild) {
        return `<td${cls}>${splitBadge}${esc(val)}</td>`;
      }
      return `<td${cls}>${esc(val)}</td>`;
    }).join('');
    // Notes cell: icon button that opens inline edit
    const noteVal = row.notes || '';
    const notesCell = fp
      ? `<td class="text-center" style="white-space:nowrap;">
          <button class="btn-note${noteVal ? ' has-note' : ''}" onclick="openNoteEdit('${esc(fp)}', this)" title="${noteVal ? esc(noteVal) : 'Add note'}">${noteVal ? '&#9998;' : '&#43;'}</button>
        </td>`
      : '<td></td>';
    // Tag cell
    const tagCell = fp
      ? `<td class="text-center" style="white-space:nowrap;">
          <span id="tags-${esc(fp)}" class="tag-chips"></span>
          <button class="btn btn-secondary btn-sm" style="padding:1px 6px; font-size:10px;" onclick="openTagPopup('${esc(fp)}')">+tag</button>
        </td>`
      : '<td></td>';
    // Review status cell: dot indicator + button
    const reviewCell = fp
      ? `<td class="text-center" style="white-space:nowrap;">${
          isUnreviewed
            ? `<span class="unreviewed-dot" title="Unreviewed"></span> <button class="btn btn-secondary btn-sm" style="padding:2px 8px; font-size:11px;" onclick="markReviewed('${esc(fp)}')">Reviewed</button>`
            : '<span style="color:var(--success); font-size:11px;">&#10003;</span>'
        }</td>`
      : '<td></td>';
    // Split action cell: Split button for unsplit non-child rows, Unsplit for child rows
    let splitCell = '<td></td>';
    if (fp && isSplitChild) {
      splitCell = `<td class="text-center" style="white-space:nowrap;">
        <button class="btn btn-secondary btn-sm" style="padding:2px 6px; font-size:10px; color:var(--danger);" onclick="unsplitTransaction('${esc(row.split_parent_fingerprint)}')" title="Remove split and restore original transaction">Unsplit</button>
      </td>`;
    } else if (fp && !isSplitChild) {
      splitCell = `<td class="text-center" style="white-space:nowrap;">
        <button class="btn btn-secondary btn-sm" style="padding:2px 6px; font-size:10px;" onclick="openSplitModal('${esc(fp)}')" title="Split this transaction across multiple categories">&#9889; Split</button>
      </td>`;
    }
    return `<tr${rowCls} data-fp="${esc(fp)}" ${drillAttrs}>${checkCell}${cells}${notesCell}${tagCell}${reviewCell}${splitCell}</tr>`;
  }).join('');

  if (append) {
    tbody.insertAdjacentHTML('beforeend', html);
  } else {
    tbody.innerHTML = html;
  }
}

function _drillIntoGroup(type, col, value) {
  const p = _pfx(type);
  const groupSel = document.getElementById(`${p}-group-by`);
  if (groupSel) groupSel.value = '';
  const colToInput = {
    category_normalized: `${p}-category`,
    category_parent:     `${p}-category`,
    category:            `${p}-category`,
    merchant:            `${p}-merchant`,
  };
  if (colToInput[col]) {
    const el = document.getElementById(colToInput[col]);
    if (el) el.value = value;
  }
  loadTxnTab(type);
}

// ── Transaction Review ────────────────────────────────────────

/** Mark a single transaction as reviewed by fingerprint. */
async function markReviewed(fingerprint) {
  try {
    await api('POST', '/transactions/mark-reviewed', { fingerprints: [fingerprint] });
    // Optimistically update the row in the DOM
    const row = document.querySelector(`button[onclick="markReviewed('${fingerprint}')"]`);
    if (row) {
      const tr = row.closest('tr');
      if (tr) {
        tr.classList.remove('unreviewed-row');
        const reviewCell = tr.querySelector('td:last-child');
        if (reviewCell) reviewCell.innerHTML = '<span style="color:var(--success); font-size:11px;">&#10003;</span>';
      }
    }
    refreshUnreviewedBadge();
  } catch (err) {
    toast('Failed to mark as reviewed: ' + err.message, 'error');
  }
}

/** Mark all currently filtered transactions as reviewed. */
async function markAllReviewed(type) {
  const f = _txnFilters(type);
  const qs = new URLSearchParams({ type });
  if (f.date_from) qs.set('date_from', f.date_from);
  if (f.date_to)   qs.set('date_to',   f.date_to);
  if (f.account)   qs.set('account',   f.account);
  if (f.category)  qs.set('category',  f.category);
  if (f.merchant)  qs.set('merchant',  f.merchant);
  if (f.subtype)   qs.set('subtype',   f.subtype);
  if (f.source && f.source !== 'all') qs.set('source', f.source);
  try {
    const result = await api('POST', `/transactions/mark-all-reviewed?${qs}`);
    toast(`Marked ${result.updated} transaction${result.updated !== 1 ? 's' : ''} as reviewed`, 'success');
    loadTxnTab(type);
    refreshUnreviewedBadge();
  } catch (err) {
    toast('Failed to mark all as reviewed: ' + err.message, 'error');
  }
}

/** Refresh the unreviewed count badge in the sidebar nav. */
async function refreshUnreviewedBadge() {
  try {
    const data = await api('GET', '/transactions/unreviewed-count');
    const badge = document.getElementById('nav-unreviewed-badge');
    if (badge) badge.textContent = data.unreviewed_count > 0 ? data.unreviewed_count : '';
  } catch {
    // Silently ignore — badge is non-critical
  }
}

// _renderTxnTfoot has been extracted to table_controls.js as renderTxnTotals().
// See table_controls.js for the implementation with proper labeled column cells.

/**
 * Render the Card Financial Summary collapsible panel below CC totals.
 * Breaks down card activity into Purchases, Payments, Credits & Adjustments, Net Activity.
 */
function _renderCcFinancialSummary(totals) {
  const panel = document.getElementById('cc-financial-summary');
  const body  = document.getElementById('cc-financial-summary-body');
  if (!panel || !body) return;

  if (!totals || !totals.row_count) {
    panel.style.display = 'none';
    return;
  }

  const f2 = v => Number(v || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const spending    = Number(totals.cc_spending    || 0);
  const payments    = Number(totals.cc_payments    || 0);
  const adjustments = Number(totals.cc_adjustments || 0);
  const netActivity = Number(totals.cc_balance     || 0);
  const netColor    = netActivity > 0 ? 'var(--danger)' : netActivity < 0 ? '#16a34a' : 'inherit';

  const row = (label, amount, color, bold, tooltip) =>
    `<div style="display:flex; justify-content:space-between; padding:5px 12px; ${bold ? 'font-weight:600; border-top:1px solid var(--border); margin-top:4px; padding-top:8px;' : ''}" ${tooltip ? `title="${tooltip}"` : ''}>
      <span style="color:var(--text-muted); font-size:13px;">${label}</span>
      <span class="mono" style="font-size:13px;${color ? ' color:' + color : ''}">${amount}</span>
    </div>`;

  body.innerHTML =
    row('Purchases (actual charges)', '$' + f2(spending), null, false) +
    row('Payments to Card',           '$' + f2(payments), null, false) +
    row('Credits & Adjustments',      '$' + f2(adjustments), null, false) +
    row('Net Activity This Period',   '$' + f2(netActivity), netColor, true,
        'Spending minus payments minus adjustments for the filtered period. Not the actual card balance.');

  panel.style.display = '';
}

// ── Transaction Notes ─────────────────────────────────────────

/** Open an inline note editor below the button. */
function openNoteEdit(fp, btnEl) {
  // Close any existing note editor
  document.querySelectorAll('.note-editor-popup').forEach(el => el.remove());

  const td = btnEl.closest('td');
  const tr = btnEl.closest('tr');
  // Find existing note from the button's title (stored there during render)
  const currentNote = btnEl.title === 'Add note' ? '' : btnEl.title;

  const editor = document.createElement('div');
  editor.className = 'note-editor-popup';
  editor.innerHTML = `
    <textarea class="note-textarea" rows="2" placeholder="Add a note...">${esc(currentNote)}</textarea>
    <div style="display:flex; gap:4px; justify-content:flex-end; margin-top:4px;">
      <button class="btn btn-secondary btn-sm" onclick="this.closest('.note-editor-popup').remove()">Cancel</button>
      <button class="btn btn-primary btn-sm" onclick="saveNote('${esc(fp)}', this)">Save</button>
    </div>
  `;
  td.style.position = 'relative';
  td.appendChild(editor);
  editor.querySelector('textarea').focus();

  // Save on Enter (without shift)
  editor.querySelector('textarea').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      saveNote(fp, editor.querySelector('.btn-primary'));
    }
  });
}

/** Save a note via PATCH endpoint. */
async function saveNote(fp, btnEl) {
  const popup = btnEl.closest('.note-editor-popup');
  const textarea = popup.querySelector('textarea');
  const noteText = textarea.value.trim() || null;
  try {
    await api('PATCH', `/transactions/${encodeURIComponent(fp)}`, { notes: noteText });
    // Update the button in the row
    const td = popup.closest('td');
    popup.remove();
    const noteBtn = td.querySelector('.btn-note');
    if (noteBtn) {
      noteBtn.title = noteText || 'Add note';
      noteBtn.innerHTML = noteText ? '&#9998;' : '&#43;';
      noteBtn.classList.toggle('has-note', !!noteText);
    }
    toast('Note saved', 'success');
  } catch (err) {
    toast('Failed to save note: ' + err.message, 'error');
  }
}

// ── Split Transactions ────────────────────────────────────────

/** Open the split transaction modal for a given fingerprint. */
function openSplitModal(fp) {
  // Find the row data from the current table
  const tr = document.querySelector(`tr[data-fp="${fp}"]`);
  if (!tr) { toast('Transaction not found in table', 'error'); return; }
  // Get amount from the row (find the amount cell)
  const cells = tr.querySelectorAll('td');
  let amount = 0;
  cells.forEach(td => {
    const text = td.textContent.trim();
    if (text.match(/^-?\$?[\d,]+\.\d{2}$/)) {
      amount = parseFloat(text.replace(/[$,]/g, ''));
    }
  });

  const modal = document.getElementById('split-txn-modal');
  if (!modal) return;
  modal.dataset.fp = fp;
  modal.dataset.amount = amount;
  document.getElementById('split-parent-amount').textContent = _fmt$(amount);
  _renderSplitRows(amount, 2);
  modal.classList.remove('hidden');
}

function closeSplitModal() {
  document.getElementById('split-txn-modal')?.classList.add('hidden');
}

/** Render N split input rows in the modal. */
function _renderSplitRows(parentAmount, count) {
  const container = document.getElementById('split-rows-container');
  if (!container) return;
  const splitAmt = Math.round((parentAmount / count) * 100) / 100;
  let html = '';
  for (let i = 0; i < count; i++) {
    const amt = i === count - 1 ? Math.round((parentAmount - splitAmt * (count - 1)) * 100) / 100 : splitAmt;
    html += `<div class="split-row" data-idx="${i}">
      <input type="text" class="form-control split-category" placeholder="Category" style="flex:2;" />
      <input type="number" class="form-control split-amount" step="0.01" value="${amt}" style="flex:1;" onchange="_updateSplitRemaining()" />
      <input type="text" class="form-control split-desc" placeholder="Description (optional)" style="flex:2;" />
    </div>`;
  }
  container.innerHTML = html;
  _updateSplitRemaining();
}

function addSplitRow() {
  const modal = document.getElementById('split-txn-modal');
  const parentAmount = parseFloat(modal.dataset.amount);
  const container = document.getElementById('split-rows-container');
  const count = container.querySelectorAll('.split-row').length + 1;
  _renderSplitRows(parentAmount, count);
}

function _updateSplitRemaining() {
  const modal = document.getElementById('split-txn-modal');
  const parentAmount = parseFloat(modal.dataset.amount);
  const inputs = document.querySelectorAll('#split-rows-container .split-amount');
  let total = 0;
  inputs.forEach(inp => { total += parseFloat(inp.value) || 0; });
  const remaining = Math.round((parentAmount - total) * 100) / 100;
  const el = document.getElementById('split-remaining');
  if (el) {
    el.textContent = `Remaining: ${_fmt$(remaining)}`;
    el.style.color = Math.abs(remaining) < 0.01 ? 'var(--success)' : 'var(--danger)';
  }
}

/** Submit split to the server. */
async function submitSplit() {
  const modal = document.getElementById('split-txn-modal');
  const fp = modal.dataset.fp;
  const rows = document.querySelectorAll('#split-rows-container .split-row');
  const splits = [];
  rows.forEach(row => {
    const category = row.querySelector('.split-category').value.trim();
    const amount = parseFloat(row.querySelector('.split-amount').value);
    const description = row.querySelector('.split-desc').value.trim();
    const s = { amount };
    if (category) s.category = category;
    if (description) s.description = description;
    splits.push(s);
  });
  try {
    const result = await api('POST', `/transactions/${encodeURIComponent(fp)}/split`, { splits });
    toast(`Split into ${result.children} transactions`, 'success');
    closeSplitModal();
    // Reload the current tab
    const activeTab = document.querySelector('.tab-btn.active');
    if (activeTab) {
      const type = activeTab.dataset.type || 'bank';
      loadTxnTab(type);
    }
  } catch (err) {
    toast('Split failed: ' + err.message, 'error');
  }
}

/** Unsplit a transaction (called from context or a button). */
async function unsplitTransaction(parentFp) {
  if (!confirm('Remove all splits and restore the original transaction?')) return;
  try {
    const result = await api('DELETE', `/transactions/${encodeURIComponent(parentFp)}/split`);
    toast(`Removed ${result.children_removed} split(s)`, 'success');
    const activeTab = document.querySelector('.tab-btn.active');
    if (activeTab) {
      const type = activeTab.dataset.type || 'bank';
      loadTxnTab(type);
    }
  } catch (err) {
    toast('Unsplit failed: ' + err.message, 'error');
  }
}


// ── Merchant Intelligence ─────────────────────────────────────

let _miSearchTimer = null;
let _miDateFrom = null;
let _miDateTo = null;
let _miYearsPopulated = false;

function _debouncedMerchantSearch() {
  clearTimeout(_miSearchTimer);
  _miSearchTimer = setTimeout(loadMerchantAnalytics, 300);
}

function setMiDatePreset(preset) {
  if (preset === 'all') {
    _miDateFrom = null;
    _miDateTo = null;
  } else if (preset === 'year') {
    const yr = parseInt(document.getElementById('mi-year')?.value);
    if (!yr) return;
    const { from, to } = _presetDates('all', yr);
    _miDateFrom = from;
    _miDateTo = to;
  } else {
    const { from, to } = _presetDates(preset);
    _miDateFrom = from;
    _miDateTo = to;
  }
  // Update active state on preset buttons
  document.querySelectorAll('.mi-preset').forEach(b => b.classList.remove('active'));
  if (preset !== 'year') {
    const active = document.querySelector(`.mi-preset[data-preset="${preset}"]`);
    if (active) active.classList.add('active');
    const yearSel = document.getElementById('mi-year');
    if (yearSel) yearSel.value = '';
  } else {
    // Year dropdown selected — no preset button active
  }
  loadMerchantAnalytics();
}

async function _populateMiYears() {
  if (_miYearsPopulated) return;
  const sel = document.getElementById('mi-year');
  if (!sel) return;
  try {
    const [cc, bank] = await Promise.all([
      api('GET', '/transactions/years?type=credit_card').catch(() => ({ years: [] })),
      api('GET', '/transactions/years?type=bank').catch(() => ({ years: [] })),
    ]);
    const years = [...new Set([...(cc.years || []), ...(bank.years || [])])].sort((a, b) => b - a);
    years.forEach(y => {
      const opt = document.createElement('option');
      opt.value = y;
      opt.textContent = y;
      sel.appendChild(opt);
    });
    _miYearsPopulated = true;
  } catch (_) {}
}

async function loadMerchantAnalytics() {
  _populateMiYears();
  const listEl = document.getElementById('mi-list');
  const sortBy = document.getElementById('mi-sort')?.value || 'total_spend';
  const search = document.getElementById('mi-search')?.value?.trim() || '';
  if (!listEl) return;
  listEl.innerHTML = '<span style="color:var(--text-muted);font-size:13px;">Loading…</span>';

  let url = `/merchant-analytics?sort_by=${sortBy}&limit=100`;
  if (search) url += `&search=${encodeURIComponent(search)}`;
  if (_miDateFrom) url += `&date_from=${encodeURIComponent(_miDateFrom)}`;
  if (_miDateTo) url += `&date_to=${encodeURIComponent(_miDateTo)}`;

  try {
    const data = await api('GET', url);
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    set('mi-total', String(data.total_merchants));
    set('mi-accel', String(data.accelerating_count));
    set('mi-shown', String(data.merchants.length));

    if (!data.merchants.length) {
      listEl.innerHTML = '<span style="color:var(--text-muted);font-size:13px;">No merchants found.</span>';
      return;
    }
    const maxSpend = Math.max(...data.merchants.map(m => m.total_spend), 1);
    listEl.innerHTML = data.merchants.map(m => {
      const barPct = Math.round(m.total_spend / maxSpend * 100);
      const trendArrow = m.trend === 'increasing' ? '▲' : m.trend === 'decreasing' ? '▼' : '→';
      const trendColor = m.trend === 'increasing' ? '#ef4444' : m.trend === 'decreasing' ? '#22c55e' : 'var(--text-muted)';
      const accelBadge = m.accelerating
        ? '<span class="mi-accel-badge">Accelerating</span>' : '';
      const lastDate = m.last_date ? m.last_date.substring(0, 10) : '—';

      // Mini sparkline from monthly_data (up to 3 bars)
      let sparkline = '';
      if (m.monthly_data && m.monthly_data.length > 0) {
        const maxM = Math.max(...m.monthly_data.map(d => d.spend), 1);
        sparkline = '<div class="mi-spark">' + m.monthly_data.map(d => {
          const h = Math.max(Math.round(d.spend / maxM * 24), 2);
          return `<div class="mi-spark-bar" style="height:${h}px;" title="${_MONTH_NAMES[d.month-1]}: ${_fmt$(d.spend)}"></div>`;
        }).join('') + '</div>';
      }

      return `<div class="mi-row">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <div style="display:flex; align-items:center; gap:8px;">
            <span class="mi-merchant-name">${esc(m.merchant)}</span>
            ${accelBadge}
          </div>
          <div style="display:flex; align-items:center; gap:12px;">
            ${sparkline}
            <span class="mi-trend" style="color:${trendColor};" title="MoM trend: ${m.trend_pct}%">${trendArrow} ${Math.abs(m.trend_pct)}%</span>
            <span class="mi-amount">${_fmt$(m.total_spend)}</span>
          </div>
        </div>
        <div class="mi-bar-track"><div class="mi-bar-fill" style="width:${barPct}%;"></div></div>
        <div class="mi-meta">
          <span>${m.txn_count} txns</span>
          <span>Avg ${_fmt$(m.monthly_avg)}/mo</span>
          <span>${m.months_active} mo active</span>
          <span>Last: ${lastDate}</span>
        </div>
      </div>`;
    }).join('');
  } catch (err) {
    listEl.innerHTML = `<span style="color:var(--danger);font-size:13px;">Error: ${esc(err.message)}</span>`;
  }
}

// ── Merchant Rules page ───────────────────────────────────────

let _editingRuleId = null; // null = creating new rule

// ── Condition group helpers ────────────────────────────────────

function _makeConditionRow(pattern, matchType, negate) {
  const row = document.createElement('div');
  row.className = 'rf-condition-row';
  row.style.cssText = 'display:flex; align-items:center; gap:8px; background:var(--bg-alt,#f8f9fa); border-radius:6px; padding:6px 10px;';

  const sel = document.createElement('select');
  sel.className = 'rf-cond-type';
  sel.style.cssText = 'width:auto; flex-shrink:0; padding:4px 6px; border-radius:5px; border:1px solid var(--border); font-size:12px;';
  ['contains', 'startswith', 'regex'].forEach(t => {
    const opt = document.createElement('option');
    opt.value = t;
    opt.textContent = t;
    opt.selected = (t === matchType);
    sel.appendChild(opt);
  });

  const inp = document.createElement('input');
  inp.type = 'text';
  inp.className = 'rf-cond-pattern';
  inp.placeholder = 'e.g. AMAZON, ^UBER, .*COFFEE.*';
  inp.value = pattern || '';
  inp.style.cssText = 'flex:1; min-width:80px; width:auto; padding:4px 8px; border-radius:5px; border:1px solid var(--border); font-size:12px; font-family:monospace; background:var(--card-bg,#fff); color:var(--text,#222);';

  const label = document.createElement('label');
  label.style.cssText = 'display:flex; align-items:center; gap:4px; font-size:12px; white-space:nowrap; cursor:pointer; flex-shrink:0;';
  const cb = document.createElement('input');
  cb.type = 'checkbox';
  cb.className = 'rf-cond-negate';
  cb.checked = !!negate;
  cb.style.cursor = 'pointer';
  label.appendChild(cb);
  label.appendChild(document.createTextNode(' NOT'));

  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'btn btn-secondary btn-sm rf-cond-remove';
  btn.textContent = '\u2715';
  btn.title = 'Remove condition';
  btn.style.cssText = 'font-size:12px; padding:2px 8px; flex-shrink:0;';
  btn.addEventListener('click', function() { _removeConditionRow(this); });

  row.appendChild(sel);
  row.appendChild(inp);
  row.appendChild(label);
  row.appendChild(btn);
  return row;
}

function _makeGroupBlock(groupLogic, conditions) {
  const block = document.createElement('div');
  block.className = 'rf-group-block';
  block.style.cssText = 'border:1px solid var(--border); border-radius:8px; padding:10px 12px;';

  // Header row: label + logic selector + remove group button
  const header = document.createElement('div');
  header.style.cssText = 'display:flex; align-items:center; justify-content:space-between; margin-bottom:8px;';
  const lbl = document.createElement('span');
  lbl.style.cssText = 'font-size:13px; font-weight:600;';
  lbl.textContent = 'Match Conditions';

  const right = document.createElement('div');
  right.style.cssText = 'display:flex; align-items:center; gap:6px; font-size:13px;';
  const logicLabel = document.createElement('span');
  logicLabel.style.cssText = 'color:var(--text-muted);';
  logicLabel.textContent = 'Combine with:';
  const logicSel = document.createElement('select');
  logicSel.className = 'rf-group-logic';
  logicSel.style.cssText = 'width:auto; padding:4px 8px; border-radius:6px; border:1px solid var(--border); font-size:13px;';
  [['AND', 'AND \u2014 all must match'], ['OR', 'OR \u2014 any must match']].forEach(([val, text]) => {
    const opt = document.createElement('option');
    opt.value = val; opt.textContent = text; opt.selected = (val === groupLogic);
    logicSel.appendChild(opt);
  });

  const removeBtn = document.createElement('button');
  removeBtn.type = 'button';
  removeBtn.className = 'btn btn-secondary btn-sm rf-group-remove';
  removeBtn.textContent = 'Remove Group';
  removeBtn.style.cssText = 'font-size:11px; padding:2px 8px; margin-left:8px;';
  removeBtn.addEventListener('click', function() { _removeGroup(this); });

  right.appendChild(logicLabel);
  right.appendChild(logicSel);
  right.appendChild(removeBtn);
  header.appendChild(lbl);
  header.appendChild(right);
  block.appendChild(header);

  // Conditions container
  const condContainer = document.createElement('div');
  condContainer.className = 'rf-group-conditions';
  condContainer.style.cssText = 'display:flex; flex-direction:column; gap:8px; margin-bottom:8px;';
  block.appendChild(condContainer);

  // Add Condition button
  const addBtn = document.createElement('button');
  addBtn.type = 'button';
  addBtn.className = 'btn btn-secondary btn-sm';
  addBtn.textContent = '+ Add Condition';
  addBtn.style.cssText = 'font-size:12px;';
  addBtn.addEventListener('click', function() { _addConditionToGroup(this.closest('.rf-group-block')); });
  block.appendChild(addBtn);

  // Populate conditions
  if (conditions && conditions.length) {
    conditions.forEach(c => {
      condContainer.appendChild(_makeConditionRow(c.pattern, c.match_type || 'contains', !!c.negate));
    });
  } else {
    condContainer.appendChild(_makeConditionRow('', 'contains', false));
  }

  _updateGroupUI();
  return block;
}

function _addConditionToGroup(groupBlock) {
  const container = groupBlock.querySelector('.rf-group-conditions');
  if (!container) return;
  container.appendChild(_makeConditionRow('', 'contains', false));
  _updateGroupUI();
}

function _removeConditionRow(btn) {
  const groupBlock = btn.closest('.rf-group-block');
  const rows = groupBlock.querySelectorAll('.rf-condition-row');
  if (rows.length <= 1) return;
  btn.closest('.rf-condition-row').remove();
  _updateGroupUI();
}

function _removeGroup(btn) {
  const groups = document.querySelectorAll('#rf-groups .rf-group-block');
  if (groups.length <= 1) return;
  btn.closest('.rf-group-block').remove();
  _updateGroupUI();
}

function _updateGroupUI() {
  const groups = document.querySelectorAll('#rf-groups .rf-group-block');
  // Show/hide remove group buttons — hide when only 1 group
  groups.forEach(g => {
    const removeBtn = g.querySelector('.rf-group-remove');
    if (removeBtn) removeBtn.style.display = groups.length > 1 ? '' : 'none';
    // Show/hide logic selector when 2+ conditions in group
    const rows = g.querySelectorAll('.rf-condition-row');
    const logicSel = g.querySelector('.rf-group-logic');
    const logicLabel = logicSel ? logicSel.previousElementSibling : null;
    if (logicSel) logicSel.style.display = rows.length >= 2 ? '' : 'none';
    if (logicLabel) logicLabel.style.display = rows.length >= 2 ? '' : 'none';
    // Show/hide condition remove buttons — keep at least one
    g.querySelectorAll('.rf-cond-remove').forEach(b => {
      b.style.visibility = rows.length > 1 ? 'visible' : 'hidden';
    });
  });
}

function addConditionGroup(groupLogic = 'AND', conditions = null) {
  const container = document.getElementById('rf-groups');
  if (!container) return;
  container.appendChild(_makeGroupBlock(groupLogic, conditions));
  _updateGroupUI();
}

// Legacy compatibility wrappers
function addConditionRow(pattern = '', matchType = 'contains', negate = false) {
  // Add to the last group, or create one if none exist
  const groups = document.querySelectorAll('#rf-groups .rf-group-block');
  if (!groups.length) { addConditionGroup('AND', [{pattern, match_type: matchType, negate}]); return; }
  const lastGroup = groups[groups.length - 1];
  _addConditionToGroup(lastGroup);
  // Set values on the newly added row
  const rows = lastGroup.querySelectorAll('.rf-condition-row');
  const lastRow = rows[rows.length - 1];
  if (pattern) lastRow.querySelector('.rf-cond-pattern').value = pattern;
  if (matchType !== 'contains') lastRow.querySelector('.rf-cond-type').value = matchType;
  if (negate) lastRow.querySelector('.rf-cond-negate').checked = true;
}

function _getRuleConditions() {
  // Returns grouped conditions structure
  const groups = document.querySelectorAll('#rf-groups .rf-group-block');
  const result = [];
  groups.forEach(g => {
    const logicSel = g.querySelector('.rf-group-logic');
    const groupLogic = logicSel ? logicSel.value : 'AND';
    const rows = g.querySelectorAll('.rf-condition-row');
    const conditions = Array.from(rows).map(row => ({
      pattern:    row.querySelector('.rf-cond-pattern').value.trim(),
      match_type: row.querySelector('.rf-cond-type').value,
      negate:     row.querySelector('.rf-cond-negate').checked,
    }));
    result.push({ group_logic: groupLogic, conditions });
  });
  return { groups: result };
}

function _setRuleConditions(conditionsData, logic) {
  const container = document.getElementById('rf-groups');
  if (!container) return;
  container.innerHTML = '';
  // Handle grouped format: {groups: [...]}
  if (conditionsData && conditionsData.groups) {
    conditionsData.groups.forEach(g => {
      addConditionGroup(g.group_logic || 'AND', g.conditions);
    });
  } else if (Array.isArray(conditionsData) && conditionsData.length) {
    // Legacy flat array — single group
    addConditionGroup(logic || 'AND', conditionsData);
  } else {
    // Empty — one default group with one empty condition
    addConditionGroup('AND', null);
  }
  _updateGroupUI();
}

// ── Merchant rules CRUD ────────────────────────────────────────

function _rulePatternSummary(r) {
  if (r.conditions && r.conditions.groups) {
    return r.conditions.groups.map(g => {
      const parts = (g.conditions || []).map(c => `${c.negate ? 'NOT ' : ''}${esc(c.match_type)} "${esc(c.pattern)}"`);
      const inner = parts.join(` <span style="color:var(--text-muted);font-size:10px;">${esc(g.group_logic || 'AND')}</span> `);
      return r.conditions.groups.length > 1 ? `(${inner})` : inner;
    }).join(' <span style="color:var(--text-muted);font-size:10px;">AND</span> ');
  }
  return `<span class="mono">${esc(r.pattern)}</span>`;
}

let _allMerchantRules = []; // cached for search filtering

async function loadMerchantRules() {
  const tbody = document.getElementById('merchant-rules-tbody');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted" style="padding:24px">Loading…</td></tr>';
  try {
    const data = await api('GET', '/merchant-rules');
    _allMerchantRules = data.rules || [];
    if (!_allMerchantRules.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted" style="padding:24px">No rules yet. Click "+ Add Rule" to create one.</td></tr>';
      _updateBadge('merchant-rules-count', 0);
      _updateMerchantRuleSearchCount();
      return;
    }
    _updateBadge('merchant-rules-count', _allMerchantRules.length);
    _renderMerchantRuleRows(_allMerchantRules);
    _updateMerchantRuleSearchCount();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5" class="text-center text-muted">Error: ${esc(err.message)}</td></tr>`;
  }
}

function _renderMerchantRuleRows(rules) {
  const tbody = document.getElementById('merchant-rules-tbody');
  if (!tbody) return;
  tbody.innerHTML = rules.map(r => `<tr>
    <td class="text-right">${esc(String(r.priority))}</td>
    <td><span class="badge badge-running" style="font-size:11px;">${esc(r.match_type)}</span></td>
    <td style="font-size:12px;">${_rulePatternSummary(r)}</td>
    <td>${esc(r.merchant)}</td>
    <td>
      <div style="display:flex;gap:6px;">
        <button class="btn btn-secondary btn-sm" onclick="openRuleForm(${r.id})">Edit</button>
        <button class="btn btn-danger btn-sm" onclick="deleteRule(${r.id})">Delete</button>
      </div>
    </td>
  </tr>`).join('');
}

function filterMerchantRules() {
  const input = document.getElementById('merchant-rules-search');
  const clearBtn = document.getElementById('merchant-rules-search-clear');
  const query = (input?.value || '').toLowerCase();
  clearBtn.style.display = query ? '' : 'none';
  if (!query) {
    _renderMerchantRuleRows(_allMerchantRules);
    _updateMerchantRuleSearchCount();
    return;
  }
  const filtered = _allMerchantRules.filter(r => {
    const pattern = (r.pattern || '').toLowerCase();
    const merchant = (r.merchant || '').toLowerCase();
    const matchType = (r.match_type || '').toLowerCase();
    // Also search inside grouped conditions
    let condText = '';
    if (r.conditions && r.conditions.groups) {
      condText = r.conditions.groups.flatMap(g => (g.conditions || []).map(c => c.pattern || '')).join(' ').toLowerCase();
    }
    return pattern.includes(query) || merchant.includes(query) || matchType.includes(query) || condText.includes(query);
  });
  if (filtered.length) {
    _renderMerchantRuleRows(filtered);
  } else {
    document.getElementById('merchant-rules-tbody').innerHTML =
      `<tr><td colspan="5" class="text-center text-muted" style="padding:24px">No rules match '${esc(query)}'</td></tr>`;
  }
  _updateMerchantRuleSearchCount(filtered.length);
}

function _updateMerchantRuleSearchCount(shown) {
  const el = document.getElementById('merchant-rules-search-count');
  if (!el) return;
  const query = (document.getElementById('merchant-rules-search')?.value || '').trim();
  if (!query || !_allMerchantRules.length) { el.textContent = ''; return; }
  el.textContent = `${shown ?? _allMerchantRules.length} of ${_allMerchantRules.length} rules`;
}

function openRuleForm(ruleId) {
  _editingRuleId = ruleId;
  ensureCardExpanded('panel-merchant-rules');
  const card = document.getElementById('rule-form-card');
  const title = document.getElementById('rule-form-title');
  card.style.display = '';
  title.textContent = ruleId ? 'Edit Rule' : 'Add Rule';
  document.getElementById('rf-test-result').textContent = '';
  document.getElementById('rf-test-matches').style.display = 'none';

  if (!ruleId) {
    document.getElementById('rf-priority').value = '0';
    document.getElementById('rf-merchant').value = '';
    _setRuleConditions(null, 'AND');
    return;
  }

  api('GET', '/merchant-rules').then(data => {
    const rule = data.rules.find(r => r.id === ruleId);
    if (!rule) return;
    document.getElementById('rf-priority').value = String(rule.priority);
    document.getElementById('rf-merchant').value = rule.merchant;
    if (rule.conditions && rule.conditions.groups) {
      _setRuleConditions(rule.conditions, rule.logic);
    } else if (rule.conditions && Array.isArray(rule.conditions)) {
      _setRuleConditions(rule.conditions, rule.logic);
    } else {
      _setRuleConditions({groups: [{group_logic: 'AND', conditions: [{pattern: rule.pattern, match_type: rule.match_type, negate: false}]}]}, 'AND');
    }
  });
}

function closeRuleForm() {
  _editingRuleId = null;
  _testMatches = [];
  document.getElementById('rule-form-card').style.display = 'none';
}

async function saveRule() {
  const merchant = document.getElementById('rf-merchant').value.trim();
  if (!merchant) {
    toast('Merchant name is required.', 'error');
    return;
  }
  // Get grouped conditions and strip empty patterns
  const grouped = _getRuleConditions();
  grouped.groups = grouped.groups.map(g => ({
    ...g,
    conditions: g.conditions.filter(c => c.pattern),
  })).filter(g => g.conditions.length > 0);
  if (!grouped.groups.length) {
    toast('At least one condition pattern is required.', 'error');
    return;
  }
  // Use first condition of first group as legacy pattern/match_type
  const firstCond = grouped.groups[0].conditions[0];
  const body = {
    pattern:    firstCond.pattern,
    match_type: firstCond.match_type,
    merchant,
    priority:   parseInt(document.getElementById('rf-priority').value, 10) || 0,
    conditions: grouped,
    logic:      grouped.groups[0].group_logic || 'AND',
  };
  try {
    if (_editingRuleId) {
      await api('PUT', `/merchant-rules/${_editingRuleId}`, body);
      toast('Rule updated.', 'success');
    } else {
      await api('POST', '/merchant-rules', body);
      toast('Rule created.', 'success');
    }
    closeRuleForm();
    loadMerchantRules();
  } catch (err) {
    toast(`Failed to save rule: ${err.message}`, 'error');
  }
}

async function deleteRule(ruleId) {
  if (!confirm('Delete this merchant rule?')) return;
  try {
    await api('DELETE', `/merchant-rules/${ruleId}`);
    toast('Rule deleted.', 'success');
    loadMerchantRules();
  } catch (err) {
    toast(`Failed to delete rule: ${err.message}`, 'error');
  }
}

let _testMatches = [];
const _TEST_PAGE = 5;

function _renderTestMatches(showCount) {
  const matchesEl = document.getElementById('rf-test-matches');
  if (!_testMatches.length) return;
  const visible = _testMatches.slice(0, showCount);
  const remaining = _testMatches.length - visible.length;
  matchesEl.innerHTML =
    visible.map(m => {
      const desc = m.description ?? m;
      const cnt  = m.count;
      return `<div style="display:flex; justify-content:space-between; padding:3px 0; border-bottom:1px solid var(--border); word-break:break-all;">
        <span class="mono" style="font-size:12px;">${esc(desc)}</span>
        ${cnt != null ? `<span style="flex-shrink:0; margin-left:8px; font-size:11px; color:var(--text-muted); white-space:nowrap;">${cnt} tx</span>` : ''}
      </div>`;
    }).join('') +
    (remaining > 0
      ? `<button class="btn btn-secondary btn-sm" onclick="_loadMoreTestMatches(${showCount})"
           style="margin-top:6px; font-size:12px;">Load ${Math.min(remaining, _TEST_PAGE)} more (${remaining} remaining)</button>`
      : '');
  matchesEl.style.display = '';
}

function _loadMoreTestMatches(currentCount) {
  _renderTestMatches(currentCount + _TEST_PAGE);
}

async function testRule() {
  const resultEl = document.getElementById('rf-test-result');
  const matchesEl = document.getElementById('rf-test-matches');
  resultEl.textContent = 'Testing\u2026';
  matchesEl.style.display = 'none';
  _testMatches = [];

  // Get grouped conditions and strip empty patterns
  const grouped = _getRuleConditions();
  grouped.groups = grouped.groups.map(g => ({
    ...g,
    conditions: g.conditions.filter(c => c.pattern),
  })).filter(g => g.conditions.length > 0);
  if (!grouped.groups.length) {
    resultEl.textContent = 'Enter at least one condition pattern first.';
    return;
  }
  const firstCond = grouped.groups[0].conditions[0];
  const body = {
    pattern:    firstCond.pattern,
    match_type: firstCond.match_type,
    merchant:   document.getElementById('rf-merchant').value.trim() || 'Test',
    priority:   parseInt(document.getElementById('rf-priority').value, 10) || 0,
    conditions: grouped,
    logic:      grouped.groups[0].group_logic || 'AND',
  };
  try {
    const data = await api('POST', '/merchant-rules/test', body);
    const uniqueCount = data.total_matches ?? data.matches.length;
    const txCount     = data.total_transactions;
    if (!data.matches.length) {
      resultEl.textContent = `No matches found (${data.total_sampled} unique descriptions scanned).`;
    } else {
      const txNote = txCount != null ? `, ${txCount} total transaction${txCount !== 1 ? 's' : ''}` : '';
      const moreNote = uniqueCount > data.matches.length ? ` — showing first ${data.matches.length}` : '';
      resultEl.textContent = `${uniqueCount} unique description${uniqueCount !== 1 ? 's' : ''} matched${txNote}${moreNote}:`;
      _testMatches = data.matches;
      _renderTestMatches(_TEST_PAGE);
    }
  } catch (err) {
    resultEl.textContent = `Error: ${err.message}`;
  }
}

// ── Re-normalization ──────────────────────────────────────────

let _renormJobId = null;
let _renormPollInterval = null;

async function startRenormalize() {
  if (!confirm('Re-apply all merchant rules to every transaction in the ledger? This may take a moment.')) return;
  const statusEl = document.getElementById('renorm-status');
  statusEl.textContent = 'Starting…';
  try {
    const data = await api('POST', '/normalize/apply');
    _renormJobId = data.job_id;
    statusEl.textContent = `Job ${_renormJobId}: pending…`;
    _pollRenorm();
  } catch (err) {
    statusEl.textContent = `Error: ${err.message}`;
  }
}

function _pollRenorm() {
  if (_renormPollInterval) clearInterval(_renormPollInterval);
  _renormPollInterval = setInterval(async () => {
    if (!_renormJobId) { clearInterval(_renormPollInterval); return; }
    try {
      const data = await api('GET', `/normalize/${_renormJobId}`);
      const statusEl = document.getElementById('renorm-status');
      const pct = data.rows_total ? Math.round((data.rows_done / data.rows_total) * 100) : 0;
      if (data.status === 'running') {
        statusEl.textContent = `Running… ${data.rows_done}/${data.rows_total || '?'} rows (${pct}%)`;
      } else if (data.status === 'success') {
        statusEl.textContent = `Done — ${data.rows_done} rows updated.`;
        clearInterval(_renormPollInterval);
        _renormJobId = null;
        loadHistory();
      } else if (data.status === 'failed') {
        statusEl.textContent = `Failed: ${data.error || 'unknown error'}`;
        clearInterval(_renormPollInterval);
        _renormJobId = null;
      }
    } catch (_) {}
  }, 1500);
}



// ── Rule Suggestions ──────────────────────────────────────────

let _ruleSuggestions = [];   // {pattern, match_type, merchant, count, num_variants, sample_descriptions}
let _catSuggestions  = [];   // {merchant, suggested_category, confidence}

let _lowFreqSuggestions = [];   // low-frequency rule suggestions

function _clearSuggestions() {
  _ruleSuggestions = [];
  _lowFreqSuggestions = [];
  const rl = document.getElementById('rule-suggestions-list');
  if (rl) rl.innerHTML = '';
  const raBtn = document.getElementById('rule-suggest-accept-all');
  if (raBtn) raBtn.style.display = 'none';
  const rs = document.getElementById('rule-suggest-status');
  if (rs) rs.textContent = '';
  const lf = document.getElementById('low-freq-list');
  if (lf) lf.innerHTML = '';
  const lfs = document.getElementById('low-freq-section');
  if (lfs) lfs.style.display = 'none';
}

async function loadRuleSuggestions() {
  const statusEl = document.getElementById('rule-suggest-status');
  const listEl   = document.getElementById('rule-suggestions-list');
  const acceptAllBtn = document.getElementById('rule-suggest-accept-all');
  if (!listEl) return;

  statusEl.textContent = 'Analyzing…';
  listEl.innerHTML = `<div style="color:var(--text-muted);font-size:13px;padding:8px 0;">
    Scanning transaction descriptions with fuzzy matching — this may take a moment…
  </div>`;
  acceptAllBtn.style.display = 'none';

  try {
    const data = await api('GET', '/merchant-rules/suggestions?include_low_frequency=true');
    _ruleSuggestions = data.suggestions || [];
    _lowFreqSuggestions = data.low_frequency || [];

    if (!_ruleSuggestions.length && !_lowFreqSuggestions.length) {
      statusEl.textContent = 'No new suggestions found.';
      listEl.innerHTML = `<span style="color:var(--text-muted);font-size:13px;">
        All common patterns are already covered by your existing rules, or you don't have enough transaction data yet.
      </span>`;
      return;
    }

    const parts = [];
    if (_ruleSuggestions.length) parts.push(`${_ruleSuggestions.length} suggestion${_ruleSuggestions.length > 1 ? 's' : ''}`);
    if (_lowFreqSuggestions.length) parts.push(`${_lowFreqSuggestions.length} low-frequency`);
    statusEl.textContent = parts.join(' + ') + ' found';
    if (_ruleSuggestions.length) acceptAllBtn.style.display = '';
    _renderRuleSuggestions();
    _renderLowFreqSuggestions();
  } catch (err) {
    statusEl.textContent = `Error: ${err.message}`;
    listEl.innerHTML = '';
  }
}

async function autoNormalizeUnmatched() {
  const btn = document.getElementById('auto-fill-btn');
  if (!btn) return;
  btn.disabled = true;
  const origText = btn.textContent;
  btn.textContent = 'Working…';
  try {
    const r = await api('POST', '/normalize/auto-fill');
    toast(`Auto-filled ${r.rows_updated} transaction${r.rows_updated !== 1 ? 's' : ''}`, 'success');
    loadMerchantAnalytics();
    loadUtilHealth();
  } catch (e) {
    toast('Auto-fill failed: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = origText;
  }
}

function toggleLowFreqSection() {
  const cb = document.getElementById('show-low-freq');
  const list = document.getElementById('low-freq-list');
  if (list) list.style.display = cb && cb.checked ? '' : 'none';
}

function _renderRuleSuggestions() {
  const listEl = document.getElementById('rule-suggestions-list');
  if (!listEl) return;
  const visible = _ruleSuggestions.filter(s => !s._dismissed);
  _updateBadge('rule-suggest-count', visible.length);
  if (!visible.length) {
    listEl.innerHTML = '<span style="color:var(--text-muted);font-size:13px;">All suggestions have been reviewed.</span>';
    document.getElementById('rule-suggest-accept-all').style.display = 'none';
    return;
  }
  listEl.innerHTML = visible.map((s, visIdx) => {
    const realIdx = _ruleSuggestions.indexOf(s);
    return _renderSuggestionRow(s, realIdx, 'std');
  }).join('');
}

function _renderLowFreqSuggestions() {
  const section = document.getElementById('low-freq-section');
  const listEl = document.getElementById('low-freq-list');
  if (!section || !listEl) return;
  if (!_lowFreqSuggestions.length) { section.style.display = 'none'; return; }
  section.style.display = '';
  _updateBadge('low-freq-count', _lowFreqSuggestions.length);
  const cb = document.getElementById('show-low-freq');
  listEl.style.display = cb && cb.checked ? '' : 'none';
  const visible = _lowFreqSuggestions.filter(s => !s._dismissed);
  listEl.innerHTML = visible.map((s, visIdx) => {
    const realIdx = _lowFreqSuggestions.indexOf(s);
    return _renderSuggestionRow(s, realIdx, 'lf');
  }).join('');
}

function _renderSuggestionRow(s, idx, pool) {
  const samples = (s.sample_descriptions || []).slice(0, 3).map(d => `<span class="mono" style="font-size:11px;">${esc(d)}</span>`).join('<br>');
  const matchBadgeColor = s.match_type === 'startswith' ? '#3b82f6' : '#8b5cf6';
  const variantNote = s.num_variants > 1 ? ` · ${s.num_variants} variants` : '';
  const fuzzyBadge = s.fuzzy_merged ? '<span style="font-size:10px; font-weight:600; background:#f59e0b22; color:#d97706; border-radius:4px; padding:1px 5px; margin-left:2px;">fuzzy</span>' : '';
  const mergedInfo = s.fuzzy_merged && s.merged_cores && s.merged_cores.length > 1
    ? `<div style="color:#d97706; font-size:10px; margin-top:2px;">Merged cores: ${s.merged_cores.map(c => esc(c)).join(', ')}</div>` : '';
  const acceptFn = pool === 'lf' ? 'acceptLowFreqSuggestion' : 'acceptRuleSuggestion';
  const editFn   = pool === 'lf' ? 'editLowFreqSuggestion'   : 'editRuleSuggestion';
  const dismissFn= pool === 'lf' ? 'dismissLowFreqSuggestion': 'dismissRuleSuggestion';
  return `
    <div style="display:flex; gap:12px; align-items:flex-start; padding:10px 12px; background:var(--bg-alt,#f8faff); border-radius:8px; border:1px solid var(--border);">
      <div style="flex:1; min-width:0;">
        <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-bottom:4px;">
          <span style="font-size:11px; font-weight:600; background:${matchBadgeColor}22; color:${matchBadgeColor}; border-radius:4px; padding:2px 6px;">${esc(s.match_type)}</span>
          <span class="mono" style="font-size:13px; font-weight:600;">${esc(s.pattern)}</span>
          ${fuzzyBadge}
          <span style="color:var(--text-muted); font-size:12px;">→</span>
          <span style="font-size:13px; font-weight:500;">${esc(s.merchant)}</span>
          <span style="font-size:11px; color:var(--text-muted); background:#e2e8f0; border-radius:10px; padding:1px 8px;">${s.count} tx${variantNote}</span>
        </div>
        <div style="color:var(--text-muted); font-size:11px; line-height:1.6;">${samples}</div>
        ${mergedInfo}
      </div>
      <div style="display:flex; gap:6px; flex-shrink:0;">
        <button class="btn btn-primary btn-sm" onclick="${acceptFn}(${idx})" title="Create this rule">✓ Accept</button>
        <button class="btn btn-secondary btn-sm" onclick="${editFn}(${idx})" title="Edit before saving">Edit</button>
        <button class="btn btn-secondary btn-sm" style="color:var(--text-muted); font-size:11px;" onclick="${dismissFn}(${idx})" title="Dismiss">Dismiss</button>
      </div>
    </div>`;
}

async function acceptRuleSuggestion(idx) {
  const s = _ruleSuggestions[idx];
  if (!s) return;
  try {
    await api('POST', '/merchant-rules', {
      pattern: s.pattern, match_type: s.match_type,
      merchant: s.merchant, priority: 0,
    });
    s._dismissed = true;
    toast(`Rule created: "${s.pattern}" → ${s.merchant}`, 'success');
    _renderRuleSuggestions();
    loadMerchantRules();
  } catch (err) {
    toast(`Failed: ${err.message}`, 'error');
  }
}

function editRuleSuggestion(idx) {
  const s = _ruleSuggestions[idx];
  if (!s) return;
  // Pre-fill the rule editor and scroll to it
  openRuleForm(null);
  document.getElementById('rf-priority').value = '0';
  document.getElementById('rf-merchant').value = s.merchant;
  _setRuleConditions([{pattern: s.pattern, match_type: s.match_type, negate: false}], 'AND');
  document.getElementById('rule-form-card').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  // Mark as dismissed from suggestions (will be created via the form)
  s._dismissed = true;
  _renderRuleSuggestions();
}

async function dismissRuleSuggestion(idx) {
  const s = _ruleSuggestions[idx];
  if (!s) return;
  try {
    await api('POST', `/merchant-rules/suggestions/${encodeURIComponent(s.pattern)}/dismiss`);
    s._dismissed = true;
    _renderRuleSuggestions();
  } catch (err) {
    toast(`Dismiss failed: ${err.message}`, 'error');
  }
}

async function acceptAllRuleSuggestions() {
  const visible = _ruleSuggestions.filter(s => !s._dismissed);
  if (!visible.length) return;
  let ok = 0, fail = 0;
  for (const s of visible) {
    try {
      await api('POST', '/merchant-rules', {
        pattern: s.pattern, match_type: s.match_type,
        merchant: s.merchant, priority: 0,
      });
      s._dismissed = true;
      ok++;
    } catch (_) { fail++; }
  }
  toast(`${ok} rule${ok !== 1 ? 's' : ''} created${fail ? ` (${fail} failed)` : ''}.`, ok ? 'success' : 'error');
  _renderRuleSuggestions();
  loadMerchantRules();
}

// ── Low-Frequency Suggestion Handlers ──────────────────────────

async function acceptLowFreqSuggestion(idx) {
  const s = _lowFreqSuggestions[idx];
  if (!s) return;
  try {
    await api('POST', '/merchant-rules', {
      pattern: s.pattern, match_type: s.match_type,
      merchant: s.merchant, priority: 0,
    });
    s._dismissed = true;
    toast(`Rule created: "${s.pattern}" → ${s.merchant}`, 'success');
    _renderLowFreqSuggestions();
    loadMerchantRules();
  } catch (err) {
    toast(`Failed: ${err.message}`, 'error');
  }
}

function editLowFreqSuggestion(idx) {
  const s = _lowFreqSuggestions[idx];
  if (!s) return;
  openRuleForm(null);
  document.getElementById('rf-priority').value = '0';
  document.getElementById('rf-merchant').value = s.merchant;
  _setRuleConditions([{pattern: s.pattern, match_type: s.match_type, negate: false}], 'AND');
  document.getElementById('rule-form-card').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  s._dismissed = true;
  _renderLowFreqSuggestions();
}

async function dismissLowFreqSuggestion(idx) {
  const s = _lowFreqSuggestions[idx];
  if (!s) return;
  try {
    await api('POST', `/merchant-rules/suggestions/${encodeURIComponent(s.pattern)}/dismiss`);
    s._dismissed = true;
    _renderLowFreqSuggestions();
  } catch (err) {
    toast(`Dismiss failed: ${err.message}`, 'error');
  }
}

// ── Category Suggestions ──────────────────────────────────────

async function loadCategorySuggestions() {
  const statusEl = document.getElementById('cat-suggest-status');
  const listEl   = document.getElementById('cat-suggestions-list');
  const acceptAllBtn = document.getElementById('cat-suggest-accept-all');
  if (!listEl) return;

  statusEl.textContent = 'Loading…';
  listEl.innerHTML = `<div style="color:var(--text-muted);font-size:13px;padding:4px 0;">Matching merchants against category patterns…</div>`;
  acceptAllBtn.style.display = 'none';

  try {
    const data = await api('GET', '/merchant-categories/suggestions');
    _catSuggestions = data.suggestions || [];

    if (!_catSuggestions.length) {
      statusEl.textContent = 'No suggestions found.';
      listEl.innerHTML = `<span style="color:var(--text-muted);font-size:13px;">
        Either all merchants are categorized already, or no keyword matches were found for the uncategorized ones.
      </span>`;
      return;
    }

    statusEl.textContent = `${_catSuggestions.length} suggestion${_catSuggestions.length > 1 ? 's' : ''}`;
    acceptAllBtn.style.display = '';
    _renderCategorySuggestions();
  } catch (err) {
    statusEl.textContent = `Error: ${err.message}`;
    listEl.innerHTML = '';
  }
}

function _renderCategorySuggestions() {
  const listEl = document.getElementById('cat-suggestions-list');
  if (!listEl) return;
  const visible = _catSuggestions.filter(s => !s._dismissed);
  _updateBadge('cat-suggest-count', visible.length);
  if (!visible.length) {
    listEl.innerHTML = '<span style="color:var(--text-muted);font-size:13px;">All suggestions reviewed.</span>';
    document.getElementById('cat-suggest-accept-all').style.display = 'none';
    return;
  }
  // Ensure taxonomy is loaded for picker dropdowns
  _ensureCategoryTaxonomy();
  listEl.innerHTML = visible.map(s => {
    const realIdx = _catSuggestions.indexOf(s);
    const confColor = s.confidence === 'high' ? '#16a34a' : '#d97706';
    return `
      <div style="display:flex; align-items:center; gap:10px; padding:7px 10px; background:var(--bg-alt,#f8faff); border-radius:6px; border:1px solid var(--border);">
        <span style="flex:1; font-size:13px;">${esc(s.merchant)}</span>
        <span style="color:var(--text-muted); font-size:12px;">→</span>
        <span class="cat-picker-target" id="cat-target-csug-${realIdx}"
              style="display:inline-block; min-width:160px; padding:3px 6px; font-size:12px;
                     border:1px solid var(--border); border-radius:4px; cursor:pointer;"
              onclick="openCategoryPickerForSuggestion(this, ${realIdx})">
          ${esc(s.suggested_category)}
        </span>
        <input type="hidden" id="csug-pick-${realIdx}" value="${esc(s.suggested_category)}" />
        <span style="font-size:11px; font-weight:600; color:${confColor}; background:${confColor}18; border-radius:4px; padding:2px 6px;">${s.confidence}</span>
        <button class="btn btn-primary btn-sm" onclick="acceptMerchantCatSuggestion(${realIdx})" title="Assign this category">✓</button>
        <button class="btn btn-secondary btn-sm" style="color:var(--text-muted); font-size:11px;" onclick="dismissMerchantCatSuggestion(${realIdx})" title="Dismiss">Dismiss</button>
      </div>`;
  }).join('');
}

function openCategoryPickerForSuggestion(el, idx) {
  openCategoryPicker(el, {
    currentCategory: el.textContent.trim(),
    allowRemove: false,
    allowCustom: true,
    onSave: (cat) => {
      document.getElementById('csug-pick-' + idx).value = cat.subcategory;
      el.textContent = cat.subcategory;
    },
  });
}

/** Accept a merchant→category suggestion. Operates on _catSuggestions data
 *  (from /merchant-categories/suggestions) and POSTs to /merchant-categories. */
async function acceptMerchantCatSuggestion(idx) {
  const s = _catSuggestions[idx];
  if (!s) return;
  const input = document.getElementById('csug-pick-' + idx);
  const category = input ? input.value.trim() : s.suggested_category;
  if (!category) { toast('Select a category first.', 'error'); return; }
  try {
    await api('POST', '/merchant-categories', { merchant: s.merchant, category });
    s._dismissed = true;
    toast(`"${s.merchant}" → ${category}`, 'success');
    _renderCategorySuggestions();
    loadUtilHealth();
  } catch (err) {
    toast(`Failed: ${err.message}`, 'error');
  }
}

/** Dismiss a merchant→category suggestion. Persists to DB. */
async function dismissMerchantCatSuggestion(idx) {
  const s = _catSuggestions[idx];
  if (!s) return;
  try {
    await api('POST', `/merchant-categories/suggestions/${encodeURIComponent(s.merchant)}/dismiss`);
    s._dismissed = true;
    _renderCategorySuggestions();
  } catch (err) {
    toast(`Dismiss failed: ${err.message}`, 'error');
  }
}

async function acceptAllCategorySuggestions() {
  const visible = _catSuggestions.filter(s => !s._dismissed);
  if (!visible.length) return;
  let ok = 0, fail = 0;
  for (const s of visible) {
    const realIdx = _catSuggestions.indexOf(s);
    const input = document.getElementById('csug-pick-' + realIdx);
    const category = input ? input.value.trim() : s.suggested_category;
    if (!category) { fail++; continue; }
    try {
      await api('POST', '/merchant-categories', { merchant: s.merchant, category });
      s._dismissed = true;
      ok++;
    } catch (_) { fail++; }
  }
  toast(`${ok} categor${ok !== 1 ? 'ies' : 'y'} assigned${fail ? ` (${fail} failed)` : ''}.`, ok ? 'success' : 'error');
  _renderCategorySuggestions();
  loadUtilHealth();
}

// ── Dashboard ─────────────────────────────────────────────────

let _dashYear  = new Date().getFullYear();
let _dashMonth = new Date().getMonth() + 1;

const _MONTH_NAMES = ['January','February','March','April','May','June',
                      'July','August','September','October','November','December'];

function dashboardPrevMonth() {
  _dashMonth--;
  if (_dashMonth < 1) { _dashMonth = 12; _dashYear--; }
  loadDashboard();
}
function dashboardNextMonth() {
  _dashMonth++;
  if (_dashMonth > 12) { _dashMonth = 1; _dashYear++; }
  loadDashboard();
}

async function loadDashboard() {
  const label = document.getElementById('dash-month-label');
  if (label) label.textContent = `${_MONTH_NAMES[_dashMonth - 1]} ${_dashYear}`;

  try {
    const data = await api('GET', `/dashboard/summary?year=${_dashYear}&month=${_dashMonth}`);
    _renderDashboard(data);
    _renderWeeklyRecap();
  } catch (err) {
    const el = document.getElementById('dash-mtd');
    if (el) el.textContent = 'Error loading';
  }
}

function _fmt$(v) {
  return '$' + Number(v || 0).toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2});
}

function _renderDashboard(data) {
  const set = (id, val) => { const el = document.getElementById(id); if (el) el.innerHTML = val; };

  set('dash-mtd', _fmt$(data.mtd_spend));
  set('dash-prev-spend', _fmt$(data.prev_spend || 0));

  // Unreviewed count KPI + sidebar badge
  const unrevCount = data.unreviewed_count || 0;
  set('dash-unreviewed', String(unrevCount));
  const navBadge = document.getElementById('nav-unreviewed-badge');
  if (navBadge) navBadge.textContent = unrevCount > 0 ? unrevCount : '';

  if (data.pct_change != null) {
    const arrow = data.pct_change >= 0 ? '▲' : '▼';
    const color = data.pct_change >= 0 ? '#ef4444' : '#22c55e';
    set('dash-vs-prev', `<span style="color:${color};">${arrow} ${Math.abs(data.pct_change)}% vs last month</span>`);
  } else {
    set('dash-vs-prev', 'No prior month data');
  }

  const topCat = (data.top_categories || [])[0];
  set('dash-top-cat', topCat ? esc(topCat.category_parent || '—') : '—');

  // Top categories bar chart (clickable for drill-down)
  const catList = document.getElementById('dash-cat-list');
  if (catList && data.top_categories && data.top_categories.length) {
    const maxAmt = Math.max(...data.top_categories.map(c => c.total_amount || 0), 1);
    catList.innerHTML = data.top_categories.map(c => {
      const amt = c.total_amount || 0;
      const catName = c.category_parent || '—';
      const pct = Math.round(amt / maxAmt * 100);
      const jsonParent = JSON.stringify(catName).replace(/"/g, '&quot;');
      return `<div style="margin-bottom:4px; cursor:pointer; padding:2px 4px; border-radius:4px; transition:background .12s;" onclick="openCategoryDrilldown(${jsonParent})" onmouseenter="this.style.background='var(--bg,#f1f5f9)'" onmouseleave="this.style.background=''">
        <div style="display:flex; justify-content:space-between; font-size:13px; margin-bottom:2px;">
          <span>${esc(catName)}</span>
          <span style="font-weight:600;">${_fmt$(amt)}</span>
        </div>
        <div style="background:var(--border); border-radius:4px; height:6px;">
          <div style="background:var(--primary,#3b82f6); border-radius:4px; height:6px; width:${pct}%;"></div>
        </div>
      </div>`;
    }).join('');
  } else if (catList) {
    catList.innerHTML = '<span style="color:var(--text-muted); font-size:13px;">No spending data for this month.</span>';
  }

  // Budget tracker (with green/yellow/red status)
  const budgetList = document.getElementById('dash-budget-list');
  if (budgetList) {
    const bva = data.budgets_vs_actual || [];
    if (bva.length) {
      budgetList.innerHTML = bva.map(b => {
        const pct = Math.min(b.pct || 0, 100);
        const color = b.pct >= 100 ? '#ef4444' : b.pct >= 80 ? '#f59e0b' : '#22c55e';
        const statusClass = b.pct >= 100 ? 'sa-status-red' : b.pct >= 80 ? 'sa-status-yellow' : 'sa-status-green';
        return `<div>
          <div style="display:flex; justify-content:space-between; align-items:center; font-size:12px; margin-bottom:2px;">
            <span><span class="sa-status-dot ${statusClass}"></span>${esc(b.parent)}</span>
            <span>${_fmt$(b.actual_amount)} / ${_fmt$(b.monthly_amount)} <span style="color:${color};">(${b.pct ?? 0}%)</span></span>
          </div>
          <div style="background:var(--border); border-radius:4px; height:6px;">
            <div style="background:${color}; border-radius:4px; height:6px; width:${pct}%;"></div>
          </div>
        </div>`;
      }).join('');
    } else {
      budgetList.innerHTML = '<span style="color:var(--text-muted); font-size:13px;">No budgets set. Click "+ Set Budget" to add one.</span>';
    }
  }

  // Spending alerts — banners + status overview
  _renderSpendingAlerts(data.spending_alerts || [], data.budgets_vs_actual || []);

  // Credit utilization alerts
  _renderUtilizationAlerts(data.utilization_alerts || []);

  // Savings goals
  _renderSavingsGoals(data.savings_goals || []);

  // Net Worth widget
  _renderNetWorthWidget(data.net_worth || {});

  // Unreviewed nudge
  _renderUnreviewedNudge(data.unreviewed_count || 0);

  // Budget pace indicators
  _renderBudgetPace(data.budgets_vs_actual || []);

  // Recent transactions
  const tbody = document.getElementById('dash-recent-tbody');
  if (tbody) {
    if (data.recent_transactions.length) {
      tbody.innerHTML = data.recent_transactions.map(tx => {
        const amt = tx.resolved_amount ?? tx.amount;
        const amtFmt = _fmt$(Math.abs(amt));
        const isCredit = tx.subtype === 'payment' || amt < 0;
        const amtColor = isCredit ? 'color:#22c55e;' : '';
        const merchant = tx.merchant || tx.description;
        // Show orange dot indicator for unreviewed transactions in dashboard recent list
        const isUnreviewed = tx.unreviewed === true || tx.unreviewed === 'true';
        const dot = isUnreviewed ? '<span class="unreviewed-dot" title="Unreviewed" style="margin-right:4px;"></span>' : '';
        return `<tr${isUnreviewed ? ' class="unreviewed-row"' : ''}>
          <td style="white-space:nowrap;">${dot}${esc(tx.date || '')}</td>
          <td>${esc(merchant || '')}<br><span style="font-size:11px;color:var(--text-muted);">${esc(tx.description || '')}</span></td>
          <td style="font-size:12px;">${esc(tx.category || '')}</td>
          <td style="font-size:12px;">${esc(tx.account || '')}</td>
          <td class="text-right" style="${amtColor} font-weight:600;">${isCredit ? '+' : ''}${amtFmt}</td>
        </tr>`;
      }).join('');
    } else {
      tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted" style="padding:24px;">No transactions found.</td></tr>';
    }
  }
}

// ── Unreviewed Nudge Widget ─────────────────────────────────────

function _renderUnreviewedNudge(count) {
  const el = document.getElementById('unreviewed-nudge');
  if (!el) return;
  if (count <= 5) { el.style.display = 'none'; return; }

  // Check dismiss state from localStorage
  const dismissed = localStorage.getItem('nudge_dismissed');
  if (dismissed) {
    const parsed = JSON.parse(dismissed);
    if (parsed.type === 'never') { el.style.display = 'none'; return; }
    if (parsed.type === 'tomorrow' || parsed.type === 'next_week') {
      const until = new Date(parsed.until);
      if (new Date() < until) { el.style.display = 'none'; return; }
    }
  }

  // Progressive tone based on how long since last review
  const lastReview = localStorage.getItem('nudge_last_review');
  const daysSince = lastReview ? Math.floor((Date.now() - new Date(lastReview).getTime()) / 86400000) : 14;
  let message, tone;
  if (daysSince < 7) {
    message = `You have <strong>${count}</strong> unreviewed transactions waiting.`;
    tone = '';
  } else if (daysSince <= 30) {
    message = `There are <strong>${count}</strong> transactions that could use your attention.`;
    tone = '';
  } else {
    message = `Whenever you have a moment, <strong>${count}</strong> transactions are ready for review.`;
    tone = '';
  }
  const estTime = Math.ceil(count / 15);
  const timeStr = estTime <= 3 ? `~${estTime} min` : 'a few minutes';

  el.style.display = '';
  el.innerHTML = `<div class="card" style="padding:14px 20px; border-left:4px solid var(--warning,#f59e0b); display:flex; align-items:center; gap:12px;">
    <div style="flex:1; font-size:13px;">
      ${message} <span style="color:var(--text-muted); font-size:12px;">(est. ${timeStr})</span>
    </div>
    <button class="btn btn-primary btn-sm" onclick="_goReviewFromNudge()">Review Now</button>
    <div style="position:relative;">
      <button class="btn btn-secondary btn-sm" onclick="_toggleNudgeDismissMenu()" style="font-size:11px;">Dismiss ▾</button>
      <div id="nudge-dismiss-menu" style="display:none; position:absolute; right:0; top:100%; margin-top:4px; background:var(--card-bg,#fff); border:1px solid var(--border); border-radius:6px; box-shadow:0 4px 12px rgba(0,0,0,.1); z-index:50; min-width:140px;">
        <div style="padding:6px 12px; cursor:pointer; font-size:12px; white-space:nowrap;" onmouseenter="this.style.background='var(--bg-alt)'" onmouseleave="this.style.background=''" onclick="_dismissNudge('tomorrow')">Until tomorrow</div>
        <div style="padding:6px 12px; cursor:pointer; font-size:12px; white-space:nowrap;" onmouseenter="this.style.background='var(--bg-alt)'" onmouseleave="this.style.background=''" onclick="_dismissNudge('next_week')">Until next week</div>
        <div style="padding:6px 12px; cursor:pointer; font-size:12px; white-space:nowrap; border-top:1px solid var(--border);" onmouseenter="this.style.background='var(--bg-alt)'" onmouseleave="this.style.background=''" onclick="_dismissNudge('never')">Don't show again</div>
      </div>
    </div>
  </div>`;
}

function _toggleNudgeDismissMenu() {
  const menu = document.getElementById('nudge-dismiss-menu');
  if (menu) menu.style.display = menu.style.display === 'none' ? '' : 'none';
}

function _dismissNudge(type) {
  let until = null;
  if (type === 'tomorrow') {
    const d = new Date(); d.setDate(d.getDate() + 1); d.setHours(0, 0, 0, 0);
    until = d.toISOString();
  } else if (type === 'next_week') {
    const d = new Date(); d.setDate(d.getDate() + 7); d.setHours(0, 0, 0, 0);
    until = d.toISOString();
  }
  localStorage.setItem('nudge_dismissed', JSON.stringify({ type, until }));
  document.getElementById('unreviewed-nudge').style.display = 'none';
}

function _goReviewFromNudge() {
  localStorage.setItem('nudge_last_review', new Date().toISOString());
  showPage('transactions');
  // Filter to unreviewed
  const sel = document.getElementById('filter-reviewed');
  if (sel) { sel.value = 'unreviewed'; loadTransactions(); }
}

// ── Weekly Spending Recap ───────────────────────────────────────

async function _renderWeeklyRecap() {
  const el = document.getElementById('weekly-recap-banner');
  if (!el) return;
  const now = new Date();
  // Only show on Monday before 6pm
  if (now.getDay() !== 1 || now.getHours() >= 18) { el.style.display = 'none'; return; }
  // Check if dismissed for this week
  const today = now.toISOString().slice(0, 10);
  const lastMonday = new Date(now); lastMonday.setDate(now.getDate() - 7);
  const weekKey = lastMonday.toISOString().slice(0, 10);
  const dismissed = localStorage.getItem('recap_dismissed_week');
  if (dismissed === weekKey) { el.style.display = 'none'; return; }
  try {
    const data = await api('GET', `/dashboard/weekly-recap?week_start=${weekKey}`);
    if (!data.txn_count) { el.style.display = 'none'; return; }
    el.style.display = '';
    el.innerHTML = `<div class="card" style="padding:14px 20px; border-left:4px solid var(--primary,#3b82f6); display:flex; align-items:center; gap:12px;">
      <div style="flex:1; font-size:13px;">
        <strong>Last Week Recap</strong> (${esc(data.week_start)} – ${esc(data.week_end)}):
        You spent <strong>${_fmt$(data.total_spend)}</strong> across <strong>${data.txn_count}</strong> transactions.
        ${data.top_category ? `Top category: <strong>${esc(data.top_category)}</strong>.` : ''}
      </div>
      <button class="btn btn-primary btn-sm" onclick="_recapSeeDetails('${esc(data.week_start)}','${esc(data.week_end)}')">See Details</button>
      <button class="btn btn-secondary btn-sm" onclick="_dismissRecap('${esc(weekKey)}')" title="Dismiss" style="font-size:11px;">✕</button>
    </div>`;
  } catch {
    el.style.display = 'none';
  }
}

function _dismissRecap(weekKey) {
  localStorage.setItem('recap_dismissed_week', weekKey);
  document.getElementById('weekly-recap-banner').style.display = 'none';
}

function _recapSeeDetails(start, end) {
  showPage('transactions');
  const startInput = document.getElementById('filter-start');
  const endInput = document.getElementById('filter-end');
  if (startInput) startInput.value = start;
  if (endInput) endInput.value = end;
  loadTransactions();
}

// ── Budget Pace Indicator ──────────────────────────────────────

function _renderBudgetPace(bva) {
  const budgetList = document.getElementById('dash-budget-list');
  if (!budgetList || !bva.length) return;
  const now = new Date();
  const dayOfMonth = now.getDate();
  const daysInMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
  if (dayOfMonth < 5) return; // Only show after day 5

  // Append pace info to each budget row
  bva.forEach((b, i) => {
    const rows = budgetList.children;
    if (i >= rows.length) return;
    const actual = b.actual_amount || 0;
    if (actual === 0) return; // No spending yet
    const projected = (actual / dayOfMonth) * daysInMonth;
    const paceRatio = projected / (b.monthly_amount || 1);
    let paceColor, paceLabel;
    if (paceRatio > 1.1) { paceColor = '#ef4444'; paceLabel = 'over budget'; }
    else if (paceRatio >= 0.9) { paceColor = '#f59e0b'; paceLabel = 'near limit'; }
    else { paceColor = '#22c55e'; paceLabel = 'on track'; }
    const paceEl = document.createElement('div');
    paceEl.style.cssText = 'font-size:11px; color:var(--text-muted); margin-top:2px;';
    paceEl.innerHTML = `At this pace: <span style="color:${paceColor}; font-weight:600;">${_fmt$(projected)}</span> by month end <span style="font-size:10px; color:${paceColor};">(${paceLabel})</span>`;
    rows[i].appendChild(paceEl);
  });
}

// ── Year-in-Review Reports ──────────────────────────────────────

let _arYear = new Date().getFullYear();

function openAnnualReport() {
  _arYear = _dashYear;
  document.getElementById('annual-report-modal').classList.remove('hidden');
  _loadAnnualReport();
}
function closeAnnualReport() {
  document.getElementById('annual-report-modal').classList.add('hidden');
}
function annualReportPrevYear() { _arYear--; _loadAnnualReport(); }
function annualReportNextYear() { _arYear++; _loadAnnualReport(); }

async function _loadAnnualReport() {
  const titleEl = document.getElementById('ar-title');
  const bodyEl = document.getElementById('ar-body');
  const badgeEl = document.getElementById('ar-stored-badge');
  if (titleEl) titleEl.textContent = `${_arYear} Year in Review`;
  if (bodyEl) bodyEl.innerHTML = '<div style="text-align:center; padding:40px; color:var(--text-muted);">Loading…</div>';
  if (badgeEl) badgeEl.textContent = '';

  try {
    const data = await api('GET', `/annual-reports/${_arYear}`);
    if (badgeEl) badgeEl.textContent = data.stored ? 'Saved' : 'Preview';
    _renderAnnualReport(data);
  } catch (err) {
    if (bodyEl) bodyEl.innerHTML = `<div style="text-align:center; padding:40px; color:var(--text-muted);">No data available for ${_arYear}.</div>`;
  }
}

function _renderAnnualReport(data) {
  const r = data.report || {};
  const bodyEl = document.getElementById('ar-body');
  if (!bodyEl) return;

  const monthly = r.monthly || [];
  const maxSpent = Math.max(...monthly.map(m => m.spent), 1);

  // Month-by-month bar chart
  const chartHtml = monthly.length ? `
    <div class="ar-section">
      <div class="ar-section-title">Month-by-Month Spending</div>
      <div class="ar-month-chart">
        ${monthly.map(m => {
          const h = Math.max(Math.round(m.spent / maxSpent * 100), 2);
          return `<div class="ar-month-bar-wrap">
            <div class="ar-month-bar" style="height:${h}px; background:${m.net >= 0 ? '#22c55e' : '#ef4444'};" title="${m.month_name}: ${_fmt$(m.spent)}"></div>
            <div class="ar-month-label">${m.month_name}</div>
          </div>`;
        }).join('')}
      </div>
    </div>` : '';

  // Top categories
  const cats = (r.top_categories || []);
  const maxCat = Math.max(...cats.map(c => c.amount), 1);
  const catsHtml = cats.length ? `
    <div class="ar-section">
      <div class="ar-section-title">Top 5 Categories</div>
      ${cats.map(c => `<div style="margin-bottom:6px;">
        <div style="display:flex; justify-content:space-between; font-size:13px; margin-bottom:2px;">
          <span>${esc(c.name)}</span>
          <span style="font-weight:600;">${_fmt$(c.amount)}</span>
        </div>
        <div style="background:var(--border); border-radius:4px; height:6px;">
          <div style="background:var(--primary,#3b82f6); border-radius:4px; height:6px; width:${Math.round(c.amount / maxCat * 100)}%;"></div>
        </div>
      </div>`).join('')}
    </div>` : '';

  // Top merchants
  const merchs = (r.top_merchants || []);
  const merchsHtml = merchs.length ? `
    <div class="ar-section">
      <div class="ar-section-title">Top 5 Merchants</div>
      ${merchs.map((m, i) => `<div style="display:flex; justify-content:space-between; padding:4px 0; border-bottom:1px solid var(--border); font-size:13px;">
        <span>${i + 1}. ${esc(m.name)}</span>
        <span style="font-weight:600;">${_fmt$(m.amount)}</span>
      </div>`).join('')}
    </div>` : '';

  const netColor = (r.net_saved || 0) >= 0 ? '#22c55e' : '#ef4444';
  const bigMonth = r.biggest_month || {};
  const lightMonth = r.lightest_month || {};

  bodyEl.innerHTML = `
    <div id="ar-printable">
      <div class="ar-narrative">${esc(data.narrative || '')}</div>
      <div class="ar-kpi-grid">
        <div class="ar-kpi">
          <div class="ar-kpi-label">Total Income</div>
          <div class="ar-kpi-value" style="color:#22c55e;">${_fmt$(r.total_income || 0)}</div>
        </div>
        <div class="ar-kpi">
          <div class="ar-kpi-label">Total Spent</div>
          <div class="ar-kpi-value" style="color:#ef4444;">${_fmt$(r.total_spent || 0)}</div>
        </div>
        <div class="ar-kpi">
          <div class="ar-kpi-label">Net Saved</div>
          <div class="ar-kpi-value" style="color:${netColor};">${(r.net_saved || 0) < 0 ? '-' : ''}${_fmt$(Math.abs(r.net_saved || 0))}</div>
        </div>
        <div class="ar-kpi">
          <div class="ar-kpi-label">Transactions</div>
          <div class="ar-kpi-value">${fmt(r.txn_count || 0)}</div>
        </div>
      </div>
      <div class="ar-kpi-grid" style="grid-template-columns:1fr 1fr 1fr;">
        <div class="ar-kpi">
          <div class="ar-kpi-label">Biggest Month</div>
          <div class="ar-kpi-value" style="font-size:16px;">${esc(bigMonth.month_name || '—')}</div>
          <div style="font-size:12px; color:var(--text-muted);">${_fmt$(bigMonth.spent || 0)}</div>
        </div>
        <div class="ar-kpi">
          <div class="ar-kpi-label">Lightest Month</div>
          <div class="ar-kpi-value" style="font-size:16px;">${esc(lightMonth.month_name || '—')}</div>
          <div style="font-size:12px; color:var(--text-muted);">${_fmt$(lightMonth.spent || 0)}</div>
        </div>
        <div class="ar-kpi">
          <div class="ar-kpi-label">Recurring Costs</div>
          <div class="ar-kpi-value" style="font-size:16px;">${_fmt$(r.recurring_monthly || 0)}/mo</div>
          <div style="font-size:12px; color:var(--text-muted);">${_fmt$(r.recurring_annual || 0)}/yr</div>
        </div>
      </div>
      ${chartHtml}
      ${catsHtml}
      ${merchsHtml}
    </div>
  `;
}

async function generateAndStoreAnnualReport() {
  try {
    await api('POST', `/annual-reports/generate?year=${_arYear}`);
    toast(`${_arYear} report saved.`, 'success');
    _loadAnnualReport();
  } catch (err) {
    toast(`Failed: ${err.message}`, 'error');
  }
}

function printAnnualReport() {
  const content = document.getElementById('ar-printable');
  if (!content) return;
  const win = window.open('', '_blank');
  win.document.write(`<!DOCTYPE html><html><head><title>${_arYear} Year in Review — Spendly</title>
    <style>
      body { font-family: system-ui, -apple-system, sans-serif; max-width: 700px; margin: 40px auto; color: #1e293b; }
      .ar-narrative { font-size: 14px; line-height: 1.6; margin-bottom: 20px; padding: 16px; background: #f8fafc; border-radius: 8px; }
      .ar-kpi-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 20px; }
      .ar-kpi { text-align: center; padding: 12px; border: 1px solid #e2e8f0; border-radius: 8px; }
      .ar-kpi-label { font-size: 11px; text-transform: uppercase; color: #64748b; margin-bottom: 4px; }
      .ar-kpi-value { font-size: 20px; font-weight: 700; }
      .ar-section { margin-bottom: 20px; }
      .ar-section-title { font-size: 14px; font-weight: 600; margin-bottom: 8px; }
      .ar-month-chart { display: flex; align-items: flex-end; gap: 4px; height: 120px; }
      .ar-month-bar-wrap { flex: 1; display: flex; flex-direction: column; align-items: center; }
      .ar-month-bar { width: 100%; border-radius: 3px 3px 0 0; }
      .ar-month-label { font-size: 10px; color: #64748b; margin-top: 4px; }
      @media print { body { margin: 20px; } }
    </style>
  </head><body>
    <h1 style="text-align:center; margin-bottom:24px;">${_arYear} Year in Review</h1>
    ${content.innerHTML}
  </body></html>`);
  win.document.close();
  setTimeout(() => win.print(), 300);
}

async function openAnnualReportHistory() {
  const modal = document.getElementById('annual-report-history-modal');
  const bodyEl = document.getElementById('arh-body');
  modal.classList.remove('hidden');
  bodyEl.innerHTML = '<div style="text-align:center; padding:24px; color:var(--text-muted);">Loading…</div>';

  try {
    const data = await api('GET', '/annual-reports');
    const reports = data.reports || [];
    if (!reports.length) {
      bodyEl.innerHTML = '<div style="text-align:center; padding:24px; color:var(--text-muted);">No saved reports yet.</div>';
      return;
    }
    bodyEl.innerHTML = reports.map(r => `
      <div class="sh-item" style="display:flex; justify-content:space-between; align-items:center; padding:10px 12px; border-bottom:1px solid var(--border);">
        <div>
          <div style="font-weight:600; font-size:14px;">${r.year} Year in Review</div>
          <div style="font-size:11px; color:var(--text-muted);">Saved ${r.created_at ? r.created_at.slice(0, 10) : '—'}</div>
        </div>
        <div style="display:flex; gap:6px;">
          <button class="btn btn-secondary btn-sm" onclick="_arYear=${r.year}; closeAnnualReportHistory(); _loadAnnualReport();" style="font-size:11px;">View</button>
          <button class="btn btn-secondary btn-sm" onclick="deleteAnnualReport(${r.year})" style="font-size:11px; color:#ef4444;">Delete</button>
        </div>
      </div>
    `).join('');
  } catch (err) {
    bodyEl.innerHTML = '<div style="text-align:center; padding:24px; color:var(--text-muted);">Failed to load.</div>';
  }
}

function closeAnnualReportHistory() {
  document.getElementById('annual-report-history-modal').classList.add('hidden');
}

async function deleteAnnualReport(year) {
  if (!confirm(`Delete the ${year} annual report?`)) return;
  try {
    await api('DELETE', `/annual-reports/${year}`);
    toast(`${year} report deleted.`, 'success');
    openAnnualReportHistory();
  } catch (err) {
    toast(`Failed: ${err.message}`, 'error');
  }
}

// ── Net Worth Tracker ───────────────────────────────────────────

const _NW_TYPE_LABELS = {
  checking: 'Checking', savings: 'Savings', investment: 'Investment',
  credit_card: 'Credit Card', loan: 'Loan', other: 'Other',
};
const _NW_ASSET_TYPES = new Set(['checking', 'savings', 'investment', 'retirement', 'digital_wallet', 'other']);

function _renderNetWorthWidget(nw) {
  const set = (id, val) => { const el = document.getElementById(id); if (el) el.innerHTML = val; };
  set('nw-assets', _fmt$(nw.total_assets || 0));
  set('nw-liabilities', _fmt$(nw.total_liabilities || 0));

  const netEl = document.getElementById('nw-total');
  if (netEl) {
    const net = nw.net_worth || 0;
    netEl.style.color = net >= 0 ? '#22c55e' : '#ef4444';
    netEl.innerHTML = (net < 0 ? '-' : '') + _fmt$(Math.abs(net));
  }
  const trendEl = document.getElementById('nw-trend');
  if (trendEl) {
    if (nw.trend != null) {
      const arrow = nw.trend >= 0 ? '▲' : '▼';
      const color = nw.trend >= 0 ? '#22c55e' : '#ef4444';
      trendEl.innerHTML = `<span style="color:${color};">${arrow} ${Math.abs(nw.trend)}% vs last snapshot</span>`;
    } else {
      trendEl.innerHTML = '';
    }
  }
  // Load accounts list
  _loadNwAccounts();
  _loadNwSnapshots();
}

async function _loadNwAccounts() {
  try {
    const data = await api('GET', '/net-worth/accounts');
    const list = document.getElementById('nw-accounts-list');
    if (!list) return;
    const accounts = data.accounts || [];
    if (!accounts.length) {
      list.innerHTML = '<span style="color:var(--text-muted); font-size:13px;">No accounts added yet.</span>';
      return;
    }
    list.innerHTML = accounts.map(a => {
      const isAsset = a.is_asset ?? _NW_ASSET_TYPES.has(a.acct_type);
      const balColor = isAsset ? '#22c55e' : '#ef4444';
      const typeLabel = _NW_TYPE_LABELS[a.acct_type] || a.acct_type;
      return `<div class="nw-account-row">
        <div style="display:flex; align-items:center; gap:8px;">
          <span class="nw-type-badge">${esc(typeLabel)}</span>
          <span style="font-weight:500; font-size:13px;">${esc(a.name)}</span>
        </div>
        <div style="display:flex; align-items:center; gap:8px;">
          <span style="font-weight:600; color:${balColor};">${_fmt$(Math.abs(a.balance))}</span>
          <button class="btn btn-secondary btn-sm" onclick="editNwAccount(${a.id},'${esc(a.name)}','${a.acct_type}',${a.balance})" style="font-size:10px; padding:2px 6px;">Edit</button>
          <button class="btn btn-secondary btn-sm" onclick="deleteNwAccount(${a.id})" style="font-size:10px; padding:2px 6px; color:#ef4444;">Del</button>
        </div>
      </div>`;
    }).join('');
  } catch (err) {
    // silent
  }
}

async function _loadNwSnapshots() {
  try {
    const data = await api('GET', '/net-worth/snapshots');
    const snapshots = data.snapshots || [];
    const toggle = document.getElementById('nw-history-toggle');
    if (toggle) toggle.style.display = snapshots.length ? '' : 'none';

    const chartEl = document.getElementById('nw-chart');
    const listEl = document.getElementById('nw-history-list');
    if (!chartEl || !listEl || !snapshots.length) return;

    // Mini bar chart (last 12 snapshots, oldest to newest)
    const recent = snapshots.slice(0, 12).reverse();
    const maxNw = Math.max(...recent.map(s => Math.abs(parseFloat(s.net_worth))), 1);
    chartEl.innerHTML = recent.map(s => {
      const nw = parseFloat(s.net_worth);
      const h = Math.max(Math.round(Math.abs(nw) / maxNw * 70), 2);
      const color = nw >= 0 ? '#22c55e' : '#ef4444';
      return `<div title="${s.snapshot_date}: ${_fmt$(nw)}" style="flex:1; min-width:8px; max-width:24px; height:${h}px; background:${color}; border-radius:2px;"></div>`;
    }).join('');

    // History list
    listEl.innerHTML = snapshots.slice(0, 20).map(s => {
      const nw = parseFloat(s.net_worth);
      const color = nw >= 0 ? '#22c55e' : '#ef4444';
      return `<div class="nw-history-row">
        <span style="font-size:12px;">${esc(s.snapshot_date)}</span>
        <div style="display:flex; align-items:center; gap:8px;">
          <span style="font-size:12px; font-weight:600; color:${color};">${_fmt$(nw)}</span>
          <button class="btn btn-secondary btn-sm" onclick="deleteNwSnapshot(${s.id})" style="font-size:10px; padding:1px 5px; color:#ef4444;">✕</button>
        </div>
      </div>`;
    }).join('');
  } catch (err) {
    // silent
  }
}

function openNwForm() {
  document.getElementById('nw-form').style.display = '';
  document.getElementById('nw-edit-id').value = '';
  document.getElementById('nw-name').value = '';
  document.getElementById('nw-type').value = 'checking';
  document.getElementById('nw-balance').value = '';
}

function closeNwForm() {
  document.getElementById('nw-form').style.display = 'none';
}

function editNwAccount(id, name, type, balance) {
  document.getElementById('nw-form').style.display = '';
  document.getElementById('nw-edit-id').value = id;
  document.getElementById('nw-name').value = name;
  document.getElementById('nw-type').value = type;
  document.getElementById('nw-balance').value = balance;
}

async function saveNwAccount() {
  const editId = document.getElementById('nw-edit-id').value;
  const name = document.getElementById('nw-name').value.trim();
  const acct_type = document.getElementById('nw-type').value;
  const balance = parseFloat(document.getElementById('nw-balance').value || 0);
  if (!name) { toast('Account name is required.', 'error'); return; }
  try {
    if (editId) {
      await api('PUT', `/net-worth/accounts/${editId}`, { name, acct_type, balance });
      toast('Account updated.', 'success');
    } else {
      await api('POST', '/net-worth/accounts', { name, acct_type, balance });
      toast('Account added.', 'success');
    }
    closeNwForm();
    loadDashboard();
  } catch (err) {
    toast(`Failed: ${err.message}`, 'error');
  }
}

async function deleteNwAccount(id) {
  if (!confirm('Delete this account?')) return;
  try {
    await api('DELETE', `/net-worth/accounts/${id}`);
    toast('Account deleted.', 'success');
    loadDashboard();
  } catch (err) {
    toast(`Failed: ${err.message}`, 'error');
  }
}

async function takeNwSnapshot() {
  try {
    const result = await api('POST', '/net-worth/snapshots');
    toast(`Snapshot saved (${result.snapshot_date}): ${_fmt$(result.net_worth)}`, 'success');
    loadDashboard();
  } catch (err) {
    toast(`Failed: ${err.message}`, 'error');
  }
}

async function deleteNwSnapshot(id) {
  if (!confirm('Delete this snapshot?')) return;
  try {
    await api('DELETE', `/net-worth/snapshots/${id}`);
    toast('Snapshot deleted.', 'success');
    loadDashboard();
  } catch (err) {
    toast(`Failed: ${err.message}`, 'error');
  }
}

function toggleNwHistory() {
  const panel = document.getElementById('nw-history-panel');
  const btn = document.querySelector('#nw-history-toggle button');
  if (panel.style.display === 'none') {
    panel.style.display = '';
    if (btn) btn.textContent = 'Hide History';
  } else {
    panel.style.display = 'none';
    if (btn) btn.textContent = 'Show History';
  }
}

// ── Spending Alerts & Thresholds ────────────────────────────────

function _renderSpendingAlerts(alerts, budgets) {
  // Alert banners
  const bannerEl = document.getElementById('spending-alerts-banner');
  if (bannerEl) {
    if (alerts.length) {
      bannerEl.style.display = '';
      bannerEl.innerHTML = alerts.map(a => {
        const isExceeded = a.status === 'exceeded';
        const cls = isExceeded ? 'sa-banner sa-banner-red' : 'sa-banner sa-banner-yellow';
        const icon = isExceeded ? '🚨' : '⚠️';
        const msg = isExceeded
          ? `${esc(a.parent)} has exceeded its monthly budget — ${_fmt$(a.spent)} of ${_fmt$(a.budget)} (${a.pct}%)`
          : `${esc(a.parent)} is approaching its budget limit — ${_fmt$(a.spent)} of ${_fmt$(a.budget)} (${a.pct}%)`;
        return `<div class="${cls}">
          <span>${icon} ${msg}</span>
          <button class="sa-banner-dismiss" onclick="this.parentElement.remove()" title="Dismiss">✕</button>
        </div>`;
      }).join('');
    } else {
      bannerEl.style.display = 'none';
      bannerEl.innerHTML = '';
    }
  }

  // Budget Status Overview (green/yellow/red per category)
  const overviewEl = document.getElementById('budget-status-overview');
  const gridEl = document.getElementById('budget-status-grid');
  if (overviewEl && gridEl) {
    if (budgets.length) {
      overviewEl.style.display = '';
      gridEl.innerHTML = budgets.map(b => {
        const statusClass = b.pct >= 100 ? 'sa-status-red' : b.pct >= 80 ? 'sa-status-yellow' : 'sa-status-green';
        const statusLabel = b.pct >= 100 ? 'Over Budget' : b.pct >= 80 ? 'Near Limit' : 'On Track';
        return `<div class="sa-status-chip ${statusClass}">
          <span class="sa-status-dot ${statusClass}"></span>
          <span class="sa-status-label">${esc(b.parent)}</span>
          <span class="sa-status-pct">${b.pct ?? 0}%</span>
          <span class="sa-status-text">${statusLabel}</span>
        </div>`;
      }).join('');
    } else {
      overviewEl.style.display = 'none';
      gridEl.innerHTML = '';
    }
  }
}

// ── Credit Utilization Alerts (from Accounts module) ────────────

function _renderUtilizationAlerts(alerts) {
  const bannerEl = document.getElementById('spending-alerts-banner');
  if (!bannerEl || !alerts.length) return;
  // Append utilization alerts after any spending alerts
  const html = alerts.map(a => {
    const cls = a.severity === 'critical' ? 'sa-banner sa-banner-red' : 'sa-banner sa-banner-yellow';
    const icon = a.severity === 'critical' ? '🚨' : '⚠️';
    const msg = `${esc(a.name)}: ${a.utilization_pct}% credit utilization (${_fmt$(a.balance)} / ${_fmt$(a.credit_limit)})`;
    return `<div class="${cls}">
      <span>${icon} ${msg}</span>
      <button class="sa-banner-dismiss" onclick="this.parentElement.remove()" title="Dismiss">✕</button>
    </div>`;
  }).join('');
  bannerEl.style.display = '';
  bannerEl.innerHTML += html;
}

// ── Balance Card (Transaction Tab Integration — Phase 6c) ─────

async function _loadBalanceCard(type, accountFilter) {
  const prefix = type === 'credit_card' ? 'cc' : 'bk';
  const container = document.getElementById(`${prefix}-balance-card`);
  if (!container) return;

  // Hide by default
  container.style.display = 'none';
  container.innerHTML = '';

  // Only show when a specific account is selected
  if (!accountFilter) return;

  try {
    const data = await api('GET', `/accounts/integration/balance-card?linked_account_id=${encodeURIComponent(accountFilter)}`);
    if (!data || !data.id) return;
    _renderBalanceCard(container, data);
  } catch (e) {
    // 404 = no linked account, silently hide
  }
}

function _renderBalanceCard(container, data) {
  const bal = _fmt$(data.balance);
  const stmtBal = data.statement_balance != null ? _fmt$(data.statement_balance) : '--';
  const limit = data.credit_limit != null ? _fmt$(data.credit_limit) : '--';
  const minPay = data.minimum_payment != null ? _fmt$(data.minimum_payment) : '--';

  // Staleness display
  let staleBadge = '';
  if (data.staleness_days != null) {
    const days = data.staleness_days;
    const label = days === 0 ? 'today' : days === 1 ? '1 day ago' : `${days} days ago`;
    const color = data.staleness_level === 'stale' ? 'var(--danger, #e74c3c)' :
                  data.staleness_level === 'aging' ? 'var(--warning, #f39c12)' :
                  'var(--success, #27ae60)';
    staleBadge = `<span style="display:inline-block; padding:2px 8px; border-radius:10px; font-size:11px; background:${color}20; color:${color}; font-weight:600;">${label}</span>`;
  }

  const verifiedAt = data.last_verified_at ? new Date(data.last_verified_at).toLocaleDateString() : 'never';
  const isLiability = data.account_class === 'liability';

  let metricsHtml = `
    <div style="display:flex; gap:24px; flex-wrap:wrap; margin-bottom:8px;">
      <div><div style="font-size:11px; color:var(--text-muted);">Current Balance</div><div style="font-size:18px; font-weight:700; font-variant-numeric:tabular-nums;">${bal}</div></div>`;
  if (isLiability) {
    metricsHtml += `
      <div><div style="font-size:11px; color:var(--text-muted);">Statement Balance</div><div style="font-size:16px; font-variant-numeric:tabular-nums;">${stmtBal}</div></div>
      <div><div style="font-size:11px; color:var(--text-muted);">Credit Limit</div><div style="font-size:16px; font-variant-numeric:tabular-nums;">${limit}</div></div>
      <div><div style="font-size:11px; color:var(--text-muted);">Min Payment</div><div style="font-size:16px; font-variant-numeric:tabular-nums;">${minPay}</div></div>`;
  }
  metricsHtml += '</div>';

  container.innerHTML = `
    <div class="card" style="border-left:4px solid var(--primary, #3b82f6);">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
        <div>
          <strong>${esc(data.name)}</strong>
          ${data.institution ? `<span style="color:var(--text-muted); margin-left:8px;">${esc(data.institution)}</span>` : ''}
          ${data.last_four ? `<span style="color:var(--text-muted);"> (${esc(data.last_four)})</span>` : ''}
        </div>
        <div style="display:flex; align-items:center; gap:8px;">
          ${staleBadge}
          <span style="font-size:11px; color:var(--text-muted);">Last updated: ${verifiedAt}</span>
        </div>
      </div>
      ${metricsHtml}
      <div style="font-size:11px; color:var(--text-muted); padding:6px 10px; background:var(--bg-secondary, #f8f9fa); border-radius:6px; margin-bottom:8px;">
        This balance was ${data.data_source === 'manual' ? 'manually entered' : 'imported via ' + esc(data.data_source)} and may not reflect recent transactions shown below.
      </div>
      <div style="display:flex; gap:8px;">
        <button class="btn btn-secondary btn-sm" onclick="_openInlineBalanceUpdate(${data.id})">Update Balance</button>
        <button class="btn btn-secondary btn-sm" onclick="navigate('accounts')">View in Accounts</button>
      </div>
      <div id="inline-balance-form-${data.id}" style="display:none; margin-top:10px; padding:10px; border:1px solid var(--border); border-radius:6px;">
        <div style="display:flex; gap:8px; align-items:flex-end; flex-wrap:wrap;">
          <div><label style="font-size:11px;">New Balance</label><input type="number" step="0.01" id="ibl-balance-${data.id}" style="padding:6px 8px; border:1px solid var(--border); border-radius:4px; width:120px;" value="${data.balance}" /></div>
          ${isLiability ? `
            <div><label style="font-size:11px;">Statement Bal</label><input type="number" step="0.01" id="ibl-stmt-${data.id}" style="padding:6px 8px; border:1px solid var(--border); border-radius:4px; width:120px;" value="${data.statement_balance || ''}" /></div>
            <div><label style="font-size:11px;">Min Payment</label><input type="number" step="0.01" id="ibl-min-${data.id}" style="padding:6px 8px; border:1px solid var(--border); border-radius:4px; width:120px;" value="${data.minimum_payment || ''}" /></div>
          ` : ''}
          <button class="btn btn-primary btn-sm" onclick="_submitInlineBalance(${data.id})">Save</button>
          <button class="btn btn-secondary btn-sm" onclick="document.getElementById('inline-balance-form-${data.id}').style.display='none'">Cancel</button>
        </div>
      </div>
    </div>`;
  container.style.display = '';
}

function _openInlineBalanceUpdate(accountId) {
  const form = document.getElementById(`inline-balance-form-${accountId}`);
  if (form) form.style.display = '';
}

async function _submitInlineBalance(accountId) {
  const balInput = document.getElementById(`ibl-balance-${accountId}`);
  if (!balInput) return;
  const bal = parseFloat(balInput.value);
  if (isNaN(bal)) { toast('Enter a valid balance', 'error'); return; }

  const entry = { account_id: accountId, current_balance: bal };
  const stmtInput = document.getElementById(`ibl-stmt-${accountId}`);
  if (stmtInput && stmtInput.value) entry.statement_balance = parseFloat(stmtInput.value);
  const minInput = document.getElementById(`ibl-min-${accountId}`);
  if (minInput && minInput.value) entry.minimum_payment = parseFloat(minInput.value);

  try {
    await api('POST', '/accounts/balances/update', { updates: [entry] });
    toast('Balance updated', 'success');
    // Refresh the balance card
    const type = _getActiveTxnType();
    const prefix = type === 'credit_card' ? 'cc' : 'bk';
    const container = document.getElementById(`${prefix}-balance-card`);
    if (container) {
      const data = await api('GET', `/accounts/${accountId}`);
      if (data) _renderBalanceCard(container, {
        ...data,
        staleness_days: 0,
        staleness_level: 'fresh',
      });
    }
  } catch (e) {
    toast('Failed to update balance: ' + e.message, 'error');
  }
}

// ── Budget form ────────────────────────────────────────────────

function openBudgetForm() {
  // Ensure parent dropdown is populated (dashboard loads before Utilities)
  if (_knownParents.length === 0) {
    api('GET', '/utilities/categories').then(d => {
      _utilCatData = d.categories || _utilCatData;
      _populateCategoryParentSelects(d.parents || _utilCatData.map(g => g.parent));
    }).catch(() => {});
  }
  document.getElementById('budget-form').style.display = '';
}
function closeBudgetForm() {
  document.getElementById('budget-form').style.display = 'none';
  ['bf-parent','bf-amount'].forEach(id => {
    const el = document.getElementById(id); if (el) el.value = '';
  });
  const bfCat = document.getElementById('bf-category');
  if (bfCat) bfCat.innerHTML = '<option value="">— All in parent —</option>';
}
async function saveBudget() {
  const parent = document.getElementById('bf-parent').value.trim();
  const category = document.getElementById('bf-category').value.trim() || null;
  const amount = parseFloat(document.getElementById('bf-amount').value);
  if (!parent || isNaN(amount) || amount <= 0) {
    toast('Parent group and a positive amount are required.', 'error'); return;
  }
  try {
    await api('POST', '/budgets', { parent, category, monthly_amount: amount });
    toast('Budget saved.', 'success');
    closeBudgetForm();
    loadDashboard();
  } catch (err) {
    toast(`Failed: ${err.message}`, 'error');
  }
}
async function deleteBudget(id) {
  if (!confirm('Delete this budget?')) return;
  try {
    await api('DELETE', `/budgets/${id}`);
    toast('Budget deleted.', 'success');
    loadDashboard();
  } catch (err) {
    toast(`Failed: ${err.message}`, 'error');
  }
}

// ── Budget Rebalancing ────────────────────────────────────────

let _rebalanceSuggestions = [];

async function loadRebalanceSuggestions() {
  const panel = document.getElementById('rebalance-panel');
  const list = document.getElementById('rebalance-list');
  const status = document.getElementById('rebalance-status');
  const intro = document.getElementById('rebalance-intro');
  if (!panel || !list) return;

  panel.style.display = '';
  status.textContent = 'Analysing…';
  list.innerHTML = '';

  try {
    const data = await api('GET', '/budgets/rebalance');
    if (data.message) {
      intro.textContent = data.message;
      status.textContent = '';
      list.innerHTML = '';
      document.getElementById('rebalance-actions').style.display = 'none';
      _rebalanceSuggestions = [];
      return;
    }

    _rebalanceSuggestions = data.suggestions || [];
    if (!_rebalanceSuggestions.length) {
      intro.textContent = 'All budgets are well-balanced — no adjustments needed.';
      status.textContent = '';
      document.getElementById('rebalance-actions').style.display = 'none';
      return;
    }

    intro.textContent = `Based on ${data.months_analysed} months of data (${data.data_span_days} days). Select suggestions to apply.`;
    status.textContent = `${_rebalanceSuggestions.length} suggestion${_rebalanceSuggestions.length !== 1 ? 's' : ''}`;
    document.getElementById('rebalance-actions').style.display = '';

    _renderRebalanceSuggestions();
  } catch (err) {
    status.textContent = `Error: ${err.message}`;
    _rebalanceSuggestions = [];
  }
}

function _renderRebalanceSuggestions() {
  const list = document.getElementById('rebalance-list');
  if (!list) return;

  list.innerHTML = _rebalanceSuggestions.map((s, i) => {
    const label = s.category ? `${s.parent} → ${s.category}` : s.parent;
    const isOver = s.direction === 'over';
    const dirColor = isOver ? '#ef4444' : '#22c55e';
    const arrow = isOver ? '▲' : '▼';
    const diffSign = isOver ? '+' : '-';

    return `<div style="display:flex; align-items:center; gap:10px; padding:10px 12px; background:var(--bg-alt,#f8faff); border-radius:8px; border:1px solid var(--border);">
      <input type="checkbox" id="rb-chk-${i}" checked style="flex-shrink:0;" />
      <div style="flex:1; min-width:0;">
        <div style="font-size:13px; font-weight:600;">${esc(label)}</div>
        <div style="font-size:12px; color:var(--text-muted); margin-top:2px;">
          Avg actual: ${_fmt$(s.avg_monthly_actual)}/mo
          <span style="color:${dirColor}; font-weight:600; margin-left:6px;">
            ${arrow} ${diffSign}${_fmt$(Math.abs(s.diff))} (${Math.abs(s.diff_pct)}% ${s.direction})
          </span>
        </div>
      </div>
      <div style="text-align:right; flex-shrink:0;">
        <div style="font-size:12px; color:var(--text-muted);">Current</div>
        <div style="font-size:14px; font-weight:600;">${_fmt$(s.current_budget)}</div>
      </div>
      <div style="font-size:16px; color:var(--text-muted);">→</div>
      <div style="text-align:right; flex-shrink:0;">
        <div style="font-size:12px; color:var(--text-muted);">Suggested</div>
        <input type="number" id="rb-amt-${i}" value="${s.suggested_budget}" min="1" step="5"
               style="width:90px; font-size:14px; font-weight:600; padding:4px 8px; border:1px solid var(--border); border-radius:6px; text-align:right;" />
      </div>
    </div>`;
  }).join('');
}

function selectAllRebalance(checked) {
  _rebalanceSuggestions.forEach((_, i) => {
    const chk = document.getElementById(`rb-chk-${i}`);
    if (chk) chk.checked = checked;
  });
}

function hideRebalancePanel() {
  const panel = document.getElementById('rebalance-panel');
  if (panel) panel.style.display = 'none';
  _rebalanceSuggestions = [];
}

async function applyRebalance() {
  const adjustments = [];
  _rebalanceSuggestions.forEach((s, i) => {
    const chk = document.getElementById(`rb-chk-${i}`);
    const amt = document.getElementById(`rb-amt-${i}`);
    if (chk && chk.checked && amt) {
      const newAmt = parseFloat(amt.value);
      if (newAmt > 0) {
        adjustments.push({ budget_id: s.budget_id, new_amount: newAmt });
      }
    }
  });

  if (!adjustments.length) {
    toast('No suggestions selected.', 'error');
    return;
  }

  if (!confirm(`Apply ${adjustments.length} budget adjustment${adjustments.length !== 1 ? 's' : ''}?`)) return;

  try {
    const result = await api('POST', '/budgets/rebalance/apply', { adjustments });
    toast(`${result.updated} budget${result.updated !== 1 ? 's' : ''} updated.`, 'success');
    hideRebalancePanel();
    loadDashboard();
  } catch (err) {
    toast(`Failed: ${err.message}`, 'error');
  }
}

// ── Category Rules ────────────────────────────────────────────

let _editingCatRuleId = null;
let _catSuggestionsData = [];
let _allCatRules = []; // cached for search filtering

// ── Category Rule condition builder helpers ───────────────────

function _makeCatConditionRow(pattern, matchType, negate) {
  const row = document.createElement('div');
  row.className = 'crf-condition-row';
  row.style.cssText = 'display:flex; align-items:center; gap:8px; background:var(--bg-alt,#f8f9fa); border-radius:6px; padding:6px 10px;';
  const sel = document.createElement('select');
  sel.className = 'crf-cond-type';
  sel.style.cssText = 'width:auto; flex-shrink:0; padding:4px 6px; border-radius:5px; border:1px solid var(--border); font-size:12px;';
  ['exact', 'contains', 'starts_with'].forEach(t => {
    const opt = document.createElement('option');
    opt.value = t; opt.textContent = t; opt.selected = (t === matchType);
    sel.appendChild(opt);
  });
  const inp = document.createElement('input');
  inp.type = 'text'; inp.className = 'crf-cond-pattern';
  inp.placeholder = 'e.g. Restaurant-Restaurant';
  inp.value = pattern || '';
  inp.style.cssText = 'flex:1; min-width:80px; width:auto; padding:4px 8px; border-radius:5px; border:1px solid var(--border); font-size:12px; font-family:monospace; background:var(--card-bg,#fff); color:var(--text,#222);';
  const label = document.createElement('label');
  label.style.cssText = 'display:flex; align-items:center; gap:4px; font-size:12px; white-space:nowrap; cursor:pointer; flex-shrink:0;';
  const cb = document.createElement('input');
  cb.type = 'checkbox'; cb.className = 'crf-cond-negate'; cb.checked = !!negate; cb.style.cursor = 'pointer';
  label.appendChild(cb); label.appendChild(document.createTextNode(' NOT'));
  const btn = document.createElement('button');
  btn.type = 'button'; btn.className = 'btn btn-secondary btn-sm crf-cond-remove';
  btn.textContent = '\u2715'; btn.title = 'Remove condition';
  btn.style.cssText = 'font-size:12px; padding:2px 8px; flex-shrink:0;';
  btn.addEventListener('click', function() { _removeCatConditionRow(this); });
  row.appendChild(sel); row.appendChild(inp); row.appendChild(label); row.appendChild(btn);
  return row;
}

function _addCatConditionToGroup(groupBlock) {
  const container = groupBlock.querySelector('.crf-group-conditions');
  if (!container) return;
  container.appendChild(_makeCatConditionRow('', 'exact', false));
  _updateCatGroupUI();
}

function _removeCatConditionRow(btn) {
  const groupBlock = btn.closest('.crf-group-block');
  const rows = groupBlock.querySelectorAll('.crf-condition-row');
  if (rows.length <= 1) return;
  btn.closest('.crf-condition-row').remove();
  _updateCatGroupUI();
}

function _makeCatGroupBlock(groupLogic, conditions) {
  const block = document.createElement('div');
  block.className = 'crf-group-block';
  block.style.cssText = 'border:1px solid var(--border); border-radius:8px; padding:10px 12px;';
  const header = document.createElement('div');
  header.style.cssText = 'display:flex; align-items:center; justify-content:space-between; margin-bottom:8px;';
  const lbl = document.createElement('span');
  lbl.style.cssText = 'font-size:13px; font-weight:600;'; lbl.textContent = 'Match Conditions';
  const right = document.createElement('div');
  right.style.cssText = 'display:flex; align-items:center; gap:6px; font-size:13px;';
  const logicLabel = document.createElement('span');
  logicLabel.style.cssText = 'color:var(--text-muted);'; logicLabel.textContent = 'Combine with:';
  const logicSel = document.createElement('select');
  logicSel.className = 'crf-group-logic';
  logicSel.style.cssText = 'width:auto; padding:4px 8px; border-radius:6px; border:1px solid var(--border); font-size:13px;';
  [['AND', 'AND — all must match'], ['OR', 'OR — any must match']].forEach(([val, text]) => {
    const opt = document.createElement('option');
    opt.value = val; opt.textContent = text; opt.selected = (val === groupLogic);
    logicSel.appendChild(opt);
  });
  const removeBtn = document.createElement('button');
  removeBtn.type = 'button'; removeBtn.className = 'btn btn-secondary btn-sm crf-group-remove';
  removeBtn.textContent = 'Remove Group';
  removeBtn.style.cssText = 'font-size:11px; padding:2px 8px; margin-left:8px;';
  removeBtn.addEventListener('click', function() { _removeCatGroup(this); });
  right.appendChild(logicLabel); right.appendChild(logicSel); right.appendChild(removeBtn);
  header.appendChild(lbl); header.appendChild(right); block.appendChild(header);
  const condContainer = document.createElement('div');
  condContainer.className = 'crf-group-conditions';
  condContainer.style.cssText = 'display:flex; flex-direction:column; gap:8px; margin-bottom:8px;';
  block.appendChild(condContainer);
  const addBtn = document.createElement('button');
  addBtn.type = 'button'; addBtn.className = 'btn btn-secondary btn-sm';
  addBtn.textContent = '+ Add Condition'; addBtn.style.cssText = 'font-size:12px;';
  addBtn.addEventListener('click', function() { _addCatConditionToGroup(this.closest('.crf-group-block')); });
  block.appendChild(addBtn);
  if (conditions && conditions.length) {
    conditions.forEach(c => { condContainer.appendChild(_makeCatConditionRow(c.pattern, c.match_type || 'exact', !!c.negate)); });
  } else {
    condContainer.appendChild(_makeCatConditionRow('', 'exact', false));
  }
  _updateCatGroupUI();
  return block;
}

function _removeCatGroup(btn) {
  const groups = document.querySelectorAll('#crf-groups .crf-group-block');
  if (groups.length <= 1) return;
  btn.closest('.crf-group-block').remove();
  _updateCatGroupUI();
}

function _updateCatGroupUI() {
  const groups = document.querySelectorAll('#crf-groups .crf-group-block');
  groups.forEach(g => {
    const removeBtn = g.querySelector('.crf-group-remove');
    if (removeBtn) removeBtn.style.display = groups.length > 1 ? '' : 'none';
    const rows = g.querySelectorAll('.crf-condition-row');
    const logicSel = g.querySelector('.crf-group-logic');
    const logicLbl = logicSel ? logicSel.previousElementSibling : null;
    if (logicSel) logicSel.style.display = rows.length >= 2 ? '' : 'none';
    if (logicLbl) logicLbl.style.display = rows.length >= 2 ? '' : 'none';
    g.querySelectorAll('.crf-cond-remove').forEach(b => { b.style.visibility = rows.length > 1 ? 'visible' : 'hidden'; });
  });
}

function addCatConditionGroup(groupLogic = 'AND', conditions = null) {
  const container = document.getElementById('crf-groups');
  if (!container) return;
  container.appendChild(_makeCatGroupBlock(groupLogic, conditions));
  _updateCatGroupUI();
}

function _setCatRuleConditions(conditionsData) {
  const container = document.getElementById('crf-groups');
  if (!container) return;
  container.innerHTML = '';
  if (conditionsData && conditionsData.groups) {
    conditionsData.groups.forEach(g => { addCatConditionGroup(g.group_logic || 'AND', g.conditions); });
  } else {
    addCatConditionGroup('AND', null);
  }
  _updateCatGroupUI();
}

function _getCatRuleConditions() {
  const groups = document.querySelectorAll('#crf-groups .crf-group-block');
  const result = [];
  groups.forEach(g => {
    const logicSel = g.querySelector('.crf-group-logic');
    const groupLogic = logicSel ? logicSel.value : 'AND';
    const rows = g.querySelectorAll('.crf-condition-row');
    const conditions = Array.from(rows).map(row => ({
      pattern:    row.querySelector('.crf-cond-pattern').value.trim(),
      match_type: row.querySelector('.crf-cond-type').value,
      negate:     row.querySelector('.crf-cond-negate').checked,
    }));
    result.push({ group_logic: groupLogic, conditions });
  });
  return { groups: result };
}

function _catRulePatternSummary(r) {
  if (r.conditions && r.conditions.groups) {
    return r.conditions.groups.map(g => {
      const parts = (g.conditions || []).map(c => `${c.negate ? 'NOT ' : ''}${esc(c.match_type)} "${esc(c.pattern)}"`);
      const inner = parts.join(` <span style="color:var(--text-muted);font-size:10px;">${esc(g.group_logic || 'AND')}</span> `);
      return r.conditions.groups.length > 1 ? `(${inner})` : inner;
    }).join(' <span style="color:var(--text-muted);font-size:10px;">AND</span> ');
  }
  return `<span class="mono">${esc(r.raw_category)}</span>`;
}

// ── Category Rules CRUD ───────────────────────────────────────

async function loadCategoryRules() {
  const tbody = document.getElementById('category-rules-tbody');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted" style="padding:24px">Loading…</td></tr>';
  // Ensure crf-parent dropdown is populated (Category Rules page loads independently of Utilities)
  if (_knownParents.length === 0) {
    try {
      const catData = await api('GET', '/utilities/categories');
      _utilCatData = catData.categories || _utilCatData;
      _populateCategoryParentSelects(catData.parents || _utilCatData.map(g => g.parent));
    } catch (_) { /* non-fatal — dropdown will be empty but rule save will still work */ }
  }
  try {
    const data = await api('GET', '/category-rules');
    _allCatRules = data.rules || [];
    if (!_allCatRules.length) {
      tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted" style="padding:24px">No rules yet. Click "+ Add Rule" or use "Analyze My Data" to create them.</td></tr>';
      _updateBadge('cat-rules-count', 0);
      _updateCatRuleSearchCount();
      return;
    }
    _updateBadge('cat-rules-count', _allCatRules.length);
    _renderCatRuleRows(_allCatRules);
    _updateCatRuleSearchCount();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="4" class="text-center text-muted">Error: ${esc(err.message)}</td></tr>`;
  }
}

function _renderCatRuleRows(rules) {
  const tbody = document.getElementById('category-rules-tbody');
  if (!tbody) return;
  tbody.innerHTML = rules.map(r => `<tr>
    <td class="mono" style="font-size:12px;">${_catRulePatternSummary(r)}</td>
    <td>${esc(r.category)}</td>
    <td><span class="badge badge-running" style="font-size:11px;">${esc(r.parent)}</span></td>
    <td>
      <div style="display:flex; gap:6px;">
        <button class="btn btn-secondary btn-sm" onclick="openCatRuleForm(${r.id})">Edit</button>
        <button class="btn btn-danger btn-sm" onclick="deleteCatRule(${r.id})">Delete</button>
      </div>
    </td>
  </tr>`).join('');
}

function openCatRuleForm(ruleId) {
  _editingCatRuleId = ruleId;
  ensureCardExpanded('panel-category-rules');
  const card = document.getElementById('cat-rule-form-card');
  document.getElementById('cat-rule-form-title').textContent = ruleId ? 'Edit Category Rule' : 'Add Category Rule';
  card.style.display = '';
  document.getElementById('crf-status').textContent = '';
  if (!ruleId) {
    document.getElementById('crf-raw').value = '';
    document.getElementById('crf-category').value = '';
    document.getElementById('crf-parent').value = '';
    _setCatRuleConditions(null);
    return;
  }
  api('GET', '/category-rules').then(data => {
    const rule = data.rules.find(r => r.id === ruleId);
    if (!rule) return;
    document.getElementById('crf-raw').value      = rule.raw_category;
    document.getElementById('crf-category').value = rule.category;
    document.getElementById('crf-parent').value   = rule.parent;
    if (rule.conditions && rule.conditions.groups) {
      _setCatRuleConditions(rule.conditions);
    } else {
      // Legacy exact-match: wrap as single condition
      _setCatRuleConditions({groups: [{group_logic: 'AND', conditions: [{pattern: rule.raw_category, match_type: 'exact', negate: false}]}]});
    }
  });
}

function closeCatRuleForm() {
  _editingCatRuleId = null;
  document.getElementById('cat-rule-form-card').style.display = 'none';
}

async function saveCatRule() {
  const category = document.getElementById('crf-category').value.trim();
  const parent   = document.getElementById('crf-parent').value;
  if (!category || !parent) {
    toast('Category and Parent Group are required.', 'error'); return;
  }
  // Get grouped conditions and strip empty patterns
  const grouped = _getCatRuleConditions();
  grouped.groups = grouped.groups.map(g => ({
    ...g,
    conditions: g.conditions.filter(c => c.pattern),
  })).filter(g => g.conditions.length > 0);
  if (!grouped.groups.length) {
    toast('At least one condition pattern is required.', 'error'); return;
  }
  // Backward compat: single group + single condition + exact → store as legacy
  let rawCategory, conditions;
  const isSingle = grouped.groups.length === 1
    && grouped.groups[0].conditions.length === 1
    && grouped.groups[0].conditions[0].match_type === 'exact'
    && !grouped.groups[0].conditions[0].negate;
  if (isSingle) {
    rawCategory = grouped.groups[0].conditions[0].pattern;
    conditions = null; // legacy exact-match
  } else {
    // Use first pattern as raw_category label
    rawCategory = grouped.groups[0].conditions[0].pattern;
    conditions = grouped;
  }
  const body = { raw_category: rawCategory, category, parent, conditions };
  try {
    if (_editingCatRuleId) {
      await api('PUT', `/category-rules/${_editingCatRuleId}`, body);
      toast('Rule updated.', 'success');
    } else {
      await api('POST', '/category-rules', body);
      toast('Rule created.', 'success');
    }
    closeCatRuleForm();
    loadCategoryRules();
  } catch (err) {
    toast(`Failed: ${err.message}`, 'error');
  }
}

function testCatRule() {
  const panel = document.getElementById('crf-test-panel');
  panel.style.display = panel.style.display === 'none' ? '' : 'none';
  if (panel.style.display !== 'none') document.getElementById('crf-test-input').focus();
}

async function runCatRuleTest() {
  const testInput = document.getElementById('crf-test-input').value.trim();
  const resultEl = document.getElementById('crf-test-result');
  const grouped = _getCatRuleConditions();
  grouped.groups = grouped.groups.map(g => ({
    ...g, conditions: g.conditions.filter(c => c.pattern),
  })).filter(g => g.conditions.length > 0);
  if (!grouped.groups.length) {
    resultEl.innerHTML = '<span style="color:var(--danger,#dc3545);">Add at least one condition pattern first.</span>';
    return;
  }
  const category = document.getElementById('crf-category').value.trim();
  const parent = document.getElementById('crf-parent').value;
  resultEl.innerHTML = '<span style="color:var(--text-muted);">Testing…</span>';
  try {
    const data = await api('POST', '/category-rules/test', {
      groups: grouped.groups,
      normalized_category: category || null,
      parent: parent || null,
      test_value: testInput || null,
    });
    let html = '';
    if (testInput) {
      html += data.matches_input
        ? `<span style="color:#16a34a;">✅ "${esc(testInput)}" matches these conditions</span>`
        : `<span style="color:#dc3545;">❌ "${esc(testInput)}" does NOT match</span>`;
      html += '<br/>';
    }
    html += `<span style="color:var(--text-muted);">Live transactions with matching raw category: <strong>${data.live_count}</strong></span>`;
    resultEl.innerHTML = html;
  } catch (err) {
    resultEl.innerHTML = `<span style="color:var(--danger,#dc3545);">Error: ${esc(err.message)}</span>`;
  }
}

async function deleteCatRule(id) {
  if (!confirm('Delete this category rule?')) return;
  try {
    await api('DELETE', `/category-rules/${id}`);
    toast('Rule deleted.', 'success');
    loadCategoryRules();
  } catch (err) {
    toast(`Failed: ${err.message}`, 'error');
  }
}

function filterCatRules() {
  const input = document.getElementById('cat-rules-search');
  const clearBtn = document.getElementById('cat-rules-search-clear');
  const query = (input?.value || '').toLowerCase();
  clearBtn.style.display = query ? '' : 'none';
  if (!query) {
    _renderCatRuleRows(_allCatRules);
    _updateCatRuleSearchCount();
    return;
  }
  const filtered = _allCatRules.filter(r => {
    const raw = (r.raw_category || '').toLowerCase();
    const cat = (r.category || '').toLowerCase();
    const parent = (r.parent || '').toLowerCase();
    let condText = '';
    if (r.conditions && r.conditions.groups) {
      condText = r.conditions.groups.flatMap(g => (g.conditions || []).map(c => c.pattern || '')).join(' ').toLowerCase();
    }
    return raw.includes(query) || cat.includes(query) || parent.includes(query) || condText.includes(query);
  });
  if (filtered.length) {
    _renderCatRuleRows(filtered);
  } else {
    document.getElementById('category-rules-tbody').innerHTML =
      `<tr><td colspan="4" class="text-center text-muted" style="padding:24px">No rules match '${esc(query)}'</td></tr>`;
  }
  _updateCatRuleSearchCount(filtered.length);
}

function _updateCatRuleSearchCount(shown) {
  const el = document.getElementById('cat-rules-search-count');
  if (!el) return;
  const query = (document.getElementById('cat-rules-search')?.value || '').trim();
  if (!query || !_allCatRules.length) { el.textContent = ''; return; }
  el.textContent = `${shown ?? _allCatRules.length} of ${_allCatRules.length} rules`;
}

// ── Category Suggestions ─────────────────────────────────────

async function loadCatSuggestions() {
  const statusEl = document.getElementById('crule-suggest-status');
  const listEl   = document.getElementById('crule-suggestions-list');
  const acceptAllBtn = document.getElementById('crule-suggest-accept-all');
  if (!listEl) return;
  statusEl.textContent = 'Loading…';
  listEl.innerHTML = `<div style="color:var(--text-muted);font-size:13px;padding:4px 0;">Scanning categories…</div>`;
  if (acceptAllBtn) acceptAllBtn.style.display = 'none';
  try {
    const data = await api('GET', '/category-rules/suggestions');
    _catSuggestionsData = data.suggestions || [];
    if (!_catSuggestionsData.length) {
      statusEl.textContent = 'All categories are mapped.';
      listEl.innerHTML = '<span style="color:var(--text-muted);font-size:13px;">No unmapped categories found.</span>';
      return;
    }
    statusEl.textContent = `${_catSuggestionsData.length} unmapped category${_catSuggestionsData.length>1?'s':''}`;
    if (acceptAllBtn) acceptAllBtn.style.display = '';
    _renderCatSuggestions();
  } catch (err) {
    statusEl.textContent = `Error: ${err.message}`;
    listEl.innerHTML = '';
  }
}

function _renderCatSuggestions() {
  const listEl = document.getElementById('crule-suggestions-list');
  if (!listEl) return;
  const visible = _catSuggestionsData.filter(s => !s._dismissed);
  _updateBadge('crule-suggest-count', visible.length);
  if (!visible.length) {
    listEl.innerHTML = '<span style="color:var(--text-muted);font-size:13px;">All suggestions reviewed.</span>';
    const ab = document.getElementById('crule-suggest-accept-all'); if(ab) ab.style.display='none';
    return;
  }
  listEl.innerHTML = visible.map((s, i) => {
    const realIdx = _catSuggestionsData.indexOf(s);
    const builtinBadge = s.is_builtin
      ? `<span style="font-size:10px; background:#22c55e22; color:#16a34a; border-radius:4px; padding:1px 6px; font-weight:600;">built-in</span>`
      : `<span style="font-size:10px; background:#94a3b822; color:#64748b; border-radius:4px; padding:1px 6px;">manual</span>`;
    return `<div style="display:flex; gap:12px; align-items:flex-start; padding:8px 12px; background:var(--bg-alt,#f8faff); border-radius:8px; border:1px solid var(--border);">
      <div style="flex:1; min-width:0;">
        <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
          ${builtinBadge}
          <span class="mono" style="font-size:13px; font-weight:600;">${esc(s.raw_category)}</span>
          <span style="color:var(--text-muted);">→</span>
          <span style="font-size:13px;">${esc(s.category)}</span>
          <span style="font-size:11px; color:var(--text-muted); background:#e2e8f0; border-radius:10px; padding:1px 8px;">${esc(s.parent)}</span>
          <span style="font-size:11px; color:var(--text-muted);">${s.count} tx</span>
        </div>
      </div>
      <div style="display:flex; gap:6px; flex-shrink:0;">
        <button class="btn btn-primary btn-sm" onclick="acceptCatSuggestion(${realIdx})">✓ Accept</button>
        <button class="btn btn-secondary btn-sm" onclick="editCatSuggestion(${realIdx})">Edit</button>
        <button class="btn btn-secondary btn-sm" style="color:var(--text-muted); font-size:11px;" onclick="dismissCatSuggestion(${realIdx})">Dismiss</button>
      </div>
    </div>`;
  }).join('');
}

/** Accept a raw-category→normalized mapping suggestion. Operates on _catSuggestionsData
 *  (from /category-rules/suggestions) and POSTs to /category-rules. */
async function acceptCatSuggestion(idx) {
  const s = _catSuggestionsData[idx]; if (!s) return;
  try {
    await api('POST', '/category-rules', { raw_category: s.raw_category, category: s.category, parent: s.parent });
    s._dismissed = true;
    toast(`Rule created: "${s.raw_category}" → ${s.category}`, 'success');
    _renderCatSuggestions();
    loadCategoryRules();
  } catch (err) { toast(`Failed: ${err.message}`, 'error'); }
}

function editCatSuggestion(idx) {
  const s = _catSuggestionsData[idx]; if (!s) return;
  openCatRuleForm(null);
  document.getElementById('crf-raw').value      = s.raw_category;
  document.getElementById('crf-category').value = s.category;
  document.getElementById('crf-parent').value   = s.parent;
  s._dismissed = true;
  _renderCatSuggestions();
  document.getElementById('cat-rule-form-card').scrollIntoView({ behavior:'smooth', block:'nearest' });
}

/** Dismiss a raw-category→normalized mapping suggestion. Persists to DB. */
async function dismissCatSuggestion(idx) {
  const s = _catSuggestionsData[idx];
  if (!s) return;
  try {
    await api('POST', `/merchant-categories/suggestions/${encodeURIComponent(s.raw_category || s.merchant || idx)}/dismiss`);
    s._dismissed = true;
    _renderCatSuggestions();
  } catch (err) {
    toast(`Dismiss failed: ${err.message}`, 'error');
  }
}

async function acceptAllCatSuggestions() {
  const visible = _catSuggestionsData.filter(s => !s._dismissed);
  if (!visible.length) return;
  let ok = 0, fail = 0;
  for (const s of visible) {
    try {
      await api('POST', '/category-rules', { raw_category: s.raw_category, category: s.category, parent: s.parent });
      s._dismissed = true; ok++;
    } catch (_) { fail++; }
  }
  toast(`${ok} rule${ok!==1?'s':''} created${fail?` (${fail} failed)`:''}`, ok?'success':'error');
  _renderCatSuggestions();
  loadCategoryRules();
}

// ── Category Normalization Apply ──────────────────────────────

let _catNormJobId = null;
let _catNormPoll  = null;

async function startCategoryNormalize() {
  if (!confirm('Apply category rules to all transactions? This may take a moment.')) return;
  const statusEl = document.getElementById('cat-norm-status');
  statusEl.textContent = 'Starting…';
  try {
    const data = await api('POST', '/category-rules/apply');
    _catNormJobId = data.job_id;
    statusEl.textContent = `Job started…`;
    _pollCatNorm();
  } catch (err) {
    statusEl.textContent = `Error: ${err.message}`;
  }
}

function _pollCatNorm() {
  if (_catNormPoll) clearInterval(_catNormPoll);
  _catNormPoll = setInterval(async () => {
    try {
      const data = await api('GET', `/normalize/${_catNormJobId}`);
      const statusEl = document.getElementById('cat-norm-status');
      if (data.status === 'success') {
        clearInterval(_catNormPoll);
        statusEl.textContent = `Done — ${data.rows_done} transactions normalized.`;
        toast('Category normalization complete.', 'success');
      } else if (data.status === 'failed') {
        clearInterval(_catNormPoll);
        statusEl.textContent = `Failed: ${data.error || 'unknown error'}`;
      } else {
        const pct = data.rows_total ? Math.round(data.rows_done / data.rows_total * 100) : 0;
        if(statusEl) statusEl.textContent = `Running… ${data.rows_done}/${data.rows_total} (${pct}%)`;
      }
    } catch (_) {}
  }, 1500);
}

// ── Date presets ──────────────────────────────────────────────

// ── Year filter logic ──────────────────────────────────────────
let _txnYears = [];
let _txnYearsLoaded = false;

async function _loadTxnYears(forceRefresh) {
  if (_txnYearsLoaded && !forceRefresh) return;
  try {
    const data = await api('GET', '/transactions/years');
    _txnYears = data.years || [];
    _txnYearsLoaded = true;
  } catch { _txnYears = []; }
  _populateYearDropdowns();
}

function _populateYearDropdowns() {
  const now = new Date();
  const currentYear = now.getFullYear();
  ['cc-year', 'bk-year'].forEach(id => {
    const sel = document.getElementById(id);
    if (!sel) return;
    // Preserve current selection when refreshing
    const prev = sel.value;
    sel.innerHTML = '';
    // Add year options — default to current year, fallback to most recent with data
    const years = _txnYears.length ? _txnYears : [currentYear];
    years.forEach(y => {
      const opt = document.createElement('option');
      opt.value = String(y); opt.textContent = String(y);
      sel.appendChild(opt);
    });
    const allOpt = document.createElement('option');
    allOpt.value = 'all'; allOpt.textContent = 'All Years';
    sel.appendChild(allOpt);
    // Restore previous selection if still valid, otherwise default
    if (prev && Array.from(sel.options).some(o => o.value === prev)) {
      sel.value = prev;
    } else if (years.includes(currentYear)) {
      sel.value = String(currentYear);
    } else {
      sel.value = String(years[0]);
    }
  });
  // Populate cash flow year options
  _populateCfYearOptions();
}

function _populateCfYearOptions() {
  const sel = document.getElementById('cf-period');
  if (!sel) return;
  // Remove existing year_* options
  Array.from(sel.options).filter(o => o.value.startsWith('year_')).forEach(o => o.remove());
  // Insert year options before "Custom Range"
  const customOpt = Array.from(sel.options).find(o => o.value === 'custom');
  _txnYears.forEach(y => {
    const opt = document.createElement('option');
    opt.value = 'year_' + y;
    opt.textContent = String(y);
    sel.insertBefore(opt, customOpt);
  });
}

function _getSelectedYear(tab) {
  const id = tab === 'credit_card' ? 'cc-year' : 'bk-year';
  const sel = document.getElementById(id);
  return sel ? sel.value : 'all';
}

function onYearChange(tab) {
  const year = _getSelectedYear(tab);
  const prefix = tab === 'credit_card' ? 'cc' : 'bk';
  const fromEl = document.getElementById(prefix + '-date-from');
  const toEl = document.getElementById(prefix + '-date-to');
  if (year === 'all') {
    if (fromEl) fromEl.value = '';
    if (toEl) toEl.value = '';
  } else {
    const y = parseInt(year);
    if (fromEl) fromEl.value = y + '-01-01';
    if (toEl) toEl.value = y + '-12-31';
  }
  loadTxnTab(tab);
}

function onDateManualChange(tab) {
  const prefix = tab === 'credit_card' ? 'cc' : 'bk';
  const fromVal = document.getElementById(prefix + '-date-from')?.value || '';
  const toVal = document.getElementById(prefix + '-date-to')?.value || '';
  const yearSel = document.getElementById(prefix + '-year');
  if (yearSel && yearSel.value !== 'all') {
    const y = yearSel.value;
    // If dates span outside selected year, snap to "All Years"
    if ((fromVal && !fromVal.startsWith(y)) || (toVal && !toVal.startsWith(y))) {
      yearSel.value = 'all';
    }
  }
  loadTxnTab(tab);
}

function _presetDates(preset, yearOverride) {
  const now = new Date();
  const yr = yearOverride || now.getFullYear();
  const isPast = yr < now.getFullYear();
  let from, to;
  const pad = n => String(n).padStart(2,'0');
  const fmt = d => `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
  switch (preset) {
    case 'this_month': {
      from = new Date(yr, now.getMonth(), 1);
      to   = new Date(yr, now.getMonth()+1, 0);
      break;
    }
    case 'last_month': {
      from = new Date(yr, now.getMonth()-1, 1);
      to   = new Date(yr, now.getMonth(), 0);
      break;
    }
    case '3months': {
      from = new Date(yr, now.getMonth()-2, 1);
      to   = new Date(yr, now.getMonth()+1, 0);
      break;
    }
    case 'ytd': {
      from = new Date(yr, 0, 1);
      to   = isPast ? new Date(yr, 11, 31) : now;
      break;
    }
    case 'all': {
      from = new Date(yr, 0, 1);
      to   = new Date(yr, 11, 31);
      break;
    }
    default: { from = null; to = null; }
  }
  return { from: from ? fmt(from) : '', to: to ? fmt(to) : '' };
}

function setDatePreset(tab, preset) {
  const year = _getSelectedYear(tab);
  const yr = year === 'all' ? null : parseInt(year);
  const { from, to } = _presetDates(preset, yr);
  if (tab === 'credit_card') {
    const f = document.getElementById('cc-date-from');
    const t = document.getElementById('cc-date-to');
    if (f) f.value = from;
    if (t) t.value = to;
    loadTxnTab('credit_card');
  } else if (tab === 'bank') {
    const f = document.getElementById('bk-date-from');
    const t = document.getElementById('bk-date-to');
    if (f) f.value = from;
    if (t) t.value = to;
    loadTxnTab('bank');
  }
}

function setReportDatePreset(preset) {
  const { from, to } = _presetDates(preset);
  const f = document.getElementById('report-date-from');
  const t = document.getElementById('report-date-to');
  if (f) f.value = from;
  if (t) t.value = to;
}

// ── Savings Goals ─────────────────────────────────────────────

let _editingSavingsId = null;

function openSavingsForm(goal) {
  _editingSavingsId = goal ? goal.id : null;
  document.getElementById('sf-id').value = goal ? goal.id : '';
  document.getElementById('sf-name').value = goal ? goal.name : '';
  document.getElementById('sf-target').value = goal ? goal.target_amount : '';
  document.getElementById('sf-current').value = goal ? goal.current_amount : 0;
  document.getElementById('sf-date').value = goal ? (goal.target_date || '') : '';
  document.getElementById('sf-account').value = goal ? (goal.linked_account || '') : '';
  document.getElementById('sf-suggestion').textContent = '';
  document.getElementById('savings-form').style.display = '';
}

function closeSavingsForm() {
  document.getElementById('savings-form').style.display = 'none';
  _editingSavingsId = null;
}

async function saveSavingsGoal() {
  const name = document.getElementById('sf-name').value.trim();
  const target = parseFloat(document.getElementById('sf-target').value);
  const current = parseFloat(document.getElementById('sf-current').value) || 0;
  const targetDate = document.getElementById('sf-date').value || null;
  const account = document.getElementById('sf-account').value.trim() || null;
  if (!name || isNaN(target) || target <= 0) {
    toast('Name and a positive target amount are required.', 'error'); return;
  }
  const payload = { name, target_amount: target, current_amount: current,
                    target_date: targetDate, linked_account: account };
  try {
    if (_editingSavingsId) {
      await api('PUT', `/savings-goals/${_editingSavingsId}`, payload);
      toast('Goal updated.', 'success');
    } else {
      await api('POST', '/savings-goals', payload);
      toast('Goal created.', 'success');
    }
    closeSavingsForm();
    loadDashboard();
  } catch (err) {
    toast(`Failed: ${err.message}`, 'error');
  }
}

async function deleteSavingsGoal(id) {
  if (!confirm('Delete this savings goal?')) return;
  try {
    await api('DELETE', `/savings-goals/${id}`);
    toast('Goal deleted.', 'success');
    loadDashboard();
  } catch (err) {
    toast(`Failed: ${err.message}`, 'error');
  }
}

async function updateSavingsProgress(id) {
  const input = document.getElementById(`sp-input-${id}`);
  if (!input) return;
  const amount = parseFloat(input.value);
  if (isNaN(amount)) { toast('Enter a valid amount.', 'error'); return; }
  const mode = document.getElementById(`sp-mode-${id}`)?.value || 'set';
  try {
    await api('POST', `/savings-goals/${id}/update-progress`, { amount, mode });
    toast('Progress updated.', 'success');
    loadDashboard();
  } catch (err) {
    toast(`Failed: ${err.message}`, 'error');
  }
}

async function loadSavingsSuggestion() {
  const el = document.getElementById('sf-suggestion');
  if (el) el.textContent = 'Calculating…';
  try {
    const data = await api('GET', '/savings-goals/suggestions');
    if (el) {
      if (data.suggested_monthly_savings > 0) {
        el.textContent = `Avg net: ${_fmt$(data.avg_monthly_net)}/mo → Suggested: ${_fmt$(data.suggested_monthly_savings)}/mo (${data.months_analysed} months analysed)`;
      } else {
        el.textContent = `Avg net: ${_fmt$(data.avg_monthly_net)}/mo (no surplus to save)`;
      }
    }
  } catch (err) {
    if (el) el.textContent = 'Could not calculate suggestion.';
  }
}

function _renderSavingsGoals(goals) {
  const el = document.getElementById('dash-savings-list');
  if (!el) return;
  if (!goals || !goals.length) {
    el.innerHTML = '<span style="color:var(--text-muted); font-size:13px;">No savings goals yet. Click "+ New Goal" to create one.</span>';
    return;
  }
  el.innerHTML = goals.map(g => {
    const pct = Math.min(g.pct || 0, 100);
    const remaining = Math.max(g.target_amount - g.current_amount, 0);
    const color = pct >= 100 ? '#22c55e' : pct >= 60 ? '#3b82f6' : '#f59e0b';

    // Calculate required monthly savings if target date exists
    let monthlyNeeded = '';
    if (g.target_date && remaining > 0) {
      const today = new Date();
      const target = new Date(g.target_date);
      const monthsLeft = Math.max(
        (target.getFullYear() - today.getFullYear()) * 12 +
        (target.getMonth() - today.getMonth()), 1
      );
      const perMonth = remaining / monthsLeft;
      monthlyNeeded = `<span style="font-size:11px; color:var(--text-muted);">Need ${_fmt$(perMonth)}/mo to reach target</span>`;
    } else if (pct >= 100) {
      monthlyNeeded = '<span style="font-size:11px; color:#22c55e; font-weight:600;">Goal reached!</span>';
    }

    const dateLabel = g.target_date
      ? `<span style="font-size:11px; color:var(--text-muted);">Target: ${g.target_date}</span>`
      : '';

    return `<div class="savings-goal-card">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
        <span style="font-weight:600; font-size:13px;">${esc(g.name)}</span>
        <div style="display:flex; gap:4px; align-items:center;">
          ${dateLabel}
          <button class="btn btn-secondary btn-sm" style="padding:2px 6px; font-size:10px;" onclick="openSavingsForm(${esc(JSON.stringify(g))})">Edit</button>
          <button class="btn btn-secondary btn-sm" style="padding:2px 6px; font-size:10px; color:var(--danger);" onclick="deleteSavingsGoal(${g.id})">Del</button>
        </div>
      </div>
      <div style="display:flex; justify-content:space-between; font-size:12px; margin-bottom:3px;">
        <span>${_fmt$(g.current_amount)} / ${_fmt$(g.target_amount)}</span>
        <span style="color:${color}; font-weight:600;">${pct}%</span>
      </div>
      <div class="savings-bar-track">
        <div class="savings-bar-fill" style="width:${pct}%; background:${color};"></div>
      </div>
      <div style="display:flex; justify-content:space-between; align-items:center; margin-top:4px;">
        ${monthlyNeeded}
        <div style="display:flex; gap:4px; align-items:center;">
          <select id="sp-mode-${g.id}" style="padding:2px 4px; font-size:11px; border:1px solid var(--border); border-radius:4px;">
            <option value="set">Set to</option>
            <option value="add">Add</option>
          </select>
          <input type="number" id="sp-input-${g.id}" placeholder="$" min="0" step="0.01"
            style="width:80px; padding:3px 6px; font-size:11px; border:1px solid var(--border); border-radius:4px;" />
          <button class="btn btn-primary btn-sm" style="padding:2px 8px; font-size:10px;"
            onclick="updateSavingsProgress(${g.id})">Update</button>
        </div>
      </div>
    </div>`;
  }).join('');
}

// ── Monthly Summary ───────────────────────────────────────────

let _summaryYear = _dashYear;
let _summaryMonth = _dashMonth;

function openMonthlySummary() {
  _summaryYear = _dashYear;
  _summaryMonth = _dashMonth;
  document.getElementById('monthly-summary-modal').classList.remove('hidden');
  _loadMonthlySummary();
}
function closeMonthlySummary() {
  document.getElementById('monthly-summary-modal').classList.add('hidden');
}

// ── Category Drill-Down (app-wide) ──────────────────────────
let _drillCategory = '';
let _drillDateFrom = '';
let _drillDateTo = '';
let _drillRows = [];

/** Derive the correct transaction tab from statement_type data.
 *  Tie defaults to credit_card. */
function resolveTransactionTab(transactions) {
  const cc = transactions.filter(t => t.statement_type === 'credit_card').length;
  const bank = transactions.filter(t => t.statement_type === 'bank').length;
  if (cc > 0 && bank === 0) return 'credit_card';
  if (bank > 0 && cc === 0) return 'bank';
  return cc >= bank ? 'credit_card' : 'bank';
}

async function openCategoryDrilldown(categoryParent, dateFrom, dateTo) {
  _drillCategory = categoryParent;

  // Default to dashboard month if no dates provided
  if (!dateFrom || !dateTo) {
    const m = String(_dashMonth).padStart(2, '0');
    dateFrom = `${_dashYear}-${m}-01`;
    const lastDay = new Date(_dashYear, _dashMonth, 0).getDate();
    dateTo = `${_dashYear}-${m}-${String(lastDay).padStart(2, '0')}`;
  }
  _drillDateFrom = dateFrom;
  _drillDateTo = dateTo;

  // Build title from date range
  const titleEl = document.getElementById('cat-drill-title');
  const fd = new Date(dateFrom + 'T00:00:00');
  const td = new Date(dateTo + 'T00:00:00');
  const monthNames = ['','Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  let titleDate;
  if (fd.getFullYear() === td.getFullYear() && fd.getMonth() === td.getMonth()) {
    titleDate = `${monthNames[fd.getMonth() + 1]} ${fd.getFullYear()}`;
  } else {
    titleDate = `${dateFrom} to ${dateTo}`;
  }
  titleEl.textContent = `${categoryParent} — ${titleDate}`;
  document.getElementById('cat-drill-body').innerHTML = '<div style="text-align:center; padding:40px; color:var(--text-muted);">Loading…</div>';
  document.getElementById('category-drilldown-modal').classList.remove('hidden');

  try {
    const data = await api('GET',
      `/transactions?category_parent=${encodeURIComponent(categoryParent)}&date_from=${dateFrom}&date_to=${dateTo}&limit=500&sort_by=amount&sort_dir=asc`
    );
    const rows = data.rows || [];
    _drillRows = rows;
    if (!rows.length) {
      document.getElementById('cat-drill-body').innerHTML = '<div style="text-align:center; padding:40px; color:var(--text-muted);">No transactions found.</div>';
      return;
    }
    const subtotal = rows.reduce((s, r) => s + (r.amount || 0), 0);
    let html = `<table style="width:100%; border-collapse:collapse; font-size:13px;">
      <thead><tr style="border-bottom:2px solid var(--border);">
        <th style="text-align:left; padding:6px 8px;">Date</th>
        <th style="text-align:left; padding:6px 8px;">Description</th>
        <th style="text-align:left; padding:6px 8px;">Merchant</th>
        <th style="text-align:right; padding:6px 8px;">Amount</th>
        <th style="text-align:left; padding:6px 8px;">Account</th>
      </tr></thead><tbody>`;
    html += rows.map(r => `<tr style="border-bottom:1px solid var(--border);">
      <td style="padding:5px 8px; white-space:nowrap;">${esc(r.transaction_date)}</td>
      <td style="padding:5px 8px; max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${esc(r.description)}">${esc(r.description)}</td>
      <td style="padding:5px 8px;">${esc(r.merchant || '')}</td>
      <td style="padding:5px 8px; text-align:right; font-variant-numeric:tabular-nums;">${_fmt$(r.amount)}</td>
      <td style="padding:5px 8px;">${esc(r.account_name || '')}</td>
    </tr>`).join('');
    html += `</tbody><tfoot><tr style="border-top:2px solid var(--border); font-weight:700;">
      <td colspan="3" style="padding:6px 8px;">Subtotal (${rows.length} transactions)</td>
      <td style="padding:6px 8px; text-align:right;">${_fmt$(subtotal)}</td>
      <td></td>
    </tr></tfoot></table>`;
    document.getElementById('cat-drill-body').innerHTML = html;
  } catch (err) {
    document.getElementById('cat-drill-body').innerHTML = `<div style="text-align:center; padding:40px; color:var(--text-muted);">Error: ${esc(err.message)}</div>`;
  }
}

function closeCategoryDrilldown() {
  document.getElementById('category-drilldown-modal').classList.add('hidden');
}

function categoryDrilldownViewAll() {
  const tab = resolveTransactionTab(_drillRows);
  const isMixed = _drillRows.some(r => r.statement_type === 'credit_card') &&
                  _drillRows.some(r => r.statement_type === 'bank');
  closeCategoryDrilldown();
  const page = tab === 'credit_card' ? 'credit-cards' : 'bank-transactions';
  const prefix = tab === 'credit_card' ? 'cc' : 'bk';
  navigate(page);
  setTimeout(() => {
    const fromEl = document.getElementById(prefix + '-date-from');
    const toEl   = document.getElementById(prefix + '-date-to');
    if (fromEl) fromEl.value = _drillDateFrom;
    if (toEl)   toEl.value   = _drillDateTo;
    const catEl = document.getElementById(prefix + '-category');
    if (catEl) catEl.value = _drillCategory;
    loadTxnTab(tab);
    if (isMixed) {
      const majorityCount = _drillRows.filter(r => r.statement_type === tab).length;
      toast('Showing ' + majorityCount + ' of ' + _drillRows.length +
        ' transactions — this category spans both credit card and bank. Switch tabs to see the rest.', 'info', 6000);
    }
  }, 100);
}

function summaryPrevMonth() {
  _summaryMonth--;
  if (_summaryMonth < 1) { _summaryMonth = 12; _summaryYear--; }
  _loadMonthlySummary();
}
function summaryNextMonth() {
  _summaryMonth++;
  if (_summaryMonth > 12) { _summaryMonth = 1; _summaryYear++; }
  _loadMonthlySummary();
}

async function _loadMonthlySummary() {
  const title = document.getElementById('ms-title');
  const body = document.getElementById('ms-body');
  const badge = document.getElementById('ms-stored-badge');
  if (title) title.textContent = `${_MONTH_NAMES[_summaryMonth - 1]} ${_summaryYear}`;
  if (body) body.innerHTML = '<div style="text-align:center; padding:40px; color:var(--text-muted);">Loading…</div>';
  if (badge) badge.textContent = '';

  try {
    const data = await api('GET', `/monthly-summaries/${_summaryYear}/${_summaryMonth}`);
    if (badge) badge.textContent = data.stored ? 'Saved' : 'Not saved';
    _renderMonthlySummary(body, data);
  } catch (err) {
    if (body) body.innerHTML = `<div style="color:var(--danger); padding:20px;">Failed to load: ${esc(err.message)}</div>`;
  }
}

function _renderMonthlySummary(el, data) {
  if (!el) return;
  const s = data.summary || {};
  const narrative = data.narrative || '';

  // Narrative paragraph
  let html = `<div class="ms-narrative">${esc(narrative)}</div>`;

  // KPI grid
  html += `<div class="ms-kpi-grid">
    <div class="ms-kpi"><div class="ms-kpi-label">Total Spent</div><div class="ms-kpi-value">${_fmt$(s.total_spent)}</div></div>
    <div class="ms-kpi"><div class="ms-kpi-label">Total Income</div><div class="ms-kpi-value" style="color:#22c55e;">${_fmt$(s.total_income)}</div></div>
    <div class="ms-kpi"><div class="ms-kpi-label">Net Savings</div><div class="ms-kpi-value" style="color:${(s.net_savings||0)>=0?'#22c55e':'#ef4444'};">${_fmt$(s.net_savings)}</div></div>
    <div class="ms-kpi"><div class="ms-kpi-label">Transactions</div><div class="ms-kpi-value">${s.txn_count || 0}</div></div>
  </div>`;

  // vs Prior Month
  if (s.spend_delta_pct != null) {
    const arrow = s.spend_delta_pct >= 0 ? '▲' : '▼';
    const color = s.spend_delta_pct >= 0 ? '#ef4444' : '#22c55e';
    html += `<div style="font-size:13px; margin-bottom:12px;">vs. prior month: <span style="color:${color}; font-weight:600;">${arrow} ${Math.abs(s.spend_delta_pct)}%</span> (was ${_fmt$(s.prev_month_spent)})</div>`;
  }

  // Top categories
  if (s.top_categories && s.top_categories.length) {
    html += '<div style="font-size:13px; font-weight:600; margin-bottom:6px;">Top Categories</div>';
    const maxAmt = Math.max(...s.top_categories.map(c => c.amount), 1);
    const sm = String(_summaryMonth).padStart(2, '0');
    const smFrom = `${_summaryYear}-${sm}-01`;
    const smLastDay = new Date(_summaryYear, _summaryMonth, 0).getDate();
    const smTo = `${_summaryYear}-${sm}-${String(smLastDay).padStart(2, '0')}`;
    html += s.top_categories.map(c => {
      const pct = Math.round(c.amount / maxAmt * 100);
      const delta = c.delta_pct != null
        ? ` <span style="font-size:11px; color:${c.delta_pct >= 0 ? '#ef4444' : '#22c55e'};">${c.delta_pct >= 0 ? '▲' : '▼'}${Math.abs(c.delta_pct)}%</span>`
        : '';
      const jsonCat = JSON.stringify(c.name).replace(/'/g, '&#39;').replace(/"/g, '&quot;');
      return `<div style="margin-bottom:6px; cursor:pointer; padding:2px 4px; border-radius:4px; transition:background .12s;" onclick="openCategoryDrilldown(${jsonCat}, '${smFrom}', '${smTo}')" onmouseenter="this.style.background='var(--bg,#f1f5f9)'" onmouseleave="this.style.background=''">
        <div style="display:flex; justify-content:space-between; font-size:12px; margin-bottom:2px;">
          <span>${esc(c.name)}${delta}</span><span style="font-weight:600;">${_fmt$(c.amount)}</span>
        </div>
        <div style="background:var(--border); border-radius:4px; height:5px;">
          <div style="background:var(--primary,#3b82f6); border-radius:4px; height:5px; width:${pct}%;"></div>
        </div>
      </div>`;
    }).join('');
  }

  // Top merchants
  if (s.top_merchants && s.top_merchants.length) {
    html += '<div style="font-size:13px; font-weight:600; margin:10px 0 6px;">Top Merchants</div>';
    html += '<div style="display:flex; flex-wrap:wrap; gap:6px;">';
    html += s.top_merchants.map(m =>
      `<span class="ms-merchant-chip">${esc(m.name)} · ${_fmt$(m.amount)}</span>`
    ).join('');
    html += '</div>';
  }

  // Biggest transaction
  if (s.biggest_transaction) {
    const b = s.biggest_transaction;
    const label = b.merchant || b.description;
    html += `<div style="margin-top:12px; padding:10px; background:var(--bg-alt,#f8f9fa); border-radius:8px; font-size:12px;">
      <span style="font-weight:600;">Biggest Purchase:</span> ${_fmt$(b.amount)} at ${esc(label)}${b.category ? ' (' + esc(b.category) + ')' : ''}${b.date ? ' on ' + esc(b.date) : ''}
    </div>`;
  }

  el.innerHTML = html;
}

async function generateAndStoreSummary() {
  try {
    await api('POST', `/monthly-summaries/generate?year=${_summaryYear}&month=${_summaryMonth}`);
    toast('Summary saved.', 'success');
    _loadMonthlySummary();
  } catch (err) {
    toast(`Failed: ${err.message}`, 'error');
  }
}

async function openSummaryHistory() {
  const modal = document.getElementById('summary-history-modal');
  const body = document.getElementById('sh-body');
  modal.classList.remove('hidden');
  body.innerHTML = '<div style="text-align:center; padding:24px; color:var(--text-muted);">Loading…</div>';

  try {
    const data = await api('GET', '/monthly-summaries');
    if (!data.summaries || !data.summaries.length) {
      body.innerHTML = '<div style="text-align:center; padding:24px; color:var(--text-muted);">No saved summaries yet. Use "Save Summary" to store one.</div>';
      return;
    }
    body.innerHTML = data.summaries.map(s => {
      const spent = s.summary?.total_spent;
      const net = s.summary?.net_savings;
      return `<div class="sh-item" onclick="closeSummaryHistory();_summaryYear=${s.year};_summaryMonth=${s.month};openMonthlySummary();" style="cursor:pointer;">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <span style="font-weight:600; font-size:13px;">${_MONTH_NAMES[s.month-1]} ${s.year}</span>
          <div style="font-size:12px; text-align:right;">
            <span>Spent: ${spent != null ? _fmt$(spent) : '—'}</span>
            ${net != null ? `<span style="margin-left:8px; color:${net>=0?'#22c55e':'#ef4444'};">Net: ${_fmt$(net)}</span>` : ''}
          </div>
        </div>
        <div style="font-size:11px; color:var(--text-muted); margin-top:4px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${esc(s.narrative || '').substring(0, 120)}…</div>
      </div>`;
    }).join('');
  } catch (err) {
    body.innerHTML = `<div style="color:var(--danger); padding:20px;">${esc(err.message)}</div>`;
  }
}

function closeSummaryHistory() {
  document.getElementById('summary-history-modal').classList.add('hidden');
}

// ── Cash Flow ──────────────────────────────────────────────────

function onCfPeriodChange() {
  const sel = document.getElementById('cf-period');
  const custom = document.getElementById('cf-custom-range');
  if (sel && custom) {
    const isCustom = sel.value === 'custom';
    const isYear = sel.value.startsWith('year_');
    custom.style.display = isCustom ? '' : 'none';
    if (isYear) {
      // Year selection → set custom dates for full year and load
      const yr = parseInt(sel.value.replace('year_', ''));
      document.getElementById('cf-date-from').value = yr + '-01-01';
      document.getElementById('cf-date-to').value = yr + '-12-31';
    }
  }
  if (sel && sel.value !== 'custom') loadCashFlow();
}

async function loadCashFlow() {
  const periodRaw = document.getElementById('cf-period')?.value || 'last_3_months';
  const transfers = document.getElementById('cf-transfers')?.checked || false;

  // Map year_YYYY selections to custom range
  let period = periodRaw;
  let url;
  if (periodRaw.startsWith('year_')) {
    const yr = periodRaw.replace('year_', '');
    url = `/cashflow/summary?period=custom&include_transfers=${transfers}&start_date=${yr}-01-01&end_date=${yr}-12-31`;
  } else {
    url = `/cashflow/summary?period=${period}&include_transfers=${transfers}`;
  }
  if (period === 'custom') {
    const from = document.getElementById('cf-date-from')?.value;
    const to   = document.getElementById('cf-date-to')?.value;
    if (from) url += `&start_date=${from}`;
    if (to)   url += `&end_date=${to}`;
  }

  try {
    const data = await api('GET', url);
    _renderCashFlow(data);
  } catch (err) {
    const el = document.getElementById('cf-income');
    if (el) el.textContent = 'Error';
    toast(`Cash flow: ${err.message}`, 'error');
  }
}

function _renderCashFlow(data) {
  const set = (id, html) => { const el = document.getElementById(id); if (el) el.innerHTML = html; };
  const s = data.summary;

  // KPI cards
  set('cf-income',   _fmt$(s.total_income));
  set('cf-spending', _fmt$(s.total_spending));

  const netColor = s.net >= 0 ? '#22c55e' : '#ef4444';
  set('cf-net', `<span style="color:${netColor}">${s.net >= 0 ? '+' : ''}${_fmt$(s.net)}</span>`);

  // Month-over-month delta
  if (data.mom_delta) {
    const d = data.mom_delta;
    const arrow = d.spending_delta >= 0 ? '▲' : '▼';
    const color = d.spending_delta >= 0 ? '#ef4444' : '#22c55e';
    const sign  = d.spending_delta >= 0 ? '+' : '-';
    set('cf-mom-delta', `<span style="color:${color}">${arrow} ${sign}${_fmt$(Math.abs(d.spending_delta))}</span>`);
    set('cf-mom-detail', `spending vs prior month`);
  } else {
    set('cf-mom-delta', '—');
    set('cf-mom-detail', 'Not enough data');
  }

  // Bar chart
  _renderCfChart(data.monthly);

  // Category breakdown
  _renderCfCategories(data.by_category);

  // Monthly detail table
  _renderCfTable(data.monthly);
}

function _renderCfChart(monthly) {
  const el = document.getElementById('cf-chart');
  const legendEl = document.getElementById('cf-chart-legend');
  if (!el) return;

  if (!monthly.length) {
    el.innerHTML = '<span style="color:var(--text-muted); font-size:13px; padding:20px;">No data for selected period.</span>';
    if (legendEl) legendEl.innerHTML = '';
    return;
  }

  const maxVal = Math.max(...monthly.flatMap(m => [m.income, m.spending]), 1);
  const chartH = 180;

  el.innerHTML = monthly.map(m => {
    const incH = Math.max(Math.round(m.income / maxVal * chartH), 2);
    const spnH = Math.max(Math.round(m.spending / maxVal * chartH), 2);
    const label = m.month.slice(0, 7); // YYYY-MM
    const shortLabel = _MONTH_NAMES[parseInt(m.month.slice(5,7), 10) - 1]?.slice(0, 3) || label;
    return `<div class="cf-bar-group" title="${label}">
      <div class="cf-bar-pair" style="height:${chartH}px;">
        <div class="cf-bar cf-bar-income" style="height:${incH}px;" title="Income: ${_fmt$(m.income)}"></div>
        <div class="cf-bar cf-bar-spending" style="height:${spnH}px;" title="Spending: ${_fmt$(m.spending)}"></div>
      </div>
      <div class="cf-bar-label">${esc(shortLabel)}</div>
    </div>`;
  }).join('');

  if (legendEl) {
    legendEl.innerHTML = `
      <span><span class="cf-legend-dot" style="background:#22c55e;"></span> Income</span>
      <span><span class="cf-legend-dot" style="background:#ef4444;"></span> Spending</span>
    `;
  }
}

function _getCfDateRange() {
  const periodRaw = document.getElementById('cf-period')?.value || 'last_3_months';
  if (periodRaw === 'custom') {
    return { from: document.getElementById('cf-date-from')?.value, to: document.getElementById('cf-date-to')?.value };
  }
  if (periodRaw.startsWith('year_')) {
    const yr = periodRaw.replace('year_', '');
    return { from: yr + '-01-01', to: yr + '-12-31' };
  }
  // For preset periods, compute approximate range
  const now = new Date();
  const to = now.toISOString().slice(0, 10);
  const months = { last_3_months: 3, last_6_months: 6, last_12_months: 12, ytd: now.getMonth() + 1 };
  const m = months[periodRaw] || 3;
  const fd = new Date(now.getFullYear(), now.getMonth() - m + 1, 1);
  return { from: fd.toISOString().slice(0, 10), to };
}

function _renderCfCategories(cats) {
  const el = document.getElementById('cf-cat-list');
  if (!el) return;

  if (!cats.length) {
    el.innerHTML = '<span style="color:var(--text-muted); font-size:13px;">No spending data.</span>';
    return;
  }

  const dr = _getCfDateRange();
  const maxAmt = Math.max(...cats.map(c => c.amount), 1);
  el.innerHTML = cats.map(c => {
    const pct = Math.round(c.amount / maxAmt * 100);
    const jsonCat = JSON.stringify(c.category).replace(/'/g, '&#39;').replace(/"/g, '&quot;');
    return `<div style="margin-bottom:6px; cursor:pointer; padding:2px 4px; border-radius:4px; transition:background .12s;" onclick="openCategoryDrilldown(${jsonCat}, '${dr.from}', '${dr.to}')" onmouseenter="this.style.background='var(--bg,#f1f5f9)'" onmouseleave="this.style.background=''">
      <div style="display:flex; justify-content:space-between; font-size:13px; margin-bottom:2px;">
        <span>${esc(c.category)}</span>
        <span style="font-weight:600;">${_fmt$(c.amount)} <span style="color:var(--text-muted); font-size:11px;">(${c.pct}%)</span></span>
      </div>
      <div style="background:var(--border); border-radius:4px; height:6px;">
        <div style="background:#ef4444; border-radius:4px; height:6px; width:${pct}%;"></div>
      </div>
    </div>`;
  }).join('');
}

function _renderCfTable(monthly) {
  const tbody = document.getElementById('cf-table-body');
  if (!tbody) return;

  if (!monthly.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted" style="padding:20px;">No data.</td></tr>';
    return;
  }

  tbody.innerHTML = monthly.map(m => {
    const netColor = m.net >= 0 ? 'color:#22c55e;' : 'color:#ef4444;';
    const label = m.month.slice(0, 7);
    return `<tr>
      <td>${label}</td>
      <td class="text-right" style="color:#22c55e;">${_fmt$(m.income)}</td>
      <td class="text-right" style="color:#ef4444;">${_fmt$(m.spending)}</td>
      <td class="text-right" style="${netColor} font-weight:600;">${m.net >= 0 ? '+' : ''}${_fmt$(m.net)}</td>
    </tr>`;
  }).join('');
}

// ── Theme Toggle (Dark / Light) ────────────────────────────────

function toggleTheme() {
  const html = document.documentElement;
  const current = html.getAttribute('data-theme');
  const next = current === 'dark' ? 'light' : 'dark';
  html.setAttribute('data-theme', next);
  localStorage.setItem('spendly-theme', next);
  _updateThemeUI(next);
}

function _updateThemeUI(theme) {
  const icon = document.getElementById('theme-icon');
  const label = document.getElementById('theme-label');
  if (icon) icon.textContent = theme === 'dark' ? '☀️' : '🌙';
  if (label) label.textContent = theme === 'dark' ? 'Light Mode' : 'Dark Mode';
}

function toggleColorblind() {
  const on = document.getElementById('colorblind-toggle')?.checked;
  if (on) {
    document.documentElement.setAttribute('data-palette', 'colorblind');
    localStorage.setItem('spendly-palette', 'colorblind');
  } else {
    document.documentElement.removeAttribute('data-palette');
    localStorage.removeItem('spendly-palette');
  }
}

// Apply saved theme/palette on load
(function _initTheme() {
  const saved = localStorage.getItem('spendly-theme');
  if (saved) {
    document.documentElement.setAttribute('data-theme', saved);
    _updateThemeUI(saved);
  }
  const palette = localStorage.getItem('spendly-palette');
  if (palette) {
    document.documentElement.setAttribute('data-palette', palette);
    const cb = document.getElementById('colorblind-toggle');
    if (cb) cb.checked = true;
  }
})();

// ── Keyboard Shortcuts ─────────────────────────────────────────

let _kbHighlightIdx = -1;

function showKeyboardHelp() {
  document.getElementById('keyboard-help-modal').classList.remove('hidden');
}
function hideKeyboardHelp() {
  document.getElementById('keyboard-help-modal').classList.add('hidden');
}

document.addEventListener('keydown', e => {
  // Don't intercept when typing in inputs, textareas, or selects
  const tag = e.target.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') {
    if (e.key === 'Escape') e.target.blur();
    return;
  }
  // Close any visible modal or slide-over on Escape
  if (e.key === 'Escape') {
    document.querySelectorAll('.modal-overlay:not(.hidden)').forEach(m => m.classList.add('hidden'));
    if (document.getElementById('rec-slideover')?.classList.contains('open')) _closeRecEditPanel();
    if (document.getElementById('edit-account-slideover')?.classList.contains('open')) closeEditAccountPanel();
    bulkClearSelection('credit_card');
    bulkClearSelection('bank');
    return;
  }
  if (e.key === '?') { showKeyboardHelp(); return; }
  if (e.key === '/') {
    e.preventDefault();
    const gs = document.getElementById('global-search-input');
    if (gs) { gs.focus(); gs.select(); } else { _focusSearchField(); }
    return;
  }

  // Tab numbers 1-9 for sidebar navigation
  if (e.key >= '1' && e.key <= '9' && !e.ctrlKey && !e.metaKey && !e.altKey) {
    const pages = ['dashboard','import','history','credit-cards','bank-transactions','cashflow','reports','merchant-rules','category-rules'];
    const idx = parseInt(e.key) - 1;
    if (idx < pages.length) { navigate(pages[idx]); return; }
  }

  // j/k for row navigation, r for review, c for category edit, x for select
  const activePage = document.querySelector('.page.active');
  if (!activePage) return;
  const tbody = activePage.querySelector('tbody');
  if (!tbody) return;
  const trs = Array.from(tbody.querySelectorAll('tr[data-fp]'));
  if (!trs.length) return;

  if (e.key === 'j') {
    _kbHighlightIdx = Math.min(_kbHighlightIdx + 1, trs.length - 1);
    _highlightRow(trs);
  } else if (e.key === 'k') {
    _kbHighlightIdx = Math.max(_kbHighlightIdx - 1, 0);
    _highlightRow(trs);
  } else if (e.key === 'r' && _kbHighlightIdx >= 0 && _kbHighlightIdx < trs.length) {
    const fp = trs[_kbHighlightIdx].dataset.fp;
    if (fp) markReviewed(fp);
  } else if (e.key === 'c' && _kbHighlightIdx >= 0 && _kbHighlightIdx < trs.length) {
    const catCell = trs[_kbHighlightIdx].querySelector('td[ondblclick]');
    if (catCell) catCell.ondblclick();
  } else if (e.key === 'x' && _kbHighlightIdx >= 0 && _kbHighlightIdx < trs.length) {
    const cb = trs[_kbHighlightIdx].querySelector('.bulk-check');
    if (cb) { cb.checked = !cb.checked; bulkToggleRow(cb); }
  }
});

function _highlightRow(trs) {
  trs.forEach(tr => tr.style.outline = '');
  if (_kbHighlightIdx >= 0 && _kbHighlightIdx < trs.length) {
    trs[_kbHighlightIdx].style.outline = '2px solid var(--primary)';
    trs[_kbHighlightIdx].scrollIntoView({ block: 'nearest' });
  }
}

function _focusSearchField() {
  const activePage = document.querySelector('.page.active');
  if (!activePage) return;
  const input = activePage.querySelector('input[type="text"][placeholder*="earch"], input[type="text"][oninput*="debounce"]');
  if (input) input.focus();
}

// ── Bulk Actions ───────────────────────────────────────────────

const _bulkSelected = { credit_card: new Set(), bank: new Set() };
const _bulkUndoPending = {};  // keyed by type: { previousValues, catLabel, timer }

function _updateRowHighlight(cb) {
  const tr = cb.closest('tr');
  if (!tr) return;
  if (cb.checked) tr.classList.add('bulk-selected');
  else tr.classList.remove('bulk-selected');
}

function bulkToggleRow(cb) {
  const fp = cb.dataset.fp;
  const type = _getActiveTxnType();
  if (cb.checked) _bulkSelected[type].add(fp);
  else _bulkSelected[type].delete(fp);
  _updateRowHighlight(cb);
  _updateBulkBar(type);
}

function bulkToggleAll(type, checked) {
  const p = type === 'credit_card' ? 'cc' : 'bk';
  const tbody = document.getElementById(`${p}-tbody`);
  if (!tbody) return;
  tbody.querySelectorAll('.bulk-check').forEach(cb => {
    cb.checked = checked;
    const fp = cb.dataset.fp;
    if (checked) _bulkSelected[type].add(fp);
    else _bulkSelected[type].delete(fp);
    _updateRowHighlight(cb);
  });
  _updateBulkBar(type);
}

function _updateBulkBar(type) {
  const p = type === 'credit_card' ? 'cc' : 'bk';
  const bar = document.getElementById(`${p}-bulk-bar`);
  const count = document.getElementById(`${p}-bulk-count`);
  const n = _bulkSelected[type].size;
  if (bar) bar.style.display = n > 0 ? '' : 'none';
  if (count) count.textContent = `${n} selected`;
  // Hide merchant panel if no selection
  if (n === 0) {
    const mp = document.getElementById(`${p}-bulk-merchant-panel`);
    if (mp) mp.style.display = 'none';
  }
}

function bulkClearSelection(type) {
  _bulkSelected[type].clear();
  const p = type === 'credit_card' ? 'cc' : 'bk';
  const tbody = document.getElementById(`${p}-tbody`);
  if (tbody) {
    tbody.querySelectorAll('.bulk-check').forEach(cb => { cb.checked = false; _updateRowHighlight(cb); });
  }
  const thead = document.getElementById(`${p}-thead`);
  if (thead) { const cb = thead.querySelector('.bulk-check'); if (cb) cb.checked = false; }
  _updateBulkBar(type);
}

function _getActiveTxnType() {
  const ccPage = document.getElementById('page-credit-cards');
  if (ccPage && ccPage.classList.contains('active')) return 'credit_card';
  return 'bank';
}

async function bulkMarkReviewed(type) {
  const fps = Array.from(_bulkSelected[type]);
  if (!fps.length) return;
  try {
    await api('POST', '/transactions/mark-reviewed', { fingerprints: fps });
    toast(`Marked ${fps.length} transaction${fps.length !== 1 ? 's' : ''} as reviewed.`, 'success');
    bulkClearSelection(type);
    loadTxnTab(type);
    refreshUnreviewedBadge();
  } catch (err) {
    toast('Failed: ' + err.message, 'error');
  }
}

function bulkAssignCategory(type, anchorEl) {
  const fps = Array.from(_bulkSelected[type]);
  if (!fps.length) return;
  const p = type === 'credit_card' ? 'cc' : 'bk';
  const oldPanel = document.getElementById(`${p}-bulk-category-panel`);
  if (oldPanel) oldPanel.style.display = 'none';
  const anchor = anchorEl || document.getElementById(`${p}-bulk-cat-anchor`);
  openCategoryPicker(anchor, {
    currentCategory: '',
    allowRemove: false,
    allowCustom: true,
    placeholder: 'Search categories…',
    onSave: async (cat) => {
      await _bulkCatRun(type, fps, cat);
    },
  });
}

function bulkAssignCategoryCancel(type) {
  _bulkBarReset(type, false);
}

async function _bulkCatRun(type, fps, cat) {
  _bulkBarSetState(type, 'processing');
  try {
    const data = await api('PATCH', '/transactions/bulk-assign-category', {
      fingerprints: fps,
      category_normalized: cat.subcategory,
      category_parent: cat.parent,
      category_override: true,
    });
    if (data.failed > 0) {
      // Highlight failed rows: fingerprints that are in fps but missing from previous_values found set
      const updatedFps = new Set((data.previous_values || []).slice(0, data.updated).map(r => r.fingerprint));
      const failedFps = fps.filter(fp => !updatedFps.has(fp));
      failedFps.forEach(fp => {
        const tr = document.querySelector(`tr[data-fp="${fp}"]`);
        if (tr) tr.style.cssText += ';border-left:3px solid #f59e0b;';
      });
      _bulkBarSetState(type, 'failure', { updated: data.updated, failed: data.failed });
    } else {
      const catLabel = cat.subcategory || cat.parent || 'category';
      _bulkUndoPending[type] = {
        previousValues: data.previous_values || [],
        catLabel,
        timer: setTimeout(() => _bulkBarReset(type, true), 4000),
      };
      _bulkBarSetState(type, 'success', { updated: data.updated, catLabel });
    }
  } catch (err) {
    _bulkBarSetState(type, 'failure', { updated: 0, failed: fps.length });
  }
}

function _bulkBarSetState(type, state, data) {
  const p = type === 'credit_card' ? 'cc' : 'bk';
  const bar = document.getElementById(`${p}-bulk-bar`);
  const statusRow = document.getElementById(`${p}-bulk-status`);
  const progressBar = document.getElementById(`${p}-bulk-progress`);
  if (!bar) return;

  // Remove all state classes
  bar.classList.remove('bulk-processing', 'bulk-success', 'bulk-failure');

  if (state === 'processing') {
    bar.classList.add('bulk-processing');
    bar.querySelectorAll('button').forEach(b => { b.style.display = 'none'; });
    bar.style.pointerEvents = 'none';
    if (statusRow) { statusRow.style.display = ''; statusRow.textContent = 'Updating…'; }
    if (progressBar) progressBar.classList.add('active');

  } else if (state === 'success') {
    bar.classList.add('bulk-success');
    bar.style.pointerEvents = '';
    if (progressBar) progressBar.classList.remove('active');
    if (statusRow) {
      statusRow.style.display = '';
      const n = data.updated;
      const label = data.catLabel || 'category';
      statusRow.innerHTML = `<span>&#10003;&nbsp; ${n} transaction${n !== 1 ? 's' : ''} &rarr; &ldquo;${esc(label)}&rdquo;</span>` +
        `<button class="btn btn-secondary btn-sm" style="margin-left:auto;font-size:11px;padding:3px 10px;" onclick="_bulkCatUndo('${type}')">Undo</button>`;
    }

  } else if (state === 'failure') {
    bar.classList.add('bulk-failure');
    bar.style.pointerEvents = '';
    if (progressBar) progressBar.classList.remove('active');
    if (statusRow) {
      statusRow.style.display = '';
      const u = data.updated, f = data.failed;
      statusRow.innerHTML = `<span>&#9888;&nbsp; ${u} updated &middot; ${f} failed &mdash; rows highlighted below</span>` +
        `<button class="btn btn-secondary btn-sm" style="margin-left:auto;font-size:11px;padding:3px 10px;" onclick="_bulkBarReset('${type}',false)">Dismiss</button>`;
    }
  }
}

function _bulkBarReset(type, doReload) {
  const p = type === 'credit_card' ? 'cc' : 'bk';
  const bar = document.getElementById(`${p}-bulk-bar`);
  const statusRow = document.getElementById(`${p}-bulk-status`);
  const progressBar = document.getElementById(`${p}-bulk-progress`);
  if (bar) {
    bar.classList.remove('bulk-processing', 'bulk-success', 'bulk-failure');
    bar.style.pointerEvents = '';
    bar.querySelectorAll('button').forEach(b => { b.style.display = ''; });
  }
  if (statusRow) { statusRow.style.display = 'none'; statusRow.innerHTML = ''; }
  if (progressBar) progressBar.classList.remove('active');
  if (_bulkUndoPending[type]) {
    clearTimeout(_bulkUndoPending[type].timer);
    delete _bulkUndoPending[type];
  }
  if (doReload) {
    bulkClearSelection(type);
    loadTxnTab(type);
  }
}

async function _bulkCatUndo(type) {
  const pending = _bulkUndoPending[type];
  if (!pending) return;
  clearTimeout(pending.timer);
  delete _bulkUndoPending[type];

  // Group previous values by (category_normalized, category_parent)
  const groups = {};
  for (const r of pending.previousValues) {
    const key = `${r.category_normalized || ''}||${r.category_parent || ''}`;
    if (!groups[key]) groups[key] = { category_normalized: r.category_normalized || '', category_parent: r.category_parent || '', fingerprints: [] };
    groups[key].fingerprints.push(r.fingerprint);
  }

  _bulkBarSetState(type, 'processing');
  try {
    for (const g of Object.values(groups)) {
      await api('PATCH', '/transactions/bulk-assign-category', {
        fingerprints: g.fingerprints,
        category_normalized: g.category_normalized,
        category_parent: g.category_parent,
        category_override: false,
      });
    }
    _bulkBarReset(type, true);
    toast('Category assignment undone', 'info', 2500);
  } catch (err) {
    _bulkBarReset(type, false);
    toast('Undo failed: ' + err.message, 'error');
  }
}

async function bulkExclude(type) {
  const fps = Array.from(_bulkSelected[type]);
  if (!fps.length) return;
  if (!confirm(`Exclude ${fps.length} transaction${fps.length !== 1 ? 's' : ''} from totals?`)) return;
  try {
    for (const fp of fps) {
      await api('PATCH', `/transactions/${encodeURIComponent(fp)}`, { excluded: true });
    }
    toast(`${fps.length} transaction${fps.length !== 1 ? 's' : ''} excluded.`, 'success');
    bulkClearSelection(type);
    loadTxnTab(type);
  } catch (err) {
    toast('Failed: ' + err.message, 'error');
  }
}

async function bulkAssignTag(type) {
  const fps = Array.from(_bulkSelected[type]);
  if (!fps.length) return;
  try {
    const data = await api('GET', '/tags');
    const tags = data.tags || [];
    if (!tags.length) { toast('Create tags in Settings first.', 'info'); return; }
    const tagNames = tags.map(t => t.name).join(', ');
    const tagName = prompt(`Available tags: ${tagNames}\nEnter tag name to assign:`);
    if (!tagName) return;
    const tag = tags.find(t => t.name.toLowerCase() === tagName.toLowerCase());
    if (!tag) { toast(`Tag "${tagName}" not found.`, 'error'); return; }
    for (const fp of fps) {
      await api('POST', '/transactions/tags', { fingerprint: fp, tag_ids: [tag.id] });
    }
    toast(`Tag "${tag.name}" assigned to ${fps.length} transaction${fps.length !== 1 ? 's' : ''}.`, 'success');
    bulkClearSelection(type);
    loadTxnTab(type);
  } catch (err) {
    toast('Failed: ' + err.message, 'error');
  }
}

// ── Bulk Assign Merchant ──────────────────────────────────────

let _merchantSearchTimer = null;

function bulkAssignMerchant(type) {
  const p = type === 'credit_card' ? 'cc' : 'bk';
  const panel = document.getElementById(`${p}-bulk-merchant-panel`);
  const n = _bulkSelected[type].size;
  if (!panel || !n) return;
  panel.style.display = '';
  document.getElementById(`${p}-bulk-merchant-n`).textContent = n;
  document.getElementById(`${p}-bulk-merchant-input`).value = '';
  document.getElementById(`${p}-bulk-merchant-dropdown`).style.display = 'none';
  document.getElementById(`${p}-bulk-merchant-input`).focus();
}

function bulkAssignMerchantCancel(type) {
  const p = type === 'credit_card' ? 'cc' : 'bk';
  const panel = document.getElementById(`${p}-bulk-merchant-panel`);
  if (panel) panel.style.display = 'none';
}

function _debounceSearchMerchants(input, type) {
  clearTimeout(_merchantSearchTimer);
  _merchantSearchTimer = setTimeout(() => _searchMerchants(input, type), 300);
}

async function _searchMerchants(input, type) {
  const p = type === 'credit_card' ? 'cc' : 'bk';
  const dd = document.getElementById(`${p}-bulk-merchant-dropdown`);
  const q = input.value.trim();
  if (!q || q.length < 1) { dd.style.display = 'none'; return; }
  try {
    const data = await api('GET', `/merchants/search?q=${encodeURIComponent(q)}&limit=10`);
    const merchants = data.merchants || [];
    if (!merchants.length) { dd.style.display = 'none'; return; }
    dd.innerHTML = merchants.map(m =>
      `<div style="padding:6px 10px; cursor:pointer; font-size:13px;" onmouseenter="this.style.background='var(--bg-alt)'" onmouseleave="this.style.background=''" onclick="_selectBulkMerchant('${p}', this.textContent)">${esc(m.merchant)} <span style="color:var(--text-muted); font-size:11px;">(${m.count})</span></div>`
    ).join('');
    dd.style.display = '';
  } catch {
    dd.style.display = 'none';
  }
}

function _selectBulkMerchant(prefix, text) {
  // Strip the count suffix
  const merchant = text.replace(/\s*\(\d+\)\s*$/, '');
  const input = document.getElementById(`${prefix}-bulk-merchant-input`);
  if (input) input.value = merchant;
  document.getElementById(`${prefix}-bulk-merchant-dropdown`).style.display = 'none';
}

async function bulkAssignMerchantConfirm(type) {
  const p = type === 'credit_card' ? 'cc' : 'bk';
  const input = document.getElementById(`${p}-bulk-merchant-input`);
  const merchant = input ? input.value.trim() : '';
  if (!merchant) { toast('Enter a merchant name.', 'error'); return; }
  const fps = Array.from(_bulkSelected[type]);
  if (!fps.length) return;
  try {
    const data = await api('PATCH', '/transactions/bulk-assign-merchant', {
      fingerprints: fps, merchant_normalized: merchant
    });
    let msg = `${data.updated} transaction${data.updated !== 1 ? 's' : ''} assigned to "${merchant}"`;
    if (data.categorized > 0) msg += ` (${data.categorized} auto-categorized)`;
    toast(msg, 'success');
    bulkAssignMerchantCancel(type);
    bulkClearSelection(type);
    loadTxnTab(type);
  } catch (err) {
    toast('Failed: ' + err.message, 'error');
  }
}

// ── Shared Category Picker Component ─────────────────────────────────────
// Single reusable category picker used by transaction rows, merchant list,
// and uncategorized merchants panel.

/**
 * openCategoryPicker(targetElement, options)
 * Transforms targetElement inline into a searchable category dropdown.
 *
 * options: {
 *   currentCategory: str|null,
 *   onSave: async (selectedCategory) => {},  // {subcategory, parent}
 *   onRemove: async () => {},
 *   allowRemove: bool (default true),
 *   allowCustom: bool (default false) — show [ Custom ] free-text entry option,
 *   placeholder: str (default "Search categories…")
 * }
 */
function openCategoryPicker(targetEl, options = {}) {
  if (targetEl.querySelector('.cat-picker-inline')) return; // Already open
  const current = options.currentCategory || '';
  const allowRemove = options.allowRemove !== false;
  const allowCustom = options.allowCustom === true;
  const placeholder = options.placeholder || 'Search categories…';
  const originalHTML = targetEl.innerHTML;
  const originalText = targetEl.textContent.trim();

  targetEl.innerHTML = `<div class="cat-picker-inline" style="position:relative;">
    <input type="text" class="cat-picker-input" value="${esc(current)}"
           placeholder="${esc(placeholder)}" autocomplete="off"
           style="width:160px; padding:3px 6px; font-size:12px; border:1px solid var(--primary); border-radius:4px;" />
  </div>`;

  const wrap = targetEl.querySelector('.cat-picker-inline');
  const input = wrap.querySelector('.cat-picker-input');

  // Portal dropdown appended to body to escape any overflow:hidden ancestors
  const dd = document.createElement('div');
  dd.className = 'cat-picker-dropdown';
  dd.style.cssText = 'display:none; position:fixed; z-index:9999;';
  document.body.appendChild(dd);

  function _positionDd() {
    const r = input.getBoundingClientRect();
    dd.style.left = r.left + 'px';
    dd.style.top = (r.bottom + 2) + 'px';
    dd.style.minWidth = Math.max(r.width, 220) + 'px';
  }

  function renderOptions(query) {
    _ensureCategoryTaxonomy().then(cats => {
      let html = '';
      for (const group of cats) {
        for (const sub of group.subcategories) {
          const label = `${group.parent} > ${sub.name}`;
          if (query && !label.toLowerCase().includes(query.toLowerCase())) continue;
          html += `<div class="cat-picker-option" data-sub="${esc(sub.name)}" data-parent="${esc(group.parent)}">${esc(label)}</div>`;
        }
      }
      if (allowCustom) {
        html += `<div class="cat-picker-option cat-picker-custom" style="font-style:italic; color:var(--text-muted); border-top:1px solid var(--border);">[ Custom ]</div>`;
      }
      if (allowRemove) {
        html += `<div class="cat-picker-option cat-picker-remove" style="color:var(--danger); border-top:1px solid var(--border);">— Remove Category —</div>`;
      }
      dd.innerHTML = html || '<div style="padding:6px 8px; color:var(--text-muted); font-size:11px;">No matches</div>';
      _positionDd();
      dd.style.display = 'block';

      // Attach click handlers
      dd.querySelectorAll('.cat-picker-option[data-sub]').forEach(opt => {
        opt.addEventListener('click', async () => {
          const sub = opt.dataset.sub;
          const parent = opt.dataset.parent;
          dd.style.display = 'none';
          if (options.onSave) {
            try {
              await options.onSave({ subcategory: sub, parent });
            } catch (err) { toast('Failed: ' + err.message, 'error'); }
          }
          cleanup();
        });
      });
      const removeOpt = dd.querySelector('.cat-picker-remove');
      if (removeOpt) {
        removeOpt.addEventListener('click', async () => {
          dd.style.display = 'none';
          if (options.onRemove) {
            try {
              await options.onRemove();
            } catch (err) { toast('Failed: ' + err.message, 'error'); }
          }
          cleanup();
        });
      }
      const customOpt = dd.querySelector('.cat-picker-custom');
      if (customOpt) {
        customOpt.addEventListener('click', () => {
          dd.style.display = 'none';
          input.value = '';
          input.placeholder = 'Type custom category…';
          input.focus();
          const customEnter = (e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              input.removeEventListener('keydown', customEnter);
              const val = input.value.trim();
              if (!val) return;
              if (options.onSave) {
                try { options.onSave({ subcategory: val, parent: null }); }
                catch (err) { toast('Failed: ' + err.message, 'error'); }
              }
              cleanup();
            }
          };
          input.addEventListener('keydown', customEnter);
        });
      }
    });
  }

  function cleanup() {
    targetEl.innerHTML = originalHTML;
    if (dd.parentNode) dd.parentNode.removeChild(dd);
    document.removeEventListener('keydown', escHandler);
    document.removeEventListener('mousedown', outsideHandler);
  }

  function cancel() {
    cleanup();
  }

  function escHandler(e) {
    if (e.key === 'Escape') { cancel(); }
  }

  function outsideHandler(e) {
    if (!wrap.contains(e.target) && !dd.contains(e.target)) { cancel(); }
  }

  input.addEventListener('input', () => renderOptions(input.value));
  input.addEventListener('focus', () => renderOptions(input.value));
  document.addEventListener('keydown', escHandler);
  setTimeout(() => document.addEventListener('mousedown', outsideHandler), 0);

  input.focus();
  input.select();
  renderOptions(input.value);
}

// ── Transaction Row Inline Category Edit ─────────────────────────────────

function inlineCategoryEdit(td, fp) {
  const currentCat = td.textContent.trim();
  const isOverride = td.dataset.override === 'true';
  openCategoryPicker(td, {
    currentCategory: currentCat === '—' ? '' : currentCat,
    onSave: async (cat) => {
      await api('PATCH', '/transactions/' + fp, {
        category_normalized: cat.subcategory,
        category_parent: cat.parent,
        category_override: true,
      });
      _updateTxnCategoryCell(td, cat.subcategory, true);
      // Show "Fix for all?" prompt if merchant exists
      const row = td.closest('tr');
      if (row) {
        const merchantCell = row.querySelector('[data-col="merchant"]');
        const merchant = merchantCell ? merchantCell.textContent.trim() : '';
        if (merchant && merchant !== '—') {
          _showFixForAllPrompt(td, fp, merchant, cat);
        }
      }
      toast('Category updated.', 'success');
    },
    onRemove: async () => {
      await api('PATCH', '/transactions/' + fp, {
        category_normalized: null,
        category_parent: null,
        category_override: false,
      });
      _updateTxnCategoryCell(td, null, false);
      toast('Category removed.', 'info');
    },
  });
}

function _updateTxnCategoryCell(td, category, overridden) {
  const display = category || '— No category —';
  const style = category ? '' : ' style="color:var(--text-muted);"';
  const badge = overridden ? ' <span class="override-badge" onclick="event.stopPropagation(); _resetCategoryOverride(this)" title="Click to reset to rule-based category">edited</span>' : '';
  td.innerHTML = `<span${style}>${esc(display)}</span>${badge}`;
  td.dataset.override = overridden ? 'true' : 'false';
}

async function _resetCategoryOverride(badgeEl) {
  const td = badgeEl.closest('td');
  const fp = td?.closest('tr')?.dataset.fp;
  if (!fp) return;
  if (!confirm('Reset to rule-based category? Your manual assignment will be removed.')) return;
  try {
    await api('PATCH', '/transactions/' + fp, {
      category_override: false,
    });
    // Trigger single-row re-normalization by removing override flag
    // The actual category will be re-applied on next normalization run
    _updateTxnCategoryCell(td, td.querySelector('span')?.textContent || '', false);
    toast('Override removed. Run "Apply Category Rules" to re-apply rule-based category.', 'info');
  } catch (err) {
    toast('Failed: ' + err.message, 'error');
  }
}

function _showFixForAllPrompt(anchorTd, fp, merchant, cat) {
  // Remove any existing prompt
  document.querySelectorAll('.fix-for-all-prompt').forEach(el => el.remove());
  const prompt = document.createElement('div');
  prompt.className = 'fix-for-all-prompt';
  prompt.innerHTML = `
    <span>Apply '${esc(cat.subcategory)}' to all '${esc(merchant)}' transactions?</span>
    <button class="btn btn-primary btn-sm" onclick="_fixForAllMerchant('${esc(merchant)}', '${esc(cat.subcategory)}', '${esc(cat.parent)}', this)">Yes, fix all</button>
    <button class="btn btn-secondary btn-sm" onclick="this.closest('.fix-for-all-prompt').remove()">No, just this one</button>
  `;
  anchorTd.closest('tr')?.after(prompt);
  // Auto-dismiss after 8 seconds
  setTimeout(() => { if (prompt.parentNode) prompt.remove(); }, 8000);
}

async function _fixForAllMerchant(merchant, category, parent, btn) {
  const prompt = btn.closest('.fix-for-all-prompt');
  try {
    await api('POST', '/merchant-categories', { merchant, category });
    // Now update all non-overridden transactions for this merchant
    const data = await api('GET', `/transactions?merchant=${encodeURIComponent(merchant)}&limit=9999`);
    const txns = data.transactions || [];
    let count = 0;
    for (const t of txns) {
      if (t.category_override) continue; // Skip existing overrides
      await api('PATCH', '/transactions/' + t.transaction_fingerprint, {
        category_normalized: category,
        category_parent: parent,
      });
      count++;
    }
    toast(`${count} transactions updated for ${merchant}`, 'success');
  } catch (err) {
    toast('Failed: ' + err.message, 'error');
  }
  if (prompt) prompt.remove();
}

// ── Onboarding Flow ────────────────────────────────────────────

function _checkOnboarding() {
  if (localStorage.getItem('spendly-onboarding-dismissed')) return;
  // Check if user has any data
  api('GET', '/runs').then(data => {
    const runs = data.runs || [];
    if (runs.length === 0) {
      document.getElementById('onboarding-modal').classList.remove('hidden');
    }
  }).catch(() => {});
}

function closeOnboarding() {
  document.getElementById('onboarding-modal').classList.add('hidden');
  if (document.getElementById('ob-dismiss')?.checked) {
    localStorage.setItem('spendly-onboarding-dismissed', '1');
  }
}

function onboardingGo(page) {
  closeOnboarding();
  navigate(page);
}

// ── Utilities Tab ─────────────────────────────────────────────

// ── Improve My Data ───────────────────────────────────────────

async function improveMyData() {
  const btn = document.getElementById('improve-run-btn');
  const statusEl = document.getElementById('improve-status');
  const labelEl = document.getElementById('improve-status-label');
  const fillEl = document.getElementById('improve-progress-fill');
  const resultEl = document.getElementById('improve-result');

  btn.disabled = true;
  btn.textContent = 'Running…';
  statusEl.style.display = 'block';
  resultEl.textContent = '';
  fillEl.style.width = '0%';
  labelEl.textContent = 'Starting normalization job…';

  const _done = (ok, label, detail) => {
    labelEl.textContent = label;
    if (detail) resultEl.innerHTML = detail;
    btn.disabled = false;
    btn.textContent = '⚡ Improve My Data';
    if (ok) _showImproveStats();
  };

  let jobId;
  try {
    const res = await api('POST', '/normalize/apply', {});
    if (res.status === 'success') {
      fillEl.style.width = '100%';
      _done(true, '✓ Complete', `Updated ${res.transactions_updated ?? 0} transactions.`);
      return;
    }
    jobId = res.job_id;
  } catch (err) {
    _done(false, '✗ Failed to start job', err.message);
    return;
  }

  // Poll until done — max 500 attempts (~10 min at 1200ms), stop after 5 consecutive errors
  let attempts = 0, consecutiveErrors = 0;
  const MAX_ATTEMPTS = 500, MAX_ERRORS = 5;

  const poll = setInterval(async () => {
    if (++attempts > MAX_ATTEMPTS) {
      clearInterval(poll);
      _done(false, '✗ Timed out', 'Job is taking too long. Check the History tab for status.');
      return;
    }
    try {
      const job = await api('GET', `/normalize/${jobId}`);
      consecutiveErrors = 0;
      const total = job.rows_total || 0;
      const done = job.rows_done || 0;
      const pct = total > 0 ? Math.round((done / total) * 100) : 0;
      fillEl.style.width = pct + '%';
      labelEl.textContent = total > 0
        ? `Processing… ${done.toLocaleString()} / ${total.toLocaleString()} transactions`
        : 'Processing…';

      if (job.status === 'success') {
        clearInterval(poll);
        fillEl.style.width = '100%';
        const viewLink = `<a href="#" onclick="event.preventDefault();navigate('cc');" style="color:var(--primary);">View transactions →</a>`;
        _done(true, '✓ Complete',
          `Applied all rules to ${done.toLocaleString()} transactions. ${viewLink}`);
        toast('Data improved — all rules applied.', 'success');
      } else if (job.status === 'error' || job.status === 'failed') {
        clearInterval(poll);
        _done(false, '✗ Job failed', job.error || 'Unknown error.');
      }
    } catch (_) {
      if (++consecutiveErrors >= MAX_ERRORS) {
        clearInterval(poll);
        _done(false, '✗ Connection lost', 'Could not reach the server. Try again.');
      }
    }
  }, 1200);
}

async function exportLearning() {
  try {
    const resp = await fetch('/learning/export');
    if (!resp.ok) throw new Error(`Server error ${resp.status}`);
    const blob = await resp.blob();
    const cd = resp.headers.get('Content-Disposition') || '';
    const match = cd.match(/filename="([^"]+)"/);
    const filename = match ? match[1] : 'spendly_learning.json';
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename; a.click();
    URL.revokeObjectURL(url);
    toast('Learning exported.', 'success');
  } catch (err) {
    toast('Export failed: ' + err.message, 'error');
  }
}

async function importLearning(input) {
  const file = input.files[0];
  if (!file) return;
  input.value = '';
  const fd = new FormData();
  fd.append('file', file);
  try {
    const res = await fetch('/learning/import', { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `Error ${res.status}`);

    if (data.total_added === 0) {
      toast('Nothing new — all rules in this file already exist in your database.', 'info');
    } else {
      const parts = [];
      if (data.merchant_rules_added)       parts.push(`${data.merchant_rules_added} merchant rules`);
      if (data.merchant_category_map_added) parts.push(`${data.merchant_category_map_added} category assignments`);
      if (data.category_rules_added)        parts.push(`${data.category_rules_added} category rules`);
      if (data.custom_categories_added)     parts.push(`${data.custom_categories_added} custom categories`);
      toast(`Imported: ${parts.join(', ')}. Click "Improve My Data" to apply.`, 'success');
    }
    _showImproveStats();
  } catch (err) {
    toast('Import failed: ' + err.message, 'error');
  }
}

async function _showImproveStats() {
  const statsEl = document.getElementById('improve-stats');
  const gridEl = document.getElementById('improve-stats-grid');
  if (!statsEl || !gridEl) return;
  try {
    const s = await api('GET', '/learning/stats');
    const items = [
      { label: 'Merchant Rules',      value: s.merchant_rules },
      { label: 'Known Merchants',     value: s.merchant_category_map },
      { label: 'Assigned Merchants',  value: s.merchants_assigned },
      { label: 'Categories',          value: s.built_in_categories + s.custom_categories },
    ];
    gridEl.innerHTML = items.map(i => `
      <div class="improve-stat-card">
        <div class="improve-stat-value">${i.value.toLocaleString()}</div>
        <div class="improve-stat-label">${i.label}</div>
      </div>`).join('');
    statsEl.style.display = 'block';
  } catch (_) { /* non-fatal */ }
}

// -- Shared: populate all category-parent <select> elements from a parents list --
let _knownParents = [];

function _populateCategoryParentSelects(parents) {
  _knownParents = parents || [];
  const ids = ['util-cat-new-parent', 'crf-parent', 'bf-parent'];
  ids.forEach(id => {
    const sel = document.getElementById(id);
    if (!sel) return;
    const current = sel.value;
    sel.innerHTML = '<option value="">— Select parent —</option>' +
      _knownParents.map(p => `<option${p === current ? ' selected' : ''}>${esc(p)}</option>`).join('');
  });
  // bf-category subcategory select — keep empty placeholder
  const bfCat = document.getElementById('bf-category');
  if (bfCat && !bfCat.dataset.populated) {
    bfCat.innerHTML = '<option value="">— All in parent —</option>';
  }
}

// Refresh bf-category options when bf-parent changes
function _onBfParentChange() {
  const parent = document.getElementById('bf-parent')?.value;
  const catSel = document.getElementById('bf-category');
  if (!catSel) return;
  const group = _utilCatData.find(g => g.parent === parent);
  const subs = group ? group.subcategories.map(s => s.name) : [];
  catSel.innerHTML = '<option value="">— All in parent —</option>' +
    subs.map(s => `<option>${esc(s)}</option>`).join('');
}

// -- Category List --
let _utilCatData = [];
async function loadUtilCategories() {
  const el = document.getElementById('util-cat-list');
  if (!el) return;
  el.innerHTML = '<span style="color:var(--text-muted);">Loading…</span>';
  try {
    const data = await api('GET', '/utilities/categories');
    _utilCatData = data.categories || [];
    _populateCategoryParentSelects(data.parents || _utilCatData.map(g => g.parent));
    _renderUtilCategories(_utilCatData);
    const total = _utilCatData.reduce((s, g) => s + g.subcategories.length, 0);
    _updateBadge('util-cat-count', total);
  } catch (err) {
    el.innerHTML = `<span style="color:var(--text-muted);">Error: ${esc(err.message)}</span>`;
  }
}

function _openAddCategoryForm() {
  document.getElementById('util-cat-add-form').style.display = '';
  document.getElementById('util-cat-new-name').value = '';
  document.getElementById('util-cat-new-parent').value = '';
  document.getElementById('util-cat-new-name').focus();
}

function _closeAddCategoryForm() {
  document.getElementById('util-cat-add-form').style.display = 'none';
}

async function _saveNewCategory() {
  const subcategory = (document.getElementById('util-cat-new-name')?.value || '').trim();
  const parent      = document.getElementById('util-cat-new-parent')?.value || '';
  if (!subcategory) { toast('Subcategory name is required.', 'error'); return; }
  if (!parent)      { toast('Parent group is required.', 'error'); return; }
  try {
    await api('POST', '/utilities/categories', { subcategory, parent });
    toast(`"${subcategory}" added under ${parent}.`, 'success');
    _closeAddCategoryForm();
    await loadUtilCategories();
  } catch (err) {
    toast(`Failed: ${err.message}`, 'error');
  }
}

function _renderUtilCategories(cats) {
  const el = document.getElementById('util-cat-list');
  if (!cats.length) { el.innerHTML = '<span style="color:var(--text-muted);">No categories found.</span>'; return; }
  el.innerHTML = cats.map(g => {
    const subs = g.subcategories.map(s =>
      `<div style="display:flex; justify-content:space-between; padding:3px 0 3px 24px; border-bottom:1px solid var(--border);">
        <span>${esc(s.name)}</span>
        <span class="mono" style="color:var(--text-muted); font-size:11px;">${s.count}</span>
      </div>`
    ).join('');
    return `<div style="margin-bottom:8px;">
      <div style="font-weight:700; padding:6px 0; border-bottom:2px solid var(--border); display:flex; justify-content:space-between;">
        <span>${esc(g.parent)}</span>
        <span class="mono" style="font-size:11px; color:var(--text-muted);">${g.count}</span>
      </div>${subs}</div>`;
  }).join('');
}

// ── Transaction Filter Chips ──────────────────────────────────

const _CHIP_LABELS = {
  date_from: 'From', date_to: 'To', account: 'Account',
  category: 'Category', merchant: 'Merchant', subtype: 'Type',
  amount_min: 'Min $', amount_max: 'Max $', tag: 'Tag',
};

function _renderFilterChips(type) {
  const p = _pfx(type);
  const bar = document.getElementById(`${p}-filter-chips`);
  if (!bar) return;
  const f = _txnFilters(type);
  const chips = [];
  const skip = new Set(['source', 'group_by', 'unreviewed_only', 'no_merchant', 'no_category']);
  Object.entries(f).forEach(([k, v]) => {
    if (skip.has(k) || !v) return;
    const label = _CHIP_LABELS[k] || k;
    chips.push({ key: k, label, value: String(v) });
  });
  if (f.unreviewed_only) chips.push({ key: 'unreviewed_only', label: 'Unreviewed', value: '' });
  if (f.no_merchant)     chips.push({ key: 'no_merchant',     label: 'No Merchant', value: '' });
  if (f.no_category)     chips.push({ key: 'no_category',     label: 'No Category', value: '' });

  if (!chips.length) { bar.style.display = 'none'; bar.innerHTML = ''; return; }
  bar.style.display = 'flex';
  bar.innerHTML = '<span style="font-size:11px; color:var(--text-muted); align-self:center; margin-right:2px;">Filters:</span>' +
    chips.map(c => `<span style="display:inline-flex; align-items:center; gap:4px; background:var(--primary,#3b82f6); color:#fff; font-size:11px; padding:2px 8px; border-radius:12px;">
      ${esc(c.label)}${c.value ? ': ' + esc(c.value) : ''}
      <button onclick="_clearFilterChip('${type}','${c.key}')" style="background:none;border:none;color:#fff;cursor:pointer;padding:0;font-size:13px;line-height:1;" title="Remove filter">✕</button>
    </span>`).join('');
}

function _clearFilterChip(type, key) {
  const p = _pfx(type);
  const checkboxKeys = { unreviewed_only: `${p}-unreviewed-only`, no_merchant: `${p}-no-merchant`, no_category: `${p}-no-category` };
  if (checkboxKeys[key]) {
    const el = document.getElementById(checkboxKeys[key]); if (el) el.checked = false;
  } else if (key === 'account') {
    _acctCtrl[type]?.reset();
  } else if (key === 'amount_min' || key === 'amount_max') {
    const el = document.getElementById(`${p}-${key.replace('_','-')}`); if (el) el.value = '';
  } else {
    const el = document.getElementById(`${p}-${key.replace('_','-')}`); if (el) el.value = '';
  }
  loadTxnTab(type);
}

function _filterUtilCategories() {
  const q = (document.getElementById('util-cat-search')?.value || '').toLowerCase();
  if (!q) { _renderUtilCategories(_utilCatData); return; }
  const filtered = _utilCatData.map(g => {
    const matchedSubs = g.subcategories.filter(s => s.name.toLowerCase().includes(q) || g.parent.toLowerCase().includes(q));
    if (!matchedSubs.length) return null;
    return { ...g, subcategories: matchedSubs, count: matchedSubs.reduce((s, x) => s + x.count, 0) };
  }).filter(Boolean);
  _renderUtilCategories(filtered);
}

// -- Merchant List --
let _utilMerchData = [];
async function loadUtilMerchants() {
  const el = document.getElementById('util-merch-list');
  if (!el) return;
  el.innerHTML = '<span style="color:var(--text-muted);">Loading…</span>';
  try {
    const data = await api('GET', '/utilities/merchants');
    _utilMerchData = data.merchants || [];
    _sortAndRenderMerchants();
    _updateBadge('util-merch-count', data.count || 0);
  } catch (err) {
    el.innerHTML = `<span style="color:var(--text-muted);">Error: ${esc(err.message)}</span>`;
  }
}

function _sortAndRenderMerchants() {
  const sortBy = document.getElementById('util-merch-sort')?.value || 'txn_count';
  const sorted = [..._utilMerchData].sort((a, b) => {
    if (sortBy === 'normalized_name') return (a.normalized_name || '').localeCompare(b.normalized_name || '');
    if (sortBy === 'last_seen') return (b.last_seen || '').localeCompare(a.last_seen || '');
    return (b.txn_count || 0) - (a.txn_count || 0);
  });
  _renderUtilMerchants(sorted);
}

function _renderUtilMerchants(merchants) {
  const el = document.getElementById('util-merch-list');
  if (!merchants.length) { el.innerHTML = '<span style="color:var(--text-muted);">No merchants found.</span>'; return; }
  el.innerHTML = `<table style="width:100%; border-collapse:collapse; font-size:12px;">
    <thead><tr style="border-bottom:2px solid var(--border); text-align:left;">
      <th style="padding:4px 6px;"><input type="checkbox" id="util-merch-select-all" onchange="_utilMerchToggleAll(this)" /></th>
      <th style="padding:4px 6px;">Merchant</th>
      <th style="padding:4px 6px; text-align:right;">Count</th>
      <th style="padding:4px 6px; text-align:right;">Total Spend</th>
      <th style="padding:4px 6px;">Category</th>
      <th style="padding:4px 6px;">Last Seen</th>
    </tr></thead><tbody>` +
    merchants.map(m => {
      const catDisplay = m.assigned_category
        ? esc(m.assigned_category)
        : '<span style="color:var(--text-muted);">\u2014 No category \u2014</span>';
      return `<tr style="border-bottom:1px solid var(--border);" data-merchant="${esc(m.normalized_name)}">
      <td style="padding:4px 6px;"><input type="checkbox" class="util-merch-check" data-merchant="${esc(m.normalized_name)}" onchange="_utilMerchUpdateBulkBar()" /></td>
      <td style="padding:4px 6px;">${esc(m.normalized_name)}</td>
      <td style="padding:4px 6px; text-align:right;" class="mono">${m.txn_count}</td>
      <td style="padding:4px 6px; text-align:right; font-variant-numeric:tabular-nums;">${_fmt$(m.total_spend || 0)}</td>
      <td style="padding:4px 6px; cursor:pointer;" onclick="_utilMerchCatClick(this, '${esc(m.normalized_name)}')" title="Click to edit" class="util-cat-cell">${catDisplay}</td>
      <td style="padding:4px 6px; color:var(--text-muted);">${m.last_seen || '\u2014'}</td>
    </tr>`;
    }).join('') +
    '</tbody></table>';
  _utilMerchUpdateBulkBar();
}

function _filterUtilMerchants() {
  const q = (document.getElementById('util-merch-search')?.value || '').toLowerCase();
  if (!q) { _sortAndRenderMerchants(); return; }
  const filtered = _utilMerchData.filter(m =>
    (m.normalized_name || '').toLowerCase().includes(q) ||
    (m.assigned_category || '').toLowerCase().includes(q)
  );
  _renderUtilMerchants(filtered);
}

function _utilMerchCatClick(td, merchant) {
  const current = td.textContent.trim();
  const currentCat = (current === '—' || current === '— No category —') ? '' : current;
  openCategoryPicker(td, {
    currentCategory: currentCat,
    onSave: async (cat) => {
      // Write to merchant_category_map — re-normalization happens server-side
      await api('POST', '/merchant-categories', {
        merchant,
        category: cat.subcategory,
        parent: cat.parent,
        source: 'user'
      });
      td.textContent = cat.subcategory;
      toast(merchant + ' → ' + cat.subcategory + ' (all transactions updated)', 'success');
    },
    onRemove: async () => {
      await api('DELETE', '/merchant-categories/' + encodeURIComponent(merchant));
      td.innerHTML = '<span style="color:var(--text-muted);">\u2014 No category \u2014</span>';
      toast('Category removed — ' + merchant + ' transactions will be re-categorized by rules', 'info');
    },
  });
}

// ── Utilities Merchant List Bulk Actions ──────────────────────────────────

let _utilMerchSelected = new Set();

function _utilMerchToggleAll(el) {
  document.querySelectorAll('.util-merch-check').forEach(cb => {
    cb.checked = el.checked;
  });
  _utilMerchUpdateBulkBar();
}

function _utilMerchUpdateBulkBar() {
  const checked = document.querySelectorAll('.util-merch-check:checked');
  _utilMerchSelected = new Set([...checked].map(cb => cb.dataset.merchant));
  const bar = document.getElementById('util-merch-bulk-bar');
  if (!bar) return;
  if (_utilMerchSelected.size >= 2) {
    bar.style.display = 'flex';
    bar.querySelector('.bulk-count').textContent = `${_utilMerchSelected.size} merchants`;
  } else {
    bar.style.display = 'none';
  }
}

function _utilMerchBulkAssignCat() {
  const bar = document.getElementById('util-merch-bulk-bar');
  const anchor = bar.querySelector('.bulk-cat-anchor');
  openCategoryPicker(anchor, {
    currentCategory: '',
    allowRemove: false,
    placeholder: 'Category for selected…',
    onSave: async (cat) => {
      const total = _utilMerchSelected.size;
      toast('Updating ' + total + ' merchants...', 'info', 3000);
      let count = 0;
      // Sequential per merchant — DuckDB single-writer constraint
      for (const merchant of _utilMerchSelected) {
        await api('POST', '/merchant-categories', {
          merchant,
          category: cat.subcategory,
          parent: cat.parent,
          source: 'user'
        });
        count++;
      }
      toast(count + ' merchants updated, all their transactions re-categorized', 'success');
      _utilMerchClearSelection();
      loadUtilMerchants();
    },
  });
}

async function _utilMerchBulkRemoveCat() {
  if (!confirm('Remove category from ' + _utilMerchSelected.size + ' merchants? Their transactions will be re-categorized by rules.')) return;
  const total = _utilMerchSelected.size;
  toast('Updating ' + total + ' merchants...', 'info', 3000);
  let count = 0;
  // Sequential per merchant — DuckDB single-writer constraint
  for (const merchant of _utilMerchSelected) {
    try {
      await api('DELETE', '/merchant-categories/' + encodeURIComponent(merchant));
      count++;
    } catch { /* skip errors */ }
  }
  toast('Category removed from ' + count + ' merchants, transactions re-categorized by rules', 'info');
  _utilMerchClearSelection();
  loadUtilMerchants();
}

function _utilMerchClearSelection() {
  _utilMerchSelected.clear();
  document.querySelectorAll('.util-merch-check').forEach(cb => cb.checked = false);
  const selectAll = document.getElementById('util-merch-select-all');
  if (selectAll) selectAll.checked = false;
  _utilMerchUpdateBulkBar();
}

// -- Rule Tester --
async function testRuleUtil() {
  const input = document.getElementById('util-rule-input');
  const resultEl = document.getElementById('util-rule-result');
  if (!input || !resultEl) return;
  const desc = input.value.trim();
  if (!desc) { toast('Enter a description first.', 'error'); return; }
  resultEl.style.display = 'block';
  resultEl.innerHTML = '<span style="color:var(--text-muted);">Testing…</span>';
  try {
    const data = await api('POST', '/utilities/test-rule', { description: desc });
    let html = '<div style="background:var(--bg-secondary); border-radius:6px; padding:12px; font-size:13px;">';
    html += `<div style="margin-bottom:6px;"><strong>Input:</strong> ${esc(data.description)}</div>`;
    if (data.merchant_rule) {
      html += `<div style="margin-bottom:6px;">
        <strong>Merchant Rule:</strong> pattern="${esc(data.merchant_rule.pattern)}" (${esc(data.merchant_rule.match_type)})
        → <strong>${esc(data.merchant_rule.merchant)}</strong></div>`;
    } else {
      html += '<div style="margin-bottom:6px; color:var(--text-muted);"><strong>Merchant Rule:</strong> No rule matched</div>';
    }
    html += `<div style="margin-bottom:6px;"><strong>Merchant:</strong> ${data.merchant ? esc(data.merchant) : '<span style="color:var(--text-muted);">none</span>'}</div>`;
    html += `<div style="margin-bottom:6px;"><strong>Category:</strong> ${data.category ? esc(data.category) : '<span style="color:var(--text-muted);">none</span>'}</div>`;
    html += `<div><strong>Parent:</strong> ${data.parent ? esc(data.parent) : '<span style="color:var(--text-muted);">none</span>'}</div>`;
    html += '</div>';
    resultEl.innerHTML = html;
  } catch (err) {
    resultEl.innerHTML = `<span style="color:var(--danger);">Error: ${esc(err.message)}</span>`;
  }
}

// -- Duplicate Review --
function _dupReasonLabel(reason) {
  if (!reason) return '—';
  if (reason === 'fuzzy_description_match') return 'Similar description';
  if (reason === 'amount_variance') return 'Amount difference';
  if (reason === 'fuzzy_description_and_amount_variance') return 'Similar description + amount difference';
  return esc(reason);
}

async function loadUtilDuplicates() {
  const el = document.getElementById('util-dup-list');
  if (!el) return;
  el.innerHTML = '<span style="color:var(--text-muted);">Loading…</span>';
  try {
    const data = await api('GET', '/duplicates?status=pending');
    const rows = data.rows || [];
    _updateBadge('util-dup-count', rows.length);
    refreshDupBadge();
    if (!rows.length) {
      el.innerHTML = '<div style="padding:20px; text-align:center; color:var(--text-muted);">No duplicate candidates — your data looks clean ✓</div>';
      return;
    }
    el.innerHTML = rows.map(r => {
      const isAmtVar = r.reason && r.reason.includes('amount_variance');
      const amtDiff = r.amount_a != null && r.amount_b != null && Math.abs(r.amount_a - r.amount_b) > 0.001;
      const descDiff = (r.desc_a || '') !== (r.desc_b || '');
      const dateDiff = (r.date_a || '') !== (r.date_b || '');
      const amberStyle = 'background:rgba(245,158,11,0.12); color:var(--warning); font-weight:600;';
      const _fmtImp = (v) => v ? new Date(v).toLocaleDateString('en-US', {month:'short', day:'numeric', year:'numeric'}) : '—';

      // Amount variance callout
      const amtCallout = isAmtVar ? `
        <div style="background:rgba(245,158,11,0.08); border:1px solid var(--warning); border-radius:6px; padding:8px 10px; margin-bottom:8px; font-size:12px;">
          <strong>⚠️ Amount difference detected</strong><br>
          Original: ${_fmt$(r.amount_a)} → Re-imported: ${_fmt$(r.amount_b)}<br>
          <span style="color:var(--text-muted);">This may be a pending transaction that settled at a different amount. Remove the original if the new amount is correct.</span>
        </div>` : '';

      // Side-by-side comparison table
      const compTable = `
        <table style="width:100%; font-size:12px; border-collapse:collapse; margin-bottom:8px;">
          <thead><tr>
            <th style="text-align:left; padding:4px 6px; border-bottom:1px solid var(--border);">Field</th>
            <th style="text-align:left; padding:4px 6px; border-bottom:1px solid var(--border);">Original</th>
            <th style="text-align:left; padding:4px 6px; border-bottom:1px solid var(--border);">Re-imported</th>
          </tr></thead>
          <tbody>
            <tr><td style="padding:4px 6px;">Date</td>
              <td style="padding:4px 6px;${dateDiff ? amberStyle : ''}">${r.date_a || '—'}</td>
              <td style="padding:4px 6px;${dateDiff ? amberStyle : ''}">${r.date_b || '—'}</td></tr>
            <tr><td style="padding:4px 6px;">Description</td>
              <td style="padding:4px 6px;${descDiff ? amberStyle : ''}">${esc(r.desc_a || '')}</td>
              <td style="padding:4px 6px;${descDiff ? amberStyle : ''}">${esc(r.desc_b || '')}</td></tr>
            <tr><td style="padding:4px 6px;">Amount</td>
              <td style="padding:4px 6px;${amtDiff ? amberStyle : ''}">${_fmt$(r.amount_a)}</td>
              <td style="padding:4px 6px;${amtDiff ? amberStyle : ''}">${_fmt$(r.amount_b)}</td></tr>
            <tr><td style="padding:4px 6px;">Imported</td>
              <td style="padding:4px 6px;">${_fmtImp(r.ingested_at_a)}</td>
              <td style="padding:4px 6px;">${_fmtImp(r.ingested_at_b)}</td></tr>
          </tbody>
        </table>`;

      // Resolution buttons — contextual labels for amount variance
      const keepBothLabel = isAmtVar ? 'Keep as separate transactions' : 'Keep Both';
      const removeNewLabel = isAmtVar ? `Keep original amount (${_fmt$(r.amount_a)})` : 'Remove Newer';
      const removeOldLabel = isAmtVar ? `Use corrected amount (${_fmt$(r.amount_b)})` : 'Remove Older';

      return `
      <div class="dup-pair" style="border:1px solid var(--border); border-radius:6px; padding:12px; margin-bottom:10px;">
        ${amtCallout}
        ${compTable}
        <div style="font-size:11px; color:var(--text-muted); margin-bottom:8px;">Reason: ${_dupReasonLabel(r.reason)}${r.similarity_score != null ? ' (' + Math.round(r.similarity_score * 100) + '% match)' : ''}</div>
        <div style="display:flex; gap:6px; flex-wrap:wrap;">
          <button class="btn btn-secondary btn-sm" onclick="resolveDup(${r.id}, 'keep_both')">${esc(keepBothLabel)}</button>
          <button class="btn btn-danger btn-sm" onclick="resolveDup(${r.id}, 'delete_b')">${esc(removeNewLabel)}</button>
          <button class="btn btn-danger btn-sm" onclick="resolveDup(${r.id}, 'delete_a')">${esc(removeOldLabel)}</button>
          <button class="btn btn-secondary btn-sm" onclick="resolveDup(${r.id}, 'not_duplicate')">Not a Duplicate</button>
        </div>
      </div>`;
    }).join('');
  } catch (err) {
    el.innerHTML = `<span style="color:var(--text-muted);">Error: ${esc(err.message)}</span>`;
  }
}

async function resolveDup(id, action) {
  try {
    await api('POST', `/duplicates/${id}/resolve`, { action });
    const labels = {keep_both: 'Kept both', delete_b: 'Removed newer', delete_a: 'Removed older', not_duplicate: 'Not a duplicate'};
    toast(`Duplicate resolved: ${labels[action] || action}`, 'success');
    loadUtilDuplicates();
  } catch (err) {
    toast(`Failed: ${err.message}`, 'error');
  }
}

async function refreshDupBadge() {
  try {
    const data = await api('GET', '/duplicates?status=pending');
    const count = (data.rows || []).length;
    const badge = document.getElementById('nav-dup-badge');
    if (badge) badge.textContent = count > 0 ? count : '';
  } catch { /* non-critical */ }
}

// -- Data Health --

/** Navigate to the correct transaction tab and apply a filter checkbox.
 *  Uses per_type breakdown from health API to pick CC vs bank tab. */
function _healthNavigateWithFilter(perType, filterKey) {
  // filterKey: 'no_category', 'unreviewed', 'no_merchant'
  const metricKey = filterKey === 'no_category' ? 'uncategorized'
                  : filterKey === 'unreviewed'  ? 'unreviewed'
                  : 'no_merchant';
  const cc = (perType?.credit_card || {})[metricKey] || 0;
  const bk = (perType?.bank || {})[metricKey] || 0;
  const type = cc >= bk ? 'credit_card' : 'bank';
  const page = type === 'credit_card' ? 'credit-cards' : 'bank-transactions';
  const prefix = type === 'credit_card' ? 'cc' : 'bk';
  navigate(page);
  setTimeout(() => {
    // Map filterKey to the checkbox ID suffix
    const idMap = {
      'no_category': `${prefix}-no-category`,
      'no_merchant': `${prefix}-no-merchant`,
      'unreviewed':  `${prefix}-unreviewed-only`,
    };
    const checkbox = document.getElementById(idMap[filterKey]);
    if (checkbox && !checkbox.checked) {
      checkbox.checked = true;
      loadTxnTab(type);
    }
    if (cc > 0 && bk > 0) {
      toast(`Showing ${type === 'credit_card' ? 'Credit Card' : 'Bank'} tab (${type === 'credit_card' ? cc : bk}). Also check ${type === 'credit_card' ? 'Bank' : 'Credit Card'} tab (${type === 'credit_card' ? bk : cc}).`, 'info', 5000);
    }
  }, 150);
}

async function loadUtilHealth() {
  const el = document.getElementById('util-health-list');
  if (!el) return;
  el.innerHTML = '<span style="color:var(--text-muted);">Loading…</span>';
  try {
    const h = await api('GET', '/utilities/health');
    // Store per_type for click handlers
    window._healthPerType = h.per_type || {};
    el.innerHTML = `
      <div class="health-grid">
        <a class="health-metric" href="#" onclick="event.preventDefault(); _healthNavigateWithFilter(window._healthPerType, 'no_category');">
          <span class="health-label">Uncategorized transactions</span>
          <span class="health-value${h.uncategorized_transactions > 0 ? ' health-warn' : ''}">${h.uncategorized_transactions}</span>
        </a>
        <a class="health-metric" href="#" onclick="event.preventDefault(); _healthNavigateWithFilter(window._healthPerType, 'unreviewed');">
          <span class="health-label">Unreviewed transactions</span>
          <span class="health-value${h.unreviewed_transactions > 0 ? ' health-warn' : ''}">${h.unreviewed_transactions}</span>
        </a>
        <a class="health-metric" href="#" onclick="event.preventDefault(); _healthNavigateWithFilter(window._healthPerType, 'no_merchant');">
          <span class="health-label">Transactions with no merchant match</span>
          <span class="health-value${h.no_merchant_match > 0 ? ' health-warn' : ''}">${h.no_merchant_match}</span>
        </a>
        <a class="health-metric" href="#" onclick="event.preventDefault(); navigate('utilities'); setTimeout(()=>ensureCardExpanded('util-card-duplicates'),100);">
          <span class="health-label">Pending duplicate candidates</span>
          <span class="health-value${h.pending_duplicates > 0 ? ' health-warn' : ''}">${h.pending_duplicates}</span>
        </a>
        <div class="health-metric" style="cursor:default;">
          <span class="health-label">Orphaned categories</span>
          <span class="health-value${h.orphaned_categories > 0 ? ' health-warn' : ''}">${h.orphaned_categories}</span>
          ${h.orphaned_categories > 0 ? '<button class="btn btn-sm btn-primary" style="margin-top:4px;" onclick="_fixOrphanedCategories()">Fix Now</button>' : ''}
        </div>
      </div>`;
  } catch (err) {
    el.innerHTML = `<span style="color:var(--text-muted);">Error: ${esc(err.message)}</span>`;
  }
}

let _orphanJobId = null;
let _orphanPollInterval = null;

async function _fixOrphanedCategories() {
  const btn = document.querySelector('#util-health .btn-primary');
  if (btn) { btn.disabled = true; btn.textContent = 'Running…'; }

  toast('Running full re-normalization…', 'info', 3000);
  try {
    const data = await api('POST', '/normalize/apply', {});
    if (data.job_id) {
      _orphanJobId = data.job_id;
      _pollOrphanFix(btn);
    } else {
      toast('Re-normalization complete', 'success');
      loadUtilHealth();
    }
  } catch (err) {
    toast('Failed: ' + err.message, 'error');
    if (btn) { btn.disabled = false; btn.textContent = 'Fix Now'; }
  }
}

function _pollOrphanFix(btn) {
  if (_orphanPollInterval) clearInterval(_orphanPollInterval);
  _orphanPollInterval = setInterval(async () => {
    if (!_orphanJobId) { clearInterval(_orphanPollInterval); return; }
    try {
      const data = await api('GET', `/normalize/${_orphanJobId}`);
      if (data.status === 'success') {
        clearInterval(_orphanPollInterval);
        _orphanJobId = null;
        toast(`Re-normalization complete — ${data.rows_done} rows updated.`, 'success');
        loadUtilHealth();
      } else if (data.status === 'failed') {
        clearInterval(_orphanPollInterval);
        _orphanJobId = null;
        toast('Re-normalization failed: ' + (data.error || 'unknown'), 'error');
        if (btn) { btn.disabled = false; btn.textContent = 'Fix Now'; }
      }
    } catch (_) {}
  }, 1500);
}

// ── Category Picker (shared) ──────────────────────────────────
// Cached taxonomy for category picker dropdowns
let _categoryTaxonomy = null;

async function _ensureCategoryTaxonomy() {
  if (_categoryTaxonomy) return _categoryTaxonomy;
  try {
    const data = await api('GET', '/utilities/categories');
    _categoryTaxonomy = data.categories || [];
  } catch {
    _categoryTaxonomy = [];
  }
  return _categoryTaxonomy;
}

// Trigger onboarding check after initial load
setTimeout(_checkOnboarding, 1500);
