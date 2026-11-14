"""One rework event (card agentboard-insights-rework-event, docs/insights-design.md capture 5, src/agentboard/rework.py).

Part 1, the capture, on a throwaway board: with [insights] off the board writes exactly the log it always did; with it on each path that sends a card back
writes ONE `Rework: <code>` line (the dedicated send-back, a reply to a card in review, a move out of Done, a second "Ready for review"), a review that follows a
request adds no second line, and a line is the code and nothing else. Part 2, the rule "Work comes back" in insights.py, on cards made up here with the
counts worked out by hand: not enough data under 5 cards, fires at 20%, says the reasons and the kinds, reads the traces older cards left, and prints no
title or note. Nothing here touches a real board."""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from agentboard import insights, rework
from agentboard.store import BoardError, Store

T0 = datetime(2026, 11, 10, 9, 0, 0)
BE_SIMPLER_REPLY = "Be simpler: one line. What is the one thing I need to do?"   # what the board's Be simpler button sends


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

    def log(self, cid):
        return [e["text"] for e in next(t for t in self.s.load() if t["id"] == cid)["log"]]

    def reworks(self, cid):
        return [x for x in self.log(cid) if x.startswith("Rework:")]

    def reviewed(self, title="Fix the thing"):
        t = self.s.add(title, status="doing")["id"]
        self.s.review(t, "first report")
        return t


class TheCodes(unittest.TestCase):
    def test_a_line_is_the_prefix_and_a_known_code(self):
        self.assertEqual(rework.line("sent-back"), "Rework: sent-back")
        with self.assertRaises(ValueError):
            rework.line("because I said so")

    def test_code_of_reads_only_lines_this_version_knows(self):
        for code in rework.CODES:
            self.assertEqual(rework.code_of(rework.line(code)), code)
        for text in ("Ready for review: it works", "Rework: something-new", "Rework:", "", None, "rework: sent-back"):
            self.assertIsNone(rework.code_of(text), text)

    def test_the_button_words_are_be_simpler_and_everything_else_is_a_change_request(self):
        self.assertEqual(rework.reply_code(BE_SIMPLER_REPLY), rework.BE_SIMPLER)
        self.assertEqual(rework.reply_code("  Be simpler"), rework.BE_SIMPLER)
        self.assertEqual(rework.reply_code("Use the other colour"), rework.CHANGES_ASKED)
        self.assertEqual(rework.reply_code(""), rework.CHANGES_ASKED)

    def test_explained_means_a_rework_line_after_the_last_report(self):
        log = lambda *texts: [{"text": x} for x in texts]   # noqa: E731
        self.assertFalse(rework.explained(log()))
        self.assertFalse(rework.explained(log("Added to doing", "Ready for review: a")))
        self.assertTrue(rework.explained(log("Ready for review: a", "Rework: sent-back")))
        self.assertFalse(rework.explained(log("Ready for review: a", "Rework: sent-back", "Ready for review: b")))   # that one was used up by b
        self.assertTrue(rework.explained(log("Ready for review: a", "Rework: be-simpler", "Ready for review: b", "Rework: reopened")))
        self.assertFalse(rework.explained(log("Ready for review: a", "Ready for review: b", "Rework: re-reviewed")))   # b's own line is no request for c
        self.assertTrue(rework.reviewed_before(log("Ready for review: a")))
        self.assertFalse(rework.reviewed_before(log("Added to doing")))


class WithTheFlagOffNothingIsWritten(Base):
    def test_every_path_leaves_the_log_as_it_always_was(self):
        t = self.reviewed()
        self.s.reply(t, BE_SIMPLER_REPLY)
        self.s.review(t, "second report")
        self.s.send_back(t, "redo it")
        self.s.review(t, "third report")
        self.s.review(t, "fourth report")
        self.s.update(t, 100, "done", status="done")
        self.s.move(t, "doing")
        self.assertEqual(self.reworks(t), [])
        self.assertEqual(self.log(t), ["Added to doing", "Ready for review: first report", BE_SIMPLER_REPLY, "Ready for review: second report", "Sent back: redo it",
                                       "Ready for review: third report", "Ready for review: fourth report", "Marked done", "Moved to doing"])


