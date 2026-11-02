"""The Chat button is an icon in the right-side group with the bell, sound and theme buttons, not a wide text button."""
import re
import unittest
from pathlib import Path

from agentboard import cli

PAGE = (Path(cli.__file__).parent / "static" / "index.html").read_text()


class ChatIconTests(unittest.TestCase):
    def test_chat_is_an_icon_button_with_a_name_for_screen_readers(self):
        m = re.search(r'<button[^>]*id="chat-btn"[^>]*>(.*?)</button>', PAGE, re.S)
        self.assertIn('aria-label="Chat"', m.group(0))
        self.assertIn("<svg", m.group(1))
        self.assertNotIn("Chat <", m.group(1))   # no visible word: the icon is the label

    def test_chat_sits_in_the_right_side_icon_group(self):
        group = re.search(r'<span class="hicons">(.*?)</span>\s*</header>', PAGE, re.S).group(1)
        for ident in ("chat-btn", "notif-btn", "snd2", "theme"):
            self.assertIn(f'id="{ident}"', group)

    def test_the_unread_count_and_its_label_still_update(self):
        self.assertIn("$('chat-n').textContent = chatUnread", PAGE)
        self.assertIn("$('chat-btn').setAttribute('aria-label'", PAGE)


if __name__ == "__main__":
    unittest.main()
