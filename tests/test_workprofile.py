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


_CLEAN = []


def clean_runtime():
    """The audit of the unmodified tree, run once for the whole module (about ten seconds)."""
    if not _CLEAN:
        _CLEAN.append(selfcheck.runtime_checks())
    return _CLEAN[0]


class TheGuards(unittest.TestCase):
    def test_what_counts_as_this_machine(self):
        for host in ("127.0.0.1", "127.8.9.10", "::1", "[::1]", "localhost", "LOCALHOST", "localhost.", "::ffff:127.0.0.1", b"127.0.0.1"):
            self.assertTrue(guards.is_loopback(host), host)
        for host in ("0.0.0.0", "", None, "canary.invalid", "198.51.100.8", "203.0.113.5", "192.0.2.1", "::", "192.0.2.254", "localhost.evil.invalid", "127.0.0.1.evil.invalid",
                     "::ffff:198.51.100.8", "128.0.0.1", 5):
            self.assertFalse(guards.is_loopback(host), host)

    def test_the_network_guard_refuses_everything_that_leaves_and_restores_after(self):
        before = (socket.socket.connect, socket.create_connection, socket.getaddrinfo, socket.socket.bind)
        with guards.network_guard() as g:
            for fn in (lambda: socket.create_connection(("192.0.2.10", 80), timeout=1), lambda: socket.create_connection(("canary.invalid", 80), timeout=1),
                       lambda: socket.getaddrinfo("canary.invalid", 80), lambda: socket.gethostbyname("canary.invalid"), lambda: socket.gethostbyaddr("198.51.100.7"),
                       lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b"x", ("198.51.100.7", 53)),
                       lambda: socket.socket().connect(("192.0.2.1", 80)), lambda: socket.socket().connect_ex(("192.0.2.1", 80)),
                       lambda: socket.socket().bind(("0.0.0.0", 0)), lambda: socket.socket().bind(("", 0)), lambda: socket.getnameinfo(("198.51.100.7", 53), 0)):
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


class NothingInTheseFilesDialsARealHost(unittest.TestCase):
    """If a guard ever stopped working, the canaries must not reach a real host or resolver (xr-workpc-selfcheck-live-canaries): every address written in
    selfcheck.py and in this file is this machine, a documentation range (RFC 5737) or, for a bind that opens nothing, 0.0.0.0."""

    ALLOWED = ("127.", "192.0.2.", "198.51.100.", "203.0.113.")

    def test_every_address_is_this_machine_or_a_documentation_range(self):
        import re
        for path in (Path(selfcheck.__file__), Path(__file__)):
            bad = []
            for n, line in enumerate(path.read_text().splitlines(), 1):
                for m in re.finditer(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])", line):
                    ip = m.group(0)
                    if not ip.startswith(self.ALLOWED) and ip not in ("0.0.0.0", "128.0.0.1"):   # (a bind that opens nothing, and a not-loopback neighbour of 127.x in the table above)
                        bad.append(f"{path.name}:{n} {ip}")
            self.assertEqual(bad, [], "an address that is not this machine or a documentation range")
        self.assertNotIn("0.0.0.0", Path(selfcheck.__file__).read_text(), "the selfcheck itself binds nothing on all interfaces, even as a canary")

    def test_the_selfcheck_looks_up_no_real_name(self):
        text = Path(selfcheck.__file__).read_text()
        for name in ("google", "cloudflare", ".".join(["8"] * 4), ".".join(["1"] * 4), "93.184." + "216.34", "169.254." + "169.254"):   # (assembled: this file holds none of them)
            self.assertNotIn(name, text, name)


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
                socket.create_connection(("canary.invalid", 80), timeout=1)
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
        results = clean_runtime()
        self.assertEqual(failing(results), [])
        self.assertGreaterEqual(len(results), 40, "the audit shrank: a check was dropped")
        text = " ".join(n for _l, n, _t in results)
        for want in ("wrong Host refused", "cross-site POST refused", "path traversal", "no request smuggling", "a JSON bomb", "a flood of connections is capped", "nosniff on every kind", "real payloads through the handlers", "an http provider (SSRF)", "a command provider",
                     "nothing tried to leave this machine", "no program was started", "listening only on loopback", "every named route answers", "private modes"):
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
        for _l, n, t in self.static + clean_runtime():
            self.assertNotIn(str(Path.home()), t)


