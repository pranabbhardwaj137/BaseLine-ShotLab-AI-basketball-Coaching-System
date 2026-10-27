"""Local-first Phase 8 web app; uses only the Python standard library for HTTP."""

from __future__ import annotations

import argparse
import hmac
import ipaddress
import secrets
import socket
import ssl
import time
import contextlib
import json
import mimetypes
import os
import statistics
import re
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PureWindowsPath
from urllib.parse import parse_qs, unquote, urlparse

import cv2
import numpy as np

from basketball.persistence.shot_lab_db import ShotLabDB
from basketball.coaching.coaching_service import build_session_insights
from basketball.services.history_service import build_player_history
from basketball.coaching.llm_coach import CoachUnavailable, answer_grounded_question, summarize_findings_for_llm
from basketball.services.video_analysis_service import (AnalysisCancelled, analyze_video, make_browser_replay,
                                    prepare_video_for_analysis)
from basketball.services.live_service import LiveCameraEngine
import basketball.services.report_service as report_service
import basketball.analysis.shooting_analysis as shooting_analysis
from basketball.services.video_analysis_service import KEY_JOINTS, MIN_SUFFICIENT_VALID_JOINT_RATIO
import basketball.workout.catalog as workout_catalog
import basketball.workout.planner as workout_planner
import basketball.workout.progress as workout_progress


PROJECT_ROOT = Path(__file__).resolve().parents[3]
WEB_ROOT = PROJECT_ROOT / "web"
if not WEB_ROOT.exists() and (Path.cwd() / "web").exists():
    WEB_ROOT = Path.cwd() / "web"
MAX_UPLOAD_BYTES = 250 * 1024 * 1024
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
VALID_CAMERA_VIEWS = {"frontal", "side_90", "oblique_45", "rear"}
VALID_SHOT_TYPES = {"catch_and_shoot", "off_dribble", "free_throw"}
VALID_SHOT_STYLES = {"jump_shot", "set_shot"}
VALID_HANDEDNESS = {"left", "right", "ambidextrous", "unspecified"}
VALID_SKILL_LEVELS = {"beginner", "intermediate", "advanced", "coach"}
MIME_EXTENSIONS = {"video/mp4": ".mp4", "video/quicktime": ".mov", "video/x-m4v": ".m4v", "video/x-msvideo": ".avi",
                   "video/x-matroska": ".mkv", "video/webm": ".webm"}
ACCESS_COOKIE = "shotlab_access"
CSRF_HEADER = "X-Shotlab"
LOOPBACK_NAMES = {"127.0.0.1", "localhost", "::1"}
WORKOUT_ID = re.compile(r"wk_[a-f0-9]{20}")
KEYFRAME_NAME = re.compile(r"shot_[A-Za-z0-9_-]{1,64}_(?:dip|release|finish)_\d{1,7}\.jpg")
ACCESS_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Baseline Shot Lab access</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f7f8f6;color:#18212f;font:16px/1.5 system-ui,sans-serif}
main{width:min(420px,calc(100vw - 32px));background:#fff;border:1px solid #d9dee5;border-radius:16px;padding:24px}
h1{margin:0 0 8px;font-size:1.5rem}p{color:#4a5566}label{display:block;font-weight:600;margin-top:16px}
input{width:100%;box-sizing:border-box;margin-top:6px;padding:12px;font:1.2rem ui-monospace,monospace;letter-spacing:.08em;border:1px solid #b9c1cc;border-radius:10px;text-transform:uppercase}
button{width:100%;margin-top:16px;padding:14px;border:0;border-radius:10px;background:#1f4fd8;color:#fff;font:600 1rem system-ui}
.err{color:#c8253a;font-weight:600}</style></head><body><main><h1>Enter the access code</h1>
<p>This Shot Lab runs on someone's computer on your network. Enter the code shown in the terminal or in the app's <b>Connect a phone</b> panel on that computer.</p>
__ERROR__<form method="get" action="/"><label for="token">Access code</label>
<input id="token" name="token" autocomplete="one-time-code" autocapitalize="characters" required autofocus>
<button type="submit">Continue</button></form></main></body></html>"""


class JobStore:
    """Small persistent job registry; analysis itself runs in one bounded worker."""

    def __init__(self, path: str, upload_root=None):
        self.path = str(path)
        self.upload_root = Path(upload_root) if upload_root else None
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS app_jobs (
                    job_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    player_id TEXT NOT NULL,
                    video_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress REAL NOT NULL DEFAULT 0,
                    message TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(app_jobs)")}
            for name, definition in (("replay_path", "TEXT"), ("cancel_requested", "INTEGER NOT NULL DEFAULT 0"),
                                     ("kind", "TEXT NOT NULL DEFAULT 'analysis'")):
                if name not in columns:
                    conn.execute(f"ALTER TABLE app_jobs ADD COLUMN {name} {definition}")
            conn.execute("""
                UPDATE app_jobs SET status='failed', message='Server restarted before this job finished',
                    error='Interrupted by server restart', updated_at=?
                WHERE status IN ('queued', 'running')
            """, (self._now(),))
            conn.commit()

    @contextlib.contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        try:
            yield conn
        finally:
            conn.close()

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()

    def create(self, job_id, session_id, player_id, video_path, kind="analysis"):
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO app_jobs (job_id, session_id, player_id, video_path, status,
                    progress, message, created_at, updated_at, kind)
                VALUES (?, ?, ?, ?, 'queued', 0, 'Waiting for local analysis worker', ?, ?, ?)
            """, (job_id, session_id, player_id, video_path, self._now(), self._now(), kind))
            conn.commit()

    def request_cancel(self, job_id):
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "UPDATE app_jobs SET cancel_requested=1, updated_at=? WHERE job_id=? AND status IN ('queued','running')",
                (self._now(), job_id))
            conn.commit()
            return cursor.rowcount > 0

    def cancel_requested(self, job_id):
        with self._connect() as conn:
            row = conn.execute("SELECT cancel_requested FROM app_jobs WHERE job_id=?", (job_id,)).fetchone()
        return bool(row and row[0])

    def set_replay_path(self, job_id, replay_path):
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE app_jobs SET replay_path=?, updated_at=? WHERE job_id=?", (replay_path, self._now(), job_id))
            conn.commit()

    def active_job_for_session(self, session_id):
        with self._connect() as conn:
            row = conn.execute("SELECT job_id FROM app_jobs WHERE session_id=? AND status IN ('queued','running') LIMIT 1",
                               (session_id,)).fetchone()
        return row["job_id"] if row else None

    def update(self, job_id, *, status=None, progress=None, message=None, result=None, error=None):
        fields = []
        values = []
        for key, value in (("status", status), ("progress", progress), ("message", message),
                           ("result_json", json.dumps(result) if result is not None else None),
                           ("error", error)):
            if value is not None:
                fields.append(f"{key}=?")
                values.append(value)
        fields.append("updated_at=?")
        values.extend((self._now(), job_id))
        with self._lock, self._connect() as conn:
            conn.execute(f"UPDATE app_jobs SET {', '.join(fields)} WHERE job_id=?", values)
            conn.commit()

    def get(self, job_id):
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM app_jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["result"] = json.loads(result.pop("result_json")) if result.get("result_json") else None
        result.pop("video_path", None)
        result["has_replay_copy"] = bool(result.pop("replay_path", None))
        result["cancel_requested"] = bool(result.get("cancel_requested"))
        return result

    def resolve_video_path(self, stored_path):
        """Return a usable local path for a stored upload.

        Job rows store absolute paths. When a project folder is moved or opened on
        another computer (for example a Windows path read on macOS), fall back to
        the same generated file name inside the configured upload directory.
        """
        if not stored_path:
            return stored_path
        if Path(stored_path).is_file() or self.upload_root is None:
            return stored_path
        name = PureWindowsPath(stored_path).name if "\\" in stored_path else Path(stored_path).name
        candidate = Path(self.upload_root) / name
        return str(candidate) if candidate.is_file() else stored_path

    def latest_completed_job_for_session(self, session_id):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT job_id FROM app_jobs WHERE session_id=? AND status='complete' AND kind='analysis' "
                "ORDER BY created_at DESC LIMIT 1",
                (session_id,),
            ).fetchone()
        return row["job_id"] if row else None

    def media_for_job(self, job_id):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT session_id, video_path, replay_path, result_json FROM app_jobs WHERE job_id=?",
                (job_id,),
            ).fetchone()
        if not row:
            return None
        result = json.loads(row["result_json"]) if row["result_json"] else {}
        replay = self.resolve_video_path(row["replay_path"]) if row["replay_path"] else None
        return {"job_id": job_id, "session_id": row["session_id"],
                "video_path": self.resolve_video_path(row["video_path"]),
                "replay_path": replay if replay and Path(replay).is_file() else None,
                "frame_count": (result.get("video") or {}).get("frame_count"),
                "video": result.get("video") or {}}

    def media_for_session(self, session_id):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT job_id FROM app_jobs WHERE session_id=? AND kind='analysis' AND result_json IS NOT NULL "
                "ORDER BY created_at DESC LIMIT 1",
                (session_id,),
            ).fetchone()
        return self.media_for_job(row["job_id"]) if row else None

    def delete_session_jobs(self, session_id):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT video_path, replay_path FROM app_jobs WHERE session_id = ?", (session_id,)
            ).fetchall()
            conn.execute("DELETE FROM app_jobs WHERE session_id = ?", (session_id,))
            conn.commit()
        paths = []
        for row in rows:
            for value in (row["video_path"], row["replay_path"]):
                if value:
                    resolved = self.resolve_video_path(value)
                    if resolved not in paths:
                        paths.append(resolved)
        return paths


