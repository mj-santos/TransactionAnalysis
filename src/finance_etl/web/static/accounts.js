// ── Accounts & Liabilities Module ─────────────────────────────────────
// Phase 1: Manage Accounts sub-view, Add/Edit Account, Payment Source Tags
// Phase 2: Overview sub-view, Update Balances grid, KPI cards, stale detection

let _accountsCache = [];
let _currentAccountsSubtab = 'manage';

// Tab data cache — prevents redundant API calls on rapid tab switching.
// Each entry: { loadedAt: Date.now() }. Stale after 60 seconds.
const _tabCache = {};
const _TAB_TTL_MS = 60_000;
function _tabIsStale(tab) {
  const t = _tabCache[tab];
  return !t || (Date.now() - t.loadedAt) > _TAB_TTL_MS;
}
function _markTabLoaded(tab) { _tabCache[tab] = { loadedAt: Date.now() }; }
function _invalidateTabCache(tab) { delete _tabCache[tab]; }

// ── Load Accounts ────────────────────────────────────────────────────
async function loadAccounts() {
  try {
    const res = await api('GET', '/accounts/');
    _accountsCache = res.accounts || [];
    _renderAccountsTable(_accountsCache);
    _populateManageFilters(_accountsCache);
    _loadPaymentSourceTags();
    _populateTagAccountDropdown(_accountsCache);
    // Also load overview data if that tab is active
    if (_currentAccountsSubtab === 'overview') {
      _loadOverviewData();
    }
  } catch (e) {
    toast('Failed to load accounts: ' + e.message, 'error');
  }
}

function _renderAccountsTable(accounts) {
  const tbody = document.getElementById('accounts-table-body');
  // Reset select-all checkbox
  const selectAll = document.getElementById('accounts-select-all');
  if (selectAll) selectAll.checked = false;
  _updateAcctBulkBar();

  if (!accounts.length) {
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; padding:32px; color:var(--text-muted);">No accounts yet. Click "+ Add New Account" to get started.</td></tr>';
    return;
  }
  tbody.innerHTML = accounts.map(a => {
    const bal = a.balance != null ? parseFloat(a.balance).toLocaleString('en-US', {style:'currency', currency:'USD'}) : '$0.00';
    const typeLabel = _typeLabel(a);
    const statusBadge = _statusBadge(a.status || 'active');
    const updatedAt = a.updated_at ? new Date(a.updated_at).toLocaleDateString() : '-';
    const menuId = `acct-menu-${a.id}`;
    return `<tr data-account-id="${a.id}">
      <td><input type="checkbox" class="acct-select-cb" data-account-id="${a.id}" onchange="_updateAcctBulkBar()" /></td>
      <td><strong>${esc(a.name)}</strong>${a.last_four ? ' <span style="color:var(--text-muted);">(' + esc(a.last_four) + ')</span>' : ''}</td>
      <td>${esc(a.institution || '-')}</td>
      <td>${typeLabel}</td>
      <td style="text-align:right; font-variant-numeric:tabular-nums;">${bal}</td>
      <td>${statusBadge}</td>
      <td style="color:var(--text-muted); font-size:13px;">${updatedAt}</td>
      <td style="position:relative; white-space:nowrap;">
        <button class="btn btn-secondary btn-sm" onclick="openEditAccount(${a.id})">Edit</button>
        <button class="btn btn-secondary btn-sm" style="padding:2px 8px; margin-left:4px; font-size:14px; line-height:1;"
          onclick="event.stopPropagation(); _toggleAcctMenu('${menuId}')">&#x22EF;</button>
        <div id="${menuId}" style="display:none; position:absolute; right:0; top:calc(100% - 2px); z-index:50;
          background:var(--card-bg,#fff); border:1px solid var(--border); border-radius:6px; box-shadow:0 4px 12px rgba(0,0,0,.12);
          min-width:130px; overflow:hidden;">
          ${a.status !== 'closed' ? `<button style="display:block; width:100%; text-align:left; padding:8px 14px; font-size:12px; border:none; background:none; cursor:pointer; color:var(--text);"
            onmouseover="this.style.background='var(--bg-alt)'" onmouseout="this.style.background='none'"
            onclick="_toggleAcctMenu('${menuId}'); closeAccount(${a.id})">Close Account</button>` : ''}
          <button style="display:block; width:100%; text-align:left; padding:8px 14px; font-size:12px; border:none; background:none; cursor:pointer; color:var(--danger);"
            onmouseover="this.style.background='var(--bg-alt)'" onmouseout="this.style.background='none'"
            onclick="_toggleAcctMenu('${menuId}'); deleteAccount(${a.id})">Delete</button>
        </div>
      </td>
    </tr>`;
  }).join('');
}

function _toggleAcctMenu(menuId) {
  document.querySelectorAll('[id^="acct-menu-"]').forEach(el => {
    if (el.id !== menuId) el.style.display = 'none';
  });
  const menu = document.getElementById(menuId);
  if (menu) menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
}

document.addEventListener('click', e => {
  if (!e.target.closest('[id^="acct-menu-"]') && !e.target.closest('button')) {
    document.querySelectorAll('[id^="acct-menu-"]').forEach(el => el.style.display = 'none');
  }
});

function _typeLabel(a) {
  const labels = {
    credit_card: 'Credit Card', mortgage: 'Mortgage', auto_loan: 'Auto Loan',
    student_loan: 'Student Loan', utility: 'Utility', personal_debt: 'Personal Debt',
    other: 'Other', checking: 'Checking', savings: 'Savings',
    investment: 'Investment', digital_wallet: 'Digital Wallet',
  };
  const subtype = a.account_class === 'asset' ? a.asset_type : a.liability_type;
  const label = labels[subtype] || a.acct_type || 'Unknown';
  const icon = a.account_class === 'asset' ? '🟢' : '🔴';
  return `${icon} ${label}`;
}

function _statusBadge(status) {
  const colors = {active: '#22c55e', closed: '#6b7280', paid_off: '#3b82f6', frozen: '#f59e0b'};
  const color = colors[status] || '#6b7280';
  return `<span style="display:inline-block; padding:2px 8px; border-radius:12px; font-size:11px; font-weight:600; background:${color}20; color:${color};">${status}</span>`;
}

// ── Search / Filter ──────────────────────────────────────────────────

// Shared helper: toggle clear button and count badge for a search bar
function _acctSearchUI(inputId, clearId, countId, shown, total) {
  const q = (document.getElementById(inputId)?.value || '').trim();
  const clearBtn = document.getElementById(clearId);
  const countEl = document.getElementById(countId);
  if (clearBtn) clearBtn.style.display = q ? '' : 'none';
  if (countEl) countEl.textContent = q ? `${shown} of ${total}` : '';
}

// ── Manage Accounts filters ──
const _TYPE_LABELS = {
  credit_card: 'Credit Card', mortgage: 'Mortgage', auto_loan: 'Auto Loan',
  student_loan: 'Student Loan', utility: 'Utility', personal_debt: 'Personal Debt',
  other: 'Other', checking: 'Checking', savings: 'Savings',
  investment: 'Investment', digital_wallet: 'Digital Wallet',
};

function _populateManageFilters(accounts) {
  const typeSet = new Set();
  const instSet = new Set();
  for (const a of accounts) {
    const subtype = a.account_class === 'asset' ? a.asset_type : a.liability_type;
    if (subtype) typeSet.add(subtype);
    if (a.institution) instSet.add(a.institution);
  }
  const typeSel = document.getElementById('manage-acct-type-filter');
  const instSel = document.getElementById('manage-acct-institution-filter');
  if (!typeSel || !instSel) return;
  const curType = typeSel.value;
  const curInst = instSel.value;
  typeSel.innerHTML = '<option value="">All Types</option>' +
    [...typeSet].sort().map(t => `<option value="${t}">${_TYPE_LABELS[t] || t}</option>`).join('');
  instSel.innerHTML = '<option value="">All Institutions</option>' +
    [...instSet].sort().map(i => `<option value="${esc(i)}">${esc(i)}</option>`).join('');
  typeSel.value = curType;
  instSel.value = curInst;
}

function _clearManageFilters() {
  const search = document.getElementById('manage-acct-search');
  const typeSel = document.getElementById('manage-acct-type-filter');
  const instSel = document.getElementById('manage-acct-institution-filter');
  if (search) search.value = '';
  if (typeSel) typeSel.value = '';
  if (instSel) instSel.value = '';
  filterManageAccounts();
}

function filterManageAccounts() {
  const query = (document.getElementById('manage-acct-search')?.value || '').toLowerCase();
  const typeFilter = document.getElementById('manage-acct-type-filter')?.value || '';
  const instFilter = document.getElementById('manage-acct-institution-filter')?.value || '';
  const hasFilter = query || typeFilter || instFilter;

  if (!hasFilter) {
    _renderAccountsTable(_accountsCache);
    _acctSearchUI('manage-acct-search', 'manage-acct-search-clear', 'manage-acct-search-count', 0, 0);
    return;
  }
  const filtered = _accountsCache.filter(a => {
    const subtype = a.account_class === 'asset' ? a.asset_type : a.liability_type;
    if (typeFilter && subtype !== typeFilter) return false;
    if (instFilter && a.institution !== instFilter) return false;
    if (query) {
      const haystack = [
        a.name, a.institution, a.last_four, a.account_code,
        a.status, a.acct_type, subtype, a.account_class,
      ].filter(Boolean).join(' ').toLowerCase();
      if (!haystack.includes(query)) return false;
    }
    return true;
  });
  _renderAccountsTable(filtered);
  _acctSearchUI('manage-acct-search', 'manage-acct-search-clear', 'manage-acct-search-count', filtered.length, _accountsCache.length);
}

// ── Overview search (DOM-based row visibility) ──
function filterOverviewAccounts() {
  const query = (document.getElementById('overview-search')?.value || '').toLowerCase();
  const tables = ['overview-liabilities-body', 'overview-assets-body'];
  let shown = 0, total = 0;
  for (const tbodyId of tables) {
    const tbody = document.getElementById(tbodyId);
    if (!tbody) continue;
    const rows = tbody.querySelectorAll('tr');
    for (const row of rows) {
      const text = row.textContent.toLowerCase();
      total++;
      if (!query || text.includes(query)) {
        row.style.display = '';
        shown++;
      } else {
        row.style.display = 'none';
      }
    }
  }
  _acctSearchUI('overview-search', 'overview-search-clear', 'overview-search-count', shown, total);
}

// ── Payment Planner search (DOM-based row visibility) ──
function filterPlannerRows() {
  const query = (document.getElementById('planner-search')?.value || '').toLowerCase();
  const tables = ['planner-open-cycles-body', 'planner-assignments-body', 'planner-payments-body'];
  let shown = 0, total = 0;
  for (const tbodyId of tables) {
    const tbody = document.getElementById(tbodyId);
    if (!tbody) continue;
    const rows = tbody.querySelectorAll('tr');
    for (const row of rows) {
      const text = row.textContent.toLowerCase();
      total++;
      if (!query || text.includes(query)) {
        row.style.display = '';
        shown++;
      } else {
        row.style.display = 'none';
      }
    }
  }
  _acctSearchUI('planner-search', 'planner-search-clear', 'planner-search-count', shown, total);
}

// ── History & Trends search (DOM-based row visibility) ──
function filterTrendsRows() {
  const query = (document.getElementById('trends-search')?.value || '').toLowerCase();
  const tables = ['trends-interest-body', 'trends-payoff-body'];
  let shown = 0, total = 0;
  for (const tbodyId of tables) {
    const tbody = document.getElementById(tbodyId);
    if (!tbody) continue;
    const rows = tbody.querySelectorAll('tr');
    for (const row of rows) {
      const text = row.textContent.toLowerCase();
      total++;
      if (!query || text.includes(query)) {
        row.style.display = '';
        shown++;
      } else {
        row.style.display = 'none';
      }
    }
  }
  _acctSearchUI('trends-search', 'trends-search-clear', 'trends-search-count', shown, total);
}

// ── Sub-tab switching ────────────────────────────────────────────────
function switchAccountsSubtab(tab) {
  const validTabs = ['overview', 'manage', 'planner', 'trends'];
  if (!validTabs.includes(tab)) return;

  _currentAccountsSubtab = tab;

  document.querySelectorAll('.accounts-subtab').forEach(b => {
    b.classList.remove('active');
    b.style.borderBottom = 'none';
  });
  const btn = document.querySelector(`.accounts-subtab[data-subtab="${tab}"]`);
  if (btn) {
    btn.classList.add('active');
    btn.style.borderBottom = '2px solid var(--primary)';
  }

  // Toggle views
  const overviewView = document.getElementById('accounts-overview-view');
  const manageView = document.getElementById('accounts-manage-view');
  const plannerView = document.getElementById('accounts-planner-view');
  const trendsView = document.getElementById('accounts-trends-view');
  if (overviewView) overviewView.style.display = tab === 'overview' ? '' : 'none';
  if (manageView) manageView.style.display = tab === 'manage' ? '' : 'none';
  if (plannerView) plannerView.style.display = tab === 'planner' ? '' : 'none';
  if (trendsView) trendsView.style.display = tab === 'trends' ? '' : 'none';

  if (tab === 'overview' && _tabIsStale('overview')) { _loadOverviewData(); _markTabLoaded('overview'); }
  if (tab === 'planner') _initPlanner();   // planner always refreshes (month may have changed)
  if (tab === 'trends' && _tabIsStale('trends')) { _loadTrendsData(); _markTabLoaded('trends'); }
}

// ── Add Account Modal ────────────────────────────────────────────────
let _addAccountStep = 1;

function openAddAccountModal() {
  _addAccountStep = 1;
  document.getElementById('add-account-modal').style.display = 'flex';
  document.getElementById('add-account-modal-title').textContent = 'Add New Account';
  // Reset form
  document.getElementById('account-step-1').style.display = '';
  document.getElementById('account-step-2').style.display = 'none';
  document.getElementById('account-step-3').style.display = 'none';
  document.getElementById('account-edit-form').style.display = 'none';
  document.getElementById('account-steps').style.display = 'flex';
  _resetAccountForm();
  _updateStepIndicators(1);
  _setupClassToggle();
}

function closeAddAccountModal() {
  document.getElementById('add-account-modal').style.display = 'none';
}

