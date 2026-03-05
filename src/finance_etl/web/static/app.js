/* =========================================================
   finance_etl  —  Web UI  app.js
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
    import:             'Import Transactions',
    history:            'Import History',
    'credit-cards':     'Credit Card Transactions',
    'bank-transactions':'Bank Transactions',
    reports:            'Analytics Reports',
    settings:           'Settings & Logs',
  };
  document.getElementById('topbar-title').textContent = titles[page] || page;

  if (page === 'history')            loadHistory();
  if (page === 'reports')            loadReports();
  if (page === 'settings')           loadSettings();
  if (page === 'credit-cards')       loadTxnTab('credit_card');
  if (page === 'bank-transactions')  loadTxnTab('bank');
}

// ── Toasts ──────────────────────────────────────────────────
function toast(msg, type = 'info', duration = 4000) {
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = msg;
  document.getElementById('toasts').appendChild(el);
  setTimeout(() => el.remove(), duration);
}

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
  } else if (run.status === 'failed') {
    toast(`Import failed: ${run.error || '(unknown error)'}`, 'error');
    maybeShowLogsOnError();
  }
}

// ── Run status card ──────────────────────────────────────────
function setRunStatus(status, runId, counts, label) {
  const card = document.getElementById('run-status');
  card.className = `run-status visible ${status}`;

  const icons = { pending: '⏳', running: '⚙️', staged: '👁️', committing: '⚙️', success: '✅', failed: '❌', fail: '❌' };
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
  tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted" style="padding:32px">Loading…</td></tr>';

  try {
    const data = await api('GET', '/runs');
    if (!data.runs.length) {
      tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted" style="padding:32px">No runs yet. Import some transactions first.</td></tr>';
      return;
    }
    tbody.innerHTML = data.runs.map(r => {
      const status = r.status || 'unknown';
      const badge  = `<span class="badge badge-${status}">${status}</span>`;
      const actions = [];
      if (['staged'].includes(status)) {
        actions.push(`<button class="btn btn-secondary btn-sm" onclick="showHistoryPreview('${r.run_id}')">👁 Preview</button>`);
        actions.push(`<button class="btn btn-success btn-sm" onclick="commitRunFromHistory('${r.run_id}')">Commit</button>`);
      } else {
        actions.push(`<button class="btn btn-secondary btn-sm" onclick="showHistoryPreview('${r.run_id}')">👁 View</button>`);
      }
      actions.push(`<button class="btn btn-danger btn-sm" onclick="showDeleteModal('${r.run_id}')">🗑 Delete</button>`);
      return `<tr>
        <td class="mono">${esc(r.run_id)}</td>
        <td>${fmtDate(r.started_at)}</td>
        <td>${badge}</td>
        <td class="text-right">${fmt(r.rows_in)}</td>
        <td class="text-right">${fmt(r.rows_staged)}</td>
        <td class="text-right">${fmt(r.rows_loaded)}</td>
        <td class="text-right ${r.errors_count > 0 ? 'text-danger' : ''}">${fmt(r.errors_count)}</td>
        <td><div style="display:flex;gap:6px">${actions.join('')}</div></td>
      </tr>`;
    }).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted">Error: ${esc(err.message)}</td></tr>`;
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

  try {
    const data = await api('GET', '/reports');
    if (!data.reports.length) {
      grid.innerHTML = '<div class="empty"><div class="empty-icon">📊</div>No reports yet. Run an import first.</div>';
      return;
    }
    grid.innerHTML = data.reports.map(name => {
      const meta = REPORT_META[name] || { icon: '📄', desc: '' };
      return `
        <div class="report-card" onclick="viewChart('${esc(name)}')">
          <div class="rc-icon">${meta.icon}</div>
          <div class="rc-name">${esc(name.replace('.csv', '').replace(/_/g, ' '))}</div>
          <div class="rc-desc">${meta.desc}</div>
          <div class="rc-actions">
            <a class="btn btn-secondary btn-sm" href="/reports/${esc(name)}" download onclick="event.stopPropagation()">
              ↓ Download
            </a>
            <button class="btn btn-secondary btn-sm" onclick="event.stopPropagation(); editReport('${esc(name)}')" title="Open as template in Custom Report Builder">
              ✏ Edit report
            </button>
            <a class="btn btn-secondary btn-sm" href="/docs#tag/reports" target="_blank" onclick="event.stopPropagation()" title="Open report documentation in new tab">
              ℹ Info
            </a>
            <button class="btn btn-primary btn-sm" onclick="event.stopPropagation(); viewChart('${esc(name)}')">
              Preview
            </button>
          </div>
        </div>`;
    }).join('');
  } catch (err) {
    grid.innerHTML = `<div class="empty">Error: ${esc(err.message)}</div>`;
  }
  document.getElementById('chart-area').style.display = 'none';
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
    document.getElementById('chart-head').innerHTML = cols.map(c => `<th>${esc(c)}</th>`).join('');
    document.getElementById('chart-body').innerHTML = data.rows.map(row =>
      `<tr>${cols.map(c => `<td>${esc(String(row[c] ?? ''))}</td>`).join('')}</tr>`
    ).join('');
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
  // Open custom report builder pre-filled as template from built-in report
  const card = document.getElementById('custom-report-card');
  card.style.display = '';
  card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

  const tmpl = REPORT_TEMPLATES[name] || { group_by: [], bucket: null, filters: [] };

  // Clear and rebuild filters
  document.getElementById('report-filter-rows').innerHTML = '';
  tmpl.filters.forEach(f => {
    addReportFilter();
    const rows = document.getElementById('report-filter-rows').children;
    const last = rows[rows.length - 1];
    if (last) {
      const fld = last.querySelector('.rf-field');
      const op  = last.querySelector('.rf-op');
      const val = last.querySelector('.rf-val');
      if (fld) fld.value = f.field;
      if (op)  op.value  = f.op;
      if (val) val.value = f.value ?? '';
    }
  });

  // Set group-by selections
  const groupSel = document.getElementById('report-group-by');
  [...groupSel.options].forEach(o => { o.selected = tmpl.group_by.includes(o.value); });

  // Set bucket
  document.getElementById('report-bucket').value = tmpl.bucket || '';
}

// ── Custom report builder ──────────────────────────────────────

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

function addReportFilter() {
  const container = document.getElementById('report-filter-rows');
  const idx = container.children.length;
  const fieldOpts = Object.entries(REPORT_FIELD_LABELS).map(([v,l]) =>
    `<option value="${v}">${esc(l)}</option>`).join('');
  const opOpts = REPORT_OPS.map(o => `<option value="${o}">${esc(o)}</option>`).join('');
  const row = document.createElement('div');
  row.style.cssText = 'display:flex; gap:6px; align-items:center;';
  row.dataset.filterIdx = idx;
  row.innerHTML = `
    <label style="display:flex;align-items:center;gap:4px;font-size:12px;white-space:nowrap;cursor:pointer;" title="Include all values (no filter applied for this field)">
      <input type="checkbox" class="rf-all" onchange="onFilterAllChange(this)"> All
    </label>
    <select class="rf-field" style="flex:2;">${fieldOpts}</select>
    <select class="rf-op"    style="flex:1;">${opOpts}</select>
    <input  class="rf-val"   style="flex:3;" type="text" placeholder="value" />
    <button class="btn btn-secondary btn-sm" onclick="this.parentElement.remove()">✕</button>`;
  container.appendChild(row);
}

function onFilterAllChange(el) {
  const row = el.closest('div');
  const op  = row.querySelector('.rf-op');
  const val = row.querySelector('.rf-val');
  if (op)  op.disabled  = el.checked;
  if (val) val.disabled = el.checked;
}

async function runCustomReport() {
  const filters = [];
  document.querySelectorAll('#report-filter-rows > div').forEach(row => {
    if (row.querySelector('.rf-all')?.checked) return; // "Include all" — skip this filter
    const field = row.querySelector('.rf-field')?.value;
    const op    = row.querySelector('.rf-op')?.value;
    const val   = row.querySelector('.rf-val')?.value;
    if (field && op) {
      let value = val;
      if (op === 'in')      value = val.split(',').map(s => s.trim()).filter(Boolean);
      if (op === 'between') value = val.split(',').map(s => s.trim());
      if (op === 'is_null' || op === 'not_null') value = null;
      filters.push({ field, op, value });
    }
  });

  const groupByEl = document.getElementById('report-group-by');
  const group_by  = [...groupByEl.selectedOptions].map(o => o.value);
  const bucket    = document.getElementById('report-bucket').value || null;
  const date_from = document.getElementById('report-date-from').value || null;
  const date_to   = document.getElementById('report-date-to').value   || null;

  document.getElementById('custom-report-results').style.display = '';
  document.getElementById('custom-report-body').innerHTML =
    '<tr><td colspan="99" class="text-center text-muted" style="padding:20px">Running…</td></tr>';
  document.getElementById('custom-report-foot').innerHTML = '';

  try {
    const data = await api('POST', '/reports/query', { filters, group_by, bucket, date_from, date_to, limit: 1000 });
    const cols = data.columns || (data.rows.length ? Object.keys(data.rows[0]) : []);
    document.getElementById('custom-report-meta').textContent =
      `${data.count ?? data.rows.length} row(s)`;
    // BUG FIX 2: custom-report-head IS already a <tr> element — do NOT wrap in another <tr>.
    // Previously: innerHTML = `<tr>${cells}</tr>` caused a <tr>-inside-<tr> which made the
    // browser strip/relocate the inner <tr>, leaving the header empty and misaligning tfoot.
    document.getElementById('custom-report-head').innerHTML =
      cols.map(c => {
        const tip = REPORT_COL_TOOLTIPS[c];
        if (!tip) return `<th>${esc(c)}</th>`;
        const href = `/metric-docs/${encodeURIComponent(c)}`;
        return `<th>${esc(c)} <a href="${href}" target="_blank" title="${esc(tip)} — Click to read more." style="font-size:10px;opacity:.65;text-decoration:none;cursor:help;" onclick="event.stopPropagation()">ℹ</a></th>`;
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

function downloadReportResults() {
  const head = document.getElementById('custom-report-head');
  const body = document.getElementById('custom-report-body');
  if (!head || !body) return;
  const headers = [...head.querySelectorAll('th')].map(th => th.textContent.replace(/\s*ℹ\s*$/, '').trim());
  const dataRows = [...body.querySelectorAll('tr')].map(tr =>
    [...tr.querySelectorAll('td')].map(td => td.textContent.trim())
  ).filter(r => r.length);
  if (!headers.length || !dataRows.length) { toast('No results to download.', 'info', 2000); return; }
  const csvLines = [headers, ...dataRows].map(r =>
    r.map(v => `"${String(v).replace(/"/g, '""')}"`).join(',')
  );
  const blob = new Blob([csvLines.join('\r\n')], { type: 'text/csv' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href     = url;
  a.download = `custom_report_${new Date().toISOString().slice(0,10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
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

// ── Utilities ─────────────────────────────────────────────────
function esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Boot ───────────────────────────────────────────────────────
loadSettings();
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
};

// Required canonical fields for UI validation hints
const WIZARD_REQUIRED_FIELDS = new Set(['transaction_date']);
// Fields removed from step 2 display (uncommon / confusing for most users)
const STEP2_HIDDEN = new Set(['debit_amount', 'credit_amount', 'dc_flag', 'posted_date']);
// BUG FIX 3: amount_debit / amount_credit are the Feature 2 fallback pair — visible in step 2.
const WIZARD_AMOUNT_GROUPS   = [
  ['debit_amount', 'credit_amount'],
  ['money_in', 'money_out'],
  ['amount'],
  ['amount_debit', 'amount_credit'],  // BUG FIX 3: fallback pair also forms a valid mapping
];

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
  // Use server-provided canonical fields if available, else fall back to wizard.suggestions keys
  const fields = (wizard.canonicalFields.length
    ? wizard.canonicalFields
    : Object.keys(wizard.suggestions).concat(
        ['transaction_date','debit_amount','credit_amount','amount','money_in','money_out',
         'dc_flag','description','posted_date','merchant','category','account','notes','currency']
          .filter(f => !Object.keys(wizard.suggestions).includes(f))
      )
  ).filter(f => !STEP2_HIDDEN.has(f));

  const labels = wizard.canonicalLabels;
  const isReq = f => WIZARD_REQUIRED_FIELDS.has(f);

  const tbody = document.getElementById('w-mapping-rows');
  tbody.innerHTML = fields.map(field => {
    const label = labels[field] || field;
    const current = wizard.mapping[field] || '';
    const isSuggested = !!wizard.suggestions[field] && wizard.suggestions[field] === current;
    const opts = ['', ...wizard.headers].map(h =>
      `<option value="${esc(h)}" ${h === current ? 'selected' : ''}>${h ? esc(h) : '(none)'}</option>`
    ).join('');
    return `
      <tr>
        <td class="field-label${isReq(field) ? ' required' : ''}">${esc(label)}</td>
        <td>
          <select data-field="${esc(field)}"
                  class="${isSuggested ? 'suggested' : ''}"
                  onchange="onMappingChange(this)">
            ${opts}
          </select>
        </td>
      </tr>`;
  }).join('');

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
  const ok = WIZARD_AMOUNT_GROUPS.some(group => group.every(f => mapped.has(f)));
  if (!ok) {
    errors.push('Amount mapping required: map (debit_amount + credit_amount), (money_in + money_out), (amount), or (amount_debit + amount_credit).');
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

  // Pre-fill date format from server-inferred hint if the field is empty
  if (wizard.suggestedDateFormat) {
    setVal('w-date-format', wizard.suggestedDateFormat);
  }

  // BUG FIX 1: Sync wizard statement_type radios from import page (if already set).
  // This lets users who selected the type before opening the wizard skip re-selecting it.
  // The wizard reads from its OWN radios at submit time (not the import page) to avoid
  // sending null when the import page radios are not yet set.
  if (!document.querySelector('input[name="w-statement-type"]:checked')) {
    const importSel = document.querySelector('input[name="statement-type"]:checked');
    if (importSel) {
      const wizSel = document.querySelector(`input[name="w-statement-type"][value="${importSel.value}"]`);
      if (wizSel) wizSel.checked = true;
    }
  }
  // Hide previous error if user re-enters step 3
  const stErr = document.getElementById('w-stmt-type-error');
  if (stErr) stErr.style.display = 'none';

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

  // BUG FIX 1 (Layer 1): Read statement_type from the wizard's OWN radio buttons.
  // Previously read from the import page radios via getStatementType() which returned
  // null when the user opened the wizard before selecting a type — silently sending
  // statement_type=null to the backend and routing rows to neither tab.
  const wizStmt = document.querySelector('input[name="w-statement-type"]:checked');
  const statementType = wizStmt ? wizStmt.value : getStatementType();
  console.log('[Mapping] statement_type submitted as:', statementType);

  if (!statementType) {
    const stErr = document.getElementById('w-stmt-type-error');
    if (stErr) stErr.style.display = '';
    toast('Select a statement type (Credit Card or Bank) before saving.', 'error');
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
      // BUG FIX 1: read from wizard selector (not import page radio)
      statement_type:   statementType,
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

/** Read current filter values from the DOM for the given tab type. */
function _txnFilters(type) {
  const p = _pfx(type);
  return {
    source:    _srcCtrl[type].value(),                                   // from radio-dropdown
    date_from: document.getElementById(`${p}-date-from`)?.value || '',
    date_to:   document.getElementById(`${p}-date-to`)?.value   || '',
    account:   (document.getElementById(`${p}-account`)?.value  || '').trim(),
    category:  (document.getElementById(`${p}-category`)?.value || '').trim(),
    merchant:  (document.getElementById(`${p}-merchant`)?.value || '').trim(),
    group_by:  document.getElementById(`${p}-group-by`)?.value  || '',
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
  if (f.group_by)  qs.set('group_by',  f.group_by);
  if (f.source && f.source !== 'all') qs.set('source', f.source);

  // Totals endpoint uses the same filter params (no pagination or sort)
  const tqs = new URLSearchParams({ type });
  if (f.date_from) tqs.set('date_from', f.date_from);
  if (f.date_to)   tqs.set('date_to',   f.date_to);
  if (f.account)   tqs.set('account',   f.account);
  if (f.category)  tqs.set('category',  f.category);
  if (f.merchant)  tqs.set('merchant',  f.merchant);
  if (f.source && f.source !== 'all') tqs.set('source', f.source);

  if (reset) {
    document.getElementById(`${p}-tbody`).innerHTML =
      `<tr><td colspan="10" class="text-center text-muted" style="padding:32px">Loading\u2026</td></tr>`;
    document.getElementById(`${p}-tfoot`).innerHTML = '';
    document.getElementById(`${p}-meta`).textContent = '';
    document.getElementById(`${p}-load-more`).style.display = 'none';
    // Populate source dropdown (table_controls.js) on every tab switch
    await _srcCtrl[type].load();
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
      _renderTxnBody(p, rows, cols, false);
    } else {
      _renderTxnBody(p, rows, cols, true);   // append rows for Load more
    }

    // Pinned tfoot always reflects the full filtered set, not just the current page.
    // renderTxnTotals is defined in table_controls.js (shared utility).
    renderTxnTotals(document.getElementById(`${p}-tfoot`), totals, type, cols.length || 10);

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
  ['date-from', 'date-to', 'account', 'category', 'merchant'].forEach(id => {
    const el = document.getElementById(`${p}-${id}`);
    if (el) el.value = '';
  });
  const grp = document.getElementById(`${p}-group-by`);
  if (grp) grp.value = '';
  _txnState[type].sortBy  = 'transaction_date';
  _txnState[type].sortDir = 'desc';
  loadTxnTab(type);
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
  thead.innerHTML = cols.map(c => {
    const isSorted = c === st.sortBy;
    const arrow    = isSorted ? (st.sortDir === 'asc' ? ' \u25b2' : ' \u25bc') : '';
    return `<th style="cursor:pointer;user-select:none;" onclick="_txnSort('${type}','${c}')">${esc(c)}${arrow}</th>`;
  }).join('');
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

/**
 * Render (or append to) the <tbody> rows.
 * Numeric columns are right-aligned and monospaced for readability.
 */
function _renderTxnBody(p, rows, cols, append) {
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

  const html = rows.map(row =>
    `<tr>${cols.map(c => {
      const val = row[c] != null ? String(row[c]) : '';
      const cls = NUMERIC_COLS.has(c) ? ' class="mono text-right"' : '';
      return `<td${cls}>${esc(val)}</td>`;
    }).join('')}</tr>`
  ).join('');

  if (append) {
    tbody.insertAdjacentHTML('beforeend', html);
  } else {
    tbody.innerHTML = html;
  }
}

// _renderTxnTfoot has been extracted to table_controls.js as renderTxnTotals().
// See table_controls.js for the implementation with proper labeled column cells.
