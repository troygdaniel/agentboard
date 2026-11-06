"""The way into the chat is the ORCH button on the Todo column (Nov 6), not an icon in the header's right-side group."""
import re
import unittest
from pathlib import Path

from agentboard import cli

PAGE = (Path(cli.__file__).parent / "static" / "index.html").read_text()


class OrchButtonTests(unittest.TestCase):
    def test_the_header_group_no_longer_has_a_chat_button(self):
        group = re.search(r'<span class="hicons">(.*?)</span>\s*</header>', PAGE, re.S).group(1)
        self.assertNotIn("chat-btn", group)
        for ident in ("notif-btn", "theme", "cfg-btn"):
            self.assertIn(f'id="{ident}"', group)

    def test_the_todo_column_draws_the_orch_button_with_a_name_for_screen_readers(self):
        fn = re.search(r"function todoColHtml\(.*?\n}\n", PAGE, re.S).group(0)
        self.assertIn('class="orch-btn" aria-controls="chat"', fn)
        self.assertIn("Talk to ORCH", fn)
        self.assertIn('<span class="chat-n">${chatUnread || \'\'}</span>', fn)   # the unread count rides the button
        self.assertNotIn('id="chat-btn"', PAGE)   # a class: Load draws its own Todo column while the board's is still in the page

    def test_the_unread_count_and_its_label_update_on_every_button_drawn(self):
        self.assertIn("document.querySelectorAll('.orch-btn').forEach(b => {", PAGE)
        self.assertIn("b.querySelector('.chat-n').textContent = chatUnread ? String(chatUnread) : ''", PAGE)
        self.assertIn("b.setAttribute('aria-label', chatUnread ? `Talk to ORCH, ${chatUnread} unread` : 'Talk to ORCH')", PAGE)


if __name__ == "__main__":
    unittest.main()
