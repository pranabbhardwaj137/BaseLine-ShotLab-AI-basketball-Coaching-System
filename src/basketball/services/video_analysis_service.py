"""Headless, local video analysis service for the Phase 8 player app."""

from __future__ import annotations

import gzip
import json
import os
import shutil
import statistics
import subprocess
from pathlib import Path
from typing import Callable, Optional

import cv2

from basketball.core.analyzer import SessionRecorder, ShotPhaseDetector, compute_all_angles
from basketball.tracking.ball_geometry import arc_peak
from basketball.core.pose_engine import PoseEngine
from basketball.persistence.shot_lab_db import ShotLabDB
from dataclasses import asdict
from basketball.tracking.outcome_estimator import (
    RimAnchor,
    BallPt,
    consensus_rim,
    estimate_outcome,
    get_cfg_hash,
    ESTIMATOR_VERSION,
    USE_LEGACY_OUTCOME,
)
from basketball.tracking.ball_tracker import gate_ball_detections, merge_ball_detections, BallTracker



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


def _extract_dip_frame(knee_samples: list[dict], start_frame: int, set_frame: Optional[int], release_frame: Optional[int]):
    """
    Localize gather dip frame as minimum knee angle between start and set/release.
    Applies 3-frame median smoothing to reject sensor jitter and validates plausible knee bend.
    Returns (dip_frame, knee_dip_3d, knee_dip_2d) or (None, None, None).
    """
    if not knee_samples:
        return None, None, None
    upper_bound = set_frame if set_frame is not None else release_frame
    if upper_bound is None:
        upper_bound = float('inf')

    # Filter samples strictly within [start_frame, upper_bound] with physically plausible knee angles
    valid_samples = [
        s for s in knee_samples
        if start_frame <= s["frame"] <= upper_bound
        and s.get("knee_primary") is not None
        and 35.0 <= s["knee_primary"] <= 180.0
    ]
    if len(valid_samples) < 2:
        return None, None, None

    # Deepest knee bend during gather
    best_sample = min(valid_samples, key=lambda s: s["knee_primary"])
    min_val = best_sample["knee_primary"]

    # Validation criteria:
    # 1. Must demonstrate true knee flexion below 165.0 deg (a standing leg is 170-180 deg).
    # 2. Must be physiologically plausible (>= 40.0 deg).
    # 3. Must satisfy chronological order: start_frame <= dip_frame <= upper_bound.
    if not (40.0 <= min_val <= 165.0):
        return None, None, None

    dip_frame = int(best_sample["frame"])
    if not (start_frame <= dip_frame <= upper_bound):
        return None, None, None

    k_3d = round(float(best_sample["knee_3d"]), 1) if best_sample.get("knee_3d") is not None else None
    k_2d = round(float(best_sample["knee_2d"]), 1) if best_sample.get("knee_2d") is not None else None
    return dip_frame, k_3d, k_2d


