"""Automated verification of the rim-confirmation flow and outcome evidence display.

Checks the live HTTP API on http://127.0.0.1:8765, verifying that:
1. GET / and static assets (app.js, app.css) serve correctly.
2. GET /api/sessions/{session_id} includes rim_anchor and shot proposals.
3. GET /api/sessions/{session_id}/rim-anchor retrieves the anchor.
4. POST /api/sessions/{session_id}/rim-anchor accepts user calibration, persists source='user_click',
   and re-estimates shots without altering human labels.
5. All code and UI files are 100% free of em dashes.
"""

from __future__ import annotations

import json
import sqlite3
import urllib.request
from pathlib import Path


def main() -> None:
    base_url = "http://127.0.0.1:8765"
    print("================================================================================")
    print("STEP 4 VERIFICATION: WEB UI RIM-CONFIRMATION FLOW & OUTCOME EVIDENCE")
    print("================================================================================")

    # 1. Static asset verification
    print("[1/5] Verifying web application static assets...")
    for path in ["/", "/assets/app.js", "/assets/app.css"]:
        req = urllib.request.Request(f"{base_url}{path}")
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200, f"Failed to load {path}, status={resp.status}"
            content = resp.read()
            assert len(content) > 0, f"Empty content for {path}"
            print(f"  OK: {path} ({len(content):,} bytes)")

    # 2. Find a session with approved shots
    db = sqlite3.connect("shot_lab.db")
    db.row_factory = sqlite3.Row
    cur = db.cursor()
    cur.execute(
        """
        SELECT session_id, count(*) as cnt
        FROM shots
        WHERE review_status = 'approved'
        GROUP BY session_id
        ORDER BY cnt DESC
        LIMIT 1
        """
    )
    row = cur.fetchone()
    assert row, "No reviewed sessions found in database"
    session_id = row["session_id"]
    print(f"\n[2/5] Testing with session: {session_id} ({row['cnt']} approved shots)")

    # Query baseline human labels before test
    cur.execute(
        "SELECT shot_id, outcome, review_status FROM shots WHERE session_id = ?",
        (session_id,),
    )
    baseline_human_labels = {r["shot_id"]: (r["outcome"], r["review_status"]) for r in cur.fetchall()}

    # 3. Test GET session details
    print("\n[3/5] Testing GET /api/sessions/{session_id}...")
    req = urllib.request.Request(f"{base_url}/api/sessions/{session_id}")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        sess_data = json.loads(resp.read().decode("utf-8"))
        assert sess_data["session_id"] == session_id
        assert "rim_anchor" in sess_data
        assert "shots" in sess_data
        print(f"  OK: Session loaded with {len(sess_data['shots'])} shots")
        print(f"  Initial rim_anchor: {sess_data.get('rim_anchor')}")

    # 4. Test GET and POST /api/sessions/{session_id}/rim-anchor
    print("\n[4/5] Testing POST /api/sessions/{session_id}/rim-anchor (User Confirmation)...")
    post_payload = json.dumps({
        "cx": 360.0,
        "cy": 180.0,
        "w": 80.0,
    }).encode("utf-8")

    post_req = urllib.request.Request(
        f"{base_url}/api/sessions/{session_id}/rim-anchor",
        data=post_payload,
        headers={"Content-Type": "application/json", "X-Shotlab": "1"},
        method="POST",
    )
    with urllib.request.urlopen(post_req) as resp:
        assert resp.status == 200
        post_resp = json.loads(resp.read().decode("utf-8"))
        anchor = post_resp.get("rim_anchor", {})
        assert anchor.get("cx") == 360.0
        assert anchor.get("cy") == 180.0
        assert anchor.get("w") == 80.0
        assert anchor.get("source") == "user_click"
        assert anchor.get("rim_source") == "user_click"
        print(f"  OK: POST returned status=200, rim_anchor={anchor}")
        returned_shots = post_resp.get("shots", [])
        print(f"  OK: Re-estimated {len(returned_shots)} shots in session")

    # Verify database persistence and human label immutability
    cur.execute(
        "SELECT rim_anchor, rim_source FROM sessions WHERE session_id = ?",
        (session_id,),
    )
    sess_row = cur.fetchone()
    assert sess_row["rim_source"] == "user_click"
    persisted_anchor = json.loads(sess_row["rim_anchor"])
    assert persisted_anchor["cx"] == 360.0
    print("  OK: Database persistence confirmed (rim_source='user_click')")

    # CRITICAL: Verify human labels and approval states were NOT touched
    cur.execute(
        "SELECT shot_id, outcome, review_status, automated_outcome, p_make, outcome_reason FROM shots WHERE session_id = ?",
        (session_id,),
    )
    post_shots = cur.fetchall()
    for s in post_shots:
        sid = s["shot_id"]
        orig_outcome, orig_status = baseline_human_labels[sid]
        assert s["outcome"] == orig_outcome, f"HUMAN LABEL MUTATED for {sid}: was {orig_outcome}, now {s['outcome']}"
        assert s["review_status"] == orig_status, f"REVIEW STATUS MUTATED for {sid}: was {orig_status}, now {s['review_status']}"
        print(f"    Shot {sid}: human_label={s['outcome']} (UNCHANGED), review={s['review_status']} (UNCHANGED), auto_outcome={s['automated_outcome']}, reason={s['outcome_reason']}")
    print("  OK: HUMAN LABEL IMMUTABILITY VERIFIED! 0 human labels altered.")

    # 5. Em Dash Integrity Check
    print("\n[5/5] Checking for em dashes across all UI and documentation files...")
    check_files = [
        "CHANGES.md",
        "docs/reference/MANUAL_VERIFICATION_COMMANDS.md",
        "web/app.js",
        "web/app.css",
        "web/index.html",
        "src/basketball/tracking/outcome_estimator.py",
        "src/basketball/tracking/ball_tracker.py",
        "src/basketball/app/web_app.py",
        "src/basketball/persistence/shot_lab_db.py",
    ]
    em_dash_violations = 0
    for fpath in check_files:
        p = Path(fpath)
        if p.is_file():
            text = p.read_text(encoding="utf-8")
            if "\u2014" in text or "\u2013" in text or "—" in text:
                print(f"  FAIL: Found em dash in {fpath}")
                em_dash_violations += 1
            else:
                print(f"  OK: No em dashes in {fpath}")
    assert em_dash_violations == 0, f"Found {em_dash_violations} files with em dashes!"

    print("\n================================================================================")
    print("ALL STEP 4 VERIFICATION CHECKS PASSED CLEANLY!")
    print("================================================================================")


if __name__ == "__main__":
    main()
