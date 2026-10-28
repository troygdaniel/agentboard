"""Done summary: the window, the kinds of change, the work areas, the one-line outcome, the text, Mermaid and HTML renderings, the route and the CLI."""
import contextlib
import io
import unittest
import urllib.request
from datetime import date

from agentboard import cli, summary
from agentboard.store import BoardError

from tests.test_reports import HttpTests as ReportsHttp

TODAY = date(2026, 10, 28)


def task(tid, title, done_on, agent="AGENT-1", project="p1", result="", description="", parent=None, report=None):
    t = {"id": tid, "title": title, "status": "done", "progress": 100, "agent": agent, "color": "green", "result": result, "description": description,
         "created": f"{done_on}T09:00:00", "updated": f"{done_on}T10:00:00",
         "log": [{"at": f"{done_on}T09:30:00", "status": "doing", "progress": 50, "text": "halfway"}, {"at": f"{done_on}T10:00:00", "status": "done", "progress": 100, "text": "Marked done"}]}
    if project:
        t["project_id"] = project
    if parent:
        t["parent_id"] = parent
    if report:
        t["report"] = {"file": report, "state": "done"}
    return t


PROJECTS = [{"id": "p1", "name": "Pakled"}, {"id": "p2", "name": "Tangen"}]
TASKS = [
    task("a", "Fix the relay", "2026-10-28", result="ACTION Troy: reinstall. STATUS a done-ready, pushed. WHY nothing.", report="a-1.html"),
    task("b", "Add a relay health check", "2026-10-27", agent="AGENT-2", result="Pushed; 12 tests pass. More words here.", description="(your worktree), relay slice. Make the relay report its own health every minute."),
    task("c", "Old card", "2026-10-01"),
    task("d", "Tangen books", "2026-10-28", project="p2", result="Troy: try ./tb add", description="Keep the books for Tangen in one file."),
    task("e", "A subtask", "2026-10-28", parent="a"),
    task("f", "No project", "2026-10-27", project=None, agent="GENERAL"),
    task("g", "Relay: the live call screen", "2026-10-26", result="pushed (checked)."),
    {"id": "h", "title": "Still doing", "status": "doing", "progress": 40, "agent": "AGENT-1", "created": "2026-10-28T09:00:00", "updated": "2026-10-28T09:30:00", "log": []},
]


