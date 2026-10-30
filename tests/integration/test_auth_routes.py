"""
test_auth_routes.py - In-memory tests for AppHandler auth & onboarding endpoints.
Runs in sandboxed mode without requiring loopback sockets.
"""

import io
import json
import tempfile
import unittest
from pathlib import Path

import basketball.app.web_app as web_app
from basketball.persistence.shot_lab_db import ShotLabDB


class MockServer:
    def __init__(self, db_path):
        self.db_path = db_path
        self.access_token = None
        self.lan_mode = False
        self.lan_urls = []
        self.tls_enabled = False
        self.ca_der_path = None
        self.ca_fingerprint = None
        self.setup_url = None
        self.auth_failures = {}


class DummyRequest:
    def __init__(self, raw_bytes=b""):
        self._rfile = io.BytesIO(raw_bytes)
        self._wfile = io.BytesIO()

    def makefile(self, mode, *args, **kwargs):
        if "b" in mode:
            if "r" in mode:
                return self._rfile
            return self._wfile
        raise ValueError("binary mode expected")

    def sendall(self, data):
        self._wfile.write(data)


def simulate_request(server, method, path, body=None, headers=None):
    hdrs = dict(headers or {})
    body_bytes = b""
    if body is not None:
        if isinstance(body, (dict, list)):
            body_bytes = json.dumps(body).encode("utf-8")
            hdrs["Content-Type"] = "application/json"
        elif isinstance(body, str):
            body_bytes = body.encode("utf-8")
        else:
            body_bytes = body
        hdrs["Content-Length"] = str(len(body_bytes))
    if method in {"POST", "PUT", "DELETE"}:
        hdrs.setdefault("X-Shotlab", "1")
    hdrs.setdefault("Host", "127.0.0.1:8000")

    # Construct raw HTTP request
    header_lines = [f"{method} {path} HTTP/1.1\r\n"]
    for k, v in hdrs.items():
        header_lines.append(f"{k}: {v}\r\n")
    header_lines.append("\r\n")
    raw_req = "".join(header_lines).encode("utf-8") + body_bytes

    dummy = DummyRequest(raw_req)

    class InMemHandler(web_app.AppHandler):
        def __init__(self, req, client_addr, srv):
            self.server = srv
            self.client_address = client_addr
            self.connection = req
            self.rfile = req.makefile("rb")
            self.wfile = req.makefile("wb")
            try:
                self.handle_one_request()
            except Exception:
                pass

        def log_message(self, *args):
            pass

    handler = InMemHandler(dummy, ("127.0.0.1", 54321), server)
    raw_output = dummy._wfile.getvalue()

    # Parse response
    parts = raw_output.split(b"\r\n\r\n", 1)
    header_part = parts[0].decode("utf-8", errors="replace")
    body_part = parts[1] if len(parts) > 1 else b""

    lines = header_part.split("\r\n")
    status_line = lines[0] if lines else ""
    status_code = int(status_line.split(" ")[1]) if len(status_line.split(" ")) > 1 else 500

    resp_headers = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            resp_headers[k.strip().lower()] = v.strip()

    return status_code, resp_headers, body_part


