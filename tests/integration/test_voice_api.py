"""Integration tests for Voice API endpoints (/api/voice/status, /api/voice/synthesize)."""

import io
import json
import unittest
from unittest.mock import MagicMock
import numpy as np

from basketball.app import web_app
from basketball.services.kokoro_service import KokoroService
from basketball.services.live_service import LiveCameraEngine


class DummyRequest:
    def __init__(self, data: bytes):
        self._rfile = io.BytesIO(data)
        self._wfile = io.BytesIO()

    def makefile(self, mode: str, *args, **kwargs):
        if "b" in mode:
            if "r" in mode:
                return self._rfile
            return self._wfile
        raise ValueError("Only binary mode makefile is supported by DummyRequest")

    def sendall(self, data: bytes):
        self._wfile.write(data)


class FakeServer:
    def __init__(self, kokoro=None):
        self.live_engine = LiveCameraEngine(weights_path=None)
        self.kokoro = kokoro or KokoroService(
            model_path="models/nonexistent/model.onnx",
            voices_path="models/nonexistent/voices.bin",
            prewarm=False,
        )
        self.db_path = "shot_lab.db"
        self.lan_mode = False
        self.lan_urls = []
        self.access_token = None
        self.tls_enabled = False
        self.ca_der_path = None
        self.ca_fingerprint = None
        self.setup_url = ""
        self.llm_chat_enabled = False
        self.llm_status = None
        self.llm_backup_status = None
        self.llm_model = None


def simulate_request(path, method="GET", body=None, headers=None, server=None):
    if server is None:
        server = FakeServer()
    body_bytes = b""
    if body is not None:
        body_bytes = json.dumps(body).encode("utf-8") if isinstance(body, dict) else body

    header_lines = [
        f"{method} {path} HTTP/1.1\r\n",
        "Host: 127.0.0.1\r\n",
        "X-Shotlab: 1\r\n",
    ]
    if headers:
        for k, v in headers.items():
            header_lines.append(f"{k}: {v}\r\n")
    if body_bytes:
        header_lines.append(f"Content-Length: {len(body_bytes)}\r\n")
        if not headers or "Content-Type" not in headers:
            header_lines.append("Content-Type: application/json\r\n")
    header_lines.append("\r\n")
    raw_req = "".join(header_lines).encode("utf-8") + body_bytes

    dummy = DummyRequest(raw_req)

    class InMemHandler(web_app.AppHandler):
        def __init__(self, req, client_addr, srv):
            self.server = srv
            self.client_address = client_addr
            self.connection = req
            self.rfile = req.makefile("rb")
            self.wfile = req.makefile("wb")
            try:
                self.handle_one_request()
            except Exception:
                pass

        def log_message(self, *args):
            pass

    InMemHandler(dummy, ("127.0.0.1", 54321), server)
    raw_output = dummy._wfile.getvalue()

    parts = raw_output.split(b"\r\n\r\n", 1)
    header_part = parts[0].decode("utf-8", errors="replace")
    body_part = parts[1] if len(parts) > 1 else b""

    lines = header_part.split("\r\n")
    status_line = lines[0] if lines else ""
    status_code = int(status_line.split(" ")[1]) if len(status_line.split(" ")) > 1 else 500

    return status_code, body_part, header_part


class VoiceAPITests(unittest.TestCase):
    def test_voice_status_endpoint_returns_json(self):
        code, body, _ = simulate_request("/api/voice/status", method="GET")
        self.assertEqual(code, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("available", data)
        self.assertIn("provider", data)
        self.assertIn("default_voice", data)
        self.assertIn("voices", data)

    def test_voice_synthesize_unavailable_returns_503(self):
        code, body, _ = simulate_request("/api/voice/synthesize", method="POST", body={"text": "Hello"})
        self.assertEqual(code, 503)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("error", data)

    def test_voice_synthesize_missing_text_returns_400(self):
        mock_kokoro = KokoroService(
            model_path="models/nonexistent/model.onnx",
            voices_path="models/nonexistent/voices.bin",
            prewarm=False,
        )
        mock_kokoro.engine = MagicMock()
        mock_kokoro.available_voices = ["af_sarah"]
        server = FakeServer(kokoro=mock_kokoro)

        code, body, _ = simulate_request("/api/voice/synthesize", method="POST", body={}, server=server)
        self.assertEqual(code, 400)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("error", data)

    def test_voice_synthesize_with_mock_kokoro_returns_wav(self):
        mock_kokoro = KokoroService(
            model_path="models/nonexistent/model.onnx",
            voices_path="models/nonexistent/voices.bin",
            prewarm=False,
        )
        mock_engine = MagicMock()
        mock_engine.create.return_value = (np.zeros(24000, dtype=np.float32), 24000)
        mock_engine.get_voices.return_value = ["af_sarah"]
        mock_kokoro.engine = mock_engine
        mock_kokoro.available_voices = ["af_sarah"]

        server = FakeServer(kokoro=mock_kokoro)
        code, body, headers = simulate_request(
            "/api/voice/synthesize",
            method="POST",
            body={"text": "Bend knees deeper"},
            server=server,
        )
        self.assertEqual(code, 200)
        self.assertIn("Content-Type: audio/wav", headers)
        self.assertTrue(body.startswith(b"RIFF"))

    def test_health_endpoint_reports_neural_tts(self):
        code, body, _ = simulate_request("/api/health", method="GET")
        self.assertEqual(code, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("neural_tts", data)


if __name__ == "__main__":
    unittest.main()
