"""Integration tests for Drills web endpoints in web_app.py."""

import base64
import io
import json
import unittest
from pathlib import Path
import cv2
import numpy as np

import basketball.app.web_app as web_app
from basketball.services.drill_service import DrillTrackingEngine


class MockServer:
    def __init__(self):
        self.access_token = None
        self.lan_mode = False
        self.lan_urls = []
        self.tls_enabled = False
        self.ca_der_path = None
        self.ca_fingerprint = None
        self.setup_url = None
        self.auth_failures = {}
        self.keyframe_dir = Path("data/keyframes")
        self.drill_engine = DrillTrackingEngine(weights_path="models/best.pt")


class DummyRequest:
    def __init__(self, raw_bytes=b""):
        self._rfile = io.BytesIO(raw_bytes)
        self._wfile = io.BytesIO()

    def makefile(self, mode, *args, **kwargs):
        if "b" in mode:
            if "r" in mode:
                return self._rfile
            return self._wfile
        raise ValueError("binary mode expected")

    def sendall(self, data):
        self._wfile.write(data)

    def settimeout(self, timeout):
        pass


def simulate_request(server, method, path, body=None, headers=None):
    hdrs = dict(headers or {})
    hdrs.setdefault("X-Shotlab", "1")
    body_bytes = b""
    if body is not None:
        if isinstance(body, (dict, list)):
            body_bytes = json.dumps(body).encode("utf-8")
            hdrs["Content-Type"] = "application/json"
        elif isinstance(body, (bytes, bytearray)):
            body_bytes = bytes(body)
        else:
            body_bytes = str(body).encode("utf-8")
        hdrs["Content-Length"] = str(len(body_bytes))
    else:
        hdrs["Content-Length"] = "0"

    raw_req = f"{method} {path} HTTP/1.1\r\nHost: localhost\r\n"
    for k, v in hdrs.items():
        raw_req += f"{k}: {v}\r\n"
    raw_req += "\r\n"

    req_stream = raw_req.encode("utf-8") + body_bytes
    dummy = DummyRequest(req_stream)
    handler = web_app.AppHandler(dummy, ("127.0.0.1", 54321), server)

    output = dummy._wfile.getvalue()
    parts = output.split(b"\r\n\r\n", 1)
    header_part = parts[0].decode("utf-8", errors="replace")
    body_part = parts[1] if len(parts) > 1 else b""

    status_line = header_part.splitlines()[0]
    status_code = int(status_line.split(" ")[1])

    resp_headers = {}
    for line in header_part.splitlines()[1:]:
        if ":" in line:
            hk, hv = line.split(":", 1)
            resp_headers[hk.strip().lower()] = hv.strip()

    parsed_json = None
    if "application/json" in resp_headers.get("content-type", ""):
        try:
            parsed_json = json.loads(body_part.decode("utf-8"))
        except Exception:
            pass

    return status_code, resp_headers, body_part, parsed_json


class TestDrillsRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = MockServer()

    def test_get_drills_catalog(self):
        status, _, _, data = simulate_request(self.server, "GET", "/api/drills")
        self.assertEqual(status, 200)
        self.assertIsNotNone(data)
        self.assertEqual(data["total"], 4)
        self.assertEqual(len(data["drills"]), 4)

    def test_drills_session_status(self):
        status, _, _, data = simulate_request(self.server, "GET", "/api/drills/session/status")
        self.assertEqual(status, 200)
        self.assertIn("is_active", data)
        self.assertIn("rep_count", data)

    def test_drills_lifecycle_start_process_stop(self):
        # 1. Start drill session
        start_payload = {"drill_id": "pound_plus_cross"}
        status, _, _, start_data = simulate_request(
            self.server, "POST", "/api/drills/session/start", body=start_payload
        )
        self.assertEqual(status, 200)
        self.assertEqual(start_data["status"], "started")
        self.assertEqual(start_data["drill_id"], "pound_plus_cross")
        self.assertEqual(start_data["target_sequence"], ["POUND", "POUND", "CROSSOVER"])
        self.assertIn("reference_biomechanics", start_data)

        # 2. Process synthetic frame (encoded as base64 JPEG)
        img = np.zeros((360, 480, 3), dtype=np.uint8)
        _, enc = cv2.imencode(".jpg", img)
        b64_img = base64.b64encode(enc.tobytes()).decode("utf-8")

        frame_payload = {
            "image": f"data:image/jpeg;base64,{b64_img}",
            "timestamp_ms": 1000,
        }
        status, _, _, frame_data = simulate_request(
            self.server, "POST", "/api/drills/process-frame", body=frame_payload
        )
        self.assertEqual(status, 200)
        self.assertEqual(frame_data["status"], "ok")
        self.assertIn("ball", frame_data)
        self.assertIn("bounce_event", frame_data)
        self.assertIn("rep_count", frame_data)
        self.assertIn("current_move", frame_data)
        self.assertIn("combos_completed", frame_data)
        self.assertIn("combo_progress", frame_data)
        self.assertIn("style_match_pct", frame_data)
        self.assertIn("angles", frame_data)
        self.assertIn("posture", frame_data)
        self.assertIn("live_cue", frame_data)

        # 3. Stop drill session
        status, _, _, stop_data = simulate_request(
            self.server, "POST", "/api/drills/session/stop"
        )
        self.assertEqual(status, 200)
        self.assertEqual(stop_data["status"], "completed")
        self.assertEqual(stop_data["drill_id"], "pound_plus_cross")
        self.assertIn("rep_count", stop_data)
        self.assertIn("combos_completed", stop_data)
        self.assertIn("style_match_pct", stop_data)
        self.assertIn("sequence_description", stop_data)
        self.assertIn("duration_seconds", stop_data)
        self.assertIn("posture_summary", stop_data)
        self.assertIn("feedback_items", stop_data)


if __name__ == "__main__":
    unittest.main()
