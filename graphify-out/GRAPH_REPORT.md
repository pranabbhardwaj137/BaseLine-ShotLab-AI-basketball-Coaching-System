# Graph Report - basketball_proj  (2026-10-27)

## Corpus Check
- 141 files · ~155,089 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 12 file(s) not represented in the graph (top: .jsonl 3, .pt 3, .task 2)

## Summary
- 2060 nodes · 3988 edges · 132 communities (85 shown, 47 thin omitted)
- Extraction: 92% EXTRACTED · 8% INFERRED · 0% AMBIGUOUS · INFERRED: 300 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `d55ff356`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- AnnotationLab
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
- os
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
- Ue
- WebAppApiTest
- Key Deliverables & Architecture Implemented
- as
- A. Extended SQLite Persistence Schema v3 (`shot_lab_db.py`)
- CalibratedFSMDetector
- 2. Work Breakdown & Task Sequence
- Project Positioning and Technical Notes
- Phase 1 — Core Capture and Vision
- Phase 2 — Shot Analysis Foundations
- kt
- _extract_dip_frame
- renderResults
- Ps
- ShotFeatureExtractor
- shot_sequence
- Work Division & Project Execution Plan
- pathlib
- Work packages
- JobStore
- M
- coaching_service.py
- ShotPhaseDetector
- evaluate_ball_tracking.py
- DatasetValidator
- answer_grounded_question
- LiveCameraEngine
- 2. In-Depth Audit Findings
- ProComparator
- Phase 3 Mid-Phase Plan — Dataset-Based Testing
- 1. Accomplishments & Deliverables
- ball_tracker.py
- README.md
- ._do_post
- Ye
- evaluate_benchmark
- Phase 8 Implementation Summary
- DatasetExporter
- HandEngine
- Phase 8 — Final user-facing video analysis app
- CoachEngine
- Phase 6 — Shot-Event Model and Verification: Context & Decisions
- sessionItem
- MLSequenceDetector
- Manual Verification and Run Commands
- TestVideoAnalysisService
- Basketball Biomechanics Metric Dictionary
- TestCoachEngine
- motionOn
- BenchmarkEvaluator
- run_all_public_dataset_evaluations
- LanAccessTest
- Phase 7 — Ball, Rim, and Trajectory Tracking: Context & Decisions
- .train
- TestBaselineEngine
- Model Weights & Assets Manifest
- zn
- interactive_review_loop
- 1. Accomplishments & Deliverables
- .evaluate_follow_up_set
- 3. Locked Decisions & Design Contracts
- app/main.py
- ReportServiceTest
- TestShotLabDB
- _run_analysis
- Workflow: Developer Onboarding
- Phase 3 — Ball Tracking Integration & Validation Plan
- TestAnnotationDB
- prepare_video_for_analysis
- match_events
- .compute_baseline
- Real-World & Public Dataset Manifest for Basketball Shot Analysis
- 08-07 Audit — AI Shooting Coach brief vs. current implementation
- Phase 5 — Developer Model Lab and Annotation Dataset: Context & Decisions
- evaluate_clip
- 3. Remediation Plan
- Real-Video Dataset Collection & Annotation Protocol
- .export
- evaluate_pose_backends.py
- Codebase Structure & Conventions
- processLiveFrame
- 2. Locked Architecture & Implementation Decisions
- Phase 7 — Ball, Rim, and Trajectory Tracking: Implementation Plan
- rules/graphify.md
- workflows/graphify.md
- Phase 5 — Developer Model Lab and Annotation Dataset
- basketball-shot-lab
- 2. Work Breakdown & Task Sequence
- test_single_clip
- Plan
- 2. Work Breakdown & Task Sequence
- Running the Applications
- Phase 7 — Ball/rim tracking and outcome evidence

