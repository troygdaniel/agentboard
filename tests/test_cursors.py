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


class ReadingIsLossless(Base):
    """chat-f2: more unread than one read shows (repro R8). Before, `chat inbox` showed the newest 50 and moved the cursor past all
    of them: with 60 unread the 10 oldest were never shown."""

    def test_sixty_unread_come_in_two_reads_oldest_first_and_none_are_lost(self):
        for i in range(60):
            self.s.chat_send(self.s.owner, f"line {i}", kind="user", to="R8")
        code, out = self.run_cli("chat", "inbox", "--name", "R8")
        shown = [l for l in out.splitlines() if l.startswith("#")]
        self.assertEqual(len(shown), 50)
        self.assertIn("line 0", shown[0])
        self.assertIn("line 49", shown[-1])
        self.assertIn("(10 more unread, from #", out)
        fifty = self.s.chat_inbox("R8", limit=None)[49]["seq"]
        self.assertEqual((cursors.get(self.s.dir, "R8"), cursors.pending(self.s.dir, "R8")["seq"]), (None, fifty))   # delivered up to the last line shown
        code, out = self.run_cli("chat", "inbox", "--name", "R8")   # the session is back: that confirms the first page, and the rest comes
        shown = [l for l in out.splitlines() if l.startswith("#")]
        self.assertEqual((len(shown), "line 50" in shown[0], "line 59" in shown[-1], "more unread" in out), (10, True, True, False))
        self.assertEqual(cursors.get(self.s.dir, "R8"), fifty)
        code, out = self.run_cli("chat", "inbox", "--name", "R8")
        self.assertIn("nothing new", out)
        self.assertEqual(cursors.get(self.s.dir, "R8"), self.s.chat_list()[-1]["seq"])

    def test_limit_zero_shows_all_and_keep_moves_nothing(self):
        for i in range(55):
            self.s.chat_send(self.s.owner, f"line {i}", kind="user", to="R8")
        code, out = self.run_cli("chat", "inbox", "--name", "R8", "--keep", "--limit", "5")
        self.assertEqual(len([l for l in out.splitlines() if l.startswith("#")]), 5)
        self.assertIn("(50 more unread", out)
        self.assertIsNone(cursors.get(self.s.dir, "R8"))
        code, out = self.run_cli("chat", "inbox", "--name", "R8", "--limit", "0")
        self.assertEqual(len([l for l in out.splitlines() if l.startswith("#")]), 55)
        self.assertNotIn("more unread", out)
        self.assertEqual(cursors.pending(self.s.dir, "R8")["seq"], self.s.chat_list()[-1]["seq"])

    def test_a_wait_wakes_on_the_oldest_unread_and_the_store_pages_oldest_first(self):
        for i in range(3):
            self.s.chat_send(self.s.owner, f"line {i}", kind="user", to="R8")
        page = self.s.chat_inbox("R8", limit=2)
        self.assertEqual([m["text"] for m in page], ["line 0", "line 1"])
        self.assertEqual([m["text"] for m in self.s.chat_inbox("R8", after=page[-1]["seq"], limit=2)], ["line 2"])

    def test_twelve_processes_reading_the_same_line_at_once_all_keep_their_cursor(self):
        import subprocess
        import sys
        import time
        self.s.chat_send(self.s.owner, "to everyone", kind="user", to="all")
        n, at = 12, time.time() + 2.5
        code = ("import sys, time, os; from agentboard import cli; at = float(sys.argv[1]); time.sleep(max(0.0, at - time.time())); "
                "cli.main(['chat', 'inbox', '--name', os.environ['AGENTBOARD_NAME']])")
        src = str(Path(cursors.__file__).resolve().parents[1])
        procs = []
        for i in range(n):
            env = {"PATH": os.environ["PATH"], "PYTHONPATH": src, "PYTHONDONTWRITEBYTECODE": "1", "HOME": self.tmp.name,
                   "AGENTBOARD_DIR": str(self.s.dir), "AGENTBOARD_NAME": f"P-{i}"}
            procs.append(subprocess.Popen([sys.executable, "-c", code, str(at)], env=env, cwd=self.tmp.name, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True))
        outs = [p.communicate(timeout=60)[0] for p in procs]
        self.assertTrue(all("to everyone" in o for o in outs), outs)
        last = self.s.chat_list()[-1]["seq"]
        self.assertEqual({k: v["seq"] for k, v in cursors.read_delivered(self.s.dir).items()}, {f"p-{i}": last for i in range(n)})   # none of the twelve writes was lost


