"""Browser tests for the workout player (web/workout.js) with a controlled clock and a fake speech engine.

* Time: Playwright's clock API drives setInterval/performance.now, so a 30-second set takes milliseconds.
* Voice: ``speechSynthesis`` is replaced by a recorder; these tests check WHAT would be spoken and WHEN,
  not real audio output (real-device audio is a manual check). Rules under test: the exercise name
  once; every repetition counted down aloud in step with the counter; a short countdown for timed
  sets; rest announced once at its start and once at its end, never counted aloud.
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
import time
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

# Records every utterance; "finishes" each one 300 ms later (on the page's controlled clock), like a real engine.
FAKE_SPEECH = """
window.__spoken = [];
class FakeUtterance { constructor(text) { this.text = text; this.onend = null; this.onerror = null; } }
window.SpeechSynthesisUtterance = FakeUtterance;
Object.defineProperty(window, 'speechSynthesis', {configurable: true, value: {
  speak(u) { window.__spoken.push(u.text); setTimeout(() => u.onend && u.onend(), 300); },
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
    def clear_spoken(page):
        page.evaluate("window.__spoken = []")

    @staticmethod
    def state(page):
        return page.evaluate("window.ShotLabWorkout._player().state")

    @staticmethod
    def item(page):
        return page.evaluate("(() => { const p = window.ShotLabWorkout._player(); return p.items[p.state.index]; })()")

    @staticmethod
    def video(page):
        return page.evaluate("""(() => { const v = document.querySelector('.wk-video');
            return v && v.isConnected ? {paused: v.paused, loop: v.loop, muted: v.muted, ready: v.readyState, src: v.currentSrc} : null; })()""")

    def advance(self, page, ms):
        page.clock.run_for(int(ms))

    def timed_cues(self, page, item):
        total = item["target"] * (2 if item["per_side"] else 1)
        return page.evaluate("([t, s]) => window.ShotLabWorkout.timedCues(t, s)", [total, item["per_side"]])

    def skip_to(self, page, predicate, limit=40):
        for _ in range(limit):
            if predicate(self.item(page)):
                return self.item(page)
            page.click("#wk-skip-ex")
            self.advance(page, 100)
        self.fail("no plan step matches")

    # ------------------------------------------------------------------ tests
    def test_cue_rules_in_browser(self):
        page = self.open_page(self.create_workout())
        cue = lambda target, per_side, k: page.evaluate(
            "([t, s, k]) => window.ShotLabWorkout.repCue({target: t, per_side: s}, k)", [target, per_side, k])
        self.assertEqual([cue(10, False, k) for k in range(1, 11)], [str(n) for n in range(10, 0, -1)])
        self.assertEqual([cue(3, True, k) for k in range(1, 7)], ["3", "2", "1", "Switch sides. 3", "2", "1"])
        texts = lambda total, per_side: [c["text"] for c in page.evaluate(
            "([t, s]) => window.ShotLabWorkout.timedCues(t, s)", [total, per_side])]
        self.assertEqual(texts(45, False), ["45 seconds", "30 seconds", "20 seconds", "10 seconds", "5", "4", "3", "2", "1"])
        self.assertEqual(texts(30, True), ["30 seconds", "20 seconds", "Switch sides", "10 seconds", "5", "4", "3", "2", "1"])
        self.assertEqual(texts(4, False), ["4 seconds", "3", "2", "1"])
        dur = lambda s: page.evaluate(f"window.ShotLabWorkout.spokenDuration({s})")
        self.assertEqual([dur(30), dur(75), dur(60), dur(120), dur(150)],
                         ["30 seconds", "75 seconds", "1 minute", "2 minutes", "2 minutes 30 seconds"])

    def test_timed_set_countdown_rest_announcements_pause_and_add_time(self):
        workout = self.create_workout()
        page = self.open_page(workout)
        page.click("#wk-start")
        self.advance(page, 100)
        first = self.item(page)
        self.assertEqual(first["mode"], "time", "first warm-up item is expected to be timed")
        total = first["target"] * (2 if first["per_side"] else 1)
        cues = self.timed_cues(page, first)
        # Name once, then the opening cue ("45 seconds"), queued after it.
        self.advance(page, 400)
        self.assertEqual(self.spoken(page), [first["name"], cues[0]["text"]])
        deadline = time.time() + 15   # polled from Python: the app's CSP forbids the eval Playwright's polling uses
        while not page.evaluate("document.querySelector('.wk-video')?.readyState >= 2") and time.time() < deadline:
            time.sleep(0.1)
        self.assertFalse(self.video(page)["paused"])
        self.assertTrue(self.video(page)["loop"] and self.video(page)["muted"])

        # Pause half-way: speech is cancelled and time stands still; resume repeats nothing.
        self.advance(page, (total / 2) * 1000)
        page.click("#wk-pause")
        self.assertEqual(page.evaluate("window.__spoken.at(-1)"), "<cancel>")
        frozen = self.state(page)
        heard = list(self.spoken(page))
        self.advance(page, 8000)
        self.assertEqual(self.state(page)["remaining_ms"], frozen["remaining_ms"])
        self.assertEqual(self.spoken(page), heard)
        page.click("#wk-resume")
        self.advance(page, 200)
        self.assertEqual(self.spoken(page), heard, "resume must not repeat a cue")

        # Visual countdown matches the voice for the final seconds.
        remaining_s = self.state(page)["remaining_ms"] / 1000
        self.advance(page, (remaining_s - 3) * 1000 + 50)   # just past the "3" cue
        self.assertEqual(page.inner_text(".wk-counter"), "0:03")
        self.assertEqual(self.spoken(page)[-1], "3")

        # Finish the set: every cue was said exactly once, in order.
        self.advance(page, 3200)
        said = self.spoken(page)
        self.assertEqual(said[:2], [first["name"], cues[0]["text"]])
        self.assertEqual([t for t in said[1:] if t in {c["text"] for c in cues}], [c["text"] for c in cues])

        # Rest: announced once with the real duration; silent afterwards; video paused.
        state = self.state(page)
        self.assertEqual(state["phase"], "rest")
        rest_s = state["rest_total_ms"] // 1000
        expected_rest = page.evaluate(f"window.ShotLabWorkout.spokenDuration({rest_s})")
        self.assertEqual(self.spoken(page)[-1], f"Rest for {expected_rest}")
        video = self.video(page)
        if video is not None:   # demonstration is paused (not playing) during rest
            self.assertTrue(video["paused"])
        self.clear_spoken(page)
        page.click("#wk-add-rest")
        self.assertAlmostEqual(self.state(page)["remaining_ms"], state["remaining_ms"] + 15000, delta=300)
        self.advance(page, (rest_s + 15) * 1000 - 1500)
        self.assertEqual(self.spoken(page), [], "the rest countdown is never spoken")
        self.assertEqual(self.state(page)["phase"], "rest")
        self.assertRegex(page.inner_text(".wk-counter"), r"^0:0[12]$")
        # Rest ends: one announcement naming the next exercise; its name is not said again.
        self.advance(page, 2000)
        nxt = self.item(page)
        said = self.spoken(page)
        self.assertEqual(said[0], f"Rest complete. Next exercise: {nxt['name']}.")
        self.assertEqual(said.count(nxt["name"]), 0)
        self.assertEqual(self.state(page)["phase"], "work")
        self.assertEqual(self.errors, [])

    def test_every_rep_is_counted_down_in_step_with_the_counter(self):
        page = self.open_page(self.create_workout())
        page.click("#wk-start")
        self.advance(page, 100)
        item = self.skip_to(page, lambda i: i["mode"] == "reps" and i["sets"] > 1)
        total = item["target"] * (2 if item["per_side"] else 1)
        rep_ms = item["cadence_s"] * 1000
        expected = [page.evaluate("([t, s, k]) => window.ShotLabWorkout.repCue({target: t, per_side: s}, k)",
                                  [item["target"], item["per_side"], k]) for k in range(1, total + 1)]
        self.advance(page, 400)   # the first number is queued behind the name
        said = self.spoken(page)
        self.assertEqual(said[-2:], [item["name"], expected[0]], "name, then the first number")
        # Each repetition: the counter shows the number that was just spoken.
        for k in range(1, total):
            if k == total // 2:   # pause in the middle of a repetition: nothing repeats after resuming
                page.click("#wk-pause")
                self.advance(page, 5000)
                page.click("#wk-resume")
            self.advance(page, rep_ms)
            last = self.spoken(page)[-1]
            self.assertEqual(last, expected[k])
            self.assertEqual(page.inner_text(".wk-counter"), last.split(". ")[-1])
        counts = [t for t in self.spoken(page) if t in set(expected)]
        self.assertEqual(counts[-total:], expected, "each number once, descending")
        # Set ends → rest between sets is announced; then "Next set" at the end.
        self.advance(page, rep_ms + 100)
        state = self.state(page)
        self.assertEqual(state["phase"], "rest")
        self.assertEqual(state["rest_kind"], "set")
        self.assertTrue(self.spoken(page)[-1].startswith("Rest for "))
        self.clear_spoken(page)
        page.click("#wk-skip-rest")
        self.advance(page, 400)
        self.assertEqual(self.spoken(page)[:2],
                         [f"Rest skipped. Next set: {item['name']}, set 2 of {item['sets']}.", expected[0]])
        # Mute: the count continues on screen only.
        page.click(".wk-voice")
        self.clear_spoken(page)
        self.advance(page, rep_ms * 3)
        self.assertEqual(self.spoken(page), [])
        self.assertEqual(self.state(page)["count"], 3)
        self.assertEqual(self.errors, [])

    def test_reload_during_rest_keeps_announcements_single(self):
        workout = self.create_workout()
        page = self.open_page(workout)
        page.click("#wk-start")
        self.advance(page, 100)
        first = self.item(page)
        self.advance(page, (first["work_s"] + 1) * 1000)
        self.assertEqual(self.state(page)["phase"], "rest")
        self.assertTrue(self.state(page)["rest_announced"])
        page.click("#wk-pause")
        page.wait_for_timeout(300)
        page.reload()
        page.wait_for_selector("#wk-resume", timeout=30000)
        restored = self.state(page)
        self.assertEqual(restored["phase"], "rest")
        self.assertTrue(restored["paused"])
        page.click("#wk-resume")
        self.advance(page, restored["remaining_ms"] + 500)
        said = self.spoken(page)
        self.assertFalse(any(t.startswith("Rest for") for t in said), "rest start is not re-announced after reload")
        self.assertEqual(sum(1 for t in said if t.startswith("Rest complete.")), 1)

    def test_end_early_gives_an_honest_summary(self):
        workout = self.create_workout()
        page = self.open_page(workout)
        page.click("#wk-start")
        self.advance(page, 100)
        first = self.item(page)
        self.advance(page, (first["work_s"] + 1) * 1000)
        page.click("#wk-end")
        page.click("#dialog-confirm")
        page.wait_for_selector("#wk-save-summary", timeout=15000)
        page.click("label:has-text('Too hard')")
        page.click("#wk-save-summary")
        page.wait_for_selector(".wk-summary-stats", timeout=15000)
        record = self.get_workout(workout["workout_id"])
        self.assertEqual(record["status"], "ended_early")
        statuses = [e["status"] for e in record["summary"]["exercises"]]
        self.assertEqual(statuses[0], "completed")
        self.assertEqual(statuses[-1], "not_reached")
        self.assertIsNone(page.evaluate("localStorage.getItem('shotLabActiveWorkout')"))

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
