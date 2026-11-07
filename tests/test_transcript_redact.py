"""The Terminal tab and /api/transcript never show a secret (sec-data-redact-transcript), and every ordinary line reads exactly as before."""
import json
import os
import socket
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from agentboard import hooks, transcript
from agentboard.server import make_handler
from agentboard.store import Store

# Fakes are assembled from pieces so this file never holds a whole one.
HEX40 = "3f9a1c7e5b2d4f6a8c0e1b3d5f7a9c2e4b6d8f0a"
AWS = "AK" + "IA" + "Q3Z7K9M2P5R8T1V4"
SK = "sk" + "-ant-" + "q3Z7k9M2p5R8t1V4w6Y0a2C4e6G8i0K2"
GH = "gh" + "p_" + "q3Z7k9M2p5R8t1V4w6Y0a2C4e6G8i0K2m4O6"
SID = "3ade7a13-15bc-4b66-9192-a8e4e579abe5"


def line(**kw):
    return json.dumps(kw)


def tool(name, **inp):
    return line(type="assistant", message={"role": "assistant", "content": [{"type": "tool_use", "name": name, "input": inp}]}, timestamp="2026-11-07T01:00:00.000Z")


def entries(raw, board_dir=None):
    return transcript.parse_line(raw, board_dir)


class SecretsAreMaskedInEveryKindOfLine(unittest.TestCase):
    def test_a_command_with_no_description_shows_the_command_with_the_secret_masked(self):
        e = entries(tool("Bash", command=f"curl -X POST https://api.example.invalid/v1 -H 'Authorization: Token {HEX40}' --data-binary @a.wav"))
        self.assertEqual(e[0]["text"], "Bash curl -X POST https://api.example.invalid/v1 -H 'Authorization: Token [redacted secret]' --data-binary @a.wav"[:160])
        self.assertNotIn(HEX40, e[0]["text"])

    def test_a_key_in_a_url_and_in_a_file_argument_is_masked(self):
        self.assertEqual(entries(tool("WebFetch", url=f"https://api.example.invalid/x?api_key={'q3Z7k9M2' + 'p5R8t1V4w6Y0'}"))[0]["text"],
                         "WebFetch https://api.example.invalid/x?api_key=[redacted secret]")
        self.assertNotIn(AWS, entries(tool("Bash", command=f"export AWS_KEY={AWS}"))[0]["text"])

    def test_a_secret_the_length_cap_would_cut_is_masked_first(self):
        e = entries(tool("Bash", command="x" * 150 + f" {AWS}"))
        self.assertNotIn("AKIA", e[0]["text"])      # cut after masking, not before

    def test_typed_lines_and_assistant_text(self):
        user = line(type="user", message={"role": "user", "content": f"here is my key {AWS}, use it"}, timestamp="2026-11-07T01:00:01.000Z")
        asst = line(type="assistant", message={"role": "assistant", "content": [{"type": "text", "text": f"Using the key {SK} now."}]}, timestamp="2026-11-07T01:00:02.000Z")
        self.assertEqual(entries(user)[0]["text"], "here is my key [redacted aws-key], use it")
        self.assertEqual(entries(asst)[0]["text"], "Using the key [redacted api-key] now.")

    def test_a_tool_error_line(self):
        raw = line(type="user", message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": "y", "is_error": True,
                                                                       "content": f"401 for Authorization: Bearer {'q3Z7k9M2' + 'p5R8t1V4w6Y0a2C4'}\ntrace"}]})
        self.assertEqual(entries(raw)[0]["text"], "401 for Authorization: Bearer [redacted secret]")

    def test_a_question_and_its_option_chips(self):
        raw = tool("AskUserQuestion", questions=[{"question": f"Is {GH} the right token?", "options": [{"label": f"Use {GH}"}, {"label": "No"}]}])
        e = entries(raw)[0]
        self.assertEqual(e["kind"], "ask")
        self.assertEqual(e["text"], "Is [redacted github-token] the right token?")
        self.assertEqual(e["options"], ["Use [redacted github-token]", "No"])


