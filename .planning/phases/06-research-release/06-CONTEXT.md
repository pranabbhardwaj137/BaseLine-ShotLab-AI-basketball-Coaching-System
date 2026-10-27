# Phase 6 — Shot-Event Model and Verification: Context & Decisions

## 1. Phase Objective & Boundary
Improve basketball shot proposal detection and keyframe event timing (`start`, `dip`, `set`, `release`, `follow_through`) using verified ground-truth labels from the Phase 5 Developer Model Lab, with measurable and documented improvements over the existing rule-based heuristic baseline (`ShotPhaseDetector`).

**Strict Scope Boundary:**
- Scope is focused strictly on shot event detection, proposal gating, keyframe timing accuracy, and model verification.
- Ball and rim tracking / trajectory fitting is strictly deferred to **Phase 7**.
- End-user UI/UX and mobile upload experience is strictly deferred to **Phase 8**.
- Academic release, two-view phone experiments, and viva materials are deferred to **Phase 9**.
- Follows the data integrity and evaluation rules of [AGENTS.md](file:///c:/Users/bhard/Downloads/major_pro/major_pro/basketball_proj/AGENTS.md).

---

## 2. Division of Labor

### 2.1 Manual Developer Work (Human-in-the-Loop)
1. **Annotation Quality & Split Review:**
   - Confirm quality of exported ground-truth intervals in `shot_lab.db` and dataset manifests.
   - Supply human ground-truth annotations for held-out test clips (player `sid`) using `annotation_lab.py` before running final benchmark evaluations.
2. **Acceptance Thresholds & Model Promotion Sign-off:**
   - Review evaluation reports and error samples (false positives during gathers/dribbles, missed set shots, low-release shots, occlusions).
   - Authorize whether candidate models beat the heuristic baseline and justify being set as the recommended detector backend.
3. **No Synthetic Ground-Truth Fabrication:**
   - Developer supplies real video annotations. The coding agent cannot fabricate ground-truth labels or invent dataset contents.

### 2.2 Coding-Agent Work (Software & Modeling Plumbing)
1. **Calibrated Kinematic Baseline (`calibrated_fsm.py` / updated `analyzer.py`):**
   - Refactor and tune `ShotPhaseDetector` parameters using grid search / optimization on the `train` split.
   - Introduce kinematic velocity guards, dip-to-rise ordering, and torso-normalized elevation thresholds to minimize timing MAE.
2. **Feature Extraction Pipeline (`feature_extractor.py`):**
   - Extract frame-by-frame biomechanical feature vectors (torso-normalized wrist velocity/acceleration, relative wrist-to-shoulder/nose elevation, kinetic joint velocities for knee, hip, shoulder, elbow, wrist).
   - Implement sliding-window aggregation with clean handling of missing landmarks (interpolation limited to $\le 2$ frames).
3. **Lightweight Sequence Classifier (`shot_detector_ml.py`):**
   - Train an interpretable tabular / sequence classifier (e.g., Logistic Regression / Random Forest / gradient boosted classifier using `scikit-learn` or pure NumPy) on the `train` split.
   - Support optional deep sequence models (1D-CNN / GRU) as exploratory extensions if deep learning dependencies are present.
4. **Reproducible Evaluation & Verification Harness (`evaluate_shot_models.py`):**
   - Benchmark heuristic baseline vs. calibrated FSM vs. learned ML models against the frozen splits.
   - Enforce player-separated holdout integrity (`train`: Klay, Lavish; `val`: Mike Dunn; `test`: Sid).
   - Generate `SHOT_MODEL_EVAL_REPORT.json` recording precision, recall, F1, timing MAE/std/spread, false positives per video-minute, and subgroup breakdowns by camera view and player.
5. **Configurable Detector Interface & Proposal Integration:**
   - Expose a unified detector interface allowing selectable backends (`--detector heuristic | ml_sequence`).
   - Emit candidate proposals to `shot_lab.db` (`machine_proposals` table) preserving immutability and human reviewability.

---

## 3. Locked Decisions & Design Contracts

### 3.1 Model Architecture & Baselines (Decision 1: Two-Tier Strategy)
- **Tier 1 (Core Baselines & Tabular ML):**
  - **Calibrated Kinematic FSM:** Systematic grid search on training split to optimize transition thresholds (wrist vertical velocity $v_y$, dip-to-rise duration, debounce frames).
  - **Lightweight ML Classifier:** Sliding-window feature classifier (`scikit-learn` / `NumPy`) classifying frames into `shot_interval` vs `hard_negative` and detecting release peaks. Lightweight, highly interpretable, fast on CPU without heavy GPU requirements.
- **Tier 2 (Exploratory Deep Models):**
  - If deep learning frameworks are present, evaluate 1D-CNN or GRU sequence models as exploratory comparisons.
  - Never gate phase completion on deep model training if lightweight models or calibrated FSM deliver the verified improvement.

### 3.2 Feature Representation & Kinematics (Decision 2: Biomechanical Kinematics)
- **Torso-Normalized Motion:**
  - Normalize vertical wrist velocity $v_y$ and acceleration $a_y$ by torso length ($\|y_{shoulder} - y_{hip}\|_2$) to achieve scale-invariance across different camera distances and player heights.
- **Relative Elevation Landmarks:**
  - Relative elevation of shooting wrist relative to shoulder ($y_{wrist} - y_{shoulder}$) and nose/forehead ($y_{wrist} - y_{nose}$).
- **Kinetic Chain Angular Dynamics:**
  - Joint angles and first-order time derivatives ($\dot{\theta}$) for knee extension, hip extension, elbow extension, and wrist flexion.
- **Phase Ordering & Timing Windows:**
  - Duration of dip-to-rise phase, knee uncoiling onset relative to elbow drive, and peak wrist release velocity window.
- **Coordinate Basis Rigor:**
  - Use 2D image coordinates for scale-normalized vertical velocities and bounding box tracking.
  - Treat 3D metric world coordinates as supplementary features, explicitly documenting estimate-to-estimate disagreement.

### 3.3 Dataset Readiness & Split Verification (Decision 3: Sync Expert Val & Enforce Test Isolation)
- **Sync Phase 3 Ground-Truth into Validation Split:**
  - Ingest `ground_truth_annotations.json` (Mike Dunn clips `mikeddunnstud1.mp4`, `mikeddunnstud2.mp4`) into `shot_lab.db` labeled tables as the official `val` split.
- **Strict Player-Separated Split Partitioning:**
  - `train`: `klay_thompson`, `lavish` (10 clips, 22 labeled intervals).
  - `val`: `mike_dunn` (4 clips, 4 verified shots).
  - `test`: `sid` (7 clips).
- **Strict Fail-Fast on Empty Test Split:**
  - The evaluation harness must fail fast and refuse to declare a model "validated on test" if `test` contains zero labeled ground-truth intervals.
  - Provide an import utility / protocol for the developer to commit verified annotations for Sid clips via `annotation_lab.py` prior to the final test release gate.

### 3.4 Acceptance Thresholds & Integration Gates (Decision 4: Configurable Backend with Guardrail Fallback)
- **Target Performance Benchmarks:**
  - **F1 Score:** $F_1 \ge 0.75$ on matched shot events (matching tolerance $\pm 15$ frames / 500 ms).
  - **Release Timing Accuracy:** Release frame absolute timing error $\text{MAE} < 150\text{ms}$ (targeting $\le 100\text{ms}$, significantly beating the ~283.4 ms heuristic baseline).
  - **Negative Action Suppression:** False positive rate $\le 1.0\text{ FP / video-minute}$ across the 8 negative action classes (`dribble_drive`, `gather_no_shot`, `pump_fake`, `pass`, etc.).
- **Promotion & Fallback Logic:**
  - **Promotion:** If the learned ML sequence detector beats the heuristic baseline across validation and test holdouts on all target metrics, it becomes the recommended/default detector backend.
  - **Fallback / Exploratory:** If the learned model fails to beat the baseline or shows severe subgroup degradation (e.g., fails on oblique camera angles), the calibrated heuristic remains the default backend, and the ML detector is marked exploratory (`--detector exploratory_ml`).
- **Human-in-the-Loop Immutability:**
  - Under no circumstances does the model output directly approve baseline shots. All model predictions are stored as `machine_proposals` in `shot_lab.db` and require human review.

---

## 4. Data Integrity & AGENTS.md Governance Rules

1. **No Fabricated or Hard-Coded Labels:**
   - Training and evaluation routines must read genuine records from `shot_lab.db`, exported JSONL manifests, or documented annotation files. Never hard-code sample predictions or fabricated evaluation metrics.
2. **Missing Input Fail-Fast Protocol:**
   - If video clips or ground-truth annotation files referenced in manifests are missing on disk, execution must abort immediately with a clear path specification and retrieval instruction.
3. **Strict Zero Split Leakage:**
   - Models trained on `train` (Klay, Lavish) must never see validation (`mike_dunn`) or test (`sid`) player footage during training or threshold tuning.
4. **Synthetic Data Separation:**
   - Synthetic fixtures are strictly isolated in `test_*.py` unit test suites and must emit `synthetic: true`. They must never be mixed into `SHOT_MODEL_EVAL_REPORT.json` or presented as real dataset results.

---

## 5. Acceptance Checks & QA Verification

The implementation of Phase 6 must satisfy the following acceptance criteria:
1. **Feature Extraction Pipeline Verification:**
   - Computes torso-normalized kinematic vectors from BlazePose landmarks with correct dimensionality, handling dropped frames ($\le 2$ frames interpolated, $>2$ frames marked invalid).
2. **Calibrated Baseline Benchmark:**
   - Optimized heuristic state machine demonstrates measurable reduction in release timing error on training/validation splits compared to the uncalibrated baseline.
3. **Learned Detector Training & Evaluation:**
   - Model trains deterministically on `train` split, selects hyperparameters on `val`, and evaluates once on held-out test data.
4. **False Positive Suppression Verification:**
   - Evaluates against the 8 negative action classes, proving rejection of gathers, pump fakes, and dribbles.
5. **Configurable CLI Backend:**
   - CLI tools (`evaluate_shot_models.py`, `batch_ingest_clips.py`) accept `--detector heuristic|calibrated|ml_sequence` with identical input/output schemas.
6. **Comprehensive Automated Test Suite:**
   - Unit tests covering feature extraction, model inference, split leakage verification, and evaluation report generation.
