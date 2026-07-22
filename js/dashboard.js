/* ══════════════════════════════════════════════════════════
   BankAI Dashboard — ChatAgent Orchesrator
   ══════════════════════════════════════════════════════════ */

'use strict';

(function initDashboard() {
    // ── Auth verification + Session restore ───────────────────────────────────
    const token = BankAI_API.getToken();
    if (!token) {
        window.location.href = '/login.html';
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

    // ── Web Audio Analyser for Waveform ──
    let audioCtx = null;
    let analyser = null;
    let animationFrameId = null;
    let micStream = null;
    let micSource = null;
    let mediaRecorder = null;
    let webSocket = null;

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
    function stopActiveSpeech() {
        if (state.synth) state.synth.cancel();
        if (state.currentAudio) {
            try {
                state.currentAudio.pause();
            } catch (_) {}
            state.currentAudio = null;
        }
        if (analyser) {
            try { analyser.disconnect(); } catch (_) {}
        }
        panel.classList.remove('speaking');
    }

    async function speak(text, callback = null) {
        if (!state.speechEnabled) {
            if (callback) callback();
            return;
        }

        stopActiveSpeech();
        
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

            // Connect to analyser for waveform animation
            try {
                const { audioCtx: ctx, analyser: ana } = getAudioContext();
                const source = ctx.createMediaElementSource(audio);
                source.connect(ana);
                ana.connect(ctx.destination);
            } catch (err) {
                console.warn('Audio visualization link failed:', err);
            }

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

    // ── Web Audio Analyser and Animation logic ──
    function getAudioContext() {
        if (!audioCtx) {
            audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            analyser = audioCtx.createAnalyser();
            analyser.fftSize = 64; // Small fftSize for clean circular bars
        }
        if (audioCtx.state === 'suspended') {
            audioCtx.resume();
        }
        return { audioCtx, analyser };
    }

    function startWaveformAnimation() {
        const canvas = document.getElementById('voiceWaveform');
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        
        const dpr = window.devicePixelRatio || 1;
        canvas.width = 88 * dpr;
        canvas.height = 88 * dpr;
        ctx.scale(dpr, dpr);
        
        const { analyser: ana } = getAudioContext();
        const bufferLength = ana.frequencyBinCount;
        const dataArray = new Uint8Array(bufferLength);
        
        function draw() {
            animationFrameId = requestAnimationFrame(draw);
            ctx.clearRect(0, 0, 88, 88);
            
            const isSpeakingOrListening = panel.classList.contains('speaking') || btnMic.classList.contains('listening');
            
            if (isSpeakingOrListening) {
                ana.getByteFrequencyData(dataArray);
            } else {
                dataArray.fill(0);
            }
            
            const centerX = 44;
            const centerY = 44;
            const baseRadius = 34; // just outside the 64px avatar
            
            ctx.beginPath();
            const numPoints = 60;
            for (let i = 0; i < numPoints; i++) {
                const angle = (i / numPoints) * Math.PI * 2;
                const dataIndex = Math.floor((i / numPoints) * bufferLength);
                let val = dataArray[dataIndex] || 0;
                
                // If fallback speech synthesis is speaking, simulate waveform
                if (panel.classList.contains('speaking') && !state.currentAudio) {
                    val = 40 + Math.random() * 30;
                }
                
                const amplitude = (val / 255) * 12; // max 12px wave offset
                const r = baseRadius + amplitude;
                
                const x = centerX + Math.cos(angle) * r;
                const y = centerY + Math.sin(angle) * r;
                
                if (i === 0) {
                    ctx.moveTo(x, y);
                } else {
                    ctx.lineTo(x, y);
                }
            }
            ctx.closePath();
            
            const grad = ctx.createRadialGradient(centerX, centerY, baseRadius, centerX, centerY, baseRadius + 12);
            grad.addColorStop(0, '#818cf8');
            grad.addColorStop(0.5, '#a78bfa');
            grad.addColorStop(1, 'rgba(167, 139, 250, 0)');
            
            ctx.strokeStyle = grad;
            ctx.lineWidth = 3;
            ctx.stroke();
            
            if (panel.classList.contains('speaking')) {
                ctx.fillStyle = 'rgba(129, 140, 248, 0.05)';
                ctx.fill();
            }
        }
        
        if (animationFrameId) cancelAnimationFrame(animationFrameId);
        draw();
    }

    // ── Mic controls ─────────────────────────────────────────────────────────
    async function startListening() {
        stopActiveSpeech(); // Cancel any active speak playback immediately when user triggers mic
        panel.classList.add('listening');
        state.speechEnabled = true; // Enable speech output once user interacts with mic
        
        // Connect microphone for visual waveform and capture audio stream
        let userStream = null;
        try {
            userStream = await navigator.mediaDevices.getUserMedia({ audio: true });
            micStream = userStream;
            const { audioCtx: ctx, analyser: ana } = getAudioContext();
            micSource = ctx.createMediaStreamSource(userStream);
            micSource.connect(ana);
        } catch (err) {
            console.warn('Microphone stream access failed:', err);
            showMicStatus('🎙️ Microphone access denied or unavailable.', true);
            panel.classList.remove('listening');
            return;
        }

        // Try to initialize Deepgram WebSocket STT
        let deepgramConnected = false;
        try {
            const tokenRes = await fetch('/api/v1/conversation/stt-token', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                }
            });

            if (!tokenRes.ok) throw new Error('Could not get Deepgram STT token');

            const tokenData = await tokenRes.json();
            const tempToken = tokenData.token;

            // Open WebSocket to Deepgram (using Sec-WebSocket-Protocol for browser auth)
            const wsUrl = 'wss://api.deepgram.com/v1/listen?model=nova-2-general&language=en-IN&endpointing=300&interim_results=true';
            webSocket = new WebSocket(wsUrl, ['token', tempToken]);

            webSocket.onopen = () => {
                deepgramConnected = true;
                btnMic.classList.add('listening');
                btnMic.setAttribute('aria-label', 'Stop listening');
                showMicStatus('🎙️ Listening (Deepgram)… speak now');

                // Start recording and sending chunks
                mediaRecorder = new MediaRecorder(userStream, { mimeType: 'audio/webm' });
                mediaRecorder.ondataavailable = (event) => {
                    if (event.data.size > 0 && webSocket.readyState === WebSocket.OPEN) {
                        webSocket.send(event.data);
                    }
                };
                mediaRecorder.start(250); // Send 250ms chunks
            };

            let finalTranscript = '';
            webSocket.onmessage = (event) => {
                const data = JSON.parse(event.data);
                const transcript = data.channel?.alternatives?.[0]?.transcript || '';
                
                if (transcript) {
                    showMicStatus(`🎙️ "${transcript}"`);
                    if (data.is_final) {
                        finalTranscript += (finalTranscript ? ' ' : '') + transcript;
                    }
                }

                // If Deepgram endpointing determines silence/end of speech
                if (data.speech_final) {
                    stopListening();
                    if (finalTranscript.trim()) {
                        inputEl.value = finalTranscript.trim();
                        send();
                    }
                }
            };

            webSocket.onerror = (err) => {
                console.error("Deepgram WS error:", err);
                if (!deepgramConnected) {
                    fallbackToNativeSTT();
                }
            };

            webSocket.onclose = () => {
                stopListening();
            };

        } catch (err) {
            console.warn("Deepgram STT initialization failed, falling back to native:", err);
            fallbackToNativeSTT();
        }

        function fallbackToNativeSTT() {
            if (!recognition) {
                BankAI_Toast.error('🎙️ Voice input not supported in this browser');
                stopListening();
                return;
            }
            try {
                recognition.start();
                btnMic.classList.add('listening');
                btnMic.setAttribute('aria-label', 'Stop listening');
                showMicStatus('🎙️ Listening (Browser fallback)… speak now');
            } catch (_) {}
        }
    }

    function stopListening() {
        btnMic.classList.remove('listening');
        btnMic.setAttribute('aria-label', 'Start voice input');
        panel.classList.remove('listening');
        showMicStatus('');

        // Stop browser-native SpeechRecognition if active
        if (recognition) try { recognition.stop(); } catch (_) { }

        // Stop Deepgram MediaRecorder and WebSocket
        if (mediaRecorder && mediaRecorder.state !== 'inactive') {
            try { mediaRecorder.stop(); } catch (_) {}
            mediaRecorder = null;
        }
        if (webSocket) {
            try { webSocket.close(); } catch (_) {}
            webSocket = null;
        }

        // Disconnect mic audio nodes
        if (micSource) {
            try { micSource.disconnect(); } catch (_) {}
            micSource = null;
        }
        if (micStream) {
            try {
                micStream.getTracks().forEach(track => track.stop());
            } catch (_) {}
            micStream = null;
        }
        if (analyser) {
            try { analyser.disconnect(); } catch (_) {}
        }
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
        stopActiveSpeech(); // Stop speech immediately when user starts typing
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
        stopActiveSpeech(); // Stop speech immediately when user submits a message
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
        ctx.strokeStyle = '#ffffff'; // Drawing color (white stroke for nocturnal terminal theme)
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
        if (rawAadhaar) aadhaar = rawAadhaar;

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
            sessionStorage.removeItem('bankai_selfie');
        }

        const now = new Date();
        document.getElementById('timestamp').textContent =
            now.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
            + ' · ' + now.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });

        if (window.speechSynthesis) {
            window.speechSynthesis.getVoices();
            window.speechSynthesis.onvoiceschanged = () => window.speechSynthesis.getVoices();
        }

        const logoutBtn = document.getElementById('logoutBtn');
        if (logoutBtn) {
            logoutBtn.addEventListener('click', () => {
                BankAI_API.clearSession();
                window.location.href = '/login.html';
            });
        }

        startWaveformAnimation();

        // ── Async orchestration: verify session → load apps → greet ──────────
        (async () => {
            // 1. Verify token is still valid
            const user = await BankAI_API.verifySession();
            if (!user) {
                BankAI_API.clearSession();
                window.location.href = '/login.html';
                return;
            }

            // 2. Load user's submissions (My Applications panel)
            await loadMyApplications();

            // 3. Check for in-progress submission to restore
            await checkSessionRestore();

            // 4. Greet (only if not resuming)
            if (state.mode === 'chat') {
                greet();
            }
        })();
    }


    // ── My Applications panel ─────────────────────────────────────────────────
    async function loadMyApplications() {
        const listEl = document.getElementById('appsList');
        const countEl = document.getElementById('appsCount');
        if (!listEl) return;

        try {
            const res = await BankAI_API.request(BankAI_API.ENDPOINTS.SUBMISSIONS);
            if (!res.ok) throw new Error('Could not load submissions');

            const subs = await res.json();
            countEl.textContent = subs.length
                ? `${subs.length} application${subs.length !== 1 ? 's' : ''}`
                : 'None yet';

            if (!subs.length) {
                listEl.innerHTML = '<div class="apps-empty">📭 No applications yet.<br>Ask the AI assistant to get started!</div>';
                return;
            }

            // Fetch form names in parallel
            const formCache = {};
            const formFetches = [...new Set(subs.map(s => s.form_id).filter(Boolean))].map(async fid => {
                try {
                    const r = await BankAI_API.request(`${BankAI_API.ENDPOINTS.SUBMISSIONS}/../forms/${fid}`);
                    if (r.ok) formCache[fid] = await r.json();
                } catch {}
            });
            await Promise.allSettled(formFetches);

            listEl.innerHTML = '';
            subs.forEach((sub, idx) => {
                const form = formCache[sub.form_id] || {};
                const formName = form.name || 'Banking Application';
                const isCompleted = sub.status === 'completed';
                const isActive = !isCompleted && sub.current_field_index > 0;

                const totalFields = form.total_fields || 0;
                const pct = totalFields > 0 ? Math.round((sub.current_field_index / totalFields) * 100) : 0;

                const dateStr = sub.created_at
                    ? new Date(sub.created_at._seconds ? sub.created_at._seconds * 1000 : sub.created_at)
                        .toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
                    : 'Recently';

                const statusClass = isCompleted ? 'completed' : (isActive ? 'active' : 'draft');
                const statusLabel = isCompleted ? '✅ Completed' : (isActive ? '⚡ In Progress' : '📝 Draft');

                const item = document.createElement('div');
                item.className = 'app-item';
                item.style.animationDelay = `${idx * 0.06}s`;
                item.innerHTML = `
                    <div class="app-icon">${isCompleted ? '✅' : '📋'}</div>
                    <div class="app-info">
                        <div class="app-name">${formName}</div>
                        <div class="app-meta">
                            <span>${dateStr}</span>
                            ${!isCompleted && totalFields ? `<span>·</span><span>${sub.current_field_index}/${totalFields} fields</span>` : ''}
                        </div>
                        ${!isCompleted && totalFields ? `
                        <div class="app-progress-wrap" style="margin-top:.45rem">
                            <div class="app-progress-fill" style="width:${pct}%"></div>
                        </div>` : ''}
                    </div>
                    <span class="app-status ${statusClass}">${statusLabel}</span>
                    ${!isCompleted ? `<button class="btn-resume" data-sub-id="${sub.id}" data-form-name="${formName}" onclick="resumeSubmission('${sub.id}', '${formName}')">Resume →</button>` : ''}
                    ${isCompleted ? `<button class="btn-resume" style="background:rgba(52,211,153,.15);color:#34d399;box-shadow:none;border:1px solid rgba(52,211,153,.3)" onclick="downloadPdfForSub('${sub.id}')">📥 PDF</button>` : ''}
                `;
                listEl.appendChild(item);
            });
        } catch (err) {
            console.warn('My Applications load failed:', err.message);
            listEl.innerHTML = '<div class="apps-empty">⚠️ Could not load applications. Server may be offline.</div>';
            if (countEl) countEl.textContent = 'Unavailable';
        }
    }


    // ── Session restore — check for in-progress form ───────────────────────────
    async function checkSessionRestore() {
        const storedSubId = sessionStorage.getItem('bankai_submission_id');
        if (!storedSubId) return;

        const status = await BankAI_API.getConversationStatus(storedSubId);
        if (!status || status.status === 'completed') {
            sessionStorage.removeItem('bankai_submission_id');
            return;
        }

        // Show restore banner
        showRestoreBanner(status, storedSubId);
    }

    function showRestoreBanner(status, submissionId) {
        const banner = document.getElementById('restoreBanner');
        if (!banner) return;

        const formName = status.form_name || 'Banking Application';
        const pct = status.progress_pct || 0;
        banner.style.display = 'block';
        banner.innerHTML = `
            <div class="restore-banner">
                <div class="restore-banner-text">
                    <span class="restore-icon">⏸️</span>
                    <div>
                        <div class="restore-title">Resume your application</div>
                        <div class="restore-sub">${formName} — ${pct}% complete (${status.current_field_index}/${status.total_fields} fields)</div>
                    </div>
                </div>
                <div class="restore-actions">
                    <button class="btn-restore" onclick="resumeSubmission('${submissionId}', '${formName}')">▶ Resume</button>
                    <button class="btn-restore-dismiss" onclick="dismissRestore()">Dismiss</button>
                </div>
            </div>
        `;
    }

    window.dismissRestore = function() {
        const banner = document.getElementById('restoreBanner');
        if (banner) banner.style.display = 'none';
        sessionStorage.removeItem('bankai_submission_id');
    };

    // Resume a submission from My Applications or restore banner
    window.resumeSubmission = function(subId, formName) {
        if (state.mode !== 'chat') {
            BankAI_Toast.warning('Please finish or cancel the current form first.');
            return;
        }
        // Close restore banner
        const banner = document.getElementById('restoreBanner');
        if (banner) banner.style.display = 'none';

        // Resume by directly sending __start__ to get next question
        state.submissionId = subId;
        state.mode = 'form_filling';
        subtitle.textContent = `Resuming: ${formName}`;
        addCancelFormBtn();
        addBubble('agent', `Welcome back! Let's continue your **${formName}** application where we left off.`);

        setBusy(true);
        showTyping();
        BankAI_API.request(BankAI_API.ENDPOINTS.CONVERSATION_NEXT, {
            method: 'POST',
            body: { submission_id: subId, message: '__resume__' }
        }).then(async res => {
            removeTyping();
            if (!res.ok) {
                // Fallback to __start__ if __resume__ not supported
                return BankAI_API.request(BankAI_API.ENDPOINTS.CONVERSATION_NEXT, {
                    method: 'POST',
                    body: { submission_id: subId, message: '__start__' }
                });
            }
            return res;
        }).then(async res => {
            removeTyping();
            if (res && res.ok) {
                const turn = await res.json();
                addBubble('agent', turn.next_question);
                if (turn.total_fields != null) {
                    showProgress(turn.current_field_index || 0, turn.total_fields);
                }
                speak(turn.next_question, () => { if (state.mode === 'form_filling') startListening(); });
            }
        }).catch(err => {
            removeTyping();
            addBubble('agent', 'Could not resume your application. Please try starting a new one.');
            state.mode = 'chat';
        }).finally(() => setBusy(false));
    };

    // Download PDF from My Applications
    window.downloadPdfForSub = async function(subId) {
        try {
            await BankAI_API.downloadPdf(subId);
        } catch (err) {
            BankAI_Toast.error(err.message || 'Failed to download PDF.');
        }
    };

    initData();
})();
