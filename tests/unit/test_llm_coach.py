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
        keys = {"XAI_API_KEY": "k", "GEMINI_API_KEY": "g", "GROQ_API_KEY": "q"}
        with mock.patch.dict(os.environ, keys, clear=False):
            for name in ("XAI_MODEL", "GROQ_MODEL", "GEMINI_MODEL"):
                os.environ.pop(name, None)
            self.assertEqual(llm.configured_providers(), ["groq", "gemini"], "Groq primary, Gemini backup; xAI not automatic")
            self.assertEqual(llm.configured_provider(), "groq")
            self.assertEqual(llm.configured_providers("gemini"), ["gemini", "groq"])
            self.assertEqual(llm.configured_providers("xai"), ["xai"])
            self.assertEqual(llm.default_model("groq"), "openai/gpt-oss-120b")
            self.assertEqual(llm.default_model("gemini"), "gemini-3.8-flash")
            self.assertEqual(llm.default_model("xai"), llm.XAI_DEFAULT_MODEL)
            os.environ["GROQ_MODEL"] = "openai/gpt-oss-20b"
            self.assertEqual(llm.default_model("groq"), "openai/gpt-oss-20b")
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "", "GEMINI_API_KEY": "g", "XAI_API_KEY": ""}, clear=False):
            self.assertEqual(llm.configured_providers(), ["gemini"])
        with mock.patch.dict(os.environ, {"XAI_API_KEY": "", "GEMINI_API_KEY": "", "GROQ_API_KEY": ""}, clear=False):
            self.assertIsNone(llm.configured_provider())
            self.assertEqual(llm.configured_providers(), [])
            self.assertIn("GROQ_API_KEY", llm.setup_message())
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "your_groq_api_key", "GEMINI_API_KEY": "your_gemini_api_key"}):
            self.assertEqual(llm.configured_providers(), [], ".env.example placeholders do not count as keys")

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


GROQ_KEY = "gsk_test_not_a_real_key"
GEMINI_KEY = "AIza_test_not_a_real_key"
CHAIN = [("groq", "openai/gpt-oss-120b"), ("gemini", "gemini-3.8-flash")]

try:
    import groq  # noqa: F401
    import httpx
except ImportError:  # pragma: no cover - optional dependency
    httpx = None


def sse(*events, done=True):
    """An OpenAI-style server-sent-event body, as Groq streams chat completions."""
    lines = [f"data: {json.dumps(event)}\n\n" for event in events]
    if done:
        lines.append("data: [DONE]\n\n")
    return "".join(lines).encode()


