# Project Roadmap — Basketball Shot Lab to User App

## Product milestone

**Build a transparent basketball shot-analysis product from a verified data workflow:** developers curate and label video in an internal Model Lab; shot-event and ball/rim models are trained and evaluated on that data; end users later upload or record video and receive evidence-linked analysis, suggestions, and history.

The internal **Developer Model Lab** and final **User App** are separate products with separate goals. The scrubber/annotation tool creates verified training and evaluation data. The User App consumes versioned inference outputs; it is not the place to label the training set.

## Planning language

- **Manual developer work:** collection, licensing, consent, labeling decisions, annotation QA, and acceptance of results. The coding agent cannot invent these inputs or approve its own predictions.
- **Coding-agent work:** software, data schemas, model/evaluation plumbing, reports, interfaces, and reproducible tests using supplied inputs.
- **Joint gate:** evidence the developer reviews before a phase can claim success.
- Synthetic fixtures test software logic only. They are never real-video accuracy results.

## Phase sequence

| Phase | Focus | Status | Exit gate |
|---|---|---|---|
| 1 | Capture and core vision | Implemented prototype | Clean setup and supported input behavior are reproducible. |
| 2 | Shot analysis foundations | Implemented prototype | Metrics and event behavior have defined units, coordinate bases, and limits. |
| 3 | Measurement integrity and real-video evaluation | **Pilot infrastructure exists; accuracy gate remains open** | Labeled coverage, event errors, and subgroup results are sufficient to justify claims; report audit issues are resolved. |
| 4 | Personal Shot Lab and coaching workflow | **Software prototype implemented; coaching effectiveness unvalidated** | Human review, baseline admission, and follow-up behavior are clear and evidence-gated. |
| 5 | Developer Model Lab and annotation dataset | **Completed and verified** | Tooling, persistence, QA validator, manifest exporter, and test suites delivered; ready for developer labeling. |
| 6 | Shot-event model and verification | **Tooling implemented; gate verdict `EXPLORATORY`** (only 3 evaluable held-out releases; see `SHOT_MODEL_EVAL_REPORT.json`) | A trained or selected detector beats the agreed heuristic baseline on held-out players/sessions, or remains explicitly experimental. |
| 7 | Ball/rim tracking and outcome evidence | **Implemented; detector `QUALIFIED_AS_ADVISORY`** (test mAP@50 0.728; rim class weaker than ball); outcomes advisory only | Ball/rim tracking is measured on held-out footage and linked to shot IDs; automated outcomes remain unknown until separately qualified. |
| 8 | Final user-facing video analysis app | **Local app complete with AI coach report, PDF and phone access over Wi-Fi (2026-10-25); real-phone UAT still open** | User can upload/record, inspect analysis and evidence, receive cautious guidance, and revisit persistent history. |
| 9 | Release, academic review, and maintenance | Planned | A clean install, reproducible evaluation, data/model provenance, limitations, and demo are ready for review. |

## Current evidence and limits

- The raw-clips harness processed 15 videos and 12,394 decoded frames. This establishes processing coverage reported by that run, not shot-detection accuracy on every clip.
- The current human event annotations cover three clips and five shots. Clips without event labels cannot count as true positives or false positives.
- The raw report's 95.9% pose figure is an unweighted average of clip rates; pooled frame coverage is about 95.05% for that report.
- The raw report's “admitted/quarantined” counts are computed from annotation matches. They do not prove those shots were written to SQLite or passed through the actual baseline gate.
- The current event detector still produces substantial false positives and timing error in practice footage. Keep machine proposals reviewable; do not present detector output as verified shot truth.
- 2D versus MediaPipe world-landmark differences are disagreement between estimates. Without independent ground truth, neither is known to be closer to reality.
- Camera angle matters. Record the view and evaluate per view. A model must abstain or warn when capture falls outside supported conditions.

## Phase 1 — Capture and core vision

**Goal:** capture video, estimate pose, render useful landmarks, and make model-asset requirements understandable.

**Existing implementation:** OpenCV video/webcam loop, MediaPipe Tasks pose landmarks, 2D and estimated world coordinates, smoothing, and display.

**Manual developer work:** verify setup on a clean machine; provide example footage that may legally be used; record hardware and capture conditions for performance measurements.

