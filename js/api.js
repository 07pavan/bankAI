/**
 * BankAI — Shared API Client (v2)
 * Centralised fetch wrapper used by all user-facing pages.
 */
const BankAI_API = (() => {
  const BASE = '/api/v1';

  const ENDPOINTS = {
    // Auth
    AUTH_ME:              `${BASE}/auth/me`,
    AUTH_LOGIN:           `${BASE}/auth/login`,

    // KYC
    KYC_SUBMIT:           `${BASE}/kyc/submit`,

    // Forms (JWT-protected, returns forms for user's bank)
    FORMS:                `${BASE}/forms`,

    // Conversation
    CONVERSATION_CHAT:    `${BASE}/conversation/chat`,
    CONVERSATION_NEXT:    `${BASE}/conversation/next`,

    // Submissions lifecycle
    SUBMISSIONS:          `${BASE}/submissions`,
    SUBMISSIONS_START:    `${BASE}/submissions/start`,
    SUBMISSIONS_COMPLETE: `${BASE}/submissions/complete`,

    // Admin
    ADMIN_BANKS:          `${BASE}/admin/banks`,
    ADMIN_FORMS:          `${BASE}/admin/forms`,
    ADMIN_SECTIONS:       `${BASE}/admin/sections`,
    ADMIN_FIELDS:         `${BASE}/admin/fields`,
    ADMIN_SUBMISSIONS:    `${BASE}/admin/submissions`,
    ADMIN_AUDITS:         `${BASE}/admin/audits`,
  };

  // Dynamic URL builders
  const submissionSignatureUrl  = (id) => `${BASE}/submissions/${id}/signature`;
  const submissionPdfUrl        = (id) => `${BASE}/submissions/${id}/pdf`;
  const conversationStatusUrl   = (id) => `${BASE}/conversation/status/${id}`;

  function getToken() {
    return (
      sessionStorage.getItem('bankai_token') ||
      sessionStorage.getItem('adminToken') ||
      ''
    );
  }

  function clearSession() {
    sessionStorage.removeItem('bankai_token');
    sessionStorage.removeItem('bankai_submission_id');
    sessionStorage.removeItem('bankai_aadhaar_masked');
    sessionStorage.removeItem('bankai_pan');
  }

  async function request(url, { method = 'GET', body = null, auth = true } = {}) {
    const headers = { 'Content-Type': 'application/json' };
    const token = getToken();

    if (auth && token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const opts = { method, headers };
    if (body) {
      opts.body = JSON.stringify(body);
    }

    try {
      const res = await fetch(url, opts);

      // On 401 — clear session and redirect to login (not back to KYC camera flow)
      if (res.status === 401) {
        clearSession();
        const isLogin = window.location.pathname.endsWith('/login.html');
        const isIndex = window.location.pathname.endsWith('/index.html') ||
                        window.location.pathname === '/';
        if (!isLogin && !isIndex) {
          window.location.href = '/login.html';
        }
        throw new Error('Session expired');
      }

      return res;
    } catch (err) {
      console.error(`API Request Error on ${url}:`, err);
      throw err;
    }
  }

  /**
   * Verify the stored token by calling /auth/me.
   * Returns user profile on success, or null if token is invalid/absent.
   */
  async function verifySession() {
    const token = getToken();
    if (!token) return null;
    try {
      const res = await request(ENDPOINTS.AUTH_ME);
      if (!res.ok) return null;
      return await res.json();
    } catch {
      return null;
    }
  }

  /**
   * Login a returning user by Aadhaar last 4 digits.
   * Pass demoMode=true to skip the check (any existing user).
   */
  async function login(aadhaarLast4, demoMode = false) {
    const res = await request(ENDPOINTS.AUTH_LOGIN, {
      method: 'POST',
      body: { aadhaar_last4: aadhaarLast4, demo_mode: demoMode },
      auth: false,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    const data = await res.json();
    if (data.access_token) {
      sessionStorage.setItem('bankai_token', data.access_token);
    }
    return data;
  }

  /**
   * Get the current conversation status for a submission (session restore).
   * Returns null on 404/error.
   */
  async function getConversationStatus(submissionId) {
    try {
      const res = await request(conversationStatusUrl(submissionId));
      if (!res.ok) return null;
      return await res.json();
    } catch {
      return null;
    }
  }

  /**
   * Upload a base64 signature image for a submission.
   */
  async function uploadSignature(submissionId, base64Image) {
    return request(submissionSignatureUrl(submissionId), {
      method: 'POST',
      body: { image: base64Image },
    });
  }

  /**
   * Download the generated PDF for a completed submission.
   */
  async function downloadPdf(submissionId) {
    const res = await request(submissionPdfUrl(submissionId), { method: 'GET' });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'PDF download failed' }));
      throw new Error(err.detail || 'PDF download failed');
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `BankAI_Application_${submissionId}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  return {
    ENDPOINTS,
    request,
    getToken,
    clearSession,
    verifySession,
    login,
    getConversationStatus,
    uploadSignature,
    downloadPdf,
  };
})();