## God Nodes (most connected - your core abstractions)
1. `ShotLabDB` - 115 edges
2. `AnnotationLab` - 41 edges
3. `ShotPhaseDetector` - 38 edges
4. `AppHandler` - 30 edges
5. `PoseEngine` - 29 edges
6. `BallTracker` - 29 edges
7. `MLSequenceDetector` - 26 edges
8. `shot_sequence()` - 24 edges
9. `PoseSeries` - 23 edges
10. `analyze_attempt()` - 22 edges

## Surprising Connections (you probably didn't know these)
- `08-03 — Validity-gated biomechanics and one-cue coaching` --references--> `CoachEngine`  [INFERRED]
  .planning/phases/08-user-facing-app/08-PLAN.md → src/basketball/coaching/coach_engine.py
- `2.1 Architectural Components` --references--> `pt_3d()`  [INFERRED]
  .planning/reports/MILESTONE_SUMMARY-v1.0.md → src/basketball/core/analyzer.py
- `4. Missing Data & Temporal Interpolation` --references--> `KineticChainAnalyzer`  [INFERRED]
  docs/reference/METRIC_DICTIONARY.md → src/basketball/core/analyzer.py
- `2.1 Configurable Wrist-Height & Vertical Velocity Gates` --references--> `ShotPhaseDetector`  [INFERRED]
  .planning/phases/03-measurement-validation/03-CONTEXT.md → src/basketball/core/analyzer.py
- `3. Scope Fences & Execution Order` --references--> `ShotPhaseDetector`  [INFERRED]
  .planning/phases/03-measurement-validation/03-CONTEXT.md → src/basketball/core/analyzer.py

## Import Cycles
- None detected.

## Communities (132 total, 47 thin omitted)

### Community 0 - "AnnotationLab"
Cohesion: 0.05
Nodes (3): AnnotationLab, on_trackbar(), main()

### Community 1 - "Phase 7: Ball, Rim, and Trajectory Tracking — Execution Summary"
Cohesion: 0.20
Nodes (5): 1. Overview & Objectives Delivered, 2. Key Metrics & Empirical Results, 3. Artifacts Created & Updated, 4. Verification & Testing, Phase 7: Ball, Rim, and Trajectory Tracking — Execution Summary

### Community 2 - "app.js"
Cohesion: 0.03
Nodes (72): applyTheme(), ARM, cameraOverlay, cameraPreview, cameraStartButton, cameraStatus, cameraStopButton, cancelButton (+64 more)

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
Cohesion: 0.10
Nodes (4): download_models(), reporthook(), build_session_report(), _video_paths()

### Community 7 - "BallTracker"
Cohesion: 0.07
Nodes (10): 3. Implementation Plan: Phased Execution, Phase 3A — Unified Timeline & State Machine Refactoring (Immediate), Phase 3B — Real-Video Ball Coverage & Alignment Evaluation (Phase 3 Gate), Phase 3C — Custom Rim Model & Automated Outcome Qualification (Phase 6 Backlog), Task 2: Dynamic Ball & Rim YOLO Tracker (`ball_tracker.py`), Task 4: Advisory Database Schema v4 & Session Pipeline Integration, BallTracker, load_yolo() (+2 more)

### Community 8 - "Milestone Summary — v1.0: Reliable, Evidence-Backed Personal Shot Analysis"
Cohesion: 0.09
Nodes (21): 1.1 Product Vision, 1.2 Core Capabilities Delivered in Milestone v1.0, 1. Executive Overview, 2.1 Architectural Components, 2. System Architecture, 3. Phase Summary & Progression, 5. Requirements Traceability Matrix, 6.1 Real-World Detection Performance & Tuning Needs (+13 more)

### Community 9 - "report.js"
Cohesion: 0.09
Nodes (33): 2. Live camera and saved-video analysis, Task 2: Live In-Session Outcome Hotkeys & HUD Overlay (`main.py`), an(), be(), d(), drillList(), ei(), evidenceList() (+25 more)

### Community 10 - "Ln"
Cohesion: 0.11
Nodes (4): c(), cn, He(), Ln

### Community 13 - "batch_ingest_clips.py"
Cohesion: 0.11
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