function _resetAccountForm() {
  const inputs = ['acct-name','acct-institution','acct-last-four','acct-open-date',
    'acct-credit-limit','acct-due-day','acct-annual-fee','acct-interest-rate',
    'acct-origination-principal','acct-origination-date','acct-loan-term',
    'acct-escrow-balance','acct-payment-source-tag','acct-balance',
    'acct-statement-balance','acct-available-balance'];
  inputs.forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
  document.getElementById('acct-responsibility').value = 'individual';
  document.getElementById('acct-annual-fee-month').value = '';
  const hasFeeCb = document.getElementById('acct-has-annual-fee');
  if (hasFeeCb) hasFeeCb.checked = false;
  // Reset radio buttons
  const liabRadio = document.querySelector('input[name="account-class"][value="liability"]');
  if (liabRadio) liabRadio.checked = true;
  const ccRadio = document.querySelector('#liability-types input[value="credit_card"]');
  if (ccRadio) ccRadio.checked = true;
}

function _setupClassToggle() {
  document.querySelectorAll('input[name="account-class"]').forEach(radio => {
    radio.onchange = () => {
      const isAsset = radio.value === 'asset';
      document.getElementById('liability-types').style.display = isAsset ? 'none' : 'flex';
      document.getElementById('asset-types').style.display = isAsset ? 'flex' : 'none';
      // Select first radio in visible group
      const firstRadio = document.querySelector(`#${isAsset ? 'asset-types' : 'liability-types'} input[type="radio"]`);
      if (firstRadio) firstRadio.checked = true;
    };
  });
}

function _updateStepIndicators(step) {
  document.querySelectorAll('.account-step').forEach(el => {
    const s = parseInt(el.dataset.step);
    const numEl = el.querySelector('.acct-step-num');
    if (s === step) {
      el.style.background = 'var(--primary)';
      el.style.color = 'white';
      if (numEl) numEl.textContent = s;
    } else if (s < step) {
      el.style.background = '#22c55e';
      el.style.color = 'white';
      if (numEl) numEl.textContent = '✓';
    } else {
      el.style.background = 'var(--bg-secondary)';
      el.style.color = 'var(--text-muted)';
      if (numEl) numEl.textContent = s;
    }
  });
}

function accountStepNext(current) {
  if (current === 1) {
    // Show step 2 with type-aware fields
    document.getElementById('account-step-1').style.display = 'none';
    document.getElementById('account-step-2').style.display = '';
    _showTypeFields();
    _updateStepIndicators(2);
  } else if (current === 2) {
    const name = document.getElementById('acct-name').value.trim();
    if (!name) { toast('Display name is required', 'error'); return; }
    document.getElementById('account-step-2').style.display = 'none';
    document.getElementById('account-step-3').style.display = '';
    _showBalanceFields();
    _updateStepIndicators(3);
  }
}

function accountStepBack(current) {
  if (current === 2) {
    document.getElementById('account-step-2').style.display = 'none';
    document.getElementById('account-step-1').style.display = '';
    _updateStepIndicators(1);
  } else if (current === 3) {
    document.getElementById('account-step-3').style.display = 'none';
    document.getElementById('account-step-2').style.display = '';
    _updateStepIndicators(2);
  }
}

function _getSelectedClass() {
  return document.querySelector('input[name="account-class"]:checked')?.value || 'liability';
}

function _getSelectedSubtype() {
  return document.querySelector('input[name="account-subtype"]:checked')?.value || 'credit_card';
}

function _showTypeFields() {
  const cls = _getSelectedClass();
  const subtype = _getSelectedSubtype();

  // Hide all conditional fields
  document.querySelectorAll('[class*="acct-field-"]').forEach(el => el.style.display = 'none');

  if (cls === 'asset') {
    document.querySelectorAll('.acct-field-asset').forEach(el => el.style.display = '');
  } else {
    if (subtype === 'credit_card') {
      document.querySelectorAll('.acct-field-cc').forEach(el => el.style.display = '');
    }
    if (['mortgage', 'auto_loan', 'student_loan'].includes(subtype)) {
      document.querySelectorAll('.acct-field-loan').forEach(el => el.style.display = '');
      if (subtype === 'mortgage') {
        document.querySelectorAll('.acct-field-mortgage').forEach(el => el.style.display = '');
      }
    }
    if (subtype === 'utility') {
      document.querySelectorAll('.acct-field-utility').forEach(el => el.style.display = '');
    }
    if (['utility', 'auto_loan', 'mortgage', 'student_loan', 'personal_debt', 'other'].includes(subtype)) {
      document.querySelectorAll('.acct-field-recurring-pay').forEach(el => el.style.display = '');
    }
  }

  // Listen for subtype changes
  document.querySelectorAll('input[name="account-subtype"]').forEach(r => {
    r.onchange = () => _showTypeFields();
  });
}

function _showBalanceFields() {
  const cls = _getSelectedClass();
  const subtype = _getSelectedSubtype();
  document.querySelectorAll('#account-step-3 [class*="acct-field-"]').forEach(el => el.style.display = 'none');
  if (cls === 'asset') {
    document.querySelectorAll('#account-step-3 .acct-field-asset').forEach(el => el.style.display = '');
  } else if (subtype === 'credit_card') {
    document.querySelectorAll('#account-step-3 .acct-field-cc').forEach(el => el.style.display = '');
    // Restore fee fields only if checkbox is checked
    const hasFee = document.getElementById('acct-has-annual-fee')?.checked;
    if (hasFee) {
      document.querySelectorAll('#account-step-3 .acct-field-cc-fee').forEach(el => el.style.display = '');
    }
  }
}

async function submitNewAccount() {
  const cls = _getSelectedClass();
  const subtype = _getSelectedSubtype();
  const name = document.getElementById('acct-name').value.trim();
  const balance = document.getElementById('acct-balance').value;

  if (!name) { toast('Display name is required', 'error'); return; }
  if (!balance && balance !== '0') { toast('Current balance is required', 'error'); return; }

  const payload = {
    name,
    account_class: cls,
    balance: parseFloat(balance) || 0,
    institution: document.getElementById('acct-institution').value.trim() || null,
    last_four: document.getElementById('acct-last-four').value.trim() || null,
    open_date: document.getElementById('acct-open-date').value || null,
    responsibility: document.getElementById('acct-responsibility').value,
  };

  if (cls === 'asset') {
    payload.asset_type = subtype;
    const avail = document.getElementById('acct-available-balance').value;
    if (avail) payload.available_balance = parseFloat(avail);
    const tag = document.getElementById('acct-payment-source-tag').value.trim();
    if (tag) payload.payment_source_tag = tag;
  } else {
    payload.liability_type = subtype;
    const stmtBal = document.getElementById('acct-statement-balance').value;
    if (stmtBal) payload.statement_balance = parseFloat(stmtBal);

    if (subtype === 'credit_card') {
      const cl = document.getElementById('acct-credit-limit').value;
      if (cl) payload.credit_limit = parseFloat(cl);
      const dd = document.getElementById('acct-due-day').value;
      if (dd) payload.due_day = parseInt(dd);
      const af = document.getElementById('acct-annual-fee').value;
      if (af) payload.annual_fee = parseFloat(af);
      const afm = document.getElementById('acct-annual-fee-month').value;
      if (afm) payload.annual_fee_month = parseInt(afm);
      const ir = document.getElementById('acct-interest-rate').value;
      if (ir) payload.interest_rate = parseFloat(ir);
    }
    if (['mortgage', 'auto_loan', 'student_loan'].includes(subtype)) {
      const op = document.getElementById('acct-origination-principal').value;
      if (op) payload.origination_principal = parseFloat(op);
      const od = document.getElementById('acct-origination-date').value;
      if (od) payload.origination_date = od;
      const lt = document.getElementById('acct-loan-term').value;
      if (lt) payload.loan_term = parseInt(lt);
      const ir = document.getElementById('acct-interest-rate').value;
      if (ir) payload.interest_rate = parseFloat(ir);
      if (subtype === 'mortgage') {
        const eb = document.getElementById('acct-escrow-balance').value;
        if (eb) payload.escrow_balance = parseFloat(eb);
      }
    }
    if (subtype === 'utility') {
      const dd = document.getElementById('acct-due-day').value;
      if (dd) payload.due_day = parseInt(dd);
    }
    const hasRecurringPay = document.getElementById('acct-has-recurring-pay')?.checked;
    if (hasRecurringPay) {
      const mp = document.getElementById('acct-monthly-payment').value;
      if (mp) payload.monthly_payment = parseFloat(mp);
    } else {
      payload.monthly_payment = null;
    }
  }

  try {
    const result = await api('POST', '/accounts/', payload);
    toast('Account created successfully', 'success');
    // Sync annual fee and monthly payment to recurring tab
    _syncAnnualFeeRecurring(result);
    _syncMonthlyPaymentRecurring(result);
    closeAddAccountModal();
    loadAccounts();
  } catch (e) {
    toast('Failed to create account: ' + e.message, 'error');
  }
}

// ── Annual Fee Checkbox Toggle ───────────────────────────────────────

function _toggleAnnualFeeFields(mode) {
  const prefix = mode === 'edit' ? 'edit-' : '';
  const checked = document.getElementById(`${prefix}acct-has-annual-fee`).checked;
  if (mode === 'edit') {
    document.getElementById('edit-field-annual-fee').style.display = checked ? '' : 'none';
    document.getElementById('edit-field-annual-fee-month').style.display = checked ? '' : 'none';
  } else {
    document.getElementById('field-annual-fee').style.display = checked ? '' : 'none';
    document.getElementById('field-annual-fee-month').style.display = checked ? '' : 'none';
  }
  if (!checked) {
    document.getElementById(`${prefix}acct-annual-fee`).value = '';
    document.getElementById(`${prefix}acct-annual-fee-month`).value = '';
  }
}

// ── Annual Fee → Recurring Sync ─────────────────────────────────────

async function _syncAnnualFeeRecurring(acct) {
  if (!acct || !acct.name) return;
  const inst = acct.institution || 'N/A';
  const last4 = acct.last_four || 'XXXX';
  const merchantKey = `${acct.name} - ${inst} - ${last4} (Annual Fee)`;
  const fee = parseFloat(acct.annual_fee) || 0;
  const feeMonth = acct.annual_fee_month;

  if (fee > 0) {
    // Calculate next estimated date from annual_fee_month
    let nextEstimated = null;
    if (feeMonth) {
      const now = new Date();
      let year = now.getFullYear();
      // If fee month already passed this year, set to next year
      if (feeMonth <= now.getMonth() + 1) year++;
      nextEstimated = `${year}-${String(feeMonth).padStart(2, '0')}-01`;
    }
    try {
      await api('POST', '/recurring/override', {
        merchant: merchantKey,
        is_recurring: true,
        label: merchantKey,
        amount: fee,
        frequency: 'annual',
        next_estimated: nextEstimated,
      });
    } catch (e) {
      // Non-fatal — don't block account save
      console.warn('Failed to sync annual fee to recurring:', e.message);
    }
  } else {
    // Fee removed — delete the generated recurring override
    try {
      await api('DELETE', `/recurring/override/${encodeURIComponent(merchantKey)}`);
    } catch (e) {
      // 404 is fine — override may not exist
    }
  }
}

// ── Monthly Payment → Recurring Sync ────────────────────────────────

async function _syncMonthlyPaymentRecurring(acct) {
  if (!acct || !acct.name) return;
  const inst = acct.institution || 'N/A';
  const last4 = acct.last_four || 'XXXX';
  const merchantKey = `${acct.name} - ${inst} - ${last4} (Monthly)`;
  const mp = parseFloat(acct.monthly_payment) || 0;

  if (mp > 0) {
    try {
      await api('POST', '/recurring/override', {
        merchant: merchantKey,
        is_recurring: true,
        label: merchantKey,
        amount: mp,
        frequency: 'monthly',
      });
    } catch (e) {
      console.warn('Failed to sync monthly payment to recurring:', e.message);
    }
  } else {
    try {
      await api('DELETE', `/recurring/override/${encodeURIComponent(merchantKey)}`);
    } catch (e) {
      // 404 is fine — override may not exist
    }
  }
}

// ── Recurring Pay Checkbox Toggle ────────────────────────────────────

function _toggleRecurringPayFields(mode) {
  const prefix = mode === 'edit' ? 'edit-' : '';
  const checked = document.getElementById(`${prefix}acct-has-recurring-pay`).checked;
  document.getElementById(`${prefix}field-recurring-pay`).style.display = checked ? '' : 'none';
  if (!checked) {
    document.getElementById(`${prefix}acct-monthly-payment`).value = '';
  }
}

// ── Edit Account ─────────────────────────────────────────────────────
const _LIABILITY_TYPES = [
  { value: 'credit_card', label: 'Credit Card' },
  { value: 'mortgage', label: 'Mortgage' },
  { value: 'auto_loan', label: 'Auto Loan' },
  { value: 'student_loan', label: 'Student Loan' },
  { value: 'utility', label: 'Utility / Service' },
  { value: 'personal_debt', label: 'Personal Debt' },
  { value: 'other', label: 'Other Liability' },
];

const _ASSET_TYPES = [
  { value: 'checking', label: 'Checking' },
  { value: 'savings', label: 'Savings' },
  { value: 'investment', label: 'Investment' },
  { value: 'digital_wallet', label: 'Digital Wallet' },
];

function _populateSubtypeDropdown(acctClass, currentSubtype) {
  const select = document.getElementById('edit-acct-subtype');
  if (!select) return;
  const types = acctClass === 'asset' ? _ASSET_TYPES : _LIABILITY_TYPES;
  select.innerHTML = types.map(t =>
    `<option value="${t.value}" ${t.value === currentSubtype ? 'selected' : ''}>${t.label}</option>`
  ).join('');
}

function _onEditClassChange() {
  const cls = document.getElementById('edit-acct-class').value;
  const defaults = cls === 'asset' ? 'checking' : 'credit_card';
  _populateSubtypeDropdown(cls, defaults);
  _onEditSubtypeChange();
}

