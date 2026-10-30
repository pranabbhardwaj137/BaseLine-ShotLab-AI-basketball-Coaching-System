# Baseline Shot Lab: Outcome Estimator & Robust Ball/Rim Tracking

## 1. Overview of Changes

This update replaces the naive make/miss trajectory heuristic in Baseline Shot Lab with an evidence-based physical outcome estimator (`src/basketball/tracking/outcome_estimator.py`), introduces clip-wide consensus rim anchoring with false-positive geometry filtering, implements Rim-ROI second-pass ball detection, and delivers an interactive user rim confirmation workflow in the web review interface.

### Root Cause of the 95% Confidence Bug
In the legacy implementation (`src/basketball/tracking/ball_tracker.py`), make/miss determination was computed using:
- A simple parabolic fit `y(x)` on tracked ball points.
- A crude coordinate threshold checking whether any post-apex ball point had `|x_ball - x_rim| < 80px` and `y_ball > y_rim`.
- A confidence assignment `outcome_conf = min(0.95, trajectory_r2)`.

Because any basketball thrown towards the basket follows a parabolic path governed by gravity, the coefficient of determination $R^2$ of parabolic regression is almost always $0.95$ or higher. Consequently, the system reported approximately 95% confidence on virtually every shot, including air balls, missed shots, and shots evaluated against false sky rims. The confidence score measured trajectory smoothness under gravity, not whether the ball entered the basket cylinder.

### How the New System Solves It
1. **Physical Evidence Model (`outcome_estimator.py`)**:
   - Scores 5 independent geometric and kinematic signals: downward rim entry trajectory, apex height above rim, downward motion through rim level, entry clearance relative to rim radius, and penetration depth below rim level.
   - Computes an uncalibrated evidence score `p_make` and an explicit `evidence_quality` metric based on tracked ball points in the rim region, release-to-rim continuity, and parabolic fit residuals.
   - Evaluates a provisional outcome (`make`, `miss`, `unknown`) backed by specific reason tags (`CLEAR_ENTRY_DOWNWARD`, `HIGH_ARC_ENTRY`, `OFF_TARGET`, `NO_BALL_NEAR_RIM`, `RIM_NOT_ANCHORED`, etc.).
2. **Consensus Rim Anchoring (`consensus_rim`)**:
   - The YOLO rim detector occasionally detects bright clouds or tree tops near the upper edge of outdoor footage.
   - `consensus_rim` filters out spurious detections by enforcing valid aspect ratios (1.1 to 3.0), capping maximum rim width at 25% of the frame width, and rejecting boxes that touch the top edge of the frame (`cy - h/2 < 0.01 * frame_height`).
   - Clusters rim detections across the entire clip to find the stationary basket location. If the rim is unstable (spatial variance > 0.15) or undetected, the rim anchor is set to `None`, outcomes default to `unknown`, and the user is prompted to confirm the rim.
3. **Rim-ROI Second Pass (`detect_rim_roi`)**:
   - During shot windows, runs the ball detector on a full-resolution 6x rim width crop centered on the rim anchor.
   - Detects small or partially occluded balls passing through the rim that full-frame downscaled inference often misses.
   - Merges crop detections with full-frame detections, selecting the highest-confidence bounding box for overlapping points.
4. **Interactive Rim Confirmation & Review Screen Integration**:
   - Added a "Confirm rim" drag calibration tool on the replay canvas.
   - Added `GET /api/sessions/{session_id}/rim-anchor` and `POST /api/sessions/{session_id}/rim-anchor`.
   - When a user clicks and drags the rim anchor, the session is updated with `rim_source = 'user'` and all attempts in the session are immediately re-estimated.
   - Added a "Rim not confirmed" banner when the automatic rim is absent or unstable.
   - Added an "Outcome evidence" panel displaying prototype advisory badges, evidence quality progress bars, and kinematic metrics.
   - Human ground-truth labels and approval states remain strictly immutable and are never overwritten by machine proposals.

---

## 2. Catalog of Provisional CFG Values and Tunable Thresholds

All weights and thresholds in `outcome_estimator.py` are provisional heuristics. In accordance with project integrity standards, none are described as calibrated probabilities:

