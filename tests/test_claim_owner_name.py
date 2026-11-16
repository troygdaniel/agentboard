"""claim and start refuse the owner's name and "all" as the agent name (night sweep, card finding-claim-and-start-accept-the-owner).

`agentboard claim <id> --name <the owner's name>` put the owner on the card as its agent, and the owner is the exception to "you may only report on
your own card". `--name all` made an agent called like the word a chat line is sent to. rename already refuses both as names the board keeps for
itself; the two commands an agent takes work with now say the same. The store is untouched, so the page (the owner's own channel) still works."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli
from agentboard.store import Store


class ClaimAndStartKeepTheBoardsNames(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name) / ".agentboard"
        d.mkdir(parents=True)
        (d / "config.toml").write_text('[board]\nowner = "Sam"\n')
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_") and k != "CLAUDE_CODE_SESSION_ID"}
        env["AGENTBOARD_DIR"] = str(d)
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        self.s = Store(d)
        self.s.add("A card to take", "", status="todo", task_id="take-me")

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                cli.main(list(argv))
                code = 0
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
                out.write("" if isinstance(e.code, int) else str(e.code))
        return code, out.getvalue()

    def test_claim_under_the_owners_name_or_all_is_refused_and_the_card_is_untouched(self):
        for name in ("Sam", "sam", " SAM ", "all", "All"):
            code, out = self.run_cli("claim", "take-me", "--name", name)
            self.assertNotEqual(code, 0, repr(name))
            self.assertIn("keeps for itself", out, repr(name))
        t = Store.get(self.s.load(), "take-me")
        self.assertEqual((t["status"], t.get("agent")), ("todo", None))

    def test_start_under_the_owners_name_or_all_is_refused_and_makes_no_card(self):
        for name in ("Sam", "ALL"):
            code, out = self.run_cli("start", "New work", "--name", name)
            self.assertNotEqual(code, 0, repr(name))
            self.assertIn("keeps for itself", out, repr(name))
        self.assertEqual([t["id"] for t in self.s.load()], ["take-me"])

    def test_the_name_from_the_environment_is_checked_too(self):
        with mock.patch.dict(os.environ, {"AGENTBOARD_NAME": "Sam"}):
            code, out = self.run_cli("claim", "take-me")
        self.assertNotEqual(code, 0)
        self.assertIn("keeps for itself", out)

    def test_an_agent_with_its_own_name_still_claims_and_starts(self):
        code, out = self.run_cli("claim", "take-me", "--name", "Samantha")
        self.assertEqual(code, 0, out)
        self.assertEqual(Store.get(self.s.load(), "take-me")["agent"], "Samantha")
        code, out = self.run_cli("start", "Other work", "--name", "ORCH")
        self.assertEqual(code, 0, out)

    def test_the_store_still_lets_the_owner_hold_a_card(self):   # the page's path: the owner takes a personal card under their own name
        self.assertEqual(self.s.claim("take-me", "Sam")["agent"], "Sam")


if __name__ == "__main__":
    unittest.main()
