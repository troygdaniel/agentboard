"""An agent may not release, move or remove a card another agent holds, nor run the end-of-day wrap-up that does it (night sweep, card sweep-func-cli).
`update`, `ask`, `review` and `checkpoint` already refused a report on another agent's card (store._must_hold); `release`, `move`, `rm` and
`wrapup --apply` did not, so one session could send every card of another back to Todo, move it to Done (the one thing an agent never does to its own)
or delete it. The same rule now covers them: the holder, ORCH, the owner, and a terminal with no session name pass; a card nobody holds is anyone's
to move (the queue is fixed that way)."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli
from agentboard.store import Store


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        for cid, agent in (("mine", "AG-1"), ("mine-two", "AG-1")):
            self.s.add(f"Card {cid}", status="doing", task_id=cid)
            self.s.claim(cid, agent)
        self.s.add("Step", parent_id="mine", task_id="mine-step")
        self.s.add("Free card", status="todo", task_id="free")

    def run_cli(self, name, *argv):
        out, err = io.StringIO(), io.StringIO()
        env = {"AGENTBOARD_DIR": str(self.s.dir)}
        if name:
            env["AGENTBOARD_NAME"] = name
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            if not name:
                os.environ.pop("AGENTBOARD_NAME", None)
            try:
                cli.main(list(argv))
                code = 0
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
                if isinstance(e.code, str):
                    err.write(e.code)
        return code, out.getvalue(), err.getvalue()

    def card(self, cid):
        return Store.get(self.s.load(), cid)

    def exists(self, cid):
        return any(t["id"] == cid for t in self.s.load())


class OtherAgentsCards(GuardTests):
    def test_release_of_a_card_another_agent_holds_is_refused(self):
        code, _, err = self.run_cli("AG-2", "release", "mine")
        self.assertNotEqual(code, 0)
        self.assertIn("held by AG-1", err)
        self.assertEqual((self.card("mine")["status"], self.card("mine")["agent"]), ("doing", "AG-1"))

    def test_release_by_agent_name_cannot_take_every_card_of_another_agent(self):
        code, out, err = self.run_cli("AG-2", "release", "--agent", "AG-1")
        self.assertNotEqual(code, 0)
        self.assertIn("held by AG-1", err)
        self.assertEqual(out, "")
        self.assertEqual([self.card(c)["status"] for c in ("mine", "mine-two")], ["doing", "doing"])

    def test_move_of_a_held_card_to_done_or_todo_is_refused(self):
        for column in ("done", "todo", "backlog"):
            code, _, err = self.run_cli("AG-2", "move", "mine", column)
            self.assertNotEqual(code, 0, column)
            self.assertIn("held by AG-1", err)
        self.assertEqual(self.card("mine")["status"], "doing")

    def test_remove_of_a_held_card_is_refused_and_so_is_its_subtask(self):
        for cid in ("mine", "mine-step"):
            code, _, err = self.run_cli("AG-2", "rm", cid)
            self.assertNotEqual(code, 0, cid)
            self.assertIn("held by AG-1", err)
        self.assertTrue(self.exists("mine") and self.exists("mine-step"))

    def test_wrapup_apply_and_ask_are_for_orch_and_the_owner(self):
        for flag in ("--apply", "--ask"):
            code, _, err = self.run_cli("AG-2", "wrapup", flag)
            self.assertNotEqual(code, 0, flag)
            self.assertIn("only ORCH or the owner", err)
        self.assertEqual([self.card(c)["status"] for c in ("mine", "mine-two")], ["doing", "doing"])

    def test_plain_wrapup_still_reads_for_any_agent(self):
        code, out, _ = self.run_cli("AG-2", "wrapup")
        self.assertEqual(code, 0)
        self.assertIn("End of day", out)


class WhoMay(GuardTests):
    def test_the_holder_may_release_move_and_remove_its_own_cards(self):
        self.assertEqual(self.run_cli("AG-1", "release", "mine")[0], 0)
        self.assertEqual(self.card("mine")["status"], "todo")
        self.assertEqual(self.run_cli("AG-1", "move", "mine-two", "backlog")[0], 0)
        self.assertEqual(self.run_cli("AG-1", "rm", "mine-two")[0], 0)
        self.assertFalse(self.exists("mine-two"))

    def test_orch_the_owner_and_a_terminal_with_no_name_may(self):
        self.assertEqual(self.run_cli("ORCH", "release", "mine")[0], 0)
        self.assertEqual(self.run_cli("", "move", "mine-two", "todo")[0], 0)
        self.s.claim("mine-two", "AG-1")
        owner = self.s.owner
        self.assertEqual(self.run_cli(owner, "rm", "mine-two")[0], 0)
        self.assertEqual(self.run_cli("orch", "wrapup", "--apply")[0], 0)

    def test_a_card_nobody_holds_is_anyones_to_move_or_remove(self):
        self.assertEqual(self.run_cli("AG-2", "move", "free", "backlog")[0], 0)
        self.assertEqual(self.card("free")["status"], "backlog")
        self.assertEqual(self.run_cli("AG-2", "rm", "free")[0], 0)
        self.assertFalse(self.exists("free"))

    def test_a_card_after_its_release_is_free_for_anyone(self):
        self.run_cli("AG-1", "release", "mine")
        self.assertEqual(self.run_cli("AG-2", "move", "mine", "backlog")[0], 0)


if __name__ == "__main__":
    unittest.main()
