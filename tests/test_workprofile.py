"""The work profile and its proof (card overnight-sec-workpc-profile): the run-time guards, the one switch, `agentboard selfcheck`, and the two server
bugs the selfcheck's red-team found (a JSON bomb dropped the connection; a symlink in the reports folder served a file from outside it).

The selfcheck is tested the way a test of a test must be: it passes on this tree, AND it fails when something is planted (a network import, a
program start, a server that no longer checks the Host, a route that reaches out), so a green selfcheck means something."""
import contextlib
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli, doctor, guards, lockdown, plugins, profile, reports, selfcheck, server, serverstate
from agentboard.store import Store

SRC = Path(selfcheck.HERE)


def levels(results, prefix):
    return {n: l for l, n, _t in results if n.startswith(prefix)}


def failing(results):
    return [(n, t) for l, n, t in results if l == selfcheck.FAIL]


class TheGuards(unittest.TestCase):
    def test_what_counts_as_this_machine(self):
        for host in ("127.0.0.1", "127.8.9.10", "::1", "[::1]", "localhost", "LOCALHOST", "localhost.", "::ffff:127.0.0.1", b"127.0.0.1"):
            self.assertTrue(guards.is_loopback(host), host)
        for host in ("0.0.0.0", "", None, "example.com", "8.8.8.8", "192.168.1.5", "10.0.0.1", "::", "169.254.169.254", "localhost.evil.example", "127.0.0.1.evil.example",
                     "::ffff:8.8.8.8", "128.0.0.1", 5):
            self.assertFalse(guards.is_loopback(host), host)

    def test_the_network_guard_refuses_everything_that_leaves_and_restores_after(self):
        before = (socket.socket.connect, socket.create_connection, socket.getaddrinfo, socket.socket.bind)
        with guards.network_guard() as g:
            for fn in (lambda: socket.create_connection(("93.184.216.34", 80), timeout=1), lambda: socket.create_connection(("example.com", 80), timeout=1),
                       lambda: socket.getaddrinfo("example.com", 80), lambda: socket.gethostbyname("example.com"), lambda: socket.gethostbyaddr("8.8.8.8"),
                       lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b"x", ("8.8.8.8", 53)),
                       lambda: socket.socket().connect(("192.0.2.1", 80)), lambda: socket.socket().connect_ex(("192.0.2.1", 80)),
                       lambda: socket.socket().bind(("0.0.0.0", 0)), lambda: socket.socket().bind(("", 0)), lambda: socket.getnameinfo(("8.8.8.8", 53), 0)):
                with self.assertRaises(guards.Refused):
                    fn()
            self.assertGreaterEqual(len(g.refused()), 11)
            self.assertTrue(all(not allowed for _k, _t, allowed in g.refused()))
        self.assertEqual(before, (socket.socket.connect, socket.create_connection, socket.getaddrinfo, socket.socket.bind))

    def test_the_network_guard_lets_this_machine_talk_to_itself(self):
        with guards.network_guard() as g:
            srv = socket.socket()
            srv.bind(("127.0.0.1", 0))
            srv.listen(1)
            c = socket.create_connection(("127.0.0.1", srv.getsockname()[1]), timeout=2)
            conn, _ = srv.accept()
            c.sendall(b"hi")
            self.assertEqual(conn.recv(2), b"hi")
            self.assertTrue(socket.getaddrinfo("localhost", 80))
            for s in (c, conn, srv):
                s.close()
            self.assertEqual(g.refused(), [])
            self.assertTrue(any(k == "connect" or k == "create_connection" for k, _t, ok in g.events if ok))

    def test_a_unix_socket_is_this_machine_too(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        path = os.path.join(d, "s")
        with guards.network_guard() as g:
            srv = socket.socket(socket.AF_UNIX)
            srv.bind(path)
            srv.listen(1)
            c = socket.socket(socket.AF_UNIX)
            c.connect(path)
            for s in (c, srv):
                s.close()
            self.assertEqual(g.refused(), [])

    def test_the_process_guard_refuses_every_way_to_start_a_program_and_restores_after(self):
        real = (subprocess.Popen.__init__, os.system, os.fork)
        with guards.process_guard() as g:
            for fn in (lambda: subprocess.run(["true"]), lambda: subprocess.Popen("true", shell=True), lambda: subprocess.check_output(["echo", "x"]), lambda: os.system("true"),
                       lambda: os.popen("true"), lambda: os.execv("/bin/true", ["true"]), lambda: os.spawnv(os.P_WAIT, "/bin/true", ["true"]), lambda: os.fork(),
                       lambda: os.posix_spawn("/bin/true", ["true"], os.environ)):
                with self.assertRaises(guards.Refused):
                    fn()
            self.assertGreaterEqual(len(g.refused()), 9)
        self.assertEqual(real, (subprocess.Popen.__init__, os.system, os.fork))
        self.assertEqual(subprocess.run(["true"]).returncode, 0)   # and programs start again afterwards


class TheSwitch(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        env.update({"XDG_CONFIG_HOME": str(self.tmp / "cfg"), "HOME": str(self.tmp)})
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(profile.reset)
        self.board = self.tmp / ".agentboard"
        self.board.mkdir()

    def test_off_by_default_and_the_off_words(self):
        self.assertIsNone(profile.reason(self.board))
        for word in ("", "0", "false", "no", "off", "home", " OFF "):
            with mock.patch.dict(os.environ, {profile.ENV: word}):
                self.assertIsNone(profile.reason(self.board), word)

    def test_anything_else_is_work_a_typo_is_a_lock_never_a_hole(self):
        for word in ("work", "WORK", " work ", "1", "true", "strict", "wrok"):
            with mock.patch.dict(os.environ, {profile.ENV: word}):
                self.assertIsNotNone(profile.reason(self.board), word)

    def test_the_machine_file_and_the_board_config_each_switch_it_on(self):
        profile.set_machine(True)
        self.assertTrue(profile.machine_file().is_file())
        self.assertEqual(profile.machine_file().stat().st_mode & 0o777, 0o600)
        self.assertIn("machine", profile.reason(self.board))
        profile.set_machine(False)
        self.assertIsNone(profile.reason(self.board))
        (self.board / "config.toml").write_text('[board]\nprofile = "work"\n')
        self.assertIn("board", profile.reason(self.board))
        (self.board / "config.toml").write_text('[board]\nprofile = "off"\n')
        self.assertIsNone(profile.reason(self.board))

    def test_no_source_can_switch_another_off(self):
        profile.set_machine(True)
        with mock.patch.dict(os.environ, {profile.ENV: "off"}):
            self.assertIsNotNone(profile.reason(self.board))   # the machine file still says work
        (self.board / "config.toml").write_text('[board]\nprofile = "off"\n')
        self.assertIsNotNone(profile.reason(self.board))
        self.assertEqual(len(profile.sources(self.board)), 1)

    def test_a_config_that_cannot_be_read_neither_crashes_nor_switches_it_off(self):
        (self.board / "config.toml").write_text("[board\nthis is not toml")
        self.assertIsNone(profile.reason(self.board))
        with mock.patch.dict(os.environ, {profile.ENV: "work"}):
            self.assertIsNotNone(profile.reason(self.board))

    def test_apply_sets_the_locks_for_this_process_and_what_it_starts(self):
        with mock.patch.dict(os.environ, {profile.ENV: "work"}):
            self.assertIsNotNone(profile.apply(self.board))
            self.assertTrue(lockdown.locked())
            self.assertIsNotNone(plugins.disabled_reason())
            self.assertEqual(os.environ["AGENTBOARD_NO_PLUGINS"], "1")
            with self.assertRaises(guards.Refused):
                socket.create_connection(("example.com", 80), timeout=1)
            profile.apply(self.board)   # idempotent: one guard, not two
            self.assertEqual(len(profile._NET), 1)

    def test_the_server_adds_the_process_guard_and_nothing_else_does(self):
        with mock.patch.dict(os.environ, {profile.ENV: "work"}):
            profile.apply(self.board)
            self.assertEqual(subprocess.run(["true"]).returncode, 0)   # a command (doctor, a hook) may still start git
            profile.apply_server()
            with self.assertRaises(guards.Refused):
                subprocess.run(["true"])

    def test_the_command_line_switches_it_on_for_the_machine_and_says_what_it_does(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.dict(os.environ, {"AGENTBOARD_DIR": str(self.board)}):
            cli.main(["profile", "work"])
        self.assertIn("work profile ON", out.getvalue())
        self.assertIn("master lock", out.getvalue())
        self.assertTrue(profile.machine_file().exists())
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.dict(os.environ, {"AGENTBOARD_DIR": str(self.board)}):
            cli.main(["profile", "off"])
        self.assertFalse(profile.machine_file().exists())

    def test_init_can_write_the_profile_into_a_new_board(self):
        old = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, old)
        shutil.rmtree(self.board)
        with contextlib.redirect_stdout(io.StringIO()):
            cli.main(["init", "--profile", "work"])
        self.assertIn('profile = "work"', (self.board / "config.toml").read_text())
        self.assertIn("board", profile.reason(self.board))


class TheMachineSaysSo(unittest.TestCase):
    """doctor and the server's state file say whether the profile is on, so a reviewer's pasted doctor output shows it too."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        env.update({"XDG_CONFIG_HOME": str(self.tmp / "cfg"), "HOME": str(self.tmp)})
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def test_doctor_has_a_profile_line_info_when_off_and_pass_when_on(self):
        line = [r for r in doctor.check_locks({}) if r[1] == "profile"]
        self.assertEqual([r[0] for r in line], [doctor.INFO])
        with mock.patch.dict(os.environ, {profile.ENV: "work"}):
            line = [r for r in doctor.check_locks({}) if r[1] == "profile"]
        self.assertEqual([r[0] for r in line], [doctor.PASS])
        self.assertIn("selfcheck", line[0][2])

    def test_the_off_line_adds_no_warning(self):
        self.assertEqual([r for r in doctor.check_locks({lockdown.ENV: "1"}) if r[0] in (doctor.WARN, doctor.FAIL)], [])

    def test_the_servers_state_file_records_the_profile(self):
        self.assertFalse(serverstate.record(8765, [])["profile"])
        with mock.patch.dict(os.environ, {profile.ENV: "work"}):
            rec = serverstate.record(8765, [])
        self.assertTrue(rec["profile"])
        board = self.tmp / ".agentboard"
        board.mkdir()
        with mock.patch.dict(os.environ, {profile.ENV: "work"}):
            serverstate.write(board, 8765, [])
        self.assertTrue(serverstate.read(board, os.getpid())["profile"])
        self.assertNotIn(str(self.tmp), json.dumps(serverstate.read(board, os.getpid())))


class TheTwoBugsTheRedTeamFound(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.board = self.tmp / ".agentboard"
        self.board.mkdir()
        self.store = Store(self.board)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.srv = server.new_server(self.store, self.port)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def ask(self, data):
        return selfcheck.raw(self.port, data)

    def test_a_json_bomb_gets_a_400_not_a_dropped_connection(self):
        body = b"[" * 400_000 + b"]" * 400_000
        r = self.ask(f"POST /api/tasks HTTP/1.1\r\nHost: localhost:{self.port}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body)
        self.assertEqual(r.status, 400)
        self.assertIn("nested too deeply", r.text())
        self.assertEqual(self.ask(f"GET /api/tasks HTTP/1.1\r\nHost: localhost:{self.port}\r\n\r\n".encode()).status, 200)

    def test_any_other_surprise_in_a_post_is_a_500_with_a_class_name_only(self):
        with mock.patch.object(Store, "add", side_effect=RuntimeError("secret detail that must not be shown")):
            body = b'{"title": "x"}'
            r = self.ask(f"POST /api/tasks HTTP/1.1\r\nHost: localhost:{self.port}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body)
        self.assertEqual(r.status, 500)
        self.assertIn("RuntimeError", r.text())
        self.assertNotIn("secret detail", r.text())

    def test_a_symlink_in_the_reports_folder_is_not_a_report(self):
        outside = self.tmp / "outside.txt"
        outside.write_text("NOT A REPORT")
        folder = reports.reports_dir(self.board)
        folder.mkdir(parents=True, exist_ok=True)
        link = folder / "escape-20261107-000000.html"
        link.symlink_to(outside)
        real = folder / "real-20261107-000000.html"
        real.write_text("<p>a report</p>")
        self.assertEqual(self.ask(f"GET /reports/{link.name} HTTP/1.1\r\nHost: localhost:{self.port}\r\n\r\n".encode()).status, 404)
        r = self.ask(f"GET /reports/{real.name} HTTP/1.1\r\nHost: localhost:{self.port}\r\n\r\n".encode())
        self.assertEqual((r.status, "a report" in r.text()), (200, True))

    def test_the_work_profile_starts_no_git_for_a_finished_card(self):
        t = self.store.add("done soon", "", "todo")
        self.store.move(t["id"], "done")
        with mock.patch.dict(os.environ, {profile.ENV: "work"}), guards.process_guard() as g:
            reports.maybe_report(self.store, t["id"]) if hasattr(reports, "maybe_report") else None
            server._GIT_CACHE.clear()
            self.assertEqual(server._git_summary(self.store, self.store.load()[0]), {})
            self.assertEqual(reports._git(["status"], self.tmp), None)
            self.assertEqual(g.events, [])


class TheSelfcheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.static = selfcheck.static_checks()

    def test_it_passes_on_this_tree_statically(self):
        self.assertEqual(failing(self.static), [])
        self.assertGreaterEqual(len(self.static), 8)
        names = " ".join(n for _l, n, _t in self.static)
        for want in ("network-capable imports", "program-starting code", "shell=True", "eval, exec, pickle", "third-party packages", "declared dependencies", "addresses in the code",
                     "the page loads nothing from outside"):
            self.assertIn(want, names)

    def test_it_passes_at_run_time_on_this_tree(self):
        results = selfcheck.runtime_checks()
        self.assertEqual(failing(results), [])
        self.assertGreaterEqual(len(results), 40, "the audit shrank: a check was dropped")
        text = " ".join(n for _l, n, _t in results)
        for want in ("wrong Host refused", "cross-site POST refused", "path traversal", "no request smuggling", "a JSON bomb", "a flood of connections is capped", "nosniff on every kind", "an http provider (SSRF)", "a command provider",
                     "nothing tried to leave this machine", "no program was started", "listening only on loopback", "every route answers", "private modes"):
            self.assertIn(want, text)

    def test_it_sets_nothing_behind_it(self):
        keep = dict(os.environ)
        before = (socket.socket.connect, subprocess.Popen.__init__)
        selfcheck.runtime_checks()
        self.assertEqual(dict(os.environ), keep)
        self.assertEqual(before, (socket.socket.connect, subprocess.Popen.__init__))

    def test_the_command_prints_a_list_and_json(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["selfcheck", "--json"])
        data = json.loads(out.getvalue())
        self.assertTrue(all({"level", "check", "detail"} <= set(d) for d in data))
        self.assertFalse([d for d in data if d["level"] == "FAIL"])
        self.assertEqual(selfcheck.exit_code([("PASS", "a", "b")]), 0)
        self.assertEqual(selfcheck.exit_code([("PASS", "a", "b"), ("FAIL", "c", "d")]), 1)
        self.assertEqual(selfcheck.exit_code([("WARN", "a", "b")]), 0)

    def test_nothing_in_the_selfcheck_text_quotes_a_secret_or_a_board(self):
        for _l, n, t in self.static + selfcheck.runtime_checks():
            self.assertNotIn(str(Path.home()), t)


class TheSelfcheckCatchesWhatItIsFor(unittest.TestCase):
    """A planted violation must turn the right line red. Without these, a green selfcheck proves nothing."""

    def planted(self, **files):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        shutil.copytree(SRC, d / "agentboard", ignore=shutil.ignore_patterns("__pycache__"))
        for name, text in files.items():
            (d / "agentboard" / name).write_text(text)
        return d / "agentboard"

    def test_a_network_import_in_a_new_file(self):
        for src in ("import socket\n", "import urllib.request\n", "from http import client\nimport http.client\n", "import requests\n", "import ssl\n"):
            root = self.planted(**{"leak.py": src})
            res = levels(selfcheck.static_checks(root), "static: network-capable imports")
            self.assertEqual(list(res.values()), [selfcheck.FAIL], src)

    def test_a_program_start_in_a_new_file(self):
        for src in ("import subprocess\n", "import os\nos.system('x')\n", "from os import popen\nimport os\nos.popen('x')\n", "import pty\n", "import ctypes\n"):
            root = self.planted(**{"leak.py": src})
            res = levels(selfcheck.static_checks(root), "static: program-starting code")
            self.assertEqual(list(res.values()), [selfcheck.FAIL], src)

    def test_shell_true_eval_pickle_and_a_third_party_package(self):
        self.assertEqual(list(levels(selfcheck.static_checks(self.planted(**{"leak.py": "import subprocess\nsubprocess.run('x', shell=True)\n"})), "static: shell=True").values()), [selfcheck.FAIL])
        self.assertEqual(list(levels(selfcheck.static_checks(self.planted(**{"leak.py": "x = eval('1')\n"})), "static: eval, exec, pickle").values()), [selfcheck.FAIL])
        self.assertEqual(list(levels(selfcheck.static_checks(self.planted(**{"leak.py": "import pickle\n"})), "static: eval, exec, pickle").values()), [selfcheck.FAIL])
        self.assertEqual(list(levels(selfcheck.static_checks(self.planted(**{"leak.py": "import yaml\n"})), "static: third-party").values()), [selfcheck.FAIL])

    def test_an_address_in_the_code_and_a_page_that_loads_from_outside(self):
        root = self.planted(**{"leak.py": "URL = 'https://telemetry.vendor.invalid/collect'\n"})
        self.assertEqual(list(levels(selfcheck.static_checks(root), "static: addresses").values()), [selfcheck.FAIL])
        root = self.planted()
        page = root / "static" / "index.html"
        page.write_text(page.read_text().replace("</head>", '<script src="https://cdn.vendor.invalid/x.js"></script></head>', 1))
        self.assertEqual(list(levels(selfcheck.static_checks(root), "static: the page loads").values()), [selfcheck.FAIL])
        for tag in ('<link rel="stylesheet" href="//fonts.vendor.invalid/a.css">', '<img src="http://x.vendor.invalid/p.gif">', "<style>@import url(https://x.vendor.invalid/a.css);</style>"):
            root = self.planted()
            page = root / "static" / "index.html"
            page.write_text(page.read_text().replace("</head>", tag + "</head>", 1))
            self.assertEqual(list(levels(selfcheck.static_checks(root), "static: the page loads").values()), [selfcheck.FAIL], tag)

    def test_a_dropped_content_security_policy(self):
        root = self.planted()
        sv = root / "server.py"
        sv.write_text(sv.read_text().replace("default-src 'none'; script-src", "default-src *; script-src", 1))
        self.assertEqual(list(levels(selfcheck.static_checks(root), "static: the page loads").values()), [selfcheck.FAIL])

    def with_handler(self, tweak):
        real = server.make_handler

        def make(store, port):
            h = real(store, port)
            tweak(h)
            return h
        return mock.patch.object(server, "make_handler", make)

    def test_a_server_that_stops_checking_the_host(self):
        def tweak(h):
            h._host_ok = lambda self: True
        with self.with_handler(tweak):
            res = selfcheck.runtime_checks()
        self.assertIn("http: wrong Host refused (DNS rebinding)", [n for n, _t in failing(res)])

    def test_a_server_that_stops_checking_the_origin_or_the_content_type(self):
        def tweak(h):
            h._guard = lambda self, post=False: self._host_ok() or (self._send(403, {"error": "bad host"}) and False)
        with self.with_handler(tweak):
            names = [n for n, _t in failing(selfcheck.runtime_checks())]
        self.assertIn("http: cross-site POST refused (CSRF)", names)
        self.assertIn("http: only exact application/json is accepted", names)

    def test_a_route_that_reaches_out_or_starts_a_program(self):
        real_get = server.make_handler

        def make(store, port):
            h = real_get(store, port)
            orig = h._route_get

            def route(self, url, q):
                if url.path == "/api/hud":
                    try:
                        socket.create_connection(("93.184.216.34", 80), timeout=1)
                    except OSError:
                        pass
                    try:
                        subprocess.run(["true"])
                    except OSError:
                        pass
                return orig(self, url, q)
            h._route_get = route
            return h
        with mock.patch.object(server, "make_handler", make):
            names = [n for n, _t in failing(selfcheck.runtime_checks())]
        self.assertIn("runtime: nothing tried to leave this machine", names)
        self.assertIn("runtime: no program was started", names)

    def test_a_listener_on_all_interfaces(self):
        real_server = server.BoundedHTTPServer

        class Wide(real_server):
            def __init__(self, addr, handler):
                super().__init__(("127.0.0.1", addr[1]), handler)
                self.server_address = ("0.0.0.0", addr[1])   # what a bind to all interfaces would report
        with mock.patch.object(server, "BoundedHTTPServer", Wide):
            names = [n for n, _t in failing(selfcheck.runtime_checks())]
        self.assertIn("runtime: listening only on loopback", names)

    def test_a_lock_that_does_not_lock(self):
        with mock.patch.object(lockdown, "locked", lambda feature=None: False):
            names = [n for n, _t in failing(selfcheck.runtime_checks())]
        self.assertIn("profile: master lock", names)


if __name__ == "__main__":
    unittest.main()
