# Graph Report - basketball_proj  (2026-10-27)

## Corpus Check
- 139 files · ~2,491,763 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 10 file(s) not represented in the graph (top: .jsonl 3, (none) 1, .cache 1)

## Summary
- 2005 nodes · 3873 edges · 137 communities (92 shown, 45 thin omitted)
- Extraction: 92% EXTRACTED · 8% INFERRED · 0% AMBIGUOUS · INFERRED: 297 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `f52baf42`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- .run_gui
- Phase 7: Ball, Rim, and Trajectory Tracking — Execution Summary
- app.js
- shooting_analysis.py
- Project State
- shot_coach.py
- app/web_app.py
- BallTracker
- Milestone Summary — v1.0: Reliable, Evidence-Backed Personal Shot Analysis
- report.js
- Ln
- AppHandler
- batch_ingest_clips.py
- ShotLabDB
- os
- Project Roadmap — Basketball Shot Lab to User App
- Basketball Coach — Project Definition
- Product requirements
- PoseEngine
- AI Models in Intelligent Basketball Performance Analysis System
- Baseline Shot Lab — Intelligent Basketball Performance Analysis System
- Ye
- WebAppApiTest
- Key Deliverables & Architecture Implemented
- as
- _rewrite_imports.py
- CalibratedFSMDetector
- 2. Work Breakdown & Task Sequence
- Project Positioning and Technical Notes
- Phase 1 — Core Capture and Vision
- Phase 2 — Shot Analysis Foundations
- kt
- ShotPhaseDetector
- renderResults
- shot_lab_db.py
- ShotFeatureExtractor
- test_shot_coach.py
- Work Division & Project Execution Plan
- pathlib
- Work packages
- JobStore
- M
- history_service.py
- SessionRecorder
- evaluate_ball_tracking.py
- DatasetValidator
- answer_grounded_question
- shot_sequence
- 3. Remediation Plan
- ProComparator
- Phase 3 Mid-Phase Plan — Dataset-Based Testing
- 1. Accomplishments & Deliverables
- ball_tracker.py
- README.md
- .update
- test_shooting_analysis.py
- evaluate_benchmark
- Phase 8 Implementation Summary
- DatasetExporter
- HandEngine
- Phase 8 — Final user-facing video analysis app
- TestShotLabFlow
- TestBallTracker
- sessionItem
- MLSequenceDetector
- Manual Verification and Run Commands
- TestVideoAnalysisService
- Basketball Biomechanics Metric Dictionary
- CoachEngine
- motionOn
- BenchmarkEvaluator
- run_all_public_dataset_evaluations
- LanAccessTest
- Phase 7 — Ball, Rim, and Trajectory Tracking: Context & Decisions
- .train
- BaselineEngine
- Model Weights & Assets Manifest
- zn
- interactive_review_loop
- 1. Accomplishments & Deliverables
- AnnotationLab
- ms
- app/main.py
- ReportServiceTest
- TestShotLabDB
- loadPlayerHistory
- Workflow: Developer Onboarding
- Phase 3 — Ball Tracking Integration & Validation Plan
- TestAnnotationDB
- EVAL-REVIEW — Phase 8: User-Facing App
- AttemptMeasurementTests
- Real-World & Public Dataset Manifest for Basketball Shot Analysis
- 08-07 Audit — AI Shooting Coach brief vs. current implementation
- llm_coach.py
- evaluate_clip
- ._session
- Real-Video Dataset Collection & Annotation Protocol
- ParabolaFit
- json
- Codebase Structure & Conventions
- 2. Locked Architecture & Implementation Decisions
- compute_all_angles
- rules/graphify.md
- workflows/graphify.md
- Phase 3 Work Plan — EPFL SportCenter Camera Pose & Court Geometry Evaluation
- basketball-shot-lab
- 2. Work Breakdown & Task Sequence
- Work order
- h
- test_single_clip
- Phase 3 — Measurement Integrity and Real-Video Validation
- Plan
- 2. Work Breakdown & Task Sequence
- 2. In-Depth Audit Findings
- Running the Applications
- Phase 7 — Ball/rim tracking and outcome evidence

## God Nodes (most connected - your core abstractions)
1. `ShotLabDB` - 114 edges
2. `AnnotationLab` - 41 edges
3. `ShotPhaseDetector` - 35 edges
4. `AppHandler` - 28 edges
5. `PoseEngine` - 26 edges
6. `MLSequenceDetector` - 26 edges
7. `BallTracker` - 24 edges
8. `PoseSeries` - 23 edges
9. `analyze_attempt()` - 22 edges
10. `ShotFeatureExtractor` - 22 edges

## Surprising Connections (you probably didn't know these)
- `08-03 — Validity-gated biomechanics and one-cue coaching` --references--> `CoachEngine`  [INFERRED]
  .planning/phases/08-user-facing-app/08-PLAN.md → src/basketball/coaching/coach_engine.py
