"""Three server fixes found by the overnight red-team (card overnight-sec-workpc-profile), each with the probe that showed it:
  1. a JSON body nested 400,000 deep (it fits in the 1 MB limit) raised RecursionError in the handler thread: no response, a dropped connection;
  2. a symlink inside the reports folder to a file outside it was served by GET /reports/<name>;
  3. one thread per connection with no limit: 300 idle sockets made 302 threads.
Raw sockets against a real server on a free loopback port; nothing leaves this machine."""
import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from agentboard import reports, server
from agentboard.store import Store


def raw(port, data, timeout=5.0):
    chunks = []
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
        s.settimeout(timeout)
        try:
            s.sendall(data)
            s.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        try:
            while True:
                c = s.recv(65536)
                if not c:
                    break
                chunks.append(c)
        except OSError:
            pass
    out = b"".join(chunks)
    head, _, body = out.partition(b"\r\n\r\n")
    status = int(head.split(b" ", 2)[1]) if head.startswith(b"HTTP/") else 0
    return status, body.decode("utf-8", "replace")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.board = self.root / ".agentboard"
        self.board.mkdir()
        self.store = Store(self.board)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]

    def start(self):
        make = getattr(server, "new_server", None)   # (so the same tests run against a build without the fixes, and fail there)
        self.srv = make(self.store, self.port) if make else server.ThreadingHTTPServer(("127.0.0.1", self.port), server.make_handler(self.store, self.port))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def get(self, path):
        return raw(self.port, f"GET {path} HTTP/1.1\r\nHost: localhost:{self.port}\r\nConnection: close\r\n\r\n".encode())

    def post(self, body):
        return raw(self.port, f"POST /api/tasks HTTP/1.1\r\nHost: localhost:{self.port}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body)


class AJsonBombIsRefused(Base):
    def test_a_deeply_nested_body_gets_a_400_and_the_server_goes_on(self):
        self.start()
        status, text = self.post(b"[" * 400_000 + b"]" * 400_000)
        self.assertEqual(status, 400)
        self.assertIn("nested too deeply", text)
        self.assertEqual(self.get("/api/tasks")[0], 200)
        self.assertEqual(self.store.load(), [])   # and nothing was written

    def test_an_ordinary_body_still_works(self):
        self.start()
        status, text = self.post(json.dumps({"title": "an ordinary card"}).encode())
        self.assertEqual(status, 200)
        self.assertEqual([t["title"] for t in self.store.load()], ["an ordinary card"])

    def test_any_other_surprise_in_a_post_is_a_500_with_a_class_name_only(self):
        self.start()
        with mock.patch.object(Store, "add", side_effect=RuntimeError("detail that must not be shown")):
            status, text = self.post(b'{"title": "x"}')
        self.assertEqual(status, 500)
        self.assertIn("RuntimeError", text)
        self.assertNotIn("detail that must not be shown", text)


class AReportMustBeAFileInTheReportsFolder(Base):
    def test_a_symlink_to_a_file_outside_is_not_served_and_a_real_report_is(self):
        outside = self.root / "outside.txt"
        outside.write_text("NOT A REPORT")
        folder = reports.reports_dir(self.board)
        folder.mkdir(parents=True, exist_ok=True)
        link = folder / "escape-20261107-000000.html"
        link.symlink_to(outside)
        real = folder / "real-20261107-000000.html"
        real.write_text("<p>a report</p>")
        self.start()
        status, text = self.get(f"/reports/{link.name}")
        self.assertEqual(status, 404)
        self.assertNotIn("NOT A REPORT", text)
        status, text = self.get(f"/reports/{real.name}")
        self.assertEqual((status, "a report" in text), (200, True))

    def test_a_symlink_to_another_report_in_the_folder_is_not_served_either(self):
        folder = reports.reports_dir(self.board)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "real-20261107-000000.html").write_text("<p>a report</p>")
        link = folder / "alias-20261107-000000.html"
        link.symlink_to(folder / "real-20261107-000000.html")
        self.start()
        self.assertEqual(self.get(f"/reports/{link.name}")[0], 404)

    def test_the_folder_itself_being_a_link_does_not_matter_to_a_real_report(self):
        elsewhere = self.root / "moved-reports"
        elsewhere.mkdir()
        (elsewhere / "real-20261107-000000.html").write_text("<p>a report</p>")
        folder = reports.reports_dir(self.board)
        folder.parent.mkdir(parents=True, exist_ok=True)
        folder.symlink_to(elsewhere)
        self.start()
        self.assertEqual(self.get("/reports/real-20261107-000000.html")[0], 200)


class ConnectionsAreCapped(Base):
    def test_the_connection_over_the_limit_gets_a_503_at_once_and_the_slots_come_back(self):
        with mock.patch.object(server.BoundedHTTPServer, "MAX_CONNECTIONS", 5):
            self.start()
        held = [socket.create_connection(("127.0.0.1", self.port), timeout=2) for _ in range(5)]
        try:
            time.sleep(0.3)
            t0 = time.time()
            status, _ = self.get("/api/tasks")
            self.assertEqual(status, 503)
            self.assertLess(time.time() - t0, 2)
        finally:
            for c in held:
                c.close()
        for _ in range(40):   # the idle connections end (closed by us: the handler sees EOF) and give their slots back
            time.sleep(0.1)
            if self.get("/api/tasks")[0] == 200:
                break
        self.assertEqual(self.get("/api/tasks")[0], 200)

    def test_the_default_limit_is_128_and_is_a_semaphore_per_server(self):
        self.assertEqual(server.BoundedHTTPServer.MAX_CONNECTIONS, 128)
        self.start()
        self.assertEqual(self.srv._slots._value, 128)

    def test_serve_builds_the_bounded_server_on_loopback(self):
        fake = mock.MagicMock()
        fake.serve_forever.side_effect = KeyboardInterrupt
        with mock.patch.object(server, "new_server", return_value=fake) as made, mock.patch.object(server.threading, "Thread"), \
                mock.patch.object(server.serverstate, "write"), mock.patch.object(server.atexit, "register"):
            server.serve(self.store, 8199, open_browser=False)
        made.assert_called_once_with(self.store, 8199)
        self.assertEqual(server.new_server.__defaults__, ("127.0.0.1",))


if __name__ == "__main__":
    unittest.main()
