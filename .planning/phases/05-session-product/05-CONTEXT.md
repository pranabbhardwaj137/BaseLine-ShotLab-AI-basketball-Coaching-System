# Phase 5 — Developer Model Lab and Annotation Dataset: Context & Decisions

## 1. Phase Objective & Boundary
Build an internal, developer-facing video scrubber and dataset annotation system (`annotation_lab.py`) to create, verify, audit, and export ground-truth datasets for shot-event detection and ball/rim models. 

**Strict Scope Boundary:**
- Scope is strictly internal developer data-tooling and dataset curation quality.
- Does **not** include the final user-facing app, cloud storage, or team task allocations.
- Follows the data integrity principles of [AGENTS.md](file:///c:/Users/bhard/Downloads/major_pro/major_pro/basketball_proj/AGENTS.md).

---

## 2. Division of Labor

### 2.1 Manual Developer Work (Human-in-the-Loop)
1. **Footage Provision & Provenance:**
   - Supply permitted real-world video clips across diverse players, shot styles, lighting, and camera views.
   - Document metadata: `player_id`, camera view (`side_90`, `oblique_45`, `frontal`), capture distance, FPS, resolution, and rights/consent status.
2. **Annotation & Verification:**
   - Identify and mark ground-truth shot events (`start`, `dip`, `set`, `release`, `follow_through`).
   - Identify and mark ground-truth shot outcomes (`make`, `miss`, `unknown`) and rim contact.
   - Mark non-shot intervals (hard negatives) across the 8-class action taxonomy.
   - Reconcile multi-annotator disagreements and approve final annotations per clip.
3. **Dataset Splits Approval:**
   - Assign and approve player- and session-separated splits (`train`, `val`, `test`).
   - Verify that no adjacent frames or sessions from the same player cross between train and test splits.

### 2.2 Coding-Agent Work (Software & Tooling)
1. **Interactive Scrubber Tool (`annotation_lab.py`):**
   - High-performance OpenCV HighGUI desktop window with frame-accurate stepping, timeline slider, and hotkey controls.
   - Fast bi-directional frame scrubbing without transcoding delays.
2. **Dual-Lane Timeline Visualization:**
   - Lane 1 (Machine Proposals - Cyan): Renders heuristic detector candidate intervals.
   - Lane 2 (Human Ground Truth - Amber): Renders human-verified boundaries.
   - Actions to accept a proposal into human lane, nudge boundaries, or discard proposals without mutating raw machine outputs.
3. **Database Schema & Persistence (`shot_lab_db.py`):**
   - Extend SQLite schema with `labeled_clips` and `labeled_intervals` tables.
   - Decouple immutable machine proposals from human-reviewed ground truth.
4. **Dataset Export & Manifest CLI (`export_dataset.py`):**
   - Export versioned `dataset_manifest.json` and JSONL datasets with SHA256 file hashes, splits, and event schemas.
5. **Automated QA & Integrity Validator (`validate_dataset.py`):**
   - Validate temporal ordering, interval bounds within video duration, class consistency, and player-split isolation.

---

## 3. Locked Decisions & Design Contracts

### 3.1 Scrubber UI Architecture (Decision 1: OpenCV HighGUI)
- Implemented as a standalone script: `annotation_lab.py`.
- Native desktop OpenCV window (`cv2.imshow`, `cv2.setMouseCallback`, `cv2.createTrackbar`).
- Zero additional heavy dependencies; low-latency scrubbing on 1080p/720p 30/60 FPS footage.
- **Keyboard Controls Contract:**
  - `Space`: Play / Pause playback.
  - `.` / `,`: Step forward / backward by 1 frame.
  - `>` / `<` (`Shift+.` / `Shift+,`): Step forward / backward by 10 frames.
  - `[` / `]`: Mark interval start frame / end frame.
  - `S`: Commit marked interval as Shot Event (prompts for boundaries / outcome).
  - `N`: Commit marked interval as Hard Negative (prompts for action class).
  - `A`: Accept active machine proposal into human lane.
  - `D`: Discard active machine proposal.
  - `U`: Undo last human annotation.
  - `R`: Refresh / re-run detector on current clip.
  - `Q`: Save and exit.

### 3.2 Hard-Negative Action Taxonomy (Decision 2: Comprehensive 8 Classes)
Every non-shot interval must be categorized into one of 8 standardized classes:
1. `dribble_drive`: Advancing or dynamic ball handling (dribble moves, crossovers, pull-up gathers).
2. `gather_no_shot`: Two-handed ball gather or dip that terminates without an upward release (e.g. pivot, pass setup).
3. `pass`: Chest, bounce, overhead, or kick-out pass.
4. `pump_fake`: Upward shooting fake motion where player retains ball or resets.
5. `rebound`: Ball pursuit and catch off the rim or backboard.
6. `defensive_contest`: Closeout, shot block contest, or defensive slide.
7. `catch_and_hold`: Receiving pass into stationary triple-threat or ball hold.
8. `idle_reset`: Walking, jogging, standing, or resetting between repetitions.

### 3.3 Dual-Lane Timeline & Proposal Workflow (Decision 3: Separate Cyan/Amber Lanes)
- **Machine Lane (Cyan):**
  - Displays intervals detected by `analyzer.py` / heuristic state machine.
  - Displays proposed `dip`, `set`, and `release` frames.
  - Strictly immutable: records `detector_name`, `version`, `confidence`, and detected frames.
- **Human Lane (Amber):**
  - Displays human-verified ground-truth shot events and hard negative intervals.
  - Supports fine-tuning: nudging release frame forward/backward, tagging outcome (`make` / `miss` / `unknown`), and annotating rim contact.
  - Stored with `annotator_id`, `review_status: "verified"`, and `timestamp`.

### 3.4 Data Persistence & Manifest Schema (Decision 4: Extended SQLite & JSON Export)
- Extended SQLite tables in `shot_lab.db`:
  - `labeled_clips`: `clip_id`, `file_path`, `file_sha256`, `player_id`, `camera_view`, `fps`, `frame_count`, `width`, `height`, `split`, `license`.
  - `labeled_intervals`: `interval_id`, `clip_id`, `interval_type` (`shot` | `hard_negative`), `action_class`, `start_frame`, `end_frame`, `dip_frame`, `set_frame`, `release_frame`, `outcome` (`make` | `miss` | `unknown`), `rim_contact`, `occluded_lower`, `occluded_upper`, `annotator_id`, `created_at`.
  - `machine_proposals`: `proposal_id`, `clip_id`, `start_frame`, `end_frame`, `dip_frame`, `release_frame`, `detector_version`, `status` (`proposed`, `accepted`, `rejected`).
- **Export CLI (`export_dataset.py`):**
  - Emits `DATASET_MANIFEST.json` and `annotations.jsonl` matching project schema.

---

## 4. Data Integrity & AGENTS.md Governance Rules

1. **No Synthetic Data in Production Manifests:**
   - Synthetic fixtures are restricted to `test_*.py` unit tests and must be explicitly marked `synthetic: true`.
   - Never write synthetic frames or mock shots into `DATASET_MANIFEST.json` or public evaluation reports.
2. **Missing Video Fail-Fast Protocol:**
   - If a clip referenced in the manifest or database is not found on disk, the system must immediately stop dependent processing.
   - Display the exact missing file path and give the user the concrete local command / folder path where the clip must be placed.
3. **Split Separation Rule:**
   - Splits (`train`, `val`, `test`) are partitioned strictly by **`player_id` and recording session**.
   - Under no circumstances may adjacent frames from the same video clip be partitioned across train and test sets.
4. **No Self-Validating Claims:**
   - Unlabeled video frames cannot be counted as true positives or true negatives.
   - Model accuracy cannot be reported without human ground-truth labels covering evaluated frames.

---

## 5. Acceptance Checks & QA Verification

The implementation of Phase 5 must pass the following acceptance checks:
1. **Interactive Scrubber Verification:**
   - Can load a 30 FPS / 60 FPS video clip, scrub to any arbitrary frame, play/pause, and step frame-by-frame with zero crash or state desync.
2. **Dual-Lane Provenance Integrity:**
   - Ingesting a machine proposal and editing it creates an independent human annotation record while leaving the machine proposal record identical and intact.
3. **Hard-Negative Coverage:**
   - Can annotate intervals from all 8 negative classes and retrieve them with correct frame bounds.
4. **Temporal Ordering & Constraint Enforcement (`validate_dataset.py`):**
   - Rejects intervals where $start > end$.
   - Rejects shot events where $start > dip$, $dip > set$, or $set > release$.
   - Rejects intervals exceeding video frame bounds ($end \ge total\_frames$).
   - Flags overlapping intervals for the same player.
5. **Split Leakage Check:**
   - Automated check confirms $Set(Players_{train}) \cap Set(Players_{test}) = \emptyset$.
6. **Reproducibility Test:**
   - Running `export_dataset.py` on test database produces deterministic JSONL records with matching SHA256 checksums.
