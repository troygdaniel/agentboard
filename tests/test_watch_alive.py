"""Watch feels alive (card watch-alive-pulse, Nov 14): a connection dot and an honest pulse per agent, both read from data the page already has.

The dot says whether the board answers (Live, Slow, Reconnecting); each Watch tile says how long since its agent was heard (fresh, ageing, silent). Neither
moves a percent, and neither asks the board for anything new. The setting, the endpoint and the page's code are pinned here; how it looks and behaves in a
browser (the dot through a lost connection, tiles ageing in place, reduced motion, dark, 390 px) is `node tests/qa/watch_alive_check.mjs`."""
import json
import re
import socket
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from agentboard import configschema as cs
from agentboard import hud, cli
from agentboard.server import make_handler
from agentboard.store import Store

ROOT = Path(__file__).resolve().parents[1]
PAGE = (Path(cli.__file__).parent / "static" / "index.html").read_text()


def fn(name, kind="function"):
    m = re.search(rf"{kind} {name}\b.*?\n\}}\n", PAGE, re.S)
    assert m, name
    return m.group(0)


def has(part, text, what=""):
    assert part in text, f"missing {part!r} {what}"   # a message that names the part, not the whole function


class TheSetting(unittest.TestCase):
    def test_silent_minutes_is_a_board_setting_that_defaults_to_ten(self):
        f = cs.SCHEMA["board"]["silent_minutes"]
        self.assertEqual((f.default, f.min), (10, 1))
        self.assertIn("`silent_minutes` | int 1..100000 | 10 |", cs.docs())

    def test_a_missing_or_nonsense_value_falls_back_to_ten(self):
        self.assertEqual(hud.silent_minutes({}), 10)
        self.assertEqual(hud.silent_minutes(None), 10)
        for bad in ("x", 0, -3, True, None, [5]):
            self.assertEqual(hud.silent_minutes({"board": {"silent_minutes": bad}}), 10, bad)
        self.assertEqual(hud.silent_minutes({"board": {"silent_minutes": 3}}), 3)

    def test_the_page_gets_it_from_api_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Store(Path(tmp) / ".agentboard")
            s.dir.mkdir(parents=True, exist_ok=True)   # a board with no card yet has no folder until its first write
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(s, port))
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            self.addCleanup(srv.shutdown)
            get = lambda: json.loads(urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/api/config", headers={"Host": f"localhost:{port}"}), timeout=5).read())
            self.assertEqual(get()["silent_minutes"], 10)
            (s.dir / "config.toml").write_text("[board]\nsilent_minutes = 4\n")
            self.assertEqual(get()["silent_minutes"], 4)


class TheTiles(unittest.TestCase):
    def test_a_tile_is_fresh_under_a_minute_ageing_after_and_silent_at_the_limit(self):
        has("const wState = secs => secs < 60 ? 'fresh' : secs < (cfg.silent_minutes || STALE_MIN) * 60 ? 'ageing' : 'silent';", PAGE)

    def test_the_tile_carries_its_state_its_clock_and_a_heard_line_that_is_never_hidden(self):
        t = fn("watchHtml")
        for part in ("st = wState(secs)", 'class="w-tile w-nav ${st}', 'data-upd="${esc(t.updated)}"', '<span class="w-heard">${wHeard(secs, t.updated)}</span>'):
            has(part, t, "in the working tile")
        self.assertNotIn('class="w-age">${alive', t)                              # the small top-right age is replaced, not kept beside it
        has("'last heard' : 'heard'", PAGE, "(silent says last heard)")
        has("<u>quiet</u>", PAGE, "(and carries a QUIET tag)")
        has("seconds ago", fn("watchHtml"), "(the aria-label says it too: colour is not the only signal)")

    def test_a_tile_ages_on_the_clock_without_a_redraw_and_without_a_request(self):
        t = fn("watchAgeTick")
        has("querySelectorAll('.w-tile[data-upd]')", t)
        has("classList.toggle(c, c === st)", t)
        for forbidden in ("fetch(", "XMLHttpRequest", "EventSource", "setInterval", "render()"):
            self.assertNotIn(forbidden, t, f"watchAgeTick must not use {forbidden}: it rides the poll's own beat")

    def test_the_percent_is_never_touched_by_any_of_it(self):
        for name in ("watchAgeTick",):
            self.assertNotIn("stroke-dasharray", fn(name))
            self.assertNotIn("progress", fn(name))
        self.assertNotRegex(PAGE[PAGE.index("const wState"):PAGE.index("function watchHtml")], r"progress|\.p\b|dasharray")


class TheDot(unittest.TestCase):
    def test_it_sits_in_the_header_before_the_old_chip_and_the_old_chip_is_unchanged(self):
        has('<span class="ab-conn" id="conn" aria-live="off"', PAGE)
        self.assertLess(PAGE.index('id="conn"'), PAGE.index('id="status" role="status" hidden'))
        has('<span class="status off" id="status" role="status" hidden><i></i><span>Disconnected; retrying</span></span>', PAGE)
        has('id="conn-sr" role="status"', PAGE, "(a state change is said once, to a screen reader)")

    def test_it_is_read_off_the_poll_the_page_already_makes(self):
        ld = fn("load", "async function")
        has("connRender(); watchAgeTick();", ld, "at the top of load()")
        has("conn.ok = Date.now(); conn.fails = 0;", ld, "after a poll answers")
        has("conn.fails++; setStatus(false);", ld, "when a poll fails")
        new = PAGE[PAGE.index("const conn = {"):PAGE.index("async function load()")]
        for forbidden in ("fetch(", "XMLHttpRequest", "EventSource", "setInterval", "new WebSocket"):
            self.assertNotIn(forbidden, new, f"the dot must not use {forbidden}: no extra polling, no extra cost")

    def test_live_slow_and_reconnecting_have_their_limits(self):
        has("const CONN_SLOW_S = 5, CONN_DOWN_S = 15, CONN_DOWN_FAILS = 3;", PAGE)
        has("conn.fails >= CONN_DOWN_FAILS || connAge() >= CONN_DOWN_S ? 'down' : conn.fails > 0 || connAge() >= CONN_SLOW_S ? 'slow' : 'ok'", PAGE)
        c = fn("connRender")
        for part in ("'Live'", "'Slow'", "'Reconnecting…'", "'last update '", "classList.toggle('offline', st === 'down')"):
            has(part, c, "in connRender()")

    def test_a_hidden_tab_is_not_a_lost_board(self):
        has("const connAge = () => (Date.now() - Math.max(conn.ok, conn.seen)) / 1000;", PAGE)
        has("document.addEventListener('visibilitychange', () => { if (!document.hidden) { conn.seen = Date.now(); connRender(); } });", PAGE)


class TheLook(unittest.TestCase):
    def css(self):
        return PAGE[:PAGE.index("</style>")]

    def test_silent_is_amber_and_still_and_ageing_pulses_slower_and_dimmer(self):
        css = self.css()
        has(".w-tile.silent .w-ring .fg { stroke: var(--warn); filter: none; }", css)
        has("animation: wpulse-slow 5s ease-out infinite;", css)
        has("@keyframes wpulse-slow { 0% { transform: scale(.9); opacity: .28; }", css)
        has(".w-tile.fresh .w-ring::after { content: ''; position: absolute; inset: -4px; border-radius: 50%; border: 2px solid var(--c); opacity: 0; animation: wpulse 2.2s ease-out infinite;", css)

    def test_a_lost_connection_dims_and_freezes_the_tiles(self):
        css = self.css()
        has("body.offline .w-tile:not(.w-waiting):not(.w-idling) { opacity: .55; filter: saturate(.45); }", css)
        has("animation-play-state: paused !important;", css)
        has(".ab-conn.down ~ #status { display: none; }", css)

    def test_reduced_motion_keeps_the_colours_and_drops_the_animation(self):
        css = self.css()
        block = css[css.rindex(".w-tile.fresh .w-heard i { animation: none; }") - 60:]
        for part in (".w-tile.fresh .w-ring::after { animation: none; opacity: .5; transform: scale(1.08); }",
                     ".w-tile.ageing .w-ring::after { animation: none; opacity: .22; transform: scale(1.08); }"):
            has(part, block, "in the reduced-motion block")

    def test_on_a_narrow_screen_the_dot_is_a_dot_until_something_is_wrong(self):
        has("@media (max-width: 760px) { .ab-conn .t { display: none; }", self.css())


if __name__ == "__main__":
    unittest.main()