### Community 22 - "Ue"
Cohesion: 0.20
Nodes (4): Ie(), rn, tn(), Ue()

### Community 23 - "WebAppApiTest"
Cohesion: 0.13
Nodes (4): FrontendUiTest, WebAppApiTest, WebAppCoachFeaturesTest, _write_synthetic_clip()

### Community 24 - "Key Deliverables & Architecture Implemented"
Cohesion: 0.18
Nodes (10): 1. SQLite Persistence & Versioned Schema (`shot_lab_db.py`), 2. Live Outcome Tagging & Boundary Ingestion (`main.py`), 3. Post-Session Review Queue & Quarantine Protection (`review_shots.py`), 4. Personal Baseline Engine (`baseline_engine.py`), 5. Hierarchical One-Cue Remediation Engine (`coach_engine.py`), Key Deliverables & Architecture Implemented, Milestone Status: COMPLETE, Operational CLI Commands (+2 more)

### Community 25 - "as"
Cohesion: 0.10
Nodes (7): as, bs(), Ts, Vs(), ws(), xs, ys()

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

### Community 34 - "renderResults"
Cohesion: 0.33
Nodes (22): api(), el(), frameOf(), frameOrDash(), jsonBody(), loadPhoneCard(), mmss(), renderPlan() (+14 more)

### Community 35 - "Ps"
Cohesion: 0.16
Nodes (13): at(), ct(), et(), it(), li(), lt(), nt(), oi() (+5 more)

### Community 37 - "shot_sequence"
Cohesion: 0.05
Nodes (18): front_view_pose(), make_cache(), _rotate(), shot_row(), shot_sequence(), side_view_pose(), DipBiomechanicalAnalysisTests, analyse() (+10 more)

### Community 38 - "Work Division & Project Execution Plan"
Cohesion: 0.11
Nodes (17): 1. `analyzer.py` (Kinematics & State Machine), 1. `pose_engine.py` & `ball_tracker.py` (Refactoring & Decoupling), 1. `report_generator.py` (Automated PDF Report Exporter), 1. Team Allocation & Stream Overview, 2. `dashboard/app.py` (Streamlit Web Dashboard), 2. `feedback_voice.py` (Offline Voice Feedback Engine), 2. `hand_engine.py` (MediaPipe Hands Integration), 2. Technical Specifications by Stream (+9 more)

### Community 40 - "Work packages"
Cohesion: 0.17
Nodes (11): 08-01 — Local upload-to-summary vertical slice, 08-02 — Replay, pose overlay, and human review with provenance, 08-03 — Validity-gated biomechanics and one-cue coaching, 08-04 — Review-approved history, comparable-session trends, practice goals, and drill follow-up, 08-05 — Optional grounded AI explanation and shareable report, 08-06 — Player UI redesign and reliability fixes, 08-07 — AI shooting coach report, phone access, and review tools, Phase 8 manual acceptance gates (+3 more)

### Community 41 - "JobStore"
Cohesion: 0.14
Nodes (6): build_parser(), generate_access_code(), JobStore, local_network_addresses(), LocalAppServer, main()

### Community 42 - "M"
Cohesion: 0.20
Nodes (17): 3. Developer Model Lab: annotate a video, 1. Executive Summary & Current State Audit, Current Reality Check, 2.1 Configurable Wrist-Height & Vertical Velocity Gates, 2.2 Kinetic Dip-to-Rise Ordering & Plausible Phase Durations, 2.3 Ball Tracking Coordination, Synchronization & Honest Degradation, 2.4 Strict Human-Gated Baseline Inclusion, 2.5 Full-Length Video Evaluation & Subgroup Metrics (+9 more)

### Community 43 - "coaching_service.py"
Cohesion: 0.22
Nodes (9): build_session_insights(), _cue_evidence(), _metric_summary(), _numeric_values(), build_player_history(), _eligible(), _session_record(), _summary() (+1 more)

