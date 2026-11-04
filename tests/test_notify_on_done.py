"""The owner's state changes reach the agent that holds the card (Nov 4): closing, undoing, sending back, moving or removing a card
leaves a reply `agentboard answer` prints, and a background `answer --wait` wakes with it."""
import contextlib
import io
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli, nav, prompt
from agentboard.store import Store

DONE = "Done by the user: the card is closed, you are free to go idle or take the next card."
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

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            cli.main(list(argv))
        return out.getvalue(), err.getvalue()

    def reviewed(self, name="Card", agent="alice"):
        """A card in review, held by an agent, with a subtask (as every card has)."""
        self.s.start(name, agent)
        cid = self.s.load()[-1]["id"]
        self.s.add("a step", parent_id=cid)
        self.s.review(cid, "ready")
        return cid

    def card(self, cid):
        return Store.get(self.s.load(), cid)

    def reply(self, cid):
        r = self.card(cid).get("reply")
        return r and r["text"]


class DoneReplyTests(Base):
    def test_closing_a_card_leaves_the_agent_a_done_reply_marked_unread(self):
        cid = self.reviewed()
        self.s.move(cid, "done")
        r = self.card(cid)["reply"]
        self.assertEqual(r["text"], DONE)
        self.assertEqual(r["by"], "you")
        self.assertNotIn("read_at", r)   # new until the agent reads it
        self.assertEqual(self.s.answer(cid)["text"], DONE)
        self.assertIn("read_at", self.card(cid)["reply"])

    def test_the_owners_name_is_used_when_the_board_has_one(self):
        self.s.dir.mkdir(parents=True, exist_ok=True)
        (self.s.dir / "config.toml").write_text('[board]\nowner = "Troy"\n')
        cid = self.reviewed()
        self.s.move(cid, "done")
        self.assertEqual(self.reply(cid), "Done by Troy: the card is closed, you are free to go idle or take the next card.")
        self.assertEqual(self.card(cid)["reply"]["by"], "Troy")

    def test_every_way_to_close_a_card_says_it(self):
        a, b, c = self.reviewed("A"), self.reviewed("B"), self.reviewed("C")
        self.s.move(a, "done")                      # drag, the d key, the panel button
        self.s.bulk_move([b], "done")               # a multi-select
        self.cli("done", c)                         # the CLI (ORCH closing for the owner)
        for cid in (a, b, c):
            self.assertEqual(self.reply(cid), DONE, cid)

    def test_a_card_nobody_holds_and_a_subtask_get_no_reply(self):
        self.s.add("Loose", status="todo")
        self.s.move("loose", "done")
        self.assertNotIn("reply", self.card("loose"))
        cid = self.reviewed()
        self.s.move(cid, "done")
        self.assertNotIn("reply", self.card("a-step"))

    def test_the_agent_marking_progress_on_a_subtask_or_moving_within_a_column_is_not_news(self):
        self.s.start("Busy", "alice")
        self.s.move("busy", "doing")   # same column
        self.assertNotIn("reply", self.card("busy"))

    def test_closing_makes_no_log_line_beyond_the_move(self):
        cid = self.reviewed()
        before = len(self.card(cid)["log"])
        self.s.move(cid, "done")
        self.assertEqual(len(self.card(cid)["log"]), before + 1)   # "Moved to done" only: the reply adds no noise


class UndoTests(Base):
    def test_undoing_a_close_says_the_card_is_back_in_review(self):
        cid = self.reviewed()
        prev, kids = self.card(cid), [t for t in self.s.load() if t.get("parent_id") == cid]
        self.s.move(cid, "done")
        self.assertEqual(self.reply(cid), DONE)
        self.s.restore(prev, None, kids)
        t = self.card(cid)
        self.assertEqual((t["status"], t["review"]), ("doing", True))
        self.assertEqual(t["reply"]["text"], "Reopened by the user: the card is back in review, not closed.")
        self.assertNotIn("read_at", t["reply"])
        self.assertTrue(t["reply"]["state"])

    def test_undoing_a_close_of_a_card_in_doing_says_doing(self):
        self.s.start("Working", "alice")
        prev = self.card("working")
        self.s.move("working", "done")
        self.s.restore(prev, None)
        self.assertEqual(self.reply("working"), "Reopened by the user: the card is back in Doing, not closed.")

    def test_undoing_a_removal_or_a_move_says_the_card_is_yours_again(self):
        cid = self.reviewed("Gone")
        prev, kids = self.card(cid), [t for t in self.s.load() if t.get("parent_id") == cid]
        self.s.delete(cid)
        self.s.restore(prev, None, kids)
        self.assertEqual(self.reply(cid), "Restored by the user: the removal is undone, the card is back in review and yours again.")
        self.s.start("Moved", "bob")
        prev = self.card("moved")
        self.s.move("moved", "todo")
        self.s.restore(prev, None)
        self.assertEqual(self.reply("moved"), "Restored by the user: the card is back in Doing and yours again.")

    def test_a_restore_that_changes_nothing_for_the_agent_stays_quiet(self):
        self.s.start("Stays", "alice")
        self.s.restore(self.card("stays"), None)
        self.assertNotIn("reply", self.card("stays"))


