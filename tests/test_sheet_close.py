"""The Settings and shortcuts sheets have a close button (Nov 4): on a phone the only way out was Esc or a tap on the dim edge."""
import unittest
from pathlib import Path

from agentboard import cli

PAGE = (Path(cli.__file__).parent / "static" / "index.html").read_text()


class SheetCloseTests(unittest.TestCase):
    def test_both_sheets_close_from_a_button_in_their_corner(self):
        self.assertIn('<h2>Settings</h2><button class="icon-btn sheet-x" id="mix-close" type="button" aria-label="Close">', PAGE)
        self.assertIn('<h2>Keyboard shortcuts</h2><button class="icon-btn sheet-x" id="keys-close" type="button" aria-label="Close">', PAGE)
        self.assertIn("if (e.target.id === 'mix' || e.target.closest('#mix-close')) { toggleMix(false); return; }", PAGE)
        self.assertIn("if (e.target.id === 'keys' || e.target.closest('#keys-close')) toggleKeys(false);", PAGE)
        self.assertIn(".sheet-x { position: absolute; top: 14px; right: 14px; }", PAGE)


if __name__ == "__main__":
    unittest.main()