def chunk(content=None, finish=None, reasoning=None):
    delta = {"role": "assistant"}
    if content is not None:
        delta["content"] = content
    if reasoning is not None:
        delta["reasoning"] = reasoning
    return {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "openai/gpt-oss-120b",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


class TrackedStream(httpx.SyncByteStream if httpx else object):
    """Response body that records whether the client closed it (cancellation)."""

    def __init__(self, parts):
        self.parts, self.closed = parts, False

    def __iter__(self):
        yield from self.parts

    def close(self):
        self.closed = True


def gemini_reply(text):
    return FakeResponse(json.dumps({"candidates": [{"content": {"parts": [
        {"text": "thinking...", "thought": True}, {"text": text}]}}]}).encode())


@unittest.skipIf(httpx is None, "groq SDK / httpx not installed")
class GroqStreamingTest(unittest.TestCase):
    """The primary provider through the official Groq SDK, with the HTTP layer mocked (no key, no network)."""

    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"GROQ_API_KEY": GROQ_KEY, "GEMINI_API_KEY": GEMINI_KEY})
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("GROQ_MODEL", "GEMINI_MODEL"):
            os.environ.pop(name, None)
        self.requests = []
        self.reply = None                # (status, headers, body-bytes | TrackedStream)
        self.gemini_calls = []

        def handler(request):
            self.requests.append(request)
            status, headers, body = self.reply
            if isinstance(body, TrackedStream):
                return httpx.Response(status, headers=headers, stream=body)
            return httpx.Response(status, headers=headers, content=body)
        llm.GROQ_HTTP_CLIENT = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(setattr, llm, "GROQ_HTTP_CLIENT", None)

        def gemini(req, timeout):
            self.gemini_calls.append(req)
            return gemini_reply("Gemini backup answer.")
        gem = mock.patch.object(llm, "urlopen", side_effect=gemini)
        gem.start()
        self.addCleanup(gem.stop)

    def stream_ok(self, *chunks):
        self.reply = (200, {"content-type": "text/event-stream"}, sse(*chunks))

    def error(self, status, code="some_code", message="error"):
        body = json.dumps({"error": {"message": message, "type": "invalid_request_error", "code": code}}).encode()
        self.reply = (status, {"content-type": "application/json"}, body)

    def events(self, chain=CHAIN, question="What should I practise?"):
        return list(llm.stream_answer(question, INSIGHTS, providers=chain))

    # ------------------------------------------------------------------ request
    def test_request_uses_the_specified_parameters(self):
        self.stream_ok(chunk("Hi"), chunk(finish="stop"))
        self.events()
        self.assertEqual(len(self.requests), 1)
        req = self.requests[0]
        self.assertEqual(str(req.url), "https://api.groq.com/openai/v1/chat/completions")
        self.assertEqual(req.headers["authorization"], f"Bearer {GROQ_KEY}")
        body = json.loads(req.content)
        self.assertEqual(body["model"], "openai/gpt-oss-120b")
        self.assertEqual(body["temperature"], 1)
        self.assertEqual(body["max_completion_tokens"], 2048)
        self.assertEqual(body["top_p"], 1)
        self.assertEqual(body["reasoning_effort"], "medium")
        self.assertIs(body["stream"], True)
        self.assertIsNone(body.get("stop"))
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user"])
        self.assertIn("evidence", json.loads(body["messages"][1]["content"]))
        self.assertNotIn("include_reasoning", body)

    def test_model_comes_from_groq_model(self):
        os.environ["GROQ_MODEL"] = "openai/gpt-oss-20b"
        self.stream_ok(chunk("Hi"), chunk(finish="stop"))
        self.events(chain=[("groq", llm.default_model("groq"))])
        self.assertEqual(json.loads(self.requests[0].content)["model"], "openai/gpt-oss-20b")
        self.stream_ok(chunk("Hi"), chunk(finish="stop"))
        self.events(chain=[("groq", "qwen/qwen3.8-27b")])
        body = json.loads(self.requests[1].content)
        self.assertNotIn("reasoning_effort", body, "only reasoning models get reasoning_effort")
        self.assertEqual((body["temperature"], body["top_p"], body["max_completion_tokens"]), (1, 1, 2048))

    # ------------------------------------------------------------------ streaming
    def test_streams_content_skipping_empty_and_reasoning_deltas(self):
        self.stream_ok(chunk(reasoning="Let me think"), chunk(""), chunk("Keep "), chunk(None), chunk("your chest tall."),
                       chunk(finish="stop"))
        events = self.events()
        self.assertEqual([e["type"] for e in events], ["start", "delta", "delta", "done"])
        self.assertEqual("".join(e["text"] for e in events if e["type"] == "delta"), "Keep your chest tall.")
        self.assertEqual(events[-1]["provider"], "groq")
        self.assertIsNone(events[-1]["fallback_from"])
        self.assertEqual(self.gemini_calls, [])
        self.stream_ok(chunk("Answer."), chunk(finish="stop"))
        result = llm.answer_grounded_question("q", INSIGHTS, providers=CHAIN)   # non-streaming wrapper
        self.assertEqual(result["answer"], "Answer.")

    def test_http_200_without_a_finished_stream_is_not_success(self):
        self.reply = (200, {"content-type": "text/event-stream"}, sse(chunk("Half an ans"), done=False))
        events = self.events()
        fallback = next(e for e in events if e["type"] == "fallback")
        self.assertEqual(fallback["code"], "incomplete")
        self.assertTrue(fallback["reset"], "partial Groq text must be replaced in the UI")
        self.assertEqual(events[-1]["provider"], "gemini")
        self.stream_ok(chunk(reasoning="thinking only"), chunk(finish="length"))
        events = self.events()
        fallback = next(e for e in events if e["type"] == "fallback")
        self.assertEqual(fallback["code"], "empty")
        self.assertFalse(fallback["reset"])

    def test_error_event_inside_the_stream_falls_back(self):
        body = sse(chunk("Start of answer"), done=False) + \
            b'data: {"error": {"message": "internal error", "type": "server_error", "code": "internal_error"}}\n\n'
        self.reply = (200, {"content-type": "text/event-stream"}, body)
        events = self.events()
        types = [e["type"] for e in events]
        self.assertEqual(types[:3], ["start", "delta", "fallback"])
        fallback = events[2]
        self.assertEqual((fallback["code"], fallback["provider_code"], fallback["reset"]), ("incomplete", "internal_error", True))
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(events[-1]["provider"], "gemini")
        self.assertEqual("".join(e["text"] for e in events[3:] if e["type"] == "delta"), "Gemini backup answer.")

    def test_length_limit_is_flagged(self):
        self.stream_ok(chunk("Long answer"), chunk(finish="length"))
        events = self.events()
        text = "".join(e["text"] for e in events if e["type"] == "delta")
        self.assertIn("cut short", text)
        self.assertEqual(events[-1]["provider"], "groq")

    def test_cancellation_closes_the_groq_stream(self):
        tracked = TrackedStream([sse(chunk("one "), done=False), sse(chunk("two "), done=False),
                                 sse(chunk("three"), chunk(finish="stop"))])
        self.reply = (200, {"content-type": "text/event-stream"}, tracked)
        events = llm.stream_answer("q", INSIGHTS, providers=CHAIN)
        self.assertEqual(next(events)["type"], "start")
        self.assertEqual(next(events)["type"], "delta")
        events.close()                      # what the server does when the browser stops the answer
        self.assertTrue(tracked.closed, "the HTTP stream to Groq is closed, so generation stops")
        self.assertEqual(self.gemini_calls, [])

    # ------------------------------------------------------------------ errors and fallback
    def test_gemini_fallback_after_groq_errors_with_status_and_code(self):
        for status, code, expected in ((429, "rate_limit_exceeded", "rate_limited"),
                                       (503, "service_unavailable", "service_error"),
                                       (500, "internal_server_error", "service_error"),
                                       (498, "capacity_exceeded", "service_error")):
            self.gemini_calls.clear()
            self.error(status, code)
            events = self.events()
            fallback = next(e for e in events if e["type"] == "fallback")
            self.assertEqual((fallback["http_status"], fallback["provider_code"], fallback["code"]), (status, code, expected))
            self.assertEqual((fallback["from"], fallback["to"]), ("groq", "gemini"))
            done = events[-1]
            self.assertEqual((done["type"], done["provider"], done["fallback_from"]), ("done", "gemini", "groq"))
            self.assertIn("so Google Gemini answered", done["notice"])
            self.assertEqual(len(self.gemini_calls), 1, "Gemini is tried once")
            body = json.loads(self.gemini_calls[0].data.decode())
            self.assertNotIn("temperature", body["generationConfig"])
        result = llm.answer_grounded_question("q", INSIGHTS, providers=CHAIN)
        self.assertEqual((result["provider"], result["answer"]), ("gemini", "Gemini backup answer."))

    def test_network_errors_fall_back(self):
        def boom(request):
            raise httpx.ConnectError("connection refused")
        llm.GROQ_HTTP_CLIENT = httpx.Client(transport=httpx.MockTransport(boom))
        events = self.events()
        fallback = next(e for e in events if e["type"] == "fallback")
        self.assertEqual(fallback["code"], "unreachable")
        self.assertEqual(events[-1]["provider"], "gemini")

        def slow(request):
            raise httpx.ReadTimeout("timed out")
        llm.GROQ_HTTP_CLIENT = httpx.Client(transport=httpx.MockTransport(slow))
        self.assertEqual(next(e for e in self.events() if e["type"] == "fallback")["code"], "timeout")

    def test_no_fallback_for_configuration_errors(self):
        for status, code, expected in ((401, "invalid_api_key", "invalid_key"),
                                       (404, "model_not_found", "model_not_found"),
                                       (400, "model_decommissioned", "model_not_found"),
                                       (403, "permission_denied", "forbidden"),
                                       (400, "invalid_request", "bad_request")):
            self.gemini_calls.clear()
            self.error(status, code)
            events = self.events()
            self.assertNotIn("fallback", [e["type"] for e in events])
            error = events[-1]
            self.assertEqual((error["type"], error["code"], error["http_status"], error["provider_code"]),
                             ("error", expected, status, code))
            self.assertIn(f"HTTP {status}", error["error"])
            self.assertNotIn(GROQ_KEY, json.dumps(events))
            self.assertEqual(self.gemini_calls, [])

    def test_both_providers_failing(self):
        self.error(429, "rate_limit_exceeded")
        down = HTTPError(llm.GEMINI_BASE, 503, "x", {}, io.BytesIO(b'{"error":{"status":"UNAVAILABLE"}}'))
        with mock.patch.object(llm, "urlopen", side_effect=down):
            events = self.events()
        error = events[-1]
        self.assertEqual(error["type"], "error")
        self.assertIn("No AI answer is available right now", error["error"])
        self.assertIn("Groq", error["error"])
        self.assertIn("Google Gemini", error["error"])
        for secret in (GROQ_KEY, GEMINI_KEY):
            self.assertNotIn(secret, json.dumps(events))
        with mock.patch.object(llm, "urlopen", side_effect=down):
            with self.assertRaises(llm.CoachUnavailable):
                llm.answer_grounded_question("q", INSIGHTS, providers=CHAIN)

    def test_invalid_input_and_missing_credentials(self):
        with self.assertRaises(ValueError):
            self.events(question="")
        self.assertEqual(self.requests, [])
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": ""}):
            events = self.events(chain=[("groq", "openai/gpt-oss-120b")])
        self.assertEqual((events[-1]["type"], events[-1]["code"]), ("error", "not_configured"))
        with self.assertRaises(llm.CoachUnavailable):
            list(llm.stream_answer("q", INSIGHTS, providers=[]))

    def test_missing_sdk_is_reported(self):
        with mock.patch.dict("sys.modules", {"groq": None}):
            self.assertFalse(llm.groq_sdk_available())
            with self.assertRaises(llm.CoachUnavailable) as ctx:
                llm._groq_client(5)
        self.assertIn("pip install groq", str(ctx.exception))


class GeminiTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"GEMINI_API_KEY": GEMINI_KEY})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_gemini_request_and_errors(self):
        with mock.patch.object(llm, "urlopen", return_value=gemini_reply("ok")) as fake:
            result = llm.answer_grounded_question("q", INSIGHTS, providers=[("gemini", "gemini-3.8-flash")])
        self.assertEqual(result["answer"], "ok", "thought parts are not shown")
        req = fake.call_args[0][0]
        self.assertTrue(req.full_url.endswith("/v1beta/models/gemini-3.8-flash:generateContent"))
        self.assertEqual(req.get_header("X-goog-api-key"), GEMINI_KEY)
        body = json.loads(req.data.decode())
        self.assertNotIn("temperature", body["generationConfig"], "Gemini 3+ rejects temperature")
        cases = [
            (http_error(400, {"error": {"status": "INVALID_ARGUMENT", "message": "API key not valid.",
                                        "details": [{"reason": "API_KEY_INVALID"}]}}), "invalid_key"),
            (http_error(400, {"error": {"status": "FAILED_PRECONDITION"}}), "forbidden"),
            (http_error(402, {"error": {"message": "Prepay credits depleted"}}), "no_credits"),
            (http_error(404, {"error": {"status": "NOT_FOUND"}}), "model_not_found"),
            (http_error(429, {"error": {"status": "RESOURCE_EXHAUSTED"}}), "rate_limited"),
            (http_error(504, {"error": {"status": "DEADLINE_EXCEEDED"}}), "timeout"),
            (http_error(500, {"error": {"status": "INTERNAL"}}), "service_error"),
        ]
        for failure, code in cases:
            with mock.patch.object(llm, "urlopen", side_effect=failure):
                with self.assertRaises(llm.CoachUnavailable) as ctx:
                    llm.answer_grounded_question("q", INSIGHTS, providers=[("gemini", "gemini-3.8-flash")])
            self.assertEqual(ctx.exception.code, code, failure)

    def test_key_checks_list_models_without_tokens(self):
        listing = FakeResponse(json.dumps({"data": [{"id": "openai/gpt-oss-120b"}]}).encode())
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": GROQ_KEY}):
            os.environ.pop("GROQ_MODEL", None)
            with mock.patch.object(llm, "urlopen", return_value=listing) as fake:
                self.assertEqual(llm.check_access("groq")["state"], "key_ok")
            self.assertEqual(fake.call_args[0][0].full_url, "https://api.groq.com/openai/v1/models")
            with mock.patch.object(llm, "urlopen", side_effect=http_error(401, {})):
                self.assertEqual(llm.check_access("groq")["state"], "invalid_key")
        os.environ.pop("GEMINI_MODEL", None)
        gem = FakeResponse(json.dumps({"models": [{"name": "models/gemini-3.6-flash"}]}).encode())
        with mock.patch.object(llm, "urlopen", return_value=gem):
            status = llm.check_access("gemini")
        self.assertEqual(status["state"], "model_not_listed")
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": ""}):
            self.assertEqual(llm.check_access("groq")["state"], "not_configured")