### Community 44 - "ShotPhaseDetector"
Cohesion: 0.08
Nodes (9): 2.1 Master Authority: Pose Owns the Shot Lifecycle, How the workflow runs today, Locked implementation choices, Phase 2 — Shot analysis foundations, SessionRecorder, ShotPhaseDetector, analyze_video(), _persist_shot_proposal() (+1 more)

### Community 45 - "evaluate_ball_tracking.py"
Cohesion: 0.19
Nodes (5): compute_file_sha256(), evaluate_dataset_object_detection(), evaluate_video_ball_tracking(), run_full_evaluation(), TestEvaluateBallTracking

### Community 46 - "DatasetValidator"
Cohesion: 0.17
Nodes (4): DatasetValidator, main(), print_validation_report(), TestDatasetValidator

### Community 47 - "answer_grounded_question"
Cohesion: 0.29
Nodes (3): answer_grounded_question(), CoachUnavailable, summarize_findings_for_llm()

### Community 49 - "2. In-Depth Audit Findings"
Cohesion: 0.13
Nodes (14): 1. Executive Summary & Verdict, 2. In-Depth Audit Findings, 4. Remediation Verification Checklist, 5. Post-Remediation Verification & Final Scorecard, Audit Scorecard, Final Audit Status, Finding 1: Hardcoded Synthetic Feature Vectors in Production Training Pipeline (CRITICAL), Finding 2: Video Truncation at 300 Frames Creating Artificial False Negatives (CRITICAL) (+6 more)

### Community 51 - "Phase 3 Mid-Phase Plan — Dataset-Based Testing"
Cohesion: 0.05
Nodes (33): Dataset roles, Goal, Phase 3 Mid-Phase Plan — Dataset-Based Testing, Recommended execution order, References checked, Task 1 — Inspect and qualify candidate data, Task 2 — Public camera-pose & kinematics checks, Task 3 — Target-workflow shooting pilot (+25 more)

### Community 52 - "1. Accomplishments & Deliverables"
Cohesion: 0.25
Nodes (7): 1. Accomplishments & Deliverables, 2. Test Verification Summary, 3. Knowledge Graph & Project Sync, B. Automated Dataset QA & Integrity Validator (`validate_dataset.py`), C. Manifest-Driven Dataset Exporter (`export_dataset.py`), E. End-to-End Integration Flow (`test_annotation_lab_flow.py`), Phase 5 Execution Summary — Developer Model Lab and Annotation Dataset

### Community 53 - "ball_tracker.py"
Cohesion: 0.07
Nodes (16): arc_peak(), ball_under_rim(), box_center(), box_to_point_distance(), calculate_entry_angle(), fit_parabola(), last_valid_box(), ParabolaFit (+8 more)

### Community 54 - "README.md"
Cohesion: 0.25
Nodes (3): Agent Rules, Data and Implementation Integrity, Repository Architecture & Conventions

### Community 58 - "evaluate_benchmark"
Cohesion: 0.32
Nodes (4): evaluate_benchmark(), evaluate_detector_on_kinematics(), main(), run_pipeline_on_clip()

### Community 59 - "Phase 8 Implementation Summary"
Cohesion: 0.29
Nodes (6): 08-06 update (2026-10-17): UI redesign and reliability, 08-07 update (2026-10-25): AI shooting coach report and phone access, Delivered, Phase 8 Implementation Summary, User acceptance still required, Verification performed by the coding agent

### Community 60 - "DatasetExporter"
Cohesion: 0.17
Nodes (4): DatasetExporter, main(), TestAnnotationLabFlow, TestDatasetExporter

### Community 62 - "Phase 8 — Final user-facing video analysis app"
Cohesion: 0.33
Nodes (6): Candidate architecture (implementation choice remains evidence-driven), Coding-agent work, Delivery order and feature gates, Manual developer work, Phase 8 — Final user-facing video analysis app, Player journey

### Community 63 - "CoachEngine"
Cohesion: 0.12
Nodes (4): seed_database(), BaselineEngine, CoachEngine, TestShotLabFlow

