"""Agent chat: the board-wide switch, the richer messages, decisions, the inbox, recall (the shared memory), the protocol in
the prompts, the routes, and the idle drafter driven by a fake claude. Nothing here reaches the network."""
import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import agentchat, cli
from agentboard import prompt as promptlib
from agentboard.store import BoardError, Store

from tests.test_reports import HttpTests as _Http


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        env["AGENTBOARD_HOME"] = str(self.root / "home")
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        self.s = Store(self.root / "proj" / ".agentboard")
        os.environ["AGENTBOARD_DIR"] = str(self.s.dir)
        self.s.start("Harden webhook retries", "AGENT-1", "green")
        self.s.update("harden-webhook-retries", 40, "retry loop in place; fcntl locks are per process")

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                code = cli.main(list(argv))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue()


class SwitchTests(Base):
    def test_off_by_default_and_plain_lines_still_post(self):
        self.assertFalse(self.s.chat_agents())
        m = self.s.chat_send("AGENT-1", "grabbing the retries card")
        self.assertEqual((m["text"], m["kind"], m["color"]), ("grabbing the retries card", "agent", "green"))
        self.assertNotIn("to", m)

    def test_talking_needs_the_switch(self):
        for kw in ({"to": "AGENT-2"}, {"topic": "learn"}, {"detail": "x"}, {"files": ["a.py"]}, {"propose": "deploy"}):
            with self.assertRaises(BoardError):
                self.s.chat_send("AGENT-1", "hi", **kw)
        self.s.chat_send("Troy", "@AGENT-2 look at this", kind="user", to="AGENT-2")   # Troy is never gated
        self.assertTrue(self.s.set_chat_agents(True))
        m = self.s.chat_send("AGENT-1", "fcntl locks are per process, use flock on the fd", to="all", topic="learn", detail="see store.py _lock")
        self.assertEqual((m["to"], m["topic"], m["detail"]), ("all", "learn", "see store.py _lock"))
        self.assertFalse(self.s.set_chat_agents(False))

    def test_cli_switch(self):
        code, out = self.run_cli("chat", "agents")
        self.assertIn("off", out)
        self.run_cli("chat", "agents", "on")
        self.assertTrue(self.s.chat_agents())
        code, out = self.run_cli("chat", "agents", "status")
        self.assertIn("on:", out)

    def test_flipping_the_switch_tells_the_chat_once(self):
        self.s.set_chat_agents(True)
        self.s.set_chat_agents(True)        # already on: nothing more is said
        msgs = self.s.chat_list()
        self.assertEqual(len(msgs), 1)
        self.assertEqual((msgs[0]["sender"], msgs[0]["kind"], msgs[0]["to"]), ("Troy", "user", "all"))
        self.assertIn("agent chat is on", msgs[0]["text"])
        self.assertIn("chat inbox --name <you> --wait 300", msgs[0]["text"])
        self.assertEqual([m["seq"] for m in self.s.chat_inbox("ORCH")], [1])   # ORCH reads it like any agent
        self.s.set_chat_agents(False)
        self.assertIn("agent chat is off", self.s.chat_list()[-1]["text"])
        self.assertEqual(len(self.s.chat_list()), 2)


