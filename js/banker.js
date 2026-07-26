(function () {
    // Authentication check for banker dashboard
    const adminToken = sessionStorage.getItem('adminToken');
    if (!adminToken) {
        window.location.href = '/admin_login.html';
        return;
    }

    const grid = document.getElementById('monitorGrid');
    const refreshBtn = document.getElementById('refreshBtn');

    // Fetch active submissions
    async function loadActiveSubmissions() {
        try {
            const res = await BankAI_API.request('/api/v1/submissions/active/monitor', {
                method: 'GET'
            });

            if (!res.ok) {
                grid.innerHTML = `
                    <div class="empty-state">
                        <h3>⚠️ Error loading submissions</h3>
                        <p>Server returned status ${res.status}. Make sure you are logged in.</p>
                    </div>
                `;
                return;
            }

            const subs = await res.json();
            renderSubmissions(subs);
        } catch (err) {
            console.error('Failed to load active submissions:', err);
            grid.innerHTML = `
                <div class="empty-state">
                    <h3>⚠️ Connection error</h3>
                    <p>Could not connect to BankAI server. Is it running?</p>
                </div>
            `;
        }
    }

    function renderSubmissions(subs) {
        if (!subs || subs.length === 0) {
            grid.innerHTML = `
                <div class="empty-state">
                    <h3>No active customer forms</h3>
                    <p>When customers start filling forms via voice, they will appear here in real-time.</p>
                </div>
            `;
            return;
        }

        grid.innerHTML = '';
        subs.forEach(sub => {
            const card = document.createElement('div');
            card.className = 'monitor-card';

            const userDisplay = sub.user_id ? `User: ${sub.user_id.slice(-6).toUpperCase()}` : 'Anonymous';
            const stateLabel = (sub.conversation_state || 'FILLING_FORM').replace('_', ' ');

            // Calculate progress (use dummy total of 5 fields if not available)
            const currentIdx = sub.current_field_index || 0;
            const total = 5; // standard fallback
            const pct = Math.min(100, Math.round((currentIdx / total) * 100));

            // Answers HTML
            let answersHtml = '';
            if (sub.data && sub.data.length > 0) {
                sub.data.forEach(ans => {
                    answersHtml += `
                        <div class="answer-row">
                            <span class="field-label">${ans.field_key}:</span>
                            <span class="field-value">${ans.value || '—'}</span>
                        </div>
                    `;
                });
            } else {
                answersHtml = '<div style="color:var(--text-muted); font-size:12px; padding:4px;">No fields filled yet.</div>';
            }

            card.innerHTML = `
                <div class="card-header">
                    <div class="customer-meta">
                        <span class="customer-id">${userDisplay}</span>
                        <div class="form-name-badge">${sub.form_name || 'Savings Form'}</div>
                    </div>
                    <span class="state-badge ${sub.conversation_state || 'filling_form'}">${stateLabel}</span>
                </div>

                <div class="progress-bar-container">
                    <div class="progress-meta">
                        <span>Filling progress</span>
                        <span>${pct}%</span>
                    </div>
                    <div class="progress-bar-bg">
                        <div class="progress-bar-fill" style="width: ${pct}%;"></div>
                    </div>
                </div>

                <div class="answers-title">Current Answers</div>
                <div class="answers-list">
                    ${answersHtml}
                </div>

                <div class="override-controls">
                    <div class="override-title">✏️ Banker Direct Override</div>
                    <div class="override-form" data-sub-id="${sub.id}">
                        <select class="override-select" id="override-key-${sub.id}">
                            <option value="full_name">Full Name</option>
                            <option value="dob">Date of Birth</option>
                            <option value="annual_income">Annual Income</option>
                            <option value="nominee_name">Nominee Name</option>
                            <option value="email">Email Address</option>
                        </select>
                        <input type="text" class="override-input" id="override-val-${sub.id}" placeholder="Enter corrected value">
                        <button class="btn-override" onclick="triggerOverride('${sub.id}')">Override</button>
                    </div>
                </div>
            `;
            grid.appendChild(card);
        });
    }

    // Expose triggerOverride to global scope for button onclicks
    window.triggerOverride = async function (submissionId) {
        const keySelect = document.getElementById(`override-key-${submissionId}`);
        const valInput = document.getElementById(`override-val-${submissionId}`);
        if (!keySelect || !valInput) return;

        const fieldKey = keySelect.value;
        const value = valInput.value.trim();

        if (!value) {
            BankAI_Toast.error('Please enter a value to override!');
            return;
        }

        try {
            const res = await BankAI_API.request(`/api/v1/submissions/${submissionId}/override`, {
                method: 'POST',
                body: { field_key: fieldKey, value: value }
            });

            if (res.ok) {
                BankAI_Toast.success(`Successfully set ${fieldKey} to: ${value}`);
                valInput.value = '';
                // Reload list
                loadActiveSubmissions();
            } else {
                const err = await res.json().catch(() => ({}));
                BankAI_Toast.error(err.detail || 'Override failed.');
            }
        } catch (err) {
            console.error('Failed to trigger override:', err);
            BankAI_Toast.error('Network error during override.');
        }
    };

    // Auto-refresh interval (every 4 seconds)
    setInterval(loadActiveSubmissions, 4000);

    // Initial load
    loadActiveSubmissions();

    if (refreshBtn) {
        refreshBtn.addEventListener('click', loadActiveSubmissions);
    }
})();