function _onEditSubtypeChange() {
  const cls     = document.getElementById('edit-acct-class').value;
  const subtype = document.getElementById('edit-acct-subtype').value;
  const conditionalFields = [
    'edit-field-credit-limit', 'edit-field-interest-rate', 'edit-field-due-day',
    'edit-field-origination-principal', 'edit-field-origination-date',
    'edit-field-loan-term', 'edit-field-escrow',
  ];
  conditionalFields.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
  });
  if (cls === 'liability') {
    if (subtype === 'credit_card') {
      ['edit-field-credit-limit', 'edit-field-interest-rate', 'edit-field-due-day'].forEach(id => {
        const el = document.getElementById(id); if (el) el.style.display = '';
      });
    } else if (['mortgage', 'auto_loan', 'student_loan'].includes(subtype)) {
      ['edit-field-interest-rate', 'edit-field-origination-principal',
       'edit-field-origination-date', 'edit-field-loan-term'].forEach(id => {
        const el = document.getElementById(id); if (el) el.style.display = '';
      });
      if (subtype === 'mortgage') {
        const el = document.getElementById('edit-field-escrow'); if (el) el.style.display = '';
      }
    } else if (subtype === 'utility') {
      const el = document.getElementById('edit-field-due-day'); if (el) el.style.display = '';
    }
  }
}

function openEditAccount(id) {
  const acct = _accountsCache.find(a => a.id === id);
  if (!acct) return;

  // Populate header context
  document.getElementById('edit-panel-name').textContent = acct.name || 'Account';
  document.getElementById('edit-panel-type-badge').textContent = _typeLabel(acct);
  const bal = acct.balance != null
    ? parseFloat(acct.balance).toLocaleString('en-US', {style:'currency', currency:'USD'})
    : '$0.00';
  document.getElementById('edit-panel-balance').textContent = bal;

  // Identity
  document.getElementById('edit-account-id').value          = acct.id;
  document.getElementById('edit-acct-name').value           = acct.name || '';
  document.getElementById('edit-acct-institution').value    = acct.institution || '';
  document.getElementById('edit-acct-last-four').value      = acct.last_four || '';
  document.getElementById('edit-acct-open-date').value      = acct.open_date || '';
  document.getElementById('edit-acct-responsibility').value = acct.responsibility || 'individual';

  // Classification
  const acctClass = acct.account_class || (acct.is_asset ? 'asset' : 'liability');
  document.getElementById('edit-acct-class').value = acctClass;
  const currentSubtype = acctClass === 'asset' ? acct.asset_type : acct.liability_type;
  _populateSubtypeDropdown(acctClass, currentSubtype || (acctClass === 'asset' ? 'checking' : 'credit_card'));
  _onEditSubtypeChange();

  // Terms
  document.getElementById('edit-acct-balance').value        = acct.balance != null ? acct.balance : '';
  document.getElementById('edit-acct-credit-limit').value   = acct.credit_limit || '';
  document.getElementById('edit-acct-interest-rate').value  = acct.interest_rate || '';
  document.getElementById('edit-acct-due-day').value        = acct.due_day || '';
  document.getElementById('edit-acct-origination-principal').value = acct.origination_principal || '';
  document.getElementById('edit-acct-origination-date').value     = acct.origination_date || '';
  document.getElementById('edit-acct-loan-term').value            = acct.loan_term || '';
  document.getElementById('edit-acct-escrow-balance').value       = acct.escrow_balance || '';

  // Annual fee
  const hasAnnualFee = acct.annual_fee != null && parseFloat(acct.annual_fee) > 0;
  document.getElementById('edit-acct-has-annual-fee').checked = hasAnnualFee;
  document.getElementById('edit-acct-annual-fee').value       = hasAnnualFee ? acct.annual_fee : '';
  document.getElementById('edit-acct-annual-fee-month').value = acct.annual_fee_month || '';
  document.getElementById('edit-field-annual-fee').style.display       = hasAnnualFee ? '' : 'none';
  document.getElementById('edit-field-annual-fee-month').style.display = hasAnnualFee ? '' : 'none';

  // Monthly payment
  const hasMonthlyPay = acct.monthly_payment != null && parseFloat(acct.monthly_payment) > 0;
  const mpCb = document.getElementById('edit-acct-has-recurring-pay');
  if (mpCb) {
    mpCb.checked = hasMonthlyPay;
    document.getElementById('edit-acct-monthly-payment').value        = hasMonthlyPay ? acct.monthly_payment : '';
    document.getElementById('edit-field-recurring-pay').style.display = hasMonthlyPay ? '' : 'none';
  }

  // Linking
  document.getElementById('edit-acct-payment-source-tag').value = acct.payment_source_tag || '';
  _populateLinkedSourceDropdown(acct);

  // Reset danger zone
  document.getElementById('edit-panel-delete-confirm').style.display = 'none';
  document.getElementById('edit-panel-delete-btn').style.display     = '';

  // Highlight active row
  document.querySelectorAll('tr.acct-row-active').forEach(r => r.classList.remove('acct-row-active'));
  const row = document.querySelector(`#accounts-table-body tr[data-account-id="${id}"]`);
  if (row) row.classList.add('acct-row-active');

  // Open slide-over
  document.getElementById('edit-account-slideover-overlay').style.display = '';
  const panel = document.getElementById('edit-account-slideover');
  panel.style.transform = 'translateX(100%)';
  panel.offsetHeight; // force reflow
  panel.classList.add('open');
}

function closeEditAccountPanel() {
  const panel = document.getElementById('edit-account-slideover');
  if (panel) panel.classList.remove('open');
  const overlay = document.getElementById('edit-account-slideover-overlay');
  if (overlay) overlay.style.display = 'none';
  document.querySelectorAll('tr.acct-row-active').forEach(r => r.classList.remove('acct-row-active'));
}

async function _confirmDeleteFromEditPanel() {
  const id = parseInt(document.getElementById('edit-account-id').value);
  if (!id) return;
  closeEditAccountPanel();
  await deleteAccount(id);
}

async function submitEditAccount() {
  const id = document.getElementById('edit-account-id').value;
  const payload = {};
  const name = document.getElementById('edit-acct-name').value.trim();
  if (name) payload.name = name;

  // Account class + type
  const acctClass = document.getElementById('edit-acct-class').value;
  const subtype = document.getElementById('edit-acct-subtype').value;
  payload.account_class = acctClass;
  if (acctClass === 'asset') {
    payload.asset_type = subtype;
  } else {
    payload.liability_type = subtype;
  }

  // Identity fields
  const inst = document.getElementById('edit-acct-institution').value.trim();
  if (inst) payload.institution = inst;
  const lf = document.getElementById('edit-acct-last-four').value.trim();
  if (lf) payload.last_four = lf;
  const openDate = document.getElementById('edit-acct-open-date').value;
  if (openDate) payload.open_date = openDate;
  const responsibility = document.getElementById('edit-acct-responsibility').value;
  if (responsibility) payload.responsibility = responsibility;

  // Terms fields
  const dd = document.getElementById('edit-acct-due-day').value;
  if (dd) payload.due_day = parseInt(dd);
  const bal = document.getElementById('edit-acct-balance').value;
  if (bal !== '') payload.balance = parseFloat(bal);
  const cl = document.getElementById('edit-acct-credit-limit').value;
  if (cl) payload.credit_limit = parseFloat(cl);
  const ir = document.getElementById('edit-acct-interest-rate').value;
  if (ir) payload.interest_rate = parseFloat(ir);

  // Loan-specific fields
  const op = document.getElementById('edit-acct-origination-principal').value;
  if (op) payload.origination_principal = parseFloat(op);
  const od = document.getElementById('edit-acct-origination-date').value;
  if (od) payload.origination_date = od;
  const lt = document.getElementById('edit-acct-loan-term').value;
  if (lt) payload.loan_term = parseInt(lt);
  const eb = document.getElementById('edit-acct-escrow-balance').value;
  if (eb) payload.escrow_balance = parseFloat(eb);

  // Annual fee
  const hasAnnualFee = document.getElementById('edit-acct-has-annual-fee').checked;
  if (hasAnnualFee) {
    const af = document.getElementById('edit-acct-annual-fee').value;
    if (af) payload.annual_fee = parseFloat(af);
    const afm = document.getElementById('edit-acct-annual-fee-month').value;
    if (afm) payload.annual_fee_month = parseInt(afm);
  } else {
    payload.annual_fee = 0;
    payload.annual_fee_month = null;
  }

  // Monthly payment
  const hasRecurringPay = document.getElementById('edit-acct-has-recurring-pay')?.checked;
  if (hasRecurringPay) {
    const mp = document.getElementById('edit-acct-monthly-payment').value;
    payload.monthly_payment = mp ? parseFloat(mp) : null;
  } else {
    payload.monthly_payment = null;
  }

  // Linking
  const tag = document.getElementById('edit-acct-payment-source-tag').value.trim();
  if (tag) payload.payment_source_tag = tag;
  const linkedSelect = document.getElementById('edit-acct-linked-source');
  if (linkedSelect) {
    const linkedVal = linkedSelect.value;
    if (linkedVal) {
      const [acctId, bankName] = linkedVal.split('||');
      payload.linked_account_id = acctId;
      payload.linked_bank_name = bankName || null;
    } else {
      payload.linked_account_id = null;
      payload.linked_bank_name = null;
    }
  }

  try {
    const result = await api('PUT', `/accounts/${id}`, payload);
    toast('Account updated', 'success');
    _syncAnnualFeeRecurring(result);
    _syncMonthlyPaymentRecurring(result);
    closeEditAccountPanel();
    loadAccounts();
  } catch (e) {
    toast('Failed to update account: ' + e.message, 'error');
  }
}

async function _populateLinkedSourceDropdown(acct) {
  const select = document.getElementById('edit-acct-linked-source');
  if (!select) return;

  select.innerHTML = '<option value="">-- Not linked --</option>';
  try {
    const sources = await api('GET', '/accounts/integration/linkable-sources');
    for (const s of sources) {
      const val = `${s.account_id}||${s.bank_name || ''}`;
      const label = `${s.bank_name || 'Unknown'} - ${s.account_id} (${s.statement_type || 'unknown'}, ${s.txn_count} txns)`;
      const linked = s.linked_to ? ` [linked to: ${esc(s.linked_to.nw_name)}]` : '';
      const opt = document.createElement('option');
      opt.value = val;
      opt.textContent = label + linked;
      select.appendChild(opt);
    }
    // Pre-select current linked source
    if (acct.linked_account_id) {
      const curVal = `${acct.linked_account_id}||${acct.linked_bank_name || ''}`;
      select.value = curVal;
    }
  } catch (e) {
    // Silently fail — sources may not exist yet
  }
}

async function closeAccount(id) {
  if (!confirm('Close this account? It will be marked as closed but not deleted.')) return;
  try {
    await api('PATCH', `/accounts/${id}/status`, {status: 'closed'});
    toast('Account closed', 'success');
    loadAccounts();
  } catch (e) {
    toast('Failed to close account: ' + e.message, 'error');
  }
}

// ── Delete & Bulk Operations ─────────────────────────────────────────

async function deleteAccount(id) {
  // Fetch impact summary first
  try {
    const impact = await api('GET', `/accounts/delete-impact/${id}`);
    const name = impact.account_name || `Account #${id}`;
    let msg = `Permanently delete "${name}"?\n\nThis will also remove:\n`;
    msg += `  - ${impact.ap_balance_ledger} balance ledger entries\n`;
    msg += `  - ${impact.ap_billing_cycles} billing cycles\n`;
    msg += `  - ${impact.ap_payments} payments\n`;
    msg += `  - ${impact.ap_payment_plan} payment plan entries\n`;
    msg += `  - ${impact.ap_card_benefits} card benefits\n`;
    msg += `  - ${impact.ap_apr_terms} APR terms\n`;
    msg += `  - ${impact.ap_payment_source_tags} source tags\n`;
    msg += `\nThis action cannot be undone.`;
    if (!confirm(msg)) return;
  } catch (e) {
    if (!confirm(`Permanently delete this account and all related data? This cannot be undone.`)) return;
  }
  try {
    await api('DELETE', `/accounts/delete/${id}`);
    toast('Account permanently deleted', 'success');
    loadAccounts();
  } catch (e) {
    toast('Failed to delete account: ' + e.message, 'error');
  }
}

function _getSelectedAccountIds() {
  return Array.from(document.querySelectorAll('.acct-select-cb:checked'))
    .map(cb => parseInt(cb.dataset.accountId));
}

function _updateAcctBulkBar() {
  const ids = _getSelectedAccountIds();
  const bar = document.getElementById('accounts-bulk-bar');
  const countEl = document.getElementById('accounts-bulk-count');
  if (!bar) return;
  if (ids.length > 0) {
    bar.style.display = 'flex';
    countEl.textContent = `${ids.length} account${ids.length > 1 ? 's' : ''} selected`;
  } else {
    bar.style.display = 'none';
  }
}

function _toggleSelectAllAccounts(checked) {
  document.querySelectorAll('.acct-select-cb').forEach(cb => { cb.checked = checked; });
  _updateAcctBulkBar();
}

function _clearAccountSelection() {
  const selectAll = document.getElementById('accounts-select-all');
  if (selectAll) selectAll.checked = false;
  document.querySelectorAll('.acct-select-cb').forEach(cb => { cb.checked = false; });
  _updateAcctBulkBar();
}

async function _bulkCloseAccounts() {
  const ids = _getSelectedAccountIds();
  if (!ids.length) return;
  if (!confirm(`Close ${ids.length} account${ids.length > 1 ? 's' : ''}? They will be marked as closed but not deleted.`)) return;
  try {
    await api('POST', '/accounts/bulk-delete', { account_ids: ids, permanent: false });
    toast(`${ids.length} account(s) closed`, 'success');
    loadAccounts();
  } catch (e) {
    toast('Bulk close failed: ' + e.message, 'error');
  }
}

async function _bulkDeleteAccounts() {
  const ids = _getSelectedAccountIds();
  if (!ids.length) return;
  const msg = `Permanently delete ${ids.length} account${ids.length > 1 ? 's' : ''} and ALL related data?\n\nThis includes balance history, billing cycles, payments, payment plans, card benefits, APR terms, and source tags.\n\nThis action CANNOT be undone.`;
  if (!confirm(msg)) return;
  try {
    await api('POST', '/accounts/bulk-delete', { account_ids: ids, permanent: true });
    toast(`${ids.length} account(s) permanently deleted`, 'success');
    loadAccounts();
  } catch (e) {
    toast('Bulk delete failed: ' + e.message, 'error');
  }
}

// ── Payment Source Tags ──────────────────────────────────────────────
async function _loadPaymentSourceTags() {
  try {
    const tags = await api('GET', '/accounts/tags');
    _renderTagsTable(tags);
  } catch (e) {
    // Tags table may be empty on first load
  }
}

