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
PHONE = "(416) 867-" + "5311"          # a real-looking number built in pieces, so this file holds no phone number for the scan to find (867-5309/5310 are the song's: fiction to the guard)
PHONE2 = "416-867-" + "5312"


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
        self.assertNotIn("5311", line[2])

    def test_a_private_key_header_fails_and_a_key_like_assignment_only_warns(self):
        self.repo({"id.pem": "-----BEGIN " + "RSA PRIVATE KEY-----\nabc\n"})
        line = next(x for x in doctor.check_git(self.proj, self.board, subprocess.run) if x[1] == "tracked files")
        self.assertEqual(line[0], doctor.FAIL)
        self.assertIn("private-key at id.pem:1", line[2])
        self.git("rm", "-q", "-f", "id.pem")
        (self.proj / "cfg.py").write_text('api_key = "' + "k3y9" * 8 + '"\nTOKEN_ENV = "AGENTBOARD_SOME_TOKEN_NAME_X"\n')
        self.git("add", "-A")
        line = next(x for x in doctor.check_git(self.proj, self.board, subprocess.run) if x[1] == "tracked files")
        self.assertEqual(line[0], doctor.WARN)
        self.assertIn("assigned-secret at cfg.py:1", line[2])   # the kind names are publiccheck's: one source
        self.assertNotIn("cfg.py:2", line[2])   # an environment variable NAME is not a secret

    def test_plain_placeholders_are_not_reported_but_real_looking_values_still_are(self):
        fiction = ("call 416-555-0123 or +14165550199 or (212) 555-0100 or 555-123-4567; sid AC" + "b" * 32 + " key AKIA" + "X" * 16 + "\n"
                   + 'TOKEN = "secret-token-do-not-leak-please"\n')
        self.repo({"docs.md": fiction})
        line = next(x for x in doctor.check_git(self.proj, self.board, subprocess.run) if x[1] == "tracked files")
        self.assertEqual(line[0], doctor.PASS, line)
        self.repo({"real.md": f"call {PHONE} or {PHONE2} (a real-looking exchange)\n"})
        line = next(x for x in doctor.check_git(self.proj, self.board, subprocess.run) if x[1] == "tracked files")
        self.assertEqual(line[0], doctor.WARN)
        self.assertIn("real.md:1", line[2])

    def test_doctor_and_publiccheck_see_the_same_things(self):
        """One source (repoguard): what the guard allows the doctor allows, and what the guard flags the doctor flags. A real-looking key FAILS
        wherever it is (a test file is no shelter); a fixture the guard lets through (plain words after sk-, the song's number, a key of one
        repeated letter, a placeholder word) is a PASS. These were the seven standing FAILs of Nov 7."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        import publiccheck
        fixtures = ("sk-learn-pipeline-for-the-model-build-2026 is a card id\n", "sid AC" + "b" * 32 + " key AKIA" + "X" * 16 + "\n", "call (416) 867-" + "5309\n",
                    "Authorization: Bearer unauthorised-deletion planned\n", 'api_key = "your-key-here-xxxxxxxxxxxxxxxxxx"\n')
        self.repo({"test_fixture.py": "".join(fixtures), "notes.md": "".join(fixtures)})
        line = next(x for x in doctor.check_git(self.proj, self.board, subprocess.run) if x[1] == "tracked files")
        self.assertEqual(line[0], doctor.PASS, line)
        self.assertEqual(publiccheck.scan_text("".join(fixtures)), [])
        real = f'KEY = "{AWS}"\n'
        for where in ("test_real.py", "real.py"):   # a test file and a source file: the same verdict
            with self.subTest(where):
                self.repo({where: real})
                line = next(x for x in doctor.check_git(self.proj, self.board, subprocess.run) if x[1] == "tracked files")
                self.assertEqual(line[0], doctor.FAIL, line)
                self.assertIn(f"aws-key at {where}:1", line[2])
                self.assertEqual([k for _n, k, _s in publiccheck.scan_text(real)], ["aws-key"])

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

    def test_masking_off_in_config_is_a_fail_and_a_changed_default_a_warn(self):
        board = self.proj / ".agentboard"
        self.assertEqual(doctor.check_redact(board)[0][0], doctor.PASS)                      # no [redact] section at all
        (board / "config.toml").write_text("[redact]\nenabled = true\n")
        self.assertEqual(doctor.check_redact(board)[0][0], doctor.PASS)
        (board / "config.toml").write_text("[redact]\nenabled = false\n")
        r = doctor.check_redact(board)[0]
        self.assertEqual(r[0], doctor.FAIL)
        self.assertIn("OFF", r[2])
        self.assertIn("enabled = false", r[2])
        (board / "config.toml").write_text('[redact]\nphones = true\nextra = ["AKIA[0-9A-Z]{16}", "hunter2"]\n')
        r = doctor.check_redact(board)[0]
        self.assertEqual(r[0], doctor.WARN)
        self.assertIn("phone numbers", r[2])
        self.assertIn("2 pattern(s)", r[2])
        self.assertNotIn("hunter2", r[2])                                                     # a pattern is never printed
        self.assertNotIn("AKIA", r[2])

    def test_the_masking_line_is_part_of_a_run_and_redact_is_a_known_section(self):
        (self.proj / ".agentboard" / "config.toml").write_text("[redact]\nenabled = false\n")
        names = [r[1] for r in doctor.run(self.proj / ".agentboard", project=self.proj, runner=FakeRunner())]
        self.assertIn("masking", names)
        self.assertNotIn("redact", " ".join(r[2] for r in doctor.check_config(self.proj / ".agentboard") if "other sections" in r[2]))

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
        with mock.patch("importlib.metadata.entry_points", return_value=[]):   # what is installed on this machine must not change the report
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
        self.assertLessEqual(len(text.splitlines()), 24)   # the overnight branches each add a line (agents, watchdog, masking, profile)
        self.assertRegex(text.splitlines()[-1], r"^\d+ FAIL, \d+ WARN, \d+ PASS, \d+ INFO$")

    def test_exit_code_fails_on_fail_and_with_strict_on_warn(self):
        self.assertEqual(doctor.exit_code([(doctor.PASS, "a", ""), (doctor.WARN, "b", "")]), 0)
        self.assertEqual(doctor.exit_code([(doctor.PASS, "a", ""), (doctor.WARN, "b", "")], strict=True), 1)
        self.assertEqual(doctor.exit_code([(doctor.FAIL, "a", "")]), 1)


class FilesEdges(unittest.TestCase):
    """What the files line says for an empty folder, a listable one whose files are private, and a link."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.board = Path(self.tmp.name) / ".agentboard"
        self.board.mkdir()

    def line(self):
        return doctor.check_files(self.board)[0]

    def test_an_empty_folder_says_nothing_alarming_whatever_its_mode(self):
        for mode in (0o700, 0o750, 0o755):
            os.chmod(self.board, mode)
            level, _name, text = self.line()
            self.assertEqual(level, doctor.PASS, mode)
            self.assertIn("empty", text)
            self.assertNotIn("0 of 0", text)
            self.assertNotIn("can be read", text)

    def test_a_listable_folder_with_private_files_is_still_a_fail_but_says_what_is_true(self):
        (self.board / "tasks.json").write_text("{}")
        os.chmod(self.board / "tasks.json", 0o600)
        os.chmod(self.board, 0o755)
        level, _name, text = self.line()
        self.assertEqual(level, doctor.FAIL)
        self.assertIn("can be listed by any user", text)
        self.assertIn("not readable by others", text)
        self.assertNotIn("0 of 1", text)           # no "0 of N entries can be read": none can
        self.assertIn("chmod -R go-rwx", text)

    def test_a_group_listable_folder_with_private_files_warns_in_the_same_honest_words(self):
        (self.board / "tasks.json").write_text("{}")
        os.chmod(self.board / "tasks.json", 0o600)
        os.chmod(self.board, 0o750)
        level, _name, text = self.line()
        self.assertEqual(level, doctor.WARN)
        self.assertIn("listed by its group", text)

    def test_a_symlink_does_not_count_as_a_readable_file(self):
        (self.board / "tasks.json").write_text("{}")
        os.chmod(self.board / "tasks.json", 0o600)
        os.symlink(self.board / "tasks.json", self.board / "link.json")      # a link's own mode is 777 or 755 and means nothing
        os.chmod(self.board, 0o700)
        self.assertEqual(self.line()[0], doctor.PASS)
        self.assertIn("1 entries", self.line()[2])


