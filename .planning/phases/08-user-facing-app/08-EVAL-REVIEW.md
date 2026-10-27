# EVAL-REVIEW — Phase 8: User-Facing App

**Audit Date:** 2026-10-15  
**AI-SPEC Present:** No  
**Audit basis:** Phase 8 plan and summary, source inspection, the manual-command index, and general product/AI evaluation practice. Phase 8 is primarily a deterministic local MediaPipe/OpenCV application with rule-based coaching; Gemini is an optional explanation layer. It is not a newly trained model phase.  
**Overall Score:** 8/100  
**Verdict:** NOT IMPLEMENTED

No `08-AI-SPEC.md` exists. Therefore there is no phase-specific evaluation rubric, reference set, promotion gate, monitoring plan, or pre-defined acceptance threshold to audit. This review uses the concrete Phase 8 behaviors named in `08-PLAN.md` as the expected product behaviors. The summary states that only Python/JavaScript syntax and diff checks ran after the WebM and Gemini changes; real-video analysis, browser camera recording, deletion, Gemini calls, and the full test suite were not run. Documentation of manual UAT is not execution evidence.

## Dimension Coverage

| Dimension | Status | Measurement | Finding |
|-----------|--------|-------------|---------|
| Upload, camera recording, and readable-video handling | PARTIAL — WARNING | Code inspection + documented manual test | `web_app.py` validates file size/type, queues analysis, and uses `prepare_video_for_analysis`; `video_analysis_service.py` has an FFmpeg fallback for undecodable recordings. No browser, camera-permission, WebM transcode, or real-video run was performed. There is no automated integration test for accepted/rejected uploads or the fallback path. |
| Shot-event proposal correctness, confidence, and abstention | MISSING — BLOCKER | Labeled-video benchmark required | The upload worker reuses `ShotPhaseDetector`, saves proposals as quarantined/unknown, and computes a tracking-confidence ratio. Phase 8 has no held-out, labeled upload-video set; no precision/recall, boundary timing error, false-positive rate, calibration, or abstention error is reported for the actual browser/upload path. Existing Phase 6 detector work cannot prove this path handles recorded/WebM input correctly. |
| Human review provenance and SQLite integrity | PARTIAL — WARNING | Code inspection + DB integration/manual UAT required | Separate `machine_*` and `annotated_*` fields, chronological/range checks, and append-only `shot_review_history` writes exist in `web_app.py` and `shot_lab_db.py`. No Phase 8 test or executed DB Browser check proves that corrections persist, preserve machine fields, reject invalid edits, and survive a server restart. |
| Coaching factuality, evidence gates, and abstention | PARTIAL — WARNING | Code-based fixture checks + expert review required | `coaching_service.py` filters to `approved` plus `SUFFICIENT`, requires five samples, keeps one cue, and labels prototype thresholds/non-causality. That is a plausible implementation, but no tests prove all bypass paths are blocked and no coach/domain-expert review evaluates whether cues and drills are appropriate for approved real clips. Static guards do not validate the measurements or the coaching conclusion. |
| History/trend arithmetic and sample gates | PARTIAL — WARNING | Deterministic fixture tests + DB reconciliation required | `history_service.py` gates metric means/spread at five observations, early/late changes at six shots and three per half, and compares matching context. There are no Phase 8 fixture tests for date boundaries, context exclusions, missing values, stdev/delta arithmetic, or weekly/streak calculations; no displayed chart has been reconciled to real approved rows. |
| Session deletion and local-data privacy behavior | PARTIAL — WARNING | Isolated destructive UAT + filesystem/DB assertions required | The delete route removes DB rows, job rows, upload files, and pose caches under managed roots, with warning messages for file failures. No disposable-DB run verifies all intended records/files are gone, unrelated sessions/settings remain, or partial filesystem failure is recoverable and visible. The lack of authentication is acceptable only because loopback-only local use is enforced; it is not production authorization. |
| Gemini grounding, safety, and failure behavior | MISSING — BLOCKER | Prompt/output test set + mocked and authorized live-call evaluation required | `llm_coach.py` restricts input to question plus approved summaries, uses an opt-in key, size/time limits, and a grounding instruction. A system prompt is not an output guardrail: the returned text is accepted without claim/citation validation, moderation, or human/LLM-judge scoring. No prompt-injection, unsupported-causality, missing-evidence, unsafe-advice, HTTP error, timeout, or malformed-response evaluation has run; no authorized Gemini call was made. |
| Performance and operational reliability | MISSING — BLOCKER | Measured workload/restart evaluation required | The code has a bounded worker and marks interrupted jobs failed on restart, but no latency/memory limits, queue-load results, readable/invalid codec matrix, restart/retry outcome, error-rate metric, or operational trace exists. Syntax checks cannot show that the local app reliably completes analysis on representative clips. |

**Coverage Score:** 0/8 (0%)

`COVERED` requires implemented behavior plus an automated or documented manual run. No dimension meets that standard because the only recorded Phase 8 verification is syntax/diff checking, while every product/AI behavior above needs execution evidence. `PARTIAL` denotes implemented, statically inspectable safeguards whose required runtime or correctness evaluation has not occurred. `MISSING` denotes a critical evaluation dimension with no measurement harness, reference data, or completed evaluation.

## Infrastructure Audit

