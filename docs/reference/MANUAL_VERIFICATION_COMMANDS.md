# Manual Verification and Run Commands

Use this as the command index for manual checks. Commands assume PowerShell is open at the repository root:

```powershell
cd C:\Users\bhard\Downloads\major_pro\major_pro\basketball_proj
```

Use the project virtual environment directly (`.venv\Scripts\python.exe`) so commands do not depend on activation. **macOS/Linux:** the Windows `.venv` in this folder cannot run there; create your own with `python3 -m venv .venv-mac && .venv-mac/bin/python -m pip install -r requirements.txt`, then replace `.venv\Scripts\python.exe` with `.venv-mac/bin/python` and `\` path separators with `/` in every command below. If the environment or assets are missing, see Setup below. Commands that write to `shot_lab.db`, reports, or `dataset_export/` are marked.

## Important split and clip-ID warning

The repository currently has conflicting split mappings:

- The supplied player-heldout plan is: Lavish + Klay = `train`, Mike Dunn = `val`, Sid = `test`.
- `clip_splits.json` and current database records use a different clip-level allocation. `run_all_clips.bat`, `run_all_clips.ps1`, and `launch_annotation_lab.py` contain their own player-heldout mapping and use some alias clip IDs.
- Batch ingestion reads `clip_splits.json` and can reassign database clips to match it. Do not claim player-heldout evaluation until the config, DB, launcher IDs, and exported manifest agree.

Current canonical IDs in `labeled_clips` include `lavish_1_90deg`, `lavish_2_90deg`, `lavish_3_mix`, `lavish_4_0deg`, `lavish_5_0deg`, `klay_vid`, `mikedunn`, `mikeddunnstud1`, `mikeddunnstud2`, `sid_1`, `sid_2`, `sid_3_mult`, `sid_4_97deg_wrim`, `sid_5_0deg`, and `sid_6_0deg`. Reuse those IDs when updating existing records. Alias IDs such as `lavish_1`, `mikedunn_stud1`, or `sid_3` can create duplicate records for the same video.

## 1. Setup and model assets

```powershell
# Create/activate an existing environment
.\.venv\Scripts\Activate.ps1

# Install package in editable mode with development dependencies
python -m pip install -e ".[dev]"

# Download/verify MediaPipe pose and hand assets into repository root
python scripts/download_models.py

# Force re-download both assets
python scripts/download_models.py --force
```

The setup command installs the dependencies from `pyproject.toml` (or `requirements.txt`).
`scripts/download_models.py` needs network access. It fetches `pose_landmarker.task` and `hand_landmarker.task` into the project root. If a download fails, use the manual URLs printed by the script. YOLO ball/rim weights are stored in `models/best.pt` and `models/ballRim.pt`.

## 2. Live camera and saved-video analysis

You can run via the root wrapper or the standard module path:

```powershell
# Live webcam (ball & rim tracking enabled by default with models/best.pt)
python main.py
# Equivalent module entry point:
python -m basketball.app.main

# Live webcam in a normal window
python main.py --windowed

# Analyze a saved clip with default ball & rim tracking
python main.py --video raw_clips\sid_1.mp4 --player sid --camera-view side_90

# Analyze a saved clip with ball & rim tracking explicitly disabled
python main.py --video raw_clips\sid_1.mp4 --no-ball

# Optional custom YOLO weights (file must exist; defaults to models/best.pt)
python main.py --video raw_clips\sid_1.mp4 --yolo models\best.pt

# Optional hands, pro comparison, or set-shot thresholds
python main.py --video raw_clips\sid_1.mp4 --hands
python main.py --video raw_clips\sid_1.mp4 --pro curry
python main.py --video raw_clips\sid_1.mp4 --shot-style set_shot

# Choose a separate DB for a non-production/demo session
python main.py --video raw_clips\sid_1.mp4 --db temp_manual_check.db
```

Live camera needs a connected, accessible webcam. Saved-video commands need the named file. The main app writes session/shot data to `shot_lab.db` unless `--db` points elsewhere. Ball and rim tracking runs by default using `models/best.pt` (or can be disabled via `--no-ball`), rendering ball/rim bounding boxes, parabolic flight trajectories, launch/entry angles, and advisory make/miss proposals. Runtime keys shown in the UI include `M` make, `X` miss, `U` unknown, `Space` pause/resume, `B` toggle ball/rim overlay, `G` toggle full-body pro ghost skeleton, `F` toggle fullscreen, `S` export session metrics, and `Q` quit. Automated outcomes remain strictly advisory (`automated_outcome`) and never overwrite human ground-truth labels (`outcome`).

## 3. Developer Model Lab: annotate a video

Basic command template (or use the concise `--clip` shorthand which auto-resolves video path, player, and split from `shot_lab.db`):

```powershell
# Concise lookup by canonical clip ID
python tools/annotation_lab.py --clip <CANONICAL_ID>

# Explicit full arguments
python tools/annotation_lab.py --video <VIDEO_PATH> --clip-id <CANONICAL_ID> --player-id <PLAYER_ID> --split <train|val|test> --db shot_lab.db
```

> [!NOTE]
> **Database Locking:** If `sqlite3.OperationalError: database is locked` occurs upon pressing `W`, ensure any open SQLite tools (such as **DB Browser for SQLite**) have committed changes ("Write Changes") or closed the database file. AnnotationLab keeps annotations in memory and displays a status warning so you can retry with `[W]` without losing progress.

Examples using the canonical clip IDs:

```powershell
# Lavish — requested train grouping
python tools/annotation_lab.py --video raw_clips\lavish_1_90deg.mp4 --clip-id lavish_1_90deg --player-id lavish --split train
python tools/annotation_lab.py --video raw_clips\lavish_2_90deg.mp4 --clip-id lavish_2_90deg --player-id lavish --split train
python tools/annotation_lab.py --video raw_clips\lavish_3_mix.mp4 --clip-id lavish_3_mix --player-id lavish --split train
python tools/annotation_lab.py --video raw_clips\lavish_4_0deg.mp4 --clip-id lavish_4_0deg --player-id lavish --split train
python tools/annotation_lab.py --video raw_clips\lavish_5_0deg.mp4 --clip-id lavish_5_0deg --player-id lavish --split train

# Klay — requested train grouping
python tools/annotation_lab.py --video raw_clips\klay_vid.mp4 --clip-id klay_vid --player-id klay_thompson --split train

# Mike Dunn — requested validation grouping
python tools/annotation_lab.py --video raw_clips\Mikedunn.mp4 --clip-id mikedunn --player-id mike_dunn --split val
python tools/annotation_lab.py --video raw_clips\mikeddunnstud1.mp4 --clip-id mikeddunnstud1 --player-id mike_dunn --split val
python tools/annotation_lab.py --video raw_clips\mikeddunnstud2.mp4 --clip-id mikeddunnstud2 --player-id mike_dunn --split val

# Sid — requested test grouping
python tools/annotation_lab.py --video raw_clips\sid_1.mp4 --clip-id sid_1 --player-id sid --split test
python tools/annotation_lab.py --video raw_clips\sid_2.mp4 --clip-id sid_2 --player-id sid --split test
python tools/annotation_lab.py --video raw_clips\sid_3_mult.mp4 --clip-id sid_3_mult --player-id sid --split test
python tools/annotation_lab.py --video raw_clips\sid_4_97deg_wrim.mp4 --clip-id sid_4_97deg_wrim --player-id sid --split test
python tools/annotation_lab.py --video raw_clips\sid_5_0deg.mp4 --clip-id sid_5_0deg --player-id sid --split test
python tools/annotation_lab.py --video raw_clips\sid_6_0deg.mp4 --clip-id sid_6_0deg --player-id sid --split test
```

These commands write annotations and clip metadata to SQLite.

Annotation Lab keyboard controls:

| Key | Action |
|---|---|
| `Space` | Play/pause |
| `,` / `.` | Step one frame backward/forward |
| `<` / `>` | Step ten frames backward/forward |
| `[` / `]` | Mark interval in/out |
| `1` / `2` / `3` / `4` | Set dip / set point / release / follow-through |
| `S` | Commit shot interval |
| `N` | Cycle negative-action class and commit negative interval |
| `M` / `X` / `U` | Set make / miss / unknown outcome |
| `A` / `D` | Accept / discard machine proposal under playhead |
| `Z` | Undo |
| `W` | Save to database |
| `P` | Toggle pose overlay |
| `R` | Run detector proposals |
| `H` | Help overlay |
| `Q` / `Esc` | Quit |

Optional annotation flags:

```powershell
# Automatically propose detections on open
python tools/annotation_lab.py --video raw_clips\sid_1.mp4 --clip-id sid_1 --player-id sid --split test --auto-detect

# Headless command path, primarily for controlled QA; synthetic input requires explicit --synthetic
python tools/annotation_lab.py --video <VIDEO_PATH> --clip-id <ID> --player-id <PLAYER> --split train --headless --commands "<SUPPORTED_COMMANDS>"
```

## 4. Annotation launchers

```powershell
# Interactive numbered menu
python scripts/launch_annotation_lab.py

# Direct menu lookup by clip ID/name substring
python scripts/launch_annotation_lab.py sid_1

# PowerShell menu or one clip
.\run_all_clips.ps1
.\run_all_clips.ps1 -Clip sid_3

# If PowerShell blocks the local script, run it with process-scoped bypass
powershell -ExecutionPolicy Bypass -File .\run_all_clips.ps1 -Clip sid_3

# Command Prompt menu
cmd /c run_all_clips.bat
```

## 5. Inject/synchronize ground-truth annotations

```powershell
# Sync ground_truth_annotations.json into labeled_clips/labeled_intervals and export afterward
python scripts/sync_split_annotations.py --json-file data/ground_truth_annotations.json --db shot_lab.db

# Sync only; do not export
python scripts/sync_split_annotations.py --json-file data/ground_truth_annotations.json --db shot_lab.db --no-export
```

## 6. Batch ingest all raw clips and detector proposals

```powershell
# Register all supported videos and generate calibrated detector proposals (default)
python scripts/batch_ingest_clips.py

# Register clips and validate, without generating proposals
python scripts/batch_ingest_clips.py --no_proposals

