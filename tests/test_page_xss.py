"""A quote in card text must not break out of an HTML attribute in the board page (the esc() hole found in the sec-audit-web review).

Three layers: the page's esc() is pinned (always runs), its round trip with unesc() is run in node (when node is installed), and the real
page is loaded in headless Chrome, limited to 127.0.0.1, with hostile strings in every free-text field (when Chrome is installed): no
element may carry an on* attribute and the page title must not change."""
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import unittest
from html.parser import HTMLParser
from http.server import ThreadingHTTPServer
from pathlib import Path

from agentboard.server import STATIC, make_handler
from agentboard.store import Store

PAGE = (STATIC / "index.html").read_text()
NODE = shutil.which("node")
CHROME = next((p for p in (os.environ.get("AGENTBOARD_TEST_CHROME"), "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                           shutil.which("google-chrome"), shutil.which("chromium")) if p and os.path.exists(p)), None)

# no quotes or ampersands inside the handler, so the page cannot be blamed for mangling it; String.fromCharCode(88,83,83) is "XSS"
CMD_TEXT = "git commit -m \"fix 'x' & y <z>\""
LINK_TEXT = "https://example.com/p?a=1&b=2"
BOOM = "document.title=String.fromCharCode(88,83,83)"
def hostile(attr="onanimationstart"):
    return f'x" {attr}="{BOOM}" y="'


class EscIsPinned(unittest.TestCase):
    def test_esc_escapes_both_quotes_and_attr_is_the_same_function(self):
        m = re.search(r"^const esc = .*$", PAGE, re.M)
        self.assertTrue(m)
        self.assertIn("&quot;", m.group(0))
        self.assertIn("&#39;", m.group(0))
        self.assertRegex(PAGE, r"(?m)^const attr = esc;")
        self.assertRegex(PAGE, r"(?m)^const unesc = ")

    def test_the_page_still_has_no_inline_event_handler_attributes_in_its_markup(self):
        self.assertEqual(re.findall(r'<[a-z][^>]*\s(on[a-z]+)=', PAGE[: PAGE.index("<script>")]), [])


@unittest.skipUnless(NODE, "node is not installed")
class EscRoundTripInNode(unittest.TestCase):
    def run_js(self, strings):
        esc = re.search(r"^const esc = .*$", PAGE, re.M).group(0)
        unesc = re.search(r"^const unesc = .*$", PAGE, re.M).group(0)
        js = ("const document = { createElement: () => { let t = ''; return { set textContent(v) { t = String(v); },"
              " get innerHTML() { return t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); } }; } };\n"
              f"{esc}\n{unesc}\nconst out = [];\nfor (const s of {json.dumps(strings)}) out.push([esc(s), unesc(esc(s)) === s]);\n"
              "console.log(JSON.stringify(out));")
        r = subprocess.run([NODE, "-e", js], capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_quotes_become_entities_and_everything_round_trips(self):
        samples = ['a"b', "a'b", 'x" onmouseover="alert(1)" y="', "<b>&amp;</b>", "&lt;already&gt;", "&quot; &#39;", "plain", ""]
        for s, (escaped, same) in zip(samples, self.run_js(samples)):
            self.assertNotIn('"', escaped, s)
            self.assertNotIn("'", escaped, s)
            self.assertTrue(same, s)


@unittest.skipUnless(CHROME, "Chrome is not installed (set AGENTBOARD_TEST_CHROME)")
class HostileTextInARealPage(unittest.TestCase):
    """Hostile text in the title, result, status line, agent name and subtask title, in the states that animate by themselves."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.s = s = Store(Path(cls.tmp.name) / ".agentboard")
        evil_agent = hostile("onmouseover")
        s.add(hostile("onanimationstart"), "", status="todo", task_id="evil")
        s.claim("evil", evil_agent)
        s.add(hostile("onanimationstart"), parent_id="evil", task_id="evil-sub")
        s.update("evil-sub", 20, hostile("onmouseover"))
        s.update("evil", text=f"ran `{CMD_TEXT}` and see {LINK_TEXT} ok")   # a log line with a code span and a link: the copy buttons must still copy the real text
        s.ask("evil", hostile("onanimationstart"))     # needs input: the card pulses, so onanimationstart would fire at once
        s.add("Finished", "", status="todo", task_id="fin")
        s.claim("fin", "AGENT-8")
        s.add("step", parent_id="fin", task_id="fin-step")
        s.update("fin-step", 100, "done")
        s.review("fin", hostile("onanimationstart"))    # a result with a quote
        s.add(hostile("onanimationstart"), "", status="todo", task_id="todo-evil")
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
            cls.port = sk.getsockname()[1]
        cls.srv = ThreadingHTTPServer(("127.0.0.1", cls.port), make_handler(s, cls.port))
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def dom(self, path):
        with tempfile.TemporaryDirectory() as ud:
            r = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--disable-sync",
                                "--disable-background-networking", "--disable-component-update", f"--user-data-dir={ud}",
                                "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1",   # nothing leaves this machine, whatever the page does
                                "--virtual-time-budget=20000", "--dump-dom", f"http://127.0.0.1:{self.port}{path}"],
                               capture_output=True, text=True, timeout=90)
        self.assertEqual(r.returncode, 0, r.stderr[-400:])
        return r.stdout

    @staticmethod
    def scan(dom):
        class P(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=True)
                self.handlers, self.title, self.attrs, self._in_title = [], "", [], False
            def handle_starttag(self, tag, attrs):
                self._in_title = tag == "title"
                for k, v in attrs:
                    self.attrs.append((k, v))
                    if k.startswith("on"):
                        self.handlers.append((tag, k))
            def handle_endtag(self, tag):
                self._in_title = False
            def handle_data(self, data):
                if self._in_title:
                    self.title += data
        p = P()
        p.feed(dom)
        return p

    def check(self, path):
        p = self.scan(self.dom(path))
        self.assertEqual(p.handlers, [], f"an element got an event-handler attribute on {path}")
        self.assertNotEqual(p.title, "XSS", f"script ran on {path}")
        return p

    def test_the_board_page(self):
        p = self.check("/")
        # not vacuous: the hostile text really is on the page, whole, as an attribute value
        self.assertTrue(hostile("onanimationstart") in [v for _k, v in p.attrs], "the hostile title should be on the page, whole")

    def test_a_card_panel_opened_from_the_link(self):
        p = self.check("/#evil")
        # the panel really is open (the body wears panel-open) and the hostile agent name is on the page whole, so the scan above is not vacuous
        self.assertTrue(any(v and "panel-open" in v.split() for k, v in p.attrs if k == "class"), "the card panel should be open")
        self.assertTrue(f"Show only {hostile('onmouseover')}" in [v for _k, v in p.attrs], "the hostile agent name should be on the page, whole")

    def test_copy_buttons_copy_the_real_text_not_entities(self):
        p = self.check("/#evil")
        copies = [v for k, v in p.attrs if k == "data-copy"]
        self.assertIn(CMD_TEXT, copies)
        self.assertIn(LINK_TEXT, copies)
        self.assertIn(LINK_TEXT, [v for k, v in p.attrs if k == "href"])

    def test_the_by_agent_page(self):
        self.check("/agents")


if __name__ == "__main__":
    unittest.main()
