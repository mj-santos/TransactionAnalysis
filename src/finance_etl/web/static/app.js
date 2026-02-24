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

  const titles = { import: 'Import Transactions', history: 'Import History', reports: 'Analytics Reports', settings: 'Settings & Logs' };
  document.getElementById('topbar-title').textContent = titles[page] || page;

  if (page === 'history') loadHistory();
  if (page === 'reports') loadReports();
  if (page === 'settings') loadSettings();
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
    checkImportReady();
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
  checkImportReady();
}

// ── Mappings ────────────────────────────────────────────────
async function loadMappings() {
  const sel = document.getElementById('mapping-select');
  try {
    const data = await api('GET', '/mappings');
    sel.innerHTML = '<option value="">— Select a bank mapping —</option>';
    data.mappings.forEach(m => {
      const opt = document.createElement('option');
      opt.value = m.path;
      opt.textContent = m.label + (m.example ? ' (example)' : '');
      sel.appendChild(opt);
    });
  } catch {
    sel.innerHTML = '<option value="">Failed to load mappings</option>';
  }
  sel.addEventListener('change', checkImportReady);
}

// ── Import button guard ──────────────────────────────────────
function checkImportReady() {
  const hasFiles   = state.uploadedFiles.some(f => {
    const chip = document.getElementById(f.chipId);
    return chip && chip.classList.contains('done');
  });
  const hasMapping = !!document.getElementById('mapping-select').value;
  const btn  = document.getElementById('import-btn');
  const hint = document.getElementById('import-hint');
  btn.disabled = !(hasFiles && hasMapping);
  if (!hasFiles && !hasMapping) hint.textContent = 'Upload a file and select a mapping to continue.';
  else if (!hasFiles)           hint.textContent = 'Upload a CSV file to continue.';
  else if (!hasMapping)         hint.textContent = 'Select a bank mapping to continue.';
  else                          hint.textContent = '';
}

// ── Start import ─────────────────────────────────────────────
async function startImport() {
  const inputs      = state.uploadedFiles.filter(f => {
    const chip = document.getElementById(f.chipId);
    return chip && chip.classList.contains('done');
  }).map(f => f.path);

  const mappingPath = document.getElementById('mapping-select').value;
  const previewOnly = document.getElementById('preview-toggle').checked;

  if (!inputs.length || !mappingPath) return;

  document.getElementById('import-btn').disabled = true;
  setRunStatus('pending', null, null, 'Queuing…');

  try {
    const data = await api('POST', '/runs', { inputs, mapping_path: mappingPath, preview_only: previewOnly });
    state.currentRunId = data.run_id;
    setRunStatus('pending', data.run_id, null, 'Queued — starting pipeline…');
    pollRun(data.run_id, onRunComplete);
  } catch (err) {
    setRunStatus('failed', null, null, `Error: ${err.message}`);
    toast(err.message, 'error');
    document.getElementById('import-btn').disabled = false;
  }
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
    document.getElementById('import-btn').disabled = false;
  } else if (run.status === 'failed') {
    toast(`Import failed: ${run.error || '(unknown error)'}`, 'error');
    document.getElementById('import-btn').disabled = false;
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
    '<tr><td colspan="6" class="text-center text-muted" style="padding:20px">Loading…</td></tr>';

  try {
    const data = await api('GET', `/runs/${runId}/preview`);
    renderPreviewRows('preview-tbody', data.rows);
    document.getElementById('preview-meta').textContent =
      `${data.count} row(s)${data.truncated ? ' (truncated)' : ''}`;
  } catch (err) {
    document.getElementById('preview-tbody').innerHTML =
      `<tr><td colspan="6" class="text-center text-muted">Error: ${esc(err.message)}</td></tr>`;
  }
}

function renderPreviewRows(tbodyId, rows) {
  const tbody = document.getElementById(tbodyId);
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted" style="padding:20px">No rows found.</td></tr>';
    return;
  }
  tbody.innerHTML = rows.map(r => `
    <tr>
      <td class="mono text-muted">${r.source_row}</td>
      <td>${esc(r.transaction_date_raw || '')}</td>
      <td style="max-width:280px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap"
          title="${esc(r.description_raw || '')}">${esc(r.description_raw || '')}</td>
      <td class="mono text-right">${esc(r.amount_raw || '')}</td>
      <td>${esc(r.currency_raw || '')}</td>
      <td class="text-muted">${esc(r.account_name || '')}</td>
    </tr>`).join('');
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
    renderPreviewRows('history-preview-tbody', data.rows);
    document.getElementById('history-preview-meta').textContent =
      `${data.count} row(s)${data.truncated ? ' (truncated to 200)' : ''}`;
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted">Error: ${esc(err.message)}</td></tr>`;
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
  area.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

  try {
    const data = await api('GET', `/charts/${name}`);
    if (!data.rows.length) {
      document.getElementById('chart-body').innerHTML =
        '<tr><td class="text-center text-muted" style="padding:20px">No data.</td></tr>';
      return;
    }
    const cols = Object.keys(data.rows[0]);
    document.getElementById('chart-head').innerHTML = cols.map(c => `<th>${esc(c)}</th>`).join('');
    document.getElementById('chart-body').innerHTML = data.rows.map(row =>
      `<tr>${cols.map(c => `<td>${esc(String(row[c] ?? ''))}</td>`).join('')}</tr>`
    ).join('');
  } catch (err) {
    document.getElementById('chart-body').innerHTML =
      `<tr><td class="text-center text-muted">Error: ${esc(err.message)}</td></tr>`;
  }
}

function closeChart() {
  document.getElementById('chart-area').style.display = 'none';
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
loadMappings();
loadSettings();