class EnvExampleTest(unittest.TestCase):
    def test_env_example_holds_placeholders_only(self):
        example = Path(__file__).resolve().parents[2] / ".env.example"
        if not example.is_file():
            self.skipTest(".env.example not present")
        import re
        for line in example.read_text(encoding="utf-8").splitlines():
            match = re.match(r"\s*([A-Z_]*API_KEY)\s*=\s*(\S*)", line)
            if match and match.group(2):
                value = match.group(2)
                self.assertTrue(value.startswith("your_") or value in ("<your-key>",),
                                f"{match.group(1)} in .env.example looks like a real key; keep real keys in .env only")
                self.assertFalse(re.match(r"(gsk_|xai-|AIza|AQ\.)", value), match.group(1))


if __name__ == "__main__":
    unittest.main()


class ReadableAnswerTest(unittest.TestCase):
    """Answer style: plain coaching language, no default tables or internal IDs, question-specific focus,
    identical instructions for every provider, and the session facts passed through unchanged."""

    QUESTIONS = {
        "What are my strengths?": "strengths",
        "What should I practise this week?": "practice",
        "What is my biggest weakness?": "weakness",
        "Explain my top issue in plain words": "weakness",
        "Which results are uncertain, and why?": "uncertain",
        "Why is my landing flagged?": "other",
    }

    def test_question_focus_and_detail(self):
        for question, focus in self.QUESTIONS.items():
            style = llm.question_style(question)
            self.assertEqual(style["focus"], focus, question)
            self.assertFalse(style["detailed"], question)
        for question in ("Show me the detailed measurements", "Give me the technical evidence for my elbow",
                         "What were the exact numbers?"):
            self.assertTrue(llm.question_style(question)["detailed"], question)

    def test_prompt_asks_for_plain_scannable_answers_without_tables_or_ids(self):
        prompt = llm.system_prompt_for("What are my strengths?")
        for phrase in ("Answer the question directly in your first sentence", "Do NOT use Markdown tables",
                       "shot IDs", "frame numbers", "internal metric names", "bullet points", "everyday words"):
            self.assertIn(phrase, prompt)
        self.assertNotIn("Technical details", prompt, "no technical section unless asked")

    def test_prompt_keeps_grounding_rules_for_every_question(self):
        for question in list(self.QUESTIONS) + ["Show me the detailed measurements"]:
            prompt = llm.system_prompt_for(question)
            for phrase in ("Never invent, change, round up or exaggerate", "a missing metric is not a result",
                           "Keep observed evidence", "cannot show injury risk or diagnose"):
                self.assertIn(phrase, prompt, question)

    def test_question_specific_guidance(self):
        self.assertIn("strongest observed habits", llm.system_prompt_for("What are my strengths?"))
        self.assertIn("practical plan for the coming week", llm.system_prompt_for("What should I practise this week?"))
        self.assertIn("single main improvement area", llm.system_prompt_for("What is my biggest weakness?"))
        self.assertIn("could not be measured", llm.system_prompt_for("Which results are uncertain?"))
        self.assertIn("do not produce a general report", llm.system_prompt_for("Why is my landing flagged?"))
        detailed = llm.system_prompt_for("Show me the detailed measurements")
        self.assertIn("### Technical details", detailed)
        self.assertIn("copied exactly from the evidence", detailed)

    def test_same_instructions_for_groq_gemini_and_xai(self):
        question = "What are my strengths?"
        captured = {}

        def fake(req, timeout):
            body = json.loads(req.data.decode())
            if "generativelanguage" in req.full_url:
                captured["gemini"] = body["systemInstruction"]["parts"][0]["text"]
                return gemini_reply("ok")
            captured["xai"] = body["input"][0]["content"]
            return FakeResponse(b'{"output_text": "ok"}')
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": GEMINI_KEY, "XAI_API_KEY": "xai-test"}), \
                mock.patch.object(llm, "urlopen", side_effect=fake):
            llm.answer_grounded_question(question, INSIGHTS, providers=[("gemini", "gemini-3.8-flash")])
            llm.answer_grounded_question(question, INSIGHTS, providers=[("xai", "grok-4.7")])
        expected = llm.system_prompt_for(question)
        self.assertEqual(captured["gemini"], expected)
        self.assertEqual(captured["xai"], expected)
        if httpx is not None:
            requests = []

            def handler(request):
                requests.append(request)
                body = "data: " + json.dumps(chunk("ok")) + "\n\ndata: " + json.dumps(chunk(finish="stop")) + "\n\ndata: [DONE]\n\n"
                return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body.encode())
            llm.GROQ_HTTP_CLIENT = httpx.Client(transport=httpx.MockTransport(handler))
            self.addCleanup(setattr, llm, "GROQ_HTTP_CLIENT", None)
            with mock.patch.dict(os.environ, {"GROQ_API_KEY": GROQ_KEY}):
                llm.answer_grounded_question(question, INSIGHTS, providers=[("groq", "openai/gpt-oss-120b")])
            self.assertEqual(json.loads(requests[0].content)["messages"][0]["content"], expected)

    def test_session_facts_reach_the_model_unchanged(self):
        report = json.loads(FIXTURE.read_text())
        findings = llm.summarize_findings_for_llm(report)
        captured = {}

        def fake(req, timeout):
            captured["user"] = json.loads(json.loads(req.data.decode())["contents"][0]["parts"][0]["text"])
            return gemini_reply("ok")
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": GEMINI_KEY}), mock.patch.object(llm, "urlopen", side_effect=fake):
            result = llm.answer_grounded_question("What are my strengths?", INSIGHTS, providers=[("gemini", "gemini-3.8-flash")],
                                                  coach_findings=findings, report_summary=llm.summarize_report_for_llm(report))
        sent = captured["user"]["evidence"]
        self.assertEqual(sent["rules_based_coach_findings"], findings, "findings (titles, confidence, values) are not altered")
        self.assertEqual(sent["metrics"], INSIGHTS["session_metrics"])
        self.assertEqual(result["evidence"], sent)

    def test_source_notice_is_short_and_free_of_error_details(self):
        exc = llm.CoachUnavailable("Groq's rate or usage limit was reached for now. [Groq HTTP 429 rate_limit_exceeded]", "rate_limited", 429)
        notice = llm._notice("Google Gemini", "gemini-3.8-flash", [("groq", exc)])
        self.assertIn("Groq was busy right now, so Google Gemini answered.", notice)
        self.assertNotIn("HTTP 429", notice)
        self.assertNotIn("rate_limit_exceeded", notice)
        self.assertLess(len(notice), 200)
