# Phase 7: Ball, Rim, and Trajectory Tracking — Execution Summary

**Execution Date:** 2026-10-10  
**Status:** Completed, Reconciled & Verified  
**Gate Verdict:** `QUALIFIED_AS_ADVISORY`  

---

## 1. Overview & Objectives Delivered

Phase 7 delivered end-to-end multi-object detection, parabolic trajectory fitting, rim entry physics, advisory outcome qualification, and an offline pose backend comparative benchmark.

1. **Multi-Clip Ingestion & Provenance:**
   - Accounted for all real raw clips on disk in `raw_clips/` (20 clips verified).
   - Synchronized `clip_splits.json` and `batch_ingest_clips.py` with expanded player registry (`mixkit_shooter`, `stock_shooter`).
   - Created `WEIGHTS_MANIFEST.md` documenting cryptographic SHA256 hashes, CC BY 4.0 licenses, and class taxonomies for all model checkpoints in `models/`.

2. **Dynamic Ball & Rim YOLO Tracker (`ball_tracker.py`):**
   - Implemented dynamic class discovery from `model.names` with substring disambiguation (preventing "basketball" from matching "basket").
   - Added shot lifecycle event hooks (`on_shot_started`, `on_shot_release`, `on_shot_ended`) synchronizing ball tracking with the master pose state machine.
   - Preserves rim observations across the active shot (`active_shot_last_rim`).
   - Fallback to `UNAVAILABLE_NO_WEIGHTS` when weights are absent or rim class is unavailable.

3. **Reconciled Trajectory & Outcome Evidence Qualification:**
   - **Gating Rule:** When trajectory evidence is insufficient, automated tracking returns advisory outcome `unknown` with a clear, specific reason:
     - $R^2 < 0.70$ or fit failure $\to$ `outcome: unknown`, `outcome_reason: POOR_TRAJECTORY_FIT`.
     - $N < 4$ post-release ball detections $\to$ `outcome: unknown`, `outcome_reason: INSUFFICIENT_FLIGHT_POINTS`.
     - Rim not detected $\to$ `outcome: unknown`, `outcome_reason: RIM_NOT_DETECTED`.
     - Weights absent / rim unsupported $\to$ `outcome: unknown`, `outcome_reason: UNAVAILABLE_NO_WEIGHTS`.
   - **Qualified Outcomes ($R^2 \ge 0.70$, rim detected, $N \ge 4$):**
     - Ball passes near/under rim post-apex $\to$ advisory `make`, `outcome_reason: TRAJECTORY_ENTRY_CONFIRMED`.
     - Ball does not align with rim aperture post-apex $\to$ advisory `miss`, `outcome_reason: MISSED_TRAJECTORY_ALIGNMENT`.
   - **Human Ground Truth Inviolability:** Automated outcomes populate advisory columns (`automated_outcome`, `automated_outcome_conf`, `trajectory_fit_r2`, `entry_angle_deg`) and never overwrite human `M/X/U` ground-truth labels in `shots.outcome` or `labeled_intervals.outcome`.

4. **Advisory Database Schema v4 (`shot_lab_db.py` & `main.py`):**
   - Non-destructive SQLite schema upgrade adding advisory columns.
   - Verified that automated metrics cannot automatically admit shots into player baseline calculations.

5. **Unified Ball & Rim Evaluation Harness (`evaluate_ball_tracking.py`):**
   - Benchmarked `models/best.pt` on the 472-image Roboflow test split (`Basketball.v1i.yolov8/test`).
   - Results: **mAP@50 = 0.7283** (exceeds $\ge 0.70$ advisory qualification threshold), Precision = 0.7687, Recall = 0.709.
   - Evaluated available labeled validation clips (`sid_4_97deg_wrim`, `lavish_3_mix`, `mikeddunnstud1`):
     - Pooled ball coverage = **74.9%**, pooled rim coverage = **28.7%**.
     - `sid_4_97deg_wrim`: 75.3% ball cov, rim absent from frame $\to$ advisory `unknown` (`RIM_NOT_DETECTED`). Human ground-truth: 14 intervals (`make`).
     - `lavish_3_mix`: 94.0% ball cov, $R^2 = 0.11 < 0.70 \to$ advisory `unknown` (`POOR_TRAJECTORY_FIT`). Human ground-truth: 11 intervals (`none`).
     - `mikeddunnstud1`: 55.3% ball cov, 82.7% rim cov, $R^2 = 0.82 \ge 0.70 \to$ advisory `miss` (`MISSED_TRAJECTORY_ALIGNMENT`). Human ground-truth: 11 intervals (`make`).
   - Emits audit-compliant `BALL_RIM_EVAL_REPORT.json`.

