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
    settings:           'Settings & Logs',
  };
  document.getElementById('topbar-title').textContent = titles[page] || page;

  if (page === 'history')            loadHistory();
  if (page === 'cashflow')           loadCashFlow();
  if (page === 'reports')            loadReports();
  if (page === 'settings')           loadSettings();
  if (page === 'credit-cards')       loadTxnTab('credit_card');
  if (page === 'bank-transactions')  loadTxnTab('bank');
  if (page === 'merchant-rules')     { loadMerchantAnalytics(); loadMerchantRules(); loadUncategorized(); _clearSuggestions(); }
  if (page === 'category-rules')     { loadCategoryRules(); }
  if (page === 'recurring-transactions') { loadRecurringTransactions(); }
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

async function loadRecurringTransactions() {
  const statusEl = document.getElementById('recurring-status');
  const listEl = document.getElementById('recurring-list');
  const totalEl = document.getElementById('recurring-monthly-total');
  const countEl = document.getElementById('recurring-count-label');

  if (statusEl) statusEl.textContent = 'Analyzing…';
  try {
    const data = await api('GET', '/recurring');
    if (statusEl) statusEl.textContent = '';

    // KPI
    totalEl.textContent = '$' + Number(data.monthly_total).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
    countEl.textContent = `${data.count} recurring charge${data.count !== 1 ? 's' : ''} detected`;

    if (!data.patterns || data.patterns.length === 0) {
      listEl.innerHTML = '<p style="color:var(--text-muted);">No recurring transactions detected. Import more data or manually mark merchants below.</p>';
      return;
    }

    _renderRecurringList(data.patterns, listEl);
  } catch (err) {
    if (statusEl) statusEl.textContent = `Error: ${err.message}`;
    listEl.innerHTML = `<p style="color:var(--danger);">Failed to load: ${esc(err.message)}</p>`;
  }
}

function _renderRecurringList(patterns, container) {
  const freqColors = {
    weekly: '#3b82f6', biweekly: '#6366f1', monthly: '#8b5cf6',
    quarterly: '#f59e0b', annual: '#22c55e', irregular: '#94a3b8',
  };

  let html = '<table style="width:100%; border-collapse:collapse;">';
  html += `<thead><tr style="border-bottom:2px solid var(--border); text-align:left;">
    <th style="padding:8px 10px;">Merchant</th>
    <th style="padding:8px 10px;">Amount</th>
    <th style="padding:8px 10px;">Frequency</th>
    <th style="padding:8px 10px;">Last Charged</th>
    <th style="padding:8px 10px;">Next Estimated</th>
    <th style="padding:8px 10px;">Hits</th>
    <th style="padding:8px 10px;"></th>
  </tr></thead><tbody>`;

  for (const p of patterns) {
    const color = freqColors[p.frequency] || '#94a3b8';
    const badge = p.is_auto
      ? '<span style="font-size:10px; background:#e2e8f0; color:#64748b; padding:1px 6px; border-radius:3px; margin-left:6px;">auto</span>'
      : '<span style="font-size:10px; background:#dbeafe; color:#3b82f6; padding:1px 6px; border-radius:3px; margin-left:6px;">manual</span>';

    html += `<tr style="border-bottom:1px solid var(--border);">
      <td style="padding:8px 10px; font-weight:500;">${esc(p.merchant)}${badge}</td>
      <td style="padding:8px 10px; font-weight:600;">$${Number(p.median_amount).toFixed(2)}</td>
      <td style="padding:8px 10px;">
        <span style="background:${color}; color:#fff; font-size:11px; padding:2px 8px; border-radius:4px;">${esc(p.frequency)}</span>
      </td>
      <td style="padding:8px 10px;">${esc(p.last_date)}</td>
      <td style="padding:8px 10px;">${p.next_estimated ? esc(p.next_estimated) : '—'}</td>
      <td style="padding:8px 10px; text-align:center;">${p.occurrences}</td>
      <td style="padding:8px 10px;">
        <button class="btn btn-secondary btn-sm" style="font-size:11px; padding:2px 8px;"
          onclick="toggleRecurring('${esc(p.merchant)}', false)">Unmark</button>
      </td>
    </tr>`;
  }
  html += '</tbody></table>';
  container.innerHTML = html;
}

/** Mark a merchant as recurring (or not) via the override API.
 *  Setting is_recurring=false creates a "force-unmark" override that
 *  suppresses auto-detection for that merchant; it does NOT delete the
 *  override row (use DELETE /recurring/override/{merchant} for that). */
async function toggleRecurring(merchant, isRecurring) {
  try {
    await api('POST', '/recurring/override', { merchant, is_recurring: isRecurring });
    toast(isRecurring ? `Marked "${merchant}" as recurring` : `Unmarked "${merchant}"`, 'success', 2500);
    loadRecurringTransactions();
  } catch (err) {
    toast(`Override failed: ${err.message}`, 'error');
  }
}

