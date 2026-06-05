/**
 * BankAI Admin Panel — admin.js
 * Handles all API communication, rendering, and modal logic for the admin panel.
 */

const API = '/api/v1/admin';

// ────────────────────────────────────────────────────────────────────────────
// State
// ────────────────────────────────────────────────────────────────────────────
let adminToken = sessionStorage.getItem('adminToken');
let allBanks = [];       // [{id, name, code, is_active}]
let selectedFormId = null;
let editingFormId = null;
let editingFieldId = null;
let selectedFieldType = 'text';
let currentSections = [];
let currentFields = [];

// Pagination
let subSkip = 0;
const subLimit = 20;

// ────────────────────────────────────────────────────────────────────────────
// Init
// ────────────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    if (adminToken) {
        tryBootstrap();
    } else {
        document.getElementById('authOverlay').style.display = 'flex';
    }
});

async function tryBootstrap() {
    try {
        // Quick sanity — hit banks endpoint
        const res = await apiFetch('/banks');
        if (!res.ok) throw new Error('Unauthorized');
        document.getElementById('authOverlay').style.display = 'none';
        document.getElementById('appShell').style.display = 'flex';
        allBanks = await res.json();
        renderBanks(allBanks);
        populateBankDropdowns();
        document.getElementById('adminUserPill').textContent = '⬤ Admin';
    } catch (e) {
        adminToken = null;
        sessionStorage.removeItem('adminToken');
        document.getElementById('authOverlay').style.display = 'flex';
        document.getElementById('authError').style.display = 'block';
        document.getElementById('authError').textContent = 'Token expired or not admin. Please re-enter.';
    }
}

async function submitToken() {
    const raw = document.getElementById('tokenInput').value.trim();
    if (!raw) { showToast('Paste a JWT token first', 'error'); return; }
    adminToken = raw;
    sessionStorage.setItem('adminToken', raw);
    document.getElementById('authError').style.display = 'none';
    await tryBootstrap();
}

function logout() {
    adminToken = null;
    sessionStorage.removeItem('adminToken');
    location.reload();
}

// ────────────────────────────────────────────────────────────────────────────
// API helper
// ────────────────────────────────────────────────────────────────────────────
function apiFetch(path, method = 'GET', body = null) {
    const opts = {
        method,
        headers: {
            'Authorization': `Bearer ${adminToken}`,
            'Content-Type': 'application/json',
        },
    };
    if (body) opts.body = JSON.stringify(body);
    return fetch(API + path, opts);
}

// ────────────────────────────────────────────────────────────────────────────
// Tab management
// ────────────────────────────────────────────────────────────────────────────
const TAB_TITLES = { banks: 'Banks', forms: 'Forms', submissions: 'Submissions' };

function showTab(name) {
    document.querySelectorAll('.tab-pane').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    document.getElementById(`tab-${name}`).classList.add('active');
    document.getElementById(`nav-${name}`).classList.add('active');
    document.getElementById('pageTitle').textContent = TAB_TITLES[name];

    if (name === 'banks') loadBanks();
    if (name === 'forms') loadForms();
    if (name === 'submissions') loadSubmissions();
}

// ────────────────────────────────────────────────────────────────────────────
// Banks
// ────────────────────────────────────────────────────────────────────────────
async function loadBanks() {
    const res = await apiFetch('/banks');
    if (!res.ok) return handleError(res);
    allBanks = await res.json();
    renderBanks(allBanks);
    populateBankDropdowns();
}

function renderBanks(banks) {
    const tbody = document.getElementById('banksBody');
    if (!banks.length) {
        tbody.innerHTML = '<tr><td colspan="5"><div class="empty"><div class="empty-icon">🏛️</div>No banks yet</div></td></tr>';
        return;
    }
    tbody.innerHTML = banks.map(b => `
    <tr>
      <td><span style="color:var(--muted);font-family:monospace">#${b.id}</span></td>
      <td><strong>${esc(b.name)}</strong></td>
      <td><code style="background:rgba(255,255,255,.06);padding:.2rem .5rem;border-radius:6px;font-size:.85rem">${esc(b.code)}</code></td>
      <td>${statusBadge(b.is_active)}</td>
      <td>—</td>
    </tr>
  `).join('');
}