| Component | Status | Finding |
|-----------|--------|---------|
| Eval tooling | Missing | The repository has earlier detector/unit evaluators and `py_compile` commands, but no Phase 8 browser/API/coaching/Gemini evaluation harness is installed or called. No RAG/LLM evaluation tool is present. |
| Reference dataset | Missing | `dataset_export/*.jsonl` serves earlier detector work. There is no curated Phase 8 test set of permitted video uploads, expected decode outcomes, reviewed shot/event labels, approved-cohort records, or Gemini question/rubric cases. |
| CI/CD integration | Missing | No Makefile, GitHub Actions workflow, or other CI configuration was found. Phase 8 checks are manual commands only. |
| Online guardrails | Partial | Loopback bind enforcement, size/type limits, managed-path checks, review-status and sample gates, Gemini opt-in, input limits, and network-error handling are implemented in request paths. Gemini output has no runtime grounding/safety validator, and guardrail behavior has not been exercised. |
| Tracing | Missing | No Langfuse/LangSmith/Arize/Phoenix/Braintrust/Promptfoo setup or equivalent structured request/LLM trace was found. Job rows expose status only; they do not provide evaluation-grade traces or quality monitoring. |

**Infrastructure Score:** 20/100

## Critical Gaps

1. **BLOCKER — No real upload-path shot-event evaluation.** The product displays and persists machine proposals, but their correctness, boundary timing, confidence behavior, and abstention rate were never measured on a held-out labeled set through the browser upload path.
2. **BLOCKER — No Gemini safety/grounding evaluation.** The optional chat can produce unrestricted model text after a prompt-only instruction. There is no reference question set, output rubric, automated validator, human review, or live-call evidence.
3. **BLOCKER — No operational reliability evaluation.** There is no evidence for representative-video completion, camera/WebM compatibility, restart behavior, resource use, queue behavior, or failure/retry reliability.

## Remediation Plan

### Must fix before production:

1. Build a versioned, permitted Phase 8 reference set outside Git: 10–20 representative local clips covering MP4 and browser WebM, readable/invalid codecs, full/partial body views, zero-shot clips, and known difficult clips. Record source ID, license/consent, expected readability, frame count/FPS, human shot intervals/release frames, and expected abstention cases in a manifest.
2. Add an upload-path evaluation command that runs the exact `prepare_video_for_analysis` plus `analyze_video` flow against that set and emits input IDs, code/config versions, decode result, processed frames, proposals, precision, recall, F1, release-frame MAE, false positives/minute, confidence/abstention coverage, and failures. Define promotion gates before interpreting results. Do not reuse synthetic fixtures as real-video accuracy evidence.
3. Create deterministic Phase 8 integration tests using temporary SQLite databases and explicitly marked synthetic fixtures for: upload rejection and queue states; review field provenance and invalid boundary rejection; five-sample/cohort gates; history/streak/context arithmetic; explicit drill persistence; and delete cleanup while preserving unrelated data. Run them in CI.
4. Keep Gemini disabled for release until a 10–20-question evaluation set exists. Include unsupported causal questions, conflicting/insufficient evidence, prompt injection, health/medical requests, empty and malformed model responses, timeout/HTTP errors, and normal basketball questions. Evaluate output against a written rubric for factual faithfulness, abstention, source references, non-causal language, safety, and error fallback. Add a response validator or conservative fail-closed fallback for claims outside the approved context; calibrate any LLM judge against human review before relying on it.
5. Run a measured operational acceptance pass on target hardware: each reference codec, browser camera recording, FFmpeg fallback, server restart while queued/running, one concurrent upload/queue-full response, deletion of a QA session, and replay after restart. Record actual latency, completion/error rates, and resource observations; define acceptable limits.

### Should fix soon:

1. Execute the existing Phase 8 manual procedure against a disposable database and real permitted clip. Capture the exact input, browser/version, result IDs, screenshots, and observed side effects. Verify deletion only on a freshly uploaded QA session.
2. Add an endpoint-level contract test for every documented API response/error and a database migration test for schema-v6 data. Ensure a session with zero proposals remains reviewable/deletable rather than appearing indistinguishable from a missing session.
3. Have a qualified basketball coach review a small set of evidence-gated cues and drills from independently reviewed clips. Record agreement/disagreement and revise the threshold/drill mapping from that evidence, keeping the results descriptive.
4. Add structured local logs for job start/end, decode route, frame count, proposals, explicit errors, and Gemini request outcome without storing keys, video content, raw landmarks, or chat text. Use them to create an offline failure-review loop.

### Nice to have:

1. Add an accessibility/browser compatibility pass for camera controls, keyboard review, readable error messages, and print-to-PDF output.
2. Add privacy-retention configuration and a recoverable-delete/archive design before any non-loopback or multi-user deployment.

## Files Found

- Phase artifacts: `08-PLAN.md`, `08-SUMMARY.md`; no `08-AI-SPEC.md` or prior Phase 8 eval review.
- Phase implementation: `web_app.py`, `video_analysis_service.py`, `coaching_service.py`, `history_service.py`, `llm_coach.py`, `shot_lab_db.py`, `web/app.js`, `web/index.html`, `web/app.css`.
- Existing evaluation/test assets, none specific to the Phase 8 app path: `evaluate_pipeline.py`, `evaluate_dataset.py`, `evaluate_shot_models.py`, `evaluate_ball_tracking.py`, `evaluate_pose_backends.py`, `evaluate_public_datasets.py`, and `test_*.py` modules.
- Manual workflow: `MANUAL_VERIFICATION_COMMANDS.md` documents Phase 8 UAT but explicitly states the behavior still needs real-video, camera, deletion, and Gemini verification.
- No Promptfoo/RAGAS/LangSmith/Braintrust configuration, tracing setup, CI configuration, or Phase 8 reference/eval dataset was found.
