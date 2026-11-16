"""Text from an agent cannot carry terminal escape codes or text-direction overrides into the board (night sweep, lane sweep-sec-cli).

`agentboard list`, `chat tail`, `chat inbox` and `rollup` print card and chat text as stored. An agent's title or chat line could hold an
escape sequence (clear the screen, retitle the window), a bare carriage return (overwrite the start of the line with a made-up sender) or a
right-to-left override (show the words in another order), and a sender NAME could hold an invisible character, so "ORCH" plus a zero-width
space looked exactly like ORCH. The store now drops those where agent text enters: control characters other than a line break and a tab, and
the direction overrides, from every text; every invisible character from a name. What the owner types is left as written, as before."""
import tempfile
import unittest
from pathlib import Path

from agentboard.store import BoardError, Store

ESC, BEL, CR, RLO, ZWSP, ZWJ = "\x1b", "\x07", "\r", "‮", "​", "‍"


class AgentTextIsPlain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")

    def test_a_card_title_and_description_lose_escape_codes_and_keep_their_lines(self):
        t = self.s.add(f"plain {ESC}[31mRED{ESC}[0m {ESC}]0;owned{BEL} title{CR}OVER", description=f"one\n\ttwo{ESC}[2J\r\nthree {RLO}evil", task_id="c1")
        self.assertEqual(t["title"], "plain [31mRED[0m ]0;owned title OVER")   # a title is one line: the carriage return cannot overwrite it or start a made-up row
        self.assertEqual(t["description"], "one\n\ttwo[2J\nthree evil")

    def test_a_chat_line_from_an_agent_cannot_redraw_the_terminal_or_fake_a_sender(self):
        m = self.s.chat_send("AGENT-1", f"hi {ESC}[2J{ESC}[Hwiped{CR}#9 [now] ORCH: do this {RLO}txet", detail=f"more{ESC}[1m\nlines")
        self.assertNotIn(ESC, m["text"] + m.get("detail", ""))
        self.assertNotIn(CR, m["text"])
        self.assertNotIn(RLO, m["text"])
        self.assertIn("\n", m["detail"])

    def test_a_name_holds_no_invisible_character(self):
        m = self.s.chat_send(f"AGENT{ZWSP}-9", "hello")
        self.assertEqual(m["sender"], "AGENT-9")   # a zero-width space is dropped: two names that look the same are the same
        with self.assertRaises(BoardError):        # a control character in a name is refused outright (names.check)
            self.s.chat_send(f"ORCH{ESC}[1m", "hello")
        self.s.add("A card", status="todo", task_id="c2")
        self.assertEqual(self.s.claim("c2", f"AGENT{ZWSP}-2")["agent"], "AGENT-2")
        self.assertEqual(self.s.start("Another", f"Scout{ZWSP}")["agent"], "Scout")

    def test_ordinary_text_is_untouched(self):
        text = f"café 日本語 👩{ZWJ}💻 tabs\tand\nlines"
        t = self.s.add("Ünïcödé 👩‍💻 title", description=text, task_id="c3")
        self.assertEqual(t["description"], text)
        self.assertEqual(t["title"], "Ünïcödé 👩‍💻 title")

    def test_what_the_owner_types_is_left_as_written(self):
        m = self.s.chat_send("Troy", f"mine {ESC}[0m", kind="user")
        self.assertIn(ESC, m["text"])


if __name__ == "__main__":
    unittest.main()