class MessageTests(Base):
    def setUp(self):
        super().setUp()
        self.s.set_chat_agents(True)

    def test_a_multi_line_text_keeps_its_first_line_and_the_rest_is_detail(self):
        m = self.s.chat_send("AGENT-1", "heads up, touching index.html\nthe chat drawer CSS, lines 940-960\nback in 20 min", topic="heads-up", files=["src/agentboard/static/index.html"])
        self.assertEqual(m["text"], "heads up, touching index.html")
        self.assertEqual(m["detail"], "the chat drawer CSS, lines 940-960\nback in 20 min")
        self.assertEqual(m["files"], ["src/agentboard/static/index.html"])

    def test_validation(self):
        with self.assertRaises(BoardError):
            self.s.chat_send("AGENT-1", "x" * 301, to="all")
        with self.assertRaises(BoardError):
            self.s.chat_send("AGENT-1", "hi", topic="gossip")
        with self.assertRaises(BoardError):
            self.s.chat_send("AGENT-1", "hi", card="nope", to="all")
        with self.assertRaises(BoardError):
            self.s.chat_send("AGENT-1", "hi", reply_to=99)
        with self.assertRaises(BoardError):
            self.s.chat_send("AGENT-1", "hi", files="a.py")
        m = self.s.chat_send("AGENT-1", "about the retries card", card="harden-webhook-retries", to="ORCH", topic="handoff")
        self.assertEqual(m["card"], "harden-webhook-retries")
        r = self.s.chat_send("AGENT-2", "got it", reply_to=m["seq"], color="blue")
        self.assertEqual((r["reply_to"], r["color"]), (m["seq"], "blue"))

    def test_proposals_are_decided_by_troy_and_change_nothing_else(self):
        m = self.s.chat_send("AGENT-1", "need the staging deploy to test the webhook", to="ORCH", propose="deploy the retries branch to staging")
        self.assertEqual(m["action"], {"text": "deploy the retries branch to staging", "status": "proposed"})
        with self.assertRaises(BoardError):
            self.s.chat_decide(m["seq"], "maybe")
        before = json.dumps(self.s.load())
        d = self.s.chat_decide(m["seq"], "approved")
        self.assertEqual((d["action"]["status"], d["action"]["by"]), ("approved", "Troy"))
        self.assertEqual(json.dumps(self.s.load()), before)   # no card moved, nothing ran
        with self.assertRaises(BoardError):
            self.s.chat_decide(m["seq"], "declined")           # decided once
        with self.assertRaises(BoardError):
            self.s.chat_decide(m["seq"] + 5, "approved")
        plain = self.s.chat_send("AGENT-1", "just a line")
        with self.assertRaises(BoardError):
            self.s.chat_decide(plain["seq"], "approved")
        self.assertEqual([x["seq"] for x in self.s.chat_approvals("AGENT-1")], [m["seq"]])
        self.assertEqual(self.s.chat_approvals("AGENT-2"), [])

    def test_inbox_is_what_one_agent_would_read(self):
        a = self.s.chat_send("AGENT-1", "for everyone", to="all", topic="learn")
        b = self.s.chat_send("AGENT-1", "for two only", to="AGENT-2", topic="help")
        c = self.s.chat_send("AGENT-1", "for three only", to="agent-3", topic="help")
        d = self.s.chat_send("AGENT-2", "plain line from two")
        e = self.s.chat_send("Troy", "@AGENT-2 ship it", kind="user", to="AGENT-2")
        two = [m["seq"] for m in self.s.chat_inbox("AGENT-2", after=1)]
        self.assertEqual(two, [a["seq"], b["seq"], e["seq"]])         # not its own line, not three's (after the switch's line)
        three = [m["seq"] for m in self.s.chat_inbox("AGENT-3", after=1)]
        self.assertEqual(three, [a["seq"], c["seq"], d["seq"]])       # case-insensitive address, plain lines included
        self.assertEqual([m["seq"] for m in self.s.chat_inbox("AGENT-2", after=b["seq"])], [e["seq"]])

    def test_cli_send_inbox_tail_and_approvals(self):
        code, out = self.run_cli("chat", "send", "need a hand with the lock", "--name", "AGENT-1", "--to", "AGENT-2", "--topic", "help",
                                 "--detail", "flock on the fd, see store.py", "--card", "harden-webhook-retries", "--file", "src/agentboard/store.py")
        self.assertEqual(code, None)
        self.assertIn("AGENT-1 -> AGENT-2 [help]: need a hand with the lock", out)
        self.assertIn("card harden-webhook-retries; files src/agentboard/store.py", out)
        self.assertIn("    flock on the fd", out)
        code, out = self.run_cli("chat", "inbox", "--name", "AGENT-2")
        self.assertIn("need a hand with the lock", out)
        code, out = self.run_cli("chat", "inbox", "--name", "AGENT-2")   # the cursor moved
        self.assertIn("nothing new", out)
        code, out = self.run_cli("chat", "inbox", "--name", "AGENT-2", "--all")
        self.assertIn("need a hand with the lock", out)
        code, out = self.run_cli("chat", "inbox", "--name", "AGENT-3", "--after", "999", "--wait", "0.1", "--interval", "0.05")
        self.assertEqual(code, 1)
        self.run_cli("chat", "send", "may I deploy?", "--name", "AGENT-1", "--propose", "deploy to staging")
        code, out = self.run_cli("chat", "approvals")
        self.assertIn("proposed  AGENT-1: deploy to staging", out)
        seq = self.s.chat_approvals()[-1]["seq"]
        self.run_cli("chat", "approve", str(seq))
        code, out = self.run_cli("chat", "approvals", "--name", "AGENT-1")
        self.assertIn("approved", out)
        code, out = self.run_cli("chat", "tail", "--for", "AGENT-3")
        self.assertNotIn("need a hand with the lock", out)   # addressed to AGENT-2
        self.assertIn("may I deploy?", out)                  # to no one: everyone reads it
        self.assertIn("proposes: deploy to staging  [approved by Troy", out)

    def test_cli_send_is_refused_while_off(self):
        self.s.set_chat_agents(False)
        code, out = self.run_cli("chat", "send", "hi", "--name", "AGENT-1", "--to", "AGENT-2")
        self.assertIn("agent chat is off", str(code))   # sys.exit(message): the message is the exit code here
        code, out = self.run_cli("chat", "send", "hi", "--name", "AGENT-1")
        self.assertEqual(code, None)