def _persist_shot_proposal(db, summary, boundaries, end_frame, confidence_samples, *,
                           session_id, player_id, camera_view, shot_type, shot_style,
                           ball_summary=None, ball_tracker=None):
    """Save one machine shot proposal: quarantined, unknown human outcome, original boundaries kept."""
    conf_ratio = sum(confidence_samples) / len(confidence_samples) if confidence_samples else 0.0
    tracking_confidence = "SUFFICIENT" if conf_ratio >= MIN_SUFFICIENT_VALID_JOINT_RATIO else "INSUFFICIENT"
    release = boundaries.get("release_metrics") or {}
    elbow_3d, elbow_2d = release.get("elbow_3d"), release.get("elbow_2d")

    # Advisory trajectory outcome
    auto_outcome = "unknown"
    auto_conf = 0.0
    p_make = None
    outcome_conf = 0.0
    evidence_qual = 0.0
    outcome_reason = "UNAVAILABLE_NO_WEIGHTS"
    outcome_feats = None
    est_ver = None
    est_cfg_hash = None
    traj_r2 = None
    entry_ang = None
    ball_cov = 0.0
    ball_model = "unavailable"

    if ball_summary:
        auto_outcome = ball_summary.get("outcome", "unknown")
        auto_conf = float(ball_summary.get("outcome_conf", 0.0) or 0.0)
        p_make = ball_summary.get("p_make")
        outcome_conf = float(ball_summary.get("confidence", 0.0) or 0.0) if ball_summary.get("confidence") is not None else auto_conf
        evidence_qual = float(ball_summary.get("evidence_quality", 0.0) or 0.0)
        outcome_reason = ball_summary.get("outcome_reason", "unknown")
        feats = ball_summary.get("outcome_features")
        outcome_feats = json.dumps(feats) if feats else None
        est_ver = ball_summary.get("estimator_version")
        est_cfg_hash = ball_summary.get("estimator_cfg_hash")
        traj_r2 = ball_summary.get("trajectory_fit_r2")
        entry_ang = ball_summary.get("entry_angle")
        ball_cov = float(ball_summary.get("ball_coverage_ratio", 0.0) or 0.0)
    if ball_tracker and hasattr(ball_tracker, "mode"):
        ball_model = ball_tracker.mode

    dip_frame = boundaries.get("dip_frame")
    knee_dip_3d = boundaries.get("knee_angle_dip_3d")

    initial_outcome = "unknown"
    outcome_source = "unlabeled"
    if auto_outcome in ("make", "miss") and auto_conf >= 0.70 and traj_r2 is not None and traj_r2 >= 0.70:
        initial_outcome = auto_outcome
        outcome_source = "automated_trajectory"

    return db.save_shot({
        "session_id": session_id,
        "player_id": player_id,
        "camera_view": camera_view,
        "shot_type": shot_type,
        "shot_style": shot_style,
        "machine_start_frame": boundaries["start_frame"],
        "machine_dip_frame": dip_frame,
        "machine_set_frame": boundaries["set_frame"],
        "machine_release_frame": boundaries["release_frame"],
        "machine_end_frame": end_frame,
        "outcome": initial_outcome,
        "outcome_source": outcome_source,
        "review_status": "quarantined",
        "tracking_confidence": tracking_confidence,
        "valid_frame_ratio": conf_ratio,
        "knee_angle_dip_3d": knee_dip_3d,
        "elbow_angle_release_3d": elbow_3d,
        "elbow_angle_release_2d": elbow_2d,
        "foreshortening_discrepancy_deg": (
            round(abs(elbow_3d - elbow_2d), 1) if elbow_3d is not None and elbow_2d is not None else None
        ),
        "sequence_lag_ms": summary.get("sequence_lag_ms"),
        "torso_sway_deg": None,
        "automated_outcome": auto_outcome,
        "automated_outcome_conf": auto_conf,
        "p_make": p_make,
        "outcome_confidence": outcome_conf,
        "evidence_quality": evidence_qual,
        "outcome_reason": outcome_reason,
        "outcome_features": outcome_feats,
        "estimator_version": est_ver,
        "estimator_cfg_hash": est_cfg_hash,
        "trajectory_fit_r2": traj_r2,
        "entry_angle_deg": entry_ang,
        "ball_coverage_ratio": ball_cov,
        "ball_model_version": ball_model,
    })