class TheLiveAudit(unittest.TestCase):
    """selfcheck --live: read-only probes of a server that is already running. A throwaway server stands in for it."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.board = self.tmp / ".agentboard"
        self.board.mkdir()
        self.store = Store(self.board)
        self.store.add("PRIVATE-CARD-TITLE")
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.asked = []
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        env.update({"HOME": str(self.tmp), "XDG_CONFIG_HOME": str(self.tmp / "cfg"), "AGENTBOARD_LOCKDOWN": "1", "AGENTBOARD_NO_PLUGINS": "1"})
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def start(self, tweak=None):
        h = server.make_handler(self.store, self.port)
        asked = self.asked
        orig_get, orig_post = h._route_get, h.do_POST

        def route(this, url, q):
            asked.append(("GET", url.path + ("?" + url.query if url.query else "")))
            return orig_get(this, url, q)

        def post(this):
            asked.append(("POST", this.path, this.headers.get("Content-Length")))
            return orig_post(this)
        h._route_get, h.do_POST = route, post
        if tweak:
            tweak(h)
        srv = server.BoundedHTTPServer(("127.0.0.1", self.port), h)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        serverstate.write(self.board, self.port, [])
        self.addCleanup(serverstate.remove, self.board)

    def live(self):
        return selfcheck.live_checks(self.port, self.board, runner=lambda *a, **k: subprocess.CompletedProcess(a, 1, "", ""))

    def test_a_good_server_passes_every_probe(self):
        self.start()
        res = self.live()
        self.assertEqual(failing(res), [])
        self.assertGreaterEqual(len([r for r in res if r[0] == selfcheck.PASS]), 11)

    def test_it_never_asks_for_a_card_a_chat_line_a_report_or_a_transcript_and_never_sends_a_body(self):
        self.start()
        self.live()
        gets = [a[1] for a in self.asked if a[0] == "GET"]
        for path in gets:
            self.assertFalse(path.startswith(("/api/tasks", "/api/task", "/api/chat", "/api/transcript", "/api/hud", "/summary", "/reports/real", "/api/boards", "/api/state")), path)
        self.assertTrue(set(["/voice.js", "/", "/nosuch"]) <= set(gets))
        posts = [a for a in self.asked if a[0] == "POST"]
        self.assertTrue(posts)
        self.assertTrue(all(a[2] == "0" for a in posts), "a probe POST carried a body")
        self.assertEqual([t["title"] for t in self.store.load()], ["PRIVATE-CARD-TITLE"])   # and nothing was written

    def test_a_running_server_that_stopped_checking_the_host_fails(self):
        self.start(lambda h: setattr(h, "_host_ok", lambda this: True))
        self.assertIn("live: wrong Host refused (DNS rebinding)", [n for n, _t in failing(self.live())])

    def test_a_running_server_that_accepts_a_cross_site_post_fails(self):
        self.start(lambda h: setattr(h, "_guard", lambda this, post=False: True))
        names = [n for n, _t in failing(self.live())]
        self.assertIn("live: cross-site and wrong-type POSTs refused (CSRF)", names)

    def test_an_older_server_without_nosniff_says_restart_it(self):
        real = server.make_handler

        def old(store, port):
            h = real(store, port)
            send = h._send

            def no_nosniff(this, code, body, ctype="application/json", extra=None):
                raw = body if isinstance(body, bytes) else json.dumps(body).encode()
                this.send_response(code)
                this.send_header("Content-Type", ctype)
                for k, v in (extra or {}).items():
                    this.send_header(k, v)
                this.send_header("Content-Length", str(len(raw)))
                this.end_headers()
                this.wfile.write(raw)
            h._send = no_nosniff
            return h
        with mock.patch.object(server, "make_handler", old):
            self.start()
        self.assertIn("live: nosniff on scripts and errors", [n for n, _t in failing(self.live())])

    def test_nothing_listening_is_one_clear_fail(self):
        res = selfcheck.live_checks(self.port, self.board)
        self.assertEqual([(l, n) for l, n, _t in res], [(selfcheck.FAIL, "live: the server answers")])

    def test_a_server_not_under_the_profile_is_a_warning_unless_this_shell_is(self):
        self.start()
        res = {n: l for l, n, _t in self.live()}
        self.assertEqual(res["live: the work profile"], selfcheck.WARN)
        with mock.patch.dict(os.environ, {profile.ENV: "work"}):
            res = {n: l for l, n, _t in self.live()}
        self.assertEqual(res["live: the work profile"], selfcheck.FAIL)

    def test_the_command_takes_a_port_and_skips_the_throwaway_audit(self):
        self.start()
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.dict(os.environ, {"AGENTBOARD_DIR": str(self.board)}):
            try:
                cli.main(["selfcheck", "--live", str(self.port), "--json"])
            except SystemExit:
                pass
        names = [d["check"] for d in json.loads(out.getvalue())]
        self.assertTrue(any(n.startswith("live:") for n in names))
        self.assertFalse(any(n.startswith("runtime:") for n in names))


class TheRoutesAreReadFromTheHandlers(unittest.TestCase):
    """xr-workpc-selfcheck-overclaims: the sweep's counts must be the routes the handlers name, GET and POST apart."""

    SRC = """
class Handler:
    def _route_get(self, url, q):
        if url.path in ("/", "/hud"):
            pass
        elif url.path == "/api/tasks":
            pass
        elif url.path.startswith("/reports/"):
            pass
        elif path == "/api/decoy-in-get":
            pass
    def do_POST(self):
        path = self.p
        if path == "/api/tasks":
            pass
        elif path == "/api/move":
            pass
        elif path.startswith("/api/x/"):
            pass
        elif url.path == "/decoy-in-post":
            pass
"""

    def test_get_and_post_are_told_apart_and_a_path_in_the_wrong_verb_is_not_counted(self):
        get, post, pre_get, pre_post = selfcheck.routes_from_source(self.SRC)
        self.assertEqual(get, ["/", "/api/tasks", "/hud"])   # (a comparison on a bare `path` inside _route_get, and on `url.path` inside do_POST, are not routes of that verb)
        self.assertEqual(post, ["/api/move", "/api/tasks"])
        self.assertEqual((pre_get, pre_post), (["/reports/"], ["/api/x/"]))

    def test_on_the_real_server_every_post_route_is_under_api_and_the_get_pages_are_not(self):
        get, post, _pg, _pp = selfcheck.routes_from_source((Path(selfcheck.HERE) / "server.py").read_text())
        self.assertTrue(all(p.startswith("/api/") for p in post), post)
        self.assertIn("/api/chat-nudge", post)
        self.assertNotIn("/api/hud", post)
        self.assertIn("/api/hud", get)
        self.assertGreaterEqual((len(get), len(post)), (15, 15))