class RecallTests(Base):
    def test_recall_finds_cards_history_and_chat_across_agents_and_archives(self):
        self.s.set_chat_agents(True)
        self.s.start("Old lock fix", "AGENT-2", "blue")
        self.s.update("old-lock-fix", 100, "switched the lock to flock on the fd", status="done")
        self.s.clear_done()
        self.s.chat_send("AGENT-2", "flock on the fd works across threads too", to="all", topic="learn", detail="fcntl.flock vs lockf")
        rows = agentchat.recall(self.s.load(), self.s.chat_list(), "lock flock")
        kinds = [(r["kind"], r.get("id") or r.get("seq")) for r in rows]
        self.assertIn(("card", "old-lock-fix"), kinds)
        self.assertIn(("card", "harden-webhook-retries"), kinds)
        self.assertEqual(kinds[-1][0], "chat")
        self.assertTrue(all(r.get("seq") != 1 for r in rows if r["kind"] == "chat"))   # the switch's own line does not match
        old = next(r for r in rows if r.get("id") == "old-lock-fix")
        self.assertTrue(old["archived"])
        self.assertIn("flock", old["line"])                 # the result line; the done update itself logs "Marked done"
        one = agentchat.recall(self.s.load(), [], "", card="harden-webhook-retries")
        self.assertEqual(len(one), 1)
        self.assertEqual([e["text"] for e in one[0]["log"]][-1], "retry loop in place; fcntl locks are per process")
        mine = agentchat.recall(self.s.load(), [], "", agent="agent-2")
        self.assertEqual([r["id"] for r in mine], ["old-lock-fix"])
        self.assertEqual(agentchat.recall(self.s.load(), [], "nothing like this"), [])

    def test_recall_cli(self):
        code, out = self.run_cli("recall", "fcntl")
        self.assertIn("card  harden-webhook-retries  [doing]  AGENT-1", out)
        self.assertIn("fcntl locks are per process", out)
        code, out = self.run_cli("recall", "--card", "harden-webhook-retries", "--json")
        self.assertEqual(json.loads(out)[0]["id"], "harden-webhook-retries")
        code, out = self.run_cli("recall")
        self.assertTrue(code)