class Collect(unittest.TestCase):
    def test_window(self):
        self.assertEqual(summary.parse_since("1d", TODAY), TODAY)
        self.assertEqual(summary.parse_since("7d", TODAY), date(2026, 10, 22))
        self.assertIsNone(summary.parse_since("all", TODAY))
        for bad in ("0d", "x", "7"):
            with self.assertRaises(BoardError):
                summary.parse_since(bad, TODAY)

    def test_groups_by_project_and_area_and_skips_subtasks_and_open_cards(self):
        d = summary.collect(TASKS, PROJECTS, "7d", today=TODAY)
        self.assertEqual(d["total"], 5)
        self.assertEqual([p["name"] for p in d["projects"]], ["Pakled", "No project", "Tangen"])
        pak = d["projects"][0]
        self.assertEqual([c["id"] for c in pak["cards"]], ["a", "b", "g"])
        self.assertEqual([(th["name"], len(th["cards"])) for th in pak["themes"]], [("Relay", 3)])
        self.assertEqual(d["kinds"], {"Fixed": 1, "Added": 1, "Changed": 3})
        self.assertEqual(d["prev"], 0)       # "Old card" is older than the 7 days before this window
        self.assertEqual(summary.collect(TASKS, PROJECTS, "14d", today=TODAY)["prev"], 1)   # 15 Oct window; 1 Oct is in the 14 days before

    def test_all_and_project_filter(self):
        self.assertEqual(summary.collect(TASKS, PROJECTS, "all", today=TODAY)["total"], 6)
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

    def test_kind_and_asked(self):
        for title, kind in (("Fix the relay", "Fixed"), ("Add a health check", "Added"), ("Rewrite README for clarity", "Documented"),
                            ("Run a QA pass on the board", "Tested"), ("Propose feature ideas", "Explored"), ("A little more warmth", "Improved"), ("The live call screen", "Changed")):
            self.assertEqual(summary.kind_of(title), kind, title)
        self.assertEqual(summary.asked("(your worktree), relay slice. Make the relay report its own health every minute.", "x"), "Make the relay report its own health every minute.")
        self.assertEqual(summary.asked("Fix the relay.", "Fix the relay"), "")
        cards = summary.collect(TASKS, PROJECTS, "7d", today=TODAY)["projects"][0]["cards"]
        self.assertEqual(cards[1]["asked"], "Make the relay report its own health every minute.")

    def test_areas_come_from_shared_title_words(self):
        cards = [{"title": t, "at": TODAY, "kind": "Changed"} for t in ("HUD: lanes", "HUD legend", "Fix the HUD rows", "Chat panel", "Chat tail", "Something else")]
        ths = summary.themes(cards, "agentboard")
        self.assertEqual([(th["name"], len(th["cards"])) for th in ths], [("HUD", 3), ("Chat", 2), ("Other", 1)])
        self.assertEqual([th["name"] for th in summary.themes([{"title": "Call one", "at": TODAY, "kind": "Changed"}, {"title": "Two calls", "at": TODAY, "kind": "Changed"}], "")], ["Call"])

    def test_text_mermaid_and_html(self):
        d = summary.collect(TASKS, PROJECTS, "7d", today=TODAY)
        d["project"] = ""
        txt = summary.to_text(d)
        self.assertIn("# Done: 22 Oct to 28 Oct", txt)
        self.assertIn("**5 cards** finished across 3 projects.", txt)
        self.assertIn("- Fix the relay — pushed.", txt)
        self.assertIn("**Relay**", txt)
        self.assertNotIn("Old card", txt)
        mm = summary.to_mermaid(d)
        self.assertTrue(mm.startswith("mindmap\n  root(("))
        self.assertIn("    Pakled 3\n      Relay 3", mm)
        page = summary.build_html(d, "/b/x")
        for s in ("Done summary", "Fix the relay", "What kind of work", "Where the work went", 'class="map"', 'id="copy"', 'id="copymm"', 'id="save"',
                  "/b/x/summary?since=30d", "data-theme", "/b/x/#a", "/b/x/reports/a-1.html", "<h4>Asked</h4>", "<h4>Timeline</h4>", "halfway"):
            self.assertIn(s, page)
        self.assertIn("Nothing finished", summary.build_html({**summary.collect([], [], "1d", today=TODAY), "project": ""}))

    def test_everything_the_agent_wrote_is_escaped(self):
        bad = task("z", "<b>t</b>", "2026-10-28", result="<script>alert(1)</script>", description="<img onerror=x>")
        d = summary.collect([bad], [], "1d", today=TODAY)
        page = summary.build_html({**d, "project": ""})
        self.assertNotIn("<script>alert", page)
        self.assertNotIn("<img onerror", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn("(", summary.to_mermaid(summary.collect([task("y", "Tangen (books) [x]", "2026-10-28", project="p2")], PROJECTS, "1d", today=TODAY)).split("\n")[2])

    def test_more_fold_past_the_shown_cards(self):
        many = [task(f"m{i}", f"Card {i}", "2026-10-28") for i in range(9)]
        page = summary.build_html({**summary.collect(many, [], "1d", today=TODAY), "project": ""})
        self.assertIn(f"<summary>{9 - summary.OTHER_SHOWN} more</summary>", page)
        txt = summary.to_text(summary.collect([task(f"m{i}", f"Card {i}", "2026-10-28") for i in range(15)], [], "1d", today=TODAY))
        self.assertIn("...and 3 more.", txt)

    def test_squarify_fills_the_rectangle(self):
        r = summary.squarify([("a", 6), ("b", 3), ("c", 1)], 0, 0, 100, 50)
        self.assertEqual(set(r), {"a", "b", "c"})
        self.assertAlmostEqual(sum(w * h for _x, _y, w, h in r.values()), 5000, places=6)
        self.assertEqual(summary.squarify([], 0, 0, 10, 10), {})


class RouteAndCli(ReportsHttp):
    """Only the tests below run here: the inherited report tests are hidden so they do not run twice."""
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

    def test_cli_text_mermaid_and_html(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["summary", "--since", "1d"])
        self.assertIn("- Fix the relay — Pushed; done.", out.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["summary", "--mermaid"])
        self.assertIn("mindmap", out.getvalue())
        path = self.root / "s.html"
        with contextlib.redirect_stdout(io.StringIO()):
            cli.main(["summary", "--html", str(path)])
        self.assertIn("Done summary", path.read_text())


for _n in [n for n in dir(ReportsHttp) if n.startswith("test_")]:
    setattr(RouteAndCli, _n, None)


if __name__ == "__main__":
    unittest.main()
