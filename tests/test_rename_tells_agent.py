"""A rename reaches the running agent (card rename-from-board). Throwaway boards only.

What is pinned: the rename posts one direct board line to the new name (the owner's line, via "board") that says what to run; the board
then waits for that name until a session calls itself by it (`agentboard me --name X`, or any command run as X); a command still run under the
old name does not end the wait; a `chat inbox --wait` or `answer --wait` that was started under the old name ends on its own with the new name,
so the agent wakes; `rename --undo` posts the line back the other way; the plan warns when the agent has a card in Doing; and Suggest returns one
plain name no agent has, from the agent's current card."""
import contextlib
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from agentboard import cli, listeners, names, rename
from agentboard.server import make_handler
from agentboard.store import Store

CONFIG = '[board]\nowner = "Pat"\n'
SRC = str(Path(cli.__file__).resolve().parent.parent)


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
        os.environ["AGENTBOARD_DIR"] = str(self.d)
        self.d.mkdir(parents=True, exist_ok=True)
        (self.d / "config.toml").write_text(CONFIG)
        self.s.add("Rename an agent from the board", task_id="open1")
        self.s.claim("open1", "Scout")

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

    def chat(self):
        return self.s._read()["chat"]


class TheBoardLine(Base):
    def test_the_rename_posts_one_direct_line_to_the_new_name(self):
        code, out = self.run_cli("rename", "Scout", "Ives")
        self.assertFalse(code, out)
        lines = [m for m in self.chat() if m.get("to") == "Ives"]
        self.assertEqual(len(lines), 1, self.chat())
        m = lines[0]
        self.assertEqual((m["sender"], m["kind"], m.get("via")), ("Pat", "user", "board"))
        self.assertIn("You are now Ives", m["text"])
        self.assertIn("agentboard me --name Ives", m["text"])
        self.assertIn("listener", m["text"].lower())
        self.assertLessEqual(len(m["text"]), 300)
        self.assertIn("Ives", "\n".join(out.splitlines()[-3:]))   # the terminal says the line went

    def test_the_board_waits_for_the_new_name_until_a_session_calls_itself_by_it(self):
        self.run_cli("rename", "Scout", "Ives")
        w = rename.waiting(self.d)
        self.assertIn("ives", w)
        self.assertEqual((w["ives"]["old"], w["ives"]["new"]), ("Scout", "Ives"))
        os.environ["AGENTBOARD_NAME"] = "Scout"   # the terminal that has not switched yet: the alias makes its commands work, but it has not switched
        code, out = self.run_cli("update", "open1", "40", "still Scout here")
        self.assertFalse(code, out)
        self.assertIn("ives", rename.waiting(self.d))
        os.environ.pop("AGENTBOARD_NAME", None)
        code, out = self.run_cli("me", "--name", "Ives", "--session", "sid-9")
        self.assertFalse(code, out)
        self.assertEqual(rename.waiting(self.d), {})

    def test_any_command_run_as_the_new_name_ends_the_wait(self):
        self.run_cli("rename", "Scout", "Ives")
        os.environ["AGENTBOARD_NAME"] = "Ives"
        self.run_cli("update", "open1", "50", "Ives now")
        self.assertEqual(rename.waiting(self.d), {})

    def test_undo_posts_the_line_back_and_waits_for_the_old_name(self):
        self.run_cli("rename", "Scout", "Ives")
        code, out = self.run_cli("rename", "--undo")
        self.assertFalse(code, out)
        last = self.chat()[-1]
        self.assertEqual((last.get("to"), last.get("via")), ("Scout", "board"))
        self.assertIn("agentboard me --name Scout", last["text"])
        self.assertEqual(list(rename.waiting(self.d)), ["scout"])

    def test_the_plan_warns_when_the_agent_is_busy(self):
        self.s.update("open1", 30, "working")   # Doing
        p = rename.plan(self.s, "Scout", "Ives")
        self.assertEqual([b["id"] for b in p["busy"]], ["open1"])
        self.assertTrue(any("safest to rename when idle" in line for line in rename.describe(p, dry=True)))
        self.s.move("open1", "todo")
        p = rename.plan(self.s, "Scout", "Ives")
        self.assertEqual(p["busy"], [])
        self.assertFalse(any("idle" in line for line in rename.describe(p, dry=True)))


