"""ORCH signs off on a card in review, with its evidence (card orch-sign-off, Nov 14).

ORCH records what it knows (merged or not, the tests that ran, the batch gate, who verified) and the board draws it next to the card's review
state, so the owner reads it before signing. When the owner signs off a card ORCH has not signed as merged, the board says so in one line and
ORCH is told. `agentboard done` by ORCH goes through the same record. Hashes, counts and results only: no message text can be stored.
The store, the command and the endpoint are driven here; how the row looks is checked in a browser (docs/screens)."""
import contextlib
import io
import json
import os
import re
import socket
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from agentboard import cli, signoff
from agentboard.server import make_handler
from agentboard.store import BoardError, Store

PAGE = (Path(cli.__file__).parent / "static" / "index.html").read_text()
HASH = "165d972"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        self.s.add("Search box", status="todo", task_id="spa")
        self.s.add("Part a", parent_id="spa", task_id="a")
        self.s.add("Part b", parent_id="spa", task_id="b")
        self.run_cli("claim", "spa", "--name", "atlas")
        self.run_cli("review", "spa", "Search remembers the last query", "--next", "nothing", name="atlas")

    def run_cli(self, *argv, name=None):
        out, err = io.StringIO(), io.StringIO()
        env = {"AGENTBOARD_DIR": str(self.s.dir)}
        if name:
            env["AGENTBOARD_NAME"] = name
        with mock.patch.dict(os.environ, env, clear=False), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            if not name:
                os.environ.pop("AGENTBOARD_NAME", None)
            try:
                cli.main(list(argv))
                code = 0
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
                if isinstance(e.code, str):
                    err.write(e.code)
        return code, out.getvalue(), err.getvalue()

    def card(self):
        return Store.get(self.s.load(), "spa")


class TheRecord(unittest.TestCase):
    def test_a_sign_off_is_hashes_counts_and_results_only(self):
        rec = signoff.clean(merged="165D972", tests=["full smoke=pass", "tests/pullout.mjs = fail"], gate="pass", verified_by="DreamBot")
        self.assertEqual(rec["merged"], HASH)                                     # a hash is kept lower-case
        self.assertEqual(rec["tests"], [{"name": "full smoke", "result": "pass"}, {"name": "tests/pullout.mjs", "result": "fail"}])
        self.assertEqual(signoff.line(rec), "merged 165d972, full smoke pass, tests/pullout.mjs fail, gate pass, verified by DreamBot")
        nm = signoff.clean(not_merged=True, ahead=2, gate="pending")
        self.assertEqual((nm["merged"], nm["ahead"]), (None, 2))
        self.assertEqual(signoff.line(nm), "not merged (2 ahead), gate pending")

    def test_a_sentence_cannot_get_in(self):
        for kw, why in (
            ({"merged": "see my note about the merge"}, "hash"),
            ({"merged": HASH, "tests": ["the whole suite went fine apart from one flaky thing=pass"]}, "name"),
            ({"merged": HASH, "tests": ["smoke=looks fine to me"]}, "result"),
            ({"merged": HASH, "tests": ["smoke"]}, "NAME=RESULT"),
            ({"merged": HASH, "gate": "looks good"}, "gate"),
            ({"merged": HASH, "verified_by": "me, after lunch, on the sofa; it was fine and I am confident"}, "session name"),
            ({"merged": HASH, "tests": ["a=pass"] * 5}, "at most"),
            ({"not_merged": True, "ahead": 100}, "count"),
            ({"merged": HASH, "ahead": 1}, "--not-merged"),
            ({"merged": HASH, "not_merged": True}, "not both"),
            ({}, "--merged"),
        ):
            with self.subTest(kw=kw):
                with self.assertRaises(ValueError) as cm:
                    signoff.clean(**kw)
                self.assertIn(why, str(cm.exception))