- `4. Missing Data & Temporal Interpolation` --references--> `KineticChainAnalyzer`  [INFERRED]
  docs/reference/METRIC_DICTIONARY.md → src/basketball/core/analyzer.py
- `2.1 Configurable Wrist-Height & Vertical Velocity Gates` --references--> `ShotPhaseDetector`  [INFERRED]
  .planning/phases/03-measurement-validation/03-CONTEXT.md → src/basketball/core/analyzer.py
- `3. Scope Fences & Execution Order` --references--> `ShotPhaseDetector`  [INFERRED]
  .planning/phases/03-measurement-validation/03-CONTEXT.md → src/basketball/core/analyzer.py
- `Finding 5: Flawed Baseline Comparison Adapter` --references--> `ShotPhaseDetector`  [INFERRED]
  .planning/phases/06-research-release/EVAL-REVIEW.md → src/basketball/core/analyzer.py

## Import Cycles
- None detected.

## Communities (137 total, 45 thin omitted)

### Community 1 - "Phase 7: Ball, Rim, and Trajectory Tracking — Execution Summary"
Cohesion: 0.20
Nodes (5): 1. Overview & Objectives Delivered, 2. Key Metrics & Empirical Results, 3. Artifacts Created & Updated, 4. Verification & Testing, Phase 7: Ball, Rim, and Trajectory Tracking — Execution Summary

### Community 2 - "app.js"
Cohesion: 0.03
Nodes (60): applyTheme(), ARM, cameraPreview, cameraStartButton, cameraStatus, cameraStopButton, cancelButton, CONNECTIONS (+52 more)

### Community 3 - "shooting_analysis.py"
Cohesion: 0.06
Nodes (27): analyze_attempt(), elbow_angle(), knee_angle(), lean(), put(), analyze_session(), angle_2d(), angle_3d() (+19 more)

### Community 4 - "Project State"
Cohesion: 0.20
Nodes (7): 10. Test Suites (Unit, Integration, E2E), Completed Work in Phase 4 (Personal Shot Lab), Current milestone, Current validation priorities, Phase 8 work package 08-06 (2026-10-17): UI redesign and reliability, Project State, TestWeightsManifestAndClips

### Community 5 - "shot_coach.py"
Cohesion: 0.09
Nodes (40): _active(), _attempt_list(), build_findings(), build_injury_section(), build_practice_plan(), evaluate_attempt(), _evidence(), _finalize() (+32 more)

### Community 6 - "app/web_app.py"
Cohesion: 0.09
Nodes (11): build_parser(), build_session_report(), _discard_cancelled_session(), generate_access_code(), local_network_addresses(), LocalAppServer, main(), _run_analysis() (+3 more)

### Community 7 - "BallTracker"
Cohesion: 0.15
Nodes (5): Phase 3A — Unified Timeline & State Machine Refactoring (Immediate), Task 2: Dynamic Ball & Rim YOLO Tracker (`ball_tracker.py`), BallTracker, load_yolo(), TestBallTrackingFlow

### Community 8 - "Milestone Summary — v1.0: Reliable, Evidence-Backed Personal Shot Analysis"
Cohesion: 0.08
Nodes (24): Task 1 — Trace coordinate systems and define metrics, 1.1 Product Vision, 1.2 Core Capabilities Delivered in Milestone v1.0, 1. Executive Overview, 2.1 Architectural Components, 2. System Architecture, 3. Phase Summary & Progression, 4. Key Architectural Decisions (ADRs) (+16 more)

### Community 9 - "report.js"
Cohesion: 0.09
Nodes (32): an(), at(), be(), ct(), d(), ei(), et(), g() (+24 more)

### Community 10 - "Ln"
Cohesion: 0.12
Nodes (5): c(), cn, Ln, Nn(), un()

### Community 13 - "batch_ingest_clips.py"
Cohesion: 0.12
Nodes (11): compute_sha256(), generate_clip_id(), infer_camera_view(), ingest_all_clips(), load_clip_splits_config(), main(), normalize_player_id(), consolidate_db() (+3 more)

### Community 15 - "os"
Cohesion: 0.10
Nodes (7): Ft(), Gn(), is(), Ls(), os, ot(), Ss

### Community 16 - "Project Roadmap — Basketball Shot Lab to User App"
Cohesion: 0.12
Nodes (16): Coding-agent work, Coding-agent work, Current evidence and limits, Global guardrails, Manual developer work, Manual developer work, Phase 1 — Capture and core vision, Phase 3 — Measurement integrity and real-video evaluation (+8 more)

### Community 17 - "Basketball Coach — Project Definition"
Cohesion: 0.18
Nodes (10): Basketball Coach — Project Definition, Current product, Current / prototype, Differentiation, Non-goals, Planned, Product principles, Product vision (+2 more)

