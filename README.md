# Baseline Shot Lab — Intelligent Basketball Performance Analysis System

A local-first AI shooting coach. Upload a video of yourself shooting, from your computer or from your phone over Wi-Fi. The app estimates your pose locally, finds each shot attempt, measures your mechanics, and writes a personalised coaching report: strengths, priorities, drills, a practice plan, and cautious technique and injury-risk-reduction guidance. Every finding is tied to timestamps and measurements from your own video, and the report can be printed or saved as a PDF. Video never leaves your computer.

> **For AI Assistants:** Agent rules: [`AGENTS.md`](AGENTS.md). Canonical verification commands: [`docs/reference/MANUAL_VERIFICATION_COMMANDS.md`](docs/reference/MANUAL_VERIFICATION_COMMANDS.md). Project status: [`.planning/STATE.md`](.planning/STATE.md), [`.planning/ROADMAP.md`](.planning/ROADMAP.md). Latest audit: [`.planning/phases/08-user-facing-app/08-07-AUDIT.md`](.planning/phases/08-user-facing-app/08-07-AUDIT.md).

---

## 1. Quickstart & Developer Onboarding

The repository is pre-configured so that onboarding is quick and does not require downloading heavy external model weights or datasets. The essential models (`models/best.pt`, `models/ballRim.pt`, `models/yolov8m-pose.pt`, `pose_landmarker.task`, `hand_landmarker.task`) and sample clips (`raw_clips/`) are included in the repository.

### Quick Setup

```powershell
# 1. Clone repository and navigate inside
cd basketball_proj

# 2. Install package in editable mode (or install requirements.txt)
python -m pip install -e .
# Alternatively: python -m pip install -r requirements.txt

# 3. Run the automated test suite (123+ tests across unit, integration, and e2e)
$env:PYTHONPATH="src;."
python -m unittest discover tests
```

### Running the Applications

#### Local Web Application (Recommended)
```powershell
# Start local web app on port 8000
python web_app.py --port 8000
# Or using the package syntax:
python -m basketball.app.web_app --port 8000
```
Open **`http://127.0.0.1:8000/`** in your browser to upload clips, view biomechanics metrics, and generate reports.

**Personalized workout:** after a report is ready, select **Generate My Personalized Workout** on the Report page. The demonstration videos are read from `workout/` in the project root (not in Git); point elsewhere with `--workout-dir PATH`. Design, rules and limits: [`docs/reference/WORKOUT_COACH.md`](docs/reference/WORKOUT_COACH.md).

#### Desktop HUD & Live Pose Analysis
```powershell
# Analyze a sample video clip with default ball & rim tracking
python main.py --video raw_clips\klay_vid.mp4 --player klay_thompson --camera-view side_90 --windowed
# Or using the package syntax:
python -m basketball.app.main --video raw_clips\klay_vid.mp4 --player klay_thompson --camera-view side_90 --windowed
```

#### Developer Annotation Lab
```powershell
python tools/annotation_lab.py
```

---

## 2. Repository Structure

The codebase is organized into modular packages under `src/basketball/` alongside dedicated directories for tests, scripts, developer tools, evaluation benchmarks, configurations, and data.

