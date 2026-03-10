/* =========================================================
   table_controls.js — shared Import Source radio-dropdown
   for Credit Cards & Bank Transactions tabs.

   Usage:
     const ctrl = makeSourceDropdown('cc-source-ctrl', 'credit_card', onChange);
     await ctrl.load();   // fetch /transactions/sources and populate
     ctrl.reset();        // set selection back to 'all'
     ctrl.value();        // returns selected run_id or 'all'
   ========================================================= */

'use strict';

/**
 * Build and manage an Import Source dropdown widget.
 * High-contrast solid-background panel, keyboard navigable.
 *
 * @param {string}   containerId  ID of the <div> that receives the widget
 * @param {string}   type         'credit_card' or 'bank' (Feature 1: never mixed)
 * @param {Function} onChange     Callback fired when the selection changes
 * @returns {{ load, reset, value }}
 */
function makeSourceDropdown(containerId, type, onChange) {
  const container = document.getElementById(containerId);
  if (!container) {
    console.warn(`[SourceDropdown] container #${containerId} not found`);
    return { load: async () => {}, reset: () => {}, value: () => 'all' };
  }

  // ── Internal state ────────────────────────────────────────
  let _selected   = 'all';   // run_id or 'all'
  let _open       = false;
  let _focusIdx   = -1;      // keyboard-focused option index (-1 = none)
  let _optionEls  = [];      // ordered list of .source-option elements

  // ── DOM structure ─────────────────────────────────────────
  const trigger = document.createElement('button');
  trigger.type      = 'button';
  trigger.className = 'source-trigger';
  trigger.setAttribute('aria-haspopup', 'listbox');
  trigger.setAttribute('aria-expanded', 'false');

  const panel = document.createElement('div');
  panel.className = 'source-panel';
  panel.setAttribute('role', 'listbox');
  panel.style.display = 'none';

  container.appendChild(trigger);
  container.appendChild(panel);

  // ── Helpers ───────────────────────────────────────────────
  function _updateTrigger(label) {
    trigger.innerHTML = '';
    trigger.appendChild(document.createTextNode(label));
    const arrow = document.createElement('span');
    arrow.className   = 'source-arrow';
    arrow.textContent = '▼';
    trigger.appendChild(arrow);
    trigger.setAttribute('aria-expanded', String(_open));
  }

  function _openPanel() {
    _open = true;
    panel.style.display = 'block';
    _focusIdx = _optionEls.findIndex(el => el.dataset.value === _selected);
    _applyFocus(_focusIdx);
    _updateTrigger(_labelFor(_selected));
  }

  function _closePanel() {
    _open = false;
    panel.style.display = 'none';
    _focusIdx = -1;
    _optionEls.forEach(el => el.classList.remove('focused'));
    _updateTrigger(_labelFor(_selected));
    trigger.focus();
  }

  function _labelFor(val) {
    const opt = _optionEls.find(el => el.dataset.value === val);
    return opt ? opt.dataset.label : 'All Imports';
  }

  function _applyFocus(idx) {
    _optionEls.forEach((el, i) => el.classList.toggle('focused', i === idx));
    if (idx >= 0 && idx < _optionEls.length) {
      _optionEls[idx].scrollIntoView({ block: 'nearest' });
    }
  }

  function _selectValue(val) {
    _selected = val;
    panel.querySelectorAll('input[type="radio"]').forEach(r => {
      r.checked = (r.value === val);
    });
    _closePanel();
    onChange(val);
  }

  // ── Render radio list ─────────────────────────────────────
  function _renderOptions(sources) {
    panel.innerHTML = '';
    _optionEls = [];

    const allOpt = _makeOption('all', 'All Imports', '', 0);
    panel.appendChild(allOpt);
    _optionEls.push(allOpt);

    if (!sources.length) {
      const empty = document.createElement('div');
      empty.className   = 'source-empty';
      empty.textContent = 'No imports found';
      panel.appendChild(empty);
      trigger.disabled = true;
      _updateTrigger('No imports found');
      return;
    }

    trigger.disabled = false;

    const labelCounts = {};
    sources.forEach(s => { labelCounts[s.label] = (labelCounts[s.label] || 0) + 1; });

    sources.forEach(src => {
      const dateStr  = src.date ? src.date.slice(0, 10) : '';
      const datePart = dateStr
        ? new Date(dateStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: '2-digit' })
        : '';
      const displayLabel = labelCounts[src.label] > 1 && datePart
        ? `${src.label} (${datePart})`
        : src.label;

      const opt = _makeOption(src.id, displayLabel, datePart, src.count);
      panel.appendChild(opt);
      _optionEls.push(opt);
    });

    const validValues = new Set(['all', ...sources.map(s => s.id)]);
    if (!validValues.has(_selected)) _selected = 'all';
    panel.querySelectorAll('input[type="radio"]').forEach(r => {
      r.checked = (r.value === _selected);
    });
    _updateTrigger(_labelFor(_selected));
  }

  function _makeOption(val, label, dateStr, count) {
    const row = document.createElement('label');
    row.className      = 'source-option';
    row.dataset.value  = val;
    row.dataset.label  = label;
    row.setAttribute('role', 'option');

    const radio = document.createElement('input');
    radio.type    = 'radio';
    radio.name    = `src-${containerId}`;
    radio.value   = val;
    radio.checked = (val === _selected);
    radio.addEventListener('change', () => { if (radio.checked) _selectValue(val); });

    // Content wrapper: bold label + small muted meta row
    const content = document.createElement('span');
    content.className = 'source-option-content';

    const labelEl = document.createElement('span');
    labelEl.className   = 'source-option-label';
    labelEl.textContent = label;
    content.appendChild(labelEl);

    if (count > 0 || dateStr) {
      const meta = document.createElement('span');
      meta.className = 'source-option-meta';
      if (count > 0) {
        const cnt = document.createElement('span');
        cnt.className   = 'source-option-count';
        cnt.textContent = `${count} txns`;
        meta.appendChild(cnt);
      }
      if (dateStr) {
        const dt = document.createElement('span');
        dt.className   = 'source-option-date';
        dt.textContent = dateStr;
        meta.appendChild(dt);
      }
      content.appendChild(meta);
    }

    row.appendChild(radio);
    row.appendChild(content);
    return row;
  }

  // ── Toggle on trigger click ───────────────────────────────
  trigger.addEventListener('click', e => {
    e.stopPropagation();
    _open ? _closePanel() : _openPanel();
  });

  // ── Keyboard navigation ───────────────────────────────────
  trigger.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      if (!_open) _openPanel();
      else {
        _focusIdx = Math.min(_focusIdx + 1, _optionEls.length - 1);
        _applyFocus(_focusIdx);
      }
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (_open) { _focusIdx = Math.max(_focusIdx - 1, 0); _applyFocus(_focusIdx); }
    } else if (e.key === 'Escape') {
      _closePanel();
    }
  });

  panel.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      _focusIdx = Math.min(_focusIdx + 1, _optionEls.length - 1);
      _applyFocus(_focusIdx);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      _focusIdx = Math.max(_focusIdx - 1, 0);
      _applyFocus(_focusIdx);
    } else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      if (_focusIdx >= 0 && _focusIdx < _optionEls.length) {
        _selectValue(_optionEls[_focusIdx].dataset.value);
      }
    } else if (e.key === 'Escape') {
      _closePanel();
    }
  });

  // ── Close on outside click or Escape ─────────────────────
  document.addEventListener('click', e => {
    if (_open && !container.contains(e.target)) _closePanel();
  });

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && _open) _closePanel();
  });

  // ── Public API ────────────────────────────────────────────

  /**
   * Fetch /transactions/sources?type=<type> and populate the dropdown.
   * Layer 1 bug is now fixed — the SQL always has a valid WHERE clause.
   */
  async function load() {
    const tabName = type === 'credit_card' ? 'CreditCards' : 'BankTransactions';
    try {
      const data    = await api('GET', `/transactions/sources?type=${encodeURIComponent(type)}`);
      const sources = data.sources || [];
      _renderOptions(sources);
      console.log(`[${tabName}] source dropdown loaded ${sources.length} source(s)`);
    } catch (err) {
      console.warn(`[${tabName}] failed to load sources:`, err.message);
      _renderOptions([]);
    }
  }

  /** Reset selection to "All Imports" without re-fetching. */
  function reset() {
    _selected = 'all';
    panel.querySelectorAll('input[type="radio"]').forEach(r => {
      r.checked = (r.value === 'all');
    });
    _updateTrigger('All Imports');
  }

  /** Return the currently selected run_id, or 'all'. */
  function value() { return _selected; }

  // Initialise trigger label
  _updateTrigger('All Imports');

  return { load, reset, value };
}

