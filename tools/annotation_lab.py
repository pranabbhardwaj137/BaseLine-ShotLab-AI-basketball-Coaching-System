"""
annotation_lab.py - Developer Model Lab Video Scrubber & Annotation Tool.

OpenCV-based desktop annotation environment for:
 - Frame-accurate scrubbing and keyframe marking (dip, set, release, follow-through)
 - Dual-lane timeline visualization (Cyan machine proposals vs. Amber human ground truth)
 - Machine proposal auto-detection via heuristic Pose/Kinematic detector (Press 'R')
 - Live MediaPipe 33-point pose skeleton and elbow angle overlay toggle (Press 'P')
 - Complete on-screen keyboard shortcut reference & cheat sheet (Press 'H')
 - Responsive UI canvas supporting landscape (1080p, 4K) and portrait (9:16) video feeds
 - Interactive outcome tagging (make, miss, unknown)
 - Hard negative interval annotation (8-class taxonomy)
 - Proposal accept/discard workflows
 - Scriptable / Headless execution mode for automated testing and CI pipelines
"""

from __future__ import annotations
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import cv2
import uuid
import copy
import argparse
import numpy as np
from typing import Dict, Any, List, Optional, Tuple
from basketball.persistence.shot_lab_db import ShotLabDB, TAXONOMY_HARD_NEGATIVES, TAXONOMY_ALL_ACTIONS
from basketball.configs.shot_types import resolve_shot_type


COLOR_BGR_CYAN = (255, 210, 0)       # #00d2ff - Machine Proposals
COLOR_BGR_AMBER = (0, 176, 255)      # #ffb000 - Human Ground Truth
COLOR_BGR_WHITE = (255, 255, 255)
COLOR_BGR_GRAY = (140, 140, 140)
COLOR_BGR_DARK_BG = (24, 22, 22)
COLOR_BGR_SELECTION = (120, 240, 255)
COLOR_BGR_GREEN = (0, 230, 80)
COLOR_BGR_RED = (60, 60, 245)
COLOR_BGR_BLUE = (245, 130, 40)
COLOR_BGR_PURPLE = (220, 60, 210)
COLOR_BGR_MAGENTA = (200, 60, 240)


SKELETON_CONNECTIONS = [
    # Torso
    (11, 12), (11, 23), (12, 24), (23, 24),
    # Arms
    (11, 13), (13, 15), (12, 14), (14, 16),
    # Wrists / Hands
    (15, 17), (15, 19), (15, 21), (16, 18), (16, 20), (16, 22),
    # Legs
    (23, 25), (25, 27), (24, 26), (26, 28),
    # Feet
    (27, 29), (27, 31), (28, 30), (28, 32),
    # Head
    (0, 1), (1, 2), (2, 3), (3, 7), (0, 4), (4, 5), (5, 6), (6, 8)
]


