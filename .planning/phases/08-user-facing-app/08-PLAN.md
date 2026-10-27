# Phase 8 Plan — User-Facing Video Analysis App

**Status:** Implementation complete for local Phase 8 slices; 08-01/02 were confirmed by user; new history/coaching/report/optional-chat behavior awaits manual UAT on real reviewed records. Hosted deployment remains deferred behind privacy and user-testing decisions.  
**Phase goal:** Deliver a local-first player flow from video upload through asynchronous pose-based analysis and a readable shot summary, built on the existing Python pipeline and Shot Lab database.

## Locked implementation choices

- Start with a responsive browser app served locally; keep processing on the user's machine.
- Use Python's standard-library HTTP server for the first vertical slice because the repository environment does not currently include FastAPI/Uvicorn. Keep API/service boundaries separable so the server can move to FastAPI later without replacing the analysis service.
- Reuse MediaPipe Pose, `ShotPhaseDetector`, `SessionRecorder`, and SQLite. Do not introduce new pose or outcome claims in this slice.
- Preserve each machine-detected attempt as quarantined with `unknown` human outcome. Ball/rim inference, coaching, chat, chart scores, and automatic outcome labels are out of scope for the first slice.
- Accept uploads only through the loopback server, store generated filenames under an ignored local upload directory, cap request size, and expose processing status.

## Work packages

### 08-01 — Local upload-to-summary vertical slice

**Coding-agent work**

1. Add a headless video-analysis service that processes every readable frame using the existing pose and shot-phase components, records detected attempts into the configured Shot Lab SQLite database, and emits honest status when no valid shots are found.
2. Add a local web server with a small JSON API for health/capabilities, video upload, job polling, and session results. Run analysis in a bounded background worker so uploads return promptly.
3. Add a responsive browser UI for player/session metadata, camera view, shot style, file upload or browser camera recording where MediaRecorder is supported, progress, and a shot summary with confidence and explicit human-review/unknown outcome status.
4. Restrict the server to loopback by default; validate upload name/type/size; use generated storage names; keep uploaded video out of version control.
5. Update `MANUAL_VERIFICATION_COMMANDS.md` with exact launch/use commands, required assets, expected result, and DB/upload side effects.

**Manual developer work**

1. Provide a permitted sample clip with a visible full-body shooter and note its expected number of shots for manual review. Missing clips must be supplied by the developer; the agent must not substitute sample or synthetic footage.
2. Open the app, upload the clip, confirm processing progress, and inspect whether detected shot rows and frames are plausible in the existing review tool.

**Acceptance evidence**

- A browser can upload a supplied local video and receive a job ID without blocking until analysis ends.
- Where browser permission and MediaRecorder are available, a camera recording can be selected and submitted through the same upload path; otherwise file upload remains available.
- Polling shows queued/running/complete/failed states with useful messages.
- A completed session is persisted in SQLite and its shot summary can be reloaded after refresh/server restart.
- Machine outcomes remain unknown and review status remains quarantined; no YOLO, coaching, LLM, or baseline admission is implied.
- Upload size/type errors are clear; generated upload paths cannot escape the configured upload directory.

### 08-02 — Replay, pose overlay, and human review with provenance

**Implementation status:** Coding slice implemented; manual review on a supplied real clip remains developer verification.

1. Cache compressed MediaPipe landmarks for each analyzed frame and keep cache files local/ignored.
2. Serve uploaded video with HTTP byte-range support so browser seeking works; serve the matching pose cache by opaque job ID.
3. Show shot event markers and frame-number editor for load, dip, set, release, and follow-through. Represent unmeasured dip as unavailable.
4. Draw the cached pose overlay during replay without rerunning inference in the browser.
5. Save human boundary/outcome/status edits separately from machine boundaries; reject invalid frame range/order and preserve append-only review history.
6. Keep outcomes manual and make/miss approval explicit; this slice does not infer outcomes or admit an unreviewed shot to baselines.
7. Update the canonical manual command index with replay/review steps, required assets, expected behavior, and local file/database side effects.

**Manual developer work:** Upload a permitted real clip, review each proposal against the replay, correct boundaries/outcome/status, save, and confirm machine fields are unchanged while human fields and history persist after refresh/restart. **User confirmed the replay/review slice works.**

