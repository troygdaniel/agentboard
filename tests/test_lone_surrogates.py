"""Half an emoji, or a byte that was not UTF-8, must not get into the board (night sweep, functional lane).

A lone surrogate is a legal JSON string ("\\ud83d", what JSON.stringify writes when a page cuts a title in the middle of an emoji) and what Python makes of a
byte that is not UTF-8 in a command line argument ("\\udcff"). The board kept it, and then every reader that turns text into UTF-8 failed: the /story page
answered 500 and `agentboard list` raised UnicodeEncodeError, for everyone, until the card was removed by hand. Every stored text goes through
redact.scrub (Store._scrub), so that is where a lone surrogate becomes the replacement character."""
import json
import socket
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from agentboard import redact, server
from agentboard.store import Store

HALF = "\ud83d"   # the first half of an emoji, alone
BYTE = "\udcff"   # what argv makes of the byte 0xff


def has_surrogate(text):
    return any(0xD800 <= ord(c) <= 0xDFFF for c in text)


class OneLoneHalfNeverReachesTheBoard(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.s = Store(Path(tmp.name) / ".agentboard")

    def test_the_masker_replaces_a_lone_half_and_leaves_a_whole_emoji_alone(self):
        self.assertEqual(redact.scrub(f"cut {HALF} here"), "cut � here")
        self.assertEqual(redact.scrub(f"bad {BYTE} byte"), "bad � byte")
        self.assertEqual(redact.scrub("whole \U0001f600 emoji, accents é and Persian ‌ stay"), "whole \U0001f600 emoji, accents é and Persian ‌ stay")

    def test_it_is_replaced_even_when_the_masker_is_switched_off(self):
        (self.s.dir).mkdir(parents=True, exist_ok=True)
        (self.s.dir / "config.toml").write_text("[redact]\nenabled = false\n")
        self.assertEqual(redact.scrub(f"a{HALF}b", self.s.dir), "a�b")

    def test_a_title_a_description_a_status_and_a_chat_line_are_all_clean_on_disk(self):
        t = self.s.add(f"cut {HALF} title", description=f"details {BYTE}", status="todo")
        self.s.claim(t["id"], "Pat-1")
        self.s.update(t["id"], 10, f"status {HALF}")
        self.s.chat_send("Pat-1", f"hello {HALF}", "agent")
        raw = (self.s.dir / "tasks.json").read_text()
        data = json.loads(raw)
        stored = json.dumps(data, ensure_ascii=False)
        self.assertFalse(has_surrogate(stored), "a lone surrogate is on disk")
        stored.encode("utf-8")   # what every reader does next; raised UnicodeEncodeError before
        self.assertIn("cut � title", stored)

    def test_the_story_page_and_the_list_still_read_a_board_that_was_given_one(self):
        t = self.s.add(f"Billing {HALF} one", status="todo", task_id="one")
        self.assertNotIn(HALF, t["title"])
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
            port = sk.getsockname()[1]
        srv = ThreadingHTTPServer(("127.0.0.1", port), server.make_handler(self.s, port))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/story") as r:
            self.assertEqual(r.status, 200)
            self.assertIn("Billing", r.read().decode())
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/tasks") as r:
            self.assertEqual(r.status, 200)
            json.dumps(json.loads(r.read()), ensure_ascii=False).encode("utf-8")


if __name__ == "__main__":
    unittest.main()
