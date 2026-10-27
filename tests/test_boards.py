"""Named boards: the registry, which board a command picks, and the server's /b/<name>/ routing."""
import contextlib
import io
import json
import os
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from agentboard import boards, cli, server
from agentboard.store import BoardError, Store, find_dir


class Env(unittest.TestCase):
    """A private ~/.agentboard (AGENTBOARD_HOME) and no board variables from the real shell."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.home = self.root / "home"
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        env["AGENTBOARD_HOME"] = str(self.home)
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        self.cwd = os.getcwd()
        self.addCleanup(os.chdir, self.cwd)


class RegistryTests(Env):
    def test_new_creates_the_folder_and_registers_it(self):
        d = boards.new("work", color="blue")
        self.assertEqual(d, self.home / "boards" / "work" / ".agentboard")
        self.assertTrue((d / "tasks.json").exists())
        self.assertEqual(boards.load()["boards"]["work"], {"path": str(d), "color": "blue"})
        self.assertEqual(boards.path_of("work"), d)
        self.assertEqual(boards.name_for(d), "work")

    def test_names_are_checked_and_not_reused(self):
        for bad in ("", "Work", "a b", "../x", "-x", "x" * 41):
            with self.assertRaises(BoardError):
                boards.check_name(bad)
        boards.new("work")
        with self.assertRaises(BoardError):
            boards.new("work")
        with self.assertRaises(BoardError):
            boards.path_of("nope")

    def test_use_and_remove(self):
        boards.new("a")
        boards.new("b")
        boards.use("b")
        self.assertEqual(boards.load()["current"], "b")
        boards.remove("b")
        self.assertIsNone(boards.load()["current"])
        self.assertTrue((self.home / "boards" / "b" / ".agentboard").exists())   # forgetting a board never deletes cards
        with self.assertRaises(BoardError):
            boards.use("b")

    def test_a_missing_registry_is_empty_and_a_broken_one_says_so(self):
        self.assertEqual(boards.load(), {"current": None, "boards": {}})
        self.home.mkdir(parents=True)
        (self.home / "boards.toml").write_text("this is [not toml")
        with self.assertRaises(BoardError):
            boards.load()

    def test_odd_characters_in_a_path_survive_the_file(self):
        d = self.root / 'a "quoted" folder' / ".agentboard"
        boards.register("odd", d)
        self.assertEqual(boards.path_of("odd"), d)


class PickTests(Env):
    def project(self, name):
        d = self.root / name
        (d / ".agentboard").mkdir(parents=True)
        return d

    def test_precedence_flag_env_then_dir_then_folder_then_use(self):
        work = boards.new("work")
        here = self.project("proj")
        other = self.project("other") / ".agentboard"
        os.chdir(here)
        self.assertEqual(find_dir(), here / ".agentboard")                      # the folder's board is the default
        boards.use("work")
        self.assertEqual(find_dir(), here / ".agentboard")                      # `use` does not override a project folder
        os.environ["AGENTBOARD_DIR"] = str(other)
        self.assertEqual(find_dir(), other)
        os.environ["AGENTBOARD_BOARD"] = "work"
        self.assertEqual(find_dir(), work.resolve())                            # a named board beats both
        os.environ.pop("AGENTBOARD_BOARD")
        os.environ.pop("AGENTBOARD_DIR")
        os.chdir(self.root)                                                     # no board in this folder: the chosen one
        self.assertEqual(find_dir(), work.resolve())
        boards.remove("work")
        with self.assertRaises(BoardError):
            find_dir()

    def test_an_unknown_board_name_is_an_error_not_a_silent_fallback(self):
        os.chdir(self.project("proj"))
        os.environ["AGENTBOARD_BOARD"] = "ghost"
        with self.assertRaises(BoardError):
            find_dir()


class BackupTests(Env):
    def test_each_board_keeps_its_own_snapshots_and_its_own_sync_copy(self):
        a, b = Store(boards.new("a")), Store(boards.new("b"))
        sync_a, sync_b = self.root / "sync-a", self.root / "sync-b"
        (a.dir / "config.toml").write_text(f'[backup]\nsync_dir = "{sync_a}"\n')
        (b.dir / "config.toml").write_text(f'[backup]\nsync_dir = "{sync_b}"\n')
        a.add("A card")
        b.add("B card")
        self.assertTrue(a.backups.snapshots() and b.backups.snapshots())
        self.assertNotEqual(a.backups.snap_dir, b.backups.snap_dir)
        ca = Store(a.dir).backups.sync(force=True)
        cb = Store(b.dir).backups.sync(force=True)
        self.assertEqual((ca.parent, cb.parent), (sync_a, sync_b))
        self.assertIn("agentboard-a-", ca.name)   # named after the board, so two boards can share one sync folder
        self.assertIn("agentboard-b-", cb.name)


class CliTests(Env):
    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(list(argv))
        return out.getvalue()

    def test_board_new_list_use_and_the_board_flag(self):
        out = self.run_cli("board", "new", "work", "--color", "green")
        self.assertIn("created board work", out)
        self.run_cli("--board", "work", "add", "On the work board", "--status", "todo")
        self.assertEqual([t["id"] for t in Store(boards.path_of("work")).load()], ["on-the-work-board"])
        listing = self.run_cli("board", "list")
        self.assertIn("work", listing)
        self.assertIn("[green]", listing)
        self.run_cli("board", "use", "work")
        os.chdir(self.root)   # no project here: the chosen board answers
        self.assertIn("on-the-work-board", self.run_cli("list"))
        os.environ["AGENTBOARD_BOARD"] = "work"   # the env var does the same as the flag
        self.assertIn("on-the-work-board", self.run_cli("list"))
        self.run_cli("board", "rm", "work")
        self.assertNotIn("work", boards.load()["boards"])


class RoutingTests(Env):
    def setUp(self):
        super().setUp()
        self.default = Store(self.root / "proj" / ".agentboard")
        self.default.add("Default card", status="todo")
        self.work = Store(boards.new("work", color="blue"))
        self.work.add("Work card", status="todo")
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), server.make_handler(self.default, self.port))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
            return r.status, r.read()

    def post(self, path, body):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())

    def titles(self, path):
        return [t["title"] for t in json.loads(self.get(path)[1])["tasks"]]

    def test_the_default_board_keeps_its_links(self):
        self.assertEqual(self.titles("/api/tasks"), ["Default card"])
        status, html = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b'window.AB_BASE = ""', html)
        self.assertEqual(self.get("/hud")[0], 200)

    def test_a_named_board_is_served_under_its_prefix(self):
        self.assertEqual(self.titles("/b/work/api/tasks"), ["Work card"])
        self.assertIn(b'window.AB_BASE = "/b/work"', self.get("/b/work/")[1])
        self.assertIn(b'window.AB_BASE = "/b/work"', self.get("/b/work/hud")[1])
        self.assertEqual(self.get("/b/work/api/hud")[0], 200)   # the HUD answers for that board

    def test_writes_land_on_the_board_in_the_url(self):
        self.post("/b/work/api/tasks", {"title": "Added over HTTP", "status": "todo"})
        self.assertEqual([t["title"] for t in self.work.load()], ["Added over HTTP", "Work card"])
        self.assertEqual([t["title"] for t in self.default.load()], ["Default card"])

    def test_unknown_boards_and_bad_names_are_404(self):
        for path in ("/b/ghost/api/tasks", "/b/ghost/", "/b/../api/tasks"):
            with self.assertRaises(urllib.error.HTTPError) as e:
                self.get(path)
            self.assertEqual(e.exception.code, 404)
            e.exception.close()

    def test_the_switcher_lists_the_default_first_then_the_others(self):
        d = json.loads(self.get("/api/boards")[1])
        self.assertEqual([b["name"] for b in d["boards"]], ["proj", "work"])
        self.assertEqual((d["current"], d["boards"][1]["url"], d["boards"][1]["color"]), ("/", "/b/work/", "blue"))
        self.assertEqual(json.loads(self.get("/b/work/api/boards")[1])["current"], "/b/work/")

    def test_a_board_registered_after_the_server_started_appears_at_once(self):
        boards.new("later")
        self.assertEqual(self.titles("/b/later/api/tasks"), [])

    def test_the_host_check_still_applies_under_a_prefix(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/b/work/api/tasks", headers={"Host": "evil.example"})
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req)
        self.assertEqual(e.exception.code, 403)
        e.exception.close()


if __name__ == "__main__":
    unittest.main()
