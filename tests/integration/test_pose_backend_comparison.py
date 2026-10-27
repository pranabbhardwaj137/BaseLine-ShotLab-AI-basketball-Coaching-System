import os
import unittest
import json
import tempfile
import numpy as np

try:
    from evaluation.evaluate_pose_backends import SHARED_JOINTS, load_yolo_pose, evaluate_pose_backends
except ImportError:
    from evaluate_pose_backends import SHARED_JOINTS, load_yolo_pose, evaluate_pose_backends


class TestPoseBackendComparison(unittest.TestCase):
    def test_shared_joints_topology(self):
        self.assertEqual(len(SHARED_JOINTS), 12)
        for name, mapping in SHARED_JOINTS.items():
            self.assertIn("mp", mapping)
            self.assertIn("yolo", mapping)
            self.assertTrue(0 <= mapping["mp"] <= 32)
            self.assertTrue(0 <= mapping["yolo"] <= 16)

    def test_load_yolo_pose(self):
        try:
            import ultralytics
        except ImportError:
            self.skipTest("ultralytics not installed (optional YOLO Pose dependency)")
        yolo_model = load_yolo_pose("models/yolov8m-pose.pt")
        self.assertIsNotNone(yolo_model, "Should successfully load models/yolov8m-pose.pt")

    def test_evaluate_pose_backends_generates_valid_report(self):
        temp_out = tempfile.mktemp(suffix=".json")
        try:
            # Run comparison on 1 short clip for 10 frames
            test_clip = "raw_clips/mikeddunnstud1.mp4"
            if os.path.exists(test_clip):
                report = evaluate_pose_backends(
                    clips=[test_clip],
                    yolo_model_path="models/yolov8m-pose.pt",
                    max_frames_per_clip=10,
                    output_report_path=temp_out
                )
                self.assertIsNotNone(report)
                self.assertEqual(report["benchmark"], "MediaPipe_vs_YOLOv8_Pose_Comparative_Study")
                self.assertEqual(len(report["clips_evaluated"]), 1)
                clip_res = report["clips_evaluated"][0]
                self.assertIn("per_joint_metrics", clip_res)
                self.assertEqual(len(clip_res["per_joint_metrics"]), 12)
        finally:
            if os.path.exists(temp_out):
                os.remove(temp_out)


if __name__ == "__main__":
    unittest.main()
