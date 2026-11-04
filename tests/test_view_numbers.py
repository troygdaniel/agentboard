"""1, 2 and 3 open Board, By agent and Load (Nov 4): the same ring [ and ] walk, by number. Not while typing, not with a modifier
held (the handler returns before), and not in the pop-out Load window, which has no board to show."""
import re
import unittest
from pathlib import Path

from agentboard import cli

PAGE = (Path(cli.__file__).parent / "static" / "index.html").read_text()


class ViewNumberTests(unittest.TestCase):
    def test_the_three_keys_go_through_goview_after_the_typing_and_modifier_checks(self):
        line = "  if ('123'.includes(e.key) && e.key && !SOLO) { e.preventDefault(); goView(+e.key - 1); return; }"
        self.assertIn(line, PAGE)
        h = PAGE[PAGE.index("document.addEventListener('keydown', e => {\n  if (e.metaKey || e.ctrlKey) return;"):]
        self.assertLess(h.index("if (typing) return;"), h.index(line))
        self.assertLess(h.index("if (e.altKey) return;"), h.index(line))

    def test_the_sheet_lists_them(self):
        self.assertIn("<dt><kbd>1</kbd> <kbd>2</kbd> <kbd>3</kbd></dt><dd>Board, By agent, Load</dd>", PAGE)


if __name__ == "__main__":
    unittest.main()
