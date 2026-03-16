// ── Accounts & Liabilities Module ─────────────────────────────────────
// Phase 1: Manage Accounts sub-view, Add/Edit Account, Payment Source Tags
// Phase 2: Overview sub-view, Update Balances grid, KPI cards, stale detection

let _accountsCache = [];
let _currentAccountsSubtab = 'manage';

// ── Load Accounts ────────────────────────────────────────────────────
async function loadAccounts() {
  try {
    const res = await api('GET', '/accounts/');
    _accountsCache = res.accounts || [];
    _renderAccountsTable(_accountsCache);
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
  if (!accounts.length) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; padding:32px; color:var(--text-muted);">No accounts yet. Click "+ Add New Account" to get started.</td></tr>';
    return;
  }
  tbody.innerHTML = accounts.map(a => {
    const bal = a.balance != null ? parseFloat(a.balance).toLocaleString('en-US', {style:'currency', currency:'USD'}) : '$0.00';
    const typeLabel = _typeLabel(a);
    const statusBadge = _statusBadge(a.status || 'active');
    const updatedAt = a.updated_at ? new Date(a.updated_at).toLocaleDateString() : '-';
    return `<tr>
      <td><strong>${esc(a.name)}</strong>${a.last_four ? ' <span style="color:var(--text-muted);">(' + esc(a.last_four) + ')</span>' : ''}</td>
      <td>${esc(a.institution || '-')}</td>
      <td>${typeLabel}</td>
      <td style="text-align:right; font-variant-numeric:tabular-nums;">${bal}</td>
      <td>${statusBadge}</td>
      <td style="color:var(--text-muted); font-size:13px;">${updatedAt}</td>
      <td>
        <button class="btn btn-secondary btn-sm" onclick="openEditAccount(${a.id})" title="Edit">Edit</button>
        ${a.status !== 'closed' ? `<button class="btn btn-danger btn-sm" onclick="closeAccount(${a.id})" title="Close" style="margin-left:4px;">Close</button>` : ''}
      </td>
    </tr>`;
  }).join('');
}

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

// ── Sub-tab switching ────────────────────────────────────────────────
function switchAccountsSubtab(tab) {
  const validTabs = ['overview', 'manage', 'planner'];
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
  if (overviewView) overviewView.style.display = tab === 'overview' ? '' : 'none';
  if (manageView) manageView.style.display = tab === 'manage' ? '' : 'none';
  if (plannerView) plannerView.style.display = tab === 'planner' ? '' : 'none';

  if (tab === 'overview') _loadOverviewData();
  if (tab === 'planner') _initPlanner();
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
    if (s === step) {
      el.style.background = 'var(--primary)';
      el.style.color = 'white';
    } else if (s < step) {
      el.style.background = '#22c55e';
      el.style.color = 'white';
    } else {
      el.style.background = 'var(--bg-secondary)';
      el.style.color = 'var(--text-muted)';
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
  }

  try {
    await api('POST', '/accounts/', payload);
    toast('Account created successfully', 'success');
    closeAddAccountModal();
    loadAccounts();
  } catch (e) {
    toast('Failed to create account: ' + e.message, 'error');
  }
}

// ── Edit Account ─────────────────────────────────────────────────────
function openEditAccount(id) {
  const acct = _accountsCache.find(a => a.id === id);
  if (!acct) return;

  document.getElementById('add-account-modal').style.display = 'flex';
  document.getElementById('add-account-modal-title').textContent = 'Edit Account';
  document.getElementById('account-steps').style.display = 'none';
  document.getElementById('account-step-1').style.display = 'none';
  document.getElementById('account-step-2').style.display = 'none';
  document.getElementById('account-step-3').style.display = 'none';
  document.getElementById('account-edit-form').style.display = '';

  document.getElementById('edit-account-id').value = acct.id;
  document.getElementById('edit-acct-name').value = acct.name || '';
  document.getElementById('edit-acct-institution').value = acct.institution || '';
  document.getElementById('edit-acct-last-four').value = acct.last_four || '';
  document.getElementById('edit-acct-due-day').value = acct.due_day || '';
  document.getElementById('edit-acct-balance').value = acct.balance != null ? acct.balance : '';
  document.getElementById('edit-acct-credit-limit').value = acct.credit_limit || '';
  document.getElementById('edit-acct-interest-rate').value = acct.interest_rate || '';
  document.getElementById('edit-acct-payment-source-tag').value = acct.payment_source_tag || '';
}