class EachPathWritesOneLine(Base):
    def setUp(self):
        super().setUp()
        self.turn_on()

    def test_the_dedicated_send_back(self):
        t = self.reviewed()
        self.s.send_back(t, "please redo the part about xyzzy")
        self.assertEqual(self.reworks(t), ["Rework: sent-back"])

    def test_the_be_simpler_button_on_a_card_in_review(self):
        t = self.reviewed()
        self.s.reply(t, BE_SIMPLER_REPLY)
        self.assertEqual(self.reworks(t), ["Rework: be-simpler"])

    def test_any_other_reply_to_a_card_in_review_is_a_change_request(self):
        t = self.reviewed()
        self.s.reply(t, "use the other colour")
        self.assertEqual(self.reworks(t), ["Rework: changes-asked"])

    def test_a_reply_to_a_card_that_is_not_in_review_is_not_rework(self):
        t = self.s.add("Fix the thing", status="doing")["id"]
        self.s.reply(t, BE_SIMPLER_REPLY)                       # still being worked on: a note, not a change request
        self.s.ask(t, "which one?")
        self.s.reply(t, "the second")
        self.s.review(t, "report")
        self.s.update(t, 100, "done", status="done")
        self.s.reply(t, "thanks")                                # closed: nothing to change
        self.assertEqual(self.reworks(t), [])

    def test_a_card_moved_out_of_done_is_reopened(self):
        t = self.reviewed()
        self.s.update(t, 100, "done", status="done")
        self.s.move(t, "doing")
        self.assertEqual(self.reworks(t), ["Rework: reopened"])
        self.s.update(t, 100, "done", status="done")
        self.s.move(t, "todo")                                   # any column out of Done
        self.assertEqual(self.reworks(t), ["Rework: reopened", "Rework: reopened"])

    def test_ordinary_moves_are_not_rework(self):
        t = self.s.add("Fix the thing", status="todo")["id"]
        self.s.move(t, "doing")
        self.s.move(t, "backlog")
        self.s.move(t, "todo")
        self.s.move(t, "done")                                   # into Done is closing, not rework
        self.s.move(t, "done")                                   # no change of column: nothing happens
        self.assertEqual(self.reworks(t), [])

    def test_the_first_report_is_not_rework_and_a_bare_second_report_is(self):
        t = self.reviewed()
        self.assertEqual(self.reworks(t), [])
        self.s.review(t, "second report, nobody asked")
        self.assertEqual(self.reworks(t), ["Rework: re-reviewed"])
        self.s.review(t, "third report, nobody asked")
        self.assertEqual(self.reworks(t), ["Rework: re-reviewed", "Rework: re-reviewed"])


class ARequestAndItsReviewAreOneRework(Base):
    def setUp(self):
        super().setUp()
        self.turn_on()

    def test_a_review_after_a_reply_adds_no_second_line(self):
        t = self.reviewed()
        self.s.reply(t, BE_SIMPLER_REPLY)
        self.s.review(t, "shorter")
        self.assertEqual(self.reworks(t), ["Rework: be-simpler"])

    def test_a_review_after_a_send_back_adds_no_second_line(self):
        t = self.reviewed()
        self.s.send_back(t, "redo it")
        self.s.review(t, "redone")
        self.assertEqual(self.reworks(t), ["Rework: sent-back"])

    def test_a_review_after_a_reopen_adds_no_second_line(self):
        t = self.reviewed()
        self.s.update(t, 100, "done", status="done")
        self.s.move(t, "doing")
        self.s.review(t, "fixed")
        self.assertEqual(self.reworks(t), ["Rework: reopened"])

    def test_a_long_round_trip_is_one_line_per_cause(self):
        t = self.reviewed()
        self.s.reply(t, BE_SIMPLER_REPLY)
        self.s.review(t, "second")
        self.s.send_back(t, "redo")
        self.s.review(t, "third")
        self.s.review(t, "fourth, nobody asked")
        self.s.update(t, 100, "done", status="done")
        self.s.move(t, "doing")
        self.assertEqual(self.reworks(t), ["Rework: be-simpler", "Rework: sent-back", "Rework: re-reviewed", "Rework: reopened"])