function _renderTagsTable(tags) {
  const tbody = document.getElementById('tags-table-body');
  if (!tags.length) {
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color:var(--text-muted); padding:16px;">No tags yet.</td></tr>';
    return;
  }
  tbody.innerHTML = tags.map(t => {
    const acct = _accountsCache.find(a => a.id === t.account_id);
    const acctName = acct ? esc(acct.name) : `#${t.account_id}`;
    return `<tr>
      <td><code>${esc(t.short_code)}</code></td>
      <td>${acctName}</td>
      <td style="color:var(--text-muted); font-size:13px;">${t.created_at ? new Date(t.created_at).toLocaleDateString() : '-'}</td>
      <td><button class="btn btn-danger btn-sm" onclick="deletePaymentSourceTag('${esc(t.short_code)}')">Delete</button></td>
    </tr>`;
  }).join('');
}

function _populateTagAccountDropdown(accounts) {
  const sel = document.getElementById('tag-account-id');
  sel.innerHTML = '<option value="">Select account...</option>' +
    accounts.map(a => `<option value="${a.id}">${esc(a.name)}</option>`).join('');
}

async function createPaymentSourceTag() {
  const code = document.getElementById('tag-short-code').value.trim();
  const accountId = document.getElementById('tag-account-id').value;
  if (!code) { toast('Short code is required', 'error'); return; }
  if (!accountId) { toast('Select an account', 'error'); return; }
  try {
    await api('POST', '/accounts/tags', {short_code: code, account_id: parseInt(accountId)});
    toast('Tag created', 'success');
    document.getElementById('tag-short-code').value = '';
    _loadPaymentSourceTags();
  } catch (e) {
    toast('Failed to create tag: ' + e.message, 'error');
  }
}

async function deletePaymentSourceTag(code) {
  if (!confirm(`Delete tag "${code}"?`)) return;
  try {
    await api('DELETE', `/accounts/tags/${encodeURIComponent(code)}`);
    toast('Tag deleted', 'success');
    _loadPaymentSourceTags();
  } catch (e) {
    toast('Failed to delete tag: ' + e.message, 'error');
  }
}

// ── Overview Sub-View (Phase 2) ─────────────────────────────────────

function _fmt(val) {
  if (val == null) return '-';
  return parseFloat(val).toLocaleString('en-US', {style:'currency', currency:'USD'});
}

async function _loadOverviewData() {
  try {
    const [summary, latestAccounts] = await Promise.all([
      api('GET', '/accounts/balances/summary'),
      api('GET', '/accounts/balances/latest'),
    ]);
    _renderKPIs(summary);
    _renderOverviewTables(latestAccounts);
  } catch (e) {
    toast('Failed to load overview: ' + e.message, 'error');
  }
}

function _renderKPIs(s) {
  document.getElementById('kpi-cash-at-hand').textContent = _fmt(s.cash_at_hand);
  document.getElementById('kpi-investments').textContent = _fmt(s.total_investments);
  document.getElementById('kpi-total-liabilities').textContent = _fmt(s.total_liabilities_excl_personal);

  const liquidEl = document.getElementById('kpi-liquid-net');
  liquidEl.textContent = _fmt(s.liquid_net);
  liquidEl.style.color = s.liquid_net >= 0 ? 'var(--success)' : 'var(--danger)';

  const pct = s.credit_utilization_pct || 0;
  const utilEl = document.getElementById('kpi-utilization');
  utilEl.textContent = pct + '%';
  const utilColor = pct > 80 ? 'var(--danger)' : pct > 30 ? 'var(--warning)' : 'var(--success)';
  utilEl.style.color = utilColor;
  const bar = document.getElementById('kpi-util-bar');
  if (bar) { bar.style.width = Math.min(pct, 100) + '%'; bar.style.background = utilColor; }

  document.getElementById('kpi-due-this-week').textContent = s.due_this_week;
  document.getElementById('kpi-monthly-interest').textContent = _fmt(s.est_monthly_interest);

  // Pre-build due-this-week popover from cached account data
  _buildDuePopover();
}

// ── KPI click handlers ───────────────────────────────────────

