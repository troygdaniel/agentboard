"""The answers the standard library writes for us (card sweep-sec-http): before this fix every response carried
`Server: agentboard Python/3.14.x`, and a request the parser refused (a method we do not serve, a URL or a header line over the limit)
got Python's own HTML error page: text/html with no nosniff header, the interpreter's words, outside the JSON every other route speaks.
A `Content-Length` that was not a number got Python's int() message back. None of it is a hole on its own; all of it tells a caller
which interpreter runs the board, and an HTML answer is one more page type to reason about. Now: the Server header is the one word
`agentboard`, and every refusal is JSON with the same headers as a 404 from our own code.
Raw sockets against a real server on a free loopback port; nothing leaves this machine."""
import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path

from agentboard import server
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
    headers = {}
    for line in head.decode("latin-1").split("\r\n")[1:]:
        k, _, v = line.partition(":")
        headers[k.strip().lower()] = v.strip()
    return status, headers, body.decode("utf-8", "replace")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.board = Path(self.tmp.name) / ".agentboard"
        self.board.mkdir()
        self.store = Store(self.board)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.srv = server.new_server(self.store, self.port)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def send(self, request_line, extra=""):
        return raw(self.port, f"{request_line} HTTP/1.1\r\nHost: localhost:{self.port}\r\n{extra}Connection: close\r\n\r\n".encode())

    def assertJsonRefusal(self, status, headers, body, code, says):
        self.assertEqual(status, code)
        self.assertEqual(headers.get("content-type"), "application/json", headers)
        self.assertEqual(headers.get("x-content-type-options"), "nosniff", headers)
        self.assertEqual(headers.get("cache-control"), "no-store", headers)
        self.assertEqual(headers.get("connection"), "close", headers)
        err = json.loads(body)["error"]
        self.assertIn(says, err)
        self.assertNotIn("Python", body)
        self.assertNotIn("<", body)


class TheServerHeaderNamesNoInterpreter(Base):
    def test_a_normal_answer_says_agentboard_and_nothing_about_python(self):
        status, headers, _ = self.send("GET /api/health")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("server"), "agentboard", headers)

    def test_so_does_a_refusal_the_parser_writes(self):
        status, headers, _ = self.send("PUT /api/tasks")
        self.assertEqual(status, 501)
        self.assertEqual(headers.get("server"), "agentboard", headers)


class ARefusalFromTheParserIsJsonLikeEveryOtherAnswer(Base):
    def test_a_method_we_do_not_serve(self):
        for method in ("PUT", "DELETE", "OPTIONS", "TRACE"):
            status, headers, body = self.send(f"{method} /api/tasks")
            self.assertJsonRefusal(status, headers, body, 501, "Unsupported method")
        status, headers, body = self.send("HEAD /api/tasks")   # a HEAD answer carries headers only, by the standard: the same ones, and no body
        self.assertEqual(status, 501)
        self.assertEqual(headers.get("content-type"), "application/json", headers)
        self.assertEqual(headers.get("x-content-type-options"), "nosniff", headers)
        self.assertEqual(headers.get("server"), "agentboard", headers)
        self.assertEqual(body, "")

    def test_a_url_over_the_limit(self):
        status, headers, body = self.send("GET /api/tasks?x=" + "a" * 70000)
        self.assertJsonRefusal(status, headers, body, 414, "URI Too Long")

    def test_a_header_line_over_the_limit(self):
        status, headers, body = self.send("GET /api/health", "X-Long: " + "a" * 70000 + "\r\n")
        self.assertJsonRefusal(status, headers, body, 431, "Line too long")

    def test_a_request_line_that_is_not_http(self):
        status, headers, body = raw(self.port, b"HELLO\r\n\r\n")
        self.assertJsonRefusal(status, headers, body, 400, "Bad request")


class ABodyLengthThatIsNotANumber(Base):
    def test_gets_the_same_words_as_a_negative_or_huge_one(self):
        status, headers, body = raw(self.port, (f"POST /api/tasks HTTP/1.1\r\nHost: localhost:{self.port}\r\nContent-Type: application/json\r\n"
                                                f"Content-Length: abc\r\nConnection: close\r\n\r\n").encode())
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body), {"error": "bad body length"})

    def test_an_ordinary_post_is_unchanged(self):
        body = b'{"title": "a card"}'
        status, headers, out = raw(self.port, (f"POST /api/tasks HTTP/1.1\r\nHost: localhost:{self.port}\r\nContent-Type: application/json\r\n"
                                               f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n").encode() + body)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(out)["title"], "a card")
        self.assertEqual(headers.get("server"), "agentboard")


if __name__ == "__main__":
    unittest.main()
