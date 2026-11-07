"""POST guards (sec-ct-exact, Nov 7): the JSON content type is matched exactly, not as a substring, so a CORS-simple type a hostile page
can send without a preflight is refused; and a browser's own Sec-Fetch-Site, when present, must say same-origin (or none)."""
import http.client
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from agentboard import server
from agentboard.store import Store


class PostGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / ".agentboard")
        probe = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(self.store, 0))
        self.port = probe.server_address[1]
        probe.server_close()
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), server.make_handler(self.store, self.port))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def post(self, content_type, extra=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        h = {"Host": f"localhost:{self.port}", **(extra or {})}
        if content_type is not None:
            h["Content-Type"] = content_type
        c.request("POST", "/api/tasks", body='{"title":"from a post"}', headers=h)
        r = c.getresponse()
        r.read()
        return r.status

    def test_a_cors_simple_type_that_merely_contains_the_words_is_refused(self):
        for ct in ("text/plain;charset=application/json", "text/plain; application/json", "multipart/form-data; boundary=application/json",
                   "application/jsonx", "xapplication/json", "", None):
            self.assertEqual(self.post(ct), 415, ct)
        self.assertEqual(self.store.load(), [])

    def test_the_exact_media_type_still_works_with_parameters_and_any_case(self):
        for ct in ("application/json", "application/json; charset=utf-8", "Application/JSON", " application/json ;charset=UTF-8"):
            self.assertEqual(self.post(ct), 200, ct)
        self.assertEqual(len(self.store.load()), 4)

    def test_a_browser_that_says_the_request_is_cross_site_is_refused(self):
        for site in ("cross-site", "same-site", "Cross-Site"):
            self.assertEqual(self.post("application/json", {"Sec-Fetch-Site": site}), 403, site)
        self.assertEqual(self.store.load(), [])
        for site in ("same-origin", "none"):   # the page itself, or a typed address
            self.assertEqual(self.post("application/json", {"Sec-Fetch-Site": site}), 200, site)

    def test_a_client_with_no_browser_headers_still_works(self):
        self.assertEqual(self.post("application/json"), 200)   # curl, the CLI, the tests: no Origin, no Sec-Fetch-Site


if __name__ == "__main__":
    unittest.main()
