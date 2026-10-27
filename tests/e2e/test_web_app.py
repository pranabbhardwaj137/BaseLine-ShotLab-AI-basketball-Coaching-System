"""Integration tests for the local Phase 8 web app API (web_app.py).

These tests start the real standard-library HTTP server on a loopback port with
temporary database/upload/cache directories. The uploaded clip is a SYNTHETIC
fixture (solid-colour frames written with OpenCV) used only to exercise the
upload -> job -> persistence -> deletion workflow. It contains no person, so the
expected analysis result is zero shot proposals; it says nothing about accuracy.
Shot rows used for review tests are inserted directly as clearly synthetic data.
"""

import json
import os
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

import basketball.app.web_app as web_app
from basketball.persistence.shot_lab_db import ShotLabDB


def _write_synthetic_clip(path, frames=12, size=(160, 120), fps=10):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    for index in range(frames):
        frame = np.full((size[1], size[0], 3), (index * 15) % 255, dtype=np.uint8)
        writer.write(frame)
    writer.release()


class WebAppApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="shotlab_web_test_"))
        cls.db_path = str(cls.tmp / "test.db")
        cls.upload_dir = cls.tmp / "uploads"
        cls.cache_dir = cls.tmp / "pose_cache"
        cls.keyframe_dir = cls.tmp / "keyframes"
        cls.upload_dir.mkdir()
        cls.cache_dir.mkdir()
        cls.keyframe_dir.mkdir()
        server = web_app.LocalAppServer(("127.0.0.1", 0), web_app.AppHandler)
        server.db_path = cls.db_path
        server.upload_dir = cls.upload_dir
        server.pose_cache_dir = cls.cache_dir
        server.keyframe_dir = cls.keyframe_dir
        server.job_store = web_app.JobStore(cls.db_path + ".web_jobs.sqlite3", upload_root=cls.upload_dir)
        server.executor = ThreadPoolExecutor(max_workers=1)
        server.worker_slots = threading.BoundedSemaphore(2)
        server.session_locks = {}
        server.llm_chat_enabled = False
        server.llm_model = "test-model"
        cls.server = server
        cls.base = f"http://127.0.0.1:{server.server_address[1]}"
        cls.thread = threading.Thread(target=server.serve_forever, daemon=True)
        cls.thread.start()
        cls.clip = cls.tmp / "synthetic_clip.mp4"
        _write_synthetic_clip(cls.clip)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.server.executor.shutdown(wait=True)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ----------------------------------------------------------------- helpers
    def request(self, method, path, body=None, headers=None):
        data = body
        headers = dict(headers or {})
        if method in {"POST", "PUT", "DELETE"}:
            headers.setdefault("X-Shotlab", "1")
        if isinstance(body, (dict, list)):
            data = json.dumps(body).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                raw = response.read()
                return response.status, raw, response.headers
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), exc.headers

    def json_request(self, method, path, body=None, headers=None):
        status, raw, _ = self.request(method, path, body, headers)
        return status, json.loads(raw.decode("utf-8"))

    def upload(self, player="web_test_player", filename="clip.mp4", data=None):
        query = (f"/api/sessions?player_id={player}&camera_view=side_90&shot_type=catch_and_shoot"
                 f"&shot_style=jump_shot&handedness=right&skill_level=intermediate&goals=")
        body = self.clip.read_bytes() if data is None else data
        return self.json_request("POST", query, body, {
            "Content-Type": "application/octet-stream", "X-Upload-Filename": filename})

    def wait_for_job(self, job_id, timeout=120):
        deadline = time.time() + timeout
        while time.time() < deadline:
            status, job = self.json_request("GET", f"/api/jobs/{job_id}")
            self.assertEqual(status, 200)
            if job["status"] in {"complete", "failed"}:
                return job
            time.sleep(0.25)
        self.fail("analysis job did not finish in time")

    # ------------------------------------------------------------------- tests
    def test_health_and_static_assets(self):
        status, health = self.json_request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(health["status"], "ok")
        self.assertFalse(health["llm_chat_enabled"])
        for path, kind in (("/", "text/html"), ("/assets/app.js", "javascript"), ("/assets/app.css", "text/css")):
            status, raw, headers = self.request("GET", path)
            self.assertEqual(status, 200, path)
            self.assertIn(kind, headers["Content-Type"])
            self.assertGreater(len(raw), 100)
        status, _, _ = self.request("GET", "/assets/../web_app.py")
        self.assertEqual(status, 404)

    def test_upload_validation_errors(self):
        status, payload = self.upload(filename="notes.txt")
        self.assertEqual(status, 415)
        self.assertIn("Supported video formats", payload["error"])
        status, payload = self.upload(player="bad%20id!")
        self.assertEqual(status, 400)
        status, payload = self.upload(data=b"")
        self.assertEqual(status, 400)
        status, payload = self.upload(data=b"definitely not a video")
        self.assertEqual(status, 400)
        self.assertEqual(list(self.upload_dir.glob("*.mp4")), [], "rejected uploads must not be kept")

    def test_upload_browser_recorded_webm_flow(self):
        from basketball.services.video_analysis_service import find_ffmpeg
        import subprocess

        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            self.skipTest("FFmpeg unavailable")

        # Generate a small browser-like WebM recording
        webm_path = self.tmp / "sample_recording.webm"
        cmd = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=2:size=160x120:rate=15",
            "-c:v", "libvpx-vp9", str(webm_path)
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"FFmpeg could not create test webm: {res.stderr}")

        # Upload WebM as browser camera recording
        status, accepted = self.upload(filename="webcam_record.webm", data=webm_path.read_bytes())
        self.assertEqual(status, 202, accepted)
        job = self.wait_for_job(accepted["job_id"])
        self.assertEqual(job["status"], "complete", job.get("error"))
        self.assertGreaterEqual(job["result"]["frames_processed"], 20)

    def test_full_upload_review_history_and_delete_flow(self):
        status, accepted = self.upload()
        self.assertEqual(status, 202, accepted)
        job = self.wait_for_job(accepted["job_id"])
        self.assertEqual(job["status"], "complete", job.get("error"))
        result = job["result"]
        self.assertEqual(result["frames_processed"], 12)
        self.assertEqual(result["shot_count"], 0, "synthetic frames contain no shooter")
        self.assertEqual(result["outcomes"]["automated"], "not_run")
        session_id = accepted["session_id"]

        # Range requests for replay seeking.
        status, raw, headers = self.request("GET", f"/api/jobs/{accepted['job_id']}/video",
                                            headers={"Range": "bytes=0-9"})
        self.assertEqual(status, 206)
        self.assertEqual(len(raw), 10)
        self.assertTrue(headers["Content-Range"].startswith("bytes 0-9/"))
        self.assertTrue((self.cache_dir / f"{session_id}.json.gz").is_file())

        # Insert a clearly synthetic machine proposal so the review API can be exercised.
        db = ShotLabDB(self.db_path)
        shot_id = db.save_shot({
            "shot_id": "shot_synthetic_review", "session_id": session_id, "player_id": "web_test_player",
            "camera_view": "side_90", "shot_type": "catch_and_shoot", "shot_style": "jump_shot",
            "machine_start_frame": 1, "machine_release_frame": 5, "machine_end_frame": 8,
            "outcome": "unknown", "outcome_source": "unlabeled", "review_status": "quarantined",
            "tracking_confidence": "SUFFICIENT", "elbow_angle_release_3d": 150.0,
        })

        status, payload = self.json_request("PUT", f"/api/shots/{shot_id}/review",
                                            {"boundaries": {"release_frame": 0}})
        self.assertEqual(status, 400)
        self.assertIn("chronological", payload["error"])
        status, payload = self.json_request("PUT", f"/api/shots/{shot_id}/review",
                                            {"boundaries": {"end_frame": 999}})
        self.assertEqual(status, 400)
        status, payload = self.json_request("PUT", f"/api/shots/{shot_id}/review", {"outcome": "make"})
        self.assertEqual(status, 400, "make/miss requires explicit approval")
        status, payload = self.json_request("PUT", f"/api/shots/{shot_id}/review", {
            "boundaries": {"release_frame": 6}, "outcome": "make", "review_status": "approved",
            "review_notes": "synthetic test review"})
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["shot"]["annotated_release_frame"], 6)
        self.assertEqual(payload["shot"]["machine_release_frame"], 5, "machine boundary is immutable")
        self.assertTrue(payload["history"])

        # Reloading the job must reflect the saved review, not the completion snapshot.
        status, job = self.json_request("GET", f"/api/jobs/{accepted['job_id']}")
        shots = {shot["shot_id"]: shot for shot in job["result"]["shots"]}
        self.assertEqual(shots[shot_id]["review_status"], "approved")
        self.assertEqual(job["result"]["shot_count"], 1)

        # Evidence gate: one approved shot is not enough for coaching or a drill.
        status, insights = self.json_request("GET", f"/api/sessions/{session_id}/insights")
        self.assertEqual(status, 200)
        self.assertIsNone(insights["cue"])
        self.assertEqual(insights["status"], "INSUFFICIENT_EVIDENCE")
        status, _ = self.json_request("POST", f"/api/sessions/{session_id}/remediation", b"")
        self.assertEqual(status, 409)
        status, payload = self.json_request("POST", f"/api/sessions/{session_id}/coach-chat", {"question": "hi"})
        self.assertEqual(status, 503)

        # History exposes the job so a past session can be reopened.
        status, history = self.json_request("GET", "/api/players/web_test_player/history")
        self.assertEqual(status, 200)
        listed = {item["session_id"]: item for item in history["sessions"]}
        self.assertEqual(listed[session_id]["job_id"], accepted["job_id"])
        self.assertEqual(listed[session_id]["approved_sufficient_shots"], 1)

        # Goal validation.
        status, _ = self.json_request("PUT", "/api/players/web_test_player/goal", {"weekly_session_target": 9})
        self.assertEqual(status, 400)
        status, goal = self.json_request("PUT", "/api/players/web_test_player/goal", {"weekly_session_target": 4})
        self.assertEqual(status, 200)
        status, history = self.json_request("GET", "/api/players/web_test_player/history")
        self.assertEqual(history["weekly_target"], 4)

        # Deletion removes DB rows, managed media, and makes the job unreachable.
        status, deleted = self.json_request("DELETE", f"/api/sessions/{session_id}")
        self.assertEqual(status, 200, deleted)
        self.assertEqual(deleted["warnings"], [])
        self.assertIsNone(db.get_session(session_id))
        self.assertFalse((self.cache_dir / f"{session_id}.json.gz").exists())
        self.assertEqual(list(self.upload_dir.glob(f"{accepted['job_id']}.*")), [])
        status, _ = self.json_request("GET", f"/api/jobs/{accepted['job_id']}")
        self.assertEqual(status, 404)

    def test_stored_video_path_from_another_computer_resolves_inside_upload_dir(self):
        name = "0123456789abcdef0123456789abcdef.mp4"
        (self.upload_dir / name).write_bytes(b"x")
        store = self.server.job_store
        windows = "C:\\Users\\someone\\basketball_proj\\user_data\\uploads\\" + name
        self.assertEqual(Path(store.resolve_video_path(windows)), self.upload_dir / name)
        self.assertEqual(Path(store.resolve_video_path("/old/mac/path/" + name)), self.upload_dir / name)
        self.assertEqual(store.resolve_video_path("/missing/elsewhere.mp4"), "/missing/elsewhere.mp4")
        os.remove(self.upload_dir / name)


