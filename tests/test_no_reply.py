"""Messages to agents got no reply (Nov 7): a line the owner typed on the board reached the agent's inbox and nothing woke the
session. Now the waits that do wake a session register themselves (listeners.py) so the panel can say delivered / read / answered
and whether anything will wake the agent; a Stop hook keeps a session from going quiet on an unread line or with no wait running;
one click asks ORCH, the only thing on the machine that reaches a session, to message it; and every prompt says to keep the wait
running between cards."""
import contextlib
import http.client
import io
import json
import os
import re
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from agentboard import cli, hooks, listeners, nav, prompt, server
from agentboard.store import BoardError, Store

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()
STOP = {"session_id": "sid-four-1234", "transcript_path": "/x.jsonl", "cwd": "/proj", "hook_event_name": "Stop", "stop_hook_active": False}


def body(fn):
    m = re.search(r"function " + fn + r"\(.*?\n}\n", HTML, re.S)
    assert m, fn
    return m.group(0)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        env = {k: v for k, v in os.environ.items() if not k.startswith(("AGENTBOARD_", "CLAUDE_CODE_SESSION_ID"))}
        env["AGENTBOARD_HOME"] = str(self.root / "home")
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        self.proj = self.root / "proj"
        self.s = Store(self.proj / ".agentboard")
        self.s.dir.mkdir(parents=True)
        os.environ["AGENTBOARD_DIR"] = str(self.s.dir)

    def run_cli(self, *argv, stdin=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch("sys.stdin", io.StringIO(stdin or "")):
            try:
                code = cli.main(list(argv))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def later(self, fn, delay=0.4):
        t = threading.Timer(delay, fn)
        self.addCleanup(t.join)
        t.start()


class TheListenerList(Base):
    def test_a_wait_registers_itself_and_leaves_no_trace_after(self):
        seen = {}
        self.later(lambda: seen.update(listeners.listening(self.s.dir)), 0.3)
        self.later(lambda: self.s.chat_send(self.s.owner, "hello four", kind="user", to="AGENT-4"), 0.6)
        code, out, _err = self.run_cli("chat", "inbox", "--name", "AGENT-4", "--wait", "5", "--interval", "0.1")
        self.assertIn("hello four", out)
        self.assertEqual(seen["AGENT-4"]["what"], "inbox")
        self.assertEqual(listeners.listening(self.s.dir), {})
        self.assertFalse(listeners.is_listening(self.s.dir, "agent-4"))

    def test_answer_wait_counts_as_listening_for_the_cards_agent(self):
        self.s.start("Card", "AGENT-4")
        self.s.add("step", parent_id="card")
        seen = {}
        self.later(lambda: seen.update(listeners.listening(self.s.dir)), 0.5)
        self.later(lambda: self.s.reply("card", "go"), 0.8)
        _code, out, _err = self.run_cli("answer", "card", "--wait", "--timeout", "5", "--interval", "0.1")
        self.assertEqual(out.strip(), "go")
        self.assertEqual(seen["AGENT-4"]["what"], "answer card")
        self.assertEqual(listeners.listening(self.s.dir), {})

    def test_a_dead_pid_is_not_listening_and_a_plain_inbox_read_never_registers(self):
        listeners.register(self.s.dir, "GHOST", "inbox", pid=2 ** 22 + 12345)   # no such process
        listeners.register(self.s.dir, "ME", "inbox")
        self.assertEqual(sorted(listeners.listening(self.s.dir)), ["ME"])
        self.assertTrue(listeners.is_listening(self.s.dir, "me"))
        listeners.unregister(self.s.dir, "ME", pid=1)   # another pid's entry is not cleared by mistake
        self.assertTrue(listeners.is_listening(self.s.dir, "ME"))
        listeners.unregister(self.s.dir, "ME")
        self.assertEqual(listeners.listening(self.s.dir), {})
        self.run_cli("chat", "inbox", "--name", "AGENT-4")
        self.assertEqual(listeners.listening(self.s.dir), {})
        self.assertFalse(listeners.alive("x"))

    def test_receipts_are_the_cursors_and_the_listeners(self):
        self.s.chat_send(self.s.owner, "hi", kind="user", to="AGENT-4")
        self.run_cli("chat", "inbox", "--name", "AGENT-4")
        (self.s.dir / "chat-cursors.json").write_text(json.dumps({"AGENT-4": 1, "agent-4": 3, "bad": "x", "worse": True}))
        r = listeners.receipts(self.s.dir)
        self.assertEqual((r["read"], r["listening"]), ({"agent-4": 3}, {}))   # keys lower-cased, the higher seq wins
        self.assertEqual(r["delivered"]["agent-4"]["seq"], 1)                # what the inbox read above printed, and when


class TheNudge(Base):
    def setUp(self):
        super().setUp()
        self.m = self.s.chat_send(self.s.owner, "what do u need from me?", kind="user", to="AGENT-4")

    def test_one_click_asks_orch_in_its_thread_and_marks_the_line(self):
        n = self.s.chat_nudge(self.m["seq"])
        self.assertEqual((n["kind"], n["to"], n["via"]), ("user", "ORCH", "board"))
        self.assertIn("AGENT-4 has not read my line #1", n["text"])
        self.assertIn("what do u need from me?", n["text"])
        self.assertIn("message its session", n["text"])
        line = self.s.chat_list()[0]
        self.assertTrue(line.get("nudged"))
        self.assertEqual([m["seq"] for m in self.s.chat_inbox("ORCH")], [n["seq"]])   # ORCH's wait wakes on it

    def test_once_a_minute_per_line(self):
        self.s.chat_nudge(self.m["seq"], now="2026-11-07T10:00:00")
        with self.assertRaises(BoardError) as e:
            self.s.chat_nudge(self.m["seq"], now="2026-11-07T10:00:40")
        self.assertIn("already nudged at 10:00", str(e.exception))
        self.s.chat_nudge(self.m["seq"], now="2026-11-07T10:01:01")

    def test_only_a_line_to_one_agent_and_never_to_orch_itself(self):
        for seq in (self.s.chat_send(self.s.owner, "all of you", kind="user", to="all")["seq"],
                    self.s.chat_send("AGENT-2", "status")["seq"],
                    self.s.chat_send(self.s.owner, "plain")["seq"]):
            with self.assertRaises(BoardError):
                self.s.chat_nudge(seq)
        orch = self.s.chat_send(self.s.owner, "hello?", kind="user", to="ORCH")
        with self.assertRaises(BoardError) as e:
            self.s.chat_nudge(orch["seq"])
        self.assertIn("ORCH is not listening", str(e.exception))
        with self.assertRaises(BoardError):
            self.s.chat_nudge(999)


class TheApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / ".agentboard")
        probe = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(self.store, 0))
        self.port = probe.server_address[1]
        probe.server_close()
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), server.make_handler(self.store, self.port))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def call(self, method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers={"Host": f"localhost:{self.port}", "Content-Type": "application/json"})
        r = c.getresponse()
        return r.status, json.loads(r.read() or b"null")

    def test_the_chat_carries_receipts_and_the_nudge_route_says_whether_orch_listens(self):
        m = self.store.chat_send(self.store.owner, "hello?", kind="user", to="AGENT-4")
        listeners.register(self.store.dir, "AGENT-2", "inbox")
        status, d = self.call("GET", "/api/chat")
        self.assertEqual(status, 200)
        self.assertEqual(d["receipts"]["read"], {})
        self.assertEqual(list(d["receipts"]["listening"]), ["AGENT-2"])
        status, d = self.call("POST", "/api/chat-nudge", {"seq": m["seq"]})
        self.assertEqual(status, 200)
        self.assertEqual(d["message"]["to"], "ORCH")
        self.assertFalse(d["orch_listening"])
        status, d = self.call("POST", "/api/chat-nudge", {"seq": m["seq"]})
        self.assertEqual(status, 400)
        self.assertIn("already nudged", d["error"])
        status, d = self.call("GET", "/api/chat")
        self.assertTrue(d["messages"][0]["nudged"])