/** Manual add from the input field at the bottom of the page. */
async function manualMarkRecurring() {
  const input = document.getElementById('recurring-manual-merchant');
  const merchant = (input.value || '').trim();
  if (!merchant) { toast('Enter a merchant name', 'error', 2000); return; }
  await toggleRecurring(merchant, true);
  input.value = '';
}

// ── Backup & Restore (v2) ─────────────────────────────────────

// Pending restore file — set by previewBackup(), consumed by confirmRestore()
let _pendingRestoreFile = null;

function downloadBackup() {
  const statusEl = document.getElementById('backup-export-status');
  if (statusEl) statusEl.textContent = 'Preparing export…';
  const a = document.createElement('a');
  a.href = '/backup/export';
  a.download = '';  // server sets Content-Disposition filename
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  if (statusEl) {
    statusEl.textContent = 'Download started.';
    setTimeout(() => { statusEl.textContent = ''; }, 4000);
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

    let html = `<p><strong>Backup version:</strong> ${esc(String(ver))}</p>`;
    if (payload.created_at) html += `<p><strong>Created:</strong> ${esc(payload.created_at)}</p>`;
    if (payload.app_version) html += `<p><strong>App version:</strong> ${esc(payload.app_version)}</p>`;

    html += '<table style="width:100%; font-size:12px; border-collapse:collapse; margin-top:8px;">';
    html += '<tr style="border-bottom:1px solid var(--border);"><th style="text-align:left; padding:4px;">Table</th><th style="text-align:right; padding:4px;">Rows</th></tr>';

    // Count rows in the backup for each table
    const tables = isV2
      ? ['runs','merchant_rules','merchant_category_map','category_rules','budget_goals','normalization_jobs','transactions_stage','transactions_norm']
      : ['merchant_rules','merchant_categories','category_rules','budget_goals','transactions'];
    for (const t of tables) {
      const arr = (isV2 ? data[t] : payload[t]) || [];
      html += `<tr><td style="padding:4px;">${esc(t)}</td><td style="text-align:right; padding:4px;">${Array.isArray(arr) ? arr.length : '?'}</td></tr>`;
    }
    html += '</table>';

    // Wizard profiles count
    const wp = payload.wizard_profiles;
    if (wp && typeof wp === 'object') {
      html += `<p style="margin-top:8px;"><strong>Wizard profiles:</strong> ${Object.keys(wp).length}</p>`;
    }

    html += '<p style="margin-top:12px; color:#e74c3c; font-weight:600;">This will replace ALL existing data. A snapshot will be saved automatically.</p>';

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

  if (statusEl) statusEl.textContent = 'Restoring…';
  const formData = new FormData();
  formData.append('file', _pendingRestoreFile);
  try {
    const resp = await fetch('/backup/restore', { method: 'POST', body: formData });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || resp.statusText);
    const parts = [];
    if (data.merchant_rules_restored) parts.push(`${data.merchant_rules_restored} merchant rules`);
    if (data.category_rules_restored) parts.push(`${data.category_rules_restored} category rules`);
    if (data.budget_goals_restored) parts.push(`${data.budget_goals_restored} budget goals`);
    if (data.transactions_norm_restored) parts.push(`${data.transactions_norm_restored} transactions`);
    if (data.runs_restored) parts.push(`${data.runs_restored} runs`);
    if (data.wizard_profiles_restored) parts.push(`${data.wizard_profiles_restored} wizard profiles`);
    const msg = `Restored: ${parts.join(', ')}.`;
    if (statusEl) statusEl.textContent = msg;
    toast('Backup restored successfully.', 'success', 6000);
    // Refresh backup status display
    loadBackupStatus();
  } catch (err) {
    if (statusEl) statusEl.textContent = `Error: ${err.message}`;
    toast(`Restore failed: ${err.message}`, 'error');
  } finally {
    document.getElementById('restore-file-input').value = '';
    _pendingRestoreFile = null;
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
      await api('POST', '/transactions/tags', { transaction_fingerprint: fingerprint, tag_id: tagId });
    } else {
      await api('DELETE', `/transactions/tags?transaction_fingerprint=${encodeURIComponent(fingerprint)}&tag_id=${tagId}`);
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
loadDashboard();
refreshUnreviewedBadge();
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

/** Read current filter values from the DOM for the given tab type. */
function _txnFilters(type) {
  const p = _pfx(type);
  return {
    source:          _srcCtrl[type].value(),                                   // from radio-dropdown
    date_from:       document.getElementById(`${p}-date-from`)?.value || '',
    date_to:         document.getElementById(`${p}-date-to`)?.value   || '',
    account:         (document.getElementById(`${p}-account`)?.value  || '').trim(),
    category:        (document.getElementById(`${p}-category`)?.value || '').trim(),
    merchant:        (document.getElementById(`${p}-merchant`)?.value || '').trim(),
    subtype:         document.getElementById(`${p}-subtype`)?.value   || '',  // CC only
    group_by:        document.getElementById(`${p}-group-by`)?.value  || '',
    unreviewed_only: document.getElementById(`${p}-unreviewed-only`)?.checked || false,
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
  if (f.tag)       qs.set('tag', f.tag);

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
  if (f.tag)       tqs.set('tag', f.tag);

  if (reset) {
    document.getElementById(`${p}-tbody`).innerHTML =
      `<tr><td colspan="10" class="text-center text-muted" style="padding:32px">Loading\u2026</td></tr>`;
    document.getElementById(`${p}-tfoot`).innerHTML = '';
    document.getElementById(`${p}-meta`).textContent = '';
    document.getElementById(`${p}-load-more`).style.display = 'none';
    // Populate source dropdown (table_controls.js) on every tab switch
    await _srcCtrl[type].load();
    // Ensure tag filter dropdown is populated
    _populateTagDropdowns();
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
    // Load tag chips for visible transaction rows
    _loadVisibleTagChips();

    // Pinned tfoot always reflects the full filtered set, not just the current page.
    // renderTxnTotals is defined in table_controls.js (shared utility).
    // Pass optional warnEl for CC legacy/conflict banners.
    renderTxnTotals(
      document.getElementById(`${p}-tfoot`), totals, type, cols.length || 10,
      document.getElementById(`${p}-totals-warn`),
    );

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
  // Hide metadata columns used only for review logic; append a Review header instead
  const HIDDEN_COLS = new Set(['transaction_fingerprint', 'unreviewed']);
  thead.innerHTML = cols.filter(c => !HIDDEN_COLS.has(c)).map(c => {
    const isSorted = c === st.sortBy;
    const arrow    = isSorted ? (st.sortDir === 'asc' ? ' \u25b2' : ' \u25bc') : '';
    return `<th style="cursor:pointer;user-select:none;" onclick="_txnSort('${type}','${c}')">${esc(c)}${arrow}</th>`;
  }).join('') + '<th class="text-center" style="min-width:100px;">Tags</th><th class="text-center" style="min-width:90px;">Review</th>';
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
  // Columns hidden from the user (used for review logic only)
  const HIDDEN_COLS = new Set(['transaction_fingerprint', 'unreviewed']);

  const visibleCols = cols.filter(c => !HIDDEN_COLS.has(c));

  const html = rows.map(row => {
    // DuckDB may serialize booleans as true or 'true' depending on driver version
    const isUnreviewed = row.unreviewed === true || row.unreviewed === 'true';
    const fp = row.transaction_fingerprint || '';
    const rowCls = isUnreviewed ? ' class="unreviewed-row"' : '';
    const cells = visibleCols.map(c => {
      const val = row[c] != null ? String(row[c]) : '';
      const cls = NUMERIC_COLS.has(c) ? ' class="mono text-right"' : '';
      return `<td${cls}>${esc(val)}</td>`;
    }).join('');
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
    return `<tr${rowCls}>${cells}${tagCell}${reviewCell}</tr>`;
  }).join('');

  if (append) {
    tbody.insertAdjacentHTML('beforeend', html);
  } else {
    tbody.innerHTML = html;
  }
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


// ── Merchant Intelligence ─────────────────────────────────────

let _miSearchTimer = null;
function _debouncedMerchantSearch() {
  clearTimeout(_miSearchTimer);
  _miSearchTimer = setTimeout(loadMerchantAnalytics, 300);
}

async function loadMerchantAnalytics() {
  const listEl = document.getElementById('mi-list');
  const sortBy = document.getElementById('mi-sort')?.value || 'total_spend';
  const search = document.getElementById('mi-search')?.value?.trim() || '';
  if (!listEl) return;
  listEl.innerHTML = '<span style="color:var(--text-muted);font-size:13px;">Loading…</span>';

  let url = `/merchant-analytics?sort_by=${sortBy}&limit=100`;
  if (search) url += `&search=${encodeURIComponent(search)}`;

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

// ── Condition row helpers ──────────────────────────────────────

function _makeConditionRow(pattern, matchType, negate) {
  // Build via DOM APIs to avoid global CSS "width:100%" on select/input
  // collapsing the pattern input to 0px inside the flex row.
  const row = document.createElement('div');
  row.className = 'rf-condition-row';
  row.style.cssText = 'display:flex; align-items:center; gap:8px; background:var(--bg-alt,#f8f9fa); border-radius:6px; padding:6px 10px;';

  // Match-type select — override global width:100% so it only sizes to content
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

  // Pattern input — flex:1 grows to fill remaining space; width:auto overrides global
  const inp = document.createElement('input');
  inp.type = 'text';
  inp.className = 'rf-cond-pattern';
  inp.placeholder = 'e.g. AMAZON, ^UBER, .*COFFEE.*';
  inp.value = pattern || '';
  inp.style.cssText = 'flex:1; min-width:80px; width:auto; padding:4px 8px; border-radius:5px; border:1px solid var(--border); font-size:12px; font-family:monospace; background:var(--card-bg,#fff); color:var(--text,#222);';

  // NOT label + checkbox
  const label = document.createElement('label');
  label.style.cssText = 'display:flex; align-items:center; gap:4px; font-size:12px; white-space:nowrap; cursor:pointer; flex-shrink:0;';
  const cb = document.createElement('input');
  cb.type = 'checkbox';
  cb.className = 'rf-cond-negate';
  cb.checked = !!negate;
  cb.style.cursor = 'pointer';
  label.appendChild(cb);
  label.appendChild(document.createTextNode(' NOT'));

  // Remove button
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'btn btn-secondary btn-sm rf-cond-remove';
  btn.textContent = '✕';
  btn.title = 'Remove condition';
  btn.style.cssText = 'font-size:12px; padding:2px 8px; flex-shrink:0;';
  btn.addEventListener('click', function() { removeConditionRow(this); });

  row.appendChild(sel);
  row.appendChild(inp);
  row.appendChild(label);
  row.appendChild(btn);
  return row;
}

function _updateLogicVisibility() {
  const rows = document.querySelectorAll('#rf-conditions .rf-condition-row');
  const wrap = document.getElementById('rf-logic-wrap');
  if (wrap) wrap.style.display = rows.length >= 2 ? 'flex' : 'none';
  // Update remove button visibility — always keep at least one row
  document.querySelectorAll('#rf-conditions .rf-cond-remove').forEach(btn => {
    btn.style.visibility = rows.length > 1 ? 'visible' : 'hidden';
  });
}

function addConditionRow(pattern = '', matchType = 'contains', negate = false) {
  const container = document.getElementById('rf-conditions');
  if (!container) return;
  container.appendChild(_makeConditionRow(pattern, matchType, negate));
  _updateLogicVisibility();
}

function removeConditionRow(btn) {
  const rows = document.querySelectorAll('#rf-conditions .rf-condition-row');
  if (rows.length <= 1) return; // Keep at least one
  btn.closest('.rf-condition-row').remove();
  _updateLogicVisibility();
}

function _getRuleConditions() {
  const rows = document.querySelectorAll('#rf-conditions .rf-condition-row');
  return Array.from(rows).map(row => ({
    pattern:    row.querySelector('.rf-cond-pattern').value.trim(),
    match_type: row.querySelector('.rf-cond-type').value,
    negate:     row.querySelector('.rf-cond-negate').checked,
  }));
}

function _setRuleConditions(conditions, logic) {
  const container = document.getElementById('rf-conditions');
  if (!container) return;
  container.innerHTML = '';
  (conditions || []).forEach(c => addConditionRow(c.pattern, c.match_type || 'contains', !!c.negate));
  if (!conditions || !conditions.length) addConditionRow(); // Ensure at least one row
  const logicEl = document.getElementById('rf-logic');
  if (logicEl) logicEl.value = logic || 'AND';
  _updateLogicVisibility();
}

// ── Merchant rules CRUD ────────────────────────────────────────

function _rulePatternSummary(r) {
  if (r.conditions && r.conditions.length) {
    const parts = r.conditions.map(c => `${c.negate ? 'NOT ' : ''}${esc(c.match_type)} "${esc(c.pattern)}"`);
    return parts.join(` <span style="color:var(--text-muted);font-size:10px;">${esc(r.logic || 'AND')}</span> `);
  }
  return `<span class="mono">${esc(r.pattern)}</span>`;
}

async function loadMerchantRules() {
  const tbody = document.getElementById('merchant-rules-tbody');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted" style="padding:24px">Loading…</td></tr>';
  try {
    const data = await api('GET', '/merchant-rules');
    if (!data.rules.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted" style="padding:24px">No rules yet. Click "+ Add Rule" to create one.</td></tr>';
      return;
    }
    tbody.innerHTML = data.rules.map(r => `<tr>
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
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5" class="text-center text-muted">Error: ${esc(err.message)}</td></tr>`;
  }
}

function openRuleForm(ruleId) {
  _editingRuleId = ruleId;
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
    if (rule.conditions && rule.conditions.length) {
      _setRuleConditions(rule.conditions, rule.logic);
    } else {
      _setRuleConditions([{pattern: rule.pattern, match_type: rule.match_type, negate: false}], 'AND');
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
  // Strip any accidentally-empty condition rows
  const conditions = _getRuleConditions().filter(c => c.pattern);
  if (!conditions.length) {
    toast('At least one condition pattern is required.', 'error');
    return;
  }
  const logic = (document.getElementById('rf-logic') || {}).value || 'AND';
  // Use first condition as legacy pattern/match_type for backward compat display
  const body = {
    pattern:    conditions[0].pattern,
    match_type: conditions[0].match_type,
    merchant,
    priority:   parseInt(document.getElementById('rf-priority').value, 10) || 0,
    conditions: conditions.length > 1 || conditions[0].negate ? conditions : null,
    logic:      conditions.length > 1 || conditions[0].negate ? logic : 'AND',
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
  resultEl.textContent = 'Testing…';
  matchesEl.style.display = 'none';
  _testMatches = [];

  // Strip empty rows — don't block on accidental blank rows
  const conditions = _getRuleConditions().filter(c => c.pattern);
  if (!conditions.length) {
    resultEl.textContent = 'Enter at least one condition pattern first.';
    return;
  }
  const logic = (document.getElementById('rf-logic') || {}).value || 'AND';
  const body = {
    pattern:    conditions[0].pattern,
    match_type: conditions[0].match_type,
    merchant:   document.getElementById('rf-merchant').value.trim() || 'Test',
    priority:   parseInt(document.getElementById('rf-priority').value, 10) || 0,
    conditions: conditions.length > 1 || conditions[0].negate ? conditions : null,
    logic,
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

// ── Merchant category panel ───────────────────────────────────

async function loadUncategorized() {
  const container = document.getElementById('uncategorized-list');
  if (!container) return;
  container.innerHTML = '<span style="color:var(--text-muted);font-size:13px;">Loading…</span>';
  try {
    const data = await api('GET', '/merchant-categories/uncategorized');
    if (!data.merchants.length) {
      container.innerHTML = '<span style="color:var(--text-muted);font-size:13px;">All merchants are categorized.</span>';
      return;
    }
    container.innerHTML = data.merchants.map(m => {
      const safeId  = m.replace(/[^a-zA-Z0-9]/g, '_');
      // JSON.stringify wraps in double-quotes; escape them for the HTML attribute
      const jsonArg = JSON.stringify(m).replace(/"/g, '&quot;');
      return `
        <div style="display:flex; align-items:center; gap:8px; padding:6px 0; border-bottom:1px solid var(--border);">
          <span style="flex:1; font-size:13px;">${esc(m)}</span>
          <input type="text" placeholder="Category…"
                 id="cat-input-${safeId}"
                 style="width:180px; padding:4px 8px; border-radius:6px; border:1px solid var(--border); font-size:12px;" />
          <button class="btn btn-primary btn-sm" onclick="assignCategory(${jsonArg})">Assign</button>
        </div>`;
    }).join('');
  } catch (err) {
    container.innerHTML = `<span style="color:var(--text-muted);font-size:13px;">Error: ${esc(err.message)}</span>`;
  }
}

async function assignCategory(merchant) {
  const safeKey = merchant.replace(/[^a-zA-Z0-9]/g, '_');
  const input = document.getElementById(`cat-input-${safeKey}`);
  const category = input ? input.value.trim() : '';
  if (!category) {
    toast('Enter a category name first.', 'error');
    return;
  }
  try {
    await api('POST', '/merchant-categories', { merchant, category });
    toast(`Category "${category}" assigned to "${merchant}".`, 'success');
    loadUncategorized();
  } catch (err) {
    toast(`Failed: ${err.message}`, 'error');
  }
}


// ── Rule Suggestions ──────────────────────────────────────────

let _ruleSuggestions = [];   // {pattern, match_type, merchant, count, num_variants, sample_descriptions}
let _catSuggestions  = [];   // {merchant, suggested_category, confidence}

function _clearSuggestions() {
  _ruleSuggestions = [];
  const rl = document.getElementById('rule-suggestions-list');
  if (rl) rl.innerHTML = '';
  const raBtn = document.getElementById('rule-suggest-accept-all');
  if (raBtn) raBtn.style.display = 'none';
  const rs = document.getElementById('rule-suggest-status');
  if (rs) rs.textContent = '';
}

async function loadRuleSuggestions() {
  const statusEl = document.getElementById('rule-suggest-status');
  const listEl   = document.getElementById('rule-suggestions-list');
  const acceptAllBtn = document.getElementById('rule-suggest-accept-all');
  if (!listEl) return;

  statusEl.textContent = 'Analyzing…';
  listEl.innerHTML = `<div style="color:var(--text-muted);font-size:13px;padding:8px 0;">
    Scanning transaction descriptions — this may take a moment…
  </div>`;
  acceptAllBtn.style.display = 'none';

  try {
    const data = await api('GET', '/merchant-rules/suggestions');
    _ruleSuggestions = data.suggestions || [];

    if (!_ruleSuggestions.length) {
      statusEl.textContent = 'No new suggestions found.';
      listEl.innerHTML = `<span style="color:var(--text-muted);font-size:13px;">
        All common patterns are already covered by your existing rules, or you don't have enough transaction data yet (minimum 3 transactions per pattern).
      </span>`;
      return;
    }

    statusEl.textContent = `${_ruleSuggestions.length} suggestion${_ruleSuggestions.length > 1 ? 's' : ''} found`;
    acceptAllBtn.style.display = '';
    _renderRuleSuggestions();
  } catch (err) {
    statusEl.textContent = `Error: ${err.message}`;
    listEl.innerHTML = '';
  }
}

function _renderRuleSuggestions() {
  const listEl = document.getElementById('rule-suggestions-list');
  if (!listEl) return;
  const visible = _ruleSuggestions.filter(s => !s._dismissed);
  if (!visible.length) {
    listEl.innerHTML = '<span style="color:var(--text-muted);font-size:13px;">All suggestions have been reviewed.</span>';
    document.getElementById('rule-suggest-accept-all').style.display = 'none';
    return;
  }
  listEl.innerHTML = visible.map((s, visIdx) => {
    const realIdx = _ruleSuggestions.indexOf(s);
    const samples = (s.sample_descriptions || []).slice(0, 3).map(d => `<span class="mono" style="font-size:11px;">${esc(d)}</span>`).join('<br>');
    const matchBadgeColor = s.match_type === 'startswith' ? '#3b82f6' : '#8b5cf6';
    const variantNote = s.num_variants > 1 ? ` · ${s.num_variants} variants` : '';
    return `
      <div style="display:flex; gap:12px; align-items:flex-start; padding:10px 12px; background:var(--bg-alt,#f8faff); border-radius:8px; border:1px solid var(--border);">
        <div style="flex:1; min-width:0;">
          <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-bottom:4px;">
            <span style="font-size:11px; font-weight:600; background:${matchBadgeColor}22; color:${matchBadgeColor}; border-radius:4px; padding:2px 6px;">${esc(s.match_type)}</span>
            <span class="mono" style="font-size:13px; font-weight:600;">${esc(s.pattern)}</span>
            <span style="color:var(--text-muted); font-size:12px;">→</span>
            <span style="font-size:13px; font-weight:500;">${esc(s.merchant)}</span>
            <span style="font-size:11px; color:var(--text-muted); background:#e2e8f0; border-radius:10px; padding:1px 8px;">${s.count} tx${variantNote}</span>
          </div>
          <div style="color:var(--text-muted); font-size:11px; line-height:1.6;">${samples}</div>
        </div>
        <div style="display:flex; gap:6px; flex-shrink:0;">
          <button class="btn btn-primary btn-sm" onclick="acceptRuleSuggestion(${realIdx})" title="Create this rule">✓ Accept</button>
          <button class="btn btn-secondary btn-sm" onclick="editRuleSuggestion(${realIdx})" title="Edit before saving">Edit</button>
          <button class="btn btn-secondary btn-sm" style="color:var(--text-muted);" onclick="dismissRuleSuggestion(${realIdx})" title="Dismiss">✗</button>
        </div>
      </div>`;
  }).join('');
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

function dismissRuleSuggestion(idx) {
  if (_ruleSuggestions[idx]) _ruleSuggestions[idx]._dismissed = true;
  _renderRuleSuggestions();
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
  if (!visible.length) {
    listEl.innerHTML = '<span style="color:var(--text-muted);font-size:13px;">All suggestions reviewed.</span>';
    document.getElementById('cat-suggest-accept-all').style.display = 'none';
    return;
  }
  listEl.innerHTML = visible.map(s => {
    const realIdx = _catSuggestions.indexOf(s);
    const confColor = s.confidence === 'high' ? '#16a34a' : '#d97706';
    const jsonMerchant = JSON.stringify(s.merchant).replace(/"/g, '&quot;');
    const jsonCat = JSON.stringify(s.suggested_category).replace(/"/g, '&quot;');
    return `
      <div style="display:flex; align-items:center; gap:10px; padding:7px 10px; background:var(--bg-alt,#f8faff); border-radius:6px; border:1px solid var(--border);">
        <span style="flex:1; font-size:13px;">${esc(s.merchant)}</span>
        <span style="color:var(--text-muted); font-size:12px;">→</span>
        <span style="font-size:13px;">${esc(s.suggested_category)}</span>
        <span style="font-size:11px; font-weight:600; color:${confColor}; background:${confColor}18; border-radius:4px; padding:2px 6px;">${s.confidence}</span>
        <button class="btn btn-primary btn-sm" onclick="acceptMerchantCatSuggestion(${realIdx})" title="Assign this category">✓</button>
        <button class="btn btn-secondary btn-sm" style="color:var(--text-muted);" onclick="dismissMerchantCatSuggestion(${realIdx})" title="Dismiss">✗</button>
      </div>`;
  }).join('');
}

/** Accept a merchant→category suggestion. Operates on _catSuggestions data
 *  (from /merchant-categories/suggestions) and POSTs to /merchant-categories. */
async function acceptMerchantCatSuggestion(idx) {
  const s = _catSuggestions[idx];
  if (!s) return;
  try {
    await api('POST', '/merchant-categories', { merchant: s.merchant, category: s.suggested_category });
    s._dismissed = true;
    toast(`"${s.merchant}" → ${s.suggested_category}`, 'success');
    _renderCategorySuggestions();
    loadUncategorized();
  } catch (err) {
    toast(`Failed: ${err.message}`, 'error');
  }
}

/** Dismiss a merchant→category suggestion. Operates on _catSuggestions data. */
function dismissMerchantCatSuggestion(idx) {
  if (_catSuggestions[idx]) _catSuggestions[idx]._dismissed = true;
  _renderCategorySuggestions();
}

async function acceptAllCategorySuggestions() {
  const visible = _catSuggestions.filter(s => !s._dismissed);
  if (!visible.length) return;
  let ok = 0, fail = 0;
  for (const s of visible) {
    try {
      await api('POST', '/merchant-categories', { merchant: s.merchant, category: s.suggested_category });
      s._dismissed = true;
      ok++;
    } catch (_) { fail++; }
  }
  toast(`${ok} categor${ok !== 1 ? 'ies' : 'y'} assigned${fail ? ` (${fail} failed)` : ''}.`, ok ? 'success' : 'error');
  _renderCategorySuggestions();
  loadUncategorized();
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
  set('dash-prev-spend', _fmt$(data.prev_spend));

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

  const topCat = data.top_categories[0];
  set('dash-top-cat', topCat ? esc(topCat.parent) : '—');

  // Top categories bar chart
  const catList = document.getElementById('dash-cat-list');
  if (catList && data.top_categories.length) {
    const maxAmt = Math.max(...data.top_categories.map(c => c.amount), 1);
    catList.innerHTML = data.top_categories.map(c => {
      const pct = Math.round(c.amount / maxAmt * 100);
      return `<div style="margin-bottom:4px;">
        <div style="display:flex; justify-content:space-between; font-size:13px; margin-bottom:2px;">
          <span>${esc(c.parent)}</span>
          <span style="font-weight:600;">${_fmt$(c.amount)}</span>
        </div>
        <div style="background:var(--border); border-radius:4px; height:6px;">
          <div style="background:var(--primary,#3b82f6); border-radius:4px; height:6px; width:${pct}%;"></div>
        </div>
      </div>`;
    }).join('');
  } else if (catList) {
    catList.innerHTML = '<span style="color:var(--text-muted); font-size:13px;">No spending data for this month.</span>';
  }

  // Budget tracker
  const budgetList = document.getElementById('dash-budget-list');
  if (budgetList) {
    if (data.budgets && data.budgets.length) {
      budgetList.innerHTML = data.budgets.map(b => {
        const pct = Math.min(b.pct || 0, 100);
        const color = pct >= 100 ? '#ef4444' : pct >= 80 ? '#f59e0b' : '#22c55e';
        const label = b.category || b.parent;
        return `<div>
          <div style="display:flex; justify-content:space-between; font-size:12px; margin-bottom:2px;">
            <span>${esc(label)}</span>
            <span>${_fmt$(b.spent)} / ${_fmt$(b.budget)} <span style="color:${color};">(${b.pct ?? 0}%)</span></span>
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

  // Savings goals
  _renderSavingsGoals(data.savings_goals || []);

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

// ── Budget form ────────────────────────────────────────────────

function openBudgetForm() {
  document.getElementById('budget-form').style.display = '';
}
function closeBudgetForm() {
  document.getElementById('budget-form').style.display = 'none';
  ['bf-parent','bf-category','bf-amount'].forEach(id => {
    const el = document.getElementById(id); if (el) el.value = '';
  });
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

async function loadCategoryRules() {
  const tbody = document.getElementById('category-rules-tbody');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted" style="padding:24px">Loading…</td></tr>';
  try {
    const data = await api('GET', '/category-rules');
    if (!data.rules.length) {
      tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted" style="padding:24px">No rules yet. Click "+ Add Rule" or use "Analyze My Data" to create them.</td></tr>';
      return;
    }
    tbody.innerHTML = data.rules.map(r => `<tr>
      <td class="mono" style="font-size:12px;">${esc(r.raw_category)}</td>
      <td>${esc(r.category)}</td>
      <td><span class="badge badge-running" style="font-size:11px;">${esc(r.parent)}</span></td>
      <td>
        <div style="display:flex; gap:6px;">
          <button class="btn btn-secondary btn-sm" onclick="openCatRuleForm(${r.id})">Edit</button>
          <button class="btn btn-danger btn-sm" onclick="deleteCatRule(${r.id})">Delete</button>
        </div>
      </td>
    </tr>`).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="4" class="text-center text-muted">Error: ${esc(err.message)}</td></tr>`;
  }
}

function openCatRuleForm(ruleId) {
  _editingCatRuleId = ruleId;
  const card = document.getElementById('cat-rule-form-card');
  document.getElementById('cat-rule-form-title').textContent = ruleId ? 'Edit Category Rule' : 'Add Category Rule';
  card.style.display = '';
  document.getElementById('crf-status').textContent = '';
  if (!ruleId) {
    ['crf-raw','crf-category'].forEach(id => { const el = document.getElementById(id); if(el) el.value=''; });
    document.getElementById('crf-parent').value = '';
    return;
  }
  api('GET', '/category-rules').then(data => {
    const rule = data.rules.find(r => r.id === ruleId);
    if (!rule) return;
    document.getElementById('crf-raw').value      = rule.raw_category;
    document.getElementById('crf-category').value = rule.category;
    document.getElementById('crf-parent').value   = rule.parent;
  });
}

function closeCatRuleForm() {
  _editingCatRuleId = null;
  document.getElementById('cat-rule-form-card').style.display = 'none';
}

async function saveCatRule() {
  const raw      = document.getElementById('crf-raw').value.trim();
  const category = document.getElementById('crf-category').value.trim();
  const parent   = document.getElementById('crf-parent').value;
  if (!raw || !category || !parent) {
    toast('All fields are required.', 'error'); return;
  }
  const body = { raw_category: raw, category, parent };
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
        <button class="btn btn-secondary btn-sm" style="color:var(--text-muted);" onclick="dismissCatSuggestion(${realIdx})">✗</button>
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

/** Dismiss a raw-category→normalized mapping suggestion. Operates on _catSuggestionsData. */
function dismissCatSuggestion(idx) {
  if (_catSuggestionsData[idx]) _catSuggestionsData[idx]._dismissed = true;
  _renderCatSuggestions();
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

function _presetDates(preset) {
  const now = new Date();
  let from, to;
  const pad = n => String(n).padStart(2,'0');
  const fmt = d => `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
  switch (preset) {
    case 'this_month': {
      from = new Date(now.getFullYear(), now.getMonth(), 1);
      to   = new Date(now.getFullYear(), now.getMonth()+1, 0);
      break;
    }
    case 'last_month': {
      from = new Date(now.getFullYear(), now.getMonth()-1, 1);
      to   = new Date(now.getFullYear(), now.getMonth(), 0);
      break;
    }
    case '3months': {
      from = new Date(now.getFullYear(), now.getMonth()-2, 1);
      to   = new Date(now.getFullYear(), now.getMonth()+1, 0);
      break;
    }
    case 'ytd': {
      from = new Date(now.getFullYear(), 0, 1);
      to   = now;
      break;
    }
    default: { from = null; to = null; }
  }
  return { from: from ? fmt(from) : '', to: to ? fmt(to) : '' };
}

function setDatePreset(tab, preset) {
  const { from, to } = _presetDates(preset);
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
    html += s.top_categories.map(c => {
      const pct = Math.round(c.amount / maxAmt * 100);
      const delta = c.delta_pct != null
        ? ` <span style="font-size:11px; color:${c.delta_pct >= 0 ? '#ef4444' : '#22c55e'};">${c.delta_pct >= 0 ? '▲' : '▼'}${Math.abs(c.delta_pct)}%</span>`
        : '';
      return `<div style="margin-bottom:6px;">
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
    custom.style.display = sel.value === 'custom' ? '' : 'none';
  }
  if (sel && sel.value !== 'custom') loadCashFlow();
}

async function loadCashFlow() {
  const period = document.getElementById('cf-period')?.value || 'last_3_months';
  const transfers = document.getElementById('cf-transfers')?.checked || false;

  let url = `/cashflow/summary?period=${period}&include_transfers=${transfers}`;
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

function _renderCfCategories(cats) {
  const el = document.getElementById('cf-cat-list');
  if (!el) return;

  if (!cats.length) {
    el.innerHTML = '<span style="color:var(--text-muted); font-size:13px;">No spending data.</span>';
    return;
  }

  const maxAmt = Math.max(...cats.map(c => c.amount), 1);
  el.innerHTML = cats.map(c => {
    const pct = Math.round(c.amount / maxAmt * 100);
    return `<div style="margin-bottom:6px;">
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
