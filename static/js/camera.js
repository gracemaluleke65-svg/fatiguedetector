/**
 * Smart Fatigue Detector - Frontend Controller
 * Version 2.0.0
 */

(function() {
    'use strict';

    // Configuration
    const CONFIG = {
        FRAME_RATE: 12,                    // Target FPS
        FRAME_INTERVAL: 1000 / 12,
        RECONNECT_DELAY: 3000,
        MAX_RECONNECT_ATTEMPTS: 5,
        AUDIO_CONTEXT_REQUIRED: true,
        ALARM_THRESHOLD: 1.0,
        VOICE_THRESHOLD: 2.0
    };

    // DOM Elements
    const elements = {
        video: document.getElementById('video'),
        canvas: document.getElementById('canvas'),
        startBtn: document.getElementById('startTrip'),
        stopBtn: document.getElementById('stopTrip'),
        videoContainer: document.getElementById('videoContainer'),
        status: document.getElementById('status'),
        alarmOverlay: document.getElementById('alarmOverlay'),
        connectionStatus: document.getElementById('connectionStatus'),
        statsPanel: document.getElementById('statsPanel')
    };

    // State management
    const state = {
        streaming: false,
        tripActive: false,
        frameInterval: null,
        audioCtx: null,
        alarmPlaying: false,
        alarmTimeout: null,
        voiceInterval: null,
        selectedVoice: null,
        socket: null,
        reconnectAttempts: 0,
        tripStats: {
            alerts: 0,
            startTime: null
        },
        mediaStream: null
    };

    // Audio synthesis
    const audio = {
        ctx: null,
        alarmOscillator: null,
        alarmGain: null,
        
        async init() {
            try {
                if (!this.ctx) {
                    this.ctx = new (window.AudioContext || window.webkitAudioContext)();
                }
                if (this.ctx.state === 'suspended') {
                    await this.ctx.resume();
                }
                return true;
            } catch (e) {
                console.error('Audio init failed:', e);
                return false;
            }
        },

        playBeep() {
            if (!this.ctx || this.ctx.state !== 'running') return;
            
            try {
                const osc = this.ctx.createOscillator();
                const gain = this.ctx.createGain();
                
                osc.connect(gain);
                gain.connect(this.ctx.destination);
                
                const now = this.ctx.currentTime;
                osc.type = 'square';
                osc.frequency.setValueAtTime(1500, now);
                osc.frequency.exponentialRampToValueAtTime(800, now + 0.1);
                
                gain.gain.setValueAtTime(0.3, now);
                gain.gain.exponentialRampToValueAtTime(0.01, now + 0.2);
                
                osc.start(now);
                osc.stop(now + 0.2);
            } catch (e) {
                console.error('Beep error:', e);
            }
        },

        playContinuousAlarm() {
            if (!this.ctx || this.ctx.state !== 'running') return;
            
            // Clear existing
            this.stopContinuousAlarm();
            
            try {
                this.alarmOscillator = this.ctx.createOscillator();
                this.alarmGain = this.ctx.createGain();
                
                this.alarmOscillator.connect(this.alarmGain);
                this.alarmGain.connect(this.ctx.destination);
                
                this.alarmOscillator.type = 'sawtooth';
                this.alarmOscillator.frequency.value = 800;
                
                // Modulate for urgency
                const lfo = this.ctx.createOscillator();
                const lfoGain = this.ctx.createGain();
                lfo.frequency.value = 5;
                lfoGain.gain.value = 200;
                lfo.connect(lfoGain);
                lfoGain.connect(this.alarmOscillator.frequency);
                lfo.start();
                
                this.alarmGain.gain.value = 0.4;
                this.alarmOscillator.start();
                
                // Store LFO for cleanup
                this.alarmOscillator.lfo = lfo;
                this.alarmOscillator.lfoGain = lfoGain;
                
            } catch (e) {
                console.error('Alarm error:', e);
            }
        },

        stopContinuousAlarm() {
            try {
                if (this.alarmOscillator) {
                    if (this.alarmOscillator.lfo) {
                        this.alarmOscillator.lfo.stop();
                        this.alarmOscillator.lfo.disconnect();
                    }
                    this.alarmOscillator.stop();
                    this.alarmOscillator.disconnect();
                    this.alarmOscillator = null;
                }
                if (this.alarmGain) {
                    this.alarmGain.disconnect();
                    this.alarmGain = null;
                }
            } catch (e) {
                // Ignore cleanup errors
            }
        }
    };

    // Speech synthesis
    const speech = {
        synth: window.speechSynthesis,
        selectedVoice: null,
        interval: null,

        init() {
            if (!this.synth) {
                console.warn('Speech synthesis not supported');
                return false;
            }
            
            // Load voices
            const loadVoices = () => {
                const voices = this.synth.getVoices();
                this.selectedVoice = voices.find(v => 
                    v.name.toLowerCase().includes('female') ||
                    v.name.includes('Google UK English Female') ||
                    v.name.includes('Samantha') ||
                    v.name.includes('Victoria')
                ) || voices.find(v => v.lang.startsWith('en'));
            };
            
            loadVoices();
            if (speechSynthesis.onvoiceschanged !== undefined) {
                speechSynthesis.onvoiceschanged = loadVoices;
            }
            return true;
        },

        speak(text) {
            if (!this.synth) return;
            
            try {
                this.synth.cancel();
                const utterance = new SpeechSynthesisUtterance(text);
                utterance.rate = 0.9;
                utterance.pitch = 1.2;
                utterance.volume = 1;
                
                if (this.selectedVoice) {
                    utterance.voice = this.selectedVoice;
                }
                
                this.synth.speak(utterance);
            } catch (e) {
                console.error('Speech error:', e);
            }
        },

        startRepeating(text, intervalMs = 2000) {
            if (this.interval) return;
            
            this.speak(text);
            this.interval = setInterval(() => this.speak(text), intervalMs);
        },

        stop() {
            if (this.interval) {
                clearInterval(this.interval);
                this.interval = null;
            }
            if (this.synth) {
                this.synth.cancel();
            }
        }
    };

    // Socket connection management
    const connection = {
        init() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const socketUrl = `${protocol}//${window.location.host}`;
            
            state.socket = io(socketUrl, {
                transports: ['websocket', 'polling'],
                reconnection: true,
                reconnectionAttempts: CONFIG.MAX_RECONNECT_ATTEMPTS,
                reconnectionDelay: CONFIG.RECONNECT_DELAY,
                timeout: 10000
            });

            this.bindEvents();
        },

        bindEvents() {
            state.socket.on('connect', () => {
                console.log('Connected to server');
                state.reconnectAttempts = 0;
                updateConnectionStatus('connected');
            });

            state.socket.on('disconnect', (reason) => {
                console.log('Disconnected:', reason);
                updateConnectionStatus('disconnected');
                handleTripEnd(true); // Auto-end on disconnect
            });

            state.socket.on('connect_error', (error) => {
                console.error('Connection error:', error);
                state.reconnectAttempts++;
                updateConnectionStatus('error');
                
                if (state.reconnectAttempts >= CONFIG.MAX_RECONNECT_ATTEMPTS) {
                    showError('Connection failed. Please refresh the page.');
                }
            });

            state.socket.on('connected', (data) => {
                console.log('Server ready:', data);
                elements.status.textContent = 'Camera ready. Click START TRIP.';
                elements.status.className = 'ready';
            });

            state.socket.on('trip_started', (data) => {
                console.log('Trip started:', data);
                state.tripStats.startTime = new Date(data.timestamp);
                updateStats();
            });

            state.socket.on('trip_ended', (data) => {
                console.log('Trip ended:', data);
                showTripSummary(data);
            });

            state.socket.on('eye_state', handleEyeState);
            
            state.socket.on('error', (data) => {
                console.error('Server error:', data);
                showError(data.message);
            });
        }
    };

    // Camera management
    const camera = {
        async init() {
            try {
                const constraints = {
                    video: {
                        width: { ideal: 640, max: 1280 },
                        height: { ideal: 480, max: 720 },
                        facingMode: 'user',
                        frameRate: { ideal: 15, max: 30 }
                    },
                    audio: false
                };

                state.mediaStream = await navigator.mediaDevices.getUserMedia(constraints);
                elements.video.srcObject = state.mediaStream;
                
                return new Promise((resolve, reject) => {
                    elements.video.onloadedmetadata = () => {
                        elements.video.play()
                            .then(() => {
                                state.streaming = true;
                                elements.startBtn.disabled = false;
                                resolve();
                            })
                            .catch(reject);
                    };
                    elements.video.onerror = reject;
                });
                
            } catch (err) {
                console.error('Camera error:', err);
                throw new Error(`Camera access denied or not available: ${err.message}`);
            }
        },

        stop() {
            if (state.mediaStream) {
                state.mediaStream.getTracks().forEach(track => track.stop());
                state.mediaStream = null;
            }
            elements.video.srcObject = null;
            state.streaming = false;
        }
    };

    // Frame capture and transmission
    function captureFrame() {
        if (!state.tripActive || !state.streaming) return;

        try {
            const canvas = elements.canvas;
            const video = elements.video;
            
            canvas.width = video.videoWidth || 640;
            canvas.height = video.videoHeight || 480;
            
            const ctx = canvas.getContext('2d');
            
            // Mirror the image for natural feel
            ctx.translate(canvas.width, 0);
            ctx.scale(-1, 1);
            ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
            ctx.setTransform(1, 0, 0, 1, 0, 0);
            
            // Compress for transmission
            const data = canvas.toDataURL('image/jpeg', 0.6);
            state.socket.emit('frame', data);
            
        } catch (e) {
            console.error('Frame capture error:', e);
        }

        state.frameInterval = setTimeout(captureFrame, CONFIG.FRAME_INTERVAL);
    }

    // Alarm management
    function startAlarm(duration) {
        if (state.alarmPlaying) {
            // Check if we need to escalate to voice
            if (duration >= CONFIG.VOICE_THRESHOLD && !speech.interval) {
                speech.startRepeating('WAKE UP', 2000);
            }
            return;
        }

        state.alarmPlaying = true;
        
        // Visual alarm
        if (elements.alarmOverlay) {
            elements.alarmOverlay.style.display = 'flex';
            elements.alarmOverlay.classList.add('active');
        }
        document.body.classList.add('alarm-active');
        elements.video.style.border = '6px solid #ff0000';
        
        // Audio alarm
        audio.playContinuousAlarm();
        
        // Escalate to voice if severe
        if (duration >= CONFIG.VOICE_THRESHOLD) {
            speech.startRepeating('WAKE UP', 2000);
        }
        
        // Auto-stop after 10 seconds if no response (safety)
        state.alarmTimeout = setTimeout(() => {
            if (state.alarmPlaying) {
                console.log('Auto-stopping alarm after timeout');
                stopAlarm();
            }
        }, 10000);
    }

    function stopAlarm() {
        if (!state.alarmPlaying) return;
        
        state.alarmPlaying = false;
        
        // Visual
        if (elements.alarmOverlay) {
            elements.alarmOverlay.style.display = 'none';
            elements.alarmOverlay.classList.remove('active');
        }
        document.body.classList.remove('alarm-active');
        elements.video.style.border = '4px solid #00b894';
        
        // Audio
        audio.stopContinuousAlarm();
        speech.stop();
        
        // Cleanup
        if (state.alarmTimeout) {
            clearTimeout(state.alarmTimeout);
            state.alarmTimeout = null;
        }
    }

    // Eye state handler
    function handleEyeState(data) {
        if (data.error) {
            elements.status.textContent = `Error: ${data.error}`;
            elements.status.className = 'error';
            return;
        }

        let inattentionDuration = 0;
        let statusHtml = '';
        let statusClass = '';

        if (!data.face_detected) {
            inattentionDuration = data.no_face_duration || 0;
            elements.video.style.borderColor = '#ff9500';
            statusHtml = `⚠️ NO FACE (${inattentionDuration.toFixed(1)}s)`;
            statusClass = 'warning';
            
        } else if (data.eyes_closed) {
            inattentionDuration = data.closed_duration || 0;
            
            if (data.alarm) {
                elements.video.style.borderColor = '#ff0000';
                statusHtml = `🔴 FATIGUE! ${inattentionDuration.toFixed(1)}s closed`;
                statusClass = 'alarm';
            } else if (inattentionDuration >= 0.5) {
                elements.video.style.borderColor = '#e74c3c';
                statusHtml = `⚠️ WARNING ${inattentionDuration.toFixed(1)}s`;
                statusClass = 'danger';
            } else {
                elements.video.style.borderColor = '#3498db';
                statusHtml = `👁️ BLINK (${(inattentionDuration * 1000).toFixed(0)}ms)`;
                statusClass = 'blink';
            }
        } else {
            elements.video.style.borderColor = '#00b894';
            statusHtml = `🟢 AWAKE<br><small>EAR: ${data.ear}</small>`;
            statusClass = 'good';
            inattentionDuration = 0;
        }

        elements.status.innerHTML = statusHtml;
        elements.status.className = statusClass;

        // Alarm logic
        if (data.alarm) {
            startAlarm(inattentionDuration);
        } else {
            stopAlarm();
        }
    }

    // UI Helpers
    function updateConnectionStatus(status) {
        if (!elements.connectionStatus) return;
        
        const statusMap = {
            'connected': { text: '● Connected', class: 'connected' },
            'disconnected': { text: '● Disconnected', class: 'disconnected' },
            'error': { text: '● Error', class: 'error' }
        };
        
        const info = statusMap[status] || statusMap.error;
        elements.connectionStatus.textContent = info.text;
        elements.connectionStatus.className = `connection-status ${info.class}`;
    }

    function showError(message) {
        elements.status.innerHTML = `❌ ${message}`;
        elements.status.className = 'error';
        setTimeout(() => {
            if (elements.status.className === 'error') {
                elements.status.textContent = 'Ready';
                elements.status.className = 'ready';
            }
        }, 5000);
    }

    function updateStats() {
        if (!elements.statsPanel) return;
        // Update trip statistics display
    }

    function showTripSummary(data) {
        const duration = data.duration_minutes || 0;
        const alerts = data.stats?.alert_summary?.total_alerts || 0;
        
        alert(`Trip Complete!\nDuration: ${duration} minutes\nAlerts: ${alerts}`);
    }

    // Event handlers
    async function handleTripStart() {
        try {
            await audio.init();
            speech.init();
            
            elements.videoContainer.style.display = 'block';
            elements.startBtn.disabled = true;
            elements.stopBtn.disabled = false;
            elements.status.textContent = '🟢 ACTIVE - Monitoring';
            elements.status.className = 'monitoring';
            
            state.socket.emit('start_trip');
            state.tripActive = true;
            captureFrame();
            
        } catch (e) {
            showError(e.message);
        }
    }

    function handleTripEnd(isAuto = false) {
        state.tripActive = false;
        
        if (state.frameInterval) {
            clearTimeout(state.frameInterval);
            state.frameInterval = null;
        }
        
        stopAlarm();
        
        elements.stopBtn.disabled = true;
        elements.startBtn.disabled = false;
        elements.status.textContent = isAuto ? 'Disconnected' : 'Stopped';
        elements.status.className = isAuto ? 'error' : 'ready';
        
        state.socket.emit('end_trip', {});
    }

    // Initialization
    async function init() {
        try {
            connection.init();
            await camera.init();
            speech.init();
            
            elements.startBtn.addEventListener('click', handleTripStart);
            elements.stopBtn.addEventListener('click', () => handleTripEnd(false));
            
            // Cleanup on page unload
            window.addEventListener('beforeunload', () => {
                stopAlarm();
                if (state.tripActive) {
                    state.socket.emit('end_trip');
                }
                camera.stop();
            });
            
            // Handle visibility change (pause when tab hidden)
            document.addEventListener('visibilitychange', () => {
                if (document.hidden && state.tripActive) {
                    console.log('Tab hidden, pausing detection');
                    // Optional: pause detection
                }
            });
            
        } catch (e) {
            showError(`Initialization failed: ${e.message}`);
            console.error(e);
        }
    }

    // Start
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();