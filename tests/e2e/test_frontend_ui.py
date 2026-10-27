"""Browser tests for the player UI (web/). Drives a real Chromium against the real server.

Uses a SYNTHETIC blank clip (no person), so analysis proposes no attempts; the test then
adds one manually, as a player would for a missed shot. Skipped when Playwright or its
Chromium build is not installed:  pip install playwright && python -m playwright install chromium
"""

import shutil
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import basketball.app.web_app as web_app
try:
    from tests.e2e.test_web_app import _write_synthetic_clip
except ImportError:
    from test_web_app import _write_synthetic_clip

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - optional dependency
    sync_playwright = None


@unittest.skipIf(sync_playwright is None, "playwright is not installed")
class FrontendUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="shotlab_ui_test_"))
        server = web_app.LocalAppServer(("127.0.0.1", 0), web_app.AppHandler)
        server.db_path = str(cls.tmp / "ui.db")
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
        cls.base = f"http://127.0.0.1:{server.server_address[1]}"
        cls.clip = cls.tmp / "synthetic_ui_clip.mp4"
        _write_synthetic_clip(cls.clip, frames=30, size=(320, 240), fps=10)
        cls.bad = cls.tmp / "notes.txt"
        cls.bad.write_text("not a video")
        try:
            cls.pw = sync_playwright().start()
            cls.browser = cls.pw.chromium.launch()
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

    def new_page(self, **context):
        ctx = self.browser.new_context(**context)
        page = ctx.new_page()
        page.errors = []
        page.on("pageerror", lambda exc: page.errors.append(str(exc)))
        return page

    def test_full_player_journey(self):
        page = self.new_page(viewport={"width": 1280, "height": 900})
        page.goto(self.base + "/#new")
        page.fill("input[name=player_id]", "ui_player")
        page.check("input[name=pain_reported]")
        page.set_input_files("#video-file", str(self.clip))
        self.assertIn("ready to analyze", page.inner_text("#file-caption"))
        page.click("#submit-button")
        page.wait_for_selector("text=Session ready to review", timeout=120000)
        self.assertEqual(page.evaluate("location.hash"), "#review")
        self.assertIn("0", page.inner_text(".stat-row"))
        self.assertIn("No attempts passed the shot detector", page.inner_text(".review-editor"))

        # Add the attempt the detector missed, using frame numbers.
        page.click("text=Add an attempt the detector missed")
        inputs = page.locator(".manual-grid input")
        inputs.nth(0).fill("2")
        inputs.nth(1).fill("10")
        inputs.nth(2).fill("20")
        page.click("text=Add attempt")
        page.wait_for_selector(".attempt", timeout=30000)
        self.assertIn("Added by you", page.inner_text(".attempt-list"))
        page.wait_for_selector(".coach-card .coach-summary-text, .coach-card .abstain", timeout=60000)

        page.click(".report-card >> text=Open full report")
        page.wait_for_selector("#report-method", timeout=60000)
        self.assertEqual(page.locator(".report-section").count(), 10)
        injury = page.inner_text("#report-injury")
        self.assertIn("Technique, Load Management, and Injury-Risk Reduction", injury)
        self.assertIn("You told us you have pain", injury)
        self.assertFalse(page.is_disabled("#report-print"))

        page.emulate_media(media="print")
        self.assertFalse(page.is_visible(".topbar"))
        self.assertFalse(page.is_visible(".report-toolbar"))
        self.assertTrue(page.is_visible("#report-overview"))
        page.emulate_media(media="screen")

        page.click("[data-nav=progress]")
        page.wait_for_selector(".session-item", timeout=30000)
        self.assertIn("Report", page.inner_text(".session-item"))
        self.assertEqual(page.errors, [])

    def test_phone_width_and_error_state(self):
        page = self.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        page.goto(self.base + "/#new")
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390)
        page.set_input_files("#video-file", str(self.bad))
        page.click("#submit-button")
        page.wait_for_selector("#job-error:not(.hidden)", timeout=30000)
        self.assertIn("Supported video formats", page.inner_text("#job-error"))
        page.goto(self.base + "/#report")
        self.assertTrue(page.is_visible("#report-empty"))
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390)
        self.assertEqual(page.errors, [])

    def test_phone_panel_shown_on_the_computer(self):
        page = self.new_page(viewport={"width": 1280, "height": 900})
        page.goto(self.base + "/#new")
        page.wait_for_selector("#phone-card:not(.hidden)", timeout=10000)
        self.assertIn("--lan", page.inner_text("#phone-card"))


if __name__ == "__main__":
    unittest.main()