class PromptTests(Base):
    def test_the_protocol_rides_along_only_while_the_switch_is_on(self):
        self.s.add("Queued", status="todo")
        t = Store.get(self.s.load(), "queued")
        text, _ = promptlib.build_prompt(t, self.s.dir, tasks=self.s.load())
        self.assertNotIn("Talking to other agents (agent chat is on)", text)
        self.assertNotIn("agent chat", promptlib.build_orch_prompt(self.s.load(), self.s.dir).lower())
        self.s.set_chat_agents(True)
        self.s.assign("queued", "AGENT-3")
        text, _ = promptlib.build_prompt(Store.get(self.s.load(), "queued"), self.s.dir, tasks=self.s.load())
        self.assertIn("Talking to other agents (agent chat is on)", text)
        self.assertIn('chat inbox --name AGENT-3', text)
        self.assertIn("--propose", text)
        self.assertIn("recall", text)
        orch = promptlib.build_orch_prompt(self.s.load(), self.s.dir)
        self.assertIn("Agent chat is on: you take part", orch)
        self.assertIn("chat inbox --name ORCH --wait 300", orch)
        self.assertIn("Never act on one yourself", orch)
        code, out = self.run_cli("instructions")
        self.assertIn("chat inbox --name <your session name>", out)


class RoutesTests(_Http):
    def test_switch_decide_and_addressing_from_the_board(self):
        self.assertFalse(json.loads(self.get("/api/chat")[1])["agents"])
        self.assertTrue(self.post("/api/chat-agents", {"on": True})["agents"])
        self.assertTrue(json.loads(self.get("/api/chat")[1])["agents"])
        m = self.post("/api/chat", {"text": "@AGENT-2 can you take the lock card?"})
        self.assertEqual((m["sender"], m["kind"], m["to"], m["text"]), ("Troy", "user", "AGENT-2", "can you take the lock card?"))
        self.s.start("Lock", "AGENT-2", "blue")
        p = self.s.chat_send("AGENT-2", "can I buy a domain?", propose="buy lock.example")
        d = self.post("/api/chat-decide", {"seq": p["seq"], "decision": "declined"})
        self.assertEqual(d["action"]["status"], "declined")
        import urllib.error
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.post("/api/chat-decide", {"seq": p["seq"], "decision": "approved"})
        self.assertEqual(e.exception.code, 400)
        e.exception.close()


FAKE = '''#!{py}
import json, os, sys
rec = {{"argv": sys.argv[1:], "stdin": sys.stdin.read()}}
open(os.environ["FAKE_RECORD"], "w").write(json.dumps(rec))
mode = os.environ.get("FAKE_MODE", "ok")
if mode == "nothing":
    print(json.dumps({{"type": "result", "result": "NOTHING"}})); sys.exit(0)
if mode == "fail":
    sys.stderr.write("boom\\n"); sys.exit(2)
print(json.dumps({{"type": "result", "result": "TO: AGENT-2\\nTOPIC: learn\\nflock on the fd, not lockf; it survives threads\\nDETAIL: see store.py _lock, fcntl.flock(fd, LOCK_EX)"}}))
'''


