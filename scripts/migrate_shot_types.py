"""
migrate_shot_types.py - Standalone Database Migration Script for Shot Types.

Adds shot_type_id, config_version, and detector_profile_id columns to database tables:
- sessions
- shots
- baselines
- labeled_clips
- attempt_analysis

Backfills existing records with canonical mappings:
- 'off_the_dribble', 'off_dribble' -> 'pull_up'
- empty / null / unknown -> 'other'
- existing valid shot types -> canonical shot_type_id
"""

from __future__ import annotations
import os
import sys
import sqlite3
import argparse
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from basketball.configs.shot_types import SHOT_TYPE_REGISTRY, SHOT_TYPE_ALIASES, resolve_shot_type, CONFIG_VERSION


def migrate_database(db_path: str = "shot_lab.db") -> dict:
    """Execute shot type schema and data migration on SQLite database."""
    if not os.path.exists(db_path):
        print(f"[migrate] Database file not found at {db_path}; nothing to migrate.")
        return {"status": "SKIPPED", "reason": "file_not_found"}

    print(f"[migrate] Connecting to database: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 1. Add missing columns
    columns_to_ensure = {
        "sessions": [
            ("shot_type_id", "TEXT DEFAULT 'catch_and_shoot'"),
        ],
        "shots": [
            ("shot_type_id", "TEXT DEFAULT 'catch_and_shoot'"),
            ("config_version", "TEXT"),
            ("detector_profile_id", "TEXT"),
        ],
        "baselines": [
            ("shot_type_id", "TEXT DEFAULT 'catch_and_shoot'"),
        ],
        "labeled_clips": [
            ("shot_type_id", "TEXT DEFAULT 'catch_and_shoot'"),
        ],
        "attempt_analysis": [
            ("config_version", "TEXT"),
            ("detector_profile_id", "TEXT"),
            ("shot_type_id", "TEXT"),
        ],
    }

    added_columns = []
    for table, cols in columns_to_ensure.items():
        cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
        if not cursor.fetchone():
            continue
        cursor.execute(f"PRAGMA table_info({table})")
        existing_cols = {row[1] for row in cursor.fetchall()}
        for col_name, col_def in cols:
            if col_name not in existing_cols:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
                added_columns.append(f"{table}.{col_name}")

    # 2. Backfill rows
    # Sessions
    cursor.execute("""
        UPDATE sessions
        SET shot_type_id = CASE
            WHEN shot_type IN ('off_the_dribble', 'off_dribble') THEN 'pull_up'
            WHEN shot_type IS NULL OR shot_type = '' THEN 'other'
            ELSE shot_type
        END
        WHERE shot_type_id IS NULL OR shot_type_id = '' OR (shot_type_id = 'catch_and_shoot' AND shot_type != 'catch_and_shoot')
    """)
    migrated_sessions = cursor.rowcount

    # Shots
    cursor.execute("""
        UPDATE shots
        SET shot_type_id = CASE
            WHEN shot_type IN ('off_the_dribble', 'off_dribble') THEN 'pull_up'
            WHEN shot_type IS NULL OR shot_type = '' THEN 'other'
            ELSE shot_type
        END
        WHERE shot_type_id IS NULL OR shot_type_id = '' OR (shot_type_id = 'catch_and_shoot' AND shot_type != 'catch_and_shoot')
    """)
    migrated_shots = cursor.rowcount

    # Baselines
    cursor.execute("""
        UPDATE baselines
        SET shot_type_id = CASE
            WHEN shot_type IN ('off_the_dribble', 'off_dribble') THEN 'pull_up'
            WHEN shot_type IS NULL OR shot_type = '' THEN 'other'
            ELSE shot_type
        END
        WHERE shot_type_id IS NULL OR shot_type_id = '' OR (shot_type_id = 'catch_and_shoot' AND shot_type != 'catch_and_shoot')
    """)
    migrated_baselines = cursor.rowcount

    # Labeled clips
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='labeled_clips'")
    if cursor.fetchone():
        cursor.execute("""
            UPDATE labeled_clips
            SET shot_type_id = 'catch_and_shoot'
            WHERE shot_type_id IS NULL OR shot_type_id = ''
        """)

    conn.commit()
    conn.close()

    summary = {
        "status": "COMPLETED",
        "added_columns": added_columns,
        "migrated_sessions": migrated_sessions,
        "migrated_shots": migrated_shots,
        "migrated_baselines": migrated_baselines,
    }
    print(f"[migrate] Migration completed successfully: {summary}")
    return summary


def main():
    parser = argparse.ArgumentParser(description="Migrate Shot Lab database schema for canonical shot types.")
    parser.add_argument("--db-path", default="shot_lab.db", help="Path to SQLite database (default: shot_lab.db)")
    args = parser.parse_args()
    migrate_database(args.db_path)


if __name__ == "__main__":
    main()

