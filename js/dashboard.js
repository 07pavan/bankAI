/* ══════════════════════════════════════════════════════════
   BankAI Dashboard — ChatAgent Orchesrator
   ══════════════════════════════════════════════════════════ */

'use strict';

(function initDashboard() {
    // ── Auth verification ──────────────────────────────────────────────────────
    const token = BankAI_API.getToken();
    if (!token) {
        window.location.href = '/index.html';
        return;
    }

    // ── DOM refs ──────────────────────────────────────────────────────────────
    const panel = document.getElementById('aiPanel');
    const history = document.getElementById('chatHistory');
    const inputEl = document.getElementById('chatInput');
    const btnMic = document.getElementById('btnMic');
    const btnSend = document.getElementById('btnSend');
    const micStatus = document.getElementById('micStatus');
    const subtitle = document.getElementById('ai-subtitle');
    const progressWrap = document.getElementById('progressWrap');
    const progressFill = document.getElementById('progressFill');
    const progressLbl = document.getElementById('progressLabel');
    const progressPct = document.getElementById('progressPct');

    // ── Agent state ───────────────────────────────────────────────────────────
    const state = {
        mode: 'chat',          // "chat" | "form_filling" | "done"
        submissionId: null,
        busy: false,
        recognition: null,
        synth: window.speechSynthesis,
        speechEnabled: false, // Start disabled to avoid unsolicited auto-TTS
    };

    // ── Speech Recognition setup ──────────────────────────────────────────────
    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    let recognition = null;
    if (SpeechRec) {
        recognition = new SpeechRec();
        recognition.lang = 'en-IN';
        recognition.interimResults = false;
        recognition.maxAlternatives = 1;

        recognition.onresult = (e) => {
            const transcript = e.results[0][0].transcript.trim();
            stopListening();
            if (transcript) {
                inputEl.value = transcript;
                send();
            }
        };

        recognition.onerror = (e) => {
            stopListening();
            if (e.error !== 'no-speech') {
                showMicStatus('Could not hear you — please try again.', true);
            }
        };

        recognition.onend = () => stopListening();
    } else {
        // Fallback for browsers without Speech Recognition
        btnMic.disabled = true;
        btnMic.title = 'Voice input is not supported in this browser. Please use Chrome or Edge.';
        btnMic.setAttribute('aria-label', 'Voice input unavailable');
        inputEl.placeholder = 'Type your message here (voice unavailable in this browser)…';
        setTimeout(() => showMicStatus('🎙️ Voice unavailable — use Chrome/Edge for speech. You can still type!'), 100);
    }

    // ── Text-to-Speech ────────────────────────────────────────────────────────
    function speak(text) {
        if (!state.synth || !state.speechEnabled) return;
        state.synth.cancel();
        
        // Remove markdown elements from speech text
        const speechText = text.replace(/\*\*([^*]+)\*\*/g, '$1');

        const utt = new SpeechSynthesisUtterance(speechText);
        utt.lang = 'en-IN';
        utt.rate = 0.92;
        utt.pitch = 1.05;

        // Prefer an Indian English voice if available
        const voices = state.synth.getVoices();
        const indVoice = voices.find(v => v.lang === 'en-IN') || voices.find(v => v.lang.startsWith('en'));
        if (indVoice) utt.voice = indVoice;

        utt.onstart = () => panel.classList.add('speaking');
        utt.onend = () => panel.classList.remove('speaking');
        utt.onerror = () => panel.classList.remove('speaking');
        state.synth.speak(utt);
    }

    // ── Mic controls ─────────────────────────────────────────────────────────
    function startListening() {
        if (!recognition) {
            BankAI_Toast.error('🎙️ Voice input not supported in this browser');
            return;
        }
        state.speechEnabled = true; // Enable speech output once user interacts with mic
        try {
            recognition.start();
            btnMic.classList.add('listening');
            btnMic.setAttribute('aria-label', 'Stop listening');
            showMicStatus('🎙️ Listening… speak now');
        } catch (_) { /* already started */ }
    }

    function stopListening() {
        if (recognition) try { recognition.stop(); } catch (_) { }
        btnMic.classList.remove('listening');
        btnMic.setAttribute('aria-label', 'Start voice input');
        showMicStatus('');
    }

    function showMicStatus(msg, isError = false) {
        micStatus.textContent = msg;
        micStatus.style.color = isError ? 'var(--accent-danger)' : 'var(--text-muted)';
        micStatus.classList.toggle('visible', !!msg);
    }

    btnMic.addEventListener('click', () => {
        if (state.busy) return;
        if (btnMic.classList.contains('listening')) stopListening();
        else startListening();
    });

    // ── Auto-resize textarea ──────────────────────────────────────────────────
    inputEl.addEventListener('input', () => {
        inputEl.style.height = 'auto';
        inputEl.style.height = Math.min(inputEl.scrollHeight, 100) + 'px';
    });

    inputEl.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            send();
        }
    });

    btnSend.addEventListener('click', send);

    // ── Send dispatcher ───────────────────────────────────────────────────────
    async function send() {
        const text = inputEl.value.trim();
        if (!text || state.busy) return;
        inputEl.value = '';
        inputEl.style.height = 'auto';

        // Enable speech once the user takes a physical action (clicks send)
        state.speechEnabled = true;

        addBubble('user', text);
        setBusy(true);
        showTyping();

        try {
            if (state.mode === 'chat') {
                await handleChatTurn(text);
            } else if (state.mode === 'form_filling') {
                await handleFormTurn(text);
            }
        } catch (err) {
            removeTyping();
            addBubble('agent', '⚠️ Something went wrong. Please try again.');
            console.error(err);
        } finally {
            setBusy(false);
        }
    }

    // ── Chat mode: POST /api/v1/conversation/chat ─────────────────────────────
    async function handleChatTurn(message) {
        try {
            const res = await BankAI_API.request(BankAI_API.ENDPOINTS.CONVERSATION_CHAT, {
                method: 'POST',
                body: { message }
            });
            removeTyping();

            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                addBubble('agent', `⚠️ ${err.detail || 'Error communicating with server.'}`);
                return;
            }

            const data = await res.json();
            addBubble('agent', data.message);
            speak(data.message);

            // If form_selection intent, show clickable form chips
            if (data.intent === 'form_selection' && data.available_forms?.length) {
                renderFormChips(data.available_forms);
            }
        } catch (err) {
            removeTyping();
            addBubble('agent', '⚠️ Error contacting the banking service.');
        }
    }

    // ── Form filling: POST /api/v1/conversation/next ──────────────────────────
    async function handleFormTurn(message) {
        try {
            const res = await BankAI_API.request(BankAI_API.ENDPOINTS.CONVERSATION_NEXT, {
                method: 'POST',
                body: { submission_id: state.submissionId, message }
            });
            removeTyping();

            if (res.status === 422) {
                const err = await res.json().catch(() => ({}));
                const msg = err.detail || 'That value looks incorrect. Please try again.';
                addBubble('agent', `⚠️ ${msg}`);
                speak(msg);
                return;
            }

            if (!res.ok) {
                addBubble('agent', '⚠️ Could not save your answer. Please try again.');
                return;
            }

            const data = await res.json();
            addBubble('agent', data.next_question);
            speak(data.next_question);

            // Update progress bar from inline response fields (no extra API call)
            if (data.total_fields != null && data.current_field_index != null) {
                showProgress(data.current_field_index, data.total_fields);
            }

            if (data.status === 'completed') {
                state.mode = 'done';
                subtitle.textContent = 'Application submitted ✅';
                hideProgress();
                addCompletion();
            }
        } catch (err) {
            removeTyping();
            addBubble('agent', '⚠️ Connection lost. Unable to submit field.');
        }
    }

    // ── Start a form submission ────────────────────────────────────────────────
    async function startFormSubmission(formId, formName) {
        setBusy(true);
        showTyping();
        try {
            const res = await BankAI_API.request(BankAI_API.ENDPOINTS.SUBMISSIONS_START, {
                method: 'POST',
                body: { form_id: formId }
            });
            removeTyping();

            if (!res.ok) {
                addBubble('agent', '⚠️ Could not start the form. Please try again.');
                return;
            }
            const sub = await res.json();
            state.submissionId = sub.id;
            state.mode = 'form_filling';
            subtitle.textContent = `Filling: ${formName}`;

            // Add Cancel Form Button in panel header
            addCancelFormBtn();

            // Ask first question
            showTyping();
            const turnRes = await BankAI_API.request(BankAI_API.ENDPOINTS.CONVERSATION_NEXT, {
                method: 'POST',
                body: { submission_id: sub.id, message: '__start__' }
            });
            removeTyping();

            if (turnRes.ok) {
                const turn = await turnRes.json();
                addBubble('agent', turn.next_question);
                speak(turn.next_question);
                // Use progress from the /next response (now includes inline fields)
                if (turn.total_fields != null) {
                    showProgress(turn.current_field_index || 0, turn.total_fields);
                }
            }
        } catch (err) {
            removeTyping();
            addBubble('agent', '⚠️ Error starting form. Please try again.');
        } finally {
            setBusy(false);
        }
    }

    // ── Add Cancel Form Button ──────────────────────────────────────────────────
    function addCancelFormBtn() {
        const header = document.querySelector('.ai-header');
        if (!header) return;

        // Prevent duplicates
        if (document.getElementById('cancel-form-btn')) return;

        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'btn btn-secondary btn-sm';
        cancelBtn.id = 'cancel-form-btn';
        cancelBtn.style.marginLeft = '10px';
        cancelBtn.textContent = 'Cancel';
        cancelBtn.addEventListener('click', () => {
            if (confirm('Are you sure you want to cancel form filling?')) {
                state.mode = 'chat';
                state.submissionId = null;
                subtitle.textContent = 'Ask about forms • Apply with voice • Get help';
                hideProgress();
                cancelBtn.remove();
                addBubble('agent', 'Form cancelled. How else can I help you today?');
                speak('Form cancelled. How else can I help you today?');
            }
        });
        
        // Insert before online badge
        const onlineBadge = document.querySelector('.ai-online');
        header.insertBefore(cancelBtn, onlineBadge);
    }

    function removeCancelFormBtn() {
        document.getElementById('cancel-form-btn')?.remove();
    }

    // ── Render form selection chips ────────────────────────────────────────────
    function renderFormChips(forms) {
        const wrap = document.createElement('div');
        wrap.className = 'form-chips';
        forms.forEach(f => {
            const chip = document.createElement('div');
            chip.className = 'form-chip';
            chip.setAttribute('role', 'button');
            chip.setAttribute('tabindex', '0');
            chip.setAttribute('aria-label', `Start ${f.name}`);
            // Build chip content safely using DOM methods (XSS prevention)
            const nameSpan = document.createElement('span');
            nameSpan.textContent = `🏦 ${f.name}`;
            const startSpan = document.createElement('span');
            startSpan.className = 'form-chip-start';
            startSpan.textContent = 'START →';
            chip.appendChild(nameSpan);
            chip.appendChild(startSpan);
            chip.addEventListener('click', () => {
                wrap.remove();
                addBubble('user', `Start ${f.name}`);
                speak(`Great! Let's fill out the ${f.name} form together.`);
                addBubble('agent', `Great! Let's begin the **${f.name}** form. I'll guide you step by step.`);
                startFormSubmission(f.id, f.name);
            });
            chip.addEventListener('keydown', e => { if (e.key === 'Enter') chip.click(); });
            wrap.appendChild(chip);
        });

        // Attach chips after the last agent bubble
        const lastBubble = [...history.querySelectorAll('.bubble.agent')].pop();
        if (lastBubble) lastBubble.querySelector('.bubble-text').appendChild(wrap);
    }

    // ── Progress bar ──────────────────────────────────────────────────────────
    function showProgress(current, total) {
        const pct = total > 0 ? Math.round((current / total) * 100) : 0;
        progressWrap.classList.add('visible');
        progressFill.style.width = pct + '%';
        progressFill.parentElement.setAttribute('aria-valuenow', pct);
        progressLbl.textContent = `Field ${current} of ${total}`;
        progressPct.textContent = pct + '%';
    }

    function hideProgress() {
        progressWrap.classList.remove('visible');
    }

    // ── Simple Markdown bold and list rendering ─────────────────────────────────
    function renderMarkdown(text) {
        // Escape HTML to prevent XSS
        let escaped = text
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");

        // Parse bold: **text**
        escaped = escaped.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

        // Parse lists: lines starting with • or * or -
        const lines = escaped.split('\n');
        const formattedLines = lines.map(line => {
            const trimmed = line.trim();
            if (trimmed.startsWith('•') || trimmed.startsWith('-') || trimmed.startsWith('*')) {
                return `<li style="margin-left: 1.2rem; list-style-type: disc;">${trimmed.substring(1).trim()}</li>`;
            }
            return line;
        });

        return formattedLines.join('<br>');
    }

    // ── Chat bubble helpers ───────────────────────────────────────────────────
    function addBubble(role, text) {
        const wrap = document.createElement('div');
        wrap.className = `bubble ${role}`;
        
        const av = document.createElement('div');
        av.className = 'bubble-avatar';
        av.textContent = role === 'agent' ? '🤖' : '👤';
        
        const txt = document.createElement('div');
        txt.className = 'bubble-text';
        
        // Render simple markdown formatted HTML safely
        txt.innerHTML = renderMarkdown(text);
        
        wrap.appendChild(av);
        wrap.appendChild(txt);
        history.appendChild(wrap);
        history.scrollTop = history.scrollHeight;
        return wrap;
    }

    const MIN_TYPING_TIME = 600; // Force minimum duration to make transitions smooth
    let typingStart = 0;

    function showTyping() {
        typingStart = Date.now();
        const t = document.createElement('div');
        t.className = 'bubble agent';
        t.id = 'typing-indicator';
        t.innerHTML = `<div class="bubble-avatar">🤖</div>
        <div class="bubble-text">
          <div class="typing"><span></span><span></span><span></span></div>
        </div>`;
        history.appendChild(t);
        history.scrollTop = history.scrollHeight;
    }

    function removeTyping() {
        const elapsed = Date.now() - typingStart;
        const delay = Math.max(0, MIN_TYPING_TIME - elapsed);
        
        // Use timeout to preserve typing animation minimum visual duration
        setTimeout(() => {
            document.getElementById('typing-indicator')?.remove();
        }, delay);
    }

    function addCompletion() {
        removeCancelFormBtn();
        addBubble('agent',
            '🎉 Your application has been submitted! Our team will review it and contact you shortly.'
        );
        speak('Your application has been submitted successfully! Our team will review it and contact you shortly.');
    }

    // ── Busy state ────────────────────────────────────────────────────────────
    function setBusy(v) {
        state.busy = v;
        btnSend.disabled = v;
        btnMic.disabled = v;
        inputEl.disabled = v;
    }

    // ── Quick-ask from service cards ──────────────────────────────────────────
    window.askAbout = function askAbout(msg) {
        if (state.mode !== 'chat') {
            BankAI_Toast.warning('💬 Complete the current form first!');
            return;
        }
        inputEl.value = msg;
        send();
    };

    // ── Coming soon ───────────────────────────────────────────────────────────
    window.showComingSoon = function showComingSoon(name) {
        BankAI_Toast.info(`🚧 ${name} — Coming soon!`);
    };

    // ── Initial greeting ──────────────────────────────────────────────────────
    function greet() {
        const hour = new Date().getHours();
        const time = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening';
        const greeting = (
            `${time}! 👋 I'm your BankAI Assistant.\n\n` +
            `I can help you:\n` +
            `• Open a savings account\n` +
            `• Link your Aadhaar\n` +
            `• Request a cheque book\n\n` +
            `Just type or tap the 🎙️ mic to speak — I'll guide you through everything!`
        );
        addBubble('agent', greeting);
        // Do NOT auto-speak to satisfy browser policies and avoid jarring UX
    }

    // ── Seed page data from sessionStorage ────────────────────────────────────
    function initData() {
        const rawAadhaar = sessionStorage.getItem('bankai_aadhaar_masked') || '';
        let aadhaar = 'XXXX XXXX ----';
        if (rawAadhaar) {
            // Check if it has 12/14 characters
            aadhaar = rawAadhaar;
        }
        
        // Mask PAN securely (keep only last 4 digits visible)
        const rawPan = sessionStorage.getItem('bankai_pan') || '';
        let pan = '----------';
        if (rawPan && rawPan.length >= 10) {
            pan = `XXXXXX${rawPan.substring(6)}`;
        }
        
        const selfie = sessionStorage.getItem('bankai_selfie');

        document.getElementById('dash-aadhaar').textContent = aadhaar;
        document.getElementById('dash-pan').textContent = pan;

        if (selfie) {
            document.getElementById('selfie-placeholder').style.display = 'none';
            const img = document.getElementById('selfie-avatar');
            img.src = selfie;
            img.style.display = 'block';
            
            // SECURITY: Clear raw selfie from sessionStorage now that it's loaded to reduce PII footprint
            sessionStorage.removeItem('bankai_selfie');
        }

        const now = new Date();
        document.getElementById('timestamp').textContent =
            now.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
            + ' · ' + now.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });

        // Pre-load voices for TTS (Chrome requires this)
        if (window.speechSynthesis) {
            window.speechSynthesis.getVoices();
            window.speechSynthesis.onvoiceschanged = () => window.speechSynthesis.getVoices();
        }

        // Add Logout Handler
        const logoutBtn = document.getElementById('logoutBtn');
        if (logoutBtn) {
            logoutBtn.addEventListener('click', () => {
                sessionStorage.clear();
                window.location.href = '/index.html';
            });
        }

        greet();
    }

    initData();
})();