**Coding-agent work:** maintain setup/asset checks, handle missing or unsupported inputs clearly, preserve timestamps and missing-data states, and document performance only from measured hardware runs.

**Exit evidence:** clean setup instructions verified; sample video and webcam paths exercised; required and optional assets and failure behavior documented.

## Phase 2 — Shot analysis foundations

**Goal:** produce explainable pose-based observations and candidate shot phases.

**Existing implementation:** `ShotPhaseDetector`, `SessionRecorder`, joint-angle and kinetic-sequencing calculations, optional hands/ball modules, and illustrative DTW/pro comparisons.

**Manual developer work:** choose and document supported camera framing and shot contexts; review metric definitions against project intent.

**Coding-agent work:** preserve coordinate-basis separation, units, timestamps, validity and confidence metadata; label pro profiles as illustrative; keep missing values missing rather than fabricating measurements.

**Exit evidence:** targeted regression coverage exists; every surfaced metric has a definition and limitation; no score is presented as validated without real reference data.

## Phase 3 — Measurement integrity and real-video evaluation

**Goal:** measure what the current heuristic pipeline gets right and wrong before training a replacement.

**Manual developer work:** annotate complete shot-event timelines for representative clips; include missed machine detections, non-shot actions, camera view, shot style, FPS, and annotation uncertainty. Preserve held-out players/sessions. Resolve annotation disagreements and confirm clip rights/consent.

**Coding-agent work:** audit evaluator frame coverage and matching; produce per-clip/player/view precision, recall, F1, release timing distributions, sample counts, and abstention/coverage. Keep synthetic reports separate from real footage. Record exact input IDs, annotation source, split, thresholds, and software/model versions.

**Exit evidence:** annotation coverage is sufficient for the stated evaluation; matching tolerance is justified; reported aggregates can be independently recomputed; held-out results and failure cases are visible. Processing every frame of an unlabeled clip does not satisfy this gate.

## Phase 4 — Personal Shot Lab and evidence-gated coaching

**Goal:** let a player review attempts, label outcomes, build personal summaries, and receive one cautious, evidence-linked cue.

**Existing implementation:** versioned SQLite Shot Lab, M/X/U labels, review CLI, baseline engine, one-cue coach engine, and follow-up summaries.

**Manual developer work:** verify that a shot is real and its boundaries are acceptable before baseline admission; use M/X for known outcomes and U for unclear outcomes; decide which coaching language and drills are appropriate for the project.

**Coding-agent work:** preserve machine output separately from edits; enforce approval and confidence gates; match baselines by player, view, and shot style; show sample counts and uncertainty; avoid causal claims and unsupported universal thresholds.

**Exit evidence:** the actual DB review-to-baseline path is tested; outcome source and review status are distinguishable; small or invalid samples produce “not enough evidence.” Software tests do not prove cue effectiveness.

## Phase 5 — Developer Model Lab and annotation dataset

**Goal:** give developers a visual, auditable way to create ground truth for training and evaluation. This phase builds the internal labeling product, not the final user experience.

### Manual developer work

1. Collect permitted videos from varied players, shot styles, venues, and supported camera views; record provenance, consent/rights, FPS, resolution, and capture metadata.
2. Define annotation instructions and event schema before labeling: shot/no-shot interval, start, dip, set point, release, follow-through, outcome (`make` / `miss` / `unknown`), visibility/occlusion, and reviewer certainty.
3. Label clips that contain no detected shot as well as clips with machine proposals. Reviewers must be able to add missed shots and mark hard negatives such as dribbles, gathers, passes, and pump fakes.
4. Independently review a subset of labels, reconcile disagreements, and freeze player/session-separated train, validation, and test splits. Do not split adjacent frames from one clip across these sets.
5. Supply clips and annotation decisions. Do not ask the coding agent to guess missing labels or invent dataset contents.

### Coding-agent work

1. Build a local developer review tool with video playback, frame-accurate scrubbing, timeline/keyframe markers, pause/step controls, and machine predictions shown separately from human labels.
2. Support add-shot, mark non-shot interval, correct event boundaries, label outcome/occlusion, undo edits, reviewer notes, and per-clip completion state. No blind approve-all operation.
3. Store source video references/fingerprints, timestamps, original predictions, human annotations, edits/provenance, reviewer and schema versions. Keep large video files outside SQLite; store durable references and structured annotations.
4. Export/import documented JSONL or equivalent annotation records with manifest, class/event definitions, split, license/provenance fields, and validation that labels point to existing frames.
5. Add annotation QA views: missing labels, impossible event order, duplicate events, coverage by class/player/view, and inter-reviewer disagreement where multiple reviews exist.
6. Add deterministic fixture tests clearly marked synthetic; never emit them as real dataset results.

