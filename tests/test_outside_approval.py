"""The approval card for an action outside the board (card agent-config-slice-2, docs/agent-configurations-design.md safety rule 2): `chat send --propose ... --outside --target
--say --money --shares`. It is the chat's own proposal (one decision, Approve and Decline, `chat approvals` for the agent) with the four things an outside action must state, and
an approval that is for that one action and lapses 30 minutes after the ask. The board cannot stop an agent from acting in its own terminal; this is the record and the rule.
A throwaway board."""
import contextlib
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli, store as storemod
from agentboard.store import BoardError, Store

FIELDS = {"target": "416-555-0100", "say": "A table for two on Friday at seven, first name only", "money": "none", "shares": "first name only"}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name).resolve()
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        env["AGENTBOARD_HOME"] = str(root / "home")
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        self.s = Store(root / "proj" / ".agentboard")
        self.d = self.s.dir
        self.d.mkdir(parents=True, exist_ok=True)
        (self.d / "config.toml").write_text('[board]\nowner = "Pat"\n')
        os.environ["AGENTBOARD_DIR"] = str(self.d)
        self.s.add("Book a table", task_id="t1")

    def propose(self, **fields):
        return self.s.chat_send("Caller-1", "Need your word to call", propose="Call the restaurant to book a table for two", outside={**FIELDS, **fields}, card="t1")

    def expire(self, seq, minutes_ago=1):
        data = json.loads((self.d / "tasks.json").read_text())
        for m in data["chat"]:
            if m["seq"] == seq:
                m["action"]["expires_at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 60 * minutes_ago))
        (self.d / "tasks.json").write_text(json.dumps(data))

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                code = cli.main(list(argv))
            except SystemExit as e:
                code = e.code
                if isinstance(code, str):
                    out.write(code)
        return code, out.getvalue()


class TheProposal(Base):
    def test_it_states_the_four_things_and_lapses_in_30_minutes(self):
        m = self.propose()
        a = m["action"]
        self.assertEqual((a["status"], a["outside"]), ("proposed", FIELDS))
        due = time.mktime(time.strptime(a["expires_at"], "%Y-%m-%dT%H:%M:%S"))
        self.assertAlmostEqual(due - time.time(), 60 * storemod.OUTSIDE_TTL_MIN, delta=5)
        self.assertEqual(storemod.OUTSIDE_TTL_MIN, 30)

    def test_each_field_must_be_stated(self):
        for f in FIELDS:
            with self.assertRaises(BoardError, msg=f) as e:
                self.propose(**{f: " "})
            self.assertIn(f, str(e.exception))
            self.assertIn("none", str(e.exception))
        self.assertEqual(self.s._read()["chat"], [])   # nothing was posted

    def test_it_needs_an_action_to_be_about(self):
        with self.assertRaises(BoardError) as e:
            self.s.chat_send("Caller-1", "hello", outside=FIELDS)
        self.assertIn("--propose", str(e.exception))

    def test_a_field_is_cut_and_a_plain_proposal_is_as_it_was(self):
        m = self.propose(say="x" * 500)
        self.assertEqual(len(m["action"]["outside"]["say"]), storemod.OUTSIDE_FIELD_MAX)
        plain = self.s.chat_send("Caller-1", "ok to rename?", propose="Rename x to y")
        self.assertNotIn("outside", plain["action"])
        self.assertNotIn("expires_at", plain["action"])


class TheDecision(Base):
    def test_one_yes_is_for_one_action(self):
        first, second = self.propose(), self.propose(say="A table for four")
        self.s.chat_decide(first["seq"], "approved")
        by_seq = {m["seq"]: m["action"]["status"] for m in self.s.chat_approvals()}
        self.assertEqual(by_seq, {first["seq"]: "approved", second["seq"]: "proposed"})   # the second still waits for its own word
        with self.assertRaises(BoardError) as e:
            self.s.chat_decide(first["seq"], "approved")
        self.assertIn("already approved", str(e.exception))
        with self.assertRaises(BoardError):
            self.s.chat_decide(first["seq"], "declined")   # nor can it be flipped afterwards

    def test_a_decline_is_recorded(self):
        m = self.propose()
        self.s.chat_decide(m["seq"], "declined")
        self.assertEqual(self.s.chat_approvals()[0]["action"]["status"], "declined")

    def test_after_30_minutes_neither_answer_is_taken(self):
        m = self.propose()
        self.expire(m["seq"])
        for decision in ("approved", "declined"):
            with self.assertRaises(BoardError) as e:
                self.s.chat_decide(m["seq"], decision)
            self.assertIn("lapsed at", str(e.exception))
            self.assertIn("propose it again", str(e.exception))
        self.assertEqual(self.s.chat_approvals()[0]["action"]["status"], "proposed")   # no decision was recorded

    def test_the_window_is_not_over_a_minute_before_the_end(self):
        m = self.propose()
        self.expire(m["seq"], minutes_ago=-1)   # a minute still to go
        self.assertEqual(self.s.chat_decide(m["seq"], "approved")["action"]["status"], "approved")

    def test_a_plain_proposal_has_no_clock(self):
        m = self.s.chat_send("Caller-1", "ok?", propose="Rename x to y")
        self.assertEqual(self.s.chat_decide(m["seq"], "approved")["action"]["status"], "approved")

    def test_lapsed_is_only_for_an_undecided_action_with_a_deadline(self):
        past = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 5))
        self.assertTrue(storemod.lapsed({"status": "proposed", "expires_at": past}))
        self.assertFalse(storemod.lapsed({"status": "approved", "expires_at": past}))
        self.assertFalse(storemod.lapsed({"status": "proposed"}))
        self.assertFalse(storemod.lapsed({"status": "proposed", "expires_at": "garbage"}))
        self.assertFalse(storemod.lapsed(None))


class TheCommandLine(Base):
    def send(self, *extra):
        return self.run_cli("chat", "send", "Need your word to call", "--name", "Caller-1", "--propose", "Call to book a table", "--card", "t1", *extra)

    def test_send_and_read_it_back(self):
        code, out = self.send("--outside", "--target", "416-555-0100", "--say", "a table for two", "--money", "none", "--shares", "first name only")
        self.assertFalse(code, out)
        code, out = self.run_cli("chat", "approvals", "--name", "Caller-1")
        self.assertIn("proposed", out)
        self.assertIn("to: 416-555-0100 | say: a table for two | money: none | shares: first name only | lapses ", out)
        self.run_cli("chat", "approve", "1")
        code, out = self.run_cli("chat", "approvals")
        self.assertIn("approved", out)
        self.assertNotIn("lapses", out)

    def test_a_lapsed_one_reads_as_lapsed(self):
        self.send("--outside", "--target", "x", "--say", "y", "--money", "none", "--shares", "none")
        self.expire(1)
        code, out = self.run_cli("chat", "approvals")
        self.assertIn("lapsed", out)
        code, out = self.run_cli("chat", "approve", "1")
        self.assertIn("lapsed at", out)

    def test_missing_fields_and_stray_flags_are_refused(self):
        code, out = self.send("--outside", "--target", "x")
        self.assertIn("must state say, money, shares", out)
        code, out = self.send("--target", "x")
        self.assertIn("go with --outside", out)
        code, out = self.run_cli("chat", "send", "hi", "--name", "Caller-1", "--outside", "--target", "x", "--say", "y", "--money", "none", "--shares", "none")
        self.assertIn("--propose", out)
        self.assertEqual(self.s._read()["chat"], [])


if __name__ == "__main__":
    unittest.main()