```
basketball_proj/
├── src/basketball/                    # Core library and production application
│   ├── core/                          # Pose estimation and kinematic feature extraction
│   │   ├── analyzer.py                # 2D/3D joint angle computation and phase detection
│   │   ├── pose_engine.py             # MediaPipe BlazePose 33-landmark inference engine
│   │   └── shot_feature_extractor.py  # Scale-normalized biomechanical kinematic features
│   ├── tracking/                      # Object tracking and shot detection
│   │   ├── ball_tracker.py            # YOLO ball and rim tracking with evidence gating
│   │   ├── ball_geometry.py           # Parabolic trajectory fitting and rim entry angles
│   │   ├── calibrated_fsm.py          # Calibrated Finite State Machine shot detector
│   │   └── shot_detector_ml.py        # ML sequence classifier for shot attempts
│   ├── analysis/                      # Biomechanics and performance analysis
│   │   ├── shooting_analysis.py       # 20 per-attempt metrics, consistency, and make/miss split
│   │   ├── baseline_engine.py         # Player personal baseline computation
│   │   └── pro_comparator.py          # Pro benchmark comparisons (Curry, Klay, Ray Allen)
│   ├── coaching/                      # Evidence-based coaching rules and advice
│   │   ├── shot_coach.py              # Rule-based findings, drill plans, and injury guidance
│   │   ├── coach_engine.py            # Multi-attempt coaching aggregation engine
│   │   ├── coaching_service.py        # Remediation follow-up and drill plan generation
│   │   └── llm_coach.py               # Optional grounded Gemini AI explanation
│   ├── persistence/                   # Data storage layer
│   │   └── shot_lab_db.py             # SQLite schema v7: sessions, shots, baselines, audits
│   ├── services/                      # High-level backend services
│   │   ├── video_analysis_service.py  # Async video decode, pose cache v2, and replay generation
│   │   ├── report_service.py          # 10-section coaching report builder and keyframe renderer
│   │   └── history_service.py         # Player progression history, trends, and weekly goals
│   ├── hand/                          # Hand and wrist tracking
│   │   └── hand_engine.py             # MediaPipe hand landmarker and wrist snap analysis
│   └── app/                           # Application entry points
│       ├── main.py                    # Desktop OpenCV HUD and live camera runner
│       └── web_app.py                 # Multi-client local HTTP web server and REST API
├── tests/                             # Comprehensive test suites
│   ├── unit/                          # 90+ fast, isolated unit tests
│   ├── integration/                   # 30+ subsystem and database integration tests
│   ├── e2e/                           # End-to-end API and browser UI test suites
│   └── support/                       # Synthetic test fixtures and stick-figure pose generators
├── scripts/                           # Maintenance and batch processing scripts
│   ├── batch_ingest_clips.py          # Automated batch ingestion and proposal generation
│   ├── clean_db_provenance.py         # Database provenance cleanup utility
│   ├── download_models.py             # Model asset verification and downloader
│   ├── export_dataset.py              # Normalized dataset exporter and manifest builder
│   ├── inspect_db.py                  # Database schema and content inspector
│   ├── review_shots.py                # Terminal-based shot review tool
│   ├── seed_shot_lab.py               # Test dataset database seeder
│   └── sync_split_annotations.py      # Ground-truth annotation synchronization tool
├── tools/                             # Interactive developer tools
│   └── annotation_lab.py              # Web-based ground truth annotation GUI
├── evaluation/                        # Evaluation benchmarks and validation harnesses
│   ├── evaluate_pipeline.py           # Pipeline measurement accuracy and timing benchmark
│   ├── evaluate_video.py              # Single-video diagnostic evaluator
│   ├── evaluate_dataset.py            # Multi-clip dataset benchmark
│   ├── evaluate_ball_tracking.py      # Ball and rim trajectory evaluation harness
│   ├── evaluate_pose_backends.py      # MediaPipe vs. YOLOv8 Pose comparative benchmark
│   ├── evaluate_public_datasets.py    # Public benchmark evaluation script
│   ├── evaluate_shot_models.py        # Shot detector comparison (heuristic vs FSM vs ML)
│   └── validate_dataset.py            # Dataset split and label integrity validator
├── configs/                           # System and dataset configuration
│   └── clip_splits.json               # Canonical clip-to-split mapping (train/val/test)
├── data/                              # Data manifests, annotations, and reports
│   ├── ground_truth_annotations.json  # Expert human-labeled shot intervals
│   ├── manifests/                     # Dataset and weights manifests
│   └── reports/                       # Generated evaluation benchmark reports
├── docs/                              # Project documentation
│   ├── reference/                     # Manual commands, metric dictionary, and deep dives
│   │   ├── MANUAL_VERIFICATION_COMMANDS.md  # Canonical runnable command index
│   │   ├── METRIC_DICTIONARY.md             # Biomechanical metric definitions
│   │   ├── AI_Models_Deep_Dive.md           # Model architecture review
│   │   └── VIDEO_ANNOTATION_PROTOCOL.md     # Protocol for video labeling
│   └── setup/                         # Setup and installation guides
├── web/                               # Frontend single-page application
│   ├── index.html                     # Main application HTML shell
│   ├── app.js                         # Core client logic, review UI, and player flow
│   ├── report.js                      # 10-section report rendering and PDF print formatting
│   └── app.css                        # Modern responsive design and design tokens
├── models/                            # Machine learning model weights
│   ├── best.pt                        # Primary YOLO ball & rim detection model (6 MB)
│   ├── ballRim.pt                     # Alternative ball & rim detection model (22 MB)
│   └── yolov8m-pose.pt                # YOLOv8 Medium pose estimation model (53 MB)
├── main.py                            # Backward-compatible root entry point for Desktop HUD
├── web_app.py                         # Backward-compatible root entry point for Web App
├── pyproject.toml                     # Modern package configuration
└── requirements.txt                   # Pinned project dependencies
```

---

## 3. Key Principles & Architecture

Baseline Shot Lab is designed around **evidence before advice**:

- **Grounded Measurements**: Each metric records its value, unit, timestamp, confidence, and the camera views for which it is geometrically valid. Occluded joints or incompatible viewpoints are marked *not measurable* rather than guessed.
- **Deterministic Coaching Rules**: Findings come from deterministic biomechanical rules applied only to medium- or high-confidence measurements, explicitly citing the attempts and frame timestamps they rest on.
- **Human-in-the-Loop Verification**: Machine-proposed attempts are quarantined in the database (`shot_lab.db`) until explicitly reviewed by the player or coach. Confirming attempts raises finding confidence; discarded attempts are never included in baselines.
- **Conservative Injury Guidance**: Explains what the video shows, why it matters biomechanically, and offers conservative modifications. Never diagnoses, predicts, or scores injury risk.

