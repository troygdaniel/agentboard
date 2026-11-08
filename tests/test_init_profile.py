"""A fresh install on a managed PC starts under the work profile (Troy, Nov 8: "yes to all"): `agentboard init` on the real command line writes
[board] profile = "work" into a NEW board's config.toml when the machine shows no home setup (no home plugin installed, no home environment variable,
no home file), says so, and asks first at a terminal. A board that already exists, a machine with any home signal, `--profile home` and a call from code
(a test, a script importing main) are never changed.

The real command line is run in subprocesses (main() with no argv is what the `agentboard` script calls) with the plugin metadata controlled, in a throwaway
HOME and folder; nothing reads a real board or a real home setup."""
import io
import os
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

from agentboard import cli, profile

SRC = str(Path(cli.__file__).resolve().parents[1])

CODE = r"""
import sys
from unittest import mock
sys.argv = ["agentboard"] + sys.argv[1:]
class EP:
    def __init__(self, name): self.name = name
eps = [EP(n) for n in {plugins!r}]
with mock.patch("importlib.metadata.entry_points", return_value=eps):
    from agentboard.cli import main
    main()
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        (self.home / ".config" / "agentboard").mkdir(parents=True)
        self.proj = self.tmp / "proj"
        self.proj.mkdir()

    def init(self, *args, plugins=(), env=None, cwd=None):
        e = {"HOME": str(self.home), "PATH": os.environ["PATH"], "PYTHONPATH": SRC, "PYTHONDONTWRITEBYTECODE": "1", **(env or {})}
        r = subprocess.run([sys.executable, "-c", CODE.format(plugins=list(plugins)), "init", "--no-demo", "--no-instructions", *args], env=e, cwd=cwd or self.proj,
                           capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
        return r.returncode, r.stdout + r.stderr

    def config(self, folder=None):
        return ((folder or self.proj) / ".agentboard" / "config.toml").read_text()


class TheFreshInstallStartsSafe(Base):
    def test_no_home_signal_means_the_work_profile_and_init_says_so(self):
        rc, out = self.init()
        self.assertEqual(rc, 0, out)
        self.assertIn('profile = "work"', self.config())
        self.assertIn("WORK PROFILE", out)
        self.assertIn("agentboard selfcheck", out)
        self.assertIn("--profile home", out)                                # and how to get the plain board

    def test_the_board_really_is_under_the_profile(self):
        self.init()
        e = {"HOME": str(self.home), "PATH": os.environ["PATH"], "PYTHONPATH": SRC, "PYTHONDONTWRITEBYTECODE": "1", "AGENTBOARD_DIR": str(self.proj / ".agentboard")}
        r = subprocess.run([sys.executable, "-m", "agentboard", "profile"], env=e, cwd=self.tmp, capture_output=True, text=True, timeout=60)
        self.assertIn("profile: WORK", r.stdout)
        self.assertIn("on by board", r.stdout)

    def test_a_second_init_changes_nothing(self):
        self.init()
        before = self.config()
        rc, out = self.init()
        self.assertEqual(self.config(), before)
        self.assertIn("already set up", out)
        self.assertNotIn("WORK PROFILE", out)


class AnyHomeSignalKeepsTheNormalBoard(Base):
    def assertPlain(self, *args, **kw):
        rc, out = self.init(*args, **kw)
        self.assertEqual(rc, 0, out)
        self.assertNotIn("profile", self.config().split("# agentboard config")[0], self.config()[:200])
        self.assertNotIn("WORK PROFILE", out)

    def test_a_home_plugin_installed(self):
        self.assertPlain(plugins=["home"])

    def test_each_home_environment_variable(self):
        for k in ("AGENTBOARD_PLUGINS", "AGENTBOARD_TEXTS", "AGENTBOARD_TEXTS_REPLY", "AGENTBOARD_FACTS", "AGENTBOARD_SOMETHING_A_PLUGIN_ADDS"):
            with self.subTest(var=k):
                shutil_rmtree = __import__("shutil").rmtree
                shutil_rmtree(self.proj / ".agentboard", True)
                self.assertPlain(env={k: "1"})

    def test_each_home_file(self):
        for name in ("home.env", "facts-never.txt"):
            with self.subTest(file=name):
                __import__("shutil").rmtree(self.proj / ".agentboard", True)
                f = self.home / ".config" / "agentboard" / name
                f.write_text("x\n")
                self.assertPlain()
                f.unlink()

    def test_the_variables_the_program_itself_defines_are_not_home_signals(self):
        for k in sorted(profile.core_env()) + ["AGENTBOARD_NO_PLUGINS", "AGENTBOARD_NO_SOMETHING"]:
            if k == "AGENTBOARD_PLUGINS":
                continue
            __import__("shutil").rmtree(self.proj / ".agentboard", True)
            rc, out = self.init(env={k: "1"})
            self.assertIn("WORK PROFILE", out, k)

    def test_every_variable_the_source_names_is_either_defined_here_or_would_count_as_home(self):
        """A new public variable must be added to profile.CORE_ENV (or configschema.ENV), or a managed PC that sets it would be taken for a home setup."""
        import re
        names = set()
        for f in Path(cli.__file__).parent.glob("*.py"):
            names |= set(re.findall(r"AGENTBOARD_[A-Z0-9_]*[A-Z0-9]", f.read_text()))
        stray = sorted(n for n in names if n not in profile.core_env() and not n.startswith("AGENTBOARD_NO") and n != "AGENTBOARD_PLUGINS")
        self.assertEqual(stray, [], "an AGENTBOARD_ variable the source names is not in profile.CORE_ENV")

    def test_signals_are_names_never_values(self):
        marker = "marker" + "-" + "7"   # (a value that is plainly not a secret: the public-repo scan reads key-shaped assignments)
        with mock.patch.dict(os.environ, {"AGENTBOARD_SOMETHING_A_PLUGIN_ADDS": marker, "HOME": str(self.home)}):
            sig = profile.home_signals()
        self.assertTrue(sig)
        self.assertIn("AGENTBOARD_SOMETHING_A_PLUGIN_ADDS", " ".join(sig))
        self.assertNotIn(marker, " ".join(sig))

    def test_an_empty_or_off_value_is_not_a_signal(self):
        with mock.patch.dict(os.environ, {"AGENTBOARD_PLUGINS": "", "AGENTBOARD_TEXTS": "  ", "HOME": str(self.home)}, clear=False):
            with mock.patch("importlib.metadata.entry_points", return_value=[]):
                self.assertNotIn("AGENTBOARD_TEXTS", " ".join(profile.home_signals()))
        with mock.patch.dict(os.environ, {"AGENTBOARD_PLUGINS": "0", "HOME": str(self.home)}):
            with mock.patch("importlib.metadata.entry_points", return_value=[]):
                self.assertNotIn("AGENTBOARD_PLUGINS", " ".join(profile.home_signals()))


class WhatIsNeverChanged(Base):
    def test_a_board_that_already_exists_is_not_touched_even_on_a_machine_with_no_home_signal(self):
        (self.proj / ".agentboard").mkdir()
        (self.proj / ".agentboard" / "tasks.json").write_text('{"tasks": [{"id": "x", "title": "work in progress", "status": "todo"}]}')
        cfg = self.proj / ".agentboard" / "config.toml"
        cfg.write_text("[ui]\ndispatch = false\n")
        before = cfg.read_bytes(), (self.proj / ".agentboard" / "tasks.json").read_bytes()
        rc, out = self.init()
        self.assertEqual((cfg.read_bytes(), (self.proj / ".agentboard" / "tasks.json").read_bytes()), before)
        self.assertNotIn("WORK PROFILE", out)

    def test_an_existing_board_that_has_no_config_file_yet_gets_the_plain_one(self):
        (self.proj / ".agentboard").mkdir()
        (self.proj / ".agentboard" / "tasks.json").write_text('{"tasks": [{"id": "x", "title": "work in progress", "status": "todo"}]}')
        rc, out = self.init()
        self.assertNotIn('profile = "work"', self.config())
        self.assertNotIn("WORK PROFILE", out)

    def test_the_homes_own_board_is_unchanged(self):
        """The owner's home board: a config without a profile, on a machine with the home setup. A real init there is a no-op."""
        (self.proj / ".agentboard").mkdir()
        (self.proj / ".agentboard" / "tasks.json").write_text('{"tasks": []}')
        (self.proj / ".agentboard" / "config.toml").write_text('[board]\nowner = "Sam"\n\n[chat]\ncasual = true\n')
        (self.home / ".config" / "agentboard" / "home.env").write_text("x\n")
        before = self.config()
        self.init(plugins=["home"])
        self.assertEqual(self.config(), before)

    def test_home_on_the_command_line_and_in_the_environment_say_plain(self):
        for args, env in (((), {"AGENTBOARD_INIT_PROFILE": "home"}), (("--profile", "home"), {})):
            __import__("shutil").rmtree(self.proj / ".agentboard", True)
            rc, out = self.init(*args, env=env)
            self.assertNotIn('profile = "work"', self.config(), (args, env))

    def test_work_says_work_even_on_a_home_machine(self):
        (self.home / ".config" / "agentboard" / "home.env").write_text("x\n")
        rc, out = self.init("--profile", "work", plugins=["home"])
        self.assertIn('profile = "work"', self.config())
        rc2, out2 = self.init(env={"AGENTBOARD_INIT_PROFILE": "work"}, cwd=self.tmp)
        self.assertIn('profile = "work"', self.config(self.tmp))

    def test_a_typo_in_the_environment_means_auto_never_off(self):
        rc, out = self.init(env={"AGENTBOARD_INIT_PROFILE": "wrok"})
        self.assertIn('profile = "work"', self.config())


