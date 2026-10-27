# Basketball Coach — Project Definition

## Product vision

Build an accessible, local-first basketball shooting practice tool that helps a player understand their own repeatable mechanics and review how those mechanics relate to shot outcomes. It should show the evidence behind each observation, disclose uncertainty, and abstain when video quality is insufficient.

This is a coaching and learning prototype. It is not laboratory motion capture, a medical assessment, or proof that one canonical shooting form is correct.

## Current product

Two entry points share one Python pipeline. `main.py` is the desktop OpenCV app for webcam or video files; `web_app.py` is a local, loopback-only browser app (New session, Review, Progress) for upload or browser recording, background pose analysis, replay with pose overlay, human review with provenance, a measured 10-section coaching report (strengths, priorities, drills, practice plan, technique and injury-risk reduction) with PDF export, phone access over Wi-Fi with an access code, evidence-gated one-cue drill plan, practice history, drill follow-up, print/PDF report, and session deletion. Current modules provide MediaPipe pose tracking, angle and shot-phase analysis, CSV session recording, optional YOLO ball tracking, optional MediaPipe hand metrics, and illustrative pro-profile/DTW comparisons. A synthetic evaluation harness exercises selected logic.

The implementation is ahead of older README status tables in some areas and behind the planning status claims in others. In particular, the project has not yet established real-video accuracy, calibrated confidence, validated biomechanical angles, or a tested makes-versus-misses coaching effect. Treat current measurements and scores as experimental until Phase 3 exits.

## Differentiation

The project competes in a crowded category of camera-based shot analysis. Feature checklists alone are not a defensible contribution. The intended distinction is a transparent **Shot Lab**:

1. Detect and show representative shots with source frames.
2. Separate made and missed attempts when outcome evidence is available.
3. Compare a player's mechanics with their own baseline before showing optional illustrative references.
4. Offer one evidence-linked adjustment or drill at a time.
5. Compare a controlled follow-up set and report what changed, uncertainty, and sample size.

The tool must describe associations as associations. It must not claim that a measured movement caused a make or miss without a suitable study.

## Product principles

- **Evidence before advice:** every cue points to a measured event, frame, and confidence state.
- **Abstain safely:** missing, occluded, or out-of-view landmarks produce “can't assess,” not fabricated values.
- **Separate coordinate systems:** image-plane measurements and model-inferred 3D estimates are separately named and validated.
- **Personal baseline first:** pro profiles are optional illustrations, never normative ground truth.
- **Offline by default:** process videos locally; make persistence and export explicit.
- **Measure product quality:** report real annotated-video results and failure cases. Synthetic fixtures are regression checks only.
- **Build vertical slices:** complete one player workflow end-to-end before adding broad UI or model complexity.

## Technical scope

### Current / prototype

- Webcam and prerecorded video input through OpenCV.
- MediaPipe Tasks pose inference and 2D landmark display.
- Angle, phase, kinetic-sequence, hand, and ball analysis modules.
- Session CSV output and OpenCV HUD.
- Optional YOLO and hand modules.

### Planned

- Real-video evaluation set with annotation protocol and reproducible metrics.
- Explicit confidence and camera-quality gate.
- Reliable session schema and player-specific longitudinal summaries.
- Shot Lab review flow with outcome labels and evidence-linked cues.
- A player-facing web/PWA coaching experience: onboarding and camera guide, upload/record, asynchronous processing, session summary, shot replay, evidence-linked coaching, and review-approved history.
- FastAPI as a candidate API boundary around the existing Python pipeline; asynchronous worker/job state for video analysis. Celery/Redis, PostgreSQL, Docker, and hosted deployment remain conditional choices based on measured product needs, not current implementation claims.
- Biomechanics charts, ghost comparison, consistency/fatigue trends, PDF reports, and gamification after metric validity, alignment, sample-size, and user-data rules are defined.
- Optional LLM coach chat only after evidence retrieval and privacy controls are stable; it must ground answers in authorized session metrics and abstain when evidence is missing.
- Optional multi-view capture experiment if resources permit; single-view 3D remains an estimate.
- Learned sequence models only if labeled data exists and they beat simpler baselines on held-out players.

## Non-goals

- Claiming sub-millimeter or lab-grade accuracy from a single phone camera.
- Presenting hand-authored pro curves as measured NBA motion-capture data.
- Publishing a similarity percentage as a validated measure of shot quality.
- Training an LSTM/Transformer without an adequately labeled dataset and baseline comparison.
- Building a large web platform before core measurements and session data are dependable.
- Presenting planned app architecture, LLM chat, or advanced visualizations as implemented or validated before the corresponding phase gates pass.

## Success definition

The project is review-ready when another person can install it, run the core workflow, understand required/optional model assets, inspect a session, reproduce evaluation results, and see honest limits. Scientific claims must be supported by a documented dataset, methods, metrics, and failure analysis.
