"""
test_annotation_db.py - Unit test suite for Phase 5 Developer Model Lab database methods.
"""

import os
import unittest
from basketball.persistence.shot_lab_db import ShotLabDB, TAXONOMY_HARD_NEGATIVES, TAXONOMY_ALL_ACTIONS

class TestAnnotationDB(unittest.TestCase):
    def setUp(self):
        self.test_db = "test_annotation_db.db"
        if os.path.exists(self.test_db):
            try:
                os.remove(self.test_db)
            except Exception:
                pass
        self.db = ShotLabDB(self.test_db)

    def tearDown(self):
        if os.path.exists(self.test_db):
            try:
                os.remove(self.test_db)
            except Exception:
                pass

    def test_clip_registration_and_retrieval(self):
        """Verify video clip registration with split and metadata."""
        clip_id = self.db.register_labeled_clip({
            "clip_id": "clip_test_01",
            "file_path": "raw_clips/test_video.mp4",
            "file_sha256": "abcdef1234567890",
            "player_id": "player_curry",
            "camera_view": "side_90",
            "shot_style": "jump_shot",
            "fps": 30.0,
            "frame_count": 300,
            "width": 1920,
            "height": 1080,
            "split": "train",
            "license": "private_project"
        })
        self.assertEqual(clip_id, "clip_test_01")

        clip = self.db.get_labeled_clip("clip_test_01")
        self.assertIsNotNone(clip)
        self.assertEqual(clip["player_id"], "player_curry")
        self.assertEqual(clip["split"], "train")
        self.assertEqual(clip["file_sha256"], "abcdef1234567890")

        # Test listing by split
        train_clips = self.db.list_labeled_clips(split="train")
        self.assertEqual(len(train_clips), 1)
        test_clips = self.db.list_labeled_clips(split="test")
        self.assertEqual(len(test_clips), 0)

    def test_machine_proposals_persistence(self):
        """Verify machine detector proposals are persisted separately from human labels."""
        self.db.register_labeled_clip({
            "clip_id": "clip_test_02",
            "file_path": "raw_clips/test_video2.mp4",
            "player_id": "player_klay",
            "camera_view": "frontal",
            "split": "val"
        })

        proposals = [
            {
                "proposal_id": "prop_01",
                "start_frame": 50,
                "end_frame": 90,
                "dip_frame": 60,
                "set_frame": 70,
                "release_frame": 78,
                "confidence": 0.88,
                "status": "proposed"
            },
            {
                "proposal_id": "prop_02",
                "start_frame": 150,
                "end_frame": 195,
                "dip_frame": 162,
                "set_frame": 175,
                "release_frame": 184,
                "confidence": 0.92,
                "status": "proposed"
            }
        ]
        count = self.db.save_machine_proposals("clip_test_02", proposals, detector_name="analyzer_heuristic", detector_version="1.0.0")
        self.assertEqual(count, 2)

        fetched = self.db.get_machine_proposals("clip_test_02")
        self.assertEqual(len(fetched), 2)
        self.assertEqual(fetched[0]["detector_name"], "analyzer_heuristic")
        self.assertEqual(fetched[0]["release_frame"], 78)

        # Update proposal status
        ok = self.db.update_machine_proposal_status("prop_01", "accepted")
        self.assertTrue(ok)
        updated = self.db.get_machine_proposals("clip_test_02")
        self.assertEqual(updated[0]["status"], "accepted")

    def test_labeled_intervals_and_negative_taxonomy(self):
        """Verify human labeled shot events and 8-class hard negatives."""
        self.db.register_labeled_clip({
            "clip_id": "clip_test_03",
            "file_path": "raw_clips/test_video3.mp4",
            "player_id": "player_curry",
            "camera_view": "oblique_45",
            "split": "test"
        })

        # Save shot interval
        shot_int_id = self.db.save_labeled_interval({
            "interval_id": "shot_01",
            "clip_id": "clip_test_03",
            "interval_type": "shot",
            "action_class": "shot_event",
            "start_frame": 100,
            "end_frame": 150,
            "dip_frame": 115,
            "set_frame": 128,
            "release_frame": 138,
            "follow_through_frame": 145,
            "outcome": "make",
            "rim_contact": "swish",
            "annotator_id": "expert_dev"
        })
        self.assertEqual(shot_int_id, "shot_01")

        # Save hard-negative interval from taxonomy (e.g. pump_fake)
        self.assertIn("pump_fake", TAXONOMY_HARD_NEGATIVES)
        neg_int_id = self.db.save_labeled_interval({
            "interval_id": "neg_01",
            "clip_id": "clip_test_03",
            "interval_type": "hard_negative",
            "action_class": "pump_fake",
            "start_frame": 200,
            "end_frame": 240,
            "notes": "Upward fake with ball kept at chest"
        })
        self.assertEqual(neg_int_id, "neg_01")

        # Verify combined retrieval via get_clip_annotations
        ann = self.db.get_clip_annotations("clip_test_03")
        self.assertIsNotNone(ann["clip"])
        self.assertEqual(len(ann["intervals"]), 2)
        self.assertEqual(ann["intervals"][0]["action_class"], "shot_event")
        self.assertEqual(ann["intervals"][0]["outcome"], "make")
        self.assertEqual(ann["intervals"][1]["action_class"], "pump_fake")
        self.assertEqual(ann["intervals"][1]["outcome"], "none")

        # Update interval
        ok = self.db.update_labeled_interval("shot_01", {"outcome": "miss", "rim_contact": "front_rim"})
        self.assertTrue(ok)
        ann_after = self.db.get_clip_annotations("clip_test_03")
        self.assertEqual(ann_after["intervals"][0]["outcome"], "miss")

        # Delete interval
        ok_del = self.db.delete_labeled_interval("neg_01")
        self.assertTrue(ok_del)
        ann_after_del = self.db.get_clip_annotations("clip_test_03")
        self.assertEqual(len(ann_after_del["intervals"]), 1)


if __name__ == "__main__":
    unittest.main()
