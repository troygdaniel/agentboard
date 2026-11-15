"""The details panel beside a card is readable (card details-panel-readable, Nov 14): a long task is one sentence to a line, cut with a Show all that works on Watch too.

The panel is `deckMoreHtml`, shared by the pile and by Watch. What it does in a browser (sentences on their own lines, the cut and the fade, Show all and Show less,
a short task whole, light, dark, 390 px) is `node tests/qa/details_panel_check.mjs`. The page's code is pinned here."""
import re
import unittest
from pathlib import Path

from agentboard import cli

PAGE = (Path(cli.__file__).parent / "static" / "index.html").read_text()


def fn(name):
    m = re.search(rf"function {name}\b.*?\n\}}\n", PAGE, re.S)
    assert m, name
    return m.group(0)


class TheSplitter(unittest.TestCase):
    def test_it_only_touches_long_plain_paragraphs(self):
        s = fn("deckSentences")
        self.assertIn("html.length < 260", s)                  # a short task is returned as it came
        self.assertIn("p.children.length", s)                  # a paragraph with markup in it is left alone
        self.assertIn("parts.length < 3", s)                   # two sentences are not a wall
        self.assertIn("textContent", s)                        # the words go back as text, never as markup
        self.assertNotIn("innerHTML =", s.replace("t.innerHTML = html;", ""))

    def test_an_abbreviation_does_not_end_a_sentence(self):
        s = fn("deckSentences")
        for ab in ("e\\.g", "i\\.e", "vs"):
            self.assertIn(ab, s)

    def test_a_word_that_ends_in_st_is_not_an_abbreviation(self):
        self.assertIn("(^|[^a-z])(e\\.g|i\\.e|vs|mr|mrs|dr|st)\\.$", fn("deckSentences"))   # "last. BUILD" is a sentence end: the abbreviation must start a word

    def test_the_task_and_the_agents_report_both_go_through_it(self):
        m = fn("deckMoreHtml")
        self.assertIn("deckSentences(d.description_html)", m)
        self.assertIn("deckSentences(d.body_html)", m)


class TheCut(unittest.TestCase):
    def test_watch_fits_a_panel_drawn_from_what_was_kept(self):
        w = fn("watchFill")
        self.assertRegex(w, r"kept\[0\] === t\.updated\) \{ deckTaskFit\(\);")   # it used to return at once, so a second open had no Show all
        self.assertIn("setTimeout(deckTaskFit, 700)", w)       # and again once the panel has opened to its width

    def test_the_css_gives_each_sentence_a_line_and_each_label_a_rule(self):
        self.assertIn(".deck-more .rich-body p.split{display:grid", PAGE)
        self.assertIn("p.split > .s{display:block}", PAGE)
        self.assertIn(".deck-more h3::after{content:'';flex:1;height:1px;background:var(--line)}", PAGE)
        self.assertIn(".deck-task .rich-body{max-height:190px", PAGE)

    def test_no_colour_of_its_own(self):
        css = "".join(re.findall(r"\.deck-more h3::after[^\n]*|p\.split[^\n]*", PAGE))
        self.assertNotRegex(css, r"#[0-9a-fA-F]{3,6}\b|rgba?\(")   # the rule and the lines take the page's tokens, so light and dark both work


if __name__ == "__main__":
    unittest.main()