class OnTheCard(Base):
    def test_orch_records_it_and_the_card_keeps_it_next_to_the_review(self):
        code, out, err = self.run_cli("signoff", "spa", "--merged", HASH, "--test", "full smoke=pass", "--gate", "pass", "--verified-by", "DreamBot", name="ORCH")
        self.assertEqual(code, 0, err)
        so = self.card()["signoff"]
        self.assertEqual((so["merged"], so["gate"], so["verified_by"], so["by"]), (HASH, "pass", "DreamBot", "ORCH"))
        self.assertTrue(so["at"])
        self.assertTrue(self.card()["review"])                                    # still waiting on the owner
        self.assertIn("ORCH sign-off: merged 165d972, full smoke pass, gate pass, verified by DreamBot", json.dumps(self.card()["log"]))
        self.assertIn("signoff", [t for t in json.loads(json.dumps(self.s.load())) if t["id"] == "spa"][0])

    def test_only_orch_records_one_and_never_the_agent_that_did_the_work(self):
        code, _, err = self.run_cli("signoff", "spa", "--merged", HASH, name="atlas")
        self.assertNotEqual(code, 0)
        self.assertIn("only ORCH", err)
        self.assertNotIn("signoff", self.card())

    def test_it_needs_a_card_in_review_and_a_top_level_card(self):
        code, _, err = self.run_cli("signoff", "a", "--merged", HASH, name="ORCH")
        self.assertNotEqual(code, 0)                                              # a subtask has no review
        self.s.add("Idle", status="todo", task_id="idle")
        code, _, err = self.run_cli("signoff", "idle", "--merged", HASH, name="ORCH")
        self.assertNotEqual(code, 0)
        self.assertIn("not in review", err)

    def test_a_new_review_the_card_going_back_to_work_or_a_send_back_drops_it(self):
        sign = lambda: self.run_cli("signoff", "spa", "--merged", HASH, name="ORCH")
        sign()
        self.run_cli("review", "spa", "Fixed one more thing", "--next", "nothing", name="atlas")
        self.assertNotIn("signoff", self.card())                                  # it spoke of the review before this one
        sign()
        self.run_cli("update", "spa", "0", "back to work", name="atlas")
        self.assertNotIn("signoff", self.card())
        self.run_cli("review", "spa", "Done again", "--next", "nothing", name="atlas")
        sign()
        self.s.send_back("spa", "check the empty case")
        self.assertNotIn("signoff", self.card())
        self.run_cli("review", "spa", "Done a third time", "--next", "nothing", name="atlas")
        sign()
        self.s.move("spa", "todo")
        self.assertNotIn("signoff", self.card())


class ORCHClosesThroughIt(Base):
    def test_orch_cannot_close_a_card_in_review_without_the_evidence(self):
        code, _, err = self.run_cli("done", "spa", name="ORCH")
        self.assertNotEqual(code, 0)
        self.assertIn("--merged", err)
        self.assertEqual(self.card()["status"], "doing")

    def test_done_with_the_flags_records_the_sign_off_and_closes_the_card(self):
        code, out, err = self.run_cli("done", "spa", "--merged", HASH, "--test", "full smoke=pass", "--gate", "pass", name="ORCH")
        self.assertEqual(code, 0, err)
        t = self.card()
        self.assertEqual(t["status"], "done")
        self.assertEqual(t["signoff"]["merged"], HASH)                            # done keeps the record it closed with

    def test_a_sign_off_that_says_not_merged_does_not_close_a_card(self):
        self.run_cli("signoff", "spa", "--not-merged", "--ahead", "2", name="ORCH")
        code, _, err = self.run_cli("done", "spa", name="ORCH")
        self.assertNotEqual(code, 0)
        self.assertIn("not merged", err)
        self.assertEqual(self.card()["status"], "doing")
        self.run_cli("signoff", "spa", "--merged", HASH, name="ORCH")             # once it is merged, ORCH records that and closes it
        code, _, err = self.run_cli("done", "spa", name="ORCH")
        self.assertEqual(code, 0, err)

    def test_the_owner_at_a_terminal_and_a_card_not_in_review_close_as_before(self):
        code, _, err = self.run_cli("done", "spa")                                # no session name: the owner
        self.assertEqual(code, 0, err)
        self.s.add("Plain", status="todo", task_id="plain")
        code, _, err = self.run_cli("done", "plain", name="ORCH")
        self.assertEqual(code, 0, err)

    def test_an_agent_closing_a_card_ORCH_never_signed_gets_a_warning_not_a_wall(self):
        code, _, err = self.run_cli("done", "spa", name="atlas")
        self.assertEqual(code, 0)                                                 # agents still close after ORCH says merged: the rule is unchanged
        self.assertIn("ORCH has not recorded a merge", err)