class OrdinaryLinesReadAsBefore(unittest.TestCase):
    def test_nothing_normal_changes(self):
        cases = [
            (tool("Read", file_path="src/ui/CallCard.tsx"), "Read src/ui/CallCard.tsx"),
            (tool("Bash", command="npm test", description="Run the header tests"), "Bash Run the header tests"),
            (tool("Bash", command="git log --oneline -3"), "Bash git log --oneline -3"),
            (tool("Bash", command=f"git show {HEX40}"), f"Bash git show {HEX40}"),
            (tool("Grep", pattern="password|secret"), "Grep password|secret"),
            (tool("SendMessage", to="ORCH", message="hi"), "SendMessage to ORCH"),
            (line(type="user", message={"role": "user", "content": f"fix 416-555-0123 in /Users/you/x and commit {HEX40}"}), f"fix 416-555-0123 in /Users/you/x and commit {HEX40}"),
            (line(type="assistant", message={"role": "assistant", "content": [{"type": "text", "text": "Reading the password reset flow, card ap-123."}]}), "Reading the password reset flow, card ap-123."),
        ]
        for raw, want in cases:
            self.assertEqual(entries(raw)[0]["text"], want)


class TheBoardSetting(unittest.TestCase):
    def test_switched_off_the_tab_shows_lines_as_written(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "config.toml").write_text("[redact]\nenabled = false\n")
            self.assertEqual(entries(tool("Bash", command=f"export K={AWS}"), d)[0]["text"], f"Bash export K={AWS}")
            self.assertEqual(entries(tool("Bash", command=f"export K={AWS}"))[0]["text"], "Bash export K=[redacted aws-key]")

    def test_your_own_patterns_apply_to_the_tab_too(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "config.toml").write_text('[redact]\nextra = ["ACME-[0-9]{6}"]\n')
            self.assertEqual(entries(tool("Bash", command="grep ACME-123456 log"), d)[0]["text"], "Bash grep [redacted match] log")


class ThroughTheRoute(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        proj = Path(self.home.name) / ".claude" / "projects" / "-Users-x"
        proj.mkdir(parents=True)
        self.file = proj / f"{SID}.jsonl"
        self.file.write_text("\n".join([
            tool("Bash", command=f"curl -H 'Authorization: Token {HEX40}' https://api.example.invalid"),
            tool("Bash", command="ls", description="List the folder"),
            line(type="user", message={"role": "user", "content": f"my key is {AWS}"}),
            line(type="assistant", message={"role": "assistant", "content": [{"type": "text", "text": f"Got {SK}."}]}),
        ]) + "\n")
        p = mock.patch.dict(os.environ, {"HOME": self.home.name})
        p.start()
        self.addCleanup(p.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        self.s.add("Card", status="todo")
        hooks.remember_session(self.s.dir, "alice", session_id=SID, transcript=str(self.file))
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), make_handler(self.s, self.port))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
            return r.read().decode()

    def test_the_route_serves_masked_lines_and_the_file_itself_is_untouched(self):
        body = self.get("/api/transcript?agent=alice")
        for secret in (HEX40, AWS, SK):
            self.assertNotIn(secret, body)
        texts = [e["text"] for e in json.loads(body)["lines"]]
        self.assertIn("Bash List the folder", texts)
        self.assertIn("my key is [redacted aws-key]", texts)
        self.assertTrue(any("Authorization: Token [redacted secret]" in t for t in texts))
        self.assertIn(AWS, self.file.read_text())     # read only: the session's own file is never rewritten

    def test_switched_off_in_the_boards_config_the_route_shows_lines_as_written(self):
        (self.s.dir / "config.toml").write_text("[redact]\nenabled = false\n")
        self.assertIn(AWS, self.get("/api/transcript?agent=alice"))


if __name__ == "__main__":
    unittest.main()