function _kpiScrollTo(elementId) {
  const el = document.getElementById(elementId);
  if (!el) return;
  // Ensure parent card is expanded (collapsed cards have display:none body)
  const collapsibleBody = el.closest('.card-collapsible-body');
  if (collapsibleBody && collapsibleBody.style.display === 'none') {
    const toggle = collapsibleBody.previousElementSibling;
    if (toggle) toggle.click();
  }
  el.closest('table, .card')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function _kpiGoToTrendsSection(sectionId) {
  // Switch to trends tab (cache handles whether to reload), then scroll
  switchAccountsSubtab('trends');
  setTimeout(() => {
    const el = document.getElementById(sectionId);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, 150);
}

function _buildDuePopover() {
  const popover = document.getElementById('kpi-due-popover');
  if (!popover) return;
  const today = new Date();
  const in7 = new Date(today); in7.setDate(today.getDate() + 7);
  const due = _accountsCache.filter(a => {
    if (!a.payment_due_date) return false;
    const d = new Date(a.payment_due_date);
    return d >= today && d <= in7;
  }).sort((a, b) => new Date(a.payment_due_date) - new Date(b.payment_due_date));

  if (!due.length) {
    popover.innerHTML = '<div style="color:var(--text-muted);">No accounts due in the next 7 days.</div>';
    return;
  }
  popover.innerHTML = due.map(a => {
    const minDue = a.minimum_payment_amount ? _fmt(a.minimum_payment_amount) : '—';
    const daysLeft = Math.round((new Date(a.payment_due_date) - today) / 86400000);
    const dayLabel = daysLeft === 0 ? 'Today' : daysLeft === 1 ? 'Tomorrow' : `In ${daysLeft}d`;
    return `<div style="display:flex; justify-content:space-between; align-items:center; padding:4px 0; border-bottom:1px solid var(--border);">
      <span style="font-weight:600;">${esc(a.name)}</span>
      <span style="color:var(--text-muted); margin:0 8px;">${dayLabel}</span>
      <span style="color:var(--danger);">${minDue}</span>
    </div>`;
  }).join('') + `<div style="margin-top:8px; color:var(--text-muted); font-size:11px; cursor:pointer;" onclick="switchAccountsSubtab('planner');document.getElementById('kpi-due-popover').classList.remove('open')">Open Payment Planner →</div>`;
}

function _kpiToggleDuePopover(e) {
  e.stopPropagation();
  const popover = document.getElementById('kpi-due-popover');
  if (!popover) return;
  const isOpen = popover.classList.contains('open');
  // Close any other open popovers first
  document.querySelectorAll('.kpi-due-popover.open').forEach(p => p.classList.remove('open'));
  if (!isOpen) popover.classList.add('open');
}

// Close due popover when clicking outside
document.addEventListener('click', () => {
  document.querySelectorAll('.kpi-due-popover.open').forEach(p => p.classList.remove('open'));
});

// ── Overview Liabilities & Assets filter/sort state ─────────────────

let _overviewLiabilities = [];
let _overviewAssets = [];

let _liabFilterState = { query: '', type: null, stale: null, sortCol: 'balance', sortDir: 'desc' };
let _assetFilterState = { query: '', type: null, stale: null, sortCol: 'balance', sortDir: 'desc' };

function _stalenessLevel(lastVerifiedAt) {
  if (!lastVerifiedAt) return 'stale';
  const days = Math.floor((Date.now() - new Date(lastVerifiedAt)) / 86400000);
  if (days > 14) return 'stale';
  if (days > 7) return 'aging';
  return 'fresh';
}

function _updateOverviewSortArrows(prefix, sortCol, sortDir) {
  const cols = prefix === 'liab'
    ? ['name', 'institution', 'balance', 'statement', 'minDue', 'dueDay', 'creditLimit', 'util', 'lastUpdated']
    : ['name', 'institution', 'balance', 'lastUpdated'];
  cols.forEach(c => {
    const el = document.getElementById(`${prefix}-sort-${c}`);
    if (!el) return;
    el.textContent = c === sortCol ? (sortDir === 'asc' ? '▲' : '▼') : '';
  });
}

function _onLiabFilterChange() {
  _liabFilterState.query = (document.getElementById('liab-search').value || '').toLowerCase();
  _applyLiabFilters();
}

function _setLiabTypeFilter(type) {
  _liabFilterState.type = type;
  document.querySelectorAll('[id^="liab-pill-type-"]').forEach(b => b.classList.remove('rec-pill-active'));
  const id = type ? `liab-pill-type-${type}` : 'liab-pill-type-all';
  document.getElementById(id)?.classList.add('rec-pill-active');
  _applyLiabFilters();
}

function _setLiabStaleFilter(stale) {
  _liabFilterState.stale = stale;
  document.querySelectorAll('[id^="liab-pill-stale-"]').forEach(b => b.classList.remove('rec-pill-active'));
  const id = stale ? `liab-pill-stale-${stale}` : 'liab-pill-stale-all';
  document.getElementById(id)?.classList.add('rec-pill-active');
  _applyLiabFilters();
}

function _sortLiab(col) {
  if (_liabFilterState.sortCol === col) {
    _liabFilterState.sortDir = _liabFilterState.sortDir === 'asc' ? 'desc' : 'asc';
  } else {
    _liabFilterState.sortCol = col;
    _liabFilterState.sortDir = 'desc';
  }
  _applyLiabFilters();
}

function _applyLiabFilters() {
  const { query, type, stale, sortCol, sortDir } = _liabFilterState;
  let rows = _overviewLiabilities.slice();

  if (query) {
    rows = rows.filter(a =>
      (a.name || '').toLowerCase().includes(query) ||
      (a.institution || '').toLowerCase().includes(query) ||
      (a.payment_source_tag || '').toLowerCase().includes(query)
    );
  }
  if (type) {
    rows = rows.filter(a => (a.liability_type || 'other') === type);
  }
  if (stale) {
    rows = rows.filter(a => _stalenessLevel(a.last_verified_at) === stale);
  }

  const numCol = ['balance', 'statement', 'minDue', 'dueDay', 'creditLimit', 'util'];
  rows.sort((a, b) => {
    let av, bv;
    if (sortCol === 'name')        { av = (a.name || '').toLowerCase(); bv = (b.name || '').toLowerCase(); }
    else if (sortCol === 'institution') { av = (a.institution || '').toLowerCase(); bv = (b.institution || '').toLowerCase(); }
    else if (sortCol === 'balance')    { av = Math.abs(parseFloat(a.balance || 0)); bv = Math.abs(parseFloat(b.balance || 0)); }
    else if (sortCol === 'statement')  { av = a.last_statement_balance != null ? Math.abs(parseFloat(a.last_statement_balance)) : -1; bv = b.last_statement_balance != null ? Math.abs(parseFloat(b.last_statement_balance)) : -1; }
    else if (sortCol === 'minDue')     { av = a.minimum_payment_amount != null ? parseFloat(a.minimum_payment_amount) : -1; bv = b.minimum_payment_amount != null ? parseFloat(b.minimum_payment_amount) : -1; }
    else if (sortCol === 'dueDay')     { av = a.due_day || 0; bv = b.due_day || 0; }
    else if (sortCol === 'creditLimit'){ av = a.credit_limit ? parseFloat(a.credit_limit) : -1; bv = b.credit_limit ? parseFloat(b.credit_limit) : -1; }
    else if (sortCol === 'util')       { const acl = a.credit_limit ? parseFloat(a.credit_limit) : 0; const bcl = b.credit_limit ? parseFloat(b.credit_limit) : 0; av = acl > 0 ? Math.abs(parseFloat(a.balance || 0)) / acl : -1; bv = bcl > 0 ? Math.abs(parseFloat(b.balance || 0)) / bcl : -1; }
    else if (sortCol === 'lastUpdated'){ av = a.last_verified_at || ''; bv = b.last_verified_at || ''; }
    else { av = 0; bv = 0; }
    if (av < bv) return sortDir === 'asc' ? -1 : 1;
    if (av > bv) return sortDir === 'asc' ? 1 : -1;
    return 0;
  });

  _updateOverviewSortArrows('liab', sortCol, sortDir);
  _renderLiabTable(rows);
}

function _renderLiabTable(rows) {
  const liabBody = document.getElementById('overview-liabilities-body');
  if (!rows.length) {
    liabBody.innerHTML = '<tr><td colspan="10" style="text-align:center; padding:24px; color:var(--text-muted);">No liabilities match</td></tr>';
    return;
  }
  liabBody.innerHTML = rows.map(a => {
    const bal = Math.abs(parseFloat(a.balance || 0));
    const stmt = a.last_statement_balance != null ? Math.abs(parseFloat(a.last_statement_balance)) : null;
    const minDue = a.minimum_payment_amount != null ? parseFloat(a.minimum_payment_amount) : null;
    const cl = a.credit_limit ? parseFloat(a.credit_limit) : null;
    const util = cl && cl > 0 ? Math.round(bal / cl * 100) : null;
    const utilStyle = util != null && util > 80 ? 'color:var(--danger); font-weight:600;' : util != null && util > 30 ? 'color:var(--warning);' : '';
    const staleInfo = _staleBadge(a.last_verified_at);
    return `<tr>
      <td><strong>${esc(a.name)}</strong>${a.last_four ? ' <span style="color:var(--text-muted);">(' + esc(a.last_four) + ')</span>' : ''}</td>
      <td>${esc(a.institution || '-')}</td>
      <td style="text-align:right; font-variant-numeric:tabular-nums;">${_fmt(bal)}</td>
      <td style="text-align:right; font-variant-numeric:tabular-nums;">${stmt != null ? _fmt(stmt) : '-'}</td>
      <td style="text-align:right; font-variant-numeric:tabular-nums;">${minDue != null ? _fmt(minDue) : '-'}</td>
      <td style="text-align:right;">${a.due_day || '-'}</td>
      <td style="text-align:right; font-variant-numeric:tabular-nums;">${cl != null ? _fmt(cl) : '-'}</td>
      <td style="text-align:right; ${utilStyle}">${util != null ? util + '%' : '-'}</td>
      <td><code style="font-size:11px;">${esc(a.payment_source_tag || '-')}</code></td>
      <td style="font-size:12px;">${staleInfo}</td>
    </tr>`;
  }).join('');
}

function _onAssetFilterChange() {
  _assetFilterState.query = (document.getElementById('asset-search').value || '').toLowerCase();
  _applyAssetFilters();
}

function _setAssetTypeFilter(type) {
  _assetFilterState.type = type;
  document.querySelectorAll('[id^="asset-pill-type-"]').forEach(b => b.classList.remove('rec-pill-active'));
  const id = type ? `asset-pill-type-${type}` : 'asset-pill-type-all';
  document.getElementById(id)?.classList.add('rec-pill-active');
  _applyAssetFilters();
}

function _setAssetStaleFilter(stale) {
  _assetFilterState.stale = stale;
  document.querySelectorAll('[id^="asset-pill-stale-"]').forEach(b => b.classList.remove('rec-pill-active'));
  const id = stale ? `asset-pill-stale-${stale}` : 'asset-pill-stale-all';
  document.getElementById(id)?.classList.add('rec-pill-active');
  _applyAssetFilters();
}

function _sortAsset(col) {
  if (_assetFilterState.sortCol === col) {
    _assetFilterState.sortDir = _assetFilterState.sortDir === 'asc' ? 'desc' : 'asc';
  } else {
    _assetFilterState.sortCol = col;
    _assetFilterState.sortDir = 'desc';
  }
  _applyAssetFilters();
}

function _applyAssetFilters() {
  const { query, type, stale, sortCol, sortDir } = _assetFilterState;
  let rows = _overviewAssets.slice();

  if (query) {
    rows = rows.filter(a =>
      (a.name || '').toLowerCase().includes(query) ||
      (a.institution || '').toLowerCase().includes(query) ||
      (a.payment_source_tag || '').toLowerCase().includes(query)
    );
  }
  if (type) {
    rows = rows.filter(a => (a.asset_type || 'other') === type);
  }
  if (stale) {
    rows = rows.filter(a => _stalenessLevel(a.last_verified_at) === stale);
  }

  rows.sort((a, b) => {
    let av, bv;
    if (sortCol === 'name')        { av = (a.name || '').toLowerCase(); bv = (b.name || '').toLowerCase(); }
    else if (sortCol === 'institution') { av = (a.institution || '').toLowerCase(); bv = (b.institution || '').toLowerCase(); }
    else if (sortCol === 'balance')    { av = parseFloat(a.balance || 0); bv = parseFloat(b.balance || 0); }
    else if (sortCol === 'lastUpdated'){ av = a.last_verified_at || ''; bv = b.last_verified_at || ''; }
    else { av = 0; bv = 0; }
    if (av < bv) return sortDir === 'asc' ? -1 : 1;
    if (av > bv) return sortDir === 'asc' ? 1 : -1;
    return 0;
  });

  _updateOverviewSortArrows('asset', sortCol, sortDir);
  _renderAssetTable(rows);
}

function _renderAssetTable(rows) {
  const assetBody = document.getElementById('overview-assets-body');
  if (!rows.length) {
    assetBody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:24px; color:var(--text-muted);">No assets match</td></tr>';
    return;
  }
  assetBody.innerHTML = rows.map(a => {
    const staleInfo = _staleBadge(a.last_verified_at);
    return `<tr>
      <td><strong>${esc(a.name)}</strong>${a.last_four ? ' <span style="color:var(--text-muted);">(' + esc(a.last_four) + ')</span>' : ''}</td>
      <td>${esc(a.institution || '-')}</td>
      <td style="text-align:right; font-variant-numeric:tabular-nums;">${_fmt(a.balance)}</td>
      <td><code style="font-size:11px;">${esc(a.payment_source_tag || '-')}</code></td>
      <td style="font-size:12px;">${staleInfo}</td>
    </tr>`;
  }).join('');
}

function _renderOverviewTables(accounts) {
  _overviewLiabilities = accounts.filter(a => a.account_class === 'liability' || a.is_asset === false);
  _overviewAssets      = accounts.filter(a => a.account_class === 'asset'     || a.is_asset === true);

  // Reset filter state query (keep sort preferences)
  _liabFilterState.query = '';
  _assetFilterState.query = '';
  const liabSearch = document.getElementById('liab-search');
  if (liabSearch) liabSearch.value = '';
  const assetSearch = document.getElementById('asset-search');
  if (assetSearch) assetSearch.value = '';

  _applyLiabFilters();
  _applyAssetFilters();
}

function _staleBadge(lastVerifiedAt) {
  if (!lastVerifiedAt) return '<span style="color:var(--danger);" title="Never verified">&#9679; Never</span>';
  const now = new Date();
  const verified = new Date(lastVerifiedAt);
  const days = Math.floor((now - verified) / (1000 * 60 * 60 * 24));
  const dateStr = verified.toLocaleDateString();
  if (days > 14) return `<span style="color:var(--danger);" title="${days} days ago">&#9679; ${dateStr}</span>`;
  if (days > 7) return `<span style="color:var(--warning);" title="${days} days ago">&#9679; ${dateStr}</span>`;
  return `<span style="color:var(--success);" title="${days} days ago">&#9679; ${dateStr}</span>`;
}

// ── Update Balances Grid ─────────────────────────────────────────────

function openUpdateBalancesGrid() {
  document.getElementById('update-balances-modal').style.display = 'flex';
  _renderUpdateBalancesGrid();
}

function closeUpdateBalancesGrid() {
  document.getElementById('update-balances-modal').style.display = 'none';
}

async function _renderUpdateBalancesGrid() {
  let accounts;
  try {
    accounts = await api('GET', '/accounts/balances/latest');
  } catch (e) {
    toast('Failed to load balances', 'error');
    return;
  }

  // Group by type for easier scanning
  const typeOrder = ['credit_card','mortgage','auto_loan','student_loan','utility','personal_debt','other','checking','savings','investment','digital_wallet'];
  accounts.sort((a, b) => {
    const aType = a.liability_type || a.asset_type || '';
    const bType = b.liability_type || b.asset_type || '';
    return typeOrder.indexOf(aType) - typeOrder.indexOf(bType);
  });

  const tbody = document.getElementById('update-balances-body');
  let lastType = null;
  let html = '';

  for (const a of accounts) {
    const subtype = a.liability_type || a.asset_type || a.acct_type;
    const typeLabels = {
      credit_card: 'Credit Cards', mortgage: 'Mortgages', auto_loan: 'Auto Loans',
      student_loan: 'Student Loans', utility: 'Utilities', personal_debt: 'Personal Debts',
      other: 'Other', checking: 'Checking', savings: 'Savings',
      investment: 'Investments', digital_wallet: 'Digital Wallets',
    };
    if (subtype !== lastType) {
      lastType = subtype;
      html += `<tr><td colspan="7" style="background:var(--bg-secondary); font-weight:600; padding:8px 12px; font-size:13px;">${typeLabels[subtype] || subtype || 'Other'}</td></tr>`;
    }

    const isCC = a.liability_type === 'credit_card';
    const staleInfo = _staleBadge(a.last_verified_at);
    html += `<tr data-account-id="${a.id}">
      <td>${esc(a.name)}${a.last_four ? ' <span style="color:var(--text-muted);">(' + esc(a.last_four) + ')</span>' : ''}</td>
      <td style="font-size:12px;">${_typeLabel(a)}</td>
      <td style="text-align:right; color:var(--text-muted); font-variant-numeric:tabular-nums;">${_fmt(a.balance)}</td>
      <td><input type="number" step="0.01" class="bal-input-current" data-id="${a.id}" placeholder="unchanged" style="width:120px; padding:4px 8px; border:1px solid var(--border); border-radius:4px; text-align:right; font-variant-numeric:tabular-nums;" /></td>
      <td class="bal-col-stmt">${isCC ? `<input type="number" step="0.01" class="bal-input-stmt" data-id="${a.id}" placeholder="${a.last_statement_balance || ''}" style="width:110px; padding:4px 8px; border:1px solid var(--border); border-radius:4px; text-align:right;" />` : '-'}</td>
      <td class="bal-col-min">${isCC ? `<input type="number" step="0.01" class="bal-input-min" data-id="${a.id}" placeholder="${a.minimum_payment_amount || ''}" style="width:100px; padding:4px 8px; border:1px solid var(--border); border-radius:4px; text-align:right;" />` : '-'}</td>
      <td style="font-size:12px;">${staleInfo}</td>
    </tr>`;
  }

  tbody.innerHTML = html;
}

// ── Payment Planner ─────────────────────────────────────────────────

let _plannerData = { plan: [], capacity: [], openCycles: [], payments: [] };
let _plannerInitialized = false;

function _initPlanner() {
  const monthInput = document.getElementById('planner-cycle-month');
  if (!monthInput.value) {
    const now = new Date();
    monthInput.value = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0');
  }
  loadPlannerData();
}

function _getPlannerMonth() {
  return document.getElementById('planner-cycle-month').value; // 'YYYY-MM'
}

function plannerPrevMonth() {
  const input = document.getElementById('planner-cycle-month');
  const d = new Date(input.value + '-01');
  d.setMonth(d.getMonth() - 1);
  input.value = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0');
  loadPlannerData();
}

function plannerNextMonth() {
  const input = document.getElementById('planner-cycle-month');
  const d = new Date(input.value + '-01');
  d.setMonth(d.getMonth() + 1);
  input.value = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0');
  loadPlannerData();
}

async function loadPlannerData() {
  const month = _getPlannerMonth();
  if (!month) return;

  try {
    const [plan, capacity, openCycles, payments] = await Promise.all([
      api('GET', `/accounts/payments/plan/${month}`),
      api('GET', `/accounts/payments/capacity?cycle_month=${month}`),
      api('GET', '/accounts/cycles/open'),
      api('GET', '/accounts/payments/history?limit=20'),
    ]);
    _plannerData = { plan, capacity, openCycles, payments };
    _renderOpenCycles(openCycles);
    _renderCapacityMeters(capacity);
    _renderAssignmentGrid(plan, capacity);
    _renderPaymentHistory(payments);
  } catch (e) {
    toast('Failed to load planner data: ' + e.message, 'error');
  }
}

function _cycleBadge(status) {
  const colors = {
    open: '#3b82f6', paid_minimum: '#f59e0b', paid_statement: '#22c55e',
    paid_full: '#22c55e', overdue: '#ef4444',
  };
  const color = colors[status] || '#6b7280';
  return `<span style="display:inline-block; padding:2px 8px; border-radius:12px; font-size:11px; font-weight:600; background:${color}20; color:${color};">${esc(status)}</span>`;
}

function _renderOpenCycles(cycles) {
  const tbody = document.getElementById('planner-open-cycles-body');
  if (!cycles.length) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; padding:16px; color:var(--text-muted);">No open billing cycles.</td></tr>';
    return;
  }
  const acctMap = {};
  _accountsCache.forEach(a => { acctMap[a.id] = a; });

  tbody.innerHTML = cycles.map(c => {
    const acct = acctMap[c.account_id];
    const name = acct ? esc(acct.name) : `#${c.account_id}`;
    return `<tr>
      <td>${name}</td>
      <td>${esc(c.cycle_label)}</td>
      <td style="text-align:right; font-variant-numeric:tabular-nums;">${_fmt(c.statement_balance)}</td>
      <td style="text-align:right; font-variant-numeric:tabular-nums;">${c.minimum_payment != null ? _fmt(c.minimum_payment) : '-'}</td>
      <td style="text-align:right; font-variant-numeric:tabular-nums;">${_fmt(c.total_paid)}</td>
      <td>${esc(c.payment_due_date || '-')}</td>
      <td>${_cycleBadge(c.status)}</td>
    </tr>`;
  }).join('');
}

function _renderCapacityMeters(capacityList) {
  const container = document.getElementById('planner-capacity-meters');
  if (!capacityList.length) {
    container.innerHTML = '<p style="color:var(--text-muted); text-align:center;">No asset accounts found.</p>';
    return;
  }
  container.innerHTML = capacityList.map(c => {
    const balance = c.balance || 0;
    const allocated = c.total_allocated || 0;
    const remaining = c.remaining_after_payments || 0;
    const pct = balance > 0 ? Math.min(100, Math.round((allocated / balance) * 100)) : 0;
    const barColor = pct > 90 ? 'var(--danger)' : pct > 70 ? 'var(--warning, #f59e0b)' : 'var(--primary)';
    const tag = c.payment_source_tag ? ` <span style="color:var(--text-muted); font-size:11px;">[${esc(c.payment_source_tag)}]</span>` : '';
    return `<div style="margin-bottom:12px;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
        <span style="font-weight:600; font-size:13px;">${esc(c.name)}${tag}</span>
        <span style="font-size:12px; color:var(--text-muted);">
          ${_fmt(allocated)} allocated / ${_fmt(balance)} balance
          &mdash; <strong style="color:${remaining < 0 ? 'var(--danger)' : 'inherit'};">${_fmt(remaining)} remaining</strong>
        </span>
      </div>
      <div style="background:var(--bg-secondary); border-radius:4px; height:8px; overflow:hidden;">
        <div style="width:${pct}%; height:100%; background:${barColor}; border-radius:4px; transition:width 0.3s;"></div>
      </div>
    </div>`;
  }).join('');
}

function _renderAssignmentGrid(plan, capacityList) {
  const tbody = document.getElementById('planner-assignments-body');
  const liabilities = _accountsCache.filter(a => a.account_class === 'liability' && (a.status === 'active' || !a.status));
  const assets = _accountsCache.filter(a => a.account_class === 'asset' && (a.status === 'active' || !a.status));

  if (!liabilities.length) {
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; padding:16px; color:var(--text-muted);">No active liability accounts.</td></tr>';
    return;
  }

  const planMap = {};
  plan.forEach(p => { planMap[p.liability_id] = p; });

  const assetOptions = assets.map(a => {
    const tag = a.payment_source_tag ? ` [${a.payment_source_tag}]` : '';
    return `<option value="${a.id}">${esc(a.name)}${tag}</option>`;
  }).join('');

  const strategyLabels = {
    statement: 'Statement — pay statement balance in full',
    minimum: 'Minimum — pay the minimum required amount',
    full_balance: 'Full Balance — pay off entire current balance',
    fixed: 'Fixed — pay a specific amount each month',
    extra_principal: 'Extra Principal — minimum + extra toward principal',
  };
  const strategies = ['statement', 'minimum', 'full_balance', 'fixed', 'extra_principal'];

  tbody.innerHTML = liabilities.map(l => {
    const p = planMap[l.id] || {};
    const selectedSource = p.source_id || '';
    const selectedStrategy = p.strategy || 'statement';
    const plannedAmt = p.planned_amount != null ? parseFloat(p.planned_amount).toFixed(2) : '';
    const status = p.status || '';

    const sourceSelect = `<select class="plan-source" data-lid="${l.id}" style="padding:4px 6px; border:1px solid var(--border); border-radius:4px; font-size:12px; max-width:160px;">
      <option value="">-- select --</option>
      ${assetOptions}
    </select>`;

    const strategySelect = `<select class="plan-strategy" data-lid="${l.id}" onchange="planStrategyChanged(${l.id})" style="padding:4px 6px; border:1px solid var(--border); border-radius:4px; font-size:12px;">
      ${strategies.map(s => `<option value="${s}" ${s === selectedStrategy ? 'selected' : ''} title="${strategyLabels[s] || s}">${s.replace(/_/g, ' ')}</option>`).join('')}
    </select>`;

    const statusBadge = status ? _cycleBadge(status) : '<span style="color:var(--text-muted); font-size:11px;">unassigned</span>';
    const canPay = selectedSource && status !== 'completed';
    const rowClass = status === 'overdue' ? 'planner-row-overdue' : (status === 'completed' ? 'planner-row-paid' : '');

    return `<tr class="${rowClass}">
      <td><strong>${esc(l.name)}</strong>${l.last_four ? ` <span style="color:var(--text-muted);">(${esc(l.last_four)})</span>` : ''}</td>
      <td style="text-align:right; font-variant-numeric:tabular-nums;">${_fmt(l.balance)}</td>
      <td style="text-align:right; font-variant-numeric:tabular-nums;">${l.last_statement_balance != null ? _fmt(l.last_statement_balance) : '-'}</td>
      <td>${sourceSelect}</td>
      <td>${strategySelect}</td>
      <td><input type="number" step="0.01" class="plan-amount" data-lid="${l.id}" value="${plannedAmt}" style="width:100px; padding:4px 8px; border:1px solid var(--border); border-radius:4px; text-align:right; font-variant-numeric:tabular-nums;" /></td>
      <td>${statusBadge}</td>
      <td>
        <button class="btn btn-primary btn-sm" onclick="openMarkPaid(${l.id})" ${!canPay ? 'disabled style="opacity:0.5;"' : ''}>Pay</button>
      </td>
    </tr>`;
  }).join('');

  // Totals footer
  const totalPlanned = liabilities.reduce((sum, l) => {
    const p = planMap[l.id];
    return sum + (p && p.planned_amount != null ? parseFloat(p.planned_amount) : 0);
  }, 0);
  const totalBalance = liabilities.reduce((sum, l) => sum + Math.abs(parseFloat(l.balance || 0)), 0);
  const tfoot = tbody.closest('table').tFoot || tbody.closest('table').createTFoot();
  tfoot.innerHTML = `<tr class="planner-totals-footer">
    <td>Totals</td>
    <td style="text-align:right; font-variant-numeric:tabular-nums;">${_fmt(totalBalance)}</td>
    <td></td><td></td><td></td>
    <td style="text-align:right; font-variant-numeric:tabular-nums;">${totalPlanned > 0 ? _fmt(totalPlanned) : '—'}</td>
    <td colspan="2"></td>
  </tr>`;

  // Set selected source values after DOM render
  liabilities.forEach(l => {
    const p = planMap[l.id];
    if (p && p.source_id) {
      const sel = document.querySelector(`.plan-source[data-lid="${l.id}"]`);
      if (sel) sel.value = p.source_id;
    }
  });
}

function planStrategyChanged(liabilityId) {
  const strategy = document.querySelector(`.plan-strategy[data-lid="${liabilityId}"]`).value;
  const amtInput = document.querySelector(`.plan-amount[data-lid="${liabilityId}"]`);
  const acct = _accountsCache.find(a => a.id === liabilityId);
  if (!acct) return;

  if (strategy === 'statement' && acct.last_statement_balance != null) {
    amtInput.value = Math.abs(parseFloat(acct.last_statement_balance)).toFixed(2);
  } else if (strategy === 'minimum' && acct.minimum_payment_amount != null) {
    amtInput.value = parseFloat(acct.minimum_payment_amount).toFixed(2);
  } else if (strategy === 'full_balance' && acct.balance != null) {
    amtInput.value = Math.abs(parseFloat(acct.balance)).toFixed(2);
  }
}

async function savePlanAssignments() {
  const month = _getPlannerMonth();
  const assignments = [];
  document.querySelectorAll('.plan-source').forEach(sel => {
    const lid = parseInt(sel.dataset.lid);
    const sourceId = sel.value;
    if (!sourceId) return;
    const strategy = document.querySelector(`.plan-strategy[data-lid="${lid}"]`).value;
    const amtInput = document.querySelector(`.plan-amount[data-lid="${lid}"]`);
    const amt = amtInput.value.trim() ? parseFloat(amtInput.value) : null;

    assignments.push({
      liability_id: lid,
      source_id: parseInt(sourceId),
      cycle_month: month,
      planned_amount: amt,
      strategy: strategy,
      status: 'planned',
    });
  });

  if (!assignments.length) {
    toast('No assignments to save. Select a payment source for at least one liability.', 'info');
    return;
  }

  try {
    await api('POST', '/accounts/payments/plan', { assignments });
    toast(`Saved ${assignments.length} assignment(s)`, 'success');
    loadPlannerData();
  } catch (e) {
    toast('Failed to save assignments: ' + e.message, 'error');
  }
}

async function rollforwardPlan() {
  const toMonth = _getPlannerMonth();
  const d = new Date(toMonth + '-01');
  d.setMonth(d.getMonth() - 1);
  const fromMonth = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0');

  try {
    const result = await api('POST', '/accounts/payments/plan/rollforward', {
      from_month: fromMonth, to_month: toMonth,
    });
    toast(`Rolled forward: ${result.created} created, ${result.skipped} skipped`, 'success');
    loadPlannerData();
  } catch (e) {
    toast('Rollforward failed: ' + e.message, 'error');
  }
}

function openMarkPaid(liabilityId) {
  const acct = _accountsCache.find(a => a.id === liabilityId);
  if (!acct) return;

  const sourceSelect = document.querySelector(`.plan-source[data-lid="${liabilityId}"]`);
  const sourceId = sourceSelect ? sourceSelect.value : '';
  const sourceAcct = _accountsCache.find(a => a.id === parseInt(sourceId));

  const amtInput = document.querySelector(`.plan-amount[data-lid="${liabilityId}"]`);
  const plannedAmt = amtInput ? amtInput.value : '';

  document.getElementById('mp-liability-id').value = liabilityId;
  document.getElementById('mp-source-id').value = sourceId;
  document.getElementById('mp-liability-name').textContent = acct.name + (acct.last_four ? ` (${acct.last_four})` : '');
  document.getElementById('mp-source-name').textContent = sourceAcct ? sourceAcct.name : 'Unknown';
  document.getElementById('mp-amount').value = plannedAmt;
  document.getElementById('mp-date').value = new Date().toISOString().slice(0, 10);
  document.getElementById('mp-confirmation').value = '';
  document.getElementById('mp-notes').value = '';
  document.getElementById('mark-paid-modal').style.display = 'flex';
}

function closeMarkPaidModal() {
  document.getElementById('mark-paid-modal').style.display = 'none';
}

async function submitPayment() {
  const fromId = parseInt(document.getElementById('mp-source-id').value);
  const toId = parseInt(document.getElementById('mp-liability-id').value);
  const amount = parseFloat(document.getElementById('mp-amount').value);
  const date = document.getElementById('mp-date').value;
  const ref = document.getElementById('mp-confirmation').value.trim();
  const notes = document.getElementById('mp-notes').value.trim();

  if (!fromId || !toId || !amount || !date) {
    toast('Please fill in all required fields', 'error');
    return;
  }

  try {
    await api('POST', '/accounts/payments/', {
      from_account_id: fromId,
      to_account_id: toId,
      payment_date: date,
      amount: amount,
      confirmation_ref: ref || null,
      notes: notes || null,
    });
    toast('Payment recorded', 'success');
    closeMarkPaidModal();
    loadPlannerData();
    loadAccounts();
  } catch (e) {
    toast('Failed to record payment: ' + e.message, 'error');
  }
}

function _renderPaymentHistory(payments) {
  const tbody = document.getElementById('planner-payments-body');
  if (!payments.length) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; padding:16px; color:var(--text-muted);">No payments recorded yet.</td></tr>';
    return;
  }
  const acctMap = {};
  _accountsCache.forEach(a => { acctMap[a.id] = a; });

  tbody.innerHTML = payments.map(p => {
    const fromName = acctMap[p.from_account_id] ? esc(acctMap[p.from_account_id].name) : `#${p.from_account_id}`;
    const toName = acctMap[p.to_account_id] ? esc(acctMap[p.to_account_id].name) : `#${p.to_account_id}`;
    return `<tr>
      <td>${esc(p.payment_date)}</td>
      <td>${fromName}</td>
      <td>${toName}</td>
      <td style="text-align:right; font-variant-numeric:tabular-nums;">${_fmt(p.amount)}</td>
      <td>${esc(p.payment_type || 'manual')}</td>
      <td>${_cycleBadge(p.status || 'pending')}</td>
      <td style="font-size:12px; color:var(--text-muted);">${p.confirmation_ref ? esc(p.confirmation_ref) : '-'}</td>
    </tr>`;
  }).join('');
}

