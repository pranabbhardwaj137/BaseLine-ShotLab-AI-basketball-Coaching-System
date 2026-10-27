# Personalized Workout Coach

The Report page has a **Generate My Personalized Workout** button. It opens a guided workout built from the
findings in that session's shooting report and from the player's own choices: equipment, fitness level,
duration, goals, pain and movements to avoid. Everything runs locally, with no AI service. The plan is
deterministic: the same report and the same choices always give the same workout.

## Files

| Path | Purpose |
|---|---|
| `configs/workout_catalog.json` | Editable exercise catalog: 121 exercises across 9 equipment groups, dosing, areas and rep cadence. 102 exercises map to a demonstration video. 19 have no video yet (for example plank, side plank, bird dog, Pallof press, step-up, single-leg balance, landing stick, marching, arm circles and leg swings). The planner does not prescribe those 19. |
| `src/basketball/workout/catalog.py` | Loads and validates the catalog. Resolves an exercise **id** to a video file inside `workout/`. |
| `src/basketball/workout/planner.py` | Validates preferences, links report findings to training areas, selects exercises, doses them and computes the duration. |
| `src/basketball/workout/progress.py` | Validates player state and progress, defines the final-10% voice rule, and builds the end-of-workout summary. |
| `src/basketball/persistence/shot_lab_db.py` | Adds the `workout_plans` table (schema v8). Deleting a session also deletes its workouts. |
| `src/basketball/app/web_app.py` | Adds the workout routes (below) and the `--workout-dir` option. |
| `web/workout.js`, `web/index.html`, `web/app.js`, `web/app.css` | Workout page: setup stages A–D, plan review, guided player, feedback and summary. |
| `tests/unit/test_workout_planner.py`, `tests/e2e/test_workout_api.py`, `tests/e2e/test_workout_ui.py` | Tests. |
| `tests/support/workout_report_fixture.json` | A report this app produced from a project test clip, trimmed to the fields the planner reads. It is a test fixture. |

`workout/` (the 305 demonstration videos) is listed in `.gitignore` and is never modified by the app.
It is read-only: files are streamed to the browser, never rewritten or converted.

## HTTP routes

| Method and route | Result |
|---|---|
| `GET /api/sessions/<sid>/workout-context` | Report summary, findings used and not used, defaults, equipment counts, video-library status, and previous workouts. |
| `POST /api/sessions/<sid>/workouts` | Body: `{"equipment":[…], "fitness_level", "duration_min", "goals":[…], "avoid":[…], "pain", "limitations_note"}`. Returns `201` with the plan, `400` for invalid choices, `422` if no exercise fits, `409` while the session is still being analysed. |
| `GET /api/sessions/<sid>/workouts` | Lists the session's workouts. |
| `GET /api/workouts/<wid>` | Plan, saved player state, progress, feedback and summary. |
| `PUT /api/workouts/<wid>/progress` | Body: `{"status":"active|completed|ended_early", "state", "progress", "feedback"}`. A final status computes the summary on the server. After that the record is locked (`409`). |
| `DELETE /api/workouts/<wid>` | Deletes the workout. |
| `GET /api/workout-media/<exercise_id>` | Streams the mapped `.mp4`, with HTTP Range support. |

The browser never sends a file path. The media route accepts only `[a-z0-9_]{1,64}` catalog ids. The
server resolves the stored relative path and refuses the request unless the result is an existing
`.mp4` file inside `--workout-dir`. Unknown ids, text-only ids, missing files and traversal attempts
all return `404`. All mutating routes keep the existing `X-Shotlab: 1` CSRF header and LAN-token checks.

## How the plan is chosen

1. **Findings to training areas.** Each improvement finding maps to areas with weights, scaled by
   confidence: high 1.0, medium 0.7, low 0.3. Low-confidence findings are labelled "possible".
   - `leg_load` → lower-body strength
   - `sequencing` → hip drive
   - `torso` → core
   - `landing` → balance
   - `consistency` → core and balance
   - `arm_extension` and `elbow_alignment` → shoulder and arm

   Two kinds of finding are not training targets:
   - `follow_through` is listed as technique-only (it is practised on court);
   - strengths are shown but not used as targets.
2. **Goals** (jump, stamina, upper body, mobility) add areas, and are labelled as the player's own goal,
   not as a finding.
3. **General fallback.** If there is no usable finding and no goal, the plan says it is general
   basketball support.
4. **Eligibility.** An exercise is used only if all of these hold:
   - **it has a demonstration video**: the catalog maps a `video` and that file exists in `--workout-dir`.
     Text-only catalog entries, and mapped entries whose file is missing, are never prescribed. If the
     folder is missing, no workout can be generated;
   - its equipment was selected (warm-up and cool-down may use equipment-free moves);
   - its level is at or below the player's;
   - its impact is allowed: beginners get no high impact; with pain, only none or low impact and no `power_low`;
   - it does not stress a body area the player asked to avoid.
5. **Ranking.** Primary-area match, demonstration video available, and the player's level. Movement
   families are not repeated.
