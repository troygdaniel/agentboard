"""GET /api/prompt and /api/orch-prompt run the card's context providers (sec-prompt-get-sideeffect, Nov 7): a side effect behind a GET.
A browser that says the request came from another site is refused and nothing runs; the page, the CLI and curl are unchanged."""
import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from agentboard import server
from agentboard.store import Store


class PromptGetGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = Store(root / ".agentboard")
        self.store.dir.mkdir(parents=True, exist_ok=True)
        self.mark = root / "ran.txt"
        # a command provider with a visible side effect: building the prompt writes a file
        (self.store.dir / "config.toml").write_text(f'[providers.mark]\ntype = "command"\nrun = "echo {{arg}} > {self.mark}"\n')
        self.card = self.store.add("needs context", ctx=["mark:hello"], status="todo")["id"]
        probe = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(self.store, 0))
        self.port = probe.server_address[1]
        probe.server_close()
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), server.make_handler(self.store, self.port))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def get(self, path, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("GET", path, headers={"Host": f"localhost:{self.port}", **(headers or {})})
        r = c.getresponse()
        return r.status, r.read()

    def test_a_cross_site_get_is_refused_and_runs_nothing(self):
        for site in ("cross-site", "same-site", "Cross-Site"):
            for path in (f"/api/prompt?id={self.card}", "/api/orch-prompt"):
                code, raw = self.get(path, {"Sec-Fetch-Site": site})
                self.assertEqual(code, 403, (site, path))
                self.assertIn(b"bad origin", raw)
        self.assertFalse(self.mark.exists(), "a provider ran for a cross-site request")

    def test_the_page_itself_still_gets_the_prompt_and_the_provider_runs(self):
        code, raw = self.get(f"/api/prompt?id={self.card}", {"Sec-Fetch-Site": "same-origin"})
        self.assertEqual(code, 200)
        self.assertIn("prompt", json.loads(raw))
        self.assertEqual(self.mark.read_text().strip(), "hello")   # the provider ran (its stdout went to the file, so the prompt itself shows no block)
        self.assertEqual(self.get("/api/orch-prompt", {"Sec-Fetch-Site": "same-origin"})[0], 200)
        self.assertEqual(self.get("/api/orch-prompt", {"Sec-Fetch-Site": "none"})[0], 200)   # a typed address

    def test_a_client_without_browser_headers_is_unchanged(self):
        self.assertEqual(self.get(f"/api/prompt?id={self.card}")[0], 200)   # curl, the tests
        self.assertTrue(self.mark.exists())

    def test_other_gets_do_not_care_about_the_header(self):
        self.assertEqual(self.get("/api/tasks", {"Sec-Fetch-Site": "cross-site"})[0], 200)   # read-only, no side effect: as before

    def test_the_readme_warns_against_quoting_arg(self):
        text = (Path(server.__file__).parents[2] / "README.md").read_text()
        self.assertIn("Do not wrap `{arg}` or `{title}` in quotes", text)


if __name__ == "__main__":
    unittest.main()
