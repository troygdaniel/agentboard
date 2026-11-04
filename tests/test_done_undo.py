"""d marks a card done and u undoes what the toast offers (Nov 3): the same target rule as c, one sound each, and a delete can be taken back."""
import json
import re
import socket
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from agentboard import nav
from agentboard.server import make_handler
from agentboard.store import Store

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


def body(fn, kind="function"):
    m = re.search(kind + r" " + fn + r"\(.*?\n}\n", HTML, re.S)
    assert m, fn
    return m.group(0)


class StoreUndoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        self.s.add("First", status="todo")
        self.s.add("Parent", status="todo")
        self.s.add("Child one", parent_id="parent")
        self.s.add("Child two", parent_id="parent")
        self.s.add("Last", status="todo")

    def ids(self):
        return [t["id"] for t in self.s.load()]

    def top(self):
        return [t["id"] for t in self.s.load() if t["status"] == "todo" and not t.get("parent_id")]

    def test_a_deleted_card_comes_back_in_its_place_with_its_subtasks(self):
        before, order = self.ids(), self.top()
        tasks = self.s.load()
        prev, kids = Store.get(tasks, "parent"), [t for t in tasks if t.get("parent_id") == "parent"]
        after = self.s.next_sibling("parent")
        self.s.delete("parent")
        self.assertEqual(self.top(), [i for i in order if i != "parent"])
        self.s.restore(prev, after, kids)
        back = self.s.load()
        self.assertEqual(sorted(self.ids()), sorted(before))
        self.assertEqual(self.top(), order)   # the same place in the column
        self.assertEqual(sorted(t["id"] for t in back if t.get("parent_id") == "parent"), ["child-one", "child-two"])
        self.assertIn("Restored to todo", [l["text"] for l in Store.get(back, "parent")["log"]])

    def test_a_deleted_subtask_comes_back_under_its_parent(self):
        tasks = self.s.load()
        prev = Store.get(tasks, "child-one")
        self.s.delete("child-one")
        self.assertNotIn("child-one", self.ids())
        self.s.restore(prev, None)
        self.assertEqual(Store.get(self.s.load(), "child-one")["parent_id"], "parent")

    def test_a_move_still_restores_exactly_as_before(self):
        prev = Store.get(self.s.load(), "first")
        self.s.move("first", "done")
        self.s.restore(prev, self.s.next_sibling("first"))
        self.assertEqual(Store.get(self.s.load(), "first")["status"], "todo")
        self.assertEqual(self.ids().count("first"), 1)


class DeleteRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        self.s.add("Gone soon", status="todo")
        self.s.add("Kid", parent_id="gone-soon")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), make_handler(self.s, self.port))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.shutdown)

    def post(self, path, payload):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json", "Host": f"localhost:{self.port}", "Origin": f"http://localhost:{self.port}"})
        return json.loads(urllib.request.urlopen(req, timeout=5).read())

    def test_delete_hands_back_what_undo_needs_and_restore_puts_it_back(self):
        r = self.post("/api/delete", {"id": "gone-soon"})
        self.assertEqual(r["prev"]["id"], "gone-soon")
        self.assertEqual([k["id"] for k in r["prev_kids"]], ["kid"])
        self.assertEqual(self.s.load(), [])
        self.post("/api/restore", {"task": r["prev"], "before": r["prev_before"], "kids": r["prev_kids"]})
        self.assertEqual(sorted(t["id"] for t in self.s.load()), ["gone-soon", "kid"])


