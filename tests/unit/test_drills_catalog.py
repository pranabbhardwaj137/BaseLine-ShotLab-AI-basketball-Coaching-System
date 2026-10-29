"""Unit tests for basketball.coaching.drills_catalog."""

import unittest
from pathlib import Path

from basketball.coaching.drills_catalog import (
    CATALOG_VERSION,
    DRILLS_CATALOG,
    get_catalog,
    get_drill_by_id,
)


class TestDrillsCatalog(unittest.TestCase):
    def test_catalog_structure(self):
        self.assertTrue(CATALOG_VERSION.startswith("drills-catalog"))
        self.assertEqual(len(DRILLS_CATALOG), 4)
        for drill in DRILLS_CATALOG:
            self.assertIn("id", drill)
            self.assertIn("name", drill)
            self.assertIn("category", drill)
            self.assertIn("difficulty", drill)
            self.assertIn("video", drill)
            self.assertIn("how", drill)
            self.assertIn("cues", drill)
            self.assertIn("form_checks", drill)
            self.assertIn("skills", drill)

    def test_get_catalog_all(self):
        cat = get_catalog()
        self.assertEqual(cat["version"], CATALOG_VERSION)
        self.assertEqual(cat["total"], 4)
        self.assertEqual(len(cat["drills"]), 4)

    def test_get_catalog_filter_difficulty(self):
        beginner = get_catalog(difficulty="beginner")
        self.assertEqual(beginner["total"], 2)
        for d in beginner["drills"]:
            self.assertEqual(d["difficulty"], "beginner")

        intermediate = get_catalog(difficulty="intermediate")
        self.assertEqual(intermediate["total"], 2)
        for d in intermediate["drills"]:
            self.assertEqual(d["difficulty"], "intermediate")

        empty = get_catalog(difficulty="advanced")
        self.assertEqual(empty["total"], 0)

    def test_get_catalog_filter_category(self):
        dribbling = get_catalog(category="dribbling")
        self.assertEqual(dribbling["total"], 4)

        shooting = get_catalog(category="shooting")
        self.assertEqual(shooting["total"], 0)

    def test_get_drill_by_id(self):
        pound = get_drill_by_id("pound_dribble")
        self.assertIsNotNone(pound)
        self.assertEqual(pound["name"], "Pound Dribble")

        missing = get_drill_by_id("non_existent_drill")
        self.assertIsNone(missing)

    def test_drill_videos_exist_on_disk(self):
        web_drills_dir = Path(__file__).resolve().parents[2] / "web" / "drills"
        for drill in DRILLS_CATALOG:
            video_file = web_drills_dir / drill["video"]
            self.assertTrue(
                video_file.exists(),
                f"Reference video {drill['video']} missing from {web_drills_dir}",
            )
            self.assertGreater(video_file.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()

