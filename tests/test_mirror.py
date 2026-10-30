"""The mirror: a session's SendMessage call lands on the chat as that session, through the hook; hooks install; me."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli, hooks
from agentboard.store import BoardError, Store

PAYLOAD = {"session_id": "59fd155b-4f7d-5229-9f4a-eb16f1f82627", "transcript_path": "/x.jsonl", "cwd": "/proj", "hook_event_name": "PostToolUse",
           "tool_name": "SendMessage", "tool_input": {"to": "AGENT-2 [3fa9c1]", "message": "The retries card is done; the queue test is yours if you want it.\nSee harden-webhook-retries, 12 tests pass.", "summary": "hand off"},
           "tool_response": {"ok": True}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        env = {k: v for k, v in os.environ.items() if not k.startswith(("AGENTBOARD_", "CLAUDE_CODE_SESSION_ID"))}
        env["AGENTBOARD_HOME"] = str(self.root / "home")
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        self.proj = self.root / "proj"
        self.s = Store(self.proj / ".agentboard")
        self.s.dir.mkdir(parents=True)
        os.environ["AGENTBOARD_DIR"] = str(self.s.dir)
        self.s.set_chat_agents(True)

    def run_cli(self, *argv, stdin=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            with mock.patch("sys.stdin", io.StringIO(stdin or "")):
                try:
                    code = cli.main(list(argv))
                except SystemExit as e:
                    code = e.code
        return code, out.getvalue()


class MirrorTests(Base):
    def test_a_send_message_lands_as_the_session_that_sent_it(self):
        os.environ["CLAUDE_CODE_SESSION_ID"] = PAYLOAD["session_id"]
        self.run_cli("me", "--name", "AGENT-1")
        del os.environ["CLAUDE_CODE_SESSION_ID"]
        m = hooks.mirror_send_message(self.s, PAYLOAD)
        self.assertEqual((m["sender"], m["to"], m["via"], m["kind"]), ("AGENT-1", "AGENT-2", "mirror", "agent"))
        self.assertEqual(m["text"], "The retries card is done; the queue test is yours if you want it.")
        self.assertEqual(m["detail"], "See harden-webhook-retries, 12 tests pass.")

    def test_names_are_learned_from_claim_start_and_chat(self):
        os.environ["CLAUDE_CODE_SESSION_ID"] = "sid-orch"
        self.run_cli("chat", "send", "hello", "--name", "ORCH")
        os.environ["CLAUDE_CODE_SESSION_ID"] = "sid-two"
        self.run_cli("start", "A card", "--name", "AGENT-2")
        self.s.add("Queued", status="todo")
        os.environ["CLAUDE_CODE_SESSION_ID"] = "sid-three"
        self.run_cli("claim", "queued", "--name", "AGENT-3")
        names = {k: v["name"] for k, v in hooks.read_sessions(self.s.dir).items()}
        self.assertEqual(names, {"sid-orch": "ORCH", "sid-two": "AGENT-2", "sid-three": "AGENT-3"})
        del os.environ["CLAUDE_CODE_SESSION_ID"]
        m = hooks.mirror_send_message(self.s, dict(PAYLOAD, session_id="sid-orch"))
        self.assertEqual(m["sender"], "ORCH")

    def test_unknown_session_gets_a_handle_and_agentboard_name_wins(self):
        m = hooks.mirror_send_message(self.s, PAYLOAD)
        self.assertEqual(m["sender"], "session-59fd15")
        os.environ["AGENTBOARD_NAME"] = "AGENT-4"
        self.assertEqual(hooks.mirror_send_message(self.s, PAYLOAD)["sender"], "AGENT-4")

    def test_nothing_is_mirrored_to_main_without_text_for_other_tools_or_with_the_switch_off(self):
        self.assertIsNone(hooks.mirror_send_message(self.s, dict(PAYLOAD, tool_input={"to": "main", "message": "x"})))
        self.assertIsNone(hooks.mirror_send_message(self.s, dict(PAYLOAD, tool_input={"to": "AGENT-2", "message": ""})))
        self.assertIsNone(hooks.mirror_send_message(self.s, dict(PAYLOAD, tool_name="Bash")))
        self.s.set_chat_agents(False)
        self.assertIsNone(hooks.mirror_send_message(self.s, PAYLOAD))
        self.assertEqual(len(self.s.chat_list()), 2)   # the switch's own two notices only

    def test_mirrored_lines_are_not_inbox_news_and_show_in_the_terminal_as_mirrored(self):
        from agentboard import agentchat
        m = hooks.mirror_send_message(self.s, PAYLOAD)
        self.assertNotIn(m["seq"], [x["seq"] for x in self.s.chat_inbox("AGENT-2")])   # it already has the private message
        self.assertIn("(mirrored)", agentchat.chat_line(m))

    def test_the_hook_command_never_fails_the_agent(self):
        code, out = self.run_cli("hook", "send-message", stdin=json.dumps(PAYLOAD))
        self.assertIsNone(code)
        self.assertEqual(out, "")
        self.assertEqual(self.s.chat_list()[-1]["via"], "mirror")
        for bad in ("not json", "", json.dumps({"tool_name": "SendMessage"}), json.dumps([1, 2])):
            code, out = self.run_cli("hook", "send-message", stdin=bad)
            self.assertIsNone(code)
            self.assertEqual(out, "")
        del os.environ["AGENTBOARD_DIR"]
        here = os.getcwd()
        self.addCleanup(os.chdir, here)
        os.chdir(self.root)   # no board anywhere up from here
        code, out = self.run_cli("hook", "send-message", stdin=json.dumps(PAYLOAD))
        self.assertIsNone(code)


class InstallTests(Base):
    def test_install_creates_or_merges_settings_and_is_idempotent(self):
        code, out = self.run_cli("hooks", "status")
        self.assertIn("not installed", out)
        code, out = self.run_cli("hooks", "install")
        self.assertIn("installed:", out)
        p = self.proj / ".claude" / "settings.json"
        d = json.loads(p.read_text())
        self.assertEqual(d["hooks"]["PostToolUse"], [{"matcher": "SendMessage", "hooks": [{"type": "command", "command": "agentboard hook send-message"}]}])
        code, out = self.run_cli("hooks", "install")
        self.assertIn("already installed", out)
        self.assertEqual(len(json.loads(p.read_text())["hooks"]["PostToolUse"]), 1)
        # existing settings and hooks are kept
        p.write_text(json.dumps({"permissions": {"allow": ["Bash(ls)"]}, "hooks": {"PostToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "echo hi"}]}]}}))
        hooks.install(self.proj)
        d = json.loads(p.read_text())
        self.assertEqual(d["permissions"], {"permissions": {"allow": ["Bash(ls)"]}}["permissions"])
        self.assertEqual([e["matcher"] for e in d["hooks"]["PostToolUse"]], ["Edit", "SendMessage"])
        p.write_text("{not json")
        with self.assertRaises(BoardError):
            hooks.install(self.proj)
        code, out = self.run_cli("hooks", "status", "--project", str(self.root / "elsewhere"))
        self.assertIn("not installed", out)


if __name__ == "__main__":
    unittest.main()