async function createBank() {
    const name = document.getElementById('bankName').value.trim();
    const code = document.getElementById('bankCode').value.trim().toUpperCase();
    if (!name || !code) { showToast('Name and code required', 'error'); return; }
    const res = await apiFetch('/banks', 'POST', { name, code });
    if (!res.ok) { const e = await res.json(); showToast(e.detail || 'Failed to create bank', 'error'); return; }
    showToast('Bank created!', 'success');
    closeModal('bankModal');
    document.getElementById('bankName').value = '';
    document.getElementById('bankCode').value = '';
    await loadBanks();
}

// ────────────────────────────────────────────────────────────────────────────
// Forms
// ────────────────────────────────────────────────────────────────────────────
function populateBankDropdowns() {
    // Filter select (forms tab)
    const filter = document.getElementById('bankFilter');
    const current = filter.value;
    filter.innerHTML = '<option value="">All Banks</option>' + allBanks.map(b =>
        `<option value="${b.id}"${b.id == current ? ' selected' : ''}>${esc(b.name)}</option>`
    ).join('');

    // formBankId select (create form modal)
    const fbi = document.getElementById('formBankId');
    fbi.innerHTML = allBanks.map(b => `<option value="${b.id}">${esc(b.name)}</option>`).join('');
}

async function loadForms() {
    const bankId = document.getElementById('bankFilter').value;
    const path = bankId ? `/forms?bank_id=${bankId}` : '/forms';
    const res = await apiFetch(path);
    if (!res.ok) return handleError(res);
    const forms = await res.json();
    renderForms(forms);
}

function renderForms(forms) {
    const tbody = document.getElementById('formsBody');
    if (!forms.length) {
        tbody.innerHTML = '<tr><td colspan="6"><div class="empty"><div class="empty-icon">📋</div>No forms yet</div></td></tr>';
        return;
    }
    const bankMap = Object.fromEntries(allBanks.map(b => [b.id, b.name]));
    tbody.innerHTML = forms.map(f => `
    <tr class="clickable" onclick="selectForm(${f.id}, '${esc(f.name)}', '${esc(f.code)}')">
      <td><span style="color:var(--muted);font-family:monospace">#${f.id}</span></td>
      <td>${esc(bankMap[f.bank_id] || '—')}</td>
      <td><strong>${esc(f.name)}</strong></td>
      <td><code style="background:rgba(255,255,255,.06);padding:.2rem .5rem;border-radius:6px;font-size:.82rem">${esc(f.code)}</code></td>
      <td>${statusBadge(f.is_active)}</td>
      <td onclick="event.stopPropagation()">
        <button class="btn btn-secondary btn-sm" onclick="openEditFormModal(${f.id},'${esc(f.name)}','${esc(f.description || '')}',${f.is_active})">Edit</button>
      </td>
    </tr>
  `).join('');
}

async function selectForm(formId, name, code) {
    selectedFormId = formId;
    document.getElementById('selectedFormName').textContent = name;
    document.getElementById('selectedFormCode').textContent = code;
    document.getElementById('formDetailCard').style.display = 'block';
    document.getElementById('formDetailCard').scrollIntoView({ behavior: 'smooth' });
    await Promise.all([loadSections(), loadFields()]);
}

function openCreateFormModal() {
    editingFormId = null;
    document.getElementById('formModalTitle').textContent = '📋 Add Form';
    document.getElementById('formModalSubmit').textContent = 'Create Form';
    document.getElementById('formName').value = '';
    document.getElementById('formCode').value = '';
    document.getElementById('formDesc').value = '';
    document.getElementById('formCode').disabled = false;
    document.getElementById('formActiveGroup').style.display = 'none';
    openModal('formModal');
}

function openEditFormModal(id, name, desc, isActive) {
    editingFormId = id;
    document.getElementById('formModalTitle').textContent = '✏️ Edit Form';
    document.getElementById('formModalSubmit').textContent = 'Save Changes';
    document.getElementById('formName').value = name;
    document.getElementById('formCode').value = '— (cannot change code) —';
    document.getElementById('formCode').disabled = true;
    document.getElementById('formDesc').value = desc;
    document.getElementById('formIsActive').checked = isActive;
    document.getElementById('formActiveGroup').style.display = 'block';
    openModal('formModal');
}