class TheStopHook(Base):
    def setUp(self):
        super().setUp()
        self.run_cli("me", "--name", "AGENT-4", "--session", STOP["session_id"])

    def test_an_unread_line_from_the_owner_blocks_the_stop_with_the_line_as_the_reason(self):
        self.s.chat_send(self.s.owner, "what do u need from me?", kind="user", to="AGENT-4")
        self.s.chat_send(self.s.owner, "hello?", kind="user", to="AGENT-4")
        d = hooks.stop_decision(self.s, STOP)
        self.assertEqual(d["decision"], "block")
        self.assertIn("“hello?”", d["reason"])
        self.assertIn("and 1 more", d["reason"])
        self.assertIn("chat inbox --name AGENT-4", d["reason"])
        self.assertIn(f"--to {self.s.owner}", d["reason"])
        self.assertIn("--wait 3600", d["reason"])
        code, out, _err = self.run_cli("hook", "stop", stdin=json.dumps(STOP))
        self.assertIsNone(code)
        self.assertEqual(json.loads(out)["decision"], "block")

    def test_a_read_line_a_line_to_others_or_a_second_stop_in_a_row_does_not_block(self):
        self.s.chat_send(self.s.owner, "hello?", kind="user", to="AGENT-4")
        self.assertTrue(hooks.stop_decision(self.s, dict(STOP, stop_hook_active=True)) is None)
        self.run_cli("chat", "inbox", "--name", "AGENT-4")   # delivered: printed, but the session has done nothing since
        listeners.register(self.s.dir, "AGENT-4", "inbox")
        d = hooks.stop_decision(self.s, STOP)
        self.assertEqual(d["decision"], "block")
        self.assertIn("your wait printed it but you have not acted on it", d["reason"])
        self.run_cli("chat", "send", "on it", "--name", "AGENT-4", "--to", self.s.owner)   # seen: the session acted as that name
        self.s.chat_send(self.s.owner, "everyone", kind="user", to="all")
        self.s.chat_send(self.s.owner, "for two", kind="user", to="AGENT-2")
        self.s.chat_send("AGENT-2", "a status line")
        self.assertIsNone(hooks.stop_decision(self.s, STOP))
        code, out, _err = self.run_cli("hook", "stop", stdin=json.dumps(STOP))
        self.assertEqual((code, out), (None, ""))

    def test_nothing_unread_but_no_wait_running_blocks_once_with_the_wait_to_start(self):
        d = hooks.stop_decision(self.s, STOP)
        self.assertEqual(d["decision"], "block")
        self.assertIn("Nothing is listening for you", d["reason"])
        self.assertIn("chat inbox --name AGENT-4 --wait 3600", d["reason"])
        self.assertIn("run_in_background", d["reason"])
        listeners.register(self.s.dir, "agent-4", "answer card")   # a wait by any spelling of the name
        self.assertIsNone(hooks.stop_decision(self.s, STOP))

    def test_a_session_the_board_does_not_know_or_the_owner_is_left_alone(self):
        self.s.chat_send(self.s.owner, "hello?", kind="user", to="AGENT-9")
        self.assertIsNone(hooks.stop_decision(self.s, dict(STOP, session_id="sid-unknown")))
        self.assertIsNone(hooks.stop_decision(self.s, "not a dict"))
        self.run_cli("me", "--name", self.s.owner, "--session", "sid-owner")
        self.assertIsNone(hooks.stop_decision(self.s, dict(STOP, session_id="sid-owner")))
        os.environ["AGENTBOARD_NAME"] = "AGENT-9"
        self.assertEqual(hooks.stop_decision(self.s, dict(STOP, session_id="sid-unknown"))["decision"], "block")

    def test_the_hook_never_fails_the_session(self):
        code, out, _err = self.run_cli("hook", "stop", stdin="{not json")
        self.assertEqual((code, out), (None, ""))
        here = os.getcwd()
        self.addCleanup(os.chdir, here)
        os.chdir(self.root)   # no board anywhere up from here
        del os.environ["AGENTBOARD_DIR"]
        code, out, _err = self.run_cli("hook", "stop", stdin=json.dumps(STOP))
        self.assertEqual((code, out), (None, ""))