/* =========================================================
   renderTxnTotals — pinned tfoot totals row for Credit Cards
   and Bank Transactions tabs.

   Renders server-computed aggregates from GET /transactions/totals
   into a visually distinct <tfoot> row with labeled value cells.

   Credit card layout (subtype model):
     | TOTALS (spans) | Row Count | Spending | Payments | Adjustments | Card Balance |
     Followed by inline warning banners for conflict rows and legacy (NULL subtype) rows.

   Bank layout:
     | TOTALS (spans) | Row Count | Total Income | Total Outflow | Net |

   @param {HTMLElement} tfootEl  The <tfoot> element to render into
   @param {object}      totals   Response from GET /transactions/totals
   @param {string}      type     'credit_card' | 'bank'
   @param {number}      numCols  Column count of the main data table (for colspan)
   @param {HTMLElement} [warnEl] Optional element to receive legacy/conflict warning HTML
   ========================================================= */
function renderTxnTotals(tfootEl, totals, type, numCols, warnEl) {
  if (!tfootEl) return;
  if (!totals || !totals.row_count) {
    tfootEl.innerHTML = '';
    if (warnEl) warnEl.innerHTML = '';
    return;
  }

  const f2 = v => Number(v || 0).toFixed(2);
  const fN = v => Number(v || 0).toLocaleString();

  let cells;
  if (type === 'credit_card') {
    // Subtype model — spending / payments / adjustments / card balance
    const balance = Number(totals.cc_balance || 0);
    const balanceColor = balance > 0 ? 'var(--danger)' : balance < 0 ? '#16a34a' : 'inherit';
    cells = [
      { label: 'Row Count',    value: fN(totals.row_count) },
      { label: 'Spending',     value: f2(totals.cc_spending) },
      { label: 'Payments',     value: f2(totals.cc_payments) },
      { label: 'Adjustments',  value: f2(totals.cc_adjustments) },
      {
        label: 'Card Balance',
        value: `<span style="color:${balanceColor}">${f2(balance)}</span>`,
        raw: true,
      },
    ];
  } else {
    cells = [
      { label: 'Row Count',    value: fN(totals.row_count) },
      { label: 'Total Income', value: f2(totals.total_income) },
      { label: 'Total Outflow',value: f2(totals.total_outflow) },
      { label: 'Net',          value: f2(totals.net_amount) },
    ];
  }

  const labelSpan = Math.max(1, numCols - cells.length);
  const cellHtml = cells.map(c =>
    `<td class="mono text-right" style="padding:6px 10px; white-space:nowrap; vertical-align:middle;">` +
    `<span style="color:var(--text-muted); font-size:10px; display:block; line-height:1.3;">${c.label}</span>` +
    `${c.raw ? c.value : c.value}</td>`
  ).join('');

  tfootEl.innerHTML =
    `<tr style="font-weight:600; border-top:2px solid var(--border); background:var(--surface);">` +
    `<td colspan="${labelSpan}" style="padding:6px 10px; font-size:11px; color:var(--text-muted); vertical-align:middle;">TOTALS</td>` +
    `${cellHtml}` +
    `</tr>`;

  // Emit warning banners for CC legacy rows and conflict rows
  if (warnEl && type === 'credit_card') {
    const parts = [];
    if ((totals.cc_conflict_count || 0) > 0) {
      parts.push(
        `<div class="auto-detect-banner nomatch" style="background:#fef3c7;border-color:#f59e0b;color:#92400e;margin-bottom:6px;">` +
        `<span style="font-size:18px">⚠️</span>` +
        `<div style="flex:1"><strong>${totals.cc_conflict_count} conflict row(s)</strong> — both cc_charge and ` +
        `cc_payment populated on the same row. Re-import and resolve before they contribute to balance.</div></div>`
      );
    }
    if ((totals.cc_legacy_count || 0) > 0) {
      parts.push(
        `<div class="auto-detect-banner nomatch" style="background:#fef3c7;border-color:#f59e0b;color:#92400e;margin-bottom:6px;">` +
        `<span style="font-size:18px">⚠️</span>` +
        `<div style="flex:1"><strong>${totals.cc_legacy_count} legacy credit card transaction(s)</strong> have no subtype. ` +
        `Re-import those statements to enable balance tracking.</div></div>`
      );
    }
    warnEl.innerHTML = parts.join('');
  }
}
