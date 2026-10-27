# Project State

## Current milestone

**Reliable, evidence-backed personal shot analysis**

- **Active phase:** Phase 8 — Local player app implementation complete and redesigned (08-06, 2026-10-17); user UAT remains for evidence-gated coaching, history/trends, drill follow-up, and PDF export on real approved records. Hosted deployment remains deferred to Phase 9.
- **08-07 (2026-10-25):** AI shooting coach report (measurements, rules, 10-section report with keyframes and PDF, injury-risk-reduction section), phone access over Wi-Fi with access code, review tools, schema v7. Full suite 141 passed / 1 skipped / 1 failed (missing `raw_clips/`). Real-clip acceptance in a disposable DB passed; real-phone checks remain developer work. See `phases/08-user-facing-app/08-07-AUDIT.md`.
- **Phase 6 note:** `SHOT_MODEL_EVAL_REPORT.json` gate verdict is `EXPLORATORY` (3 evaluable validation releases). The web app therefore keeps the existing pose heuristic and treats every detection as a reviewable proposal. No model was retrained in 08-06 because there is not enough labeled held-out data to show an improvement.
- **Phase 1:** Capture/pose/rendering implemented as a prototype; clean-install and cross-platform evidence documented.
- **Phase 2:** Shot state, kinematics, DTW/comparison and related components implemented as prototypes; not broadly validated. Pro profiles are illustrative.
- **Phase 3 (Measurement Integrity & Full-Length Video Benchmark):** Pilot infrastructure exists; accuracy gate remains open.
- **Phase 4 (Personal Shot Lab & Evidence-Gated Coaching):** Completed and verified.
- **Phase 5 (Developer Model Lab & Annotation Dataset):** Completed and verified.
- **Phase 6 (Shot-Event Model and Verification):** Completed and verified.
- **Phase 7 (Ball, Rim, and Trajectory Tracking):** Completed and verified.
  - Multi-clip ingestion: registered 8 newly added raw clips in `clip_splits.json` and `batch_ingest_clips.py` with expanded player registry (`mixkit_shooter`, `stock_shooter`).
  - Cryptographic weights manifest (`WEIGHTS_MANIFEST.md`): recorded SHA256 hashes, licenses (CC BY 4.0), and class taxonomies for `models/best.pt`, `models/ballRim.pt`, and `models/yolov8m-pose.pt`.
  - Dynamic ball & rim tracker (`ball_tracker.py`): dynamic class resolution from `model.names` with substring disambiguation, shot lifecycle event hooks, and fallback to `UNAVAILABLE_NO_WEIGHTS`.
  - Trajectory geometry & physics engine (`ball_geometry.py`): parabola fit with $R^2$ goodness-of-fit, entry angle, launch angle, and minimum evidence gating ($N \ge 4$ points).
  - Advisory DB Schema v4 (`shot_lab_db.py` & `main.py`): columns for advisory make/miss, confidence, trajectory fit $R^2$, entry angle, and ball coverage ratio. Immutable human ground-truth labels (`shots.outcome`).
  - Offline pose backend comparative study (`evaluate_pose_backends.py`): evaluated 12 shared joints across validation clips between MediaPipe Tasks Pose and YOLOv8m Pose, generating `POSE_BACKEND_COMPARISON_REPORT.json`.
  - Unified evaluation harness (`evaluate_ball_tracking.py`): evaluated Roboflow test set (472 images, mAP@50 = 0.7283) and validation footage (73.7% ball coverage), generating `BALL_RIM_EVAL_REPORT.json` (`QUALIFIED_AS_ADVISORY`).
  - All 19 Phase 7 tests passing in 56.3s with zero failures. Knowledge graph updated via `graphify update .`.
