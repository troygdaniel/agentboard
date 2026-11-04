"""The red "Needs your input" clears when the agent has read the reply or next reports on the card (Nov 4).

It used to clear only on an update to the card itself. An agent's progress arrives as subtask updates, so a question asked on the card
stayed red for as long as the agent kept working on subtasks, long after it had read "Go ahead"."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli, hud, nav
from agentboard.store import Store

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        env["AGENTBOARD_DIR"] = str(self.s.dir)
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def card(self, cid):
        return Store.get(self.s.load(), cid)

    def asking(self, cid="deploy"):
        return bool(self.card(cid).get("needs_input"))

    def asked(self, question="Staging or prod?", steps=("one", "two")):
        """AGENT-1's shape: a card with subtasks, the question asked on the card itself."""
        self.s.start("Deploy", "alice")
        for step in steps:
            self.s.add(step, parent_id="deploy")
        self.s.ask("deploy", question)
        return [self.card("deploy")["id"]] + [k["id"] for k in self.s.load() if k.get("parent_id") == "deploy"]


class ReadingTheReply(Base):
    """Way 1: the agent reads the reply with `answer`."""

    def test_an_unread_reply_leaves_the_card_asking(self):
        self.asked()
        self.s.reply("deploy", "Go ahead")
        self.assertTrue(self.asking())

    def test_reading_a_quick_reply_clears_the_ask(self):
        self.asked()
        self.s.reply("deploy", "Go ahead")
        self.assertEqual(self.s.answer("deploy")["text"], "Go ahead")
        c = self.card("deploy")
        self.assertFalse(c.get("needs_input"))
        self.assertNotIn("question", c)
        self.assertNotIn("body_md", c)

    def test_reading_a_typed_reply_clears_the_ask(self):
        self.asked()
        self.s.reply("deploy", "Use prod, but after 6pm")
        self.s.answer("deploy")
        self.assertFalse(self.asking())

    def test_the_card_stops_showing_the_question_as_its_status_line(self):
        self.asked("Staging or prod?")
        self.s.reply("deploy", "prod")
        self.s.answer("deploy")
        self.assertNotEqual(self.card("deploy")["status_text"], "Staging or prod?")

    def test_the_history_says_the_reply_was_read(self):
        self.asked()
        self.s.reply("deploy", "Go ahead")
        self.s.answer("deploy")
        self.assertEqual(self.card("deploy")["log"][-1]["text"], "Reply read")

    def test_polling_after_the_first_read_does_not_write_again(self):
        self.asked()
        self.s.reply("deploy", "Go ahead")
        self.s.answer("deploy")
        before = (self.s.dir / "tasks.json").read_text()
        self.s.answer("deploy")
        self.assertEqual((self.s.dir / "tasks.json").read_text(), before)

    def test_the_command_line_read_clears_it_too(self):
        self.asked()
        self.s.reply("deploy", "Go ahead")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["answer", "deploy"])
        self.assertFalse(self.asking())

    def test_the_header_count_and_hud_drop_it(self):
        self.asked()
        self.assertEqual(hud.build(self.s.load())["totals"]["waiting"], 1)
        self.s.reply("deploy", "Go ahead")
        self.s.answer("deploy")
        self.assertEqual(hud.build(self.s.load())["totals"]["waiting"], 0)

    def test_a_question_asked_on_a_subtask_clears_on_the_card_and_the_subtask(self):
        self.s.start("Deploy", "alice")
        self.s.add("one", parent_id="deploy")
        self.s.ask("one", "Which region?")
        self.assertTrue(self.asking())
        self.s.reply("deploy", "eu-west")
        self.s.answer("deploy")
        self.assertFalse(self.asking())
        self.assertNotIn("ask_child", self.card("deploy"))
        self.assertNotIn("needs_input", self.card("one"))

    def test_a_state_note_does_not_clear_a_question_by_being_read(self):
        """Undoing a move can put back a card that is still waiting on you: "Restored by you" is not an answer."""
        self.asked()
        self.s.reply("deploy", "x")
        self.s.answer("deploy")
        self.s.ask("deploy", "Staging or prod?")   # asks again; ask() drops the old answer
        with self.s.transaction() as tasks:
            Store.get(tasks, "deploy")["reply"] = {"text": "Restored by the user: the card is back in Doing and yours again.",
                                                   "at": "2026-11-04T17:00:00", "by": "x", "state": True}
        self.s.answer("deploy")
        self.assertTrue(self.asking())

    def test_reading_a_reply_on_a_card_that_is_not_asking_changes_nothing(self):
        self.s.start("Deploy", "alice")
        self.s.add("one", parent_id="deploy")
        self.s.reply("deploy", "just so you know")
        updated = self.card("deploy")["updated"]
        self.s.answer("deploy")
        c = self.card("deploy")
        self.assertEqual(c["updated"], updated)
        self.assertNotEqual(c["log"][-1]["text"], "Reply read")