class OtherStateTests(Base):
    def test_send_back_says_the_card_is_open_again_and_keeps_the_note(self):
        cid = self.reviewed()
        self.s.send_back(cid, "also the dark theme")
        text = self.s.answer(cid)["text"]
        self.assertEqual(text, "Sent back by the user: the card is open again in Doing, not closed. Note: also the dark theme")

    def test_moving_a_card_off_the_agent_says_it_is_no_longer_theirs(self):
        self.s.start("Taken", "alice")
        self.s.move("taken", "todo")
        self.assertEqual(self.reply("taken"), "Moved by the user to Todo: the card is no longer yours, stop work on it and go idle or take the next card.")
        self.assertNotIn("agent", self.card("taken"))   # the board released it; the reply still reaches the waiting agent by id

    def test_reopening_a_done_card_by_drag_says_so(self):
        cid = self.reviewed()
        self.s.move(cid, "done")
        self.s.move(cid, "doing")
        self.assertEqual(self.reply(cid), "Reopened by the user: the card is back in Doing, not closed.")

    def test_a_removed_card_wakes_a_waiting_agent_and_a_typo_still_errors(self):
        cid = self.reviewed()
        threading.Timer(0.4, lambda: self.s.delete(cid)).start()
        out, err = self.cli("answer", cid, "--wait", "--timeout", "10", "--interval", "0.1")
        self.assertEqual(out.strip(), cli.REMOVED_NOTE)
        self.assertIn("is gone", err)
        with self.assertRaises(SystemExit) as e:
            self.cli("answer", "no-such-card", "--wait", "--timeout", "0.3", "--interval", "0.1")
        self.assertIn("no such task", str(e.exception))


class WaitTests(Base):
    def test_a_background_answer_wait_wakes_with_the_done_reply(self):
        cid = self.reviewed()
        threading.Timer(0.4, lambda: self.s.move(cid, "done")).start()
        t0 = time.time()
        out, err = self.cli("answer", cid, "--wait", "--timeout", "10", "--interval", "0.1")
        self.assertEqual(out.strip(), DONE)
        self.assertRegex(err, r"\(replied \d{4}-\d\d-\d\d \d\d:\d\d by you, just now\)")   # who and when
        self.assertLess(time.time() - t0, 5)

    def test_a_reopen_after_the_agent_read_done_is_new_again(self):
        # the agent read "Done" and went idle; nothing is pushed to it, but the next `answer` finds the reopen, unread
        cid = self.reviewed()
        prev, kids = self.card(cid), [t for t in self.s.load() if t.get("parent_id") == cid]
        self.s.move(cid, "done")
        self.assertIn("read_at", self.s.answer(cid))
        self.s.restore(prev, None, kids)
        self.assertNotIn("read_at", self.card(cid)["reply"])
        out, _ = self.cli("answer", cid)
        self.assertIn("Reopened by the user: the card is back in review", out)

    def test_a_wait_started_before_the_reopen_wakes_with_it(self):
        # an agent that is waiting on a card the owner closed by mistake: the undo lands while it waits
        cid = self.reviewed()
        prev, kids = self.card(cid), [t for t in self.s.load() if t.get("parent_id") == cid]
        self.s.move(cid, "done")
        self.s.reply(cid, "x")   # stands in for any later reply; then the board clears it as the agent moves on
        with self.s.transaction() as tasks:
            Store.get(tasks, cid).pop("reply")
        threading.Timer(0.4, lambda: self.s.restore(prev, None, kids)).start()
        out, _ = self.cli("answer", cid, "--wait", "--timeout", "10", "--interval", "0.1")
        self.assertIn("Reopened by the user: the card is back in review", out)

    def test_an_agent_that_is_not_waiting_finds_it_with_answer(self):
        cid = self.reviewed()
        self.s.move(cid, "done")
        out, _ = self.cli("answer", cid)
        self.assertEqual(out.strip(), DONE)


class PromptTests(Base):
    def text(self, cid):
        text, _ = prompt.build_prompt(Store.get(self.s.load(), cid), self.s.dir, tasks=self.s.load())
        return text

    def test_the_card_prompt_tells_the_agent_to_wait_after_review(self):
        self.s.add("Plain", status="todo")
        text = self.text("plain")
        self.assertIn("After `review`, do not sit idle", text)
        self.assertIn("answer plain --wait --timeout 3600", text)
        self.assertIn('closes it ("Done by the user")', text)

    def test_the_parent_and_subtask_prompts_wait_on_the_parent(self):
        self.s.add("Big", status="todo")
        self.s.add("Small", parent_id="big")
        self.assertIn("answer big --wait --timeout 3600", self.text("big"))
        sub = self.text("small")
        self.assertIn("answer big --wait --timeout 3600", sub)
        self.assertIn("review the PARENT", sub)

    def test_agentboard_instructions_say_the_same(self):
        out, _ = self.cli("instructions")
        self.assertIn("After an `ask` or a `review`, do not sit idle", out)
        self.assertIn('close it ("Done by the user: the card is closed")', out)


class QuietTests(Base):
    def test_the_board_never_shows_a_state_note_as_you_replied(self):
        self.assertIn("!t.reply.state && !asking ? `<div class=\"replied\">You replied:", HTML)
        self.assertIn("if (t.reply && t.reply.text && !t.reply.state) return `<div class=\"qr\">", HTML)

    def test_a_typed_reply_is_still_untagged_so_the_board_shows_it(self):
        cid = self.reviewed()
        self.s.reply(cid, "Go ahead")
        self.assertNotIn("state", self.card(cid)["reply"])


if __name__ == "__main__":
    unittest.main()
