"""Server tests: Grok chat route (mocked xAI), HTTPS handshake diagnostics and the certificate setup page."""

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
    import cryptography  # noqa: F401
    import basketball.app.local_tls as local_tls
except ImportError:  # pragma: no cover
    local_tls = None

FAKE_KEY = "xai-test-not-a-real-key-456"


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
    server.llm_provider = "xai" if chat else None
    server.llm_model = "grok-4.7" if chat else None
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
        cls.env = mock.patch.dict(os.environ, {"XAI_API_KEY": FAKE_KEY})
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
        self.assertEqual(health["llm_provider"], "xai")
        self.assertEqual(health["llm_model"], "grok-4.7")
        self.assertNotIn(FAKE_KEY, json.dumps(health))
        status, health = self.call(self.off, "GET", "/api/health")
        self.assertFalse(health["llm_chat_enabled"])
        self.assertIn("XAI_API_KEY", health["llm_setup"])

    def test_disabled_chat_explains_setup(self):
        sid = ShotLabDB(self.off.db_path).create_session(player_id="p2", camera_view="side_90", shot_type="catch_and_shoot",
                                                         shot_style="jump_shot", fps=30.0, model_version="t", notes="{}")
        status, body = self.call(self.off, "POST", f"/api/sessions/{sid}/coach-chat", {"question": "hi"})
        self.assertEqual(status, 503)
        self.assertEqual(body["code"], "not_configured")
        self.assertIn(".env", body["error"])

    def test_answer_and_error_paths(self):
        reply = {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Work on balance."}]}]}
        with mock.patch.object(llm, "urlopen", return_value=FakeResponse(json.dumps(reply).encode())) as fake:
            status, body = self.ask()
        self.assertEqual(status, 200, body)
        self.assertEqual(body["answer"], "Work on balance.")
        self.assertEqual(body["provider"], "xai")
        self.assertNotIn(FAKE_KEY, json.dumps(body))
        sent = json.loads(fake.call_args[0][0].data.decode())
        self.assertNotIn(FAKE_KEY, json.dumps(sent))   # the key travels only in the Authorization header

        no_credits = urllib.error.HTTPError(llm.XAI_ENDPOINT, 403, "x", {},
                                            io.BytesIO(b'{"error":"Your team does not have any credits"}'))
        with mock.patch.object(llm, "urlopen", side_effect=no_credits):
            status, body = self.ask()
        self.assertEqual((status, body["code"]), (502, "no_credits"))
        self.assertIn("credits", body["error"])
        status, health = self.call(self.server, "GET", "/api/health")
        self.assertEqual(health["llm_status"]["state"], "no_credits")

        limited = urllib.error.HTTPError(llm.XAI_ENDPOINT, 429, "x", {}, io.BytesIO(b"{}"))
        with mock.patch.object(llm, "urlopen", side_effect=limited):
            status, body = self.ask()
        self.assertEqual((status, body["code"]), (429, "rate_limited"))
        with mock.patch.object(llm, "urlopen", side_effect=TimeoutError()):
            status, body = self.ask()
        self.assertEqual((status, body["code"]), (504, "timeout"))
        status, body = self.ask("x" * 1001)
        self.assertEqual(status, 400)
        status, _ = self.call(self.server, "POST", "/api/sessions/nope/coach-chat", {"question": "hi"})
        self.assertEqual(status, 404)

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
