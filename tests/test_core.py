import argparse
import tempfile
import threading
import unittest
import unittest.mock
from pathlib import Path

from agentboard import prompt, providers
from agentboard.store import BoardError, Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / ".agentboard"
        self.s = Store(self.dir)

    def tearDown(self):
        self.tmp.cleanup()

    def test_claim_conflict_and_force(self):
        self.s.add("A", status="todo")
        self.s.claim("a", "alice", "blue")
        with self.assertRaises(BoardError):
            self.s.claim("a", "bob")
        self.assertEqual(self.s.claim("a", "bob", force=True)["agent"], "bob")

    def test_back_to_todo_releases_owner_but_keeps_progress(self):
        self.s.add("A", status="todo")
        self.s.claim("a", "alice")
        self.s.update("a", 40)
        t = self.s.move("a", "todo")
        self.assertNotIn("agent", t)
        self.assertEqual(t["progress"], 40)

    def test_concurrent_updates_not_lost(self):
        for i in range(8):
            self.s.add(f"t{i}", status="doing")
        threads = [threading.Thread(target=self.s.update, args=(f"t{i}", 10 * i)) for i in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual([t["progress"] for t in self.s.load()], [10 * i for i in range(8)])


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.dir = self.root / ".agentboard"
        self.dir.mkdir()
        (self.root / "doc.md").write_text("# A\n## Dad\nfacts\n### Sizes\n33\n## Other\nsecret\n")
        (self.dir / "config.toml").write_text(
            '[providers.docs]\ntype="markdown"\npath="doc.md"\n'
            '[providers.priv]\ntype="command"\nrun="echo 555-123-4567"\nprivate=true\nredact=["\\\\d{3}-\\\\d{4}"]\n')

    def tearDown(self):
        self.tmp.cleanup()

    def test_markdown_sections_include_subsections_only(self):
        text, warns = prompt.build_prompt({"id": "x", "title": "T", "ctx": ["docs:Dad"]}, self.dir)
        self.assertIn("facts", text)
        self.assertIn("33", text)
        self.assertNotIn("secret", text)
        self.assertEqual(warns, [])

    def test_private_provider_skipped_when_public_and_redacted_otherwise(self):
        task = {"id": "x", "title": "T", "ctx": ["priv"]}
        private, _ = prompt.build_prompt(task, self.dir)
        public, _ = prompt.build_prompt(task, self.dir, public=True)
        self.assertIn("[REDACTED]", private)
        self.assertNotIn("4567", private)
        self.assertNotIn("priv", public)

    def test_unknown_provider_warns(self):
        _, warns = prompt.build_prompt({"id": "x", "title": "T", "ctx": ["nope"]}, self.dir)
        self.assertEqual(len(warns), 1)


if __name__ == "__main__":
    unittest.main()


class StartTests(unittest.TestCase):
    def test_start_is_idempotent_for_same_agent_only(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            t = s.start("Fix bug", "atlas", "blue")
            self.assertEqual((t["status"], t["agent"], t["color"]), ("doing", "atlas", "blue"))
            self.assertEqual(s.start("Fix bug", "atlas", task_id="fix-bug")["id"], "fix-bug")
            with self.assertRaises(BoardError):
                s.start("Fix bug", "bolt", task_id="fix-bug")
            self.assertEqual(len(s.load()), 1)


class HistoryTests(unittest.TestCase):
    def test_done_keeps_result_and_history_records_steps(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            s.start("Job", "atlas")
            s.update("job", 50, "halfway")
            t = s.update("job", text="shipped it", status="done")
            self.assertEqual(t["result"], "shipped it")
            self.assertEqual([e["text"] for e in t["log"]], ["Started by atlas", "halfway", "Marked done"])
            self.assertNotIn("result", s.move("job", "todo"))


class UndoTests(unittest.TestCase):
    def test_restore_puts_task_back_with_owner_and_position(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            s.start("A", "atlas", "blue")
            s.start("B", "bolt")
            prev = Store.get(s.load(), "a")
            before = s.next_sibling("a")
            self.assertEqual(before, "b")
            s.move("a", "todo")                       # drops the owner
            self.assertNotIn("agent", Store.get(s.load(), "a"))
            s.restore(prev, before)
            tasks = s.load()
            self.assertEqual([t["id"] for t in tasks], ["a", "b"])
            self.assertEqual((tasks[0]["agent"], tasks[0]["status"]), ("atlas", "doing"))


class HudTests(unittest.TestCase):
    def test_agents_totals_feed_and_timeline(self):
        from agentboard import hud
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            s.start("A", "atlas", "blue")
            s.update("a", 40, "halfway")
            s.start("B", "bolt")
            s.update("b", text="ok", status="done")
            s.add("C", status="todo")
            h = hud.build(s.load())
            self.assertEqual({a["name"]: a["state"] for a in h["agents"]}, {"atlas": "working", "bolt": "idle"})
            self.assertEqual((h["totals"]["working"], h["totals"]["done_today"], h["totals"]["queued"]), (1, 1, 1))
            self.assertIn("Added to todo", [e["text"] for e in h["events"]])
            self.assertEqual(sum(h["timeline"]), 5)
            self.assertEqual(sum(h["agents"][0]["spark"]), 2)
            self.assertTrue(all(a["started"] for a in h["agents"]))   # elapsed-time source for the constellation
            atlas = next(a for a in h["agents"] if a["name"] == "atlas")
            self.assertEqual([r["text"] for r in atlas["recent"]][0], "halfway")   # newest first, current task only
            self.assertLessEqual(len(atlas["recent"]), 3)


class LaneTests(unittest.TestCase):
    def test_segments_follow_the_log(self):
        from datetime import datetime
        from agentboard import hud
        at = lambda m: f"2026-01-01T10:{m:02d}:00"
        e = lambda m, st, text: {"at": at(m), "status": st, "text": text}
        task = {"log": [e(0, "todo", "Added to todo"), e(5, "doing", "Claimed by a"), e(9, "doing", "step"),
                        e(12, "doing", "Needs input: ok?"), e(15, "doing", "back"), e(20, "doing", "Ready for review: x"),
                        e(25, "done", "Marked done")]}
        runs = [(k, a.minute, b.minute) for k, a, b in hud.segments(task, datetime(2026, 1, 1, 10, 30))]
        self.assertEqual(runs, [("queue", 0, 5), ("busy", 5, 12), ("waiting", 12, 15), ("busy", 15, 20), ("review", 20, 25)])

    def test_open_run_extends_to_now_and_feeds_lanes_and_queue(self):
        from agentboard import hud
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            s.start("A", "atlas", "blue")
            s.add("B", status="todo")
            h = hud.build(s.load())
            self.assertEqual([r["k"] for r in h["lanes"]["atlas"]], ["busy"])
            self.assertEqual(h["queue"][-1], 1)
            self.assertEqual(len(h["queue"]), hud.TIMELINE_BUCKETS)
            self.assertEqual(h["window_min"], 60)


class AskTests(unittest.TestCase):
    def test_ask_sets_flag_and_update_clears_it(self):
        from agentboard import hud
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            s.start("Deploy", "atlas")
            t = s.ask("deploy", "Staging or prod?")
            self.assertTrue(t["needs_input"])
            self.assertEqual(t["status_text"], "Staging or prod?")
            h = hud.build(s.load())
            self.assertEqual(h["agents"][0]["state"], "waiting")
            self.assertEqual(h["totals"]["waiting"], 1)
            t = s.update("deploy", 60, "resuming")
            self.assertNotIn("needs_input", t)
            self.assertEqual(hud.build(s.load())["totals"]["waiting"], 0)


class ReviewTests(unittest.TestCase):
    def test_review_hands_off_and_user_signoff_keeps_result(self):
        from agentboard import hud
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            s.start("Ship it", "atlas")
            t = s.review("ship-it", "All tests green")
            self.assertTrue(t["review"])
            self.assertEqual((t["progress"], t["result"]), (100, "All tests green"))
            h = hud.build(s.load())
            self.assertEqual(h["agents"][0]["state"], "review")
            self.assertEqual(h["totals"]["review"], 1)
            t = s.move("ship-it", "done")          # the user drags it to Done
            self.assertNotIn("review", t)
            self.assertEqual(t["result"], "All tests green")
            self.assertEqual(hud.build(s.load())["totals"]["done_today"], 1)


class ProjectTests(unittest.TestCase):
    def test_add_and_assign(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            p = s.add_project("Kitchen Remodel", "#ff0000")
            s.add("Pick tile", status="todo", project_id=p["id"])
            t = Store.get(s.load(), "pick-tile")
            self.assertEqual(t["project_id"], p["id"])
            self.assertEqual(s.load_projects()[0]["name"], "Kitchen Remodel")

    def test_assign_unknown_project_raises(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            s.add("A", status="todo")
            with self.assertRaises(BoardError):
                s.set_project("a", "nope")

    def test_unassign_clears_project_id(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            p = s.add_project("Taxes")
            s.add("A", status="backlog", project_id=p["id"])
            s.set_project("a", None)
            self.assertNotIn("project_id", Store.get(s.load(), "a"))

    def test_delete_project_unties_its_tasks(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            p = s.add_project("Taxes")
            s.add("A", status="backlog", project_id=p["id"])
            s.delete_project(p["id"])
            self.assertEqual(s.load_projects(), [])
            self.assertNotIn("project_id", Store.get(s.load(), "a"))

    def test_update_project_fields(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            p = s.add_project("Taxes", "#111111")
            updated = s.update_project(p["id"], name="2026 Taxes", color="#222222")
            self.assertEqual((updated["name"], updated["color"]), ("2026 Taxes", "#222222"))


class DependencyTests(unittest.TestCase):
    def test_add_with_unknown_blocker_raises(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            with self.assertRaises(BoardError):
                s.add("Frontend", status="todo", blocked_by=["nope"])

    def test_add_stores_blocked_by(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            s.add("Backend", task_id="backend", status="todo")
            t = s.add("Frontend", status="todo", blocked_by=["backend"])
            self.assertEqual(t["blocked_by"], ["backend"])

    def test_start_refuses_while_blocker_not_done(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            s.add("Backend", task_id="backend", status="todo")
            with self.assertRaises(BoardError):
                s.start("Frontend", "atlas", blocked_by=["backend"])
            t = s.start("Frontend", "atlas", blocked_by=["backend"], force=True)
            self.assertEqual(t["blocked_by"], ["backend"])

    def test_claim_refuses_while_blocker_not_done_then_succeeds_once_done(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            s.add("Backend", task_id="backend", status="todo")
            s.add("Frontend", task_id="frontend", status="todo", blocked_by=["backend"])
            with self.assertRaises(BoardError):
                s.claim("frontend", "atlas")
            s.claim("frontend", "atlas", force=True)  # force bypasses the guard
            s.move("frontend", "todo")
            s.start("Backend done already", "bolt", task_id="backend2")
            s.move("backend", "done")
            s.claim("frontend", "atlas")  # now resolved on its own, no --force needed

    def test_deleted_blocker_no_longer_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            s.add("Backend", task_id="backend", status="todo")
            s.add("Frontend", task_id="frontend", status="todo", blocked_by=["backend"])
            s.delete("backend")
            s.claim("frontend", "atlas")  # missing blocker is treated as resolved


class WaitTests(unittest.TestCase):
    def test_reaches_plain_status_target(self):
        from agentboard import cli
        self.assertEqual(cli._wait_result({"status": "done"}, "done"), "reached done")
        self.assertIsNone(cli._wait_result({"status": "doing"}, "done"))

    def test_review_target_needs_the_review_flag(self):
        from agentboard import cli
        self.assertEqual(
            cli._wait_result({"status": "doing", "review": True, "result": "shipped"}, "review"),
            "ready for review — shipped")
        self.assertIsNone(cli._wait_result({"status": "doing"}, "review"))

    def test_needs_input_target(self):
        from agentboard import cli
        self.assertEqual(
            cli._wait_result({"status": "doing", "needs_input": True, "question": "A or B?"}, "needs_input"),
            "needs input — A or B?")
        self.assertIsNone(cli._wait_result({"status": "doing"}, "needs_input"))

    def test_review_and_needs_input_end_the_wait_early_even_when_not_the_target(self):
        from agentboard import cli
        self.assertEqual(
            cli._wait_result({"status": "doing", "review": True, "result": "x"}, "done"),
            "ready for review (target was done) — x")
        self.assertEqual(
            cli._wait_result({"status": "doing", "needs_input": True, "question": "y?"}, "done"),
            "needs input (target was done) — y?")

    def test_wait_cli_returns_immediately_when_already_at_target(self):
        import io
        from contextlib import redirect_stdout
        from agentboard import cli
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            s.start("Deploy", "atlas", task_id="deploy")
            s.update("deploy", text="shipped", status="done")
            out = io.StringIO()
            a = argparse.Namespace(id="deploy", status="done", interval=0.01, timeout=None)
            with redirect_stdout(out), unittest.mock.patch.object(cli, "_store", return_value=s):
                cli.cmd_wait(a)
            self.assertIn("reached done", out.getvalue())

    def test_wait_cli_times_out(self):
        from agentboard import cli
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            s.start("Deploy", "atlas", task_id="deploy")
            a = argparse.Namespace(id="deploy", status="done", interval=0.01, timeout=0.03)
            with unittest.mock.patch.object(cli, "_store", return_value=s):
                with self.assertRaises(SystemExit):
                    cli.cmd_wait(a)


class BodyTests(unittest.TestCase):
    def test_ask_and_review_store_body_md_and_clear_it_on_next_transition(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            s.start("Deploy", "atlas")
            t = s.ask("deploy", "Staging or prod?", "- a\n- b")
            self.assertEqual(t["body_md"], "- a\n- b")
            t = s.update("deploy", 60, "resuming")
            self.assertNotIn("body_md", t)
            t = s.review("deploy", "Shipped", "## Recap\nDone.")
            self.assertEqual(t["body_md"], "## Recap\nDone.")
            t = s.move("deploy", "done")
            self.assertNotIn("body_md", t)

    def test_body_md_is_optional(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            s.start("Deploy", "atlas")
            t = s.ask("deploy", "Staging or prod?")
            self.assertNotIn("body_md", t)


class MarkdownTests(unittest.TestCase):
    def test_escapes_raw_html_instead_of_passing_it_through(self):
        from agentboard import markdown
        html = markdown.to_html('<script>alert(1)</script>')
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)

    def test_renders_headings_lists_code_and_links(self):
        from agentboard import markdown
        html = markdown.to_html(
            "## Recap\n- did a\n- did b\n\n```diff\n-old\n+new\n```\n\nSee [docs](https://example.com).")
        self.assertIn('<h2>Recap</h2>', html)
        self.assertIn('<ul><li>did a</li><li>did b</li></ul>', html)
        self.assertIn('<pre><code class="lang-diff">-old\n+new</code></pre>', html)
        self.assertIn('<a href="https://example.com" target="_blank" rel="noopener noreferrer">docs</a>', html)

    def test_rejects_non_http_link_schemes(self):
        from agentboard import markdown
        html = markdown.to_html('[click](javascript:alert(1))')
        self.assertNotIn('<a ', html)

    def test_empty_input(self):
        from agentboard import markdown
        self.assertEqual(markdown.to_html(''), '')
        self.assertEqual(markdown.to_html(None), '')


class TailTests(unittest.TestCase):
    """cmd_tail's polling loop isn't itself unit-tested (it sleeps forever until Ctrl+C); these
    cover _tail_fresh, the pure dedup/watermark step it calls each poll."""

    def test_first_poll_returns_nothing_new_against_its_own_baseline(self):
        from agentboard.cli import _tail_fresh
        events = [{"task": "a", "at": "2026-01-01T10:00:01", "text": "step 2"},
                  {"task": "a", "at": "2026-01-01T10:00:00", "text": "step 1"}]
        fresh, last_at, seen = _tail_fresh(events, events[0]["at"], {("a", events[0]["at"], "step 2")})
        self.assertEqual(fresh, [])
        self.assertEqual(last_at, "2026-01-01T10:00:01")

    def test_new_events_after_watermark_come_back_oldest_first(self):
        from agentboard.cli import _tail_fresh
        last_at, seen = "2026-01-01T10:00:00", {("a", "2026-01-01T10:00:00", "step 1")}
        events = [{"task": "b", "at": "2026-01-01T10:00:02", "text": "step 3"},
                  {"task": "a", "at": "2026-01-01T10:00:01", "text": "step 2"},
                  {"task": "a", "at": "2026-01-01T10:00:00", "text": "step 1"}]
        fresh, last_at, seen = _tail_fresh(events, last_at, seen)
        self.assertEqual([e["text"] for e in fresh], ["step 2", "step 3"])
        self.assertEqual(last_at, "2026-01-01T10:00:02")

    def test_same_second_collision_is_not_dropped_or_duplicated(self):
        from agentboard.cli import _tail_fresh
        t = "2026-01-01T10:00:05"
        events = [{"task": "c", "at": t, "text": "burst-3"}, {"task": "b", "at": t, "text": "burst-2"},
                  {"task": "a", "at": t, "text": "burst-1"}]
        # poll 1 sees burst-1 and burst-2 at the same second
        fresh, last_at, seen = _tail_fresh(events[1:], "2026-01-01T10:00:04", set())
        self.assertEqual([e["text"] for e in fresh], ["burst-1", "burst-2"])
        # poll 2: burst-3 lands at the same second as the watermark — must appear exactly once, not replay 1/2
        fresh, last_at, seen = _tail_fresh(events, last_at, seen)
        self.assertEqual([e["text"] for e in fresh], ["burst-3"])

    def test_empty_board_advances_nothing(self):
        from agentboard.cli import _tail_fresh
        fresh, last_at, seen = _tail_fresh([], "2026-01-01T10:00:00", set())
        self.assertEqual(fresh, [])
        self.assertEqual(last_at, "2026-01-01T10:00:00")   # unseeded by an empty snapshot


class NotifyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / ".agentboard"
        self.dir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _write_config(self, text):
        (self.dir / "config.toml").write_text(text)

    def test_off_by_default_when_config_has_no_notify_section(self):
        from agentboard.cli import _notify_cfg
        self._write_config('[board]\nstale_minutes = 60\n')
        self.assertEqual(_notify_cfg(self.dir), (False, None))

    def test_off_when_no_config_file_at_all(self):
        from agentboard.cli import _notify_cfg
        self.assertEqual(_notify_cfg(self.dir), (False, None))

    def test_reads_enabled_and_optional_sound(self):
        from agentboard.cli import _notify_cfg
        self._write_config('[notify]\nenabled = true\nsound = "Glass"\n')
        self.assertEqual(_notify_cfg(self.dir), (True, "Glass"))

    def test_disabled_never_shells_out(self):
        from agentboard.cli import _notify
        self._write_config('[notify]\nenabled = false\n')
        with unittest.mock.patch("agentboard.cli.subprocess.run") as run:
            _notify(self.dir, "title", "subtitle", "body")
        run.assert_not_called()

    def test_enabled_shells_out_to_osascript_with_escaped_fields(self):
        from agentboard.cli import _notify
        self._write_config('[notify]\nenabled = true\nsound = "Glass"\n')
        with unittest.mock.patch("agentboard.cli.subprocess.run") as run:
            _notify(self.dir, 'Agent "atlas"', "task title", 'Deploy "now"?')
        run.assert_called_once()
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[:2], ["osascript", "-e"])
        script = cmd[2]
        self.assertIn('display notification "Deploy \\"now\\"?"', script)
        self.assertIn('title "Agent \\"atlas\\""', script)
        self.assertIn('subtitle "task title"', script)
        self.assertIn('sound name "Glass"', script)

    def test_enabled_without_sound_omits_sound_clause(self):
        from agentboard.cli import _notify
        self._write_config('[notify]\nenabled = true\n')
        with unittest.mock.patch("agentboard.cli.subprocess.run") as run:
            _notify(self.dir, "t", "s", "b")
        self.assertNotIn("sound name", run.call_args.args[0][2])

    def test_never_raises_if_osascript_is_missing(self):
        from agentboard.cli import _notify
        self._write_config('[notify]\nenabled = true\n')
        with unittest.mock.patch("agentboard.cli.subprocess.run", side_effect=OSError("not found")):
            _notify(self.dir, "t", "s", "b")   # must not raise

    def test_skipped_entirely_on_non_darwin(self):
        from agentboard.cli import _notify
        self._write_config('[notify]\nenabled = true\n')
        with unittest.mock.patch("agentboard.cli.sys.platform", "linux"), \
             unittest.mock.patch("agentboard.cli.subprocess.run") as run:
            _notify(self.dir, "t", "s", "b")
        run.assert_not_called()

    def test_ask_and_review_fire_notification_when_enabled(self):
        from agentboard.store import Store
        from agentboard import cli
        s = Store(self.dir)
        self._write_config('[notify]\nenabled = true\n')
        s.start("Ship it", "atlas")
        with unittest.mock.patch("agentboard.cli._store", return_value=s), \
             unittest.mock.patch("agentboard.cli.subprocess.run") as run:
            cli.cmd_ask(argparse.Namespace(id="ship-it", question="Staging or prod?", body=None, body_file=None))
            cli.cmd_review(argparse.Namespace(id="ship-it", text="All green", body=None, body_file=None))
        self.assertEqual(run.call_count, 2)
        self.assertIn("Staging or prod?", run.call_args_list[0].args[0][2])
        self.assertIn("All green", run.call_args_list[1].args[0][2])

    def test_ask_does_not_shell_out_when_disabled(self):
        from agentboard.store import Store
        from agentboard import cli
        s = Store(self.dir)
        self._write_config('[notify]\nenabled = false\n')
        s.start("Ship it", "atlas")
        with unittest.mock.patch("agentboard.cli._store", return_value=s), \
             unittest.mock.patch("agentboard.cli.subprocess.run") as run:
            cli.cmd_ask(argparse.Namespace(id="ship-it", question="Staging or prod?", body=None, body_file=None))
        run.assert_not_called()


class ClearTests(unittest.TestCase):
    def test_clear_archives_done_and_unarchive_restores(self):
        from agentboard import hud
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            s.start("A", "atlas")
            s.review("a", "ok")
            s.move("a", "done")
            s.add("B", status="todo")
            self.assertEqual(s.clear_done(), ["a"])
            self.assertTrue(Store.get(s.load(), "a")["archived"])
            self.assertEqual(hud.build(s.load())["totals"]["done_today"], 1)   # HUD still counts it
            s.unarchive(["a"])
            self.assertNotIn("archived", Store.get(s.load(), "a"))
