"""Two sessions under one name (chat-f4, loss path 6, repro R4): the listener file keeps one entry per process, the board shows
"N sessions", a second registration under a live name is warned once (terminal and the name's thread), and when one ends the other
still counts as listening. A throwaway board; nothing reaches a real one."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli, hooks, listeners
from agentboard.store import Store


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
        os.environ["AGENTBOARD_DIR"] = str(self.s.dir)
        self.s.add("seed")

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(list(argv))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()


class OneEntryPerProcess(Base):
    def test_two_sessions_are_two_entries_and_one_ending_leaves_the_other_listening(self):
        listeners.register(self.s.dir, "AGENT-1", "inbox", pid=1)
        listeners.register(self.s.dir, "agent-1", "answer card", pid=os.getpid())   # the other spelling is the same name
        self.assertEqual(listeners.sessions(self.s.dir, "Agent-1"), 2)
        L = listeners.listening(self.s.dir)
        self.assertEqual(list(L), ["AGENT-1"])                                       # one key, the first spelling
        self.assertEqual(L["AGENT-1"]["sessions"], 2)
        self.assertEqual(L["AGENT-1"]["what"], "inbox")
        listeners.unregister(self.s.dir, "AGENT-1", pid=os.getpid())                  # R4b: the shorter-lived one ends
        self.assertTrue(listeners.is_listening(self.s.dir, "agent-1"))               # the other still counts
        self.assertEqual(listeners.sessions(self.s.dir, "AGENT-1"), 1)
        listeners.unregister(self.s.dir, "AGENT-1", pid=os.getpid())                  # a second unregister by the same pid is a no-op
        self.assertEqual(listeners.sessions(self.s.dir, "AGENT-1"), 1)
        listeners.unregister(self.s.dir, "AGENT-1", pid=1)
        self.assertEqual(listeners.listening(self.s.dir), {})
        self.assertEqual(json.loads((self.s.dir / listeners.FILE).read_text()), {})

    def test_the_same_pid_registering_again_is_one_entry_and_an_old_file_shape_still_reads(self):
        listeners.register(self.s.dir, "AGENT-2", "inbox")
        listeners.register(self.s.dir, "AGENT-2", "inbox")
        self.assertEqual(listeners.sessions(self.s.dir, "AGENT-2"), 1)
        (self.s.dir / listeners.FILE).write_text(json.dumps({"OLD": {"pid": 1, "since": "2026-01-01T00:00:00", "what": "inbox"}}))   # one dict per name, as before
        self.assertEqual(listeners.listening(self.s.dir)["OLD"]["sessions"], 1)
        listeners.register(self.s.dir, "old", "inbox", pid=os.getpid())
        self.assertEqual(listeners.sessions(self.s.dir, "OLD"), 2)

    def test_a_second_wait_under_a_live_name_is_warned_in_its_terminal_and_nothing_is_posted(self):
        listeners.register(self.s.dir, "AGENT-3", "inbox", pid=1)   # a live session already waits as AGENT-3
        self.s.chat_send(self.s.owner, "ping", kind="user", to="AGENT-3")
        n = len(self.s.chat_list())
        code, out, err = self.run_cli("chat", "inbox", "--name", "AGENT-3", "--wait", "1", "--interval", "0.1")
        self.assertIn("2 sessions are listening as AGENT-3", err)
        self.assertIn("ping", out)
        self.assertEqual(len(self.s.chat_list()), n)                 # no chat line: one to the name would wake both waits; the board's side is the chip
        # a board notice to the name (the nudge's kind) never blocks the Stop hook as an unanswered owner line
        self.s.chat_send(self.s.owner, "a board notice", kind="user", to="AGENT-3", via="board")
        self.run_cli("chat", "inbox", "--name", "AGENT-3")
        with mock.patch.dict(os.environ, {"AGENTBOARD_NAME": "AGENT-3"}):
            d = hooks.stop_decision(self.s, {"session_id": "s", "stop_hook_active": False})
        self.assertIsNone(d)
        listeners.unregister(self.s.dir, "AGENT-3", pid=1)
        code, out, err = self.run_cli("chat", "inbox", "--name", "AGENT-3", "--wait", "1", "--interval", "0.1")   # alone: no warning
        self.assertNotIn("sessions are listening", err)

    def test_the_receipts_feed_and_the_page_carry_the_count(self):
        listeners.register(self.s.dir, "AGENT-1", "inbox", pid=1)
        listeners.register(self.s.dir, "AGENT-1", "inbox")
        self.assertEqual(listeners.receipts(self.s.dir)["listening"]["AGENT-1"]["sessions"], 2)
        page = (Path(listeners.__file__).parent / "static" / "index.html").read_text()
        for needle in ("function sessionsChip(name)", "chatReceipts.listening[k].sessions", "${n} sessions</span>", "${esc(name)}${sessionsChip(name)}</span>",
                       "const twins = sessionsChip(m.to);", ".chip.sessions {"):
            self.assertIn(needle, page)
        listeners.unregister(self.s.dir, "AGENT-1", pid=1)
        listeners.unregister(self.s.dir, "AGENT-1")