class TheStaticScanSeesWhatIsWrittenOut(unittest.TestCase):
    def scan(self, src):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        f = d / "x.py"
        f.write_text(src)
        return selfcheck.scan_file(f)

    def test_aliases_and_from_imports_of_os(self):
        for src in ("import os as o\no.system('x')\n", "from os import system\nsystem('x')\n", "from os import popen as p\np('x')\n", "import os\ngetattr(os, 'system')('x')\n",
                    "import os\nos.execv('/bin/sh', ['sh'])\n"):
            calls = self.scan(src)["calls"]
            self.assertTrue(any(c in selfcheck.PROCESS_CALLS for c in calls), (src, calls))

    def test_the_planted_aliases_turn_the_static_check_red(self):
        for src in ("import os as o\no.system('x')\n", "from os import system\n", "import os\ngetattr(os, 'popen')('x')\n"):
            root = Path(tempfile.mkdtemp())
            self.addCleanup(shutil.rmtree, root, True)
            shutil.copytree(SRC, root / "agentboard", ignore=shutil.ignore_patterns("__pycache__"))
            (root / "agentboard" / "leak.py").write_text(src)
            res = levels(selfcheck.static_checks(root / "agentboard"), "static: program-starting code")
            self.assertEqual(list(res.values()), [selfcheck.FAIL], src)

    def test_bare_addresses_and_host_names_are_found_and_reserved_ones_are_not(self):
        hits = lambda src: [h for h, _l in self.scan(src)["urls"]]
        outside = ".".join(["10", "1", "2", "3"]), "ping " + ".".join(["203", "0", "1", "9"]) + " now"   # (assembled: this file names no address outside the allowed ranges)
        for text in outside + ("http://telemetry.vendor.com/x", "telemetry.vendor.com", "collector.example-cloud.io"):
            self.assertTrue([h for h in hits(f"X = {text!r}\n") if not selfcheck.address_ok(h)], text)
        for text in ("192.0.2.5", "198.51.100.7", "203.0.113.9", "canary.invalid", "127.0.0.1", "localhost:8765", "http://localhost:8765/x", "start.sh", "Terminal.app", "1.2.3", "0.3.0"):
            self.assertEqual([h for h in hits(f"X = {text!r}\n") if not selfcheck.address_ok(h)], [], text)
        self.assertEqual([h for h in hits('def f():\n    """see ' + outside[0] + ' and telemetry.vendor.com"""\n') if not selfcheck.address_ok(h)], [])   # a docstring is not read

    def test_a_planted_bare_address_turns_the_static_check_red(self):
        for src in ("HOST = '" + ".".join(["10", "1", "2", "3"]) + "'\n", "HOST = 'collector.vendor.io'\n"):
            root = Path(tempfile.mkdtemp())
            self.addCleanup(shutil.rmtree, root, True)
            shutil.copytree(SRC, root / "agentboard", ignore=shutil.ignore_patterns("__pycache__"))
            (root / "agentboard" / "leak.py").write_text(src)
            self.assertEqual(list(levels(selfcheck.static_checks(root / "agentboard"), "static: addresses").values()), [selfcheck.FAIL], src)