### Community 18 - "Product requirements"
Cohesion: 0.12
Nodes (15): Non-functional requirements, PR-10 — Optional grounded coach chat and engagement, PR-1 — Capture and setup, PR-2 — Pose and measurement integrity, PR-3 — Shot events and biomechanics, PR-4 — Ball and outcome analysis, PR-5 — Coaching and personalization, PR-6 — Session and Shot Lab (+7 more)

### Community 20 - "AI Models in Intelligent Basketball Performance Analysis System"
Cohesion: 0.07
Nodes (28): 1. YOLOv8-Pose (Best Alternative for Pose), 2. ViTPose (Most Accurate Pose Model Available), 3. Ball Detection: YOLOv8 Object Detection, 4. Action Recognition: SlowFast / VideoSwin Transformer, 5. Shooting Feedback with LSTM (Custom Temporal Model), 6. MediaPipe Hands (Wrist/Finger Tracking), 7. Pose3D: Lifting 2D to 3D (VideoPose3D), A Deep Technical Reference for Academic Viva (+20 more)

### Community 21 - "Baseline Shot Lab — Intelligent Basketball Performance Analysis System"
Cohesion: 0.29
Nodes (7): 2. Repository Structure, 3. Key Principles & Architecture, 4. Guidelines for Adding New Features, 5. Testing & Verification, 6. Academic Profile & Team, Baseline Shot Lab — Intelligent Basketball Performance Analysis System, Data Flow

### Community 22 - "Ye"
Cohesion: 0.10
Nodes (6): He(), Ie(), rn, tn(), Ue(), Ye

### Community 23 - "WebAppApiTest"
Cohesion: 0.13
Nodes (4): FrontendUiTest, WebAppApiTest, WebAppCoachFeaturesTest, _write_synthetic_clip()

### Community 24 - "Key Deliverables & Architecture Implemented"
Cohesion: 0.18
Nodes (10): 1. SQLite Persistence & Versioned Schema (`shot_lab_db.py`), 2. Live Outcome Tagging & Boundary Ingestion (`main.py`), 3. Post-Session Review Queue & Quarantine Protection (`review_shots.py`), 4. Personal Baseline Engine (`baseline_engine.py`), 5. Hierarchical One-Cue Remediation Engine (`coach_engine.py`), Key Deliverables & Architecture Implemented, Milestone Status: COMPLETE, Operational CLI Commands (+2 more)

### Community 25 - "as"
Cohesion: 0.11
Nodes (5): as, Ts, Vs(), xs, ys()

### Community 27 - "CalibratedFSMDetector"
Cohesion: 0.13
Nodes (4): CalibratedFSMDetector, optimize_fsm_parameters(), TestShotModelsFlow, TestCalibratedFSMDetector

### Community 28 - "2. Work Breakdown & Task Sequence"
Cohesion: 0.20
Nodes (9): 1. Executive Summary & Architecture Principles, 2. Work Breakdown & Task Sequence, 3. Acceptance Criteria, Phase 4 — Personal Shot Lab & Evidence-Gated Coaching, Task 1: SQLite Persistence & Provenance Schema (`shot_lab_db.py`), Task 3: Post-Session Shot Review & Explicit Per-Shot Admission Tool (`review_shots.py`), Task 4: Personal Baseline & Descriptive Association Engine (`baseline_engine.py`), Task 5: Mechanics-Based Hierarchical One-Cue Remediation & Follow-Up Engine (`coach_engine.py`) (+1 more)

### Community 29 - "Project Positioning and Technical Notes"
Cohesion: 0.29
Nodes (6): Claims and evidence boundaries, Current assessment, Product landscape, Project Positioning and Technical Notes, Recommended differentiation and next work, Reference reading

### Community 30 - "Phase 1 — Core Capture and Vision"
Cohesion: 0.33
Nodes (5): Closeout evidence to preserve, Deferred, Delivered scope, Objective, Phase 1 — Core Capture and Vision

### Community 31 - "Phase 2 — Shot Analysis Foundations"
Cohesion: 0.33
Nodes (5): Closeout evidence to preserve, Deferred, Delivered scope, Objective, Phase 2 — Shot Analysis Foundations

### Community 32 - "kt"
Cohesion: 0.13
Nodes (4): hs(), kt, Pt, rt()

### Community 33 - "ShotPhaseDetector"
Cohesion: 0.18
Nodes (5): How the workflow runs today, Locked implementation choices, ShotPhaseDetector, analyze_video(), _persist_shot_proposal()

### Community 34 - "renderResults"
Cohesion: 0.36
Nodes (21): api(), el(), frameOf(), jsonBody(), loadPhoneCard(), mmss(), renderPlan(), renderResults() (+13 more)

### Community 37 - "test_shot_coach.py"
Cohesion: 0.15
Nodes (5): fake_analysis(), FindingTests, metric(), PlanAndInjuryTests, session()