class HeadsUp(Base):
    def setUp(self):
        super().setUp()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), make_handler(self.s, self.port))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.shutdown)

    def post(self, path, payload):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json", "Host": f"localhost:{self.port}", "Origin": f"http://localhost:{self.port}"})
        return json.loads(urllib.request.urlopen(req, timeout=5).read())

    def to_orch(self):
        return [m["text"] for m in self.s.chat_list() if m.get("to") == "ORCH"]

    def test_signing_off_a_card_ORCH_has_not_signed_says_so_and_tells_ORCH(self):
        r = self.post("/api/move", {"id": "spa", "status": "done"})
        self.assertEqual(r["heads_up"], "Signed off without ORCH: not signed yet. ORCH has been told.")
        self.assertEqual(self.card()["status"], "done")                           # the owner's word is never blocked
        lines = self.to_orch()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("spa", lines[0])
        self.assertIn("without ORCH's sign-off (not signed yet)", lines[0])       # a fact line: the card and the state, no message text

    def test_a_card_ORCH_signed_as_not_merged_says_not_merged_yet(self):
        self.run_cli("signoff", "spa", "--not-merged", "--ahead", "2", name="ORCH")
        r = self.post("/api/move", {"id": "spa", "status": "done"})
        self.assertEqual(r["heads_up"], "Signed off without ORCH: not merged yet. ORCH has been told.")

    def test_a_card_ORCH_signed_as_merged_has_nothing_to_warn_about(self):
        self.run_cli("signoff", "spa", "--merged", HASH, name="ORCH")
        r = self.post("/api/move", {"id": "spa", "status": "done"})
        self.assertIsNone(r["heads_up"])

    def test_only_a_card_that_was_in_review_warns(self):
        self.s.add("Quiet", status="todo", task_id="quiet")
        self.assertIsNone(self.post("/api/move", {"id": "quiet", "status": "done"})["heads_up"])
        self.assertIsNone(self.post("/api/move", {"id": "spa", "status": "backlog"})["heads_up"])

    def test_the_bulk_close_says_how_many(self):
        self.s.add("Second", status="todo", task_id="two")
        self.run_cli("claim", "two", "--name", "grace")
        self.run_cli("review", "two", "Also done", "--next", "nothing", name="grace")
        r = self.post("/api/bulk-move", {"ids": ["spa", "two"], "status": "done"})
        self.assertEqual(r["heads_up"], "Signed off 2 cards without ORCH's sign-off. ORCH has been told.")


class OnThePage(unittest.TestCase):
    """The row is drawn by the page; its look is the mock-up Troy approved (three states, one place). These read the page's code."""

    def fn(self, name):
        return re.search(rf"function {name}\(.*?\n\}}", PAGE, re.S).group(0)

    def has(self, part, text, what=""):
        self.assertTrue(part in text, f"missing {part!r} {what}")           # a message that names the part, not the whole function

    def test_the_row_has_three_states_and_everything_in_it_is_escaped(self):
        f = self.fn("signoffHtml")
        for part in ("so none", "so ${ok ? 'ok' : 'warn'}", "ORCH signed off", "ORCH: not merged", "ORCH has not signed this yet", "batch gate"):
            self.has(part, f)
        self.assertNotIn("innerHTML", f)
        for field in ("so.merged", "so.ahead", "x.name", "x.result", "so.gate", "so.verified_by"):
            self.assertRegex(f, r"esc\([^)]*" + re.escape(field), f"{field} is not escaped")   # every stored field goes through esc()
        self.assertIsNone(re.search(r"\$\{(so|x)\.\w+\}", f), "a stored field is interpolated without esc()")   # none is dropped into the markup raw

    def test_it_sits_under_the_agents_sentence_on_the_card_and_at_the_top_of_the_panel(self):
        self.has("(reviewing ? signoffHtml(t) : '');", PAGE, "in card()'s saidRow")                # saidRow: the sentence, then the row
        self.has("${top}${askFlag}${saidRow}${foldRow}", self.fn("card"), "(the row rides inside saidRow)")
        self.has("return signoffHtml(t) + `<div class=\"p-you", self.fn("youPanel"), "in youPanel()")
        self.has("!t.review", self.fn("signoffHtml"), "(only a card in review shows it)")

    def test_the_heads_up_is_the_move_toast(self):
        mv = re.search(r"async function move\(.*?\n\}\n", PAGE, re.S).group(0)
        self.has("r.heads_up) toast(r.heads_up, { prev: r.prev, before: r.prev_before, kids: r.prev_kids });", mv, "in move() (the toast keeps its Undo)")
        self.has("toast(`Moved ", mv, "(the plain line is still there)")


if __name__ == "__main__":
    unittest.main()
