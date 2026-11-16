"""Night sweep (sweep-sec-data, Nov 15): `agentboard chat tail` died with a traceback on a hand-edited board whose chat line held a string where the
action dict belongs. A terminal line is printed for whatever shape a stored message has; nothing here touches a real board."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import agentchat, cli
from agentboard.store import Store

S = "2026-11-15T10:00:00"


class OddMessagesStillPrint(unittest.TestCase):
    def test_an_action_that_is_not_a_dict_is_ignored(self):
        line = agentchat.chat_line({"seq": 3, "at": S, "sender": "AGENT-1", "text": "odd", "kind": "agent", "action": "string"})
        self.assertIn("#3", line)
        self.assertNotIn("proposes", line)

    def test_an_action_missing_its_fields_prints_what_it_has(self):
        line = agentchat.chat_line({"seq": 4, "at": S, "sender": "AGENT-1", "text": "odd", "kind": "agent", "action": {"status": None}})
        self.assertIn("proposes: None  [None]", line)

    def test_files_and_detail_of_the_wrong_type_are_ignored(self):
        line = agentchat.chat_line({"seq": 5, "at": S, "sender": "AGENT-1", "text": "odd", "kind": "agent", "files": "notalist", "detail": 7, "to": 5, "topic": 7})
        self.assertIn("#5", line)
        self.assertNotIn("files", line)
        self.assertIn("-> 5", line)

    def test_a_good_line_prints_as_before(self):
        m = {"seq": 6, "at": S, "sender": "AGENT-1", "text": "hi", "kind": "agent", "to": "ORCH", "files": ["a.py"], "detail": "more\nlines",
             "action": {"text": "do it", "status": "approved", "by": "Troy", "decided_at": S}}
        line = agentchat.chat_line(m)
        self.assertEqual(line.splitlines()[0], f"#6 [{S}] AGENT-1 -> ORCH: hi   (files a.py)")
        self.assertIn("    more", line)
        self.assertIn(f"    proposes: do it  [approved by Troy {S}]", line)


class TheTailCommand(unittest.TestCase):
    def test_chat_tail_prints_every_line_of_an_odd_board(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        env["AGENTBOARD_HOME"] = str(root / "home")
        with mock.patch.dict(os.environ, env, clear=True):
            s = Store(root / "proj" / ".agentboard")
            os.environ["AGENTBOARD_DIR"] = str(s.dir)
            s.add("a card")
            path = s.dir / "tasks.json"
            d = json.loads(path.read_text())
            d["chat"] = [{"seq": 1, "at": S, "sender": "AGENT-1", "text": "fine", "kind": "agent"},
                         {"seq": 3, "at": S, "sender": "AGENT-1", "text": "odd fields", "kind": "agent", "to": 5, "reply_to": "x", "action": "string", "files": "notalist", "topic": 7},
                         {"seq": 4, "at": S, "sender": "AGENT-1", "text": "action odd", "kind": "agent", "action": {"status": None, "text": None, "outside": "str", "expires_at": 1}}]
            d["chat_seq"] = 4
            path.write_text(json.dumps(d))
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                try:
                    code = cli.main(["chat", "tail"])
                except SystemExit as e:
                    code = e.code
        self.assertIn(code, (0, None), out.getvalue())
        self.assertNotIn("Traceback", out.getvalue())
        for want in ("#1", "#3", "#4", "fine", "odd fields", "action odd"):
            self.assertIn(want, out.getvalue())


if __name__ == "__main__":
    unittest.main()