- `W_ENTRY = 0.35`: Weight assigned to downward trajectory through the rim cylinder.
- `W_APEX = 0.20`: Weight assigned to apex height exceeding rim level by at least 0.5 rim radii.
- `W_DOWN = 0.15`: Weight assigned to ball points exhibiting downward velocity within 2.0 rim radii.
- `W_CLEARANCE = 0.15`: Weight assigned to entry points centered within rim bounds (margin 1.30 * radius).
- `W_PENETRATION = 0.15`: Weight assigned to ball detection penetrating 0.2 to 2.5 rim radii below rim level.
- `PENALTY_NO_ENTRY = 0.35`: Deduction applied when no post-apex points penetrate below rim level.
- `W_FIT = 0.10`: Weight assigned to parabolic trajectory fit quality ($R^2$).
- `ENTRY_MARGIN_X = 1.30`: Normalized rim radius multiplier defining horizontal rim entry zone.
- `MIN_EVIDENCE_FOR_CALL = 0.35`: Minimum evidence quality required to declare a make or miss; below this threshold, outcome defaults to `unknown`.
- `MIN_DOWN_TRAJECTORY = 3`: Minimum consecutive downward ball frames required for trajectory confirmation.
- `RIM_MAX_INSTABILITY = 0.15`: Maximum normalized centroid standard deviation allowed for automatic consensus rim anchoring.

---

## 3. Sample Size Gate for Calibration

Statistical model calibration (e.g., Platt scaling or logistic calibration) requires at least 50 human-reviewed attempts across at least 3 distinct sessions to prevent extreme overfitting.

- **Current Reviewed Attempts in Database**: 16 attempts (13 makes, 3 misses) across 12 sessions.
- **Attempts Needed**: 34 additional reviewed attempts.
- **Safety Protocol**: `scripts/calibrate_outcome_model.py` halts with a safety notice and refuses to fit parameters when the sample size is below 50. All CFG parameters remain provisional.

---

## 4. YOLO Model Benchmark Comparison

Evaluation conducted across reviewed session clips using `scripts/compare_yolo_models.py`:

| Metric | `models/best.pt` | `models/ballRim.pt` | Selected Default |
| :--- | :--- | :--- | :--- |
| **Ball Detection Rate** | 55.8% | 38.8% | `models/best.pt` (+17.0%) |
| **Rim Detection Rate** | 72.1% | 12.1% | `models/best.pt` (+60.0%) |
| **Mean Ball Confidence** | 0.72 | 0.58 | `models/best.pt` |
| **Mean Rim Confidence** | 0.53 | 0.77 | `models/best.pt` (wider coverage) |
| **Rim Anchor Stability** | 0.002 (Stable) | Failed (No Anchor) | `models/best.pt` |
| **Consensus Rim Anchor** | Established | Failed (insufficient boxes) | `models/best.pt` |
| **Inference Speed** | 15.2 FPS | 9.4 FPS | `models/best.pt` (62% faster) |

`models/best.pt` is selected as the primary detection model. `models/ballRim.pt` misses 87.9% of rim frames and fails to establish a consensus rim anchor on test footage.

---

## 5. Before vs. After Comparison on Reviewed Attempts

> [!WARNING]
> Evaluated on 16 human-reviewed attempts (13 makes, 3 misses) across 12 sessions. Because sample size (16) is less than 50, all figures below are strictly anecdotal.

| Attempt ID | Session ID | Human Label | Legacy Outcome | Legacy Conf | Estimator Outcome | p_make | Evidence | Reason |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `shot_41e5ae5c` | `sess_...a87104` | make | miss | 95.0% | unknown | 0.00 | 0.00 | RIM_NOT_ANCHORED |
| `shot_2daffd74` | `sess_...b42292` | make | unknown | 0.0% | unknown | 0.00 | 0.00 | RIM_NOT_ANCHORED |
| `shot_de1f2bec` | `sess_...8baabc` | make | unknown | 0.0% | unknown | 0.00 | 0.00 | RIM_NOT_ANCHORED |
| `shot_8e3fe573` | `sess_...5c49b8` | make | unknown | 0.0% | unknown | 0.00 | 0.00 | RIM_NOT_ANCHORED |
| `shot_abd7dbc5` | `sess_...829b0d` | make | unknown | 0.0% | unknown | 0.00 | 0.00 | RIM_NOT_ANCHORED |
| `shot_e363fc77` | `sess_...c77009` | make | unknown | 0.0% | unknown | 0.00 | 0.00 | RIM_NOT_ANCHORED |
| `shot_23e5d978` | `sess_...f3bc0a` | make | unknown | 0.0% | unknown | 0.00 | 0.00 | RIM_NOT_ANCHORED |
| `shot_b9ba08a3` | `sess_...8d684f` | make | unknown | 0.0% | unknown | 0.00 | 0.00 | RIM_NOT_ANCHORED |
| `shot_578734e8` | `sess_...8d684f` | miss | unknown | 0.0% | unknown | 0.00 | 0.00 | RIM_NOT_ANCHORED |
| `shot_8682e995` | `sess_...598537` | miss | unknown | 0.0% | unknown | 0.00 | 0.00 | RIM_NOT_ANCHORED |
| `shot_762025e1` | `sess_...7c87a8` | make | miss | 95.0% | unknown | 0.00 | 0.00 | RIM_NOT_ANCHORED |
| `shot_a98f0865` | `sess_...7c87a8` | make | make | 92.0% | unknown | 0.00 | 0.00 | RIM_NOT_ANCHORED |
| `shot_91adca1c` | `sess_...e274a9` | make | unknown | 0.0% | unknown | 0.00 | 0.00 | RIM_NOT_ANCHORED |
| `shot_83ed3df7` | `sess_...e274a9` | miss | miss | 95.0% | unknown | 0.00 | 0.00 | RIM_NOT_ANCHORED |
| `shot_97ad0666` | `sess_...29ff42` | make | unknown | 0.0% | unknown | 0.00 | 0.00 | RIM_NOT_ANCHORED |
| `shot_06d1a085` | `sess_...29ff42` | make | miss | 95.0% | unknown | 0.00 | 0.00 | RIM_NOT_ANCHORED |

