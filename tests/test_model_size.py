"""Model on the card and size (card agentboard-insights-model-size, docs/insights-design.md captures 6 and 8).

Part 1, the captures, on a throwaway board: `claim --model X` and `start --model X` put the model on the card; $AGENTBOARD_MODEL is read at claim only with
[insights] enabled (an implicit read must not change what a board with it off writes); a bad --model is refused and the claim does not happen; a bad value in
the environment is ignored. `add --size` and `start --size` keep S, M or L. With insights on, the first review records the size the card came out as, from its
own time since its first claim, and never again. Part 2, the rules on cards made up here with times worked out by hand: estimates miss, and kind of card
against agent or model. Nothing here touches a real board."""
import contextlib
import io
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from agentboard import cli, insights
from agentboard.store import BoardError, Store

T0 = datetime(2026, 11, 10, 9, 0, 0)


def at(h):
    return (T0 + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%S")


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
        self.s.dir.mkdir(parents=True, exist_ok=True)
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


class TheHelpers(unittest.TestCase):
    def test_model_names_are_short_identifiers(self):
        for good in ("claude-sonnet-5-5", "opus 5.5", "Fable 5.2", "gpt-5", "vendor/model:7b", "  padded  "):
            self.assertTrue(insights.clean_model(good))
        self.assertEqual(insights.clean_model("  opus   5.5 "), "opus 5.5")
        self.assertIsNone(insights.clean_model(""))
        self.assertIsNone(insights.clean_model(None))
        for bad in ("a;b", "x" * 61, "has a `tick`", "line\nbreak", "$(whoami)", "-leading"):
            with self.assertRaises(ValueError, msg=bad):
                insights.clean_model(bad)

    def test_size_of_has_its_edges_where_the_design_says(self):
        self.assertEqual([insights.size_of(h) for h in (0.0, 0.99, 1.0, 2.99, 3.0, 9.0)], ["S", "S", "M", "M", "L", "L"])

    def test_first_claim_is_the_earliest_start(self):
        log = [{"at": at(5), "text": "Claimed by B"}, {"at": at(2), "text": "Started by A"}, {"at": at(1), "text": "Added to todo"}]
        self.assertEqual(insights.first_claim(log), T0 + timedelta(hours=2))
        self.assertIsNone(insights.first_claim([{"at": at(1), "text": "Added to todo"}]))
        self.assertEqual(insights.build_size(log, at(2.5)), "S")
        self.assertIsNone(insights.build_size([], at(2.5)))
        self.assertIsNone(insights.build_size(log, at(0)))   # a clock that ran backwards gives nothing


class TheModelIsRecordedAtClaim(Base):
    def make(self, title="Fix a thing"):
        return self.s.add(title, status="todo")["id"]

    def test_with_the_flag_off_the_environment_is_not_read(self):
        os.environ["AGENTBOARD_MODEL"] = "claude-sonnet-5-5"
        t = self.make()
        self.s.claim(t, "A1")
        self.assertNotIn("model", self.card(t))
        c, _ = self.s.start_card("Another", "A2")
        self.assertNotIn("model", c)

    def test_an_explicit_model_is_kept_even_with_the_flag_off(self):
        t = self.make()
        self.s.claim(t, "A1", model="claude-sonnet-5-5")
        self.assertEqual(self.card(t)["model"], "claude-sonnet-5-5")

    def test_with_the_flag_on_the_environment_is_read_at_claim(self):
        self.turn_on()
        os.environ["AGENTBOARD_MODEL"] = "claude-haiku-5-5"
        t = self.make()
        self.s.claim(t, "A1")
        self.assertEqual(self.card(t)["model"], "claude-haiku-5-5")

    def test_an_explicit_model_beats_the_environment(self):
        self.turn_on()
        os.environ["AGENTBOARD_MODEL"] = "claude-haiku-5-5"
        t = self.make()
        self.s.claim(t, "A1", model="opus 5.5")
        self.assertEqual(self.card(t)["model"], "opus 5.5")

    def test_a_bad_value_in_the_environment_is_ignored_not_a_failed_claim(self):
        self.turn_on()
        os.environ["AGENTBOARD_MODEL"] = "oops; rm -rf"
        t = self.make()
        self.s.claim(t, "A1")
        self.assertNotIn("model", self.card(t))
        self.assertEqual(self.card(t)["agent"], "A1")

    def test_a_bad_explicit_model_refuses_the_claim_and_changes_nothing(self):
        t = self.make()
        with self.assertRaises(BoardError):
            self.s.claim(t, "A1", model="a;b")
        self.assertEqual(self.card(t)["status"], "todo")
        self.assertNotIn("agent", self.card(t))

    def test_the_next_claim_does_not_inherit_the_last_ones_model(self):
        t = self.make()
        self.s.claim(t, "A1", model="opus 5.5")
        self.s.move(t, "todo")
        self.s.claim(t, "A2")
        self.assertNotIn("model", self.card(t))
        self.s.move(t, "todo")
        self.s.claim(t, "A3", model="claude-haiku-5-5")
        self.assertEqual(self.card(t)["model"], "claude-haiku-5-5")

    def test_start_records_the_model_and_size(self):
        c, created = self.s.start_card("Fix the other", "A1", model="opus 5.5", size="s")
        self.assertTrue(created)
        self.assertEqual((c["model"], c["size"]), ("opus 5.5", "S"))

    def test_the_command_takes_the_flags(self):
        t = self.make()
        code, out = self.run_cli("claim", t, "--name", "A1", "--model", "claude-sonnet-5-5")
        self.assertIn("claimed", out)
        self.assertEqual(self.card(t)["model"], "claude-sonnet-5-5")
        code, out = self.run_cli("start", "Add the thing", "--name", "A2", "--size", "l", "--model", "opus 5.5")
        c = self.card("add-the-thing")
        self.assertEqual((c["size"], c["model"]), ("L", "opus 5.5"))
        code, out = self.run_cli("claim", self.make("Fix two"), "--name", "A3", "--model", "x;y")
        self.assertIn("a model name is at most", str(code) + out)   # a refusal is the exit message
        self.assertNotIn("agent", self.card("fix-two"))


class TheSizeIsAskedAtAdd(Base):
    def test_a_size_is_kept_in_either_case(self):
        for given, want in (("S", "S"), ("m", "M"), (" L ", "L")):
            c = self.s.add(f"card {given.strip()}", status="todo", size=given)
            self.assertEqual(c["size"], want)

    def test_no_size_writes_no_field(self):
        self.assertNotIn("size", self.s.add("plain", status="todo"))
        self.assertNotIn("size", self.s.add("blank", status="todo", size=""))

    def test_anything_else_is_refused(self):
        for bad in ("XL", "x", "3", "medium"):
            with self.assertRaises(BoardError, msg=bad):
                self.s.add("bad", status="todo", size=bad)
        self.assertEqual(self.s.load(), [])

    def test_the_command_refuses_a_bad_size_and_accepts_lower_case(self):
        code, _ = self.run_cli("add", "Bad one", "--size", "XL")
        self.assertEqual(code, 2)
        self.run_cli("add", "Good one", "--size", "m", "--status", "todo")
        self.assertEqual(self.card("good-one")["size"], "M")


class TheActualSizeIsRecordedAtTheFirstReview(Base):
    def reviewed_after(self, hours, flag=True, claim_log=True):
        if flag:
            self.turn_on()
        t = self.s.add("Fix a thing", status="todo", size="M")["id"]
        with mock.patch("agentboard.store._now", lambda: at(0)):
            if claim_log:
                self.s.claim(t, "A1")
            else:
                self.s.update(t, 10, "going", status="doing")
        with mock.patch("agentboard.store._now", lambda: at(hours)):
            self.s.review(t, "done")
        return self.card(t)

    def test_under_an_hour_is_s_under_three_is_m_and_more_is_l(self):
        for hours, want in ((0.5, "S"), (1.0, "M"), (2.9, "M"), (3.0, "L"), (8.0, "L")):
            self.setUp()
            self.assertEqual(self.reviewed_after(hours)["actual_size"], want, hours)

    def test_only_the_first_report_sets_it(self):
        t = self.reviewed_after(0.5)["id"]
        with mock.patch("agentboard.store._now", lambda: at(9)):
            self.s.review(t, "again")
        self.assertEqual(self.card(t)["actual_size"], "S")

    def test_with_the_flag_off_nothing_is_written(self):
        self.assertNotIn("actual_size", self.reviewed_after(2.0, flag=False))

    def test_a_card_with_no_claim_in_its_log_gets_none(self):
        c = self.reviewed_after(2.0, claim_log=False)
        self.assertIn("Ready for review: done", [e["text"] for e in c["log"]])   # the review still happened
        self.assertNotIn("actual_size", c)


def card(cid, title="Fix a thing", agent=None, model=None, size=None, build=None, actual=None, claim=0.0):
    """A card as tasks.json holds it; build is the hours from its claim to its first report (None: never reported)."""
    log = [{"at": at(0), "status": "todo", "progress": 0, "text": "Added to todo"}, {"at": at(claim), "status": "doing", "progress": 5, "text": f"Claimed by {agent}"}]
    if build is not None:
        log.append({"at": at(claim + build), "status": "doing", "progress": 100, "text": "Ready for review: it works"})
    t = {"id": cid, "title": title, "description": "", "status": "doing", "progress": 100 if build is not None else 5, "created": at(0), "log": log}
    for k, v in (("agent", agent), ("model", model), ("size", size), ("actual_size", actual)):
        if v:
            t[k] = v
    return t


def rule(tasks, name):
    return next(o for o in insights.compute(tasks, now=T0 + timedelta(days=3))["observations"] if o["rule"] == name)


class EstimatesMiss(unittest.TestCase):
    def test_under_five_sized_cards_is_not_enough_data(self):
        r = rule([card(f"c{i}", size="M", build=2.0) for i in range(4)] + [card("nosize", build=2.0)], "estimate-miss")
        self.assertEqual((r["state"], r["n"]), ("not-enough-data", 4))

    def test_the_actual_is_worked_out_from_the_build_time_when_none_was_stored(self):
        tasks = [card(f"c{i}", size="S", build=2.0) for i in range(5)]       # all took 2 h: M, bigger than S
        r = rule(tasks, "estimate-miss")
        self.assertEqual((r["state"], r["value"]), ("fires", 1.0))
        self.assertIn("5 of 5", r["sentence"])
        self.assertEqual(r["evidence"][0], "Estimated → came out: S→M 5")

    def test_a_stored_actual_wins_over_the_log(self):
        tasks = [card(f"c{i}", size="M", build=0.2, actual="L") for i in range(5)]
        r = rule(tasks, "estimate-miss")
        self.assertEqual(r["value"], 1.0)
        self.assertIn("M→L 5", r["evidence"][0])

    def test_forty_percent_fires_and_thirty_nine_does_not(self):
        base = [card(f"ok{i}", size="M", build=2.0) for i in range(3)]       # M, M: as estimated
        r = rule(base + [card("big1", size="M", build=4.0), card("big2", size="S", build=4.0)], "estimate-miss")
        self.assertEqual((r["state"], r["value"]), ("fires", 0.4))
        self.assertIn("big2 grew by 2 sizes", " ".join(r["evidence"]))
        r = rule(base + [card("fine", size="M", build=2.0)] + [card("a", size="M", build=4.0)] + [card(f"x{i}", size="L", build=4.0) for i in range(3)], "estimate-miss")
        self.assertEqual(r["state"], "quiet")                                 # 1 of 8
        self.assertEqual(r["suggestion"], "")

    def test_a_card_that_came_out_smaller_is_not_a_miss(self):
        tasks = [card(f"c{i}", size="L", build=0.3) for i in range(5)]
        self.assertEqual(rule(tasks, "estimate-miss")["state"], "quiet")

    def test_it_says_what_it_cannot_see(self):
        r = rule([card(f"c{i}", size="S", build=2.0) for i in range(5)], "estimate-miss")
        self.assertIn("not lines changed", r["cannot_see"])


class KindAgainstAgentOrModel(unittest.TestCase):
    def cells(self, kind_title, a, b, key="agent", n_a=5, n_b=5):
        mk = (lambda i, who, h: card(f"{who}{i}", title=kind_title, build=h, **{key: who}))
        return [mk(i, "A1", a) for i in range(n_a)] + [mk(i, "A2", b) for i in range(n_b)]

    def test_one_cell_with_five_cards_is_not_enough_data(self):
        r = rule(self.cells("Fix thing", 1.0, 2.0, n_a=6, n_b=3), "kind-agent")
        self.assertEqual(r["state"], "not-enough-data")
        self.assertIn("largest cell has 6", r["sentence"])

    def test_a_cell_under_five_cards_is_left_out(self):
        self.assertEqual(rule(self.cells("Fix thing", 1.0, 2.0, n_b=4), "kind-agent")["state"], "not-enough-data")

    def test_two_cells_one_under_seventy_percent_of_the_other_fires(self):
        r = rule(self.cells("Fix thing", 1.0, 2.0), "kind-agent")          # 1.0 against 2.0: 50%
        self.assertEqual((r["state"], r["value"], r["n"]), ("fires", 0.5, 10))
        self.assertIn("Fixed cards: A1 took a median 1.0 h to build (5 cards) against 2.0 h for the other agents (5 cards), 50% of their time, under 70%.", r["sentence"])
        self.assertIn("Fixed / A1: 5 cards, median 1.0 h", r["evidence"][0])
        self.assertIn("A1 on Fixed cards", r["suggestion"])

    def test_seventy_percent_exactly_and_above_is_quiet(self):
        r = rule(self.cells("Fix thing", 1.4, 2.0), "kind-agent")          # 70%: not under it
        self.assertEqual((r["state"], r["suggestion"]), ("quiet", ""))
        self.assertEqual(rule(self.cells("Fix thing", 1.8, 2.0), "kind-agent")["state"], "quiet")

    def test_kinds_are_compared_separately(self):
        mixed = [card(f"f{i}", title="Fix thing", build=1.0, agent="A1") for i in range(5)] + [card(f"a{i}", title="Add thing", build=2.0, agent="A2") for i in range(5)]
        self.assertEqual(rule(mixed, "kind-agent")["state"], "not-enough-data")   # A1 only fixed, A2 only added: no kind has two agents

    def test_the_model_dimension_works_the_same_way(self):
        r = rule(self.cells("Fix thing", 1.0, 3.0, key="model"), "kind-model")
        self.assertEqual((r["state"], r["n"]), ("fires", 10))
        self.assertIn("other models", r["sentence"])
        self.assertEqual(rule(self.cells("Fix thing", 1.0, 3.0, key="model"), "kind-agent")["state"], "not-enough-data")   # no agent set on these

    def test_it_names_agents_only_in_the_sentence_about_them_and_never_a_title(self):
        tasks = self.cells("Fix the quasar thing", 1.0, 2.0)
        result = insights.compute(tasks, now=T0 + timedelta(days=3))
        text = insights.render(result) + insights.as_json(result)
        self.assertNotIn("quasar", text)
        self.assertIn("A1", text)

    def test_the_thresholds_are_in_the_json(self):
        th = insights.compute([], now=T0)["thresholds"]
        self.assertEqual((th["kind_ratio"], th["estimate_miss_share"], th["size_s_h"]), (0.7, 0.4, 1.0))


if __name__ == "__main__":
    unittest.main()
