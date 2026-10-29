"""
shot_lab_db.py - Personal Shot Lab SQLite Persistence and Provenance Engine.

Provides versioned schema management, separate tracking for machine predictions
and human-corrected annotations, context grouping, and remediation logs.
"""

from __future__ import annotations
import sqlite3
import datetime
import uuid
import json
from typing import Dict, Any, List, Optional, Tuple

import contextlib
import hashlib, base64, os, secrets, re

from basketball.configs.shot_types import CONFIG_VERSION, resolve_shot_type

SCHEMA_VERSION = 9

TAXONOMY_HARD_NEGATIVES = [
    "dribble_drive",
    "gather_no_shot",
    "pass",
    "pump_fake",
    "rebound",
    "defensive_contest",
    "catch_and_hold",
    "idle_reset",
]
TAXONOMY_ALL_ACTIONS = ["shot_event"] + TAXONOMY_HARD_NEGATIVES

class ShotLabDB:
    def __init__(self, db_path: str = "shot_lab.db"):
        self.db_path = db_path
        self.init_db()

    @contextlib.contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()


    def init_db(self) -> None:
        """Initialize SQLite database tables with versioned schema."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Schema metadata
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            cursor.execute("SELECT value FROM schema_meta WHERE key = 'version'")
            row = cursor.fetchone()
            if not row:
                cursor.execute("INSERT INTO schema_meta (key, value) VALUES ('version', ?)", (str(SCHEMA_VERSION),))
            elif int(row[0]) < SCHEMA_VERSION:
                cursor.execute("UPDATE schema_meta SET value = ? WHERE key = 'version'", (str(SCHEMA_VERSION),))

            # Players
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS players (
                    player_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    height_m REAL,
                    wingspan_m REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Users & Authentication
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    player_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    skill_level TEXT DEFAULT 'intermediate',
                    handedness TEXT DEFAULT 'right',
                    shot_style TEXT DEFAULT 'jump_shot',
                    height_cm REAL,
                    wingspan_cm REAL,
                    goals TEXT,
                    pain_reported INTEGER DEFAULT 0,
                    onboarding_completed INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (player_id) REFERENCES players (player_id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_sessions (
                    token TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            """)

            # Sessions
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    player_id TEXT NOT NULL,
                    camera_view TEXT NOT NULL, -- 'frontal', 'side_90', 'oblique_45'
                    shot_type TEXT NOT NULL,   -- 'catch_and_shoot', 'off_dribble', 'free_throw'
                    shot_type_id TEXT DEFAULT 'catch_and_shoot',
                    shot_style TEXT DEFAULT 'jump_shot', -- 'jump_shot', 'set_shot'
                    fps REAL DEFAULT 30.0,
                    model_version TEXT,
                    rim_anchor TEXT,
                    rim_source TEXT DEFAULT 'auto',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    notes TEXT,
                    FOREIGN KEY (player_id) REFERENCES players (player_id)
                )
            """)

            # Shots (Preserves machine predictions and human annotations separately)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS shots (
                    shot_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    player_id TEXT NOT NULL,
                    camera_view TEXT NOT NULL,
                    shot_type TEXT NOT NULL,
                    shot_type_id TEXT DEFAULT 'catch_and_shoot',
                    shot_style TEXT DEFAULT 'jump_shot',
                    config_version TEXT,
                    detector_profile_id TEXT,

                    -- Machine detected event boundaries (Immutable from capture)
                    machine_start_frame INTEGER,
                    machine_dip_frame INTEGER,
                    machine_set_frame INTEGER,
                    machine_release_frame INTEGER,
                    machine_end_frame INTEGER,

                    -- Human annotated/corrected event boundaries
                    annotated_start_frame INTEGER,
                    annotated_dip_frame INTEGER,
                    annotated_set_frame INTEGER,
                    annotated_release_frame INTEGER,
                    annotated_end_frame INTEGER,

                    -- Outcome & Provenance
                    outcome TEXT DEFAULT 'unknown',       -- 'make', 'miss', 'unknown'
                    outcome_source TEXT DEFAULT 'unlabeled', -- 'live_hotkey', 'manual_review', 'unlabeled'
                    review_status TEXT DEFAULT 'quarantined', -- 'quarantined', 'approved', 'discarded'
                    review_notes TEXT,

                    -- Tracking Confidence & Quality Gates
                    tracking_confidence TEXT NOT NULL,    -- 'SUFFICIENT', 'INSUFFICIENT'
                    valid_frame_ratio REAL DEFAULT 1.0,

                    -- 3D World Space Biomechanics (Estimates in meters)
                    knee_angle_dip_3d REAL,
                    elbow_angle_release_3d REAL,
                    release_height_rel_m REAL,

                    -- 2D Image Space Biomechanics & Foreshortening
                    elbow_angle_release_2d REAL,
                    foreshortening_discrepancy_deg REAL,

                    -- Kinetic Sequencing
                    sequence_lag_ms REAL,
                    sequence_order_valid INTEGER DEFAULT 1,
                    torso_sway_deg REAL,

                    -- Raw reference
                    raw_landmarks_ref TEXT,

                    -- Advisory / Shadow Ball & Rim Outcome Tracking (Phase 7 & 8)
                    automated_outcome TEXT DEFAULT 'unknown',
                    automated_outcome_conf REAL DEFAULT 0.0,
                    p_make REAL,
                    outcome_confidence REAL,
                    evidence_quality REAL,
                    outcome_reason TEXT,
                    outcome_features TEXT,
                    estimator_version TEXT,
                    estimator_cfg_hash TEXT,
                    trajectory_fit_r2 REAL,
                    entry_angle_deg REAL,
                    ball_coverage_ratio REAL DEFAULT 0.0,
                    ball_model_version TEXT,

                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES sessions (session_id),
                    FOREIGN KEY (player_id) REFERENCES players (player_id)
                )
            """)

            # Baselines (Descriptive associations for matched player/view/type/style)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS baselines (
                    baseline_id TEXT PRIMARY KEY,
                    player_id TEXT NOT NULL,
                    camera_view TEXT NOT NULL,
                    shot_type TEXT NOT NULL,
                    shot_type_id TEXT DEFAULT 'catch_and_shoot',
                    shot_style TEXT DEFAULT 'jump_shot',
                    sample_size_makes INTEGER NOT NULL,
                    sample_size_misses INTEGER NOT NULL,
                    sample_size_total INTEGER DEFAULT 0,

                    -- Descriptive distributions (mean and sample std dev)
                    mean_elbow_release_make REAL,
                    std_elbow_release_make REAL,
                    mean_elbow_release_miss REAL,
                    std_elbow_release_miss REAL,
                    mean_elbow_release_all REAL,
                    std_elbow_release_all REAL,

                    mean_sequence_lag_make REAL,
                    std_sequence_lag_make REAL,
                    mean_sequence_lag_miss REAL,
                    std_sequence_lag_miss REAL,
                    mean_sequence_lag_all REAL,
                    std_sequence_lag_all REAL,

                    mean_knee_dip_make REAL,
                    std_knee_dip_make REAL,
                    mean_knee_dip_miss REAL,
                    std_knee_dip_miss REAL,
                    mean_knee_dip_all REAL,
                    std_knee_dip_all REAL,

                    mean_torso_sway_make REAL,
                    std_torso_sway_make REAL,
                    mean_torso_sway_miss REAL,
                    std_torso_sway_miss REAL,
                    mean_torso_sway_all REAL,
                    std_torso_sway_all REAL,

                    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (player_id) REFERENCES players (player_id)
                )
            """)

            # Remediations (One-Cue-at-a-Time practice loop)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS remediations (
                    remediation_id TEXT PRIMARY KEY,
                    player_id TEXT NOT NULL,
                    baseline_id TEXT,
                    shot_style TEXT DEFAULT 'jump_shot',
                    targeted_flaw TEXT NOT NULL,
                    priority_tier INTEGER NOT NULL, -- 1=Sequencing, 2=Release, 3=Stability
                    recommended_drill TEXT NOT NULL,
                    drill_reps INTEGER DEFAULT 10,
                    drill_completed INTEGER DEFAULT 0,
                    pre_drill_metric_mean REAL,
                    pre_drill_metric_std REAL,
                    post_drill_metric_mean REAL,
                    post_drill_metric_std REAL,
                    pre_make_count INTEGER DEFAULT 0,
                    pre_total_count INTEGER DEFAULT 0,
                    post_make_count INTEGER DEFAULT 0,
                    post_total_count INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'active',   -- 'active', 'completed', 'dismissed'
                    feedback_notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (player_id) REFERENCES players (player_id),
                    FOREIGN KEY (baseline_id) REFERENCES baselines (baseline_id)
                )
            """)

            # -------------------------------------------------------------
            # Phase 5: Developer Model Lab & Annotation Ground Truth Schema
            # -------------------------------------------------------------
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS labeled_clips (
                    clip_id TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    file_sha256 TEXT,
                    player_id TEXT NOT NULL,
                    camera_view TEXT NOT NULL,
                    shot_type_id TEXT DEFAULT 'catch_and_shoot',
                    shot_style TEXT DEFAULT 'jump_shot',
                    fps REAL DEFAULT 30.0,
                    frame_count INTEGER,
                    width INTEGER,
                    height INTEGER,
                    split TEXT DEFAULT 'train', -- 'train', 'val', 'test'
                    license TEXT DEFAULT 'private_project',
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS machine_proposals (
                    proposal_id TEXT PRIMARY KEY,
                    clip_id TEXT NOT NULL,
                    detector_name TEXT NOT NULL,
                    detector_version TEXT NOT NULL,
                    start_frame INTEGER,
                    end_frame INTEGER,
                    dip_frame INTEGER,
                    set_frame INTEGER,
                    release_frame INTEGER,
                    confidence REAL,
                    status TEXT DEFAULT 'proposed', -- 'proposed', 'accepted', 'discarded'
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (clip_id) REFERENCES labeled_clips (clip_id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS labeled_intervals (
                    interval_id TEXT PRIMARY KEY,
                    clip_id TEXT NOT NULL,
                    interval_type TEXT NOT NULL, -- 'shot', 'hard_negative'
                    action_class TEXT NOT NULL,  -- 'shot_event' or 8 hard-negative classes
                    start_frame INTEGER NOT NULL,
                    end_frame INTEGER NOT NULL,
                    dip_frame INTEGER,
                    set_frame INTEGER,
                    release_frame INTEGER,
                    follow_through_frame INTEGER,
                    outcome TEXT DEFAULT 'unknown', -- 'make', 'miss', 'unknown', 'none'
                    rim_contact TEXT,
                    occluded_lower INTEGER DEFAULT 0,
                    occluded_upper INTEGER DEFAULT 0,
                    annotator_id TEXT DEFAULT 'human_reviewer',
                    review_status TEXT DEFAULT 'verified', -- 'draft', 'verified'
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (clip_id) REFERENCES labeled_clips (clip_id)
                )
            """)

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_intervals_clip ON labeled_intervals (clip_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_proposals_clip ON machine_proposals (clip_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_clips_split ON labeled_clips (split)")

            # Phase 8: append-only audit trail for human review edits.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS shot_review_history (
                    review_id TEXT PRIMARY KEY,
                    shot_id TEXT NOT NULL,
                    reviewer_id TEXT NOT NULL DEFAULT 'local_user',
                    previous_values_json TEXT NOT NULL,
                    updated_values_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (shot_id) REFERENCES shots (shot_id)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_review_history_shot ON shot_review_history (shot_id, created_at)")

            # Phase 8: player-selected weekly practice target, stored locally.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS player_app_settings (
                    player_id TEXT PRIMARY KEY,
                    weekly_session_target INTEGER NOT NULL DEFAULT 3,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (player_id) REFERENCES players (player_id)
                )
            """)

            # 08-07 (schema v7): measured shooting analysis, session quality/consistency,
            # and the persisted coaching report. All are derived from the pose cache and
            # shot rows; they never modify machine or human shot fields.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS attempt_analysis (
                    shot_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    analysis_version TEXT NOT NULL,
                    boundaries_key TEXT NOT NULL,
                    analysis_json TEXT NOT NULL,
                    config_version TEXT,
                    detector_profile_id TEXT,
                    shot_type_id TEXT,
                    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (shot_id) REFERENCES shots (shot_id)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_attempt_analysis_session ON attempt_analysis (session_id)")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS session_analysis (
                    session_id TEXT PRIMARY KEY,
                    analysis_version TEXT NOT NULL,
                    input_key TEXT NOT NULL,
                    analysis_json TEXT NOT NULL,
                    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS session_reports (
                    session_id TEXT PRIMARY KEY,
                    report_version TEXT NOT NULL,
                    input_key TEXT NOT NULL,
                    report_json TEXT NOT NULL,
                    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 09 (schema v8): Personalized Workout Coach. One row per generated plan, always tied to
            # the shooting session whose report it was built from. JSON columns hold the plan, the
            # resumable player state, recorded set-level progress, feedback and the final summary.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS workout_plans (
                    workout_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    player_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'planned',
                    plan_version TEXT NOT NULL,
                    preferences_json TEXT NOT NULL,
                    findings_json TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    planned_duration_s INTEGER NOT NULL,
                    state_json TEXT,
                    progress_json TEXT,
                    feedback_json TEXT,
                    summary_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP,
                    ended_at TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES sessions (session_id)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_workout_plans_session ON workout_plans (session_id)")

            # Run column migration checks for backwards compatibility
            self._migrate_columns(cursor)
            conn.commit()

    def _migrate_columns(self, cursor: sqlite3.Cursor) -> None:
        """Add missing columns to existing tables if schema was initialized earlier."""
        table_columns = {
            "users": [("pain_reported", "INTEGER DEFAULT 0")],
            "sessions": [
                ("shot_style", "TEXT DEFAULT 'jump_shot'"),
                ("shot_type_id", "TEXT DEFAULT 'catch_and_shoot'"),
                ("rim_anchor", "TEXT"),
                ("rim_source", "TEXT DEFAULT 'auto'"),
            ],
            "shots": [
                ("shot_style", "TEXT DEFAULT 'jump_shot'"),
                ("shot_type_id", "TEXT DEFAULT 'catch_and_shoot'"),
                ("config_version", "TEXT"),
                ("detector_profile_id", "TEXT"),
                ("review_status", "TEXT DEFAULT 'quarantined'"),
                ("automated_outcome", "TEXT DEFAULT 'unknown'"),
                ("automated_outcome_conf", "REAL DEFAULT 0.0"),
                ("p_make", "REAL"),
                ("outcome_confidence", "REAL"),
                ("evidence_quality", "REAL"),
                ("outcome_reason", "TEXT"),
                ("outcome_features", "TEXT"),
                ("estimator_version", "TEXT"),
                ("estimator_cfg_hash", "TEXT"),
                ("trajectory_fit_r2", "REAL"),
                ("entry_angle_deg", "REAL"),
                ("ball_coverage_ratio", "REAL DEFAULT 0.0"),
                ("ball_model_version", "TEXT"),
            ],
            "baselines": [
                ("shot_style", "TEXT DEFAULT 'jump_shot'"),
                ("shot_type_id", "TEXT DEFAULT 'catch_and_shoot'"),
                ("sample_size_total", "INTEGER DEFAULT 0"),
                ("mean_elbow_release_all", "REAL"),
                ("std_elbow_release_all", "REAL"),
                ("mean_sequence_lag_all", "REAL"),
                ("std_sequence_lag_all", "REAL"),
                ("mean_knee_dip_all", "REAL"),
                ("std_knee_dip_all", "REAL"),
                ("mean_torso_sway_all", "REAL"),
                ("std_torso_sway_all", "REAL"),
            ],
            "labeled_clips": [
                ("shot_type_id", "TEXT DEFAULT 'catch_and_shoot'"),
            ],
            "attempt_analysis": [
                ("config_version", "TEXT"),
                ("detector_profile_id", "TEXT"),
                ("shot_type_id", "TEXT"),
            ],
            "remediations": [
                ("shot_style", "TEXT DEFAULT 'jump_shot'"),
                ("drill_completed", "INTEGER DEFAULT 0"),
                ("pre_drill_metric_std", "REAL"),
                ("post_drill_metric_std", "REAL"),
                ("pre_make_count", "INTEGER DEFAULT 0"),
                ("pre_total_count", "INTEGER DEFAULT 0"),
                ("post_make_count", "INTEGER DEFAULT 0"),
                ("post_total_count", "INTEGER DEFAULT 0"),
            ]
        }
        for table, cols in table_columns.items():
            cursor.execute(f"PRAGMA table_info({table})")
            existing = {row[1] for row in cursor.fetchall()}
            for col_name, col_def in cols:
                if col_name not in existing:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")

        # Backfill shot_type_id mapping: off_the_dribble/off_dribble -> pull_up, unknown -> other
        cursor.execute("""
            UPDATE sessions
            SET shot_type_id = CASE
                WHEN shot_type IN ('off_the_dribble', 'off_dribble') THEN 'pull_up'
                WHEN shot_type IS NULL OR shot_type = '' THEN 'other'
                ELSE shot_type
            END
            WHERE shot_type_id IS NULL OR shot_type_id = '' OR (shot_type_id = 'catch_and_shoot' AND shot_type != 'catch_and_shoot')
        """)
        cursor.execute("""
            UPDATE shots
            SET shot_type_id = CASE
                WHEN shot_type IN ('off_the_dribble', 'off_dribble') THEN 'pull_up'
                WHEN shot_type IS NULL OR shot_type = '' THEN 'other'
                ELSE shot_type
            END
            WHERE shot_type_id IS NULL OR shot_type_id = '' OR (shot_type_id = 'catch_and_shoot' AND shot_type != 'catch_and_shoot')
        """)
        cursor.execute("""
            UPDATE baselines
            SET shot_type_id = CASE
                WHEN shot_type IN ('off_the_dribble', 'off_dribble') THEN 'pull_up'
                WHEN shot_type IS NULL OR shot_type = '' THEN 'other'
                ELSE shot_type
            END
            WHERE shot_type_id IS NULL OR shot_type_id = '' OR (shot_type_id = 'catch_and_shoot' AND shot_type != 'catch_and_shoot')
        """)
        cursor.execute("""
            UPDATE labeled_clips
            SET shot_type_id = 'catch_and_shoot'
            WHERE shot_type_id IS NULL OR shot_type_id = ''
        """)


    def upsert_player(self, player_id: str, name: str, height_m: Optional[float] = None, wingspan_m: Optional[float] = None) -> str:
        """Register or update player profile."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO players (player_id, name, height_m, wingspan_m)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(player_id) DO UPDATE SET
                    name = excluded.name,
                    height_m = COALESCE(excluded.height_m, players.height_m),
                    wingspan_m = COALESCE(excluded.wingspan_m, players.wingspan_m)
            """, (player_id, name, height_m, wingspan_m))
            conn.commit()
            return player_id

    def get_player(self, player_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a player record by player_id."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM players WHERE player_id = ?", (player_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def create_session(
        self,
        session_id: Optional[str] = None,
        player_id: str = "default_player",
        camera_view: str = "frontal",
        shot_type: str = "catch_and_shoot",
        shot_style: str = "jump_shot",
        fps: float = 30.0,
        model_version: str = "1.0.0",
        notes: Optional[str] = None,
        shot_type_id: Optional[str] = None,
    ) -> str:
        """Create a new shot analysis session."""
        if not session_id:
            session_id = f"sess_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:6]}"

        canon_shot_type = resolve_shot_type(shot_type_id or shot_type)

        # Ensure player exists
        self.upsert_player(player_id, player_id)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO sessions (session_id, player_id, camera_view, shot_type, shot_type_id, shot_style, fps, model_version, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (session_id, player_id, camera_view, shot_type, canon_shot_type, shot_style, fps, model_version, notes))
            conn.commit()
            return session_id

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Fetch persisted session context for the local insights service."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
            return dict(row) if row else None

    def delete_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Delete one player's session, shots, review audit, and session-linked drills."""
        with self._get_connection() as conn:
            session_row = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if not session_row:
                return None
            session = dict(session_row)
            shot_rows = conn.execute(
                "SELECT shot_id FROM shots WHERE session_id = ?", (session_id,)
            ).fetchall()
            shot_ids = [row[0] for row in shot_rows]
            if shot_ids:
                placeholders = ",".join("?" for _ in shot_ids)
                conn.execute(
                    f"DELETE FROM shot_review_history WHERE shot_id IN ({placeholders})", shot_ids
                )
                conn.execute(f"DELETE FROM shots WHERE shot_id IN ({placeholders})", shot_ids)
            remediation_rows = conn.execute(
                "SELECT remediation_id, feedback_notes FROM remediations WHERE player_id = ?",
                (session["player_id"],),
            ).fetchall()
            for remediation in remediation_rows:
                try:
                    notes = json.loads(remediation["feedback_notes"] or "{}")
                except (TypeError, json.JSONDecodeError):
                    notes = {}
                if session_id in {notes.get("source_session_id"), notes.get("follow_up_session_id")}:
                    conn.execute("DELETE FROM remediations WHERE remediation_id = ?", (remediation["remediation_id"],))
            for table in ("attempt_analysis", "session_analysis", "session_reports", "workout_plans"):
                conn.execute(f"DELETE FROM {table} WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            conn.commit()
            return session

    # ------------------------------------------------------------------ 09 workout plans
    _WORKOUT_JSON = ("preferences", "findings", "plan", "state", "progress", "feedback", "summary")

    def _workout_row(self, row) -> Optional[Dict[str, Any]]:
        if not row:
            return None
        record = dict(row)
        for key in self._WORKOUT_JSON:
            raw = record.pop(f"{key}_json", None)
            try:
                record[key] = json.loads(raw) if raw else None
            except (TypeError, json.JSONDecodeError):
                record[key] = None
        return record

    def save_workout_plan(self, workout_id: str, session_id: str, player_id: str, plan: Dict[str, Any],
                          preferences: Dict[str, Any], findings: Any) -> None:
        with self._get_connection() as conn:
            conn.execute(
                "INSERT INTO workout_plans (workout_id, session_id, player_id, status, plan_version, preferences_json, "
                "findings_json, plan_json, planned_duration_s) VALUES (?, ?, ?, 'planned', ?, ?, ?, ?, ?)",
                (workout_id, session_id, player_id, plan.get("plan_version", ""), json.dumps(preferences),
                 json.dumps(findings), json.dumps(plan), int(plan["duration"]["total_s"])),
            )
            conn.commit()

    def get_workout_plan(self, workout_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM workout_plans WHERE workout_id = ?", (workout_id,)).fetchone()
        return self._workout_row(row)

    def list_workout_plans(self, session_id: str) -> list:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT workout_id, session_id, player_id, status, planned_duration_s, created_at, started_at, ended_at, "
                "updated_at, plan_json, summary_json FROM workout_plans WHERE session_id = ? ORDER BY created_at DESC, rowid DESC",
                (session_id,)).fetchall()
        out = []
        for row in rows:
            record = dict(row)
            plan = json.loads(record.pop("plan_json") or "{}")
            summary = json.loads(record.pop("summary_json") or "null")
            record["title"] = plan.get("title")
            record["summary"] = summary
            out.append(record)
        return out

    def update_workout_progress(self, workout_id: str, *, status: str, state: Any, progress: Any,
                                feedback: Any = None, summary: Any = None, started: bool = False,
                                ended: bool = False) -> None:
        """Write player state/progress in one statement; start/end timestamps are set once, server-side."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE workout_plans SET status = ?, state_json = ?, progress_json = ?, "
                "feedback_json = COALESCE(?, feedback_json), summary_json = COALESCE(?, summary_json), "
                "started_at = CASE WHEN ? AND started_at IS NULL THEN CURRENT_TIMESTAMP ELSE started_at END, "
                "ended_at = CASE WHEN ? AND ended_at IS NULL THEN CURRENT_TIMESTAMP ELSE ended_at END, "
                "updated_at = CURRENT_TIMESTAMP WHERE workout_id = ?",
                (status, json.dumps(state), json.dumps(progress), json.dumps(feedback) if feedback is not None else None,
                 json.dumps(summary) if summary is not None else None, int(started), int(ended), workout_id),
            )
            conn.commit()

    def delete_workout_plan(self, workout_id: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM workout_plans WHERE workout_id = ?", (workout_id,))
            conn.commit()
            return cursor.rowcount > 0

    # ------------------------------------------------------------------ 08-07 analysis store
    def save_session_analysis(self, session_id: str, analysis: Dict[str, Any], input_key: str) -> None:
        """Replace the stored analysis for a session and its attempts in one transaction."""
        attempts = analysis.get("attempts", [])
        config_ver = analysis.get("config_version") or CONFIG_VERSION
        detector_prof = analysis.get("detector_profile_id")
        shot_type_id = resolve_shot_type(analysis.get("shot_type_id") or analysis.get("shot_type"))
        with self._get_connection() as conn:
            conn.execute("DELETE FROM attempt_analysis WHERE session_id = ?", (session_id,))
            for attempt in attempts:
                if not attempt.get("shot_id"):
                    continue
                key = f"{attempt.get('start_frame')}:{attempt.get('release_frame')}:{attempt.get('end_frame')}"
                att_cver = attempt.get("config_version") or config_ver
                att_dprof = attempt.get("detector_profile_id") or detector_prof
                att_stid = attempt.get("shot_type_id") or shot_type_id
                conn.execute(
                    "INSERT OR REPLACE INTO attempt_analysis (shot_id, session_id, analysis_version, boundaries_key, analysis_json, config_version, detector_profile_id, shot_type_id, computed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
                    (attempt["shot_id"], session_id, analysis.get("analysis_version", ""), key, json.dumps(attempt), att_cver, att_dprof, att_stid),
                )
            conn.execute(
                "INSERT OR REPLACE INTO session_analysis (session_id, analysis_version, input_key, analysis_json, computed_at) "
                "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
                (session_id, analysis.get("analysis_version", ""), input_key, json.dumps(analysis)),
            )
            conn.commit()

    def get_session_analysis(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM session_analysis WHERE session_id = ?", (session_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["analysis"] = json.loads(result.pop("analysis_json"))
        return result

    def save_session_report(self, session_id: str, report: Dict[str, Any], input_key: str, version: str) -> None:
        with self._get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO session_reports (session_id, report_version, input_key, report_json, generated_at) "
                "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
                (session_id, version, input_key, json.dumps(report)),
            )
            conn.commit()

    def get_session_report(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM session_reports WHERE session_id = ?", (session_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["report"] = json.loads(result.pop("report_json"))
        return result

    def get_weekly_session_target(self, player_id: str) -> int:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT weekly_session_target FROM player_app_settings WHERE player_id = ?",
                (player_id,),
            ).fetchone()
        return int(row[0]) if row else 3

    def set_weekly_session_target(self, player_id: str, target: int) -> None:
        if isinstance(target, bool) or not isinstance(target, int) or not 1 <= target <= 7:
            raise ValueError("Weekly session target must be an integer from 1 through 7")
        self.upsert_player(player_id, player_id)
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO player_app_settings (player_id, weekly_session_target, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(player_id) DO UPDATE SET
                    weekly_session_target = excluded.weekly_session_target,
                    updated_at = CURRENT_TIMESTAMP
            """, (player_id, target))
            conn.commit()

    def save_shot(self, shot_data: Dict[str, Any]) -> str:
        """
        Persist a shot record. Preserves machine predictions and initializes
        annotated boundaries with machine values.
        """
        shot_id = shot_data.get("shot_id") or f"shot_{str(uuid.uuid4())[:8]}"
        now = datetime.datetime.now().isoformat()

        m_start = shot_data.get("start_frame") or shot_data.get("machine_start_frame")
        m_dip = shot_data.get("dip_frame") or shot_data.get("machine_dip_frame")
        m_set = shot_data.get("set_frame") or shot_data.get("machine_set_frame")
        m_release = shot_data.get("release_frame") or shot_data.get("machine_release_frame")
        m_end = shot_data.get("end_frame") or shot_data.get("machine_end_frame")

        a_start = shot_data.get("annotated_start_frame", m_start)
        a_dip = shot_data.get("annotated_dip_frame", m_dip)
        a_set = shot_data.get("annotated_set_frame", m_set)
        a_release = shot_data.get("annotated_release_frame", m_release)
        a_end = shot_data.get("annotated_end_frame", m_end)

        outcome = shot_data.get("outcome", "unknown").lower()
        if outcome not in ("make", "miss", "unknown"):
            outcome = "unknown"

        outcome_source = shot_data.get("outcome_source", "unlabeled")
        shot_style = shot_data.get("shot_style", "jump_shot")

        # Determine default review_status
        review_status = shot_data.get("review_status")
        if not review_status:
            if outcome_source == "live_hotkey" and outcome in ("make", "miss"):
                review_status = "approved"
            else:
                review_status = "quarantined"

        tracking_conf = shot_data.get("tracking_confidence", "SUFFICIENT")

        st_raw = shot_data.get("shot_type", "catch_and_shoot")
        st_id = resolve_shot_type(shot_data.get("shot_type_id") or st_raw)
        cfg_ver = shot_data.get("config_version") or CONFIG_VERSION
        det_prof_id = shot_data.get("detector_profile_id")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO shots (
                    shot_id, session_id, player_id, camera_view, shot_type, shot_type_id, shot_style,
                    config_version, detector_profile_id,
                    machine_start_frame, machine_dip_frame, machine_set_frame, machine_release_frame, machine_end_frame,
                    annotated_start_frame, annotated_dip_frame, annotated_set_frame, annotated_release_frame, annotated_end_frame,
                    outcome, outcome_source, review_status, review_notes,
                    tracking_confidence, valid_frame_ratio,
                    knee_angle_dip_3d, elbow_angle_release_3d, release_height_rel_m,
                    elbow_angle_release_2d, foreshortening_discrepancy_deg,
                    sequence_lag_ms, sequence_order_valid, torso_sway_deg,
                    raw_landmarks_ref,
                    automated_outcome, automated_outcome_conf,
                    p_make, outcome_confidence, evidence_quality,
                    outcome_reason, outcome_features,
                    estimator_version, estimator_cfg_hash,
                    trajectory_fit_r2, entry_angle_deg,
                    ball_coverage_ratio, ball_model_version,
                    created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?,
                    ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?,
                    ?, ?, ?,
                    ?, ?,
                    ?, ?, ?,
                    ?,
                    ?, ?,
                    ?, ?, ?,
                    ?, ?,
                    ?, ?,
                    ?, ?,
                    ?, ?,
                    ?, ?
                )
            """, (
                shot_id,
                shot_data.get("session_id", "default_session"),
                shot_data.get("player_id", "default_player"),
                shot_data.get("camera_view", "frontal"),
                st_raw,
                st_id,
                shot_style,
                cfg_ver,
                det_prof_id,
                m_start, m_dip, m_set, m_release, m_end,
                a_start, a_dip, a_set, a_release, a_end,
                outcome, outcome_source, review_status, shot_data.get("review_notes"),
                tracking_conf, shot_data.get("valid_frame_ratio", 1.0),
                shot_data.get("knee_angle_dip_3d"),
                shot_data.get("elbow_angle_release_3d"),
                shot_data.get("release_height_rel_m"),
                shot_data.get("elbow_angle_release_2d"),
                shot_data.get("foreshortening_discrepancy_deg"),
                shot_data.get("sequence_lag_ms"),
                1 if shot_data.get("sequence_order_valid", True) else 0,
                shot_data.get("torso_sway_deg"),
                shot_data.get("raw_landmarks_ref"),
                shot_data.get("automated_outcome", "unknown"),
                float(shot_data.get("automated_outcome_conf", 0.0) or 0.0),
                shot_data.get("p_make"),
                shot_data.get("outcome_confidence"),
                shot_data.get("evidence_quality"),
                shot_data.get("outcome_reason"),
                json.dumps(shot_data.get("outcome_features")) if isinstance(shot_data.get("outcome_features"), dict) else shot_data.get("outcome_features"),
                shot_data.get("estimator_version"),
                shot_data.get("estimator_cfg_hash"),
                shot_data.get("trajectory_fit_r2"),
                shot_data.get("entry_angle_deg") or shot_data.get("entry_angle"),
                float(shot_data.get("ball_coverage_ratio", 0.0) or 0.0),
                shot_data.get("ball_model_version"),
                now, now
            ))
            conn.commit()
            return shot_id

    def update_shot_annotation(
        self,
        shot_id: str,
        annotated_boundaries: Optional[Dict[str, int]] = None,
        outcome: Optional[str] = None,
        outcome_source: Optional[str] = None,
        review_status: Optional[str] = None,
        review_notes: Optional[str] = None,
        tracking_confidence: Optional[str] = None,
        shot_style: Optional[str] = None,
        reviewer_id: str = "local_user",
    ) -> bool:
        """
        Update human-corrected boundaries or outcome label while preserving
        machine-detected predictions intact.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM shots WHERE shot_id = ?", (shot_id,))
            row = cursor.fetchone()
            if not row:
                return False

            previous_values = dict(row)

            updates = []
            params = []
            now = datetime.datetime.now().isoformat()

            if annotated_boundaries:
                if "start_frame" in annotated_boundaries:
                    updates.append("annotated_start_frame = ?")
                    params.append(annotated_boundaries["start_frame"])
                if "dip_frame" in annotated_boundaries:
                    updates.append("annotated_dip_frame = ?")
                    params.append(annotated_boundaries["dip_frame"])
                if "set_frame" in annotated_boundaries:
                    updates.append("annotated_set_frame = ?")
                    params.append(annotated_boundaries["set_frame"])
                if "release_frame" in annotated_boundaries:
                    updates.append("annotated_release_frame = ?")
                    params.append(annotated_boundaries["release_frame"])
                if "end_frame" in annotated_boundaries:
                    updates.append("annotated_end_frame = ?")
                    params.append(annotated_boundaries["end_frame"])

            if outcome is not None:
                cleaned_outcome = outcome.lower()
                if cleaned_outcome in ("make", "miss", "unknown"):
                    updates.append("outcome = ?")
                    params.append(cleaned_outcome)
                    src = outcome_source if outcome_source is not None else "manual_review"
                    updates.append("outcome_source = ?")
                    params.append(src)
            elif outcome_source is not None:
                updates.append("outcome_source = ?")
                params.append(outcome_source)

            if review_status is not None:
                cleaned_status = review_status.lower()
                if cleaned_status in ("quarantined", "approved", "discarded"):
                    updates.append("review_status = ?")
                    params.append(cleaned_status)

            if review_notes is not None:
                updates.append("review_notes = ?")
                params.append(review_notes)

            if tracking_confidence is not None:
                updates.append("tracking_confidence = ?")
                params.append(tracking_confidence)

            if shot_style is not None:
                updates.append("shot_style = ?")
                params.append(shot_style)

            updates.append("updated_at = ?")
            params.append(now)
            params.append(shot_id)

            sql = f"UPDATE shots SET {', '.join(updates)} WHERE shot_id = ?"
            cursor.execute(sql, tuple(params))
            cursor.execute("SELECT * FROM shots WHERE shot_id = ?", (shot_id,))
            updated_values = dict(cursor.fetchone())
            tracked_fields = (
                "annotated_start_frame", "annotated_dip_frame", "annotated_set_frame",
                "annotated_release_frame", "annotated_end_frame", "outcome",
                "outcome_source", "review_status", "review_notes",
            )
            before = {key: previous_values.get(key) for key in tracked_fields}
            after = {key: updated_values.get(key) for key in tracked_fields}
            if before != after:
                cursor.execute("""
                    INSERT INTO shot_review_history (
                        review_id, shot_id, reviewer_id, previous_values_json, updated_values_json
                    ) VALUES (?, ?, ?, ?, ?)
                """, (
                    str(uuid.uuid4()), shot_id, reviewer_id,
                    json.dumps(before, sort_keys=True), json.dumps(after, sort_keys=True),
                ))
            conn.commit()
            return cursor.rowcount > 0

    def get_shot_review_history(self, shot_id: str) -> List[Dict[str, Any]]:
        """Return persisted human review edits for one shot, oldest first."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM shot_review_history WHERE shot_id = ? ORDER BY created_at, rowid",
                (shot_id,),
            ).fetchall()
        history = []
        for row in rows:
            item = dict(row)
            item["previous_values"] = json.loads(item.pop("previous_values_json"))
            item["updated_values"] = json.loads(item.pop("updated_values_json"))
            history.append(item)
        return history

    def update_shot_machine_outcome(self, shot_id: str, outcome_data: Dict[str, Any]) -> bool:
        """
        Update only the machine-proposed outcome fields for a shot attempt.
        Never touches human label, outcome_source, review_status, or boundary annotations.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT shot_id FROM shots WHERE shot_id = ?", (shot_id,))
            if not cursor.fetchone():
                return False

            now = datetime.datetime.now().isoformat()
            features_raw = outcome_data.get("features") or outcome_data.get("outcome_features")
            features_json = json.dumps(features_raw) if isinstance(features_raw, dict) else features_raw

            cursor.execute("""
                UPDATE shots
                SET automated_outcome = ?,
                    automated_outcome_conf = ?,
                    p_make = ?,
                    outcome_confidence = ?,
                    evidence_quality = ?,
                    outcome_reason = ?,
                    outcome_features = ?,
                    estimator_version = ?,
                    estimator_cfg_hash = ?,
                    updated_at = ?
                WHERE shot_id = ?
            """, (
                outcome_data.get("label") or outcome_data.get("automated_outcome", "unknown"),
                outcome_data.get("confidence") if outcome_data.get("confidence") is not None else outcome_data.get("automated_outcome_conf", 0.0),
                outcome_data.get("p_make"),
                outcome_data.get("confidence") if outcome_data.get("confidence") is not None else outcome_data.get("outcome_confidence"),
                outcome_data.get("evidence_quality"),
                outcome_data.get("reason") or outcome_data.get("outcome_reason"),
                features_json,
                outcome_data.get("estimator_version"),
                outcome_data.get("estimator_cfg_hash"),
                now,
                shot_id
            ))
            conn.commit()
            return cursor.rowcount > 0

    def set_session_rim_anchor(self, session_id: str, anchor_data: Dict[str, Any], rim_source: str = "auto") -> bool:
        """Persist confirmed or consensus rim anchor for a session."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT session_id FROM sessions WHERE session_id = ?", (session_id,))
            if not cursor.fetchone():
                return False
            anchor_json = json.dumps(anchor_data) if isinstance(anchor_data, dict) else anchor_data
            cursor.execute("""
                UPDATE sessions
                SET rim_anchor = ?,
                    rim_source = ?
                WHERE session_id = ?
            """, (anchor_json, rim_source, session_id))
            conn.commit()
            return cursor.rowcount > 0

    def get_session_rim_anchor(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve persisted rim anchor for a session."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT rim_anchor, rim_source FROM sessions WHERE session_id = ?", (session_id,))
            row = cursor.fetchone()
            if not row or not row[0]:
                return None
            try:
                data = json.loads(row[0])
                if isinstance(data, dict):
                    data["source"] = row[1] or "auto"
                return data
            except Exception:
                return None

    def get_shot(self, shot_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single shot record as a dict."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM shots WHERE shot_id = ?", (shot_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_shots(
        self,
        player_id: Optional[str] = None,
        session_id: Optional[str] = None,
        camera_view: Optional[str] = None,
        shot_type: Optional[str] = None,
        shot_style: Optional[str] = None,
        review_status: Optional[str] = None,
        min_confidence: Optional[str] = "SUFFICIENT",
        shot_type_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query shots with optional filters."""
        query = "SELECT * FROM shots WHERE 1=1"
        params = []

        if player_id:
            query += " AND player_id = ?"
            params.append(player_id)
        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)
        if camera_view:
            query += " AND camera_view = ?"
            params.append(camera_view)
        target_type = shot_type_id or shot_type
        if target_type:
            canon = resolve_shot_type(target_type)
            query += " AND (shot_type_id = ? OR shot_type = ?)"
            params.extend([canon, target_type])
        if shot_style:
            query += " AND shot_style = ?"
            params.append(shot_style)
        if review_status:
            query += " AND review_status = ?"
            params.append(review_status)
        if min_confidence:
            query += " AND tracking_confidence = ?"
            params.append(min_confidence)

        query += " ORDER BY created_at ASC"

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            return [dict(row) for row in cursor.fetchall()]

    def save_baseline(self, baseline_data: Dict[str, Any]) -> str:
        """Save a computed player baseline profile."""
        baseline_id = baseline_data.get("baseline_id") or f"base_{str(uuid.uuid4())[:8]}"
        st_val = baseline_data.get("shot_type", "catch_and_shoot")
        st_id = resolve_shot_type(baseline_data.get("shot_type_id") or st_val)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO baselines (
                    baseline_id, player_id, camera_view, shot_type, shot_type_id, shot_style,
                    sample_size_makes, sample_size_misses, sample_size_total,
                    mean_elbow_release_make, std_elbow_release_make,
                    mean_elbow_release_miss, std_elbow_release_miss,
                    mean_elbow_release_all, std_elbow_release_all,
                    mean_sequence_lag_make, std_sequence_lag_make,
                    mean_sequence_lag_miss, std_sequence_lag_miss,
                    mean_sequence_lag_all, std_sequence_lag_all,
                    mean_knee_dip_make, std_knee_dip_make,
                    mean_knee_dip_miss, std_knee_dip_miss,
                    mean_knee_dip_all, std_knee_dip_all,
                    mean_torso_sway_make, std_torso_sway_make,
                    mean_torso_sway_miss, std_torso_sway_miss,
                    mean_torso_sway_all, std_torso_sway_all,
                    computed_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?,
                    ?, ?,
                    ?, ?,
                    ?, ?,
                    ?, ?,
                    ?, ?,
                    ?, ?,
                    ?, ?,
                    ?, ?,
                    ?, ?,
                    ?, ?,
                    ?, ?,
                    CURRENT_TIMESTAMP
                )
            """, (
                baseline_id,
                baseline_data["player_id"],
                baseline_data.get("camera_view", "frontal"),
                st_val,
                st_id,
                baseline_data.get("shot_style", "jump_shot"),
                baseline_data.get("sample_size_makes", 0),
                baseline_data.get("sample_size_misses", 0),
                baseline_data.get("sample_size_total", 0),
                baseline_data.get("mean_elbow_release_make"),
                baseline_data.get("std_elbow_release_make"),
                baseline_data.get("mean_elbow_release_miss"),
                baseline_data.get("std_elbow_release_miss"),
                baseline_data.get("mean_elbow_release_all"),
                baseline_data.get("std_elbow_release_all"),
                baseline_data.get("mean_sequence_lag_make"),
                baseline_data.get("std_sequence_lag_make"),
                baseline_data.get("mean_sequence_lag_miss"),
                baseline_data.get("std_sequence_lag_miss"),
                baseline_data.get("mean_sequence_lag_all"),
                baseline_data.get("std_sequence_lag_all"),
                baseline_data.get("mean_knee_dip_make"),
                baseline_data.get("std_knee_dip_make"),
                baseline_data.get("mean_knee_dip_miss"),
                baseline_data.get("std_knee_dip_miss"),
                baseline_data.get("mean_knee_dip_all"),
                baseline_data.get("std_knee_dip_all"),
                baseline_data.get("mean_torso_sway_make"),
                baseline_data.get("std_torso_sway_make"),
                baseline_data.get("mean_torso_sway_miss"),
                baseline_data.get("std_torso_sway_miss"),
                baseline_data.get("mean_torso_sway_all"),
                baseline_data.get("std_torso_sway_all")
            ))
            conn.commit()
            return baseline_id

    def get_latest_baseline(
        self,
        player_id: str,
        camera_view: str,
        shot_type: str,
        shot_style: Optional[str] = "jump_shot",
        shot_type_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Get the most recent baseline for a player in a specific context."""
        target_st = resolve_shot_type(shot_type_id or shot_type)
        query = "SELECT * FROM baselines WHERE player_id = ? AND camera_view = ? AND (shot_type_id = ? OR shot_type = ?)"
        params = [player_id, camera_view, target_st, target_st]
        if shot_style:
            query += " AND shot_style = ?"
            params.append(shot_style)
        query += " ORDER BY computed_at DESC LIMIT 1"

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            row = cursor.fetchone()
            return dict(row) if row else None

    def save_remediation(self, rem_data: Dict[str, Any]) -> str:
        """Save a coaching remediation recommendation."""
        rem_id = rem_data.get("remediation_id") or f"rem_{str(uuid.uuid4())[:8]}"
        now = datetime.datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO remediations (
                    remediation_id, player_id, baseline_id, shot_style,
                    targeted_flaw, priority_tier, recommended_drill, drill_reps,
                    drill_completed,
                    pre_drill_metric_mean, pre_drill_metric_std,
                    post_drill_metric_mean, post_drill_metric_std,
                    pre_make_count, pre_total_count,
                    post_make_count, post_total_count,
                    status, feedback_notes, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?,
                    ?, ?,
                    ?, ?,
                    ?, ?,
                    ?, ?,
                    ?, ?, ?, ?
                )
            """, (
                rem_id,
                rem_data["player_id"],
                rem_data.get("baseline_id"),
                rem_data.get("shot_style", "jump_shot"),
                rem_data["targeted_flaw"],
                rem_data.get("priority_tier", 1),
                rem_data["recommended_drill"],
                rem_data.get("drill_reps", 10),
                1 if rem_data.get("drill_completed", False) else 0,
                rem_data.get("pre_drill_metric_mean"),
                rem_data.get("pre_drill_metric_std"),
                rem_data.get("post_drill_metric_mean"),
                rem_data.get("post_drill_metric_std"),
                rem_data.get("pre_make_count", 0),
                rem_data.get("pre_total_count", 0),
                rem_data.get("post_make_count", 0),
                rem_data.get("post_total_count", 0),
                rem_data.get("status", "active"),
                rem_data.get("feedback_notes"),
                now, now
            ))
            conn.commit()
            return rem_id

    def update_remediation_status(
        self,
        remediation_id: str,
        status: str,
        drill_completed: Optional[bool] = None,
        post_drill_metric_mean: Optional[float] = None,
        post_drill_metric_std: Optional[float] = None,
        post_make_count: Optional[int] = None,
        post_total_count: Optional[int] = None,
        feedback_notes: Optional[str] = None
    ) -> bool:
        """Update remediation progress and post-drill outcome."""
        now = datetime.datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            updates = ["status = ?", "updated_at = ?"]
            params = [status, now]

            if drill_completed is not None:
                updates.append("drill_completed = ?")
                params.append(1 if drill_completed else 0)
            if post_drill_metric_mean is not None:
                updates.append("post_drill_metric_mean = ?")
                params.append(post_drill_metric_mean)
            if post_drill_metric_std is not None:
                updates.append("post_drill_metric_std = ?")
                params.append(post_drill_metric_std)
            if post_make_count is not None:
                updates.append("post_make_count = ?")
                params.append(post_make_count)
            if post_total_count is not None:
                updates.append("post_total_count = ?")
                params.append(post_total_count)
            if feedback_notes is not None:
                updates.append("feedback_notes = ?")
                params.append(feedback_notes)

            params.append(remediation_id)
            cursor.execute(f"UPDATE remediations SET {', '.join(updates)} WHERE remediation_id = ?", tuple(params))
            conn.commit()
            return cursor.rowcount > 0

    def get_active_remediation(self, player_id: str) -> Optional[Dict[str, Any]]:
        """Get current active remediation for a player."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM remediations
                WHERE player_id = ? AND status = 'active'
                ORDER BY created_at DESC LIMIT 1
            """, (player_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_remediation(self, remediation_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM remediations WHERE remediation_id = ?", (remediation_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_latest_remediation(self, player_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM remediations WHERE player_id = ? ORDER BY created_at DESC LIMIT 1",
                (player_id,),
            ).fetchone()
        return dict(row) if row else None

    # =========================================================================
    # Phase 5: Developer Model Lab & Annotation Ground Truth Persistence
    # =========================================================================

    def register_labeled_clip(self, clip_data: Optional[Dict[str, Any]] = None, **kwargs) -> str:
        """Register or update video clip metadata in labeled_clips table."""
        data = dict(clip_data or {})
        data.update(kwargs)
        clip_id = data.get("clip_id") or f"clip_{uuid.uuid4().hex[:8]}"
        st_id = resolve_shot_type(data.get("shot_type_id") or data.get("shot_type") or "catch_and_shoot")
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO labeled_clips (
                    clip_id, file_path, file_sha256, player_id, camera_view,
                    shot_type_id, shot_style, fps, frame_count, width, height, split, license, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(clip_id) DO UPDATE SET
                    file_path=excluded.file_path,
                    file_sha256=excluded.file_sha256,
                    player_id=excluded.player_id,
                    camera_view=excluded.camera_view,
                    shot_type_id=excluded.shot_type_id,
                    shot_style=excluded.shot_style,
                    fps=excluded.fps,
                    frame_count=excluded.frame_count,
                    width=excluded.width,
                    height=excluded.height,
                    split=excluded.split,
                    license=excluded.license,
                    notes=excluded.notes
            """, (
                clip_id,
                data.get("file_path", ""),
                data.get("file_sha256"),
                data.get("player_id", "unknown_player"),
                data.get("camera_view", "unknown_view"),
                st_id,
                data.get("shot_style", "jump_shot"),
                data.get("fps", 30.0),
                data.get("frame_count"),
                data.get("width"),
                data.get("height"),
                data.get("split", "train"),
                data.get("license", "private_project"),
                data.get("notes")
            ))
            conn.commit()
            return clip_id

    def get_labeled_clip(self, clip_id: str) -> Optional[Dict[str, Any]]:
        """Fetch labeled clip metadata by clip_id."""
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM labeled_clips WHERE clip_id = ?", (clip_id,))
            row = c.fetchone()
            return dict(row) if row else None

    def list_labeled_clips(self, split: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all labeled clips, optionally filtered by split."""
        with self._get_connection() as conn:
            c = conn.cursor()
            if split:
                c.execute("SELECT * FROM labeled_clips WHERE split = ? ORDER BY created_at ASC", (split,))
            else:
                c.execute("SELECT * FROM labeled_clips ORDER BY created_at ASC")
            return [dict(r) for r in c.fetchall()]

    def save_machine_proposals(
        self,
        clip_id: str,
        proposals: List[Dict[str, Any]],
        detector_name: str = "analyzer_v1",
        detector_version: str = "1.0.0"
    ) -> int:
        """Persist candidate machine detector proposals for a clip."""
        inserted = 0
        with self._get_connection() as conn:
            c = conn.cursor()
            for p in proposals:
                prop_id = p.get("proposal_id") or f"prop_{uuid.uuid4().hex[:8]}"
                c.execute("""
                    INSERT INTO machine_proposals (
                        proposal_id, clip_id, detector_name, detector_version,
                        start_frame, end_frame, dip_frame, set_frame, release_frame,
                        confidence, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(proposal_id) DO UPDATE SET
                        start_frame=excluded.start_frame,
                        end_frame=excluded.end_frame,
                        dip_frame=excluded.dip_frame,
                        set_frame=excluded.set_frame,
                        release_frame=excluded.release_frame,
                        confidence=excluded.confidence,
                        status=excluded.status
                """, (
                    prop_id,
                    clip_id,
                    p.get("detector_name", detector_name),
                    p.get("detector_version", detector_version),
                    p.get("start_frame"),
                    p.get("end_frame"),
                    p.get("dip_frame"),
                    p.get("set_frame"),
                    p.get("release_frame"),
                    p.get("confidence", 1.0),
                    p.get("status", "proposed")
                ))
                inserted += 1
            conn.commit()
        return inserted

    def get_machine_proposals(self, clip_id: str) -> List[Dict[str, Any]]:
        """Get machine proposals for a clip ordered by start_frame."""
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT * FROM machine_proposals
                WHERE clip_id = ?
                ORDER BY start_frame ASC
            """, (clip_id,))
            return [dict(r) for r in c.fetchall()]

    def update_machine_proposal_status(self, proposal_id: str, status: str) -> bool:
        """Update machine proposal status ('proposed', 'accepted', 'discarded')."""
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute("""
                UPDATE machine_proposals SET status = ?
                WHERE proposal_id = ?
            """, (status, proposal_id))
            conn.commit()
            return c.rowcount > 0

    def save_labeled_interval(self, interval_data: Optional[Dict[str, Any]] = None, **kwargs) -> str:
        """Save a human ground-truth interval (shot or 8-class hard negative)."""
        data = dict(interval_data or {})
        data.update(kwargs)
        interval_id = data.get("interval_id") or f"int_{uuid.uuid4().hex[:8]}"
        interval_type = data.get("interval_type", "shot")
        action_class = data.get("action_class")
        if not action_class:
            action_class = "shot_event" if interval_type == "shot" else "idle_reset"

        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO labeled_intervals (
                    interval_id, clip_id, interval_type, action_class,
                    start_frame, end_frame, dip_frame, set_frame, release_frame, follow_through_frame,
                    outcome, rim_contact, occluded_lower, occluded_upper,
                    annotator_id, review_status, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(interval_id) DO UPDATE SET
                    interval_type=excluded.interval_type,
                    action_class=excluded.action_class,
                    start_frame=excluded.start_frame,
                    end_frame=excluded.end_frame,
                    dip_frame=excluded.dip_frame,
                    set_frame=excluded.set_frame,
                    release_frame=excluded.release_frame,
                    follow_through_frame=excluded.follow_through_frame,
                    outcome=excluded.outcome,
                    rim_contact=excluded.rim_contact,
                    occluded_lower=excluded.occluded_lower,
                    occluded_upper=excluded.occluded_upper,
                    annotator_id=excluded.annotator_id,
                    review_status=excluded.review_status,
                    notes=excluded.notes,
                    updated_at=CURRENT_TIMESTAMP
            """, (
                interval_id,
                data["clip_id"],
                interval_type,
                action_class,
                int(data["start_frame"]),
                int(data["end_frame"]),
                data.get("dip_frame"),
                data.get("set_frame"),
                data.get("release_frame"),
                data.get("follow_through_frame"),
                data.get("outcome", "none" if interval_type == "hard_negative" else "unknown"),
                data.get("rim_contact"),
                1 if data.get("occluded_lower") else 0,
                1 if data.get("occluded_upper") else 0,
                data.get("annotator_id", "human_reviewer"),
                data.get("review_status", "verified"),
                data.get("notes")
            ))
            conn.commit()
            return interval_id

    def update_labeled_interval(self, interval_id: str, updates: Dict[str, Any]) -> bool:
        """Update fields of an existing labeled interval."""
        allowed_fields = [
            "interval_type", "action_class", "start_frame", "end_frame",
            "dip_frame", "set_frame", "release_frame", "follow_through_frame",
            "outcome", "rim_contact", "occluded_lower", "occluded_upper",
            "annotator_id", "review_status", "notes"
        ]
        set_clauses = []
        params = []
        for f in allowed_fields:
            if f in updates:
                set_clauses.append(f"{f} = ?")
                val = updates[f]
                if f in ("occluded_lower", "occluded_upper"):
                    val = 1 if val else 0
                params.append(val)
        if not set_clauses:
            return False
        set_clauses.append("updated_at = CURRENT_TIMESTAMP")
        params.append(interval_id)
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute(f"UPDATE labeled_intervals SET {', '.join(set_clauses)} WHERE interval_id = ?", tuple(params))
            conn.commit()
            return c.rowcount > 0

    def delete_labeled_interval(self, interval_id: str) -> bool:
        """Delete a human labeled interval."""
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM labeled_intervals WHERE interval_id = ?", (interval_id,))
            conn.commit()
            return c.rowcount > 0

    def get_clip_annotations(self, clip_id: str) -> Dict[str, Any]:
        """Get clip record, machine proposals, and human intervals."""
        clip = self.get_labeled_clip(clip_id)
        proposals = self.get_machine_proposals(clip_id)
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT * FROM labeled_intervals
                WHERE clip_id = ?
                ORDER BY start_frame ASC
            """, (clip_id,))
            intervals = [dict(r) for r in c.fetchall()]
        return {
            "clip": clip,
            "proposals": proposals,
            "intervals": intervals
        }

    # =========================================================================
    # User Authentication & Onboarding
    # =========================================================================

    @staticmethod
    def hash_password(password: str, salt: bytes | None = None) -> str:
        """Hash a password using PBKDF2-HMAC-SHA256 with 100,000 iterations."""
        if salt is None:
            salt = secrets.token_bytes(16)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
        return base64.b64encode(salt + dk).decode("ascii")

    @staticmethod
    def verify_password(stored: str, password: str) -> bool:
        """Verify a password against stored PBKDF2 hash."""
        try:
            raw = base64.b64decode(stored.encode("ascii"))
            if len(raw) < 17:
                return False
            salt, dk = raw[:16], raw[16:]
            chk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
            return secrets.compare_digest(dk, check) if "check" in locals() else secrets.compare_digest(dk, chk)
        except Exception:
            return False

    def create_user(
        self,
        email: str,
        password: str,
        name: str,
        player_id: Optional[str] = None,
        skill_level: str = "intermediate",
        handedness: str = "right",
        shot_style: str = "jump_shot",
        height_cm: Optional[float] = None,
        wingspan_cm: Optional[float] = None,
        goals: Optional[str] = None,
        pain_reported: bool = False,
        onboarding_completed: bool = False
    ) -> Dict[str, Any]:
        """Register a new user and link to player registry."""
        email_clean = email.strip().lower()
        if not email_clean or "@" not in email_clean:
            raise ValueError("A valid email address is required.")
        if len(password) < 6:
            raise ValueError("Password must be at least 6 characters long.")
        name_clean = name.strip() or "Shooter"

        # Derive a valid player_id if not explicitly passed
        if not player_id or not player_id.strip():
            derived = re.sub(r"[^A-Za-z0-9_\-]", "_", name_clean.lower()).strip("_")
            player_id = derived[:32] if derived else f"player_{uuid.uuid4().hex[:6]}"
        player_id = re.sub(r"[^A-Za-z0-9_\-]", "_", player_id.strip())

        user_id = f"usr_{uuid.uuid4().hex[:12]}"
        pwd_hash = self.hash_password(password)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        height_m = (height_cm / 100.0) if height_cm and height_cm > 0 else None
        wingspan_m = (wingspan_cm / 100.0) if wingspan_cm and wingspan_cm > 0 else None

        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Ensure player exists in players table
            cursor.execute("""
                INSERT OR IGNORE INTO players (player_id, name, height_m, wingspan_m, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (player_id, name_clean, height_m, wingspan_m, now))

            cursor.execute("""
                INSERT INTO users (
                    id, player_id, name, email, password_hash,
                    skill_level, handedness, shot_style,
                    height_cm, wingspan_cm, goals, pain_reported,
                    onboarding_completed, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id, player_id, name_clean, email_clean, pwd_hash,
                skill_level, handedness, shot_style,
                height_cm, wingspan_cm, goals or "", 1 if pain_reported else 0,
                1 if onboarding_completed else 0, now, now
            ))
            conn.commit()

        return self.get_user_by_id(user_id)

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Fetch user record by email including password_hash."""
        email_clean = email.strip().lower()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE LOWER(email) = ?", (email_clean,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Fetch public user record by id (excludes password_hash)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, player_id, name, email, skill_level, handedness,
                       shot_style, height_cm, wingspan_cm, goals, pain_reported,
                       onboarding_completed, created_at, updated_at
                FROM users WHERE id = ?
            """, (user_id,))
            row = cursor.fetchone()
            if not row:
                return None
            res = dict(row)
            res["pain_reported"] = bool(res.get("pain_reported"))
            res["onboarding_completed"] = bool(res.get("onboarding_completed"))
            return res

    def verify_user_credentials(self, email: str, password: str) -> Optional[Dict[str, Any]]:
        """Verify user credentials and return sanitized user record if valid."""
        user = self.get_user_by_email(email)
        if not user:
            return None
        if self.verify_password(user["password_hash"], password):
            return self.get_user_by_id(user["id"])
        return None

    def update_user_profile(self, user_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update profile fields and sync player attributes."""
        allowed_fields = {
            "name", "skill_level", "handedness", "shot_style",
            "height_cm", "wingspan_cm", "goals", "pain_reported", "onboarding_completed"
        }
        fields_to_update = {k: v for k, v in updates.items() if k in allowed_fields}
        if not fields_to_update:
            return self.get_user_by_id(user_id)

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        set_clauses = [f"{k} = ?" for k in fields_to_update.keys()]
        set_clauses.append("updated_at = ?")
        values = list(fields_to_update.values())
        if "onboarding_completed" in fields_to_update:
            idx = list(fields_to_update.keys()).index("onboarding_completed")
            values[idx] = 1 if fields_to_update["onboarding_completed"] else 0
        values.extend([now, user_id])

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE users SET {', '.join(set_clauses)} WHERE id = ?", values)
            conn.commit()

            if "name" in fields_to_update or "height_cm" in fields_to_update or "wingspan_cm" in fields_to_update:
                cursor.execute("SELECT player_id, name, height_cm, wingspan_cm FROM users WHERE id = ?", (user_id,))
                row = cursor.fetchone()
                if row:
                    h_m = (row["height_cm"] / 100.0) if row["height_cm"] else None
                    w_m = (row["wingspan_cm"] / 100.0) if row["wingspan_cm"] else None
                    cursor.execute("""
                        UPDATE players SET name = ?, height_m = ?, wingspan_m = ?
                        WHERE player_id = ?
                    """, (row["name"], h_m, w_m, row["player_id"]))
                    conn.commit()

        return self.get_user_by_id(user_id)

    def create_user_session(self, user_id: str, duration_days: int = 30) -> str:
        """Create a session token stored in user_sessions table."""
        token = secrets.token_hex(24)
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        expires_dt = now_dt + datetime.timedelta(days=duration_days)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO user_sessions (token, user_id, created_at, expires_at)
                VALUES (?, ?, ?, ?)
            """, (token, user_id, now_dt.isoformat(), expires_dt.isoformat()))
            conn.commit()
        return token

    def get_user_by_session(self, token: str) -> Optional[Dict[str, Any]]:
        """Validate session token and return user if active."""
        if not token or not isinstance(token, str):
            return None
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT user_id, expires_at FROM user_sessions WHERE token = ?
            """, (token,))
            row = cursor.fetchone()
            if not row:
                return None
            if row["expires_at"] < now_iso:
                cursor.execute("DELETE FROM user_sessions WHERE token = ?", (token,))
                conn.commit()
                return None
            user_id = row["user_id"]
        return self.get_user_by_id(user_id)

    def delete_user_session(self, token: str) -> bool:
        """Invalidate a session token upon logout."""
        if not token:
            return False
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM user_sessions WHERE token = ?", (token,))
            conn.commit()
            return cursor.rowcount > 0

