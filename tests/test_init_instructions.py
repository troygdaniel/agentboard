"""`agentboard init` can connect the agents (overnight-ux-init-agent-instructions, Nov 7): add agentboard's instructions to the CLAUDE.md or
AGENTS.md that is already in the folder, when the person says yes (at a terminal) or passes --instructions. It only appends, between two comment
lines; it never rewrites what is there, never follows a link, never creates a file unasked, and a second run changes nothing."""
import contextlib
import io
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli


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
                self.assertTrue(added.lstrip("\n").startswith(cli.INSTR_START + "\n"))
                self.assertTrue(added.endswith(cli.INSTR_END + "\n"))
                self.assertTrue(added.startswith(lead + cli.INSTR_START), repr(added[:6]))   # exactly one blank line before the block (none in an empty file)
                self.assertIn("agentboard start", added)
                self.assertIn("added agentboard's instructions to CLAUDE.md", out)

    def test_the_block_is_what_agentboard_instructions_prints(self):
        (self.here / "CLAUDE.md").write_text("x\n")
        self.init("--instructions", "--no-demo")
        block = self.read().split(cli.INSTR_START + "\n", 1)[1].rsplit("\n" + cli.INSTR_END, 1)[0]
        self.assertEqual(block, cli._instructions_text(self.here / ".agentboard").rstrip())

    def test_a_second_run_changes_nothing(self):
        (self.here / "CLAUDE.md").write_text("# Notes\n")
        self.init("--instructions", "--no-demo")
        before = self.read()
        out = self.init("--instructions")
        self.assertEqual(self.read(), before)
        self.assertEqual(before.count(cli.INSTR_START), 1)
        self.assertIn("CLAUDE.md already has agentboard's instructions", out)

    def test_a_file_that_already_has_the_lines_by_hand_is_left_alone(self):
        (self.here / "CLAUDE.md").write_text("## Agent board\n\nmy own copy\n")
        self.init("--instructions", "--no-demo")
        self.assertEqual(self.read(), "## Agent board\n\nmy own copy\n")

    def test_claude_md_is_preferred_and_agents_md_is_used_when_it_is_the_only_one(self):
        (self.here / "CLAUDE.md").write_text("a\n")
        (self.here / "AGENTS.md").write_text("b\n")
        self.init("--instructions", "--no-demo")
        self.assertIn(cli.INSTR_START, self.read("CLAUDE.md"))
        self.assertEqual(self.read("AGENTS.md"), "b\n")
        (self.here / "CLAUDE.md").unlink()
        os.rename(self.here / ".agentboard", self.here / "old")
        self.init("--instructions", "--no-demo")
        self.assertIn(cli.INSTR_START, self.read("AGENTS.md"))

    def test_with_neither_file_the_flag_creates_agents_md_and_nothing_else_does(self):
        self.init("--no-demo", tty=True, answers=["y"])
        self.assertFalse((self.here / "AGENTS.md").exists())                    # no file, no question, no creation
        self.assertEqual(self.asked, [])
        os.rename(self.here / ".agentboard", self.here / "old")
        self.init("--instructions", "--no-demo")
        self.assertIn(cli.INSTR_START, self.read("AGENTS.md"))

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


class TheLinks(Base):
    """Cross-review xr-init-instructions-symlink: with CLAUDE.md and AGENTS.md both links, --instructions wrote through AGENTS.md into another folder."""

    def setUp(self):
        super().setUp()
        self.shared = self.here.parent / "shared"
        self.shared.mkdir()
        self.targets = {}
        for name in ("CLAUDE.md", "AGENTS.md"):
            (self.shared / name).write_text(f"{name} of the whole team\n")
            self.targets[name] = (self.shared / name).read_bytes()

    def untouched(self):
        for name, data in self.targets.items():
            self.assertEqual((self.shared / name).read_bytes(), data, f"{name} in the shared folder was written through")
        self.assertEqual(sorted(p.name for p in self.shared.iterdir()), ["AGENTS.md", "CLAUDE.md"])

    def test_both_files_links_writes_nothing_anywhere_and_says_why(self):
        for name in self.targets:
            os.symlink(self.shared / name, self.here / name)
        out = self.init("--instructions", "--no-demo")
        self.untouched()
        self.assertIn("AGENTS.md here is a link, and agentboard never writes through a link", out)
        self.assertIn("agentboard instructions", out.split("next:")[1])               # nothing was added, so the paste step stays on the list
        self.assertTrue((self.here / ".agentboard" / "tasks.json").exists())          # the board itself is still set up
        self.assertTrue((self.here / "AGENTS.md").is_symlink())                        # and the link is still a link

    def test_only_agents_md_a_link_and_no_claude_md(self):
        os.symlink(self.shared / "AGENTS.md", self.here / "AGENTS.md")
        out = self.init("--instructions", "--no-demo")
        self.untouched()
        self.assertIn("is a link", out)

    def test_a_link_to_nothing_is_not_created_through(self):
        os.symlink(self.shared / "gone.md", self.here / "AGENTS.md")
        self.init("--instructions", "--no-demo")
        self.assertFalse((self.shared / "gone.md").exists())

    def test_a_claude_md_link_with_a_real_agents_md_writes_the_real_one_only(self):
        os.symlink(self.shared / "CLAUDE.md", self.here / "CLAUDE.md")
        (self.here / "AGENTS.md").write_text("mine\n")
        self.init("--instructions", "--no-demo")
        self.untouched()
        self.assertIn(cli.INSTR_START, self.read("AGENTS.md"))

    def test_the_append_itself_refuses_a_link_even_when_the_check_before_it_was_skipped(self):
        link = self.here / "AGENTS.md"
        os.symlink(self.shared / "AGENTS.md", link)
        with self.assertRaises(OSError):
            cli._add_instructions(link, self.here / ".agentboard")
        self.untouched()
        os.unlink(link)
        os.symlink(self.shared / "later.md", link)                                    # a link to nothing: O_CREAT must not create the target
        with self.assertRaises(OSError):
            cli._add_instructions(link, self.here / ".agentboard")
        self.assertFalse((self.shared / "later.md").exists())