class AnnotationLab:
    """Core interactive and headless video annotation engine."""

    def __init__(
        self,
        video_path: str,
        clip_id: Optional[str] = None,
        player_id: str = "dev_player",
        split: str = "train",
        db_path: str = "shot_lab.db",
        headless: bool = False,
        synthetic: bool = False,
        auto_detect: bool = False,
        shot_type_id: str = "catch_and_shoot",
    ):
        self.video_path = video_path
        self.synthetic = synthetic
        self.headless = headless
        self.player_id = player_id
        self.split = split
        self.shot_type_id = resolve_shot_type(shot_type_id)
        self.db = ShotLabDB(db_path)

        # Derive or validate clip_id
        if not clip_id:
            base_name = os.path.splitext(os.path.basename(video_path))[0]
            self.clip_id = f"clip_{base_name}"
        else:
            self.clip_id = clip_id

        # Verify video file existence
        if not os.path.exists(video_path):
            if not self.synthetic:
                raise FileNotFoundError(
                    f"[DATA INTEGRITY VIOLATION per AGENTS.md]\n"
                    f"Video file '{video_path}' does not exist on disk.\n"
                    f"Please verify or supply video footage at: '{os.path.abspath(video_path)}'\n"
                    f"Or pass --synthetic if running test fixtures."
                )
            else:
                self.cap = None
                self.width = 640
                self.height = 360
                self.frame_count = 300
                self.fps = 30.0
        else:
            self.cap = cv2.VideoCapture(video_path)
            if not self.cap.isOpened():
                raise RuntimeError(f"Unable to open video file with OpenCV: '{video_path}'")
            self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
            self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 360
            self.frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 100
            self.fps = float(self.cap.get(cv2.CAP_PROP_FPS)) or 30.0
            if self.frame_count <= 0:
                self.frame_count = 100

        # UI Toggles
        self.show_pose: bool = False
        self.show_help: bool = False
        self.pose_engine = None
        self.pose_cache: Dict[int, Any] = {}

        # State tracking
        self.current_frame = 0
        self.is_playing = False
        self.active_in: Optional[int] = None
        self.active_out: Optional[int] = None
        self.active_dip: Optional[int] = None
        self.active_set: Optional[int] = None
        self.active_release: Optional[int] = None
        self.active_follow_through: Optional[int] = None
        self.active_outcome: str = "make"
        self.active_negative_idx: int = 0
        self.status_message: str = "Ready. [H] Help Cheatsheet | [P] Pose Skeleton | [R] Auto-Detect Proposals"

        # Undo stack (stores list snapshots of human_intervals)
        self.undo_stack: List[List[Dict[str, Any]]] = []

        # Load / initialize DB clip record & annotations
        self._init_db_records(auto_detect=auto_detect)

    def _init_db_records(self, auto_detect: bool = False) -> None:
        """Register clip if missing and load proposals and intervals."""
        existing_clip = self.db.get_labeled_clip(self.clip_id)
        if not existing_clip:
            self.db.register_labeled_clip(
                clip_id=self.clip_id,
                file_path=self.video_path,
                player_id=self.player_id,
                camera_view="side_90",
                shot_type_id=self.shot_type_id,
                shot_style="jump_shot",
                fps=self.fps,
                frame_count=self.frame_count,
                width=self.width,
                height=self.height,
                split=self.split
            )

        data = self.db.get_clip_annotations(self.clip_id)
        self.machine_proposals: List[Dict[str, Any]] = data.get("proposals", [])
        self.human_intervals: List[Dict[str, Any]] = data.get("intervals", [])

        # Auto-detect proposals if M-Lane is empty and enabled or short video
        if len(self.machine_proposals) == 0:
            if auto_detect or (not self.synthetic and self.frame_count <= 350):
                self.auto_detect_machine_proposals()
            elif not self.synthetic:
                self.status_message = "M-Lane is empty. Press [R] to auto-detect candidate shots with MediaPipe AI."

    def _push_undo(self) -> None:
        """Save a snapshot of current human intervals to the undo stack."""
        self.undo_stack.append(copy.deepcopy(self.human_intervals))
        if len(self.undo_stack) > 50:
            self.undo_stack.pop(0)

    # -------------------------------------------------------------------------
    # MediaPipe Pose Engine & Skeleton Overlay
    # -------------------------------------------------------------------------

    def _ensure_pose_engine(self):
        """Lazy load MediaPipe PoseEngine if not already initialized."""
        if self.pose_engine is None and not self.synthetic:
            try:
                from basketball.core.pose_engine import PoseEngine
                self.pose_engine = PoseEngine(smoothing_alpha=0.35)
            except Exception as e:
                self.status_message = f"PoseEngine initialization failed: {e}"
        return self.pose_engine

    def get_pose_for_frame(self, frame_idx: int, frame_bgr: Optional[np.ndarray] = None) -> Optional[Dict[str, Any]]:
        """Get MediaPipe landmarks for frame_idx, utilizing cache for smooth scrubbing."""
        if self.synthetic:
            return None

        if frame_idx in self.pose_cache:
            return self.pose_cache[frame_idx]

        engine = self._ensure_pose_engine()
        if engine is None:
            return None

        if frame_bgr is None:
            frame_bgr = self.get_current_frame_image()

        timestamp_ms = int(frame_idx * (1000.0 / self.fps))
        out = engine.process(frame_bgr, timestamp_ms)
        if out is not None:
            self.pose_cache[frame_idx] = out
        return out

    def draw_pose_skeleton(self, img: np.ndarray, pose_out: Dict[str, Any]) -> None:
        """Draw 33 body landmarks, skeleton bones, and shooting elbow angle callout."""
        if not pose_out or "smoothed_landmarks" not in pose_out:
            return

        landmarks = pose_out["smoothed_landmarks"]
        valid = pose_out.get("valid", {})
        h, w = img.shape[:2]

        # Draw bone connections
        for p1, p2 in SKELETON_CONNECTIONS:
            if p1 in landmarks and p2 in landmarks:
                v1 = valid.get(p1, False)
                v2 = valid.get(p2, False)
                if v1 and v2:
                    pt1 = (int(landmarks[p1]["norm_x"] * w), int(landmarks[p1]["norm_y"] * h))
                    pt2 = (int(landmarks[p2]["norm_x"] * w), int(landmarks[p2]["norm_y"] * h))
                    cv2.line(img, pt1, pt2, (0, 240, 100), 2)

        # Draw landmark joint points
        for idx, lm in landmarks.items():
            pt = (int(lm["norm_x"] * w), int(lm["norm_y"] * h))
            is_val = valid.get(idx, False)
            color = (255, 210, 0) if is_val else (0, 140, 255)
            cv2.circle(img, pt, 4, color, -1)

        # Compute biomechanical angles if analyzer is available
        try:
            from basketball.core.analyzer import compute_all_angles
            angles = compute_all_angles(
                landmarks, valid,
                world_landmarks=pose_out.get("world_landmarks"),
                min_visibility=0.40
            )
            if angles and angles.get("elbow_shooting_2d") is not None:
                elbow_angle = angles["elbow_shooting_2d"]
                side = angles.get("shooting_side", "right")
                elbow_idx = 13 if side == "left" else 14

                if elbow_idx in landmarks and valid.get(elbow_idx, False):
                    ex = int(landmarks[elbow_idx]["norm_x"] * w)
                    ey = int(landmarks[elbow_idx]["norm_y"] * h)

                    # Draw callout pill next to elbow
                    box_w, box_h = 160, 26
                    bx1 = max(5, min(w - box_w - 5, ex + 12))
                    by1 = max(5, min(h - box_h - 5, ey - 28))
                    cv2.rectangle(img, (bx1, by1), (bx1 + box_w, by1 + box_h), (25, 25, 25), -1)
                    cv2.rectangle(img, (bx1, by1), (bx1 + box_w, by1 + box_h), COLOR_BGR_CYAN, 1)
                    cv2.putText(
                        img, f"Elbow: {elbow_angle:.1f} deg",
                        (bx1 + 8, by1 + 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, COLOR_BGR_WHITE, 1
                    )
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Auto-Detect Machine Proposals (Cyan M-Lane)
    # -------------------------------------------------------------------------

    def auto_detect_machine_proposals(self, force: bool = False) -> int:
        """Run heuristic shot detector across video to populate Cyan M-Lane proposals."""
        if self.synthetic:
            if not self.machine_proposals or force:
                mock_prop = [{
                    "proposal_id": f"prop_auto_{uuid.uuid4().hex[:6]}",
                    "detector_name": "heuristic_detector_v1",
                    "detector_version": "1.0.0",
                    "start_frame": 20,
                    "end_frame": 60,
                    "dip_frame": 30,
                    "set_frame": 42,
                    "release_frame": 50,
                    "confidence": 0.88,
                    "status": "proposed"
                }]
                self.db.save_machine_proposals(self.clip_id, mock_prop)
                self.machine_proposals = self.db.get_machine_proposals(self.clip_id)
                self.status_message = "Generated synthetic candidate proposal on Cyan M-Lane."
                return len(mock_prop)
            return len(self.machine_proposals)

        if not self.video_path or not os.path.exists(self.video_path):
            return 0

        if self.machine_proposals and not force:
            return len(self.machine_proposals)

        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            return 0

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 100

        try:
            from basketball.core.pose_engine import PoseEngine
            from basketball.core.analyzer import compute_all_angles, ShotPhaseDetector
            engine = PoseEngine(smoothing_alpha=0.35)
            detector = ShotPhaseDetector()
        except Exception as e:
            self.status_message = f"Detector unavailable: {e}"
            cap.release()
            return 0

        f_idx = 0
        cur_start = None
        cur_dip = None
        cur_set = None
        cur_release = None
        proposals = []

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            t_ms = int(f_idx * (1000.0 / fps))
            out = engine.process(frame, t_ms)
            if out:
                self.pose_cache[f_idx] = out
                angles = compute_all_angles(out['smoothed_landmarks'], out['valid'], world_landmarks=out.get('world_landmarks'))
                state, vy, ve = detector.update(out['smoothed_landmarks'], angles, t_ms)

                if state == 'idle' and cur_start is not None and (f_idx - cur_start) > 90:
                    cur_start = None
                    cur_dip = None
                    cur_set = None
                    cur_release = None

                if state in ('preparing', 'set_point') and cur_start is None:
                    cur_start = f_idx
                if state == 'preparing':
                    cur_dip = f_idx
                elif state == 'set_point':
                    cur_set = f_idx
                elif state == 'releasing':
                    if cur_release is None:
                        cur_release = f_idx
                elif state == 'follow_through' and cur_start is not None:
                    start_f = max(0, cur_start)
                    end_f = min(total - 1, f_idx)
                    dip_f = cur_dip if cur_dip is not None and start_f <= cur_dip <= end_f else None
                    set_f = cur_set if cur_set is not None and start_f <= cur_set <= end_f else None
                    rel_f = cur_release if cur_release is not None and start_f <= cur_release <= end_f else None

                    # Check ordering
                    if dip_f is not None and set_f is not None and dip_f > set_f:
                        dip_f = None
                    if set_f is not None and rel_f is not None and set_f > rel_f:
                        set_f = None
                    if dip_f is not None and rel_f is not None and dip_f > rel_f:
                        dip_f = None

                    if 5 <= (end_f - start_f) <= 120:
                        prop = {
                            "proposal_id": f"prop_{uuid.uuid4().hex[:6]}",
                            "detector_name": "heuristic_detector_v1",
                            "detector_version": "1.0.0",
                            "start_frame": start_f,
                            "end_frame": end_f,
                            "dip_frame": dip_f,
                            "set_frame": set_f,
                            "release_frame": rel_f,
                            "confidence": 0.85,
                            "status": "proposed"
                        }
                        proposals.append(prop)
                    cur_start = None
                    cur_dip = None
                    cur_set = None
                    cur_release = None
            f_idx += 1

        cap.release()
        engine.close()

        if proposals:
            self.db.save_machine_proposals(self.clip_id, proposals)
            self.machine_proposals = self.db.get_machine_proposals(self.clip_id)
            self.status_message = f"Auto-detected {len(proposals)} proposal(s) on Cyan M-Lane! Press [A] to accept, [D] to discard."
        else:
            self.status_message = "Detector scan completed: 0 candidate shots found in this clip."

        return len(proposals)

    # -------------------------------------------------------------------------
    # Navigation & Seek Actions
    # -------------------------------------------------------------------------

    def step_frame(self, delta: int) -> int:
        """Step current frame by delta, clamped to bounds."""
        self.current_frame = max(0, min(self.frame_count - 1, self.current_frame + delta))
        return self.current_frame

    def seek_frame(self, frame_idx: int) -> int:
        """Seek directly to frame index."""
        self.current_frame = max(0, min(self.frame_count - 1, frame_idx))
        return self.current_frame

    def mark_in(self, frame_idx: Optional[int] = None) -> int:
        """Set in mark for current interval."""
        self.active_in = self.current_frame if frame_idx is None else frame_idx
        self.status_message = f"Marked In at frame {self.active_in}"
        return self.active_in

    def mark_out(self, frame_idx: Optional[int] = None) -> int:
        """Set out mark for current interval."""
        self.active_out = self.current_frame if frame_idx is None else frame_idx
        self.status_message = f"Marked Out at frame {self.active_out}"
        return self.active_out

    def set_keyframe(self, key_type: str, frame_idx: Optional[int] = None) -> Optional[int]:
        """Set dip, set, release, or follow_through keyframe."""
        f = self.current_frame if frame_idx is None else frame_idx
        if key_type == "dip":
            self.active_dip = f
            self.status_message = f"Dip keyframe set at frame {f}"
        elif key_type == "set":
            self.active_set = f
            self.status_message = f"Set-point keyframe set at frame {f}"
        elif key_type == "release":
            self.active_release = f
            self.status_message = f"Release keyframe set at frame {f}"
        elif key_type == "follow_through":
            self.active_follow_through = f
            self.status_message = f"Follow-through keyframe set at frame {f}"
        return f

    def cycle_negative_taxonomy(self) -> str:
        """Cycle through the 8-class hard negative actions."""
        self.active_negative_idx = (self.active_negative_idx + 1) % len(TAXONOMY_HARD_NEGATIVES)
        selected = TAXONOMY_HARD_NEGATIVES[self.active_negative_idx]
        self.status_message = f"Selected negative action: '{selected}'"
        return selected

    def set_outcome(self, outcome: str) -> str:
        """Set outcome to 'make', 'miss', or 'unknown'."""
        out = outcome.lower()
        if out in ("m", "make"):
            self.active_outcome = "make"
        elif out in ("x", "miss"):
            self.active_outcome = "miss"
        elif out in ("u", "unknown"):
            self.active_outcome = "unknown"
        self.status_message = f"Active outcome set to: '{self.active_outcome.upper()}'"
        return self.active_outcome

    # -------------------------------------------------------------------------
    # Interval Commitments & Machine Proposal Management
    # -------------------------------------------------------------------------

    def commit_shot(self) -> Dict[str, Any]:
        """Commit active interval as human ground-truth shot_event."""
        start = self.active_in if self.active_in is not None else max(0, self.current_frame - 20)
        end = self.active_out if self.active_out is not None else min(self.frame_count - 1, self.current_frame + 20)

        if start > end:
            start, end = end, start

        self._push_undo()

        # Validate keyframes: must fall within [start, end] and respect chronology
        dip = self.active_dip if self.active_dip is not None and start <= self.active_dip <= end else None
        set_f = self.active_set if self.active_set is not None and start <= self.active_set <= end else None
        rel = self.active_release if self.active_release is not None and start <= self.active_release <= end else None
        ft = self.active_follow_through if self.active_follow_through is not None and start <= self.active_follow_through <= end else None

        # Check relative ordering
        if dip is not None and set_f is not None and dip > set_f:
            dip, set_f = None, None
        if set_f is not None and rel is not None and set_f > rel:
            set_f = None
        if dip is not None and rel is not None and dip > rel:
            dip = None
        if rel is not None and ft is not None and rel > ft:
            ft = None

        intv = {
            "interval_id": f"shot_{uuid.uuid4().hex[:8]}",
            "clip_id": self.clip_id,
            "interval_type": "shot",
            "action_class": "shot_event",
            "start_frame": start,
            "end_frame": end,
            "dip_frame": dip,
            "set_frame": set_f,
            "release_frame": rel,
            "follow_through_frame": ft,
            "outcome": self.active_outcome,
            "annotator_id": "human_reviewer",
            "review_status": "verified"
        }
        self.human_intervals.append(intv)
        self.human_intervals.sort(key=lambda x: x["start_frame"])

        # Reset active working marks
        self.active_in = None
        self.active_out = None
        self.active_dip = None
        self.active_set = None
        self.active_release = None
        self.active_follow_through = None

        self.status_message = f"Committed Shot [{start}..{end}] ({self.active_outcome.upper()})"
        return intv

    def commit_negative(self, action_class: Optional[str] = None) -> Dict[str, Any]:
        """Commit active interval as a hard negative action."""
        cls_name = action_class or TAXONOMY_HARD_NEGATIVES[self.active_negative_idx]
        start = self.active_in if self.active_in is not None else max(0, self.current_frame - 15)
        end = self.active_out if self.active_out is not None else min(self.frame_count - 1, self.current_frame + 15)

        if start > end:
            start, end = end, start

        self._push_undo()

        intv = {
            "interval_id": f"neg_{uuid.uuid4().hex[:8]}",
            "clip_id": self.clip_id,
            "interval_type": "hard_negative",
            "action_class": cls_name,
            "start_frame": start,
            "end_frame": end,
            "dip_frame": None,
            "set_frame": None,
            "release_frame": None,
            "follow_through_frame": None,
            "outcome": "none",
            "annotator_id": "human_reviewer",
            "review_status": "verified"
        }
        self.human_intervals.append(intv)
        self.human_intervals.sort(key=lambda x: x["start_frame"])

        self.active_in = None
        self.active_out = None
        self.status_message = f"Committed Negative '{cls_name}' [{start}..{end}]"
        return intv

    def get_proposal_at_frame(self, frame_idx: int) -> Optional[Dict[str, Any]]:
        """Find candidate machine proposal spanning frame_idx."""
        for p in self.machine_proposals:
            s = p.get("start_frame", 0)
            e = p.get("end_frame", 0)
            if s <= frame_idx <= e:
                return p
        return None

    def accept_proposal(self) -> Optional[Dict[str, Any]]:
        """Accept machine proposal at current frame into human lane."""
        prop = self.get_proposal_at_frame(self.current_frame)
        if not prop:
            self.status_message = "No machine proposal under playhead to accept."
            return None

        self._push_undo()
        prop["status"] = "accepted"
        self.db.update_machine_proposal_status(prop["proposal_id"], "accepted")

        # Sanitize candidate frames
        s = prop.get("start_frame", 0)
        e = prop.get("end_frame", 0)
        d = prop.get("dip_frame")
        st = prop.get("set_frame")
        r = prop.get("release_frame")

        if d is not None and not (s <= d <= e): d = None
        if st is not None and not (s <= st <= e): st = None
        if r is not None and not (s <= r <= e): r = None

        if d is not None and st is not None and d > st: d = None
        if st is not None and r is not None and st > r: st = None
        if d is not None and r is not None and d > r: d = None

        # Convert to human interval
        intv = {
            "interval_id": f"shot_from_{prop['proposal_id']}",
            "clip_id": self.clip_id,
            "interval_type": "shot",
            "action_class": "shot_event",
            "start_frame": s,
            "end_frame": e,
            "dip_frame": d,
            "set_frame": st,
            "release_frame": r,
            "follow_through_frame": None,
            "outcome": self.active_outcome,
            "annotator_id": "human_reviewer",
            "review_status": "verified"
        }
        self.human_intervals.append(intv)
        self.human_intervals.sort(key=lambda x: x["start_frame"])
        self.status_message = f"Accepted proposal {prop['proposal_id']} -> Human Shot"
        return intv

    def discard_proposal(self) -> Optional[Dict[str, Any]]:
        """Discard machine proposal at current frame."""
        prop = self.get_proposal_at_frame(self.current_frame)
        if not prop:
            self.status_message = "No machine proposal under playhead to discard."
            return None

        prop["status"] = "discarded"
        self.db.update_machine_proposal_status(prop["proposal_id"], "discarded")
        self.status_message = f"Discarded proposal {prop['proposal_id']}"
        return prop

    def undo(self) -> bool:
        """Revert last interval edit from undo stack."""
        if not self.undo_stack:
            self.status_message = "Nothing to undo."
            return False
        self.human_intervals = self.undo_stack.pop()
        self.status_message = "Undo performed: reverted last interval change."
        return True

    def save_to_database(self) -> int:
        """Persist all current human intervals and proposals to database."""
        try:
            with self.db._get_connection() as conn:
                c = conn.cursor()
                c.execute("DELETE FROM labeled_intervals WHERE clip_id = ?", (self.clip_id,))
                conn.commit()

            count = 0
            for intv in self.human_intervals:
                self.db.save_labeled_interval(intv)
                count += 1

            for prop in self.machine_proposals:
                self.db.update_machine_proposal_status(prop["proposal_id"], prop.get("status", "proposed"))

            self.status_message = f"Saved {count} interval(s) to database successfully."
            return count
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower():
                self.status_message = "DB LOCKED: Close DB Browser for SQLite and press [W] to retry."
                print(f"\n[ERROR] Database is locked! Please close DB Browser for SQLite (or other open DB tools) and press [W] to retry saving.\n")
            else:
                self.status_message = f"DB Error: {e}"
                print(f"\n[ERROR] Database error: {e}\n")
            return -1

    # -------------------------------------------------------------------------
    # High-Clarity Viewport Rendering & Studio Layout
    # -------------------------------------------------------------------------

    def get_current_frame_image(self) -> np.ndarray:
        """Fetch current frame image from VideoCapture or create placeholder."""
        if self.cap and self.cap.isOpened():
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame)
            ret, frame = self.cap.read()
            if ret and frame is not None:
                return frame
        # Fallback synthetic frame
        img = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        img[:] = (35, 35, 40)
        cv2.putText(
            img,
            f"SYNTHETIC FRAME {self.current_frame}",
            (int(self.width * 0.20), int(self.height * 0.45)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (100, 200, 100),
            2
        )
        return img

    def render_overlay(self, frame: np.ndarray) -> np.ndarray:
        """Render on-frame overlay for backwards-compatibility and unit tests."""
        h, w = frame.shape[:2]
        canvas = frame.copy()

        # Dynamic scaling based on frame resolution
        scale = max(0.4, min(w / 800.0, h / 600.0))
        tl_h = int(80 * scale)
        tl_top = max(0, h - tl_h)

        cv2.rectangle(canvas, (0, tl_top), (w, h), COLOR_BGR_DARK_BG, -1)
        cv2.line(canvas, (0, tl_top), (w, tl_top), COLOR_BGR_GRAY, 1)

        pad_x = int(35 * scale)
        tl_w = max(10, w - (2 * pad_x))
        lane_m_y = tl_top + int(25 * scale)
        lane_h_y = tl_top + int(55 * scale)

        cv2.putText(canvas, "M:", (5, lane_m_y + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4 * scale, COLOR_BGR_CYAN, 1)
        cv2.putText(canvas, "H:", (5, lane_h_y + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4 * scale, COLOR_BGR_AMBER, 1)

        def frame_to_x(f_idx: int) -> int:
            ratio = max(0.0, min(1.0, float(f_idx) / max(1, self.frame_count - 1)))
            return int(pad_x + ratio * tl_w)

        # M-Lane
        for p in self.machine_proposals:
            if p.get("status") == "discarded":
                continue
            x1 = frame_to_x(p.get("start_frame", 0))
            x2 = max(x1 + 3, frame_to_x(p.get("end_frame", 0)))
            cv2.rectangle(canvas, (x1, lane_m_y - 6), (x2, lane_m_y + 6), COLOR_BGR_CYAN, -1)

        # H-Lane
        for intv in self.human_intervals:
            x1 = frame_to_x(intv.get("start_frame", 0))
            x2 = max(x1 + 3, frame_to_x(intv.get("end_frame", 0)))
            is_shot = intv.get("interval_type") == "shot"
            col = COLOR_BGR_AMBER if is_shot else COLOR_BGR_MAGENTA
            cv2.rectangle(canvas, (x1, lane_h_y - 6), (x2, lane_h_y + 6), col, -1)

        # Playhead
        cur_x = frame_to_x(self.current_frame)
        cv2.line(canvas, (cur_x, tl_top), (cur_x, h), COLOR_BGR_WHITE, 2)

        return canvas

    def render_canvas(self, raw_frame: np.ndarray) -> np.ndarray:
        """Render high-clarity 1360x800 presentation studio with responsive video placement."""
        CANVAS_W = 1360
        CANVAS_H = 800
        canvas = np.zeros((CANVAS_H, CANVAS_W, 3), dtype=np.uint8)
        canvas[:] = (22, 20, 20)

        # Optional MediaPipe pose overlay on raw frame
        display_raw = raw_frame.copy()
        if self.show_pose:
            pose_out = self.get_pose_for_frame(self.current_frame, display_raw)
            if pose_out:
                self.draw_pose_skeleton(display_raw, pose_out)

        # ---------------------------------------------------------------------
        # 1. Video Viewport (Center Box: Y=75 to Y=625, H=550, W=1360)
        # ---------------------------------------------------------------------
        fh, fw = display_raw.shape[:2]
        max_vw = 1360
        max_vh = 550

        scale = min(max_vw / fw, max_vh / fh)
        new_w = max(1, int(fw * scale))
        new_h = max(1, int(fh * scale))

        scaled_video = cv2.resize(
            display_raw, (new_w, new_h),
            interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
        )
        x_off = (CANVAS_W - new_w) // 2
        y_off = 75 + (max_vh - new_h) // 2

        canvas[y_off:y_off + new_h, x_off:x_off + new_w] = scaled_video
        cv2.rectangle(canvas, (x_off, y_off), (x_off + new_w, y_off + new_h), (55, 55, 55), 1)

        # ---------------------------------------------------------------------
        # 2. Top Header HUD Bar (Y=0 to Y=75)
        # ---------------------------------------------------------------------
        cv2.rectangle(canvas, (0, 0), (CANVAS_W, 75), (28, 26, 26), -1)
        cv2.line(canvas, (0, 75), (CANVAS_W, 75), (60, 60, 60), 1)

        play_str = "PLAYING" if self.is_playing else "PAUSED"
        pose_str = "ON" if self.show_pose else "OFF"

        line1 = f"ShotLab | Clip: {self.clip_id} | Frame {self.current_frame}/{self.frame_count-1} | [{play_str}] | Split: {self.split.upper()} | Pose [P]: {pose_str}"
        cv2.putText(canvas, line1, (16, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.52, COLOR_BGR_WHITE, 1)

        in_str = str(self.active_in) if self.active_in is not None else "-"
        out_str = str(self.active_out) if self.active_out is not None else "-"
        dip_str = str(self.active_dip) if self.active_dip is not None else "-"
        set_str = str(self.active_set) if self.active_set is not None else "-"
        rel_str = str(self.active_release) if self.active_release is not None else "-"
        ft_str = str(self.active_follow_through) if self.active_follow_through is not None else "-"
        active_neg = TAXONOMY_HARD_NEGATIVES[self.active_negative_idx]

        line2 = (
            f"In: {in_str}  Out: {out_str} | Dip: {dip_str}  Set: {set_str}  Rel: {rel_str}  FT: {ft_str} | "
            f"Outcome [M/X/U]: {self.active_outcome.upper()} | Neg Class [N]: {active_neg}"
        )
        cv2.putText(canvas, line2, (16, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.48, COLOR_BGR_SELECTION, 1)

        prop_under = self.get_proposal_at_frame(self.current_frame)
        if prop_under and prop_under.get("status") != "discarded":
            prop_msg = f">> MACHINE PROPOSAL {prop_under['proposal_id']} [{prop_under['start_frame']}..{prop_under['end_frame']}] Rel:{prop_under.get('release_frame')} | Press [A] to Accept, [D] to Discard"
            cv2.putText(canvas, prop_msg, (16, 68), cv2.FONT_HERSHEY_SIMPLEX, 0.44, COLOR_BGR_CYAN, 1)
        elif len(self.machine_proposals) > 0:
            prop_msg = f"Cyan M-Lane: {len(self.machine_proposals)} proposals loaded | Press [R] to re-run auto-detection"
            cv2.putText(canvas, prop_msg, (16, 68), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (180, 180, 180), 1)
        else:
            prop_msg = "Cyan M-Lane empty. Press [R] to auto-detect candidate shot events using MediaPipe AI."
            cv2.putText(canvas, prop_msg, (16, 68), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (0, 180, 255), 1)

        # ---------------------------------------------------------------------
        # 3. Bottom Dual-Lane Timeline (Y=625 to Y=765, H=140)
        # ---------------------------------------------------------------------
        tl_top = 625
        cv2.rectangle(canvas, (0, tl_top), (CANVAS_W, 765), (26, 24, 24), -1)
        cv2.line(canvas, (0, tl_top), (CANVAS_W, tl_top), (60, 60, 60), 1)

        pad_x = 100
        tl_w = CANVAS_W - pad_x - 40
        lane_m_y = tl_top + 38   # Machine Lane
        lane_h_y = tl_top + 84   # Human Lane

        # Lane labels
        cv2.putText(canvas, "M-LANE:", (12, lane_m_y + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.48, COLOR_BGR_CYAN, 1)
        cv2.putText(canvas, "H-LANE:", (12, lane_h_y + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.48, COLOR_BGR_AMBER, 1)

        # Rail tracks
        cv2.line(canvas, (pad_x, lane_m_y), (pad_x + tl_w, lane_m_y), (50, 50, 55), 3)
        cv2.line(canvas, (pad_x, lane_h_y), (pad_x + tl_w, lane_h_y), (50, 50, 55), 3)

        def frame_to_x(f_idx: int) -> int:
            ratio = max(0.0, min(1.0, float(f_idx) / max(1, self.frame_count - 1)))
            return int(pad_x + ratio * tl_w)

        # 3a. Draw Cyan Machine Proposals (M-Lane)
        for p in self.machine_proposals:
            if p.get("status") == "discarded":
                continue
            x1 = frame_to_x(p.get("start_frame", 0))
            x2 = max(x1 + 4, frame_to_x(p.get("end_frame", 0)))
            cv2.rectangle(canvas, (x1, lane_m_y - 10), (x2, lane_m_y + 10), COLOR_BGR_CYAN, -1)
            # Release tick
            rel = p.get("release_frame")
            if rel is not None:
                xr = frame_to_x(rel)
                cv2.circle(canvas, (xr, lane_m_y), 4, COLOR_BGR_RED, -1)

            # Highlight border if playhead inside proposal
            if p.get("start_frame", 0) <= self.current_frame <= p.get("end_frame", 0):
                cv2.rectangle(canvas, (x1 - 1, lane_m_y - 11), (x2 + 1, lane_m_y + 11), COLOR_BGR_WHITE, 1)

        # 3b. Draw Amber Human Intervals (H-Lane)
        for intv in self.human_intervals:
            x1 = frame_to_x(intv.get("start_frame", 0))
            x2 = max(x1 + 4, frame_to_x(intv.get("end_frame", 0)))
            is_shot = intv.get("interval_type") == "shot"
            col = COLOR_BGR_AMBER if is_shot else COLOR_BGR_MAGENTA
            cv2.rectangle(canvas, (x1, lane_h_y - 10), (x2, lane_h_y + 10), col, -1)

            if is_shot:
                for kf_val, kf_col in [
                    (intv.get("dip_frame"), COLOR_BGR_BLUE),
                    (intv.get("set_frame"), COLOR_BGR_PURPLE),
                    (intv.get("release_frame"), COLOR_BGR_RED),
                    (intv.get("follow_through_frame"), COLOR_BGR_GREEN)
                ]:
                    if kf_val is not None:
                        xk = frame_to_x(kf_val)
                        cv2.circle(canvas, (xk, lane_h_y), 4, kf_col, -1)

        # 3c. Active Selection Band
        if self.active_in is not None and self.active_out is not None:
            sx1 = frame_to_x(min(self.active_in, self.active_out))
            sx2 = frame_to_x(max(self.active_in, self.active_out))
            overlay = canvas.copy()
            cv2.rectangle(overlay, (sx1, tl_top + 15), (sx2, tl_top + 115), COLOR_BGR_SELECTION, -1)
            cv2.addWeighted(overlay, 0.30, canvas, 0.70, 0, canvas)
        elif self.active_in is not None:
            cv2.line(canvas, (frame_to_x(self.active_in), tl_top + 15), (frame_to_x(self.active_in), tl_top + 115), COLOR_BGR_SELECTION, 2)
        elif self.active_out is not None:
            cv2.line(canvas, (frame_to_x(self.active_out), tl_top + 15), (frame_to_x(self.active_out), tl_top + 115), COLOR_BGR_SELECTION, 2)

        # 3d. Playhead Needle
        cur_x = frame_to_x(self.current_frame)
        cv2.line(canvas, (cur_x, tl_top + 10), (cur_x, tl_top + 120), COLOR_BGR_WHITE, 2)
        cv2.circle(canvas, (cur_x, tl_top + 14), 5, COLOR_BGR_WHITE, -1)

        # Keyframe Legend along timeline bottom
        leg_str = "Keyframes: [1] Dip=Blue  [2] Set=Purple  [3] Rel=Red  [4] FT=Green"
        cv2.putText(canvas, leg_str, (pad_x, tl_top + 130), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (180, 180, 180), 1)

        # ---------------------------------------------------------------------
        # 4. Bottom Footer & Status Bar (Y=765 to Y=800, H=35)
        # ---------------------------------------------------------------------
        cv2.rectangle(canvas, (0, 765), (CANVAS_W, CANVAS_H), (18, 16, 16), -1)
        cv2.line(canvas, (0, 765), (CANVAS_W, 765), (50, 50, 50), 1)

        # Status toast message
        status_col = (0, 60, 255) if ("lock" in self.status_message.lower() or "error" in self.status_message.lower()) else (0, 240, 160)
        cv2.putText(canvas, self.status_message, (16, 788), cv2.FONT_HERSHEY_SIMPLEX, 0.46, status_col, 1)

        # Quick legend
        legend = "[H] Help Card | [P] Skeleton | [R] Auto-Detect | [S] Shot | [N] Neg | [W] Save | [Q] Quit"
        cv2.putText(canvas, legend, (720, 788), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (200, 200, 200), 1)

        # ---------------------------------------------------------------------
        # 5. On-Screen Help Cheatsheet Modal (If 'H' toggled)
        # ---------------------------------------------------------------------
        if self.show_help:
            self._render_help_modal(canvas)

        return canvas

    def _render_help_modal(self, canvas: np.ndarray) -> None:
        """Render floating cheatsheet dialog on top of the viewport."""
        mx1, my1, mw, mh = 170, 95, 1020, 510
        mx2, my2 = mx1 + mw, my1 + mh

        overlay = canvas.copy()
        cv2.rectangle(overlay, (mx1, my1), (mx2, my2), (15, 15, 20), -1)
        cv2.addWeighted(overlay, 0.92, canvas, 0.08, 0, canvas)
        cv2.rectangle(canvas, (mx1, my1), (mx2, my2), COLOR_BGR_AMBER, 2)

        title = "BASKETBALL SHOT LAB ANNOTATOR - KEYBOARD CHEATSHEET"
        cv2.putText(canvas, title, (mx1 + 25, my1 + 35), cv2.FONT_HERSHEY_SIMPLEX, 0.65, COLOR_BGR_AMBER, 2)

        help_lines = [
            ("NAVIGATION & SCRUBBING:", COLOR_BGR_CYAN),
            ("  [Space]       Toggle Play / Pause playback", COLOR_BGR_WHITE),
            ("  [,] / [.]     Step -1 / +1 single frame (precision scrubbing)", COLOR_BGR_WHITE),
            ("  [<] / [>]     Jump -10 / +10 frames", COLOR_BGR_WHITE),
            ("  Top Slider    Seek across the entire video", COLOR_BGR_WHITE),
            ("", COLOR_BGR_WHITE),
            ("INTERVAL MARKING & SHOT EVENTS:", COLOR_BGR_CYAN),
            ("  [[]           Set In-Point (start frame of action)", COLOR_BGR_WHITE),
            ("  []]           Set Out-Point (end frame of action)", COLOR_BGR_WHITE),
            ("  [1] / [2]     Mark Dip Keyframe / Set-Point Keyframe", COLOR_BGR_WHITE),
            ("  [3] / [4]     Mark Release Keyframe / Follow-Through Keyframe", COLOR_BGR_WHITE),
            ("  [S]           Commit Interval as SHOT EVENT (Amber in H-Lane)", COLOR_BGR_WHITE),
            ("  [M] / [X] / [U] Set Outcome: [M]ake / Miss [X] / [U]nknown", COLOR_BGR_WHITE),
            ("", COLOR_BGR_WHITE),
            ("HARD NEGATIVES (Train AI to Reject Dribbles / Passes):", COLOR_BGR_CYAN),
            ("  [N]           Cycle 8 negative types & commit: dribble_drive, pass, pump_fake...", COLOR_BGR_WHITE),
            ("", COLOR_BGR_WHITE),
            ("MACHINE PROPOSALS & COMPUTER VISION:", COLOR_BGR_CYAN),
            ("  [R]           Run / Re-run Auto-Detector to fill Cyan M-Lane with candidate shots", COLOR_BGR_WHITE),
            ("  [A]           ACCEPT Cyan proposal under playhead -> converts to Human Shot", COLOR_BGR_WHITE),
            ("  [D]           DISCARD false detector proposal under playhead", COLOR_BGR_WHITE),
            ("  [P]           Toggle Live MediaPipe 33-Point Pose Skeleton & Elbow Angles", COLOR_BGR_WHITE),
            ("", COLOR_BGR_WHITE),
            ("WORKFLOW & SAVE:", COLOR_BGR_CYAN),
            ("  [Z] Undo last interval   |   [W] Save to database   |   [H] Toggle this help card", COLOR_BGR_WHITE),
        ]

        cur_y = my1 + 65
        for text, color in help_lines:
            if text:
                is_header = text.startswith("  ") is False and ":" in text
                scale = 0.48 if is_header else 0.42
                thick = 2 if is_header else 1
                cv2.putText(canvas, text, (mx1 + 30, cur_y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick)
            cur_y += 18

        foot = "Press [H] or [Space] anytime to dismiss this cheatsheet."
        cv2.putText(canvas, foot, (mx1 + 30, my2 - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (0, 240, 160), 1)

    # -------------------------------------------------------------------------
    # Command Dispatch (Shared by GUI & Headless Scripting)
    # -------------------------------------------------------------------------

    def execute_command(self, cmd: str) -> None:
        """Dispatch a string command (e.g. 'step:10', 'mark_in', 'commit_shot')."""
        cmd = cmd.strip()
        if not cmd:
            return

        parts = cmd.split(":", 1)
        action = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else None

        if action == "step":
            delta = int(arg) if arg else 1
            self.step_frame(delta)
        elif action == "seek":
            idx = int(arg) if arg else 0
            self.seek_frame(idx)
        elif action == "mark_in":
            idx = int(arg) if arg else None
            self.mark_in(idx)
        elif action == "mark_out":
            idx = int(arg) if arg else None
            self.mark_out(idx)
        elif action in ("dip", "set_dip"):
            self.set_keyframe("dip", int(arg) if arg else None)
        elif action in ("set", "set_set"):
            self.set_keyframe("set", int(arg) if arg else None)
        elif action in ("rel", "set_rel", "release"):
            self.set_keyframe("release", int(arg) if arg else None)
        elif action in ("ft", "set_ft", "follow_through"):
            self.set_keyframe("follow_through", int(arg) if arg else None)
        elif action == "outcome":
            self.set_outcome(arg or "make")
        elif action == "cycle_neg":
            self.cycle_negative_taxonomy()
        elif action == "commit_shot":
            self.commit_shot()
        elif action == "commit_neg":
            self.commit_negative(arg)
        elif action == "accept_prop":
            self.accept_proposal()
        elif action == "discard_prop":
            self.discard_proposal()
        elif action == "auto_detect":
            self.auto_detect_machine_proposals(force=True)
        elif action == "toggle_pose":
            self.show_pose = not self.show_pose
        elif action == "toggle_help":
            self.show_help = not self.show_help
        elif action == "undo":
            self.undo()
        elif action == "save":
            self.save_to_database()
        else:
            self.status_message = f"Unknown command: '{cmd}'"

    # -------------------------------------------------------------------------
    # Main Execution Loops (GUI / Headless)
    # -------------------------------------------------------------------------

    def run_headless(self, commands: Optional[List[str]] = None) -> None:
        """Execute in headless mode without window creation."""
        if commands:
            for c in commands:
                self.execute_command(c)
        raw_frame = self.get_current_frame_image()
        _ = self.render_overlay(raw_frame)
        _ = self.render_canvas(raw_frame)

    def run_gui(self) -> None:
        """Run interactive OpenCV HighGUI window loop with responsive layout."""
        win_name = f"Shot Lab Annotation - {self.clip_id}"
        cv2.namedWindow(win_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(win_name, 1360, 800)

        def on_trackbar(val: int) -> None:
            self.seek_frame(val)

        cv2.createTrackbar("Frame", win_name, self.current_frame, max(1, self.frame_count - 1), on_trackbar)

        try:
            while True:
                if self.is_playing:
                    if self.current_frame < self.frame_count - 1:
                        self.current_frame += 1
                        cv2.setTrackbarPos("Frame", win_name, self.current_frame)
                    else:
                        self.is_playing = False

                raw_frame = self.get_current_frame_image()
                display_canvas = self.render_canvas(raw_frame)
                cv2.imshow(win_name, display_canvas)

                delay = max(1, int(1000.0 / self.fps)) if self.is_playing else 30
                key = cv2.waitKey(delay) & 0xFF

                if key in (ord('q'), 27):  # Q or Esc
                    break
                elif key in (ord('h'), ord('H')):  # H: Toggle Help
                    self.show_help = not self.show_help
                elif key in (ord('p'), ord('P')):  # P: Toggle Pose Skeleton
                    self.show_pose = not self.show_pose
                    self.status_message = f"Pose Skeleton: {'ON' if self.show_pose else 'OFF'}"
                elif key in (ord('r'), ord('R')):  # R: Auto-Detect Proposals
                    self.status_message = "Running machine detector... please wait."
                    display_canvas = self.render_canvas(raw_frame)
                    cv2.imshow(win_name, display_canvas)
                    cv2.waitKey(1)
                    self.auto_detect_machine_proposals(force=True)
                elif key == 32:           # Space
                    if self.show_help:
                        self.show_help = False
                    else:
                        self.is_playing = not self.is_playing
                elif key in (ord(','), 44):  # Step -1
                    self.step_frame(-1)
                    cv2.setTrackbarPos("Frame", win_name, self.current_frame)
                elif key in (ord('.'), 46):  # Step +1
                    self.step_frame(1)
                    cv2.setTrackbarPos("Frame", win_name, self.current_frame)
                elif key in (ord('<'), 60):  # Step -10
                    self.step_frame(-10)
                    cv2.setTrackbarPos("Frame", win_name, self.current_frame)
                elif key in (ord('>'), 62):  # Step +10
                    self.step_frame(10)
                    cv2.setTrackbarPos("Frame", win_name, self.current_frame)
                elif key == ord('['):
                    self.mark_in()
                elif key == ord(']'):
                    self.mark_out()
                elif key == ord('1'):
                    self.set_keyframe("dip")
                elif key == ord('2'):
                    self.set_keyframe("set")
                elif key == ord('3'):
                    self.set_keyframe("release")
                elif key == ord('4'):
                    self.set_keyframe("follow_through")
                elif key in (ord('s'), ord('S')):
                    self.commit_shot()
                elif key in (ord('n'), ord('N')):
                    self.cycle_negative_taxonomy()
                    self.commit_negative()
                elif key in (ord('m'), ord('M')):
                    self.set_outcome("make")
                elif key in (ord('x'), ord('X')):
                    self.set_outcome("miss")
                elif key in (ord('u'), ord('U')):
                    self.set_outcome("unknown")
                elif key in (ord('a'), ord('A')):
                    self.accept_proposal()
                elif key in (ord('d'), ord('D')):
                    self.discard_proposal()
                elif key in (ord('z'), ord('Z')):
                    self.undo()
                elif key in (ord('w'), ord('W')):
                    self.save_to_database()

        finally:
            cv2.destroyAllWindows()
            if self.cap:
                self.cap.release()
            if self.pose_engine:
                try:
                    self.pose_engine.close()
                except Exception:
                    pass


def main():
    parser = argparse.ArgumentParser(description="Developer Model Lab Video Scrubber & Annotation Tool.")
    parser.add_argument("--video", help="Path to video file.")
    parser.add_argument("--clip", "--clip-id", dest="clip_id", help="Lookup clip by ID from database or raw_clips/.")
    parser.add_argument("--player-id", default=None, help="Player ID (defaults to clip owner from DB).")
    parser.add_argument("--split", choices=["train", "val", "test"], help="Dataset split (defaults to split from DB).")
    parser.add_argument("--db", default="shot_lab.db", help="Path to SQLite database.")
    parser.add_argument("--headless", action="store_true", help="Run in headless mode without GUI.")
    parser.add_argument("--synthetic", action="store_true", help="Allow synthetic test video fixture.")
    parser.add_argument("--shot-type", default="catch_and_shoot", help="Shot type ID (default: catch_and_shoot).")
    parser.add_argument("--auto-detect", action="store_true", help="Automatically run detector proposals on load.")
    parser.add_argument("--commands", help="Comma-separated commands to execute in headless mode.")
    args = parser.parse_args()

    video_path = args.video
    clip_id = args.clip_id
    player_id = args.player_id or "dev_player"
    split = args.split or "train"

    # Auto-resolve from database if --clip passed without --video
    if not video_path and clip_id:
        db_inst = ShotLabDB(args.db)
        clip_rec = db_inst.get_labeled_clip(clip_id)
        if clip_rec:
            video_path = clip_rec["file_path"]
            if not os.path.exists(video_path):
                alt = os.path.join("raw_clips", os.path.basename(video_path))
                if os.path.exists(alt):
                    video_path = alt
            player_id = args.player_id or clip_rec.get("player_id", player_id)
            split = args.split or clip_rec.get("split", split)
        else:
            cand = os.path.join("raw_clips", f"{clip_id}.mp4")
            if os.path.exists(cand):
                video_path = cand

    if not video_path:
        parser.error("Either --video <path> or an existing registered --clip <clip_id> must be specified.")

    app = AnnotationLab(
        video_path=video_path,
        clip_id=clip_id,
        player_id=player_id,
        split=split,
        db_path=args.db,
        headless=args.headless,
        synthetic=args.synthetic,
        auto_detect=args.auto_detect,
        shot_type_id=args.shot_type,
    )

    if args.headless:
        cmds = [c.strip() for c in args.commands.split(",")] if args.commands else []
        app.run_headless(cmds)
        print(f"Headless execution completed for clip '{app.clip_id}'.")
    else:
        app.run_gui()


if __name__ == "__main__":
    main()