class TestAuthRoutes(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="shotlab_inmem_auth_"))
        self.db_path = str(self.tmp / "shotlab.db")
        self.server = MockServer(self.db_path)
        # Ensure schema
        ShotLabDB(self.db_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_auth_me_unauthenticated(self):
        code, hdrs, body = simulate_request(self.server, "GET", "/api/auth/me")
        self.assertEqual(code, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertIsNone(data.get("user"))

    def test_signup_login_profile_logout_cycle(self):
        signup_data = {
            "name": "Klay Thompson",
            "email": "klay@warriors.test",
            "password": "champion_release_11",
            "player_id": "klay_11",
            "skill_level": "advanced",
            "handedness": "right",
            "shot_style": "jump_shot",
            "height_cm": 198.0,
            "wingspan_cm": 206.0,
            "goals": "Zero-dip quick release and balanced landing",
            "pain_reported": True,
            "onboarding_completed": True
        }
        # 1. Signup
        code, hdrs, body = simulate_request(self.server, "POST", "/api/auth/signup", body=signup_data)
        self.assertEqual(code, 201)
        res = json.loads(body.decode("utf-8"))
        self.assertIn("user", res)
        self.assertEqual(res["user"]["name"], "Klay Thompson")
        self.assertEqual(res["user"]["player_id"], "klay_11")
        self.assertTrue(res["user"]["pain_reported"])
        self.assertTrue(res["user"]["onboarding_completed"])
        token = res["token"]

        # Cookie header for subsequent requests
        auth_cookie = {"cookie": f"shotlab_user_session={token}"}

        # 2. Check /api/auth/me with cookie
        code, hdrs, body = simulate_request(self.server, "GET", "/api/auth/me", headers=auth_cookie)
        self.assertEqual(code, 200)
        me_res = json.loads(body.decode("utf-8"))
        self.assertIsNotNone(me_res.get("user"))
        self.assertEqual(me_res["user"]["email"], "klay@warriors.test")
        self.assertTrue(me_res["user"]["pain_reported"])

        # 3. Duplicate signup is rejected
        code, hdrs, body = simulate_request(self.server, "POST", "/api/auth/signup", body=signup_data)
        self.assertEqual(code, 409)

        # 4. Profile update
        update_data = {
            "goals": "Refine release angle consistency",
            "height_cm": 201.0,
            "pain_reported": False
        }
        code, hdrs, body = simulate_request(self.server, "POST", "/api/auth/profile", body=update_data, headers=auth_cookie)
        self.assertEqual(code, 200)
        up_res = json.loads(body.decode("utf-8"))
        self.assertEqual(up_res["user"]["goals"], "Refine release angle consistency")
        self.assertEqual(up_res["user"]["height_cm"], 201.0)
        self.assertFalse(up_res["user"]["pain_reported"])

        # 5. Logout
        code, hdrs, body = simulate_request(self.server, "POST", "/api/auth/logout", headers=auth_cookie)
        self.assertEqual(code, 200)
        self.assertIn("max-age=0", hdrs.get("set-cookie", "").lower())

        # 6. /api/auth/me after logout returns null user
        code, hdrs, body = simulate_request(self.server, "GET", "/api/auth/me", headers=auth_cookie)
        self.assertEqual(code, 200)
        logged_out_me = json.loads(body.decode("utf-8"))
        self.assertIsNone(logged_out_me.get("user"))

        # 7. Login with credentials
        login_data = {"email": "klay@warriors.test", "password": "champion_release_11"}
        code, hdrs, body = simulate_request(self.server, "POST", "/api/auth/login", body=login_data)
        self.assertEqual(code, 200)
        login_res = json.loads(body.decode("utf-8"))
        self.assertEqual(login_res["user"]["name"], "Klay Thompson")

        # 8. Login with wrong password returns 401
        wrong_data = {"email": "klay@warriors.test", "password": "wrongpassword"}
        code, hdrs, body = simulate_request(self.server, "POST", "/api/auth/login", body=wrong_data)
        self.assertEqual(code, 401)

    def test_hero_asset_served(self):
        code, hdrs, body = simulate_request(self.server, "GET", "/assets/hero.jpg")
        self.assertEqual(code, 200)
        self.assertEqual(hdrs.get("content-type"), "image/jpeg")
        self.assertTrue(len(body) > 1000)

    def test_demo_accounts_endpoint(self):
        code, hdrs, body = simulate_request(self.server, "GET", "/api/auth/demo-accounts")
        self.assertEqual(code, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("accounts", data)
        self.assertEqual(len(data["accounts"]), 4)
        names = [a["name"] for a in data["accounts"]]
        self.assertIn("Pranab", names)
        self.assertIn("Pavan", names)
        self.assertIn("Pracheth", names)
        self.assertIn("Puneeth", names)

    def test_demo_login_endpoint(self):
        # 1. 1-click login as Pranab
        code, hdrs, body = simulate_request(self.server, "POST", "/api/auth/demo-login", body={"athlete": "pranab"})
        self.assertEqual(code, 200)
        res = json.loads(body.decode("utf-8"))
        self.assertIn("user", res)
        self.assertEqual(res["user"]["name"], "Pranab")
        self.assertEqual(res["user"]["player_id"], "pranab")
        self.assertEqual(res["user"]["handedness"], "right")
        self.assertEqual(res["user"]["height_cm"], 182.0)
        self.assertFalse(res["user"]["pain_reported"])
        self.assertIn("shotlab_user_session=", hdrs.get("set-cookie", ""))

        # 2. 1-click login as Puneeth (has soreness noted)
        code, hdrs, body = simulate_request(self.server, "POST", "/api/auth/demo-login", body={"athlete": "puneeth"})
        self.assertEqual(code, 200)
        res_puneeth = json.loads(body.decode("utf-8"))
        self.assertEqual(res_puneeth["user"]["name"], "Puneeth")
        self.assertTrue(res_puneeth["user"]["pain_reported"])

        # 3. Invalid athlete returns 404
        code, hdrs, body = simulate_request(self.server, "POST", "/api/auth/demo-login", body={"athlete": "nonexistent_player"})
        self.assertEqual(code, 404)


if __name__ == "__main__":
    unittest.main()