### Community 64 - "Phase 6 — Shot-Event Model and Verification: Context & Decisions"
Cohesion: 0.20
Nodes (9): 1. Phase Objective & Boundary, 2.1 Manual Developer Work (Human-in-the-Loop), 2. Division of Labor, 3.1 Model Architecture & Baselines (Decision 1: Two-Tier Strategy), 3.2 Feature Representation & Kinematics (Decision 2: Biomechanical Kinematics), 3.4 Acceptance Thresholds & Integration Gates (Decision 4: Configurable Backend with Guardrail Fallback), 3. Locked Decisions & Design Contracts, 4. Data Integrity & AGENTS.md Governance Rules (+1 more)

### Community 65 - "sessionItem"
Cohesion: 0.24
Nodes (12): clearReview(), confirmDialog(), dateParts(), openSession(), pollJob(), prepareJobPanel(), sessionItem(), setBadge() (+4 more)

### Community 66 - "MLSequenceDetector"
Cohesion: 0.11
Nodes (3): D. Lightweight ML Sequence Classifier & Proposal Generator (`shot_detector_ml.py`), MLSequenceDetector, TestMLSequenceDetector

### Community 67 - "Manual Verification and Run Commands"
Cohesion: 0.11
Nodes (19): 11. Demo and maintenance commands — use care, 12. Scratch scripts and reusable modules, 13. Phase 7: Ball, Rim & Trajectory Tracking and Comparative Pose Benchmarking, 14. Phase 8: Local player app, evidence-gated coaching, history, and reports, 15. 08-07: AI shooting coach report, phone access over Wi-Fi, and review tools, 16. Pranabv1: Live camera ball tracking HUD, automated outcome, and dip-angle verification (Web App), 1. Setup and model assets, 4. Annotation launchers (+11 more)

### Community 69 - "Basketball Biomechanics Metric Dictionary"
Cohesion: 0.15
Nodes (12): 1. Landmark Index Reference (MediaPipe BlazePose 33 Keypoints), 2. Joint Angle Definitions & Formulas, 3. Kinetic Chain Sequencing & Angular Velocities, 4. Missing Data & Temporal Interpolation, 5. Personal Shot Lab Statistical Semantics & Notation, Basketball Biomechanics Metric Dictionary, Continuous Metric Distribution ($\bar{x} \pm s$), Direction-Aware Velocity Definitions ($d\theta/dt$) (+4 more)

### Community 71 - "motionOn"
Cohesion: 0.13
Nodes (24): animateReport(), countUp(), describeContext(), drawChartOnView(), enter(), fmt(), formatDate(), goalRing() (+16 more)

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
Cohesion: 0.14
Nodes (23): 2.1 Manual Developer Work (Human-in-the-Loop), 4. Data Integrity & AGENTS.md Governance Rules, 1. Executive Summary & Architecture Principles, 2.2 Coding-Agent Work (Software & Modeling Plumbing), 3.3 Dataset Readiness & Split Verification (Decision 3: Sync Expert Val & Enforce Test Isolation), 5. Acceptance Checks & QA Verification, 1. Executive Summary & Architectural Decisions, 2. Work Breakdown & Task Sequence (+15 more)

### Community 78 - "Model Weights & Assets Manifest"
Cohesion: 0.20
Nodes (9): 1. Active Phase 7 Production Checkpoint, 2. Experimental Pose Comparison Model, 3. Alternative & Reference Checkpoints, 4. Compliance and Licensing Summary, Model Weights & Assets Manifest, `models/ballRim.pt`, `models/best.pt`, `models/bestYT.pt` (+1 more)

### Community 79 - "zn"
Cohesion: 0.11
Nodes (10): hn(), ks(), l, mn(), Nn(), p(), Rs(), un() (+2 more)

### Community 81 - "interactive_review_loop"
Cohesion: 0.36
Nodes (4): interactive_review_loop(), main(), print_shot_detail(), print_shot_table()

