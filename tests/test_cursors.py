"""The chat cursor file (cursors.py): one key per name whatever the case, locked forward-only writes, and the Stop hook reading it the
way everything else does (rev1107-stophook-case). Before: `agentboard me --name AGENT-4` plus `chat inbox --name agent-4` left the
cursor under one spelling and the hook looked it up by the other, so every owner line to that name in the log blocked the stop at
every turn end. A throwaway board; nothing reaches a real one."""
import contextlib
import io
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli, cursors, hooks, listeners
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
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                code = cli.main(list(argv))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue()


class CursorFileTests(Base):
    def test_one_key_per_name_whatever_the_case_and_never_backwards(self):
        self.assertIsNone(cursors.get(self.s.dir, "AGENT-4"))
        self.assertEqual(cursors.advance(self.s.dir, "AGENT-4", 5), 5)
        self.assertEqual(cursors.advance(self.s.dir, "agent-4", 3), 5)        # never back
        self.assertEqual(cursors.advance(self.s.dir, " Agent-4 ", 7), 7)
        self.assertEqual(json.loads(cursors.path(self.s.dir).read_text()), {"agent-4": 7})
        self.assertEqual((cursors.get(self.s.dir, "AGENT-4"), cursors.get(self.s.dir, "agent-4")), (7, 7))
        self.assertFalse((self.s.dir / "chat-cursors.json.bak").exists())

    def test_an_older_mixed_case_file_reads_as_the_highest_seq_per_name(self):
        cursors.path(self.s.dir).write_text(json.dumps({"AGENT-4": 9, "agent-4": 4, "Agent-4": 6, "ORCH": 2, "bad": "x", "b": True}))
        self.assertEqual(cursors.read(self.s.dir), {"agent-4": 9, "orch": 2})
        cursors.advance(self.s.dir, "orch", 3)
        self.assertEqual(json.loads(cursors.path(self.s.dir).read_text()), {"agent-4": 9, "orch": 3})   # rewritten clean
        cursors.path(self.s.dir).write_text("not json")
        self.assertEqual(cursors.read(self.s.dir), {})
        self.assertEqual(cursors.advance(self.s.dir, "x", 1), 1)

    def test_twenty_readers_advancing_at_once_lose_nothing(self):
        names = [f"R-{i}" for i in range(20)]
        go = threading.Barrier(len(names))

        def one(n, seq):
            go.wait()
            cursors.advance(self.s.dir, n, seq)

        ts = [threading.Thread(target=one, args=(n, i + 1)) for i, n in enumerate(names)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(cursors.read(self.s.dir), {f"r-{i}": i + 1 for i in range(20)})


class EveryPathUsesIt(Base):
    def test_inbox_answer_wait_and_receipts_agree_on_the_key(self):
        self.s.chat_send(self.s.owner, "hi", kind="user", to="AGENT-4")
        self.run_cli("chat", "inbox", "--name", "agent-4")
        last = self.s.chat_list()[-1]["seq"]
        self.assertEqual(cursors.read(self.s.dir), {"agent-4": last})
        self.assertEqual(listeners.receipts(self.s.dir)["read"], {"agent-4": last})
        code, out = self.run_cli("chat", "inbox", "--name", "AGENT-4")   # the other spelling: nothing new, cursor not moved back
        self.assertIn("nothing new", out)
        self.s.chat_send(self.s.owner, "again", kind="user", to="Agent-4")
        self.s.claim("seed", "AGENT-4")
        os.environ["AGENTBOARD_NAME"] = "Agent-4"   # answer --wait reads its name from the environment: a third spelling
        code, out = self.run_cli("answer", "seed", "--wait", "--timeout", "2", "--interval", "0.1")
        self.assertIn("again", out)
        self.assertEqual(cursors.read(self.s.dir), {"agent-4": self.s.chat_list()[-1]["seq"]})

    def test_the_stop_hook_does_not_block_on_a_line_read_under_another_spelling(self):
        self.s.chat_send(self.s.owner, "please look", kind="user", to="AGENT-4")
        self.run_cli("chat", "inbox", "--name", "agent-4")       # read as agent-4
        listeners.register(self.s.dir, "AGENT-4", "inbox")
        payload = {"session_id": "s1", "stop_hook_active": False}
        with mock.patch.dict(os.environ, {"AGENTBOARD_NAME": "AGENT-4"}):
            self.assertIsNone(hooks.stop_decision(self.s, payload))   # read: let the session stop
            self.s.chat_send(self.s.owner, "one more", kind="user", to="agent-4")
            d = hooks.stop_decision(self.s, payload)
        self.assertEqual(d["decision"], "block")
        self.assertIn("one more", d["reason"])
        listeners.unregister(self.s.dir, "AGENT-4")
