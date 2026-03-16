// ── Accounts & Liabilities Module ─────────────────────────────────────
// Phase 1: Manage Accounts sub-view, Add/Edit Account, Payment Source Tags

let _accountsCache = [];

// ── Load Accounts ────────────────────────────────────────────────────
async function loadAccounts() {
  try {
    const res = await api('GET', '/accounts/');
    _accountsCache = res.accounts || [];
    _renderAccountsTable(_accountsCache);
    _loadPaymentSourceTags();
    _populateTagAccountDropdown(_accountsCache);
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
  // Phase 1 only implements 'manage'
  if (tab !== 'manage') return;
  document.querySelectorAll('.accounts-subtab').forEach(b => {
    b.classList.remove('active');
    b.style.borderBottom = 'none';
  });
  const btn = document.querySelector(`.accounts-subtab[data-subtab="${tab}"]`);
  if (btn) {
    btn.classList.add('active');
    btn.style.borderBottom = '2px solid var(--primary)';
  }
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
