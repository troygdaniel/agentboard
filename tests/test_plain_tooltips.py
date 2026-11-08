"""Plain tooltips (overnight-ux-nav-and-panel-words, Nov 7): the header's tabs and buttons, the ORCH pill and the Copy prompt buttons say in plain words
what they do, so a developer who has never seen the board is not left guessing at "Load" or "ORCH". Words only: no label changes."""
import re
import unittest
from pathlib import Path

from agentboard import cli

PAGE = (Path(cli.__file__).parent / "static" / "index.html").read_text()


def title_of(html_snippet):
    m = re.search(r'title="([^"]*)"', html_snippet)
    return m.group(1) if m else ""


class Header(unittest.TestCase):
    def tag(self, ident):
        return re.search(rf'<(?:a|button)[^>]*id="{ident}"[^>]*>', PAGE).group(0)

    def test_every_tab_and_the_later_button_explains_itself(self):
        want = {"tab-board": ("three columns", "Todo", "Doing", "Done"), "tab-agents": ("lane per agent",), "hud-btn": ("live view", "waiting on you"),
                "later-btn": ("parked", "another day")}
        for ident, words in want.items():
            t = title_of(self.tag(ident))
            for w in words:
                self.assertIn(w, t, f"{ident}: {t!r}")

    def test_the_shortcut_keys_are_in_the_words_where_there_is_one(self):
        self.assertIn("(h)", title_of(self.tag("hud-btn")))
        self.assertIn("(l)", title_of(self.tag("later-btn")))

    def test_the_labels_themselves_did_not_change(self):
        for label in (">Board</a>", ">By agent</a>", ">Load</a>", ">Later <span"):
            self.assertIn(label, PAGE)

    def test_no_tooltip_uses_the_agents_only_words(self):
        for ident in ("tab-board", "tab-agents", "hud-btn", "later-btn"):
            t = title_of(self.tag(ident)).lower()
            for jargon in ("orch", "telemetry", "backlog", "hud"):
                self.assertNotIn(jargon, t, f"{ident}: {t!r}")


class Buttons(unittest.TestCase):
    def test_copy_prompt_says_what_gets_copied_and_where_it_goes(self):
        for needle in ('<button class="copy" type="button" title="', '<button class="btn" id="p-copy" title="'):
            i = PAGE.index(needle)
            t = title_of(PAGE[i:i + 260])
            self.assertIn("instructions", t)
            self.assertIn("agent's terminal", t)
            self.assertIn("(c)", t)                      # the key that does the same

    def test_the_orch_pill_says_what_orch_is(self):
        i = PAGE.index('<button class="orch-btn"')
        t = title_of(PAGE[i:i + 400])
        self.assertIn("coordinator session", t)
        self.assertIn('Talk to ORCH', PAGE[i:i + 400])  # the accessible name is unchanged


if __name__ == "__main__":
    unittest.main()
