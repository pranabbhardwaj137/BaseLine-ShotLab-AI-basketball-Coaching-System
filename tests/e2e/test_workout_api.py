"""HTTP tests for the workout coach routes: context, plan creation, progress, summary and safe media.

The shooting report is the committed fixture ``tests/support/workout_report_fixture.json`` (a report
produced by this app from a project test clip, trimmed to the fields the planner reads); the report
builder is patched to return it so the test does not depend on pose models or video analysis.
"""

import json
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

import basketball.app.web_app as web_app
import basketball.workout.catalog as wc
from basketball.persistence.shot_lab_db import ShotLabDB

FIXTURE = Path(__file__).resolve().parents[1] / "support" / "workout_report_fixture.json"


class WorkoutApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="shotlab_workout_api_"))
        cls.db_path = str(cls.tmp / "w.db")
        db = ShotLabDB(cls.db_path)
        cls.session_id = db.create_session(player_id="workout_test_player", camera_view="side_90",
                                           shot_type="catch_and_shoot", shot_style="jump_shot", fps=30.0,
                                           model_version="test", notes=json.dumps({"skill_level": "beginner"}))
        cls.other_session = db.create_session(player_id="workout_test_player", camera_view="side_90",
                                              shot_type="catch_and_shoot", shot_style="jump_shot", fps=30.0,
                                              model_version="test", notes="{}")
        report = json.loads(FIXTURE.read_text(encoding="utf-8"))

        def fake_report(server, session_id, force=False):
            data = json.loads(json.dumps(report))
            data["meta"]["session_id"] = session_id
            return data

        cls.patch = mock.patch.object(web_app, "build_session_report", side_effect=fake_report)
        cls.patch.start()
        # A temporary workout folder with placeholder bytes under every mapped file name (enough for Range
        # tests), except one file deliberately left out to test the "missing on disk" path.
        cls.catalog = wc.load_catalog()
        cls.workout_dir = cls.tmp / "workout"
        cls.video_bytes = bytes(range(256)) * 40
        cls.missing_id = "split_squat_bw"
        for exercise in cls.catalog["exercises"]:
            if exercise.get("video") and exercise["id"] != cls.missing_id:
                target = cls.workout_dir / exercise["video"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(cls.video_bytes)
        (cls.tmp / "secret.mp4").write_bytes(b"secret")

        server = web_app.LocalAppServer(("127.0.0.1", 0), web_app.AppHandler)
        server.db_path = cls.db_path
        server.upload_dir = str(cls.tmp / "up")
        server.pose_cache_dir = str(cls.tmp / "pc")
        server.keyframe_dir = str(cls.tmp / "kf")
        server.job_store = web_app.JobStore(cls.db_path + ".web_jobs.sqlite3", upload_root=server.upload_dir)
        server.executor = ThreadPoolExecutor(max_workers=1)
        server.worker_slots = threading.BoundedSemaphore(2)
        server.session_locks = {}
        server.llm_chat_enabled = False
        server.llm_model = "test-model"
        server.workout_dir = cls.workout_dir
        cls.server = server
        cls.base = f"http://127.0.0.1:{server.server_address[1]}"
        cls.thread = threading.Thread(target=server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.server.executor.shutdown(wait=True)
        cls.patch.stop()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def request(self, method, path, body=None, headers=None, csrf=True):
        headers = dict(headers or {})
        if method in {"POST", "PUT", "DELETE"} and csrf:
            headers.setdefault("X-Shotlab", "1")
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                return response.status, response.read(), response.headers
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), exc.headers

    def json_request(self, method, path, body=None, **kw):
        status, raw, _ = self.request(method, path, body, **kw)
        try:
            return status, json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return status, {"raw": raw.decode("utf-8", "replace")}

    def create(self, session_id=None, **prefs):
        body = {"equipment": ["bodyweight"], "fitness_level": "beginner", "duration_min": 20}
        body.update(prefs)
        return self.json_request("POST", f"/api/sessions/{session_id or self.session_id}/workouts", body)

    # ------------------------------------------------------------------ tests
    def test_context_reflects_the_report(self):
        status, ctx = self.json_request("GET", f"/api/sessions/{self.session_id}/workout-context")
        self.assertEqual(status, 200)
        self.assertEqual({f["id"] for f in ctx["findings"]["improvements"]}, {"torso", "consistency", "landing"})
        self.assertIn("upper body moves a lot", ctx["summary"].lower())
        self.assertEqual(ctx["defaults"]["fitness_level"], "beginner")
        self.assertEqual(len(ctx["equipment"]), 9)
        self.assertTrue(ctx["video_library"]["folder_found"])
        self.assertNotIn(str(self.workout_dir), json.dumps(ctx))
        status, _ = self.json_request("GET", "/api/sessions/no_such_session/workout-context")
        self.assertEqual(status, 404)

    def test_create_validates_preferences(self):
        status, body = self.create(equipment=[])
        self.assertEqual(status, 400)
        self.assertIn("at least one", json.dumps(body))
        status, _ = self.create(duration_min=10)
        self.assertEqual(status, 400)
        status, _ = self.create(equipment=["../../etc"])
        self.assertEqual(status, 400)

    def test_choices_that_cannot_be_filled_with_video_exercises_are_refused(self):
        status, body = self.create(equipment=["barbell"], avoid=["ankle"])
        self.assertEqual(status, 422)
        self.assertIn("video-demonstrated", body["error"])
        status, body = self.create(duration_min=60, pain=True, avoid=["ankle", "floor", "wrist"])
        self.assertEqual(status, 422)
        self.assertIn("demonstration video", body["error"])
        self.assertIn("60 minutes", body["error"])

    def test_mutations_require_csrf_header(self):
        status, _ = self.json_request("POST", f"/api/sessions/{self.session_id}/workouts",
                                      {"equipment": ["bodyweight"]}, csrf=False)
        self.assertEqual(status, 403)

    def test_plan_lifecycle_progress_summary_and_lock(self):
        status, created = self.create(duration_min=25)
        self.assertEqual(status, 201)
        workout_id = created["workout_id"]
        plan = created["plan"]
        self.assertGreaterEqual(plan["duration"]["total_s"], 25 * 60)
        self.assertEqual(created["status"], "planned")
        # Video-demonstrated exercises only: every item has an id-based media url; a mapped exercise whose
        # file is missing on disk is never prescribed, and neither is any text-only exercise.
        for item in plan["items"]:
            self.assertEqual(item["media_url"], f"/api/workout-media/{item['exercise_id']}")
            self.assertTrue(self.catalog["_by_id"][item["exercise_id"]].get("video"))
            self.assertNotEqual(item["exercise_id"], self.missing_id)

        status, listing = self.json_request("GET", f"/api/sessions/{self.session_id}/workouts")
        self.assertEqual(status, 200)
        self.assertIn(workout_id, [w["workout_id"] for w in listing["workouts"]])

        first = plan["items"][0]
        state = {"index": 1, "set": 0, "phase": "rest", "remaining_ms": 20000, "rest_total_ms": 30000,
                 "announced": [first["uid"]], "paused": True}
        progress = {"items": {first["uid"]: {"sets": [{"status": "completed"}] * first["sets"]}}, "active_s": 90}
        status, saved = self.json_request("PUT", f"/api/workouts/{workout_id}/progress",
                                          {"status": "active", "state": state, "progress": progress})
        self.assertEqual(status, 200)
        self.assertEqual(saved["status"], "active")
        status, again = self.json_request("GET", f"/api/workouts/{workout_id}")
        self.assertEqual(again["state"]["announced"], [first["uid"]])
        self.assertEqual(again["state"]["phase"], "rest")
        self.assertTrue(again["started_at"])

        status, bad = self.json_request("PUT", f"/api/workouts/{workout_id}/progress",
                                        {"status": "active", "state": {"announced": ["s99-nope"]}})
        self.assertEqual(status, 400)

        state["phase"] = "done"
        state["ending"] = "ended_early"
        status, final = self.json_request("PUT", f"/api/workouts/{workout_id}/progress", {
            "status": "ended_early", "state": state, "progress": progress,
            "feedback": {"difficulty": "about_right", "felt_pain": False, "note": "ok"}})
        self.assertEqual(status, 200)
        summary = final["summary"]
        self.assertEqual(summary["status"], "ended_early")
        self.assertEqual(summary["counts"]["completed"], 1)
        self.assertEqual(summary["counts"]["not_reached"], len(plan["items"]) - 1)
        self.assertEqual(final["feedback"]["difficulty"], "about_right")
        self.assertTrue(final["ended_at"])

        status, _ = self.json_request("PUT", f"/api/workouts/{workout_id}/progress",
                                      {"status": "completed", "state": state, "progress": progress})
        self.assertEqual(status, 409, "a finished workout must not be rewritten")

        status, _ = self.json_request("DELETE", f"/api/workouts/{workout_id}")
        self.assertEqual(status, 200)
        status, _ = self.json_request("GET", f"/api/workouts/{workout_id}")
        self.assertEqual(status, 404)

    def test_invalid_workout_ids(self):
        for path in ("/api/workouts/wk_nothex", "/api/workouts/../../etc", "/api/workouts/wk_" + "a" * 20):
            status, _ = self.json_request("GET", path)
            self.assertEqual(status, 404, path)

    def test_media_route_streams_with_range_and_rejects_everything_else(self):
        status, raw, headers = self.request("GET", "/api/workout-media/running_in_place")
        self.assertEqual(status, 200)
        self.assertEqual(raw, self.video_bytes)
        self.assertEqual(headers["Content-Type"], "video/mp4")
        status, raw, headers = self.request("GET", "/api/workout-media/running_in_place", headers={"Range": "bytes=10-19"})
        self.assertEqual(status, 206)
        self.assertEqual(raw, self.video_bytes[10:20])
        self.assertTrue(headers["Content-Range"].startswith("bytes 10-19/"))
        for bad in ("..%2Fsecret", "%2e%2e%2fsecret.mp4", "Running_In_Place", "no_such_exercise",
                    "march_in_place",  # text-only exercise: no video mapped
                    "split_squat_bw"):  # mapped, but its file is deliberately absent from this test folder
            status, raw, _ = self.request("GET", "/api/workout-media/" + bad)
            self.assertEqual(status, 404, bad)
            self.assertNotIn(b"secret", raw)

    def test_deleting_the_session_removes_its_workouts(self):
        status, created = self.create(session_id=self.other_session)
        self.assertEqual(status, 201)
        ShotLabDB(self.db_path).delete_session(self.other_session)
        status, _ = self.json_request("GET", f"/api/workouts/{created['workout_id']}")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