class ReportingOnTheCard(Base):
    """Way 2: the agent next reports on the card, without having read the reply."""

    def test_an_update_on_the_card_itself_clears_it(self):
        self.s.start("Plain", "alice")
        self.s.ask("plain", "Staging or prod?")
        self.s.update("plain", 40, "going with prod")
        self.assertFalse(self.asking("plain"))

    def test_an_update_on_a_subtask_clears_a_question_asked_on_the_card(self):
        """The bug: the red stayed while the agent worked its subtasks."""
        self.asked()
        self.s.reply("deploy", "Go ahead")
        self.s.update("one", 50, "building")
        c = self.card("deploy")
        self.assertFalse(c.get("needs_input"))
        self.assertNotIn("question", c)

    def test_the_subtask_update_wins_even_with_the_reply_unread(self):
        self.asked()
        self.s.update("one", 50, "building")
        self.assertFalse(self.asking())

    def test_a_subtask_finishing_clears_it(self):
        self.asked()
        self.s.update("one", 100, "built")
        self.assertFalse(self.asking())

    def test_the_card_shows_the_subtask_note_after_the_question_clears(self):
        self.asked("Staging or prod?")
        self.s.update("one", 50, "building the image")
        self.assertEqual(self.card("deploy")["status_text"], "building the image")

    def test_the_cards_history_closes_the_question_with_the_subtask_note(self):
        """Otherwise the panel's "Latest" would go on saying "Needs input: ..." after the red is gone."""
        self.asked()
        self.s.update("one", 50, "building")
        self.assertEqual(self.card("deploy")["log"][-1]["text"], "one: building")
        self.s.update("two", 10)
        self.assertNotEqual(self.card("deploy")["log"][-1]["text"], "Resumed")   # only the update that ends the question logs on the card

    def test_a_read_reply_is_dropped_when_a_subtask_reports(self):
        """Otherwise the card would keep showing "You replied ..." for the rest of its life."""
        self.asked()
        self.s.reply("deploy", "Go ahead")
        self.s.answer("deploy")
        self.s.update("one", 50, "building")
        self.assertNotIn("reply", self.card("deploy"))

    def test_an_unread_reply_survives_a_subtask_update(self):
        self.asked()
        self.s.reply("deploy", "Go ahead")
        self.s.update("one", 50, "building")
        self.assertEqual(self.card("deploy")["reply"]["text"], "Go ahead")

    def test_the_subtask_that_asked_clears_its_card_as_before(self):
        self.s.start("Deploy", "alice")
        self.s.add("one", parent_id="deploy")
        self.s.add("two", parent_id="deploy")
        self.s.ask("one", "Which region?")
        self.s.update("one", 10, "using eu-west")
        self.assertFalse(self.asking())
        self.assertNotIn("needs_input", self.card("one"))

    def test_another_subtask_reporting_does_not_clear_a_question_asked_on_a_subtask(self):
        self.s.start("Deploy", "alice")
        self.s.add("one", parent_id="deploy")
        self.s.add("two", parent_id="deploy")
        self.s.ask("one", "Which region?")
        self.s.update("two", 10, "other work")
        self.assertTrue(self.asking())
        self.assertTrue(self.card("one")["needs_input"])

    def test_review_clears_it(self):
        self.asked()
        self.s.review("deploy", "done")
        self.assertFalse(self.asking())


class WhileTheAgentIsSilent(Base):
    """The state stays until the agent does one of the two."""

    def test_a_reply_alone_changes_nothing_but_the_reply(self):
        self.asked()
        self.s.reply("deploy", "Go ahead")
        c = self.card("deploy")
        self.assertTrue(c["needs_input"])
        self.assertEqual(c["question"], "Staging or prod?")
        self.assertEqual(hud.build(self.s.load())["totals"]["waiting"], 1)

    def test_asking_again_after_a_read_is_red_again_with_the_new_question(self):
        self.asked()
        self.s.reply("deploy", "Go ahead")
        self.s.answer("deploy")
        self.s.ask("deploy", "And the database?")
        c = self.card("deploy")
        self.assertTrue(c["needs_input"])
        self.assertEqual(c["question"], "And the database?")
        self.assertNotIn("reply", c)


class TheBoardReadsOneField(unittest.TestCase):
    """Card, header count, By agent, Load and the right panel all read `needs_input`, so clearing it clears them together."""

    def test_nothing_in_the_page_keeps_its_own_copy_of_the_ask(self):
        for stale in ("askedAt", "replyRead", "t.asked"):
            self.assertNotIn(stale, HTML)
        self.assertIn("const asks = working.filter(t => t.needs_input).length", HTML)
        self.assertIn("const asking = !!t.needs_input && doing;", HTML)


if __name__ == "__main__":
    unittest.main()
