"""Two LOWs from the Nov 7 merge review. rev1107-receipts-never-age: a receipt is history after a day, and a line to an agent under [hud]
retired is too: no warning, no Nudge, no 15 s re-render. rev1107-answered-means-any-line: "answered" means a reply to THAT line (chat send
--reply-to <n>); a later line to the owner without it says "wrote back"; the prompts and the Stop hook tell agents to answer with --reply-to."""
import json
import os
import socket
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from agentboard import hooks, prompt, server

from test_mirror import Base

HTML = (Path(__file__).resolve().parents[1] / "src" / "agentboard" / "static" / "index.html").read_text()
README = (Path(__file__).resolve().parents[1] / "README.md").read_text()


def body(fn):
    i = HTML.index(f"function {fn}(")
    return HTML[i:HTML.index("\n}\n", i)]


class ThePage(unittest.TestCase):
    def test_a_receipt_is_history_after_a_day_or_for_a_retired_agent(self):
        self.assertIn("RECEIPT_MAX_S = 86400", HTML)
        r = body("receiptOf")
        self.assertIn("const retired = chatRetired.some(r => sameName(r, to));", r)
        self.assertIn("if (age >= RECEIPT_MAX_S || retired) return { state: delivered ? 'delivered' : 'sent', old: true, retired };", r)
        h = body("receiptHtml")
        self.assertIn("if (r.old) return", h)
        self.assertIn("retired agent", h)
        self.assertIn("return r && !r.old && ['sent', 'delivered'].includes(r.state); })) renderChat(); }, 15000);", HTML)
        self.assertIn("chatRetired = d.retired || [];", body("loadChat"))

    def test_answered_means_a_reply_to_that_line_and_wrote_back_is_the_softer_word(self):
        r = body("receiptOf")
        self.assertIn("if (later.some(x => x.reply_to === m.seq)) return { state: 'answered' };", r)
        self.assertIn("if (later.some(x => toOwner(x))) return { state: 'wrote back' };", r)
        self.assertIn(".cmsg-rcpt.wrote-back .st", HTML)
        self.assertIn("**answered** (it replied to that line with", README)
        self.assertIn("**wrote back**", README)
        self.assertIn("A line older than a day, or one to an agent listed under `[hud] retired`", README)


class ThePromptsAndTheHookSayReplyTo(Base):
    def test_every_answer_instruction_carries_reply_to(self):
        from agentboard import cli, rules
        for t in (rules.wake("{ab}", "{task_id}", "me", "review"), prompt.ORCH_TEMPLATE, cli.INSTRUCTIONS):   # the card prompts take their wait paragraph from rules.py
            self.assertIn("--reply-to", t)
        self.assertNotIn('--to {owner}`, then start the wait again', prompt.DEFAULT_TEMPLATE)
        self.assertNotIn("--to {owner}", rules.wake("{ab}", "{task_id}", "me", "review"))   # the command word is {owner_cli}, the prose is {owner}

    def test_the_stop_hook_names_the_line_to_reply_to(self):
        m = self.s.chat_send(self.s.owner, "what do you need?", kind="user", to="AGENT-4")
        os.environ["AGENTBOARD_NAME"] = "AGENT-4"
        d = hooks.stop_decision(self.s, {"session_id": "sid-4", "stop_hook_active": False})
        self.assertEqual(d["decision"], "block")
        self.assertIn(f"--to {self.s.owner} --reply-to {m['seq']}", d["reason"])


class TheApiNamesRetiredAgents(Base):
    def test_api_chat_carries_the_retired_list(self):
        (self.s.dir / "config.toml").write_text('[hud]\nretired = ["AGENT-9"]\n')
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
            port = sk.getsockname()[1]
        srv = ThreadingHTTPServer(("127.0.0.1", port), server.make_handler(self.s, port))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/chat", headers={"Host": f"localhost:{port}"})
        with urllib.request.urlopen(req, timeout=5) as r:
            d = json.loads(r.read())
        self.assertEqual(d["retired"], ["AGENT-9"])
        self.assertIn("receipts", d)


if __name__ == "__main__":
    unittest.main()