def _video_paths(server, session_id):
    media = server.job_store.media_for_session(session_id)
    if not media:
        return []
    return [path for path in (media.get("video_path"), media.get("replay_path")) if path]


def build_session_report(server, session_id, *, force=False):
    return report_service.build_report(
        server.db_path, session_id, server.pose_cache_dir, server.keyframe_dir,
        _video_paths(server, session_id), force=force)


def _run_analysis(server, job_id, session_id, player_id, metadata, video_path, analysis_video_path=None,
                  kind="analysis"):
    store = server.job_store
    try:
        with server.session_locks.setdefault(session_id, threading.Lock()):
            if not store.get(job_id):
                return
            if store.cancel_requested(job_id):
                raise AnalysisCancelled()
            store.update(job_id, status="running", message="Starting pose analysis")

            def report(progress, message):
                if store.cancel_requested(job_id):
                    raise AnalysisCancelled()
                # Pose analysis is ~85% of the work; replay copy and report follow.
                store.update(job_id, status="running", progress=round(progress * 0.85, 4), message=message)

            result = analyze_video(
                video_path=analysis_video_path or video_path,
                db_path=server.db_path,
                session_id=session_id,
                player_id=player_id,
                camera_view=metadata["camera_view"],
                shot_type=metadata["shot_type"],
                shot_style=metadata["shot_style"],
                pose_cache_path=str(server.pose_cache_dir / f"{session_id}.json.gz"),
                progress=report,
                persist_shots=(kind == "analysis"),
            )
            if kind == "analysis":
                store.update(job_id, progress=0.87, message="Preparing a replay copy that plays in every browser")
                replay = make_browser_replay(video_path, result.get("video") or {}, str(server.upload_dir))
                if replay:
                    store.set_replay_path(job_id, replay)
                result["replay_copy"] = bool(replay)
            if store.cancel_requested(job_id):
                raise AnalysisCancelled()
            store.update(job_id, progress=0.93, message="Measuring mechanics and writing your coaching report")
            try:
                built = build_session_report(server, session_id, force=True)
                result["report_ready"] = True
                result["report_summary"] = (built.get("overview") or {}).get("summary")
            except Exception as exc:  # the analysis itself succeeded; report can be rebuilt later
                result["report_ready"] = False
                result["report_error"] = f"The coaching report could not be built yet: {exc}"
            if kind == "analysis":
                store.update(job_id, status="complete", progress=1.0, message="Analysis complete", result=result)
            else:
                store.update(job_id, status="complete", progress=1.0,
                             message="Pose data refreshed; the coaching report was rebuilt.",
                             result={"session_id": session_id, "kind": kind, "report_ready": result.get("report_ready"),
                                     "frames_processed": result.get("frames_processed")})
    except AnalysisCancelled:
        store.update(job_id, status="failed", message="Analysis cancelled by you.", error="cancelled")
        if kind == "analysis":
            _discard_cancelled_session(server, session_id, job_id)
    except Exception as exc:
        store.update(
            job_id,
            status="failed",
            message="Analysis failed. Check that the clip is readable and the pose model is available.",
            error=str(exc),
        )
    finally:
        if analysis_video_path and analysis_video_path != video_path:
            Path(analysis_video_path).unlink(missing_ok=True)
        server.worker_slots.release()


def _discard_cancelled_session(server, session_id, job_id):
    """A cancelled first analysis leaves a half-written session: remove its rows and managed files.

    The job row stays (status failed, error 'cancelled') so the browser can show what happened.
    """
    try:
        ShotLabDB(server.db_path).delete_session(session_id)
        (server.pose_cache_dir / f"{session_id}.json.gz").unlink(missing_ok=True)
        media = server.job_store.media_for_job(job_id) or {}
        root = server.upload_dir.resolve()
        for value in (media.get("video_path"), media.get("replay_path")):
            if value and root in Path(value).resolve().parents:
                Path(value).unlink(missing_ok=True)
    except Exception:
        pass


