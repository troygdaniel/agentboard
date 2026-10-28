"""Card reports: writing on review/done, the page's contents, the controls' API, listing and ageing."""
import contextlib
import io
import json
import os
import socket
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from agentboard import boards, cli, reports, server
from agentboard.store import BoardError, Store


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.addCleanup(self.tmp.cleanup)
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        env["AGENTBOARD_HOME"] = str(self.root / "home")
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        self.proj = self.root / "proj"
        self.proj.mkdir()
        self.s = Store(self.proj / ".agentboard")
        os.environ["AGENTBOARD_DIR"] = str(self.s.dir)

    def files(self):
        return [r["file"] for r in reports.list_reports(self.s.dir)]

    def page(self, name=None):
        return (reports.reports_dir(self.s.dir) / (name or self.files()[0])).read_text()

    def review(self, title="Trim bundle size", agent="nova", sentence="Merge the bundle change; it cut 412kb to 271kb.", body=None, card=None):
        self.s.start(title, agent)
        cid = card or self.s.load()[-1]["id"]
        self.s.review(cid, sentence, body)
        return cid


class WritingTests(Base):
    def test_review_writes_a_report_and_the_card_remembers_it(self):
        cid = self.review()
        self.assertEqual(len(self.files()), 1)
        self.assertRegex(self.files()[0], r"^trim-bundle-size-\d{8}-\d{6}\.html$")
        t = Store.get(self.s.load(), cid)
        self.assertEqual(t["report"]["file"], self.files()[0])
        self.assertEqual(t["report"]["state"], "review")

    def test_the_page_says_one_thing_per_line_with_the_action_first(self):
        self.review(body="## What changed\nSplit the bundle.\n\n## How to try\nOpen http://localhost:5273/ and check the landing page.\n\n## Tests\n237 tests pass, 2 failed earlier.")
        page = self.page()
        self.assertIn("<h1>Trim bundle size</h1>", page)
        self.assertIn("nova", page)
        self.assertLess(page.index("Merge the bundle change"), page.index("Built"))   # the ACTION sentence leads
        for h in ("Built", "Timeline", "Try it"):
            self.assertIn(h, page)
        self.assertIn("<b>237</b><span>tests pass", page)   # the totals are tiles, not sentences
        self.assertIn("<b>2</b><span>failed", page)
        self.assertIn("http://localhost:5273/", page)
        self.assertIn('id="done"', page)
        self.assertIn("/api/send-back", page)
        self.assertIn("/api/move", page)

    def test_an_ask_leads_with_the_question(self):
        self.s.start("Harden retries", "echo")
        self.s.ask("harden-retries", "Pick the retry limit: 3 or 5?")
        reports.maybe_report(self.s, ["harden-retries"])
        self.assertEqual(self.files(), [])   # an ask is not review or done: no report yet

    def test_everything_the_agent_wrote_is_escaped(self):
        self.review(title="<script>alert(1)</script>", agent="<b>x</b>", sentence="<img src=x onerror=alert(2)> done", body="<script>alert(3)</script>\n\n[a](javascript:alert(4))")
        page = self.page()
        self.assertNotIn("<script>alert", page)
        self.assertNotIn("<img src=x", page)
        self.assertNotIn("<b>x</b>", page)
        self.assertNotIn('href="javascript', page)               # (the markdown link stays plain text)

    def test_done_writes_a_second_report_and_a_repeat_is_not_duplicated(self):
        cid = self.review()
        self.assertEqual(len(self.files()), 1)
        self.s.update(cid, status="done")
        self.assertEqual(len(self.files()), 2)
        self.assertEqual(Store.get(self.s.load(), cid)["report"]["state"], "done")
        reports.maybe_report(self.s, [cid])
        self.assertEqual(len(self.files()), 2)                     # same state, same result: nothing new

    def test_moving_to_done_by_drag_also_writes_one(self):
        self.s.start("Moved", "a")
        self.s.move("moved", "done")
        self.assertEqual(len(self.files()), 1)
        self.s.start("Bulk", "a")
        self.s.bulk_move(["bulk"], "done")
        self.assertEqual(len(self.files()), 2)

    def test_a_failing_report_never_undoes_the_move(self):
        self.s.start("Safe", "a")
        with mock.patch.object(reports, "write_report", side_effect=OSError("disk full")):
            self.s.review("safe", "done anyway")
        self.assertTrue(Store.get(self.s.load(), "safe")["review"])
        self.assertEqual(self.files(), [])

    def test_the_agents_own_markdown_file_adds_a_section(self):
        self.s.start("Extra", "a")
        reports.reports_dir(self.s.dir).mkdir(parents=True)
        (reports.reports_dir(self.s.dir) / "extra.md").write_text("## Benchmarks\nFaster by 30%.")
        self.s.review("extra", "ready")
        self.assertIn("More from the agent", self.page())
        self.assertIn("Faster by 30%", self.page())

    def test_commits_files_and_links_come_from_the_repo_the_card_was_open_in(self):
        git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=self.proj, check=True, capture_output=True)
        git("init", "-q")
        git("remote", "add", "origin", "git@github.com:troygdaniel/example.git")
        (self.proj / "before.txt").write_text("x")
        git("add", ".")
        git("commit", "-qm", "before the card")
        self.s.start("Built", "a")
        (self.proj / "feature.py").write_text("print(1)")
        git("add", "feature.py")
        git("commit", "-qm", "add the feature")
        self.s.review("built", "ready")
        page = self.page()
        self.assertIn("add the feature", page)
        self.assertIn("https://github.com/troygdaniel/example/commit/", page)
        self.assertIn("feature.py", page)

    def test_without_a_repo_it_says_so_and_still_writes(self):
        self.review()
        self.assertIn("No git repository found", self.page())


