"""`agentboard init` can connect the agents (overnight-ux-init-agent-instructions, Nov 7): add agentboard's instructions to the CLAUDE.md or
AGENTS.md that is already in the folder, when the person says yes (at a terminal) or passes --instructions. It only appends, between two comment
lines; it never rewrites what is there, never follows a link, never creates a file unasked, and a second run changes nothing."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import agentfiles, cli


class Tty(io.StringIO):
    def isatty(self):
        return True


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.here = Path(self.tmp.name).resolve() / "proj"
        self.here.mkdir()
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        old = os.getcwd()
        os.chdir(self.here)
        self.addCleanup(os.chdir, old)

    def init(self, *argv, tty=False, answers=None):
        out = Tty() if tty else io.StringIO()
        asked = []

        def fake_input(prompt=""):
            asked.append(prompt)
            if not answers:
                raise EOFError
            return answers.pop(0)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()), mock.patch("sys.stdin", mock.Mock(isatty=lambda: tty)), \
                mock.patch("builtins.input", fake_input):
            cli.main(["init", *argv])
        self.asked = asked
        return out.getvalue()

    def read(self, name="CLAUDE.md"):
        return (self.here / name).read_text()


class TheFlag(Base):
    def test_it_appends_between_markers_and_leaves_what_was_there_alone(self):
        for original, lead in (("# Notes\n\nOne line.\n", "\n"), ("# Notes\n\nNo newline at the end", "\n\n"), ("", ""),
                               ("Trailing spaces  \n\n\n", "\n"), ("windows\r\nlines\r\n", "\n"), ("\tindented\n   \n", "\n")):
            with self.subTest(original=original[-12:]):
                for f in (".agentboard", "CLAUDE.md"):
                    p = self.here / f
                    (p.unlink() if p.is_file() else __import__("shutil").rmtree(p, ignore_errors=True)) if p.exists() else None
                (self.here / "CLAUDE.md").write_bytes(original.encode())   # bytes both ways: a Windows file's line ends must come back as they were
                out = self.init("--instructions", "--no-demo")
                text = (self.here / "CLAUDE.md").read_bytes().decode()
                self.assertTrue(text.startswith(original))                      # only appended
                added = text[len(original):]
                self.assertTrue(added.lstrip("\n").startswith(agentfiles.INSTR_START + "\n"))
                self.assertTrue(added.endswith(agentfiles.INSTR_END + "\n"))
                self.assertTrue(added.startswith(lead + agentfiles.INSTR_START), repr(added[:6]))   # exactly one blank line before the block (none in an empty file)
                self.assertIn("agentboard start", added)
                self.assertIn("added agentboard's instructions to CLAUDE.md", out)

    def test_the_block_is_what_agentboard_instructions_prints(self):
        (self.here / "CLAUDE.md").write_text("x\n")
        self.init("--instructions", "--no-demo")
        block = self.read().split(agentfiles.INSTR_START + "\n", 1)[1].rsplit("\n" + agentfiles.INSTR_END, 1)[0]
        self.assertEqual(block, cli._instructions_text(self.here / ".agentboard").rstrip())

    def test_a_second_run_changes_nothing(self):
        (self.here / "CLAUDE.md").write_text("# Notes\n")
        self.init("--instructions", "--no-demo")
        before = self.read()
        out = self.init("--instructions")
        self.assertEqual(self.read(), before)
        self.assertEqual(before.count(agentfiles.INSTR_START), 1)
        self.assertIn("CLAUDE.md already has agentboard's instructions", out)

    def test_a_file_that_already_has_the_lines_by_hand_is_left_alone(self):
        (self.here / "CLAUDE.md").write_text("## Agent board\n\nmy own copy\n")
        self.init("--instructions", "--no-demo")
        self.assertEqual(self.read(), "## Agent board\n\nmy own copy\n")

    def test_claude_md_is_preferred_and_agents_md_is_used_when_it_is_the_only_one(self):
        (self.here / "CLAUDE.md").write_text("a\n")
        (self.here / "AGENTS.md").write_text("b\n")
        self.init("--instructions", "--no-demo")
        self.assertIn(agentfiles.INSTR_START, self.read("CLAUDE.md"))
        self.assertEqual(self.read("AGENTS.md"), "b\n")
        (self.here / "CLAUDE.md").unlink()
        os.rename(self.here / ".agentboard", self.here / "old")
        self.init("--instructions", "--no-demo")
        self.assertIn(agentfiles.INSTR_START, self.read("AGENTS.md"))

    def test_with_neither_file_the_flag_creates_agents_md_and_nothing_else_does(self):
        self.init("--no-demo", tty=True, answers=["y"])
        self.assertFalse((self.here / "AGENTS.md").exists())                    # no file, no question, no creation
        self.assertEqual(self.asked, [])
        os.rename(self.here / ".agentboard", self.here / "old")
        self.init("--instructions", "--no-demo")
        self.assertIn(agentfiles.INSTR_START, self.read("AGENTS.md"))

    def test_a_link_is_never_followed(self):
        target = self.here.parent / "elsewhere.md"
        target.write_text("not yours\n")
        os.symlink(target, self.here / "CLAUDE.md")
        self.init("--instructions", "--no-demo")
        self.assertEqual(target.read_text(), "not yours\n")                      # the link's target is untouched
        self.assertTrue((self.here / "AGENTS.md").exists())                     # a real file was made instead

    def test_a_file_that_cannot_be_written_is_said_and_the_board_is_still_set_up(self):
        (self.here / "CLAUDE.md").write_text("x\n")
        os.chmod(self.here / "CLAUDE.md", 0o444)
        self.addCleanup(os.chmod, self.here / "CLAUDE.md", 0o644)
        out = self.init("--instructions", "--no-demo")
        self.assertIn("could not write CLAUDE.md", out)
        self.assertIn("agentboard instructions", out)                           # and the manual way is still offered
        self.assertTrue((self.here / ".agentboard" / "tasks.json").exists())
        self.assertEqual(self.read(), "x\n")

    def test_no_instructions_wins(self):
        (self.here / "CLAUDE.md").write_text("x\n")
        self.init("--instructions", "--no-instructions", "--no-demo")
        self.assertEqual(self.read(), "x\n")


class TheQuestion(Base):
    def test_at_a_terminal_it_asks_once_when_a_file_is_there(self):
        (self.here / "CLAUDE.md").write_text("x\n")
        out = self.init("--no-demo", tty=True, answers=["y"])
        self.assertEqual(len(self.asked), 1)
        self.assertIn("CLAUDE.md", self.asked[0])
        self.assertIn(agentfiles.INSTR_START, self.read())
        self.assertNotIn("agentboard instructions ", out.split("next:")[1])      # connected: the paste step is not offered again

    def test_anything_but_yes_leaves_the_file_alone(self):
        for answers in (["n"], [""], ["maybe"], None):
            with self.subTest(answers=answers):
                d = self.here.parent / f"p{answers[0] if answers else 'eof'}x"
                d.mkdir()
                os.chdir(d)
                (d / "CLAUDE.md").write_text("x\n")
                out = self.init("--no-demo", tty=True, answers=answers)
                self.assertEqual((d / "CLAUDE.md").read_text(), "x\n")
                self.assertIn("agentboard instructions", out.split("next:")[1])  # the manual step stays on the list

    def test_it_never_asks_when_not_at_a_terminal_or_when_told_not_to_or_on_a_used_board(self):
        (self.here / "CLAUDE.md").write_text("x\n")
        self.init("--no-demo", tty=False, answers=["y"])
        self.assertEqual((self.asked, self.read()), ([], "x\n"))
        self.init("--no-demo", "--no-instructions", tty=True, answers=["y"])
        self.assertEqual((self.asked, self.read()), ([], "x\n"))
        from agentboard.store import Store
        Store(self.here / ".agentboard").add("Work", status="todo")
        self.init("--no-demo", tty=True, answers=["y"])
        self.assertEqual((self.asked, self.read()), ([], "x\n"))

    def test_it_does_not_ask_about_a_file_that_already_has_the_lines(self):
        (self.here / "CLAUDE.md").write_text(f"{agentfiles.INSTR_START}\nmine\n{agentfiles.INSTR_END}\n")
        self.init("--no-demo", tty=True, answers=["y"])
        self.assertEqual(self.asked, [])

    def test_the_demo_question_comes_first_and_both_can_be_answered(self):
        (self.here / "CLAUDE.md").write_text("x\n")
        self.init(tty=True, answers=["y", "y"])
        self.assertEqual(len(self.asked), 2)
        self.assertIn("sample cards", self.asked[0])
        self.assertIn("CLAUDE.md", self.asked[1])


if __name__ == "__main__":
    unittest.main()