class AppHandler(BaseHTTPRequestHandler):
    server_version = "BasketballShotLab/0.2"
    timeout = 120  # seconds per socket operation; drops idle or stalled connections

    def log_message(self, fmt, *args):
        # Avoid writing query-string profile fields and goals to the console log.
        print(f"[web] {self.command} {urlparse(self.path).path}")

    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _text_error(self, status, message):
        self._json(status, {"error": message})

    # ------------------------------------------------------------------ access control
    def _client_ip(self):
        raw = self.client_address[0]
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            return None
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        return ip

    def _host_name(self):
        host = (self.headers.get("Host") or "").strip().lower()
        if host.startswith("["):
            return host[1:host.find("]")] if "]" in host else host
        return host.rsplit(":", 1)[0] if host.count(":") == 1 else host

    def _token_ok(self):
        token = self.server.access_token
        if not token:
            return False
        supplied = self.headers.get("X-Access-Token") or ""
        cookie = self.headers.get("Cookie") or ""
        for part in cookie.split(";"):
            name, _, value = part.strip().partition("=")
            if name == ACCESS_COOKIE:
                supplied = supplied or value
        return bool(supplied) and hmac.compare_digest(supplied.strip().upper().encode(), token.encode())

    def _too_many_failures(self, ip):
        record = self.server.auth_failures.get(str(ip))
        if not record:
            return False
        count, first = record
        if time.time() - first > 600:
            self.server.auth_failures.pop(str(ip), None)
            return False
        return count >= 10

    def _record_failure(self, ip):
        count, first = self.server.auth_failures.get(str(ip), (0, time.time()))
        self.server.auth_failures[str(ip)] = (count + 1, first)

    def _send_html(self, status, body, extra_headers=()):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")
        for name, value in extra_headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def _is_local_request(self):
        ip = self._client_ip()
        return bool(ip and ip.is_loopback and self._host_name() in LOOPBACK_NAMES)

    def _guard(self):
        """Host check, optional LAN token, and CSRF header for state-changing requests."""
        ip = self._client_ip()
        if not self.server.lan_mode:
            if self._host_name() not in LOOPBACK_NAMES:
                self._text_error(403, "Unexpected Host header. Open the app at http://127.0.0.1 or http://localhost.")
                return False
        elif not self._is_local_request():
            if ip is None or not (ip.is_private or ip.is_link_local or ip.is_loopback):
                self._text_error(403, "Only devices on your local network can use this app.")
                return False
            if not self._token_ok():
                if self._too_many_failures(ip):
                    self._text_error(429, "Too many wrong access codes. Wait 10 minutes and try again.")
                    return False
                parsed = urlparse(self.path)
                supplied = parse_qs(parsed.query).get("token", [""])[0].strip().upper().replace(" ", "")
                if self.command == "GET" and parsed.path == "/" and supplied:
                    if hmac.compare_digest(supplied.encode(), self.server.access_token.encode()):
                        cookie = f"{ACCESS_COOKIE}={self.server.access_token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=2592000"
                        if self.server.tls_enabled:
                            cookie += "; Secure"
                        self.send_response(303)
                        self.send_header("Location", "/")
                        self.send_header("Set-Cookie", cookie)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return False
                    self._record_failure(ip)
                    self._send_html(401, ACCESS_PAGE.replace("__ERROR__", '<p class="err">That code is not right. Check it on the computer and try again.</p>'))
                    return False
                if self.command == "GET" and parsed.path == "/":
                    self._send_html(401, ACCESS_PAGE.replace("__ERROR__", ""))
                    return False
                self._text_error(401, "Access code required. Open the app's main page on this device and enter the code.")
                return False
        if self.command in {"POST", "PUT", "DELETE"} and self.headers.get(CSRF_HEADER) != "1":
            self._text_error(403, f"Missing {CSRF_HEADER} header; requests must come from the Shot Lab page.")
            return False
        return True

    def do_GET(self):
        if self._guard():
            self._do_get()

    def do_POST(self):
        if self._guard():
            self._do_post()

    def do_PUT(self):
        if self._guard():
            self._do_put()

    def do_DELETE(self):
        if self._guard():
            self._do_delete()

    def _do_get(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/connection":
            if not self._is_local_request():
                return self._text_error(403, "Connection details are only shown on the computer running the app.")
            return self._json(200, {
                "lan_enabled": bool(self.server.lan_mode), "urls": self.server.lan_urls,
                "access_code": self.server.access_token if self.server.lan_mode else None,
                "tls": bool(self.server.tls_enabled),
                "how_to_enable": "Restart with --lan to let phones on the same Wi-Fi connect (see README).",
            })

        report_match = re.fullmatch(r"/api/sessions/([A-Za-z0-9_-]{1,100})/report", parsed.path)
        if report_match:
            session_id = report_match.group(1)
            if not ShotLabDB(self.server.db_path).get_session(session_id):
                return self._text_error(404, "Session not found")
            if self.server.job_store.active_job_for_session(session_id):
                return self._text_error(409, "This session is still being analysed; the report will be ready when it finishes.")
            refresh = parse_qs(parsed.query).get("refresh", ["0"])[0] == "1"
            lock = self.server.session_locks.setdefault(session_id, threading.Lock())
            if not lock.acquire(timeout=60):
                return self._text_error(409, "The session is busy; try again in a moment.")
            try:
                report = build_session_report(self.server, session_id, force=refresh)
            except LookupError as exc:
                return self._text_error(404, str(exc))
            except Exception as exc:
                return self._text_error(500, f"Could not build the report: {exc}")
            finally:
                lock.release()
            source = self.server.job_store.media_for_session(session_id)
            report["meta"]["job_id"] = source["job_id"] if source else None
            return self._json(200, report)

        keyframe_match = re.fullmatch(r"/api/sessions/([A-Za-z0-9_-]{1,100})/keyframes/([^/]+)", parsed.path)
        if keyframe_match:
            session_id, name = keyframe_match.groups()
            if not KEYFRAME_NAME.fullmatch(name):
                return self._text_error(404, "Keyframe not found")
            folder = self.server.keyframe_dir / session_id
            return self._stream_local_file(str(folder / name), self.server.keyframe_dir, allow_range=False,
                                           content_type="image/jpeg")
        if parsed.path == "/api/health":
            ball_status = "unavailable"
            engine = getattr(self.server, "live_engine", None)
            if engine and engine.ball_tracker:
                ball_status = getattr(engine.ball_tracker, "mode", "unavailable")
            return self._json(200, {
                "status": "ok",
                "processing": "local_pose_analysis",
                "ball_rim_tracking": ball_status,
                "llm_chat_enabled": bool(self.server.llm_chat_enabled),
                "max_upload_bytes": MAX_UPLOAD_BYTES,
                "llm_provider": "gemini" if self.server.llm_chat_enabled else None,
            })

        history_match = re.fullmatch(r"/api/players/([A-Za-z0-9_-]{1,64})/history", parsed.path)
        if history_match:
            history = build_player_history(self.server.db_path, history_match.group(1))
            for session in history.get("sessions", []):
                session["job_id"] = self.server.job_store.latest_completed_job_for_session(session["session_id"])
            return self._json(200, history)

        match = re.fullmatch(r"/api/jobs/([a-f0-9]{32})", parsed.path)
        if match:
            job = self.server.job_store.get(match.group(1))
            if not job:
                return self._text_error(404, "Job not found")
            if job.get("status") == "complete" and job.get("result"):
                # The stored result is a snapshot from when analysis finished. Return
                # the current shot rows so saved human reviews survive a page reload.
                db = ShotLabDB(self.server.db_path)
                if not db.get_session(job["session_id"]):
                    return self._text_error(404, "This session was deleted")
                shots = db.get_shots(session_id=job["session_id"], min_confidence=None)
                for shot in shots:
                    shot["review_history"] = db.get_shot_review_history(shot["shot_id"])
                job["result"]["shots"] = shots
                job["result"]["shot_count"] = len(shots)
            return self._json(200, job)

        match = re.fullmatch(r"/api/jobs/([a-f0-9]{32})/video", parsed.path)
        if match:
            media = self.server.job_store.media_for_job(match.group(1))
            if not media:
                return self._text_error(404, "Job not found")
            want_original = parse_qs(parsed.query).get("original", ["0"])[0] == "1"
            path = media["video_path"] if want_original or not media.get("replay_path") else media["replay_path"]
            return self._stream_local_file(path, self.server.upload_dir, allow_range=True)

        match = re.fullmatch(r"/api/jobs/([a-f0-9]{32})/pose", parsed.path)
        if match:
            media = self.server.job_store.media_for_job(match.group(1))
            if not media:
                return self._text_error(404, "Job not found")
            pose_path = self.server.pose_cache_dir / f"{media['session_id']}.json.gz"
            return self._stream_local_file(str(pose_path), self.server.pose_cache_dir, allow_range=False,
                                           content_type="application/json", content_encoding="gzip")

        match = re.fullmatch(r"/api/sessions/([A-Za-z0-9_-]{1,100})", parsed.path)
        insights_match = re.fullmatch(r"/api/sessions/([A-Za-z0-9_-]{1,100})/insights", parsed.path)
        if insights_match:
            session_id = insights_match.group(1)
            insights = build_session_insights(self.server.db_path, session_id)
            if insights.get("status") == "NOT_FOUND":
                return self._text_error(404, insights["message"])
            for evidence in insights.get("evidence", []):
                source = self.server.job_store.media_for_session(evidence["session_id"])
                evidence["job_id"] = source["job_id"] if source else None
            return self._json(200, insights)
        if match:
            session_id = match.group(1)
            shots = ShotLabDB(self.server.db_path).get_shots(session_id=session_id, min_confidence=None)
            if not shots:
                return self._text_error(404, "Session not found or it contains no persisted shot proposals")
            db = ShotLabDB(self.server.db_path)
            for shot in shots:
                shot["review_history"] = db.get_shot_review_history(shot["shot_id"])
            return self._json(200, {
                "session_id": session_id,
                "shots": shots,
                "shot_count": len(shots),
                "outcomes": {"human": "unknown_pending_review", "automated": "not_run"},
            })

        context_match = re.fullmatch(r"/api/sessions/([A-Za-z0-9_-]{1,100})/workout-context", parsed.path)
        if context_match:
            return self._workout_context(context_match.group(1))
        workouts_match = re.fullmatch(r"/api/sessions/([A-Za-z0-9_-]{1,100})/workouts", parsed.path)
        if workouts_match:
            session_id = workouts_match.group(1)
            if not ShotLabDB(self.server.db_path).get_session(session_id):
                return self._text_error(404, "Session not found")
            return self._json(200, {"session_id": session_id,
                                    "workouts": ShotLabDB(self.server.db_path).list_workout_plans(session_id)})
        workout_match = re.fullmatch(r"/api/workouts/([A-Za-z0-9_]{1,40})", parsed.path)
        if workout_match:
            record = self._get_workout(workout_match.group(1))
            if not record:
                return self._text_error(404, "Workout not found")
            return self._json(200, self._workout_payload(record))
        media_match = re.fullmatch(r"/api/workout-media/([^/]{1,80})", parsed.path)
        if media_match:
            exercise_id = media_match.group(1)
            if not workout_catalog.EXERCISE_ID.fullmatch(exercise_id):
                return self._text_error(404, "Unknown exercise")
            try:
                catalog = workout_catalog.load_catalog(self.server.workout_catalog_path)
            except (OSError, ValueError) as exc:
                return self._text_error(500, f"The exercise catalog could not be loaded: {exc}")
            path = workout_catalog.media_path(catalog, exercise_id, self.server.workout_dir)
            if not path:
                return self._text_error(404, "No demonstration video is available for this exercise")
            return self._stream_local_file(str(path), self.server.workout_dir, allow_range=True, content_type="video/mp4")

        assets = {"/": ("index.html", "text/html; charset=utf-8"),
                  "/assets/app.js": ("app.js", "text/javascript; charset=utf-8"),
                  "/assets/app.css": ("app.css", "text/css; charset=utf-8"),
                  "/assets/report.js": ("report.js", "text/javascript; charset=utf-8"),
                  "/assets/workout.js": ("workout.js", "text/javascript; charset=utf-8"),
                  "/assets/fonts/archivo-variable.woff2": ("fonts/archivo-variable.woff2", "font/woff2")}
        asset = assets.get(parsed.path)
        if asset:
            path = WEB_ROOT / asset[0]
            try:
                body = path.read_bytes()
            except OSError:
                return self._text_error(500, "A web app asset is missing from the project")
            self.send_response(200)
            self.send_header("Content-Type", asset[1])
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-cache" if not asset[0].startswith("fonts/") else "max-age=604800")
            self.send_header("Referrer-Policy", "no-referrer")
            if asset[0] == "index.html":
                self.send_header("Content-Security-Policy",
                                 "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
                                 "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
                                 "font-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)
            return

        self._text_error(404, "Not found")

    def _stream_local_file(self, raw_path, allowed_root, *, allow_range, content_type=None, content_encoding=None):
        path = Path(raw_path).resolve()
        root = Path(allowed_root).resolve()
        if root not in path.parents or not path.is_file():
            return self._text_error(404, "Replay asset is not available")
        size = path.stat().st_size
        start, end, status = 0, size - 1, 200
        range_header = self.headers.get("Range") if allow_range else None
        if range_header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
            if not match or (not match.group(1) and not match.group(2)):
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            if match.group(1):
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else size - 1
            else:
                start = max(0, size - int(match.group(2)))
            if start >= size or end < start:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            end = min(end, size - 1)
            status = 206
        length = max(0, end - start + 1)
        self.send_response(status)
        self.send_header("Content-Type", content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(length))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        if allow_range:
            self.send_header("Accept-Ranges", "bytes")
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if content_encoding:
            self.send_header("Content-Encoding", content_encoding)
        self.end_headers()
        with path.open("rb") as source:
            source.seek(start)
            remaining = length
            while remaining:
                chunk = source.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def _read_json(self, limit):
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            size = -1
        if size <= 0 or size > limit:
            raise ValueError(f"Request body must be between 1 byte and {limit // 1024 or 1} KB of JSON")
        payload = json.loads(self.rfile.read(size))
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        return payload

    def _do_post(self):
        path = urlparse(self.path).path
        if path == "/api/live/process-frame":
            return self._handle_live_process_frame()
        if path == "/api/live/reset":
            return self._handle_live_reset()

        create_workout = re.fullmatch(r"/api/sessions/([A-Za-z0-9_-]{1,100})/workouts", path)
        if create_workout:
            return self._create_workout(create_workout.group(1))
        cancel_match = re.fullmatch(r"/api/jobs/([a-f0-9]{32})/cancel", path)
        if cancel_match:
            job = self.server.job_store.get(cancel_match.group(1))
            if not job:
                return self._text_error(404, "Job not found")
            if not self.server.job_store.request_cancel(cancel_match.group(1)):
                return self._text_error(409, f"This job is already {job['status']}.")
            return self._json(202, {"job_id": cancel_match.group(1), "status": "cancelling",
                                    "message": "Stopping after the current frame."})

        manual_match = re.fullmatch(r"/api/sessions/([A-Za-z0-9_-]{1,100})/shots", path)
        if manual_match:
            return self._add_manual_attempt(manual_match.group(1))

        refresh_match = re.fullmatch(r"/api/sessions/([A-Za-z0-9_-]{1,100})/refresh-pose", path)
        if refresh_match:
            return self._refresh_pose(refresh_match.group(1))
        remediation_match = re.fullmatch(r"/api/sessions/([A-Za-z0-9_-]{1,100})/remediation", path)
        if remediation_match:
            session_id = remediation_match.group(1)
            db = ShotLabDB(self.server.db_path)
            session = db.get_session(session_id)
            if not session:
                return self._text_error(404, "Session not found")
            insights = build_session_insights(self.server.db_path, session_id)
            cue = insights.get("cue")
            if not cue or cue.get("priority_tier", 0) <= 0:
                return self._text_error(409, "There is no evidence-gated drill recommendation to add yet")
            active = db.get_active_remediation(session["player_id"])
            if active:
                return self._json(200, {"remediation": active, "already_active": True})
            metric_key = cue.get("target_metric_key")
            metric = next((item for item in insights.get("cohort_metrics", []) if item.get("key") == metric_key), None)
            if not metric or metric.get("mean") is None:
                return self._text_error(409, "The cue metric no longer meets its evidence threshold")
            cohort = db.get_shots(
                player_id=session["player_id"], camera_view=session["camera_view"],
                shot_type=session["shot_type"], shot_style=session.get("shot_style", "jump_shot"),
                review_status="approved", min_confidence="SUFFICIENT",
            )
            make_count = sum(shot.get("outcome") == "make" for shot in cohort)
            labeled_count = sum(shot.get("outcome") in {"make", "miss"} for shot in cohort)
            notes = {
                "source_session_id": session_id,
                "camera_view": session["camera_view"], "shot_type": session["shot_type"],
                "shot_style": session.get("shot_style", "jump_shot"),
                "metric_key": metric_key, "metric_unit": metric.get("unit"),
                "metric_sample_count": metric.get("sample_count"),
                "source_evidence": insights.get("evidence", []),
            }
            remediation_id = db.save_remediation({
                "player_id": session["player_id"], "shot_style": session.get("shot_style", "jump_shot"),
                "targeted_flaw": cue.get("cue_title", metric_key),
                "priority_tier": int(cue.get("priority_tier", 1)),
                "recommended_drill": cue.get("recommended_drill", "Practice the displayed cue"),
                "drill_reps": int(cue.get("drill_reps", 10)),
                "pre_drill_metric_mean": metric["mean"], "pre_drill_metric_std": metric["sample_std"],
                "pre_make_count": make_count, "pre_total_count": labeled_count,
                "feedback_notes": json.dumps(notes, ensure_ascii=False),
            })
            return self._json(201, {"remediation": db.get_remediation(remediation_id), "already_active": False})

        chat_match = re.fullmatch(r"/api/sessions/([A-Za-z0-9_-]{1,100})/coach-chat", path)
        if chat_match:
            if not self.server.llm_chat_enabled:
                return self._text_error(503, "Gemini coach chat is disabled. Restart with --enable-llm-chat after configuring GEMINI_API_KEY.")
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size <= 0 or size > 8 * 1024:
                    return self._text_error(413, "Chat request must be between 1 byte and 8 KB")
                payload = json.loads(self.rfile.read(size))
            except (ValueError, json.JSONDecodeError):
                return self._text_error(400, "Chat request must be valid JSON")
            if not isinstance(payload, dict) or not isinstance(payload.get("question"), str):
                return self._text_error(400, "Provide a question as text")
            session_id = chat_match.group(1)
            insights = build_session_insights(self.server.db_path, session_id)
            if insights.get("status") == "NOT_FOUND":
                return self._text_error(404, insights["message"])
            stored = ShotLabDB(self.server.db_path).get_session_report(session_id)
            report = stored["report"] if stored else None
            try:
                response = answer_grounded_question(
                    payload["question"], insights, model=self.server.llm_model,
                    coach_findings=summarize_findings_for_llm(report),
                    recording_limits=(report or {}).get("overview", {}).get("limitations", []),
                )
            except ValueError as exc:
                return self._text_error(400, str(exc))
            except CoachUnavailable as exc:
                return self._text_error(502, str(exc))
            return self._json(200, response)

        if path != "/api/sessions":
            return self._text_error(404, "Not found")

        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self._text_error(400, "Invalid Content-Length")
        if size <= 0:
            return self._text_error(400, "Choose a video file before starting analysis")
        if size > MAX_UPLOAD_BYTES:
            return self._text_error(413, "Video is larger than the 250 MB local upload limit")
        if not self.server.worker_slots.acquire(blocking=False):
            return self._text_error(429, "The local analysis queue is full; wait for the current clip to finish")

        def fail_upload(status_code, msg):
            self.server.worker_slots.release()
            try:
                if 0 < size <= 10 * 1024 * 1024:
                    self.rfile.read(size)
            except Exception:
                pass
            return self._text_error(status_code, msg)

        query = parse_qs(urlparse(self.path).query)
        get_value = lambda key, default: query.get(key, [default])[0].strip()
        player_id = get_value("player_id", "player")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", player_id):
            return fail_upload(400, "Player ID may contain only letters, numbers, underscore, or hyphen")

        camera_view = get_value("camera_view", "frontal")
        shot_type = get_value("shot_type", "catch_and_shoot")
        shot_style = get_value("shot_style", "jump_shot")
        handedness = get_value("handedness", "unspecified")
        skill_level = get_value("skill_level", "beginner")
        goals = get_value("goals", "")
        pain_reported = get_value("pain_reported", "0") in {"1", "true", "yes"}
        if camera_view not in VALID_CAMERA_VIEWS or shot_type not in VALID_SHOT_TYPES or shot_style not in VALID_SHOT_STYLES:
            return fail_upload(400, "Choose a supported camera view, shot type, and shot style")
        if handedness not in VALID_HANDEDNESS or skill_level not in VALID_SKILL_LEVELS or len(goals) > 500:
            return fail_upload(400, "Check handedness, skill level, and keep goals under 500 characters")

        original_name = Path(unquote(self.headers.get("X-Upload-Filename", "session.mp4"))).name[:200] or "session.mp4"
        extension = Path(original_name).suffix.lower()
        if not extension:
            extension = MIME_EXTENSIONS.get((self.headers.get("X-Upload-Type") or "").split(";")[0].strip().lower(), "")
        if extension not in ALLOWED_EXTENSIONS:
            return fail_upload(415, "Supported video formats: MP4, MOV, M4V, AVI, MKV, and WebM")

        job_id = uuid.uuid4().hex
        upload_path = self.server.upload_dir / f"{job_id}{extension}"
        try:
            remaining = size
            with upload_path.open("xb") as target:
                while remaining:
                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("Upload ended before all declared bytes arrived")
                    target.write(chunk)
                    remaining -= len(chunk)
            video_metadata, analysis_video_path = prepare_video_for_analysis(
                str(upload_path), str(self.server.upload_dir)
            )
        except Exception as exc:
            upload_path.unlink(missing_ok=True)
            if "analysis_video_path" in locals() and analysis_video_path:
                Path(analysis_video_path).unlink(missing_ok=True)
            self.server.worker_slots.release()
            return self._text_error(400, f"Could not accept this video: {exc}")

        profile = {
            "source": "local_web_upload",
            "original_filename": original_name,
            "upload_id": job_id,
            "handedness": handedness,
            "skill_level": skill_level,
            "goals": goals,
            "pain_reported": pain_reported,
            "video": video_metadata,
        }
        try:
            db = ShotLabDB(self.server.db_path)
            session_id = db.create_session(
                player_id=player_id,
                camera_view=camera_view,
                shot_type=shot_type,
                shot_style=shot_style,
                fps=video_metadata["fps"],
                model_version="mediapipe_pose_current",
                notes=json.dumps(profile, ensure_ascii=False),
            )
        except Exception as exc:
            upload_path.unlink(missing_ok=True)
            if analysis_video_path:
                Path(analysis_video_path).unlink(missing_ok=True)
            self.server.worker_slots.release()
            return self._text_error(500, f"Could not create a session record: {exc}")
        metadata = {"camera_view": camera_view, "shot_type": shot_type, "shot_style": shot_style}
        job_created = False
        try:
            self.server.job_store.create(job_id, session_id, player_id, str(upload_path))
            job_created = True
            self.server.session_locks.setdefault(session_id, threading.Lock())
            self.server.executor.submit(
                _run_analysis, self.server, job_id, session_id, player_id, metadata,
                str(upload_path), analysis_video_path,
            )
        except Exception as exc:
            if job_created:
                self.server.job_store.update(job_id, status="failed", message="Could not queue analysis", error=str(exc))
            upload_path.unlink(missing_ok=True)
            if analysis_video_path:
                Path(analysis_video_path).unlink(missing_ok=True)
            self.server.worker_slots.release()
            return self._text_error(500, f"Could not queue this analysis: {exc}")

        self._json(202, {
            "job_id": job_id,
            "session_id": session_id,
            "status": "queued",
            "status_url": f"/api/jobs/{job_id}",
            "video": video_metadata,
            "message": "Video saved locally; pose analysis is queued on this device.",
        })

    def _handle_live_process_frame(self):
        engine = getattr(self.server, "live_engine", None)
        if engine is None:
            try:
                engine = LiveCameraEngine()
                self.server.live_engine = engine
            except Exception:
                engine = None
        if engine is None:
            return self._text_error(503, "Live camera engine is not available")
        try:
            content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > 8 * 1024 * 1024:
                return self._text_error(400, "Live frame must be between 1 byte and 8 MB")

            client_ts = None
            if self.headers.get("X-Timestamp-Ms"):
                try:
                    client_ts = int(self.headers["X-Timestamp-Ms"])
                except ValueError:
                    pass

            if content_type == "application/json":
                payload = json.loads(self.rfile.read(size))
                img_data = payload.get("image", "")
                if "," in img_data:
                    img_data = img_data.split(",", 1)[1]
                import base64
                frame_bytes = base64.b64decode(img_data)
                if payload.get("timestamp_ms") is not None:
                    client_ts = int(payload["timestamp_ms"])
            else:
                frame_bytes = self.rfile.read(size)

            if not frame_bytes:
                return self._text_error(400, "Empty frame data")

            np_arr = np.frombuffer(frame_bytes, np.uint8)
            frame_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if frame_bgr is None:
                return self._text_error(400, "Could not decode frame as image")

            result = engine.process_frame(frame_bgr, client_ts)
            return self._json(200, result)
        except Exception as exc:
            return self._text_error(500, f"Live frame error: {exc}")

    def _handle_live_reset(self):
        engine = getattr(self.server, "live_engine", None)
        if engine is None:
            try:
                engine = LiveCameraEngine()
                self.server.live_engine = engine
            except Exception:
                engine = None
        if engine is None:
            return self._text_error(503, "Live camera engine is not available")
        res = engine.reset_session()
        payload = {"status": "ok", "stats": res}
        payload.update(res)
        return self._json(200, payload)

    def _add_manual_attempt(self, session_id):
        """Add an attempt the detector missed. Human-made, so it is approved with provenance."""
        db = ShotLabDB(self.server.db_path)
        session = db.get_session(session_id)
        if not session:
            return self._text_error(404, "Session not found")
        media = self.server.job_store.media_for_session(session_id)
        if not media or not isinstance(media.get("frame_count"), int):
            return self._text_error(409, "This session has no analysed video, so attempts cannot be added.")
        try:
            payload = self._read_json(4 * 1024)
        except (ValueError, json.JSONDecodeError) as exc:
            return self._text_error(400, str(exc))
        frames = {}
        for key in ("start_frame", "set_frame", "release_frame", "end_frame"):
            value = payload.get(key)
            if value is None and key == "set_frame":
                continue
            if isinstance(value, bool) or not isinstance(value, int):
                return self._text_error(400, f"{key} must be a whole frame number")
            if not 0 <= value < media["frame_count"]:
                return self._text_error(400, f"{key} must be within this video's frame range (0–{media['frame_count'] - 1})")
            frames[key] = value
        ordered = [frames[k] for k in ("start_frame", "set_frame", "release_frame", "end_frame") if k in frames]
        if any(b < a for a, b in zip(ordered, ordered[1:])) or frames["end_frame"] - frames["start_frame"] < 3:
            return self._text_error(400, "Frames must be in order (start ≤ release ≤ end) and span at least 4 frames")
        notes = payload.get("review_notes", "")
        if not isinstance(notes, str) or len(notes) > 2000:
            return self._text_error(400, "Review notes must be text under 2000 characters")
        confidence, ratio = "INSUFFICIENT", 0.0
        try:
            series = shooting_analysis.PoseSeries(shooting_analysis.load_pose_cache(
                self.server.pose_cache_dir / f"{session_id}.json.gz"))
            window = list(series.window(frames["start_frame"], frames["end_frame"]))
            ratios = [sum(1 for j in KEY_JOINTS if series.point(f, j)) / len(KEY_JOINTS) for f in window]
            ratio = sum(ratios) / len(ratios) if ratios else 0.0
            confidence = "SUFFICIENT" if ratio >= MIN_SUFFICIENT_VALID_JOINT_RATIO else "INSUFFICIENT"
        except (OSError, ValueError):
            pass
        shot_id = db.save_shot({
            "session_id": session_id, "player_id": session["player_id"], "camera_view": session["camera_view"],
            "shot_type": session["shot_type"], "shot_style": session.get("shot_style") or "jump_shot",
            "machine_start_frame": None, "machine_dip_frame": None, "machine_set_frame": None,
            "machine_release_frame": None, "machine_end_frame": None,
            "annotated_start_frame": frames["start_frame"], "annotated_dip_frame": None,
            "annotated_set_frame": frames.get("set_frame"), "annotated_release_frame": frames["release_frame"],
            "annotated_end_frame": frames["end_frame"],
            "outcome": "unknown", "outcome_source": "manual_attempt", "review_status": "quarantined",
            "tracking_confidence": confidence, "valid_frame_ratio": ratio,
        })
        db.update_shot_annotation(shot_id, annotated_boundaries={}, outcome="unknown", outcome_source="manual_attempt",
                                  review_status="approved", review_notes=notes or "Attempt added manually in Review.")
        shot = db.get_shot(shot_id)
        shot["review_history"] = db.get_shot_review_history(shot_id)
        return self._json(201, {"shot": shot, "message": "Attempt added and approved. Its measurements appear in the report."})

    def _refresh_pose(self, session_id):
        """Re-run pose on the saved video to upgrade an older cache; reviewed shots are untouched."""
        db = ShotLabDB(self.server.db_path)
        session = db.get_session(session_id)
        if not session:
            return self._text_error(404, "Session not found")
        media = self.server.job_store.media_for_session(session_id)
        if not media or not media.get("video_path") or not Path(media["video_path"]).is_file():
            return self._text_error(409, "The original video for this session is not on this computer.")
        if self.server.job_store.active_job_for_session(session_id):
            return self._text_error(409, "This session is already being processed.")
        if not self.server.worker_slots.acquire(blocking=False):
            return self._text_error(429, "The local analysis queue is full; wait for the current clip to finish")
        try:
            _, analysis_copy = prepare_video_for_analysis(media["video_path"], str(self.server.upload_dir))
        except Exception as exc:
            self.server.worker_slots.release()
            return self._text_error(400, f"Could not read the saved video: {exc}")
        job_id = uuid.uuid4().hex
        self.server.job_store.create(job_id, session_id, session["player_id"], media["video_path"], kind="pose_refresh")
        metadata = {"camera_view": session["camera_view"], "shot_type": session["shot_type"],
                    "shot_style": session.get("shot_style") or "jump_shot"}
        self.server.executor.submit(_run_analysis, self.server, job_id, session_id, session["player_id"], metadata,
                                    media["video_path"], analysis_copy, "pose_refresh")
        return self._json(202, {"job_id": job_id, "status": "queued", "kind": "pose_refresh",
                                "message": "Re-running pose analysis on the saved video. Your reviews are kept."})

    def _do_put(self):
        path = urlparse(self.path).path
        progress_match = re.fullmatch(r"/api/workouts/([A-Za-z0-9_]{1,40})/progress", path)
        if progress_match:
            return self._update_workout(progress_match.group(1))
        goal_match = re.fullmatch(r"/api/players/([A-Za-z0-9_-]{1,64})/goal", path)
        if goal_match:
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size <= 0 or size > 1024:
                    return self._text_error(413, "Goal update must be under 1 KB")
                payload = json.loads(self.rfile.read(size))
            except (ValueError, json.JSONDecodeError):
                return self._text_error(400, "Goal update must be valid JSON")
            target = payload.get("weekly_session_target") if isinstance(payload, dict) else None
            try:
                ShotLabDB(self.server.db_path).set_weekly_session_target(goal_match.group(1), target)
            except ValueError as exc:
                return self._text_error(400, str(exc))
            return self._json(200, {"player_id": goal_match.group(1), "weekly_session_target": target})

        followup_match = re.fullmatch(r"/api/remediations/([A-Za-z0-9_-]{1,100})/follow-up", path)
        if followup_match:
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size <= 0 or size > 2 * 1024:
                    return self._text_error(413, "Follow-up selection must be under 2 KB")
                payload = json.loads(self.rfile.read(size))
            except (ValueError, json.JSONDecodeError):
                return self._text_error(400, "Follow-up selection must be valid JSON")
            session_id = payload.get("session_id") if isinstance(payload, dict) else None
            if not isinstance(session_id, str):
                return self._text_error(400, "Choose a follow-up session ID")
            db = ShotLabDB(self.server.db_path)
            remediation = db.get_remediation(followup_match.group(1))
            session = db.get_session(session_id)
            if not remediation or not session:
                return self._text_error(404, "Drill plan or follow-up session not found")
            if remediation["player_id"] != session["player_id"]:
                return self._text_error(409, "Follow-up must belong to the same player")
            try:
                notes = json.loads(remediation.get("feedback_notes") or "{}")
            except json.JSONDecodeError:
                notes = {}
            expected_context = (notes.get("camera_view"), notes.get("shot_type"), notes.get("shot_style"))
            actual_context = (session.get("camera_view"), session.get("shot_type"), session.get("shot_style") or "jump_shot")
            if session_id == notes.get("source_session_id") or actual_context != expected_context:
                return self._text_error(409, "Choose a different session with the same camera view and shot type/style")
            metric_key = notes.get("metric_key")
            if metric_key not in {"sequence_lag_ms", "elbow_angle_release_3d", "torso_sway_deg"}:
                return self._text_error(409, "The saved drill has no supported metric to compare")
            shots = db.get_shots(session_id=session_id, review_status="approved", min_confidence="SUFFICIENT")
            values = [float(shot[metric_key]) for shot in shots
                      if isinstance(shot.get(metric_key), (int, float)) and not isinstance(shot.get(metric_key), bool)]
            if len(values) < 5:
                return self._text_error(409, f"Follow-up needs at least five approved, confidence-sufficient shots with {metric_key}; found {len(values)}")
            made = sum(shot.get("outcome") == "make" for shot in shots)
            labeled = sum(shot.get("outcome") in {"make", "miss"} for shot in shots)
            notes.update({"follow_up_session_id": session_id, "follow_up_sample_count": len(values)})
            db.update_remediation_status(
                remediation["remediation_id"], status="completed", drill_completed=True,
                post_drill_metric_mean=statistics.mean(values),
                post_drill_metric_std=statistics.stdev(values),
                post_make_count=made, post_total_count=labeled,
                feedback_notes=json.dumps(notes, ensure_ascii=False),
            )
            updated = db.get_remediation(remediation["remediation_id"])
            return self._json(200, {
                "remediation": updated,
                "comparison": {
                    "metric_key": metric_key,
                    "pre_mean": remediation.get("pre_drill_metric_mean"),
                    "pre_sample_std": remediation.get("pre_drill_metric_std"),
                    "post_mean": statistics.mean(values),
                    "post_sample_std": statistics.stdev(values),
                    "post_sample_count": len(values),
                    "make_rate_pre": remediation.get("pre_make_count", 0) / remediation.get("pre_total_count") if remediation.get("pre_total_count") else None,
                    "make_rate_post": made / labeled if labeled else None,
                    "notice": "Descriptive before/after comparison only; it does not prove the drill caused a change.",
                },
            })

        view_match = re.fullmatch(r"/api/sessions/([A-Za-z0-9_-]{1,100})/camera-view", path)
        if view_match:
            session_id = view_match.group(1)
            try:
                payload = self._read_json(1024)
            except (ValueError, json.JSONDecodeError) as exc:
                return self._text_error(400, str(exc))
            view = payload.get("camera_view")
            if view not in VALID_CAMERA_VIEWS:
                return self._text_error(400, "Choose side_90, oblique_45, frontal or rear")
            db = ShotLabDB(self.server.db_path)
            if not db.get_session(session_id):
                return self._text_error(404, "Session not found")
            if self.server.job_store.active_job_for_session(session_id):
                return self._text_error(409, "Wait for the analysis to finish before changing the camera view.")
            with db._get_connection() as conn:
                conn.execute("UPDATE sessions SET camera_view = ? WHERE session_id = ?", (view, session_id))
                conn.execute("UPDATE shots SET camera_view = ?, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?", (view, session_id))
                conn.commit()
            return self._json(200, {"session_id": session_id, "camera_view": view,
                                    "message": "Camera view updated. Measurements and the report will be rebuilt for this view."})

        match = re.fullmatch(r"/api/shots/([A-Za-z0-9_-]{1,100})/review", path)
        if not match:
            return self._text_error(404, "Not found")
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > 64 * 1024:
                return self._text_error(413, "Review update must be between 1 byte and 64 KB")
            payload = json.loads(self.rfile.read(size))
        except (ValueError, json.JSONDecodeError):
            return self._text_error(400, "Review update must be valid JSON")
        if not isinstance(payload, dict):
            return self._text_error(400, "Review update must be a JSON object")

        shot_id = match.group(1)
        db = ShotLabDB(self.server.db_path)
        shot = db.get_shot(shot_id)
        if not shot:
            return self._text_error(404, "Shot not found")
        media = self.server.job_store.media_for_session(shot["session_id"])
        if not media or not isinstance(media.get("frame_count"), int):
            return self._text_error(409, "Completed source video metadata is unavailable for this shot")
        boundaries = payload.get("boundaries", {})
        allowed = {"start_frame", "dip_frame", "set_frame", "release_frame", "end_frame"}
        if not isinstance(boundaries, dict) or set(boundaries) - allowed:
            return self._text_error(400, "Boundaries contain unsupported fields")
        for key, value in boundaries.items():
            if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
                return self._text_error(400, f"{key} must be a frame number or null")
        effective = {}
        for key in ("start_frame", "dip_frame", "set_frame", "release_frame", "end_frame"):
            annotated = shot.get(f"annotated_{key}")
            machine = shot.get(f"machine_{key}")
            value = boundaries[key] if key in boundaries else (annotated if annotated is not None else machine)
            if value is not None:
                if value < 0 or value >= media["frame_count"]:
                    return self._text_error(400, f"{key} must be within this video's frame range")
                effective[key] = value
        ordered = [effective[key] for key in ("start_frame", "dip_frame", "set_frame", "release_frame", "end_frame")
                   if key in effective]
        if any(right < left for left, right in zip(ordered, ordered[1:])):
            return self._text_error(400, "Shot phase frames must be in chronological order")
        outcome = payload.get("outcome", shot.get("outcome", "unknown"))
        status = payload.get("review_status", shot.get("review_status", "quarantined"))
        notes = payload.get("review_notes", shot.get("review_notes") or "")
        if outcome not in {"make", "miss", "unknown"}:
            return self._text_error(400, "Outcome must be make, miss, or unknown")
        if status not in {"quarantined", "approved", "discarded"}:
            return self._text_error(400, "Review status must be quarantined, approved, or discarded")
        if not isinstance(notes, str) or len(notes) > 2000:
            return self._text_error(400, "Review notes must be under 2000 characters")
        if outcome in {"make", "miss"} and status != "approved":
            return self._text_error(400, "Confirm a make/miss label by setting review status to approved")
        if not db.update_shot_annotation(
            shot_id, annotated_boundaries=boundaries, outcome=outcome,
            outcome_source="manual_review", review_status=status, review_notes=notes,
        ):
            return self._text_error(500, "Could not save the review update")
        return self._json(200, {"shot": db.get_shot(shot_id), "history": db.get_shot_review_history(shot_id)})

    def _do_delete(self):
        workout_match = re.fullmatch(r"/api/workouts/([A-Za-z0-9_]{1,40})", urlparse(self.path).path)
        if workout_match:
            if not WORKOUT_ID.fullmatch(workout_match.group(1)) or \
                    not ShotLabDB(self.server.db_path).delete_workout_plan(workout_match.group(1)):
                return self._text_error(404, "Workout not found")
            return self._json(200, {"deleted_workout_id": workout_match.group(1)})
        match = re.fullmatch(r"/api/sessions/([A-Za-z0-9_-]{1,100})", urlparse(self.path).path)
        if not match:
            return self._text_error(404, "Not found")
        session_id = match.group(1)
        session_lock = self.server.session_locks.setdefault(session_id, threading.Lock())
        if not session_lock.acquire(blocking=False):
            return self._text_error(409, "Wait for this session's analysis to finish before deleting it")
        try:
            return self._delete_session(session_id)
        finally:
            session_lock.release()

    def _delete_session(self, session_id):
        db = ShotLabDB(self.server.db_path)
        session = db.delete_session(session_id)
        if not session:
            return self._text_error(404, "Session not found")

        warnings = []
        for video_path in self.server.job_store.delete_session_jobs(session_id):
            path = Path(video_path).resolve()
            root = self.server.upload_dir.resolve()
            if root not in path.parents:
                warnings.append("A stored video path was outside the managed upload directory and was left untouched.")
                continue
            try:
                path.unlink(missing_ok=True)
            except OSError:
                warnings.append("The database session was deleted, but an uploaded video could not be removed from disk.")
        keyframe_folder = (self.server.keyframe_dir / session_id).resolve()
        if self.server.keyframe_dir.resolve() in keyframe_folder.parents and keyframe_folder.is_dir():
            try:
                for image in keyframe_folder.glob("*.jpg"):
                    image.unlink(missing_ok=True)
                keyframe_folder.rmdir()
            except OSError:
                warnings.append("Some report keyframe images could not be removed from disk.")
        pose_path = (self.server.pose_cache_dir / f"{session_id}.json.gz").resolve()
        if self.server.pose_cache_dir.resolve() not in pose_path.parents:
            warnings.append("Pose cache path was outside the managed directory and was left untouched.")
        else:
            try:
                pose_path.unlink(missing_ok=True)
            except OSError:
                warnings.append("The database session was deleted, but its pose cache could not be removed from disk.")
        return self._json(200, {
            "deleted_session_id": session_id,
            "deleted_player_id": session["player_id"],
            "warnings": warnings,
            "message": "Session, shot records, review history, analysis, report, linked drill records, upload job metadata, video, replay copy, keyframes and pose data were deleted.",
        })


    # ------------------------------------------------------------------ 09 workout coach
    def _session_report(self, session_id):
        """The persisted report for exactly this session, or (None, error-sent)."""
        db = ShotLabDB(self.server.db_path)
        if not db.get_session(session_id):
            self._text_error(404, "Session not found")
            return None
        if self.server.job_store.active_job_for_session(session_id):
            self._text_error(409, "This session is still being analysed; the workout can be planned when the report is ready.")
            return None
        lock = self.server.session_locks.setdefault(session_id, threading.Lock())
        if not lock.acquire(timeout=60):
            self._text_error(409, "The session is busy; try again in a moment.")
            return None
        try:
            return build_session_report(self.server, session_id)
        except LookupError as exc:
            self._text_error(404, str(exc))
        except Exception as exc:
            self._text_error(500, f"Could not load the shooting report: {exc}")
        finally:
            lock.release()
        return None

    def _workout_catalog(self):
        try:
            return workout_catalog.load_catalog(self.server.workout_catalog_path)
        except (OSError, ValueError) as exc:
            self._text_error(500, f"The exercise catalog could not be loaded: {exc}")
            return None

    def _workout_context(self, session_id):
        report = self._session_report(session_id)
        if report is None:
            return
        catalog = self._workout_catalog()
        if catalog is None:
            return
        findings = workout_planner.extract_findings(report)
        status = workout_catalog.video_status(catalog, self.server.workout_dir)
        present = set(status["present"])
        equipment = []
        for key, info in catalog["equipment"].items():
            main = [e for e in catalog["exercises"] if e["equipment"] == key and "main" in e["phases"]]
            equipment.append({"key": key, "label": info["label"], "description": info["description"],
                              "exercises": len(main), "videos": sum(1 for e in main if e["id"] in present)})
        skill = (report.get("overview") or {}).get("skill_level")
        return self._json(200, {
            "session_id": session_id,
            "source": {k: findings[k] for k in ("session_id", "player_id", "session_date", "video_filename",
                                                "report_generated_at", "attempts_total", "attempts_confirmed")},
            "summary": workout_planner.summary_sentence(findings, catalog),
            "findings": findings,
            "defaults": {"fitness_level": skill if skill in workout_catalog.LEVELS else "intermediate" if skill == "coach" else "beginner",
                         "pain": bool((report.get("injury") or {}).get("pain_reported")), "duration_min": 20},
            "equipment": equipment, "goals": workout_planner.GOALS, "avoid": workout_planner.AVOID,
            "durations": list(workout_planner.DURATION_CHOICES),
            "video_library": {"mapped_present": len(status["present"]), "mapped_missing": len(status["missing"]),
                              "folder_found": Path(self.server.workout_dir).is_dir()},
            "workouts": ShotLabDB(self.server.db_path).list_workout_plans(session_id),
        })

    def _create_workout(self, session_id):
        try:
            raw = self._read_json(16 * 1024)
        except (ValueError, json.JSONDecodeError) as exc:
            return self._text_error(400, str(exc))
        catalog = self._workout_catalog()
        if catalog is None:
            return
        try:
            prefs = workout_planner.validate_preferences(raw, catalog)
        except ValueError as exc:
            return self._text_error(400, str(exc))
        report = self._session_report(session_id)
        if report is None:
            return
        cache = {}

        def available(exercise_id):
            if exercise_id not in cache:
                cache[exercise_id] = workout_catalog.media_path(catalog, exercise_id, self.server.workout_dir) is not None
            return cache[exercise_id]

        try:
            plan = workout_planner.build_plan(report, prefs, catalog, video_available=available)
        except Exception as exc:
            return self._text_error(500, f"Could not build the workout: {exc}")
        if not any(item["phase"] == "main" for item in plan["items"]):
            return self._text_error(422, "No video-demonstrated exercise fits this combination of equipment, level, pain and "
                                         "movements to avoid. Add Bodyweight or other equipment, or remove a limitation, and try again.")
        if plan["duration"]["total_s"] < plan["duration"]["target_s"]:
            # Only video-demonstrated exercises are prescribed; never pad the plan with text-only exercises.
            achievable = plan["duration"]["total_s"] // 60
            shorter = None
            for minutes in sorted(workout_planner.DURATION_CHOICES, reverse=True):
                if minutes >= prefs["duration_min"]:
                    continue
                trial = workout_planner.build_plan(report, dict(prefs, duration_min=minutes), catalog,
                                                   video_available=available)
                if trial["duration"]["total_s"] >= trial["duration"]["target_s"]:
                    shorter = minutes
                    break
            hint = f"choose {shorter} minutes, " if shorter else ""
            return self._text_error(422, f"With these choices only about {achievable} minutes of exercises with a "
                                         f"demonstration video fit, short of the {prefs['duration_min']} minutes you asked for. "
                                         f"To continue, {hint}add equipment, or remove a movement limitation.")
        workout_id = "wk_" + uuid.uuid4().hex[:20]
        session = ShotLabDB(self.server.db_path).get_session(session_id)
        ShotLabDB(self.server.db_path).save_workout_plan(workout_id, session_id, session["player_id"], plan, prefs,
                                                         plan["findings_used"])
        return self._json(201, self._workout_payload(self._get_workout(workout_id)))

    def _get_workout(self, workout_id):
        if not WORKOUT_ID.fullmatch(workout_id):
            return None
        return ShotLabDB(self.server.db_path).get_workout_plan(workout_id)

    @staticmethod
    def _workout_payload(record):
        return {key: record.get(key) for key in ("workout_id", "session_id", "player_id", "status", "plan", "state",
                                                 "progress", "feedback", "summary", "planned_duration_s",
                                                 "created_at", "started_at", "ended_at", "updated_at")}

    def _update_workout(self, workout_id):
        record = self._get_workout(workout_id)
        if not record:
            return self._text_error(404, "Workout not found")
        if record["status"] in workout_progress.FINAL_STATUSES:
            return self._text_error(409, "This workout is finished; its record can no longer change.")
        try:
            body = self._read_json(512 * 1024)
            status = body.get("status")
            if status not in ("active", "completed", "ended_early"):
                raise ValueError("status must be active, completed or ended_early")
            plan = record["plan"]
            state = workout_progress.validate_state(plan, body.get("state") or {})
            progress = workout_progress.validate_progress(plan, body.get("progress") or {})
            feedback = workout_progress.validate_feedback(body.get("feedback"))
        except (ValueError, json.JSONDecodeError) as exc:
            return self._text_error(400, str(exc))
        final = status in workout_progress.FINAL_STATUSES
        db = ShotLabDB(self.server.db_path)
        db.update_workout_progress(workout_id, status=status, state=state, progress=progress, feedback=feedback,
                                   started=True, ended=final)
        if final:
            updated = db.get_workout_plan(workout_id)
            summary = workout_progress.build_summary(plan, progress, feedback, status, updated["started_at"], updated["ended_at"])
            db.update_workout_progress(workout_id, status=status, state=state, progress=progress, summary=summary)
        return self._json(200, self._workout_payload(db.get_workout_plan(workout_id)))


class LocalAppServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    lan_mode = False
    access_token = None
    tls_enabled = False
    lan_urls: list = []
    workout_dir = workout_catalog.DEFAULT_WORKOUT_DIR
    workout_catalog_path = workout_catalog.DEFAULT_CATALOG_PATH

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.auth_failures = {}
        try:
            self.live_engine = LiveCameraEngine()
        except Exception:
            self.live_engine = None


ACCESS_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I to avoid typos on a phone


def generate_access_code(length=10):
    return "".join(secrets.choice(ACCESS_ALPHABET) for _ in range(length))


def local_network_addresses():
    """Best-effort list of this computer's private IPv4 addresses (no traffic is sent)."""
    found = []
    for probe in ("10.255.255.255", "192.168.255.255", "172.31.255.255"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect((probe, 1))
                address = sock.getsockname()[0]
        except OSError:
            continue
        if address not in found and ipaddress.ip_address(address).is_private and not address.startswith("127."):
            found.append(address)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = info[4][0]
            if address not in found and ipaddress.ip_address(address).is_private and not address.startswith("127."):
                found.append(address)
    except OSError:
        pass
    return found


def build_parser():
    parser = argparse.ArgumentParser(description="Run the local Basketball Shot Lab web app")
    parser.add_argument("--host", default=None,
                        help="Bind address. Default 127.0.0.1 (this computer only); with --lan the default is 0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", default="shot_lab.db", help="Shot Lab SQLite path")
    parser.add_argument("--upload-dir", default="user_data/uploads", help="Local directory for uploaded clips")
    parser.add_argument("--pose-cache-dir", default="user_data/pose_cache", help="Local directory for replay pose data")
    parser.add_argument("--keyframe-dir", default="user_data/keyframes", help="Local directory for report keyframe images")
    parser.add_argument("--workout-dir", default=str(workout_catalog.DEFAULT_WORKOUT_DIR),
                        help="Folder with the exercise demonstration videos (default: the project's workout/ folder)")
    parser.add_argument("--lan", action="store_true",
                        help="Allow phones on the same private network (Wi-Fi) to connect with an access code")
    parser.add_argument("--access-code", default=os.environ.get("SHOTLAB_ACCESS_CODE"),
                        help="Access code for --lan (default: a new random code each start, or SHOTLAB_ACCESS_CODE)")
    parser.add_argument("--tls-cert", help="PEM certificate for HTTPS (e.g. made with mkcert); needed for phone camera recording")
    parser.add_argument("--tls-key", help="PEM private key matching --tls-cert")
    parser.add_argument("--enable-llm-chat", action="store_true",
                        help="Enable optional network-backed coach chat using approved metrics only")
    parser.add_argument("--llm-model", default=os.environ.get("GEMINI_MODEL", "gemini-3.6-flash"),
                        help="Gemini model available to your API key (or set GEMINI_MODEL)")
    return parser


def main():
    args = build_parser().parse_args()
    host = args.host or ("0.0.0.0" if args.lan else "127.0.0.1")
    loopback = host in {"127.0.0.1", "localhost", "::1"}
    if not loopback and not args.lan:
        raise SystemExit("Binding to a non-loopback address needs --lan, which turns on access-code protection.")
    if args.lan:
        try:
            bind_ip = ipaddress.ip_address(host)
        except ValueError:
            raise SystemExit("With --lan, --host must be an IP address (default 0.0.0.0).")
        if not (bind_ip.is_unspecified or bind_ip.is_private or bind_ip.is_loopback):
            raise SystemExit("--lan only binds to private network addresses; this app must not be exposed to the internet.")
    if not 1 <= args.port <= 65535:
        raise SystemExit("Port must be between 1 and 65535")
    if bool(args.tls_cert) != bool(args.tls_key):
        raise SystemExit("Pass both --tls-cert and --tls-key, or neither.")
    if args.enable_llm_chat and not os.environ.get("GEMINI_API_KEY", "").strip():
        raise SystemExit("Gemini coach chat needs GEMINI_API_KEY. Configure it in the environment, or omit --enable-llm-chat.")
    if args.enable_llm_chat and not args.llm_model:
        raise SystemExit("Gemini coach chat needs a model. Pass --llm-model or set GEMINI_MODEL to one available to your API key.")
    access_code = None
    if args.lan:
        access_code = (args.access_code or generate_access_code()).strip().upper().replace(" ", "")
        if len(access_code) < 8 or not re.fullmatch(r"[A-Z0-9]+", access_code):
            raise SystemExit("The access code must be at least 8 letters/digits.")

    db_path = str(Path(args.db).resolve())
    upload_dir = Path(args.upload_dir).resolve()
    pose_cache_dir = Path(args.pose_cache_dir).resolve()
    keyframe_dir = Path(args.keyframe_dir).resolve()
    for folder in (upload_dir, pose_cache_dir, keyframe_dir):
        folder.mkdir(parents=True, exist_ok=True)
    server = LocalAppServer((host, args.port), AppHandler)
    scheme = "http"
    if args.tls_cert:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(args.tls_cert, args.tls_key)
        # Handshake lazily in each request thread so one stalled client cannot block accept().
        server.socket = context.wrap_socket(server.socket, server_side=True, do_handshake_on_connect=False)
        scheme = "https"
    server.db_path = db_path
    server.upload_dir = upload_dir
    server.pose_cache_dir = pose_cache_dir
    server.keyframe_dir = keyframe_dir
    server.workout_dir = Path(args.workout_dir).resolve()
    server.job_store = JobStore(db_path + ".web_jobs.sqlite3", upload_root=upload_dir)
    server.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="shot-analysis")
    server.worker_slots = threading.BoundedSemaphore(2)
    server.session_locks = {}
    server.llm_chat_enabled = args.enable_llm_chat
    server.llm_model = args.llm_model
    server.live_engine = LiveCameraEngine()
    server.lan_mode = bool(args.lan)
    server.access_token = access_code
    server.tls_enabled = scheme == "https"
    addresses = local_network_addresses() if args.lan and ipaddress.ip_address(host).is_unspecified else ([host] if args.lan else [])
    server.lan_urls = [f"{scheme}://{address}:{args.port}/" for address in addresses]

    print(f"Basketball Shot Lab web app on this computer: {scheme}://127.0.0.1:{args.port}")
    if args.lan:
        print("Phone access over Wi-Fi is ON (private network only, access code required).")
        for url in server.lan_urls or [f"{scheme}://<this computer's Wi-Fi IP>:{args.port}/"]:
            print(f"  Open on your phone: {url}")
        print(f"  Access code: {access_code}")
        print(f"  One-tap link (keep private): {(server.lan_urls or ['<url>'])[0]}?token={access_code}")
        if scheme == "http":
            print("  Uploading from the photo library works over http. Camera recording on phones needs https (--tls-cert/--tls-key).")
    print(f"Shot Lab database: {db_path}")
    print(f"Local video uploads: {upload_dir}")
    print("Processing: local MediaPipe pose + shot-phase detector + measurement engine; YOLO/outcomes are not run in this flow.")
    print(f"Optional AI coach chat: {'enabled (approved metric summaries are sent to Gemini)' if args.enable_llm_chat else 'disabled'}")
    print("Press Ctrl+C to stop the server.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
    finally:
        server.server_close()
        server.executor.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    main()
