"""The ORCH boot prompt belongs to the ORCH button only: no card prompt ever carries it."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import prompt
from agentboard.store import Store

MARK = "You are ORCH"


class OrchLeakTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        env["AGENTBOARD_DIR"] = str(self.s.dir)
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def prompt_for(self, task_id):
        text, _ = prompt.build_prompt(Store.get(self.s.load(), task_id), self.s.dir, tasks=self.s.load())
        return text

    def orch_text(self):
        return prompt.build_orch_prompt(self.s.load(), self.s.dir)

    def test_the_orch_prompt_is_the_only_one_that_says_it(self):
        self.assertIn(MARK, self.orch_text())

    def test_no_kind_of_card_prompt_says_it(self):
        self.s.add("Plain card", status="todo")
        self.s.add("Parent card", status="todo")
        self.s.claim("parent-card", "alice")
        self.s.add("Child card", parent_id="parent-card")
        for card in ("plain-card", "parent-card", "child-card"):
            self.assertNotIn(MARK, self.prompt_for(card), card)

    def test_a_description_with_the_whole_orch_prompt_pasted_in_is_cut_back(self):
        keep = prompt.say(prompt.KEEP_SIMPLE.rstrip("\n"), self.s.dir)
        pasted_prompts = (self.orch_text(),                                   # today's prompt, snapshot and all
                          prompt.say(prompt.ORCH_TEMPLATE.split("## Peers")[0], self.s.dir) + keep,    # an older one that ended at Keep it simple
                          "# You are ORCH, the orchestrator for this board\n\n## Role\n\n- Add and split cards.\n\n" + keep)
        for n, pasted in enumerate(pasted_prompts):
            with self.subTest(n):
                self.s.add(f"Fix it {n}", description="Do the thing.\n\n" + pasted, status="todo")
                text = self.prompt_for(f"fix-it-{n}")
                self.assertNotIn(MARK, text)
                self.assertNotIn("Rename this session to ORCH", text)
                self.assertNotIn("Never without the user's own words", text)
                self.assertNotIn("Board snapshot", text)
                self.assertIn("Do the thing.", text)
                self.assertIn("One sentence, one idea: what the user should do or reply.", text)

    def test_a_card_about_the_leak_keeps_its_quoted_mention(self):
        quoted = "The prompt continues with '# You are ORCH, the orchestrator' after Task details."
        self.s.add("Leak report", description=quoted, status="todo")
        self.assertIn(quoted, self.prompt_for("leak-report"))

    def test_the_orch_prompt_tells_orch_to_copy_only_keep_it_simple(self):
        text = self.orch_text()
        self.assertIn('Copy only the "Keep it simple" block above', text)
        self.assertNotIn("Copy the block above", text)
        self.assertIn("Never paste the rest of this prompt into a card.", text)


if __name__ == "__main__":
    unittest.main()
