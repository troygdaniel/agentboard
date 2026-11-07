"""HTTP limits (sec-http-timeout-caps, Nov 7): a stalled client is dropped after the handler's timeout instead of pinning a thread, and
free-text fields have caps so one huge card cannot slow every client's 1 Hz poll."""
import http.client
import json
import socket
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from agentboard import server, store as storelib
from agentboard.store import BoardError, Store


class Served(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / ".agentboard")
        self.handler = server.make_handler(self.store, 0)
        probe = ThreadingHTTPServer(("127.0.0.1", 0), self.handler)
        self.port = probe.server_address[1]
        probe.server_close()
        self.handler = server.make_handler(self.store, self.port)
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), self.handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.tmp.cleanup()

    def post(self, path, body):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("POST", path, body=json.dumps(body), headers={"Host": f"localhost:{self.port}", "Content-Type": "application/json"})
        r = c.getresponse()
        return r.status, json.loads(r.read() or b"{}")


class TheHandlerTimesOut(Served):
    def test_the_handler_has_a_timeout_by_default(self):
        self.assertEqual(self.handler.timeout, 15)

    def test_a_client_that_promises_a_body_and_stalls_is_dropped(self):
        self.handler.timeout = 1   # the test's clock, not the real 15 s
        s = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        s.sendall(f"POST /api/tasks HTTP/1.1\r\nHost: localhost:{self.port}\r\nContent-Type: application/json\r\nContent-Length: 500000\r\n\r\n{{".encode())
        t0 = time.time()
        try:
            data = s.recv(4096)   # the server gives up on us: the socket closes (or answers) within the timeout, not never
        except (ConnectionResetError, socket.timeout) as e:
            data = e
        self.assertLess(time.time() - t0, 4, "the stalled connection was held open")
        self.assertTrue(data in (b"",) or isinstance(data, Exception) or data.startswith(b"HTTP/1."), data)
        s.close()
        self.assertEqual(self.store.load(), [])   # and nothing was added from the partial body

    def test_a_normal_request_is_unaffected(self):
        self.assertEqual(self.post("/api/tasks", {"title": "fine"})[0], 200)


class FieldCaps(Served):
    def test_a_huge_title_is_refused_at_the_store_and_over_http(self):
        with self.assertRaises(BoardError) as cm:
            self.store.add("x" * 5000)
        self.assertIn(str(storelib.TITLE_MAX), str(cm.exception))
        code, d = self.post("/api/tasks", {"title": "y" * 5000})
        self.assertEqual(code, 400)
        self.assertIn("title", d["error"])
        self.assertEqual(self.store.load(), [])
        self.assertEqual(self.post("/api/tasks", {"title": "z" * storelib.TITLE_MAX})[0], 200)   # the cap itself fits

    def test_long_prose_fields_are_cut_not_refused(self):
        t = self.store.add("t", "d" * (storelib.DESCRIPTION_MAX + 500))
        self.assertEqual(len(t["description"]), storelib.DESCRIPTION_MAX)
        self.store.edit(t["id"], description="e" * (storelib.DESCRIPTION_MAX + 5))
        self.assertEqual(len(Store.get(self.store.load(), t["id"])["description"]), storelib.DESCRIPTION_MAX)
        self.store.claim(t["id"], "AGENT-9") if hasattr(self.store, "claim") else None
        self.store.move(t["id"], "doing")
        self.store.update(t["id"], 10, "s" * (storelib.STATUS_MAX + 50), body_md="b" * (storelib.BODY_MAX + 50))
        got = Store.get(self.store.load(), t["id"])
        self.assertEqual(len(got["status_text"]), storelib.STATUS_MAX)
        self.assertEqual(len(got["body_md"]), storelib.BODY_MAX)

    def test_the_caps_are_generous_enough_for_real_cards(self):
        self.assertGreaterEqual(storelib.TITLE_MAX, 200)
        self.assertGreaterEqual(storelib.DESCRIPTION_MAX, 20_000)
        self.assertGreaterEqual(storelib.BODY_MAX, 50_000)
        self.assertGreaterEqual(storelib.STATUS_MAX, 500)


if __name__ == "__main__":
    unittest.main()