async function submitFormModal() {
    if (editingFormId) {
        await updateForm();
    } else {
        await createForm();
    }
}

async function createForm() {
    const bank_id = parseInt(document.getElementById('formBankId').value);
    const name = document.getElementById('formName').value.trim();
    const code = document.getElementById('formCode').value.trim();
    const description = document.getElementById('formDesc').value.trim() || null;
    if (!name || !code) { showToast('Name and code required', 'error'); return; }
    const res = await apiFetch('/forms', 'POST', { bank_id, name, code, description });
    if (!res.ok) { const e = await res.json(); showToast(e.detail || 'Failed', 'error'); return; }
    showToast('Form created!', 'success');
    closeModal('formModal');
    await loadForms();
}

async function updateForm() {
    const name = document.getElementById('formName').value.trim();
    const description = document.getElementById('formDesc').value.trim() || null;
    const is_active = document.getElementById('formIsActive').checked;
    const res = await apiFetch(`/forms/${editingFormId}`, 'PUT', { name, description, is_active });
    if (!res.ok) { const e = await res.json(); showToast(e.detail || 'Failed', 'error'); return; }
    showToast('Form updated!', 'success');
    closeModal('formModal');
    await loadForms();
}

// ────────────────────────────────────────────────────────────────────────────
// Sections
// ────────────────────────────────────────────────────────────────────────────
async function loadSections() {
    if (!selectedFormId) return;
    const res = await apiFetch(`/forms/${selectedFormId}/sections`);
    if (!res.ok) return;
    currentSections = await res.json();
    updateSectionSelect();
    renderFormBuilder();
}

function updateSectionSelect() {
    const sel = document.getElementById('fieldSection');
    sel.innerHTML = '<option value="">— No section —</option>' + currentSections.map(s =>
        `<option value="${s.id}">${esc(s.name)}</option>`
    ).join('');
}

async function createSection() {
    if (!selectedFormId) { showToast('Select a form first', 'error'); return; }
    const name = document.getElementById('sectionName').value.trim();
    const order_index = parseInt(document.getElementById('sectionOrder').value) || 0;
    if (!name) { showToast('Section name required', 'error'); return; }
    const res = await apiFetch(`/forms/${selectedFormId}/sections`, 'POST', { name, order_index });
    if (!res.ok) { const e = await res.json(); showToast(e.detail || 'Failed', 'error'); return; }
    showToast('Section added!', 'success');
    closeModal('sectionModal');
    document.getElementById('sectionName').value = '';
    document.getElementById('sectionOrder').value = '0';
    await loadSections();
}

// ────────────────────────────────────────────────────────────────────────────
// Fields
// ────────────────────────────────────────────────────────────────────────────
async function loadFields() {
    if (!selectedFormId) return;
    const res = await apiFetch(`/forms/${selectedFormId}/fields`);
    if (!res.ok) return;
    currentFields = await res.json();
    renderFormBuilder();
}

function renderFormBuilder() {
    const builder = document.getElementById('visualFormBuilder');
    if (!builder) return;

    if (!currentSections.length && !currentFields.length) {
        builder.innerHTML = `
            <div class="empty-builder">
                <div style="font-size: 2.5rem; margin-bottom: 0.75rem;">📋</div>
                <h3 style="font-weight:700; font-size:1.1rem; color:var(--text-primary);">This form is empty</h3>
                <p style="color: var(--text-muted); font-size: 0.88rem; margin-top: 0.25rem;">
                    Add sections and fields to define the form structure.
                </p>
            </div>
        `;
        return;
    }

    const sortedSections = [...currentSections].sort((a, b) => a.order_index - b.order_index);
    const sortedFields = [...currentFields].sort((a, b) => a.order_index - b.order_index);

    const fieldsBySection = {};
    const unassignedFields = [];

    sortedFields.forEach(f => {
        if (f.section_id) {
            if (!fieldsBySection[f.section_id]) fieldsBySection[f.section_id] = [];
            fieldsBySection[f.section_id].push(f);
        } else {
            unassignedFields.push(f);
        }
    });

    let html = '';

    // Render unassigned fields if any exist
    if (unassignedFields.length > 0) {
        html += renderBuilderSection({ id: null, name: 'General / Unassigned Fields', order_index: 0 }, unassignedFields);
    }

    // Render each section
    sortedSections.forEach(s => {
        const sectionFields = fieldsBySection[s.id] || [];
        html += renderBuilderSection(s, sectionFields);
    });

    builder.innerHTML = html;
}

