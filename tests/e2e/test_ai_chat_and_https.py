"""Server tests: AI chat route (mocked Groq primary + Gemini backup), HTTPS diagnostics and the setup page."""

import io
import json
import os
import shutil
import socket
import ssl
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

import basketball.app.web_app as web_app
import basketball.coaching.llm_coach as llm
from basketball.persistence.shot_lab_db import ShotLabDB

try:
    import groq  # noqa: F401
    import httpx
except ImportError:  # pragma: no cover
    httpx = None

try:
    import cryptography  # noqa: F401
    import basketball.app.local_tls as local_tls
except ImportError:  # pragma: no cover
    local_tls = None

FAKE_KEY = "gsk_test_not_a_real_key_456"
FAKE_GEMINI_KEY = "AIza_test_not_a_real_key_789"
CHAIN = [("groq", "openai/gpt-oss-120b"), ("gemini", "gemini-3.8-flash")]


def make_server(tmp, *, chat=False):
    server = web_app.LocalAppServer(("127.0.0.1", 0), web_app.AppHandler)
    server.db_path = str(tmp / "chat.db")
    for name in ("upload_dir", "pose_cache_dir", "keyframe_dir"):
        folder = tmp / name
        folder.mkdir(exist_ok=True)
        setattr(server, name, folder)
    server.job_store = web_app.JobStore(server.db_path + ".web_jobs.sqlite3", upload_root=server.upload_dir)
    server.executor = ThreadPoolExecutor(max_workers=1)
    server.worker_slots = threading.BoundedSemaphore(2)
    server.session_locks = {}
    server.llm_chat_enabled = chat
    server.llm_provider = CHAIN[0][0] if chat else None
    server.llm_model = CHAIN[0][1] if chat else None
    server.llm_chain = list(CHAIN) if chat else None
    return server


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class ChatRouteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="shotlab_chat_"))
        cls.server = make_server(cls.tmp, chat=True)
        cls.off = make_server(Path(tempfile.mkdtemp(prefix="shotlab_chat_off_")), chat=False)
        for server in (cls.server, cls.off):
            threading.Thread(target=server.serve_forever, daemon=True).start()
        cls.session_id = ShotLabDB(cls.server.db_path).create_session(
            player_id="chat_player", camera_view="side_90", shot_type="catch_and_shoot", shot_style="jump_shot",
            fps=30.0, model_version="test", notes="{}")
        cls.env = mock.patch.dict(os.environ, {"GROQ_API_KEY": FAKE_KEY, "GEMINI_API_KEY": FAKE_GEMINI_KEY})
        cls.env.start()

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        for server in (cls.server, cls.off):
            server.shutdown()
            server.server_close()
            server.executor.shutdown(wait=True)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def call(self, server, method, path, body=None, headers=None):
        headers = dict(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if method != "GET":
            headers.setdefault("X-Shotlab", "1")
        req = urllib.request.Request(f"http://127.0.0.1:{server.server_address[1]}{path}", data=data, method=method,
                                     headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def ask(self, question="What should I practise?"):
        return self.call(self.server, "POST", f"/api/sessions/{self.session_id}/coach-chat", {"question": question})

    def test_health_reports_provider_without_the_key(self):
        status, health = self.call(self.server, "GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(health["llm_chat_enabled"])
        self.assertEqual(health["llm_provider"], "groq")
        self.assertEqual(health["llm_model"], "openai/gpt-oss-120b")
        self.assertEqual(health["llm_backup"]["provider"], "gemini")
        self.assertEqual(health["llm_backup"]["model"], "gemini-3.8-flash")
        self.assertNotIn(FAKE_KEY, json.dumps(health))
        self.assertNotIn(FAKE_GEMINI_KEY, json.dumps(health))
        status, health = self.call(self.off, "GET", "/api/health")
        self.assertFalse(health["llm_chat_enabled"])
        self.assertIn("GROQ_API_KEY", health["llm_setup"])

    def test_disabled_chat_explains_setup(self):
        sid = ShotLabDB(self.off.db_path).create_session(player_id="p2", camera_view="side_90", shot_type="catch_and_shoot",
                                                         shot_style="jump_shot", fps=30.0, model_version="t", notes="{}")
        status, body = self.call(self.off, "POST", f"/api/sessions/{sid}/coach-chat", {"question": "hi"})
        self.assertEqual(status, 503)
        self.assertEqual(body["code"], "not_configured")
        self.assertIn(".env", body["error"])

    # Groq goes through the official SDK (HTTP mocked with httpx.MockTransport); Gemini through urllib (mocked).
    def groq_replies(self, handler):
        llm.GROQ_HTTP_CLIENT = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(setattr, llm, "GROQ_HTTP_CLIENT", None)

    @staticmethod
    def groq_stream(*texts, finish=True):
        events = [{"choices": [{"index": 0, "delta": {"content": t}, "finish_reason": None}]} for t in texts]
        if finish:
            events.append({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
        body = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + ("data: [DONE]\n\n" if finish else "")
        return lambda request: httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body.encode())

    @staticmethod
    def groq_error(status, code):
        body = json.dumps({"error": {"message": "x", "type": "invalid_request_error", "code": code}}).encode()
        return lambda request: httpx.Response(status, headers={"content-type": "application/json"}, content=body)

    @staticmethod
    def gemini(text=None, error=None):
        def fake(req, timeout):
            if error is not None:
                raise error
            return FakeResponse(json.dumps({"candidates": [{"content": {"parts": [{"text": text}]}}]}).encode())
        return fake

    def stream(self, question="What should I practise?"):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.server.server_address[1]}/api/sessions/{self.session_id}/coach-chat",
            data=json.dumps({"question": question}).encode(), method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/x-ndjson", "X-Shotlab": "1"})
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                self.assertIn("application/x-ndjson", response.headers["Content-Type"])
                return response.status, [json.loads(line) for line in response.read().decode().splitlines() if line.strip()]
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    @unittest.skipIf(httpx is None, "groq SDK / httpx not installed")
    def test_streamed_answer_and_fallback_in_the_same_response(self):
        self.groq_replies(self.groq_stream("Work ", "", "on balance."))
        with mock.patch.object(llm, "urlopen", side_effect=AssertionError("no fallback")):
            status, events = self.stream()
        self.assertEqual(status, 200)
        self.assertEqual([e["type"] for e in events], ["start", "delta", "delta", "done"])
        self.assertEqual("".join(e["text"] for e in events if e["type"] == "delta"), "Work on balance.")
        self.assertEqual(events[-1]["provider"], "groq")
        self.assertNotIn(FAKE_KEY, json.dumps(events))

        self.groq_replies(self.groq_error(429, "rate_limit_exceeded"))
        with mock.patch.object(llm, "urlopen", side_effect=self.gemini("Backup answer: land softly.")):
            status, events = self.stream()
        self.assertEqual(status, 200)
        types = [e["type"] for e in events]
        self.assertEqual(types, ["start", "fallback", "start", "delta", "done"])
        self.assertEqual((events[1]["http_status"], events[1]["provider_code"]), (429, "rate_limit_exceeded"))
        self.assertEqual(events[-1]["provider"], "gemini")
        self.assertEqual(events[3]["text"], "Backup answer: land softly.")

        self.groq_replies(self.groq_stream("Half", finish=False))   # HTTP 200 but the stream never finished
        with mock.patch.object(llm, "urlopen", side_effect=self.gemini("Complete backup answer.")):
            status, events = self.stream()
        fallback = next(e for e in events if e["type"] == "fallback")
        self.assertEqual((fallback["code"], fallback["reset"]), ("incomplete", True))
        self.assertEqual(events[-1]["provider"], "gemini")

    @unittest.skipIf(httpx is None, "groq SDK / httpx not installed")
    def test_stream_errors(self):
        self.groq_replies(self.groq_error(429, "rate_limit_exceeded"))
        down = urllib.error.HTTPError(llm.GEMINI_BASE, 503, "x", {}, io.BytesIO(b"{}"))
        with mock.patch.object(llm, "urlopen", side_effect=self.gemini(error=down)):
            status, events = self.stream()
        self.assertEqual(events[-1]["type"], "error")
        self.assertIn("No AI answer is available right now", events[-1]["error"])

        self.groq_replies(self.groq_error(401, "invalid_api_key"))
        with mock.patch.object(llm, "urlopen", side_effect=AssertionError("no fallback for a bad key")):
            status, events = self.stream()
        self.assertEqual((events[-1]["type"], events[-1]["code"], events[-1]["http_status"]), ("error", "invalid_key", 401))
        status, health = self.call(self.server, "GET", "/api/health")
        self.assertEqual(health["llm_status"]["state"], "invalid_key")
        status, body = self.stream(question="x" * 1001)
        self.assertEqual(status, 400)

    @unittest.skipIf(httpx is None, "groq SDK / httpx not installed")
    def test_closing_the_browser_connection_stops_groq(self):
        closed = threading.Event()

        class Slow(httpx.SyncByteStream):
            def __iter__(self):
                for index in range(60):
                    if closed.is_set():
                        return
                    event = {"choices": [{"index": 0, "delta": {"content": f"word{index} "}, "finish_reason": None}]}
                    yield f"data: {json.dumps(event)}\n\n".encode()
                    time.sleep(0.05)

            def close(self):
                closed.set()
        self.groq_replies(lambda request: httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Slow()))
        port = self.server.server_address[1]
        body = json.dumps({"question": "Long answer please"}).encode()
        with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
            sock.sendall((f"POST /api/sessions/{self.session_id}/coach-chat HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                          "Content-Type: application/json\r\nAccept: application/x-ndjson\r\nX-Shotlab: 1\r\n"
                          f"Content-Length: {len(body)}\r\n\r\n").encode() + body)
            received = b""
            while b'"delta"' not in received:
                received += sock.recv(4096)
        self.assertTrue(closed.wait(10), "the server closed the Groq stream after the browser disconnected")

    def test_json_route_still_works(self):
        """The non-streaming JSON reply (scripts, older pages) uses the same provider chain."""
        if httpx is None:
            self.skipTest("groq SDK / httpx not installed")
        self.groq_replies(self.groq_error(503, "service_unavailable"))
        with mock.patch.object(llm, "urlopen", side_effect=self.gemini("Backup via JSON.")):
            status, body = self.ask()
        self.assertEqual(status, 200)
        self.assertEqual((body["provider"], body["fallback_from"], body["answer"]), ("gemini", "groq", "Backup via JSON."))

    def test_chat_requires_csrf_header(self):
        status, _ = self.call(self.server, "POST", f"/api/sessions/{self.session_id}/coach-chat", {"question": "hi"},
                              headers={"X-Shotlab": "0"})
        self.assertEqual(status, 403)


@unittest.skipIf(local_tls is None, "cryptography is not installed")
class HttpsDiagnosticsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="shotlab_tlsdiag_"))
        cls.tls = local_tls.ensure_local_certificates(cls.tmp / "certs", [])
        cls.server = make_server(cls.tmp)
        cls.server.ca_der_path = cls.tls["ca_der"]
        cls.server.ca_fingerprint = local_tls.ca_fingerprint(cls.tls["ca_pem"])
        web_app.enable_tls(cls.server, cls.tls["cert"], cls.tls["key"])
        cls.server.setup_url = "http://127.0.0.1:1/"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.port = cls.server.server_address[1]
        cls.setup = web_app.start_setup_server("127.0.0.1", 0, {
            "ca_der": cls.tls["ca_der"], "fingerprint": cls.server.ca_fingerprint, "computer": "test-mac",
            "https_url_for": lambda host: f"https://127.0.0.1:{cls.port}/"})

    @classmethod
    def tearDownClass(cls):
        for server in (cls.server, cls.setup):
            server.shutdown()
            server.server_close()
        cls.server.executor.shutdown(wait=True)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def wait_event(self, predicate):
        deadline = time.time() + 10
        while time.time() < deadline:
            event = self.server.tls_events.get("127.0.0.1")
            if event and predicate(event):
                return event
            time.sleep(0.05)
        self.fail(f"no matching TLS event: {self.server.tls_events}")

    def test_untrusting_client_is_reported_clearly(self):
        with self.assertRaises(ssl.SSLError):
            with socket.create_connection(("127.0.0.1", self.port), timeout=10) as raw:
                ssl.create_default_context().wrap_socket(raw, server_hostname="127.0.0.1")
        event = self.wait_event(lambda e: "UNKNOWN_CA" in e["reason"] or "CERTIFICATE" in e["reason"])
        self.assertIn("does not trust", event["hint"])
        self.assertIn("http://127.0.0.1:1/", event["hint"])
        # The computer's own connection panel lists the device and the fix.
        context = ssl.create_default_context(cafile=str(self.tls["ca_pem"]))
        with urllib.request.urlopen(f"https://127.0.0.1:{self.port}/api/connection", context=context, timeout=10) as r:
            info = json.loads(r.read())
        self.assertEqual(info["tls_problems"][0]["ip"], "127.0.0.1")
        self.assertEqual(info["setup_url"], "http://127.0.0.1:1/")

    def test_plain_http_to_the_https_port_is_explained(self):
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as raw:
            raw.sendall(b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            try:
                raw.recv(100)
            except OSError:
                pass
        event = self.wait_event(lambda e: "HTTP" in e["reason"] or "VERSION" in e["reason"])
        self.assertIn("https://", event["hint"])

    def test_setup_page_serves_only_the_public_certificate(self):
        base = f"http://127.0.0.1:{self.setup.server_address[1]}"
        with urllib.request.urlopen(base + "/", timeout=10) as r:
            page = r.read().decode()
        self.assertIn(self.server.ca_fingerprint, page)
        self.assertIn("Certificate Trust Settings", page)
        self.assertIn("Do not bypass", page)
        self.assertIn(f"https://127.0.0.1:{self.port}/", page)
        with urllib.request.urlopen(base + "/shotlab-ca.crt", timeout=10) as r:
            self.assertEqual(r.headers["Content-Type"], "application/x-x509-ca-cert")
            body = r.read()
        self.assertEqual(body, Path(self.tls["ca_der"]).read_bytes())
        self.assertNotIn(b"PRIVATE", body)
        for path in ("/api/health", "/shotlab-local-ca-key.pem", "/../certs/shotlab-server-key.pem", "/?token=x"):
            try:
                with urllib.request.urlopen(base + path, timeout=10) as r:
                    status, text = r.status, r.read()
            except urllib.error.HTTPError as exc:
                status, text = exc.code, exc.read()
            if path == "/?token=x":
                self.assertEqual(status, 200)
                self.assertNotIn(b"access_code", text)
            else:
                self.assertEqual(status, 404, path)
                self.assertNotIn(b"PRIVATE", text)


if __name__ == "__main__":
    unittest.main()
