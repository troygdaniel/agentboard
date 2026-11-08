"""A plugin route registered browser=True (mic1, Nov 8): the server answers 403 unless the request says Sec-Fetch-Site: same-origin, which a browser sets for the board's own
page and a bare curl, an agent's shell or a script does not. A speed bump, not a wall (anything running as you can send the header); the point is that nothing reaches such
a route by accident or by a prompt-injected `curl`. Fake plugin only."""
import unittest

from agentboard import plugins
from agentboard.store import BoardError

from test_plugins import Base, EP, Served, _raise

CALLS = []


def register(api):
    api.add_route("POST", "private", lambda store, body: CALLS.append(("private", body)) or {"ok": True}, browser=True)
    api.add_route("GET", "private-read", lambda store, q: CALLS.append(("private-read", q)) or {"ok": True}, browser=True)
    api.add_route("POST", "open", lambda store, body: CALLS.append(("open", body)) or {"ok": True})            # an ordinary route: unchanged
    api.add_route("POST", "private-refuse", lambda store, body: _raise(BoardError("not today")), browser=True)   # the plugin's own refusal still comes through


class BrowserRoutes(Served):
    def setUp(self):
        super().setUp()
        CALLS.clear()
        self.load(EP("demo", register))

    def test_a_bare_request_is_refused_before_the_plugin_runs(self):
        for path, body in (("/api/x/demo/private", {"a": 1}), ("/api/x/demo/private-read", None)):
            code, out = self.call(path, body)
            self.assertEqual(code, 403, path)
            self.assertIn("board's own page", out["error"])
        self.assertEqual(CALLS, [])

    def test_every_other_value_of_the_header_is_refused_too(self):
        for site in ("cross-site", "same-site", "none", "", "same-origin2", "same_origin", "*"):
            for path, body in (("/api/x/demo/private", {}), ("/api/x/demo/private-read", None)):
                self.assertEqual(self.call(path, body, headers={"Sec-Fetch-Site": site})[0], 403, (site, path))
        self.assertEqual(CALLS, [])

    def test_the_pages_own_request_goes_through_in_any_case_and_spacing(self):
        for site in ("same-origin", "Same-Origin", " same-origin "):
            self.assertEqual(self.call("/api/x/demo/private", {"a": 1}, headers={"Sec-Fetch-Site": site}), (200, {"ok": True}), site)
        self.assertEqual(self.call("/api/x/demo/private-read?x=1", headers={"Sec-Fetch-Site": "same-origin"}), (200, {"ok": True}))
        self.assertEqual([c[0] for c in CALLS], ["private"] * 3 + ["private-read"])

    def test_a_foreign_origin_is_still_refused_even_with_the_header(self):
        self.assertEqual(self.call("/api/x/demo/private", {}, headers={"Sec-Fetch-Site": "same-origin", "Origin": "http://evil.example"})[0], 403)
        self.assertEqual(CALLS, [])

    def test_an_ordinary_route_of_the_same_plugin_is_unchanged(self):
        self.assertEqual(self.call("/api/x/demo/open", {"a": 1}), (200, {"ok": True}))
        self.assertEqual(self.call("/api/x/demo/open", {"a": 2}, headers={"Sec-Fetch-Site": "same-origin"}), (200, {"ok": True}))

    def test_the_plugins_own_refusal_still_reaches_the_page(self):
        self.assertEqual(self.call("/api/x/demo/private-refuse", {}, headers={"Sec-Fetch-Site": "same-origin"}), (400, {"error": "not today"}))

    def test_an_unknown_route_is_a_404_whatever_the_header(self):
        self.assertEqual(self.call("/api/x/demo/nothing", {}, headers={"Sec-Fetch-Site": "same-origin"})[0], 404)
        self.assertEqual(self.call("/api/x/demo/nothing", {})[0], 404)

    def test_a_lock_still_removes_the_route_first(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"AGENTBOARD_NO_PLUGINS": "1"}):
            self.assertEqual(self.call("/api/x/demo/private", {}, headers={"Sec-Fetch-Site": "same-origin"})[0], 404)


class Registration(Base):
    def api(self):
        p = plugins.Plugin("demo")
        return plugins.Api(p), p

    def test_only_a_real_boolean_is_accepted(self):
        api, p = self.api()
        for junk in ("yes", 1, None, [], "true"):
            with self.assertRaises(ValueError, msg=repr(junk)):
                api.add_route("POST", "x", lambda s, b: {}, browser=junk)
        self.assertEqual(p.routes, {})
        api.add_route("POST", "x", lambda s, b: {}, browser=True)
        api.add_route("POST", "y", lambda s, b: {}, browser=False)
        api.add_route("POST", "z", lambda s, b: {})
        self.assertEqual(p.browser, {("POST", "x")})

    def test_a_plugin_can_ask_whether_this_core_has_the_flag(self):
        self.assertIs(plugins.BROWSER_ROUTES, True)

    def test_browser_route_is_false_for_unknown_plugins_and_while_plugins_are_off(self):
        self.load(EP("demo", register))
        self.assertTrue(plugins.browser_route("POST", "demo", "private"))
        self.assertFalse(plugins.browser_route("POST", "demo", "open"))
        self.assertFalse(plugins.browser_route("POST", "other", "private"))
        self.assertFalse(plugins.browser_route("GET", "demo", "private"))     # the method is part of the route
        import os
        from unittest import mock
        for lock in ({"AGENTBOARD_NO_PLUGINS": "1"}, {"AGENTBOARD_LOCKDOWN": "1"}):
            with mock.patch.dict(os.environ, lock):
                self.assertFalse(plugins.browser_route("POST", "demo", "private"), lock)   # a lock takes the plugins away, flag included


if __name__ == "__main__":
    unittest.main()
