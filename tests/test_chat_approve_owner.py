"""Only the owner approves or declines an action an agent proposed in the chat (night sweep, card sweep-func-cli).
`chat approve N` and `chat decline N` took any caller: an agent could propose "buy lock.example" and approve it itself, and the decision was recorded as the
owner's. `configuration accept` already refuses a session that has an agent name ("it is the owner's word, not an agent's"); the two chat decisions now do the
same. A shell with no agent name set is the owner at a terminal, as everywhere else. The name is the session's own word, so this stops the wrong caller, not
a determined one; the board's button (the owner's page) is the real way."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli
from agentboard.store import Store


class ApproveOwnerOnly(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        self.p = self.s.chat_send("AGENT-2", "can I buy a domain?", propose="buy lock.example")

    def run_cli(self, name, *argv):
        out, err = io.StringIO(), io.StringIO()
        env = {"AGENTBOARD_DIR": str(self.s.dir)}
        if name:
            env["AGENTBOARD_NAME"] = name
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            if not name:
                os.environ.pop("AGENTBOARD_NAME", None)
            try:
                cli.main(["chat", *argv])
                code = 0
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
                if isinstance(e.code, str):
                    err.write(e.code)
        return code, out.getvalue(), err.getvalue()

    def status(self):
        m = next(m for m in self.s.chat_all() if m["seq"] == self.p["seq"]) if hasattr(self.s, "chat_all") else \
            next(m for m in self.s._read()["chat"] if m["seq"] == self.p["seq"])
        return m["action"]["status"]

    def test_an_agent_cannot_approve_or_decline_not_even_its_own_proposal(self):
        for name in ("AGENT-2", "AGENT-1", "ORCH"):
            for verb in ("approve", "decline"):
                code, _, err = self.run_cli(name, verb, str(self.p["seq"]))
                self.assertNotEqual(code, 0, (name, verb))
                self.assertIn("owner's word", err)
        self.assertEqual(self.status(), "proposed")

    def test_the_owner_at_a_terminal_with_no_name_decides(self):
        code, out, _ = self.run_cli("", "approve", str(self.p["seq"]))
        self.assertEqual(code, 0)
        self.assertEqual(self.status(), "approved")

    def test_the_owner_by_name_declines(self):
        code, _, _ = self.run_cli(self.s.owner, "decline", str(self.p["seq"]))
        self.assertEqual(code, 0)
        self.assertEqual(self.status(), "declined")

    def test_an_agent_still_reads_its_own_approvals(self):
        code, _, _ = self.run_cli("AGENT-2", "approvals")
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
