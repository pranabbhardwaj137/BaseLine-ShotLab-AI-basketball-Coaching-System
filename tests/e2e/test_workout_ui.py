"""Browser tests for the workout player (web/workout.js) with a controlled clock and a fake speech engine.

* Time: Playwright's clock API drives setInterval/performance.now, so a 30-second set takes milliseconds.
* Voice: ``speechSynthesis`` is replaced by a recorder; these tests check WHAT would be spoken and WHEN,
  not real audio output (real-device audio is a manual check).
* Video: the container's Chromium has no H.264 decoder, so this test writes small synthetic VP9 clips
  (ffmpeg test pattern) under the catalog's file names in a temporary folder. They exercise the
  loop / pause-on-rest logic only; the real H.264 library must be checked in Safari or Chrome.

Skipped when Playwright/Chromium or ffmpeg is unavailable.
"""

import json
import math
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

import basketball.app.web_app as web_app
import basketball.workout.catalog as wc
from basketball.persistence.shot_lab_db import ShotLabDB

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - optional dependency
    sync_playwright = None

FIXTURE = Path(__file__).resolve().parents[1] / "support" / "workout_report_fixture.json"

FAKE_SPEECH = """
window.__spoken = [];
class FakeUtterance { constructor(text) { this.text = text; } }
window.SpeechSynthesisUtterance = FakeUtterance;
Object.defineProperty(window, 'speechSynthesis', {configurable: true, value: {
  speak(u) { window.__spoken.push(u.text); },
  cancel() { window.__spoken.push('<cancel>'); },
  getVoices() { return []; }, speaking: false, pending: false }});
"""


