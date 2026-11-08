"""The masker stays fast on hostile input (sec2-mask-quadratic-dos): the text eyJ repeated was quadratic (44 s for 400 KB, 9.9 s for one 198 KB
POST that froze the whole server), and the masker ran on bodies up to 1 MB before they were cut to their caps."""
import json
import socket
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from agentboard import redact, transcript
from agentboard.server import make_handler
from agentboard.store import DESCRIPTION_MAX, BoardError, Store
from timing import Mixin, limit

LIMIT = 2.0          # seconds on an idle machine: linear work is about 0.05 s per MB; the quadratic case took minutes.
                     # Every timing assertion goes through tests/timing.py: the limit stretches with the machine's load of the moment
                     # and a run over it is tried again (best of three), so a busy laptop cannot fail green code.
JWT = "ey" + "J" + "hbGciOiJIUzI1NiJ9" + "." + "eyJzdWIiOiIxMjM0NTY3ODkwIn0" + "." + "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
BEGIN, END = "-----BEGIN " + "PRIVATE KEY-----", "-----END " + "PRIVATE KEY-----"        # built from parts: the repo scan flags a whole one
UNITS = {
    "eyJ": "eyJ", "eyJ.": "eyJ.", "jwt-ish": "eyJhbGciOiJIUzI1NiJ9.", "AKIA": "AKIA", "AKIA+16": "AKIA" + "0" * 15, "sk-": "sk-", "sk-ant-": "sk-ant-", "sk-+19": "sk-" + "a" * 19,
    "ghp_": "ghp_", "xoxb-": "xoxb-", "AC": "AC", "AC+31": "AC" + "0" * 31, "SK": "SK", "BEGIN": BEGIN, "BEGIN..END": BEGIN + " " + END,
    "auth bearer": "Authorization: Bearer ", "auth": "Authorization:", "password": "password", "password =": "password = ", "key ": "key ", "key=": "key=", "token:": "token: ",
    "sk_live_": "sk_live_", "AIza": "AIza", "AIza+34": "AIza" + "a" * 34, "hooks": "hooks.slack.com/services/TA/BA/", "npm_": "npm_", "SG.": "SG.", "SG.a.": "SG." + "a" * 20 + ".",
    "://": "://", "://a:": "://a:", "://a:b": "://a:b", "Bearer+19": "Bearer " + "a" * 19, "key=+19": "key=" + "a" * 19, "whsec_": "whsec_", "credentials=": "credentials=",
    "aws secret": "aws_secret_access_key  =  ",
    "BEGIN+text": BEGIN + " " + "w" * 9000 + " ", "END": END + " ", "BEGIN BEGIN": BEGIN + " " + BEGIN + " ", "auth token": "Authorization: Token ", "auth + 9 chars": "Authorization: Bearer " + "a" * 9 + " ",
    "secret + spaces": "secret   ", "space": " ", "quote": 'password="', "api_key": "api_key ", "Bearer": "Bearer ", "dash": "-", "x-": "x-", "digit": "1", "dots": ".", "newline": "\n",
}