**Exit evidence:** a developer can open a supplied clip, inspect the whole timeline, add both detected and missed attempts, label boundaries/outcomes, save/reopen work without losing provenance, and export a validated dataset. A reviewed dataset manifest and split are supplied by the developer.

## Phase 6 — Shot-event model and verification

**Goal:** improve shot proposal and event timing using the Phase 5 labels, with measured benefit over the current heuristic.

### Manual developer work

1. Confirm annotation quality and dataset splits before training.
2. Set acceptance metrics and thresholds before comparing models; select held-out players/sessions that remain untouched during tuning.
3. Review error samples, especially false shots during gathers/dribbles, missed shots, low-release set shots, occlusion, and unseen camera views.
4. Decide whether results justify replacing, supplementing, or retaining the current heuristic.

### Coding-agent work

1. Build a reproducible training/evaluation pipeline from manifest-driven inputs; fail clearly if clips or required labels are missing.
2. Compare the existing heuristic with simple pose-sequence baselines before adding a larger learned model. Treat wrist height/velocity, dip-to-rise order, duration, and optional ball-hand proximity as features to evaluate—not assumed truths.
3. Train only on the training split; use validation for model/threshold selection; evaluate once on player/session-held-out test data.
4. Report precision, recall, F1, timing error and spread, per-view/player performance, false positives per video-minute, and confidence/abstention behavior.
5. Save model artifact, input manifest, code/config version, class/event schema, and evaluation report together. Keep human review and correction available.

**Exit evidence:** model beats the agreed baseline on held-out data without hiding subgroup failures, or the system retains heuristic proposals and labels learned results exploratory. Do not permit fully automatic baseline admission solely because a model emits high confidence until confidence is calibrated and the gate is validated.

## Phase 7 — Ball/rim tracking and outcome evidence

**Goal:** measure ball flight and rim interaction within a known pose-shot window; qualify automated outcomes separately from shot-event detection.

### Manual developer work

1. Collect permitted clips where ball and hoop are visible, covering makes, misses, occlusions, motion blur, and supported viewpoints.
2. Annotate ball/rim boxes on representative frames and verify shot outcomes independently. Define whether the target is rim, hoop opening, backboard, or multiple classes before training.
3. Reserve entire clips/venues/camera views for held-out evaluation where feasible; document dataset licenses and model-weight provenance.

### Coding-agent work

1. Build frame sampling, YOLO-format annotation validation, training, and held-out evaluation tools. Do not assume a public hoop model or its published scores transfer to project footage.
2. Match detections to pose-owned shot IDs and timestamps; preserve skipped/missing detections as unknown and never carry tracks across shots.
3. Persist ball/rim coverage, trajectory-fit quality, release alignment, outcome, confidence, source, and model version in the shot record/export. Keep automated outcome separate from human M/X/U labels.
4. Evaluate ball detection coverage and box metrics, track continuity, release alignment, and make/miss precision/recall on labeled held-out footage.
5. Keep automatic make/miss disabled or advisory until its separately documented acceptance gate passes. Human labels remain available for correction.

**Exit evidence:** reproducible held-out ball/rim results exist; every observation is attached to the correct shot; missing rim weights/detections yield explicit unavailable/unknown states; outcomes cannot silently overwrite human labels.

## Phase 8 — Final user-facing video analysis app

**Status:** Local app implementation complete; upload/summary and replay/review were confirmed by user. History/trends, drill follow-up, printable report, and optional AI chat are implemented. On 2026-10-17 the player UI was redesigned (work package 08-06: three-view layout, clip timeline, attempt list, session reopening) and reliability fixes plus an automated API test suite (`test_web_app.py`) were added. Manual UAT on eligible real records is still required. Hosted deployment remains Phase 9/release work.

