/* ═══════════════════════════════════════════════════
   ocr.js  —  Tesseract.js wrapper + Aadhaar / PAN extraction
   With multi-pass OCR and improved extraction logic
   ═══════════════════════════════════════════════════ */

const OCRModule = (() => {

    /**
     * Run OCR with optimized Tesseract parameters
     * @param {string} imageDataUrl — base64 data URL
     * @param {function} onProgress  — progress callback (0–100)
     * @param {object} opts — extra options
     * @returns {Promise<string>}
     */
    async function recognize(imageDataUrl, onProgress, opts = {}) {
        const tesseractConfig = {
            logger: (info) => {
                if (info.status === 'recognizing text' && onProgress) {
                    onProgress(Math.round(info.progress * 100));
                }
            },
        };

        const result = await Tesseract.recognize(imageDataUrl, 'eng', tesseractConfig);
        return result.data.text;
    }

    /**
     * Run OCR specifically tuned for Aadhaar cards
     * Does multiple passes with different preprocessing
     */
    async function recognizeAadhaar(originalDataUrl, canvasEl, onProgress) {
        const results = [];

        // Pass 1: Original image (raw capture)
        onProgress && onProgress(5);
        const text1 = await recognize(originalDataUrl, (p) => onProgress && onProgress(Math.round(p * 0.3)));
        results.push(text1);
        console.log('[OCR Pass 1 - Raw]', text1);

        const extracted1 = extractAadhaar(text1);
        if (extracted1) return { text: text1, number: extracted1 };

        // Pass 2: Adaptive threshold preprocessing
        onProgress && onProgress(35);
        // Reload original image onto canvas for preprocessing
        await drawImageToCanvas(originalDataUrl, canvasEl);
        const preprocessed1 = CameraModule.preprocessForOCR(canvasEl);
        const text2 = await recognize(preprocessed1, (p) => onProgress && onProgress(35 + Math.round(p * 0.3)));
        results.push(text2);
        console.log('[OCR Pass 2 - Threshold]', text2);

        const extracted2 = extractAadhaar(text2);
        if (extracted2) return { text: text2, number: extracted2 };

        // Pass 3: Simple contrast boost
        onProgress && onProgress(70);
        await drawImageToCanvas(originalDataUrl, canvasEl);
        const preprocessed2 = CameraModule.preprocessSimple(canvasEl);
        const text3 = await recognize(preprocessed2, (p) => onProgress && onProgress(70 + Math.round(p * 0.3)));
        results.push(text3);
        console.log('[OCR Pass 3 - Contrast]', text3);

        const extracted3 = extractAadhaar(text3);
        if (extracted3) return { text: text3, number: extracted3 };

        // If no pass found it, try combining all text
        const combinedText = results.join('\n');
        const combinedExtract = extractAadhaar(combinedText);
        onProgress && onProgress(100);

        return { text: combinedText, number: combinedExtract };
    }

    /**
     * Run OCR specifically tuned for PAN cards
     */
    async function recognizePAN(originalDataUrl, canvasEl, onProgress) {
        const results = [];

        // Pass 1: Original
        onProgress && onProgress(5);
        const text1 = await recognize(originalDataUrl, (p) => onProgress && onProgress(Math.round(p * 0.3)));
        results.push(text1);
        console.log('[OCR Pass 1 - Raw]', text1);

        const extracted1 = extractPAN(text1);
        if (extracted1) return { text: text1, number: extracted1 };

        // Pass 2: Adaptive threshold
        onProgress && onProgress(35);
        await drawImageToCanvas(originalDataUrl, canvasEl);
        const preprocessed1 = CameraModule.preprocessForOCR(canvasEl);
        const text2 = await recognize(preprocessed1, (p) => onProgress && onProgress(35 + Math.round(p * 0.3)));
        results.push(text2);
        console.log('[OCR Pass 2 - Threshold]', text2);

        const extracted2 = extractPAN(text2);
        if (extracted2) return { text: text2, number: extracted2 };

        // Pass 3: Simple contrast
        onProgress && onProgress(70);
        await drawImageToCanvas(originalDataUrl, canvasEl);
        const preprocessed2 = CameraModule.preprocessSimple(canvasEl);
        const text3 = await recognize(preprocessed2, (p) => onProgress && onProgress(70 + Math.round(p * 0.3)));
        results.push(text3);
        console.log('[OCR Pass 3 - Contrast]', text3);

        const extracted3 = extractPAN(text3);
        if (extracted3) return { text: text3, number: extracted3 };

        // Combine all text
        const combinedText = results.join('\n');
        const combinedExtract = extractPAN(combinedText);
        onProgress && onProgress(100);

        return { text: combinedText, number: combinedExtract };
    }

    /**
     * Helper: draw a data URL image onto a canvas
     */
    function drawImageToCanvas(dataUrl, canvasEl) {
        return new Promise((resolve) => {
            const img = new Image();
            img.onload = () => {
                canvasEl.width = img.width;
                canvasEl.height = img.height;
                const ctx = canvasEl.getContext('2d');
                ctx.drawImage(img, 0, 0);
                resolve();
            };
            img.src = dataUrl;
        });
    }

    /**
     * Extract Aadhaar number from OCR text
     * Enhanced: handles common OCR misreads, spaces, dashes
     */
    function extractAadhaar(text) {
        if (!text) return null;

        // Normalize: fix common OCR misreads for digits
        let cleaned = text
            .replace(/[oO]/g, '0')   // O → 0
            .replace(/[lI|]/g, '1')  // l, I, | → 1
            .replace(/[zZ]/g, '2')   // Z → 2
            .replace(/[sS]/g, '5')   // S → 5
            .replace(/[bB]/g, '8');  // B → 8 (only in digit context)

        // Pattern 1: Spaced format "XXXX XXXX XXXX"
        const spacedMatch = cleaned.match(/(\d{4}[\s\-\.]+\d{4}[\s\-\.]+\d{4})/);
        if (spacedMatch) {
            const digits = spacedMatch[1].replace(/[^\d]/g, '');
            if (digits.length === 12) {
                return `${digits.slice(0, 4)} ${digits.slice(4, 8)} ${digits.slice(8, 12)}`;
            }
        }

        // Pattern 2: Consecutive 12 digits
        const solidMatch = cleaned.match(/\b(\d{12})\b/);
        if (solidMatch) {
            const d = solidMatch[1];
            return `${d.slice(0, 4)} ${d.slice(4, 8)} ${d.slice(8, 12)}`;
        }

        // Pattern 3: Find any cluster of 12+ digits in the text
        const allDigits = cleaned.replace(/[^\d\s]/g, '').replace(/\s+/g, '');
        if (allDigits.length >= 12) {
            // Look for the longest run of digits
            const runs = cleaned.match(/[\d\s\-\.]{12,}/g);
            if (runs) {
                for (const run of runs) {
                    const digits = run.replace(/[^\d]/g, '');
                    if (digits.length >= 12) {
                        const d = digits.slice(0, 12);
                        // Validate: Aadhaar doesn't start with 0 or 1
                        if (d[0] !== '0' && d[0] !== '1') {
                            return `${d.slice(0, 4)} ${d.slice(4, 8)} ${d.slice(8, 12)}`;
                        }
                    }
                }
            }

            // Fallback: just take first 12 digits found anywhere
            if (allDigits.length >= 12) {
                const d = allDigits.slice(0, 12);
                return `${d.slice(0, 4)} ${d.slice(4, 8)} ${d.slice(8, 12)}`;
            }
        }

        return null;
    }

    /**
     * Extract PAN from OCR text
     * Enhanced: handles common OCR misreads
     */
    function extractPAN(text) {
        if (!text) return null;

        // Normalize: uppercase everything
        let cleaned = text.toUpperCase();

        // Fix common OCR digit→letter and letter→digit misreads in PAN context
        // PAN format: AAAAA9999A (5 alpha + 4 digit + 1 alpha)

        // Direct match first
        const directMatch = cleaned.match(/[A-Z]{5}\d{4}[A-Z]/);
        if (directMatch) return directMatch[0];

        // Try with common misreads fixed
        // Replace common misreads: 0↔O, 1↔I/L, 5↔S, 8↔B
        const lines = cleaned.split(/\n/);
        for (const line of lines) {
            // Try each segment that looks roughly like PAN (10 chars, mix of alpha & digit)
            const segments = line.match(/[A-Z0-9]{10,12}/g);
            if (!segments) continue;

            for (const seg of segments) {
                // Try to force-fit PAN pattern
                const fixed = forcePANPattern(seg);
                if (fixed) return fixed;
            }
        }

        // Broader search: look for "Permanent Account Number" nearby text
        const panArea = cleaned.match(/(?:PERMANENT|ACCOUNT|NUMBER|INCOME\s*TAX)[^\n]*\n?([^\n]*)/i);
        if (panArea) {
            const nearbyMatch = panArea[1].match(/[A-Z]{5}\d{4}[A-Z]/);
            if (nearbyMatch) return nearbyMatch[0];
        }

        return null;
    }

    /**
     * Try to force-fit a 10-char string into PAN pattern AAAAA9999A
     */
    function forcePANPattern(str) {
        if (str.length < 10) return null;
        const s = str.slice(0, 10);

        let result = '';

        // Positions 0-4: must be letters
        for (let i = 0; i < 5; i++) {
            const c = s[i];
            if (/[A-Z]/.test(c)) {
                result += c;
            } else if (c === '0') {
                result += 'O';
            } else if (c === '1') {
                result += 'I';
            } else if (c === '5') {
                result += 'S';
            } else if (c === '8') {
                result += 'B';
            } else {
                return null; // can't fix
            }
        }

        // Positions 5-8: must be digits
        for (let i = 5; i < 9; i++) {
            const c = s[i];
            if (/\d/.test(c)) {
                result += c;
            } else if (c === 'O') {
                result += '0';
            } else if (c === 'I' || c === 'L') {
                result += '1';
            } else if (c === 'S') {
                result += '5';
            } else if (c === 'B') {
                result += '8';
            } else {
                return null;
            }
        }

        // Position 9: must be letter
        const last = s[9];
        if (/[A-Z]/.test(last)) {
            result += last;
        } else if (last === '0') {
            result += 'O';
        } else if (last === '1') {
            result += 'I';
        } else {
            return null;
        }

        // Validate PAN structure: 4th char indicates type
        if (/^[A-Z]{5}\d{4}[A-Z]$/.test(result)) {
            return result;
        }

        return null;
    }

    return {
        recognize,
        recognizeAadhaar,
        recognizePAN,
        extractAadhaar,
        extractPAN,
    };
})();