class CountsOnly(Base):
    def setUp(self):
        super().setUp()
        self.turn_on()

    def test_a_rework_line_never_holds_the_owners_or_the_agents_words(self):
        t = self.reviewed("Fix the xyzzy title")
        self.s.reply(t, "the plugh is wrong, redo it")
        self.s.review(t, "report about the quux")
        self.s.send_back(t, "the owner's private note")
        lines = self.reworks(t)
        self.assertEqual(lines, ["Rework: changes-asked", "Rework: sent-back"])
        for x in lines:
            for word in ("plugh", "quux", "xyzzy", "private", "redo"):
                self.assertNotIn(word, x)

    def test_a_subtask_has_no_review_step_so_it_writes_none(self):
        parent = self.s.add("Fix the parent", status="doing")["id"]
        kid = self.s.add("step one", status="doing", parent_id=parent)["id"]
        self.s.review(kid, "done")                # a subtask's report is just 100%
        self.assertEqual(self.reworks(kid), [])
        with self.assertRaises(BoardError):
            self.s.send_back(kid, "no")


def card(cid, title="Fix a thing", reviews=1, sent_back=False, codes=(), parent_id=None):
    """A card as tasks.json holds it, its log made from what happened (a count of reports, an old-style Sent back line, rework lines)."""
    log = [{"at": at(0), "status": "todo", "progress": 0, "text": "Added to todo"}, {"at": at(1), "status": "doing", "progress": 5, "text": "Claimed by AGENT-1"}]
    for i in range(reviews):
        log.append({"at": at(2 + i), "status": "doing", "progress": 100, "text": f"Ready for review: report {i + 1} about the zork"})
    if sent_back:
        log.append({"at": at(9), "status": "doing", "progress": 95, "text": "Sent back: the zork note", "by": "owner"})
    for c in codes:
        log.append({"at": at(9), "status": "doing", "progress": 95, "text": rework.line(c)})
    t = {"id": cid, "title": title, "description": "", "status": "done", "progress": 100, "created": at(0), "agent": "AGENT-1", "log": log}
    if parent_id:
        t["parent_id"] = parent_id
    return t


def rule(tasks):
    return next(o for o in insights.compute(tasks, now=T0 + timedelta(days=3))["observations"] if o["rule"] == "rework")


