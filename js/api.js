/**
 * BankAI — Shared API Client
 */
const BankAI_API = (() => {
  const BASE = '/api/v1';

  const ENDPOINTS = {
    KYC_SUBMIT: `${BASE}/kyc/submit`,
    AUTH_ME: `${BASE}/auth/me`,
    CONVERSATION_CHAT: `${BASE}/conversation/chat`,
    CONVERSATION_NEXT: `${BASE}/conversation/next`,
    SUBMISSIONS: `${BASE}/submissions`,
    SUBMISSIONS_START: `${BASE}/submissions/start`,
    SUBMISSIONS_COMPLETE: `${BASE}/submissions/complete`,
    ADMIN_BANKS: `${BASE}/admin/banks`,
    ADMIN_FORMS: `${BASE}/admin/forms`,
    ADMIN_SECTIONS: `${BASE}/admin/sections`,
    ADMIN_FIELDS: `${BASE}/admin/fields`,
    ADMIN_SUBMISSIONS: `${BASE}/admin/submissions`,
  };

  // Dynamic URL builders for submission-scoped endpoints
  const submissionSignatureUrl = (submissionId) =>
    `${BASE}/submissions/${submissionId}/signature`;

  const submissionPdfUrl = (submissionId) =>
    `${BASE}/submissions/${submissionId}/pdf`;

  function getToken() {
    // KYC auth stores token in sessionStorage
    return sessionStorage.getItem('bankai_token') || sessionStorage.getItem('adminToken') || '';
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
      
      // Auto redirect to index/login if 401 Unauthorized
      if (res.status === 401) {
        sessionStorage.removeItem('bankai_token');
        sessionStorage.removeItem('adminToken');
        // Avoid infinite loop if we are already on index.html
        if (!window.location.pathname.endsWith('/index.html') && window.location.pathname !== '/') {
          window.location.href = '/index.html';
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
   * Upload a base64 signature image for a submission.
   * @param {string} submissionId  - Firestore submission doc ID
   * @param {string} base64Image   - base64 string (with or without data URL prefix)
   * @returns {Promise<Response>}
   */
  async function uploadSignature(submissionId, base64Image) {
    return request(submissionSignatureUrl(submissionId), {
      method: 'POST',
      body: { image: base64Image },
    });
  }

  /**
   * Download the generated PDF for a completed submission.
   * Triggers a file-save dialog in the browser.
   * @param {string} submissionId  - Firestore submission doc ID
   * @returns {Promise<void>}
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
    uploadSignature,
    downloadPdf,
  };
})();