### Community 38 - "Work Division & Project Execution Plan"
Cohesion: 0.11
Nodes (17): 1. `analyzer.py` (Kinematics & State Machine), 1. `pose_engine.py` & `ball_tracker.py` (Refactoring & Decoupling), 1. `report_generator.py` (Automated PDF Report Exporter), 1. Team Allocation & Stream Overview, 2. `dashboard/app.py` (Streamlit Web Dashboard), 2. `feedback_voice.py` (Offline Voice Feedback Engine), 2. `hand_engine.py` (MediaPipe Hands Integration), 2. Technical Specifications by Stream (+9 more)

### Community 40 - "Work packages"
Cohesion: 0.17
Nodes (11): 08-01 — Local upload-to-summary vertical slice, 08-02 — Replay, pose overlay, and human review with provenance, 08-03 — Validity-gated biomechanics and one-cue coaching, 08-04 — Review-approved history, comparable-session trends, practice goals, and drill follow-up, 08-05 — Optional grounded AI explanation and shareable report, 08-06 — Player UI redesign and reliability fixes, 08-07 — AI shooting coach report, phone access, and review tools, Phase 8 manual acceptance gates (+3 more)

### Community 42 - "M"
Cohesion: 0.15
Nodes (18): 1. Executive Summary & Current State Audit, 2.2 Explicit Status & Missing-Data Schema, 2. Core Architecture: "Hand-in-Hand" Timeline Synchronization, Current Reality Check, 2.1 Configurable Wrist-Height & Vertical Velocity Gates, 2.2 Kinetic Dip-to-Rise Ordering & Plausible Phase Durations, 2.3 Ball Tracking Coordination, Synchronization & Honest Degradation, 2.4 Strict Human-Gated Baseline Inclusion (+10 more)

### Community 43 - "history_service.py"
Cohesion: 0.24
Nodes (9): build_session_insights(), _cue_evidence(), _metric_summary(), _numeric_values(), build_player_history(), _eligible(), _session_record(), _summary() (+1 more)

### Community 44 - "SessionRecorder"
Cohesion: 0.13
Nodes (3): 2.1 Master Authority: Pose Owns the Shot Lifecycle, Phase 2 — Shot analysis foundations, SessionRecorder

### Community 45 - "evaluate_ball_tracking.py"
Cohesion: 0.19
Nodes (5): compute_file_sha256(), evaluate_dataset_object_detection(), evaluate_video_ball_tracking(), run_full_evaluation(), TestEvaluateBallTracking

### Community 46 - "DatasetValidator"
Cohesion: 0.17
Nodes (4): DatasetValidator, main(), print_validation_report(), TestDatasetValidator

### Community 47 - "answer_grounded_question"
Cohesion: 0.29
Nodes (3): answer_grounded_question(), CoachUnavailable, summarize_findings_for_llm()

### Community 48 - "shot_sequence"
Cohesion: 0.22
Nodes (6): make_cache(), shot_row(), shot_sequence(), analyse(), ConfidenceAndMissingDataTests, ViewAndQualityTests

### Community 49 - "3. Remediation Plan"
Cohesion: 0.13
Nodes (14): 1. Executive Summary & Verdict, 3. Remediation Plan, 4. Remediation Verification Checklist, 5. Post-Remediation Verification & Final Scorecard, Audit Scorecard, Final Audit Status, Key Takeaways:, Phase 6 Evaluation Audit Review (EVAL-REVIEW.md) (+6 more)

### Community 51 - "Phase 3 Mid-Phase Plan — Dataset-Based Testing"
Cohesion: 0.20
Nodes (10): Dataset roles, Goal, Phase 3 Mid-Phase Plan — Dataset-Based Testing, Recommended execution order, References checked, Task 1 — Inspect and qualify candidate data, Task 2 — Public camera-pose & kinematics checks, Task 3 — Target-workflow shooting pilot (+2 more)

### Community 52 - "1. Accomplishments & Deliverables"
Cohesion: 0.25
Nodes (7): 1. Accomplishments & Deliverables, 2. Test Verification Summary, 3. Knowledge Graph & Project Sync, B. Automated Dataset QA & Integrity Validator (`validate_dataset.py`), C. Manifest-Driven Dataset Exporter (`export_dataset.py`), E. End-to-End Integration Flow (`test_annotation_lab_flow.py`), Phase 5 Execution Summary — Developer Model Lab and Annotation Dataset

### Community 53 - "ball_tracker.py"
Cohesion: 0.14
Nodes (9): arc_peak(), ball_under_rim(), box_center(), box_to_point_distance(), calculate_entry_angle(), last_valid_box(), point_distance(), release_angle_deg() (+1 more)

### Community 54 - "README.md"
Cohesion: 0.25
Nodes (3): Agent Rules, Data and Implementation Integrity, Repository Architecture & Conventions

### Community 55 - ".update"
Cohesion: 0.24
Nodes (3): _ball_above_elbow(), _shooting_elbow_y(), _wrist_pixels()

