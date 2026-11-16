"""A command provider fills {arg} and {title} in one pass (night sweep, lane sweep-sec-cli).

`providers.command` replaced {arg} first and {title} second. An arg that is the text "{title}" was quoted, and then the title was pasted INSIDE
those quotes with quotes of its own, so a quote in the card's title closed the string and the rest of the title ran as shell. Both values come
from a card (its --ctx spec and its title), so card text could run a command wherever the owner had set up a command provider. The fix
substitutes both placeholders in a single pass: text that arrives through one value is never read again as a placeholder."""
import tempfile
import unittest
from pathlib import Path

from agentboard import providers


class OnePass(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.board = self.root / ".agentboard"
        self.board.mkdir()
        self.conf = {"type": "command", "run": "printf '%s|' {arg} {title}"}

    def run_it(self, arg, title, run=None):
        conf = {**self.conf, **({"run": run} if run else {})}
        return providers.command(arg, conf, {"title": title}, self.board)

    def test_plain_values_arrive_as_one_word_each(self):
        self.assertEqual(self.run_it("a b", "it's a title"), "a b|it's a title|")

    def test_a_placeholder_inside_the_arg_is_text_not_a_second_substitution(self):
        marker = self.root / "ran"
        title = f"x'; touch {marker}; echo '"
        out = self.run_it("{title}", title)
        self.assertFalse(marker.exists(), "text from the card's title ran as a shell command")
        self.assertEqual(out, "{title}|" + title + "|")

    def test_a_placeholder_inside_the_title_is_text_too(self):
        self.assertEqual(self.run_it("one", "{arg} and {title}"), "one|{arg} and {title}|")

    def test_a_template_may_use_a_placeholder_twice(self):
        self.assertEqual(self.run_it("a", "t", run="printf '%s|' {arg} {arg} {title}"), "a|a|t|")


if __name__ == "__main__":
    unittest.main()