class TheInstall(Base):
    def test_install_writes_both_hooks_status_names_a_missing_one_and_uninstall_takes_both(self):
        _code, out, _err = self.run_cli("hooks", "install")
        self.assertIn("hook stop", out)
        self.assertIn("going quiet", out)
        p = self.proj / ".claude" / "settings.json"
        d = json.loads(p.read_text())
        self.assertEqual(d["hooks"]["PostToolUse"][0]["matcher"], "SendMessage")
        self.assertEqual(list(d["hooks"]["Stop"][0]), ["hooks"])   # no matcher on a Stop hook
        self.assertTrue(d["hooks"]["Stop"][0]["hooks"][0]["command"].endswith("hook stop"))
        self.assertIn("installed:", self.run_cli("hooks", "status")[1])
        del d["hooks"]["Stop"]   # an older install: only the mirror
        p.write_text(json.dumps(d))
        self.assertIn("partly installed (missing: stop", self.run_cli("hooks", "status")[1])
        _p, changed = hooks.install(self.proj)
        self.assertTrue(changed)
        self.assertTrue(hooks.installed(self.proj, "stop"))
        self.assertFalse(hooks.install(self.proj)[1])
        hooks.uninstall(self.proj)
        self.assertFalse(p.exists())
        self.assertIn("not installed", self.run_cli("hooks", "status")[1])

    def test_ours_knows_both_events_and_nothing_else(self):
        self.assertTrue(hooks._ours({"command": "/opt/ab/agentboard hook stop"}))
        self.assertTrue(hooks._ours({"command": "/opt/ab/agentboard hook stop"}, "stop"))
        self.assertFalse(hooks._ours({"command": "/opt/ab/agentboard hook stop"}, "send-message"))
        self.assertFalse(hooks._ours({"command": "/opt/ab/agentboard hook dance"}))
        self.assertFalse(hooks._ours({"command": "/usr/local/bin/audit-log hook stop"}))