### Community 57 - "test_shooting_analysis.py"
Cohesion: 0.21
Nodes (4): front_view_pose(), _rotate(), side_view_pose(), GeometryTests

### Community 58 - "evaluate_benchmark"
Cohesion: 0.15
Nodes (7): evaluate_benchmark(), evaluate_detector_on_kinematics(), main(), match_events(), run_pipeline_on_clip(), Step 6: Feed Real Landmarks to Heuristic Baseline, TestEvaluateShotModels

### Community 59 - "Phase 8 Implementation Summary"
Cohesion: 0.29
Nodes (6): 08-06 update (2026-10-17): UI redesign and reliability, 08-07 update (2026-10-25): AI shooting coach report and phone access, Delivered, Phase 8 Implementation Summary, User acceptance still required, Verification performed by the coding agent

### Community 60 - "DatasetExporter"
Cohesion: 0.16
Nodes (4): compute_file_sha256(), DatasetExporter, main(), TestDatasetExporter

### Community 62 - "Phase 8 — Final user-facing video analysis app"
Cohesion: 0.33
Nodes (6): Candidate architecture (implementation choice remains evidence-driven), Coding-agent work, Delivery order and feature gates, Manual developer work, Phase 8 — Final user-facing video analysis app, Player journey

### Community 65 - "sessionItem"
Cohesion: 0.23
Nodes (14): clearReview(), dateParts(), formatDate(), openSession(), pollJob(), prepareJobPanel(), sessionItem(), setBadge() (+6 more)

### Community 66 - "MLSequenceDetector"
Cohesion: 0.11
Nodes (3): D. Lightweight ML Sequence Classifier & Proposal Generator (`shot_detector_ml.py`), MLSequenceDetector, TestMLSequenceDetector

### Community 67 - "Manual Verification and Run Commands"
Cohesion: 0.11
Nodes (18): 11. Demo and maintenance commands — use care, 12. Scratch scripts and reusable modules, 13. Phase 7: Ball, Rim & Trajectory Tracking and Comparative Pose Benchmarking, 14. Phase 8: Local player app, evidence-gated coaching, history, and reports, 15. 08-07: AI shooting coach report, phone access over Wi-Fi, and review tools, 1. Setup and model assets, 4. Annotation launchers, 5. Inject/synchronize ground-truth annotations (+10 more)

### Community 68 - "TestVideoAnalysisService"
Cohesion: 0.11
Nodes (5): find_ffmpeg(), make_browser_replay(), probe_video(), _generate_test_clip(), TestVideoAnalysisService

### Community 69 - "Basketball Biomechanics Metric Dictionary"
Cohesion: 0.15
Nodes (12): 1. Landmark Index Reference (MediaPipe BlazePose 33 Keypoints), 2. Joint Angle Definitions & Formulas, 3. Kinetic Chain Sequencing & Angular Velocities, 4. Missing Data & Temporal Interpolation, 5. Personal Shot Lab Statistical Semantics & Notation, Basketball Biomechanics Metric Dictionary, Continuous Metric Distribution ($\bar{x} \pm s$), Direction-Aware Velocity Definitions ($d\theta/dt$) (+4 more)

### Community 70 - "CoachEngine"
Cohesion: 0.11
Nodes (3): CoachEngine, _mean_and_std(), TestCoachEngine

### Community 71 - "motionOn"
Cohesion: 0.21
Nodes (12): animateReport(), confirmDialog(), enter(), motionOn(), moveNavIndicator(), moveSegmentThumb(), playHero(), pop() (+4 more)

### Community 72 - "BenchmarkEvaluator"
Cohesion: 0.12
Nodes (4): BenchmarkEvaluator, Completed Audit Fixes in Phase 3, interpolate_kinematic_series(), KineticChainAnalyzer

### Community 73 - "run_all_public_dataset_evaluations"
Cohesion: 0.25
Nodes (5): evaluate_epfl_camerapose_dataset(), evaluate_shot_dataset_qualification(), evaluate_spl_biomechanics_compatibility(), load_json_permissive(), run_all_public_dataset_evaluations()

### Community 75 - "Phase 7 — Ball, Rim, and Trajectory Tracking: Context & Decisions"
Cohesion: 0.20
Nodes (9): 1. Phase Objective & Boundary, 3.1 Model Weights & Class Mapping (Decision 1: Dynamic Best.pt), 3.2 Evidence Architecture (Decision 2: Strict Advisory Separation), 3.3 Pose Backend Experiment (Decision 3: Dedicated Offline Comparative Benchmark), 3.4 Verification & Reporting (Decision 4: Dual-Track Benchmark), 3. Locked Decisions & Design Contracts, 4. Verification & Testing Contracts, 5. Next Steps (+1 more)

