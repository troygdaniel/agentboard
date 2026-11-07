"""The board page ships with a nonce CSP and frame protection (the sec-page-csp finding): a stray handler or script cannot run, nothing the
page runs can reach another host, and no other site can frame it."""
import os
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from agentboard import server
from agentboard.server import STATIC, make_handler
from agentboard.store import Store

CHROME = next((p for p in (os.environ.get("AGENTBOARD_TEST_CHROME"), "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                           shutil.which("google-chrome"), shutil.which("chromium")) if p and os.path.exists(p)), None)


class Served:
    """A real board server on a free 127.0.0.1 port, for one test class."""

    def __init__(self, static=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / ".agentboard")
        self.store.add("A card", "", status="todo", task_id="a-card")
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
            self.port = sk.getsockname()[1]
        self.patch = mock.patch.object(server, "STATIC", static) if static else None
        if self.patch:
            self.patch.start()
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), make_handler(self.store, self.port))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=10) as r:
            return r.status, dict(r.headers), r.read().decode()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()
        if self.patch:
            self.patch.stop()
        self.tmp.cleanup()


class PageHeaders(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web = Served()

    @classmethod
    def tearDownClass(cls):
        cls.web.close()

    def test_the_page_carries_a_csp_whose_nonce_is_on_every_inline_script(self):
        for path in ("/", "/hud", "/agents"):
            _code, h, body = self.web.get(path)
            csp = h["Content-Security-Policy"]
            nonce = re.search(r"script-src 'nonce-([\w-]+)'", csp).group(1)
            inline = re.findall(r"<script(?![^>]*\ssrc=)([^>]*)>", body)
            self.assertTrue(inline, path)
            for attrs in inline:
                self.assertEqual(attrs.strip(), f'nonce="{nonce}"', path)

    def test_the_policy_is_strict(self):
        csp = self.web.get("/")[1]["Content-Security-Policy"]
        for want in ("default-src 'none'", "connect-src 'self'", "base-uri 'none'", "form-action 'none'", "frame-ancestors 'none'"):
            self.assertIn(want, csp)
        self.assertNotIn("unsafe-eval", csp)
        script_src = next(d for d in csp.split(";") if d.strip().startswith("script-src"))
        self.assertNotIn("unsafe-inline", script_src)
        self.assertNotIn("*", csp)
        self.assertNotRegex(csp, r"https?:")

    def test_each_response_gets_its_own_nonce(self):
        a, b = (re.search(r"nonce-([\w-]+)", self.web.get("/")[1]["Content-Security-Policy"]).group(1) for _ in range(2))
        self.assertNotEqual(a, b)
        self.assertGreaterEqual(len(a), 20)

    def test_nobody_can_frame_it_or_sniff_it(self):
        h = self.web.get("/")[1]
        self.assertEqual(h["X-Frame-Options"], "DENY")
        self.assertEqual(h["X-Content-Type-Options"], "nosniff")
        self.assertEqual(h["Referrer-Policy"], "no-referrer")
        self.assertEqual(self.web.get("/voice.js")[1]["X-Content-Type-Options"], "nosniff")

    def test_report_and_summary_pages_cannot_be_framed_either(self):
        for path in ("/summary", "/reports"):
            h = self.web.get(path)[1]
            self.assertIn("frame-ancestors 'none'", h["Content-Security-Policy"], path)
            self.assertEqual(h["X-Frame-Options"], "DENY", path)
            self.assertEqual(h["X-Content-Type-Options"], "nosniff", path)


@unittest.skipUnless(CHROME, "Chrome is not installed (set AGENTBOARD_TEST_CHROME)")
class PageInARealBrowser(unittest.TestCase):
    """Headless Chrome, resolving nothing but 127.0.0.1."""

    @classmethod
    def setUpClass(cls):
        cls.real = Served()

    @classmethod
    def tearDownClass(cls):
        cls.real.close()

    def run_chrome(self, web, path="/"):
        with tempfile.TemporaryDirectory() as ud:
            r = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--disable-sync",
                                "--disable-background-networking", "--disable-component-update", f"--user-data-dir={ud}",
                                "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1", "--enable-logging=stderr", "--v=0",
                                "--virtual-time-budget=8000", "--dump-dom", f"http://127.0.0.1:{web.port}{path}"],
                               capture_output=True, text=True, timeout=90)
        self.assertEqual(r.returncode, 0, r.stderr[-300:])
        title = re.search(r"<title>(.*?)</title>", r.stdout, re.S)
        console = [ln for ln in r.stderr.splitlines() if "CONSOLE" in ln]
        return r.stdout, (title.group(1) if title else ""), console

    def test_an_inline_handler_and_a_bare_inline_script_are_refused(self):
        # a copy of the page with two things a CSP must stop: an inline handler on the body, and a bare inline script (type= keeps the
        # server from giving it the nonce). STATIC is patched only for the length of this test.
        with tempfile.TemporaryDirectory() as static:
            page = (STATIC / "index.html").read_text()
            page = page.replace("<body>", "<body onload=\"document.title='HANDLER-RAN'\">", 1)
            page = page.replace("</body>", "<script type=\"text/javascript\">document.title='INLINE-RAN'</script></body>", 1)
            (Path(static) / "index.html").write_text(page)
            shutil.copy(STATIC / "voice.js", Path(static) / "voice.js")
            probe = Served(Path(static))
            try:
                dom, title, console = self.run_chrome(probe)
            finally:
                probe.close()
        self.assertNotIn(title, ("HANDLER-RAN", "INLINE-RAN"))
        self.assertTrue(any("Content Security Policy" in ln and "inline" in ln for ln in console), console[:3])   # the browser said so
        self.assertIn('class="card', dom)   # and the page's own (nonce'd) script still ran and drew the board

    def test_the_real_page_draws_the_board_with_no_csp_complaint(self):
        for path in ("/", "/agents", "/#a-card"):   # the board, By agent, and a card panel opened from a link
            dom, _title, console = self.run_chrome(self.real, path)
            self.assertEqual([ln for ln in console if "Content Security Policy" in ln or "Refused" in ln], [], path)
            self.assertIn("A card", dom, path)


if __name__ == "__main__":
    unittest.main()
