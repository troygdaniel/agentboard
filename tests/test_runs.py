"""One-shot agents (`agentboard run`), driven by a fake claude binary: nothing here calls the real one."""
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from agentboard import runs
from agentboard.store import BoardError, Store

FAKE = '''#!{py}
import json, os, subprocess, sys, time
mode = os.environ.get("FAKE_MODE", "ok")
rec = {{"argv": sys.argv[1:], "stdin": sys.stdin.read(), "cwd": os.getcwd(), "env": {{k: v for k, v in os.environ.items() if k.startswith("AGENTBOARD")}}}}
open(os.environ["FAKE_RECORD"], "w").write(json.dumps(rec))
card = os.environ.get("FAKE_CARD", "")
if mode == "sleep":
    time.sleep(60)
if mode == "touch":
    open("left-behind.txt", "w").write("x")
if mode == "commit":
    import subprocess
    open("work.txt", "w").write("x")
    subprocess.run(["git", "add", "."], check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "work"], check=True)
if mode == "review":
    subprocess.run([sys.executable, "-m", "agentboard", "review", card, "Self report"], check=True)
if mode == "fail":
    sys.stderr.write("first line\\nboom: something broke\\n")
    sys.exit(3)
if mode == "budget":
    print(json.dumps({{"type": "result", "subtype": "error_max_budget_usd", "is_error": True, "total_cost_usd": 2.5, "result": ""}}))
    sys.exit(1)
print(json.dumps({{"type": "result", "subtype": "success", "is_error": False, "result": "Did the thing.\\nMore detail.", "total_cost_usd": 0.12, "duration_ms": 900}}))
'''


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.store = Store(self.root / "proj" / ".agentboard")
        self.work = self.root / "work"
        self.work.mkdir()
        fake = self.root / "claude"
        fake.write_text(FAKE.format(py=sys.executable))
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        self.record = self.root / "record.json"
        env = {"AGENTBOARD_CLAUDE": str(fake), "FAKE_RECORD": str(self.record), "FAKE_MODE": "ok",
               "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        self.store.add("Fix the widget", description="The widget is broken in the header.", status="todo")
        os.environ["FAKE_CARD"] = "fix-the-widget"

    def run_it(self, **kw):
        kw.setdefault("cwd", str(self.work))
        kw.setdefault("log", lambda *_: None)
        return runs.run_card(self.store, "fix-the-widget", **kw)

    def card(self):
        return Store.get(self.store.load(), "fix-the-widget")

    def recorded(self):
        return json.loads(self.record.read_text())


class RunTests(Base):
    # -- the happy path --------------------------------------------------------------------------------------------------------
    def test_a_clean_run_claims_the_card_then_moves_it_to_review_with_cost_and_time(self):
        rec = self.run_it(name="RUN-1", color="green", budget=2.5, minutes=1)
        c = self.card()
        self.assertEqual(rec["status"], "finished")
        self.assertEqual((c["status"], c["agent"], c["color"]), ("doing", "RUN-1", "green"))
        self.assertTrue(c["review"])
        self.assertIn("Did the thing.", c["result"])
        self.assertEqual(c["run"]["status"], "finished")
        self.assertEqual(c["run"]["cost_usd"], 0.12)
        self.assertGreaterEqual(c["run"]["duration_s"], 0)
        self.assertIn("$0.12", c["result"])
        self.assertTrue(any("One-shot run finished" in e["text"] for e in c["log"]))
        self.assertTrue((Path(rec["dir"]) / "prompt.md").exists() and (Path(rec["dir"]) / "stdout.json").exists())

    def test_the_prompt_is_the_card_prompt_plus_the_rules(self):
        self.run_it(name="RUN-1", budget=2.5, minutes=3)
        prompt = self.recorded()["stdin"]
        self.assertIn("Fix the widget", prompt)
        self.assertIn("The widget is broken in the header.", prompt)
        self.assertIn("Rules for this run", prompt)
        self.assertIn("review fix-the-widget", prompt)
        self.assertIn("Never place calls", prompt)           # the never-dial, never-buy rules stay in the prompt
        self.assertIn("buy or subscribe", prompt)
        self.assertIn("ACTION", prompt)
        self.assertIn("3 minutes and $2.5", prompt)

    def test_the_budget_goes_to_claude_and_no_permission_is_widened(self):
        self.run_it(budget=2.5, minutes=1)
        argv = self.recorded()["argv"]
        self.assertEqual(argv[argv.index("--max-budget-usd") + 1], "2.5")
        self.assertIn("-p", argv)
        joined = " ".join(argv).lower()
        for widening in ("dangerously", "permission", "allowedtools", "allowed-tools", "bypass", "settings", "--add-dir", "mcp"):
            self.assertNotIn(widening, joined)

    def test_the_run_points_agentboard_at_this_board_and_runs_in_the_chosen_folder(self):
        os.environ["AGENTBOARD_BOARD"] = "somewhere-else"   # must not leak into the run
        try:
            self.run_it(name="RUN-1", color="blue", minutes=1)
        finally:
            os.environ.pop("AGENTBOARD_BOARD")
        r = self.recorded()
        self.assertEqual(r["cwd"], str(self.work))
        self.assertEqual(r["env"]["AGENTBOARD_DIR"], str(self.store.dir))
        self.assertEqual((r["env"]["AGENTBOARD_NAME"], r["env"]["AGENTBOARD_COLOR"]), ("RUN-1", "blue"))
        self.assertNotIn("AGENTBOARD_BOARD", r["env"])

    def test_a_card_the_agent_already_reported_is_not_reported_twice(self):
        os.environ["FAKE_MODE"] = "review"
        self.run_it(name="RUN-1", minutes=1)
        c = self.card()
        self.assertEqual(c["result"], "Self report")
        self.assertEqual(c["run"]["status"], "finished")

    # -- failures --------------------------------------------------------------------------------------------------------------
    def test_a_failed_run_asks_with_the_tail_of_the_output(self):
        os.environ["FAKE_MODE"] = "fail"
        rec = self.run_it(name="RUN-1", minutes=1)
        c = self.card()
        self.assertEqual(rec["status"], "failed")
        self.assertTrue(c["needs_input"])
        self.assertIn("failed (exit 3)", c["question"])
        self.assertIn("boom: something broke", c["body_md"])
        self.assertEqual(c["run"]["status"], "failed")
        self.assertNotIn("review", c)

    def test_a_budget_stop_is_a_failure_that_says_so(self):
        os.environ["FAKE_MODE"] = "budget"
        rec = self.run_it(name="RUN-1", budget=2.5, minutes=1)
        self.assertEqual(rec["status"], "failed")
        self.assertIn("error_max_budget_usd", self.card()["question"])
        self.assertEqual(self.card()["run"]["cost_usd"], 2.5)

    def test_the_time_limit_stops_the_process_and_asks(self):
        os.environ["FAKE_MODE"] = "sleep"
        with mock.patch.object(runs, "KILL_GRACE_S", 1):
            rec = self.run_it(name="RUN-1", minutes=0.02)
        self.assertEqual(rec["status"], "timeout")
        self.assertIn("minute limit", self.card()["question"])
        self.assertFalse(runs.pid_alive(rec["pid"]))

    def test_the_kill_switch_stops_a_live_run(self):
        os.environ["FAKE_MODE"] = "sleep"
        out = {}
        with mock.patch.object(runs, "KILL_GRACE_S", 1):
            th = threading.Thread(target=lambda: out.update(rec=self.run_it(name="RUN-1", minutes=5)))
            th.start()
            for _ in range(100):
                live = runs.live_run(self.store.dir, "fix-the-widget")
                if live and live[1].get("pid"):
                    break
                time.sleep(0.1)
            self.assertIsNotNone(live)
            runs.kill_run(self.store.dir, "fix-the-widget")
            th.join(timeout=20)
        self.assertEqual(out["rec"]["status"], "killed")
        self.assertIn("kill switch", self.card()["question"])
        self.assertFalse(runs.pid_alive(out["rec"]["pid"]))
        with self.assertRaises(BoardError):
            runs.kill_run(self.store.dir, "fix-the-widget")   # nothing live any more

    def test_a_missing_claude_binary_is_a_clear_error_and_changes_nothing(self):
        with mock.patch.dict(os.environ, {"AGENTBOARD_CLAUDE": ""}), mock.patch("shutil.which", return_value=None):
            with self.assertRaises(BoardError):
                self.run_it()
        self.assertEqual(self.card()["status"], "todo")

    # -- refusing --------------------------------------------------------------------------------------------------------------
    def test_it_refuses_a_done_card_a_claimed_card_a_subtask_and_a_second_live_run(self):
        self.store.claim("fix-the-widget", "alice")
        with self.assertRaises(BoardError):
            self.run_it(name="RUN-1")                            # held by alice
        self.assertEqual(self.card()["agent"], "alice")
        self.store.update("fix-the-widget", status="done")
        with self.assertRaises(BoardError):
            self.run_it(name="alice")
        self.store.add("Other", status="todo")
        self.store.claim("other", "bob")
        self.store.add("Child", parent_id="other")
        with self.assertRaises(BoardError):
            runs.run_card(self.store, "child", cwd=str(self.work), log=lambda *_: None)
        d = runs.runs_dir(self.store.dir) / "fix-the-widget" / "x"
        d.mkdir(parents=True)
        runs.write_run(d, {"card": "fix-the-widget", "id": "x", "status": "running", "supervisor_pid": os.getpid(), "started": "2026-01-01T00:00:00"})
        self.store.add("Third", status="todo")
        with self.assertRaises(BoardError):
            runs.check_startable(self.store, "fix-the-widget", "alice")   # (done is checked first) ...
        self.store.update("fix-the-widget", status="doing")
        with self.assertRaises(BoardError):
            runs.check_startable(self.store, "fix-the-widget", "alice")   # ... and a live run is refused

    def test_a_run_whose_supervisor_died_is_listed_as_lost(self):
        d = runs.runs_dir(self.store.dir) / "fix-the-widget" / "old"
        d.mkdir(parents=True)
        runs.write_run(d, {"card": "fix-the-widget", "id": "old", "name": "x", "status": "running", "supervisor_pid": 99999999, "started": "2026-01-01T00:00:00"})
        self.assertEqual(runs.all_runs(self.store.dir)[0][1]["status"], "lost")
        self.assertIsNone(runs.live_run(self.store.dir, "fix-the-widget"))
        self.assertTrue(runs.list_lines(self.store.dir))


class ServerTests(Base):
    def setUp(self):
        super().setUp()
        import socket
        from http.server import ThreadingHTTPServer

        from agentboard import server
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
            self.port = sk.getsockname()[1]
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), server.make_handler(self.store, self.port))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def call(self, path, body=None):
        import urllib.request
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"}, method="POST" if body is not None else "GET")
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())

    def test_the_board_sees_a_live_run_and_a_dead_supervisor_is_not_shown_as_live(self):
        self.store.claim("fix-the-widget", "RUN-1")
        self.store.set_run("fix-the-widget", {"status": "running", "supervisor_pid": os.getpid()})
        task = self.call("/api/tasks")["tasks"][0]
        self.assertTrue(task["run"]["alive"])
        self.store.set_run("fix-the-widget", {"supervisor_pid": 99999999})
        self.assertFalse(self.call("/api/tasks")["tasks"][0]["run"]["alive"])

    def test_the_stop_button_endpoint_is_the_kill_switch(self):
        os.environ["FAKE_MODE"] = "sleep"
        out = {}
        with mock.patch.object(runs, "KILL_GRACE_S", 1):
            th = threading.Thread(target=lambda: out.update(rec=runs.run_card(self.store, "fix-the-widget", name="RUN-1", cwd=str(self.work), minutes=5, log=lambda *_: None)))
            th.start()
            for _ in range(100):
                live = runs.live_run(self.store.dir, "fix-the-widget")
                if live and live[1].get("pid"):
                    break
                time.sleep(0.1)
            self.assertIn("asked run", self.call("/api/run-kill", {"id": "fix-the-widget"})["result"])
            th.join(timeout=20)
        self.assertEqual(out["rec"]["status"], "killed")


class WorktreeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=self.repo, check=True, capture_output=True)
        git("init", "-q")
        (self.repo / "a.txt").write_text("a")
        git("add", ".")
        git("commit", "-qm", "init")
        self.store = Store(self.root / "board" / ".agentboard")
        self.store.add("Fix the widget", status="todo")
        fake = self.root / "claude"
        fake.write_text(FAKE.format(py=sys.executable))
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        env = {"AGENTBOARD_CLAUDE": str(fake), "FAKE_RECORD": str(self.root / "rec.json"), "FAKE_MODE": "ok", "FAKE_CARD": "fix-the-widget"}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def _run(self):
        old = os.getcwd()
        os.chdir(self.repo)
        try:
            return runs.run_card(self.store, "fix-the-widget", minutes=1, log=lambda *_: None)
        finally:
            os.chdir(old)

    def worktrees(self):
        return subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=self.repo, capture_output=True, text=True).stdout.count("worktree ")

    def test_a_run_from_a_main_checkout_gets_its_own_worktree_and_a_clean_one_is_removed(self):
        rec = self._run()
        self.assertTrue(rec["worktree"]["created"])
        self.assertEqual(json.loads((self.root / "rec.json").read_text())["cwd"], rec["worktree"]["path"])
        self.assertNotEqual(rec["worktree"]["path"], str(self.repo))
        self.assertEqual(rec["worktree_cleanup"], "removed")
        self.assertFalse(Path(rec["worktree"]["path"]).exists())
        self.assertEqual(self.worktrees(), 1)
        self.assertEqual(subprocess.run(["git", "branch", "--list", "run/*"], cwd=self.repo, capture_output=True, text=True).stdout.strip(), "")

    def test_a_worktree_with_leftovers_is_kept_and_the_card_says_where(self):
        os.environ["FAKE_MODE"] = "touch"
        rec = self._run()
        self.assertTrue(rec["worktree_cleanup"].startswith("kept: uncommitted"))
        self.assertTrue(Path(rec["worktree"]["path"], "left-behind.txt").exists())
        self.assertIn(rec["worktree"]["path"], Store.get(self.store.load(), "fix-the-widget")["body_md"])
        self.assertEqual(self.worktrees(), 2)

    def test_a_worktree_with_commits_is_kept(self):
        os.environ["FAKE_MODE"] = "commit"
        rec = self._run()
        self.assertTrue(rec["worktree_cleanup"].startswith("kept: 1 commit"))
        self.assertEqual(self.worktrees(), 2)

    def test_an_explicit_cwd_is_used_as_it_is_and_never_removed(self):
        rec = runs.run_card(self.store, "fix-the-widget", cwd=str(self.repo), minutes=1, log=lambda *_: None)
        self.assertFalse(rec["worktree"]["created"])
        self.assertEqual(rec["worktree_cleanup"], "")
        self.assertEqual(self.worktrees(), 1)