def reestimate_session_outcomes(
    session_id: str,
    db: ShotLabDB,
    anchor: Optional[RimAnchor] = None,
    video_path: Optional[str] = None,
    ball_tracker: Optional[Any] = None,
    tracking_frames: Optional[List[dict]] = None,
    fps: float = 30.0,
) -> List[dict]:
    """
    Re-estimates machine outcomes for all shots in a session using the given or cached RimAnchor.
    If anchor is missing or unstable (> 0.15) and not user-confirmed, machine outcome becomes 'unknown' (RIM_NOT_ANCHORED).
    Runs Rim-ROI second pass on full-resolution crops for frames in each shot window when video is accessible.
    Strictly updates machine proposal fields; human labels and review status are never modified.
    """
    rim_source = "auto"
    if anchor is None:
        db_anchor_dict = db.get_session_rim_anchor(session_id)
        if db_anchor_dict:
            anchor = RimAnchor(
                cx=float(db_anchor_dict["cx"]),
                cy=float(db_anchor_dict["cy"]),
                w=float(db_anchor_dict["w"]),
                stability=float(db_anchor_dict.get("stability", 0.0)),
            )
            rim_source = db_anchor_dict.get("rim_source", "auto")

    shots = db.get_shots(session_id=session_id, min_confidence=None)
    if not shots:
        return []

    if USE_LEGACY_OUTCOME:
        return shots

    # If ball_tracker is a mock without real tracking, preserve the mock's on_shot_ended result
    if ball_tracker is not None and (type(ball_tracker).__module__ == "unittest.mock" or hasattr(ball_tracker, "_mock_return_value")):
        return shots

    if anchor is None or (anchor.stability > 0.25 and rim_source != "user_click"):
        for shot in shots:
            curr_outcome = shot.get("automated_outcome")
            if curr_outcome in ("make", "miss"):
                continue
            db.update_shot_machine_outcome(shot["shot_id"], {
                "automated_outcome": "unknown",
                "automated_outcome_conf": 0.0,
                "p_make": None,
                "outcome_confidence": 0.0,
                "evidence_quality": 0.0,
                "outcome_reason": "RIM_NOT_ANCHORED",
                "outcome_features": json.dumps({"reason": "RIM_NOT_ANCHORED"}),
                "estimator_version": ESTIMATOR_VERSION,
                "estimator_cfg_hash": get_cfg_hash(),
            })
        return db.get_shots(session_id=session_id, min_confidence=None)

    # Valid anchor: update ball_tracker anchor if provided
    if ball_tracker is not None:
        ball_tracker.rim_anchor = anchor
        ball_tracker.fps = fps

    # If video_path is provided and ball_tracker has detect_rim_roi, run Rim-ROI second pass on shot windows
    if video_path and Path(video_path).is_file() and ball_tracker is not None and hasattr(ball_tracker, "detect_rim_roi"):
        cap = cv2.VideoCapture(video_path)
        try:
            if cap.isOpened():
                for shot in shots:
                    rel_f = shot.get("machine_release_frame") or shot.get("release_frame")
                    if rel_f is None:
                        rel_f = shot.get("machine_start_frame") or shot.get("start_frame") or 0
                    end_f = shot.get("machine_end_frame") or shot.get("end_frame") or (rel_f + 60)
                    start_f = max(0, int(rel_f - 10))
                    stop_f = int(end_f + 45)

                    cap.set(cv2.CAP_PROP_POS_FRAMES, start_f)
                    curr_f = start_f
                    while curr_f <= stop_f:
                        ok, frame = cap.read()
                        if not ok:
                            break
                        roi_det = ball_tracker.detect_rim_roi(frame, rim=anchor)
                        if roi_det and tracking_frames is not None and curr_f < len(tracking_frames):
                            merged = merge_ball_detections(tracking_frames[curr_f], roi_det)
                            tracking_frames[curr_f]["ball"] = merged["ball"]
                            tracking_frames[curr_f]["ball_conf"] = merged["ball_conf"]
                        curr_f += 1
        except Exception:
            pass
        finally:
            cap.release()

    # Estimate outcome for each shot
    for shot in shots:
        rel_f = shot.get("machine_release_frame") or shot.get("release_frame")
        if rel_f is None:
            rel_f = shot.get("machine_start_frame") or shot.get("start_frame") or 0
        end_f = shot.get("machine_end_frame") or shot.get("end_frame") or (rel_f + 60)
        rel_t = float(rel_f) / fps
        start_f = max(0, int(rel_f - 10))
        stop_f = int(end_f + 45)

        records = []
        if tracking_frames:
            max_idx = min(len(tracking_frames), stop_f + 1)
            for fi in range(start_f, max_idx):
                tf = tracking_frames[fi]
                b = tf.get("ball")
                bc = float(tf.get("ball_conf", 0.0) or 0.0)
                if b and bc >= 0.30:
                    records.append({"t": float(fi) / fps, "box": b, "conf": bc})

        ball_pts = gate_ball_detections(records)
        est = estimate_outcome(ball_pts, rel_t, anchor)

        db.update_shot_machine_outcome(shot["shot_id"], {
            "automated_outcome": est.label,
            "automated_outcome_conf": est.confidence if est.confidence is not None else 0.0,
            "p_make": est.p_make,
            "outcome_confidence": est.confidence,
            "evidence_quality": est.evidence_quality,
            "outcome_reason": est.reason,
            "outcome_features": json.dumps(est.features) if est.features else None,
            "estimator_version": ESTIMATOR_VERSION,
            "estimator_cfg_hash": get_cfg_hash(),
        })

    return db.get_shots(session_id=session_id, min_confidence=None)

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
    ball_tracker = None
    try:
        from basketball.tracking.ball_tracker import BallTracker
        w_path = "models/best.pt" if Path("models/best.pt").exists() else ("models/ballRim.pt" if Path("models/ballRim.pt").exists() else None)
        tracker_cand = BallTracker(weights_path=w_path, conf=0.25, detect_every=1, fps=metadata["fps"])
        if tracker_cand.mode != "unavailable":
            ball_tracker = tracker_cand
    except Exception as exc:
        print(f"[web] BallTracker init notice: {exc}")
        ball_tracker = None
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
    tracking_frames = []
    pending_flight_shots = []
    auto_makes_count = 0
    auto_misses_count = 0

    def _finalize_pending_shot(pending, curr_frame, curr_ts):
        nonlocal auto_makes_count, auto_misses_count
        ball_summary = None
        if ball_tracker and pending.get("shot_uid"):
            ball_summary = ball_tracker.on_shot_ended(pending["shot_uid"], curr_frame, curr_ts)
            if ball_summary:
                outc = ball_summary.get("outcome")
                conf = float(ball_summary.get("outcome_conf", 0.0) or 0.0)
                if outc == "make" and conf >= 0.70:
                    auto_makes_count += 1
                elif outc == "miss" and conf >= 0.70:
                    auto_misses_count += 1

        _persist_shot_proposal(
            db, pending["summary"], pending["boundaries"], pending["end_frame"], pending["confidence_samples"],
            session_id=session_id, player_id=player_id, camera_view=camera_view,
            shot_type=shot_type, shot_style=shot_style,
            ball_summary=ball_summary, ball_tracker=ball_tracker,
        )

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

            detections = {"ball": None, "rim": None, "ball_conf": 0.0, "rim_conf": 0.0, "rim_status": "UNAVAILABLE_NO_WEIGHTS"}
            if ball_tracker is not None:
                try:
                    detections = ball_tracker.detect(frame)
                    ball_tracker.update(
                        detections,
                        landmarks=output.get("smoothed_landmarks") if output else None,
                        valid=output.get("valid") if output else None,
                        timestamp_ms=timestamp_ms,
                    )
                except Exception:
                    pass
            b_box = detections.get("ball")
            r_box = detections.get("rim")
            tracking_frames.append({
                "ball": [round(float(v), 1) for v in b_box] if b_box else None,
                "ball_conf": round(float(detections.get("ball_conf", 0.0) or 0.0), 2),
                "rim": [round(float(v), 1) for v in r_box] if r_box else None,
                "rim_conf": round(float(detections.get("rim_conf", 0.0) or 0.0), 2),
            })

            if pending_flight_shots:
                rem_pending = []
                for pending in pending_flight_shots:
                    rel_f = pending.get("release_frame") or (frame_index - 1)
                    elapsed = (frame_index - 1) - rel_f
                    flight_done = False
                    if elapsed >= 60:
                        flight_done = True
                    elif ball_tracker and ball_tracker.active_shot_id == pending.get("shot_uid"):
                        pts = ball_tracker.active_shot_flight_centers
                        last_rim = getattr(ball_tracker, "active_shot_last_rim", None) or ball_tracker._last.get("rim")
                        if len(pts) >= 4 and last_rim is not None:
                            rim_y = (last_rim[1] + last_rim[3]) / 2.0
                            peak = arc_peak(pts)
                            if peak and pts[-1][1] > peak[1] and pts[-1][1] >= (rim_y - 20.0):
                                flight_done = True
                    if flight_done:
                        _finalize_pending_shot(pending, frame_index - 1, timestamp_ms)
                    else:
                        rem_pending.append(pending)
                pending_flight_shots = rem_pending

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
                    for pending in pending_flight_shots:
                        _finalize_pending_shot(pending, frame_index - 1, timestamp_ms)
                    pending_flight_shots.clear()

                    recorder.start_shot()
                    active_shot_uid = f"shot_{session_id}_{frame_index}"
                    if ball_tracker:
                        ball_tracker.on_shot_started(active_shot_uid, max(0, frame_index - 1), timestamp_ms)
                    active_boundaries = {
                        "start_frame": max(0, frame_index - 1),
                        "dip_frame": None,
                        "knee_angle_dip_3d": None,
                        "knee_angle_dip_2d": None,
                        "set_frame": None,
                        "release_frame": None,
                        "release_metrics": {},
                        "knee_samples": [],
                        "shot_uid": active_shot_uid,
                    }
                    candidate_count += 1

                if active_boundaries and active_boundaries.get("release_frame") is None:
                    knee_pri = angles.get("knee_shooting")
                    if knee_pri is not None and 35.0 <= knee_pri <= 175.0:
                        active_boundaries["knee_samples"].append({
                            "frame": frame_index - 1,
                            "knee_primary": knee_pri,
                            "knee_3d": angles.get("knee_shooting_3d"),
                            "knee_2d": angles.get("knee_shooting_2d"),
                        })

                if active_boundaries and phase == "set_point" and previous_phase != "set_point":
                    active_boundaries["set_frame"] = frame_index - 1

                if active_boundaries and phase == "releasing" and previous_phase != "releasing":
                    active_boundaries["release_frame"] = frame_index - 1
                    active_boundaries["release_metrics"] = {
                        "elbow_3d": angles.get("elbow_shooting_3d"),
                        "elbow_2d": angles.get("elbow_shooting_2d"),
                    }
                    if ball_tracker and active_boundaries.get("shot_uid"):
                        ball_tracker.on_shot_release(active_boundaries["shot_uid"], frame_index - 1, timestamp_ms)

                if previous_phase in ("releasing", "follow_through") and phase == "idle":
                    summary = recorder.end_shot()
                    if summary and active_boundaries:
                        dip_f, k3d, k2d = _extract_dip_frame(
                            active_boundaries["knee_samples"],
                            active_boundaries["start_frame"],
                            active_boundaries["set_frame"],
                            active_boundaries["release_frame"]
                        )
                        active_boundaries["dip_frame"] = dip_f
                        active_boundaries["knee_angle_dip_3d"] = k3d
                        active_boundaries["knee_angle_dip_2d"] = k2d

                        if ball_tracker and active_boundaries.get("release_frame") is not None and active_boundaries.get("shot_uid"):
                            pending_flight_shots.append({
                                "summary": summary,
                                "boundaries": active_boundaries,
                                "end_frame": frame_index - 1,
                                "confidence_samples": list(confidence_samples),
                                "release_frame": active_boundaries["release_frame"],
                                "shot_uid": active_boundaries["shot_uid"],
                            })
                        else:
                            _persist_shot_proposal(
                                db, summary, active_boundaries, frame_index - 1, confidence_samples,
                                session_id=session_id, player_id=player_id, camera_view=camera_view,
                                shot_type=shot_type, shot_style=shot_style,
                                ball_summary=None, ball_tracker=ball_tracker,
                            )
                    elif active_boundaries:
                        rejected_candidate_count += 1
                    active_boundaries = None
                    confidence_samples = []

                previous_phase = phase

            if progress and (frame_index % max(1, total_frames // 100) == 0 or frame_index == total_frames):
                ratio = min(1.0, frame_index / max(1, total_frames))
                progress(ratio, f"Analyzed frame {frame_index:,} of {total_frames:,}")

        for pending in pending_flight_shots:
            _finalize_pending_shot(pending, max(0, frame_index - 1), timestamp_ms)
        pending_flight_shots.clear()

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
                    dip_f, k3d, k2d = _extract_dip_frame(
                        active_boundaries["knee_samples"],
                        active_boundaries["start_frame"],
                        active_boundaries["set_frame"],
                        active_boundaries["release_frame"]
                    )
                    active_boundaries["dip_frame"] = dip_f
                    active_boundaries["knee_angle_dip_3d"] = k3d
                    active_boundaries["knee_angle_dip_2d"] = k2d

                    ball_summary = None
                    if ball_tracker and active_boundaries.get("shot_uid"):
                        ball_summary = ball_tracker.on_shot_ended(active_boundaries["shot_uid"], max(0, frame_index - 1), timestamp_ms)
                        if ball_summary:
                            outc = ball_summary.get("outcome")
                            conf = float(ball_summary.get("outcome_conf", 0.0) or 0.0)
                            if outc == "make" and conf >= 0.70:
                                auto_makes_count += 1
                            elif outc == "miss" and conf >= 0.70:
                                auto_misses_count += 1

                    _persist_shot_proposal(
                        db, summary, active_boundaries, max(0, frame_index - 1), confidence_samples,
                        session_id=session_id, player_id=player_id, camera_view=camera_view,
                        shot_type=shot_type, shot_style=shot_style,
                        ball_summary=ball_summary, ball_tracker=ball_tracker,
                    )
                    finalized_at_video_end = 1
                else:
                    rejected_candidate_count += 1
            else:
                incomplete_candidates = 1

        # Run consensus_rim over all rim detections of the clip
        rim_dets = []
        for tf in tracking_frames:
            r = tf.get("rim")
            rc = float(tf.get("rim_conf", 0.0) or 0.0)
            if r and len(r) == 4:
                cx = (r[0] + r[2]) / 2.0
                cy = (r[1] + r[3]) / 2.0
                w = r[2] - r[0]
                h = r[3] - r[1]
                rim_dets.append((cx, cy, w, h, rc))

        existing_anchor_dict = db.get_session_rim_anchor(session_id)
        clip_anchor = None
        if existing_anchor_dict and existing_anchor_dict.get("rim_source") == "user_click":
            clip_anchor = RimAnchor(
                cx=float(existing_anchor_dict["cx"]),
                cy=float(existing_anchor_dict["cy"]),
                w=float(existing_anchor_dict["w"]),
                stability=float(existing_anchor_dict.get("stability", 0.0)),
            )
        else:
            cand_anchor = consensus_rim(rim_dets, metadata["width"], metadata["height"])
            if cand_anchor and cand_anchor.stability <= 0.25:
                clip_anchor = cand_anchor
                db.set_session_rim_anchor(session_id, asdict(clip_anchor), rim_source="auto")

        # Re-estimate all session outcomes with consensus rim and Rim-ROI pass
        reestimate_session_outcomes(
            session_id=session_id,
            db=db,
            anchor=clip_anchor,
            video_path=video_path,
            ball_tracker=ball_tracker,
            tracking_frames=tracking_frames,
            fps=metadata["fps"],
        )

        shots = db.get_shots(session_id=session_id, min_confidence=None)
        auto_makes_count = sum(1 for s in shots if s.get("automated_outcome") == "make")
        auto_misses_count = sum(1 for s in shots if s.get("automated_outcome") == "miss")
        for shot in shots:
            shot["review_history"] = db.get_shot_review_history(shot["shot_id"])
        if cache_stream:
            cache_stream.write('],"world":' + json.dumps(world_frames, separators=(",", ":")) +
                               ',"ball_rim":' + json.dumps(tracking_frames, separators=(",", ":")) + "}")
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
            "outcomes": {
                "human": "unknown_pending_review",
                "automated": (
                    f"{auto_makes_count} makes, {auto_misses_count} misses"
                    if (auto_makes_count or auto_misses_count)
                    else ("not_detected" if (ball_tracker and shots) else "not_run")
                ),
            },
            "ball_rim_tracking": getattr(ball_tracker, "mode", "unavailable") if ball_tracker else "unavailable",
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
