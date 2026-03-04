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
 * Build and manage an Import Source radio-button dropdown widget.
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
  let _selected = 'all';   // run_id or 'all'
  let _open     = false;

  // ── DOM structure ─────────────────────────────────────────
  // [▼ Display All] trigger button
  const trigger = document.createElement('button');
  trigger.type      = 'button';
  trigger.className = 'source-trigger';
  trigger.setAttribute('aria-haspopup', 'listbox');
  trigger.setAttribute('aria-expanded', 'false');

  // Hidden panel with radio inputs
  const panel = document.createElement('div');
  panel.className = 'source-panel';
  panel.setAttribute('role', 'listbox');
  panel.style.display = 'none';

  container.appendChild(trigger);
  container.appendChild(panel);

  // ── Helpers ───────────────────────────────────────────────
  function _updateTrigger(label) {
    trigger.textContent = '';
    const arrow = document.createElement('span');
    arrow.className  = 'source-arrow';
    arrow.textContent = _open ? '▲' : '▼';
    trigger.appendChild(document.createTextNode(label + ' '));
    trigger.appendChild(arrow);
    trigger.setAttribute('aria-expanded', String(_open));
  }

  function _openPanel() {
    _open = true;
    panel.style.display = 'block';
    _updateTrigger(_labelFor(_selected));
  }

  function _closePanel() {
    _open = false;
    panel.style.display = 'none';
    _updateTrigger(_labelFor(_selected));
  }

  function _labelFor(val) {
    if (val === 'all') return 'All Imports';
    const radio = panel.querySelector(`input[value="${CSS.escape(val)}"]`);
    return radio ? radio.dataset.label : val;
  }

  function _selectValue(val) {
    _selected = val;
    // Sync radio checked state
    panel.querySelectorAll('input[type="radio"]').forEach(r => {
      r.checked = (r.value === val);
    });
    _closePanel();
    onChange(val);
  }

  // ── Render radio list ─────────────────────────────────────
  function _renderOptions(sources) {
    panel.innerHTML = '';

    // "Display All" is always the first and always present
    const allOpt = _makeRadio('all', 'All Imports', '', 0);
    panel.appendChild(allOpt);

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

    // Track labels to detect duplicates — append date when label repeats
    const labelCounts = {};
    sources.forEach(s => { labelCounts[s.label] = (labelCounts[s.label] || 0) + 1; });

    sources.forEach(src => {
      const dateStr  = src.date ? src.date.slice(0, 10) : '';
      const datePart = dateStr
        ? new Date(dateStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: '2-digit' })
        : '';
      // Disambiguate duplicate labels by appending date
      const displayLabel = labelCounts[src.label] > 1 && datePart
        ? `${src.label} (${datePart})`
        : src.label;

      panel.appendChild(_makeRadio(src.id, displayLabel, datePart, src.count));
    });

    // Restore previously-selected value if it still exists, otherwise reset to 'all'
    const validValues = new Set(['all', ...sources.map(s => s.id)]);
    if (!validValues.has(_selected)) _selected = 'all';
    panel.querySelectorAll('input[type="radio"]').forEach(r => {
      r.checked = (r.value === _selected);
    });
    _updateTrigger(_labelFor(_selected));
  }

  function _makeRadio(val, label, dateStr, count) {
    const row   = document.createElement('label');
    row.className = 'source-option';

    const radio = document.createElement('input');
    radio.type          = 'radio';
    radio.name          = `src-${containerId}`;
    radio.value         = val;
    radio.dataset.label = label;
    radio.checked       = (val === _selected);
    radio.addEventListener('change', () => { if (radio.checked) _selectValue(val); });

    const text = document.createElement('span');
    text.className = 'source-option-label';
    text.textContent = label;

    row.appendChild(radio);
    row.appendChild(text);

    if (count > 0) {
      const cnt = document.createElement('span');
      cnt.className   = 'source-option-count';
      cnt.textContent = `${count} txns`;
      row.appendChild(cnt);
    }
    if (dateStr) {
      const dt = document.createElement('span');
      dt.className   = 'source-option-date';
      dt.textContent = dateStr;
      row.appendChild(dt);
    }

    return row;
  }

  // ── Toggle on trigger click ───────────────────────────────
  trigger.addEventListener('click', e => {
    e.stopPropagation();
    _open ? _closePanel() : _openPanel();
  });

  // ── Close on outside click ───────────────────────────────
  document.addEventListener('click', e => {
    if (_open && !container.contains(e.target)) _closePanel();
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
