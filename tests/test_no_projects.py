"""Projects are gone (4 Nov 2026): no store methods, CLI commands, routes, filter, pill or panel select. A board file from before
still loads; its projects list and the cards' project_id are ignored and dropped on the next save."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from agentboard import cli
from agentboard.store import Store

from tests.test_reports import HttpTests as ReportsHttp

PAGE = (Path(cli.__file__).parent / "static" / "index.html").read_text()


class OldBoardsStillLoad(unittest.TestCase):
    def test_a_board_with_projects_loads_and_sheds_them_on_save(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / ".agentboard"; root.mkdir()
            (root / "tasks.json").write_text(json.dumps({"tasks": [
                {"id": "a", "title": "A", "status": "todo", "progress": 0, "project_id": "p1", "created": "2026-10-01T09:00:00", "updated": "2026-10-01T09:00:00"}],
                "projects": [{"id": "p1", "name": "Atlas"}], "chat": [], "chat_seq": 0}))
            s = Store(root)
            self.assertEqual([t["id"] for t in s.load()], ["a"])
            s.add("B", status="todo")
            saved = json.loads((root / "tasks.json").read_text())
            self.assertNotIn("projects", saved)
            self.assertEqual(next(t for t in saved["tasks"] if t["id"] == "a").get("project_id"), "p1")   # an old field is left alone, nothing reads it

    def test_the_store_and_cli_have_no_project_surface(self):
        for name in ("add_project", "load_projects", "set_project", "bulk_set_project", "delete_project", "update_project", "project_transaction"):
            self.assertFalse(hasattr(Store, name), name)
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
            cli.main(["project", "list"])
        self.assertIn("invalid choice: 'project'", err.getvalue())
        for flag in ("--project",):
            self.assertNotIn(flag, cli.INSTRUCTIONS)
        self.assertNotIn("## Projects", cli.INSTRUCTIONS)
        self.assertNotIn("## Projects", (Path(cli.__file__).parents[2] / "CLAUDE.md").read_text())


class Routes(ReportsHttp):
    def test_the_project_routes_are_gone(self):
        import urllib.error
        for path in ("/api/projects",):
            with self.assertRaises(urllib.error.HTTPError) as cm:
                self.get(path)
            self.assertEqual(cm.exception.code, 404)


for _n in [n for n in dir(ReportsHttp) if n.startswith("test_")]:
    setattr(Routes, _n, None)


class Page(unittest.TestCase):
    def test_the_page_has_no_project_filter_pill_dot_or_select(self):
        for s in ("project-filter", "bulk-project", "p-project", "projPill", "pdot", "proj-row", "renderProjectFilter", "renderBulkProjectOptions",
                  "/api/projects", "/api/task-project", "/api/bulk-project", "projectOf(", "projColor("):
            self.assertNotIn(s, PAGE, s)


if __name__ == "__main__":
    unittest.main()