function renderBuilderSection(section, fields) {
    const isGeneral = section.id === null;
    const sectionTitle = esc(section.name);
    
    let fieldsHtml = '';
    if (fields.length === 0) {
        fieldsHtml = `
            <div class="empty-section-placeholder">
                <span style="font-size: 1.1rem;">✨</span>
                <span>No fields in this section yet. Click "+ Add Field" to add one.</span>
            </div>
        `;
    } else {
        fieldsHtml = fields.map(f => renderBuilderFieldCard(f)).join('');
    }

    const headerActions = isGeneral 
        ? `<button class="btn btn-secondary btn-sm" onclick="openCreateFieldModalForSection(null)">+ Add Field</button>`
        : `
            <div style="display:flex; gap:0.5rem; align-items:center;">
                <span class="section-order-badge" title="Order Index">Order: ${section.order_index}</span>
                <button class="btn btn-secondary btn-sm" onclick="openCreateFieldModalForSection(${section.id})">+ Add Field</button>
            </div>
        `;

    return `
        <div class="builder-section-card ${isGeneral ? 'general-section' : ''}">
            <div class="builder-section-header">
                <div style="display:flex; align-items:center; gap:0.6rem;">
                    <span style="font-size: 1.15rem;">${isGeneral ? '⚙️' : '📁'}</span>
                    <h3 class="builder-section-title">${sectionTitle}</h3>
                </div>
                ${headerActions}
            </div>
            <div class="builder-field-grid">
                ${fieldsHtml}
            </div>
        </div>
    `;
}

function openCreateFieldModalForSection(sectionId) {
    openCreateFieldModal();
    const s = document.getElementById('fieldSection');
    if (sectionId) {
        s.value = sectionId;
    } else {
        s.value = '';
    }
}

