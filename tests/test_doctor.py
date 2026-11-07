"""agentboard doctor: read-only PASS/FAIL lines. It changes nothing and opens no socket; ps, lsof and git are faked unless a real git repo is the point."""
import os
import re
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli, doctor, lockdown
from agentboard.store import Store

AWS = "AKIA" + "ABCDEFGHIJKLMNOP"      # built in pieces so this file is not itself a hit
PHONE = "(416) 867-" + "5309"


class FakeRunner:
    """Stands in for subprocess.run for ps, lsof and git (git is only faked when a test gives it a table)."""
    def __init__(self, ps="", listen=(), conns=(), lsof_missing=False, git=None):
        self.ps, self.listen, self.conns, self.lsof_missing, self.git, self.calls = ps, list(listen), list(conns), lsof_missing, git or {}, []

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        if argv[0] == "ps":
            return subprocess.CompletedProcess(argv, 0, stdout=self.ps, stderr="")
        if argv[0] == "lsof":
            if self.lsof_missing:
                raise FileNotFoundError("lsof")
            names = self.listen if "-sTCP:LISTEN" in argv else self.conns
            return subprocess.CompletedProcess(argv, 0, stdout="p123\n" + "".join(f"f3\nn{n}\n" for n in names), stderr="")
        if argv[0] == "git":
            key = " ".join(argv[3:]) if argv[1] == "-C" else " ".join(argv[1:])
            rc, out = self.git.get(key, (128, ""))
            return subprocess.CompletedProcess(argv, rc, stdout=out, stderr="")
        raise AssertionError(f"doctor ran something unexpected: {argv}")


PS_SERVER = "  123 /Users/me/.local/bin/agentboard serve --no-open\n  456 /bin/zsh -l\n  789 agentboard doctor\n  790 grep agentboard serve\n"


def level_of(results, name):
    return [r[0] for r in results if r[1] == name]


class Listeners(unittest.TestCase):
    def test_loopback_only_passes(self):
        r = doctor.check_listeners(FakeRunner(PS_SERVER, listen=["127.0.0.1:8765", "[::1]:8765"], conns=["127.0.0.1:50000->127.0.0.1:8765"]))
        self.assertEqual([x[0] for x in r], [doctor.PASS, doctor.PASS])
        self.assertIn("127.0.0.1:8765", r[0][2])

    def test_a_listener_on_every_interface_fails(self):
        for name in ("*:8765", "[::]:8765", "0.0.0.0:8765", "192.168.1.20:8765"):
            r = doctor.check_listeners(FakeRunner(PS_SERVER, listen=[name]))
            self.assertEqual(r[0][0], doctor.FAIL, name)

    def test_a_connection_to_another_machine_fails(self):
        r = doctor.check_listeners(FakeRunner(PS_SERVER, listen=["127.0.0.1:8765"], conns=["127.0.0.1:5000->93.184.216.34:443", "127.0.0.1:50000->127.0.0.1:8765"]))
        self.assertEqual(level_of(r, "connections"), [doctor.FAIL])
        self.assertIn("93.184.216.34:443", r[1][2])

    def test_nothing_running_or_no_lsof_is_information_not_a_pass(self):
        self.assertEqual(doctor.check_listeners(FakeRunner("  1 /sbin/launchd\n"))[0][0], doctor.INFO)
        self.assertEqual(doctor.check_listeners(FakeRunner(PS_SERVER, lsof_missing=True))[0][0], doctor.INFO)

    def test_it_only_looks_at_the_servers_not_at_doctor_or_grep(self):
        runner = FakeRunner(PS_SERVER, listen=["127.0.0.1:8765"])
        doctor.check_listeners(runner)
        lsof = next(c for c in runner.calls if c[0] == "lsof")
        self.assertEqual(lsof[lsof.index("-p") + 1], "123")


class Locks(unittest.TestCase):
    def test_the_master_lock_state(self):
        self.assertEqual(doctor.check_locks({})[0][0], doctor.WARN)
        self.assertEqual(doctor.check_locks({"AGENTBOARD_LOCKDOWN": "1"})[0][0], doctor.PASS)
        self.assertEqual(doctor.check_locks({"AGENTBOARD_LOCKDOWN": "0"})[0][0], doctor.WARN)

    def test_narrow_locks_are_found_by_reading_the_package_not_from_a_list(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "x.py").write_text('LOCK = "AGENTBOARD_NO_THING"\n')
            with mock.patch.object(doctor, "_HERE", Path(d)):
                out = doctor.check_locks({"AGENTBOARD_NO_THING": "1"})
                self.assertIn("AGENTBOARD_NO_THING on", out[1][2])
                self.assertIn("AGENTBOARD_NO_THING off", doctor.check_locks({})[1][2])