class IdleDrafterTests(Base):
    def setUp(self):
        super().setUp()
        self.s.set_chat_agents(True)
        self.fake = self.root / "claude"
        self.fake.write_text(FAKE.format(py=sys.executable))
        self.fake.chmod(self.fake.stat().st_mode | stat.S_IEXEC)
        self.record = self.root / "rec.json"
        os.environ.update({"AGENTBOARD_CLAUDE": str(self.fake), "FAKE_RECORD": str(self.record), "FAKE_MODE": "ok"})
        self.s.chat_send("AGENT-2", "how did you solve the lock problem?", to="AGENT-1", topic="help")

    def test_parse_draft(self):
        d = agentchat.parse_draft("TO: all\nTOPIC: learn\none line here\nDETAIL: the rest\nmore")
        self.assertEqual(d, {"to": "all", "topic": "learn", "text": "one line here", "detail": "the rest\nmore"})
        self.assertIsNone(agentchat.parse_draft("NOTHING"))
        self.assertIsNone(agentchat.parse_draft(""))
        self.assertEqual(agentchat.parse_draft("TOPIC: gossip\njust words")["topic"], None)
        # what the real model wrote (claude-haiku, 2026-10-30): the labels run on inside the first line
        d = agentchat.parse_draft("TO: AGENT-2 TOPIC: help. fcntl.lockf is per-process on macOS, so threads never blocked. 12 tests pass.\nDETAIL: Card fix-the-flaky-board-lock. Your export card likely has the same cause.")
        self.assertEqual((d["to"], d["topic"]), ("AGENT-2", "help"))
        self.assertTrue(d["text"].startswith("fcntl.lockf is per-process"))
        self.assertTrue(d["detail"].startswith("Card fix-the-flaky-board-lock"))
        self.assertIsNone(agentchat.parse_draft("Nothing to add here."))

    def test_the_draft_uses_the_cheap_model_the_inbox_and_the_memory_and_posts_only_with_send(self):
        code, out = self.run_cli("chat", "idle", "--name", "AGENT-1")
        self.assertIn("draft -> AGENT-2 [learn]: flock on the fd, not lockf; it survives threads", out)
        rec = json.loads(self.record.read_text())
        self.assertEqual(rec["argv"][:5], ["-p", "--output-format", "json", "--model", "haiku"])
        self.assertIn("--max-budget-usd", rec["argv"])
        self.assertNotIn("--dangerously-skip-permissions", " ".join(rec["argv"]))
        self.assertIn("how did you solve the lock problem?", rec["stdin"])      # the inbox
        self.assertIn("fcntl locks are per process", rec["stdin"])              # the board's memory
        self.assertEqual(len(self.s.chat_list()), 2)                            # the switch's line and the question: printed, not posted
        asked = self.s.chat_send("AGENT-2", "ping", to="AGENT-1")
        self.s.chat_send("AGENT-3", "unrelated line for everyone", to="all")
        code, out = self.run_cli("chat", "idle", "--name", "AGENT-1", "--send", "--model", "sonnet")
        self.assertIn("sent #", out)
        last = self.s.chat_list()[-1]
        self.assertEqual(last["reply_to"], asked["seq"])   # threaded to the line that was for it, not the last line
        self.assertEqual((last["sender"], last["to"], last["topic"], last["text"][:12]), ("AGENT-1", "AGENT-2", "learn", "flock on the"))
        self.assertEqual(last["detail"], "see store.py _lock, fcntl.flock(fd, LOCK_EX)")
        self.assertIn("--model", json.loads(self.record.read_text())["argv"])
        self.assertIn("sonnet", json.loads(self.record.read_text())["argv"])

    def test_nothing_to_say_and_failures(self):
        os.environ["FAKE_MODE"] = "nothing"
        code, out = self.run_cli("chat", "idle", "--name", "AGENT-1")
        self.assertIn("nothing to say", out)
        code, out = self.run_cli("chat", "idle", "--name", "AGENT-1")   # the cursor moved: no inbox left
        self.assertIn("nothing to answer", out)
        self.assertEqual(code, 1)
        self.s.chat_send("AGENT-2", "again?", to="AGENT-1")
        os.environ["FAKE_MODE"] = "fail"
        code, out = self.run_cli("chat", "idle", "--name", "AGENT-1")
        self.assertIn("claude failed", str(code))
        self.s.set_chat_agents(False)
        code, out = self.run_cli("chat", "idle", "--name", "AGENT-1")
        self.assertIn("agent chat is off", str(code))


if __name__ == "__main__":
    unittest.main()