### Data Flow

```
 Browser / Phone Client (web/index.html, app.js, report.js)
   │  Video Upload (with progress) · Review UI · Replay Player · Report View
   ▼
 web_app.py (Standard Library HTTP Server)
   ├── Security Guard: CSRF check, Host validation, LAN access code, rate limiting
   ├── Job Store (<db>.web_jobs.sqlite3): Async job queues, progress tracking, cancellation
   ├── Worker Pipeline (services/video_analysis_service.py):
   │     OpenCV Video Decode → MediaPipe BlazePose (33 landmarks, raw + 3D metric world)
   │     → ShotPhaseDetector (dip, rise, release, landing proposals)
   │     → Pose Cache v2 (.json.gz raw unlagged landmark stream)
   │     → H.264 Replay Generation (for iOS HEVC compatibility)
   │     → services/report_service.py:
   │          analysis/shooting_analysis.py (20 biomechanical metrics, consistency, make/miss)
   │          coaching/shot_coach.py (strengths, priority improvements, scaled drills)
   │          OpenCV Keyframe Extraction → user_data/keyframes/<session>/
   └── SQLite Database (shot_lab.db, Schema v7):
         sessions, labeled_clips, shots, attempt_analysis, session_reports, baselines, remediations
```

---

## 4. Guidelines for Adding New Features

When extending the system with new features, follow these architectural guidelines:

1. **Keep Existing Features Intact**: Existing entry points (`main.py`, `web_app.py`), CLI arguments, and API routes must remain backward-compatible.
2. **Modular Placement**:
   - New kinematic metrics: Place in `src/basketball/analysis/shooting_analysis.py`.
   - New coaching rules: Place in `src/basketball/coaching/shot_coach.py`.
   - New database queries: Add helper methods to `src/basketball/persistence/shot_lab_db.py`.
   - New API endpoints: Add route handler in `src/basketball/app/web_app.py`.
3. **Use Package Imports**: Within `src/`, always use absolute package imports:
   ```python
   from basketball.core.pose_engine import PoseEngine
   from basketball.persistence.shot_lab_db import ShotLabDB
   ```
4. **Write Tests**: Add corresponding unit tests in `tests/unit/` or integration tests in `tests/integration/`. Use synthetic test fixtures from `tests/support/tests_support_synthetic_pose.py` to keep tests deterministic and independent of GPU/ultralytics availability.
5. **Update Verification Index**: If an entry point or CLI option is added or changed, update [`docs/reference/MANUAL_VERIFICATION_COMMANDS.md`](docs/reference/MANUAL_VERIFICATION_COMMANDS.md).

---

## 5. Testing & Verification

Run the entire automated test suite:

```powershell
$env:PYTHONPATH="src;."
python -m unittest discover tests
```

- **Unit tests (`tests/unit/`)**: 92 tests verifying ball geometry, trajectory fitting, biomechanics calculations, baseline aggregation, coaching rules, and dataset export.
- **Integration tests (`tests/integration/`)**: 31 tests verifying database workflows, video processing pipelines, annotation lab flows, and model evaluation routines.
- **E2E tests (`tests/e2e/`)**: 17 tests verifying the web server REST API, file upload handling, job lifecycle, keyframe security, and session management.
- **Workout coach**: `tests/unit/test_workout_planner.py` (catalog, equipment/level/pain rules, finding links, duration formula, final-10% voice rule, honest summary), `tests/e2e/test_workout_api.py` (routes, progress lock, safe media streaming) and `tests/e2e/test_workout_ui.py` (Playwright with a controlled clock and recorded speech; needs Playwright Chromium and ffmpeg, otherwise skipped).

All tests are designed to run out-of-the-box on standard CPU environments without requiring optional dependencies like GPU PyTorch or cloud APIs.

---

## 6. Academic Profile & Team

- **Course:** BCS506 Major Project, B.E. Information Science & Engineering, VTU — BMS Institute of Technology & Management, Bengaluru (2025–26)
- **Guide:** Asst. Prof. Amulya P, Department of ISE
- **Team:**
  - Pranab Bhardwaj (1BY23IS154) — Core vision layer, architecture, and tracking pipeline
  - Pavan R Bhat (1BY23IS145) — Kinematics and shot-phase detection
  - Pracheth Kashyap (1BY23IS152) — Session recorder, database, and dataset export
  - Puneetgouda Patil (1BY23IS165) — Feedback, coaching rules, and output interface
- **Lineage:** Combines `Basketball-Shot-Analyzer` (kinematics, phase detection, session recording) and `basketball-shot-analysis` (YOLO ball/rim, trajectory fitting), rebuilt on the MediaPipe Tasks API, Ultralytics YOLO, and SQLite provenance engine.
