/* ═══════════════════════════════════════════════════
   app.js  —  KYC Flow orchestrator / state machine
   ═══════════════════════════════════════════════════ */

(() => {
    'use strict';

    // ── Accessibility & Language Toggle Setup ──
    const btnA11yToggle = document.getElementById('btnA11yToggle');
    const langSelect = document.getElementById('langSelect');

    // Initialize Theme
    if (localStorage.getItem('a11yMode') === 'enabled') {
        document.body.classList.add('accessibility-mode');
        if (btnA11yToggle) btnA11yToggle.textContent = '♿ Normal Mode';
    }

    if (btnA11yToggle) {
        btnA11yToggle.addEventListener('click', () => {
            const enabled = document.body.classList.toggle('accessibility-mode');
            localStorage.setItem('a11yMode', enabled ? 'enabled' : 'disabled');
            btnA11yToggle.textContent = enabled ? '♿ Normal Mode' : '♿ Easy Mode';
            if (window.BankAI_Toast) {
                window.BankAI_Toast.info(enabled ? 'Accessibility Mode enabled (Large font / High contrast)' : 'Normal mode restored');
            }
        });
    }

    // Initialize Language
    const storedLang = localStorage.getItem('userLanguage') || 'en-IN';
    if (langSelect) {
        langSelect.value = storedLang;
        langSelect.addEventListener('change', () => {
            localStorage.setItem('userLanguage', langSelect.value);
            if (window.BankAI_Toast) {
                window.BankAI_Toast.info(`Language set to ${langSelect.options[langSelect.selectedIndex].text}`);
            }
        });
    }

    // ── State ──
    const kycData = {
        aadhaar: null,
        pan: null,
        selfie: null,
    };

    let currentStep = 1;

    // ── DOM refs ──
    const stepItems = document.querySelectorAll('.step-item');
    const connectorFills = document.querySelectorAll('.connector-fill');
    const panels = document.querySelectorAll('.kyc-panel');

    // Step 1 — Aadhaar
    const startAadhaar = document.getElementById('start-aadhaar');
    const videoAadhaar = document.getElementById('video-aadhaar');
    const canvasAadhaar = document.getElementById('canvas-aadhaar');
    const viewportAadh = document.getElementById('viewport-aadhaar');
    const countdownAadh = document.getElementById('countdown-aadhaar');
    const previewAadh = document.getElementById('preview-aadhaar');
    const capturedImgAdh = document.getElementById('captured-img-aadhaar');
    const loaderAadh = document.getElementById('loader-aadhaar');
    const progressAadh = document.getElementById('progress-aadhaar');
    const resultAadh = document.getElementById('result-aadhaar');
    const inputAadh = document.getElementById('input-aadhaar');
    const retryAadh = document.getElementById('retry-aadhaar');
    const confirmAadh = document.getElementById('confirm-aadhaar');

    // Step 2 — PAN
    const startPan = document.getElementById('start-pan');
    const videoPan = document.getElementById('video-pan');
    const canvasPan = document.getElementById('canvas-pan');
    const viewportPan = document.getElementById('viewport-pan');
    const countdownPan = document.getElementById('countdown-pan');
    const previewPan = document.getElementById('preview-pan');
    const capturedImgPan = document.getElementById('captured-img-pan');
    const loaderPan = document.getElementById('loader-pan');
    const progressPan = document.getElementById('progress-pan');
    const resultPan = document.getElementById('result-pan');
    const inputPan = document.getElementById('input-pan');
    const retryPan = document.getElementById('retry-pan');
    const confirmPan = document.getElementById('confirm-pan');

    // Step 3 — Selfie
    const startSelfie = document.getElementById('start-selfie');
    const videoSelfie = document.getElementById('video-selfie');
    const canvasSelfie = document.getElementById('canvas-selfie');
    const previewSelf = document.getElementById('preview-selfie');
    const capturedImgSlf = document.getElementById('captured-img-selfie');
    const captureSelfie = document.getElementById('capture-selfie');
    const selfieActions = document.getElementById('selfie-actions');
    const retakeSelfie = document.getElementById('retake-selfie');
    const useSelfie = document.getElementById('use-selfie');

    // Success
    const summaryAadh = document.getElementById('summary-aadhaar');
    const summaryPan = document.getElementById('summary-pan');
    const summarySelfie = document.getElementById('summary-selfie');

    // ══════════════════════════════════
    // Step Navigation
    // ══════════════════════════════════
    function goToStep(step) {
        currentStep = step;

        // Update stepper
        stepItems.forEach((el, i) => {
            const s = i + 1;
            el.classList.remove('active', 'completed');
            if (s < step) el.classList.add('completed');
            if (s === step) el.classList.add('active');
        });

        // Connector fills
        connectorFills.forEach((fill, i) => {
            fill.style.width = (i + 1 < step) ? '100%' : '0%';
        });

        // Panels
        const panelIds = ['panel-aadhaar', 'panel-pan', 'panel-selfie', 'panel-success'];
        panels.forEach(p => p.classList.remove('active'));
        const targetPanel = document.getElementById(panelIds[step - 1]);
        // Trigger re-animation
        targetPanel.style.animation = 'none';
        targetPanel.offsetHeight; // reflow
        targetPanel.style.animation = '';
        targetPanel.classList.add('active');
    }

    // ── Voice Guidance / Screen Reader helpers ──
    const A11Y_STRINGS = {
        'en-IN': {
            holdAadhaar: "Please hold your Aadhaar card steady in front of the camera. Capturing in three seconds.",
            holdPan: "Please hold your PAN card steady in front of the camera. Capturing in three seconds.",
            selfie: "Please look straight into the camera and hold still. Capturing in three seconds.",
            readAadhaar: "I scanned your Aadhaar number as {num}. If this is correct, tap Confirm. Otherwise, edit it or scan again.",
            readPan: "I scanned your PAN number as {num}. If this is correct, tap Confirm. Otherwise, edit it or scan again."
        },
        'hi-IN': {
            holdAadhaar: "कृपया अपना आधार कार्ड कैमरे के सामने सीधा रखें। तीन सेकंड में फोटो ली जाएगी।",
            holdPan: "कृपया अपना पैन कार्ड कैमरे के सामने सीधा रखें। तीन सेकंड में फोटो ली जाएगी।",
            selfie: "कृपया सीधे कैमरे में देखें और शांत रहें। तीन सेकंड में फोटो ली जाएगी।",
            readAadhaar: "मैंने आपका आधार नंबर {num} पढ़ा है। यदि यह सही है, तो आगे बढ़ें। नहीं तो सुधारें या फिर से स्कैन करें।",
            readPan: "मैंने आपका पैन नंबर {num} पढ़ा है। यदि यह सही है, तो आगे बढ़ें। नहीं तो सुधारें या फिर से स्कैन करें।"
        },
        'kn-IN': {
            holdAadhaar: "ದಯವಿಟ್ಟು ನಿಮ್ಮ ಆಧಾರ್ ಕಾರ್ಡ್ ಅನ್ನು ಕ್ಯಾಮೆರಾದ ಮುಂದೆ ಸ್ಥಿರವಾಗಿ ಹಿಡಿಯಿರಿ. ಮೂರು ಸೆಕೆಂಡುಗಳಲ್ಲಿ ಫೋಟೋ ತೆಗೆದುಕೊಳ್ಳಲಾಗುವುದು.",
            holdPan: "ದಯವಿಟ್ಟು ನಿಮ್ಮ ಪ್ಯಾನ್ ಕಾರ್ಡ್ ಅನ್ನು ಕ್ಯಾಮೆರಾದ ಮುಂದೆ ಸ್ಥಿರವಾಗಿ ಹಿಡಿಯಿರಿ. ಮೂರು ಸೆಕೆಂಡುಗಳಲ್ಲಿ ಫೋಟೋ ತೆಗೆದುಕೊಳ್ಳಲಾಗುವುದು.",
            selfie: "ದಯವಿಟ್ಟು ನೇರವಾಗಿ ಕ್ಯಾಮೆರಾವನ್ನು ನೋಡಿ ಮತ್ತು ಸ್ಥಿರವಾಗಿರಿ. ಮೂರು ಸೆಕೆಂಡುಗಳಲ್ಲಿ ಫೋಟೋ ತೆಗೆದುಕೊಳ್ಳಲಾಗುವುದು.",
            readAadhaar: "ನಿಮ್ಮ ಆಧಾರ್ ಸಂಖ್ಯೆ {num} ಎಂದು ನಾನು ಓದಿದ್ದೇನೆ. ಇದು ಸರಿಯಾಗಿದ್ದರೆ ದೃಢೀಕರಿಸಿ, ಇಲ್ಲದಿದ್ದರೆ ತಿದ್ದಿ ಅಥವಾ ಮತ್ತೆ ಸ್ಕ್ಯಾನ್ ಮಾಡಿ.",
            readPan: "ನಿಮ್ಮ ಪ್ಯಾನ್ ಸಂಖ್ಯೆ {num} ಎಂದು ನಾನು ಓದಿದ್ದೇನೆ. ಇದು ಸರಿಯಾಗಿದ್ದರೆ ದೃಢೀಕರಿಸಿ, ಇಲ್ಲದಿದ್ದರೆ ತಿದ್ದಿ ಅಥವಾ ಮತ್ತೆ ಸ್ಕ್ಯಾನ್ ಮಾಡಿ."
        },
        'te-IN': {
            holdAadhaar: "దయచేసి మీ ఆధార్ కార్డ్‌ని కెమెరా ముందు స్థిరంగా ఉంచండి. మూడు సెకన్లలో ఫోటో తీయబడుతుంది.",
            holdPan: "దయచేసి మీ పాన్ కార్డ్‌ని కెమెరా ముందు స్థిరంగా ఉంచండి. మూడు సెకన్లలో ఫోటో తీయబడుతుంది.",
            selfie: "దయచేసి నేరుగా కెమెరా వైపు చూస్తూ నిశ్శబ్దంగా ఉండండి. మూడు సెకన్లలో ఫోటో తీయబడుతుంది.",
            readAadhaar: "నేను మీ ఆధార్ నంబర్‌ను {num} గా చదివాను. ఇది సరైనదైతే కన్ఫర్మ్ చేయండి, లేదంటే సరిచేసి మళ్లీ స్ಕಾన్ చేయండి.",
            readPan: "నేను మీ పాన్ నంబర్‌ను {num} గా చదివాను. ఇది సరైనదైతే కన్ఫర్మ్ చేయండి, లేదంటే సరిచేసి మళ్లీ స్కాన్ చేయండి."
        },
        'ta-IN': {
            holdAadhaar: "தயவுசெய்து உங்கள் ஆதார் அட்டையை கேமராவுக்கு முன்னால் நிலையாக வைக்கவும். மூன்று வினாடிகளில் படம் பிடிக்கப்படும்.",
            holdPan: "தயவுசெய்து உங்கள் பான் அட்டையை கேமராவுக்கு முன்னால் நிலையாக வைக்கவும். மூன்று வினாடிகளில் படம் பிடிக்கப்படும்.",
            selfie: "தயவுசெய்து கேமராவை நேராகப் பார்த்து அசையாமல் இருங்கள். மூன்று வினாடிகளில் படம் பிடிக்கப்படும்.",
            readAadhaar: "உங்கள் ஆதார் எண்ணை {num} எனப் படித்துள்ளேன். இது சரியென்றால் உறுதிப்படுத்தவும், இல்லையெனில் திருத்தவும் அல்லது மீண்டும் ஸ்கேன் செய்யவும்.",
            readPan: "உங்கள் பான் எண்ணை {num} எனப் படித்துள்ளேன். இது சரியென்றால் உறுதிப்படுத்தவும், இல்லையெனில் திருத்தவும் அல்லது மீண்டும் ஸ்கேன் செய்யவும்."
        }
    };

    function getA11yText(key, replacements = {}) {
        const lang = localStorage.getItem('userLanguage') || 'en-IN';
        let str = (A11Y_STRINGS[lang] || A11Y_STRINGS['en-IN'])[key] || '';
        for (const [k, v] of Object.entries(replacements)) {
            str = str.replace(`{${k}}`, v);
        }
        return str;
    }

    function speakA11y(text) {
        if (localStorage.getItem('a11yMode') !== 'enabled') return;
        if (!window.speechSynthesis) return;
        window.speechSynthesis.cancel();
        const currentLang = localStorage.getItem('userLanguage') || 'en-IN';
        const utt = new SpeechSynthesisUtterance(text);
        utt.lang = currentLang;
        
        const voices = window.speechSynthesis.getVoices();
        let targetVoice = voices.find(v => v.lang === currentLang) || 
                          voices.find(v => v.lang.startsWith(currentLang.split('-')[0]));
        if (!targetVoice && currentLang !== 'en-IN') {
            targetVoice = voices.find(v => v.lang === 'en-IN') || voices.find(v => v.lang.startsWith('en'));
        }
        if (targetVoice) utt.voice = targetVoice;
        window.speechSynthesis.speak(utt);
    }

    function makeSpokenDigits(str) {
        if (!str) return '';
        return str.replace(/\s+/g, '').split('').join(', ');
    }

    // ══════════════════════════════════
    // Aadhaar Document Scan (multi-pass OCR)
    // ══════════════════════════════════
    async function runAadhaarScan() {
        startAadhaar.style.display = 'none';
        viewportAadh.style.display = 'block';
        previewAadh.style.display = 'none';
        loaderAadh.style.display = 'none';
        resultAadh.style.display = 'none';

        speakA11y(getA11yText('holdAadhaar'));

        try {
            await CameraModule.start(videoAadhaar, 'environment');
        } catch (err) {
            BankAI_Toast.error('Could not access camera. Please grant camera permission and try again.');
            startAadhaar.style.display = 'block';
            return;
        }

        const dataUrl = await CameraModule.autoCaptureWithCountdown(
            videoAadhaar, canvasAadhaar, countdownAadh, 3
        );

        CameraModule.stop();
        viewportAadh.style.display = 'none';
        capturedImgAdh.src = dataUrl;
        previewAadh.style.display = 'block';

        loaderAadh.style.display = 'block';
        progressAadh.style.width = '0%';

        const result = await OCRModule.recognizeAadhaar(dataUrl, canvasAadhaar, (pct) => {
            progressAadh.style.width = pct + '%';
        });

        loaderAadh.style.display = 'none';
        inputAadh.value = result.number || '';
        resultAadh.style.display = 'block';

        if (!result.number) {
            inputAadh.placeholder = 'Could not detect — please enter manually';
            inputAadh.focus();
            speakA11y(localStorage.getItem('userLanguage') === 'hi-IN' ? 'मैं आपका आधार नंबर नहीं पढ़ पाया। कृपया इसे टाइप करें।' : 'Could not detect card number. Please type it.');
        } else {
            const spokenNum = makeSpokenDigits(result.number);
            speakA11y(getA11yText('readAadhaar', { num: spokenNum }));
        }
    }

    // ══════════════════════════════════
    // PAN Document Scan (multi-pass OCR)
    // ══════════════════════════════════
    async function runPANScan() {
        startPan.style.display = 'none';
        viewportPan.style.display = 'block';
        previewPan.style.display = 'none';
        loaderPan.style.display = 'none';
        resultPan.style.display = 'none';

        speakA11y(getA11yText('holdPan'));

        try {
            await CameraModule.start(videoPan, 'environment');
        } catch (err) {
            BankAI_Toast.error('Could not access camera. Please grant camera permission and try again.');
            startPan.style.display = 'block';
            return;
        }

        const dataUrl = await CameraModule.autoCaptureWithCountdown(
            videoPan, canvasPan, countdownPan, 3
        );

        CameraModule.stop();
        viewportPan.style.display = 'none';
        capturedImgPan.src = dataUrl;
        previewPan.style.display = 'block';

        loaderPan.style.display = 'block';
        progressPan.style.width = '0%';

        const result = await OCRModule.recognizePAN(dataUrl, canvasPan, (pct) => {
            progressPan.style.width = pct + '%';
        });

        loaderPan.style.display = 'none';
        inputPan.value = result.number || '';
        resultPan.style.display = 'block';

        if (!result.number) {
            inputPan.placeholder = 'Could not detect — please enter manually';
            inputPan.focus();
            speakA11y(localStorage.getItem('userLanguage') === 'hi-IN' ? 'मैं आपका पैन नंबर नहीं पढ़ पाया। कृपया इसे टाइप करें।' : 'Could not detect card number. Please type it.');
        } else {
            const spokenNum = makeSpokenDigits(result.number);
            speakA11y(getA11yText('readPan', { num: spokenNum }));
        }
    }

    // ══════════════════════════════════
    // Step 1 — Aadhaar handlers
    // ══════════════════════════════════
    startAadhaar.addEventListener('click', () => runAadhaarScan());

    retryAadh.addEventListener('click', () => {
        resultAadh.style.display = 'none';
        previewAadh.style.display = 'none';
        startAadhaar.style.display = 'block';
        startAadhaar.click();
    });

    // Clear validation error when user types
    inputAadh.addEventListener('input', () => inputAadh.classList.remove('invalid'));
    inputPan.addEventListener('input', () => inputPan.classList.remove('invalid'));

    confirmAadh.addEventListener('click', () => {
        const val = inputAadh.value.trim();
        const aadhaarPattern = /^\d{4}\s?\d{4}\s?\d{4}$/;
        if (!val || !aadhaarPattern.test(val)) {
            inputAadh.classList.add('invalid');
            BankAI_Toast.error('Please enter a valid 12-digit Aadhaar number.');
            inputAadh.focus();
            return;
        }
        kycData.aadhaar = val;
        CameraModule.stop();
        goToStep(2);
        setTimeout(() => startPan.click(), 400);
    });

    // ══════════════════════════════════
    // Step 2 — PAN handlers
    // ══════════════════════════════════
    startPan.addEventListener('click', () => runPANScan());

    retryPan.addEventListener('click', () => {
        resultPan.style.display = 'none';
        previewPan.style.display = 'none';
        startPan.style.display = 'block';
        startPan.click();
    });

    confirmPan.addEventListener('click', () => {
        const val = inputPan.value.trim().toUpperCase();
        const panPattern = /^[A-Z]{5}\d{4}[A-Z]$/;
        if (!val || !panPattern.test(val)) {
            inputPan.classList.add('invalid');
            BankAI_Toast.error('Please enter a valid 10-character PAN (e.g. ABCDE1234F).');
            inputPan.focus();
            return;
        }
        inputPan.value = val; // Set the cleaned uppercase value back to UI
        kycData.pan = val;
        CameraModule.stop();
        goToStep(3);
        setTimeout(() => startSelfie.click(), 400);
    });

    // ══════════════════════════════════
    // Step 3 — Selfie handlers
    // ══════════════════════════════════
    startSelfie.addEventListener('click', async () => {
        startSelfie.style.display = 'none';
        previewSelf.style.display = 'none';
        selfieActions.style.display = 'none';

        speakA11y(getA11yText('selfie'));

        const viewport = document.getElementById('viewport-selfie');
        viewport.style.display = 'block';
        captureSelfie.style.display = 'flex';

        // Mirror the video for selfie
        videoSelfie.style.transform = 'scaleX(-1)';

        try {
            await CameraModule.start(videoSelfie, 'user');
        } catch (err) {
            BankAI_Toast.error('Could not access front camera. Please grant permission and try again.');
            startSelfie.style.display = 'block';
            captureSelfie.style.display = 'none';
            return;
        }
    });

    captureSelfie.addEventListener('click', () => {
        const dataUrl = SelfieModule.capture(videoSelfie, canvasSelfie);
        CameraModule.stop();

        const viewport = document.getElementById('viewport-selfie');
        viewport.style.display = 'none';
        captureSelfie.style.display = 'none';

        capturedImgSlf.src = dataUrl;
        previewSelf.style.display = 'block';
        selfieActions.style.display = 'flex';
    });

    retakeSelfie.addEventListener('click', () => {
        SelfieModule.clear();
        startSelfie.click();
    });

    useSelfie.addEventListener('click', () => {
        kycData.selfie = SelfieModule.getSelfie();
        CameraModule.stop();
        showSuccess();
    });

    // ══════════════════════════════════
    // Success Screen
    // ══════════════════════════════════
    function showSuccess() {
        // Mark step 3 as completed
        stepItems[2].classList.remove('active');
        stepItems[2].classList.add('completed');
        connectorFills[1].style.width = '100%';

        // Populate summary
        const aadhaarVal = kycData.aadhaar || '—';
        // Mask Aadhaar: show only last 4 digits
        const masked = aadhaarVal.length >= 4
            ? 'XXXX XXXX ' + aadhaarVal.slice(-4)
            : aadhaarVal;
        summaryAadh.textContent = masked;
        summaryPan.textContent = kycData.pan || '—';

        if (kycData.selfie) {
            summarySelfie.src = kycData.selfie;
        }

        // Navigate to success panel
        panels.forEach(p => p.classList.remove('active'));
        const successPanel = document.getElementById('panel-success');
        successPanel.style.animation = 'none';
        successPanel.offsetHeight;
        successPanel.style.animation = '';
        successPanel.classList.add('active');

        // Spawn particles
        spawnParticles();

        // Send to backend
        submitKYC();
    }

    function spawnParticles() {
        const container = document.getElementById('particles');
        container.innerHTML = '';
        const colors = ['#34d399', '#38bdf8', '#a78bfa', '#fbbf24', '#f472b6'];
        for (let i = 0; i < 18; i++) {
            const p = document.createElement('div');
            p.className = 'particle';
            const angle = (i / 18) * 360;
            const dist = 50 + Math.random() * 40;
            const dx = Math.cos(angle * Math.PI / 180) * dist;
            const dy = Math.sin(angle * Math.PI / 180) * dist;
            p.style.background = colors[i % colors.length];
            p.style.setProperty('--dx', dx + 'px');
            p.style.setProperty('--dy', dy + 'px');
            p.style.animation = `particleBurst 0.8s ease ${i * 0.04}s forwards`;
            p.style.transform = `translate(-50%, -50%)`;
            // Override animation with custom end position
            p.animate([
                { transform: 'translate(-50%, -50%) scale(0)', opacity: 1 },
                { transform: `translate(calc(-50% + ${dx}px), calc(-50% + ${dy}px)) scale(1)`, opacity: 0 },
            ], { duration: 800, delay: i * 40, easing: 'ease-out', fill: 'forwards' });
            container.appendChild(p);
        }
    }

    // ══════════════════════════════════
    // Backend submission
    // ══════════════════════════════════
    async function submitKYC() {
        const dashBtn = document.getElementById('go-to-dashboard');
        dashBtn.disabled = true;
        dashBtn.textContent = 'Submitting…';

        const payload = {
            aadhaar: kycData.aadhaar,
            pan: kycData.pan,
            selfie: kycData.selfie, // base64
        };

        try {
            const res = await BankAI_API.request(BankAI_API.ENDPOINTS.KYC_SUBMIT, {
                method: 'POST',
                body: payload,
                auth: false, // KYC submit doesn't need a prior token — it creates one
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            const data = await res.json();

            // Store token + user info for dashboard
            if (data.access_token) {
                sessionStorage.setItem('bankai_token', data.access_token);
            }
            if (data.submission_id !== undefined) {
                sessionStorage.setItem('bankai_submission_id', data.submission_id);
            }
            // Store masked values for dashboard display
            sessionStorage.setItem('bankai_aadhaar_masked', summaryAadh.textContent);
            sessionStorage.setItem('bankai_pan', kycData.pan || '—');
            if (kycData.selfie) sessionStorage.setItem('bankai_selfie', kycData.selfie);

            // Store last-4 of aadhaar for future logins (returning user)
            const raw = kycData.aadhaar || '';
            const digitsOnly = raw.replace(/\s/g, '');
            if (digitsOnly.length >= 4) {
                sessionStorage.setItem('bankai_aadhaar_last4', digitsOnly.slice(-4));
            }

            BankAI_Toast.success('KYC Submitted Successfully! Opening Dashboard...');
            setTimeout(() => {
                window.location.href = '/dashboard.html';
            }, 1500);

        } catch (err) {
            console.warn('Backend submission failed (offline mode):', err.message);
            BankAI_Toast.warning('Could not reach server — running in demo mode.');

            // Offer login page as alternative
            const dashBtn2 = document.getElementById('go-to-dashboard');
            dashBtn2.disabled = false;
            dashBtn2.innerHTML = 'Open Dashboard (Demo) →';

            setTimeout(() => {
                window.location.href = '/dashboard.html';
            }, 2000);
        }

        dashBtn.disabled = false;
        dashBtn.textContent = 'Open Dashboard →';
    }

    // ── Dashboard navigation ──
    document.getElementById('go-to-dashboard').addEventListener('click', () => {
        window.location.href = '/dashboard.html';
    });

    // ── Init ──
    goToStep(1);

})();
