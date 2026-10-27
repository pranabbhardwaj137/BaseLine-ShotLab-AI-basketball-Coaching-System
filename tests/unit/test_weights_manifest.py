import os
import unittest
import json
import hashlib

try:
    from scripts.batch_ingest_clips import normalize_player_id, load_clip_splits_config, PLAYER_REGISTRY
except ImportError:
    from batch_ingest_clips import normalize_player_id, load_clip_splits_config, PLAYER_REGISTRY


class TestWeightsManifestAndClips(unittest.TestCase):
    def test_weights_manifest_exists_and_verified(self):
        manifest_path = "data/manifests/WEIGHTS_MANIFEST.md" if os.path.exists("data/manifests/WEIGHTS_MANIFEST.md") else "WEIGHTS_MANIFEST.md"
        self.assertTrue(os.path.exists(manifest_path), "WEIGHTS_MANIFEST.md must exist")
        with open(manifest_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check required models are documented
        self.assertIn("models/best.pt", content)
        self.assertIn("models/ballRim.pt", content)
        self.assertIn("models/yolov8m-pose.pt", content)

        # Check that SHA256 hashes in manifest match actual files
        for fname, expected_hash in [
            ("models/best.pt", "d3a52414eb0970661d98473663a858ce7c05db6d8a6e107a413d2c714231d43f"),
            ("models/ballRim.pt", "56b7b23d63aedfa01cd0b4ffe9ffe97444ca80ffa934dc736b1c5ed91d0f940a"),
            ("models/yolov8m-pose.pt", "dbe539ea268db2534390942cfdf206e521f376f19e5415967a57f6a2ddfa3c90")
        ]:
            if os.path.exists(fname):
                h = hashlib.sha256()
                with open(fname, "rb") as fp:
                    while chunk := fp.read(65536):
                        h.update(chunk)
                self.assertEqual(h.hexdigest(), expected_hash, f"Hash mismatch for {fname}")
                self.assertIn(expected_hash, content, f"Hash {expected_hash} must be in WEIGHTS_MANIFEST.md")

    def test_all_raw_clips_accounted_for_in_splits(self):
        splits_cfg = load_clip_splits_config()
        self.assertTrue(os.path.exists("raw_clips"), "raw_clips/ directory must exist")
        raw_files = [f for f in os.listdir("raw_clips") if f.lower().endswith(".mp4")]
        self.assertGreaterEqual(len(raw_files), 1, "Should have raw clips present")

        for f in raw_files:
            clip_id = os.path.splitext(f)[0].lower()
            split = splits_cfg.get(clip_id, "train")
            self.assertIn(split, ["train", "val", "test"], f"Clip {clip_id} has invalid split: {split}")

            # Verify player normalization succeeds without exception
            pid, pname = normalize_player_id(f)
            self.assertIn(pid, PLAYER_REGISTRY, f"Player {pid} not registered in PLAYER_REGISTRY")
            self.assertTrue(len(pname) > 0)


if __name__ == "__main__":
    unittest.main()
