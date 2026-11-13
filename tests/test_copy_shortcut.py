"""The c key copies a card's prompt, and Chat has no key (Nov 3). One copy path, one 'copied' sound, from the key or a button."""
import re
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


def body(fn, kind="function"):
    m = re.search(kind + r" " + fn + r"\(.*?\n}\n", HTML, re.S)
    assert m, fn
    return m.group(0)


class ChatLosesItsKeyTests(unittest.TestCase):
    def test_chat_has_no_shortcut_left_anywhere(self):
        self.assertNotIn("Chat (c)", HTML)
        self.assertNotIn("$('chat-btn').click()", HTML)   # the old c handler clicked the Chat button
        self.assertNotIn("<dd>Chat</dd>", HTML)
        self.assertIn('class="orch-btn" aria-controls="chat"', HTML)   # still reachable by its button: ORCH on the Todo column (Nov 6)

    def test_the_c_key_copies_and_is_in_the_shortcuts_list(self):
        self.assertEqual(HTML.count("e.key === 'c'"), 1)
        self.assertIn("if (e.key === 'c') { copyPromptByKey(); return; }", HTML)
        self.assertRegex(HTML, r'<dt><kbd>c</kbd></dt><dd id="key-copy">Copy a card\'s prompt[^<]*pointed at or focused last[^<]*selected or open[^<]*</dd>')

    def test_the_key_is_ignored_while_typing_and_works_in_load(self):
        handler = HTML[HTML.index("document.addEventListener('keydown', e => {\n  if (e.metaKey"):]
        handler = handler[: handler.index("\n});")]
        self.assertLess(handler.index("if (typing) return;"), handler.index("copyPromptByKey()"))
        self.assertLess(handler.index("copyPromptByKey()"), handler.index("if (hudIsOpen() && SOLO && 'nl'.includes(e.key)) return;"))   # the pop-out's stop comes after them
        self.assertLess(handler.index("if (e.key === 'Escape')"), handler.index("copyPromptByKey()"))


class OneCopyPathTests(unittest.TestCase):
    def test_every_prompt_copy_goes_through_one_function(self):
        self.assertEqual(HTML.count("fetch('/api/prompt?id=' + encodeURIComponent(id))"), 1)   # the other fetch is the panel's prompt preview, which copies nothing
        self.assertEqual(HTML.count("async function copyPromptOf("), 1)
        for caller in (body("copyPrompt", "async function"), body("copyPromptByKey", "async function")):
            self.assertIn("copyPromptOf(", caller)
        self.assertIn("await copyPromptOf(openId, b);", HTML)   # the panel's Copy button
        panel_copy = HTML[HTML.index("if (b.id === 'p-copy') {"):HTML.index("} else if (b.id === 'p-run-stop')")]
        self.assertNotIn("clipboard", panel_copy)
        self.assertNotIn("fetch(", panel_copy)

    def test_the_one_path_plays_the_one_copied_sound_and_flips_a_todo_card(self):
        path = body("copyPromptOf", "async function")
        self.assertEqual(path.count("touch.after('copy')"), 1)
        self.assertIn("copied.set(id, label); renderKeepingCardFocus();", path)
        self.assertLess(path.index("clipboard.writeText"), path.index("touch.after('copy')"))   # only after the clipboard has it

    def test_the_key_adds_no_sound_of_its_own(self):
        self.assertNotIn("touch(", body("copyPromptByKey", "async function"))
        self.assertNotIn("touch.after", body("copyPromptByKey", "async function"))


class WhichCardTests(unittest.TestCase):
    def test_the_order_is_pointer_or_keyboard_by_whichever_was_last_then_selected_then_the_open_card(self):
        pick = body("aimedCard")
        self.assertIn("(aimedBy === 'pointer' ? [under, focused, picked, openId] : [focused, picked, under, openId]).find(Boolean)", pick)
        self.assertIn("selected.size === 1", pick)
        self.assertIn("if (at !== pointerAt) { pointerAt = at; aimedBy = 'pointer'; }", HTML)   # a repeated move at the same spot is not you
        self.assertIn("window.addEventListener('keydown', e => { if (!['c', 'd', 'u'].includes(e.key)) aimedBy = 'key'; }, true);", HTML)   # c, d and u act on the aimed card; they do not move the aim

    def test_a_card_in_any_column_or_view_is_found_by_its_class(self):
        pick = body("aimedCard")
        self.assertIn(".closest?.('.card')", pick)       # Board, By agent, Load's Doing cards and the Later drawer all use .card
        self.assertIn("'.card:hover'", pick)
        self.assertNotIn("status", pick)                  # no column or status is special-cased

    def test_a_card_with_no_button_to_flip_says_which_one_it_copied(self):
        key = body("copyPromptByKey", "async function")
        self.assertIn("byId.get(id)?.status !== 'todo'", key)
        self.assertIn("toast(`Copied the prompt of", key)
        self.assertIn("toast('Point at a card, or open one, then press c to copy its prompt')", key)


if __name__ == "__main__":
    unittest.main()