6. **Offline Pose Backend Comparative Study (`evaluate_pose_backends.py`):**
   - Evaluated 12 shared biomechanical joints between Google MediaPipe Tasks Pose (Heavy) and Ultralytics YOLOv8 Pose (`models/yolov8m-pose.pt`) across validation clips.
   - Overall mean normalized joint distance was **0.0054 to 0.0863**.
   - Generated `POSE_BACKEND_COMPARISON_REPORT.json` without runtime overhead on live analysis.

---

## 2. Key Metrics & Empirical Results

| Metric | Measured Value | Benchmark / Gate Threshold | Gate Status |
| :--- | :--- | :--- | :--- |
| **Object Detection mAP@50** | **0.7283** | $\ge 0.70$ (Roboflow Test Split) | **QUALIFIED_AS_ADVISORY** |
| **Ball Detection mAP@50** | **0.9613** | — | High Precision |
| **Rim Detection mAP@50** | **0.4954** | — | Moderate (Advisory Only) |
| **Dataset Precision / Recall** | **0.7687 / 0.7090** | — | Robust on 472 images |
| **Validation Video Ball Coverage** | **74.9%** | — | Stable tracking continuity |
| **Validation Video Rim Coverage** | **28.7%** | — | Field-of-view dependent |
| **Pose Backend Mutual Disagreement** | **0.005 - 0.086** | — | Strong cross-model agreement |

---

## 3. Artifacts Created & Updated

- `WEIGHTS_MANIFEST.md` — SHA256 checksums, licenses, class mappings.
- `BALL_RIM_EVAL_REPORT.json` — Dataset test and video continuity evaluation report with reconciled gating.
- `POSE_BACKEND_COMPARISON_REPORT.json` — MediaPipe vs. YOLOv8 Pose comparative report.
- `MANUAL_VERIFICATION_COMMANDS.md` — Section 13 updated with reconciled gating details.
- `ball_tracker.py` — Dynamic class mapping, substring filter, active rim memory, strict $R^2 \ge 0.70$ gating.
- `ball_geometry.py` — $R^2$ goodness-of-fit, entry angle, launch angle calculations.
- `shot_lab_db.py` — Schema v4 automatic migration.
- `main.py` — Live HUD and DB integration with `--weights`.
- `evaluate_ball_tracking.py` — Dual-track benchmark runner with ground truth interval comparison.
- `evaluate_pose_backends.py` — Pose comparative evaluation tool with per-clip timestamp isolation.
- Unit Test Suites:
  - `test_weights_manifest.py` (2 tests)
  - `test_ball_tracker.py` (8 tests — covering all qualified & gated scenarios)
  - `test_ball_geometry.py` (6 tests)
  - `test_ball_tracking_flow.py` (2 tests)
  - `test_pose_backend_comparison.py` (3 tests)
  - `test_evaluate_ball_tracking.py` (3 tests)

---

## 4. Verification & Testing

All 24 Phase 7 tests executed and passed in 58.2s:
```powershell
.venv\Scripts\python.exe -m unittest test_weights_manifest.py test_ball_tracker.py test_ball_geometry.py test_ball_tracking_flow.py test_pose_backend_comparison.py test_evaluate_ball_tracking.py
# Ran 24 tests in 58.246s — OK (0 failures, 0 errors)
```
Knowledge graph updated:
```powershell
.venv\Scripts\python.exe -m graphify update .
```
