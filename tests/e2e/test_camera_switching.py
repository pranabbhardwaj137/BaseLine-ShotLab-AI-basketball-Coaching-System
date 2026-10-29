"""Front/rear camera switching (web/app.js) with a scripted camera (tests/support/fake_camera.js).

The fake replaces ``navigator.mediaDevices`` with canvas-backed streams so we control what each
"phone" does: iPhone-style (several rear lenses; opening a camera ends the previous one),
Android-style (only one camera may be open), browsers that reject ``facingMode: {exact}``, devices
without a front camera, and permission refusal. Real iPhone/Android behaviour still needs a manual
check on the devices themselves.
"""

import shutil
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import basketball.app.web_app as web_app

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - optional dependency
    sync_playwright = None

FAKE_CAMERA = (Path(__file__).resolve().parents[1] / "support" / "fake_camera.js").read_text(encoding="utf-8")
IPHONE = "{exclusive: false, steal: true}"
ANDROID = "{exclusive: true}"
NO_EXACT = "{exclusive: true, exactFacing: false}"
REAR_ONLY = """{exclusive: true, devices: [
  {deviceId: 'back-1', label: 'Back Camera', facing: 'environment'},
  {deviceId: 'back-2', label: 'Back Ultra Wide Camera', facing: 'environment'}]}"""
ONE_CAMERA = "{exclusive: true, devices: [{deviceId: 'cam', label: 'Integrated Webcam', facing: 'user'}]}"

PREVIEW = """(() => {
  const s = document.querySelector('#camera-preview').srcObject;
  const t = s && s.getVideoTracks()[0];
  return t ? {label: t.__dev && t.__dev.label, facing: t.__dev && t.__dev.facing, state: t.readyState,
              live: window.__cam.live.length} : null;
})()"""


@unittest.skipIf(sync_playwright is None, "playwright is not installed")
class CameraSwitchingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="shotlab_camswitch_"))
        server = web_app.LocalAppServer(("127.0.0.1", 0), web_app.AppHandler)
        server.db_path = str(cls.tmp / "cam.db")
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
        cls.server = server
        threading.Thread(target=server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{server.server_address[1]}"   # localhost is a secure context
        try:
            cls.pw = sync_playwright().start()
            cls.browser = cls.pw.chromium.launch(args=["--no-proxy-server"])
        except Exception as exc:  # pragma: no cover - browser binary missing
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

    def open(self, config):
        ctx = self.browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        ctx.add_init_script(f"window.__fakeCamConfig = {config};")
        ctx.add_init_script(FAKE_CAMERA)
        page = ctx.new_page()
        self.errors = []
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.goto(self.base + "/#new")
        page.click("#tab-camera")
        page.click("#camera-start")
        page.wait_for_selector("#record-start:not(.hidden)", timeout=15000)
        self.addCleanup(ctx.close)
        return page

    def switch(self, page):
        page.click("#camera-switch")
        page.wait_for_selector("#camera-switch:not(.hidden):not([disabled])", timeout=15000)
        return page.evaluate(PREVIEW)

    def assert_single_live(self, page, preview):
        self.assertEqual(preview["state"], "live")
        self.assertEqual(preview["live"], 1, "exactly one camera open; the previous one was released")

    # ------------------------------------------------------------------ tests
    def test_iphone_style_switches_front_and_back_not_other_rear_lenses(self):
        page = self.open(IPHONE)
        self.assertEqual(page.evaluate(PREVIEW)["label"], "Back Camera")
        self.assertEqual(page.inner_text("#camera-switch"), "Use front camera")
        for expected in ("Front Camera", "Back Camera", "Front Camera"):
            preview = self.switch(page)
            self.assertEqual(preview["label"], expected)
            self.assert_single_live(page, preview)
        self.assertIn("front camera", page.inner_text("#camera-status"))
        self.assertEqual(page.inner_text("#camera-switch"), "Use rear camera")
        self.assertEqual(self.errors, [])

    def test_android_style_releases_the_old_camera_before_opening_the_other(self):
        page = self.open(ANDROID)
        preview = self.switch(page)
        self.assertEqual(preview["facing"], "user")
        self.assert_single_live(page, preview)
        preview = self.switch(page)
        self.assertEqual(preview["facing"], "environment")
        self.assert_single_live(page, preview)
        self.assertNotIn("busy", page.inner_text("#camera-status"))
        calls = page.evaluate("window.__cam.calls")
        self.assertEqual(calls[1]["video"]["facingMode"], {"exact": "user"}, "front camera requested with facingMode")

    def test_falls_back_to_device_labels_when_exact_facing_is_rejected(self):
        page = self.open(NO_EXACT)
        preview = self.switch(page)
        self.assertEqual(preview["label"], "Front Camera")
        self.assert_single_live(page, preview)
        calls = page.evaluate("window.__cam.calls")
        self.assertTrue(any(c["video"].get("deviceId") == {"exact": "front-1"} for c in calls if isinstance(c["video"], dict)))

    def test_missing_front_camera_is_reported_and_rear_camera_kept(self):
        page = self.open(REAR_ONLY)
        preview = self.switch(page)
        self.assertEqual(preview["facing"], "environment")
        self.assert_single_live(page, preview)
        status = page.inner_text("#camera-status")
        self.assertIn("Could not switch to the front camera", status)
        self.assertIn("no front camera was found", status)

    def test_single_camera_hides_the_switch(self):
        page = self.open(ONE_CAMERA)
        self.assertFalse(page.is_visible("#camera-switch"))

    def test_permission_denied_while_switching_is_explained(self):
        page = self.open(ANDROID)
        page.evaluate("window.__cam.deny = true")
        page.click("#camera-switch")
        page.wait_for_selector("#camera-start:not(.hidden)", timeout=15000)
        status = page.inner_text("#camera-status")
        self.assertIn("permission was denied", status)
        self.assertEqual(page.evaluate("window.__cam.live.length"), 0, "no camera left running")

    def test_switching_with_recording_stop_and_retake(self):
        page = self.open(ANDROID)
        self.switch(page)                                  # front camera, before recording
        page.click("#record-start")
        page.wait_for_timeout(300)
        self.assertFalse(page.is_visible("#camera-switch"), "no switching in the middle of a clip")
        page.wait_for_timeout(1500)
        page.click("#record-stop")
        page.wait_for_selector("#record-retake:not(.hidden)", timeout=15000)
        self.assertIn("Recording ready", page.inner_text("#camera-status"))
        page.click("#record-retake")
        page.wait_for_selector("#record-start:not(.hidden)", timeout=15000)
        preview = self.switch(page)                        # after retake: back to the rear camera
        self.assertEqual(preview["facing"], "environment")
        self.assert_single_live(page, preview)
        page.click("#record-start")
        page.wait_for_timeout(1500)
        page.click("#record-stop")
        page.wait_for_selector("#record-retake:not(.hidden)", timeout=15000)
        size = page.evaluate("document.querySelector('#camera-review').src ? 1 : 0")
        self.assertEqual(size, 1)
        page.click("#camera-stop")
        self.assertEqual(page.evaluate("window.__cam.live.length"), 0, "turning the camera off releases it")
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