class TheLinesSayExactlyWhatWasChecked(unittest.TestCase):
    """xr-workpc-selfcheck-overclaims: counts in a PASS line are the real ones."""

    @classmethod
    def setUpClass(cls):
        cls.res = {n: t for _l, n, t in selfcheck.static_checks() + clean_runtime()}

    def test_the_route_counts_are_the_extractors(self):
        get, post, pre_get, _pp = selfcheck.routes_from_source((Path(selfcheck.HERE) / "server.py").read_text())
        line = self.res["runtime: every named route answers without a 5xx"]
        self.assertIn(f"{len(get)} GET routes", line)
        self.assertIn(f"{len(post)} POST routes requested with an empty body", line)
        self.assertIn("validation path", line)

    def test_the_real_payload_line_names_the_routes_that_got_only_validation(self):
        _g, post, _pg, _pp = selfcheck.routes_from_source((Path(selfcheck.HERE) / "server.py").read_text())
        line = self.res["runtime: real payloads through the handlers"]
        self.assertRegex(line, rf"\d+ of {len(post)} POST routes took a real payload the board accepted")
        self.assertIn("/api/run-kill", line)
        self.assertIn("/api/transcribe", line)
        took = int(line.split(" of ", 1)[0])
        self.assertGreaterEqual(took, len(post) - 2)

    def test_the_flood_line_counts_held_and_refused_apart(self):
        line = self.res["http: a flood of connections is capped"]
        self.assertIn("128 are held idle (the cap, 128)", line)
        self.assertIn("30 more were refused with 503", line)
        self.assertNotIn("158 idle connections held", line)

    def test_the_lock_lines_say_the_lock_not_the_features_code_path(self):
        self.assertIn("covered by the lock's tests", self.res["profile: claude rounds refused"])

    def test_the_address_line_names_what_it_did_not_read(self):
        line = self.res["static: addresses in the code"]
        self.assertIn("docstrings are not read", line)
        self.assertIn("built from pieces at run time would not show", line)


