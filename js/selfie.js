/* ═══════════════════════════════════════════════════
   selfie.js  —  Selfie capture & storage
   ═══════════════════════════════════════════════════ */

const SelfieModule = (() => {
    let selfieDataUrl = null;

    /**
     * Capture selfie from video
     * @param {HTMLVideoElement} videoEl
     * @param {HTMLCanvasElement} canvasEl
     * @returns {string} base64 data URL
     */
    function capture(videoEl, canvasEl) {
        const w = videoEl.videoWidth;
        const h = videoEl.videoHeight;
        canvasEl.width = w;
        canvasEl.height = h;
        const ctx = canvasEl.getContext('2d');

        // Mirror the selfie (front camera is mirrored)
        ctx.translate(w, 0);
        ctx.scale(-1, 1);
        ctx.drawImage(videoEl, 0, 0, w, h);
        ctx.setTransform(1, 0, 0, 1, 0, 0); // reset

        selfieDataUrl = canvasEl.toDataURL('image/jpeg', 0.92);
        return selfieDataUrl;
    }

    /** Get stored selfie */
    function getSelfie() {
        return selfieDataUrl;
    }

    /** Clear stored selfie */
    function clear() {
        selfieDataUrl = null;
    }

    return { capture, getSelfie, clear };
})();