if __name__ == "__main__":
    unittest.main()


class WebAppCoachFeaturesTest(WebAppApiTest):
    """08-07 features: report, manual attempts, keyframes, camera view, cancel, refresh, guards."""

    def raw(self, method, path, headers=None, body=None, server=None):
        import http.client
        port = (server or self.server).server_address[1]
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, dict(response.getheaders()), data

    def uploaded_session(self):
        status, accepted = self.upload(player="coach_player")
        self.assertEqual(status, 202, accepted)
        job = self.wait_for_job(accepted["job_id"])
        self.assertEqual(job["status"], "complete", job.get("error"))
        return accepted, job

    def test_csrf_header_and_host_check(self):
        status, _, body = self.raw("PUT", "/api/players/p1/goal", {"Content-Type": "application/json"}, b'{"weekly_session_target": 3}')
        self.assertEqual(status, 403)
        self.assertIn(b"X-Shotlab", body)
        status, _, _ = self.raw("GET", "/api/health", {"Host": "evil.example:80"})
        self.assertEqual(status, 403)

    def test_too_short_video_is_rejected(self):
        short = self.tmp / "short.mp4"
        _write_synthetic_clip(short, frames=3, fps=10)
        status, payload = self.upload(data=short.read_bytes())
        self.assertEqual(status, 400)
        self.assertIn("only", payload["error"])

    def test_report_manual_attempt_keyframes_and_camera_view(self):
        accepted, job = self.uploaded_session()
        session_id = accepted["session_id"]
        self.assertTrue(job["result"]["report_ready"], job["result"].get("report_error"))
        status, report = self.json_request("GET", f"/api/sessions/{session_id}/report")
        self.assertEqual(status, 200, report)
        self.assertEqual(report["overview"]["attempts_total"], 0)
        self.assertEqual(report["meta"]["job_id"], accepted["job_id"])
        self.assertIn("injury", report)

        url = f"/api/sessions/{session_id}/shots"
        status, payload = self.json_request("POST", url, {"start_frame": 6, "release_frame": 3, "end_frame": 9})
        self.assertEqual(status, 400)
        status, payload = self.json_request("POST", url, {"start_frame": 1, "release_frame": 5, "end_frame": 99})
        self.assertEqual(status, 400)
        status, payload = self.json_request("POST", url, {"start_frame": 1, "release_frame": 5, "end_frame": 9})
        self.assertEqual(status, 201, payload)
        shot = payload["shot"]
        self.assertEqual(shot["review_status"], "approved")
        self.assertEqual(shot["outcome_source"], "manual_attempt")
        self.assertIsNone(shot["machine_release_frame"])
        self.assertEqual(shot["annotated_release_frame"], 5)
        self.assertTrue(shot["review_history"])

        status, report = self.json_request("GET", f"/api/sessions/{session_id}/report")
        self.assertEqual(report["overview"]["attempts_total"], 1)
        self.assertFalse(report["meta"]["from_cache"])
        self.assertTrue(report["shots"][0]["manually_added"])
        names = [k["name"] for k in report["evidence"]["keyframes"]]
        self.assertTrue(names)
        status, headers, data = self.raw("GET", f"/api/sessions/{session_id}/keyframes/{names[0]}")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "image/jpeg")
        self.assertTrue(data.startswith(b"\xff\xd8"))
        for bad in ("..%2F..%2Ftest.db", "x.jpg", "shot_a_release_1.png"):
            status, _, _ = self.raw("GET", f"/api/sessions/{session_id}/keyframes/{bad}")
            self.assertEqual(status, 404, bad)

        status, payload = self.json_request("PUT", f"/api/sessions/{session_id}/camera-view", {"camera_view": "sideways"})
        self.assertEqual(status, 400)
        status, payload = self.json_request("PUT", f"/api/sessions/{session_id}/camera-view", {"camera_view": "rear"})
        self.assertEqual(status, 200)
        self.assertEqual(ShotLabDB(self.db_path).get_session(session_id)["camera_view"], "rear")

        # Pose refresh re-runs pose only; the manual attempt and its review stay.
        status, payload = self.json_request("POST", f"/api/sessions/{session_id}/refresh-pose", b"")
        self.assertEqual(status, 202, payload)
        refreshed = self.wait_for_job(payload["job_id"])
        self.assertEqual(refreshed["status"], "complete", refreshed.get("error"))
        self.assertEqual(refreshed["kind"], "pose_refresh")
        shots = ShotLabDB(self.db_path).get_shots(session_id=session_id, min_confidence=None)
        self.assertEqual([s["shot_id"] for s in shots], [shot["shot_id"]])

        status, deleted = self.json_request("DELETE", f"/api/sessions/{session_id}")
        self.assertEqual(status, 200)
        self.assertFalse((self.keyframe_dir / session_id).exists())

    def test_cancel_marks_job_and_discards_partial_session(self):
        db = ShotLabDB(self.db_path)
        session_id = db.create_session(player_id="cancel_player", camera_view="side_90", shot_type="catch_and_shoot",
                                       shot_style="jump_shot", fps=10.0, model_version="test", notes="{}")
        video = self.upload_dir / "cancelme.mp4"
        shutil.copy(self.clip, video)
        job_id = "c" * 32
        self.server.job_store.create(job_id, session_id, "cancel_player", str(video))
        status, payload = self.json_request("POST", f"/api/jobs/{job_id}/cancel", b"")
        self.assertEqual(status, 202)
        self.assertTrue(self.server.worker_slots.acquire(blocking=False))
        web_app._run_analysis(self.server, job_id, session_id, "cancel_player",
                              {"camera_view": "side_90", "shot_type": "catch_and_shoot", "shot_style": "jump_shot"}, str(video))
        job = self.server.job_store.get(job_id)
        self.assertEqual((job["status"], job["error"]), ("failed", "cancelled"))
        self.assertIsNone(db.get_session(session_id))
        self.assertFalse(video.exists())
        status, payload = self.json_request("POST", f"/api/jobs/{job_id}/cancel", b"")
        self.assertEqual(status, 409)