- **Phase 8 current slice:** User confirmed local upload/summary and replay/review work. The app now includes per-session mechanic summaries and one-cue advice from approved, `SUFFICIENT` shots (five measured samples minimum); comparable-session history and metric spreads; weekly goal/streak from eligible sessions; explicit drill saving and matched-context follow-up comparison; print-to-PDF report; per-session deletion of DB/review/job/media/cache data; and optional AI chat behind `--enable-llm-chat`, `OPENAI_API_KEY`, and an explicitly configured model. Viewing insights remains read-only. The AI call sends only the question and approved metric summaries/cue/source references, never video/raw landmarks. Current detector has no distinct dip event; the UI reports unavailable. YOLO and automated outcomes are not used by this upload flow. New Phase 8 behavior still needs manual UAT with real approved records; AI needs user-provided credentials/model access and separate network verification. Hosted deployment, authentication, and external-host retention policy remain release work.

## Phase 8 work package 08-06 (2026-10-17): UI redesign and reliability

- [x] **Player UI redesign (`web/index.html`, `web/app.css`, `web/app.js`):** three views (New session, Review, Progress) with hash navigation; "coach's whiteboard" design system with self-hosted Archivo font (`web/fonts/`, SIL OFL, no external requests); upload/record source tabs; camera framing guide; clip timeline with attempt segments, release ticks, playhead and keyboard frame stepping; attempt list with review status; review editor with explicit Approve / Leave for later / Not a shot and Make / Miss / Not sure choices; readable change history; mechanics with sample-gate bars; cue card with evidence jump links or an abstention meter; Progress goal ring, streak, drill card, trend charts with ±1 SD bars, and per-session Open review / Delete. Responsive to 390 px with no horizontal overflow; visible focus, reduced-motion support, CSP header on the page.
- [x] **Reload shows current reviews:** `GET /api/jobs/<id>` now returns live shot rows from SQLite instead of the completion snapshot (previously a page reload showed pre-review state).
- [x] **Reopen any web session:** history entries include the latest completed `job_id`; Progress offers **Open review**.
- [x] **Portable upload paths:** stored absolute video paths from another computer (e.g. Windows paths opened on macOS) resolve to the same generated filename inside `--upload-dir`; files outside it are still never served or deleted. Verified against the existing `shot_lab.db.web_jobs.sqlite3`, whose replay previously returned 404 on macOS.
- [x] **End-of-clip attempts:** an attempt with an observed release that is cut off by the end of the clip is now proposed (quarantined, unknown outcome, last frame as follow-through) instead of being silently dropped. Candidates without a release are still not proposed and are reported as incomplete.
- [x] **Tests:** new `test_web_app.py` (4 integration tests on a real loopback server with a synthetic blank clip). Stale `SCHEMA_VERSION == 4` assertion in `test_ball_tracking_flow.py` relaxed to `>= 4` because Phase 8 moved the schema to v6 while keeping the Phase 7 columns.
- **Verification run (cloud Linux, Python 3.13, MediaPipe 0.10.32, ultralytics 8.4):** `pytest` 80 passed, 1 skipped, 1 failed. The failure is `test_weights_manifest.test_all_raw_clips_accounted_for_in_splits`, because `raw_clips/` is deleted in the current working tree. Real-clip API run on the user's 25 s practice clip: 753 frames, 7 proposals (MP4) and 5 proposals for the same clip re-encoded to WebM, showing detector sensitivity to encoding. Browser screenshots taken at 1440 px and 390 px. Coaching-ready UI states were exercised only on a disposable QA database with approvals made for workflow testing; they are not evidence about the player.
- **Observed limitation:** on that clip the cached MediaPipe skeleton sometimes follows a bystander rather than the shooter, which the replay overlay makes visible. Single-person framing remains a capture requirement.

## Completed Work in Phase 4 (Personal Shot Lab)