class ACallFromCodeIsUnchanged(unittest.TestCase):
    """cli.main([...]) with an argv (a test, a script) never looks at the machine: the plain board, as before this change."""

    def test_main_with_an_argv_writes_the_plain_board(self):
        tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        old = os.getcwd()
        os.chdir(tmp)
        self.addCleanup(os.chdir, old)
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        env["HOME"] = str(tmp)   # (a machine with no home files: the real one may have them)
        with mock.patch.dict(os.environ, env, clear=True), mock.patch("importlib.metadata.entry_points", return_value=[]), mock.patch("sys.stdout", io.StringIO()):
            self.assertEqual(profile.home_signals(), [])
            cli.main(["init", "--no-demo", "--no-instructions"])
        self.assertNotIn('profile = "work"', (tmp / ".agentboard" / "config.toml").read_text())

    def test_init_choice_table(self):
        with mock.patch.dict(os.environ, {k: v for k, v in os.environ.items() if k != profile.INIT_ENV}, clear=True):
            self.assertEqual(profile.init_choice(None, real_cli=True)[0], "auto")
            self.assertEqual(profile.init_choice(None, real_cli=False)[0], "home")
            self.assertEqual(profile.init_choice("work", real_cli=False)[0], "work")
            self.assertEqual(profile.init_choice("home", real_cli=True)[0], "home")
        with mock.patch.dict(os.environ, {profile.INIT_ENV: "work"}):
            self.assertEqual(profile.init_choice(None, real_cli=False)[0], "work")
            self.assertEqual(profile.init_choice("home", real_cli=True)[0], "home")   # the flag beats the environment
        with mock.patch.dict(os.environ, {profile.INIT_ENV: "bogus"}):
            self.assertEqual(profile.init_choice(None, real_cli=False)[0], "auto")


