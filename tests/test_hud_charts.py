"""HUD: one chart per agent (progress over the window, activity per bucket) and the idle agents folded into one line."""
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from agentboard import hud
from agentboard.store import Store

NOW = datetime(2026, 10, 29, 12, 0, 0)


def at(minutes_ago):
    return (NOW - timedelta(minutes=minutes_ago)).strftime(hud.FMT)


def doing(tid, agent, log, progress=None, **extra):
    t = {"id": tid, "title": tid, "status": "doing", "agent": agent, "progress": progress if progress is not None else (log[-1].get("progress", 0) if log else 0),
         "created": at(120), "updated": log[-1]["at"] if log else at(120), "log": log}
    t.update(extra)
    return t


class ChartTests(unittest.TestCase):
    def test_progress_is_carried_forward_per_bucket_and_events_are_counted(self):
        log = [{"at": at(90), "status": "doing", "progress": 5, "text": "Claimed by a"},
               {"at": at(31), "status": "doing", "progress": 30, "text": "a third"},
               {"at": at(30), "status": "doing", "progress": 40, "text": "more"},
               {"at": at(3), "status": "doing", "progress": 80, "text": "nearly"}]
        c = hud.chart(doing("x", "a", log), [], NOW)
        self.assertEqual(len(c["pct"]), hud.TIMELINE_BUCKETS)
        self.assertEqual(c["pct"][0], 5)            # known from before the window
        self.assertEqual(c["pct"][14], 40)          # bucket ending at -30m takes both lines in it
        self.assertEqual(c["pct"][15], 40)          # carried forward
        self.assertEqual(c["pct"][-1], 80)
        self.assertEqual(sum(c["events"]), 3)       # the claim is outside the window
        self.assertEqual(c["events"][14], 2)

    def test_nothing_said_yet_is_none_not_zero_and_the_live_value_wins(self):
        c = hud.chart(doing("x", "a", [{"at": at(5), "status": "doing", "progress": 20, "text": "go"}], progress=35), [], NOW)
        self.assertIsNone(c["pct"][0])
        self.assertEqual(c["pct"][-2], 20)
        self.assertEqual(c["pct"][-1], 35)          # what the card says now

    def test_subtask_lines_count_as_activity_but_never_set_the_parents_percent(self):
        parent = doing("p", "a", [{"at": at(10), "status": "doing", "progress": 50, "text": "half"}])
        kid = {"id": "k", "parent_id": "p", "status": "doing", "log": [{"at": at(4), "status": "doing", "progress": 90, "text": "kid"}]}
        c = hud.chart(parent, [kid], NOW)
        self.assertEqual(sum(c["events"]), 2)
        self.assertEqual(c["pct"][-1], 50)

    def test_bad_progress_values_are_ignored(self):
        log = [{"at": at(8), "status": "doing", "progress": "lots", "text": "a"}, {"at": at(6), "status": "doing", "progress": True, "text": "b"},
               {"at": at(2), "status": "doing", "progress": 250, "text": "c"}]
        c = hud.chart(doing("x", "a", log, progress=250), [], NOW)
        self.assertEqual(c["pct"][-1], 100)
        self.assertEqual([v for v in c["pct"] if v is not None][0], 100)


class FoldTests(unittest.TestCase):
    def test_every_agent_has_a_chart_and_idle_ones_are_folded(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            s.start("A", "atlas", "blue")
            s.update("a", 40, "halfway")
            s.start("B", "bolt")
            s.update("b", text="ok", status="done")
            h = hud.build(s.load())
            self.assertTrue(all(len(a["chart"]["pct"]) == hud.TIMELINE_BUCKETS for a in h["agents"]))
            atlas = next(a for a in h["agents"] if a["name"] == "atlas")
            self.assertEqual(atlas["chart"]["pct"][-1], 40)
            self.assertEqual(h["idle"]["n"], 1)
            self.assertEqual([a["name"] for a in h["idle"]["agents"]], ["bolt"])
            self.assertEqual(h["idle"]["agents"][0]["task"], "B")
            self.assertEqual(h["idle"]["done_today"], 1)

    def test_roster_peers_without_a_card_are_idle_and_retired_ones_stay_out(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            s.start("A", "AGENT-1", "green")
            h = hud.build(s.load(), roster=["AGENT-1", "AGENT-2", "AGENT-3"], retired=["AGENT-3"])
            self.assertEqual([(a["name"], a["state"]) for a in h["agents"]], [("AGENT-1", "working"), ("AGENT-2", "idle")])
            self.assertEqual([a["name"] for a in h["idle"]["agents"]], ["AGENT-2"])
            self.assertEqual(h["totals"]["working"], 1)   # a roster peer is not a card

    def test_roster_reads_only_an_explicit_orch_table(self):
        self.assertEqual(hud.roster({"orch": {"agents": [{"name": "AGENT-1"}, {"name": " AGENT-2 "}, {"color": "red"}, "junk"]}}), ["AGENT-1", "AGENT-2"])
        self.assertEqual(hud.roster({}), [])
        self.assertEqual(hud.roster({"orch": {"agents": "AGENT-1"}}), [])
        self.assertEqual(hud.roster(None), [])


if __name__ == "__main__":
    unittest.main()
