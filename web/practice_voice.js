/**
 * practice_voice.js - Audio coach speech synthesizer and queue manager for live Practice.
 *
 * Implements a small replaceable TTS interface adhering to the voice queue,
 * mute toggle, and watchdog cancellation patterns from web/workout.js.
 * Pluggable backend allows future local Kokoro benchmarking/swap without altering coaching logic.
 */

(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.PracticeVoice = factory();
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  // Default browser speech synthesis speaker backend
  const BrowserSpeechBackend = {
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

    say(text, { priority = 'normal', kind = 'coach' } = {}) {
      if (!text || typeof text !== 'string' || !text.trim()) return false;
      if (!this.isSupported() || !this.enabled) return false;

      // Drop older pending coach cues if a new one arrives (latest focus supersedes)
      if (kind === 'coach') {
        this.queue = this.queue.filter(item => item.kind !== 'coach');
      }

      this.queue.push({ text: String(text).trim(), kind, priority });
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

      this.busy = true;
      try {
        const res = this.backend.speak(next.text, done, done);
        if (!res && !this.backend.isSupported()) {
          finished = true;
          this.busy = false;
          return;
        }
      } catch {
        finished = true;
        this.busy = false;
        return;
      }

      // Watchdog timeout to prevent voice queue stall if browser speech drops end event
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

  return PracticeVoice;
});