class TheProfileSaysWhereItCameFrom(unittest.TestCase):
    """xr-workpc-profile-off-message: apply() writes work into the environment for what it starts; that must not be reported as the shell's own word."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "cfg" / "agentboard").mkdir(parents=True)
        self.board = self.tmp / "proj" / ".agentboard"
        self.board.mkdir(parents=True)
        self.base = {"HOME": str(self.tmp), "XDG_CONFIG_HOME": str(self.tmp / "cfg"), "PATH": os.environ["PATH"], "PYTHONPATH": str(Path(selfcheck.HERE).parent),
                     "PYTHONDONTWRITEBYTECODE": "1", "AGENTBOARD_DIR": str(self.board)}

    def run_cli(self, *args, **env):
        r = subprocess.run([sys.executable, "-m", "agentboard", *args], env={**self.base, **env}, capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout + r.stderr

    def machine(self, on=True):
        f = self.tmp / "cfg" / "agentboard" / "profile"
        f.write_text("work\n") if on else f.unlink()

    def test_the_machine_file_alone_is_called_the_machine_not_the_environment(self):
        self.machine()
        code, out = self.run_cli("profile")
        self.assertIn("on by machine", out)
        self.assertNotIn("on by environment", out)

    def test_profile_off_does_not_blame_the_environment_for_the_machine_file_it_just_removed(self):
        self.machine()
        code, out = self.run_cli("profile", "off")
        self.assertIn("machine switch removed", out)
        self.assertIn("profile: normal", out)
        self.assertNotIn("environment", out)
        self.assertNotIn("stays on", out)

    def test_when_the_shell_really_says_work_the_note_names_it(self):
        self.machine()
        code, out = self.run_cli("profile", "off", AGENTBOARD_PROFILE="work")
        self.assertIn("machine switch removed", out)
        self.assertIn("on by environment", out)
        self.assertIn("environment still says work", out)
        self.assertNotIn("machine still says", out)

    def test_the_board_config_is_named_as_the_board(self):
        (self.board / "config.toml").write_text('[board]\nprofile = "work"\n')
        code, out = self.run_cli("profile")
        self.assertIn("on by board", out)
        self.assertNotIn("on by environment", out)

    def test_the_selfcheck_names_the_machine_file_as_the_source(self):
        self.machine()
        code, out = self.run_cli("selfcheck", "--json")
        line = next(d for d in json.loads(out) if d["check"] == "profile: on in this shell")
        self.assertEqual(line["level"], "PASS")
        self.assertTrue(line["detail"].startswith("machine:"), line["detail"])

    def test_with_nothing_on_the_selfcheck_warns_and_says_how(self):
        code, out = self.run_cli("selfcheck", "--json")
        line = next(d for d in json.loads(out) if d["check"] == "profile: on in this shell")
        self.assertEqual(line["level"], "WARN")
        self.assertIn("agentboard profile work", line["detail"])


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
        root = self.planted(**{"leak.py": "URL = 'https://telemetry.vendor.io/collect'\n"})
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
                        socket.create_connection(("192.0.2.10", 80), timeout=1)
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
