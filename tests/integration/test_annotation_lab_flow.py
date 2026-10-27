"""
test_annotation_lab_flow.py - End-to-End Integration Test Suite for Phase 5 Developer Model Lab.

Validates the full workflow:
 1. Clip registration and detector machine proposals ingestion.
 2. Interactive / headless annotation tool (accept proposal, keyframe marking, 8-class negative action, undo).
 3. Database persistence maintaining strict separation of machine proposals and human labels.
 4. Automated dataset QA validation (temporal ordering, taxonomy, split leakage, missing video rules).
 5. Manifest-driven JSONL export with SHA256 checksums and provenance metadata.
 6. Real clip video loading & overlay rendering test.
"""

import os
import json
import tempfile
import unittest
import numpy as np

from basketball.persistence.shot_lab_db import ShotLabDB, TAXONOMY_HARD_NEGATIVES
from tools.annotation_lab import AnnotationLab
from evaluation.validate_dataset import DatasetValidator
try:
    from scripts.export_dataset import DatasetExporter, compute_string_sha256
except ImportError:
    from export_dataset import DatasetExporter, compute_string_sha256


class TestAnnotationLabFlow(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "flow_test.db")
        self.export_dir = os.path.join(self.tmp_dir.name, "flow_export")
        self.db = ShotLabDB(self.db_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_missing_video_integrity_rule(self):
        """Enforces AGENTS.md rule: missing video files raise actionable errors, not silent mocks."""
        non_existent_file = os.path.join(self.tmp_dir.name, "missing_footage.mp4")
        with self.assertRaises(FileNotFoundError) as ctx:
            AnnotationLab(
                video_path=non_existent_file,
                clip_id="clip_missing",
                db_path=self.db_path,
                headless=True,
                synthetic=False
            )
        self.assertIn("DATA INTEGRITY VIOLATION", str(ctx.exception))
        self.assertIn("missing_footage.mp4", str(ctx.exception))

    def test_complete_synthetic_flow(self):
        """End-to-end flow with synthetic fixture explicitly marked."""
        synthetic_path = os.path.join(self.tmp_dir.name, "synthetic_clip.mp4")

        # 1. Initialize AnnotationLab in synthetic headless mode
        app = AnnotationLab(
            video_path=synthetic_path,
            clip_id="clip_flow_01",
            player_id="player_dev_1",
            split="train",
            db_path=self.db_path,
            headless=True,
            synthetic=True
        )

        # 2. Ingest machine proposals
        proposals = [
            {
                "proposal_id": "prop_flow_101",
                "start_frame": 30,
                "end_frame": 70,
                "dip_frame": 40,
                "set_frame": 50,
                "release_frame": 58,
                "confidence": 0.91,
                "status": "proposed"
            }
        ]
        self.db.save_machine_proposals("clip_flow_01", proposals, detector_name="analyzer_v1", detector_version="1.0.0")
        app._init_db_records()  # reload state

        self.assertEqual(len(app.machine_proposals), 1)

        # 3. Headless actions:
        #  a) Seek to frame 45 (inside proposal) and accept proposal
        #  b) Mark hard negative (pump_fake) between frame 100 and 130
        #  c) Mark manual shot event with keyframes between frame 150 and 200
        #  d) Save to database
        commands = [
            "seek:45",
            "accept_prop",
            "seek:100",
            "mark_in",
            "seek:130",
            "mark_out",
            "commit_neg:pump_fake",
            "seek:150",
            "mark_in",
            "seek:200",
            "mark_out",
            "dip:160",
            "set:172",
            "rel:182",
            "ft:190",
            "outcome:make",
            "commit_shot",
            "save"
        ]
        app.run_headless(commands)

        # 4. Verify DB persistence and machine/human separation
        annotations = self.db.get_clip_annotations("clip_flow_01")
        clip_rec = annotations["clip"]
        props_rec = annotations["proposals"]
        intvs_rec = annotations["intervals"]

        self.assertIsNotNone(clip_rec)
        self.assertEqual(clip_rec["player_id"], "player_dev_1")

        # Machine proposal remains preserved, status updated
        self.assertEqual(len(props_rec), 1)
        self.assertEqual(props_rec[0]["proposal_id"], "prop_flow_101")
        self.assertEqual(props_rec[0]["status"], "accepted")
        self.assertEqual(props_rec[0]["release_frame"], 58)  # Original machine proposal preserved

        # Human intervals contain 3 items: accepted shot, pump_fake, manual shot
        self.assertEqual(len(intvs_rec), 3)

        # First interval was converted from proposal
        self.assertEqual(intvs_rec[0]["action_class"], "shot_event")
        self.assertEqual(intvs_rec[0]["interval_type"], "shot")
        self.assertEqual(intvs_rec[0]["start_frame"], 30)
        self.assertEqual(intvs_rec[0]["end_frame"], 70)

        # Second interval is pump_fake
        self.assertEqual(intvs_rec[1]["action_class"], "pump_fake")
        self.assertEqual(intvs_rec[1]["interval_type"], "hard_negative")
        self.assertEqual(intvs_rec[1]["start_frame"], 100)
        self.assertEqual(intvs_rec[1]["end_frame"], 130)

        # Third interval is manual shot
        self.assertEqual(intvs_rec[2]["action_class"], "shot_event")
        self.assertEqual(intvs_rec[2]["start_frame"], 150)
        self.assertEqual(intvs_rec[2]["end_frame"], 200)
        self.assertEqual(intvs_rec[2]["release_frame"], 182)
        self.assertEqual(intvs_rec[2]["outcome"], "make")

        # 5. QA Dataset Validation
        validator = DatasetValidator(db=self.db, check_file_existence=False)
        rep = validator.validate()
        self.assertEqual(rep["status"], "PASSED", f"Validation failed: {rep.get('errors')}")
        self.assertEqual(rep["total_shots"], 2)
        self.assertEqual(rep["total_negatives"], 1)

        # 6. Manifest-Driven Export
        exporter = DatasetExporter(
            db=self.db,
            out_dir=self.export_dir,
            is_synthetic=True,
            force=False,
            validate_before_export=True
        )
        export_res = exporter.export()
        self.assertEqual(export_res["status"], "SUCCESS")

        manifest_path = os.path.join(self.export_dir, "DATASET_MANIFEST.json")
        self.assertTrue(os.path.exists(manifest_path))

        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        self.assertTrue(manifest["synthetic"])
        self.assertEqual(manifest["total_clips"], 1)
        self.assertEqual(manifest["total_intervals"], 3)
        self.assertEqual(manifest["taxonomy"]["action_classes"]["pump_fake"], 1)
        self.assertEqual(manifest["taxonomy"]["action_classes"]["shot_event"], 2)

        # Check train.jsonl
        train_jsonl_path = os.path.join(self.export_dir, "train.jsonl")
        self.assertTrue(os.path.exists(train_jsonl_path))
        with open(train_jsonl_path, "r", encoding="utf-8") as f:
            record = json.loads(f.readline())

        self.assertEqual(record["clip_id"], "clip_flow_01")
        self.assertEqual(len(record["machine_proposals"]), 1)
        self.assertEqual(len(record["human_intervals"]), 3)

    def test_undo_operation(self):
        """Verify that Z/undo removes the last committed interval."""
        synthetic_path = os.path.join(self.tmp_dir.name, "synthetic_undo.mp4")
        app = AnnotationLab(
            video_path=synthetic_path,
            clip_id="clip_undo_01",
            db_path=self.db_path,
            headless=True,
            synthetic=True
        )

        app.execute_command("seek:20")
        app.execute_command("mark_in")
        app.execute_command("seek:40")
        app.execute_command("mark_out")
        app.execute_command("commit_shot")
        self.assertEqual(len(app.human_intervals), 1)

        # Undo
        app.execute_command("undo")
        self.assertEqual(len(app.human_intervals), 0)

    def test_real_video_clip_rendering(self):
        """Test with an actual video file from raw_clips/ if available."""
        real_clip_path = os.path.join("raw_clips", "klay_vid.mp4")
        if not os.path.exists(real_clip_path):
            self.skipTest(f"Real clip '{real_clip_path}' not present, skipping real rendering test.")

        app = AnnotationLab(
            video_path=real_clip_path,
            clip_id="clip_klay_test",
            player_id="klay_thompson",
            split="train",
            db_path=self.db_path,
            headless=True,
            synthetic=False
        )

        self.assertGreater(app.frame_count, 0)
        self.assertGreater(app.width, 0)
        self.assertGreater(app.height, 0)

        # Fetch frame and test rendering
        frame = app.get_current_frame_image()
        self.assertIsInstance(frame, np.ndarray)
        self.assertEqual(frame.shape[0], app.height)
        self.assertEqual(frame.shape[1], app.width)

        # Render overlay
        overlay = app.render_overlay(frame)
        self.assertIsInstance(overlay, np.ndarray)
        self.assertEqual(overlay.shape, frame.shape)


if __name__ == "__main__":
    unittest.main()
