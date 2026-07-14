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
        speechEnabled: false,  // Start disabled to avoid unsolicited auto-TTS
        currentAudio: null,    // Playback handle for Deepgram audio stream
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
    async function speak(text, callback = null) {
        if (!state.speechEnabled) {
            if (callback) callback();
            return;
        }

        // Cancel any active browser native speech or active audio playback
        if (state.synth) state.synth.cancel();
        if (state.currentAudio) {
            try {
                state.currentAudio.pause();
            } catch (_) {}
            state.currentAudio = null;
        }
        
        // Remove markdown elements from speech text
        const speechText = text.replace(/\*\*([^*]+)\*\*/g, '$1');

        try {
            panel.classList.add('speaking');
            
            // Call the backend speech proxy endpoint
            const res = await fetch('/api/v1/conversation/speak', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify({ text: speechText })
            });

            if (!res.ok) {
                throw new Error('Deepgram TTS failed or not configured');
            }

            const blob = await res.blob();
            const audioUrl = URL.createObjectURL(blob);
            const audio = new Audio(audioUrl);
            state.currentAudio = audio;

            audio.onended = () => {
                panel.classList.remove('speaking');
                URL.revokeObjectURL(audioUrl);
                state.currentAudio = null;
                if (callback) callback();
            };

            audio.onerror = () => {
                panel.classList.remove('speaking');
                URL.revokeObjectURL(audioUrl);
                state.currentAudio = null;
                // Fall back to browser voice on audio playback error
                speakFallback(speechText, callback);
            };

            await audio.play();

        } catch (err) {
            console.warn("Deepgram TTS unavailable, falling back to browser-native voice:", err);
            speakFallback(speechText, callback);
        }
    }

    // Browser-native speech synthesis fallback
    function speakFallback(speechText, callback) {
        if (!state.synth) {
            panel.classList.remove('speaking');
            if (callback) callback();
            return;
        }

        const utt = new SpeechSynthesisUtterance(speechText);
        utt.lang = 'en-IN';
        utt.rate = 0.92;
        utt.pitch = 1.05;

        // Prefer an Indian English voice if available
        const voices = state.synth.getVoices();
        const indVoice = voices.find(v => v.lang === 'en-IN') || voices.find(v => v.lang.startsWith('en'));
        if (indVoice) utt.voice = indVoice;

        utt.onstart = () => panel.classList.add('speaking');
        utt.onend = () => {
            panel.classList.remove('speaking');
            if (callback) callback();
        };
        utt.onerror = () => {
            panel.classList.remove('speaking');
            if (callback) callback();
        };
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
                speak(msg, () => {
                    if (state.mode === 'form_filling') {
                        startListening();
                    }
                });
                return;
            }

            if (!res.ok) {
                addBubble('agent', '⚠️ Could not save your answer. Please try again.');
                return;
            }

            const data = await res.json();
            addBubble('agent', data.next_question);
            
            // Check if signature collection is active
            const isSigState = data.conversation_state === 'signature';
            if (isSigState) {
                openSignatureModal();
                addSignatureButton();
            } else {
                removeSignatureButton();
            }

            speak(data.next_question, () => {
                // Auto-start listening after TTS finishes, unless we entered signature state
                if (!isSigState && (state.mode === 'form_filling' || state.mode === 'chat')) {
                    startListening();
                }
            });

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
                
                // Check signature state immediately
                const isSigState = turn.conversation_state === 'signature';
                if (isSigState) {
                    openSignatureModal();
                    addSignatureButton();
                }

                speak(turn.next_question, () => {
                    if (!isSigState && state.mode === 'form_filling') {
                        startListening();
                    }
                });

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
                removeSignatureButton();
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

    // ── HTML5 Signature Canvas Drawing Pad Logic ─────────────────────────────────
    let canvasInitialized = false;
    let drawing = false;
    const canvas = document.getElementById('signatureCanvas');
    const ctx = canvas ? canvas.getContext('2d') : null;

    function initCanvas() {
        if (!canvas || canvasInitialized) return;
        canvasInitialized = true;

        // Set up mouse events
        canvas.addEventListener('mousedown', startDrawing);
        canvas.addEventListener('mousemove', draw);
        canvas.addEventListener('mouseup', stopDrawing);
        canvas.addEventListener('mouseleave', stopDrawing);

        // Set up touch events (mobile friendly)
        canvas.addEventListener('touchstart', (e) => {
            const touch = e.touches[0];
            const mouseEvent = new MouseEvent('mousedown', {
                clientX: touch.clientX,
                clientY: touch.clientY
            });
            canvas.dispatchEvent(mouseEvent);
            e.preventDefault();
        });
        canvas.addEventListener('touchmove', (e) => {
            const touch = e.touches[0];
            const mouseEvent = new MouseEvent('mousemove', {
                clientX: touch.clientX,
                clientY: touch.clientY
            });
            canvas.dispatchEvent(mouseEvent);
            e.preventDefault();
        });
        canvas.addEventListener('touchend', (e) => {
            const mouseEvent = new MouseEvent('mouseup', {});
            canvas.dispatchEvent(mouseEvent);
            e.preventDefault();
        });

        // Clear button
        document.getElementById('clearSigBtn').addEventListener('click', clearCanvas);

        // Close button
        document.getElementById('closeSigModal').addEventListener('click', () => {
            document.getElementById('signatureModal').classList.remove('open');
        });

        // Save button
        document.getElementById('saveSigBtn').addEventListener('click', async () => {
            const buffer = new Uint32Array(ctx.getImageData(0, 0, canvas.width, canvas.height).data.buffer);
            const hasDrawn = buffer.some(color => color !== 0);

            if (!hasDrawn) {
                BankAI_Toast.error('Please sign before saving!');
                return;
            }

            const dataUrl = canvas.toDataURL('image/png');
            setBusy(true);
            try {
                const res = await BankAI_API.uploadSignature(state.submissionId, dataUrl);
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    BankAI_Toast.error(err.detail || 'Failed to save signature.');
                    return;
                }
                BankAI_Toast.success('Signature saved successfully!');
                document.getElementById('signatureModal').classList.remove('open');
                removeSignatureButton();
                
                showTyping();
                await handleFormTurn('Signature provided');
            } catch (err) {
                console.error(err);
                BankAI_Toast.error('Network error uploading signature.');
            } finally {
                setBusy(false);
            }
        });
    }

    function getMousePos(e) {
        const rect = canvas.getBoundingClientRect();
        return {
            x: (e.clientX - rect.left) * (canvas.width / rect.width),
            y: (e.clientY - rect.top) * (canvas.height / rect.height)
        };
    }

    function startDrawing(e) {
        drawing = true;
        ctx.beginPath();
        const pos = getMousePos(e);
        ctx.moveTo(pos.x, pos.y);
        ctx.lineWidth = 3;
        ctx.lineCap = 'round';
        ctx.strokeStyle = '#0f172a'; // Drawing color (dark slate slate-900)
    }

    function draw(e) {
        if (!drawing) return;
        const pos = getMousePos(e);
        ctx.lineTo(pos.x, pos.y);
        ctx.stroke();
    }

    function stopDrawing() {
        drawing = false;
    }

    function clearCanvas() {
        if (ctx) {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
        }
    }

    function openSignatureModal() {
        const modal = document.getElementById('signatureModal');
        if (modal) {
            modal.classList.add('open');
            initCanvas();
            clearCanvas();
        }
    }

    function addSignatureButton() {
        // Prevent duplicates
        if (document.getElementById('reopen-sig-btn')) return;

        const btn = document.createElement('button');
        btn.className = 'btn btn-primary btn-sm';
        btn.id = 'reopen-sig-btn';
        btn.style.marginTop = '10px';
        btn.innerHTML = '✍️ Draw Signature';
        btn.addEventListener('click', openSignatureModal);

        const lastBubble = [...history.querySelectorAll('.bubble.agent')].pop();
        if (lastBubble) {
            lastBubble.querySelector('.bubble-text').appendChild(btn);
        }
    }

    function removeSignatureButton() {
        document.getElementById('reopen-sig-btn')?.remove();
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
        removeSignatureButton();
        const bubble = addBubble('agent',
            '🎉 Your application has been submitted! Our team will review it and contact you shortly.\n\nYour PDF is ready for download.'
        );

        // Add Download PDF button
        const dlBtn = document.createElement('button');
        dlBtn.className = 'btn btn-primary btn-sm';
        dlBtn.style.marginTop = '10px';
        dlBtn.innerHTML = '📥 Download PDF';
        dlBtn.addEventListener('click', async () => {
            dlBtn.disabled = true;
            dlBtn.innerHTML = '⏳ Generating...';
            try {
                await BankAI_API.downloadPdf(state.submissionId);
                dlBtn.innerHTML = '📥 Download PDF';
                dlBtn.disabled = false;
            } catch (err) {
                console.error(err);
                BankAI_Toast.error(err.message || 'Failed to download PDF.');
                dlBtn.innerHTML = '📥 Download PDF';
                dlBtn.disabled = false;
            }
        });
        bubble.querySelector('.bubble-text').appendChild(dlBtn);

        speak('Your application has been submitted successfully! Your PDF is ready for download.');
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
        
        const greetingDisplay = (
            `${time}! 👋 I'm your BankAI Assistant.\n\n` +
            `I can help you:\n` +
            `• Open a savings account\n` +
            `• Link your Aadhaar\n` +
            `• Request a cheque book\n\n` +
            `Please speak your request now — I'm listening!`
        );
        addBubble('agent', greetingDisplay);

        const greetingSpeechText = `${time}! Welcome to BankAI. I am your banking assistant. I can help you open a savings account, link your Aadhaar, or request a cheque book. What would you like to do today?`;
        
        let spoken = false;
        
        // Safety fallback: if speech doesn't start or finish within 5 seconds, activate mic anyway
        const safetyTimer = setTimeout(() => {
            if (!spoken) {
                spoken = true;
                startListening();
            }
        }, 5000);

        speak(greetingSpeechText, () => {
            if (!spoken) {
                spoken = true;
                clearTimeout(safetyTimer);
                setTimeout(() => {
                    startListening();
                }, 300);
            }
        });
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
