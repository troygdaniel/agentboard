"""Insights v0 (card agentboard-insights-v0, docs/insights-design.md): three small captures behind [insights] enabled = true, and `agentboard insights`.

Part 1, the captures, on a throwaway board: with the flag off the board writes exactly what it always did; with it on a card made with blockers logs them, a
card whose last blocker finishes gets an "Unblocked" line, the name that made a card is kept in the log entry's `actor`, and a card closed without a reason is
"shipped". Part 2, the four rules, on cards made up here with times worked out by hand: blocked cards wait, a few cards hold the hours, the nights are idle,
a card in hand. Each says "not enough data" under 5 samples, fires at its threshold, and prints only counts, timings and ids. Nothing here touches a real board."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from agentboard import cli, insights
from agentboard.store import BoardError, Store

T0 = datetime(2026, 11, 10, 9, 0, 0)   # a Tuesday morning: every time below is T0 plus hours worked out by hand


def at(h):
    return (T0 + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%S")


def card(cid, agent=None, created=0.0, claim=None, review=None, done=None, blocked_by=(), blocked_at=None, unblocked_at=None, title="a card", parent_id=None):
    """A card as tasks.json holds it, with its log built from the hours given (None: the event never happened)."""
    log = [{"at": at(created), "status": "todo", "progress": 0, "text": "Added to todo"}]
    if blocked_at is not None:
        log.append({"at": at(blocked_at), "status": "todo", "progress": 0, "text": "Blocked by something"})
    if claim is not None:
        log.append({"at": at(claim), "status": "doing", "progress": 5, "text": f"Claimed by {agent}"})
    if review is not None:
        log.append({"at": at(review), "status": "doing", "progress": 100, "text": "Ready for review: it works"})
    if unblocked_at is not None:
        log.append({"at": at(unblocked_at), "status": "todo", "progress": 0, "text": "Unblocked: every blocker is done"})
    if done is not None:
        log.append({"at": at(done), "status": "done", "progress": 100, "text": "Marked done"})
    t = {"id": cid, "title": title, "description": "", "status": "done" if done is not None else "doing", "progress": 100 if done is not None else 5,
         "created": at(created), "log": log}
    if agent:
        t["agent"] = agent
    if blocked_by:
        t["blocked_by"] = list(blocked_by)
    if parent_id:
        t["parent_id"] = parent_id
    return t


def one(result, rule):
    return next(o for o in result["observations"] if o["rule"] == rule)


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
        os.environ["AGENTBOARD_DIR"] = str(self.s.dir)

    def turn_on(self):
        self.s.dir.mkdir(parents=True, exist_ok=True)   # the folder appears with the first card; the flag may be set before it
        (self.s.dir / "config.toml").write_text("[insights]\nenabled = true\n")

    def card(self, cid):
        return next(t for t in self.s.load() if t["id"] == cid)

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                code = cli.main(list(argv))
            except SystemExit as e:
                code = e.code
        return code, out.getvalue()


class OddBoardFilesDoNotCrashTheReaders(Base):
    def test_a_log_entry_whose_text_is_not_a_string_is_skipped_not_fatal(self):
        """A hand-edited or copied board (the night sweep's odd board, Nov 15) held a log entry with a number for its text; `agentboard insights` died with
        AttributeError. The reader treats it as an empty line."""
        self.turn_on()
        self.s.add("odd", status="done")
        path = self.s.dir / "tasks.json"
        d = json.loads(path.read_text())
        d["tasks"][0]["log"] = [{"at": 12, "status": None, "progress": None, "text": 5}, {"at": "2026-11-15T10:00:00", "status": "doing", "progress": 0}]
        path.write_text(json.dumps(d))
        self.assertEqual(insights._text(d["tasks"][0]["log"][0]), "")
        self.assertEqual(insights._text("not a dict"), "")
        code, out = self.run_cli("insights")
        self.assertNotIn("Traceback", out)
        self.assertIn(code, (0, None))


class CapturesAreOffByDefault(Base):
    def test_with_the_flag_off_nothing_new_is_written(self):
        blocker = self.s.add("the blocker", status="todo")["id"]
        dep = self.s.add("waits on it", status="todo", blocked_by=[blocker], actor="ORCH")
        self.assertEqual([e["text"] for e in dep["log"]], ["Added to todo"])
        self.assertNotIn("actor", dep["log"][0])
        self.s.update(blocker, 100, "done", status="done")
        self.assertEqual([e["text"] for e in self.card(dep["id"])["log"]], ["Added to todo"])   # no Unblocked line
        self.assertNotIn("closed_as", self.card(blocker))

    def test_the_flag_is_read_from_config_toml_and_only_true_counts(self):
        self.s.dir.mkdir(parents=True, exist_ok=True)
        for text, want in (("[insights]\nenabled = true\n", True), ("[insights]\nenabled = false\n", False), ('[insights]\nenabled = "yes"\n', False), ("", False), ("[insights]\n", False)):
            (self.s.dir / "config.toml").write_text(text)
            self.assertIs(insights.enabled(self.s.dir), want, text)

    def test_the_command_says_how_to_turn_it_on(self):
        code, out = self.run_cli("insights")
        self.assertIn("Insights are off", out)
        self.assertIn("enabled = true", out)

    def test_an_explicit_reason_is_kept_even_with_the_flag_off(self):
        t = self.s.add("close me", status="doing")
        self.s.update(t["id"], 100, "done", status="done", closed_as="not-needed")
        self.assertEqual(self.card(t["id"])["closed_as"], "not-needed")


class BlockersAreLogged(Base):
    def setUp(self):
        super().setUp()
        self.turn_on()

    def test_a_card_made_with_blockers_logs_them_with_its_blockers_titles(self):
        a = self.s.add("first blocker", status="todo")["id"]
        b = self.s.add("second blocker", status="todo")["id"]
        dep = self.s.add("waits", status="todo", blocked_by=[a, b])
        self.assertEqual([e["text"] for e in dep["log"]], ["Added to todo", "Blocked by first blocker, second blocker"])

    def test_the_last_blocker_finishing_unblocks_once_and_not_before(self):
        a = self.s.add("first", status="doing")["id"]
        b = self.s.add("second", status="doing")["id"]
        dep = self.s.add("waits", status="todo", blocked_by=[a, b])["id"]
        self.s.update(a, 100, "done", status="done")
        self.assertNotIn("Unblocked: every blocker is done", [e["text"] for e in self.card(dep)["log"]])   # one is still open
        self.s.update(b, 100, "done", status="done")
        texts = [e["text"] for e in self.card(dep)["log"]]
        self.assertEqual(texts.count("Unblocked: every blocker is done"), 1)
        self.s.update(dep, 10, "started", status="doing")            # later changes do not say it again
        self.assertEqual([e["text"] for e in self.card(dep)["log"]].count("Unblocked: every blocker is done"), 1)

    def test_a_card_that_never_waited_gets_no_unblocked_line_and_a_done_dependent_none_either(self):
        a = self.s.add("blocker", status="doing")["id"]
        free = self.s.add("free", status="todo")["id"]
        dep = self.s.add("waits", status="doing", blocked_by=[a])["id"]
        self.s.update(dep, 100, "done early", status="done")
        self.s.update(a, 100, "done", status="done")
        self.assertNotIn("Unblocked", " ".join(e["text"] for e in self.card(free)["log"]))
        self.assertNotIn("Unblocked", " ".join(e["text"] for e in self.card(dep)["log"]))

    def test_start_with_force_logs_the_blockers_too(self):
        a = self.s.add("blocker", status="todo")["id"]
        t, created = self.s.start_card("forced start", "AGENT-9", None, blocked_by=[a], force=True)
        self.assertTrue(created)
        self.assertEqual([e["text"] for e in t["log"]], ["Started by AGENT-9", "Blocked by blocker"])
        self.assertEqual(t["log"][0]["actor"], "AGENT-9")


class WhoMadeTheCard(Base):
    def setUp(self):
        super().setUp()
        self.turn_on()

    def test_the_actor_is_kept_in_the_added_entry_and_never_in_by(self):
        t = self.s.add("made by ORCH", status="todo", actor="ORCH")
        self.assertEqual(t["log"][0]["actor"], "ORCH")
        self.assertNotIn("by", t["log"][0])            # `by` marks a human entry and the page styles it as one

    def test_no_name_known_means_no_actor(self):
        self.assertNotIn("actor", self.s.add("nobody said", status="todo")["log"][0])

    def test_the_cli_takes_the_name_from_the_environment(self):
        with mock.patch.dict(os.environ, {"AGENTBOARD_NAME": "ORCH"}):
            self.run_cli("add", "via the shell", "--status", "todo")
        self.assertEqual(self.card("via-the-shell")["log"][0]["actor"], "ORCH")

    def test_an_actor_is_cut_at_sixty_characters(self):
        self.assertEqual(len(self.s.add("long", status="todo", actor="x" * 200)["log"][0]["actor"]), 60)


class ClosingReason(Base):
    def setUp(self):
        super().setUp()
        self.turn_on()

    def test_done_without_a_reason_is_shipped(self):
        t = self.s.add("ship it", status="doing")["id"]
        self.s.update(t, 100, "ok", status="done")
        self.assertEqual(self.card(t)["closed_as"], "shipped")

    def test_the_reason_given_wins_and_the_cli_takes_it(self):
        t = self.s.add("a twin", status="doing")["id"]
        code, out = self.run_cli("done", t, "--reason", "duplicate")
        self.assertIn("done", out)
        self.assertEqual(self.card(t)["closed_as"], "duplicate")

    def test_a_reason_outside_the_list_is_refused_and_the_card_stays_open(self):
        t = self.s.add("not yet", status="doing")["id"]
        with self.assertRaises(BoardError):
            self.s.update(t, 100, "x", status="done", closed_as="because")
        self.assertEqual(self.card(t)["status"], "doing")
        code, out = self.run_cli("done", t, "--reason", "because")
        self.assertNotEqual(code, 0)

    def test_the_closing_list_is_the_one_the_design_names(self):
        self.assertEqual(insights.CLOSE_REASONS, ("shipped", "duplicate", "not-reproduced", "superseded", "not-needed"))


class BlockedCardsWait(unittest.TestCase):
    def blockers(self, waits, **kw):
        """One blocker per wait, finished at 10 h after T0, and a dependent made at 10 - wait hours."""
        tasks = [card("blk", "A", created=0, claim=0, review=9, done=10)]
        for i, w in enumerate(waits):
            tasks.append(card(f"dep{i}", "A", created=10 - w, claim=10, review=11, done=11, blocked_by=["blk"], **kw))
        return tasks

    def test_the_median_wait_is_measured_from_creation_to_the_blockers_done(self):
        r = insights.compute(self.blockers([1, 2, 3, 4, 10]), now=T0 + timedelta(days=1))
        o = one(r, "blocked-wait")
        self.assertEqual((o["state"], o["n"], o["value"]), ("fires", 5, 3.0))
        self.assertEqual(o["evidence"], ["dep4 10.0 h", "dep3 4.0 h", "dep2 3.0 h"])

    def test_it_is_quiet_under_the_threshold_and_fires_at_it(self):
        self.assertEqual(one(insights.compute(self.blockers([1, 1, 1, 1, 1])), "blocked-wait")["state"], "quiet")
        o = one(insights.compute(self.blockers([2, 2, 2, 2, 2])), "blocked-wait")
        self.assertEqual((o["state"], o["value"]), ("fires", 2.0))   # at least 2 h

    def test_four_samples_are_not_enough(self):
        o = one(insights.compute(self.blockers([5, 5, 5, 5])), "blocked-wait")
        self.assertEqual((o["state"], o["n"]), ("not-enough-data", 4))
        self.assertIn("need 5", o["sentence"])

    def test_the_logged_blocked_and_unblocked_times_win_over_the_guess(self):
        tasks = [card("blk", "A", created=0, claim=0, review=9, done=10)]
        for i in range(5):   # made at 0, blocked line at 4, unblocked line at 6: the wait is 2 h, not the 10 h the blocker's done time would say
            tasks.append(card(f"dep{i}", "A", created=0, claim=10, review=11, done=11, blocked_by=["blk"], blocked_at=4, unblocked_at=6))
        o = one(insights.compute(tasks), "blocked-wait")
        self.assertEqual((o["state"], o["value"]), ("fires", 2.0))

    def test_a_card_nobody_claimed_waits_for_an_assignment_not_for_its_blocker(self):
        tasks = self.blockers([5, 5, 5, 5, 5]) + [card("unclaimed", None, created=0, blocked_by=["blk"])]
        self.assertEqual(one(insights.compute(tasks), "blocked-wait")["n"], 5)

    def test_a_card_still_blocked_and_one_with_a_missing_blocker_are_left_out(self):
        tasks = self.blockers([5, 5, 5, 5, 5]) + [card("open", "A", created=0, blocked_by=["dep0x"]), card("gone", "A", created=0, claim=1, blocked_by=["no-such-card"])]
        tasks.append(card("dep0x", "A", created=0, claim=1))   # never finished
        self.assertEqual(one(insights.compute(tasks), "blocked-wait")["n"], 5)


class ABigCardsHoldTheHours(unittest.TestCase):
    def builds(self, hours):
        return [card(f"c{i}", "A", created=i * 20, claim=i * 20, review=i * 20 + h, done=i * 20 + h) for i, h in enumerate(hours)]

    def test_one_big_card_among_small_ones_fires_with_its_share(self):
        o = one(insights.compute(self.builds([0.5, 0.5, 0.5, 0.5, 4.0])), "big-cards")   # 4 of 6 build hours
        self.assertEqual((o["state"], o["n"], o["value"]), ("fires", 5, 0.67))
        self.assertEqual(o["evidence"], ["c4 4.0 h"])
        self.assertIn("1 of 5 cards took 3 h or more", o["sentence"])

    def test_evenly_sized_cards_are_quiet(self):
        o = one(insights.compute(self.builds([1, 1, 1, 1, 1])), "big-cards")
        self.assertEqual((o["state"], o["value"]), ("quiet", 0.0))
        self.assertEqual(o["suggestion"], "")

    def test_exactly_three_hours_is_big_and_forty_percent_fires(self):
        o = one(insights.compute(self.builds([3, 1, 1, 1, 1.5])), "big-cards")   # 3 of 7.5 = 40%
        self.assertEqual((o["state"], o["value"]), ("fires", 0.4))

    def test_a_card_with_no_review_has_no_build_time(self):
        tasks = self.builds([1, 1, 1, 1]) + [card("noreview", "A", created=0, claim=1, done=2)]
        self.assertEqual(one(insights.compute(tasks), "big-cards")["state"], "not-enough-data")


class TheNightsAreIdle(unittest.TestCase):
    def agent_with_gaps(self, gap_start_hour, gap_h, n=5, agent="A"):
        """n cards of one hour with a gap of gap_h after each, the first gap starting at T0 + gap_start_hour (T0 is 09:00)."""
        tasks, t = [], gap_start_hour - 1
        for i in range(n + 1):
            tasks.append(card(f"{agent}{i}", agent, created=0, claim=t, review=t + 1, done=t + 1))
            t += 1 + gap_h
        return tasks

    def test_gaps_from_23_to_06_are_mostly_night(self):
        # T0 is 09:00. Card a_k runs 22:00 to 23:00 on day k (hours 13 to 14, plus 24 a day), card b_k runs 06:00 to 07:00 the next morning (hours 21 to 22):
        # five gaps of 7 h, each with 6 night hours (00:00 to 06:00) and 1 hour before midnight. The 15 h gap from b_k to a_k+1 is over 8 h and is not counted.
        tasks = []
        for k in range(5):
            tasks.append(card(f"a{k}", "A", created=0, claim=13 + 24 * k, review=14 + 24 * k, done=14 + 24 * k))
            tasks.append(card(f"b{k}", "A", created=0, claim=21 + 24 * k, review=22 + 24 * k, done=22 + 24 * k))
        o = one(insights.compute(tasks), "idle-nights")
        self.assertEqual((o["state"], o["n"], o["value"]), ("fires", 5, 0.86))     # 30 night hours of 35
        self.assertIn("35.0 h; 30.0 h of them (86%) fall between midnight and 08:00", o["sentence"])

    def test_daytime_gaps_are_quiet(self):
        o = one(insights.compute(self.agent_with_gaps(1, 2, n=5)), "idle-nights")   # 10:00 to 12:00 gaps, 3 h cycle: some cross into the evening but none reach 00:00
        self.assertEqual(o["n"], 5)
        self.assertEqual((o["state"], o["value"]), ("quiet", 0.0))

    def test_a_gap_over_eight_hours_is_a_day_off_not_a_wait(self):
        o = one(insights.compute(self.agent_with_gaps(1, 9, n=5)), "idle-nights")
        self.assertEqual(o["state"], "not-enough-data")
        self.assertEqual(o["n"], 0)

    def test_two_cards_held_at_once_leave_no_gap_between_them(self):
        tasks = [card("x1", "A", created=0, claim=0, review=10, done=10), card("x2", "A", created=0, claim=1, review=2, done=2)]
        self.assertEqual(one(insights.compute(tasks), "idle-nights")["n"], 0)


class ACardInHand(unittest.TestCase):
    def cards(self, n, work, gap, agent="A"):
        return [card(f"{agent}{i}", agent, created=0, claim=i * (work + gap), review=i * (work + gap) + work, done=i * (work + gap) + work) for i in range(n)]

    def test_an_agent_that_holds_a_card_a_quarter_of_the_time_fires_with_the_caveat(self):
        r = insights.compute(self.cards(5, 1, 3))   # 5 h held over 17 h
        o = one(r, "holding")
        self.assertEqual((o["state"], o["n"], o["value"]), ("fires", 5, 0.29))
        self.assertIn("A held a card 29% of the time", o["sentence"])
        self.assertIn("Work that has no card", o["cannot_see"])

    def test_back_to_back_cards_are_quiet(self):
        o = one(insights.compute(self.cards(5, 2, 0)), "holding")
        self.assertEqual((o["state"], o["value"]), ("quiet", 1.0))

    def test_an_agent_with_four_cards_is_not_enough_data_and_each_agent_is_its_own_row(self):
        r = insights.compute(self.cards(5, 1, 3, "A") + self.cards(4, 1, 3, "B"))
        rows = [o for o in r["observations"] if o["rule"] == "holding"]
        self.assertEqual([(o["state"], o["evidence"][0].split()[0]) for o in rows], [("fires", "A")])
        r2 = insights.compute(self.cards(4, 1, 3, "B"))
        self.assertEqual(one(r2, "holding")["state"], "not-enough-data")


class FiltersAndSafety(unittest.TestCase):
    def test_since_agent_and_prefix_pick_the_cards(self):
        tasks = [card(f"x-{i}", "A", created=0, claim=i, review=i + 1, done=i + 1) for i in range(6)] + [card("y-0", "B", created=0, claim=0, review=1, done=1)]
        self.assertEqual(insights.compute(tasks)["cards"], 7)
        self.assertEqual(insights.compute(tasks, agent="a")["cards"], 6)
        self.assertEqual(insights.compute(tasks, prefix="y-")["cards"], 1)
        self.assertEqual(insights.compute(tasks, since=T0 + timedelta(hours=4))["cards"], 3)   # last events at 5, 6, 7 h: x-4, x-5 ... counted by their last event

    def test_subtasks_are_not_cards_of_their_own(self):
        tasks = [card("p", "A", created=0, claim=0, review=1, done=1), card("p-sub", "A", created=0, claim=0, review=1, done=1, parent_id="p")]
        self.assertEqual(insights.compute(tasks)["cards"], 1)

    def test_the_output_has_ids_numbers_and_templates_but_never_card_text(self):
        tasks = self.secret_board()
        r = insights.compute(tasks)
        for text in (insights.render(r), insights.as_json(r)):
            self.assertNotIn("SECRETWORD", text)
            self.assertNotIn("PRIVATEDESC", text)

    @staticmethod
    def secret_board():
        tasks = [card("blk", "A", created=0, claim=0, review=9, done=10, title="SECRETWORD blocker")]
        for i in range(5):
            t = card(f"dep{i}", "A", created=0, claim=10 + i * 8, review=11 + i * 8, done=11 + i * 8, blocked_by=["blk"], title=f"SECRETWORD {i}")
            t["description"] = "PRIVATEDESC"
            t["result"] = "PRIVATEDESC"
            tasks.append(t)
        return tasks

    def test_garbage_in_the_cards_never_raises(self):
        junk = [{"id": "a"}, {"id": "b", "log": "not a list", "created": "yesterday"}, {"id": "c", "log": [None, 5, {"at": "x", "text": None}], "blocked_by": [1, None]},
                {"id": "d", "created": "2026-11-10T09:00:00", "claim": 3, "log": [{"at": "2026-13-45T99:00:00", "text": "Claimed by A"}]}, "not a card", None]
        r = insights.compute(junk)
        self.assertEqual(r["cards"], 4)
        insights.render(r)
        insights.as_json(r)

    def test_parse_since(self):
        now = datetime(2026, 11, 14, 12, 0, 0)
        self.assertEqual(insights.parse_since("7d", now), now - timedelta(days=7))
        self.assertEqual(insights.parse_since("24h", now), now - timedelta(hours=24))
        self.assertIsNone(insights.parse_since("all", now))
        for bad in ("week", "0d", "-3d", "7", "d7", ""):
            if bad == "":
                self.assertEqual(insights.parse_since(bad, now), now - timedelta(days=7))   # empty means the default
            else:
                with self.assertRaises(ValueError):
                    insights.parse_since(bad, now)


class TheCommand(Base):
    def setUp(self):
        super().setUp()
        self.turn_on()
        blk = self.s.add("blocker", status="doing")["id"]
        self.s.update(blk, 100, "ok", status="done")

    def test_text_output_has_the_head_and_a_block_for_every_rule(self):
        code, out = self.run_cli("insights", "--since", "all")
        self.assertIn("Insights over", out)
        self.assertIn("counts and timings only", out)
        self.assertIn("[not-enough-data] Blocked cards wait", out)
        self.assertIn("A few cards hold the hours", out)
        self.assertIn("The nights are idle", out)

    def test_json_output_parses_and_carries_the_thresholds(self):
        code, out = self.run_cli("insights", "--json", "--since", "30d")
        d = json.loads(out)
        self.assertEqual(d["thresholds"]["min_n"], 5)
        self.assertEqual({o["rule"] for o in d["observations"]}, {"blocked-wait", "big-cards", "idle-nights", "rework", "estimate-miss", "kind-agent", "kind-model", "holding", "waiting-for-work"})
        self.assertTrue(all(o["state"] in ("fires", "quiet", "not-enough-data") for o in d["observations"]))

    def test_a_bad_since_says_the_allowed_shapes(self):
        code, out = self.run_cli("insights", "--since", "yesterday")
        self.assertNotEqual(code, 0)
        self.assertIn("7d, 24h or all", str(code))   # sys.exit(message): the message is the exit status

    def test_it_is_read_only(self):
        before = (self.s.dir / "tasks.json").read_bytes()
        self.run_cli("insights", "--since", "all")
        self.assertEqual((self.s.dir / "tasks.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