// ── History & Trends ────────────────────────────────────────────────

async function _loadTrendsData() {
  try {
    const [utilization, interest, fees, paymentSummary] = await Promise.all([
      api('GET', '/accounts/analytics/utilization'),
      api('GET', '/accounts/analytics/interest-cost'),
      api('GET', '/accounts/analytics/annual-fees'),
      api('GET', '/accounts/analytics/payment-summary?months=12'),
    ]);
    _renderUtilization(utilization);
    _renderInterestCost(interest);
    _renderAnnualFees(fees);
    _renderPaymentSummaryChart(paymentSummary);
    _populateAccountTrendSelect();
    loadPayoffProjection();
    _loadNetWorthTrend();
  } catch (e) {
    toast('Failed to load trends data: ' + e.message, 'error');
  }
}

async function _loadNetWorthTrend() {
  try {
    const data = await api('GET', '/accounts/analytics/trends/aggregate?months=24');
    _renderNetWorthChart(data);
  } catch (e) {
    // Silently degrade — no snapshots yet
    const el = document.getElementById('trends-networth-chart');
    if (el) el.innerHTML = '<span style="color:var(--text-muted); font-size:13px; padding:20px;">No snapshot data yet. Update balances to generate snapshots.</span>';
  }
}

function _renderNetWorthChart(data) {
  const el = document.getElementById('trends-networth-chart');
  const legendEl = document.getElementById('trends-networth-legend');
  if (!el) return;

  if (!data.length) {
    el.innerHTML = '<span style="color:var(--text-muted); font-size:13px; padding:20px;">No snapshot data yet. Update balances to generate snapshots.</span>';
    if (legendEl) legendEl.innerHTML = '';
    return;
  }

  const chartH = 180;
  const maxVal = Math.max(...data.flatMap(d => [d.total_assets, d.total_liabilities]), 1);

  // Net worth delta headline
  const latest = data[data.length - 1];
  const prev = data.length >= 2 ? data[data.length - 2] : null;
  let deltaHtml = '';
  if (prev && latest) {
    const delta = latest.net_worth - prev.net_worth;
    const sign = delta >= 0 ? '+' : '';
    const color = delta >= 0 ? 'var(--success)' : 'var(--danger)';
    deltaHtml = `<div style="font-size:13px; margin-bottom:8px;">
      Net worth <strong style="font-size:18px;">${_fmt(latest.net_worth)}</strong>
      <span style="color:${color}; margin-left:8px;">${sign}${_fmt(delta)} vs last snapshot</span>
    </div>`;
  }
  el.insertAdjacentHTML('beforebegin', deltaHtml);

  el.innerHTML = data.map((d, i) => {
    const assH = Math.max(Math.round(d.total_assets / maxVal * chartH), 2);
    const liabH = Math.max(Math.round(d.total_liabilities / maxVal * chartH), 2);
    const label = d.date ? String(d.date).slice(0, 7) : '?';
    const tooltipHtml = `<div class="nw-bar-tooltip">
      <div style="font-weight:700; margin-bottom:4px;">${label}</div>
      <div style="color:#22c55e;">Assets: ${_fmt(d.total_assets)}</div>
      <div style="color:#ef4444;">Liabilities: ${_fmt(d.total_liabilities)}</div>
      <div style="border-top:1px solid var(--border); margin-top:4px; padding-top:4px; font-weight:600;">Net: ${_fmt(d.net_worth)}</div>
    </div>`;
    return `<div class="nw-bar-group" style="flex:1; display:flex; flex-direction:column; align-items:center; min-width:24px;"
        onclick="this.classList.toggle('tip-open')" onmouseleave="this.classList.remove('tip-open')">
      ${tooltipHtml}
      <div style="display:flex; gap:1px; align-items:flex-end; height:${chartH}px;">
        <div style="width:10px; height:${assH}px; background:#22c55e; border-radius:2px 2px 0 0;"></div>
        <div style="width:10px; height:${liabH}px; background:#ef4444; border-radius:2px 2px 0 0;"></div>
      </div>
      <div style="font-size:9px; color:var(--text-muted); margin-top:2px; white-space:nowrap;">${label.slice(5)}</div>
    </div>`;
  }).join('');

  if (legendEl) {
    legendEl.innerHTML = `
      <span><span style="display:inline-block; width:10px; height:10px; border-radius:2px; background:#22c55e; vertical-align:middle; margin-right:4px;"></span> Assets</span>
      <span><span style="display:inline-block; width:10px; height:10px; border-radius:2px; background:#ef4444; vertical-align:middle; margin-right:4px;"></span> Liabilities</span>
    `;
  }
}

