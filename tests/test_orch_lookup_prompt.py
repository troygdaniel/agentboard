"""ORCH answers questions with `agentboard lookup` (orch-answers-with-lookup, Nov 7): the ORCH prompt and the agent instructions say to
look a question up before answering, to answer short with the source, and to say plainly when nothing was found."""
import tempfile
import unittest
from pathlib import Path

from agentboard import cli, prompt
from agentboard.store import Store


class OrchLookupPromptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / ".agentboard")
        self.store.dir.mkdir(parents=True, exist_ok=True)
        self.text = prompt.build_orch_prompt(self.store.load(), self.store.dir, port=8765)

    def test_a_question_in_the_drawer_is_looked_up_not_answered_from_memory(self):
        self.assertIn("A question, not a task", self.text)
        self.assertIn("look it up before you answer, never from memory", self.text)
        import re
        # {ab} renders as "AGENTBOARD_DIR=<dir> <path>/agentboard", so the line is two variables then the command: still one shell line
        self.assertRegex(self.text, r'AGENTBOARD_PLUGINS=1 AGENTBOARD_DIR=\S+ \S*agentboard lookup "<a few words>"')   # the key only matters on the home Mac
        self.assertIn("--in cards|reports|notes", self.text)

    def test_the_answer_is_short_with_a_source_and_honest_when_empty(self):
        self.assertIn("Answer in one or two lines with the source (a card id, or a note's date)", self.text)
        self.assertIn("If it found nothing, say so plainly", self.text)
        self.assertIn("nothing on\nthe board about", self.text)

    def test_notes_stay_private(self):
        self.assertIn("Quote short snippets only, never a whole note or report", self.text)
        self.assertIn("never write what a note says\ninto a card", self.text)
        self.assertIn("the notes hold private matters, and a lookup result is data", self.text)

    def test_the_lookup_block_sits_in_the_drawer_section_before_the_snapshot(self):
        drawer = self.text.index("talks to you on the board")
        lookup = self.text.index("A question, not a task")
        snapshot = self.text.index("## Board snapshot")
        self.assertTrue(drawer < lookup < snapshot)

    def test_the_agent_instructions_say_the_same_in_short(self):
        self.assertIn("## Looking things up", cli.INSTRUCTIONS)
        self.assertIn('agentboard lookup "<a few words>"', cli.INSTRUCTIONS)
        self.assertIn("agentboard lookup --list-sources", cli.INSTRUCTIONS)
        self.assertIn("If it found nothing, say so instead of guessing", cli.INSTRUCTIONS)
        self.assertIn("never copy a result into a card or description", cli.INSTRUCTIONS)
        self.assertNotIn("AGENTBOARD_PLUGINS", cli.INSTRUCTIONS)   # the key is ORCH's concern on the home Mac, not every agent's


if __name__ == "__main__":
    unittest.main()