### Community 82 - "1. Accomplishments & Deliverables"
Cohesion: 0.22
Nodes (8): 1. Accomplishments & Deliverables, 3. Test Suite Verification, 4. Phase Exit Verdict, B. Biomechanical Kinematic Feature Extraction Pipeline (`shot_feature_extractor.py`), C. Calibrated Kinematic FSM Baseline (`calibrated_fsm.py`), E. Unified Model Benchmark Harness & Provenance Report (`evaluate_shot_models.py`), F. Unified CLI Integration & Flow Tests (`batch_ingest_clips.py`, `test_shot_models_flow.py`), Phase 6 Execution Summary — Shot-Event Model and Verification

### Community 84 - "3. Locked Decisions & Design Contracts"
Cohesion: 0.40
Nodes (5): 3.1 Scrubber UI Architecture (Decision 1: OpenCV HighGUI), 3.2 Hard-Negative Action Taxonomy (Decision 2: Comprehensive 8 Classes), 3.3 Dual-Lane Timeline & Proposal Workflow (Decision 3: Separate Cyan/Amber Lanes), 3.4 Data Persistence & Manifest Schema (Decision 4: Extended SQLite & JSON Export), 3. Locked Decisions & Design Contracts

### Community 85 - "app/main.py"
Cohesion: 0.14
Nodes (17): evaluate_video_file(), Task 1 — Trace coordinate systems and define metrics, 4. Key Architectural Decisions (ADRs), build_parser(), draw_pose(), main(), maybe_ball_tracker(), maybe_hand_engine() (+9 more)

### Community 88 - "_run_analysis"
Cohesion: 0.25
Nodes (5): _discard_cancelled_session(), _run_analysis(), report(), AnalysisCancelled, make_browser_replay()

### Community 89 - "Workflow: Developer Onboarding"
Cohesion: 0.22
Nodes (8): A. Live / Video Desktop HUD, B. Local Web Application, C. Developer Annotation Lab, Step 1: Environment Setup, Step 2: Verify Pre-bundled Assets, Step 3: Run the Test Suite, Step 4: Run Entry Points, Workflow: Developer Onboarding

### Community 90 - "Phase 3 — Ball Tracking Integration & Validation Plan"
Cohesion: 0.22
Nodes (7): 2.2 Explicit Status & Missing-Data Schema, 2. Core Architecture: "Hand-in-Hand" Timeline Synchronization, 4. Acceptance Criteria, Phase 3 — Ball Tracking Integration & Validation Plan, 1. Phase Objective, 3. Scope Fences & Execution Order, Phase 3 — Measurement Integrity & Real-Video Validation: Context & Locked Decisions

### Community 92 - "prepare_video_for_analysis"
Cohesion: 0.13
Nodes (11): Critical Gaps, Dimension Coverage, EVAL-REVIEW — Phase 8: User-Facing App, Files Found, Infrastructure Audit, Must fix before production:, Nice to have:, Remediation Plan (+3 more)

### Community 95 - "Real-World & Public Dataset Manifest for Basketball Shot Analysis"
Cohesion: 0.29
Nodes (6): 1. Candidate Dataset Qualification Matrix, 2.1 EPFL SportCenter Camera-Pose Schema (`clones/sportcenter_camerapose_dataset`), 2. Dataset Schemas & Label Availabilities, 3. Project Single-Player Pilot Clips Manifest, 4. Evaluation Separation Guarantees, Real-World & Public Dataset Manifest for Basketball Shot Analysis

### Community 96 - "08-07 Audit — AI Shooting Coach brief vs. current implementation"
Cohesion: 0.33
Nodes (6): 08-07 Audit — AI Shooting Coach brief vs. current implementation, Decisions, Gaps against the brief, Resolution (2026-10-25), Things that are honest already and must stay that way, What works (verified 2026-10-17, re-checked today)

### Community 97 - "Phase 5 — Developer Model Lab and Annotation Dataset: Context & Decisions"
Cohesion: 0.33
Nodes (5): 1. Phase Objective & Boundary, 2.2 Coding-Agent Work (Software & Tooling), 2. Division of Labor, 5. Acceptance Checks & QA Verification, Phase 5 — Developer Model Lab and Annotation Dataset: Context & Decisions