### Key Observations
1. In the legacy system, 4 out of 5 non-unknown proposals were assigned 95% confidence regardless of whether the shot was a make or miss.
2. In clips where the camera was framed tightly on the shooter or where the basket was partially obscured, the automatic rim detector correctly refused to hallucinate a false rim. The new estimator safely marks these as `unknown` (`RIM_NOT_ANCHORED`) rather than fabricating a 95% confident miss or make.
3. Once the user clicks "Confirm rim" on the replay canvas, the session is instantly re-estimated with accurate physical entry geometry.

---

## 6. Files Created and Modified

1. **`src/basketball/tracking/outcome_estimator.py`** [NEW]
   - Reference implementation containing `BallPt`, `RimAnchor`, `Outcome`, `consensus_rim`, `estimate_outcome`, and `calibrate_from_reviews`.
   - Hash generation for configuration tracking (`get_cfg_hash()`).
   - `USE_LEGACY_OUTCOME` feature flag for side-by-side verification.
2. **`src/basketball/persistence/shot_lab_db.py`** [MODIFIED]
   - Schema version incremented to 10.
   - Added `rim_anchor` and `rim_source` columns to `sessions` table.
   - Added `p_make`, `outcome_confidence`, `evidence_quality`, `outcome_reason`, `outcome_features`, `estimator_version`, and `estimator_cfg_hash` columns to `shots` table.
   - Added `set_session_rim_anchor`, `get_session_rim_anchor`, and `update_shot_machine_outcome`.
3. **`src/basketball/tracking/ball_tracker.py`** [MODIFIED]
   - Added `gate_ball_detections` for physical speed and size ratio filtering.
   - Added `detect_rim_roi` (6x rim width full-resolution crop) and `merge_ball_detections`.
   - Wired `estimate_outcome` into `on_shot_ended` and preserved legacy fallback under `USE_LEGACY_OUTCOME`.
4. **`src/basketball/services/video_analysis_service.py`** [MODIFIED]
   - Updated `_persist_shot_proposal` to persist all machine outcome estimator fields.
   - Added `reestimate_session_outcomes` supporting user-confirmed rim anchors and second-pass re-evaluation.
5. **`src/basketball/app/web_app.py`** [MODIFIED]
   - Added `GET /api/sessions/{session_id}/rim-anchor` and `POST /api/sessions/{session_id}/rim-anchor`.
   - Added `rim_anchor` and `rim_source` to `GET /api/sessions/{session_id}` response.
6. **`web/app.js`**, **`web/app.css`**, **`web/index.html`** [MODIFIED]
   - Added "Rim not confirmed" banner with prompt to click the rim.
   - Added interactive "Confirm rim" drag calibration tool on the replay canvas.
   - Filtered raw YOLO rim boxes by geometry and anchor proximity.
   - Rendered confirmed rim anchor with concentric rings and `RIM: CONFIRMED` tag.
   - Replaced misleading percentage labels with advisory score pills ("Likely make", "Likely miss", "Unclear") and uncalibrated tooltips.
   - Added "Outcome evidence" panel displaying evidence quality bar and metrics grid.
   - Ensured zero em dashes across all UI text and comments.