class Files(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.board = Path(self.tmp.name) / ".agentboard"
        self.board.mkdir()
        (self.board / "tasks.json").write_text("{}")
        (self.board / "sub").mkdir()
        (self.board / "sub" / "x.json").write_text("{}")

    def modes(self, d, f):
        os.chmod(self.board, d)
        os.chmod(self.board / "sub", d)
        os.chmod(self.board / "tasks.json", f)
        os.chmod(self.board / "sub" / "x.json", f)

    def test_private_group_and_world(self):
        self.modes(0o700, 0o600)
        self.assertEqual(doctor.check_files(self.board)[0][0], doctor.PASS)
        self.modes(0o750, 0o640)
        self.assertEqual(doctor.check_files(self.board)[0][0], doctor.WARN)
        self.modes(0o755, 0o644)
        r = doctor.check_files(self.board)[0]
        self.assertEqual(r[0], doctor.FAIL)
        self.assertIn("chmod -R go-rwx", r[2])

    def test_a_missing_folder_is_information(self):
        self.assertEqual(doctor.check_files(Path(self.tmp.name) / "nope")[0][0], doctor.INFO)


class Git(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = Path(self.tmp.name).resolve() / "proj"
        self.proj.mkdir()
        self.board = self.proj / ".agentboard"
        self.board.mkdir()

    def git(self, *args):
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x.y", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x.y"}
        subprocess.run(["git", *args], cwd=self.proj, env=env, check=True, capture_output=True)

    def repo(self, files, ignore=True):
        self.git("init", "-q")
        if ignore:
            (self.proj / ".gitignore").write_text(".agentboard/\n")
        for name, text in files.items():
            (self.proj / name).write_text(text)
        self.git("add", "-A")

    def test_a_clean_repo_with_the_board_ignored_passes(self):
        self.repo({"a.py": "print('hi')\n"})
        r = doctor.check_git(self.proj, self.board, subprocess.run)
        self.assertEqual([x[0] for x in r], [doctor.PASS, doctor.PASS])

    def test_a_key_fails_a_phone_warns_and_neither_is_printed(self):
        self.repo({"k.py": f'KEY = "{AWS}"\n', "n.md": f"call {PHONE} tonight\n"})
        r = doctor.check_git(self.proj, self.board, subprocess.run)
        line = next(x for x in r if x[1] == "tracked files")
        self.assertEqual(line[0], doctor.FAIL)
        self.assertIn("k.py:1", line[2])
        self.assertIn("n.md:1", line[2])
        self.assertNotIn(AWS, line[2])
        self.assertNotIn("5309", line[2])

    def test_a_private_key_header_fails_and_a_key_like_assignment_only_warns(self):
        self.repo({"id.pem": "-----BEGIN " + "RSA PRIVATE KEY-----\nabc\n"})
        line = next(x for x in doctor.check_git(self.proj, self.board, subprocess.run) if x[1] == "tracked files")
        self.assertEqual(line[0], doctor.FAIL)
        self.assertIn("private key at id.pem:1", line[2])
        self.git("rm", "-q", "-f", "id.pem")
        (self.proj / "cfg.py").write_text('api_key = "' + "k3y9" * 8 + '"\nTOKEN_ENV = "AGENTBOARD_SOME_TOKEN_NAME_X"\n')
        self.git("add", "-A")
        line = next(x for x in doctor.check_git(self.proj, self.board, subprocess.run) if x[1] == "tracked files")
        self.assertEqual(line[0], doctor.WARN)
        self.assertIn("key-like assignment at cfg.py:1", line[2])
        self.assertNotIn("cfg.py:2", line[2])   # an environment variable NAME is not a secret

    def test_plain_placeholders_are_not_reported_but_real_looking_values_still_are(self):
        fiction = ("call 416-555-0123 or +14165550199 or (212) 555-0100 or 555-123-4567; sid AC" + "b" * 32 + " key AKIA" + "X" * 16 + "\n"
                   + 'TOKEN = "secret-token-do-not-leak-please"\n')
        self.repo({"docs.md": fiction})
        line = next(x for x in doctor.check_git(self.proj, self.board, subprocess.run) if x[1] == "tracked files")
        self.assertEqual(line[0], doctor.PASS, line)
        self.repo({"real.md": f"call {PHONE} or 416-867-5310 (a real-looking exchange)\n"})
        line = next(x for x in doctor.check_git(self.proj, self.board, subprocess.run) if x[1] == "tracked files")
        self.assertEqual(line[0], doctor.WARN)
        self.assertIn("real.md:1", line[2])

    def test_only_a_phone_number_is_a_warning(self):
        self.repo({"n.md": f"call {PHONE} tonight\n", "ok.py": "x = 1\n"})
        line = next(x for x in doctor.check_git(self.proj, self.board, subprocess.run) if x[1] == "tracked files")
        self.assertEqual(line[0], doctor.WARN)
        self.assertIn("phone number at n.md:1", line[2])

    def test_a_board_that_is_tracked_fails_and_one_not_ignored_warns(self):
        self.repo({"a.py": "x=1\n"}, ignore=False)
        r = next(x for x in doctor.check_git(self.proj, self.board, subprocess.run) if x[1] == "board in git")
        self.assertEqual(r[0], doctor.WARN)
        (self.board / "tasks.json").write_text("{}")
        self.git("add", "-f", ".agentboard/tasks.json")
        r = next(x for x in doctor.check_git(self.proj, self.board, subprocess.run) if x[1] == "board in git")
        self.assertEqual(r[0], doctor.FAIL)
        self.assertIn("git rm -r --cached", r[2])

    def test_the_boards_own_files_are_not_scanned_and_a_non_repo_is_information(self):
        self.repo({"a.py": "x=1\n"})
        (self.board / "tasks.json").write_text(f'{{"k": "{AWS}"}}')
        line = next(x for x in doctor.check_git(self.proj, self.board, subprocess.run) if x[1] == "tracked files")
        self.assertEqual(line[0], doctor.PASS)
        with tempfile.TemporaryDirectory() as plain:
            self.assertEqual(doctor.check_git(Path(plain), Path(plain) / ".agentboard", subprocess.run)[0][0], doctor.INFO)


class HooksConfigCode(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.proj = Path(self.tmp.name) / "proj"
        for d in (self.home / ".claude", self.proj / ".claude", self.proj / ".agentboard"):
            d.mkdir(parents=True)
        p = mock.patch.object(Path, "home", return_value=self.home)
        p.start()
        self.addCleanup(p.stop)

    def settings(self, where, text):
        (where / ".claude" / "settings.json").write_text(text)

    def test_hooks_are_listed_and_a_bare_agentboard_command_warns(self):
        self.settings(self.proj, '{"hooks": {"PostToolUse": [{"matcher": "SendMessage", "hooks": [{"type": "command", "command": "agentboard hook send-message"}]}]}}')
        r = doctor.check_hooks(self.proj)
        self.assertEqual([x[0] for x in r], [doctor.INFO, doctor.WARN])
        self.assertIn("PostToolUse[SendMessage] agentboard hook send-message", r[0][2])
        self.settings(self.proj, '{"hooks": {"PostToolUse": [{"matcher": "SendMessage", "hooks": [{"type": "command", "command": "/opt/ab/agentboard hook send-message"}]}]}}')
        self.assertEqual([x[0] for x in doctor.check_hooks(self.proj)], [doctor.INFO])
        self.settings(self.proj, "{not json")
        self.assertEqual(doctor.check_hooks(self.proj)[0][0], doctor.WARN)

    def test_no_settings_files_at_all_is_information(self):
        self.assertEqual([x[0] for x in doctor.check_hooks(self.proj)], [doctor.INFO])
        self.assertIn("no Claude Code settings", doctor.check_hooks(self.proj)[0][2])

    def test_config_switches_warn_unless_the_master_lock_is_on(self):
        (self.proj / ".agentboard" / "config.toml").write_text(
            '[chat]\ncasual = true\n[providers.mail]\ntype = "command"\nrun = "echo"\n[backup]\nsync_dir = "~/x"\n[extra]\na = 1\n')
        with mock.patch.dict(os.environ, {"AGENTBOARD_LOCKDOWN": ""}):
            r = doctor.check_config(self.proj / ".agentboard")
        self.assertEqual(r[0][0], doctor.WARN)
        for word in ("chat.casual", "providers.mail", "backup.sync_dir"):
            self.assertIn(word, r[0][2])
        self.assertIn("extra", r[1][2])
        with mock.patch.dict(os.environ, {"AGENTBOARD_LOCKDOWN": "1"}):
            self.assertEqual(doctor.check_config(self.proj / ".agentboard")[0][0], doctor.PASS)
        (self.proj / ".agentboard" / "config.toml").write_text("")
        with mock.patch.dict(os.environ, {"AGENTBOARD_LOCKDOWN": ""}):
            self.assertEqual(doctor.check_config(self.proj / ".agentboard")[0][0], doctor.PASS)

    def test_outbound_capable_modules_beyond_the_core_warn_by_name(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "providers.py").write_text("import urllib.request\n")
            (Path(d) / "server.py").write_text("from http.server import BaseHTTPRequestHandler\n")
            with mock.patch.object(doctor, "_HERE", Path(d)):
                self.assertEqual(doctor.check_code()[0][0], doctor.PASS)
                (Path(d) / "other.py").write_text("import socket\n")
                r = doctor.check_code()[0]
        self.assertEqual(r[0], doctor.WARN)
        self.assertIn("other", r[2].split("Beyond the core")[1])

    def test_a_version_that_disagrees_with_the_installed_package_warns(self):
        with mock.patch("importlib.metadata.version", return_value="9.9.9"):
            r = doctor.check_version(FakeRunner())
        self.assertEqual([x[0] for x in r], [doctor.INFO, doctor.WARN])


class WholeReport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.board = self.root / "proj" / ".agentboard"
        Store(self.board).add("A card", status="todo")
        for p in [self.board, *self.board.rglob("*")]:
            os.chmod(p, 0o700 if p.is_dir() else 0o600)

    def run_doctor(self, **kw):
        return doctor.run(self.board, env=kw.pop("env", {}), runner=kw.pop("runner", FakeRunner()), **kw)

    def snapshot(self):
        return sorted((str(p.relative_to(self.root)), p.stat().st_mtime_ns, p.stat().st_size) for p in self.root.rglob("*"))

    def test_it_changes_nothing_on_disk(self):
        before = self.snapshot()
        with mock.patch.object(Path, "home", return_value=self.root / "home"):
            self.run_doctor()
        self.assertEqual(self.snapshot(), before)

    def test_it_opens_no_socket_even_if_every_socket_call_fails(self):
        def refuse(*a, **k):
            raise AssertionError("doctor opened a socket or looked up a name")
        with mock.patch.multiple(socket, socket=refuse, create_connection=refuse, getaddrinfo=refuse, gethostbyname=refuse):
            with mock.patch.object(Path, "home", return_value=self.root / "home"):
                results = self.run_doctor()
        self.assertTrue(results)

    def test_the_module_imports_no_network_library(self):
        src = Path(doctor.__file__).read_text()
        self.assertIsNone(re.search(r"^\s*(?:import|from)\s+(?:socket|urllib|http|ssl|requests)\b", src, re.M))

    def test_it_only_runs_ps_lsof_and_git(self):
        runner = FakeRunner(PS_SERVER, listen=["127.0.0.1:8765"])
        with mock.patch.object(Path, "home", return_value=self.root / "home"):
            self.run_doctor(runner=runner)
        self.assertEqual({c[0] for c in runner.calls}, {"ps", "lsof", "git"})

    def test_render_is_short_and_ends_with_the_counts(self):
        with mock.patch.object(Path, "home", return_value=self.root / "home"):
            results = self.run_doctor()
        text = doctor.render(results, self.board)
        self.assertLessEqual(len(text.splitlines()), 20)
        self.assertRegex(text.splitlines()[-1], r"^\d+ FAIL, \d+ WARN, \d+ PASS, \d+ INFO$")

    def test_exit_code_fails_on_fail_and_with_strict_on_warn(self):
        self.assertEqual(doctor.exit_code([(doctor.PASS, "a", ""), (doctor.WARN, "b", "")]), 0)
        self.assertEqual(doctor.exit_code([(doctor.PASS, "a", ""), (doctor.WARN, "b", "")], strict=True), 1)
        self.assertEqual(doctor.exit_code([(doctor.FAIL, "a", "")]), 1)


class Cli(unittest.TestCase):
    def test_the_command_prints_the_report_and_exits_1_on_a_fail(self):
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d).resolve() / "proj"
            board = proj / ".agentboard"
            Store(board).add("A card", status="todo")
            import contextlib
            import io
            runner = FakeRunner()
            for mode in (0o755, 0o700):
                for p in [board, *board.rglob("*")]:
                    os.chmod(p, (0o755 if p.is_dir() else 0o644) if mode == 0o755 else (0o700 if p.is_dir() else 0o600))
                out = io.StringIO()
                with mock.patch.dict(os.environ, {"AGENTBOARD_DIR": str(board), "AGENTBOARD_LOCKDOWN": ""}), \
                        mock.patch("agentboard.doctor.subprocess.run", runner), mock.patch.object(Path, "home", return_value=Path(d) / "home"), \
                        contextlib.redirect_stdout(out):
                    try:
                        cli.main(["doctor"])
                        code = 0
                    except SystemExit as e:
                        code = e.code
                self.assertIn("agentboard doctor", out.getvalue())
                self.assertEqual(code, 1 if mode == 0o755 else 0, out.getvalue())


if __name__ == "__main__":
    unittest.main()