### Community 76 - ".train"
Cohesion: 0.08
Nodes (33): 1. Phase Objective & Boundary, 2.1 Manual Developer Work (Human-in-the-Loop), 2.2 Coding-Agent Work (Software & Tooling), 2. Division of Labor, 4. Data Integrity & AGENTS.md Governance Rules, 5. Acceptance Checks & QA Verification, Phase 5 — Developer Model Lab and Annotation Dataset: Context & Decisions, 1. Phase Objective & Boundary (+25 more)

### Community 77 - "BaselineEngine"
Cohesion: 0.11
Nodes (4): seed_database(), BaselineEngine, _mean_and_std(), TestBaselineEngine

### Community 78 - "Model Weights & Assets Manifest"
Cohesion: 0.20
Nodes (9): 1. Active Phase 7 Production Checkpoint, 2. Experimental Pose Comparison Model, 3. Alternative & Reference Checkpoints, 4. Compliance and Licensing Summary, Model Weights & Assets Manifest, `models/ballRim.pt`, `models/best.pt`, `models/bestYT.pt` (+1 more)

### Community 79 - "zn"
Cohesion: 0.13
Nodes (5): bs(), l, Rs(), ws(), zn

### Community 81 - "interactive_review_loop"
Cohesion: 0.36
Nodes (4): interactive_review_loop(), main(), print_shot_detail(), print_shot_table()

### Community 82 - "1. Accomplishments & Deliverables"
Cohesion: 0.20
Nodes (9): 1. Accomplishments & Deliverables, 3. Test Suite Verification, 4. Phase Exit Verdict, A. Split Synchronization & Custom Allocation (`sync_split_annotations.py`, `clip_splits.json`), B. Biomechanical Kinematic Feature Extraction Pipeline (`shot_feature_extractor.py`), C. Calibrated Kinematic FSM Baseline (`calibrated_fsm.py`), E. Unified Model Benchmark Harness & Provenance Report (`evaluate_shot_models.py`), F. Unified CLI Integration & Flow Tests (`batch_ingest_clips.py`, `test_shot_models_flow.py`) (+1 more)

### Community 83 - "AnnotationLab"
Cohesion: 0.14
Nodes (3): TestAnnotationLabFlow, AnnotationLab, main()

### Community 84 - "ms"
Cohesion: 0.14
Nodes (16): 2. Live camera and saved-video analysis, 3. Developer Model Lab: annotate a video, Task 2: Live In-Session Outcome Hotkeys & HUD Overlay (`main.py`), 3.1 Scrubber UI Architecture (Decision 1: OpenCV HighGUI), 3.2 Hard-Negative Action Taxonomy (Decision 2: Comprehensive 8 Classes), 3.3 Dual-Lane Timeline & Proposal Workflow (Decision 3: Separate Cyan/Amber Lanes), 3.4 Data Persistence & Manifest Schema (Decision 4: Extended SQLite & JSON Export), 3. Locked Decisions & Design Contracts (+8 more)

### Community 85 - "app/main.py"
Cohesion: 0.31
Nodes (8): build_parser(), draw_pose(), main(), maybe_ball_tracker(), maybe_hand_engine(), maybe_pro_comparator(), run(), shooting_side()

### Community 88 - "loadPlayerHistory"
Cohesion: 0.22
Nodes (10): countUp(), describeContext(), drawChartOnView(), fmt(), goalRing(), iconEl(), loadPlayerHistory(), renderHistoryCharts() (+2 more)

### Community 89 - "Workflow: Developer Onboarding"
Cohesion: 0.22
Nodes (8): A. Live / Video Desktop HUD, B. Local Web Application, C. Developer Annotation Lab, Step 1: Environment Setup, Step 2: Verify Pre-bundled Assets, Step 3: Run the Test Suite, Step 4: Run Entry Points, Workflow: Developer Onboarding

### Community 90 - "Phase 3 — Ball Tracking Integration & Validation Plan"
Cohesion: 0.20
Nodes (8): 3. Implementation Plan: Phased Execution, 4. Acceptance Criteria, Phase 3 — Ball Tracking Integration & Validation Plan, Phase 3B — Real-Video Ball Coverage & Alignment Evaluation (Phase 3 Gate), Phase 3C — Custom Rim Model & Automated Outcome Qualification (Phase 6 Backlog), 1. Phase Objective, 3. Scope Fences & Execution Order, Phase 3 — Measurement Integrity & Real-Video Validation: Context & Locked Decisions

### Community 92 - "EVAL-REVIEW — Phase 8: User-Facing App"
Cohesion: 0.20
Nodes (9): Critical Gaps, Dimension Coverage, EVAL-REVIEW — Phase 8: User-Facing App, Files Found, Infrastructure Audit, Must fix before production:, Nice to have:, Remediation Plan (+1 more)

