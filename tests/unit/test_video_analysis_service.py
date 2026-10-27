"""Unit tests for video_analysis_service (probe, transcode, ffmpeg discovery, and replay)."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
import cv2
import numpy as np

from basketball.services.video_analysis_service import (
    find_ffmpeg,
    probe_video,
    prepare_video_for_analysis,
    make_browser_replay,
    MIN_DURATION_SECONDS,
    MAX_DURATION_SECONDS,
    BROWSER_SAFE_CODECS,
)


def _generate_test_clip(path: str, frames: int = 30, size: tuple = (320, 240), fps: float = 30.0) -> None:
    """Generate a clean synthetic MP4 video file using OpenCV."""
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, size)
    for i in range(frames):
        img = np.full((size[1], size[0], 3), (i * 8) % 256, dtype=np.uint8)
        writer.write(img)
    writer.release()


class TestVideoAnalysisService(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_vas_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_find_ffmpeg(self):
        """find_ffmpeg must locate either system ffmpeg or imageio_ffmpeg binary."""
        ffmpeg = find_ffmpeg()
        self.assertIsNotNone(ffmpeg, "find_ffmpeg() should find an executable ffmpeg via imageio_ffmpeg or PATH")
        self.assertTrue(os.path.exists(ffmpeg), f"Returned ffmpeg path does not exist on disk: {ffmpeg}")

    def test_probe_video_valid(self):
        """probe_video correctly extracts metadata from an OpenCV-readable video."""
        clip_path = os.path.join(self.temp_dir, "valid.mp4")
        _generate_test_clip(clip_path, frames=45, size=(320, 240), fps=30.0)

        meta = probe_video(clip_path)
        self.assertEqual(meta["frame_count"], 45)
        self.assertEqual(meta["width"], 320)
        self.assertEqual(meta["height"], 240)
        self.assertAlmostEqual(meta["fps"], 30.0, places=1)
        self.assertAlmostEqual(meta["duration_seconds"], 1.5, places=2)
        self.assertIn("codec", meta)

    def test_probe_video_nonexistent(self):
        """probe_video raises ValueError on missing file."""
        with self.assertRaises(ValueError) as ctx:
            probe_video(os.path.join(self.temp_dir, "does_not_exist.mp4"))
        self.assertIn("could not be opened", str(ctx.exception).lower())

    def test_probe_video_too_short(self):
        """probe_video rejects clips shorter than MIN_DURATION_SECONDS."""
        clip_path = os.path.join(self.temp_dir, "short.mp4")
        _generate_test_clip(clip_path, frames=5, size=(160, 120), fps=30.0)  # ~0.16s

        with self.assertRaises(ValueError) as ctx:
            probe_video(clip_path)
        self.assertIn("only", str(ctx.exception).lower())
        self.assertIn("record at least", str(ctx.exception).lower())

    def test_prepare_video_direct_path(self):
        """prepare_video_for_analysis returns metadata and None for valid directly-readable MP4."""
        clip_path = os.path.join(self.temp_dir, "direct.mp4")
        _generate_test_clip(clip_path, frames=30, size=(320, 240), fps=30.0)

        meta, converted = prepare_video_for_analysis(clip_path, self.temp_dir)
        self.assertIsNone(converted, "Directly readable video should not produce a temporary transcode")
        self.assertEqual(meta["frame_count"], 30)

    def test_prepare_video_transcode_fallback(self):
        """prepare_video_for_analysis bridges unreadable videos via FFmpeg transcode."""
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            self.skipTest("FFmpeg unavailable")

        # Create a test webm using FFmpeg
        webm_path = os.path.join(self.temp_dir, "browser_recording.webm")
        import subprocess
        cmd = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=30",
            "-c:v", "libvpx-vp9", webm_path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"FFmpeg failed to create test webm: {res.stderr}")

        # Test prepare_video_for_analysis on this webm
        meta, converted = prepare_video_for_analysis(webm_path, self.temp_dir)
        self.assertGreaterEqual(meta["frame_count"], 50)
        self.assertEqual(meta["width"], 320)
        self.assertEqual(meta["height"], 240)
        if converted:
            self.assertTrue(os.path.exists(converted), "Converted MP4 file must exist")
            # Cleanup
            Path(converted).unlink(missing_ok=True)

    def test_make_browser_replay_safe_codec(self):
        """make_browser_replay returns None when file is already browser safe."""
        clip_path = os.path.join(self.temp_dir, "safe.mp4")
        _generate_test_clip(clip_path, frames=30)
        metadata = {"codec": "h264", "height": 720}

        replay_path = make_browser_replay(clip_path, metadata, self.temp_dir)
        self.assertIsNone(replay_path, "H.264 MP4 should not require a replay copy")


if __name__ == "__main__":
    unittest.main()
