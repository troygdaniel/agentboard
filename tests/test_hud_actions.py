"""The HUD's ACTION strip: every ask / review / abandoned card as one 'who needs what' row."""
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from agentboard import hud
from agentboard.store import Store


class ParseActionTests(unittest.TestCase):
    def test_three_line_shape_on_separate_lines(self):
        a = hud.parse_action("ACTION Troy: tap Call me once\nSTATUS card-x done-ready\nWHY it costs one call")
        self.assertEqual((a["who"], a["what"]), ("Troy", "tap Call me once"))
        self.assertEqual(a["status"], "card-x done-ready")
        self.assertEqual(a["why"], "it costs one call")

    def test_joined_with_pipes_and_colon_variants(self):
        a = hud.parse_action("ACTION: ORCH: restart the API | STATUS: x 40% | WHY: y")
        self.assertEqual((a["who"], a["what"], a["status"]), ("ORCH", "restart the API", "x 40%"))
        self.assertEqual(hud.parse_action("ACTION  AGENT-2: regenerate types")["who"], "AGENT-2")
        self.assertEqual(hud.parse_action("ACTION none")["who"], "none")

    def test_plain_text_is_not_an_action_line(self):
        a = hud.parse_action("Which port should the server use?")
        self.assertEqual(a, {"who": "", "what": "", "status": "", "why": ""})


class ActionRowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = Store(Path(self.tmp.name) / ".agentboard")

    def tearDown(self):
        self.tmp.cleanup()

    def test_asks_for_troy_come_first_then_reviews_then_stale(self):
        self.s.start("Review me", "atlas", "blue")
        self.s.review("review-me", "ACTION Troy: open /hud and look | STATUS review-me done-ready")
        self.s.start("Ask me", "bolt")
        self.s.ask("ask-me", "Which port?")
        self.s.start("Quiet one", "cass")
        self.s.start("Busy one", "dan")
        self.s.update("busy-one", 50, "halfway")
        tasks = self.s.load()
        quiet = next(t for t in tasks if t["id"] == "quiet-one")
        quiet["updated"] = (datetime.now() - timedelta(hours=3)).strftime(hud.FMT)
        rows = hud.actions(tasks)
        self.assertEqual([r["kind"] for r in rows], ["ask", "review", "stale"])
        ask, rev, stale = rows
        self.assertEqual((ask["who"], ask["what"], ask["agent"]), ("Troy", "Which port?", "bolt"))
        self.assertEqual((rev["who"], rev["what"]), ("Troy", "open /hud and look"))
        self.assertEqual(rev["status"], "review-me done-ready")
        self.assertEqual((stale["who"], stale["agent"]), ("ORCH", "cass"))
        self.assertIn("no update for", stale["what"])
        self.assertGreaterEqual(stale["age_min"], 179)
        self.assertTrue(all(r["id"] != "busy-one" for r in rows))

    def test_action_named_for_another_agent_sorts_after_troy(self):
        self.s.start("A", "atlas")
        self.s.review("a", "ACTION AGENT-2: add the field to openapi | STATUS a done-ready")
        self.s.start("B", "bolt")
        self.s.review("b", "all done")
        rows = hud.actions(self.s.load())
        self.assertEqual([(r["who"], r["id"]) for r in rows], [("Troy", "b"), ("AGENT-2", "a")])
        self.assertEqual(rows[0]["what"], "all done")   # no ACTION line: the summary is the ask

    def test_build_carries_actions_and_open_counts(self):
        self.s.start("A", "atlas")
        self.s.ask("a", "go?")
        self.s.start("B", "atlas")
        h = hud.build(self.s.load())
        self.assertEqual([r["id"] for r in h["actions"]], ["a"])
        atlas = next(x for x in h["agents"] if x["name"] == "atlas")
        self.assertEqual(atlas["open"], 2)
        self.assertEqual(sorted(atlas["open_titles"]), ["A", "B"])
        self.assertEqual(h["actions"][0]["age_min"], 0)


class RetiredAgentTests(unittest.TestCase):
    def test_retired_names_leave_agents_lanes_and_actions_but_not_history(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            s.start("Old", "AGENT-5")
            s.ask("old", "still here?")
            s.start("New", "AGENT-1")
            tasks = s.load()
            h = hud.build(tasks, retired={"AGENT-5"})
            self.assertEqual([a["name"] for a in h["agents"]], ["AGENT-1"])
            self.assertNotIn("AGENT-5", h["lanes"])
            self.assertEqual(h["actions"], [])
            self.assertTrue(any(e["agent"] == "AGENT-5" for e in h["events"]))   # the feed still shows what it did
            self.assertEqual(h["totals"]["working"], 2)                          # its card is still a Doing card
            self.assertEqual(sorted(a["name"] for a in hud.build(tasks)["agents"]), ["AGENT-1", "AGENT-5"])

    def test_retired_reads_the_hud_table_and_ignores_junk(self):
        self.assertEqual(hud.retired({"hud": {"retired": ["AGENT-5", " x ", 3]}}), {"AGENT-5", "x"})
        self.assertEqual(hud.retired({"hud": {"retired": "AGENT-5"}}), set())
        self.assertEqual(hud.retired({}), set())
        self.assertEqual(hud.retired(None), set())


if __name__ == "__main__":
    unittest.main()
