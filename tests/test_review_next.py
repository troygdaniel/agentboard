"""Every review says what the owner does next (Nov 12). The You line on a card leads with the agent's next step, so the step has to be
there: `review` takes `--next "<one line>"` (or a `## Next` section in the body) and refuses a review with neither. "nothing" is an answer."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli, prompt
from agentboard.store import Store


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        self.s.add("Spa shortlist", status="todo", task_id="spa")
        for sid in ("find", "check"):
            self.s.add(f"Part {sid}", parent_id="spa", task_id=sid)
        self.run_cli("claim", "spa", "--name", "atlas")

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"AGENTBOARD_DIR": str(self.s.dir)}), \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                cli.main(list(argv))
                code = 0
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
                if isinstance(e.code, str):
                    err.write(e.code)                                    # the CLI reports a refusal as its exit message
        return code, out.getvalue(), err.getvalue()

    def card(self):
        return Store.get(self.s.load(), "spa")


class TheCommand(Base):
    def test_a_review_with_no_next_step_is_refused_and_says_how(self):
        code, out, err = self.run_cli("review", "spa", "Five options with prices")
        self.assertNotEqual(code, 0)
        self.assertIn("--next", err)
        self.assertIn("--next nothing", err)
        self.assertFalse(self.card().get("review"))                     # nothing was handed in

    def test_next_becomes_the_reports_next_section(self):
        code, _, _ = self.run_cli("review", "spa", "Five options with prices", "--next", "Reply with the number of the spa to book")
        self.assertEqual(code, 0)
        t = self.card()
        self.assertTrue(t["review"])
        self.assertEqual(t["result"], "Five options with prices")       # the one sentence is untouched
        self.assertIn("## Next\n- Reply with the number of the spa to book", t["body_md"])

    def test_it_is_added_after_a_body_that_has_none(self):
        self.run_cli("review", "spa", "Done", "--body", "## Changed\n- five spas compared", "--next", "nothing")
        body = self.card()["body_md"]
        self.assertLess(body.index("## Changed"), body.index("## Next\n- nothing"))

    def test_a_body_that_already_says_next_needs_no_flag_and_is_not_doubled(self):
        code, _, _ = self.run_cli("review", "spa", "Done", "--body", "## Changed\n- x\n## Next\n- Call the dentist")
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli("review", "spa", "Done", "--body", "## Next\n- Call the dentist", "--next", "something else")
        self.assertEqual(code, 0)
        self.assertEqual(self.card()["body_md"].count("## Next"), 1)

    def test_an_empty_next_or_an_empty_section_does_not_count(self):
        for argv in (("--next", "   "), ("--body", "## Changed\n- x\n## Next\n")):
            code, _, err = self.run_cli("review", "spa", "Done", *argv)
            self.assertNotEqual(code, 0, argv)
            self.assertIn("--next", err)

    def test_a_multi_line_text_can_carry_the_section(self):
        code, _, _ = self.run_cli("review", "spa", "Done\n## Next\n- nothing")
        self.assertEqual(code, 0)

    def test_a_subtask_has_no_review_step_so_nothing_is_asked_of_it(self):
        code, out, _ = self.run_cli("review", "find", "found five")
        self.assertEqual(code, 0)
        self.assertIn("subtask finished", out)


class ThePrompts(Base):
    def test_every_prompt_that_shows_review_shows_next(self):
        tasks = self.s.load()
        texts = [prompt.build_prompt(Store.get(tasks, i), self.s.dir, tasks=tasks)[0] for i in ("spa", "find")]
        texts.append(prompt.say(cli.INSTRUCTIONS, None))
        for text in texts:
            lines = [ln for ln in text.splitlines() if " review " in ln and "<one-line result>" in ln]
            self.assertTrue(lines)
            for ln in lines:
                self.assertIn("--next", ln, ln)

    def test_the_rule_is_stated_once_in_the_card_prompt_and_the_instructions(self):
        tasks = self.s.load()
        card_prompt = prompt.build_prompt(Store.get(tasks, "spa"), self.s.dir, tasks=tasks)[0]
        for text in (card_prompt, prompt.say(cli.INSTRUCTIONS, None)):
            self.assertEqual(text.count("refuses a review that has neither"), 1)
            self.assertIn("--next nothing", text)


if __name__ == "__main__":
    unittest.main()