async function submitEditAccount() {
  const id = document.getElementById('edit-account-id').value;
  const payload = {};
  const name = document.getElementById('edit-acct-name').value.trim();
  if (name) payload.name = name;
  const inst = document.getElementById('edit-acct-institution').value.trim();
  if (inst) payload.institution = inst;
  const lf = document.getElementById('edit-acct-last-four').value.trim();
  if (lf) payload.last_four = lf;
  const dd = document.getElementById('edit-acct-due-day').value;
  if (dd) payload.due_day = parseInt(dd);
  const bal = document.getElementById('edit-acct-balance').value;
  if (bal !== '') payload.balance = parseFloat(bal);
  const cl = document.getElementById('edit-acct-credit-limit').value;
  if (cl) payload.credit_limit = parseFloat(cl);
  const ir = document.getElementById('edit-acct-interest-rate').value;
  if (ir) payload.interest_rate = parseFloat(ir);
  const tag = document.getElementById('edit-acct-payment-source-tag').value.trim();
  if (tag) payload.payment_source_tag = tag;

  try {
    await api('PUT', `/accounts/${id}`, payload);
    toast('Account updated', 'success');
    closeAddAccountModal();
    loadAccounts();
  } catch (e) {
    toast('Failed to update account: ' + e.message, 'error');
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
  document.getElementById('kpi-total-liabilities').textContent = _fmt(s.total_liabilities_excl_personal);
  document.getElementById('kpi-total-assets').textContent = _fmt(s.total_assets);
  const netEl = document.getElementById('kpi-net-position');
  netEl.textContent = _fmt(s.net_position);
  netEl.style.color = s.net_position >= 0 ? 'var(--success)' : 'var(--danger)';
  const utilEl = document.getElementById('kpi-utilization');
  utilEl.textContent = s.credit_utilization_pct + '%';
  utilEl.style.color = s.credit_utilization_pct > 80 ? 'var(--danger)' : s.credit_utilization_pct > 30 ? 'var(--warning)' : 'var(--success)';
  document.getElementById('kpi-due-this-week').textContent = s.due_this_week;
  document.getElementById('kpi-monthly-interest').textContent = _fmt(s.est_monthly_interest);
}

function _renderOverviewTables(accounts) {
  const liabilities = accounts.filter(a => a.account_class === 'liability' || a.is_asset === false);
  const assets = accounts.filter(a => a.account_class === 'asset' || a.is_asset === true);

  // Liabilities
  const liabBody = document.getElementById('overview-liabilities-body');
  if (!liabilities.length) {
    liabBody.innerHTML = '<tr><td colspan="10" style="text-align:center; padding:24px; color:var(--text-muted);">No liabilities</td></tr>';
  } else {
    liabBody.innerHTML = liabilities.map(a => {
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
        <td>${a.due_day || '-'}</td>
        <td style="text-align:right; font-variant-numeric:tabular-nums;">${cl != null ? _fmt(cl) : '-'}</td>
        <td style="text-align:right; ${utilStyle}">${util != null ? util + '%' : '-'}</td>
        <td><code style="font-size:11px;">${esc(a.payment_source_tag || '-')}</code></td>
        <td style="font-size:12px;">${staleInfo}</td>
      </tr>`;
    }).join('');
  }

  // Assets
  const assetBody = document.getElementById('overview-assets-body');
  if (!assets.length) {
    assetBody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:24px; color:var(--text-muted);">No assets</td></tr>';
  } else {
    assetBody.innerHTML = assets.map(a => {
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
      ${strategies.map(s => `<option value="${s}" ${s === selectedStrategy ? 'selected' : ''}>${s.replace(/_/g, ' ')}</option>`).join('')}
    </select>`;

    const statusBadge = status ? _cycleBadge(status) : '<span style="color:var(--text-muted); font-size:11px;">unassigned</span>';
    const canPay = selectedSource && status !== 'completed';

    return `<tr>
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
    if (_currentAccountsSubtab === 'overview') _loadOverviewData();
  } catch (e) {
    toast('Failed to save balances: ' + e.message, 'error');
  }
}