6. **Structure.**
   - Warm-up: pulse raiser plus mobility for the areas worked.
   - Main block: 4–7 exercises, ordered power → compound → balance → accessory → core → conditioning.
   - Cool-down: stretches for the areas worked.

Each main exercise carries a rationale:
- why it was chosen (the finding title, attempts affected and confidence, or the goal);
- the expected benefit;
- what the evidence cannot show;
- a coaching cue;
- an easier version and a harder version.

Every plan also lists what the app did **not** measure: jump height, shooting power and fitness.

## Duration

```
item seconds = sets × work + (sets − 1) × rest between sets + rest after the item
work         = seconds (timed) or ceil(reps × cadence)   (× 2 for exercises done on each side)
plan total   = sum of item seconds
```

Rests come from `dosing` in the catalog, so they differ by exercise type. For example, compound
strength rests 75–120 s between sets, core rests 30 s, and conditioning rests 20–30 s. The warm-up ends
with a 30 s transition. There is no rest after the last main exercise or after the final item.

The planner never returns less than 20 minutes or less than the requested length. If the plan is too
short, it adds, in order:
1. a stretch, for small gaps;
2. an exercise from the least-covered focus area;
3. a general-support exercise from another area (labelled general);
4. a set of a low-intensity exercise (at most 2 sets when pain is reported);
5. another stretch;
6. easy running in place, if it fits the player's limits.

All of these are video-demonstrated exercises. Very restrictive choices can leave too few video
exercises; for example, avoiding ankle-loading movements together with only one kind of equipment.
In that case the plan is not padded with text-only filler. `POST …/workouts` returns `422` with the
number of minutes that fit and, where one exists, the longest shorter duration that works. If no
video-demonstrated warm-up drill fits, the warm-up uses gentle video-demonstrated stretches instead.

If heavier doses for stronger levels would overshoot the request by more than 3 minutes, it removes
sets or extra stretches. It never removes a focus area's only exercise. Every change is listed under
"Adjustments" in the plan. The "Remaining" time in the player is an estimate that is recomputed from
the plan and the actual position.

## Guided player and voice

- **Demonstration video.** The video is muted, loops during work, and is paused during rest. You can
  replay it or play it at 0.5×. Every prescribed exercise has a video. If a file is deleted after the
  plan was made, or the browser cannot decode it, the written steps are shown for that exercise.
- **Counting.** Repetitions are a *guided count* at the planned cadence. The app does not detect or
  verify the movement, and the summary says so.
- **Voice.** It uses the browser's `speechSynthesis` and has no other dependencies.
  - The exercise name is spoken once, when the exercise starts.
  - During a set, only the last `max(1, ceil(N × 0.10))` numbers are spoken, counting down. For
    N = 50 that is "5, 4, 3, 2, 1"; for N = 10 it is "1".
  - Rest is silent.
  - Pause, skip and end cancel speech. The mute button stops speech.
  - Spoken numbers and announced exercises are saved, so a reload never repeats them.
- **Controls.**
  - During work: Pause/Resume, Set done, Skip set, Skip exercise, End workout.
  - During rest: Skip rest, Add 15 seconds.
- **Saving.** Progress is saved to the server on every change and every few seconds, and on `pagehide`.
  After a reload the workout resumes paused, at the same step.
- **Summary.** It is computed on the server from the per-set records. Each exercise is completed,
  partial, skipped or not reached. Skipped or unreached work is never counted as done. The next-session
  advice follows the feedback (too hard, too easy or pain).

## Safety wording

The plan gives no diagnosis. If pain is reported, it lowers intensity and tells the player to stop and
have the pain assessed before repeating the exercises. It does not claim to fix a shot.

## Editing the catalog

Edit `configs/workout_catalog.json` and restart the server. The catalog is also reloaded when its
modification time changes. Validation fails loudly in these cases:
- unknown equipment, kind, level, impact, area or stress tag;
- a duplicate id;
- empty instructions, cues or mistakes;
- a `video` that is not a relative `.mp4` path inside `workout/`.

`GET /api/sessions/<sid>/workout-context` reports `video_library.missing`, which lists mapped files not
found on disk. Run the catalog test against the real folder with:

```bash
PYTHONPATH=src:. python3 -m pytest -q tests/unit/test_workout_planner.py -k videos
```

## Known limits

- The demonstration videos are H.264 MP4s and should play in Safari and Chrome on macOS. This was not
  verified in the agent's workspace, whose Chromium has no H.264 decoder. The automated tests use
  temporary VP9 stand-ins to check loop and pause logic only.
- Voice was tested with a recording stand-in for `speechSynthesis`. Real audio, voice choice and the
  iOS "speech needs a user gesture first" behaviour must be checked on real devices.
- 203 of the 305 videos are not mapped to catalog entries yet. Mapping more of them, especially
  ankle-friendly and seated options, widens the choices for restrictive limitations. This needs no
  code changes.
- Because only video-demonstrated exercises are used, the 19 text-only catalog entries currently have
  no effect. They become eligible as soon as a matching video is added and mapped.
