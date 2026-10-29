"""Browser test of the "Ask about this session" card with streamed answers.

Groq (official SDK) is mocked at the HTTP layer with httpx.MockTransport; Gemini (urllib) is mocked
with unittest.mock. No API keys or network are used. Skipped without Playwright, the groq SDK or ffmpeg.
"""

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

import basketball.app.web_app as web_app
import basketball.coaching.llm_coach as llm

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None
try:
    import groq  # noqa: F401
    import httpx
except ImportError:  # pragma: no cover
    httpx = None


def sse_event(text=None, finish=None):
    delta = {"content": text} if text is not None else {}
    return f"data: {json.dumps({'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]})}\n\n".encode()


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@unittest.skipIf(sync_playwright is None or httpx is None, "playwright and the groq SDK are needed")
@unittest.skipIf(shutil.which("ffmpeg") is None, "ffmpeg is needed for the synthetic clip")
class ChatUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="shotlab_chatui_"))
        server = web_app.LocalAppServer(("127.0.0.1", 0), web_app.AppHandler)
        server.db_path = str(cls.tmp / "chat.db")
        for name in ("upload_dir", "pose_cache_dir", "keyframe_dir"):
            folder = cls.tmp / name
            folder.mkdir()
            setattr(server, name, folder)
        server.job_store = web_app.JobStore(server.db_path + ".web_jobs.sqlite3", upload_root=server.upload_dir)
        server.executor = ThreadPoolExecutor(max_workers=1)
        server.worker_slots = threading.BoundedSemaphore(2)
        server.session_locks = {}
        server.llm_chat_enabled = True
        server.llm_provider, server.llm_model = "groq", "openai/gpt-oss-120b"
        server.llm_chain = [("groq", "openai/gpt-oss-120b"), ("gemini", "gemini-3.8-flash")]
        cls.server = server
        threading.Thread(target=server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{server.server_address[1]}"
        cls.env = mock.patch.dict(os.environ, {"GROQ_API_KEY": "gsk_test_not_real", "GEMINI_API_KEY": "AIza_test_not_real"})
        cls.env.start()
        # A short synthetic clip so the Review screen (where the chat card lives) can open.
        clip = cls.tmp / "clip.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15:duration=2",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(clip)], check=True, stdin=subprocess.DEVNULL)
        query = "player_id=chat_ui&camera_view=side_90&shot_type=catch_and_shoot&shot_style=jump_shot&handedness=right&skill_level=beginner&goals=&pain_reported=0"
        req = urllib.request.Request(f"{cls.base}/api/sessions?{query}", data=clip.read_bytes(), method="POST",
                                     headers={"X-Shotlab": "1", "Content-Type": "application/octet-stream",
                                              "X-Upload-Filename": "clip.mp4"})
        with urllib.request.urlopen(req, timeout=60) as response:
            cls.job_id = json.loads(response.read())["job_id"]
        deadline = time.time() + 180
        while time.time() < deadline:
            with urllib.request.urlopen(f"{cls.base}/api/jobs/{cls.job_id}", timeout=30) as response:
                if json.loads(response.read())["status"] in ("complete", "failed"):
                    break
            time.sleep(1)
        try:
            cls.pw = sync_playwright().start()
            cls.browser = cls.pw.chromium.launch(args=["--no-proxy-server"])
        except Exception as exc:  # pragma: no cover
            cls.server.shutdown()
            cls.env.stop()
            raise unittest.SkipTest(f"Chromium for Playwright is not available: {exc}")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.server.executor.shutdown(wait=True)
        cls.env.stop()
        llm.GROQ_HTTP_CLIENT = None
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def open_review(self):
        ctx = self.browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True)
        page = ctx.new_page()
        self.errors = []
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.goto(self.base + "/#new")
        page.evaluate(f"localStorage.setItem('shotLabLastJobId', '{self.job_id}')")
        page.goto(self.base + "/#review")
        page.reload()
        page.wait_for_selector("#chat-title", timeout=60000)
        self.addCleanup(ctx.close)
        card = page.locator("section.card:has(#chat-title)")
        self.wait(page, lambda: not card.locator("input").is_disabled())
        return page, card

    @staticmethod
    def wait(page, predicate, timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return
            page.wait_for_timeout(100)
        raise AssertionError("timed out")

    def slow_groq(self, words, delay=0.15, finish=True, closed=None):
        class Slow(httpx.SyncByteStream):
            def __iter__(self):
                for word in words:
                    if closed is not None and closed.is_set():
                        return
                    yield sse_event(word)
                    time.sleep(delay)
                if finish:
                    yield sse_event(finish="stop") + b"data: [DONE]\n\n"

            def close(self):
                if closed is not None:
                    closed.set()
        llm.GROQ_HTTP_CLIENT = httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Slow())))

    def test_streams_into_the_card_then_shows_the_notice(self):
        self.slow_groq(["Keep ", "", "your ", "chest ", "tall ", "and ", "land ", "softly."])
        page, card = self.open_review()
        card.locator("input").fill("How do I fix my torso?")
        card.locator("button[type=submit]").click()
        answer = card.locator(".chat-answer")
        self.wait(page, lambda: "Keep your" in answer.inner_text())
        partial = answer.inner_text()
        self.assertNotIn("Answered by", partial, "text appears while it is still being generated")
        self.wait(page, lambda: "Answered by Groq" in answer.inner_text())
        self.assertIn("Keep your chest tall and land softly.", answer.inner_text())
        self.assertEqual(self.errors, [])

    def test_gemini_answer_replaces_a_failed_groq_stream_in_the_same_card(self):
        self.slow_groq(["Partial ", "Groq ", "text"], finish=False)   # stream ends without finishing
        page, card = self.open_review()
        backup = {"candidates": [{"content": {"parts": [{"text": "Gemini says: hold your follow-through."}]}}]}
        with mock.patch.object(llm, "urlopen", return_value=FakeResponse(json.dumps(backup).encode())):
            card.locator("input").fill("What should I practise?")
            card.locator("button[type=submit]").click()
            answer = card.locator(".chat-answer")
            self.wait(page, lambda: "Answered by Google Gemini" in answer.inner_text())
        text = answer.inner_text()
        self.assertIn("Gemini says: hold your follow-through.", text)
        self.assertNotIn("Partial Groq text", text, "the backup answer replaces the incomplete one")
        self.assertIn("so Google Gemini answered", text)

    def test_stop_button_cancels_the_answer(self):
        closed = threading.Event()
        self.slow_groq([f"w{i} " for i in range(80)], delay=0.1, closed=closed)
        page, card = self.open_review()
        card.locator("input").fill("Give me a long answer")
        card.locator("button[type=submit]").click()
        answer = card.locator(".chat-answer")
        self.wait(page, lambda: "w2" in answer.inner_text())
        card.locator("button", has_text="Stop").click()
        self.wait(page, lambda: "Stopped." in answer.inner_text())
        self.assertTrue(closed.wait(10), "the server closed the Groq stream after Stop")
        self.assertFalse(card.locator("button[type=submit]").is_disabled())


