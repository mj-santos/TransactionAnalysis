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
    return `<tr>
      <td><input type="checkbox" class="acct-select-cb" data-account-id="${a.id}" onchange="_updateAcctBulkBar()" /></td>
      <td><strong>${esc(a.name)}</strong>${a.last_four ? ' <span style="color:var(--text-muted);">(' + esc(a.last_four) + ')</span>' : ''}</td>
      <td>${esc(a.institution || '-')}</td>
      <td>${typeLabel}</td>
      <td style="text-align:right; font-variant-numeric:tabular-nums;">${bal}</td>
      <td>${statusBadge}</td>
      <td style="color:var(--text-muted); font-size:13px;">${updatedAt}</td>
      <td>
        <button class="btn btn-secondary btn-sm" onclick="openEditAccount(${a.id})" title="Edit">Edit</button>
        ${a.status !== 'closed' ? `<button class="btn btn-danger btn-sm" onclick="closeAccount(${a.id})" title="Close" style="margin-left:4px;">Close</button>` : ''}
        <button class="btn btn-sm" onclick="deleteAccount(${a.id})" title="Delete" style="margin-left:4px; color:var(--danger); background:none; border:1px solid var(--danger);">Delete</button>
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

  if (tab === 'overview') _loadOverviewData();
  if (tab === 'planner') _initPlanner();
  if (tab === 'trends') _loadTrendsData();
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
}

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

  // Populate account class + subtype dropdowns
  const acctClass = acct.account_class || (acct.is_asset ? 'asset' : 'liability');
  document.getElementById('edit-acct-class').value = acctClass;
  const currentSubtype = acctClass === 'asset' ? acct.asset_type : acct.liability_type;
  _populateSubtypeDropdown(acctClass, currentSubtype || (acctClass === 'asset' ? 'checking' : 'credit_card'));

  // Populate linked transaction source dropdown
  _populateLinkedSourceDropdown(acct);
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

  // Handle linked transaction source
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
    await api('PUT', `/accounts/${id}`, payload);
    toast('Account updated', 'success');
    closeAddAccountModal();
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

  el.innerHTML = data.map(d => {
    const assH = Math.max(Math.round(d.total_assets / maxVal * chartH), 2);
    const liabH = Math.max(Math.round(d.total_liabilities / maxVal * chartH), 2);
    const label = d.date ? String(d.date).slice(0, 7) : '?';
    return `<div style="flex:1; display:flex; flex-direction:column; align-items:center; min-width:24px;" title="${label}\nAssets: ${_fmt(d.total_assets)}\nLiabilities: ${_fmt(d.total_liabilities)}\nNet: ${_fmt(d.net_worth)}">
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
    const monthsLabel = a.months_to_payoff != null ? `${a.months_to_payoff} mo` : '<span style="color:var(--danger);">Never</span>';
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
    if (_currentAccountsSubtab === 'overview') _loadOverviewData();
  } catch (e) {
    toast('Failed to save balances: ' + e.message, 'error');
  }
}
