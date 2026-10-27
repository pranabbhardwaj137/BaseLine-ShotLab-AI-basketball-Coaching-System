"""
test_sync_split_annotations.py - Unit tests for sync_split_annotations.py
"""

import os
import json
import tempfile
import unittest
import shutil

from basketball.persistence.shot_lab_db import ShotLabDB
try:
    from scripts.sync_split_annotations import sync_annotations_to_db
except ImportError:
    from sync_split_annotations import sync_annotations_to_db


class TestSyncSplitAnnotations(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_shot_lab.db")
        self.db = ShotLabDB(self.db_path)

        # Create dummy video file
        self.raw_dir = os.path.join(self.tmp_dir.name, "raw_clips")
        os.makedirs(self.raw_dir, exist_ok=True)
        self.dummy_video = os.path.join(self.raw_dir, "test_clip.mp4")
        with open(self.dummy_video, "wb") as f:
            f.write(b"\x00" * 1024)

        # Create dummy annotation json
        self.ann_json = os.path.join(self.tmp_dir.name, "test_annotations.json")
        self.test_data = {
            "version": "1.0.0",
            "clips": [
                {
                    "clip_id": "clip_001",
                    "file": self.dummy_video,
                    "metadata": {
                        "player_id": "test_player",
                        "camera_view": "side_90",
                        "fps": 30.0
                    },
                    "shots": [
                        {
                            "shot_id": "shot_01",
                            "events": {
                                "shot_start_frame": 10,
                                "peak_dip_frame": 20,
                                "set_point_frame": 30,
                                "release_frame": 40,
                                "follow_through_frame": 50
                            },
                            "outcome": {
                                "result": "made",
                                "rim_contact": "swish"
                            }
                        }
                    ]
                }
            ]
        }
        with open(self.ann_json, "w", encoding="utf-8") as f:
            json.dump(self.test_data, f)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_missing_json_raises(self):
        with self.assertRaises(FileNotFoundError):
            sync_annotations_to_db(json_path="non_existent_file.json", db_path=self.db_path, export_after_sync=False)

    def test_missing_video_raises_fail_fast(self):
        bad_json = os.path.join(self.tmp_dir.name, "bad.json")
        with open(bad_json, "w", encoding="utf-8") as f:
            json.dump({
                "clips": [{
                    "clip_id": "missing_clip",
                    "file": "missing_video_file_xyz.mp4",
                    "metadata": {}
                }]
            }, f)

        with self.assertRaises(FileNotFoundError):
            sync_annotations_to_db(json_path=bad_json, db_path=self.db_path, export_after_sync=False)

    def test_successful_sync_and_idempotence(self):
        # First sync
        res1 = sync_annotations_to_db(
            json_path=self.ann_json,
            db_path=self.db_path,
            export_after_sync=False
        )
        self.assertEqual(res1["status"], "SUCCESS")
        self.assertEqual(res1["clips_synced"], 1)
        self.assertEqual(res1["new_intervals_synced"], 1)

        # Check DB records
        clip = self.db.get_labeled_clip("test_clip")
        self.assertIsNotNone(clip)
        self.assertEqual(clip["player_id"], "test_player")

        ann = self.db.get_clip_annotations("test_clip")
        intervals = ann.get("intervals", [])
        self.assertEqual(len(intervals), 1)
        self.assertEqual(intervals[0]["start_frame"], 10)
        self.assertEqual(intervals[0]["release_frame"], 40)
        self.assertEqual(intervals[0]["outcome"], "make")

        # Second sync: should be idempotent and add 0 new intervals
        res2 = sync_annotations_to_db(
            json_path=self.ann_json,
            db_path=self.db_path,
            export_after_sync=False
        )
        self.assertEqual(res2["new_intervals_synced"], 0)
        ann2 = self.db.get_clip_annotations("test_clip")
        self.assertEqual(len(ann2.get("intervals", [])), 1)


if __name__ == "__main__":
    unittest.main()