class TheFileMode(unittest.TestCase):
    """Cross-review xr-init-instructions-agents-md-mode: the real CLI runs under umask 077, and the file `init --instructions` created came out 0600,
    unreadable to a teammate or CI. The in-process tests never tighten the umask, so this one runs the real command in a subprocess under umask 022."""

    def run_init(self, folder, *extra, umask=0o022):
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
        env["HOME"] = str(folder / "home")
        (folder / "home").mkdir(exist_ok=True)
        got = subprocess.run([sys.executable, "-m", "agentboard", "init", "--no-demo", *extra], cwd=folder / "proj", env=env, capture_output=True, text=True,
                             preexec_fn=lambda: os.umask(umask), timeout=60)
        self.assertEqual(got.returncode, 0, got.stderr)
        return got.stdout

    def mode(self, path):
        return stat.S_IMODE(path.stat().st_mode)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name).resolve()
        (self.folder / "proj").mkdir()

    def test_a_new_agents_md_is_readable_like_gitignore_while_the_board_stays_private(self):
        self.run_init(self.folder, "--instructions")
        proj = self.folder / "proj"
        self.assertEqual(self.mode(proj / "AGENTS.md"), 0o644)
        self.assertEqual(self.mode(proj / ".gitignore"), 0o644)                       # the file the same command already wrote for others
        self.assertEqual(self.mode(proj / ".agentboard"), 0o700)                      # task data is still private
        self.assertEqual(self.mode(proj / ".agentboard" / "tasks.json") & 0o077, 0)

    def test_it_follows_the_users_umask_not_a_fixed_mode(self):
        self.run_init(self.folder, "--instructions", umask=0o002)
        self.assertEqual(self.mode(self.folder / "proj" / "AGENTS.md"), 0o664)

    def test_an_existing_file_keeps_its_mode(self):
        claude = self.folder / "proj" / "CLAUDE.md"
        claude.write_text("# notes\n")
        os.chmod(claude, 0o640)
        self.run_init(self.folder, "--instructions")
        self.assertEqual(self.mode(claude), 0o640)
        self.assertIn(cli.INSTR_START, claude.read_text())

    def test_agentboard_umask_still_wins_when_the_user_set_it(self):
        env_umask = {"AGENTBOARD_UMASK": "077"}
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        env.update(env_umask, PYTHONPATH=os.pathsep.join(p for p in sys.path if p), HOME=str(self.folder / "home"))
        (self.folder / "home").mkdir(exist_ok=True)
        got = subprocess.run([sys.executable, "-m", "agentboard", "init", "--no-demo", "--instructions"], cwd=self.folder / "proj", env=env,
                             capture_output=True, text=True, preexec_fn=lambda: os.umask(0o022), timeout=60)
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertTrue((self.folder / "proj" / "AGENTS.md").exists())


class TheQuestion(Base):
    def test_at_a_terminal_it_asks_once_when_a_file_is_there(self):
        (self.here / "CLAUDE.md").write_text("x\n")
        out = self.init("--no-demo", tty=True, answers=["y"])
        self.assertEqual(len(self.asked), 1)
        self.assertIn("CLAUDE.md", self.asked[0])
        self.assertIn(cli.INSTR_START, self.read())
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
        (self.here / "CLAUDE.md").write_text(f"{cli.INSTR_START}\nmine\n{cli.INSTR_END}\n")
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
