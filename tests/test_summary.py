"""Done summary: the window, grouping by project and day, the one-line result, the text and HTML renderings, the route and the CLI."""
import contextlib
import io
import json
import os
import tempfile
import unittest
import urllib.request
from datetime import date, datetime
from pathlib import Path
from unittest import mock

from agentboard import cli, summary
from agentboard.store import BoardError, Store

from tests.test_reports import HttpTests as ReportsHttp

TODAY = date(2026, 10, 28)


def task(tid, title, done_on, agent="AGENT-1", project="p1", result="", color="green", parent=None):
    t = {"id": tid, "title": title, "status": "done", "progress": 100, "agent": agent, "color": color, "result": result,
         "created": f"{done_on}T09:00:00", "updated": f"{done_on}T10:00:00",
         "log": [{"at": f"{done_on}T10:00:00", "status": "done", "progress": 100, "text": "Marked done"}]}
    if project:
        t["project_id"] = project
    if parent:
        t["parent_id"] = parent
    return t


PROJECTS = [{"id": "p1", "name": "Pakled"}, {"id": "p2", "name": "Tangen"}]
TASKS = [
    task("a", "Fix the relay", "2026-10-28", result="ACTION Troy: reinstall. STATUS a done-ready, pushed. WHY nothing."),
    task("b", "Red team", "2026-10-27", agent="AGENT-2", color="blue", result="Pushed; 12 tests pass. More words here."),
    task("c", "Old card", "2026-10-01"),
    task("d", "Tangen books", "2026-10-28", project="p2", agent="AGENT-1", result="Troy: try ./tb add"),
    task("e", "A subtask", "2026-10-28", parent="a"),
    task("f", "No project", "2026-10-27", project=None, agent="GENERAL", color="#123456"),
    {"id": "g", "title": "Still doing", "status": "doing", "progress": 40, "agent": "AGENT-1", "created": "2026-10-28T09:00:00", "updated": "2026-10-28T09:30:00", "log": []},
]


class Collect(unittest.TestCase):
    def test_window(self):
        self.assertEqual(summary.parse_since("1d", TODAY), TODAY)
        self.assertEqual(summary.parse_since("7d", TODAY), date(2026, 10, 22))
        self.assertIsNone(summary.parse_since("all", TODAY))
        for bad in ("0d", "x", "7"):
            with self.assertRaises(BoardError):
                summary.parse_since(bad, TODAY)

    def test_groups_by_project_and_day_and_skips_subtasks_and_open_cards(self):
        d = summary.collect(TASKS, PROJECTS, "7d", today=TODAY)
        self.assertEqual(d["total"], 4)
        self.assertEqual([p["name"] for p in d["projects"]], ["Pakled", "No project", "Tangen"])
        pak = d["projects"][0]
        self.assertEqual(sorted(pak["days"]), [date(2026, 10, 27), TODAY])
        self.assertEqual([c["id"] for c in pak["days"][TODAY]], ["a"])
        self.assertEqual(d["per_day"][TODAY], {"AGENT-1": 2})
        self.assertEqual(set(d["agents"]), {"AGENT-1", "AGENT-2", "GENERAL"})
        self.assertEqual(len(d["days"]), 7)

    def test_all_and_project_filter(self):
        self.assertEqual(summary.collect(TASKS, PROJECTS, "all", today=TODAY)["total"], 5)
        d = summary.collect(TASKS, PROJECTS, "7d", project="p2", today=TODAY)
        self.assertEqual([p["id"] for p in d["projects"]], ["p2"])
        with self.assertRaises(BoardError):
            summary.collect(TASKS, PROJECTS, "7d", project="nope", today=TODAY)

    def test_one_line_prefers_status_and_first_sentence(self):
        self.assertEqual(summary.one_line("ACTION Troy: reinstall. STATUS a done-ready, pushed. WHY nothing."), "pushed.")
        self.assertEqual(summary.one_line("Pushed; 12 tests pass. More words here."), "Pushed; 12 tests pass.")
        self.assertEqual(summary.one_line("ACTION none. Troy: try ./tb add"), "try ./tb add")
        self.assertEqual(summary.one_line(""), "")
        self.assertTrue(summary.one_line("x" * 400).endswith("…"))

    def test_agent_colours_stay_distinct(self):
        d = summary.collect(TASKS, PROJECTS, "7d", today=TODAY)
        cols = [a["color"] for a in d["agents"].values()]
        self.assertEqual(len(cols), len(set(cols)))
        self.assertEqual(d["agents"]["GENERAL"]["color"], "#123456")

    def test_text_and_html(self):
        d = summary.collect(TASKS, PROJECTS, "7d", today=TODAY)
        d["project"] = ""
        txt = summary.to_text(d)
        self.assertIn("# Done: 22 Oct to 28 Oct", txt)
        self.assertIn("**4 cards** finished across 3 projects by 3 agents.", txt)
        self.assertIn("- Fix the relay: pushed. (AGENT-1)", txt)
        self.assertNotIn("Old card", txt)
        page = summary.build_html(d, "/b/x")
        for s in ("Done summary", "Fix the relay", "Closed per day", "By agent", 'id="copy"', 'id="save"', '/b/x/summary?since=30d', 'data-theme'):
            self.assertIn(s, page)
        self.assertIn("Nothing finished", summary.build_html({**summary.collect([], [], "1d", today=TODAY), "project": ""}))

    def test_everything_the_agent_wrote_is_escaped(self):
        bad = task("z", "<b>t</b>", "2026-10-28", result="<script>alert(1)</script>")
        d = summary.collect([bad], [], "1d", today=TODAY)
        page = summary.build_html({**d, "project": ""})
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;", page)

    def test_more_fold_past_six_cards_a_day(self):
        many = [task(f"m{i}", f"Card {i}", "2026-10-28") for i in range(9)]
        page = summary.build_html({**summary.collect(many, [], "1d", today=TODAY), "project": ""})
        self.assertIn("<summary>3 more</summary>", page)
        txt = summary.to_text(summary.collect([task(f"m{i}", f"Card {i}", "2026-10-28") for i in range(15)], [], "1d", today=TODAY))
        self.assertIn("...and 3 more.", txt)


class RouteAndCli(ReportsHttp):
    """Only the two tests below run here: the inherited report tests are hidden so they do not run twice."""
    def setUp(self):
        super().setUp()
        tid = self.s.start("Fix the relay", "AGENT-1", color="green")["id"]
        self.s.review(tid, "Pushed; done.")
        self.s.move(tid, "done")

    def test_route(self):
        page = self.get("/summary?since=7d")[1].decode()
        self.assertIn("Fix the relay", page)
        self.assertIn("Pushed; done.", page)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.get("/summary?since=bad")
        self.assertEqual(cm.exception.code, 400)

    def test_cli_text_and_html(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["summary", "--since", "1d"])
        self.assertIn("- Fix the relay: Pushed; done. (AGENT-1)", out.getvalue())
        path = self.root / "s.html"
        with contextlib.redirect_stdout(io.StringIO()):
            cli.main(["summary", "--html", str(path)])
        self.assertIn("Done summary", path.read_text())


for _n in [n for n in dir(ReportsHttp) if n.startswith("test_")]:
    setattr(RouteAndCli, _n, None)


if __name__ == "__main__":
    unittest.main()
