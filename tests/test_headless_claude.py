"""The board's own claude -p rounds (casual, autopilot, idle drafts) read other agents' chat lines and card words, so they run with no
tools, no MCP servers, no skills, no saved session, from a fresh empty folder. agentboard run is the one that works in a repo: left alone."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import agentchat, runs


class Fake:
    """Stands in for subprocess.run: records argv, the prompt on stdin and the working folder, and answers like claude -p."""
    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kw):
        cwd = kw.get("cwd")
        self.calls.append({"argv": list(argv), "input": kw.get("input"), "cwd": cwd, "cwd_existed": bool(cwd) and Path(cwd).is_dir(),
                           "cwd_files": sorted(os.listdir(cwd)) if cwd and Path(cwd).is_dir() else None})
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps({"result": "ok then"}), stderr="")


class HeadlessRounds(unittest.TestCase):
    def setUp(self):
        os.environ.pop("AGENTBOARD_LOCKDOWN", None)
        self.fake = Fake()
        p = mock.patch("subprocess.run", self.fake)
        p.start()
        self.addCleanup(p.stop)

    def check(self, call):
        argv = call["argv"]
        i = argv.index("--tools")
        self.assertEqual(argv[i + 1], "", "--tools must be followed by an empty list (no tools at all)")
        for flag in ("--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence", "--max-budget-usd"):
            self.assertIn(flag, argv)
        for flag in ("--dangerously-skip-permissions", "--permission-mode", "--allowedTools", "--allowed-tools", "--add-dir", "--mcp-config"):
            self.assertNotIn(flag, argv)
        self.assertTrue(call["cwd_existed"], "it runs in a real folder")
        self.assertEqual(call["cwd_files"], [], "the folder is empty")
        self.assertTrue(str(Path(call["cwd"]).resolve()).startswith(str(Path(tempfile.gettempdir()).resolve())), call["cwd"])
        self.assertNotEqual(Path(call["cwd"]).resolve(), Path.cwd().resolve())
        self.assertFalse(Path(call["cwd"]).exists(), "and it is removed afterwards")

    def test_the_casual_line_has_no_tools_and_runs_from_an_empty_temp_folder(self):
        agentchat.casual_line("claude", "haiku", 0.05, {"sender": "AGENT-1", "text": "x" * 40})
        self.assertEqual(len(self.fake.calls), 1)
        self.check(self.fake.calls[0])
        self.assertIn("x" * 40, self.fake.calls[0]["input"])   # the message still reaches it, on stdin

    def test_the_idle_and_autopilot_drafter_has_no_tools_either(self):
        agentchat._ask_model("claude", "haiku", 0.05, "draft one reply to this inbox")
        self.assertEqual(len(self.fake.calls), 1)
        self.check(self.fake.calls[0])
        self.assertEqual(self.fake.calls[0]["input"], "draft one reply to this inbox")

    def test_the_model_and_budget_still_go_through(self):
        agentchat._ask_model("claude", "haiku", 0.25, "p")
        argv = self.fake.calls[0]["argv"]
        self.assertEqual(argv[argv.index("--model") + 1], "haiku")
        self.assertEqual(argv[argv.index("--max-budget-usd") + 1], "0.25")
        self.assertEqual(argv[:2], ["claude", "-p"])

    def test_agentboard_run_is_not_given_the_no_tools_flags(self):
        """It is meant to work in a repo with the permissions an interactive agent there has (the security audit notes this)."""
        src = Path(runs.__file__).read_text()
        self.assertNotIn('"--tools"', src)
        self.assertIn('"--max-budget-usd"', src)


if __name__ == "__main__":
    unittest.main()