**Goal:** make the player’s coaching experience the centerpiece: guide setup, accept a recording or uploaded session, show processing progress, then return an understandable shot-by-shot review, cautious coaching, and progress over time. This app consumes the Developer Model Lab’s versioned schemas and inference services; it does not replace developer annotation work.

### Player journey

1. **Onboarding:** collect handedness, experience/skill level, practice goals, and preferred shot style. Provide a camera setup guide based on evaluated framing/view limits; save only the profile data needed for personalization.
2. **Capture or upload:** support a video upload first and recording where the selected platform supports it. Ask for session metadata and camera view; explain unsupported framing before processing when possible.
3. **Processing:** submit work through a stable API, show queued/running/complete/failed states and useful recovery guidance. Long video analysis must not block the UI request.
4. **Session summary:** show detected/reviewed shot counts, confidence/unknown counts, a small set of valid metrics, and clearly labeled experimental ball/rim results.
5. **Shot replay:** provide a scrubber with pose/ball overlays where available and phase markers for load, set, release, and follow-through. Let the player inspect or correct machine proposals; preserve original predictions and human edits separately.
6. **Coaching:** show one primary, evidence-linked cue at a time with the supporting frame/metric, confidence, limitation, and a concrete drill. Do not display a cue when the evidence gate fails.
7. **Progress/history:** compare review-approved sessions for the same player, shot style, and camera view. Show sample sizes and view changes; distinguish consistency trends from shot outcome or causal claims.

### Delivery order and feature gates

1. **Pipeline API and job contract:** wrap the existing Python pipeline behind FastAPI endpoints for health/capabilities, upload/session creation, job status, results, and deletion. Keep CV inference in a worker boundary. Start with a simple local worker and persistent job state; add Celery/Redis only if measured concurrency or deployment needs justify the operational cost.
2. **Web/PWA vertical slice:** build onboarding/profile, upload, progress, and a usable results page against the API. Prefer a responsive web/PWA prototype unless user testing or required device APIs justify Flutter/React Native.
3. **Replay and evidence UI:** add shot timeline, phase markers, skeleton replay, confidence/unknown states, and human correction. A radar chart may summarize a small set of normalized metrics only when definitions, validity, and missing-data behavior are clear; also provide readable per-metric values.
4. **Coaching and session trends:** connect the existing rule-based coach to reviewed evidence, then add drill completion and longitudinal history. Define consistency and fatigue-drift measures before exposing scores; do not label ordinary within-session variation as fatigue without supporting evidence.
5. **Optional LLM coach:** implemented as an explicit opt-in requiring `OPENAI_API_KEY` and `--enable-llm-chat`. It receives only approved metric summaries, the rule-based cue, source references, and the user's question; it never receives video/raw landmarks and does not persist chat. Manual API-backed verification remains open.
6. **Optional engagement and sharing:** implemented weekly session goal and activity streak with a documented approved-shot activity rule; consistency is per-metric sample spread rather than a composite score. Browser print-to-PDF export includes evidence counts and limitations. Manual UI verification remains open.
7. **Polish and demo:** accessibility, loading/error states, privacy/data deletion, responsive layout, and a recorded walkthrough that includes one successful flow and one abstention/failure case.

### Candidate architecture (implementation choice remains evidence-driven)

| Layer | Planned responsibility | Candidate implementation |
|---|---|---|
| Player UI | Onboarding, upload/record, processing state, replay, coaching, history | Responsive PWA/web app first; Flutter/React Native only if platform needs justify it |
| API | Stable session, upload, job, result, correction, and deletion contracts | FastAPI with documented OpenAPI/Swagger endpoints |
| Job execution | Run long CV analysis without blocking requests | Existing Python CV pipeline behind a worker; Celery + Redis only if deployment/concurrency requires it |
| Vision and analysis | Pose, shot events, optional ball/rim, metrics | OpenCV + MediaPipe; YOLO remains optional/experimental until its per-view gates pass |
| Coaching | Transparent rules first; optional grounded chat later | Existing rule-based engine; later LLM retrieval over authorized session evidence |
| Persistence | Profiles, sessions, shots, job state, model provenance | SQLite for local prototype; PostgreSQL for multi-user deployment; videos stored separately with explicit retention/deletion policy |
| Delivery | Reproducible install and deployment | Docker and CI after the local vertical slice is stable; no deployment claim until exercised |

These are roadmap targets, not claims about the current implementation. Each layer must be implemented and verified before it is described as present in a demo or defense.

