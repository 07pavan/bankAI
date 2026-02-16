/* ═══════════════════════════════════════════════════
   camera.js  —  Camera access, auto-capture, stream mgmt
   With image preprocessing for better OCR accuracy
   ═══════════════════════════════════════════════════ */

const CameraModule = (() => {
  let activeStream = null;

  /**
   * Start camera and pipe to <video>
   * @param {HTMLVideoElement} videoEl
   * @param {'environment'|'user'} facing
   * @returns {Promise<MediaStream>}
   */
  async function start(videoEl, facing = 'environment') {
    stop();

    const constraints = {
      video: {
        facingMode: facing,
        width: { ideal: 1920 },   // Higher resolution for better OCR
        height: { ideal: 1440 },
      },
      audio: false,
    };

    try {
      activeStream = await navigator.mediaDevices.getUserMedia(constraints);
      videoEl.srcObject = activeStream;
      await videoEl.play();
      return activeStream;
    } catch (err) {
      console.error('Camera error:', err);
      throw err;
    }
  }

  /** Stop active camera stream */
  function stop() {
    if (activeStream) {
      activeStream.getTracks().forEach(t => t.stop());
      activeStream = null;
    }
  }

  /**
   * Capture current video frame to a canvas and return data URL
   */
  function captureFrame(videoEl, canvasEl) {
    const w = videoEl.videoWidth;
    const h = videoEl.videoHeight;
    canvasEl.width = w;
    canvasEl.height = h;
    const ctx = canvasEl.getContext('2d');
    ctx.drawImage(videoEl, 0, 0, w, h);
    return canvasEl.toDataURL('image/png', 1.0);  // PNG for lossless quality
  }

  /**
   * ─── Image Preprocessing Pipeline ───
   * Applies multiple transformations to improve OCR accuracy
   */
  function preprocessForOCR(canvasEl) {
    const ctx = canvasEl.getContext('2d');
    const w = canvasEl.width;
    const h = canvasEl.height;
    const imageData = ctx.getImageData(0, 0, w, h);
    const data = imageData.data;

    // Step 1: Convert to grayscale
    for (let i = 0; i < data.length; i += 4) {
      const gray = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
      data[i] = gray;
      data[i + 1] = gray;
      data[i + 2] = gray;
    }

    // Step 2: Increase contrast (stretch histogram)
    let min = 255, max = 0;
    for (let i = 0; i < data.length; i += 4) {
      if (data[i] < min) min = data[i];
      if (data[i] > max) max = data[i];
    }
    const range = max - min || 1;
    for (let i = 0; i < data.length; i += 4) {
      const val = Math.round(((data[i] - min) / range) * 255);
      data[i] = val;
      data[i + 1] = val;
      data[i + 2] = val;
    }

    // Step 3: Adaptive thresholding (Sauvola-like)
    // Use a local window to determine threshold
    ctx.putImageData(imageData, 0, 0);
    const grayData = ctx.getImageData(0, 0, w, h);
    const src = grayData.data;
    const out = ctx.createImageData(w, h);
    const dst = out.data;

    const blockSize = 15;
    const half = Math.floor(blockSize / 2);
    const k = 0.08; // Sauvola parameter
    const R = 128;   // dynamic range

    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        let sum = 0, sumSq = 0, count = 0;

        const yStart = Math.max(0, y - half);
        const yEnd = Math.min(h - 1, y + half);
        const xStart = Math.max(0, x - half);
        const xEnd = Math.min(w - 1, x + half);

        for (let ly = yStart; ly <= yEnd; ly++) {
          for (let lx = xStart; lx <= xEnd; lx++) {
            const val = src[(ly * w + lx) * 4];
            sum += val;
            sumSq += val * val;
            count++;
          }
        }

        const mean = sum / count;
        const variance = (sumSq / count) - (mean * mean);
        const stdDev = Math.sqrt(Math.max(0, variance));
        const threshold = mean * (1 + k * ((stdDev / R) - 1));

        const idx = (y * w + x) * 4;
        const pixel = src[idx];
        const bw = pixel > threshold ? 255 : 0;
        dst[idx] = bw;
        dst[idx + 1] = bw;
        dst[idx + 2] = bw;
        dst[idx + 3] = 255;
      }
    }

    ctx.putImageData(out, 0, 0);
    return canvasEl.toDataURL('image/png', 1.0);
  }

  /**
   * Simpler preprocessing: just grayscale + high contrast + sharpen
   * Used as a fallback / alternate pass
   */
  function preprocessSimple(canvasEl) {
    const ctx = canvasEl.getContext('2d');
    const w = canvasEl.width;
    const h = canvasEl.height;
    const imageData = ctx.getImageData(0, 0, w, h);
    const data = imageData.data;

    // Grayscale + strong contrast boost
    for (let i = 0; i < data.length; i += 4) {
      let gray = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
      // Contrast factor 2.0
      gray = ((gray - 128) * 2.0) + 128;
      gray = Math.max(0, Math.min(255, gray));
      data[i] = gray;
      data[i + 1] = gray;
      data[i + 2] = gray;
    }

    ctx.putImageData(imageData, 0, 0);

    // Apply unsharp mask via CSS filter trick (re-draw with filter)
    const tempCanvas = document.createElement('canvas');
    tempCanvas.width = w;
    tempCanvas.height = h;
    const tempCtx = tempCanvas.getContext('2d');
    tempCtx.filter = 'contrast(1.5) brightness(1.1)';
    tempCtx.drawImage(canvasEl, 0, 0);

    ctx.drawImage(tempCanvas, 0, 0);
    return canvasEl.toDataURL('image/png', 1.0);
  }

  /**
   * Auto-capture with countdown — longer delay for better positioning
   */
  function autoCaptureWithCountdown(videoEl, canvasEl, countdownEl, seconds = 3) {
    return new Promise((resolve) => {
      const numSpan = countdownEl.querySelector('.countdown-num');
      countdownEl.style.display = 'flex';
      let remaining = seconds;
      numSpan.textContent = remaining;

      const interval = setInterval(() => {
        remaining -= 1;
        if (remaining <= 0) {
          clearInterval(interval);
          countdownEl.style.display = 'none';
          // Flash effect
          countdownEl.parentElement.style.transition = 'filter 0.15s';
          countdownEl.parentElement.style.filter = 'brightness(2)';
          setTimeout(() => {
            countdownEl.parentElement.style.filter = 'brightness(1)';
          }, 150);
          const dataUrl = captureFrame(videoEl, canvasEl);
          resolve(dataUrl);
        } else {
          numSpan.textContent = remaining;
        }
      }, 1000);
    });
  }

  return { start, stop, captureFrame, autoCaptureWithCountdown, preprocessForOCR, preprocessSimple };
})();