class LanAccessTest(unittest.TestCase):
    """--lan mode: access code, cookie, private-network-only, lockout."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="shotlab_lan_test_"))
        server = web_app.LocalAppServer(("127.0.0.1", 0), web_app.AppHandler)
        server.db_path = str(cls.tmp / "lan.db")
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
        server.lan_mode = True
        server.access_token = "TESTCODE99"
        server.lan_urls = ["http://192.168.1.20:8765/"]
        cls.server = server
        cls.thread = threading.Thread(target=server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = server.server_address[1]
        cls.phone = {"Host": f"192.168.1.20:{cls.port}"}  # what a phone on the Wi-Fi would send

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.server.executor.shutdown(wait=True)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def raw(self, method, path, headers=None, body=None):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, dict(response.getheaders()), data

    def setUp(self):
        self.server.auth_failures.clear()

    def test_phone_needs_the_code_then_gets_a_cookie(self):
        status, _, _ = self.raw("GET", "/api/health", self.phone)
        self.assertEqual(status, 401)
        status, headers, body = self.raw("GET", "/", self.phone)
        self.assertEqual(status, 401)
        self.assertIn(b"Enter the access code", body)
        status, _, body = self.raw("GET", "/?token=WRONGCODE1", self.phone)
        self.assertEqual(status, 401)
        self.assertIn(b"not right", body)
        status, headers, _ = self.raw("GET", "/?token=testcode99", self.phone)
        self.assertEqual(status, 303)
        cookie = headers["Set-Cookie"].split(";")[0]
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])
        status, _, _ = self.raw("GET", "/api/health", {**self.phone, "Cookie": cookie})
        self.assertEqual(status, 200)
        status, _, _ = self.raw("GET", "/api/health", {**self.phone, "X-Access-Token": "TESTCODE99"})
        self.assertEqual(status, 200)
        status, _, _ = self.raw("PUT", "/api/players/p/goal", {**self.phone, "Cookie": cookie, "Content-Type": "application/json"},
                                b'{"weekly_session_target": 2}')
        self.assertEqual(status, 403, "CSRF header still required")

    def test_computer_itself_needs_no_code_and_sees_connection_details(self):
        status, _, body = self.raw("GET", "/api/connection", {"Host": f"127.0.0.1:{self.port}"})
        self.assertEqual(status, 200)
        info = json.loads(body)
        self.assertTrue(info["lan_enabled"])
        self.assertEqual(info["access_code"], "TESTCODE99")
        status, _, _ = self.raw("GET", "/api/connection", {**self.phone, "X-Access-Token": "TESTCODE99"})
        self.assertEqual(status, 403)

    def test_lockout_after_repeated_wrong_codes(self):
        for _ in range(10):
            self.raw("GET", "/?token=BADBADBAD1", self.phone)
        status, _, _ = self.raw("GET", "/?token=TESTCODE99", self.phone)
        self.assertEqual(status, 429)

    def test_public_addresses_are_refused(self):
        import email.message
        handler = web_app.AppHandler.__new__(web_app.AppHandler)
        handler.server = self.server
        handler.client_address = ("8.8.8.8", 5555)
        handler.command, handler.path = "GET", "/api/health"
        handler.headers = email.message.Message()
        handler.headers["Host"] = "203.0.113.5:8765"
        handler.headers["X-Access-Token"] = "TESTCODE99"
        errors = []
        handler._text_error = lambda status, message: errors.append(status)
        self.assertFalse(handler._guard())
        self.assertEqual(errors, [403])

    def test_access_code_generation(self):
        code = web_app.generate_access_code()
        self.assertEqual(len(code), 10)
        self.assertTrue(set(code) <= set(web_app.ACCESS_ALPHABET))
