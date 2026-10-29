"""Integration tests for live audio coach API endpoints."""

import io
import json
import unittest
from basketball.app import web_app
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
    def __init__(self):
        self.live_engine = LiveCameraEngine(weights_path=None)
        self.db_path = "shot_lab.db"
        self.lan_mode = False
        self.lan_urls = []
        self.access_token = None
        self.tls_enabled = False
        self.ca_der_path = None
        self.ca_fingerprint = None
        self.setup_url = ""
        self.llm_chat_enabled = False


def simulate_request(path, method="GET", body=None, headers=None):
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

    return status_code, body_part


class LiveAudioAPITests(unittest.TestCase):
    def test_live_reset_endpoint_returns_audio_coach_caption(self):
        code, body = simulate_request("/api/live/reset", method="POST", body={"player_id": "player"})
        self.assertEqual(code, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "ok")
        self.assertIn("caption", data)
        self.assertIn("focus", data)

    def test_live_recap_endpoint_returns_recap_speech(self):
        code, body = simulate_request("/api/live/recap", method="GET")
        self.assertEqual(code, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["event_type"], "recap")
        self.assertTrue(data["speak"])
        self.assertIn("text", data)
        self.assertIn("caption", data)


if __name__ == "__main__":
    unittest.main()
