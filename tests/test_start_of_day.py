"""Start of day (Nov 12): `wrapup --apply` also saves the page as data; /api/wrapup serves the newest; the board opens it once by itself on the
first load of a new day (nothing open, nothing typed, from an earlier day, not seen yet) and on `w`; a row opens its card."""
import json
import os
import re
import socket
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from agentboard import cli, wrapup
from agentboard.server import make_handler
from agentboard.store import Store

PAGE = (Path(cli.__file__).parent / "static" / "index.html").read_text()


def body(name):
    i = PAGE.index(f"function {name}(")
    return PAGE[i:PAGE.index("\n}\n", i) + 2]


class Saved(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        p = mock.patch.dict(os.environ, {"AGENTBOARD_DIR": str(self.s.dir)})
        p.start()
        self.addCleanup(p.stop)
        for i, (a, pct) in enumerate((("AGENT-1", 40), ("AGENT-2", 70))):
            self.s.add(f"c{i}", task_id=f"c{i}", status="todo"); self.s.claim(f"c{i}", a); self.s.update(f"c{i}", pct, "x")
        self.s.add("q", task_id="q", status="todo"); self.s.claim("q", "AGENT-3"); self.s.ask("q", "Which?")

    def test_apply_saves_the_page_as_data_beside_the_markdown(self):
        order, path = wrapup.apply(self.s, wrapup.plan(self.s))
        j = json.loads((path.parent / f"{path.stem}.json").read_text())
        self.assertEqual((j["wrapped"], [c["id"] for c in j["carry"]], [c["id"] for c in j["needs"]]), (True, ["c1", "c0"], ["q"]))
        self.assertEqual(j["headline"], "Wrapped up: 2 cards back in Todo, best first.")
        self.assertEqual(j["date"], path.stem)
        self.assertEqual(wrapup.last_data(self.s)["date"], path.stem)

    def test_last_data_is_the_newest_and_skips_a_file_it_cannot_read(self):
        wrapup.apply(self.s, wrapup.plan(self.s))
        d = self.s.dir / "wrapups"
        (d / "2099-01-01.json").write_text("{not json")
        (d / "2098-01-01.json").write_text(json.dumps({"date": "2098-01-01", "at": "x", "headline": "later one"}))
        self.assertEqual(wrapup.last_data(self.s)["headline"], "later one")
        self.assertIsNone(wrapup.last_data(Store(Path(self.tmp.name) / "other" / ".agentboard")))

    def test_the_endpoint_serves_it_or_says_there_is_none(self):
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0)); port = sk.getsockname()[1]
        srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(self.s, port))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (srv.shutdown(), srv.server_close()))
        get = lambda: json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/wrapup", timeout=10))
        self.assertEqual(get(), {"none": True})
        wrapup.apply(self.s, wrapup.plan(self.s))
        self.assertEqual([c["id"] for c in get()["carry"]], ["c1", "c0"])


class ThePage(unittest.TestCase):
    def test_it_opens_by_itself_only_when_nothing_is_in_use_and_it_is_new(self):
        f = body("startOfDay")
        self.assertIn("fetch('/api/wrapup', { cache: 'no-store' })", f)
        self.assertIn("const busy = isTyping() || openId || hudIsOpen() || $('keys').classList.contains('on') || mixIsOpen() || tourIsOpen();", f)
        self.assertIn("if (d.date >= localDay() || seen === d.date + ' ' + d.at || busy) return;", f)          # today's, seen, or busy: stay out of the way
        self.assertIn("if (!auto) toast('No wrap-up saved yet", f)                                              # w says so; the automatic one stays silent
        self.assertIn("if (!SOLO && location.hash.length <= 1) setTimeout(() => startOfDay(true), 1500);", PAGE)   # not at a card hash, not in the pop-out

    def test_closing_marks_it_seen_and_esc_closes_it_before_the_settings_sheet(self):
        self.assertIn("try { localStorage.setItem(SOD_KEY, sodKey); } catch (e) {}", body("closeSod"))
        esc = PAGE[PAGE.index("if (e.tookPanel) return;"):]
        self.assertLess(esc.index("toggleKeys(false)"), esc.index("closeSod()"))
        self.assertLess(esc.index("closeSod()"), esc.index("toggleMix(false)"))
        self.assertIn("if (e.key === 'w') { if ($('sod').classList.contains('on')) closeSod(); else startOfDay(false); return; }", PAGE)
        self.assertIn("|| $('sod').classList.contains('on')) return;", body("maybeAutoOpen"))                  # no card opens under it

    def test_a_row_opens_its_card_and_says_where_it_stands_only_if_it_moved(self):
        self.assertIn("e.stopPropagation(); closeSod(); openPanel(id);", PAGE)
        h = body("sodHtml")
        self.assertIn("now.status === was ? ''", h)
        self.assertIn("no longer on the board", h)
        self.assertIn("row(c, i + 1, 'todo')", h)
        self.assertGreaterEqual(len(re.findall(r"esc\(", h)), 8)                                              # agent text is escaped
        self.assertIn('<dt><kbd>w</kbd></dt><dd id="key-wrap">', PAGE)


if __name__ == "__main__":
    unittest.main()
