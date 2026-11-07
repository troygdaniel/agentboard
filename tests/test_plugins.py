"""The plugin hook (src/agentboard/plugins.py): generic, off unless the machine says so, stopped by both locks, and invisible with no plugin.
Fake plugins only: nothing here imports or installs a real one."""
import contextlib
import io
import json
import os
import re
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from agentboard import cli, lockdown, nav, plugins
from agentboard.server import make_handler
from agentboard.store import BoardError, Store

SRC = Path(nav.__file__).parent
HTML = (SRC / "static" / "index.html").read_text()
SEEN = []   # what the demo plugin's thread saw


class EP:
    """An entry point as importlib.metadata gives one: a name and load() -> the register function."""
    def __init__(self, name, fn):
        self.name, self._fn = name, fn

    def load(self):
        return self._fn


def _raise(e):
    raise e


def demo_register(api):
    api.add_command("demo-cmd", "a demo", lambda p: p.add_argument("--x", type=int, default=1),
                    lambda a, store: print(f"x={a.x} board={store.dir.parent.name}"))
    api.add_route("GET", "hello", lambda store, q: {"hi": q.get("name", "?"), "board": str(store.dir)})
    api.add_route("POST", "echo", lambda store, body: {"got": body})
    api.add_route("POST", "refuse", lambda store, body: _raise(BoardError("not today")))
    api.add_route("POST", "boom", lambda store, body: _raise(RuntimeError("secret-token-123")))
    api.add_route("GET", "notadict", lambda store, q: "text")
    api.add_state(lambda store: {"on": True})
    api.add_thread(lambda store: SEEN.append(store.dir))
    api.set_page(script="window.demo = 1;", style=".demo { color: red; }")