### 08-03 — Validity-gated biomechanics and one-cue coaching

**Implementation status:** Coding slice implemented; developer must manually verify both abstention and eligible-evidence cases with real, approved records.

1. Show per-session biomechanical summaries only from review-approved shots with `SUFFICIENT` tracking confidence. Show sample counts and withhold aggregates when fewer than five non-missing values exist for a metric.
2. Compute a matched personal cohort by player, camera view, shot type, and shot style. Require at least five approved, sufficient-confidence shots overall and at least five non-missing values for the cue's metric.
3. Reuse the existing style-specific `CoachEngine` thresholds and one-cue priority. Treat thresholds as prototype starting defaults; include the measured evidence, metric, sample count, drill, and available source shot/frame references.
4. If a cohort, metric, or supported measurement is insufficient, return a plain-language abstention and do not fill missing measurements or infer a cue from another metric.
5. Make the app insights endpoint read-only: do not persist a new baseline or remediation just from viewing this dashboard. Do not use make/miss associations as causal evidence.
6. Correct baseline admission so quarantined shots cannot qualify because they were edited or carry notes; only explicitly approved records are baseline candidates.
7. Update the manual command index and README with evidence gates, outcomes, and verification procedure.

**Manual developer work:** Verify the UI abstains with fewer than five approved valid shots or fewer than five samples for a metric. Then use at least five actual reviewed/approved shots with matching player/view/type/style and check the displayed metric/cue against DB values and source frames. Do not count synthetic/demo records as real evidence.

### 08-04 — Review-approved history, comparable-session trends, practice goals, and drill follow-up

**Implementation status:** Implemented; requires manual UAT with real approved records.

1. Add schema-v6 `player_app_settings` for the player-selected weekly session target (1–7); do not count a session unless it contains an approved, `SUFFICIENT` shot.
2. Show weekly progress and active-day streak from persisted UTC session dates; define a counted practice session/day in the UI and do not imply a performance score.
3. Show the player's recent saved sessions so unreviewed sessions remain reachable for review/deletion. Count a session toward progress and show metrics only when approved, confidence-sufficient shots exist. Restrict mean/spread, line charts, and adjacent-session deltas to identical player, camera view, shot type, and shot style.
4. Show “consistency” as the sample standard deviation of each measured metric, with the sample count and minimum of five. Do not combine metrics into an unexplained score.
5. Show early/late within-session metric changes only with at least six approved shots and three available values in each half. Label this as descriptive change, not fatigue or a cause.
6. Save a drill/remediation only after an explicit player action. Permit follow-up comparison only against a different session with the same context and at least five approved, confidence-sufficient metric values. Store pre/post mean and spread plus human-labeled outcome counts when present; state that the comparison does not establish causality.

### 08-05 — Optional grounded AI explanation and shareable report

**Implementation status:** Implemented behind an explicit opt-in for AI; report uses browser print-to-PDF. AI requires user-supplied API credentials for runtime UAT.

1. Keep local rule-based coaching as the default. Enable the AI coach only with `--enable-llm-chat`, `GEMINI_API_KEY`, and an explicitly configured API model (`--llm-model` or `GEMINI_MODEL`).
2. Send only the current question, approved metric summaries, one rule-based cue, and source shot/frame references. Never send video, raw landmarks, unreviewed detections, or human labels as causal evidence. Do not persist chat text.
3. Show supplied sample counts and source references beside the model response. Bound question and response size; show network/model errors without breaking local coaching.
4. Generate the print report from the same insights object as the UI, showing session metadata, units/counts, cue or abstention, source frames, generation time, and limitations.
5. Keep history and goal data local in SQLite. Provide an explicit per-session delete action that removes its session/shots/review audit, session-linked drill rows, job metadata, uploaded video, and pose cache. Hosted deployment, multi-user authentication, mobile capture, and external data-retention rules remain release work; do not claim them implemented by this local slice.

### 08-06 — Player UI redesign and reliability fixes

**Implementation status:** Implemented and verified by automated API tests, a real-clip API run, and browser screenshots (2026-10-17). Manual UAT by the developer is still required.

