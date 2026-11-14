"""Talk it through: an answer lands in the thread of its question (card talk-it-through-bugs). The owner asks ORCH about a card (the board's own box posts
a line to ORCH with the card); ORCH answers from a shell with `agentboard chat send "..." --name ORCH`, usually with none of the flags that thread a line. That line
used to be a broadcast with no card: it never reached the conversation on the board, it went to every agent's inbox, and ORCH had to send it again with
--to, --card and --reply-to. Now Store.chat_send threads a plain answer to the question the owner asked its sender, and an answer that names its question
takes that question's card. The Chrome check of what the box shows is tests/qa/talk_check.mjs; this pins the store's rules, including what is NOT an answer."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import store as store_mod
from agentboard.store import BoardError, Store


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        env["AGENTBOARD_HOME"] = str(Path(self.tmp.name).resolve() / "home")
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        self.s = Store(Path(self.tmp.name).resolve() / "proj" / ".agentboard")
        self.card = self.s.add("the card in front")["id"]
        self.other = self.s.add("another card")["id"]
        self.third = self.s.add("a card AGENT-1 holds")["id"]
        self.s.claim(self.third, "AGENT-1")                 # AGENT-1 is a name the board knows
        data = self.s._read()
        data["chat_agents"] = True                           # the owner's switch: agents may talk to each other
        self.s._write(data)

    def ask(self, text="what does this card want?", to="ORCH", card=None, at=None):
        """The owner's line, the way the board's Talk it through box posts it: to ORCH, about the card."""
        if at:
            with mock.patch.object(store_mod, "_now", return_value=at):
                return self.s.chat_send(self.s.owner, text, kind="user", to=to, card=card or self.card)
        return self.s.chat_send(self.s.owner, text, kind="user", to=to, card=card or self.card)

    def line(self, seq):
        return next(m for m in self.s.chat_list(limit=500) if m["seq"] == seq)


class PlainAnswerIsThreaded(Base):
    def test_a_plain_answer_goes_to_the_owner_in_the_thread_of_the_question(self):
        q = self.ask()
        a = self.s.chat_send("ORCH", "It wants a decision.")                       # no --to, no --card, no --reply-to
        self.assertEqual((a["reply_to"], a["card"]), (q["seq"], self.card))
        self.assertTrue(store_mod._to_owner(a["to"], self.s.owner), a)           # to the owner, not to every inbox

    def test_it_no_longer_reaches_every_agent(self):
        self.ask()
        a = self.s.chat_send("ORCH", "It wants a decision.")
        self.assertNotIn(a["seq"], [m["seq"] for m in self.s.chat_inbox("AGENT-2")])
        self.assertNotIn(a["seq"], [m["seq"] for m in self.s.chat_inbox("ORCH")])  # and not back to its own sender

    def test_names_match_in_any_case(self):
        q = self.ask(to="orch")
        self.assertEqual(self.s.chat_send("ORCH", "ok")["reply_to"], q["seq"])
        q2 = self.ask(to="ORCH")
        self.assertEqual(self.s.chat_send("orch", "ok again")["reply_to"], q2["seq"])

    def test_it_answers_the_latest_question(self):
        self.ask("first?")
        q2 = self.ask("second?")
        self.assertEqual(self.s.chat_send("ORCH", "the answer")["reply_to"], q2["seq"])

    def test_it_works_for_any_agent_the_owner_asked_not_only_orch(self):
        q = self.ask(to="AGENT-1", card=self.other)
        a = self.s.chat_send("AGENT-1", "done, check it")
        self.assertEqual((a["reply_to"], a["card"]), (q["seq"], self.other))

    def test_a_question_without_a_card_threads_without_a_card(self):
        q = self.s.chat_send(self.s.owner, "how are you?", kind="user", to="ORCH")
        a = self.s.chat_send("ORCH", "fine")
        self.assertEqual(a["reply_to"], q["seq"])
        self.assertNotIn("card", a)

    def test_the_card_may_be_named_when_it_is_the_questions_card(self):
        q = self.ask()
        a = self.s.chat_send("ORCH", "answer", card=self.card)
        self.assertEqual((a["reply_to"], a["card"]), (q["seq"], self.card))


class NotAnAnswer(Base):
    def test_a_line_to_an_agent_is_not_an_answer_and_does_not_use_up_the_question(self):
        q = self.ask()
        m = self.s.chat_send("ORCH", "AGENT-1, rebase please", to="AGENT-1")
        self.assertNotIn("reply_to", m)
        self.assertEqual(m["to"], "AGENT-1")
        self.assertEqual(self.s.chat_send("ORCH", "the answer")["reply_to"], q["seq"])

    def test_a_line_about_another_card_is_not_an_answer(self):
        q = self.ask()
        m = self.s.chat_send("ORCH", "about the other one", card=self.other)
        self.assertNotIn("reply_to", m)
        self.assertEqual(m["card"], self.other)
        self.assertNotIn("to", m)
        self.assertEqual(self.s.chat_send("ORCH", "the answer")["reply_to"], q["seq"])   # still open

    def test_once_answered_the_next_plain_line_is_an_announcement(self):
        self.ask()
        self.s.chat_send("ORCH", "the answer")
        a = self.s.chat_send("ORCH", "Merged, thanks.")
        self.assertNotIn("reply_to", a)
        self.assertNotIn("to", a)
        self.assertIn(a["seq"], [m["seq"] for m in self.s.chat_inbox("AGENT-2")])      # still for everyone

    def test_a_reply_to_the_question_counts_as_the_answer_even_with_a_different_card_or_recipient(self):
        q = self.ask()
        self.s.chat_send("ORCH", "answer by number", reply_to=q["seq"])
        a = self.s.chat_send("ORCH", "next plain line")
        self.assertNotIn("reply_to", a)

    def test_a_question_older_than_half_an_hour_is_not_used(self):
        self.ask(at="2020-01-01T00:00:00")
        a = self.s.chat_send("ORCH", "a late word")
        self.assertNotIn("reply_to", a)
        self.assertNotIn("to", a)

    def test_a_question_to_someone_else_is_not_ORCHs_to_answer(self):
        self.ask(to="AGENT-1")
        a = self.s.chat_send("ORCH", "a plain line")
        self.assertNotIn("reply_to", a)

    def test_nothing_is_threaded_when_nobody_asked(self):
        a = self.s.chat_send("ORCH", "a plain line")
        self.assertEqual({k for k in a if k in ("to", "card", "reply_to")}, set())

    def test_the_owners_own_lines_and_a_line_with_files_or_a_reply_are_left_as_written(self):
        self.ask()
        u = self.s.chat_send(self.s.owner, "a plain owner line", kind="user")
        self.assertNotIn("reply_to", u)
        self.assertNotIn("reply_to", self.s.chat_send("ORCH", "touching a file", files=["src/x.py"]))
        q2 = self.s.chat_send(self.s.owner, "x", kind="user", to="AGENT-1")
        self.assertEqual(self.s.chat_send("ORCH", "explicit", reply_to=q2["seq"])["reply_to"], q2["seq"])   # an explicit reply-to is never replaced


class ReplyToTakesTheCard(Base):
    def test_an_answer_that_names_its_question_takes_the_questions_card(self):
        q = self.ask()
        a = self.s.chat_send("ORCH", "by number", to="you", reply_to=q["seq"])
        self.assertEqual(a["card"], self.card)

    def test_a_card_named_on_the_answer_wins(self):
        q = self.ask()
        a = self.s.chat_send("ORCH", "by number", to="you", reply_to=q["seq"], card=self.other)
        self.assertEqual(a["card"], self.other)

    def test_a_question_whose_card_is_gone_gives_no_card_and_no_error(self):
        q = self.ask()
        self.s.delete(self.card)
        a = self.s.chat_send("ORCH", "by number", to="you", reply_to=q["seq"])
        self.assertNotIn("card", a)

    def test_an_unknown_question_is_still_refused(self):
        with self.assertRaises(BoardError):
            self.s.chat_send("ORCH", "x", reply_to=99999)


if __name__ == "__main__":
    unittest.main()