class ThePrompts(Base):
    def test_every_agent_prompt_and_the_instructions_keep_the_wait_running_between_cards(self):
        self.s.add("Plain", status="todo")
        self.s.start("Parent", "alice")
        self.s.add("Kid", parent_id="parent")
        for tid in ("plain", "parent", "kid"):
            text, _ = prompt.build_prompt(Store.get(self.s.load(), tid), self.s.dir, tasks=self.s.load())
            self.assertIn('chat inbox --name "<your session name>" --wait 3600', text, tid)
        _code, out, _err = self.run_cli("instructions")
        self.assertIn('chat inbox --name "<your session name>" --wait 3600', out)
        self.assertIn("Nothing else does", out)

    def test_the_orch_prompt_keeps_its_wait_and_relays_a_nudge_by_send_message(self):
        text = prompt.build_orch_prompt(self.s.load(), self.s.dir)
        self.assertIn("chat inbox --name ORCH --wait 3600", text)
        self.assertIn("has not read my line #N", text)
        self.assertIn("your SendMessage does", text)
        self.assertIn("Never answer in the agent's place", text)


class ThePanel(unittest.TestCase):
    def test_a_line_to_one_agent_carries_a_receipt_delivered_read_or_answered(self):
        self.assertIn("${receiptHtml(m)}</div>`;", body("chatBubble"))
        r = body("receiptOf")
        self.assertIn("if (m.kind !== 'user' || !m.to || m.to === 'all' || toOwner(m) || m.via) return null;", r)
        self.assertIn("x.seq > m.seq && (toOwner(x) || x.reply_to === m.seq))) return { state: 'answered' };", r)
        self.assertIn("chatReceipts.read[rk] >= m.seq) return { state: 'seen' };", r)
        self.assertIn("return { state: 'delivered', late: since >= RESHOW_S };", r)   # printed, and for how long nothing confirmed it
        self.assertIn("state: 'sent', late: age >= RECEIPT_WARN_S", r)
        self.assertIn("const RECEIPT_WARN_S = 60, RESHOW_S = 300;", HTML)
        self.assertIn('"receipts": listeners.receipts(self.store.dir)', Path(server.__file__).read_text())
        self.assertIn("chatReceipts = d.receipts || { read: {}, delivered: {}, listening: {} };", body("loadChat"))

    def test_after_a_minute_unread_it_says_whether_anything_wakes_the_agent_and_offers_the_nudge(self):
        h = body("receiptHtml")
        self.assertIn("is listening but has not read this yet", h)
        self.assertIn("is not listening: nothing on the board wakes it", h)
        self.assertIn('data-nudge="${m.seq}"', h)
        self.assertIn("Nudge via ORCH", h)
        self.assertIn("asked ORCH to message it", h)
        self.assertIn("ORCH is not listening: nothing on the board wakes it. Type in its terminal, or boot one with Copy prompt", h)
        self.assertIn("api('/api/chat-nudge', { seq: +b.dataset.nudge })", HTML)
        self.assertIn("['sent', 'delivered'].includes(receiptOf(m)?.state))) renderChat(); }, 15000);", HTML)
        self.assertIn("Not seen in 5 min: it comes again with the next inbox read.", h)
        self.assertIn(".cmsg-rcpt { display: flex;", HTML)
        self.assertIn(".cmsg.user .cmsg-rcpt { justify-content: flex-end;", HTML)


if __name__ == "__main__":
    unittest.main()
