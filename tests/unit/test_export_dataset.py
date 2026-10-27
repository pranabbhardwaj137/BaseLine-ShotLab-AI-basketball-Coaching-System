"""
test_export_dataset.py - Unit test suite for DatasetExporter.
"""

import os
import json
import hashlib
import tempfile
import unittest
from basketball.persistence.shot_lab_db import ShotLabDB
try:
    from scripts.export_dataset import DatasetExporter, compute_string_sha256
except ImportError:
    from export_dataset import DatasetExporter, compute_string_sha256

class TestDatasetExporter(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_shot_lab.db")
        self.export_dir = os.path.join(self.tmp_dir.name, "export_output")
        self.db = ShotLabDB(self.db_path)

        # Seed sample data: train clip
        self.db.register_labeled_clip(
            clip_id="clip_train_1",
            player_id="player_A",
            session_id="sess_1",
            file_path="video_a.mp4",
            split="train",
            frame_count=200
        )
        self.db.save_machine_proposals("clip_train_1", [
            {"proposal_id": "prop_1", "start_frame": 10, "end_frame": 50, "release_frame": 35}
        ])
        self.db.save_labeled_interval(
            clip_id="clip_train_1",
            interval_type="shot",
            action_class="shot_event",
            start_frame=12,
            end_frame=48,
            dip_frame=15,
            set_frame=25,
            release_frame=35,
            follow_through_frame=45,
            outcome="make",
            human_annotator_id="tester"
        )

        # Seed sample data: test clip with hard negative (different player!)
        self.db.register_labeled_clip(
            clip_id="clip_test_1",
            player_id="player_B",
            session_id="sess_2",
            file_path="video_b.mp4",
            split="test",
            frame_count=200
        )
        self.db.save_labeled_interval(
            clip_id="clip_test_1",
            interval_type="negative",
            action_class="pass",
            start_frame=50,
            end_frame=80,
            outcome="none",
            human_annotator_id="tester"
        )

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_export_success_with_synthetic_flag(self):
        exporter = DatasetExporter(
            db=self.db,
            out_dir=self.export_dir,
            is_synthetic=True,
            force=False,
            validate_before_export=True
        )
        res = exporter.export()
        self.assertEqual(res["status"], "SUCCESS")

        manifest_path = os.path.join(self.export_dir, "DATASET_MANIFEST.json")
        self.assertTrue(os.path.exists(manifest_path))

        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        self.assertEqual(manifest["manifest_version"], "1.0.0")
        self.assertTrue(manifest["synthetic"])
        self.assertEqual(manifest["total_clips"], 2)
        self.assertEqual(manifest["total_intervals"], 2)
        self.assertEqual(manifest["taxonomy"]["action_classes"]["shot_event"], 1)
        self.assertEqual(manifest["taxonomy"]["action_classes"]["pass"], 1)
        self.assertEqual(manifest["player_split_mapping"]["train"], ["player_A"])
        self.assertEqual(manifest["player_split_mapping"]["test"], ["player_B"])

        # Check train.jsonl
        train_jsonl_path = os.path.join(self.export_dir, "train.jsonl")
        self.assertTrue(os.path.exists(train_jsonl_path))
        with open(train_jsonl_path, "r", encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["clip_id"], "clip_train_1")
        # Dual lane presence
        self.assertEqual(len(lines[0]["machine_proposals"]), 1)
        self.assertEqual(lines[0]["machine_proposals"][0]["proposal_id"], "prop_1")
        self.assertEqual(len(lines[0]["human_intervals"]), 1)
        self.assertEqual(lines[0]["human_intervals"][0]["action_class"], "shot_event")

        # Verify checksum recorded matches actual train.jsonl content
        with open(train_jsonl_path, "r", encoding="utf-8") as f:
            content = f.read()
        expected_sha = compute_string_sha256(content)
        self.assertEqual(manifest["splits"]["train"]["sha256"], expected_sha)

    def test_export_validation_failure_blocks_export(self):
        # Create player split leakage to induce validation error
        self.db.register_labeled_clip(
            clip_id="clip_leak",
            player_id="player_A",  # player_A already in train!
            session_id="sess_leak",
            file_path="video_c.mp4",
            split="test",
            frame_count=200
        )
        self.db.save_labeled_interval(
            clip_id="clip_leak",
            interval_type="shot",
            action_class="shot_event",
            start_frame=10,
            end_frame=30,
            outcome="miss"
        )

        exporter = DatasetExporter(
            db=self.db,
            out_dir=self.export_dir,
            is_synthetic=True,
            force=False,
            validate_before_export=True
        )
        with self.assertRaises(ValueError):
            exporter.export()

    def test_export_force_bypasses_validation_failure(self):
        # Leakage introduced
        self.db.register_labeled_clip(
            clip_id="clip_leak",
            player_id="player_A",
            session_id="sess_leak",
            file_path="video_c.mp4",
            split="test",
            frame_count=200
        )
        self.db.save_labeled_interval(
            clip_id="clip_leak",
            interval_type="shot",
            action_class="shot_event",
            start_frame=10,
            end_frame=30,
            outcome="miss"
        )

        exporter = DatasetExporter(
            db=self.db,
            out_dir=self.export_dir,
            is_synthetic=True,
            force=True,  # Force bypass
            validate_before_export=True
        )
        res = exporter.export()
        self.assertEqual(res["status"], "SUCCESS")
        manifest_path = os.path.join(self.export_dir, "DATASET_MANIFEST.json")
        self.assertTrue(os.path.exists(manifest_path))


if __name__ == "__main__":
    unittest.main()
