"""Headless, local video analysis service for the Phase 8 player app."""

from __future__ import annotations

import gzip
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional

import cv2

from basketball.core.analyzer import SessionRecorder, ShotPhaseDetector, compute_all_angles
from basketball.core.pose_engine import PoseEngine
from basketball.persistence.shot_lab_db import ShotLabDB


# Joints that define "tracking confidence" for a shot proposal (unchanged since Phase 8).
KEY_JOINTS = (11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28)
# Pose cache format 2 stores all 33 MediaPipe landmarks plus estimated world coordinates,
# so measurements (head, heels, feet, 3D angles) can be recomputed without re-running pose.
CACHE_JOINTS = tuple(range(33))
CACHE_FORMAT = 2
MIN_SUFFICIENT_VALID_JOINT_RATIO = 0.60
MAX_DURATION_SECONDS = 10 * 60
MIN_DURATION_SECONDS = 0.5


class AnalysisCancelled(RuntimeError):
    """Raised from the progress callback when the user cancels a job."""


def find_ffmpeg() -> str | None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, OSError, RuntimeError):
        return None


def probe_video(path: str) -> dict:
    """Read basic video metadata and reject files OpenCV cannot decode."""
    capture = cv2.VideoCapture(path)
    try:
        if not capture.isOpened():
            raise ValueError("The uploaded file could not be opened as a video.")
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if frames <= 0 or width <= 0 or height <= 0:
            raise ValueError("The video has no readable frames or dimensions.")
        if fps <= 1.0:
            fps = 30.0
        ok, first = capture.read()
        if not ok or first is None:
            raise ValueError("The video's first frame could not be decoded; the file may be corrupt or use an unsupported codec.")
        duration = frames / fps
        if duration < MIN_DURATION_SECONDS:
            raise ValueError(f"The video is only {duration:.1f} s long; record at least one full shot.")
        if duration > MAX_DURATION_SECONDS:
            raise ValueError(f"The video is {duration / 60:.1f} minutes long; the limit is {MAX_DURATION_SECONDS // 60} minutes. Trim it or split it into shorter clips.")
        fourcc_value = int(capture.get(cv2.CAP_PROP_FOURCC) or 0)
        codec = "".join(chr((fourcc_value >> 8 * i) & 0xFF) for i in range(4)).strip("\x00 ").lower() or None
        return {
            "fps": fps,
            "frame_count": frames,
            "width": width,
            "height": height,
            "duration_seconds": round(frames / fps, 2),
            "codec": codec,
        }
    finally:
        capture.release()


def prepare_video_for_analysis(path: str, temp_dir: str) -> tuple[dict, str | None]:
    """Return OpenCV-readable metadata and, when needed, a temporary MP4 transcode.

    The browser camera recorder commonly produces WebM. Some OpenCV wheels lack a
    decoder for that codec, so use FFmpeg only as a local format bridge; all frame
    analysis still runs through the existing OpenCV/MediaPipe pipeline.
    """
    try:
        return probe_video(path), None
    except ValueError as original_error:
        if "minutes long" in str(original_error) or "s long;" in str(original_error):
            raise
        source = Path(path)
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            if True:
                raise ValueError(
                    f"{original_error} This OpenCV build cannot read the browser recording. "
                    "Install the local video decoder with `python -m pip install imageio-ffmpeg`, "
                    "then restart the app and upload/record again."
                ) from original_error

        output = Path(temp_dir) / f"{source.stem}-opencv-{os.getpid()}.mp4"
        command = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
            "-an", "-c:v", "mpeg4", "-q:v", "3", "-movflags", "+faststart", str(output),
        ]
        try:
            converted = subprocess.run(command, capture_output=True, text=True, check=False)
            if converted.returncode != 0:
                detail = (converted.stderr or "").strip()[-500:]
                raise ValueError(f"Local video conversion failed: {detail or 'FFmpeg could not decode this recording.'}")
            metadata = probe_video(str(output))
            return metadata, str(output)
        except Exception:
            output.unlink(missing_ok=True)
            raise


BROWSER_SAFE_CODECS = {"avc1", "h264", "x264", "vp80", "vp90", "vp08", "vp09"}


def make_browser_replay(path: str, metadata: dict, out_dir: str, *, max_height: int = 1080) -> str | None:
    """Create an H.264 MP4 replay copy when the upload may not play in every browser.

    iPhones record HEVC (hvc1/hev1), which Firefox and many Android/Windows browsers
    cannot play. The original file is always kept; the copy is only for playback.
    Returns the copy's path, or None when no copy is needed or FFmpeg is unavailable.
    """
    codec = (metadata or {}).get("codec") or ""
    suffix = Path(path).suffix.lower()
    if codec in BROWSER_SAFE_CODECS and suffix in {".mp4", ".webm", ".mov"} and (metadata or {}).get("height", 0) <= 2160:
        return None
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return None
    output = Path(out_dir) / f"{Path(path).stem}-replay.mp4"
    scale = f"scale=-2:'min({max_height},ih)'"
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(path), "-an",
               "-vf", scale, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
               "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=900)
    except (OSError, subprocess.TimeoutExpired):
        output.unlink(missing_ok=True)
        return None
    if result.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
        output.unlink(missing_ok=True)
        return None
    return str(output)