- [x] **SQLite & Provenance Engine (`shot_lab_db.py`):** Schema version 2 with `players`, `sessions`, `shots`, `baselines`, and `remediations`. Preserves immutable machine boundaries (`machine_*_frame`) alongside editable human review boundaries (`annotated_*_frame`). Added `shot_style` and `review_status` columns with automatic migration.
- [x] **Live Outcome Hotkeys & HUD Overlay (`main.py`):** Interactive non-blocking 2.5s prompt `[M] Make | [X] Miss | [U] Unknown` stamping `outcome_source: live_hotkey` and approving reviewed shots while leaving unlabeled/unknown attempts quarantined. Passed `shot_style` context through pipeline.
- [x] **Post-Session Review Queue (`review_shots.py`):** CLI and interactive keyframe scrubber allowing boundary and label overrides without data loss. Explicit per-shot approval (`--approve`) and discarding (`--discard`). Blind batch-approval (`--batch-approve`) explicitly rejected with exit code 1 to safeguard baseline integrity.
- [x] **Personal Baseline Engine (`baseline_engine.py`):** Strict shot-style isolation (`jump_shot` vs `set_shot`). Enforces $N \ge 5$ approved shots for baseline computation. Gated make-versus-miss contrast until $N_{\text{makes}} \ge 5 \land N_{\text{misses}} \ge 5$ to prevent small-sample noise distortion. Reports $\bar{x} \pm s$ sample standard deviations and temporal quantization error ($\pm 33.3\text{ms}$ at 30 FPS).
- [x] **Hierarchical One-Cue Remediation (`coach_engine.py`):** Triggers cues based on repeating mechanics thresholds against baselines (Tier 1 Sequencing $\to$ Tier 2 Release Extension $\to$ Tier 3 Frontal Stability). Separated thresholds and drills for `jump_shot` and `set_shot`. Follow-up set evaluation produces purely observational reporting ($N_{\text{pre}}$, $N_{\text{post}}$, $\bar{x} \pm s$, $M/N$ make percentages, `drill_completed`) with zero causal claims.
- [x] **Comprehensive Test Suite:** 18/18 tests passing across `test_shot_lab_db.py`, `test_baseline_engine.py`, `test_coach_engine.py`, and `test_shot_lab_flow.py`.

**Evidence limit:** Passing integration tests confirm application flow, not field accuracy. The N≥5 gate is not protection against false detections unless the underlying shots are reviewed/confirmed.


## Completed Audit Fixes in Phase 3

- [x] **Coordinate-Basis Purity:** `pt_3d` in `analyzer.py` strictly requires all joints from `world_landmarks` in meters; zero fallback to normalized image coordinates within 3D angle calculations.
- [x] **Interpolation Limit Alignment:** Production `interpolate_kinematic_series` default and synthetic evaluator aligned to identical $\le 2$ frames rule ($\le 66\text{ms}$ at 30 FPS).
- [x] **Exploratory Real-Video Benchmark:** `evaluate_video.py` generates `KLAY_EVAL_REPORT.json` with frame-by-frame breakdown, detection rate (65.1%), and explicit labeling of 2D vs. 3D estimate-to-estimate disagreement ($\pm 22.9^\circ$).
- [x] **Metric Dictionary:** Created `METRIC_DICTIONARY.md` defining all formulas, joint triplets, coordinate bases, units, and limitations.
- [x] **Separation of Evidence:** Synthetic regression results (`EVAL_REPORT.json`) strictly distinguished from real video evaluation (`KLAY_EVAL_REPORT.json`).

## Current validation priorities

- The 283.4 ms pilot release-timing MAE is much larger than one-frame quantization at 30 FPS (about 33.3 ms); investigate state-machine timing and false transitions first.
- Evaluate configurable combinations of wrist height/velocity, dip-to-rise ordering, and plausible duration. Treat ball-hand proximity as optional only when YOLO coverage/confidence is measured; unavailable detections mean unknown contact.
- Expand annotations across players and camera views. Report per-player/per-view F1 and timing-error distributions, sample counts, and uncertainty when the sample supports it.
- Record machine-to-human boundary correction rate, boundary shift, and outcome relabel rate while retaining original machine detections.
- The reported 19.7° 2D/world difference is estimate disagreement. Without independent ground truth, neither estimate is known to be more accurate.

