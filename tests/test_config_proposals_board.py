"""The owner's Accept and Ignore of what ORCH suggested, over HTTP (card agent-config-slice-3b): `GET /api/configurations` lists the proposals that wait, `POST /api/configuration/proposal`
decides one. Only that click applies a change; the file is validated again; a decided or unknown one is refused."""
import json
import os
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from agentboard import configproposals as cp, configurations as cfgs
from agentboard.server import make_handler
from agentboard.store import Store

WHY = "5 of the last 9 cards were reviewed twice"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        env["AGENTBOARD_HOME"] = str(Path(self.tmp.name) / "home")
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        self.s.dir.mkdir(parents=True, exist_ok=True)
        (self.s.dir / "config.toml").write_text('[board]\nowner = "Pat"\n[agents]\nconfigurations = true\n')
        cfgs.apply(self.s.dir, cfgs.builtin("day-to-day"), "day-to-day")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), make_handler(self.s, self.port))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.shutdown)

    def call(self, path, payload=None):
        h = {"Content-Type": "application/json", "Host": f"localhost:{self.port}", "Origin": f"http://localhost:{self.port}"}
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=None if payload is None else json.dumps(payload).encode(), headers=h)
        try:
            r = urllib.request.urlopen(req, timeout=5)
            return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def propose(self, name="Caller-2"):
        return cp.propose(self.s.dir, "ORCH", "add-name", {"role": "caller", "name": name}, WHY, "Pat")


class TheList(Base):
    def test_proposals_that_wait_are_listed_with_their_line(self):
        self.propose()
        code, d = self.call("/api/configurations")
        self.assertEqual(code, 200)
        self.assertEqual([(p["id"], p["kind"], p["text"]) for p in d["proposals"]], [(1, "add-name", f"Add Caller-2 to the caller role: {WHY}")])
        self.assertEqual(d["proposals"][0]["change"], {"role": "caller", "name": "Caller-2"})

    def test_decided_ones_and_an_off_setting_list_nothing(self):
        self.propose()
        cp.ignore(self.s.dir, 1, "Pat")
        self.assertEqual(self.call("/api/configurations")[1]["proposals"], [])
        (self.s.dir / "config.toml").write_text('[board]\nowner = "Pat"\n')
        self.assertEqual(self.call("/api/configurations")[1], {"enabled": False})


class TheDecision(Base):
    def test_accept_applies_it_and_returns_the_new_state(self):
        self.propose()
        code, d = self.call("/api/configuration/proposal", {"id": 1, "decision": "accepted"})
        self.assertEqual(code, 200, d)
        self.assertEqual(d["proposals"], [])
        caller = next(r for r in d["applied"]["roles"] if r["role"] == "caller")
        self.assertEqual(caller["names"], ["Caller-1", "Caller-2"])
        self.assertEqual(cp.read(self.s.dir)[0]["status"], "accepted")

    def test_ignore_changes_nothing_else(self):
        self.propose()
        before = cfgs.applied(self.s.dir)
        code, d = self.call("/api/configuration/proposal", {"id": 1, "decision": "ignored"})
        self.assertEqual((code, d["proposals"]), (200, []))
        self.assertEqual(cfgs.applied(self.s.dir), before)
        self.assertEqual(cp.read(self.s.dir)[0]["status"], "ignored")

    def test_refusals(self):
        self.propose()
        for body, word in (({"id": 1, "decision": "yes"}, "accepted or ignored"), ({"id": "1", "decision": "accepted"}, "proposal number"), ({"decision": "accepted"}, "proposal number"),
                           ({"id": 9, "decision": "accepted"}, "no proposal #9")):
            code, d = self.call("/api/configuration/proposal", body)
            self.assertEqual(code, 400, body)
            self.assertIn(word, json.dumps(d), body)
        self.call("/api/configuration/proposal", {"id": 1, "decision": "accepted"})
        code, d = self.call("/api/configuration/proposal", {"id": 1, "decision": "accepted"})
        self.assertEqual(code, 400)
        self.assertIn("already accepted", json.dumps(d))

    def test_off_means_off(self):
        self.propose()
        (self.s.dir / "config.toml").write_text('[board]\nowner = "Pat"\n')
        code, d = self.call("/api/configuration/proposal", {"id": 1, "decision": "accepted"})
        self.assertEqual(code, 400)
        self.assertIn("are off", json.dumps(d))
        self.assertEqual(cfgs.applied(self.s.dir)["roles"][0]["names"], ["Caller-1"])


if __name__ == "__main__":
    unittest.main()