class AtATerminalItAsksFirst(unittest.TestCase):
    def run_init(self, answer, tty=True):
        tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        old = os.getcwd()
        os.chdir(tmp)
        self.addCleanup(os.chdir, old)
        a = Namespace(profile=None, _real_cli=True, demo=False, no_demo=True, no_instructions=True, add_instructions=False)

        class Tty(io.StringIO):
            def isatty(self):
                return tty
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        asked = []

        def fake_input(q):
            asked.append(q)
            if isinstance(answer, Exception):
                raise answer
            return answer
        with mock.patch.dict(os.environ, {**env, "HOME": str(tmp)}, clear=True), mock.patch("importlib.metadata.entry_points", return_value=[]), \
                mock.patch("sys.stdin", Tty()), mock.patch("sys.stdout", Tty()), mock.patch("builtins.input", fake_input):
            cli.cmd_init(a)
        return (tmp / ".agentboard" / "config.toml").read_text(), asked

    def test_enter_means_yes(self):
        cfg, asked = self.run_init("")
        self.assertIn('profile = "work"', cfg)
        self.assertEqual(len(asked), 1)
        self.assertIn("work profile", asked[0].lower())

    def test_no_gives_the_plain_board(self):
        cfg, asked = self.run_init("n")
        self.assertNotIn('profile = "work"', cfg)

    def test_a_closed_stdin_keeps_the_safe_default(self):
        cfg, asked = self.run_init(EOFError())
        self.assertIn('profile = "work"', cfg)

    def test_a_script_is_not_asked(self):
        cfg, asked = self.run_init("n", tty=False)
        self.assertEqual(asked, [])
        self.assertIn('profile = "work"', cfg)


class TheWordsAreWhereAPersonReadsThem(unittest.TestCase):
    README = (Path(cli.__file__).resolve().parents[2] / "README.md").read_text()

    def test_the_quick_start_says_a_fresh_install_starts_safe(self):
        quick = self.README.split("## Quick start", 1)[1].split("## The agent lifecycle", 1)[0]
        for phrase in ('profile = "work"', "agentboard init --profile home", "selfcheck", "managed", "never changed"):
            self.assertIn(phrase, quick)

    def test_init_help_names_the_three_choices(self):
        r = subprocess.run([sys.executable, "-m", "agentboard", "init", "--help"], env={"PATH": os.environ["PATH"], "PYTHONPATH": SRC, "PYTHONDONTWRITEBYTECODE": "1", "HOME": "/nonexistent"},
                           capture_output=True, text=True, timeout=30)
        self.assertIn("work,home,auto", r.stdout.replace(" ", ""))


if __name__ == "__main__":
    unittest.main()
