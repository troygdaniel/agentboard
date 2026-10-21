import tempfile
import threading
import unittest
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
