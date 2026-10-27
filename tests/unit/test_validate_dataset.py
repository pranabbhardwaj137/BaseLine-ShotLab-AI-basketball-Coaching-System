"""
test_validate_dataset.py - Unit tests for DatasetValidator.
"""

import os
import unittest
import tempfile
from basketball.persistence.shot_lab_db import ShotLabDB
from evaluation.validate_dataset import DatasetValidator

class TestDatasetValidator(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_shot_lab.db")
        self.db = ShotLabDB(self.db_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_empty_dataset_fails(self):
        validator = DatasetValidator(db=self.db, check_file_existence=False)
        rep = validator.validate()
        self.assertEqual(rep["status"], "FAILED")
        self.assertTrue(any(e["code"] == "ERR_EMPTY_DATASET" for e in rep["errors"]))

    def test_valid_dataset_passes(self):
        self.db.register_labeled_clip(
            clip_id="clip_001",
            player_id="player_A",
            session_id="sess_1",
            file_path="dummy.mp4",
            split="train",
            frame_count=100
        )
        self.db.save_labeled_interval(
            clip_id="clip_001",
            interval_type="shot",
            action_class="shot_event",
            start_frame=10,
            end_frame=50,
            dip_frame=15,
            set_frame=25,
            release_frame=35,
            follow_through_frame=45,
            outcome="make",
            human_annotator_id="tester"
        )
        self.db.save_labeled_interval(
            clip_id="clip_001",
            interval_type="negative",
            action_class="pump_fake",
            start_frame=60,
            end_frame=80,
            outcome="none",
            human_annotator_id="tester"
        )

        validator = DatasetValidator(db=self.db, check_file_existence=False)
        rep = validator.validate()
        self.assertEqual(rep["status"], "PASSED", f"Validation errors: {rep['errors']}")
        self.assertEqual(len(rep["errors"]), 0)
        self.assertEqual(rep["total_shots"], 1)
        self.assertEqual(rep["total_negatives"], 1)

    def test_temporal_order_violation(self):
        self.db.register_labeled_clip(
            clip_id="clip_002",
            player_id="player_B",
            session_id="sess_1",
            file_path="dummy.mp4",
            split="train",
            frame_count=100
        )
        # release before set!
        self.db.save_labeled_interval(
            clip_id="clip_002",
            interval_type="shot",
            action_class="shot_event",
            start_frame=10,
            end_frame=50,
            set_frame=35,
            release_frame=25,
            outcome="miss",
            human_annotator_id="tester"
        )

        validator = DatasetValidator(db=self.db, check_file_existence=False)
        rep = validator.validate()
        self.assertEqual(rep["status"], "FAILED")
        self.assertTrue(any(e["code"] == "ERR_TEMPORAL_ORDER" for e in rep["errors"]))

    def test_taxonomy_violation(self):
        self.db.register_labeled_clip(
            clip_id="clip_003",
            player_id="player_C",
            session_id="sess_1",
            file_path="dummy.mp4",
            split="train",
            frame_count=100
        )
        self.db.save_labeled_interval(
            clip_id="clip_003",
            interval_type="negative",
            action_class="invalid_action_foo",
            start_frame=10,
            end_frame=30,
            outcome="none",
            human_annotator_id="tester"
        )

        validator = DatasetValidator(db=self.db, check_file_existence=False)
        rep = validator.validate()
        self.assertEqual(rep["status"], "FAILED")
        self.assertTrue(any(e["code"] == "ERR_TAXONOMY" for e in rep["errors"]))

    def test_split_leakage_detection(self):
        # player_X appears in both train and test!
        self.db.register_labeled_clip(
            clip_id="clip_train",
            player_id="player_X",
            session_id="sess_1",
            file_path="dummy1.mp4",
            split="train",
            frame_count=100
        )
        self.db.register_labeled_clip(
            clip_id="clip_test",
            player_id="player_X",
            session_id="sess_2",
            file_path="dummy2.mp4",
            split="test",
            frame_count=100
        )
        self.db.save_labeled_interval(
            clip_id="clip_train",
            interval_type="shot",
            action_class="shot_event",
            start_frame=10,
            end_frame=30,
            outcome="make",
            human_annotator_id="tester"
        )
        self.db.save_labeled_interval(
            clip_id="clip_test",
            interval_type="shot",
            action_class="shot_event",
            start_frame=10,
            end_frame=30,
            outcome="miss",
            human_annotator_id="tester"
        )

        validator = DatasetValidator(db=self.db, check_file_existence=False)
        rep = validator.validate()
        self.assertEqual(rep["status"], "FAILED")
        self.assertTrue(any(e["code"] == "ERR_SPLIT_LEAKAGE" for e in rep["errors"]))

    def test_missing_video_check(self):
        non_existent_file = os.path.join(self.tmp_dir.name, "does_not_exist.mp4")
        self.db.register_labeled_clip(
            clip_id="clip_missing",
            player_id="player_Y",
            session_id="sess_1",
            file_path=non_existent_file,
            split="train",
            frame_count=100
        )
        self.db.save_labeled_interval(
            clip_id="clip_missing",
            interval_type="shot",
            action_class="shot_event",
            start_frame=10,
            end_frame=30,
            outcome="make",
            human_annotator_id="tester"
        )

        validator = DatasetValidator(db=self.db, check_file_existence=True)
        rep = validator.validate()
        self.assertEqual(rep["status"], "FAILED")
        err = next(e for e in rep["errors"] if e["code"] == "ERR_MISSING_VIDEO")
        self.assertIn("AGENTS.md", err["message"])
        self.assertIn("does_not_exist.mp4", err["message"])

if __name__ == "__main__":
    unittest.main()
