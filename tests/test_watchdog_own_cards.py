"""`watchdog --fix` is the owner's and ORCH's for other agents' cards; an agent fixes only its own (night sweep, card sweep-func-cli).
The agent protocol says "never run --fix on another agent's claim", but nothing enforced it: on a scratch board a session with no cards of its own handed AG-8's
subtasks to another agent, merged twin cards and (with `--fix all`) would release every stuck card on the board. The fix is allowed when the finding is about the
caller's own card, or nobody's; ORCH, the owner and a terminal with no session name may fix any. A refusal changes nothing, not even the fixes that were allowed."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli
from agentboard.store import Store


class OwnCards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        for keeper in ("p1", "p2", "p3", "p4", "p5"):   # five pairs of twins held by AG-1: a card and the `-2` made by a second start of the same work
            for tid in (keeper, f"{keeper}-2"):
                self.s.add(f"Work {keeper}", status="todo", task_id=tid)
                self.s.claim(tid, "AG-1")
        for tid in ("q1", "q1-2"):   # one pair held by AG-2
            self.s.add("Work q1", status="todo", task_id=tid)
            self.s.claim(tid, "AG-2")

    def run_cli(self, name, *argv):
        out, err = io.StringIO(), io.StringIO()
        env = {"AGENTBOARD_DIR": str(self.s.dir)}
        if name:
            env["AGENTBOARD_NAME"] = name
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            if not name:
                os.environ.pop("AGENTBOARD_NAME", None)
            try:
                cli.main(["watchdog", "--stale-minutes", "100000", *argv])
                code = 0
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
                if isinstance(e.code, str):
                    err.write(e.code)
        return code, out.getvalue(), err.getvalue()

    def findings(self):
        return json.loads(self.run_cli("", "--json")[1])

    def number(self, agent, kind="twins", nth=0):
        hits = [n for n, f in enumerate(self.findings(), 1) if f["kind"] == kind and f["agent"] == agent]
        if len(hits) <= nth:
            self.fail(f"no {kind} finding #{nth} for {agent}: {self.findings()}")
        return hits[nth]

    def ids(self):
        return sorted(t["id"] for t in self.s.load())


class Tests(OwnCards):
    def test_the_setup_has_twin_findings_for_both_agents(self):
        self.assertTrue(self.number("AG-1"))
        self.assertTrue(self.number("AG-2"))

    def test_an_agent_cannot_fix_a_finding_about_another_agents_card(self):
        n = self.number("AG-1")
        before = self.ids()
        code, _, err = self.run_cli("AG-2", "--fix", str(n))
        self.assertNotEqual(code, 0)
        self.assertIn("AG-1", err)
        self.assertIn("ORCH", err)
        self.assertEqual(self.ids(), before)

    def test_fix_all_by_an_agent_is_refused_whole_when_one_finding_is_not_its_own(self):
        before = self.ids()
        code, _, err = self.run_cli("AG-2", "--fix", "all")
        self.assertNotEqual(code, 0)
        self.assertEqual(self.ids(), before)   # nothing of its own was fixed either: all or nothing

    def test_an_agent_fixes_its_own_finding(self):
        n = self.number("AG-2")
        code, out, _ = self.run_cli("AG-2", "--fix", str(n))
        self.assertEqual(code, 0)
        self.assertIn("done", out)
        self.assertNotIn("q1-2", self.ids())
        self.assertIn("p1-2", self.ids())   # AG-1's twins were not touched

    def test_orch_the_owner_and_a_terminal_with_no_name_fix_anyones(self):
        for i, name in enumerate(("ORCH", "orch", self.s.owner, "")):
            n = self.number("AG-1")
            self.assertEqual(self.run_cli(name, "--fix", str(n))[0], 0, name)
            self.assertEqual(len([x for x in self.ids() if x.endswith("-2") and x.startswith("p")]), 4 - i)

    def test_reading_the_list_is_open_to_every_agent(self):
        code, out, _ = self.run_cli("AG-3")
        self.assertEqual(code, 0)
        self.assertIn("twins", out)

if __name__ == "__main__":
    unittest.main()
