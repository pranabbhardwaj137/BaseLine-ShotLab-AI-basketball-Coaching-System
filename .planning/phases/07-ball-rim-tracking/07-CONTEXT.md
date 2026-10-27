# Phase 7 — Ball, Rim, and Trajectory Tracking: Context & Decisions

## 1. Phase Objective & Boundary
Measure basketball flight and rim interaction within pose-detected shot intervals, qualify automated make/miss evidence separately from human annotations, and conduct an experimental offline comparison between MediaPipe and YOLO Pose backends.

**Strict Scope Boundary:**
- **Ball & Rim Tracking:** Detect ball and rim bounding boxes, track ball trajectory post-release, fit parabolic flight, and calculate entry/release angles and rim proximity.
- **Experimental Pose Comparison:** Compare MediaPipe with YOLO Pose on shared joints via a dedicated offline benchmark without altering the primary live pipeline.
- **Strict Evidence Qualification:** Automated make/miss is strictly advisory/shadow. Automated outcomes never overwrite human `M/X/U` ground-truth labels and are never admitted to personal baselines automatically.
- **Weight Governance:** Keep external model weights in `models/` under their original filenames. Record file SHA256 hashes, licenses, class mappings, and provenance.
- **Deferred to Phase 8:** End-user mobile upload UI/UX and full user app.
- **Deferred to Phase 9:** Final release packaging, academic paper synthesis, and viva presentation assets.

---

## 2. Division of Labor

### 2.1 Manual Developer Work (Human-in-the-Loop)
1. **Annotation & Footage Quality:**
   - Review footage where ball and rim are visible (e.g., `sid_4_97deg_wrim`, `lavish_1_90deg`, `lavish_2_90deg`, etc.).
   - Verify ground-truth shot outcomes independently using human `M` (make) / `X` (miss) labeling.
2. **Model Weight Verification:**
   - Supply and verify external model weights in `models/` (`best.pt`, `ballRim.pt`, `yolov8m-pose.pt`).
   - Confirm dataset licensing (`Basketball.v1i.yolov8` under CC BY 4.0).
3. **Gate Approval:**
   - Review `BALL_RIM_EVAL_REPORT.json` and decide whether tracking coverage and trajectory fit justify experimental or production use.

### 2.2 Coding-Agent Work (Software, Plumbing & Evaluation)
1. **Dynamic YOLO Ball & Rim Integration (`ball_tracker.py`):**
   - Support configurable `--weights` path defaulting to `models/best.pt`.
   - Implement dynamic class mapping from `model.names` (inspecting class keys for `ball`, `rim`, `hoop`, `basketball`) rather than hardcoded integer indices.
   - Maintain explicit graceful degradation: if weights are absent or `ultralytics` fails to load, emit `UNAVAILABLE_NO_WEIGHTS` status rather than crashing.
2. **Shot-Synchronized Trajectory Engine (`ball_geometry.py`, `ball_tracker.py`):**
   - Synchronize tracking strictly to pose shot lifecycle (`on_shot_started`, `on_shot_release`, `on_shot_ended`).
   - Fit parabolic trajectory to ball centers post-release ($N \ge 4$ points).
   - Compute arc peak $(x_{peak}, y_{peak})$, launch angle, entry angle, trajectory fit coefficient of determination ($R^2$), and rim proximity distance.
3. **Advisory Database & Session Storage (`shot_lab_db.py`, `main.py`):**
   - Add advisory columns to `shots` table: `automated_outcome`, `automated_outcome_conf`, `trajectory_fit_r2`, `entry_angle_deg`, `ball_coverage_ratio`.
   - Preserve human `outcome` (`M`/`X`/`U`) as immutable ground truth; automated classification remains shadow/advisory.
4. **Offline Pose Backend Comparative Experiment (`evaluate_pose_backends.py`):**
   - Build an offline comparison tool evaluating MediaPipe Tasks Pose vs. YOLOv8 Pose (`models/yolov8m-pose.pt`) on validation clips.
   - Compare 12 shared keypoints: left/right shoulder, elbow, wrist, hip, knee, ankle.
   - Measure joint detection coverage %, temporal dropout rate, and estimate-to-estimate Euclidean and angular differences without slowing down live inference.
5. **Unified Evaluation Harness & Audit Report (`evaluate_ball_tracking.py`):**
   - Benchmark object detection mAP@50, Precision, and Recall of `models/best.pt` on `Basketball.v1i.yolov8/test` (472 images).
   - Evaluate ball flight continuity, $R^2$, and release alignment on project video clips.
   - Generate `BALL_RIM_EVAL_REPORT.json` complying with `AGENTS.md`.

