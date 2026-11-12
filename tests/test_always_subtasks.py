"""Every card gets subtasks, always (Nov 3): the prompt and protocol say so, the CLI nudges, the board shows a cue."""
import contextlib
import io
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli, nav, prompt
from agentboard.store import Store

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()
REPO = Path(nav.__file__).parents[2]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        self.s.add("Solo", status="todo", task_id="solo")
        self.s.add("Big", status="todo", task_id="big")
        for sid in ("one", "two"):
            self.s.add(f"Part {sid}", parent_id="big", task_id=sid)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"AGENTBOARD_DIR": str(self.s.dir)}), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                cli.main(list(argv))
                code = 0
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
        return code, out.getvalue(), err.getvalue()

    def prompt_for(self, task_id):
        tasks = self.s.load()
        return prompt.build_prompt(Store.get(tasks, task_id), self.s.dir, tasks=tasks)[0]


class PromptTests(Base):
    def test_a_plain_card_prompt_says_to_add_subtasks_as_soon_as_you_start(self):
        text = self.prompt_for("solo")                     # the description is just the title: nothing was pasted in
        self.assertIn("## Step 1: add subtasks as soon as you start", text)
        self.assertIn("at least two, even on", text)
        self.assertIn("(do it, check it)", text)
        self.assertIn('add "<step>" --parent solo', text)

    def test_the_subtask_step_comes_after_claiming_and_before_progress(self):
        text = self.prompt_for("solo")
        self.assertLess(text.index("## Step 0: claim this task"), text.index("## Step 1: add subtasks"))
        self.assertLess(text.index("## Step 1: add subtasks"), text.index("## Progress reporting"))

    def test_progress_is_reported_on_the_subtasks_not_the_card(self):
        text = self.prompt_for("solo")
        self.assertIn('update <subtask id> 100 "<one-line result>"', text)
        self.assertNotIn("update solo 10", text)            # a card with subtasks has a computed %, so this would be refused

    def test_a_card_that_already_has_subtasks_keeps_its_list_and_does_not_repeat_the_step(self):
        text = self.prompt_for("big")
        self.assertIn("- one: Part one", text)
        self.assertNotIn("## Step 1: add subtasks", text)

    def test_a_subtask_prompt_does_not_ask_for_subtasks_of_its_own(self):
        self.assertNotIn("## Step 1: add subtasks", self.prompt_for("one"))   # one level deep

    def test_a_custom_template_is_left_alone(self):
        (self.s.dir / "config.toml").write_text('[prompt]\ntemplate = "mine {task_id}"\n')
        self.assertEqual(self.prompt_for("solo"), "mine solo")

    def test_the_orch_boot_prompt_says_never_to_paste_the_line(self):
        text = prompt.build_orch_prompt(self.s.load(), self.s.dir)
        self.assertIn("Every card gets subtasks, always", text)
        self.assertIn("never paste that line into a description", text)


class ProtocolTests(Base):
    def test_the_protocol_says_always_and_at_start(self):
        for text in (cli.INSTRUCTIONS, (REPO / "CLAUDE.md").read_text()):
            self.assertIn("Every card gets subtasks, always", text)
            self.assertIn("at least two, even on a tiny card (do it, check it)", text)
            self.assertIn("The board flags a Doing card with no subtasks, and `review` warns about one", " ".join(text.split()))


class CliTests(Base):
    def test_claim_with_no_subtasks_says_to_add_them(self):
        code, out, _ = self.run_cli("claim", "solo", "--name", "atlas")
        self.assertEqual(code, 0)
        self.assertIn('agentboard add "<step>" --parent solo', out)

    def test_claim_of_a_card_with_subtasks_does_not_nudge(self):
        _, out, _ = self.run_cli("claim", "big", "--name", "atlas")
        self.assertNotIn("no subtasks yet", out)

    def test_start_keeps_stdout_to_the_bare_id_and_nudges_on_stderr(self):
        code, out, err = self.run_cli("start", "Fresh work", "--name", "atlas")
        self.assertEqual((code, out.strip()), (0, "fresh-work"))
        self.assertIn("fresh-work has no subtasks yet", err)

    def test_start_under_a_parent_does_not_nudge(self):
        self.run_cli("claim", "big", "--name", "atlas")
        _, _, err = self.run_cli("start", "Another bit", "--name", "atlas", "--parent", "big")
        self.assertNotIn("no subtasks yet", err)

    def test_review_without_subtasks_warns_but_still_goes_through(self):
        self.run_cli("claim", "solo", "--name", "atlas")
        code, out, err = self.run_cli("review", "solo", "done", "--next", "nothing")
        self.assertEqual(code, 0)
        self.assertIn("warning: solo has no subtasks", err)
        self.assertIn("ready for review", out)
        self.assertTrue(Store.get(self.s.load(), "solo")["review"])

    def test_review_with_subtasks_or_on_a_subtask_does_not_warn(self):
        self.run_cli("claim", "big", "--name", "atlas")
        _, _, err = self.run_cli("review", "one", "done")        # a subtask: no review step, so nothing to warn about
        self.assertEqual(err, "")
        _, _, err = self.run_cli("review", "big", "done", "--next", "nothing")
        self.assertEqual(err, "")

    def test_add_a_top_level_card_reminds_on_stderr_and_leaves_stdout_alone(self):
        code, out, err = self.run_cli("add", "New thing", "--status", "todo")
        self.assertEqual((code, out.strip()), (0, "added new-thing (todo)"))
        self.assertIn("every card gets subtasks", err)

    def test_add_a_subtask_is_quiet(self):
        _, out, err = self.run_cli("add", "A step", "--parent", "solo")
        self.assertEqual((out.strip(), err), ("added a-step (todo)", ""))


class BoardCueTests(unittest.TestCase):
    CARD = HTML[HTML.index("function card(t) {"):HTML.index("function subsBlock")]

    def test_a_doing_card_with_no_subtasks_gets_the_cue(self):
        self.assertIn("const noSubs = doing && !nSubs && !t.needs_input && !t.review ?", self.CARD)
        self.assertIn('<div class="nosubs"', self.CARD)
        self.assertIn("No subtasks yet", self.CARD)

    def test_the_cue_sits_under_the_bar_and_is_declared_before_it_is_read(self):
        self.assertIn("${bar}${noSubs}${meta}", self.CARD)
        self.assertLess(self.CARD.index("const noSubs = "), self.CARD.index("return `<div class=\"card "))   # a TDZ error blanks the board
        self.assertLess(self.CARD.index("const nSubs = "), self.CARD.index("const noSubs = "))

    def test_the_cue_is_styled_in_the_warn_colour(self):
        self.assertRegex(HTML, r"\.nosubs \{[^}]*color: var\(--warn\)")


if __name__ == "__main__":
    unittest.main()
