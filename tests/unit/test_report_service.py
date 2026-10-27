"""End-to-end tests for report_service.py on a SYNTHETIC session (stick-figure pose + blank video)."""

import gzip
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

import basketball.services.report_service as rs
from basketball.persistence.shot_lab_db import ShotLabDB
try:
    from tests.support.tests_support_synthetic_pose import make_cache, shot_sequence
except ImportError:
    from tests_support_synthetic_pose import make_cache, shot_sequence

SECTIONS = ["overview", "executive", "technical", "evidence", "shots", "correction_plan", "practice_plan",
            "injury", "progress", "methodology"]


class ReportServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="shotlab_report_test_"))
        self.db_path = str(self.tmp / "t.db")
        self.cache_dir = self.tmp / "pc"
        self.kf_dir = self.tmp / "kf"
        self.cache_dir.mkdir()
        self.db = ShotLabDB(self.db_path)
        self.session_id = self.db.create_session(
            player_id="synthetic_player", camera_view="side_90", shot_type="catch_and_shoot", shot_style="jump_shot",
            fps=30.0, model_version="test", notes=json.dumps({"original_filename": "synthetic.mp4", "skill_level": "beginner",
                                                              "video": {"fps": 30.0, "duration_seconds": 7.5}}))
        poses = []
        for i in range(3):
            offset = len(poses)
            poses.extend(shot_sequence(knee_min=168, drift_px=260))
            self.db.save_shot({"session_id": self.session_id, "player_id": "synthetic_player", "camera_view": "side_90",
                               "shot_type": "catch_and_shoot", "shot_style": "jump_shot",
                               "machine_start_frame": offset + 8, "machine_release_frame": offset + 24,
                               "machine_end_frame": offset + 40, "tracking_confidence": "SUFFICIENT"})
        with gzip.open(self.cache_dir / f"{self.session_id}.json.gz", "wt", encoding="utf-8") as handle:
            json.dump(make_cache(poses), handle)
        self.video = self.tmp / "synthetic.mp4"
        writer = cv2.VideoWriter(str(self.video), cv2.VideoWriter_fourcc(*"mp4v"), 30, (500, 500))
        for f in range(len(poses)):
            writer.write(np.full((500, 500, 3), 40 + f % 50, dtype=np.uint8))
        writer.release()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def build(self, **kwargs):
        return rs.build_report(self.db_path, self.session_id, self.cache_dir, self.kf_dir, [str(self.video)], **kwargs)

    def test_report_has_all_sections_and_real_values(self):
        report = self.build()
        for key in SECTIONS:
            self.assertIn(key, report)
        overview = report["overview"]
        self.assertEqual(overview["attempts_total"], 3)
        self.assertEqual(overview["video_filename"], "synthetic.mp4")
        self.assertEqual(overview["analysis_status"], "COMPLETE")
        self.assertTrue(any("has been confirmed" in x for x in overview["limitations"]))
        improvement_ids = {f["finding_id"] for f in report["correction_plan"]}
        self.assertIn("leg_load", improvement_ids)
        self.assertEqual(report["injury"]["title"], "Technique, Load Management, and Injury-Risk Reduction")
        self.assertEqual(len(report["shots"]), 3)
        self.assertEqual(len(report["technical"]), 9)
        stance = next(r for r in report["technical"] if r["area"] == "Stance")
        self.assertEqual(stance["observation"], "Not measurable from this video")
        self.assertIn("generated_at", report["meta"])
        self.assertIn("ball", report["evidence"]["ball_trajectory"].lower())

    def test_keyframes_are_rendered_from_the_video(self):
        report = self.build()
        frames = report["evidence"]["keyframes"]
        self.assertGreaterEqual(len(frames), 6)
        for item in frames:
            path = self.kf_dir / self.session_id / item["name"]
            self.assertTrue(path.is_file(), item["name"])
            image = cv2.imread(str(path))
            self.assertEqual(image.shape[:2], (500, 500))
            self.assertAlmostEqual(item["time_s"], item["frame"] / 30.0, places=2)

    def test_report_is_persisted_and_rebuilt_when_reviews_change(self):
        first = self.build()
        self.assertFalse(first["meta"]["from_cache"])
        again = self.build()
        self.assertTrue(again["meta"]["from_cache"])
        shot = self.db.get_shots(session_id=self.session_id, min_confidence=None)[0]
        self.db.update_shot_annotation(shot["shot_id"], annotated_boundaries={}, outcome="unknown",
                                       outcome_source="manual_review", review_status="approved", review_notes="")
        rebuilt = self.build()
        self.assertFalse(rebuilt["meta"]["from_cache"])
        self.assertEqual(rebuilt["overview"]["attempts_confirmed"], 1)

    def test_discarded_attempt_is_excluded(self):
        shot = self.db.get_shots(session_id=self.session_id, min_confidence=None)[0]
        self.db.update_shot_annotation(shot["shot_id"], annotated_boundaries={}, outcome="unknown",
                                       outcome_source="manual_review", review_status="discarded", review_notes="")
        report = self.build()
        self.assertEqual(report["overview"]["attempts_discarded"], 1)
        self.assertEqual(len(report["evidence"]["comparison"]["rows"]), 2)

    def test_missing_pose_cache_gives_an_honest_report(self):
        (self.cache_dir / f"{self.session_id}.json.gz").unlink()
        report = self.build()
        self.assertEqual(report["overview"]["analysis_status"], "NO_POSE_DATA")
        self.assertEqual(report["executive"]["strengths"], [])
        self.assertEqual(report["evidence"]["keyframes"], [])
        self.assertTrue(report["injury"]["general_guidance"])

    def test_delete_session_removes_analysis_and_report(self):
        self.build()
        self.assertIsNotNone(self.db.get_session_report(self.session_id))
        self.db.delete_session(self.session_id)
        self.assertIsNone(self.db.get_session_report(self.session_id))
        self.assertIsNone(self.db.get_session_analysis(self.session_id))

    def test_unknown_session(self):
        with self.assertRaises(LookupError):
            rs.build_report(self.db_path, "sess_missing", self.cache_dir, self.kf_dir, [])


if __name__ == "__main__":
    unittest.main()
