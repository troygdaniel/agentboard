"""Watch with the keyboard only (sweep2-ux, 16 Nov). A Watch tile can be reached with Tab (tabindex 0), but only the arrow keys and a click told the page which tile was selected, and Enter opens
the selected one; so a tile reached with Tab did nothing on Enter. Worse, the Now pile's own key handler runs on the Watch too: it took the Enter, called deckDetails(), which sets the text of
a Details button the Watch does not have, threw a TypeError after cancelling the key, and flipped the pile's saved Details setting. A tile that takes focus is now the selected one, and the
pile's handler leaves the Watch alone. This pins the two changes; the real check, Tab to a tile, Enter, Esc and no exception in headless Chrome, is tests/qa/watch_keys_check.mjs:
`node tests/qa/watch_keys_check.mjs`."""
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


class WatchKeysTests(unittest.TestCase):
    def test_the_piles_key_handler_leaves_the_watch_alone(self):
        self.assertIn("if (!MEFIRST || nowWatch || e.metaKey || e.ctrlKey || e.altKey) return;", HTML)

    def test_the_watch_has_its_own_enter_and_esc(self):
        at = HTML.index("document.addEventListener('keydown', e => {\n  if (!(MEFIRST && nowWatch)")
        handler = HTML[at: at + 1400]
        self.assertIn("if (e.key === 'Enter' && watchSel) {", handler)
        self.assertIn("if (e.key === 'Escape' && watchOpenId) {", handler)

    def test_a_tile_that_takes_focus_is_the_selected_one(self):
        at = HTML.index("document.addEventListener('focusin', e => {   // a tile reached with Tab is the selected one")
        h = HTML[at: HTML.index("\n});", at)]
        self.assertIn("e.target.closest?.('.deck.watch .w-nav')", h)
        self.assertIn("watchSel = w.dataset.wid;", h)
        self.assertIn("w.classList.add('sel');", h)

    def test_the_focus_handler_comes_before_the_watch_key_handler_that_reads_the_selection(self):
        self.assertLess(HTML.index("document.addEventListener('focusin', e => {   // a tile reached with Tab"),
                        HTML.index("document.addEventListener('keydown', e => {\n  if (!(MEFIRST && nowWatch)"))


if __name__ == "__main__":
    unittest.main()
