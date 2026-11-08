"""The agent protocol's watchdog (overnight-rel-agent-protocol): each way a board gets stuck between agents is found, named, and put
right by its one fix. A throwaway board; nothing reaches a real one."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from agentboard import cli, doctor, hooks, listeners, server, watchdog
from agentboard.store import BoardError, Store

from tests.test_reports import HttpTests as _Http

NOW = datetime.now().replace(microsecond=0)            # the CLI and the chat stamps use the real clock, so the tests do too
OLD = (NOW - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S")


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

    def age(self, *ids, at=OLD):
        """Backdate cards (and their last history line) so they read as idle for three hours."""
        with self.s.transaction() as tasks:
            for t in tasks:
                if t["id"] in ids:
                    t["updated"] = at
                    if t.get("log"):
                        t["log"][-1]["at"] = at

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(list(argv))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def kinds(self, **kw):
        return [(f["kind"], f["id"] or f["agent"]) for f in watchdog.findings(self.s, now=NOW, **kw)]


class CleanBoard(Base):
    def test_a_healthy_board_has_no_finding(self):
        self.s.start("Harden retries", "AGENT-1", None)
        self.s.add("step", parent_id="harden-retries")
        hooks.remember_session(self.s.dir, "AGENT-1", session_id="s1")
        listeners.register(self.s.dir, "AGENT-1", "inbox")
        self.assertEqual(self.kinds(), [])
        code, out, err = self.run_cli("watchdog")
        self.assertIn("ok  no stuck claim", out)
        listeners.unregister(self.s.dir, "AGENT-1")


class StuckAndVanished(Base):
    def test_a_stale_claim_and_a_stuck_card_are_released_to_todo_with_their_history(self):
        self.s.add("Queued work", task_id="queued")
        self.s.claim("queued", "AGENT-2")                                  # claimed, never worked
        self.s.start("Export pipeline", "AGENT-3", None)
        self.s.update("export-pipeline", 40, "half way")                    # worked, then silence
        hooks.remember_session(self.s.dir, "AGENT-2", session_id="s2")
        hooks.remember_session(self.s.dir, "AGENT-3", session_id="s3")
        self.age("queued", "export-pipeline")
        found = watchdog.findings(self.s, now=NOW)
        kinds = {f["kind"]: f for f in found}
        self.assertEqual(kinds["claimed-idle"]["id"], "queued")
        self.assertEqual(kinds["stuck"]["id"], "export-pipeline")
        self.assertEqual({f["agent"] for f in found if f["kind"] == "vanished"}, {"AGENT-2", "AGENT-3"})   # both: no wait, no update, no chat
        self.assertEqual(kinds["stuck"]["fix"], {"action": "release", "id": "export-pipeline", "label": "Release to Todo"})
        touched = watchdog.heal(self.s, "release", "export-pipeline")
        t = self.s.get(self.s.load(), "export-pipeline")
        self.assertEqual((touched, t["status"], t.get("agent")), (["export-pipeline"], "todo", None))
        self.assertIn("Released to Todo: AGENT-3 had no wait running", t["log"][-1]["text"])
        self.assertEqual(t["log"][-1]["by"], f"the watchdog, for {self.s.owner}")
        self.assertEqual(t["log"][0]["text"], "Started by AGENT-3")                        # the history stays
        with self.assertRaises(BoardError):
            watchdog.heal(self.s, "release", "export-pipeline")                             # not in Doing any more

    def test_a_listening_holder_is_not_vanished_and_a_chatting_one_is_not_either(self):
        self.s.start("Export pipeline", "AGENT-3", None)
        self.s.start("Second", "AGENT-4", None)
        hooks.remember_session(self.s.dir, "AGENT-3", session_id="s3")
        hooks.remember_session(self.s.dir, "AGENT-4", session_id="s4")
        self.age("export-pipeline", "second")
        listeners.register(self.s.dir, "AGENT-3", "inbox")                  # waiting: a line wakes it
        self.s.chat_send("AGENT-4", "still here, reading")                  # spoke just now
        kinds = self.kinds()
        self.assertNotIn(("vanished", "AGENT-3"), kinds)
        self.assertNotIn(("stuck", "export-pipeline"), kinds)               # listening: the HUD's stale row covers it
        self.assertNotIn(("vanished", "AGENT-4"), kinds)
        listeners.unregister(self.s.dir, "AGENT-3")

    def test_release_all_takes_every_card_of_a_vanished_agent_and_its_open_subtasks(self):
        self.s.start("A", "AGENT-5", None)
        self.s.add("a step", parent_id="a")
        self.s.start("B", "AGENT-5", None)
        self.s.start("C", "AGENT-6", None)
        hooks.remember_session(self.s.dir, "AGENT-5", session_id="s5")
        self.age("a", "a-step", "b", "c")
        van = [f for f in watchdog.findings(self.s, now=NOW) if f["kind"] == "vanished" and f["agent"] == "AGENT-5"][0]
        self.assertEqual(van["fix"], {"action": "release-all", "id": "AGENT-5", "label": "Release AGENT-5's cards to Todo"})
        self.assertIn("holds 2 Doing cards", van["what"])
        self.assertEqual(sorted(watchdog.heal(self.s, "release-all", "AGENT-5")), ["a", "b"])
        by = {t["id"]: t for t in self.s.load()}
        self.assertEqual([(by[i]["status"], by[i].get("agent")) for i in ("a", "a-step", "b")], [("todo", None)] * 3)
        self.assertEqual((by["c"]["status"], by["c"]["agent"]), ("doing", "AGENT-6"))   # another agent's card is not touched
        self.assertEqual([f["kind"] for f in watchdog.findings(self.s, now=NOW) if f["agent"] == "AGENT-6"], ["vanished", "stuck", "no-session"])

    def test_a_card_waiting_on_the_owner_is_never_stuck(self):
        self.s.start("Asked", "AGENT-7", None)
        self.s.ask("asked", "which colour?")
        self.s.start("Reviewed", "AGENT-7", None)
        self.s.review("reviewed", "done")
        hooks.remember_session(self.s.dir, "AGENT-7", session_id="s7")
        self.age("asked", "reviewed")
        self.assertEqual(self.kinds(), [])


class Shapes(Base):
    def test_twins_are_merged_into_the_keeper(self):
        self.s.start("Harden retries", "AGENT-1", None)
        self.s.start("Harden retries", "AGENT-1", None, task_id="harden-retries-2")   # what an older start made
        hooks.remember_session(self.s.dir, "AGENT-1", session_id="s1")
        listeners.register(self.s.dir, "AGENT-1", "inbox")
        f = [f for f in watchdog.findings(self.s, now=NOW) if f["kind"] == "twins"]
        self.assertEqual((f[0]["id"], f[0]["fix"]["action"], f[0]["fix"]["label"]), ("harden-retries-2", "merge", "Merge into harden-retries"))
        self.assertEqual(watchdog.heal(self.s, "merge", "harden-retries-2"), ["harden-retries", "harden-retries-2"])
        ids = [t["id"] for t in self.s.load()]
        self.assertEqual(ids, ["harden-retries"])
        self.assertIn("Merged harden-retries-2 into this card", self.s.load()[0]["log"][-1]["text"])
        self.assertTrue(any("before-watchdog-merge" in Path(b).name for b in self.s.backups.snapshots()))   # a named snapshot first
        listeners.unregister(self.s.dir, "AGENT-1")

    def test_a_split_card_hands_its_subtasks_to_the_holder(self):
        self.s.start("Export pipeline", "AGENT-3", None)
        self.s.add("step one", parent_id="export-pipeline", task_id="s1")
        self.s.add("step two", parent_id="export-pipeline", task_id="s2")
        self.s.claim("s1", "AGENT-9", force=True)                           # a second agent took a subtask (--force, as it would have to)
        self.s.update("s2", 100, "done already")
        hooks.remember_session(self.s.dir, "AGENT-3", session_id="s3")
        listeners.register(self.s.dir, "AGENT-3", "inbox")
        f = [f for f in watchdog.findings(self.s, now=NOW) if f["kind"] == "split-card"][0]
        self.assertEqual((f["id"], f["fix"]), ("export-pipeline", {"action": "hand", "id": "export-pipeline", "label": "Hand the subtasks to AGENT-3"}))
        self.assertIn("AGENT-9 holds open subtasks", f["what"])
        self.assertEqual(watchdog.heal(self.s, "hand", "export-pipeline"), ["s1"])
        self.assertEqual(self.s.get(self.s.load(), "s1")["agent"], "AGENT-3")
        self.assertEqual([x["kind"] for x in watchdog.findings(self.s, now=NOW) if x["kind"] == "split-card"], [])
        listeners.unregister(self.s.dir, "AGENT-3")

    def test_an_orphan_becomes_a_card_of_its_own_and_a_subtask_ahead_follows_its_parent(self):
        self.s.start("Parent", "AGENT-3", None)
        self.s.add("lonely", parent_id="parent", task_id="lonely")
        self.s.add("eager", parent_id="parent", task_id="eager")
        with self.s.transaction() as tasks:
            tasks[:] = [t for t in tasks if t["id"] != "parent"] + [dict(next(t for t in tasks if t["id"] == "parent"), id="parent-kept")]
            for t in tasks:
                if t["id"] == "eager":
                    t["parent_id"], t["status"] = "parent-kept", "doing"
                if t["id"] == "parent-kept":
                    t["status"] = "todo"
        hooks.remember_session(self.s.dir, "AGENT-3", session_id="s3")
        found = {f["kind"]: f for f in watchdog.findings(self.s, now=NOW)}
        self.assertEqual(found["orphan"]["fix"], {"action": "adopt", "id": "lonely", "label": "Make it a card of its own"})
        self.assertEqual(found["subtask-ahead"]["fix"], {"action": "follow", "id": "eager", "label": "Follow the parent to Todo"})
        watchdog.heal(self.s, "adopt", "lonely")
        watchdog.heal(self.s, "follow", "eager")
        by = {t["id"]: t for t in self.s.load()}
        self.assertNotIn("parent_id", by["lonely"])
        self.assertEqual(by["eager"]["status"], "todo")
        self.assertEqual([f["kind"] for f in watchdog.findings(self.s, now=NOW) if f["kind"] in ("orphan", "subtask-ahead")], [])

    def test_two_sessions_and_a_session_the_hooks_cannot_reach_are_said_not_fixed(self):
        self.s.start("Export pipeline", "AGENT-3", None)
        listeners.register(self.s.dir, "AGENT-1", "inbox", pid=1)
        listeners.register(self.s.dir, "agent-1", "inbox")
        found = {f["kind"]: f for f in watchdog.findings(self.s, now=NOW)}
        self.assertEqual((found["two-sessions"]["agent"], found["two-sessions"]["fix"]), ("AGENT-1", None))
        self.assertIn("rename one with /rename", found["two-sessions"]["what"])
        self.assertEqual((found["no-session"]["agent"], found["no-session"]["fix"]), ("AGENT-3", None))
        self.assertIn("agentboard me --name AGENT-3", found["no-session"]["what"])
        hooks.remember_session(self.s.dir, "AGENT-3", session_id="s3")
        self.assertNotIn("no-session", {f["kind"] for f in watchdog.findings(self.s, now=NOW)})
        listeners.unregister(self.s.dir, "AGENT-1", pid=1)
        listeners.unregister(self.s.dir, "AGENT-1")


class TheCli(Base):
    def test_watchdog_lists_numbered_findings_and_fix_n_does_one(self):
        self.s.add("Queued work", task_id="queued")
        self.s.claim("queued", "AGENT-2")
        hooks.remember_session(self.s.dir, "AGENT-2", session_id="s2")
        self.age("queued")
        code, out, err = self.run_cli("watchdog", "--stale-minutes", "60")
        self.assertIn(" 1. vanished      AGENT-2", out)
        self.assertIn(" 2. claimed-idle  queued", out)
        self.assertIn("fix: Release to Todo  (agentboard watchdog --fix 2)", out)
        code, out, err = self.run_cli("watchdog", "--stale-minutes", "60", "--json")
        self.assertEqual(json.loads(out)[1]["fix"]["action"], "release")
        code, out, err = self.run_cli("watchdog", "--stale-minutes", "60", "--fix", "2")
        self.assertIn("2. Release to Todo: done (queued)", out)
        self.assertEqual(self.s.get(self.s.load(), "queued")["status"], "todo")
        code, out, err = self.run_cli("watchdog", "--stale-minutes", "60")
        self.assertIn("ok  no stuck claim", out)
        code, out, err = self.run_cli("watchdog", "--fix", "9")
        self.assertIn("ok", out)   # nothing to fix: the list is empty, --fix 9 is not reached

    def test_fix_all_finishes_when_a_vanished_agents_release_covered_its_stuck_rows_and_a_bad_fix_is_refused(self):
        self.s.start("A", "AGENT-5", None)
        self.s.start("B", "AGENT-5", None)
        self.s.update("b", 30, "some work")
        hooks.remember_session(self.s.dir, "AGENT-5", session_id="s5")
        self.age("a", "b")
        code, out, err = self.run_cli("watchdog", "--stale-minutes", "60", "--fix", "all")
        self.assertIsNone(code, str(code))                                  # the run ends well
        self.assertIn("Release AGENT-5's cards to Todo: done (a, b)", out)
        self.assertEqual(out.count("already done"), 2)                     # the stuck and claimed-idle rows were covered by the release-all
        self.assertEqual([t["status"] for t in self.s.load()], ["todo", "todo"])
        code, out, err = self.run_cli("watchdog", "--fix", "abc")
        self.assertIn("--fix takes finding numbers (1, or 1,3) or all; not 'abc'", str(code))


class TheHudAndTheDoctor(Base):
    def test_doctor_warns_with_the_counts_and_passes_when_clean(self):
        self.s.add("Queued work", task_id="queued")
        self.s.claim("queued", "AGENT-2")
        self.age("queued")
        lines = {r[1]: r for r in doctor.check_watchdog(self.s.dir)}
        self.assertEqual(lines["watchdog"][0], doctor.WARN)
        self.assertIn("1 vanished, 1 claimed-idle, 1 no-session: run `agentboard watchdog`", lines["watchdog"][2])
        watchdog.heal(self.s, "release", "queued")
        hooks.remember_session(self.s.dir, "AGENT-2", session_id="s2")
        self.assertEqual(doctor.check_watchdog(self.s.dir)[0][0], doctor.PASS)
        self.assertEqual(doctor.check_watchdog(Path(self.tmp.name) / "nowhere")[0][0], doctor.INFO)

    def test_the_page_has_the_strip_and_the_one_click_fix(self):
        page = (Path(server.__file__).parent / "static" / "index.html").read_text()
        for needle in ('<div class="h-dog" id="h-dog" hidden aria-label="Stuck between agents"></div>', "function dogRender(items)", "dogRender(d.watchdog);",
                       "data-dog-action=\"${hh(f.fix.action)}\" data-dog-id=\"${hh(f.fix.id)}\"", "api('/api/watchdog-fix', { action: b.dataset.dogAction, id: b.dataset.dogId })",
                       ".h-dog { flex: none;"):
            self.assertIn(needle, page)


class OverHttp(_Http):
    def test_the_hud_carries_the_findings_and_one_post_does_the_fix(self):
        self.s.add("Queued work", task_id="queued")
        self.s.claim("queued", "AGENT-2")
        old = (datetime.now() - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S")
        with self.s.transaction() as tasks:
            for t in tasks:
                if t["id"] == "queued":
                    t["updated"] = old
                    t["log"][-1]["at"] = old
        d = json.loads(self.get("/api/hud")[1])
        kinds = [f["kind"] for f in d["watchdog"]]
        self.assertIn("claimed-idle", kinds)
        fix = next(f["fix"] for f in d["watchdog"] if f["kind"] == "claimed-idle")
        r = self.post("/api/watchdog-fix", fix)
        self.assertEqual(r, {"touched": ["queued"]})
        self.assertEqual(self.s.get(self.s.load(), "queued")["status"], "todo")
        d = json.loads(self.get("/api/hud")[1])
        self.assertNotIn("claimed-idle", [f["kind"] for f in d["watchdog"]])


class TheBoardPageAndThePrompts(Base):
    """overnight-rel-agent-protocol-2: the same strip under the Board's Doing header, fed by /api/tasks; ORCH's prompt and the agent
    instructions name the command."""

    def test_the_board_page_builds_the_strip_from_the_tasks_feed(self):
        page = (Path(server.__file__).parent / "static" / "index.html").read_text()
        for needle in ("boardDog = j.watchdog || [];", "const dog = k === 'doing' && !BYAGENT ? dogHtml(boardDog) : '';", "function dogHtml(items)",
                       '<div class="h-dog board-dog" aria-label="Stuck between agents">', ".col .board-dog {", "dogKey = ''; raw = '';"):
            self.assertIn(needle, page)

    def test_orch_and_the_instructions_name_the_watchdog(self):
        from agentboard import prompt
        self.assertIn("watchdog                                           # a card looks stuck?", prompt.ORCH_TEMPLATE)
        self.assertIn("`agentboard watchdog` lists every such case with its one fix", cli.INSTRUCTIONS)
        self.assertIn("Never `--force` past another agent's claim", cli.INSTRUCTIONS)
        code, out, err = self.run_cli("instructions")
        self.assertIn("agentboard watchdog", out)


class TasksFeed(_Http):
    def test_api_tasks_carries_the_findings_only_when_there_are_some(self):
        d = json.loads(self.get("/api/tasks")[1])
        self.assertNotIn("watchdog", d)
        self.s.add("Queued work", task_id="queued")
        self.s.claim("queued", "AGENT-2")
        old = (datetime.now() - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S")
        with self.s.transaction() as tasks:
            for t in tasks:
                if t["id"] == "queued":
                    t["updated"] = old
                    t["log"][-1]["at"] = old
        d = json.loads(self.get("/api/tasks")[1])
        self.assertIn("claimed-idle", [f["kind"] for f in d["watchdog"]])
