"""
kokoro_service.py - Lightweight local neural text-to-speech service using Kokoro ONNX.

Provides high-quality, low-latency offline voice synthesis for:
- Live Practice Audio Coach cues and feedback
- Guided Workout repetition countdowns, rest notifications, and exercise announcements

Includes in-memory LRU caching of audio buffers for rapid repetition counting (<1ms latency).
"""

from __future__ import annotations

import io
import logging
import threading
import wave
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

try:
    from kokoro_onnx import Kokoro
except ImportError:
    Kokoro = None


DEFAULT_MODEL_CANDIDATES = [
    Path("models/kokoro/kokoro-v0_19.int8.onnx"),
    Path("models/kokoro/kokoro-v0_19.onnx"),
    Path("models/kokoro/kokoro-v0_19.fp16.onnx"),
]

DEFAULT_VOICE_CANDIDATES = [
    Path("models/kokoro/voices.bin"),
    Path("models/kokoro/voices.json"),
]


class KokoroService:
    """Thread-safe neural TTS service using Kokoro ONNX."""

    def __init__(
        self,
        model_path: Optional[str | Path] = None,
        voices_path: Optional[str | Path] = None,
        default_voice: str = "af_sarah",
        cache_size: int = 128,
        prewarm: bool = True,
    ):
        self.default_voice = default_voice
        self.cache_size = cache_size
        self._lock = threading.Lock()
        self._cache: OrderedDict[str, bytes] = OrderedDict()
        self.engine: Optional[Kokoro] = None
        self.model_file: Optional[Path] = None
        self.voices_file: Optional[Path] = None
        self.available_voices: List[str] = []

        if Kokoro is None:
            logger.info("kokoro-onnx package not installed; KokoroService will report unavailable")
            return

        resolved_model = None
        if model_path:
            mp = Path(model_path)
            if mp.exists():
                resolved_model = mp
        else:
            for cand in DEFAULT_MODEL_CANDIDATES:
                if cand.exists():
                    resolved_model = cand
                    break

        resolved_voices = None
        if voices_path:
            vp = Path(voices_path)
            if vp.exists():
                resolved_voices = vp
        else:
            for cand in DEFAULT_VOICE_CANDIDATES:
                if cand.exists():
                    resolved_voices = cand
                    break

        if resolved_model and resolved_voices:
            try:
                self.engine = Kokoro(str(resolved_model), str(resolved_voices))
                self.model_file = resolved_model
                self.voices_file = resolved_voices
                self.available_voices = list(self.engine.get_voices())
                logger.info(
                    "Kokoro ONNX engine loaded from %s with %d voices",
                    resolved_model,
                    len(self.available_voices),
                )
                if prewarm:
                    threading.Thread(target=self._prewarm_cache, daemon=True).start()
            except Exception as exc:
                logger.warning("Failed to initialize Kokoro ONNX engine: %s", exc)
                self.engine = None
        else:
            logger.info(
                "Kokoro weights not found; KokoroService inactive"
            )

    def is_available(self) -> bool:
        return self.engine is not None

    def get_status(self) -> Dict[str, Any]:
        return {
            "available": self.is_available(),
            "provider": "kokoro_onnx" if self.is_available() else "unavailable",
            "model": str(self.model_file) if self.model_file else None,
            "default_voice": self.default_voice,
            "voices": self.available_voices,
            "cache_entries": len(self._cache),
        }

    def _prewarm_cache(self) -> None:
        """Pre-generate common workout counts and cues for instant response."""
        common_phrases = [
            "1", "2", "3", "4", "5", "6", "7", "8", "9", "10",
            "Switch sides.", "Rest complete.", "Rest for 30 seconds.",
            "Audio coach active.", "Audio coach unmuted.", "Audio coach muted.",
        ]
        for phrase in common_phrases:
            try:
                self.synthesize_wav(
                    phrase,
                    voice=self.default_voice,
                    speed=1.1 if phrase.isdigit() else 1.0,
                )
            except Exception:
                pass

    def synthesize_wav(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: float = 1.0,
        lang: str = "en-us",
    ) -> Optional[bytes]:
        clean_text = (text or "").strip()
        if not clean_text or not self.is_available():
            return None

        chosen_voice = voice or self.default_voice
        if self.available_voices and chosen_voice not in self.available_voices:
            chosen_voice = self.available_voices[0]

        cache_key = f"{clean_text}|{chosen_voice}|{speed:.2f}|{lang}"
        with self._lock:
            if cache_key in self._cache:
                self._cache.move_to_end(cache_key)
                return self._cache[cache_key]

        try:
            with self._lock:
                samples, sample_rate = self.engine.create(
                    clean_text,
                    voice=chosen_voice,
                    speed=speed,
                    lang=lang,
                )
            pcm16 = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
            bio = io.BytesIO()
            with wave.open(bio, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(pcm16.tobytes())
            wav_bytes = bio.getvalue()

            with self._lock:
                self._cache[cache_key] = wav_bytes
                if len(self._cache) > self.cache_size:
                    self._cache.popitem(last=False)
            return wav_bytes
        except Exception as exc:
            logger.warning("Kokoro synthesis error for '%s': %s", clean_text, exc)
            return None

