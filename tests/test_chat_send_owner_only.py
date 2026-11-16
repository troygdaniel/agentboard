"""An agent's session cannot post a chat line as the owner or as ORCH (card finding-chat-send-user-and-name-orch-own, found in sweep-func-cli).
`chat send --user` posted a line as the human, and `--name ORCH` or `--name <owner>` posted as ORCH or the owner, from any session: agents act on
owner lines (night mode, approvals), so the sender has to mean something. Now a session whose AGENTBOARD_NAME is an agent is refused all three, as
`chat approve` refuses it (tests/test_chat_approve_owner.py). ORCH keeps `--user`: it relays the owner's words. A shell with no agent name set is the
owner at a terminal, as everywhere else. The name is the session's own word, so this stops the wrong caller, not a determined one."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli
from agentboard.store import Store


class SendAsOwnerOrOrch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")

    def run_cli(self, name, *argv):
        out, err = io.StringIO(), io.StringIO()
        env = {"AGENTBOARD_DIR": str(self.s.dir)}
        if name:
            env["AGENTBOARD_NAME"] = name
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            if not name:
                os.environ.pop("AGENTBOARD_NAME", None)
            try:
                cli.main(["chat", "send", *argv])
                code = 0
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
                if isinstance(e.code, str):
                    err.write(e.code)
        return code, out.getvalue(), err.getvalue()

    def lines(self):
        return self.s.chat_list(limit=50)

    def test_an_agent_session_cannot_post_as_the_owner_or_orch(self):
        for argv in (["hello", "--user"], ["hello", "--name", "ORCH"], ["hello", "--name", self.s.owner], ["hello", "--user", "--name", "AGENT-2"]):
            code, _, err = self.run_cli("AGENT-2", *argv)
            self.assertNotEqual(code, 0, argv)
            self.assertIn("own name", err, argv)
        self.assertEqual(self.lines(), [])

    def test_the_agent_still_posts_as_itself(self):
        code, _, _ = self.run_cli("AGENT-2", "hello")
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli("AGENT-2", "hello again", "--name", "AGENT-2")
        self.assertEqual(code, 0)
        self.assertEqual([(m["sender"], m["kind"]) for m in self.lines()], [("AGENT-2", "agent"), ("AGENT-2", "agent")])

    def test_orch_relays_the_owner_with_user(self):
        code, _, _ = self.run_cli("ORCH", "night mode is on", "--user")
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli("ORCH", "take the next card", "--name", "ORCH")
        self.assertEqual(code, 0)
        self.assertEqual([(m["sender"], m["kind"]) for m in self.lines()], [(self.s.owner, "user"), ("ORCH", "agent")])

    def test_the_owner_at_a_terminal_with_no_name_posts_as_the_owner(self):
        code, _, _ = self.run_cli("", "hello", "--user")
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(self.s.owner, "hello again", "--user")
        self.assertEqual(code, 0)
        self.assertEqual([(m["sender"], m["kind"]) for m in self.lines()], [(self.s.owner, "user"), (self.s.owner, "user")])


if __name__ == "__main__":
    unittest.main()