function renderBuilderFieldCard(f) {
    const isRequired = f.required;
    const isActive = f.is_active;
    const key = esc(f.field_key);
    const label = esc(f.label);
    const type = esc(f.field_type);
    
    let previewInput = '';
    if (type === 'text') {
        previewInput = `<input type="text" class="form-control" disabled placeholder="Text response..." style="opacity: 0.5; cursor: not-allowed; height: 36px; padding: 0 .75rem; font-size: .85rem;" />`;
    } else if (type === 'number') {
        previewInput = `<input type="number" class="form-control" disabled placeholder="12345..." style="opacity: 0.5; cursor: not-allowed; height: 36px; padding: 0 .75rem; font-size: .85rem;" />`;
    } else if (type === 'date') {
        previewInput = `<input type="date" class="form-control" disabled style="opacity: 0.5; cursor: not-allowed; height: 36px; padding: 0 .75rem; font-size: .85rem;" />`;
    } else if (type === 'select') {
        let optionsHtml = '<option>Select option...</option>';
        if (f.options && Array.isArray(f.options)) {
            optionsHtml += f.options.map(opt => `<option disabled>${esc(opt.label || opt.value || opt)}</option>`).join('');
        }
        previewInput = `<select class="form-control" disabled style="opacity: 0.5; cursor: not-allowed; height: 36px; padding: 0 .75rem; font-size: .85rem;">${optionsHtml}</select>`;
    } else if (type === 'radio') {
        let optionsHtml = '';
        if (f.options && Array.isArray(f.options)) {
            optionsHtml = f.options.map(opt => `
                <label style="display:inline-flex; align-items:center; gap:0.25rem; font-size:0.8rem; color:var(--text-secondary); cursor: not-allowed;">
                    <input type="radio" disabled name="dummy_${f.id}" /> ${esc(opt.label || opt.value || opt)}
                </label>
            `).join('');
        } else {
            optionsHtml = `
                <label style="display:inline-flex; align-items:center; gap:0.25rem; font-size:0.8rem; color:var(--text-secondary); cursor: not-allowed;">
                    <input type="radio" disabled /> Option 1
                </label>
                <label style="display:inline-flex; align-items:center; gap:0.25rem; font-size:0.8rem; color:var(--text-secondary); cursor: not-allowed;">
                    <input type="radio" disabled /> Option 2
                </label>
            `;
        }
        previewInput = `<div style="display:flex; gap:0.75rem; flex-wrap:wrap; padding: 0.2rem 0;">${optionsHtml}</div>`;
    } else if (type === 'checkbox') {
        previewInput = `
            <label style="display:inline-flex; align-items:center; gap:0.4rem; font-size:0.82rem; color:var(--text-secondary); cursor: not-allowed; padding: 0.2rem 0;">
                <input type="checkbox" disabled /> I agree to the terms
            </label>
        `;
    }

    const typeColors = { text: 'blue', number: 'purple', date: 'yellow', select: 'green', radio: 'green', checkbox: 'green' };
    const badgeColor = typeColors[type] || 'blue';

    const fJson = JSON.stringify(f).replace(/"/g, '&quot;');

    return `
        <div class="builder-field-card ${isActive ? '' : 'field-inactive'}">
            <div class="field-card-header">
                <div style="display:flex; align-items:center; gap:0.3rem; overflow:hidden;">
                    <span class="field-card-label" title="${label}">${label}</span>
                    ${isRequired ? '<span class="field-required-star" title="Required">*</span>' : ''}
                </div>
                <button class="field-edit-btn" onclick="openEditFieldModal(${fJson})" title="Edit Field">✏️</button>
            </div>
            
            <div class="field-card-preview">
                ${previewInput}
            </div>
            
            <div class="field-card-footer">
                <code class="field-key-badge">${key}</code>
                <span class="badge badge-${badgeColor}" style="font-size: 0.65rem; padding: 0.15rem 0.35rem;">${type}</span>
                ${isActive ? '' : '<span class="badge badge-red" style="font-size: 0.65rem; padding: 0.15rem 0.35rem;">Inactive</span>'}
            </div>
        </div>
    `;
}

function selectFieldType(type) {
    selectedFieldType = type;
    document.querySelectorAll('.type-chip').forEach(c => {
        c.classList.toggle('sel', c.dataset.type === type);
    });
}

function openCreateFieldModal() {
    editingFieldId = null;
    selectedFieldType = 'text';
    document.getElementById('fieldModalTitle').textContent = '🔧 Add Field';
    document.getElementById('fieldModalSubmit').textContent = 'Add Field';
    document.getElementById('fieldKey').value = '';
    document.getElementById('fieldKey').disabled = false;
    document.getElementById('fieldLabel').value = '';
    document.getElementById('fieldOrder').value = '0';
    document.getElementById('fieldRequired').checked = true;
    document.getElementById('fieldOptions').value = '';
    document.getElementById('fieldValidation').value = '';
    document.getElementById('fieldActiveGroup').style.display = 'none';
    document.querySelectorAll('.type-chip').forEach(c => c.classList.toggle('sel', c.dataset.type === 'text'));
    openModal('fieldModal');
}

function openEditFieldModal(f) {
    editingFieldId = f.id;
    selectedFieldType = f.field_type;
    document.getElementById('fieldModalTitle').textContent = '✏️ Edit Field';
    document.getElementById('fieldModalSubmit').textContent = 'Save Field';
    document.getElementById('fieldKey').value = f.field_key;
    document.getElementById('fieldKey').disabled = true;
    document.getElementById('fieldLabel').value = f.label;
    document.getElementById('fieldOrder').value = f.order_index;
    document.getElementById('fieldRequired').checked = f.required;
    document.getElementById('fieldIsActive').checked = f.is_active;
    document.getElementById('fieldOptions').value = f.options ? JSON.stringify(f.options, null, 2) : '';
    document.getElementById('fieldValidation').value = f.validation_rule ? JSON.stringify(f.validation_rule, null, 2) : '';
    document.querySelectorAll('.type-chip').forEach(c => c.classList.toggle('sel', c.dataset.type === f.field_type));
    document.getElementById('fieldActiveGroup').style.display = 'block';
    const s = document.getElementById('fieldSection');
    if (f.section_id) {
        for (let o of s.options) { if (o.value == f.section_id) { o.selected = true; break; } }
    } else {
        s.value = '';
    }
    openModal('fieldModal');
}

async function submitFieldModal() {
    if (editingFieldId) await updateField();
    else await createField();
}

async function createField() {
    if (!selectedFormId) { showToast('No form selected', 'error'); return; }
    const field_key = document.getElementById('fieldKey').value.trim();
    const label = document.getElementById('fieldLabel').value.trim();
    if (!field_key || !label) { showToast('Key and label required', 'error'); return; }

    const body = {
        field_key,
        label,
        field_type: selectedFieldType,
        required: document.getElementById('fieldRequired').checked,
        order_index: parseInt(document.getElementById('fieldOrder').value) || 0,
        section_id: parseInt(document.getElementById('fieldSection').value) || null,
        options: parseJsonField('fieldOptions'),
        validation_rule: parseJsonField('fieldValidation'),
    };

    const res = await apiFetch(`/forms/${selectedFormId}/fields`, 'POST', body);
    if (!res.ok) { const e = await res.json(); showToast(e.detail || 'Failed', 'error'); return; }
    showToast('Field created!', 'success');
    closeModal('fieldModal');
    await loadFields();
}

async function updateField() {
    const label = document.getElementById('fieldLabel').value.trim();
    const body = {
        label,
        field_type: selectedFieldType,
        required: document.getElementById('fieldRequired').checked,
        order_index: parseInt(document.getElementById('fieldOrder').value) || 0,
        is_active: document.getElementById('fieldIsActive').checked,
        options: parseJsonField('fieldOptions'),
        validation_rule: parseJsonField('fieldValidation'),
    };
    const res = await apiFetch(`/fields/${editingFieldId}`, 'PUT', body);
    if (!res.ok) { const e = await res.json(); showToast(e.detail || 'Failed', 'error'); return; }
    showToast('Field updated!', 'success');
    closeModal('fieldModal');
    await loadFields();
}

function parseJsonField(id) {
    const raw = document.getElementById(id).value.trim();
    if (!raw) return null;
    try { return JSON.parse(raw); } catch { showToast(`Invalid JSON in ${id}`, 'error'); return null; }
}

// ────────────────────────────────────────────────────────────────────────────
// Submissions
// ────────────────────────────────────────────────────────────────────────────
async function loadSubmissions() {
    const res = await apiFetch(`/submissions?skip=${subSkip}&limit=${subLimit}`);
    if (!res.ok) return handleError(res);
    const subs = await res.json();
    renderSubmissions(subs);
    document.getElementById('submissionCount').textContent = `${subs.length} shown`;
    document.getElementById('prevBtn').disabled = subSkip === 0;
    document.getElementById('nextBtn').disabled = subs.length < subLimit;
    document.getElementById('pageInfo').textContent = `Offset ${subSkip}`;
}

function renderSubmissions(subs) {
    const tbody = document.getElementById('submissionsBody');
    if (!subs.length) {
        tbody.innerHTML = '<tr><td colspan="8"><div class="empty"><div class="empty-icon">📊</div>No submissions yet</div></td></tr>';
        return;
    }
    const stateColor = { welcome: 'purple', select_application: 'blue', filling_form: 'yellow', review: 'yellow', complete: 'green', chat: 'blue' };
    tbody.innerHTML = subs.map(s => `
    <tr>
      <td><span style="color:var(--muted);font-family:monospace">#${s.id}</span></td>
      <td><span style="font-family:monospace;font-size:.85rem">U${s.user_id}</span></td>
      <td>${esc(s.bank_name || '—')}</td>
      <td>${esc(s.form_name || '—')}</td>
      <td>${s.status === 'completed' ? '<span class="badge badge-green">Completed</span>' : '<span class="badge badge-yellow">Draft</span>'}</td>
      <td><span class="badge badge-${stateColor[s.conversation_state] || 'blue'}">${esc(s.conversation_state || '—')}</span></td>
      <td style="font-size:.82rem;color:var(--muted)">${s.created_at ? s.created_at.slice(0, 16).replace('T', ' ') : '—'}</td>
      <td><button class="btn btn-accent btn-sm" onclick="loadSubmissionDetail(${s.id})">View</button></td>
    </tr>
  `).join('');
}

async function loadSubmissionDetail(id) {
    const res = await apiFetch(`/submissions/${id}`);
    if (!res.ok) return handleError(res);
    const s = await res.json();
    document.getElementById('submissionDetailCard').style.display = 'block';
    document.getElementById('submissionDetailCard').scrollIntoView({ behavior: 'smooth' });
    const body = document.getElementById('submissionDetailBody');
    const fields = s.data.map(d => `
    <div class="field-chip">
      <div class="field-chip-key">${esc(d.field_key)}</div>
      <div class="field-chip-val">${esc(d.value || '—')}</div>
    </div>
  `).join('');
    body.innerHTML = `
    <div class="detail-row"><div class="detail-key">Submission ID</div><div class="detail-val">#${s.id}</div></div>
    <div class="detail-row"><div class="detail-key">User ID</div><div class="detail-val">U${s.user_id}</div></div>
    <div class="detail-row"><div class="detail-key">Bank</div><div class="detail-val">${esc(s.bank_name || '—')}</div></div>
    <div class="detail-row"><div class="detail-key">Form</div><div class="detail-val">${esc(s.form_name || '—')}</div></div>
    <div class="detail-row"><div class="detail-key">Status</div><div class="detail-val">${s.status === 'completed' ? '<span class="badge badge-green">Completed</span>' : '<span class="badge badge-yellow">Draft</span>'}</div></div>
    <div class="detail-row"><div class="detail-key">Conversation State</div><div class="detail-val"><span class="badge badge-blue">${esc(s.conversation_state || '—')}</span></div></div>
    <div class="detail-row"><div class="detail-key">Current Field Index</div><div class="detail-val">${s.current_field_index}</div></div>
    <div class="detail-row"><div class="detail-key">Created</div><div class="detail-val">${s.created_at || '—'}</div></div>
    <div class="detail-row"><div class="detail-key">Updated</div><div class="detail-val">${s.updated_at || '—'}</div></div>
    <div style="margin-top:1.2rem">
      <div style="font-size:.8rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:.75rem">Answered Fields (${s.data.length})</div>
      ${fields ? `<div class="field-data-grid">${fields}</div>` : '<div style="color:var(--muted);font-size:.9rem">No fields answered yet.</div>'}
    </div>
  `;
}

function closeSubmissionDetail() {
    document.getElementById('submissionDetailCard').style.display = 'none';
}

function prevPage() { if (subSkip > 0) { subSkip = Math.max(0, subSkip - subLimit); loadSubmissions(); } }
function nextPage() { subSkip += subLimit; loadSubmissions(); }

// ────────────────────────────────────────────────────────────────────────────
// Modal helpers
// ────────────────────────────────────────────────────────────────────────────
function openModal(id) { document.getElementById(id).classList.add('open'); }
function closeModal(id) { document.getElementById(id).classList.remove('open'); }

// Close modal on overlay click
document.querySelectorAll('.modal-overlay').forEach(overlay => {
    overlay.addEventListener('click', e => {
        if (e.target === overlay) overlay.classList.remove('open');
    });
});

// ────────────────────────────────────────────────────────────────────────────
// Toast
// ────────────────────────────────────────────────────────────────────────────
function showToast(msg, type = 'success') {
    // Delegate to shared toast system
    const mappedType = type === 'success' ? 'success' : 'error';
    BankAI_Toast.show(msg, mappedType);
}

// ────────────────────────────────────────────────────────────────────────────
// Utilities
// ────────────────────────────────────────────────────────────────────────────
function esc(str) {
    if (str == null) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function statusBadge(isActive) {
    return isActive
        ? '<span class="badge badge-green">● Active</span>'
        : '<span class="badge badge-red">● Inactive</span>';
}

async function handleError(res) {
    let msg = `HTTP ${res.status}`;
    try { const e = await res.json(); msg = e.detail || msg; } catch { }
    showToast(msg, 'error');
    if (res.status === 401 || res.status === 403) {
        adminToken = null;
        sessionStorage.removeItem('adminToken');
        setTimeout(() => location.reload(), 1500);
    }
}