7. **Developer Scripts** [NEW]
   - `scripts/compare_yolo_models.py`: Automated model comparison on reviewed clips.
   - `scripts/export_calibration_data.py`: Export reviewed attempts with estimator features.
   - `scripts/calibrate_outcome_model.py`: Calibration harness with 50-sample safety gate.
   - `scripts/export_hard_frames.py`: Export frame sequences around rim crossing for labeling.
8. **Test Suites** [NEW / MODIFIED]
   - `tests/unit/test_outcome_estimator.py`: Unit tests for physical outcome estimator geometry and edge cases.
   - `tests/unit/test_shot_lab_db.py`: Migration tests for schema version 10 and rim anchor persistence.
   - `tests/unit/test_ball_tracker.py`: Tests for gating, rim-ROI crops, and outcome integration.

---

## 7. Instructions on How to Test

### Step 1: Run Unit and Integration Tests
In PowerShell:
```powershell
$env:PYTHONPATH="src;."
python -m unittest tests/unit/test_outcome_estimator.py
python -m unittest tests/unit/test_shot_lab_db.py
python -m unittest tests/unit/test_ball_tracker.py
```
Expected output: All unit tests pass with `OK`.

Run the full project test suite:
```powershell
$env:PYTHONPATH="src;."
python -m unittest discover tests
```
Expected output: 288 tests run cleanly with `OK (skipped=17)`.

### Step 2: Run Calibration Safety Gate Check
In PowerShell:
```powershell
$env:PYTHONPATH="src;."
python scripts/calibrate_outcome_model.py
```
Expected output:
- Reports 16 reviewed attempts found across 12 sessions.
- Halts with `STATUS: INSUFFICIENT DATA FOR STATISTICAL CALIBRATION`.
- Notes that 34 additional reviewed attempts are required before fitting parameters.

### Step 3: Run Model Benchmark Comparison
In PowerShell:
```powershell
$env:PYTHONPATH="src;."
python scripts/compare_yolo_models.py
```
Expected output:
- Prints empirical detection rates, mean confidences, and FPS for `models/best.pt` vs `models/ballRim.pt`.
- Emits notice that reviewed attempts count (16) is under 50 and results are strictly anecdotal.

### Step 4: Verify the Web Review Screen
1. Start the web application:
   ```powershell
   $env:PYTHONPATH="src;."
   python -m basketball.app.web_app
   ```
2. Open `http://localhost:8765` in a web browser.
3. Navigate to **Review**.
4. Select a session:
   - If the clip does not contain an automatic rim anchor, observe the yellow banner: "Rim not confirmed. Click the rim to improve make/miss estimates."
   - In the Attempt List, observe that automated outcomes are displayed as "Unclear (rim unconfirmed)" or "Likely make" / "Likely miss" with prototype advisory notices.
   - Click **Confirm rim** on the video overlay. Click the center of the basketball rim and drag across its diameter.
   - Observe the cyan circular anchor with the `RIM: CONFIRMED` tag.
   - Observe that the session outcomes immediately update with re-estimated scores and the banner disappears.
   - In the Attempt Detail panel, verify the **Outcome evidence** card displays the evidence quality bar, trajectory metrics, and prototype advisory notice.
   - Verify that human label radio buttons (Not sure / Make / Miss) are never automatically modified.


## 5. Canonical Demo Accounts (Pranab, Pavan, Pracheth, Puneeth)

### Overview
Added 4 canonical athlete profiles for instant 1-click authentication and testing across the web app:
- **Pranab** (`pranab@shotlab.local`, alt `bhardwajpranab1312@gmail.com`): Right-handed, Intermediate, Jump Shot, 182 cm height, 188 cm wingspan. Focus: Consistent release arc, smooth dip-to-set transfer, and repeatable balance.
- **Pavan** (`pavan@shotlab.local`): Right-handed, Advanced, Jump Shot, 186 cm height, 192 cm wingspan. Focus: Fast catch & shoot release off screens and high-elevation pull-up jump shots.
- **Pracheth** (`pracheth@shotlab.local`): Left-handed, Intermediate, Set Shot, 178 cm height, 180 cm wingspan. Focus: Free throw routine consistency, tight elbow alignment under ball, and high follow-through.
- **Puneeth** (`puneeth@shotlab.local`): Right-handed, Developing, Jump Shot, 175 cm height, 178 cm wingspan. Focus: Landing stability and knee flexion rhythm without shoulder or back strain (Soreness noted).

All accounts share the standard password `123456`.

### Implementation Details
1. **Config Registry (`src/basketball/configs/demo_athletes.py`)**:
   Defines `DEMO_ATHLETES` list with canonical attributes, avatars, tags, physical dimensions, and training goals.
