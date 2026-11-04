"""Closing Load (Esc, h) must not park keyboard focus on the Load tab: :focus-visible drew a whitish ring round it while
Board or By agent was the lit tab, so it read as if Load were selected (Nov 3)."""
import re
import unittest
from pathlib import Path

from agentboard import cli

PAGE = (Path(cli.__file__).parent / "static" / "index.html").read_text()


class LoadTabFocusTests(unittest.TestCase):
    def test_closing_load_does_not_focus_the_load_tab(self):
        close = re.search(r"function closeHud\(\) \{.*?\n\}", PAGE, re.S).group(0)
        self.assertNotIn(".focus(", close)

    def test_the_only_lit_tab_is_the_page_you_are_on(self):
        self.assertIn(".ab-tabs .tab.on {", PAGE)
        self.assertEqual(len(re.findall(r"hud-btn'\)\.focus\(", PAGE)), 0)


if __name__ == "__main__":
    unittest.main()