class CliTests(Base):
    """`agentboard run` and `agentboard runs` through the real command line, with the fake claude."""

    def cli(self, *args):
        env = {**os.environ, "AGENTBOARD_DIR": str(self.store.dir)}
        return subprocess.run([sys.executable, "-m", "agentboard", *args], capture_output=True, text=True, env=env, cwd=self.work)

    def test_run_then_runs_lists_it(self):
        p = self.cli("run", "fix-the-widget", "--name", "RUN-2", "--cwd", str(self.work), "--max-minutes", "1", "--budget", "1")
        self.assertEqual(p.returncode, 0, p.stderr)
        listing = self.cli("runs").stdout
        self.assertIn("fix-the-widget", listing)
        self.assertIn("finished", listing)
        self.assertIn("$0.12", listing)

    def test_a_failed_run_exits_nonzero(self):
        os.environ["FAKE_MODE"] = "fail"
        p = self.cli("run", "fix-the-widget", "--cwd", str(self.work), "--max-minutes", "1")
        self.assertEqual(p.returncode, 1)

    def test_detach_returns_at_once_and_the_run_finishes_by_itself(self):
        t0 = time.time()
        p = self.cli("run", "fix-the-widget", "--cwd", str(self.work), "--max-minutes", "1", "--detach")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("run started in the background", p.stdout)
        for _ in range(100):
            c = self.card()
            if c.get("run", {}).get("status") == "finished":
                break
            time.sleep(0.2)
        self.assertEqual(self.card()["run"]["status"], "finished")
        self.assertLess(time.time() - t0, 30)


if __name__ == "__main__":
    unittest.main()