### Manual developer work

1. Decide initial target platform and local-first/cloud privacy behavior; get player/coach feedback on upload, review, and coaching language.
2. Define supported camera conditions and user-facing abstention/framing guidance from evaluation results.
3. Validate prototype workflows with real users and report usability issues without converting anecdotes into accuracy claims.
4. Supply onboarding defaults and coaching/drill wording; review whether profile fields and goals are understandable and necessary.
5. Decide video retention, deletion, and sharing rules before any hosted upload path. Confirm any external LLM provider/privacy terms before enabling coach chat.
6. Review visual summaries and progress measures for misleading interpretations; approve the rules behind streaks, goals, and any consistency score.

### Coding-agent work

1. Define and version API request/response and job-state schemas before UI coupling. Expose pipeline/model availability, progress, structured errors, and cancellation/deletion behavior.
2. Build onboarding and camera guide, upload/record entry, session metadata, asynchronous processing progress, retry/failure handling, and session summary.
3. Build shot-by-shot replay with frame-accurate scrubbing, phase timeline, available pose/ball overlays, machine confidence, and review corrections with full provenance.
4. Build the biomechanics dashboard from validity-gated measurements. Include charts such as a radar-style profile only with documented normalization and missing-value handling; keep raw values, units, and confidence visible.
5. Connect one-cue coaching and drills to evidence in the current shot/session. Add personal-best/ghost comparison only when aligned clips or comparable phase sequences exist; clearly mark illustrative references.
6. Persist profiles, job state, sessions, shot results, model/config versions, and user corrections. Add history/trend views only from review-approved records and matching view/style cohorts.
7. Define consistency and fatigue-drift formulas, minimum sample sizes, and abstention behavior before surfacing these scores. Keep results descriptive and avoid causal claims.
8. Add optional LLM chat only behind a feature flag after evidence retrieval, privacy, grounding, and abstention behavior are tested. Cite the exact session metrics used in each answer; do not let chat create or modify ground truth.
9. Add optional streaks/goals/badges and PDF export after core analysis/replay works. PDF output must include provenance, sample counts, confidence, and limitations.
10. Add Docker/CI and hosted deployment only after local install and privacy/deletion workflows are verified. Keep video storage separate from the relational database and enforce the approved retention policy.

**Exit evidence:** an end user can complete onboarding, upload, follow processing status, inspect/correct shots in replay, understand confidence and evidence, receive an appropriate cue/drill or a clear abstention, revisit comparable approved history, set a practice target, compare an eligible follow-up, print/save an evidence report, and delete a local session with its managed media/cache files. The local vertical slice works without developer-only annotation tools exposed to players. LLM chat is optional and disabled unless explicitly configured. Hosted deployment, authentication, retention policy for external hosting, and recorded user feedback remain release gates; Phase 8 should not be called user-validated until the manual acceptance checks in `08-PLAN.md` are completed.

## Phase 9 — Release and academic review

**Goal:** package a defensible project that another person can install, run, inspect, and evaluate.

**Manual developer work:** secure clip/model permissions; prepare demonstration footage, project defense narrative, limitations, and reviewer responses.

**Coding-agent work:** clean-install check, dependency and model setup, command documentation, reproducible reports, privacy/data deletion checks, model card and dataset manifest, and consistency audit across README, roadmap, state, and implementation.

**Exit evidence:** setup and demo work on a clean environment; no unlicensed media/weights are redistributed; real/synthetic evidence is clearly separated; metrics, failure cases, supported views, and limitations are reviewable.

## Global guardrails

- Manual labels and source clips are user/developer inputs. Never fabricate or hard-code them.
- Keep machine predictions immutable; save human edits with provenance and timestamps.
- Train/test splits must prevent player, session, or near-duplicate frame leakage.
- Distinguish event detection, pose measurement, ball/rim detection, outcome classification, and coaching usefulness as separate claims and evaluation tasks.
- Use machine output as a proposal until its relevant gate passes; support abstention and human correction.
- A user-facing app may be prototyped in parallel against a versioned API contract, but real predictions and advice must wait for validated model outputs.
- Do not claim universal performance across camera angles. Publish supported views and per-view limitations.
- Never claim causal coaching benefit from make/miss associations or a simple pre/post comparison.
