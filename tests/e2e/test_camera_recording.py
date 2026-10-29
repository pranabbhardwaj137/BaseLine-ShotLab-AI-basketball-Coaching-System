"""Browser tests for in-page camera recording over HTTPS, and for the http:// explanation.

Chromium runs with its built-in *fake* camera (``--use-fake-device-for-media-stream``: a moving
test pattern), so these tests check the recorder's states, the recorded file, and that the
recording is accepted by the real upload/analysis endpoint. They do not exercise a physical
camera, iPhone/Android browsers, or Safari's MP4 recorder (manual checks; see README).

The server uses the built-in local HTTPS certificate (the same code path as ``--https``); the
browser context ignores certificate trust because the test CA is not installed in Chromium.
Skipped when Playwright/Chromium or the ``cryptography`` package is unavailable.
"""

import json
import shutil
import ssl
import tempfile
import threading
import time
import unittest
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import basketball.app.web_app as web_app

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - optional dependency
    sync_playwright = None
try:
    import cryptography  # noqa: F401
    import basketball.app.local_tls as local_tls
except ImportError:  # pragma: no cover - optional dependency
    local_tls = None

CHROMIUM_ARGS = ["--no-proxy-server", "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"]


@unittest.skipIf(sync_playwright is None, "playwright is not installed")
@unittest.skipIf(local_tls is None, "cryptography is not installed")
class CameraRecordingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="shotlab_camera_test_"))
        tls = local_tls.ensure_local_certificates(cls.tmp / "certs", [])
        cls.ca_pem = tls["ca_pem"]
        cls.ca_der = tls["ca_der"]
        server = web_app.LocalAppServer(("127.0.0.1", 0), web_app.AppHandler)
        server.db_path = str(cls.tmp / "camera.db")
        for name in ("upload_dir", "pose_cache_dir", "keyframe_dir"):
            folder = cls.tmp / name
            folder.mkdir()
            setattr(server, name, folder)
        server.job_store = web_app.JobStore(server.db_path + ".web_jobs.sqlite3", upload_root=server.upload_dir)
        server.executor = ThreadPoolExecutor(max_workers=1)
        server.worker_slots = threading.BoundedSemaphore(2)
        server.session_locks = {}
        server.llm_chat_enabled = False
        server.llm_model = "x"
        server.ca_der_path = tls["ca_der"]
        server.ca_fingerprint = local_tls.ca_fingerprint(tls["ca_pem"])
        web_app.enable_tls(server, tls["cert"], tls["key"])
        cls.server = server
        threading.Thread(target=server.serve_forever, daemon=True).start()
        cls.base = f"https://127.0.0.1:{server.server_address[1]}"
        try:
            cls.pw = sync_playwright().start()
            cls.browser = cls.pw.chromium.launch(args=CHROMIUM_ARGS)
        except Exception as exc:  # browser binary missing
            cls.server.shutdown()
            raise unittest.SkipTest(f"Chromium for Playwright is not available: {exc}")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.server.executor.shutdown(wait=True)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def open(self, width=1280, height=900, mobile=False, init_script=None):
        ctx = self.browser.new_context(ignore_https_errors=True, viewport={"width": width, "height": height},
                                       is_mobile=mobile, has_touch=mobile, permissions=["camera"])
        if init_script:
            ctx.add_init_script(init_script)
        page = ctx.new_page()
        self.errors = []
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.goto(self.base + "/#new")
        page.wait_for_selector("#tab-camera")
        self.addCleanup(ctx.close)
        return page

    @staticmethod
    def wait_js(page, expression, timeout=15000):
        """Poll a JS expression from Python (the app's CSP forbids the eval Playwright's polling needs)."""
        deadline = time.time() + timeout / 1000
        while time.time() < deadline:
            if page.evaluate(expression):
                return
            page.wait_for_timeout(100)
        raise AssertionError(f"timed out waiting for: {expression}")

    def visible(self, page, *selectors):
        return {s: page.is_visible(s) for s in selectors}

    # ------------------------------------------------------------------ tests
    def test_https_server_verifies_with_the_local_ca_and_serves_its_certificate(self):
        context = ssl.create_default_context(cafile=str(self.ca_pem))
        with urllib.request.urlopen(self.base + "/shotlab-ca.crt", context=context, timeout=30) as response:
            self.assertEqual(response.headers["Content-Type"], "application/x-x509-ca-cert")
            self.assertEqual(response.read(), self.ca_der.read_bytes())
        with self.assertRaises(urllib.error.URLError):   # an untrusted client must not connect silently
            urllib.request.urlopen(self.base + "/", context=ssl.create_default_context(), timeout=30)

    def test_record_pause_resume_review_retake_and_upload(self):
        page = self.open()
        self.assertTrue(page.evaluate("window.isSecureContext"))
        page.fill("input[name=player_id]", "camera_test")
        page.click("#tab-camera")
        self.assertEqual(self.visible(page, "#camera-start", "#record-start", "#camera-stop"),
                         {"#camera-start": True, "#record-start": False, "#camera-stop": False})
        page.click("#camera-start")
        page.wait_for_selector("#record-start:not(.hidden)", timeout=15000)
        self.wait_js(page, "document.querySelector('#camera-preview').readyState >= 2", 15000)
        self.assertTrue(page.is_visible("#camera-stop"))
        self.assertFalse(page.is_visible("#camera-switch"), "only one (fake) camera: no switch button")
        ratio = page.evaluate("getComputedStyle(document.querySelector('#camera-viewport')).aspectRatio")
        self.assertRegex(ratio, r"^\d+ / \d+$", "viewport follows the camera's real frame shape")

        page.click("#record-start")
        page.wait_for_timeout(1600)
        self.assertTrue(page.is_visible("#rec-indicator"))
        self.assertEqual(self.visible(page, "#record-pause", "#record-stop", "#record-start"),
                         {"#record-pause": True, "#record-stop": True, "#record-start": False})
        page.click("#record-pause")
        frozen = page.inner_text("#rec-time")
        self.assertEqual(page.inner_text("#rec-label"), "PAUSED")
        page.wait_for_timeout(1500)
        self.assertEqual(page.inner_text("#rec-time"), frozen, "paused time is not counted")
        page.click("#record-pause")
        self.assertEqual(page.inner_text("#rec-label"), "REC")
        page.wait_for_timeout(1600)
        page.click("#record-stop")
        page.wait_for_selector("#record-retake:not(.hidden)", timeout=15000)
        self.wait_js(page, "document.querySelector('#camera-review').readyState >= 1", 15000)
        review = page.evaluate("""() => { const v = document.querySelector('#camera-review');
            return {hidden: v.hidden, src: v.src.slice(0, 5), w: v.videoWidth}; }""")
        self.assertEqual(review["src"], "blob:")
        self.assertFalse(review["hidden"])
        self.assertIn("Recording ready", page.inner_text("#camera-status"))

        page.click("#record-retake")
        page.wait_for_selector("#record-start:not(.hidden)")
        page.click("#submit-button")   # nothing recorded after the retake
        self.assertIn("Record a clip first", page.inner_text("#form-error"))
        page.click("#record-start")
        page.wait_for_timeout(3000)
        page.click("#record-stop")
        page.wait_for_selector("#record-retake:not(.hidden)", timeout=15000)
        page.click("#submit-button")

        # The recording reaches the normal upload + analysis pipeline.
        self.wait_js(page, "localStorage.getItem('shotLabLastJobId')", 60000)
        job_id = page.evaluate("localStorage.getItem('shotLabLastJobId')")
        deadline = time.time() + 240
        job = {}
        context = ssl.create_default_context(cafile=str(self.ca_pem))
        while time.time() < deadline:
            with urllib.request.urlopen(f"{self.base}/api/jobs/{job_id}", context=context, timeout=30) as response:
                job = json.loads(response.read())
            if job.get("status") in ("complete", "failed"):
                break
            time.sleep(1)
        self.assertEqual(job.get("status"), "complete", job)
        uploads = list(Path(self.server.upload_dir).glob(f"{job_id}.*"))
        self.assertTrue(any(p.suffix in (".webm", ".mp4") for p in uploads), uploads)
        self.assertEqual(self.errors, [])

    def test_turning_the_camera_off_while_recording_keeps_the_clip(self):
        page = self.open()
        page.click("#tab-camera")
        page.click("#camera-start")
        page.wait_for_selector("#record-start:not(.hidden)", timeout=15000)
        page.click("#record-start")
        page.wait_for_timeout(1500)
        page.click("#camera-stop")
        page.wait_for_selector("#record-retake:not(.hidden)", timeout=15000)
        self.assertIn("Recording ready", page.inner_text("#camera-status"))
        self.assertEqual(page.evaluate("document.querySelector('#camera-preview').srcObject"), None)

    def test_http_page_explains_https_instead_of_claiming_no_support(self):
        # Simulates a phone opening http://<computer IP>: not a secure context, no mediaDevices.
        insecure = """
        Object.defineProperty(window, 'isSecureContext', {value: false, configurable: true});
        Object.defineProperty(navigator, 'mediaDevices', {value: undefined, configurable: true});
        """
        page = self.open(width=390, height=844, mobile=True, init_script=insecure)
        page.click("#tab-camera")
        note = page.inner_text("#camera-secure-note")
        self.assertIn("https", note)
        self.assertIn("--https", note)
        page.click("#camera-start")
        self.assertIn("not available on this http:// address", page.inner_text("#camera-status"))
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390)

    def test_permission_denied_message(self):
        deny = """
        navigator.mediaDevices.getUserMedia = () => Promise.reject(Object.assign(new Error('denied'), {name: 'NotAllowedError'}));
        """
        page = self.open(init_script=deny)
        page.click("#tab-camera")
        page.click("#camera-start")
        self.wait_js(page, "document.querySelector('#camera-status').textContent.includes('permission')")
        self.assertIn("Allow the camera for this site", page.inner_text("#camera-status"))
        self.assertTrue(page.is_visible("#camera-start"))

    def test_phone_layout_has_no_overflow_and_large_controls(self):
        page = self.open(width=390, height=844, mobile=True)
        page.click("#tab-camera")
        page.click("#camera-start")
        page.wait_for_selector("#record-start:not(.hidden)", timeout=15000)
        page.click("#record-start")
        page.wait_for_timeout(800)
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390)
        for selector in ("#record-stop", "#record-pause"):
            box = page.locator(selector).bounding_box()
            self.assertGreaterEqual(box["height"], 44, selector)
        page.click("#record-stop")
        page.wait_for_selector("#record-retake:not(.hidden)", timeout=15000)


if __name__ == "__main__":
    unittest.main()
