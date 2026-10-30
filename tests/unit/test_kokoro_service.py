"""Unit tests for KokoroService (neural TTS engine)."""

import unittest
from unittest.mock import MagicMock, patch
import numpy as np

from basketball.services.kokoro_service import KokoroService


class TestKokoroService(unittest.TestCase):
    def test_unavailable_when_missing_files(self):
        service = KokoroService(
            model_path="models/nonexistent/model.onnx",
            voices_path="models/nonexistent/voices.bin",
            prewarm=False,
        )
        self.assertFalse(service.is_available())
        status = service.get_status()
        self.assertFalse(status["available"])
        self.assertEqual(status["provider"], "unavailable")
        self.assertIsNone(service.synthesize_wav("test"))

    def test_empty_or_whitespace_text(self):
        service = KokoroService(
            model_path="models/nonexistent/model.onnx",
            voices_path="models/nonexistent/voices.bin",
            prewarm=False,
        )
        self.assertIsNone(service.synthesize_wav(""))
        self.assertIsNone(service.synthesize_wav("   "))
        self.assertIsNone(service.synthesize_wav(None))

    def test_mock_engine_synthesis_and_caching(self):
        mock_engine = MagicMock()
        # Return fake 1-second audio array (24000 samples)
        fake_samples = np.zeros(24000, dtype=np.float32)
        mock_engine.create.return_value = (fake_samples, 24000)
        mock_engine.get_voices.return_value = ["af_sarah", "am_adam"]

        service = KokoroService(
            model_path="models/nonexistent/model.onnx",
            voices_path="models/nonexistent/voices.bin",
            prewarm=False,
        )
        service.engine = mock_engine
        service.available_voices = ["af_sarah", "am_adam"]

        self.assertTrue(service.is_available())
        status = service.get_status()
        self.assertTrue(status["available"])
        self.assertEqual(status["voices"], ["af_sarah", "am_adam"])

        # First call: invokes engine.create
        wav1 = service.synthesize_wav("Bend your knees")
        self.assertIsNotNone(wav1)
        self.assertTrue(wav1.startswith(b"RIFF"))
        self.assertEqual(mock_engine.create.call_count, 1)

        # Second call with same text: should hit cache, NOT engine.create
        wav2 = service.synthesize_wav("Bend your knees")
        self.assertEqual(wav1, wav2)
        self.assertEqual(mock_engine.create.call_count, 1)

    def test_cache_eviction(self):
        mock_engine = MagicMock()
        fake_samples = np.zeros(100, dtype=np.float32)
        mock_engine.create.return_value = (fake_samples, 24000)
        mock_engine.get_voices.return_value = ["af_sarah"]

        service = KokoroService(
            model_path="models/nonexistent/model.onnx",
            voices_path="models/nonexistent/voices.bin",
            cache_size=2,
            prewarm=False,
        )
        service.engine = mock_engine
        service.available_voices = ["af_sarah"]

        service.synthesize_wav("Phrase 1")
        service.synthesize_wav("Phrase 2")
        self.assertEqual(len(service._cache), 2)

        service.synthesize_wav("Phrase 3")
        self.assertEqual(len(service._cache), 2)
        # Phrase 1 should have been evicted
        keys = list(service._cache.keys())
        self.assertTrue(any("Phrase 2" in k for k in keys))
        self.assertTrue(any("Phrase 3" in k for k in keys))
        self.assertFalse(any("Phrase 1" in k for k in keys))

    def test_voice_fallback_when_voice_unknown(self):
        mock_engine = MagicMock()
        mock_engine.create.return_value = (np.zeros(100, dtype=np.float32), 24000)
        mock_engine.get_voices.return_value = ["af_sarah"]

        service = KokoroService(
            model_path="models/nonexistent/model.onnx",
            voices_path="models/nonexistent/voices.bin",
            prewarm=False,
        )
        service.engine = mock_engine
        service.available_voices = ["af_sarah"]

        service.synthesize_wav("Hello", voice="unknown_voice_xyz")
        # Verify engine was called with fallback 'af_sarah'
        mock_engine.create.assert_called_once()
        args, kwargs = mock_engine.create.call_args
        self.assertEqual(kwargs.get("voice"), "af_sarah")


if __name__ == "__main__":
    unittest.main()