class WorkComesBack(unittest.TestCase):
    def test_under_five_cards_is_not_enough_data(self):
        r = rule([card(f"c{i}") for i in range(4)])
        self.assertEqual(r["state"], "not-enough-data")
        self.assertEqual(r["n"], 4)

    def test_a_card_never_reported_finished_is_not_in_the_count(self):
        tasks = [card(f"c{i}") for i in range(4)] + [card("late", reviews=0)]
        self.assertEqual(rule(tasks)["state"], "not-enough-data")   # four seen, the fifth was never reported

    def test_ten_cards_one_back_is_quiet(self):
        tasks = [card(f"c{i}") for i in range(9)] + [card("back", reviews=2)]
        r = rule(tasks)
        self.assertEqual((r["state"], r["n"], r["value"]), ("quiet", 10, 0.1))
        self.assertEqual(r["suggestion"], "")
        self.assertIn("1 of 10", r["sentence"])

    def test_exactly_twenty_percent_fires(self):
        tasks = [card(f"c{i}") for i in range(8)] + [card("a", reviews=2), card("b", sent_back=True)]
        r = rule(tasks)
        self.assertEqual((r["state"], r["value"], r["threshold"]), ("fires", 0.2, insights.REWORK_SHARE))
        self.assertIn("2 of 10", r["sentence"])

    def test_the_reasons_are_counted_and_the_commonest_picks_the_suggestion(self):
        tasks = [card(f"c{i}") for i in range(6)] + [
            card("a", reviews=2, codes=["be-simpler"]), card("b", reviews=2, codes=["be-simpler", "sent-back"]), card("c", codes=["be-simpler"]),
            card("d", reviews=2)]                                    # came back, no reason on record (before the capture)
        r = rule(tasks)
        self.assertEqual(r["state"], "fires")
        self.assertEqual(r["evidence"][0], "Reasons (every rework line): be-simpler 3, sent-back 1, no reason recorded 1")
        self.assertEqual(r["suggestion"], insights.REWORK_SAYS["be-simpler"])

    def test_cards_from_before_the_capture_count_by_their_old_traces(self):
        tasks = [card(f"c{i}") for i in range(6)] + [card("two", reviews=2), card("old", sent_back=True), card("both", reviews=3, sent_back=True)]
        r = rule(tasks)
        self.assertIn("3 of 9", r["sentence"])
        self.assertIn("no reason recorded 3", r["evidence"][0])
        self.assertIn("with insights on", r["suggestion"])           # no reason anywhere: the suggestion says the next ones will carry one

    def test_a_rework_line_alone_counts_even_with_one_report(self):
        tasks = [card(f"c{i}") for i in range(5)] + [card("x", reviews=1, codes=["reopened"])]
        self.assertIn("1 of 6", rule(tasks)["sentence"])

    def test_kinds_with_five_cards_are_shown_with_their_own_share(self):
        fixes = [card(f"f{i}", title=f"Fix thing {i}", reviews=2 if i < 3 else 1) for i in range(6)]        # 3 of 6
        adds = [card(f"a{i}", title=f"Add thing {i}") for i in range(5)]                                      # 0 of 5
        few = [card(f"d{i}", title=f"Docs page {i}", reviews=2) for i in range(2)]                            # all back, but only 2 cards: not shown
        ev = rule(fixes + adds + few)["evidence"]
        self.assertIn("Fixed: 3 of 6 came back (50%)", ev)
        self.assertIn("Added: 0 of 5 came back (0%)", ev)
        self.assertFalse(any(x.startswith("Documented") for x in ev))

    def test_subtasks_are_not_cards_here(self):
        tasks = [card(f"c{i}") for i in range(5)] + [card("kid", reviews=3, parent_id="c0")]
        self.assertEqual(rule(tasks)["n"], 5)

    def test_it_prints_counts_and_ids_never_a_title_or_a_note(self):
        tasks = [card(f"c{i}", title="Fix the quasar thing") for i in range(6)] + [card("back", title="Fix the quasar thing", sent_back=True, codes=["sent-back"])]
        result = insights.compute(tasks, now=T0 + timedelta(days=3))
        for text in (insights.render(result), insights.as_json(result)):
            for word in ("quasar", "zork"):
                self.assertNotIn(word, text)
        self.assertIn("Work comes back", insights.render(result))

    def test_the_threshold_is_in_the_json(self):
        d = json.loads(insights.as_json(insights.compute([card(f"c{i}") for i in range(5)], now=T0 + timedelta(days=3))))
        self.assertEqual(d["thresholds"]["rework_share"], 0.2)


class TheCommandShowsIt(Base):
    def test_a_board_that_reworks_prints_the_rule_with_its_reasons(self):
        from agentboard import cli
        import contextlib
        import io
        self.turn_on()
        ids = []
        for i in range(8):
            t = self.s.add(f"Fix thing {i}", status="doing")["id"]
            self.s.review(t, "report")
            ids.append(t)
        self.s.reply(ids[0], BE_SIMPLER_REPLY)
        self.s.send_back(ids[1], "redo")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                cli.main(["insights", "--since", "all"])
            except SystemExit:
                pass
        text = out.getvalue()
        self.assertIn("[fires] Work comes back: 2 of 8 cards that were reported finished came back (25%)", text)
        self.assertIn("be-simpler 1, sent-back 1", text)
        self.assertNotIn("redo", text)


if __name__ == "__main__":
    unittest.main()