class KeysTests(unittest.TestCase):
    def handler(self):
        h = HTML[HTML.index("document.addEventListener('keydown', e => {\n  if (e.metaKey"):]
        return h[: h.index("\n});")]

    def test_d_and_u_are_handled_once_after_typing_and_before_load_returns_early(self):
        h = self.handler()
        for key, call in (("d", "markDoneByKey()"), ("u", "undoByKey()")):
            self.assertEqual(HTML.count(f"e.key === '{key}'"), 1, key)
            self.assertLess(h.index("if (typing) return;"), h.index(call))
            self.assertLess(h.index(call), h.index("if (hudIsOpen()) {\n    if (e.key === 'f')"))
        self.assertIn("if (e.metaKey || e.ctrlKey) return;", h)   # Cmd/Ctrl+D and +U stay the browser's

    def test_no_single_key_is_handled_twice(self):
        keys = re.findall(r"e\.key === '(\w)'", self.handler())
        self.assertEqual(sorted(set(k for k in keys if keys.count(k) > 1)), ["h"])   # h opens Load and, inside Load, closes it
        self.assertTrue({"d", "u", "c", "n", "l", "h", "a", "e", "m", "s"} <= set(keys))

    def test_both_keys_are_on_the_shortcuts_list(self):
        self.assertRegex(HTML, r'<dt><kbd>d</kbd></dt><dd id="key-done">Mark that same card done</dd>')
        self.assertRegex(HTML, r'<dt><kbd>u</kbd></dt><dd id="key-undo">Undo what the toast offers: a move, a done, a delete, Archive or Clear, a bulk change</dd>')


class DoneKeyTests(unittest.TestCase):
    def test_d_does_what_the_done_button_does_on_the_card_c_would_copy(self):
        d = body("markDoneByKey", "async function")
        self.assertIn("aimedCard()", d)
        self.assertIn("await move(id, 'done')", d)   # the same /api/move the Mark done button calls
        self.assertEqual(body("copyPromptByKey", "async function").count("aimedCard()"), 1)
        self.assertEqual(HTML.count("function aimedCard()"), 1)

    def test_d_says_why_it_did_nothing_and_never_acts_behind_a_sheet(self):
        d = body("markDoneByKey", "async function")
        self.assertLess(d.index("mixIsOpen()"), d.index("aimedCard()"))
        self.assertIn("is already done", d)
        self.assertIn("t.parent_id", d)
        self.assertIn("press d to mark it done", d)

    def test_d_plays_the_done_settle_only_after_the_move_landed(self):
        d = body("markDoneByKey", "async function")
        self.assertIn("if (await move(id, 'done')) {", d)
        self.assertLess(d.index("await move"), d.index("touch.after('drop', 'done', t.agent)"))
        self.assertIn("let ok = false;", body("move", "async function"))
        self.assertIn("return ok;", body("move", "async function"))

    def test_a_panel_card_marked_done_closes_its_panel_like_the_button(self):
        self.assertIn("if (id === openId) closePanel();", body("markDoneByKey", "async function"))


class UndoKeyTests(unittest.TestCase):
    def test_u_and_the_toast_button_are_the_same_undo(self):
        self.assertIn("$('toast-undo').onclick = undoLast;", HTML)
        self.assertIn("function undoByKey() { if (undoInfo && $('toast').classList.contains('on')) undoLast(); }", HTML)

    def test_u_with_nothing_to_undo_does_nothing_quietly(self):
        u = re.search(r"function undoByKey\(\)[^\n]*", HTML).group(0)
        self.assertNotIn("toast(", u)
        self.assertNotIn("touch", u)
        self.assertNotIn("showError", u)

    def test_an_undo_says_what_it_undid_and_plays_one_sound_only_when_it_worked(self):
        u = body("undoLast", "async function")
        self.assertIn("toast(`Undone: ${label}`)", u)
        self.assertEqual(u.count("touch.after('undo')"), 1)
        self.assertLess(u.index("ok = true"), u.index("touch.after('undo')"))
        self.assertIn("undoInfo = null;", u)   # a toast's undo can be used once
        self.assertEqual(HTML.count("undo:  t => "), 1)

    def test_every_undo_kind_still_goes_through_it(self):
        u = body("undoLast", "async function")
        for route in ("/api/unarchive", "/api/restore"):
            self.assertIn(route, u)
        self.assertIn("u.replay", u)

    def test_a_delete_offers_its_undo(self):
        self.assertIn("toast(`Deleted “${gone?.title ?? 'the card'}”`, { prev: r.prev, before: r.prev_before, kids: r.prev_kids });", HTML)


if __name__ == "__main__":
    unittest.main()
