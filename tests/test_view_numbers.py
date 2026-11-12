"""1, 2 and 3 open Board, By agent and Needs you (Nov 4, retargeted Nov 12): the ring [ and ] walk, by number. One handler, after the typing and
modifier checks (a digit typed into a field stays a digit), not in the pop-out Load window, which has no board to show; one line on the ? sheet."""
import unittest
from pathlib import Path

from agentboard import cli

PAGE = (Path(cli.__file__).parent / "static" / "index.html").read_text()


class ViewNumberTests(unittest.TestCase):
    def test_one_handler_goes_through_goview_after_the_typing_and_modifier_checks(self):
        line = "  if ((e.key === '1' || e.key === '2' || e.key === '3') && !SOLO && !e.altKey) { e.preventDefault(); goView(+e.key - 1); return; }"
        self.assertEqual(PAGE.count(line), 1)
        self.assertNotIn("'123'.includes(e.key)", PAGE)                                          # the earlier duplicate is gone
        h = PAGE[PAGE.index("document.addEventListener('keydown', e => {\n  if (e.metaKey || e.ctrlKey) return;"):]
        self.assertLess(h.index("if (typing) return;"), h.index(line))
        self.assertLess(h.index("if (e.altKey) return;"), h.index(line))

    def test_the_sheet_lists_them_once_and_names_the_third_view(self):
        self.assertEqual(PAGE.count("<dt><kbd>1</kbd> <kbd>2</kbd> <kbd>3</kbd></dt>"), 1)
        self.assertIn("<dt><kbd>1</kbd> <kbd>2</kbd> <kbd>3</kbd></dt><dd>Board, By agent, Needs you</dd>", PAGE)


if __name__ == "__main__":
    unittest.main()