class SendBackTests(Base):
    def test_send_back_keeps_the_agent_on_the_card_with_the_note_to_read(self):
        cid = self.review()
        self.s.send_back(cid, "  also handle the dark theme  ")
        t = Store.get(self.s.load(), cid)
        self.assertEqual((t["status"], t["agent"]), ("doing", "nova"))
        self.assertNotIn("review", t)
        self.assertEqual(self.s.answer(cid)["text"], "also handle the dark theme")
        self.assertIn("Sent back", t["status_text"])
        with self.assertRaises(BoardError):
            self.s.send_back(cid, "  ")

    def test_a_done_card_can_be_sent_back_too(self):
        cid = self.review()
        self.s.update(cid, status="done")
        self.s.send_back(cid, "one more thing")
        self.assertEqual(Store.get(self.s.load(), cid)["status"], "doing")


class AgeingTests(Base):
    def make(self, card, age_h, now=None):
        self.s.start(card, "a") if not any(t["id"] == card for t in self.s.load()) else None
        return reports.write_report(self.s, card, now=(now or datetime.now()) - timedelta(hours=age_h))

    def test_old_reports_go_but_the_newest_per_card_stays(self):
        self.s.start("Alpha", "a")
        self.s.start("Beta", "a")
        old1, old2, new = self.make("alpha", 50), self.make("alpha", 30), self.make("alpha", 2)
        only_old = self.make("beta", 100)                  # the only report of its card: kept however old
        gone = reports.sweep(self.s.dir, hours=24)
        self.assertEqual(sorted(gone), sorted([old1, old2]))
        self.assertEqual(sorted(self.files()), sorted([new, only_old]))

    def test_it_never_touches_anything_but_report_files(self):
        self.s.start("Alpha", "a")
        self.s.add("keep me", status="todo")
        self.make("alpha", 80)
        self.make("alpha", 60)
        d = reports.reports_dir(self.s.dir)
        (d / "alpha.md").write_text("notes")
        (d / "notes.txt").write_text("x")
        (d / "alpha-old.html").write_text("not a report name")
        (self.s.dir / "backups").mkdir(exist_ok=True)
        (self.s.dir / "backups" / "snap-20200101-000000.json.gz").write_text("b")
        before = self.s.path.read_text()
        reports.sweep(self.s.dir, hours=1)
        self.assertEqual(self.s.path.read_text(), before)
        for name in ("alpha.md", "notes.txt", "alpha-old.html"):
            self.assertTrue((d / name).exists(), name)
        self.assertTrue((self.s.dir / "backups" / "snap-20200101-000000.json.gz").exists())
        self.assertEqual(len(self.files()), 1)

    def test_keep_hours_comes_from_config_and_defaults_to_24(self):
        self.assertEqual(reports.keep_hours(self.s.dir), 24.0)
        self.s.dir.mkdir(parents=True, exist_ok=True)
        (self.s.dir / "config.toml").write_text("[reports]\nkeep_hours = 2\n")
        self.assertEqual(reports.keep_hours(self.s.dir), 2.0)
        self.s.start("Alpha", "a")
        self.make("alpha", 3)
        newest = self.make("alpha", 0.5)
        reports.sweep(self.s.dir)
        self.assertEqual(self.files(), [newest])

    def test_the_cli_lists_and_purges(self):
        self.s.start("Alpha", "a")
        self.make("alpha", 90)
        self.make("alpha", 1)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["reports"])
        self.assertIn("alpha", out.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["reports", "--purge"])
        self.assertIn("removed 1 report", out.getvalue())
        self.assertEqual(len(self.files()), 1)


