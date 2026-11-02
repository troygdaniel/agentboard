"""Load shows the idle agents expanded by default; the fold stays as the way to collapse them, and a collapse is remembered."""
import unittest
from pathlib import Path

from agentboard import cli

PAGE = (Path(cli.__file__).parent / "static" / "index.html").read_text()


class LoadIdleTests(unittest.TestCase):
    def test_the_idle_fold_starts_open_unless_the_browser_remembers_a_collapse(self):
        self.assertIn("let idleOpen = true, lastHud = null;", PAGE)
        self.assertIn("idleOpen = localStorage.getItem('agentboard-idle') !== 'closed';", PAGE)

    def test_clicking_the_fold_collapses_it_and_remembers_the_choice(self):
        self.assertIn("idleOpen = !idleOpen; try { localStorage.setItem('agentboard-idle', idleOpen ? 'open' : 'closed'); }", PAGE)
        self.assertIn('id="h-fold" role="button" tabindex="0" aria-expanded="${idleOpen}"', PAGE)

    def test_open_shows_the_rows_not_the_closed_summary_chips(self):
        self.assertIn('.h-fold[aria-expanded="true"] .h-fold-list { display: none; }', PAGE)


if __name__ == "__main__":
    unittest.main()