TECHNICAL_ANSWER = """Your clearest strength is your **arm extension** at release.

### What you do well
| Strength | Measurement | Confidence |
|---|---|---|
| Arm extension | 168° average (shot_435e6936, frame 24) | medium |
| Release height | 1.1× torso_length_ratio | medium |

- Your elbow_angle_release_deg stayed steady (shot shot_ce84f070, frame 31).
- Keep doing the *hold your finish* drill.

Evidence: shot_435e6936 frame 24"""


class ChatFormattingTest(ChatUiTest):
    """The answer renderer: readable by default, technical detail only when asked; same for every provider."""

    # Reuse ChatUiTest's server and helpers without running its tests a second time.
    test_streams_into_the_card_then_shows_the_notice = None
    test_gemini_answer_replaces_a_failed_groq_stream_in_the_same_card = None
    test_stop_button_cancels_the_answer = None

    def render(self, page, text, detailed=False):
        return page.evaluate("""([text, detailed]) => {
            const box = document.createElement('div');
            box.className = 'chat-answer';
            document.body.append(box);
            window.ShotLabChat.render(box, text, {detailed});
            return {html: box.innerHTML, text: box.innerText, tables: box.querySelectorAll('table').length,
                    items: [...box.querySelectorAll('li')].map(li => li.innerText),
                    headings: [...box.querySelectorAll('h4')].map(h => h.innerText),
                    bold: [...box.querySelectorAll('strong')].map(b => b.innerText),
                    scripts: box.querySelectorAll('img,script').length};
        }""", [text, detailed])

    def test_default_rendering_is_readable(self):
        page, _card = self.open_review()
        out = self.render(page, TECHNICAL_ANSWER)
        self.assertEqual(out["tables"], 0, "no tables in ordinary answers")
        self.assertEqual(out["headings"], ["What you do well"])
        self.assertIn("arm extension", out["bold"])
        for internal in ("shot_", "frame 24", "frame 31", "torso_length_ratio", "elbow_angle_release_deg", "|", "**", "###"):
            self.assertNotIn(internal, out["text"], internal)
        self.assertTrue(any(item.startswith("Arm extension: 168° average, medium") for item in out["items"]), out["items"])
        self.assertIn("168°", out["text"], "measured values are kept, not altered")
        self.assertIn("1.1×", out["text"])
        self.assertIn("elbow angle release stayed steady", out["text"])

    def test_detailed_rendering_keeps_the_table(self):
        page, _card = self.open_review()
        out = self.render(page, TECHNICAL_ANSWER, detailed=True)
        self.assertEqual(out["tables"], 1)
        self.assertIn("frame 24", out["text"], "frame references are kept when detail was asked for")
        self.assertIn("168° average", out["text"])
        self.assertNotIn("shot_435e6936", out["text"], "internal IDs are never shown")
        self.assertNotIn("torso_length_ratio", out["text"])

    def test_model_output_cannot_inject_markup(self):
        page, _card = self.open_review()
        out = self.render(page, '**Tip** <img src=x onerror="window.pwned=1"> <script>window.pwned=2</script>')
        self.assertEqual(out["scripts"], 0)
        self.assertIn("<img", out["text"])
        self.assertIsNone(page.evaluate("window.pwned"))

    def test_chat_card_hides_raw_metadata_by_default_and_shows_it_on_request(self):
        words = [line + "\n" for line in TECHNICAL_ANSWER.split("\n")]
        self.slow_groq(words, delay=0.01)
        page, card = self.open_review()
        card.locator("input").fill("What are my strengths?")
        card.locator("button[type=submit]").click()
        answer = card.locator(".chat-answer")
        self.wait(page, lambda: "Answered by Groq" in answer.inner_text())
        text = answer.inner_text()
        for raw in ("Metrics supplied", "Evidence:", "No shot-level evidence", "shot_435e6936", "|---|"):
            self.assertNotIn(raw, text, raw)
        self.assertEqual(answer.locator("table").count(), 0)
        self.assertEqual(answer.locator(".chat-evidence").count(), 0)
        self.assertIn("Your clearest strength is your arm extension at release.", text)

        self.slow_groq(words, delay=0.01)
        card.locator("input").fill("Show me the detailed measurements")
        card.locator("button[type=submit]").click()
        self.wait(page, lambda: "Answered by Groq" in answer.inner_text() and answer.locator("table").count() == 1)
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