class TwoStepReceipts(Base):
    """chat-f3 (loss path 5, repro R2): printing is DELIVERED; SEEN only when the session next acts as that name; a delivered line not
    confirmed in RESHOW_S comes again with the next inbox read."""

    def test_a_dead_reader_gets_the_line_again_a_live_one_does_not(self):
        from datetime import datetime, timedelta
        q = self.s.chat_send(self.s.owner, "did you get this?", kind="user", to="R2")
        code, out = self.run_cli("chat", "inbox", "--name", "R2")                # the wait printed it (to a session that may be gone)
        self.assertIn("did you get this", out)
        self.assertEqual((cursors.get(self.s.dir, "R2"), cursors.pending(self.s.dir, "R2")["seq"]), (None, q["seq"]))
        self.assertEqual(listeners.receipts(self.s.dir)["delivered"]["r2"]["seq"], q["seq"])
        # the reader was gone: nothing confirms; 6 minutes later the next read shows it again
        cursors.deliver(self.s.dir, "R2", q["seq"], now=datetime.now() - timedelta(minutes=6))   # backdate the delivery
        code, out = self.run_cli("chat", "inbox", "--name", "R2")
        self.assertIn("never confirmed: shown again", out)
        self.assertIn("did you get this", out)
        # a live reader: the next read within the window confirms, and the line does not come again
        q2 = self.s.chat_send(self.s.owner, "and this?", kind="user", to="R2")
        code, out = self.run_cli("chat", "inbox", "--name", "R2")                # confirms q, prints q2
        self.assertTrue("and this" in out and "did you get this" not in out)
        code, out = self.run_cli("chat", "inbox", "--name", "R2")                # confirms q2
        self.assertIn("nothing new", out)
        self.assertEqual(cursors.get(self.s.dir, "R2"), q2["seq"])
        self.assertIsNone(cursors.pending(self.s.dir, "R2"))

    def test_a_busy_reader_is_seen_when_it_next_acts_and_keep_after_all_leave_it_alone(self):
        q = self.s.chat_send(self.s.owner, "busy?", kind="user", to="R2")
        self.run_cli("chat", "inbox", "--name", "R2")
        self.s.claim("seed", "R2")
        with mock.patch.dict(os.environ, {"AGENTBOARD_NAME": "r2"}):
            self.run_cli("update", "seed", "40", "half way")                     # any board command as that name (env), any case: seen
        self.assertEqual((cursors.get(self.s.dir, "R2"), cursors.pending(self.s.dir, "R2")), (q["seq"], None))
        q2 = self.s.chat_send(self.s.owner, "more", kind="user", to="R2")
        for flags in (("--keep",), ("--all",), ("--after", "0")):
            code, out = self.run_cli("chat", "inbox", "--name", "R2", *flags)     # a look without moving anything delivers nothing new either
            self.assertIn("more", out)
        self.assertEqual(cursors.pending(self.s.dir, "R2")["seq"], q2["seq"])    # --all and --after still printed it: delivered
        self.assertEqual(cursors.get(self.s.dir, "R2"), q["seq"])

    def test_the_page_knows_the_four_states(self):
        page = (Path(cursors.__file__).parent / "static" / "index.html").read_text()
        for needle in ("return { state: 'seen' }", "return { state: 'delivered', late: since >= RESHOW_S }", "state: 'sent', late: age >= RECEIPT_WARN_S",
                       "Not seen in 5 min: it comes again with the next inbox read.", ".cmsg-rcpt.seen .st", "chatReceipts.delivered[dk]"):
            self.assertIn(needle, page)
        self.assertNotIn("state: 'read'", page)


class EveryPathUsesIt(Base):
    def test_inbox_answer_wait_and_receipts_agree_on_the_key(self):
        self.s.chat_send(self.s.owner, "hi", kind="user", to="AGENT-4")
        self.run_cli("chat", "inbox", "--name", "agent-4")
        last = self.s.chat_list()[-1]["seq"]
        self.assertEqual(cursors.read_delivered(self.s.dir)["agent-4"]["seq"], last)
        code, out = self.run_cli("chat", "inbox", "--name", "AGENT-4")   # the other spelling: confirms it, nothing new, cursor not moved back
        self.assertIn("nothing new", out)
        self.assertEqual(cursors.read(self.s.dir), {"agent-4": last})
        self.assertEqual(listeners.receipts(self.s.dir)["read"], {"agent-4": last})
        self.s.chat_send(self.s.owner, "again", kind="user", to="Agent-4")
        self.s.claim("seed", "AGENT-4")
        os.environ["AGENTBOARD_NAME"] = "Agent-4"   # answer --wait reads its name from the environment: a third spelling
        code, out = self.run_cli("answer", "seed", "--wait", "--timeout", "2", "--interval", "0.1")
        self.assertIn("again", out)
        self.assertEqual(cursors.pending(self.s.dir, "agent-4")["seq"], self.s.chat_list()[-1]["seq"])
        self.run_cli("me", "--name", "AGENT-4")   # any command as that name confirms it
        self.assertEqual(cursors.read(self.s.dir), {"agent-4": self.s.chat_list()[-1]["seq"]})

    def test_the_stop_hook_does_not_block_on_a_line_read_under_another_spelling(self):
        self.s.chat_send(self.s.owner, "please look", kind="user", to="AGENT-4")
        self.run_cli("chat", "inbox", "--name", "agent-4")       # printed as agent-4
        self.run_cli("me", "--name", "Agent-4")                  # and acted on as Agent-4: seen
        listeners.register(self.s.dir, "AGENT-4", "inbox")
        payload = {"session_id": "s1", "stop_hook_active": False}
        with mock.patch.dict(os.environ, {"AGENTBOARD_NAME": "AGENT-4"}):
            self.assertIsNone(hooks.stop_decision(self.s, payload))   # read: let the session stop
            self.s.chat_send(self.s.owner, "one more", kind="user", to="agent-4")
            d = hooks.stop_decision(self.s, payload)
        self.assertEqual(d["decision"], "block")
        self.assertIn("one more", d["reason"])
        listeners.unregister(self.s.dir, "AGENT-4")