function _renderUtilization(data) {
  const aggEl = document.getElementById('trends-utilization-aggregate');
  const cardsEl = document.getElementById('trends-utilization-cards');
  if (!aggEl) return;

  const agg = data.aggregate;
  const pct = agg.utilization_pct;
  const barColor = pct > 80 ? 'var(--danger)' : pct > 30 ? 'var(--warning, #f59e0b)' : 'var(--primary)';

  aggEl.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
      <span style="font-weight:700; font-size:16px;">Aggregate: ${pct}%</span>
      <span style="color:var(--text-muted); font-size:13px;">${_fmt(agg.total_balance)} / ${_fmt(agg.total_limit)} &mdash; ${_fmt(agg.available_credit)} available</span>
    </div>
    <div style="background:var(--bg-secondary); border-radius:6px; height:12px; overflow:hidden;">
      <div style="width:${Math.min(pct, 100)}%; height:100%; background:${barColor}; border-radius:6px; transition:width 0.3s;"></div>
    </div>
    ${pct > 30 ? '<div style="color:var(--danger); font-size:12px; margin-top:4px;">Above 30% FICO threshold</div>' : '<div style="color:var(--success); font-size:12px; margin-top:4px;">Below 30% FICO threshold</div>'}
  `;

  if (!data.cards.length) {
    cardsEl.innerHTML = '<p style="color:var(--text-muted);">No credit cards with limits found.</p>';
    return;
  }

  cardsEl.innerHTML = `<table style="width:100%;">
    <thead><tr>
      <th>Card</th><th>Institution</th>
      <th style="text-align:right;">Balance</th>
      <th style="text-align:right;">Limit</th>
      <th style="text-align:right;">Utilization</th>
      <th style="text-align:right;">Available</th>
      <th style="width:120px;">Bar</th>
    </tr></thead>
    <tbody>${data.cards.map(c => {
      const u = c.utilization_pct;
      const bc = u > 80 ? 'var(--danger)' : u > 30 ? 'var(--warning, #f59e0b)' : 'var(--primary)';
      return `<tr>
        <td>${esc(c.name)}${c.last_four ? ` <span style="color:var(--text-muted);">(${esc(c.last_four)})</span>` : ''}</td>
        <td>${esc(c.institution || '-')}</td>
        <td style="text-align:right; font-variant-numeric:tabular-nums;">${_fmt(c.balance)}</td>
        <td style="text-align:right; font-variant-numeric:tabular-nums;">${_fmt(c.credit_limit)}</td>
        <td style="text-align:right; font-weight:600; color:${bc};">${u}%</td>
        <td style="text-align:right; font-variant-numeric:tabular-nums;">${_fmt(c.available_credit)}</td>
        <td><div style="background:var(--bg-secondary); border-radius:4px; height:6px;"><div style="width:${Math.min(u, 100)}%; height:100%; background:${bc}; border-radius:4px;"></div></div></td>
      </tr>`;
    }).join('')}</tbody>
  </table>`;
}

function _renderInterestCost(data) {
  const summaryEl = document.getElementById('trends-interest-summary');
  const tbody = document.getElementById('trends-interest-body');
  if (!summaryEl) return;

  summaryEl.innerHTML = `
    <div style="display:flex; gap:24px; flex-wrap:wrap;">
      <div><span style="color:var(--text-muted); font-size:12px; text-transform:uppercase;">Monthly Interest</span><div style="font-size:20px; font-weight:700; color:var(--danger);">${_fmt(data.total_monthly_interest)}</div></div>
      <div><span style="color:var(--text-muted); font-size:12px; text-transform:uppercase;">Annual Interest</span><div style="font-size:20px; font-weight:700; color:var(--danger);">${_fmt(data.total_annual_interest)}</div></div>
    </div>
  `;

  if (!data.accounts.length) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color:var(--text-muted);">No accounts with interest rates.</td></tr>';
    return;
  }

  tbody.innerHTML = data.accounts.map(a => `<tr>
    <td>${esc(a.name)}${a.last_four ? ` <span style="color:var(--text-muted);">(${esc(a.last_four)})</span>` : ''}</td>
    <td style="text-align:right; font-variant-numeric:tabular-nums;">${_fmt(a.balance)}</td>
    <td style="text-align:right;">${a.apr}%</td>
    <td style="text-align:right; font-variant-numeric:tabular-nums; color:var(--danger);">${_fmt(a.monthly_interest)}</td>
    <td style="text-align:right; font-variant-numeric:tabular-nums; color:var(--danger);">${_fmt(a.annual_interest)}</td>
  </tr>`).join('');
}

async function loadPayoffProjection() {
  const strategy = document.getElementById('trends-payoff-strategy')?.value || 'statement';
  const hints = {
    minimum: 'Slowest payoff, highest total interest.',
    statement: 'Pays statement balance in full — avoids interest on revolving credit.',
    aggressive: 'Doubles the minimum payment; reduces term significantly.',
  };
  const hintEl = document.getElementById('trends-payoff-strategy-hint');
  if (hintEl) hintEl.textContent = hints[strategy] || '';
  try {
    const data = await api('GET', `/accounts/analytics/payoff-projection?strategy=${strategy}`);
    _renderPayoffProjection(data);
  } catch (e) {
    toast('Failed to load payoff projection: ' + e.message, 'error');
  }
}

function _renderPayoffProjection(data) {
  const tbody = document.getElementById('trends-payoff-body');
  if (!tbody) return;

  if (!data.length) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; color:var(--text-muted);">No liabilities with balances.</td></tr>';
    return;
  }

  tbody.innerHTML = data.map(a => {
    let monthsLabel;
    if (a.months_to_payoff == null) {
      monthsLabel = '<span style="color:var(--danger);">Never</span>';
    } else if (a.months_to_payoff >= 24) {
      const yrs = (a.months_to_payoff / 12).toFixed(1);
      monthsLabel = `<span title="${a.months_to_payoff} months">${yrs} yrs</span>`;
    } else {
      monthsLabel = `${a.months_to_payoff} mo`;
    }
    return `<tr>
      <td>${esc(a.name)}</td>
      <td style="text-align:right; font-variant-numeric:tabular-nums;">${_fmt(a.balance)}</td>
      <td style="text-align:right;">${a.apr}%</td>
      <td style="text-align:right; font-variant-numeric:tabular-nums;">${_fmt(a.monthly_payment)}</td>
      <td style="text-align:right; font-weight:600;">${monthsLabel}</td>
      <td style="text-align:right; font-variant-numeric:tabular-nums; color:var(--danger);">${_fmt(a.total_interest)}</td>
      <td style="text-align:right; font-variant-numeric:tabular-nums;">${_fmt(a.total_cost)}</td>
    </tr>`;
  }).join('');
}

function _renderAnnualFees(data) {
  const totalEl = document.getElementById('trends-fees-total');
  const chartEl = document.getElementById('trends-fees-chart');
  const tbody = document.getElementById('trends-fees-body');
  if (!totalEl) return;

  totalEl.innerHTML = `<span style="font-size:18px; font-weight:700;">Total Annual Fees: ${_fmt(data.total_annual_fees)}</span>`;

  // Bar chart by month
  const maxMonthly = Math.max(...data.by_month.map(m => m.total), 1);
  const chartH = 100;
  chartEl.innerHTML = data.by_month.map(m => {
    const h = m.total > 0 ? Math.max(Math.round(m.total / maxMonthly * chartH), 4) : 0;
    return `<div style="flex:1; display:flex; flex-direction:column; align-items:center; min-width:24px;" title="${m.month_name}: ${_fmt(m.total)} (${m.count} card${m.count !== 1 ? 's' : ''})">
      <div style="width:80%; height:${h}px; background:${m.total > 0 ? 'var(--primary)' : 'transparent'}; border-radius:2px 2px 0 0; margin-top:auto;"></div>
      <div style="font-size:10px; color:var(--text-muted); margin-top:2px;">${m.month_name.slice(0, 3)}</div>
    </div>`;
  }).join('');

  if (!data.accounts.length) {
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color:var(--text-muted);">No accounts with annual fees.</td></tr>';
    return;
  }
  tbody.innerHTML = data.accounts.map(a => `<tr>
    <td>${esc(a.name)}${a.last_four ? ` <span style="color:var(--text-muted);">(${esc(a.last_four)})</span>` : ''}</td>
    <td>${esc(a.institution || '-')}</td>
    <td style="text-align:right; font-variant-numeric:tabular-nums;">${_fmt(a.annual_fee)}</td>
    <td>${a.fee_month_name}</td>
  </tr>`).join('');
}

function _renderPaymentSummaryChart(data) {
  const el = document.getElementById('trends-payment-chart');
  const legendEl = document.getElementById('trends-payment-legend');
  if (!el) return;

  if (!data.length) {
    el.innerHTML = '<span style="color:var(--text-muted); font-size:13px; padding:20px;">No payment data yet.</span>';
    if (legendEl) legendEl.innerHTML = '';
    return;
  }

  const chartH = 120;
  const maxVal = Math.max(...data.map(d => d.total), 1);

  el.innerHTML = data.map(d => {
    const h = Math.max(Math.round(d.total / maxVal * chartH), 4);
    return `<div style="flex:1; display:flex; flex-direction:column; align-items:center; min-width:30px;" title="${d.month}: ${_fmt(d.total)} (${d.count} payments)">
      <div style="font-size:10px; color:var(--text-muted); margin-bottom:2px;">${_fmt(d.total)}</div>
      <div style="width:70%; height:${h}px; background:var(--primary); border-radius:2px 2px 0 0; margin-top:auto;"></div>
      <div style="font-size:10px; color:var(--text-muted); margin-top:2px;">${d.month.slice(5)}</div>
    </div>`;
  }).join('');

  if (legendEl) {
    const totalAll = data.reduce((s, d) => s + d.total, 0);
    legendEl.innerHTML = `<span style="color:var(--text-muted);">Total: ${_fmt(totalAll)} across ${data.reduce((s, d) => s + d.count, 0)} payments</span>`;
  }
}

function _populateAccountTrendSelect() {
  const sel = document.getElementById('trends-account-select');
  if (!sel) return;
  const current = sel.value;
  sel.innerHTML = '<option value="">Select an account...</option>' +
    _accountsCache.map(a => `<option value="${a.id}">${esc(a.name)} (${a.account_class})</option>`).join('');
  if (current) sel.value = current;
}

async function loadAccountBalanceTrend() {
  const acctId = document.getElementById('trends-account-select')?.value;
  const chartEl = document.getElementById('trends-account-chart');
  const labelsEl = document.getElementById('trends-account-labels');
  if (!acctId || !chartEl) return;

  try {
    const data = await api('GET', `/accounts/analytics/trends/${acctId}?limit=24`);
    if (!data.length) {
      chartEl.innerHTML = '<span style="color:var(--text-muted); font-size:13px;">No balance history for this account.</span>';
      if (labelsEl) labelsEl.innerHTML = '';
      return;
    }

    const chartH = 140;
    const balances = data.map(d => Math.abs(d.balance));
    const maxVal = Math.max(...balances, 1);

    chartEl.innerHTML = data.map(d => {
      const bal = Math.abs(d.balance);
      const h = Math.max(Math.round(bal / maxVal * chartH), 2);
      return `<div style="flex:1; display:flex; flex-direction:column; align-items:center; min-width:12px;" title="${d.date}: ${_fmt(d.balance)}">
        <div style="width:80%; height:${h}px; background:var(--primary); border-radius:2px 2px 0 0; margin-top:auto;"></div>
      </div>`;
    }).join('');

    if (labelsEl && data.length > 0) {
      labelsEl.innerHTML = `<span>${data[0].date}</span><span>${data[data.length - 1].date}</span>`;
    }
  } catch (e) {
    chartEl.innerHTML = '<span style="color:var(--text-muted);">Failed to load trend.</span>';
  }
}

// ── Import Wizard ───────────────────────────────────────────────────

let _importState = { fileData: null, scenario: 'single', mapping: {}, sections: {}, preview: null };

function openImportWizard() {
  _importState = { fileData: null, scenario: 'single', mapping: {}, sections: {}, preview: null };
  document.getElementById('import-wizard-modal').style.display = 'flex';
  document.getElementById('import-step-0').style.display = '';
  document.getElementById('import-step-1').style.display = 'none';
  document.getElementById('import-step-2').style.display = 'none';
  document.getElementById('import-step-3').style.display = 'none';
  document.getElementById('import-file-input').value = '';
  document.getElementById('import-file-name').textContent = '';
  document.getElementById('import-next-0').disabled = true;
}

function closeImportWizard() {
  document.getElementById('import-wizard-modal').style.display = 'none';
}

function importWizardBack(step) {
  document.getElementById(`import-step-${step}`).style.display = 'none';
  document.getElementById(`import-step-${step + 1}`).style.display = 'none';
  document.getElementById(`import-step-${step}`).style.display = '';
}

async function handleImportFileSelect(input) {
  const file = input.files[0];
  if (!file) return;
  document.getElementById('import-file-name').textContent = file.name;

  // Upload to temp and detect
  const formData = new FormData();
  formData.append('file', file);
  try {
    const uploadRes = await fetch('/upload-temp', { method: 'POST', body: formData });
    if (!uploadRes.ok) throw new Error('Upload failed');
    const { path } = await uploadRes.json();

    const data = await api('POST', `/accounts/import/detect?file_path=${encodeURIComponent(path)}`);
    _importState.fileData = data;
    _importState.fileData.uploaded_path = path;
    document.getElementById('import-next-0').disabled = false;
  } catch (e) {
    // Fallback: read file client-side for CSV
    if (file.name.endsWith('.csv')) {
      const text = await file.text();
      const lines = text.split('\n').filter(l => l.trim());
      const headers = lines[0].split(',').map(h => h.trim().replace(/^"|"$/g, ''));
      const rows = lines.slice(1).map(l => l.split(',').map(c => c.trim().replace(/^"|"$/g, '')));
      _importState.fileData = {
        file_type: 'csv', headers, row_count: rows.length,
        preview_rows: rows.slice(0, 10), all_rows: rows, boundaries: [],
      };
      document.getElementById('import-next-0').disabled = false;
    } else {
      toast('Failed to process file: ' + e.message, 'error');
    }
  }
}

function importWizardStep1() {
  _importState.scenario = document.querySelector('input[name="import-scenario"]:checked')?.value || 'single';
  document.getElementById('import-step-0').style.display = 'none';
  document.getElementById('import-step-1').style.display = '';

  const container = document.getElementById('import-preview-container');
  const fd = _importState.fileData;
  if (!fd) return;

  if (_importState.scenario === 'single') {
    // Show row range selector
    const boundaries = fd.boundaries || [];
    const suggestedSplit = boundaries.find(b => b.type === 'blank' || b.type === 'total');
    const splitRow = suggestedSplit ? suggestedSplit.row : Math.floor(fd.row_count / 2);

    container.innerHTML = `
      <h4 style="margin-bottom:8px;">Assign Row Ranges</h4>
      <p style="color:var(--text-muted); font-size:13px; margin-bottom:12px;">
        Tell us which rows contain liabilities (credit cards, loans) and which contain assets (bank accounts).
        ${boundaries.length ? `<br>We detected ${boundaries.length} section boundary(s).` : ''}
      </p>
      <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:16px;">
        <div style="padding:12px; border:2px solid var(--danger); border-radius:8px;">
          <strong style="color:var(--danger);">Liabilities</strong>
          <div style="display:flex; gap:8px; margin-top:8px;">
            <label style="font-size:12px;">Start: <input type="number" id="import-liab-start" value="1" min="1" style="width:60px; padding:4px; border:1px solid var(--border); border-radius:4px;" /></label>
            <label style="font-size:12px;">End: <input type="number" id="import-liab-end" value="${splitRow > 1 ? splitRow - 1 : fd.row_count}" min="1" style="width:60px; padding:4px; border:1px solid var(--border); border-radius:4px;" /></label>
          </div>
        </div>
        <div style="padding:12px; border:2px solid var(--success); border-radius:8px;">
          <strong style="color:var(--success);">Assets</strong>
          <div style="display:flex; gap:8px; margin-top:8px;">
            <label style="font-size:12px;">Start: <input type="number" id="import-asset-start" value="${splitRow > 1 ? splitRow + 1 : 1}" min="1" style="width:60px; padding:4px; border:1px solid var(--border); border-radius:4px;" /></label>
            <label style="font-size:12px;">End: <input type="number" id="import-asset-end" value="${fd.row_count}" min="1" style="width:60px; padding:4px; border:1px solid var(--border); border-radius:4px;" /></label>
          </div>
        </div>
      </div>
      <div style="max-height:300px; overflow:auto; border:1px solid var(--border); border-radius:4px;">
        <table style="width:100%; font-size:12px;">
          <thead><tr><th style="width:30px;">#</th>${fd.headers.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead>
          <tbody>${(fd.preview_rows || []).map((r, i) => `<tr style="background:${i < 5 ? 'rgba(239,68,68,0.05)' : 'rgba(34,197,94,0.05)'};">
            <td style="color:var(--text-muted);">${i + 1}</td>${r.map(c => `<td>${esc(String(c))}</td>`).join('')}
          </tr>`).join('')}</tbody>
        </table>
      </div>
    `;
  } else {
    // Two files scenario - just use all rows as liabilities for first file
    container.innerHTML = `
      <h4 style="margin-bottom:8px;">File Detected</h4>
      <p style="color:var(--text-muted); font-size:13px; margin-bottom:12px;">
        This file will be imported as <strong>liability</strong> accounts. You can import asset accounts separately after.
      </p>
      <div style="margin-bottom:8px;">
        <label style="font-weight:600;">Import as:</label>
        <select id="import-section-type" style="padding:4px 8px; border:1px solid var(--border); border-radius:4px; margin-left:8px;">
          <option value="liability">Liabilities (credit cards, loans)</option>
          <option value="asset">Assets (bank accounts)</option>
        </select>
      </div>
      <div style="max-height:200px; overflow:auto; border:1px solid var(--border); border-radius:4px;">
        <table style="width:100%; font-size:12px;">
          <thead><tr>${fd.headers.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead>
          <tbody>${(fd.preview_rows || []).slice(0, 5).map(r => `<tr>${r.map(c => `<td>${esc(String(c))}</td>`).join('')}</tr>`).join('')}</tbody>
        </table>
      </div>
    `;
  }
}

function importWizardStep2() {
  document.getElementById('import-step-1').style.display = 'none';
  document.getElementById('import-step-2').style.display = '';

  const fd = _importState.fileData;
  const container = document.getElementById('import-mapping-container');

  // Determine sections to map
  const sections = [];
  if (_importState.scenario === 'single') {
    sections.push({
      type: 'liability', label: 'Liabilities',
      start: parseInt(document.getElementById('import-liab-start')?.value) || 1,
      end: parseInt(document.getElementById('import-liab-end')?.value) || fd.row_count,
    });
    sections.push({
      type: 'asset', label: 'Assets',
      start: parseInt(document.getElementById('import-asset-start')?.value) || 1,
      end: parseInt(document.getElementById('import-asset-end')?.value) || fd.row_count,
    });
  } else {
    const sectionType = document.getElementById('import-section-type')?.value || 'liability';
    sections.push({ type: sectionType, label: sectionType === 'liability' ? 'Liabilities' : 'Assets', start: 1, end: fd.row_count });
  }
  _importState.sections = sections;

  // Build mapping UI for each section (using same headers for single-file)
  const headers = fd.headers;
  const fields_liab = ['account_name', 'current_balance', 'statement_balance', 'minimum_payment', 'due_date', 'credit_limit', 'interest_rate', 'payment_source', 'institution', 'last_four', 'notes'];
  const fields_asset = ['account_name', 'current_balance', 'institution', 'payment_source_tag', 'notes'];

  const headerOpts = '<option value="">-- skip --</option>' + headers.map(h => `<option value="${esc(h)}">${esc(h)}</option>`).join('');

  // Auto-suggest
  const suggestions = {};
  for (const s of sections) {
    suggestions[s.type] = _autoSuggestMappings(headers, s.type);
  }

  container.innerHTML = sections.map(s => {
    const fields = s.type === 'liability' ? fields_liab : fields_asset;
    const sugg = suggestions[s.type] || {};
    return `<div style="margin-bottom:20px;">
      <h4 style="margin-bottom:8px;">${esc(s.label)} (rows ${s.start}–${s.end})</h4>
      <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px;">
        ${fields.map(f => {
          const label = f.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
          const req = (f === 'account_name' || f === 'current_balance') ? ' *' : '';
          return `<div>
            <label style="font-size:12px; font-weight:${req ? '700' : '400'};">${label}${req}</label>
            <select class="import-mapping" data-section="${s.type}" data-field="${f}" style="width:100%; padding:4px 8px; border:1px solid var(--border); border-radius:4px; font-size:12px;">
              ${headerOpts}
            </select>
          </div>`;
        }).join('')}
      </div>
    </div>`;
  }).join('');

  // Set auto-suggested values
  for (const s of sections) {
    const sugg = suggestions[s.type];
    for (const [field, header] of Object.entries(sugg)) {
      if (header) {
        const sel = document.querySelector(`.import-mapping[data-section="${s.type}"][data-field="${field}"]`);
        if (sel) sel.value = header;
      }
    }
  }
}

function _autoSuggestMappings(headers, sectionType) {
  const keywords = {
    account_name: ['account', 'name', 'vendor', 'payee', 'creditor', 'card', 'description'],
    current_balance: ['balance', 'current', 'owed', 'outstanding', 'amount'],
    statement_balance: ['statement', 'amountdue', 'billed'],
    minimum_payment: ['minimum', 'minpayment', 'min'],
    due_date: ['due', 'duedate', 'paymentdue', 'day'],
    credit_limit: ['limit', 'creditlimit'],
    interest_rate: ['apr', 'rate', 'interest'],
    payment_source: ['source', 'payfrom', 'pay from'],
    institution: ['bank', 'issuer', 'institution', 'provider'],
    last_four: ['last4', 'lastfour', 'ending'],
    notes: ['notes', 'memo', 'comment'],
    payment_source_tag: ['tag', 'code', 'shortcode'],
  };
  const result = {};
  const used = new Set();
  const fields = sectionType === 'liability'
    ? ['account_name', 'current_balance', 'statement_balance', 'minimum_payment', 'due_date', 'credit_limit', 'interest_rate', 'payment_source', 'institution', 'last_four', 'notes']
    : ['account_name', 'current_balance', 'institution', 'payment_source_tag', 'notes'];

  for (const field of fields) {
    const kws = keywords[field] || [];
    for (const h of headers) {
      if (used.has(h)) continue;
      const norm = h.toLowerCase().replace(/[^a-z0-9]/g, '');
      if (kws.some(kw => norm.includes(kw))) {
        result[field] = h;
        used.add(h);
        break;
      }
    }
  }
  return result;
}

async function importWizardStep3() {
  document.getElementById('import-step-2').style.display = 'none';
  document.getElementById('import-step-3').style.display = '';

  const fd = _importState.fileData;
  const allRows = fd.all_rows || fd.preview_rows || [];
  let allAccounts = [];

  for (const section of _importState.sections) {
    // Collect mapping
    const mapping = {};
    document.querySelectorAll(`.import-mapping[data-section="${section.type}"]`).forEach(sel => {
      if (sel.value) mapping[sel.dataset.field] = sel.value;
    });

    // Get rows for this section
    const sectionRows = allRows.slice(section.start - 1, section.end);

    // Build preview locally
    const headers = fd.headers;
    const headerIdx = {};
    headers.forEach((h, i) => { headerIdx[h] = i; });

    for (const row of sectionRows) {
      const getName = (field) => {
        const col = mapping[field];
        if (!col || !(col in headerIdx)) return null;
        const idx = headerIdx[col];
        return idx < row.length ? String(row[idx]).trim() : null;
      };
      const name = getName('account_name');
      if (!name) continue;

      const parseNum = (v) => {
        if (!v) return null;
        const cleaned = v.replace(/[$€£,\s]/g, '').replace(/^\((.+)\)$/, '-$1');
        const n = parseFloat(cleaned);
        return isNaN(n) ? null : Math.round(n * 100) / 100;
      };

      allAccounts.push({
        account_name: name,
        current_balance: parseNum(getName('current_balance')) || 0,
        account_class: section.type,
        inferred_type: _inferType(name, section.type),
        statement_balance: parseNum(getName('statement_balance')),
        minimum_payment: parseNum(getName('minimum_payment')),
        due_date: getName('due_date'),
        credit_limit: parseNum(getName('credit_limit')),
        interest_rate: parseNum(getName('interest_rate')),
        payment_source: getName('payment_source') || getName('payment_source_tag'),
        institution: getName('institution'),
        last_four: getName('last_four'),
        notes: getName('notes'),
      });
    }
  }

  _importState.preview = allAccounts;

  // Render preview
  const container = document.getElementById('import-commit-preview');
  if (!allAccounts.length) {
    container.innerHTML = '<p style="color:var(--text-muted);">No accounts found. Check your column mappings and row ranges.</p>';
    return;
  }

  container.innerHTML = `
    <h4 style="margin-bottom:8px;">Ready to import ${allAccounts.length} account(s)</h4>
    <div style="max-height:400px; overflow:auto; border:1px solid var(--border); border-radius:4px;">
      <table style="width:100%; font-size:12px;">
        <thead><tr><th>Account</th><th>Type</th><th style="text-align:right;">Balance</th><th>Institution</th><th>Source</th></tr></thead>
        <tbody>${allAccounts.map(a => `<tr>
          <td><strong>${esc(a.account_name)}</strong>${a.last_four ? ` (${esc(a.last_four)})` : ''}</td>
          <td>${esc(a.inferred_type || a.account_class)}</td>
          <td style="text-align:right; font-variant-numeric:tabular-nums;">${_fmt(a.current_balance)}</td>
          <td>${esc(a.institution || '-')}</td>
          <td>${esc(a.payment_source || '-')}</td>
        </tr>`).join('')}</tbody>
      </table>
    </div>
  `;
}

function _inferType(name, defaultClass) {
  const n = name.toLowerCase();
  const patterns = [
    [/mortgage|home\s*loan/, 'mortgage'], [/auto|car|truck|bronco|subaru|toyota|honda|ford/, 'auto_loan'],
    [/student|school|navient|mohela/, 'student_loan'], [/energy|electric|water|gas|verizon|phone|utility|power|cable|internet/, 'utility'],
    [/checking|chk/, 'checking'], [/savings|sav/, 'savings'], [/invest|brokerage|401k|ira/, 'investment'],
    [/venmo|paypal|zelle|cashapp/, 'digital_wallet'],
  ];
  for (const [re, type] of patterns) {
    if (re.test(n)) return type;
  }
  return defaultClass === 'liability' ? 'credit_card' : 'checking';
}

async function commitAccountImport() {
  const accounts = _importState.preview;
  if (!accounts || !accounts.length) {
    toast('No accounts to import', 'info');
    return;
  }
  const dupAction = document.getElementById('import-dup-action').value;

  try {
    const result = await api('POST', '/accounts/import/commit', {
      accounts, duplicate_action: dupAction,
    });
    toast(`Import complete: ${result.created} created, ${result.updated} updated, ${result.skipped} skipped`, 'success');
    closeImportWizard();
    loadAccounts();
  } catch (e) {
    toast('Import failed: ' + e.message, 'error');
  }
}

// ── Bulk Balance Update ─────────────────────────────────────────────

async function submitBulkBalanceUpdate() {
  const updates = [];
  document.querySelectorAll('.bal-input-current').forEach(input => {
    const val = input.value.trim();
    if (!val) return; // Skip unchanged
    const id = parseInt(input.dataset.id);
    const entry = { account_id: id, current_balance: parseFloat(val) };

    const stmtInput = document.querySelector(`.bal-input-stmt[data-id="${id}"]`);
    if (stmtInput && stmtInput.value.trim()) {
      entry.statement_balance = parseFloat(stmtInput.value.trim());
    }
    const minInput = document.querySelector(`.bal-input-min[data-id="${id}"]`);
    if (minInput && minInput.value.trim()) {
      entry.minimum_payment = parseFloat(minInput.value.trim());
    }
    updates.push(entry);
  });

  if (!updates.length) {
    toast('No changes to save', 'info');
    return;
  }

  try {
    const result = await api('POST', '/accounts/balances/update', { updates });
    toast(`Updated ${result.updated} account(s). Snapshot saved.`, 'success');
    closeUpdateBalancesGrid();
    loadAccounts();
    _invalidateTabCache('overview');
    _invalidateTabCache('trends');
    if (_currentAccountsSubtab === 'overview') { _loadOverviewData(); _markTabLoaded('overview'); }
    if (_currentAccountsSubtab === 'trends') { _loadTrendsData(); _markTabLoaded('trends'); }
  } catch (e) {
    toast('Failed to save balances: ' + e.message, 'error');
  }
}