### Community 99 - "3. Remediation Plan"
Cohesion: 0.33
Nodes (6): 3. Remediation Plan, Step 1: Fix Split Configuration & Eliminate Clip Aliasing in DB, Step 2: Prevent Test Runner Pollution of `dataset_export/`, Step 3: Implement Real-Video Kinematic Feature Extraction for ML Training, Step 4: Remove Video Truncation & Enforce Frame-Coverage Guards, Step 5: Fix Ground-Truth Accounting & Legacy Intervals

### Community 100 - "Real-Video Dataset Collection & Annotation Protocol"
Cohesion: 0.40
Nodes (4): 1. Video Recording Setup Guidelines, 2. Ground-Truth Annotation Schema (`annotations.json`), 3. Evaluation Metrics & Error Quantification, Real-Video Dataset Collection & Annotation Protocol

### Community 102 - "evaluate_pose_backends.py"
Cohesion: 0.22
Nodes (4): evaluate_pose_backends(), load_yolo_pose(), run_pose_comparison_on_clip(), TestPoseBackendComparison

### Community 103 - "Codebase Structure & Conventions"
Cohesion: 0.50
Nodes (3): Codebase Structure & Conventions, Directory Layout, Rules for Code Changes

### Community 104 - "processLiveFrame"
Cohesion: 0.40
Nodes (5): flashOutcomeBanner(), processLiveFrame(), renderLiveHUD(), scheduleLiveFrame(), startLiveTracking()

### Community 105 - "2. Locked Architecture & Implementation Decisions"
Cohesion: 0.17
Nodes (11): 1. Phase Objective, 2.1 Shot Outcome Labeling, Quarantine & Review Queue (Explicit Per-Shot Review), 2.2 Cue Prioritization & Remediation Engine (Mechanics-Based Gating), 2.3 Shot-Style Differentiation (`jump_shot` vs `set_shot`), 2.4 Follow-Up Comparison Architecture (Observational, No Combined Score), 2.5 Persistence & Storage Engine (`shot_lab.db`), 2.6 Evidence Framing & Ground Truth Boundaries, 2. Locked Architecture & Implementation Decisions (+3 more)

### Community 106 - "Phase 7 — Ball, Rim, and Trajectory Tracking: Implementation Plan"
Cohesion: 0.50
Nodes (3): 1. Executive Summary & Architectural Decisions, 3. Success Criteria & Phase 7 Exit Gate, Phase 7 — Ball, Rim, and Trajectory Tracking: Implementation Plan

### Community 126 - "2. Work Breakdown & Task Sequence"
Cohesion: 0.33
Nodes (6): 2. Work Breakdown & Task Sequence, Task 1: Extended Annotation Schema & Persistence (`shot_lab_db.py`), Task 2: Automated Dataset QA & Integrity Validator (`validate_dataset.py`), Task 3: Dataset Exporter & Manifest Generator (`export_dataset.py`), Task 4: Interactive Video Scrubber & Annotation Lab (`annotation_lab.py`), Task 5: End-to-End Verification Test Suite (`test_annotation_lab_flow.py`)

### Community 129 - "test_single_clip"
Cohesion: 0.28
Nodes (3): classify_clip_metadata(), run_raw_clips_suite(), test_single_clip()

### Community 131 - "Plan"
Cohesion: 0.29
Nodes (7): Plan, Task 2 — Confidence and temporal integrity, Task 3 — Repair synthetic evaluator semantics, Task 4 — Real-video annotation coverage and configurable shot-event gating, Task 5 — Full-length real-video evaluation and stratified reporting, Task 6 — Ball trajectory synchronization & honest degradation, Task 7 — Documentation and phase closeout

