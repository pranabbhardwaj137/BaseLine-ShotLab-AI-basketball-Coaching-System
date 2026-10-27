# Agent Rules

## Repository Architecture & Conventions

- **Source Code (`src/basketball/`)**: All application and library logic lives under `src/basketball/`. Subpackages are domain-separated:
  - `core/`: Pose estimation (`pose_engine.py`), joint angle computation (`analyzer.py`), and feature extraction (`shot_feature_extractor.py`).
  - `tracking/`: Ball/rim tracking (`ball_tracker.py`), trajectory math (`ball_geometry.py`), FSM detector (`calibrated_fsm.py`), and ML detector (`shot_detector_ml.py`).
  - `analysis/`: Biomechanical shooting metrics (`shooting_analysis.py`), baseline engine (`baseline_engine.py`), and pro comparator (`pro_comparator.py`).
  - `coaching/`: Rules-based coaching (`shot_coach.py`, `coach_engine.py`), coaching service (`coaching_service.py`), and optional LLM coach (`llm_coach.py`).
  - `persistence/`: SQLite database layer (`shot_lab_db.py`).
  - `services/`: Video processing pipeline (`video_analysis_service.py`), report generation (`report_service.py`), and player history (`history_service.py`).
  - `hand/`: Hand tracking and wrist snap analysis (`hand_engine.py`).
  - `app/`: CLI desktop HUD (`main.py`) and local web server (`web_app.py`).
- **Tests (`tests/`)**:
  - `tests/unit/`: Fast, isolated tests for mathematical calculations, state machines, and rule engines.
  - `tests/integration/`: Subsystem integration tests (e.g. database flows, video analysis pipelines).
  - `tests/e2e/`: End-to-end tests for the web application and browser interface.
  - `tests/support/`: Shared test fixtures and synthetic pose generators (`tests_support_synthetic_pose.py`).
- **Developer Scripts & Tools**:
  - `scripts/`: Batch ingestion (`batch_ingest_clips.py`), export (`export_dataset.py`), seeding, and database utilities.
  - `tools/`: Interactive developer tools, such as the annotation lab (`annotation_lab.py`).
  - `evaluation/`: Benchmark evaluation harnesses for accuracy, timing, ball tracking, and pose comparison.
- **Data & Configuration**:
  - `configs/`: Clip splits and player configurations (`clip_splits.json`).
  - `data/`: Ground truth annotations, manifests (`DATASET_MANIFEST.md`, `WEIGHTS_MANIFEST.md`), and evaluation reports.
  - `docs/`: Reference specifications, setup guides, and manual verification index.
- **Entry Points & Compatibility**:
  - Package entry points: `python -m basketball.app.main` (desktop HUD) and `python -m basketball.app.web_app` (web server).
  - Root entry point shims (`main.py`, `web_app.py`) are maintained for backward compatibility. New features must not break existing interfaces.
  - All unit and integration tests must pass cleanly: `$env:PYTHONPATH="src;."; python -m unittest discover tests`.

## Data and Implementation Integrity

- Do not hard-code dataset contents, copied sample predictions, expected evaluation scores, or fabricated labels into production code or reports. Read real inputs from explicit CLI options, configuration, environment variables, or a documented data manifest.
- Synthetic values are allowed only in clearly named test fixtures. Mark their reports and output as synthetic; never present them as results from a public or real-world dataset.
- Do not claim a public dataset has been downloaded, parsed, or evaluated unless the implementation actually reads its source files and produces results from those records. Static dataset descriptions and schema checks are not dataset evaluations.
- If a requested file, dataset, Drive link, credentialed resource, or external dependency is inaccessible or missing, stop work that depends on it. Tell the user exactly what is inaccessible and what path/access is needed. Do not silently skip it or replace it with mock data.
- In the same response, give the user a concrete manual retrieval/access command appropriate to the source (for example, a `git clone`, official dataset download command, or local path to upload). Ask the user to provide the downloaded files or accessible path, then continue independent work that does not depend on them.
- Keep external dataset downloads outside version control by default; record source, revision, license, and expected directory in a manifest. Never redistribute footage or annotations beyond their license terms.
- Evaluation outputs must record input file IDs, annotation source, split, sample counts, metric definitions, and whether results are synthetic, public-data, or project-recorded. Fail clearly when inputs are missing or labels do not cover evaluated frames.
- At the end of the agent workflow give the user steps on how to test out the work by giving python executable command, what inputs they need to provide, and what output to expect.
- Never make up or fabricate any results. Use only real data from the inputs or mock data as specified or tell the user if data couldnt be gathered. 
- Keep `docs/reference/MANUAL_VERIFICATION_COMMANDS.md` as the canonical, source-checked index of runnable project commands. Whenever an agent adds, changes, or removes an executable entry point, CLI option, launcher, test command, or manual verification workflow, update this document in the same change. Include exact command, required inputs/assets, expected output, and database/file side effects. Clearly mark destructive, synthetic, optional, and data-dependent commands. Do not copy stale split mappings or claim commands were run unless verified.