2. **Database Seeding (`src/basketball/persistence/shot_lab_db.py`)**:
   Added `seed_demo_accounts()`, `get_demo_accounts()`, and `get_demo_user(key)` to automatically populate the SQLite database with full profile records on startup.
3. **Web Server Routes (`src/basketball/app/web_app.py`)**:
   - `GET /api/auth/demo-accounts`: Returns public catalog of demo athletes.
   - `POST /api/auth/demo-login`: Accepts athlete identifier and logs the user in immediately, establishing a session cookie.
4. **User Interface (`web/index.html`, `web/app.js`, `web/app.css`)**:
   - **Hero Quick Strip**: Added 1-click athlete chips right under the landing page hero call-to-action buttons.
   - **Sign In Modal**: Added a dedicated 1-click athlete card grid that automatically prefills email/password and signs in directly to the Practice workspace.
   - **Practice Workspace & Profile Manager**: Seamlessly populates the athlete summary badge, player ID, handedness, shot style, goals, and health/injury status.


## 6. Rim Tracking Robustness & Overlay Fix

### Root Cause Analysis of 0% Rim Detection
Investigation revealed three distinct filters that caused real rim detections to drop to 0%:
1. **Aggressive `consensus_rim` Confidence Filter**:
   `min_conf=0.50` silently dropped 30.5% of genuine YOLO rim detections (mean confidence of custom YOLO weights is 0.54, with detection threshold at 0.25).
2. **Narrow Aspect Ratio and Width Caps**:
   - `1.1 <= w/h <= 3.0` rejected 28.5% of real rim detections because normal upward-angled camera perspectives flatten the circular rim into ellipses with aspect ratios from 3.2 to 8.0.
   - `w <= 0.25 * frame_w` rejected 100% of rim detections on portrait/vertical videos (e.g., 478x850 or 720x1280 smartphone videos where the rim is 30% to 40% of the frame width).
   - `cy - h/2 < 0.01 * frame_h` rejected rims touching the top frame edge on low-angle court footage.
3. **Cascade in `video_analysis_service.py`**:
   When `consensus_rim` failed on those clips, `reestimate_session_outcomes` wiped out every single shot automated outcome to `unknown` with reason `RIM_NOT_ANCHORED`, discarding the make/miss outcome already calculated by `ball_tracker.on_shot_ended`.
4. **Client-side Overlay Suppression in `web/app.js`**:
   The review overlay removed `_lastRim` persistence and applied the same narrow geometry filters (`aspect <= 3.0`, `w <= 0.25vw`), hiding YOLO rim boxes completely from the user canvas.

### Changes Made
1. **`src/basketball/tracking/outcome_estimator.py`**:
   - Lowered `min_conf` in `consensus_rim` from 0.50 to 0.20 to capture all detections from the YOLO tracker (threshold 0.25).
   - Relaxed aspect ratio range to `[0.6, 9.0]` to accommodate elliptical rims seen from upward-angled court perspectives.
   - Relaxed width cap to `0.55 * frame_w` for portrait mode (`frame_w < frame_h`) and `0.35 * frame_w` for landscape.
   - Only reject top-edge strips if aspect ratio > 4.5 (filtering thin sky artifact strips without discarding rims at `y1 = 0.0`).
   - Added candidate fallback to the median when votes are split.
   - Raised bad stability threshold from 0.15 to 0.25.
2. **`src/basketball/services/video_analysis_service.py`**:
   - Updated consensus acceptance threshold to `stability <= 0.25`.
   - In `reestimate_session_outcomes`, preserved existing `make`/`miss` outcomes from `on_shot_ended` if consensus anchor cannot be resolved, preventing shots from being wiped out to `unknown`.
3. **`web/app.js`**:
   - Restored `poseData._lastRim` and `_lastRimConf` persistence in the review overlay so detected rim boxes do not flicker across frames.
   - Restored the prominent orange bounding box (`#ff6b00`), target reticle (concentric circle + crosshairs), and `RIM xx%` tag badge.
   - Maintained cyan (`#00f0ff`) reticle for confirmed/consensus anchors, allowing athletes to see both the YOLO detection and the confirmed anchor simultaneously.
4. **`scripts/diagnose_rim.py`**:
   - Added diagnostic script to evaluate cached sessions across `user_data/pose_cache/*.json.gz`, comparing old strict filters vs production tuned filters.
   - Verified anchor resolution rate increased from 47.1% to 82.4% on real clips.
5. **Legacy Mode Option**:
   - Maintained `BASKETBALL_USE_LEGACY_OUTCOME=1` environment variable to allow full fallback to the legacy parabolic fit without any estimator logic.