### Community 132 - "2. Work Breakdown & Task Sequence"
Cohesion: 0.40
Nodes (5): 2. Work Breakdown & Task Sequence, Task 3: Trajectory Fitting, Geometry & Physics (`ball_geometry.py`), Task 5: Offline Pose Backend Comparative Experiment (`evaluate_pose_backends.py`), Task 6: Unified Ball/Rim Evaluation Harness & Audit Report (`evaluate_ball_tracking.py`), Task 7: Manual Verification Index & Verification Loop

### Community 134 - "Running the Applications"
Cohesion: 0.33
Nodes (6): 1. Quickstart & Developer Onboarding, Desktop HUD & Live Pose Analysis, Developer Annotation Lab, Local Web Application (Recommended), Quick Setup, Running the Applications

### Community 136 - "Phase 7 — Ball/rim tracking and outcome evidence"
Cohesion: 0.67
Nodes (3): Coding-agent work, Manual developer work, Phase 7 — Ball/rim tracking and outcome evidence

## Knowledge Gaps
- **355 isolated node(s):** `basketball-shot-lab`, `LABELS`, `PHASES`, `form`, `fileInput` (+350 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 895 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **47 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ShotLabDB` connect `ShotLabDB` to `AnnotationLab`, `shot_coach.py`, `app/web_app.py`, `BallTracker`, `os`, `AppHandler`, `batch_ingest_clips.py`, `WebAppApiTest`, `A. Extended SQLite Persistence Schema v3 (`shot_lab_db.py`)`, `CalibratedFSMDetector`, `shot_sequence`, `pathlib`, `coaching_service.py`, `ShotPhaseDetector`, `DatasetValidator`, `._do_post`, `evaluate_benchmark`, `DatasetExporter`, `CoachEngine`, `Manual Verification and Run Commands`, `TestCoachEngine`, `TestBaselineEngine`, `.init_db`, `interactive_review_loop`, `.evaluate_follow_up_set`, `app/main.py`, `ReportServiceTest`, `TestShotLabDB`, `_run_analysis`, `Phase 3 — Ball Tracking Integration & Validation Plan`, `TestAnnotationDB`, `2. Work Breakdown & Task Sequence`?**
  _High betweenness centrality (0.233) - this node is a cross-community bridge._
- **Why does `ShotPhaseDetector` connect `ShotPhaseDetector` to `Phase 6 — Shot-Event Model and Verification: Context & Decisions`, `test_single_clip`, `evaluate_clip`, `Plan`, `AnnotationLab`, `Phase 3 — Ball Tracking Integration & Validation Plan`, `BallTracker`, `BenchmarkEvaluator`, `M`, `.train`, `LiveCameraEngine`, `2. In-Depth Audit Findings`, `1. Accomplishments & Deliverables`, `PoseEngine`, `app/main.py`, `numpy`, `evaluate_benchmark`, `prepare_video_for_analysis`?**
  _High betweenness centrality (0.141) - this node is a cross-community bridge._
- **Why does `AnnotationLab` connect `AnnotationLab` to `pathlib`, `os`, `.train`, `ShotPhaseDetector`, `ShotLabDB`, `PoseEngine`, `DatasetExporter`?**
  _High betweenness centrality (0.098) - this node is a cross-community bridge._
- **Are the 37 inferred relationships involving `ShotLabDB` (e.g. with `16. Pranabv1: Live camera ball tracking HUD, automated outcome, and dip-angle verification (Web App)` and `evaluate_benchmark()`) actually correct?**
  _`ShotLabDB` has 37 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `AnnotationLab` (e.g. with `1. Executive Summary & Architectural Decisions` and `TestAnnotationLabFlow`) actually correct?**
  _`AnnotationLab` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 26 inferred relationships involving `ShotPhaseDetector` (e.g. with `evaluate_clip()` and `BenchmarkEvaluator`) actually correct?**
  _`ShotPhaseDetector` has 26 INFERRED edges - model-reasoned connections that need verification._
- **What connects `basketball-shot-lab`, `LABELS`, `PHASES` to the rest of the system?**
  _355 weakly-connected nodes found - possible documentation gaps or missing edges._