"""Tests for the AI coach chat providers with mocked HTTP (no real API key or network needed)."""

import io
import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError

import basketball.coaching.llm_coach as llm

FAKE_KEY = "xai-test-not-a-real-key-123"
FIXTURE = Path(__file__).resolve().parents[1] / "support" / "workout_report_fixture.json"
INSIGHTS = {"session_id": "sess_test", "status": "INSUFFICIENT_EVIDENCE", "context": {"player_id": "p"},
            "session_metrics": [{"label": "Knee bend", "sample_count": 2, "minimum_required": 5}], "evidence": []}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code, body):
    return HTTPError(llm.XAI_ENDPOINT, code, "error", {}, io.BytesIO(json.dumps(body).encode()))


class XaiProviderTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"XAI_API_KEY": FAKE_KEY}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("XAI_MODEL", None)

    def ask(self, **kw):
        return llm.answer_grounded_question("Why is my torso flagged?", INSIGHTS, model="grok-4.7", provider="xai", **kw)

    def test_request_follows_the_responses_api_and_parses_output(self):
        captured = {}

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["headers"] = dict(req.header_items())
            captured["body"] = json.loads(req.data.decode())
            captured["timeout"] = timeout
            return FakeResponse(json.dumps({"output": [
                {"type": "reasoning", "summary": []},
                {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Keep your chest tall."}]},
            ]}).encode())

        report = json.loads(FIXTURE.read_text())
        with mock.patch.object(llm, "urlopen", side_effect=fake_urlopen):
            result = self.ask(coach_findings=llm.summarize_findings_for_llm(report),
                              report_summary=llm.summarize_report_for_llm(report))
        self.assertEqual(captured["url"], "https://api.x.ai/v1/responses")
        self.assertEqual(captured["headers"]["Authorization"], f"Bearer {FAKE_KEY}")
        self.assertEqual(captured["body"]["model"], "grok-4.7")
        self.assertIs(captured["body"]["store"], False)
        self.assertEqual([m["role"] for m in captured["body"]["input"]], ["system", "user"])
        user = json.loads(captured["body"]["input"][1]["content"])
        self.assertEqual(user["question"], "Why is my torso flagged?")
        self.assertTrue(user["evidence"]["rules_based_coach_findings"])
        self.assertIn("session", user["evidence"]["report"])
        self.assertEqual(result["answer"], "Keep your chest tall.")
        self.assertEqual(result["provider"], "xai")
        self.assertNotIn(FAKE_KEY, json.dumps(result))

    def test_top_level_output_text_is_accepted(self):
        with mock.patch.object(llm, "urlopen", return_value=FakeResponse(b'{"output_text": "Short answer."}')):
            self.assertEqual(self.ask()["answer"], "Short answer.")

    def test_errors_are_mapped_without_leaking_the_key(self):
        cases = [
            (http_error(401, {"error": "Incorrect API key provided"}), "invalid_key"),
            (http_error(400, {"error": "Incorrect API key provided: xai-***"}), "invalid_key"),
            (http_error(403, {"error": "Your newly created team doesn't have any credits yet."}), "no_credits"),
            (http_error(403, {"error": "The caller does not have permission"}), "forbidden"),
            (http_error(404, {"error": "The model grok-x does not exist"}), "model_not_found"),
            (http_error(429, {"error": "rate limit"}), "rate_limited"),
            (http_error(500, {"error": "boom"}), "service_error"),
            (URLError(socket.timeout("timed out")), "timeout"),
            (URLError(OSError("no route")), "unreachable"),
            (TimeoutError(), "timeout"),
        ]
        for error, code in cases:
            with mock.patch.object(llm, "urlopen", side_effect=error):
                with self.assertRaises(llm.CoachUnavailable) as ctx:
                    self.ask()
            self.assertEqual(ctx.exception.code, code, error)
            self.assertNotIn(FAKE_KEY, str(ctx.exception))
        self.assertEqual(llm._xai_error(http_error(429, {})).status, 429)

    def test_empty_or_unreadable_answers(self):
        with mock.patch.object(llm, "urlopen", return_value=FakeResponse(b'{"output": []}')):
            with self.assertRaises(llm.CoachUnavailable) as ctx:
                self.ask()
        self.assertEqual(ctx.exception.code, "empty")
        with mock.patch.object(llm, "urlopen", return_value=FakeResponse(b"<html>")):
            with self.assertRaises(llm.CoachUnavailable) as ctx:
                self.ask()
        self.assertEqual(ctx.exception.code, "bad_response")

    def test_missing_key_gives_setup_message(self):
        with mock.patch.dict(os.environ, {"XAI_API_KEY": ""}):
            with self.assertRaises(llm.CoachUnavailable) as ctx:
                self.ask()
        self.assertEqual(ctx.exception.code, "not_configured")
        self.assertIn(".env", str(ctx.exception))

    def test_question_validation(self):
        for question in ("", "   ", "x" * 1001):
            with self.assertRaises(ValueError):
                llm.answer_grounded_question(question, INSIGHTS, model="grok-4.7", provider="xai")

    def test_key_check(self):
        listing = FakeResponse(json.dumps({"data": [{"id": "grok-4.7"}, {"id": "grok-4-fast"}]}).encode())
        with mock.patch.object(llm, "urlopen", return_value=listing):
            self.assertEqual(llm.check_xai_access()["state"], "key_ok")
        other = FakeResponse(json.dumps({"data": [{"id": "grok-9"}]}).encode())
        with mock.patch.object(llm, "urlopen", return_value=other):
            status = llm.check_xai_access()
        self.assertEqual(status["state"], "model_not_listed")
        self.assertIn("XAI_MODEL", status["message"])
        with mock.patch.object(llm, "urlopen", side_effect=http_error(401, {"error": "bad key"})):
            self.assertEqual(llm.check_xai_access()["state"], "invalid_key")
        with mock.patch.object(llm, "urlopen", side_effect=URLError("offline")):
            self.assertEqual(llm.check_xai_access()["state"], "unreachable")


class ConfigTest(unittest.TestCase):
    def test_dotenv_loading_never_overrides_the_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("# comment\nXAI_API_KEY='from-file'\nexport XAI_MODEL=grok-test  # note\nBAD LINE\nEMPTY=\n")
            with mock.patch.dict(os.environ, {"XAI_API_KEY": "from-env"}, clear=False):
                os.environ.pop("XAI_MODEL", None)
                loaded = llm.load_dotenv(env)
                self.assertEqual(os.environ["XAI_API_KEY"], "from-env")
                self.assertEqual(os.environ["XAI_MODEL"], "grok-test")
                self.assertIn("XAI_MODEL", loaded)
                self.assertNotIn("XAI_API_KEY", loaded)
            self.assertEqual(llm.load_dotenv(Path(tmp) / "missing.env"), [])

    def test_provider_selection_and_models(self):
        with mock.patch.dict(os.environ, {"XAI_API_KEY": "k", "GEMINI_API_KEY": "g"}, clear=False):
            os.environ.pop("XAI_MODEL", None)
            self.assertEqual(llm.configured_provider(), "xai")
            self.assertEqual(llm.configured_provider("gemini"), "gemini")
            self.assertEqual(llm.default_model("xai"), llm.XAI_DEFAULT_MODEL)
            os.environ["XAI_MODEL"] = "grok-custom"
            self.assertEqual(llm.default_model("xai"), "grok-custom")
        with mock.patch.dict(os.environ, {"XAI_API_KEY": "", "GEMINI_API_KEY": ""}, clear=False):
            self.assertIsNone(llm.configured_provider())
            self.assertIsNone(llm.configured_provider("xai"))

    def test_report_summary_is_bounded_and_text_only(self):
        report = json.loads(FIXTURE.read_text())
        report["technical"] = [{"area": f"A{i}", "observation": "x" * 2000, "confidence": "high"} for i in range(30)]
        summary = llm.summarize_report_for_llm(report, [{"title": "Workout", "status": "planned", "summary": "y" * 900}])
        self.assertEqual(len(summary["technical_areas"]), 10)
        self.assertLessEqual(len(summary["technical_areas"][0]["observation"]), 201)
        self.assertEqual(summary["latest_workout_plan"]["title"], "Workout")
        evidence = llm.build_evidence(INSIGHTS, report_summary=summary)
        self.assertLess(len(json.dumps(evidence)), 20000)
        self.assertEqual(llm.summarize_report_for_llm(None), {})


if __name__ == "__main__":
    unittest.main()