1. Rebuild the browser UI around three views (New session, Review, Progress) without changing API contracts or evidence gates.
2. Make review fast and legible: clip timeline with attempt segments and release ticks, attempt list, explicit decision/outcome choices, readable change history.
3. Return live shot rows from `GET /api/jobs/<id>` so saved reviews survive reloads; expose `job_id` per history session so any web session can be reopened.
4. Resolve stored upload paths copied from another computer inside the configured upload directory only.
5. Propose an attempt cut off by the end of the clip only when a release was observed; keep it quarantined.
6. Bundle fonts locally and send a restrictive Content-Security-Policy so the page makes no external requests.
7. Add `test_web_app.py` and update the command index, README, roadmap, and state.

### 08-07 — AI shooting coach report, phone access, and review tools

**Implementation status:** Implemented 2026-10-25 (see `08-07-AUDIT.md`). Automated tests and a real-clip acceptance run in a disposable DB passed. Real iPhone/Android checks are developer work.

1. Measurement engine on the pose cache (`shooting_analysis.py`) with per-metric confidence, view support, plausibility, quality/view assessment, consistency and make/miss split.
2. Deterministic coach (`shot_coach.py`): findings answering the five questions, drills scaled by experience, first focus, practice plan, injury-risk-reduction section with explicit limits.
3. Report service (`report_service.py`): 10 sections, annotated keyframes, schema-v7 persistence keyed on inputs; Report view and print/PDF layout (`web/report.js`).
4. Worker: pose cache v2 (raw landmarks + world), H.264 replay copy, report build, cancellation; upload duration/decoding checks.
5. Review: manual attempts, camera-view correction, pose refresh, prev/next, mm:ss, angle overlay, coach markers and timestamp links.
6. `--lan` phone access with access code, private-network restriction, lockout, CSRF and Host guards, optional TLS.
7. Tests: `test_shooting_analysis.py`, `test_shot_coach.py`, `test_report_service.py`, extended `test_web_app.py`, Playwright `test_frontend_ui.py`. Docs updated.

**Manual developer work:** run the section-15 acceptance in `MANUAL_VERIFICATION_COMMANDS.md` on a permitted clip, including from an iPhone and an Android phone on the same Wi-Fi; judge whether the coaching language and thresholds suit the project; decide whether to keep `--lan` sessions to trusted home networks only.

### Phase 8 manual acceptance gates

- **History/privacy:** a new or empty player shows no invented activity; quarantined/insufficient shots do not count; changing the weekly target persists after reload.
- **Trend semantics:** comparable sessions use matching camera/type/style only; five-value metric gates work; within-session split is withheld below six shots; displayed deltas can be reconciled to approved database values.
- **Drill loop:** merely viewing a cue does not write a remediation; explicit save creates one; mismatched context/under-five follow-up is rejected; accepted follow-up stores real post metrics and is labeled descriptive.
- **Report:** browser print preview contains the displayed metrics, counts, cue/abstention, and limitations; saving as PDF is user initiated.
- **Deletion:** deleting a session removes its database records and managed video/cache files; confirm unrelated sessions, player goal, and unrelated drill rows remain.
- **AI opt-in:** default health reports chat disabled; opt-in requires a key; with approved user credentials, inspect that the answer uses only the supplied context, citations are shown separately, and the app handles network/API errors. This has not been run from this workspace.
- Passing UI checks is workflow evidence, not model accuracy evidence. No real clip, eligible 5-shot cohort, or API credential was consumed for this implementation turn.

## Verification commands

Run from the repository root:

```powershell
.venv\Scripts\python.exe web_app.py --host 127.0.0.1 --port 8765 --db shot_lab.db --upload-dir user_data\uploads --pose-cache-dir user_data\pose_cache
```

Open `http://127.0.0.1:8765`, upload a permitted real clip, scrub the replay and pose overlay, correct one proposal, save a review, refresh, and verify the restored result and `shot_review_history` in the selected SQLite database. To exercise coaching, approve at least five confidence-sufficient shots for the same player/view/type/style and ensure five have the same available mechanic measurement. Use a separate `--db` path for a disposable manual run. No accuracy claim is established by this workflow alone.
