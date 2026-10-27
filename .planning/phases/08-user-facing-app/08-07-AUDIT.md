# 08-07 Audit — AI Shooting Coach brief vs. current implementation

**Date:** 2026-10-25 · **Scope:** upload → analysis → persistence → results → report, against the "Basketball Shot Lab: AI Shooting Coach" brief.

## How the workflow runs today

1. `web/app.js` sends the raw file with `fetch` to `POST /api/sessions` (`web_app.py`). Size (≤250 MB), extension and OpenCV decodability are checked; WebM falls back to an FFmpeg MP4 copy.
2. One background worker runs `video_analysis_service.analyze_video`: MediaPipe pose on every frame → `ShotPhaseDetector` → `SessionRecorder` → quarantined shot rows in SQLite, plus a gzip pose cache for replay.
3. The Review view replays the original upload with the pose overlay, lets the user edit boundaries/outcome/status (audited), and calls `/insights` (approved shots only, N ≥ 5 gate, one cue from `coach_engine`).
4. The "report" is a short browser print of the insights object.

## What works (verified 2026-10-17, re-checked today)

Upload and job polling, loopback-only server, byte-range replay, pose overlay, review with provenance, evidence-gated cue, history/goal/drill follow-up, deletion, 80/82 tests.

## Gaps against the brief

| Brief requirement | Current state | Severity |
| --- | --- | --- |
| Video-driven coaching report with strengths, priorities, drills, practice plan | Only one rules cue, and only after 5 **approved** shots in the same context. A first upload produces no coaching at all. | **Blocking** |
| Per-attempt biomechanics (stance, knee/hip flexion, elbow, torso, release height, follow-through, landing, timing) with units/time/confidence | Upload flow stores only elbow-at-release (2D/3D) and a sequencing lag. Knee-at-dip and torso sway are hard-coded `None`. No per-metric confidence or camera-view gating. | **Blocking** |
| Pose cache sufficient for re-analysis | Cache keeps 12 joints, image coordinates only: no head, heels, feet, or world coordinates. Old sessions cannot be re-measured for feet/head metrics without re-running pose. | High |
| Video quality / camera-view assessment | None. Declared camera view is never checked against the footage. | High |
| Injury-risk-reduction section | Absent. | **Blocking** |
| Annotated keyframes / visual evidence in the report | Absent; the print report is text only. | High |
| Full report persisted and reopenable | Not persisted; regenerated from insights at print time. | High |
| Upload progress, duration/corrupt validation, cancellation | `fetch` gives no upload progress; no duration limit; no cancel. | Medium |
| iPhone/Android access over Wi-Fi with access control | Server refuses non-loopback binds; no authentication. | **Blocking** for phone use |
| iPhone HEVC footage playable in every browser | Today's upload (`822b442d…`, HEVC 2560×1440) replays only in browsers with HEVC support (Safari, recent Chrome on macOS). No H.264 replay copy. | Medium |
| Manually add a missed attempt | Only existing proposals can be edited. | Medium |
| Prev/next attempt, timestamps, measurement overlay, insights linked to time | Partial (timeline + attempt list; frame numbers, no mm:ss; no angle overlay; no insight links). | Medium |

## Things that are honest already and must stay that way

- Machine proposals are quarantined; human labels are never overwritten; make/miss is never inferred in the upload flow.
- No universal "ideal angle" is presented as validated; thresholds are labelled prototype defaults.
- Ball/rim tracking is not run in the upload flow and must not be implied.

## Resolution (2026-10-25)

| Gap | Resolution | Verified by |
| --- | --- | --- |
| No coaching on first upload | `shot_coach.py` findings on all non-discarded attempts, confidence reduced for unconfirmed ones; strict N≥5 drill plan kept | `test_shot_coach.py`; real 54 s clip |
| Missing biomechanics | `shooting_analysis.py`: 20 metrics with unit, time, confidence, view support, plausibility | `test_shooting_analysis.py`; real clips |
| Pose cache too thin **and time-lagged** | Cache v2: 33 raw landmarks + world coordinates; centred 1-2-1 smoothing in analysis. The causal EMA trailed the wrist by ~85 px at release on the test clip | Raw vs cached comparison on frame 29; keyframe alignment |
| Detector "release" is the start of the arm rise | Release estimated from arm extension unless the user corrected it; both recorded | Real clip: elbow-at-release 102–147° → 169–177° |
| Timing windows included the landing | Restricted to dip→release | Real clip: release-vs-legs −300 ms → −67 ms |
| No quality/view check | `assess_video_quality` + view gating on declared **and** observed view; camera-view correction endpoint; `rear` view added | Tests; real rear-view clip; side clip mislabelled as rear |
| No injury section | Four-part observations + general guidance + limits + pain flag | Wording tests (no diagnosis/prediction) |
| No visual evidence / persisted report | Annotated keyframes from real frames; schema v7 tables; reopen from saved report | `test_report_service.py`; restart check |
| Upload progress, duration, cancel | XHR progress, 0.5 s–10 min check, first-frame decode, cancel endpoint | `test_web_app.py`, `test_frontend_ui.py` |
| Phone access | `--lan` (private networks, access code, cookie, lockout), CSRF header, Host check, optional TLS | `LanAccessTest`; live curl from network address incl. TLS 1.3 |
| HEVC replay | H.264 replay copy when needed | Real iPhone HEVC clip |
| Manual attempts, prev/next, timestamps, overlays, insight links | Implemented in Review | Playwright journey |

## Decisions

- Keep the stdlib server and SQLite; add schema v7 tables for attempt analysis, session analysis and reports. No new framework is needed.
- New pure-Python modules: `shooting_analysis.py` (measurements), `shot_coach.py` (rules, drills, plan, injury guidance), `report_service.py` (10-section report + keyframes). They read the pose cache, so they can be re-run after a human edits an attempt without re-running MediaPipe.
- Report findings use attempts that are not discarded. Findings built only on unconfirmed machine proposals are labelled and their confidence is reduced one level. The existing strict N ≥ 5 approved-shot gate keeps governing baselines, trends and the drill follow-up loop.
- Phone access: explicit `--lan` mode with a random access token (cookie after first visit), private-network clients only, optional TLS (`--tls-cert/--tls-key`). Loopback stays the default.
- No model retraining: the held-out evidence (3 releases) still cannot show an improvement.