def _persist_shot_proposal(db, summary, boundaries, end_frame, confidence_samples, *,
                           session_id, player_id, camera_view, shot_type, shot_style):
    """Save one machine shot proposal: quarantined, unknown outcome, original boundaries kept."""
    conf_ratio = sum(confidence_samples) / len(confidence_samples) if confidence_samples else 0.0
    # Match the Shot Lab baseline gate's persisted vocabulary.
    tracking_confidence = "SUFFICIENT" if conf_ratio >= MIN_SUFFICIENT_VALID_JOINT_RATIO else "INSUFFICIENT"
    release = boundaries.get("release_metrics") or {}
    elbow_3d, elbow_2d = release.get("elbow_3d"), release.get("elbow_2d")
    return db.save_shot({
        "session_id": session_id,
        "player_id": player_id,
        "camera_view": camera_view,
        "shot_type": shot_type,
        "shot_style": shot_style,
        "machine_start_frame": boundaries["start_frame"],
        "machine_dip_frame": boundaries["dip_frame"],
        "machine_set_frame": boundaries["set_frame"],
        "machine_release_frame": boundaries["release_frame"],
        "machine_end_frame": end_frame,
        "outcome": "unknown",
        "outcome_source": "unlabeled",
        "review_status": "quarantined",
        "tracking_confidence": tracking_confidence,
        "valid_frame_ratio": conf_ratio,
        # Save release-frame measurements in their actual coordinate bases.
        # The current detector does not identify a distinct dip frame, so
        # knee-at-dip is intentionally left unavailable.
        "knee_angle_dip_3d": None,
        "elbow_angle_release_3d": elbow_3d,
        "elbow_angle_release_2d": elbow_2d,
        "foreshortening_discrepancy_deg": (
            round(abs(elbow_3d - elbow_2d), 1) if elbow_3d is not None and elbow_2d is not None else None
        ),
        "sequence_lag_ms": summary.get("sequence_lag_ms"),
        "torso_sway_deg": None,
    })


