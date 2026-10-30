/**
 * practice_voice.js - Audio coach speech synthesizer and queue manager for live Practice and Workouts.
 *
 * Implements a pluggable TTS interface supporting:
 * 1. Kokoro Neural TTS (local high-fidelity voice via Kokoro ONNX)
 * 2. Browser SpeechSynthesis (native Web Speech fallback)
 */

(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.PracticeVoice = factory();
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  // Native browser speech synthesis fallback backend
  const BrowserSpeechBackend = {
    name: 'browser',
    isSupported() {
      return (
        typeof window !== 'undefined' &&
        'speechSynthesis' in window &&
        typeof window.SpeechSynthesisUtterance === 'function'
      );
    },
    unlock() {
      if (this.isSupported()) {
        try {
          if (window.speechSynthesis.paused) {
            window.speechSynthesis.resume();
          }
        } catch {
          /* ignore */
        }
      }
    },
    speak(text, onEnd, onError) {
      if (!this.isSupported()) {
        if (onError) onError(new Error('SpeechSynthesis not supported'));
        return null;
      }
      try {
        if (window.speechSynthesis.paused) {
          window.speechSynthesis.resume();
        }
        const utterance = new window.SpeechSynthesisUtterance(String(text));
        utterance.rate = 1.0;
        utterance.pitch = 1.0;
        utterance.volume = 1.0;
        utterance.lang = 'en-US';

        const voices = window.speechSynthesis.getVoices();
        if (voices && voices.length) {
          const enVoice =
            voices.find(v => v.lang === 'en-US' || v.lang === 'en_US') ||
            voices.find(v => v.lang && v.lang.toLowerCase().startsWith('en')) ||
            voices[0];
          if (enVoice) utterance.voice = enVoice;
        }

        utterance.onend = () => {
          if (onEnd) onEnd();
        };
        utterance.onerror = (err) => {
          if (onError) onError(err);
        };

        window.speechSynthesis.speak(utterance);
        if (window.speechSynthesis.paused) {
          window.speechSynthesis.resume();
        }
        return utterance;
      } catch (err) {
        if (onError) onError(err);
        return null;
      }
    },
    cancel() {
      if (this.isSupported()) {
        try {
          window.speechSynthesis.cancel();
        } catch {
          /* ignore */
        }
      }
    },
  };

  // Kokoro Neural TTS backend via local server ONNX engine
  const KokoroSpeechBackend = {
    name: 'kokoro',
    currentAudio: null,
    audioCache: new Map(),

    isSupported() {
      return typeof window !== 'undefined' && typeof window.fetch === 'function';
    },

    unlock() {
      // Audio element playback permitted under user gesture
    },

    async speak(text, onEnd, onError) {
      this.cancel();
      const cleanText = String(text || '').trim();
      if (!cleanText) {
        if (onEnd) onEnd();
        return null;
      }

      try {
        let audioUrl = this.audioCache.get(cleanText);
        if (!audioUrl) {
          const res = await fetch('/api/voice/synthesize', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Shotlab': '1' },
            body: JSON.stringify({ text: cleanText }),
          });
          if (!res.ok) {
            throw new Error(`Kokoro synthesis HTTP error ${res.status}`);
          }
          const blob = await res.blob();
          audioUrl = URL.createObjectURL(blob);
          if (cleanText.length <= 40) {
            this.audioCache.set(cleanText, audioUrl);
          }
        }

        const audio = new Audio(audioUrl);
        this.currentAudio = audio;

        const cleanup = () => {
          if (this.currentAudio === audio) {
            this.currentAudio = null;
          }
        };

        audio.onended = () => {
          cleanup();
          if (onEnd) onEnd();
        };

        audio.onerror = (err) => {
          cleanup();
          if (onError) onError(err);
        };

        await audio.play();
        return audio;
      } catch (err) {
        this.currentAudio = null;
        if (onError) onError(err);
        return null;
      }
    },

    cancel() {
      if (this.currentAudio) {
        try {
          this.currentAudio.pause();
          this.currentAudio.currentTime = 0;
        } catch {
          /* ignore */
        }
        this.currentAudio = null;
      }
    },

    async prewarm(phrases) {
      if (!Array.isArray(phrases) || typeof window === 'undefined' || !window.fetch) return;
      for (const phrase of phrases) {
        const clean = String(phrase || '').trim();
        if (!clean || this.audioCache.has(clean)) continue;
        try {
          const res = await fetch('/api/voice/synthesize', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Shotlab': '1' },
            body: JSON.stringify({ text: clean }),
          });
          if (res.ok) {
            const blob = await res.blob();
            this.audioCache.set(clean, URL.createObjectURL(blob));
          }
        } catch {
          /* ignore prewarm error */
        }
      }
    },
  };

  if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
    try {
      window.speechSynthesis.onvoiceschanged = () => {
        try { window.speechSynthesis.getVoices(); } catch { /* ignore */ }
      };
    } catch {
      /* ignore */
    }
  }

  const STORAGE_KEY = 'baseline_practice_voice_enabled';

  function readStoredVoicePref() {
    try {
      if (typeof window !== 'undefined' && window.localStorage) {
        const val = window.localStorage.getItem(STORAGE_KEY);
        if (val !== null) return val === '1' || val === 'true';
      }
    } catch {
      /* ignore */
    }
    return true; // Default unmuted
  }

  function writeStoredVoicePref(enabled) {
    try {
      if (typeof window !== 'undefined' && window.localStorage) {
        window.localStorage.setItem(STORAGE_KEY, enabled ? '1' : '0');
      }
    } catch {
      /* ignore */
    }
  }

  const PracticeVoice = {
    backend: BrowserSpeechBackend,
    provider: 'browser',
    enabled: readStoredVoicePref(),
    queue: [],
    busy: false,
    gen: 0,
    guard: null,

    isSupported() {
      return Boolean(this.backend && this.backend.isSupported && this.backend.isSupported());
    },

    unlock() {
      if (this.backend && typeof this.backend.unlock === 'function') {
        this.backend.unlock();
      }
    },

    setBackend(customBackend) {
      if (customBackend && typeof customBackend.speak === 'function' && typeof customBackend.cancel === 'function') {
        this.cancel();
        this.backend = customBackend;
        this.provider = customBackend.name || 'custom';
      }
    },

    setMuted(muted) {
      this.enabled = !muted;
      writeStoredVoicePref(this.enabled);
      if (!this.enabled) {
        this.cancel();
      }
    },

    isMuted() {
      return !this.enabled;
    },

    toggleMute() {
      this.setMuted(!this.isMuted());
      return this.isMuted();
    },

    say(text, { priority = 'normal', kind = 'coach', force = false } = {}) {
      if (!text || typeof text !== 'string' || !text.trim()) return false;
      if (!this.isSupported()) return false;
      if (!this.enabled && !force) return false;

      // Drop older pending coach cues or counts of the same kind
      if (kind === 'coach') {
        this.queue = this.queue.filter(item => item.kind !== 'coach');
      } else if (kind === 'count') {
        this.queue = this.queue.filter(item => item.kind !== 'count');
      }

      this.queue.push({ text: String(text).trim(), kind, priority, force });
      this.pump();
      return true;
    },

    pump() {
      if (this.busy || !this.queue.length) return;
      const next = this.queue.shift();
      const currentGen = this.gen;
      let finished = false;

      const done = () => {
        if (finished || currentGen !== this.gen) return;
        finished = true;
        clearTimeout(this.guard);
        this.guard = null;
        this.busy = false;
        this.pump();
      };

      const onError = (err) => {
        // If Kokoro backend fails, gracefully fall back to browser speech for this cue
        if (this.backend !== BrowserSpeechBackend && BrowserSpeechBackend.isSupported()) {
          try {
            BrowserSpeechBackend.speak(next.text, done, done);
            return;
          } catch {
            /* ignore */
          }
        }
        done();
      };

      this.busy = true;
      try {
        const res = this.backend.speak(next.text, done, onError);
        if (!res && !this.backend.isSupported()) {
          finished = true;
          this.busy = false;
          return;
        }
      } catch {
        onError();
        return;
      }

      // Watchdog timeout to prevent voice queue stall
      this.guard = setTimeout(done, Math.max(1400, next.text.length * 115));
    },

    cancel() {
      this.gen += 1;
      this.queue = [];
      this.busy = false;
      if (this.guard) {
        clearTimeout(this.guard);
        this.guard = null;
      }
      try {
        if (this.backend && typeof this.backend.cancel === 'function') {
          this.backend.cancel();
        }
      } catch {
        /* ignore */
      }
    },
  };

  // Expose backends for testing or manual selection
  PracticeVoice.BrowserSpeechBackend = BrowserSpeechBackend;
  PracticeVoice.KokoroSpeechBackend = KokoroSpeechBackend;

  // Auto-probe server for Kokoro ONNX neural speech availability
  if (typeof window !== 'undefined' && typeof window.fetch === 'function') {
    fetch('/api/voice/status')
      .then(res => res.json())
      .then(status => {
        if (status && status.available) {
          PracticeVoice.setBackend(KokoroSpeechBackend);
          PracticeVoice.provider = 'kokoro';
          console.log('[PracticeVoice] Kokoro neural TTS active (model: ' + status.model + ')');
          setTimeout(() => {
            KokoroSpeechBackend.prewarm([
              '1', '2', '3', '4', '5', '6', '7', '8', '9', '10',
              'Rest complete.', 'Workout complete.', 'Next set', 'Next exercise'
            ]);
          }, 1000);
        } else {
          PracticeVoice.provider = 'browser';
        }
      })
      .catch(() => {
        PracticeVoice.provider = 'browser';
      });
  }

  return PracticeVoice;
});