class TheOldWaitEnds(Base):
    """The wait was started under the old name, in its own process as an agent's shell would: it ends with the new name, which is what wakes the agent."""

    def start(self, *argv):
        env = {**os.environ, "PYTHONPATH": SRC}
        return subprocess.Popen([sys.executable, "-m", "agentboard", *argv], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)

    def finish(self, proc):
        try:
            out, _ = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
            self.fail("the wait did not end: " + out)
        return proc.returncode, out

    def wait_registered(self, name):
        for _ in range(200):
            if listeners.sessions(self.d, name):
                return
            threading.Event().wait(0.05)
        self.fail(f"{name} never registered a wait")

    def test_chat_inbox_wait_ends_with_the_new_name(self):
        proc = self.start("chat", "inbox", "--name", "Scout", "--wait", "25", "--interval", "0.2")
        self.wait_registered("Scout")
        self.run_cli("rename", "Scout", "Ives")
        code, out = self.finish(proc)
        self.assertEqual(code, 0, out)
        self.assertIn("You are now Ives", out)
        self.assertIn("agentboard me --name Ives", out)
        self.assertNotIn("Scout", listeners._read(self.d))   # its entry is gone with it

    def test_answer_wait_ends_with_the_new_name(self):
        self.s.update("open1", 30, "working")
        self.s.review("open1", "ready", by="Scout")
        proc = self.start("answer", "open1", "--wait", "--timeout", "25", "--interval", "0.2")
        self.wait_registered("Scout")
        self.run_cli("rename", "Scout", "Ives")
        code, out = self.finish(proc)
        self.assertEqual(code, 0, out)
        self.assertIn("You are now Ives", out)


class Suggest(Base):
    def test_a_plain_one_line_name_from_the_current_card(self):
        self.s.update("open1", 30, "working")
        got = rename.suggest(self.s, "Scout")
        self.assertEqual(set(got), {"name", "from"})
        self.assertRegex(got["name"], rename.NAME_RE)
        self.assertNotIn("\n", got["name"])
        self.assertEqual(got["name"], "RenameBot")
        self.assertIn("open1", got["from"])
        self.assertNotIn(names.key(got["name"]), rename._names_in_use(self.s, self.s._read(), self.s._read_archive()))

    def test_a_taken_name_gets_a_number_and_a_stopword_title_is_skipped(self):
        self.s.add("The RenameBot card", task_id="t2")
        self.s.claim("t2", "RenameBot")
        got = rename.suggest(self.s, "Scout")
        self.assertEqual(got["name"], "RenameBot-2")
        self.s.add("Of the and or", task_id="t3")
        self.s.claim("t3", "Zed")
        got = rename.suggest(self.s, "Zed")
        self.assertEqual(got["name"], "Agent-1")   # nothing to go by: a numbered fallback that is still a plain name

    def test_an_agent_with_no_card_gets_the_fallback(self):
        self.s.chat_send("Lone", "hello", kind="agent")
        got = rename.suggest(self.s, "Lone")
        self.assertEqual(got["name"], "Agent-1")
        self.assertIn("no card", got["from"])

    def test_cli_suggest_prints_the_name_alone(self):
        code, out = self.run_cli("rename", "Scout", "--suggest")
        self.assertFalse(code, out)
        self.assertEqual(out.strip(), "RenameBot")


class TheDialogsApi(Base):
    def setUp(self):
        super().setUp()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), make_handler(self.s, self.port))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.shutdown)

    def js(self, path, payload):
        h = {"Content-Type": "application/json", "Host": f"localhost:{self.port}", "Origin": f"http://localhost:{self.port}"}
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=json.dumps(payload).encode(), headers=h)
        try:
            r = urllib.request.urlopen(req, timeout=5)
            return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            body = e.read()
            e.close()
            return e.code, json.loads(body)

    def test_suggest_busy_and_waiting_reach_the_page(self):
        self.s.update("open1", 30, "working")
        code, r = self.js("/api/rename/suggest", {"old": "Scout"})
        self.assertEqual((code, r["name"]), (200, "RenameBot"))
        code, r = self.js("/api/rename/plan", {"old": "Scout", "new": ""})
        self.assertEqual(code, 200)
        self.assertEqual([b["id"] for b in r["plan"]["busy"]], ["open1"])
        code, r = self.js("/api/rename", {"old": "Scout", "new": "Ives"})
        self.assertEqual(code, 200)
        self.assertEqual(r["waiting"], "Ives")
        self.assertTrue(r["posted"])   # the seq of the board line
        self.assertEqual(list(listeners.receipts(self.d)["renames"]), ["ives"])   # the page sees who has not switched yet, where it sees who is listening
        code, r = self.js("/api/rename/suggest", {"old": "Nobody"})
        self.assertEqual(code, 400)


if __name__ == "__main__":
    unittest.main()
