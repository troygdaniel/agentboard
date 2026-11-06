"""The transcript route (Nov 6): a session's transcript path is registered on claim/start, the server tails it read only, and the
.jsonl parses into the lines the Terminal tab shows."""
import contextlib
import io
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

from agentboard import cli, hooks, transcript
from agentboard.server import make_handler
from agentboard.store import Store

SID = "3ade7a13-15bc-4b66-9192-a8e4e579abe5"


def line(**kw):
    return json.dumps(kw)


LINES = [
    line(type="user", isMeta=True, message={"role": "user", "content": "<system-reminder>named</system-reminder>"}, timestamp="2026-11-06T01:00:00.000Z"),
    line(type="user", message={"role": "user", "content": "fix the header"}, timestamp="2026-11-06T01:00:01.000Z"),
    line(type="assistant", message={"role": "assistant", "content": [
        {"type": "thinking", "thinking": "private"},
        {"type": "text", "text": "Reading the file first."},
        {"type": "tool_use", "name": "Read", "input": {"file_path": "src/ui/CallCard.tsx"}},
        {"type": "tool_use", "name": "Bash", "input": {"command": "npm test -- --grep header", "description": "Run the header tests"}},
        {"type": "tool_use", "name": "Bash", "input": {"command": "ls -la"}},
        {"type": "tool_use", "name": "SendMessage", "input": {"to": "ORCH", "message": "hi"}},
    ]}, timestamp="2026-11-06T01:00:02.000Z"),
    line(type="user", message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": "ok\nmore", "is_error": False}]}, timestamp="2026-11-06T01:00:03.000Z"),
    line(type="user", message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": "y", "content": "Error: no such file\ntrace", "is_error": True}]}, timestamp="2026-11-06T01:00:04.000Z"),
    line(type="assistant", isSidechain=True, message={"role": "assistant", "content": [{"type": "text", "text": "a subagent's line"}]}),
    line(type="api-request", message={}),
    "not json at all",
    line(type="assistant", message={"role": "assistant", "content": [{"type": "text", "text": "Done: the name leads."}]}, timestamp="2026-11-06T01:00:05.000Z"),
]


class ParseTests(unittest.TestCase):
    def test_the_conversation_lines_come_out_and_the_rest_does_not(self):
        got = [e for raw in LINES for e in transcript.parse_line(raw)]
        self.assertEqual([(e["kind"], e["text"]) for e in got], [
            ("user", "fix the header"),
            ("text", "Reading the file first."),
            ("tool", "Read src/ui/CallCard.tsx"),
            ("tool", "Bash Run the header tests"),
            ("tool", "Bash ls -la"),
            ("tool", "SendMessage to ORCH"),
            ("error", "Error: no such file"),
            ("text", "Done: the name leads."),
        ])
        self.assertEqual(got[0]["at"], "2026-11-06 01:00:01")
        self.assertNotIn("private", json.dumps(got))   # thinking never shows
        self.assertNotIn("subagent", json.dumps(got))

    def test_a_long_argument_is_cut_to_one_line(self):
        t = transcript.tool_line("Bash", {"command": "x" * 500})
        self.assertLessEqual(len(t), transcript.LINE_MAX)
        self.assertTrue(t.endswith("…"))
        self.assertEqual(transcript.tool_line("Mystery", None), "Mystery")


class TailTests(unittest.TestCase):
    def test_only_the_end_is_read_and_a_cut_first_line_is_dropped(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.jsonl"
            rows = [line(type="assistant", message={"role": "assistant", "content": [{"type": "text", "text": f"line {i} " + "x" * 100}]}) for i in range(100)]
            p.write_text("\n".join(rows) + "\n")
            text, size = transcript.tail_text(p, max_bytes=2000)
            self.assertEqual(size, p.stat().st_size)
            got = [e["text"][:8] for raw in text.splitlines() for e in transcript.parse_line(raw)]
            self.assertTrue(got)
            self.assertEqual(got[-1], "line 99 ")
            self.assertTrue(all(g.startswith("line ") for g in got))   # no half line


class FindAndRegisterTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.proj = Path(self.home.name) / ".claude" / "projects" / "-Users-x-dev-app"
        self.proj.mkdir(parents=True)
        self.file = self.proj / f"{SID}.jsonl"
        self.file.write_text("\n".join(LINES) + "\n")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        self.s.add("Card", status="todo")
        self.s.add("step", parent_id="card")
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_") and k != "CLAUDE_CODE_SESSION_ID"}
        env.update({"AGENTBOARD_DIR": str(self.s.dir), "HOME": self.home.name, "CLAUDE_CODE_SESSION_ID": SID})
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def test_the_transcript_is_found_from_the_session_id_and_an_explicit_path_wins(self):
        self.assertEqual(transcript.find_transcript(SID), str(self.file))
        self.assertIsNone(transcript.find_transcript("nope-nope-nope"))
        self.assertIsNone(transcript.find_transcript("../etc"))
        self.assertEqual(transcript.find_transcript(SID, explicit="/tmp/other.jsonl"), "/tmp/other.jsonl")

    def test_claim_and_start_record_it_and_the_newest_session_wins(self):
        with contextlib.redirect_stdout(io.StringIO()):
            cli.main(["claim", "card", "--name", "alice"])
        rec = hooks.read_sessions(self.s.dir)[SID]
        self.assertEqual(rec["name"], "alice")
        self.assertEqual(rec["transcript"], str(self.file))
        self.assertEqual(hooks.transcript_for(self.s.dir, "ALICE"), str(self.file))
        other = self.proj / "other.jsonl"
        other.write_text("")
        with contextlib.redirect_stdout(io.StringIO()):
            cli.main(["start", "More", "--name", "alice", "--transcript", str(other)])
        self.assertEqual(hooks.transcript_for(self.s.dir, "alice"), str(other))
        self.assertIsNone(hooks.transcript_for(self.s.dir, "bob"))

    def test_a_record_without_an_id_keeps_the_path_it_had(self):
        hooks.remember_session(self.s.dir, "alice", transcript=str(self.file))
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": SID, "HOME": "/nonexistent"}):
            hooks.remember_session(self.s.dir, "alice")   # nothing found now: the old path stays
        self.assertEqual(hooks.read_sessions(self.s.dir)[SID]["transcript"], str(self.file))


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        proj = Path(self.home.name) / ".claude" / "projects" / "-Users-x"
        proj.mkdir(parents=True)
        self.file = proj / f"{SID}.jsonl"
        self.file.write_text("\n".join(LINES) + "\n")
        self.outside = Path(self.home.name) / "elsewhere.jsonl"
        self.outside.write_text("\n".join(LINES) + "\n")
        p = mock.patch.dict(os.environ, {"HOME": self.home.name})
        p.start()
        self.addCleanup(p.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        self.s.add("Card", status="todo")   # the first write makes the board folder sessions.json lives in
        hooks.remember_session(self.s.dir, "alice", session_id=SID, transcript=str(self.file))
        hooks.remember_session(self.s.dir, "mallory", session_id="m" * 36, transcript=str(self.outside))
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), make_handler(self.s, self.port))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.shutdown)

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
            return json.loads(r.read())

    def test_the_route_tails_the_registered_file(self):
        d = self.get("/api/transcript?agent=alice")
        self.assertEqual(d["agent"], "alice")
        self.assertEqual(d["file"], f"{SID}.jsonl")
        self.assertEqual([e["kind"] for e in d["lines"]], ["user", "text", "tool", "tool", "tool", "tool", "error", "text"])
        self.assertEqual(d["size"], self.file.stat().st_size)
        self.assertNotIn("missing", d)

    def test_it_fails_soft(self):
        self.assertEqual(self.get("/api/transcript?agent=bob"), {"agent": "bob", "lines": [], "missing": True, "why": "no transcript registered"})
        self.assertEqual(self.get("/api/transcript")["why"], "no agent named")
        self.assertEqual(self.get("/api/transcript?agent=mallory")["why"], "outside ~/.claude/projects")
        self.file.unlink()
        self.assertEqual(self.get("/api/transcript?agent=alice")["why"], "no such file")


if __name__ == "__main__":
    unittest.main()