class Base(unittest.TestCase):
    key = "1"   # AGENTBOARD_PLUGINS; None = unset

    def setUp(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        if self.key is not None:
            env["AGENTBOARD_PLUGINS"] = self.key
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        plugins._reset()
        self.addCleanup(plugins._reset)
        SEEN.clear()

    def env(self, **kw):
        p = mock.patch.dict(os.environ, kw)
        p.start()
        self.addCleanup(p.stop)

    def load(self, *eps):
        return plugins.load(list(eps) or [EP("demo", demo_register)])


class TheGate(Base):
    key = None

    def test_off_by_default_nothing_is_looked_up_or_imported(self):
        boom = EP("demo", lambda api: _raise(AssertionError("imported while off")))
        boom.load = lambda: _raise(AssertionError("imported while off"))
        with mock.patch("importlib.metadata.entry_points", side_effect=AssertionError("looked up while off")):
            self.assertFalse(plugins.enabled())
            self.assertIn("AGENTBOARD_PLUGINS", plugins.disabled_reason())
            self.assertEqual(plugins.load(), [])
            self.assertEqual(plugins.load([boom]), [])
        self.assertEqual((plugins.commands(), plugins.active(), plugins.failed(), plugins.state(None), plugins.page_tags("")), ([], [], [], {}, ""))

    def test_the_key_is_exactly_1(self):
        for v in ("true", "yes", " 1", "1 ", "2", "on", "", "0", "01"):
            self.env(AGENTBOARD_PLUGINS=v)
            self.assertFalse(plugins.enabled(), repr(v))
        self.env(AGENTBOARD_PLUGINS="1")
        self.assertTrue(plugins.enabled())

    def test_the_narrow_lock_beats_the_key_and_fails_closed(self):
        self.env(AGENTBOARD_PLUGINS="1")
        for v in ("1", "true", "yes", "maybe", "2", "on"):
            self.env(AGENTBOARD_NO_PLUGINS=v)
            self.assertFalse(plugins.enabled(), repr(v))
            self.assertIn("AGENTBOARD_NO_PLUGINS", plugins.disabled_reason())
            self.assertEqual(self.load(), [])
        for v in ("", "0", "false", "no", " NO "):
            self.env(AGENTBOARD_NO_PLUGINS=v)
            self.assertTrue(plugins.enabled(), repr(v))

    def test_the_master_lock_beats_everything(self):
        self.env(AGENTBOARD_PLUGINS="1", AGENTBOARD_NO_PLUGINS="0", AGENTBOARD_LOCKDOWN="1")
        self.assertFalse(plugins.enabled())
        self.assertIn(lockdown.ENV, plugins.disabled_reason())
        self.assertEqual(self.load(), [])

    def test_a_lock_set_after_loading_takes_every_plugin_away_at_once(self):
        self.env(AGENTBOARD_PLUGINS="1")
        self.assertEqual(self.load(), ["demo"])
        self.assertEqual(len(plugins.commands()), 1)
        self.assertTrue(plugins.state(None) == {"demo": {"on": True}})
        self.assertIn("page.js", plugins.page_tags(""))
        self.env(AGENTBOARD_LOCKDOWN="1")
        self.assertEqual((plugins.commands(), plugins.active(), plugins.state(None), plugins.page_tags(""), plugins.route("GET", "demo", "hello")),
                         ([], [], {}, "", None))
        self.assertEqual(plugins.start_threads(None), [])
        os.environ.pop("AGENTBOARD_LOCKDOWN")
        self.assertEqual(plugins.active()[0].name, "demo")   # lifting the lock brings back what was loaded; it was never unloaded or reloaded


class TheRegistry(Base):
    def test_a_plugin_registers_what_it_offers(self):
        self.assertEqual(self.load(), ["demo"])
        p = plugins.active()[0]
        self.assertEqual([c[0] for c in p.commands], ["demo-cmd"])
        self.assertEqual(sorted(p.routes), [("GET", "hello"), ("GET", "notadict"), ("POST", "boom"), ("POST", "echo"), ("POST", "refuse")])
        self.assertEqual(plugins.page_tags("/b/x"), '<script src="/b/x/api/x/demo/page.js" defer></script>')   # one script; no stylesheet link (the CSP forbids files)

    def test_a_plugin_that_fails_to_register_costs_only_itself_and_only_its_class_name_is_kept(self):
        bad = EP("bad", lambda api: _raise(RuntimeError("the secret token is abc123")))
        self.assertEqual(self.load(bad, EP("demo", demo_register)), ["demo"])
        self.assertEqual(plugins.failed(), [("bad", "RuntimeError")])
        text = "\n".join(plugins.status_lines())
        self.assertIn("failed: bad (RuntimeError)", text)
        self.assertNotIn("abc123", text)

    def test_bad_names_and_repeats_are_refused(self):
        self.assertEqual(self.load(EP("Bad Name", demo_register), EP("../x", demo_register), EP("demo", demo_register), EP("demo", demo_register)), ["demo"])
        self.assertEqual([n for n, _ in plugins.failed()], ["Bad Name", "../x", "demo"])

    def test_a_plugin_cannot_register_outside_its_own_namespace(self):
        api = plugins.Api(plugins.Plugin("demo"))
        for path in ("../x", "/x", "a//b", "A", "page.js", "page.css", "x.js", "a/../b", "", "x" * 80, "%2e%2e/x"):
            with self.assertRaises(ValueError, msg=repr(path)):
                api.add_route("GET", path, lambda s, b: {})
        for method in ("PUT", "DELETE", "get", None):
            with self.assertRaises(ValueError):
                api.add_route(method, "ok", lambda s, b: {})
        api.add_route("GET", "ok/deeper-1", lambda s, b: {})
        with self.assertRaises(ValueError):
            api.add_route("GET", "ok/deeper-1", lambda s, b: {})   # twice

    def test_a_command_name_must_be_a_plain_word(self):
        api = plugins.Api(plugins.Plugin("demo"))
        for name in ("Bad", "-x", "a b", "", "x;rm", None):
            with self.assertRaises(ValueError, msg=repr(name)):
                api.add_command(name, "h", None, lambda a, s: None)

    def test_it_loads_once_per_process(self):
        calls = []
        ep = EP("demo", lambda api: calls.append(1))
        plugins.load([ep])
        plugins.load([ep])
        self.assertEqual(calls, [1])

    def test_state_merges_dicts_and_drops_what_fails_or_is_not_a_dict(self):
        def reg(api):
            api.add_state(lambda store: {"a": 1})
            api.add_state(lambda store: _raise(RuntimeError("x")))
            api.add_state(lambda store: "nope")
            api.add_state(lambda store: {"b": 2})
            api.add_state(lambda store: None)
        plugins.load([EP("one", reg), EP("quiet", lambda api: api.add_state(lambda store: None))])
        self.assertEqual(plugins.state(None), {"one": {"a": 1, "b": 2}})

    def test_threads_start_with_the_store_and_one_that_raises_ends_with_one_line(self):
        def reg(api):
            api.add_thread(lambda store: SEEN.append(store))
            api.add_thread(lambda store: _raise(RuntimeError("secret-token-123")))
        plugins.load([EP("t", reg)])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            for th in plugins.start_threads("STORE"):
                th.join(2)
        self.assertEqual(SEEN, ["STORE"])
        self.assertEqual(out.getvalue().strip(), "agentboard: plugin t: RuntimeError")
        self.assertNotIn("secret", out.getvalue())

    def test_this_module_names_no_feature_of_the_core(self):
        src = (SRC / "plugins.py").read_text().lower()
        for word in ("twilio", "sms", "pull-texts", "texts"):
            self.assertNotIn(word, src)


class Served(Base):
    """A real board server on an ephemeral port, as the page and a plugin's script talk to it."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        self.s.dir.mkdir(parents=True, exist_ok=True)
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
            self.port = sk.getsockname()[1]
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), make_handler(self.s, self.port))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def call(self, path, body=None, headers=None, raw=False):
        data = None if body is None else json.dumps(body).encode()
        h = {"Content-Type": "application/json", **(headers or {})}
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                code, blob, ctype = r.status, r.read(), r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            code, blob, ctype = e.code, e.read(), e.headers.get("Content-Type", "")
            e.close()
        if raw:
            return code, blob.decode(), ctype
        try:
            return code, json.loads(blob or b"{}")
        except ValueError:
            return code, {}


class WithNoPlugin(Served):
    key = None

    def test_the_board_answers_exactly_as_before(self):
        self.assertEqual(self.call("/api/x/demo/hello")[0], 404)
        self.assertEqual(self.call("/api/x/demo/page.js", raw=True)[0], 404)
        self.assertEqual(self.call("/api/x/demo/echo", {})[0], 404)
        self.assertNotIn("plugins", self.call("/api/tasks")[1])
        code, page, _ = self.call("/", raw=True)
        self.assertEqual(code, 200)
        self.assertNotIn("/api/x/", page)

    def test_a_key_with_no_plugin_installed_changes_nothing_either(self):
        self.env(AGENTBOARD_PLUGINS="1")
        self.assertEqual(plugins.load([]), [])
        self.assertNotIn("plugins", self.call("/api/tasks")[1])
        self.assertNotIn("/api/x/", self.call("/", raw=True)[1])


class WithAPlugin(Served):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.load(), ["demo"])

    def test_get_and_post_routes_reach_the_plugin_with_the_right_board(self):
        code, out = self.call("/api/x/demo/hello?name=troy")
        self.assertEqual((code, out["hi"], out["board"]), (200, "troy", str(self.s.dir)))
        self.assertEqual(self.call("/api/x/demo/echo", {"a": [1, 2]}), (200, {"got": {"a": [1, 2]}}))

    def test_a_board_error_is_the_plugins_own_words_any_other_error_is_only_its_class(self):
        self.assertEqual(self.call("/api/x/demo/refuse", {}), (400, {"error": "not today"}))
        self.assertEqual(self.call("/api/x/demo/boom", {}), (500, {"error": "RuntimeError"}))
        self.assertEqual(self.call("/api/x/demo/notadict")[0], 500)

    def test_only_what_was_registered_answers(self):
        for path in ("/api/x/demo/echo", "/api/x/demo/nothing", "/api/x/other/hello", "/api/x/demo/hello/extra",
                     "/api/x/demo/page.js/../hello", "/api/x/demo/%2e%2e/hello", "/api/x/DEMO/hello", "/api/x/demo/"):
            self.assertEqual(self.call(path)[0], 404, path)   # echo is POST-only: a GET is a 404, like any unregistered route
        self.assertEqual(self.call("/api/x/demo/hello", {})[0], 404)   # and hello is GET-only

    def test_the_page_script_is_served_with_its_style_inside_and_the_page_loads_it(self):
        code, js, ctype = self.call("/api/x/demo/page.js", raw=True)
        self.assertEqual((code, ctype.split(";")[0]), (200, "text/javascript"))
        self.assertIn("document.createElement('style')", js)   # the style is put in a <style> element: a stylesheet file would be blocked by the CSP
        self.assertIn('".demo { color: red; }"', js)
        self.assertTrue(js.rstrip().endswith("window.demo = 1;"))
        self.assertEqual(self.call("/api/x/demo/page.css", raw=True)[0], 404)
        page = self.call("/", raw=True)[1]
        self.assertIn('<script src="/api/x/demo/page.js" defer></script>', page)
        self.assertNotIn("stylesheet", page.split("</head>")[0].split("page.js")[-1])

    def test_the_page_policy_lets_a_same_origin_plugin_script_run_and_the_asset_is_nosniff(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/")
        with urllib.request.urlopen(req, timeout=5) as r:
            csp = r.headers["Content-Security-Policy"]
            r.read()
        self.assertRegex(csp, r"script-src [^;]*'self'")
        self.assertNotRegex(csp, r"script-src [^;]*'unsafe-inline'")   # and it still does not allow inline scripts without the nonce
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/x/demo/page.js")
        with urllib.request.urlopen(req, timeout=5) as r:
            r.read()
            self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")

    def test_the_polls_carry_the_plugins_state(self):
        self.assertEqual(self.call("/api/tasks")[1]["plugins"], {"demo": {"on": True}})

    def test_the_same_guards_as_the_core_routes(self):
        self.assertEqual(self.call("/api/x/demo/echo", {}, headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.call("/api/x/demo/echo", {}, headers={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.call("/api/x/demo/hello", headers={"Host": "evil.example"})[0], 403)

    def test_either_lock_set_while_the_board_runs_closes_every_door(self):
        for var in ("AGENTBOARD_NO_PLUGINS", "AGENTBOARD_LOCKDOWN"):
            with mock.patch.dict(os.environ, {var: "1"}):
                for path in ("/api/x/demo/hello", "/api/x/demo/page.js"):
                    self.assertEqual(self.call(path, raw=True)[0], 404, (var, path))
                self.assertEqual(self.call("/api/x/demo/echo", {})[0], 404)
                self.assertNotIn("plugins", self.call("/api/tasks")[1])
                self.assertNotIn("/api/x/", self.call("/", raw=True)[1])
            self.assertEqual(self.call("/api/x/demo/hello")[0], 200)


class TheCommandLine(Base):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                cli.main(list(argv))
                code = 0
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def eps(self, *eps):
        return mock.patch("importlib.metadata.entry_points", return_value=list(eps or [EP("demo", demo_register)]))

    def test_plugins_says_why_it_is_off_and_makes_no_lookup(self):
        for env, word in (({"AGENTBOARD_PLUGINS": "0"}, "off: $AGENTBOARD_PLUGINS is not 1"), ({"AGENTBOARD_PLUGINS": "1", "AGENTBOARD_LOCKDOWN": "1"}, "locked: $AGENTBOARD_LOCKDOWN"),
                          ({"AGENTBOARD_PLUGINS": "1", "AGENTBOARD_NO_PLUGINS": "1"}, "locked: $AGENTBOARD_NO_PLUGINS")):
            plugins._reset()
            with mock.patch.dict(os.environ, env), mock.patch("importlib.metadata.entry_points", side_effect=AssertionError("looked up")):
                code, out, _ = self.run_cli("plugins")
            self.assertEqual(code, 0)
            self.assertIn(word, out)
            self.assertIn("nothing is looked up, loaded or imported", out)

    def test_plugins_lists_what_is_loaded(self):
        with self.eps():
            self.assertIn("plugins: on, 1 loaded: demo", self.run_cli("plugins")[1])
        plugins._reset()
        with self.eps():
            pass
        with mock.patch("importlib.metadata.entry_points", return_value=[]):
            self.assertIn("none installed", self.run_cli("plugins")[1])

    def test_a_plugin_command_exists_only_while_allowed_and_runs_with_the_store(self):
        store = mock.Mock(dir=Path("/x/board/.agentboard"))
        with self.eps(), mock.patch.object(cli, "_store", return_value=store):
            self.assertEqual(self.run_cli("demo-cmd", "--x", "5")[:2], (0, "x=5 board=board\n"))
        plugins._reset()
        os.environ.pop("AGENTBOARD_PLUGINS")
        with self.eps():
            code, _, err = self.run_cli("demo-cmd")
        self.assertEqual(code, 2)
        self.assertIn("invalid choice", err)

    def test_a_plugin_cannot_shadow_a_core_command(self):
        def reg(api):
            api.add_command("list", "shadow", None, lambda a, s: print("HIJACKED"))
            api.add_command("plugins", "shadow", None, lambda a, s: print("HIJACKED"))
        with self.eps(EP("evil", reg)):
            code, out, _ = self.run_cli("plugins")
        self.assertNotIn("HIJACKED", out)
        self.assertIn("plugins: on", out)

    def test_a_command_whose_setup_fails_loses_only_itself(self):
        def reg(api):
            api.add_command("broken", "h", lambda p: _raise(RuntimeError("secret-token-123")), lambda a, s: None)
            api.add_command("fine", "h", None, lambda a, s: print("fine"))
        with self.eps(EP("p", reg)), mock.patch.object(cli, "_store", return_value=mock.Mock()):
            code, out, err = self.run_cli("fine")
            self.assertEqual((code, out), (0, "fine\n"))
            self.assertIn("agentboard: plugin p: broken: RuntimeError", err)
            self.assertNotIn("secret", err)
            code, _, err = self.run_cli("broken")
            self.assertIn("could not be set up", str(code))   # main() exits with the BoardError's words


class ThePage(unittest.TestCase):
    def test_the_page_offers_plugins_one_small_object_and_two_empty_slots(self):
        self.assertIn("const AB = window.AB = (() => {", HTML)
        self.assertIn('<span id="ab-slot-header" style="display:contents"></span>', HTML)   # display:contents: empty, it adds no box and no gap
        self.assertIn('<div id="ab-slot-settings"></div>', HTML)
        for needle in ("AB.state = j.plugins || {}", "AB.notify()", "${AB.chips(t)}"):
            self.assertIn(needle, HTML)

    def test_the_object_exists_before_anything_can_render(self):
        self.assertLess(HTML.index("const AB = window.AB"), HTML.index("function render("))
        self.assertLess(HTML.index("const esc = "), HTML.index("const AB = window.AB"))

    def test_a_plugin_that_throws_cannot_break_the_page(self):
        block = HTML[HTML.index("const AB = window.AB"):HTML.index("fetch('/api/config')")]
        self.assertGreaterEqual(len(re.findall(r"safe\(", block)), 3)   # watchers, the first call and the chips all go through the try/catch


if __name__ == "__main__":
    unittest.main()