### Community 95 - "Real-World & Public Dataset Manifest for Basketball Shot Analysis"
Cohesion: 0.29
Nodes (6): 1. Candidate Dataset Qualification Matrix, 2.1 EPFL SportCenter Camera-Pose Schema (`clones/sportcenter_camerapose_dataset`), 2. Dataset Schemas & Label Availabilities, 3. Project Single-Player Pilot Clips Manifest, 4. Evaluation Separation Guarantees, Real-World & Public Dataset Manifest for Basketball Shot Analysis

### Community 96 - "08-07 Audit — AI Shooting Coach brief vs. current implementation"
Cohesion: 0.33
Nodes (6): 08-07 Audit — AI Shooting Coach brief vs. current implementation, Decisions, Gaps against the brief, Resolution (2026-10-25), Things that are honest already and must stay that way, What works (verified 2026-10-17, re-checked today)

### Community 100 - "Real-Video Dataset Collection & Annotation Protocol"
Cohesion: 0.40
Nodes (4): 1. Video Recording Setup Guidelines, 2. Ground-Truth Annotation Schema (`annotations.json`), 3. Evaluation Metrics & Error Quantification, Real-Video Dataset Collection & Annotation Protocol

### Community 101 - "ParabolaFit"
Cohesion: 0.15
Nodes (4): fit_parabola(), ParabolaFit, sample_parabola(), TestBallGeometry

### Community 102 - "json"
Cohesion: 0.21
Nodes (4): evaluate_pose_backends(), load_yolo_pose(), run_pose_comparison_on_clip(), TestPoseBackendComparison

### Community 103 - "Codebase Structure & Conventions"
Cohesion: 0.50
Nodes (3): Codebase Structure & Conventions, Directory Layout, Rules for Code Changes

### Community 105 - "2. Locked Architecture & Implementation Decisions"
Cohesion: 0.17
Nodes (11): 1. Phase Objective, 2.1 Shot Outcome Labeling, Quarantine & Review Queue (Explicit Per-Shot Review), 2.2 Cue Prioritization & Remediation Engine (Mechanics-Based Gating), 2.3 Shot-Style Differentiation (`jump_shot` vs `set_shot`), 2.4 Follow-Up Comparison Architecture (Observational, No Combined Score), 2.5 Persistence & Storage Engine (`shot_lab.db`), 2.6 Evidence Framing & Ground Truth Boundaries, 2. Locked Architecture & Implementation Decisions (+3 more)

### Community 106 - "compute_all_angles"
Cohesion: 0.22
Nodes (7): evaluate_video_file(), detect_proposals_for_clip(), compute_all_angles(), calc_2d(), calc_3d(), pt_2d(), get_angle_3d()

### Community 122 - "Phase 3 Work Plan — EPFL SportCenter Camera Pose & Court Geometry Evaluation"
Cohesion: 0.20
Nodes (9): 1. Context & Dataset Qualification Audit, 2.1 Court Grid Projection & FOV Coverage, 2.2 Planar Homography vs. Distorted Camera Projection Reprojection Check, 2. Mathematical Definition of Supported Checks, 3. Implementation Tasks, 4. Acceptance Criteria, Phase 3 Work Plan — EPFL SportCenter Camera Pose & Court Geometry Evaluation, Task 1: Real Dataset Loader & Evaluator (`evaluate_public_datasets.py`) (+1 more)

### Community 126 - "2. Work Breakdown & Task Sequence"
Cohesion: 0.20
Nodes (9): 1. Executive Summary & Architecture Principles, 2. Work Breakdown & Task Sequence, 3. Acceptance Gates for Phase 5 Completion, Phase 5 — Developer Model Lab and Annotation Dataset, Task 1: Extended Annotation Schema & Persistence (`shot_lab_db.py`), Task 2: Automated Dataset QA & Integrity Validator (`validate_dataset.py`), Task 3: Dataset Exporter & Manifest Generator (`export_dataset.py`), Task 4: Interactive Video Scrubber & Annotation Lab (`annotation_lab.py`) (+1 more)

### Community 127 - "Work order"
Cohesion: 0.20
Nodes (9): 1. Coordinate and metric audit, 2. Confidence and missing-data behavior, 3. Benchmark correctness, 4. Ball and trajectory reliability, 5. Review release, Active Execution Plan — Phase 3, Follow-on, Verification policy (+1 more)

### Community 128 - "h"
Cohesion: 0.40
Nodes (10): drillList(), evidenceList(), findingCard(), h(), j(), K(), render(), section() (+2 more)

### Community 129 - "test_single_clip"
Cohesion: 0.28
Nodes (3): classify_clip_metadata(), run_raw_clips_suite(), test_single_clip()

### Community 130 - "Phase 3 — Measurement Integrity and Real-Video Validation"
Cohesion: 0.29
Nodes (5): Deliverables, Goal, Out of scope, Phase 3 — Measurement Integrity and Real-Video Validation, Risks and mitigations