---

## 3. Locked Decisions & Design Contracts

### 3.1 Model Weights & Class Mapping (Decision 1: Dynamic Best.pt)
- **Primary Weights:** `models/best.pt` (6.25 MB, YOLOv8n, trained on `Basketball.v1i.yolov8`).
- **Storage Location:** External weights stay in `models/` under their original filenames. No renaming or overwriting until formally validated.
- **Dynamic Class Detection:**
  ```python
  # Dynamic mapping based on model.names
  # models/best.pt: {0: 'basketball', 1: 'rim', 2: 'sports ball'}
  ball_classes = [idx for idx, name in model.names.items() if any(k in name.lower() for k in ['ball', 'basketball'])]
  rim_classes = [idx for idx, name in model.names.items() if any(k in name.lower() for k in ['rim', 'hoop', 'basket'])]
  ```
- **Fallback:** Graceful fallback to `UNAVAILABLE_NO_WEIGHTS` if weights are missing.

### 3.2 Evidence Architecture (Decision 2: Strict Advisory Separation)
- **Human Ground Truth Inviolability:**
  - `shots.outcome` (`make`, `miss`, `unknown`) is human-owned ground truth.
  - Automated detection populates `shots.automated_outcome` and `shots.trajectory_fit_r2`.
  - Automated outcomes NEVER overwrite human labels and are NEVER admitted to personal baselines automatically.
- **Trajectory Minimum Evidence Gate:**
  - $N < 4$ post-release ball detections $\to$ `trajectory_status: INSUFFICIENT_POINTS`.
  - Fit $R^2 < 0.70$ $\to$ `trajectory_status: POOR_FIT`.
  - No ball detected during shot $\to$ `ball_coverage: NOT_DETECTED`.

### 3.3 Pose Backend Experiment (Decision 3: Dedicated Offline Comparative Benchmark)
- **Primary Pose Engine:** MediaPipe Tasks Pose (`pose_landmarker.task`) remains the live, production engine for all biomechanics calculations.
- **Experimental Runner:** `evaluate_pose_backends.py` runs offline on identical clips to compare MediaPipe against `models/yolov8m-pose.pt`.
- **Metrics Evaluated:**
  - Joint detection completeness (% of frames with confidence $> 0.5$).
  - Fast-motion robustness during release frames.
  - Estimate-to-estimate joint distance (pixel and normalized offset).
  - Explicit reporting: neither model is assumed as absolute ground truth; the report documents mutual agreement and failure modes.

### 3.4 Verification & Reporting (Decision 4: Dual-Track Benchmark)
- **Part A (Dataset Object Detection):**
  - Evaluates `models/best.pt` on `Basketball.v1i.yolov8/test` (472 images).
  - Emits Precision, Recall, and mAP@50 for `basketball` and `rim`.
- **Part B (Project Video Trajectory Continuity):**
  - Runs on canonical validation clips (`raw_clips/`).
  - Reports average ball detection coverage % during shot intervals, mean trajectory $R^2$, and rim proximity detection rate.
- **Output Artifact:** `BALL_RIM_EVAL_REPORT.json` recording code commit, weights SHA256, test set size, and metric values.

---

## 4. Verification & Testing Contracts

1. **Unit Tests:**
   - `test_ball_tracker.py`: Tests dynamic class resolution, missing weights handling, trajectory parabola fitting, and shot lifecycle synchronization.
   - `test_ball_geometry.py`: Tests parabola fitting, apex calculation, entry angle calculation, and box-to-point Euclidean distances.
2. **Integration Tests:**
   - `test_pose_backend_comparison.py`: Tests offline joint matching and agreement metric calculation between MediaPipe and YOLO Pose outputs.
   - `test_ball_tracking_flow.py`: Tests end-to-end video processing with `--ball` and `--weights models/best.pt`.
3. **Manual Verification Command Index:**
   - Update `MANUAL_VERIFICATION_COMMANDS.md` with exact CLI commands for running ball tracking, pose backend comparison, and Phase 7 benchmark.

---

## 5. Next Steps
1. Run `/gsd-plan-phase 7` to generate the detailed wave-by-wave execution plan (`07-PLAN.md`).
2. Implement Phase 7 tasks and test suite.
3. Execute Phase 7 benchmarks and emit `BALL_RIM_EVAL_REPORT.json`.