# Choose detector
python scripts/batch_ingest_clips.py --detector heuristic
python scripts/batch_ingest_clips.py --detector calibrated
python scripts/batch_ingest_clips.py --detector ml_sequence

# Explicit paths; rerun proposals even when proposals already exist
python scripts/batch_ingest_clips.py --clips_dir raw_clips --db_path shot_lab.db --detector calibrated --force_repropose
```

## 7. Validate and export dataset

```powershell
# Validate existence, labels, frame bounds, taxonomy, splits, and physical-file collisions
python evaluation/validate_dataset.py

# Strict player-heldout validation (players cannot span splits)
python evaluation/validate_dataset.py --strategy player

# Save validation report
python evaluation/validate_dataset.py --strategy player --json-report DATASET_VALIDATION_REPORT.json

# Export validated split JSONL and manifest (writes/overwrites dataset_export/)
python scripts/export_dataset.py --db shot_lab.db --out-dir dataset_export --strategy player
```

## 8. Inspect SQLite records and manually review shots

```powershell
# List clips, proposals, human intervals, shots, and baseline status
python scripts/inspect_db.py

# Inspect one clip
python scripts/inspect_db.py --clip-id lavish_1_90deg

# Use another DB file
python scripts/inspect_db.py --db shot_lab.db --clip-id sid_1

# List/review quarantined shots interactively
python scripts/review_shots.py --quarantined --interactive

# List all shots or only approved shots
python scripts/review_shots.py --list
python scripts/review_shots.py --approved --list

# Inspect, approve, discard, or correct one shot
python scripts/review_shots.py --inspect <SHOT_ID>
python scripts/review_shots.py --approve <SHOT_ID> --notes "Verified after frame review"
python scripts/review_shots.py --discard <SHOT_ID> --notes "Not a shot"
python scripts/review_shots.py --set-outcome <SHOT_ID> make
python scripts/review_shots.py --set-release-frame <SHOT_ID> <FRAME>
```

Approval/review commands mutate the DB. Review the shot first. No blind batch approval is supported.
Personal baselines and app coaching use only shots with `review_status='approved'` and `tracking_confidence='SUFFICIENT'`.

In DB Browser for SQLite, open `shot_lab.db`, choose **Execute SQL**, and run:

```sql
SELECT c.clip_id, c.player_id, c.split, c.file_path,
       COUNT(i.interval_id) AS intervals,
       SUM(CASE WHEN i.action_class='shot_event' THEN 1 ELSE 0 END) AS shot_events,
       SUM(CASE WHEN i.action_class='shot_event' AND i.release_frame IS NOT NULL THEN 1 ELSE 0 END) AS releases_labeled
FROM labeled_clips c
LEFT JOIN labeled_intervals i ON i.clip_id=c.clip_id
GROUP BY c.clip_id, c.player_id, c.split, c.file_path
ORDER BY c.split, c.player_id, c.clip_id;
```

## 9. Real-video and model evaluations

```powershell
# Phase 6 detector benchmark; full clip by default; report path is explicit
python evaluation/evaluate_shot_models.py --split val --report SHOT_MODEL_VAL_REPORT.json

# Run test only after model/threshold choices are frozen; do not tune against test
python evaluation/evaluate_shot_models.py --split test --report SHOT_MODEL_TEST_REPORT.json

# Optional short diagnostic only; explicitly truncated, not a full-clip benchmark
python evaluation/evaluate_shot_models.py --split val --max-frames 300 --report SHOT_MODEL_VAL_300FRAME_DIAGNOSTIC.json

# Evaluate existing human annotations against the main pipeline
python evaluation/evaluate_dataset.py --annotations data/ground_truth_annotations.json --output DATASET_EVAL_REPORT.json

# Optional short diagnostic or ball tracking coverage
python evaluation/evaluate_dataset.py --max-frames 300 --output DATASET_DIAGNOSTIC_300FRAME.json
python evaluation/evaluate_dataset.py --eval-ball --output DATASET_BALL_COVERAGE_REPORT.json

# Evaluate one clip
python evaluation/evaluate_video.py --video raw_clips\klay_vid.mp4 --output KLAY_EVAL_REPORT.json

# Run the raw-clips suite (real footage; may take a long time)
python evaluation/run_all_raw_clips_test.py --raw-dir raw_clips --annotations data/ground_truth_annotations.json --output RAW_CLIPS_TEST_REPORT.json

# Public dataset checks; needs the EPFL files at the supplied path
python evaluation/evaluate_public_datasets.py --epfl-dir clones\sportcenter_camerapose_dataset --sample-stride 50 --output PUBLIC_DATASETS_REPORT.json
```

## 10. Test Suites (Unit, Integration, E2E)

```powershell
# Run the complete test suite (Unit, Integration, E2E)
python -m unittest discover tests

# Run categorized suites individually:
python -m unittest discover tests/unit
python -m unittest discover tests/integration
python -m unittest discover tests/e2e

# Run specific functional test suites:
python -m unittest tests/unit/test_shooting_analysis.py
python -m unittest tests/unit/test_shot_coach.py
python -m unittest tests/unit/test_report_service.py
python -m unittest tests/unit/test_shot_lab_db.py
python -m unittest tests/unit/test_calibrated_fsm.py
python -m unittest tests/unit/test_shot_detector_ml.py
python -m unittest tests/unit/test_ball_geometry.py
python -m unittest tests/integration/test_shot_lab_flow.py
python -m unittest tests/integration/test_export_dataset.py
python -m unittest tests/integration/test_sync_split_annotations.py
python -m unittest tests/integration/test_weights_manifest.py
python -m unittest tests/e2e/test_web_app.py
python -m unittest tests/unit/test_workout_planner.py
python -m unittest tests/e2e/test_workout_api.py
python -m unittest tests/e2e/test_workout_ui.py   # needs Playwright Chromium + ffmpeg; skipped otherwise
python -m unittest tests/unit/test_local_tls.py   # needs cryptography (openssl CLI for the chain check)
python -m unittest tests/e2e/test_camera_recording.py   # Playwright Chromium fake camera + cryptography; skipped otherwise

