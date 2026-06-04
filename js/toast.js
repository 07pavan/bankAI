/**
 * BankAI — Shared Toast Notification Module
 */
const BankAI_Toast = (() => {
  let container = null;

  function init() {
    if (container) return;
    container = document.createElement('div');
    container.className = 'toast-container';
    container.id = 'bankai-toast-container';
    document.body.appendChild(container);
  }

  /** Escape HTML to prevent XSS from toast message content */
  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  /**
   * Show a toast message
   * @param {string} message - Message to display
   * @param {'info'|'success'|'error'|'warning'} type - Type of toast
   * @param {number} duration - Auto-close duration in ms
   */
  function show(message, type = 'info', duration = 4000) {
    init();

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    
    // Icon mapping
    let icon = 'ℹ️';
    if (type === 'success') icon = '✅';
    if (type === 'error') icon = '❌';
    if (type === 'warning') icon = '⚠️';

    toast.innerHTML = `
      <span class="toast-icon" aria-hidden="true">${icon}</span>
      <span class="toast-message">${escapeHtml(message)}</span>
    `;

    container.appendChild(toast);

    // Auto-remove
    const timeout = setTimeout(() => {
      dismiss(toast);
    }, duration);

    // Allow dismiss on click
    toast.addEventListener('click', () => {
      clearTimeout(timeout);
      dismiss(toast);
    });
  }

  function dismiss(toast) {
    toast.classList.add('fade-out');
    toast.addEventListener('animationend', () => {
      if (toast.parentNode) {
        toast.parentNode.removeChild(toast);
      }
    });
  }

  return {
    show,
    info: (msg, dur) => show(msg, 'info', dur),
    success: (msg, dur) => show(msg, 'success', dur),
    error: (msg, dur) => show(msg, 'error', dur),
    warning: (msg, dur) => show(msg, 'warning', dur)
  };
})();