class ExtractionTests(unittest.TestCase):
    def test_test_totals(self):
        self.assertEqual(reports.test_totals("Ran 237 tests in 19s. 332 passed, 2 failed."), ["332 passed", "Ran 237 tests", "2 failed"])
        self.assertEqual(reports.test_totals("nothing here"), [])

    def test_how_to_try_stops_at_the_next_heading(self):
        md = "## Built\nstuff\n\n## How to try\nrun it\nthen look\n\n## Notes\nignored"
        self.assertEqual(reports.how_to_try(md), "run it\nthen look")
        self.assertEqual(reports.how_to_try("## Built\nonly"), "")

    def test_sections_shown_on_their_own_are_not_repeated_in_what_was_built(self):
        md = "## What changed\nSplit it.\n\n## How to try\nrun it\n\n## Tests\n237 pass\n\n## Notes\nlast"
        self.assertEqual(reports.without_sections(md), "## What changed\nSplit it.\n\n## Notes\nlast")

    def test_urls_are_deduplicated_and_trimmed(self):
        self.assertEqual(reports.urls_in("See https://a.example/x. and (https://a.example/x) also http://localhost:8765/hud,"), ["https://a.example/x", "http://localhost:8765/hud"])


class HttpTests(Base):
    def setUp(self):
        super().setUp()
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
            self.port = sk.getsockname()[1]
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), server.make_handler(self.s, self.port))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
            return r.status, r.read(), dict(r.headers)

    def post(self, path, body):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())

    def test_the_card_carries_its_report_and_the_page_is_served_with_a_tight_csp(self):
        cid = self.review()
        name = self.files()[0]
        task = json.loads(self.get("/api/tasks")[1])["tasks"][0]
        self.assertEqual(task["report"]["file"], name)
        status, body, headers = self.get(f"/reports/{name}")
        self.assertEqual(status, 200)
        self.assertIn(b"Trim bundle size", body)
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        self.assertEqual(cid, "trim-bundle-size")

    def test_the_list_is_newest_first(self):
        self.review("First", "a", card="first")
        self.review("Second", "b", card="second")
        old = reports.write_report(self.s, "first", now=datetime.now() - timedelta(hours=5))
        page = self.get("/reports/")[1].decode()
        self.assertEqual(page.count("<li>"), 3)
        self.assertLess(page.index("second"), page.index(old))

    def test_only_report_files_are_served(self):
        self.review()
        for bad in ("../tasks.json", "..%2Ftasks.json", "tasks.json", "x.html", ".env"):
            with self.assertRaises(urllib.error.HTTPError) as e:
                self.get(f"/reports/{bad}")
            self.assertEqual(e.exception.code, 404)
            e.exception.close()

    def test_the_controls_call_the_board_api(self):
        cid = self.review()
        self.post("/api/send-back", {"id": cid, "text": "please redo the header"})
        self.assertEqual(self.s.answer(cid)["text"], "please redo the header")
        self.s.review(cid, "second try")
        self.post("/api/move", {"id": cid, "status": "done"})
        self.assertEqual(Store.get(self.s.load(), cid)["status"], "done")

    def test_a_named_board_serves_its_own_reports_under_its_prefix(self):
        work = Store(boards.new("work"))
        work.start("Work card", "w")
        work.review("work-card", "ready")
        names = [r["file"] for r in reports.list_reports(work.dir)]
        self.assertEqual(self.get(f"/b/work/reports/{names[0]}")[0], 200)
        self.assertIn("/b/work/reports/", self.get("/b/work/reports/")[1].decode())
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.get(f"/reports/{names[0]}")   # not the default board's
        e.exception.close()
        self.assertEqual(e.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