class FakeDist:
    """A stand-in for the install record: what pip leaves in direct_url.json."""
    def __init__(self, folder=None, raw=None):
        self.raw = raw if raw is not None else (None if folder is None else '{"url": "file://%s"}' % folder)

    def read_text(self, name):
        assert name == "direct_url.json"
        return self.raw


class StaleInstall(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.repo = self.root / "repo"
        self.source = self.repo / "src" / "agentboard"
        self.installed = self.root / "site-packages" / "agentboard"
        for d in (self.source / "static", self.installed / "static"):
            d.mkdir(parents=True)
        for base in (self.source, self.installed):
            for f in ("__init__.py", "cli.py", "store.py", "static/index.html"):
                (base / f).write_text("x")

    def check(self, dist=None, here=None):
        return doctor.check_install(here or self.installed, FakeDist(self.repo) if dist is None else dist)[0]

    def test_a_copy_with_no_file_the_source_lacks_passes(self):
        level, name, text = self.check()
        self.assertEqual((level, name), (doctor.PASS, "install"))
        self.assertIn("no file its source", text)

    def test_removed_modules_that_linger_in_the_installed_copy_warn_by_name_with_the_fix(self):
        for f in ("texts.py", "sms.py"):
            (self.installed / f).write_text("old code")
        level, _name, text = self.check()
        self.assertEqual(level, doctor.WARN)
        self.assertIn("stale install: sms.py, texts.py are in the installed copy but not in the source", text)
        self.assertIn(f"fix: pipx uninstall agentboard; rm -rf {doctor._short(self.repo)}/build; pipx install {doctor._short(self.repo)}", text)   # build/ is where the stale files come from

    def test_one_file_reads_in_the_singular_and_a_long_list_is_cut(self):
        (self.installed / "texts.py").write_text("old")
        self.assertIn("texts.py is in the installed copy", self.check()[2])
        for i in range(8):
            (self.installed / f"old{i}.py").write_text("old")
        text = self.check()[2]
        self.assertIn("and 4 more", text)
        self.assertLessEqual(text.count(".py"), doctor.MAX_SHOWN + 1)

    def test_an_old_static_file_counts_too(self):
        (self.installed / "static" / "gone.js").write_text("old")
        self.assertIn("static/gone.js", self.check()[2])

    def test_caches_do_not_count(self):
        (self.installed / "__pycache__").mkdir()
        (self.installed / "__pycache__" / "cli.cpython-314.pyc").write_bytes(b"\0")
        (self.installed / "stray.pyc").write_bytes(b"\0")
        self.assertEqual(self.check()[0], doctor.PASS)

    def test_a_copy_that_is_older_than_the_source_is_not_this_checks_business(self):
        (self.source / "newmodule.py").write_text("new")      # the source has a file the installed copy does not
        self.assertEqual(self.check()[0], doctor.PASS)

    def test_running_from_the_source_itself_passes(self):
        level, _name, text = self.check(here=self.source)
        self.assertEqual(level, doctor.PASS)
        self.assertIn("running from the source", text)

    def test_without_an_install_record_it_is_information_not_a_warning(self):
        for dist in (FakeDist(raw=None), FakeDist(raw=""), FakeDist(raw="not json"), FakeDist(raw='{"url": "https://example.invalid/x.git"}'), None):
            level, _name, text = doctor.check_install(self.installed, dist)[0]
            self.assertEqual(level, doctor.INFO, dist)
            self.assertIn("cannot be compared", text)

    def test_a_source_that_is_gone_is_information(self):
        level, _name, text = doctor.check_install(self.installed, FakeDist(self.root / "moved"))[0]
        self.assertEqual(level, doctor.INFO)
        self.assertIn("nothing to compare with", text)

    def test_the_new_warning_does_not_change_the_exit_rules(self):
        (self.installed / "texts.py").write_text("old")
        results = doctor.check_install(self.installed, FakeDist(self.repo))
        self.assertEqual(doctor.exit_code(results), 0)
        self.assertEqual(doctor.exit_code(results, strict=True), 1)

    def test_it_reads_two_folders_and_changes_nothing(self):
        (self.installed / "texts.py").write_text("old")
        before = sorted((str(p), p.stat().st_mtime_ns) for p in self.root.rglob("*"))
        self.check()
        self.assertEqual(sorted((str(p), p.stat().st_mtime_ns) for p in self.root.rglob("*")), before)

    def test_the_whole_report_includes_the_line(self):
        board = self.root / "proj" / ".agentboard"
        Store(board).add("A card", status="todo")
        with mock.patch.object(doctor, "_installed_record", return_value=FakeDist(self.repo)), mock.patch.object(doctor, "_HERE", self.installed), \
                mock.patch.object(Path, "home", return_value=self.root / "home"):
            (self.installed / "sms.py").write_text("old")
            results = doctor.run(board, env={}, runner=FakeRunner())
        self.assertEqual(level_of(results, "install"), [doctor.WARN])


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