# Synthetic pipeline benchmark
python evaluation/evaluate_pipeline.py
python evaluation/evaluate_pipeline.py --json
```

Known environment-dependent tests: `test_ball_tracker`, `test_ball_tracking_flow`, and `test_pose_backend_comparison` need `ultralytics` plus the `models/*.pt` weights; `test_weights_manifest.test_all_raw_clips_accounted_for_in_splits` needs the `raw_clips/` folder listed in `clip_splits.json`. Without those inputs they fail for missing resources, not for logic errors.

Tests should use temporary DBs and fixtures. After tests, inspect `dataset_export/` and confirm its manifest/hash did not change unexpectedly.

## 11. Demo and maintenance commands — use care

```powershell
# Seed sample players/shots/baselines. Use a separate DB; data is demo/sample data, not evaluation data.
.venv\Scripts\python.exe seed_shot_lab.py --db demo_shot_lab.db

# Consolidate duplicate clip aliases in the default DB. This mutates shot_lab.db; back it up first.
Copy-Item .\shot_lab.db .\shot_lab.before_cleanup.db
.venv\Scripts\python.exe clean_db_provenance.py
```

`clean_db_provenance.py` has no CLI path override and operates on `shot_lab.db` and `raw_clips/` in the current directory. Do not run it on the only copy of a valued DB without reviewing its code and making a backup.

## 12. Scratch scripts and reusable modules

These are developer diagnostics, not stable user workflows:

```powershell
.venv\Scripts\python.exe scratch_analyze_klay.py
.venv\Scripts\python.exe scratch_inspect_timeline.py
```

They may use hard-coded sample paths and may fail if those files or DB records are absent. Core modules such as `analyzer.py`, `pose_engine.py`, `shot_lab_db.py`, `ball_tracker.py`, `ball_geometry.py`, `shot_feature_extractor.py`, and `coaching_service.py` are imported by the app/tools; they are not standalone manual commands.

## 13. Phase 7: Ball, Rim & Trajectory Tracking and Comparative Pose Benchmarking

```powershell
# Batch ingest all clips (including newly added clips) with metadata and split synchronization
.venv\Scripts\python.exe batch_ingest_clips.py --dry-run
.venv\Scripts\python.exe batch_ingest_clips.py

# Live / video analysis with dynamic YOLO ball and rim tracking
.venv\Scripts\python.exe main.py --video raw_clips\sid_4_97deg_wrim.mp4 --ball --weights models\best.pt

# Evaluate custom ball/rim detector on dataset test split & available labeled validation clips
.venv\Scripts\python.exe evaluate_ball_tracking.py --weights models\best.pt --output BALL_RIM_EVAL_REPORT.json

# Offline Comparative Pose Benchmark: MediaPipe Tasks Pose vs. YOLOv8 Pose (12 shared joints)
.venv\Scripts\python.exe evaluate_pose_backends.py --yolo-model models\yolov8m-pose.pt --max-frames 80 --output POSE_BACKEND_COMPARISON_REPORT.json
```

Expected Outputs & Effects:
- `BALL_RIM_EVAL_REPORT.json`: Contains real mAP@50, precision, recall on Roboflow test set (`Basketball.v1i.yolov8/test`), video tracking continuity on validation clips, trajectory $R^2$ fit, entry angle, and advisory qualification gate. Automated outcomes are strictly gated ($R^2 < 0.70$, missing rim, or $< 4$ points return advisory `unknown` with clear reasons: `POOR_TRAJECTORY_FIT`, `RIM_NOT_DETECTED`, `INSUFFICIENT_FLIGHT_POINTS`). Automated outcomes never overwrite human ground truth.
- `POSE_BACKEND_COMPARISON_REPORT.json`: Measures mutual keypoint normalized distance and detection rates across 12 shared joints without slowing down live inference.
- `WEIGHTS_MANIFEST.md`: Cryptographic provenance and SHA256 hashes for `models/best.pt`, `models/ballRim.pt`, and `models/yolov8m-pose.pt`.

## 14. Phase 8: Local player app, evidence-gated coaching, history, and reports

### 14a. Drills section

The Drills tab is a self-contained practice mode. No video upload or pose analysis is required.

**Verify the drill catalog module:**

```bash
# macOS/Linux
PYTHONPATH=src python3 -c "
from basketball.coaching.drills_catalog import get_catalog
cat = get_catalog()
print('Total drills:', cat['total'])
for d in cat['drills']:
    print(' ', d['id'], '|', d['difficulty'], '|', d['video'])
"
```

Expected output: 4 drills listed with their video filenames and difficulty levels. Exit code 0.

**Verify drill video files are present:**

```bash
ls web/drills/
# Expected: pound_dribble.mp4  pound_plus_cross.mp4  pound_plus_v-dribble.mp4  v-dribble_plus_cross.mp4
```

**Verify the API endpoint syntax:**

```bash
PYTHONPATH=src python3 -m py_compile src/basketball/coaching/drills_catalog.py
# Expected: no output, exit code 0
```

**Test the live `/api/drills` endpoint** (server must be running):

```bash
# Start the server first in another terminal:
# python3 web_app.py --port 8000

curl -s http://127.0.0.1:8000/api/drills | python3 -m json.tool | head -20
# Expected: JSON with "total": 4 and a "drills" array

# Filter by difficulty
curl -s "http://127.0.0.1:8000/api/drills?difficulty=beginner" | python3 -m json.tool | grep '"total"'
# Expected: "total": 2

# Test video streaming (byte-range)
curl -I http://127.0.0.1:8000/drills/pound_dribble.mp4
# Expected: HTTP/1.1 200 OK, Content-Type: video/mp4, Accept-Ranges: bytes
```

**Test the YOLO Ball Tracking, Ground Bounce & Dribble Style Engine:**

Run the dedicated unit and integration tests:

```powershell
$env:PYTHONPATH="src;."
python -m unittest tests.unit.test_drill_service tests.integration.test_drills_routes -v
```

Expected output: 21 tests pass with `OK` (18 unit tests + 3 integration tests).

**Test the Drills UI & Dribble Style Tracking in the browser:**

1. Open `http://127.0.0.1:8765/#drills`
2. Four drill cards appear, each with a video thumbnail, difficulty badge, and skill chips.
3. Click any combo drill (e.g. **Pound + Crossover** or **Pound + V-Dribble**) — the drill runner opens with the reference demo video on the left and camera placeholder on the right.
4. Click **Start camera & count reps** — browser requests camera permission; allow it.
5. The reference demo video loops; your camera feed starts.
6. A live MediaPipe skeleton overlay appears on your body (green lines for athletic stance, amber if knees are upright). A real-time knee bend angle badge (e.g. `154°`), live move indicator (`MOVE: POUND (R)`), and dynamic live coaching cue pill appear.
7. **Strict Ground Dribble Verification**:
   - Holding or jiggling the ball at waist/knee height will NOT increment the rep counter.
   - Ball must descend from hip/knee release level all the way to floor level near the feet (Δy ≥ 0.12, y ≥ 0.66) and rebound upward to count as an authentic dribble rep.
8. **Dribble Style & Demo Sequence Adherence**:
   - The engine tracks lateral displacement ΔX and body midline position X_mid to classify every bounce as `POUND`, `CROSSOVER`, or `V_DRIBBLE`.
   - The HUD displays the live move and combo step (e.g. `Step 1/3: Pound` -> `Step 2/3: Pound` -> `Step 3/3: Cross`).
   - Completing the sequence matching the demo video increments the **Combos Completed** counter and triggers a visual celebration ripple and flash.
9. Click **Stop drill** — the session stops on the backend and displays genuine measured biomechanics and style adherence:
   - **Authentic Reps** & Cadence (reps/sec) with ground contact height validation
   - **Completed Combos** matching the demo video sequence
   - **Style Match %** (% adherence to demo video movements)
   - **Average Knee Bend** vs Reference Athlete Target (e.g. 160.5° for Pound + Cross)
   - **Stance Adherence %** (% time maintaining athletic knee bend)
   - **Eyes Up %** (% time head held high looking forward)
   - Detailed evidence-based feedback on move counts, sequence fidelity, and posture.
10. Click **Done — back to drills** to return to the catalog.

No data is written to the database or uploaded. Camera feed stays local.

---

Check Python syntax without starting the server or processing footage:

```powershell
python -m py_compile web_app.py src/basketball/services/video_analysis_service.py src/basketball/persistence/shot_lab_db.py src/basketball/analysis/baseline_engine.py src/basketball/coaching/coaching_service.py src/basketball/services/history_service.py src/basketball/coaching/llm_coach.py
node --check web\app.js   # optional, needs Node.js
python -m unittest tests/e2e/test_web_app.py
```

Expected output: no output and exit code `0`. This creates ignored Python bytecode under `__pycache__`.

Start the local browser app from the repository root:

```powershell
python web_app.py --host 127.0.0.1 --port 8765 --db shot_lab.db --upload-dir user_data\uploads --pose-cache-dir user_data\pose_cache
# Equivalent module entry point:
python -m basketball.app.web_app --host 127.0.0.1 --port 8765 --db shot_lab.db --upload-dir user_data\uploads --pose-cache-dir user_data\pose_cache

# Start with mobile phone access enabled over Wi-Fi:
python web_app.py --lan
# Or with a custom fixed access code:
python web_app.py --lan --access-code BASKETBALL2026
```

macOS/Linux equivalent:

```bash
python web_app.py --host 127.0.0.1 --port 8765 --db shot_lab.db --upload-dir user_data/uploads --pose-cache-dir user_data/pose_cache
```

**App layout (redesigned UI):** four primary workspace views in the sidebar and top navigation. **Practice** (`#practice`, with backward-compatible `#new` hash alias) is the capture hub holding the compact toggleable hero, the simplified athlete summary ("Today's practice" with prefilled profile defaults, pain status, and an "Edit profile" trigger), practice focus radio chips ("What are you working on?"), explicit shot style selection (jump shot vs. set shot), camera angle confirmation, and practice video capture (Upload a file / Record with camera). **Review** shows the open session: summary counts, replay with pose overlay, a clickable clip timeline (each attempt is a coloured segment; the dark tick is its release frame; arrow keys step frames when the timeline is focused), the attempt list, and the review editor, followed by Measured mechanics, Coaching cue, Ask about this session, and Session report. The red number next to Review is the count of attempts still needing review. **Report** shows the comprehensive biomechanical analysis report with export capabilities. **Progress** shows the weekly goal ring, streak, counted sessions, current drill, trend charts and every saved session with **Open review** / **Review attempts** and **Delete**. Fonts are bundled in `web/fonts/` (Archivo, SIL OFL), so the page loads no external resources.

**Reopening a session:** in Progress select **Open review** on any session that was uploaded through the web app. Sessions created by `main.py` or other tools have no web job, so they show only **Delete**. Reloading the page reopens the last session in this browser. The job response now returns the current shot rows from SQLite (not the snapshot taken when analysis finished), so saved reviews always appear after a reload.

**Moved or shared project folders:** job records store absolute upload paths. If the folder was copied from another computer (for example Windows paths opened on macOS), the server falls back to the same generated filename inside the configured `--upload-dir`, so replay and deletion keep working. Files outside the upload directory are never served or deleted.

For destructive deletion checks, make and use a disposable DB copy first:

```powershell
if (Test-Path .\shot_lab_phase8_qa.db) { throw "shot_lab_phase8_qa.db already exists; choose a different QA filename" }
Copy-Item .\shot_lab.db .\shot_lab_phase8_qa.db
.venv\Scripts\python.exe web_app.py --host 127.0.0.1 --port 8765 --db shot_lab_phase8_qa.db --upload-dir user_data\phase8_qa_uploads --pose-cache-dir user_data\phase8_qa_pose_cache
```

Requires the existing `shot_lab.db`; the copy preserves real labels/metrics but does not copy old upload/job files. New uploads get fresh replay metadata. This creates a second SQLite DB and the corresponding `.web_jobs.sqlite3`, upload, and pose-cache paths. It is recommended for delete/goal/drill UAT so the main database stays intact. For deletion checks, delete only a session uploaded through this QA server; older copied session rows do not have matching copied job/media pointers.

Open `http://127.0.0.1:8765` (or `https://` if using `--https`), review the prefilled athlete summary, select practice focus and camera angle, choose a permitted real video or turn on the camera, and start analysis. The app accepts MP4, MOV, AVI, MKV, and WebM uploads up to 250 MB. Keep the server bound to loopback; this prototype rejects non-loopback bind addresses.

**Required inputs/assets:** installed project requirements, `pose_landmarker.task`, and a permitted, readable video file with visible player footage. The full clip is processed. When custom YOLO weights (`models/best.pt` or `models/ballRim.pt`) are present, ball & rim tracking runs automatically during video analysis.

**In-app camera recording & immersive full-screen mode:** on `http://127.0.0.1:8765`, in **Practice video** choose **Record with camera**, select **Turn on camera** and allow browser permission.
- **Immersive Full-Screen Mode:** Click the fullscreen icon button (`#hud-btn-fullscreen`) on the top-left of the HUD to enter edge-to-edge camera preview. In immersive mode, sidebars and cards are hidden so the shooter has an uncluttered view of live pose tracking and trajectory feedback. Exit immersive mode via the floating "Exit full screen" button, the escape icon, or pressing the `Escape` key.
- **Secondary Metrics Toggle:** Click `#hud-btn-toggle-metrics` to toggle the top metrics bar (`RIM (LIVE)`, `PEAK MAX`, `KNEE`, `ARM`, `PHASE`) on or off.
- **Honest HUD Indicators:** When starting a session with no recorded attempts, the success rate shows `—` (dash) instead of misleading `0%`. When a rim is detected, the status pill shows `LOCKED` (or verified confidence %) instead of artificial `100%`.
- **Mobile Landscape Advisory:** On narrow screens in portrait mode, an orientation advisory recommends landscape framing for full court and hoop capture. During recording, accidental page scrolling is prevented (`is-camera-recording`).
- **Recording & Submission:** Click **Start recording** and **Stop**. A recorded clip is placed into the upload control; select **Analyze Practice Clip** to process it. Browser camera permission and MediaRecorder support are required; recordings are capped at 250 MB and held in browser memory until submitted. The app tries OpenCV directly with local FFmpeg fallback if the browser's container requires conversion. Check that **Turn off camera** stops all tracks.
- **Live Practice Audio Coach & Speech Feedback:**
  - **Speech Synthesis:** In the camera HUD overlay, an audio coach uses the browser's native `speechSynthesis` to speak suggestive form cues (in English) before each rep and brief feedback after completed shots when supported by valid measurements.
  - **Mute / Voice Toggle:** Click `#hud-btn-voice` (speaker icon) in the top-left HUD toolbar to mute/unmute speech. When muted, voice queue is instantly cancelled and state is persisted in localStorage; the visible text caption banner (`#hud-coach-banner`) remains displayed.
  - **Evidence Gating & Gating Logic:**
    1. *Historical Evidence:* If the selected athlete has $\ge 5$ approved, sufficient-confidence shots with a confirmed baseline or active remediation, the pre-rep cue reinforces that focus (e.g. *"Try letting your legs start the shot before your arm extends"* or *"Try finishing with your elbow higher"*).
    2. *Session Observations:* If history is insufficient, the coach monitors reliable live shot kinematics (elbow release angle and knee dip).
    3. *Setup Reminder:* If neither history nor session flaws are found, a generic reminder (*"Set your feet and balance before shooting"*) is given.
    4. *Confidence Gating:* If landmark visibility is insufficient ($< 0.45$) or key shooting joints are occluded, mechanics speech is suppressed.
    5. *Suggestive Tone & No Outcome Speech:* The coach uses purely suggestive language (never promises or guarantees made shots) and **never announces makes or misses in speech** (outcomes remain on the visual HUD banner).
    6. *End-of-Set Recap:* When clicking **End Session** (`#hud-finish-btn`) or closing the camera, a short recap summarizes the set reps and primary focus (e.g. *"Set complete: 10 shots tracked. Focus on arm extension in your next set"*).

**Existing desktop OpenCV camera workflow:** this is a separate live-analysis path, not a browser recording upload. Run `.venv\Scripts\python.exe main.py --player player --camera-view side_90 --shot-type catch_and_shoot --shot-style jump_shot --db shot_lab.db --no-ball --windowed`; OpenCV opens the computer's camera, analyzes frames live, and saves detected shot records to SQLite. Press `Q` to end the live run. It does not save the original webcam video or create the web app's replay job, so use the browser recorder above when you need a saved video and seekable replay. This prototype is local testing; a production website will need a separate recording/job/history design.

**Expected behavior:** the page switches to Review; the upload returns a session/job ID; the page polls queued/running/complete/failed status with a progress bar; on completion it shows attempts proposed, attempts needing review, attempts approved and frames analyzed. The uploaded clip is shown with frame seeking, cached MediaPipe skeleton overlay (toggle **Pose**; **Angles** adds live elbow/knee angles), and YOLO ball & rim overlay (toggle **Ball & Rim** renders neon rim box, circular target reticle, crosshair, cyan ball circle, RIM/BALL % confidence badges, and glowing parabolic flight trajectory with waypoint dots) even when no attempt was proposed. For the selected attempt, phase buttons jump to the load/set/release/follow-through frames. If a clip ends after an observed release but before the detector returned to idle, that attempt is still proposed (quarantined, unknown outcome) with the last frame as its follow-through and the page says so; a candidate with no observed release is reported as incomplete and not proposed. Replay needs a browser that can decode the uploaded codec (Chrome/Safari/Edge play H.264 MP4; some open-source Chromium builds do not, and the page then says replay is unavailable while frame-number review still works). The current detector does not identify a distinct dip frame, so the UI labels it unavailable instead of inventing one. Below the replay, the **Coach summary** (section 15) reports findings from all non-discarded attempts with confidence labels, and the **Personal drill plan** card keeps the strict rule: it gives at most one trackable drill cue from matched, approved, sufficient-confidence history (five or more measurements) or explicitly abstains. A clean clip with no accepted shots may show zero proposals. This is a software workflow check, not a detector-accuracy result.

**Manual replay/review workflow:** choose an attempt in the list or on the clip timeline, jump to each phase, compare the machine event to the visible movement, edit frame numbers when needed (**Set as release frame** copies the replay's current frame). The review editor automatically pre-selects high-confidence automated make/miss predictions (`automated_outcome_conf` >= 0.70 and `trajectory_fit_r2` >= 0.70) while keeping `review_status: quarantined`. An advisory trajectory banner indicates the detected outcome, confidence, and $R^2$, with a **Confirm prediction** button that sets both outcome and Approve. The reviewer can confirm, adjust (**Outcome you saw**: Not sure / Make / Miss), or choose a **Decision** (Leave for later = `quarantined`, Approve = `approved`, Not a shot = `discarded`), optionally add notes, and select **Save review**. **Next attempt** moves on. Make/miss labels require Approve; the page explains this before sending. Saving writes only `annotated_*_frame`, human outcome/review fields, and an append-only `shot_review_history` entry; `machine_*_frame` fields stay unchanged. Open **Change history** under the editor after saving; it lists each saved edit with before/after values, and the machine proposal frames. Refresh the page to confirm it restores the latest job from this browser and reloads corrections. The endpoint rejects out-of-video frames and non-chronological phase boundaries.

**Manual coaching-evidence workflow:** first inspect the abstention state with fewer than five approved, `SUFFICIENT` shots or fewer than five non-missing samples for a metric. To check the eligible state, manually review and approve at least five real shots with the same player ID, camera view, shot type, and shot style, where at least five have the same stored mechanic (for example, sequence lag or 3D elbow release angle). Use the same DB containing those approved records; a fresh disposable DB will abstain until it has enough eligible data. The dashboard may show a cue only when its matched metric has at least five values. It shows threshold evidence and source shot/frame references. These are prototype starting thresholds, not validated clinical standards. Viewing insights does not write a baseline or remediation.

Inspect the read-only insights response after replacing `<SESSION_ID>` with the returned session ID:

```text
GET http://127.0.0.1:8765/api/sessions/<SESSION_ID>/insights
```

Expected JSON includes the matched context, approved sample counts, metric availability, and either one cue or an explicit abstention. The request does not write measurements, labels, baselines, or remediation records; normal schema initialization/migration may still occur.

To verify persistence in DB Browser for SQLite, open the same database supplied to `--db`, then run:

```sql
SELECT shot_id,
       machine_start_frame, annotated_start_frame,
       machine_set_frame, annotated_set_frame,
       machine_release_frame, annotated_release_frame,
       machine_end_frame, annotated_end_frame,
       outcome, outcome_source, review_status, review_notes
FROM shots
ORDER BY updated_at DESC;

SELECT shot_id, reviewer_id, previous_values_json, updated_values_json, created_at
FROM shot_review_history
ORDER BY created_at DESC;
```

Expected: edited event frames appear in `annotated_*_frame`; corresponding `machine_*_frame` values retain the detector output; the review-history row shows before/after JSON. This workflow mutates the selected DB with the human review.

**Side effects and privacy:** creates/updates the selected Shot Lab DB with a session, machine-proposed shots, human corrections, schema-v6 `shot_review_history`, and player weekly-goal settings; creates `<db>.web_jobs.sqlite3` for persistent job status; saves the uploaded source under `user_data\uploads\<generated-id>.<ext>` and a compressed per-frame pose cache under `user_data\pose_cache\<session-id>.json.gz`. Both user-data folders are ignored by Git. Source videos and pose caches remain local and are not automatically deleted. Remove individual files manually when no longer needed. Jobs interrupted by server restart are marked failed; re-submit the clip to retry.

**Known scope limits:** when YOLO weights (`models/best.pt` or `models/ballRim.pt`) are available, the upload pipeline automatically runs ball & rim tracking, post-release flight trajectory fitting, and advisory make/miss qualification (`automated_outcome`, `automated_outcome_conf`, `trajectory_fit_r2`, `entry_angle_deg`), pre-selecting high-confidence predictions in the review UI while keeping proposals quarantined until human confirmation. When weights are missing, outcomes default to `unknown` and `ball_rim_tracking` reports `unavailable`. Coaching supports only metrics actually saved by the current upload pipeline; unavailable knee-at-dip and torso-sway measures are not estimated. The pose overlay is a cached MediaPipe estimate, not ground truth. Use review-approved data only where the existing baseline gates allow it.

### Phase 8 history, weekly goal, drill follow-up, and PDF report

The **Progress** view loads for the Player ID shown at its top (change it there to switch players). All saved sessions remain visible so unreviewed sessions can be inspected or deleted, but only sessions with at least one human-approved, `SUFFICIENT` shot count toward activity or receive metrics. Metric means and sample standard deviations require at least five measured values. Trend charts and comparisons use only the same player, camera view, shot type, and shot style. “Consistency” is the per-metric sample standard deviation, not a validated score. Early-to-late differences require at least six eligible shots and at least three non-missing values in each half; these are descriptive within-session changes, not a fatigue finding.

Choose a weekly goal from 1–7. The goal is saved in `player_app_settings`; a practice session counts only if it contains an approved, confidence-sufficient shot. Activity dates and streaks use the UTC date stored by SQLite.

When an evidence-gated cue is present, select **Add drill to my practice plan** in the Coaching cue card. This explicit action writes an entry to `remediations`; merely viewing the cue is read-only. After uploading and reviewing a different session with the same player, camera view, shot type, and style, open that session in Review, then in Progress choose **Compare the open session to before the drill**. It requires at least five approved, sufficient-confidence measurements for the cue metric. It stores the post-session mean/spread and any human-labeled make-rate counts. The before/after comparison is descriptive and does not establish that the drill caused the change.

Open the **Report** view (or **Open full report** on Review) and choose **Print or save as PDF**, then choose **Save as PDF** in the browser print dialog. The report is the full 10-section coaching report described in section 15 (overview, coaching summary, technical table, keyframes, shot-by-shot, correction plan, practice plan, injury-risk reduction, progress, methodology); saving the PDF writes only to the location selected in the browser.

To delete a session, select **Delete** on its card in Progress and confirm the prompt. **Destructive:** this removes that session's DB row, shots, review history, linked drill rows, app job record, uploaded source video, and pose-cache file. It preserves other sessions and the player's weekly-goal setting. If file deletion fails, the API reports a warning and the remaining file must be removed manually. The endpoint is `DELETE http://127.0.0.1:8765/api/sessions/<SESSION_ID>`; use it only after confirming the target ID.

Useful API checks while the local server is running:

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8765/api/players/player/history"
Invoke-RestMethod -Method Put -Uri "http://127.0.0.1:8765/api/players/player/goal" -ContentType "application/json" -Body '{"weekly_session_target":3}'
```

Replace `player` with the Player ID used in the app. History returns approved sessions, comparable metric summaries, weekly activity, and active/latest drill. Goal updates accept only an integer from 1 through 7 and write `player_app_settings`. These calls do not create synthetic records.

### Optional Gemini-backed AI coach chat

AI chat is **disabled by default**. It requires a Google Gemini API key, internet access, and API access to the selected model. No key is stored in this repository. Get a key from Google AI Studio, enter it without displaying it in the PowerShell prompt, then launch the server with chat explicitly enabled:

```powershell
$key = Read-Host "Gemini API key" -AsSecureString
$env:GEMINI_API_KEY = [System.Net.NetworkCredential]::new("", $key).Password
$env:GEMINI_MODEL = Read-Host "Gemini model available to your API key (Enter for gemini-3.6-flash)"
if (-not $env:GEMINI_MODEL) { $env:GEMINI_MODEL = "gemini-3.6-flash" }
.venv\Scripts\python.exe web_app.py --host 127.0.0.1 --port 8765 --db shot_lab.db --upload-dir user_data\uploads --pose-cache-dir user_data\pose_cache --enable-llm-chat --llm-provider gemini --llm-model $env:GEMINI_MODEL
```

Required input: user-provided `GEMINI_API_KEY`; no additional model weight is needed. The UI should enable the **Ask** button in **Ask about this session**. The chat sends the user's question plus a compact set of approved metric summaries/cue/source references to Google's Gemini `generateContent` API; it does not send uploaded video or raw landmarks and does not persist chat text. The answer appears with metric sample counts and shot/frame references supplied to the model. Network/API errors should leave local rule-based insight available. To disable chat, stop and restart without `--enable-llm-chat`; close the shell to clear its environment variable. Do not put the key in project files or command history.

Without a key, start the default command and check `/api/health` for `llm_chat_enabled: false`. A chat request should return HTTP 503 with the explicit opt-in message. Do not claim Gemini behavior was verified without a real authorized API call. The Gemini API endpoint/auth pattern follows [Google's official Generate Content REST documentation](https://ai.google.dev/api/generate-content).

### DB Browser checks for Phase 8 persistence

Open the same DB supplied through `--db` and run:

```sql
SELECT key, value FROM schema_meta WHERE key='version';

SELECT player_id, weekly_session_target, updated_at
FROM player_app_settings ORDER BY updated_at DESC;

SELECT remediation_id, player_id, targeted_flaw, recommended_drill,
       status, drill_completed, pre_drill_metric_mean, post_drill_metric_mean,
       pre_drill_metric_std, post_drill_metric_std, feedback_notes, created_at, updated_at
FROM remediations ORDER BY created_at DESC;
```

Expected schema version is `6`. Weekly targets change only after a player chooses one. Remediation rows appear only after explicitly saving a drill; follow-up fields populate only after a qualifying reviewed session is compared. Viewing insights/history or printing a report does not change shot labels or create baselines/remediations.

Stop the server with `Ctrl+C`. Use another unused port if `8765` is already occupied.

## 15. 08-07: AI shooting coach report, phone access over Wi-Fi, and review tools

### Starting the server

**Default (this computer only, bound to 127.0.0.1):**

Windows PowerShell:
```powershell
python web_app.py
```

macOS/Linux:
```bash
python web_app.py
# or: .venv-mac/bin/python web_app.py
```

Defaults: `--db shot_lab.db --upload-dir user_data/uploads --pose-cache-dir user_data/pose_cache --keyframe-dir user_data/keyframes --port 8765`, bound to `127.0.0.1`. Requests whose `Host` header is not `127.0.0.1`/`localhost` are refused (403), and every `POST`/`PUT`/`DELETE` needs the header `X-Shotlab: 1` (the page sends it; curl examples below include it).

### Running on a mobile phone (same Wi-Fi network)

**Start with phone access:**

Windows PowerShell:
```powershell
python web_app.py --lan                       # random 10-character access code each start
python web_app.py --lan --access-code MYCODE2026   # or a fixed code (>= 8 letters/digits)
```

macOS/Linux:
```bash
python web_app.py --lan                       # random 10-character access code each start
python web_app.py --lan --access-code MYCODE2026   # or a fixed code (>= 8 letters/digits)
```

**Mobile phone setup and verification workflow:**

1. **Wi-Fi requirement:** Connect both your computer and your phone to the **same Wi-Fi network**.
2. **Firewall permission (Windows):** If Windows Defender Firewall displays a prompt, check **Private networks** and click **Allow access**.
3. **Expected terminal output:**
   - Displays the local address: `Basketball Shot Lab web app on this computer: http://127.0.0.1:8765`
   - Confirms LAN mode: `Phone access over Wi-Fi is ON (private network only, access code required).`
   - Prints the LAN URL: `  Open on your phone: http://<Wi-Fi IP>:8765/`
   - Prints the generated code: `  Access code: <10-CHAR-CODE>`
   - Prints a direct link: `  One-tap link (keep private): http://<Wi-Fi IP>:8765/?token=<CODE>`
4. **Connecting on your phone:**
   - **QR Code Instant Scan (Recommended):** On the host computer, the **Use it from your phone** card displays a live vector QR code. Open your smartphone camera (iOS Camera app or Android Camera/Google Lens), point it at the screen, and tap the recognized URL pop-up. The URL includes the access token (`?token=...`), instantly authenticating and opening the Practice dashboard with zero manual typing.
   - **Manual connection:** Open Safari or Chrome on your phone, type `http://<Wi-Fi IP>:8765/` (or `https://`), enter the access code on the prompt screen, and submit.
   - **Copy one-tap link:** Clicking "Copy one-tap link" copies the complete authenticated URL directly to your clipboard.
   - On success, the server issues a 30-day `HttpOnly`, `SameSite=Strict` authentication cookie, redirecting to the Shot Lab dashboard. Transient local loopback probes (127.0.0.1) are cleared automatically so no spurious TLS warning banners distract during live testing or demo.
   - Ten wrong access codes from one device triggers a 10-minute rate limit lockout (HTTP 429). Requests from non-private addresses get 403. `GET /api/connection` shows the address and code only to the host computer itself.
5. **Mobile video uploads:**
   - You can upload shooting clips directly from your phone's photo library/camera roll over plain `http://`.
   - The backend automatically handles mobile formats, including iPhone HEVC (`.mov`/`.mp4`), generating an H.264 replay proxy when needed.
6. **In-browser camera recording on phones (HTTPS):**
   - Mobile browsers require **HTTPS** (secure context) for WebRTC / `navigator.mediaDevices.getUserMedia` physical camera hardware access.
   - **Built-in (recommended):** `python -m pip install cryptography`, then `python web_app.py --lan --https`. See section 17 and README › "Phone camera over Wi-Fi (HTTPS)" for trusting the certificate on each device.
   - **Your own certificate (e.g. mkcert):** pass `--tls-cert` and `--tls-key`:
     ```powershell
     mkcert -cert-file certs/shotlab.pem -key-file certs/shotlab-key.pem <Computer Wi-Fi IP> localhost 127.0.0.1
     python web_app.py --lan --tls-cert certs/shotlab.pem --tls-key certs/shotlab-key.pem
     ```
   - Both flags are required together and cannot be combined with `--https`. The access cookie gets the `Secure` flag. `certs/`, `*.pem` and `user_data/` are git-ignored.
   - If running over plain HTTP, simply record the clip with your phone's native Camera app, then choose **Upload a file** in the web app.

**What happens after an upload (worker stages and progress):** pose analysis (0–85%) → "Preparing a replay copy that plays in every browser" (an H.264 copy `<upload id>-replay.mp4` in the upload dir, only when the codec/container may not play everywhere, e.g. iPhone HEVC; the original is kept) → "Measuring mechanics and writing your coaching report" (stores `attempt_analysis`, `session_analysis`, `session_reports` rows and keyframe JPEGs under `user_data/keyframes/<session_id>/`) → complete. **Cancel analysis** (or `POST /api/jobs/<job_id>/cancel`) stops after the current frame, marks the job `failed`/`cancelled`, and removes the partial session, its pose cache and upload.

**Upload validation:** extensions MP4/MOV/M4V/AVI/MKV/WebM (or inferred from `X-Upload-Type` when the name has none), ≤ 250 MB, duration 0.5 s–10 min, first frame must decode (FFmpeg fallback first). Errors are returned as 400/413/415 with a plain message; nothing is kept on failure.

**Report:**

```bash
curl -s http://127.0.0.1:8765/api/sessions/<SESSION_ID>/report | python3 -m json.tool | head -80
curl -s "http://127.0.0.1:8765/api/sessions/<SESSION_ID>/report?refresh=1" > /dev/null   # force a rebuild
```

Expected keys: `meta, overview, executive, technical, evidence, shots, correction_plan, practice_plan, injury, progress, findings, methodology`. `meta.from_cache` is `true` when the saved report was reused; any review edit, manual attempt, camera-view change or pose refresh changes the inputs and triggers a rebuild. Returns 409 while the session is still being analysed. In the browser: **Report** tab, or **Open full report** on Review; **Print or save as PDF** prints the report only (page numbers and footer in Chromium-based browsers). Side effects: writes/overwrites rows in `session_analysis`, `attempt_analysis`, `session_reports` and keyframe files for that session; never changes shot fields.

**Review tools (browser):** Pose and Angles toggles on the replay (live elbow/knee image-plane angles), ‹ Prev / Next › attempt, mm:ss timestamps, red/green coach markers on the timeline, per-attempt measurements under the editor, timestamp chips in the Coach summary. **Add an attempt the detector missed** (or `POST /api/sessions/<id>/shots` with `{"start_frame":…, "release_frame":…, "end_frame":…}`) creates an approved shot with `outcome_source = manual_attempt`, no machine frames, and a review-history entry. A **Recording check** banner offers **Save view** (`PUT /api/sessions/<id>/camera-view` with `{"camera_view":"side_90|oblique_45|frontal|rear"}`; updates the session and its shot rows). Sessions analysed before 2026-10-25 show **Refresh pose data** (`POST /api/sessions/<id>/refresh-pose`): re-runs pose on the saved video, rewrites only the pose cache, keeps every shot and review, then rebuilds the report.

```bash
curl -s -X POST http://127.0.0.1:8765/api/sessions/<SESSION_ID>/shots -H "X-Shotlab: 1" -H "Content-Type: application/json" -d '{"start_frame":120,"release_frame":140,"end_frame":160}'
curl -s -X PUT  http://127.0.0.1:8765/api/sessions/<SESSION_ID>/camera-view -H "X-Shotlab: 1" -H "Content-Type: application/json" -d '{"camera_view":"side_90"}'
```

**Deletion** now also removes the session's analysis and report rows, replay copy and keyframe folder.

**DB check (schema v7; v8 after section 16):**

```sql
SELECT key, value FROM schema_meta WHERE key='version';          -- expect 7 (8 once the workout coach has run)
SELECT session_id, analysis_version, computed_at FROM session_analysis ORDER BY computed_at DESC;
SELECT shot_id, boundaries_key, analysis_version FROM attempt_analysis WHERE session_id = '<SESSION_ID>';
SELECT session_id, report_version, generated_at FROM session_reports ORDER BY generated_at DESC;
```

**Manual acceptance on real footage (developer):** upload a permitted side-on clip; confirm/correct attempts; check that each Coach-summary finding's timestamps show the described moment; open section 8 and confirm it states what the video shows, why it may matter, a conservative modification and what cannot be concluded, with no diagnosis; print to PDF; restart the server and reopen the report (expect `Saved report from …`). Repeat from an iPhone and an Android phone with `--lan`. The developer must do the phone checks; they were not done in the agent workspace.

## 16. 09: Personalized workout coach

Full design: `docs/reference/WORKOUT_COACH.md`. Inputs: a session with a finished report, plus the demonstration videos in `workout/` (project root, not in Git, read-only). Only exercises with a demonstration video in that folder are prescribed. Without `workout/` the rest of the app works, but generating a workout returns `422`. Very restrictive choices that leave too few video exercises also return `422`, with the minutes that fit.

```bash
# macOS / Linux
.venv-mac/bin/python web_app.py --port 8765                                   # uses ./workout
.venv-mac/bin/python web_app.py --port 8765 --workout-dir "/path/to/workout"  # another folder
```

```powershell
.venv\Scripts\python.exe web_app.py --port 8765 --workout-dir C:\path\to\workout
```

In the browser:
1. Open **Report**.
2. Select **Generate My Personalized Workout**.
3. Choose equipment, level, duration (20–60 min) and limitations.
4. Select **Generate My Workout**.
5. Review the plan and select **Start workout**.

Expected:
- every main exercise shows **Why this exercise**, linked to a report finding or to your goal;
- the total is at least 20 minutes and at least the duration you chose;
- videos loop during work and pause during rest;
- the voice says the exercise name once, then only the last 10% of each count;
- reloading the page resumes paused;
- **End workout** produces a summary that marks unfinished work as skipped or not reached.

API checks (`X-Shotlab: 1` is required on POST/PUT/DELETE):

```bash
curl -s http://127.0.0.1:8765/api/sessions/<SESSION_ID>/workout-context | python3 -m json.tool | head -40
curl -s -X POST http://127.0.0.1:8765/api/sessions/<SESSION_ID>/workouts -H "X-Shotlab: 1" -H "Content-Type: application/json" \
     -d '{"equipment":["bodyweight","band"],"fitness_level":"beginner","duration_min":25,"avoid":[],"goals":[],"pain":false}'
curl -s http://127.0.0.1:8765/api/workouts/<WORKOUT_ID> | python3 -m json.tool | head -20
curl -s -o /dev/null -w "%{http_code}\n" -H "Range: bytes=0-99" http://127.0.0.1:8765/api/workout-media/running_in_place   # 206
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8765/api/workout-media/..%2F..%2Fetc%2Fpasswd                   # 404
curl -s -X DELETE http://127.0.0.1:8765/api/workouts/<WORKOUT_ID> -H "X-Shotlab: 1"
```

Side effects:
- creates or updates rows in `workout_plans` (schema v8 adds this table on first start);
- deleting a session deletes its workouts;
- video files are never written.

DB check:

```sql
SELECT workout_id, session_id, status, planned_duration_s, created_at, ended_at FROM workout_plans ORDER BY created_at DESC;
```

Tests:

```bash
PYTHONPATH=src:. python3 -m pytest -q tests/unit/test_workout_planner.py tests/e2e/test_workout_api.py tests/e2e/test_workout_ui.py
```

- The catalog-to-video check runs only when `workout/` is present; otherwise it is skipped.
- The UI test writes temporary **synthetic VP9** clips under the catalog's file names to test loop and pause logic. It does not test H.264 playback.

**Manual checks (developer).** These were not done in the agent workspace:
- H.264 demo playback in Safari and Chrome on macOS;
- real speech output and voice choice;
- iPhone/Android over `--lan`, including screen lock and returning to the tab.

## 17. Pranabv1: Live camera ball tracking HUD, automated outcome, and dip-angle verification (Web App)

**Start Web Application Server (Windows / cross-platform):**

```powershell
# Using py -3.12 or python
py -3.12 web_app.py
# Equivalent module entry point:
py -3.12 -m basketball.app.web_app --port 8765
```

Defaults: `--db shot_lab.db --upload-dir user_data/uploads --pose-cache-dir user_data/pose_cache --keyframe-dir user_data/keyframes --port 8765`, bound to 127.0.0.1.

**Live Camera Ball & Rim Tracking (Browser):**
1. Open `http://127.0.0.1:8765/` in Chrome or Edge and navigate to the **Live Camera** tab (`#pane-camera`).
2. Click **Start Camera & Tracking**.
3. Open Developer Tools (`F12` -> Console tab) to monitor live frame processing without errors.
4. The interface renders:
   - Live video feed with overlaid `<canvas id="camera-overlay">`.
   - Top broadcast HUD pills:
     - Rim lock status (`Rim Calibrated` in green or `Searching for rim…` in amber).
     - Arc peak (`PEAK MAX`).
     - Live knee angle (`KNEE`): displays measured numerical degrees (e.g. `158.4°`) when detected, or `--` when absent or below confidence threshold.
     - Live arm angle (`ARM`): displays measured numerical degrees (e.g. `92.1°`) when detected, or `--` when absent.
     - Current shot phase (`PHASE`): displays clean phase strings (`"IDLE"`, `"GATHERING"`, `"DIP"`, `"SET POINT"`, `"RELEASING"`, `"FOLLOW THROUGH"`).
   - Neon orange skeleton overlay, detected basket rim box with concentric target reticle, detected basketball bounding box, and parabolic glowing trajectory trail.
   - Bottom broadcast stats card: Shots made (`SUCCESSES`), shots missed (`FAILURES`), and shooting percentage (`SUCCESS`).
   - Recalibrate button (`Recalibrate Rim`) to reset tracker state via `POST /api/live/reset`.
   - Dynamic popup banner when a shot outcome is detected (`SHOT MADE!` / `SHOT MISSED!`).

**Live Verification Failure Indicators & Symptoms:**
- **Console TypeError (`p.toUpperCase is not a function`)**: Indicates `current_phase` was sent as a 3-tuple `(state, wrist_v_y, elbow_v_ang)` rather than an unpacked string. The web client expects a string.
- **Phase HUD Stuck on "IDLE"**: Indicates `compute_all_angles` or `phase_detector.update` positional arguments were misaligned, resulting in invalid kinematic inputs for phase transition logic.
- **Missing Angle Readouts (`--`) Despite Full Body Visible**: Indicates `world_landmarks` or landmark validity map was misdirected, preventing 2D/3D angle calculation.
- **Zero Shot Attempts Registered**: Indicates shot lifecycle callbacks (`on_shot_started`, `on_shot_release`, `on_shot_ended`) failed to fire due to tuple comparison failure against phase names.
- **Invented Angles on Black/Empty Frame**: Check that missing or low-visibility frames yield `knee_angle: null`, `elbow_angle: null`, and `phase: "idle"`.

**Live API Endpoints (Manual verification):**
```powershell
# Health check (includes live camera engine and ball tracker readiness)
curl -s http://127.0.0.1:8765/api/health

# Reset live camera session tracker
curl -s -X POST http://127.0.0.1:8765/api/live/reset -H "X-Shotlab: 1"

# Post frame for live tracking analysis (JSON payload with base64 JPEG and client timestamp)
curl -s -X POST http://127.0.0.1:8765/api/live/process-frame -H "X-Shotlab: 1" -H "Content-Type: application/json" -d '{"image_data":"data:image/jpeg;base64,...","timestamp_ms":1000}'
```

**Dip-Angle Localization and Omission Verification:**
- For shots with a distinct knee dip ($40^\circ \le \text{knee} \le 165^\circ$), `machine_dip_frame` and `knee_angle_dip_3d` are persisted in `ShotLabDB`, and the review timeline renders a gold `Dip` marker and editable keyframe input.
- For flat-footed shots or noisy landmark detections where no valid dip occurs between start and release, the pipeline sets `dip_frame = None`. In this case, the web review timeline and editor **strictly omit** the Dip marker and input controls (no blank inputs, placeholders, or guessed values).
- Automated shot outcome (`automated_outcome`, `automated_outcome_conf`) displays as `Automatic: Made/Missed (X%)` or `Needs confirmation`, leaving human ground-truth `shots.outcome` untouched until confirmed.

**Automated Test Suite Verification:**
```powershell
$env:PYTHONPATH="src;."
py -3.12 -m unittest discover tests
# Or run specific test suites:
py -3.12 -m unittest tests/unit/test_live_camera_service.py
py -3.12 -m unittest tests/unit/test_dip_angle_model.py
py -3.12 -m unittest tests/unit/test_video_analysis_ball_tracking.py
py -3.12 -m unittest tests/e2e/test_web_app.py
```
## 17. 10: Camera recording over Wi-Fi (HTTPS) and workout voice guidance

**Root cause of "camera recording does not work over Wi-Fi":**
- Pages opened at `http://<Wi-Fi IP>` are not a secure context, so browsers remove `navigator.mediaDevices`.
- Before this change, the page then said "This browser cannot record locally".
- It now explains the https requirement, and `--https` provides HTTPS without extra tools.

```bash
python -m pip install cryptography
python web_app.py --lan --https                              # creates user_data/certs/ on first start
python web_app.py --lan --https --cert-dir /path/to/certs    # keep certificates elsewhere
```

Expected terminal output, in addition to the LAN lines:
- `HTTPS certificate made on this computer (local use only):`
- `Covers: localhost, <host>.local, 127.0.0.1, ::1, <Wi-Fi IP>`
- the CA certificate path;
- `CA SHA-256 fingerprint: …`;
- `A NEW local CA was created…` on the first start only.

Addresses outside private ranges are listed as "Not covered".

Side effects:
- writes `user_data/certs/` with these files:
  - `shotlab-local-ca.pem` / `.crt` (public);
  - `shotlab-local-ca-key.pem` (private, mode 600);
  - `shotlab-server.pem`, `shotlab-server-key.pem` (private, mode 600);
  - `shotlab-server.json`;
- the server certificate is re-issued when the LAN addresses change or it nears expiry;
- deleting the folder creates a new CA (devices must trust it again).

Checks:

```bash
curl -s --cacert user_data/certs/shotlab-local-ca.pem https://127.0.0.1:8765/shotlab-ca.crt -o /tmp/ca.crt && echo "TLS OK"
openssl x509 -in user_data/certs/shotlab-local-ca.pem -noout -ext nameConstraints   # private ranges, localhost, .local only
```

**Browser checklist (manual; physical devices):**

| Step | Expected |
|---|---|
| Phone opens `http://<IP>:8765` and selects **Record with camera** | A note says https is required; uploading still works |
| Phone opens `https://<IP>:8765` after trusting the certificate | No warning; **Turn on camera** asks for permission and shows the preview in the camera's real frame shape |
| Switch camera | Shown only when the device has more than one camera; switches front/back |
| Start recording | REC indicator and timer appear |
| Pause | Timer freezes (where the browser supports pause) |
| Stop | The clip plays back in the viewport; **Retake** discards it |
| **Analyze this session** | Upload progress, then a normal analysis job |
| Safari | Records MP4 |
| Chrome / Android | Records WebM |

**Workout voice (browser, any device):**

| Step | Expected |
|---|---|
| Start a workout | The exercise name once |
| Repetition sets | Every rep counted down ("10, 9 … 1"), matching the on-screen number; each-side exercises say "Switch sides. 10" |
| Timed sets | "45 seconds", then every 10 s, then 5–1 |
| Rest begins | "Rest for N seconds" once, then silence; the countdown is on screen only |
| Rest ends | "Rest complete. Next exercise: X." (or "Next set: X, set 2 of 3."); X's name is not said again |
| Pause / mute / skip | Speech stops immediately; resuming repeats nothing |
| Reload during rest | Resumes paused; the rest start is not announced again |

Automated (synthetic):

```bash
PYTHONPATH=src:. python3 -m pytest -q tests/unit/test_local_tls.py tests/e2e/test_camera_recording.py tests/e2e/test_workout_ui.py tests/unit/test_workout_planner.py
```

What the automated tests use:
- the camera tests use Chromium's **fake camera** (a test pattern), not a physical camera;
- the voice tests use a **recording stand-in** for speech;
- none of them verify real audio, Safari/iOS recording or Android devices; those remain manual checks.

## 18. 11: AI coach chat (Groq primary, Gemini backup), HTTPS trust diagnostics and the phone setup page

**Configure the chat** (`.env` is git-ignored; `.env.example` holds placeholders only):

```bash
python -m pip install groq   # official Groq SDK (primary provider, streaming); also in requirements.txt
cp .env.example .env    # then set GROQ_API_KEY=… and GEMINI_API_KEY=… in .env (never in .env.example)
PYTHONPATH=src python3 -m basketball.coaching.llm_coach            # key check per provider: lists models, no tokens
PYTHONPATH=src python3 -m basketball.coaching.llm_coach --answer   # also a one-word reply from each (uses a little quota)
python web_app.py --lan --https                                    # chat turns on automatically when a key is set
```

Expected output of the key check:
- one line per configured provider, for example `Groq (primary, model openai/gpt-oss-120b): key_ok - …` and `Google Gemini (backup, model gemini-3.8-flash): key_ok - …`;
- other possible states: `invalid_key`, `model_not_listed` (lists usable models), `forbidden`, `unreachable`;
- exit code 0 only if every configured provider is `key_ok`.

Start-up lines:
- `Settings loaded from .env: GEMINI_API_KEY, GROQ_API_KEY` (key names only, never values);
- `AI coach chat: enabled - Groq (openai/gpt-oss-120b); backup Google Gemini (gemini-3.8-flash)…`;
- one `AI coach chat key check (…)` line per provider.

Options:
- `--disable-llm-chat` keeps chat off.
- `--llm-provider {auto,groq,gemini,xai}` chooses the primary; `auto` means Groq, then Gemini.
- `--llm-model ID` sets the primary provider's model.
- `--env-file PATH` reads a different settings file.

Groq request (official SDK, `stream=True`):
- parameters: `temperature=1`, `max_completion_tokens=2048`, `top_p=1`, `reasoning_effort="medium"` (reasoning models only), `stream=True`;
- success means the stream ended with a finish reason and produced answer text.

Streaming endpoint: `POST /api/sessions/<id>/coach-chat` with `Accept: application/x-ndjson` returns one JSON event per line:
- `start {provider, model}`;
- `delta {text}`;
- `fallback {from, to, code, http_status, provider_code, reset}`;
- then `done {provider, model, fallback_from, notice, evidence}` or `error {error, code, http_status, provider_code}`.

Closing the connection cancels Groq. Without that `Accept` header the route returns one JSON reply, as before.

Answer style:
- **Instructions:** `llm_coach.system_prompt_for(question)` is the same for every provider. It asks for plain coaching language with no tables, IDs, frame numbers or internal metric names, and adds guidance for strengths, practice, weakness and uncertain questions. The grounding rules are unchanged.
- **Detail on request:** questions asking for detail/measurements/evidence add a `### Technical details` section. The `done` event then has `detailed: true`, and the chat card shows a "Measurements behind this answer" section.
- **Browser check:** ask "What are my strengths?" and expect a short answer with bullets and no tables or IDs. Then ask "Show me the detailed measurements" and expect the numbers in a separate section.

Fallback rule:
- Gemini is tried only when Groq fails temporarily: `rate_limited` (429), `service_error` (5xx/498), `timeout`, `unreachable`, `incomplete` (the stream broke off), or `empty` (no answer text).
- No fallback for `invalid_key`, `forbidden`, `model_not_found`, `bad_request`, or an invalid question.
- Each provider is called at most once per question.

API checks:
- `GET /api/health` returns `llm_provider`, `llm_model`, `llm_status`, and `llm_backup` `{provider, model, label, status}`, or `llm_setup` when chat is off.
- `POST /api/sessions/<id>/coach-chat` (needs `X-Shotlab: 1`) returns:
  - `200 {answer, provider, model, fallback_from, notice, evidence}`;
  - or `{error, code}` with codes `not_configured` 503, `invalid_key`/`forbidden`/`model_not_found` 502, `rate_limited` 429, `timeout` 504, `unreachable`/`service_error` 503.
- Side effects: nothing is stored locally.

**HTTPS trust diagnostics:**
- **Phone setup page** (with `--lan --https`): it is printed as `Phone setup (certificate + steps, plain http, certificate only): http://<IP>:8766/`.
  - `GET /` returns the steps and the fingerprint.
  - `GET /shotlab-ca.crt` returns the public CA certificate.
  - Every other path returns 404. Private-network clients only.
  - `--setup-port N` changes the port; `--setup-port 0` turns the page off.
- **Handshake failures** are logged as one line per device: `[https] <ip>: SSLV3_ALERT_CERTIFICATE_UNKNOWN. This device does not trust…`, or `HTTP_REQUEST` when `http://` was used on the https port. They are also listed in `GET /api/connection` → `tls_problems` (computer only).
- **Camera diagnostics** (camera pane): shows secure context, `getUserMedia`, `MediaRecorder`, supported recording types, the number of cameras and the last camera error.

**Front/rear camera switch** (camera pane, before recording or after Stop/Retake):
- The button reads **Use front camera** or **Use rear camera**.
- It releases the current camera, then opens the other side with `facingMode: {exact: "user"|"environment"}`. If that is rejected, it uses a listed camera whose label matches, then `facingMode: {ideal: …}`.
- If the other side cannot be opened, the previous camera is reopened and the reason is shown.
- The button is hidden while recording and on devices with a single camera.

```bash
PYTHONPATH=src:. python3 -m pytest -q tests/unit/test_llm_coach.py tests/e2e/test_ai_chat_and_https.py tests/e2e/test_chat_ui.py tests/e2e/test_camera_switching.py   # mocked APIs (Groq SDK over a mock HTTP transport), scripted camera
```

## 19. Athletic Monochrome Landing Page & User Authentication / Onboarding

**Overview:**
Integrates the athletic black-and-white landing page theme (featuring the male basketball athlete visual from `landing-page-black-white-with-male-basketball-athlete`) into the web UI without breaking existing functionality. Adds local SQLite user authentication and athlete onboarding (`users` and `user_sessions` tables in `shot_lab.db`), syncing shooting hand, experience, style, and physical profile directly into session setup.

**Start the web application:**
```bash
python -m basketball.app.web_app --port 8000
# Or using the root entry point:
python web_app.py --port 8000
```

**Run automated unit and integration tests:**
```bash
PYTHONPATH="src:." python3 -m unittest tests/unit/test_auth.py tests/integration/test_auth_routes.py
```
Expected output:
```text
.......
----------------------------------------------------------------------
Ran 7 tests in 0.4s

OK
```

**Manual Browser Verification Steps:**
1. Open `http://127.0.0.1:8000/` in a browser.
2. Confirm the athletic high-contrast black-and-white theme is active by default, displaying the male basketball athlete hero banner (`/assets/hero.jpg`) with gradient overlay, bold athletic typography ("PRECISION IN EVERY REP. ELEVATE YOUR SHOOTING FORM."), and metric highlights (33 Keypoints, 20+ Biomechanical Metrics, 100% On-Device Privacy).
3. In the top bar, click **Join Lab** (or click **Shooter Profile & Onboarding** on the hero card):
   - **Step 1 (Account):** Enter Full Name, Player ID / Handle, Email, Password. Click **Continue to Shooter Profile**.
   - **Step 2 (Shooter Profile):** Select Shooting Hand (Right/Left/Ambidextrous), Experience Level (Beginner/Intermediate/Advanced/Coach), Primary Shot Style (Jump Shot/Set Shot), Height (cm), Wingspan (cm), and Goals.
   - Click **Complete Onboarding & Sign Up**.
4. Confirm success:
   - A welcome toast appears ("Welcome to Shot Lab...").
   - The topbar replaces "Sign In / Join Lab" with the athlete user badge showing user avatar, name, and skill level.
   - The **Player and session** setup form (`#upload-form`) is automatically pre-filled with the user's Player ID, Shooting hand, Experience, Shot style, and Goals.
5. Click the user badge to open **Shooter Profile & Settings**:
   - Update shooting goals or height and click **Save Profile Changes** — data updates in SQLite `users` and `players` tables.
   - Click **Sign Out** — session is invalidated, and topbar returns to "Sign In / Join Lab".
6. Click **Sign In**: enter registered email and password to log back in.
7. Confirm all existing workflows (drag-and-drop video upload, camera recording, reviewing quarantined attempts, coaching reports, and dribble drills) work with full backward compatibility.

## Expected verification outputs

- Annotation Lab: video window opens; edits are saved to the selected SQLite DB when saved/committed.
- `inspect_db.py`: clip, proposal, interval, and shot tables show IDs, labels, splits, and review state.
- `validate_dataset.py`: `PASSED` with zero errors; warnings still need inspection.
- `export_dataset.py`: `train.jsonl`, `val.jsonl`, `test.jsonl`, and `DATASET_MANIFEST.json` written to the chosen output directory.
- Evaluation tools: JSON report with input/split/sample metadata and metrics. `EXPLORATORY` means acceptance gates were not met.
- Unit tests: unittest summary ending in `OK`; this verifies tested software behavior, not real-world accuracy.


## 20. Shot Types Registry & Per-Shot-Type Analysis Configuration Layer

### 20.1 Run Shot Types Registry Unit Tests
- **Command**:
  ```powershell
  $env:PYTHONPATH="src;."
  python -m unittest tests/unit/test_shot_types_registry.py
  ```
- **Inputs**: None (uses in-memory test databases and synthetic fixtures).
- **Expected Output**:
  - 9 tests passing cleanly.
  - Verifies all 12 shot types are present across 4 groups (Stationary, Dynamic, Range, Other).
  - Confirms metric weights sum to 1.0 for every shot type.
  - Tests alias resolution (off_the_dribble and off_dribble map to pull_up).
  - Tests baseline isolation by shot type (pull_up shots do not dilute catch_and_shoot baselines).
  - Verifies heuristic detector fallback when needs_calibration is true.
  - Verifies coaching engine priority boost by metric weight: `priority * (1.0 + weight * 2.0)`.
  - Verifies coaching engine 'not enough evidence' state when attempts are below threshold.
- **Side Effects**: None (temporary databases deleted on teardown).

### 20.2 Database Schema Version 9 Migration
- **Command**:
  ```powershell
  $env:PYTHONPATH="src;."
  python scripts/migrate_shot_types.py --db-path user_data/shot_lab.db
  ```
- **Inputs**: Path to existing SQLite database (default: `user_data/shot_lab.db`).
- **Expected Output**:
  - `[INFO] Migrated database to schema version 9 with shot_type_id columns.`
  - Backfills `shot_type_id` on `sessions`, `shots`, `baselines`, `labeled_clips`, and `attempt_analysis`.
  - Maps existing `off_the_dribble` and `off_dribble` entries to `pull_up`.
- **Side Effects**: Modifies database schema to version 9.

### 20.3 Annotation Lab with Shot Type Selection
- **Command**:
  ```powershell
  $env:PYTHONPATH="src;."
  python tools/annotation_lab.py raw_clips/mikeddunnstud1.mp4 --shot-type pull_up
  ```
- **Inputs**: Video file path, optional `--shot-type` (e.g. `pull_up`, `catch_and_shoot`, `step_back`, `free_throw`).
- **Expected Output**:
  - Launches annotation interface registering attempts with `shot_type_id="pull_up"`.
- **Side Effects**: Writes annotated shot records to database.

### 20.4 Web App Shot Type API Verification
- **Command**:
  ```powershell
  $env:PYTHONPATH="src;."
  python -m basketball.app.web_app
  ```
- **Inputs**: Navigate to `http://localhost:8765/api/shot-types` in browser or curl.
- **Expected Output**:
  - Returns JSON containing `version: "1.0"`, `shot_types` dictionary with all 12 canonical entries, and `aliases` mapping.


## 21. Ball Tracking Outcome Estimator, Consensus Rim Anchor, and Model Calibration Verification

### 21.1 YOLO Model Comparison
- **Command**:
  ```powershell
  $env:PYTHONPATH="src;."
  python scripts/compare_yolo_models.py --db shot_lab.db --frames-per-clip 30
  ```
- **Inputs**: Path to SQLite database containing reviewed attempts (default: `shot_lab.db`), optional `--models` list (default: `models/best.pt models/ballRim.pt`), `--frames-per-clip` (default: 60).
- **Expected Output**:
  - Reports count of reviewed attempts.
  - If count < 50, emits notice: `NOTICE: Reviewed attempts count (X) is under 50. Results are strictly anecdotal and cannot be considered a statistically significant benchmark.`
  - Prints markdown table with columns: `Model`, `Ball Det %`, `Rim Det %`, `Ball Mean Conf`, `Rim Mean Conf`, `Rim Stability`, `FPS`.
- **Side Effects**: Read-only evaluation; does not modify database or model weights.

### 21.2 Calibration Dataset Export
- **Command**:
  ```powershell
  $env:PYTHONPATH="src;."
  python scripts/export_calibration_data.py --db shot_lab.db --output user_data/calibration_data.json
  ```
- **Inputs**: SQLite database with reviewed shots (default: `shot_lab.db`), output file path (default: `user_data/calibration_data.json`).
- **Expected Output**:
  - `Exported X reviewed attempts (Y makes, Z misses) across N sessions to user_data/calibration_data.json.`
  - Preserves `session_id`, `player_id`, human label, automated outcome, uncalibrated `p_make`, `evidence_quality`, and full feature dictionary.
- **Side Effects**: Writes JSON export to destination file.

### 21.3 Outcome Estimator Calibration Gate
- **Command**:
  ```powershell
  $env:PYTHONPATH="src;."
  python scripts/calibrate_outcome_model.py --db shot_lab.db --data user_data/calibration_data.json
  ```
- **Inputs**: Pre-exported calibration data or reads directly from `shot_lab.db`.
- **Expected Output**:
  - Verifies minimum sample size gate (50 reviewed attempts across >= 3 sessions).
  - If below threshold: prints `STATUS: INSUFFICIENT DATA FOR STATISTICAL CALIBRATION`, shows remaining count needed, and prevents premature fitting.
  - If above threshold: fits L2-regularized logistic weights across session folds and outputs proposed provisional configuration without touching production CFG.
- **Side Effects**: None; production CFG is never modified automatically.

### 21.4 Export Hard Frames around Rim Crossing
- **Command**:
  ```powershell
  $env:PYTHONPATH="src;."
  python scripts/export_hard_frames.py --db shot_lab.db --out-dir user_data/hard_frames --limit 5
  ```
- **Inputs**: SQLite database containing shot reviews (default: `shot_lab.db`), target directory (default: `user_data/hard_frames`), optional `--limit`.
- **Expected Output**:
  - Identifies human/machine disagreement and high-uncertainty attempts.
  - Extracts image sequences around estimated rim crossing (`release_frame + 0.75s`).
  - Writes JPEG frames and `manifest.json` under `user_data/hard_frames/<shot_id>/`.
- **Side Effects**: Creates image files and metadata manifests in output folder.

### 21.5 Rim Anchor REST API
- **Command**:
  ```powershell
  # Start web server
  $env:PYTHONPATH="src;."
  python -m basketball.app.web_app
  ```
  In browser / curl:
  - `GET http://localhost:8765/api/sessions/{session_id}/rim-anchor`
    - Returns JSON: `{"session_id": "...", "rim_anchor": {"cx": ..., "cy": ..., "w": ..., "stability": ..., "rim_source": "auto"|"user_click"}}`.
  - `POST http://localhost:8765/api/sessions/{session_id}/rim-anchor` with payload `{"cx": 500, "cy": 300, "w": 80}`
    - Replaces session rim anchor with `user_click` provenance.
    - Re-estimates machine outcomes for all shots in the session using full-resolution Rim-ROI second pass and updated trajectory math.
    - Returns updated anchor and re-estimated shot list without mutating human labels.
- **Side Effects**: Updates `sessions` and `shots` machine outcome columns in `shot_lab.db`.

### 21.6 Web Review Rim Confirmation Workflow
- **Procedure**:
  1. Open a session in Shot Lab Review (`http://localhost:8765/#review`).
  2. If the automatic clip rim detector was uncertain (stability > 0.15 or false rim rejected), notice the amber banner: `Rim not confirmed. Click the rim to improve make/miss estimates.`
  3. Click `Confirm rim` (in banner or overlay controls).
  4. On the video canvas, cursor changes to a crosshair. Click the rim center and drag to the rim outer edge, then release.
  5. The client submits `POST /api/sessions/{session_id}/rim-anchor`, updates the session anchor in cyan (`#00f0ff`) with concentric rings and `RIM: CONFIRMED` badge, re-estimates all attempts in the session, and refreshes the attempt list with `Likely make` / `Likely miss` / `Unclear` and reason pills.