@unittest.skipIf(sync_playwright is None, "playwright is not installed")
@unittest.skipIf(shutil.which("ffmpeg") is None, "ffmpeg is needed to write the synthetic VP9 test clips")
class WorkoutPlayerUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="shotlab_workout_ui_"))
        clip = cls.tmp / "synthetic_vp9.webm"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x200:rate=15:duration=2",
                        "-c:v", "libvpx-vp9", "-b:v", "100k", "-an", "-y", str(clip)],
                       check=True, stdin=subprocess.DEVNULL, timeout=120)
        catalog = wc.load_catalog()
        cls.workout_dir = cls.tmp / "workout"
        for exercise in catalog["exercises"]:
            if exercise.get("video"):
                target = cls.workout_dir / exercise["video"]
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(clip, target)  # synthetic VP9 stand-in under the real .mp4 name
        db_path = str(cls.tmp / "ui.db")
        cls.session_id = ShotLabDB(db_path).create_session(
            player_id="workout_ui_player", camera_view="side_90", shot_type="catch_and_shoot",
            shot_style="jump_shot", fps=30.0, model_version="test", notes=json.dumps({"skill_level": "beginner"}))
        report = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.patch = mock.patch.object(web_app, "build_session_report",
                                      side_effect=lambda server, sid, force=False: dict(report, meta=dict(report["meta"], session_id=sid)))
        cls.patch.start()
        server = web_app.LocalAppServer(("127.0.0.1", 0), web_app.AppHandler)
        server.db_path = db_path
        for name in ("upload_dir", "pose_cache_dir", "keyframe_dir"):
            folder = cls.tmp / name
            folder.mkdir()
            setattr(server, name, folder)
        server.job_store = web_app.JobStore(db_path + ".web_jobs.sqlite3", upload_root=server.upload_dir)
        server.executor = ThreadPoolExecutor(max_workers=1)
        server.worker_slots = threading.BoundedSemaphore(2)
        server.session_locks = {}
        server.llm_chat_enabled = False
        server.llm_model = "x"
        server.workout_dir = cls.workout_dir
        cls.server = server
        threading.Thread(target=server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            cls.pw = sync_playwright().start()
            cls.browser = cls.pw.chromium.launch()
        except Exception as exc:  # browser binary missing
            cls.server.shutdown()
            cls.patch.stop()
            raise unittest.SkipTest(f"Chromium for Playwright is not available: {exc}")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.server.executor.shutdown(wait=True)
        cls.patch.stop()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ------------------------------------------------------------------ helpers
    def create_workout(self, **prefs):
        body = {"equipment": ["bodyweight"], "fitness_level": "beginner", "duration_min": 20}
        body.update(prefs)
        req = urllib.request.Request(f"{self.base}/api/sessions/{self.session_id}/workouts",
                                     data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "X-Shotlab": "1"})
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.loads(response.read())

    def get_workout(self, workout_id):
        with urllib.request.urlopen(f"{self.base}/api/workouts/{workout_id}", timeout=60) as response:
            return json.loads(response.read())

    def open_page(self, workout, width=1280, height=900, mobile=False):
        ctx = self.browser.new_context(viewport={"width": width, "height": height}, is_mobile=mobile,
                                       has_touch=mobile, reduced_motion="reduce")
        ctx.add_init_script(FAKE_SPEECH)
        page = ctx.new_page()
        self.errors = []
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.clock.install()
        page.goto(self.base + "/#new")
        page.evaluate("""([wid, sid]) => {
            localStorage.setItem('shotLabWorkoutSession', sid);
            localStorage.setItem('shotLabActiveWorkout', JSON.stringify({workout_id: wid, session_id: sid}));
        }""", [workout["workout_id"], self.session_id])
        page.goto(self.base + "/#workout")
        page.wait_for_selector("#wk-start", timeout=30000)
        self.addCleanup(ctx.close)
        return page

    @staticmethod
    def spoken(page):
        return [t for t in page.evaluate("window.__spoken") if t != "<cancel>"]

    @staticmethod
    def state(page):
        return page.evaluate("window.ShotLabWorkout._player().state")

    @staticmethod
    def item(page):
        return page.evaluate("(() => { const p = window.ShotLabWorkout._player(); return p.items[p.state.index]; })()")

    @staticmethod
    def video(page):
        return page.evaluate("""(() => { const v = document.querySelector('.wk-video');
            return v ? {paused: v.paused, loop: v.loop, muted: v.muted, ready: v.readyState, src: v.currentSrc} : null; })()""")

    def advance(self, page, ms):
        page.clock.run_for(int(ms))

    # ------------------------------------------------------------------ tests
    def test_spoken_count_rule_in_browser(self):
        page = self.open_page(self.create_workout())
        for n, expected in {50: 5, 40: 4, 30: 3, 20: 2, 10: 1, 5: 1, 1: 1}.items():
            self.assertEqual(page.evaluate(f"window.ShotLabWorkout.spokenCount({n})"), expected, n)

    def test_timed_set_voice_rest_pause_reload_mute_and_end_early(self):
        workout = self.create_workout()
        page = self.open_page(workout)
        page.click("#wk-start")
        self.advance(page, 200)
        first = self.item(page)
        self.assertEqual(first["mode"], "time", "first warm-up item is expected to be timed")
        total = first["target"] * (2 if first["per_side"] else 1)
        n_spoken = max(1, math.ceil(total * 0.10))
        self.assertEqual(self.spoken(page), [first["name"]], "exercise name is announced once at the start")

        # Video loops, muted, during work.
        page.wait_for_function("document.querySelector('.wk-video') && document.querySelector('.wk-video').readyState >= 2",
                               timeout=15000)
        video = self.video(page)
        self.assertTrue(video["loop"] and video["muted"])
        self.assertFalse(video["paused"])
        self.assertIn("/api/workout-media/", video["src"])

        # Nothing is spoken during the first 90% of the count.
        self.advance(page, (total - n_spoken) * 1000 - 400)
        self.assertEqual(self.spoken(page), [first["name"]])
        # The final 10% is spoken, descending, once each.
        self.advance(page, n_spoken * 1000 + 300)
        self.assertEqual(self.spoken(page), [first["name"]] + [str(n) for n in range(n_spoken, 0, -1)])

        # Rest: silent, video paused, Add 15 s and Skip Rest work.
        state = self.state(page)
        self.assertEqual(state["phase"], "rest")
        self.assertTrue(self.video(page)["paused"], "demonstration pauses during rest")
        before = len(self.spoken(page))
        remaining = state["remaining_ms"]
        page.click("#wk-add-rest")
        self.assertAlmostEqual(self.state(page)["remaining_ms"], remaining + 15000, delta=300)
        self.advance(page, 5000)
        self.assertEqual(len(self.spoken(page)), before, "rest is silent")
        page.click("#wk-skip-rest")
        self.advance(page, 200)
        second = self.item(page)
        self.assertEqual(self.state(page)["phase"], "work")
        self.assertEqual(self.spoken(page)[-1], second["name"])
        if second["media_url"]:
            self.assertFalse(self.video(page)["paused"], "video plays again for the next exercise")
        else:  # text-only exercise: the written guide replaces the video
            self.assertTrue(page.is_visible(".wk-noguide"))
            self.assertIsNone(self.video(page))

        # Pause cancels speech and freezes the timer; resume does not repeat anything.
        self.advance(page, 2000)
        page.evaluate("window.__spoken = []")
        page.click("#wk-pause")
        self.assertIn("<cancel>", page.evaluate("window.__spoken"))
        frozen = self.state(page)
        self.advance(page, 10000)
        after = self.state(page)
        for key in ("remaining_ms", "count", "elapsed_ms", "index", "set"):
            self.assertEqual(after[key], frozen[key], key)
        if second["media_url"]:
            self.assertTrue(self.video(page)["paused"])

        # Reload: restored paused at the same step; the name is not announced again.
        page.wait_for_timeout(300)  # let the pause save reach the server
        page.reload()
        page.wait_for_selector("#wk-resume", timeout=30000)
        restored = self.state(page)
        self.assertTrue(restored["paused"])
        self.assertEqual(restored["index"], frozen["index"])
        self.assertIn(second["uid"], restored["announced"])
        page.click("#wk-resume")
        self.advance(page, 500)
        self.assertNotIn(second["name"], self.spoken(page), "no re-announcement after reload")

        # Mute: the rest of this set produces no numbers.
        page.click(".wk-voice")
        self.assertFalse(self.state(page)["voice"])
        page.evaluate("window.__spoken = []")
        current = self.item(page)
        set_ms = (current["work_s"] + 2) * 1000
        self.advance(page, set_ms)
        self.assertEqual(self.spoken(page), [], "muted voice speaks nothing")

        # End early: honest summary.
        page.click("#wk-end")
        page.click("#dialog-confirm")
        page.wait_for_selector("#wk-save-summary", timeout=15000)
        page.click("label:has-text('Too hard')")
        page.click("#wk-save-summary")
        page.wait_for_selector(".wk-summary-stats", timeout=15000)
        record = self.get_workout(workout["workout_id"])
        self.assertEqual(record["status"], "ended_early")
        summary = record["summary"]
        statuses = [e["status"] for e in summary["exercises"]]
        self.assertEqual(statuses[0], "completed")
        self.assertEqual(statuses[-1], "not_reached")
        self.assertLess(summary["counts"]["completed"], len(statuses))
        self.assertIsNone(page.evaluate("localStorage.getItem('shotLabActiveWorkout')"))
        self.assertEqual(self.errors, [])

    def test_rep_set_speaks_only_the_final_ten_percent(self):
        page = self.open_page(self.create_workout())
        page.click("#wk-start")
        self.advance(page, 200)
        for _ in range(30):
            if self.item(page)["mode"] == "reps":
                break
            page.click("#wk-skip-ex")
            self.advance(page, 100)
        item = self.item(page)
        self.assertEqual(item["mode"], "reps", "plan has no repetition exercise")
        self.assertEqual(self.spoken(page)[-1], item["name"])
        if item["media_url"]:
            page.wait_for_function("document.querySelector('.wk-video')?.readyState >= 2", timeout=15000)
            self.assertFalse(self.video(page)["paused"])
        page.evaluate("window.__spoken = []")
        total = item["target"] * (2 if item["per_side"] else 1)
        n_spoken = max(1, math.ceil(total * 0.10))
        rep_ms = item["cadence_s"] * 1000
        self.advance(page, rep_ms * (total - n_spoken) - 300)
        self.assertEqual(self.spoken(page), [], "no numbers in the first 90% of the repetitions")
        self.advance(page, rep_ms * n_spoken + 400)
        self.assertEqual(self.spoken(page), [str(n) for n in range(n_spoken, 0, -1)])
        self.assertEqual(self.state(page)["phase"], "rest" if item["sets"] > 1 or item["rest_after_s"] else "work")

    def test_mobile_player_has_no_horizontal_overflow(self):
        page = self.open_page(self.create_workout(), width=390, height=844, mobile=True)
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390)
        page.click("#wk-start")
        self.advance(page, 500)
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390)
        for selector in ("#wk-pause", "#wk-set-done", "#wk-skip-ex", "#wk-end"):
            box = page.locator(selector).bounding_box()
            self.assertIsNotNone(box, selector)
            self.assertGreaterEqual(box["height"], 40, f"{selector} touch target")


if __name__ == "__main__":
    unittest.main()
