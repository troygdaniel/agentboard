"""Agent state history (card agentboard-insights-agent-states, docs/insights-design.md capture 4). The server samples every agent's state once a minute, with [insights] on, and
appends a line to .agentboard/agent-states.jsonl when it changes (and a heartbeat every 15 minutes); insights.py reads those lines to say how long each agent waited for work
and where the night gaps went. Part 1: the state rule. Part 2: the sampler on a throwaway board. Part 3: the server wiring. Part 4: the observations, on state lines made up here
with the hours worked out by hand. Nothing here touches a real board, starts a program or reads card text."""
import json
import os
import re
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from agentboard import agentstates, insights, listeners
from agentboard.store import Store

NOW = datetime(2026, 11, 14, 12, 0, 0)
SRC = Path(agentstates.__file__).parent


def stamp(minutes_ago):
    return (NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%S")


def doing(updated_minutes_ago=1, **kw):
    return dict({"status": "doing", "updated": stamp(updated_minutes_ago)}, **kw)


class TheStateRule(unittest.TestCase):
    def state(self, cards, listening=False):
        return agentstates.agent_state(cards, listening, NOW, abandoned_min=120)

    def test_no_open_card_is_listening_or_away(self):
        self.assertEqual(self.state([], listening=True), "listening")
        self.assertEqual(self.state([], listening=False), "away")
        self.assertEqual(self.state([{"status": "done"}, {"status": "todo"}], listening=True), "listening")   # a finished card is not an open one

    def test_an_open_card_touched_recently_is_working_then_quiet_then_abandoned(self):
        self.assertEqual(self.state([doing(1)]), "working")
        self.assertEqual(self.state([doing(10)]), "working")          # up to STALE_MIN
        self.assertEqual(self.state([doing(11)]), "quiet")
        self.assertEqual(self.state([doing(120)]), "quiet")
        self.assertEqual(self.state([doing(121)]), "abandoned")
        self.assertEqual(self.state([{"status": "doing"}]), "abandoned")   # never touched: no stamp

    def test_a_listener_does_not_make_an_agent_with_a_card_idle(self):
        self.assertEqual(self.state([doing(1)], listening=True), "working")

    def test_every_open_card_waiting_on_the_owner_is_waiting(self):
        self.assertEqual(self.state([doing(5, needs_input=True)]), "waiting")
        self.assertEqual(self.state([doing(5, review=True)]), "review")
        self.assertEqual(self.state([doing(5, review=True), doing(5, needs_input=True)]), "waiting")

    def test_a_card_in_review_does_not_hide_the_work_on_another(self):
        self.assertEqual(self.state([doing(5, review=True), doing(2)]), "working")      # the HUD would say review; the agent is busy
        self.assertEqual(self.state([doing(5, review=True), doing(30)]), "quiet")

    def test_the_states_are_the_documented_list(self):
        self.assertEqual(agentstates.STATES, ("working", "quiet", "abandoned", "waiting", "review", "listening", "away"))


class WhoIsTracked(unittest.TestCase):
    def test_agents_holding_a_card_and_the_roster_less_the_retired(self):
        tasks = [{"id": "a", "agent": "A", "status": "doing", "updated": stamp(1)}, {"id": "b", "agent": "B", "status": "done"},
                 {"id": "a-sub", "agent": "S", "status": "doing", "parent_id": "a", "updated": stamp(1)}, {"id": "r", "agent": "Retired", "status": "doing", "updated": stamp(1)}]
        got = agentstates.current(tasks, ["b"], NOW, roster=["Rostered", ""], retired=["retired"])
        self.assertEqual(got, {"A": "working", "B": "listening", "Rostered": "away"})     # a subtask's agent is not a holder, the retired are left out, names match in any case

    def test_garbage_in_the_cards_never_raises(self):
        self.assertEqual(agentstates.current([None, 5, {"id": "x"}, {"agent": ""}], [], NOW), {})


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
        self.s.dir.mkdir(parents=True, exist_ok=True)
        self.now = datetime.now().replace(microsecond=0)

    def turn_on(self):
        (self.s.dir / "config.toml").write_text("[insights]\nenabled = true\n")

    def lines(self):
        p = self.s.dir / agentstates.FILE
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


class TheSampler(Base):
    def test_with_the_flag_off_nothing_is_written(self):
        self.s.start_card("work", "AGENT-1", None)
        self.assertEqual(agentstates.sample(self.s, self.now), 0)
        self.assertFalse((self.s.dir / agentstates.FILE).exists())

    def test_the_first_sample_writes_every_agent_and_an_unchanged_one_writes_nothing(self):
        self.turn_on()
        self.s.start_card("work", "AGENT-1", None)
        self.s.start_card("more work", "AGENT-2", None)
        self.assertEqual(agentstates.sample(self.s, self.now), 2)
        self.assertEqual({(x["agent"], x["state"]) for x in self.lines()}, {("AGENT-1", "working"), ("AGENT-2", "working")})
        self.assertEqual(agentstates.sample(self.s, self.now + timedelta(minutes=1)), 0)        # nothing changed

    def test_a_change_writes_one_line_for_that_agent_only(self):
        self.turn_on()
        self.s.start_card("work", "AGENT-1", None)
        self.s.start_card("more work", "AGENT-2", None)
        agentstates.sample(self.s, self.now)
        self.s.ask("more-work", "which one?")                         # AGENT-2's only open card is now a question to the owner
        self.assertEqual(agentstates.sample(self.s, self.now + timedelta(minutes=1)), 1)
        last = self.lines()[-1]
        self.assertEqual((last["agent"], last["state"]), ("AGENT-2", "waiting"))

    def test_a_heartbeat_is_written_every_fifteen_minutes_even_when_nothing_changed(self):
        self.turn_on()
        self.s.start_card("work", "AGENT-1", None)
        self.s.update("work", 100, "done", status="done")            # no open card and no wait: away, and it stays away
        agentstates.sample(self.s, self.now)
        self.assertEqual(agentstates.sample(self.s, self.now + timedelta(minutes=14, seconds=59)), 0)
        later = self.now + timedelta(minutes=15)
        self.assertEqual(agentstates.sample(self.s, later), 1)
        self.assertEqual([x["at"] for x in self.lines()][-1], later.strftime("%Y-%m-%dT%H:%M:%S"))

    def test_a_wait_running_under_the_name_is_listening(self):
        self.turn_on()
        self.s.start_card("work", "AGENT-1", None)
        self.s.update("work", 100, "done", status="done")
        listeners.register(self.s.dir, "AGENT-1", "inbox", pid=os.getpid())
        self.addCleanup(listeners.unregister, self.s.dir, "AGENT-1", os.getpid())
        agentstates.sample(self.s, self.now)
        self.assertEqual(self.lines()[-1]["state"], "listening")

    def test_a_line_has_a_time_a_name_and_a_state_and_no_text(self):
        self.turn_on()
        self.s.start_card("SECRET WORDS in a title", "AGENT-1", None)
        agentstates.sample(self.s, self.now)
        raw = (self.s.dir / agentstates.FILE).read_text()
        self.assertNotIn("SECRET", raw)
        self.assertEqual(sorted(json.loads(raw.splitlines()[0])), ["agent", "at", "state"])

    def test_a_big_file_rolls_to_dot_one_and_every_agent_starts_the_new_one(self):
        self.turn_on()
        self.s.start_card("work", "AGENT-1", None)
        with mock.patch.object(agentstates, "MAX_BYTES", 50):
            agentstates.sample(self.s, self.now)
            agentstates.sample(self.s, self.now + timedelta(minutes=16))           # a heartbeat that finds the file over the limit
        self.assertTrue((self.s.dir / (agentstates.FILE + ".1")).exists())
        self.assertEqual(len(self.lines()), 1)
        self.assertEqual(len(agentstates.read(self.s.dir)), 2)                     # the reader joins the two files

    def test_read_skips_lines_that_are_not_ours_and_returns_them_oldest_first(self):
        p = self.s.dir / agentstates.FILE
        p.write_text('{"at": "2026-11-14T10:00:00", "agent": "B", "state": "away"}\nnot json\n{"at": "x", "agent": "A", "state": "working"}\n'
                     '{"at": "2026-11-14T09:00:00", "agent": "A", "state": "bogus"}\n{"at": "2026-11-14T09:30:00", "agent": "A", "state": "working"}\n[1, 2]\n')
        got = agentstates.read(self.s.dir)
        self.assertEqual([(a, s) for a, s, _ in got], [("A", "working"), ("B", "away")])

    def test_the_tail_read_finds_each_agents_last_line_in_a_long_file(self):
        p = self.s.dir / agentstates.FILE
        old = "".join(json.dumps({"at": "2026-11-14T08:%02d:00" % (i % 60), "agent": "A", "state": "away"}) + "\n" for i in range(5000))
        p.write_text(old + json.dumps({"at": "2026-11-14T11:59:00", "agent": "A", "state": "working"}) + "\n")
        self.assertEqual(agentstates._last_by_agent(p)["A"][0], "working")


class TheServerRunsIt(unittest.TestCase):
    def test_the_server_ticks_the_sampler_once_a_minute_in_a_thread_that_never_stops_the_board(self):
        src = (SRC / "server.py").read_text()
        m = re.search(r"def _states\(\):.*?threading\.Thread\(target=_states, daemon=True\)\.start\(\)", src, re.S)
        self.assertIsNotNone(m)
        body = m.group(0)
        self.assertIn("agentstates.sample(store)", body)
        self.assertIn("time.sleep(60)", body)
        self.assertIn("except Exception", body)


def lines(*rows):
    """State lines from (agent, state, hours after NOW's midnight 00:00) rows."""
    base = datetime(2026, 11, 14, 0, 0, 0)
    return [(a, s, base + timedelta(hours=h)) for a, s, h in rows]


def beats(agent, state, from_h, to_h):
    """A heartbeat line every 15 minutes from from_h to to_h (hours after 00:00, exclusive)."""
    out, h = [], from_h
    while h < to_h:
        out.append((agent, state, h))
        h += 0.25
    return lines(*out)


NOON = datetime(2026, 11, 14, 12, 0, 0)


class StateIntervals(unittest.TestCase):
    def test_a_state_holds_until_the_next_line_and_the_two_owner_states_are_one(self):
        iv = insights.state_intervals(lines(("A", "working", 1), ("A", "waiting", 2), ("A", "review", 3), ("A", "away", 4)), None, NOON)["A"]
        self.assertEqual([(st, round((e - s).total_seconds() / 3600, 2)) for s, e, st in iv], [("working", 0.5), ("owner", 0.5), ("owner", 0.5), ("away", 0.5)])   # each holds 30 minutes at most

    def test_heartbeats_cover_a_long_state_and_silence_is_not_covered(self):
        rows = beats("A", "listening", 1, 5) + lines(("A", "working", 9))     # four hours of beats, then nothing for four hours, then one line
        iv = insights.state_intervals(rows, None, NOON)["A"]
        self.assertAlmostEqual(sum((e - s).total_seconds() for s, e, st in iv if st == "listening") / 3600, 4.25, places=2)   # the last beat holds a further 30 minutes (15 past the next, absent, one)
        self.assertAlmostEqual(sum((e - s).total_seconds() for s, e, st in iv if st == "working") / 3600, 0.5, places=2)   # the silence in between was not watched

    def test_the_window_clips_both_ends(self):
        rows = beats("A", "working", 0, 10)
        iv = insights.state_intervals(rows, datetime(2026, 11, 14, 4, 0, 0), datetime(2026, 11, 14, 6, 0, 0))["A"]
        self.assertAlmostEqual(sum((e - s).total_seconds() for s, e, st in iv) / 3600, 2.0, places=2)


class WaitingForWork(unittest.TestCase):
    def run_rule(self, rows):
        return insights.waiting_for_work(insights.state_intervals(rows, None, NOON) if rows else None)

    def test_no_history_says_how_to_get_it(self):
        o = self.run_rule(None)[0]
        self.assertEqual(o["state"], "not-enough-data")
        self.assertIn("no state history yet", o["sentence"])

    def test_under_eight_observed_hours_is_not_enough(self):
        o = self.run_rule(beats("A", "listening", 0, 5.75))[0]        # the last beat at 5.5 h holds to 6.0 h
        self.assertEqual(o["state"], "not-enough-data")
        self.assertIn("6.0 observed hours", o["sentence"])
        self.assertIn("need 8", o["sentence"])

    def test_a_quarter_of_the_time_waiting_fires_and_names_where_the_rest_went(self):
        rows = beats("A", "listening", 0, 3) + beats("A", "working", 3, 9) + beats("A", "away", 9, 12)       # 3 of 12 h waiting for work
        o = self.run_rule(rows)[0]
        self.assertEqual((o["state"], o["value"], o["n"]), ("fires", 0.25, 12))
        self.assertIn("A waited for work 25% of the 12 hours", o["sentence"])
        self.assertEqual(o["evidence"], ["A: working 50%, waiting for work 25%, away 25%"])
        self.assertTrue(o["suggestion"])

    def test_a_busy_agent_is_quiet_and_each_agent_is_its_own_row(self):
        rows = beats("A", "working", 0, 12) + beats("B", "listening", 0, 12)
        out = self.run_rule(rows)
        self.assertEqual([(o["state"], o["evidence"][0].split(":")[0]) for o in out], [("quiet", "A"), ("fires", "B")])


class NightGapsAndHoldingSayWhereTheTimeWent(unittest.TestCase):
    def cards(self):
        """Agent A: five cards of an hour, each followed by a 7 h gap from 23:00 to 06:00 (see test_insights.TheNightsAreIdle), n = 5 gaps."""
        from tests.test_insights import card, T0
        tasks = []
        for k in range(5):
            tasks.append(card(f"a{k}", "A", created=0, claim=13 + 24 * k, review=14 + 24 * k, done=14 + 24 * k))
            tasks.append(card(f"b{k}", "A", created=0, claim=21 + 24 * k, review=22 + 24 * k, done=22 + 24 * k))
        return tasks, T0

    def test_the_gap_hours_are_split_by_what_the_agent_was_doing(self):
        tasks, t0 = self.cards()
        rows = []
        for k in range(5):   # each gap, 23:00 to 06:00 (hours 14..21 after 09:00 = 23:00..06:00): waiting for work until 03:00 then away
            g0 = t0 + timedelta(hours=14 + 24 * k)
            rows += [("A", "listening", g0 + timedelta(minutes=15 * i)) for i in range(16)] + [("A", "away", g0 + timedelta(hours=4) + timedelta(minutes=15 * i)) for i in range(12)]
        r = insights.compute(tasks, now=t0 + timedelta(days=6), states=rows)
        o = next(x for x in r["observations"] if x["rule"] == "idle-nights")
        self.assertEqual(o["state"], "fires")
        self.assertIn("in those gaps the state history shows waiting for work 57%, away 43% (100% of the gap hours are covered)", " ".join(o["evidence"]))
        self.assertIn("'away'", o["cannot_see"])

    def test_without_history_the_night_rule_keeps_its_caveat(self):
        tasks, t0 = self.cards()
        o = next(x for x in insights.compute(tasks, now=t0 + timedelta(days=6))["observations"] if x["rule"] == "idle-nights")
        self.assertIn("until agent state history is captured", o["cannot_see"])
        self.assertEqual(len(o["evidence"]), 1)

    def test_thin_history_says_how_much_it_covers_and_changes_nothing_else(self):
        tasks, t0 = self.cards()
        rows = [("A", "listening", t0 + timedelta(hours=14, minutes=15 * i)) for i in range(4)]    # an hour of one gap
        o = next(x for x in insights.compute(tasks, now=t0 + timedelta(days=6), states=rows)["observations"] if x["rule"] == "idle-nights")
        self.assertIn("covers only", o["cannot_see"])
        self.assertEqual(len(o["evidence"]), 1)

    def test_holding_gets_the_measured_split_when_enough_hours_were_watched(self):
        from tests.test_insights import card, T0
        tasks = [card(f"h{i}", "A", created=0, claim=i * 4, review=i * 4 + 1, done=i * 4 + 1) for i in range(5)]    # 5 h held over 17 h
        rows = []
        for i in range(17 * 4):
            rows.append(("A", "working" if i % 4 == 0 else "listening", T0 + timedelta(minutes=15 * i)))
        o = [x for x in insights.compute(tasks, now=T0 + timedelta(hours=18), states=rows)["observations"] if x["rule"] == "holding"][0]
        self.assertEqual(o["state"], "fires")
        self.assertIn("state history over the same span: waiting for work 75%, working 25%", " ".join(o["evidence"]))
        self.assertIn("'away'", o["cannot_see"])


class TheCommandReadsIt(Base):
    def test_the_command_passes_the_recorded_lines_to_the_rules_and_prints_the_fifth(self):
        import contextlib
        import io
        from agentboard import cli
        os.environ["AGENTBOARD_DIR"] = str(self.s.dir)
        self.turn_on()
        self.s.start_card("work", "AGENT-1", None)
        agentstates.sample(self.s, self.now)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["insights", "--since", "all", "--json"])
        d = json.loads(out.getvalue())
        wf = next(o for o in d["observations"] if o["rule"] == "waiting-for-work")
        self.assertEqual(wf["state"], "not-enough-data")
        self.assertIn("observed hours", wf["sentence"])          # there is history now, just not eight hours of it


if __name__ == "__main__":
    unittest.main()