### Community 131 - "Plan"
Cohesion: 0.29
Nodes (7): Plan, Task 2 — Confidence and temporal integrity, Task 3 — Repair synthetic evaluator semantics, Task 4 — Real-video annotation coverage and configurable shot-event gating, Task 5 — Full-length real-video evaluation and stratified reporting, Task 6 — Ball trajectory synchronization & honest degradation, Task 7 — Documentation and phase closeout

### Community 132 - "2. Work Breakdown & Task Sequence"
Cohesion: 0.29
Nodes (7): 2. Work Breakdown & Task Sequence, Task 1: Clip Ingestion & Weights Manifest, Task 3: Trajectory Fitting, Geometry & Physics (`ball_geometry.py`), Task 4: Advisory Database Schema v4 & Session Pipeline Integration, Task 5: Offline Pose Backend Comparative Experiment (`evaluate_pose_backends.py`), Task 6: Unified Ball/Rim Evaluation Harness & Audit Report (`evaluate_ball_tracking.py`), Task 7: Manual Verification Index & Verification Loop

### Community 133 - "2. In-Depth Audit Findings"
Cohesion: 0.33
Nodes (6): 2. In-Depth Audit Findings, Finding 1: Hardcoded Synthetic Feature Vectors in Production Training Pipeline (CRITICAL), Finding 2: Video Truncation at 300 Frames Creating Artificial False Negatives (CRITICAL), Finding 3: Ground-Truth Shot Count Mismatch & Database Clip Aliasing (CRITICAL), Finding 4: Dataset Manifest Provenance Corruption & Physical Train/Test Leakage (CRITICAL), Finding 5: Flawed Baseline Comparison Adapter

### Community 134 - "Running the Applications"
Cohesion: 0.33
Nodes (6): 1. Quickstart & Developer Onboarding, Desktop HUD & Live Pose Analysis, Developer Annotation Lab, Local Web Application (Recommended), Quick Setup, Running the Applications

### Community 136 - "Phase 7 — Ball/rim tracking and outcome evidence"
Cohesion: 0.67
Nodes (3): Coding-agent work, Manual developer work, Phase 7 — Ball/rim tracking and outcome evidence

## Knowledge Gaps
- **342 isolated node(s):** `basketball-shot-lab`, `LABELS`, `PHASES`, `form`, `fileInput` (+337 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 867 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **45 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ShotLabDB` connect `ShotLabDB` to `shot_coach.py`, `app/web_app.py`, `BallTracker`, `.upsert_player`, `os`, `AppHandler`, `batch_ingest_clips.py`, `WebAppApiTest`, `CalibratedFSMDetector`, `ShotPhaseDetector`, `shot_lab_db.py`, `pathlib`, `M`, `history_service.py`, `DatasetValidator`, `shot_sequence`, `evaluate_benchmark`, `DatasetExporter`, `TestShotLabFlow`, `CoachEngine`, `BaselineEngine`, `.init_db`, `interactive_review_loop`, `AnnotationLab`, `app/main.py`, `ReportServiceTest`, `TestShotLabDB`, `TestAnnotationDB`, `2. Work Breakdown & Task Sequence`?**
  _High betweenness centrality (0.246) - this node is a cross-community bridge._
- **Why does `ShotPhaseDetector` connect `ShotPhaseDetector` to `test_single_clip`, `evaluate_clip`, `Plan`, `2. Work Breakdown & Task Sequence`, `Phase 3 — Ball Tracking Integration & Validation Plan`, `2. In-Depth Audit Findings`, `BenchmarkEvaluator`, `compute_all_angles`, `M`, `SessionRecorder`, `.train`, `os`, `1. Accomplishments & Deliverables`, `AnnotationLab`, `app/main.py`, `numpy`, `evaluate_benchmark`, `EVAL-REVIEW — Phase 8: User-Facing App`?**
  _High betweenness centrality (0.129) - this node is a cross-community bridge._
- **Why does `M()` connect `M` to `h`, `Plan`, `2. Locked Architecture & Implementation Decisions`, `report.js`, `ms`, `Key Deliverables & Architecture Implemented`?**
  _High betweenness centrality (0.102) - this node is a cross-community bridge._
- **Are the 36 inferred relationships involving `ShotLabDB` (e.g. with `evaluate_benchmark()` and `DatasetValidator`) actually correct?**
  _`ShotLabDB` has 36 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `AnnotationLab` (e.g. with `1. Executive Summary & Architectural Decisions` and `TestAnnotationLabFlow`) actually correct?**
  _`AnnotationLab` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 25 inferred relationships involving `ShotPhaseDetector` (e.g. with `evaluate_clip()` and `BenchmarkEvaluator`) actually correct?**
  _`ShotPhaseDetector` has 25 INFERRED edges - model-reasoned connections that need verification._
- **What connects `basketball-shot-lab`, `LABELS`, `PHASES` to the rest of the system?**
  _342 weakly-connected nodes found - possible documentation gaps or missing edges._