"""Starting the day (Nov 13): the board says when ORCH is not running and puts the prompt that starts it one click away, on every front
tab. It gives the words and starts nothing: the owner pastes them into whatever agent they use. `agentboard orch` prints the same prompt."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli, prompt
from agentboard.store import Store

PAGE = (Path(__file__).resolve().parent.parent / "src" / "agentboard" / "static" / "index.html").read_text()


class OrchCommand(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        self.s = Store(Path(self.tmp.name).resolve() / "proj" / ".agentboard")
        env["AGENTBOARD_DIR"] = str(self.s.dir)
        env["AGENTBOARD_HOME"] = str(Path(self.tmp.name).resolve() / "home")
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        self.s.add("Spa shortlist", status="todo", task_id="spa")

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(list(argv))
        return out.getvalue()

    def test_prints_the_prompt_the_button_copies(self):
        out = self.run_cli("orch")
        self.assertTrue(out.startswith("# You are ORCH"))
        self.assertIn("Spa shortlist", out)
        want = prompt.build_orch_prompt(self.s.load(), self.s.dir, port=8765)
        self.assertEqual(out.splitlines()[0], want.splitlines()[0])
        self.assertEqual(len(out.splitlines()), len((want + "\n").splitlines()))

    def test_port_is_named_when_given(self):
        self.assertIn("9001", self.run_cli("orch", "--port", "9001"))

    def test_it_starts_nothing_and_runs_on_a_locked_machine(self):
        before = self.s.load()
        with mock.patch.dict(os.environ, {"AGENTBOARD_LOCKDOWN": "1"}), mock.patch("subprocess.Popen") as popen:
            out = self.run_cli("orch")
        self.assertTrue(out.startswith("# You are ORCH"))
        popen.assert_not_called()
        self.assertEqual(before, self.s.load())


class OrchOnThePage(unittest.TestCase):
    def test_the_line_says_when_orch_is_away(self):
        self.assertIn("'ORCH is not running'", PAGE)
        self.assertIn("classList.toggle('orch-down', down)", PAGE)
        self.assertIn("orchGraceMs = 90000", PAGE)   # ORCH between two waits is not gone

    def test_copy_prompt_is_the_main_button_in_the_panel_and_on_the_empty_tabs(self):
        panel = PAGE[PAGE.index("function orchStart("):PAGE.index("function orchArrived(")]
        self.assertIn('class="btn primary orch-copy">Copy prompt</button>', panel)
        self.assertIn("Claude Code, Devin, Copilot", panel)   # any agent, not one vendor's
        offer = PAGE[PAGE.index("const orchOffer"):PAGE.index("let dogOpen")]
        self.assertIn('class="btn primary orch-copy">Copy prompt</button>', offer)
        self.assertIn("watch the agents work.</p>${orchOffer()}", PAGE)
        self.assertIn("${live.length ? '' : orchOffer()}", PAGE)

    def test_the_claude_line_is_an_extra_and_matches_the_command(self):
        self.assertIn("""ORCH_CLAUDE = 'claude -n ORCH "$(agentboard orch)"'""", PAGE)
        self.assertNotIn("ORCH_SAY", PAGE)

    def test_the_board_only_gives_words(self):
        block = PAGE[PAGE.index("let orchUp = null"):PAGE.index("let dogOpen")]
        for word in ("/api/spawn", "/api/dispatch", "method: 'POST'", "api('"):
            self.assertNotIn(word, block)

    def test_a_board_with_no_orch_offers_nothing(self):
        self.assertIn("if (chatFirstLoad || !cfg || !cfg.dispatch) return;", PAGE)

    def test_orch_arriving_is_shown(self):
        self.assertIn("ORCH is here", PAGE)
        self.assertIn("if (was === false && orchUp) orchArrived();", PAGE)


if __name__ == "__main__":
    unittest.main()