class EveryShapeIsLinear(Mixin, unittest.TestCase):
    def test_a_megabyte_of_any_shape_prefix_is_masked_in_well_under_the_limit(self):
        for name, unit in UNITS.items():
            text = (unit * (1_000_000 // len(unit) + 1))[:1_000_000]
            self.assertFast(redact.scrub, LIMIT, text, msg=repr(name))

    def test_the_original_attack_text(self):
        out = self.assertFast(redact.scrub, LIMIT, "eyJ" * 330_000)       # 990 KB
        self.assertEqual(out, "eyJ" * 330_000)               # nothing in it is a JWT, so nothing is changed


class ARealJwtIsStillFound(Mixin, unittest.TestCase):
    def test_bare_after_token_after_bearer_in_json_and_in_a_sentence(self):
        for text, want in ((JWT, "[redacted jwt]"), (f"token={JWT}", "token=[redacted jwt]"), (f"Authorization: Bearer {JWT}", None),
                           (f"Bearer {JWT} end", "Bearer [redacted jwt] end"), (json.dumps({"jwt": JWT}), '{"jwt": "[redacted jwt]"}'),
                           (f"the jwt {JWT}.", "the jwt [redacted jwt]."), (f"(\"{JWT}\")", '("[redacted jwt]")')):
            got = redact.scrub(text)
            self.assertNotIn(JWT, got, text[:30])
            if want:
                self.assertEqual(got, want)

    def test_a_jwt_among_a_lot_of_other_text_is_found_fast(self):
        text = "noise eyJ " * 50_000 + JWT + " more " * 50_000
        out = self.assertFast(redact.scrub, LIMIT, text)
        self.assertNotIn(JWT, out)


class TheInputIsBoundedBeforeMasking(Mixin, unittest.TestCase):
    def test_head_cuts_at_a_word_boundary_and_leaves_small_text_alone(self):
        self.assertEqual(redact.head("short", 100), "short")
        self.assertEqual(redact.head("aaa bbb ccc", 9), "aaa bbb")             # the cut fell inside ccc: back to the space
        self.assertEqual(redact.head("aaa bbb ccc", 7), "aaa bbb")             # the cut fell on the end of a word
        self.assertEqual(redact.head("x" * 1000, 100), "x" * 100)              # no space to go back to: a plain cut
        self.assertEqual(redact.head(None, 5), None)

    def test_a_key_cut_in_half_by_the_bound_is_not_left_behind(self):
        key = "AK" + "IA" + "Q3Z7K9M2P5R8T1V4"
        text = "word " * 20 + key + " tail"
        cut = redact.head(text, 100 + 8)                  # lands inside the key
        self.assertNotIn("AKIA", cut)

    def test_scrub_with_a_bound_looks_at_no_more_than_that(self):
        self.assertEqual(redact.scrub("a " * 100, bound=50), redact.head("a " * 100, 50))


class TheStoreStaysResponsive(Mixin, unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")

    def test_a_huge_description_is_stored_capped_and_fast(self):
        t = self.assertFast(self.s.add, LIMIT, "Big", "eyJ" * 330_000, status="todo", task_id="big")
        self.assertLessEqual(len(t["description"]), DESCRIPTION_MAX)

    def test_every_path_that_takes_long_text_is_fast(self):
        s = self.s
        s.set_chat_agents(True)
        s.add("Card", status="todo", task_id="c")
        s.claim("c", "AGENT-1")
        s.add("step", parent_id="c", task_id="step")
        big = "eyJ" * 330_000
        for name, fn in (("edit", lambda: s.edit("c", description=big)), ("update", lambda: s.update("step", 10, big, body_md=big)),
                         ("ask", lambda: s.ask("c", big, body_md=big)), ("chat", lambda: s.chat_send("AGENT-1", "hi\n" + big, detail=big)),
                         ("chat, one huge line to the owner (cut into line plus detail)", lambda: s.chat_send("AGENT-1", big)),
                         ("chat, one huge line to an agent (refused)", lambda: self.assertRaises(BoardError, s.chat_send, "AGENT-1", big, to="AGENT-2"))):
            self.assertFast(fn, LIMIT, msg=name)

    def test_a_secret_near_the_start_of_a_huge_body_is_still_masked(self):
        key = "AK" + "IA" + "Q3Z7K9M2P5R8T1V4"
        s = self.s
        s.add("Card", status="todo", task_id="c")
        s.claim("c", "AGENT-1")
        s.add("step", parent_id="c", task_id="step")
        s.update("step", 10, "x", body_md=f"{key} " + "filler " * 100_000)
        self.assertNotIn(key, (s.dir / "tasks.json").read_text())


class TheTranscriptTabStaysResponsive(Mixin, unittest.TestCase):
    def test_a_huge_text_block_a_huge_command_and_a_huge_typed_line(self):
        big = "eyJ" * 330_000
        lines = [json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": big}, {"type": "tool_use", "name": "Bash", "input": {"command": big}}]}}),
                 json.dumps({"type": "user", "message": {"content": big}})]
        out = self.assertFast(lambda: [e for raw in lines for e in transcript.parse_line(raw)], 1.0)
        self.assertEqual({e["kind"] for e in out}, {"text", "tool", "user"})
        for e in out:
            self.assertLessEqual(len(e["text"]), transcript.TEXT_MAX)


class TheServerKeepsAnswering(Mixin, unittest.TestCase):
    def test_a_big_post_does_not_freeze_the_next_request(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        s = Store(Path(tmp.name) / ".agentboard")
        s.add("Existing", status="todo")
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
            port = sk.getsockname()[1]
        srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(s, port))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        body = json.dumps({"title": "Big", "description": "eyJ" * 66_000}).encode()      # the 198 KB of the repro
        post = urllib.request.Request(f"http://127.0.0.1:{port}/api/tasks", data=body, headers={"Content-Type": "application/json"})
        results = {}

        def do_post():
            t = time.perf_counter()
            urllib.request.urlopen(post, timeout=30).read()
            results["post"] = time.perf_counter() - t
        th = threading.Thread(target=do_post)
        th.start()
        time.sleep(0.05)
        t = time.perf_counter()
        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/tasks", timeout=30).read()
        results["get"] = time.perf_counter() - t
        th.join(30)
        self.assertLess(results["post"], limit(LIMIT))
        self.assertLess(results["get"], limit(LIMIT))


if __name__ == "__main__":
    unittest.main()