def analyze_video(
    video_path: str,
    db_path: str,
    session_id: str,
    player_id: str,
    camera_view: str,
    shot_type: str,
    shot_style: str,
    pose_cache_path: Optional[str] = None,
    progress: Optional[Callable[[float, str], None]] = None,
    persist_shots: bool = True,
) -> dict:
    """Process a complete video and persist pose-shot proposals to Shot Lab.

    With ``persist_shots=False`` only the pose cache is rewritten (used to upgrade the
    pose data of an older session without touching its reviewed shots).
    """
    metadata = probe_video(video_path)
    capture = cv2.VideoCapture(video_path)
    pose = None
    recorder = SessionRecorder()
    detector = ShotPhaseDetector(shot_style=shot_style)
    db = ShotLabDB(db_path)
    frame_index = 0
    previous_phase = "idle"
    active_boundaries = None
    candidate_count = 0
    rejected_candidate_count = 0
    confidence_samples = []
    total_frames = metadata["frame_count"]
    interval_ms = 1000.0 / metadata["fps"]
    cache_path = Path(pose_cache_path) if pose_cache_path else None
    cache_tmp = cache_path.with_suffix(cache_path.suffix + ".tmp") if cache_path else None
    cache_stream = None
    world_frames = []
    frames_with_pose = 0

    try:
        pose = PoseEngine()
        if not capture.isOpened():
            raise ValueError("The video could not be reopened for analysis.")

        if cache_path:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_stream = gzip.open(cache_tmp, "wt", encoding="utf-8")
            cache_stream.write(json.dumps({
                "format": CACHE_FORMAT,
                "fps": metadata["fps"], "frame_count": total_frames,
                "width": metadata["width"], "height": metadata["height"],
                "landmark_indices": CACHE_JOINTS,
                "coordinates": "frames: raw normalised image x, y, visibility, valid (no smoothing); world: MediaPipe estimated metres (hip-centred)",
            }, separators=(",", ":"))[:-1] + ',"frames":[')

        while True:
            ok, frame = capture.read()
            if not ok:
                break

            timestamp_ms = round(frame_index * interval_ms)
            output = pose.process(frame, timestamp_ms)
            frame_index += 1

            if cache_stream:
                if frame_index > 1:
                    cache_stream.write(",")
                frame_points = []
                world_points = None
                if output is not None:
                    # Raw per-frame landmarks: the causal smoothing used by the live detector
                    # lags fast arm motion, so analysis applies its own centred smoothing.
                    landmarks_for_cache = output["landmarks"]
                    valid_for_cache = output["valid"]
                    world = output.get("world_landmarks") or {}
                    if world:
                        world_points = [
                            [round(float(world[j]["world_x"]), 4), round(float(world[j]["world_y"]), 4),
                             round(float(world[j]["world_z"]), 4)] if j in world else None
                            for j in CACHE_JOINTS
                        ]
                    for joint in CACHE_JOINTS:
                        landmark = landmarks_for_cache.get(joint)
                        if landmark is None:
                            frame_points.append(None)
                        else:
                            frame_points.append([
                                round(float(landmark["norm_x"]), 6),
                                round(float(landmark["norm_y"]), 6),
                                round(float(landmark.get("visibility", 0.0)), 4),
                                bool(valid_for_cache.get(joint, False)),
                            ])
                else:
                    frame_points = []
                world_frames.append(world_points)
                cache_stream.write(json.dumps(frame_points, separators=(",", ":")))

            if output is not None:
                frames_with_pose += 1
            if output is not None and persist_shots:
                landmarks = output["smoothed_landmarks"]
                valid = output["valid"]
                angles = compute_all_angles(
                    landmarks,
                    valid,
                    world_landmarks=output.get("world_landmarks"),
                    min_visibility=0.45,
                )
                phase, _, _ = detector.update(landmarks, angles, timestamp_ms)
                recorder.push_frame(angles, phase, timestamp_ms)

                if recorder.recording:
                    confidence_samples.append(
                        sum(1 for joint in KEY_JOINTS if valid.get(joint, False)) / len(KEY_JOINTS)
                    )

                if (
                    previous_phase in ("idle", "preparing")
                    and phase in ("preparing", "set_point", "releasing")
                    and not recorder.recording
                ):
                    recorder.start_shot()
                    active_boundaries = {
                        "start_frame": max(0, frame_index - 1),
                        "dip_frame": None,
                        "set_frame": None,
                        "release_frame": None,
                        "release_metrics": {},
                    }
                    candidate_count += 1

                if active_boundaries and phase == "set_point" and previous_phase != "set_point":
                    active_boundaries["set_frame"] = frame_index - 1

                if active_boundaries and phase == "releasing" and previous_phase != "releasing":
                    active_boundaries["release_frame"] = frame_index - 1
                    active_boundaries["release_metrics"] = {
                        "elbow_3d": angles.get("elbow_shooting_3d"),
                        "elbow_2d": angles.get("elbow_shooting_2d"),
                    }

                if previous_phase in ("releasing", "follow_through") and phase == "idle":
                    summary = recorder.end_shot()
                    if summary and active_boundaries:
                        _persist_shot_proposal(
                            db, summary, active_boundaries, frame_index - 1, confidence_samples,
                            session_id=session_id, player_id=player_id, camera_view=camera_view,
                            shot_type=shot_type, shot_style=shot_style,
                        )
                    elif active_boundaries:
                        rejected_candidate_count += 1
                    active_boundaries = None
                    confidence_samples = []

                previous_phase = phase

            if progress and (frame_index % max(1, total_frames // 100) == 0 or frame_index == total_frames):
                ratio = min(1.0, frame_index / max(1, total_frames))
                progress(ratio, f"Analyzed frame {frame_index:,} of {total_frames:,}")

        # A clip that stops right after the release never returns the detector to
        # "idle", so the attempt would be silently dropped. Keep it as a reviewable
        # proposal only when a release was actually observed; it stays quarantined
        # with an unknown outcome like every other machine proposal.
        finalized_at_video_end = 0
        incomplete_candidates = 0
        if recorder.recording:
            if active_boundaries and active_boundaries.get("release_frame") is not None:
                summary = recorder.end_shot()
                if summary:
                    _persist_shot_proposal(
                        db, summary, active_boundaries, max(0, frame_index - 1), confidence_samples,
                        session_id=session_id, player_id=player_id, camera_view=camera_view,
                        shot_type=shot_type, shot_style=shot_style,
                    )
                    finalized_at_video_end = 1
                else:
                    rejected_candidate_count += 1
            else:
                incomplete_candidates = 1

        shots = db.get_shots(session_id=session_id, min_confidence=None)
        for shot in shots:
            shot["review_history"] = db.get_shot_review_history(shot["shot_id"])
        if cache_stream:
            cache_stream.write('],"world":' + json.dumps(world_frames, separators=(",", ":")) + "}")
            cache_stream.close()
            cache_stream = None
            cache_tmp.replace(cache_path)
        return {
            "session_id": session_id,
            "status": "complete",
            "video": metadata,
            "frames_processed": frame_index,
            "candidate_count": candidate_count,
            "rejected_candidate_count": rejected_candidate_count,
            "incomplete_candidate_count": incomplete_candidates,
            "finalized_at_video_end_count": finalized_at_video_end,
            "shot_count": len(shots),
            "outcomes": {"human": "unknown_pending_review", "automated": "not_run"},
            "ball_rim_tracking": "not_run_in_web_upload_slice",
            "pose_cache": "available" if cache_path else "not_saved",
            "pose_cache_format": CACHE_FORMAT,
            "frames_with_pose": frames_with_pose,
            "shots": shots,
            "notice": "Shot detections are machine proposals. Review before using for coaching or baselines.",
        }
    finally:
        if cache_stream:
            cache_stream.close()
        if cache_tmp:
            cache_tmp.unlink(missing_ok=True)
        capture.release()
        if pose is not None:
            pose.close()
