"""The board's side of agent configurations and rename (card agent-config-slice-3): what the picker asks for and what the Rename dialog does.

`GET /api/configurations` lists what ships and what is applied; `POST /api/configuration/preview|apply|clear` show an imported file, apply one and take it off;
`GET /api/configuration/export` hands back a file; `POST /api/rename/plan|rename|undo` are the counts, the rename and its Undo, the same functions the
command line runs. Every write is the owner's click: nothing here starts a program, and an imported file is validated before it is shown or kept."""
import json
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from agentboard import configurations as cfgs
from agentboard.server import make_handler
from agentboard.store import Store

GOOD = {"configuration": 1, "name": "Mine", "roles": [{"role": "writer", "names": ["Writer-1"], "purpose": "writes"}]}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        self.s.dir.mkdir(parents=True, exist_ok=True)
        self.s.add("Search box", status="todo", task_id="spa")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), make_handler(self.s, self.port))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.shutdown)

    def on(self):
        (self.s.dir / "config.toml").write_text("[agents]\nconfigurations = true\n")

    def call(self, path, payload=None):
        h = {"Content-Type": "application/json", "Host": f"localhost:{self.port}", "Origin": f"http://localhost:{self.port}"}
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=None if payload is None else json.dumps(payload).encode(), headers=h)
        try:
            r = urllib.request.urlopen(req, timeout=5)
            return r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    def js(self, path, payload=None):
        code, raw, _ = self.call(path, payload)
        return code, json.loads(raw)


class ThePicker(Base):
    def test_the_three_built_ins_ship_in_the_boards_order(self):
        self.assertEqual([c["key"] for c in cfgs.builtin_list()], ["build", "dream-up", "day-to-day"])
        for c in cfgs.builtin_list():
            self.assertEqual({k: v for k, v in c.items() if k != "key"}, cfgs.validate({k: v for k, v in c.items() if k != "key"}))   # each is a valid file as it stands
        build = cfgs.builtin("build")
        self.assertEqual(cfgs.roster(build), ["Dev-1", "Dev-2", "QA-1", "Arch", "Design"])
        for r in build["roles"]:
            for never in ("merge", "push", "install"):
                self.assertIn(never, r["may_not"], f"{r['role']} may not {never}")   # nobody on the build team merges, pushes or installs

    def test_off_the_page_is_told_it_is_off_and_nothing_else(self):
        self.assertEqual(self.js("/api/configurations"), (200, {"enabled": False}))

    def test_on_it_lists_what_ships_with_the_terminals_to_type(self):
        self.on()
        code, st = self.js("/api/configurations")
        self.assertEqual(code, 200)
        self.assertTrue(st["enabled"])
        self.assertIsNone(st["applied"])
        self.assertEqual([c["key"] for c in st["builtin"]], ["build", "dream-up", "day-to-day"])
        dev = st["builtin"][0]["start"][0]
        self.assertEqual((dev["name"], dev["role"], dev["lines"]), ("Dev-1", "dev", ["/rename Dev-1", "export AGENTBOARD_NAME=Dev-1"]))

    def test_applying_one_by_key_keeps_the_applied_copy_and_says_so(self):
        self.on()
        code, st = self.js("/api/configuration/apply", {"key": "build"})
        self.assertEqual(code, 200)
        self.assertEqual((st["applied"]["name"], st["applied"]["source"]), ("Build or improve an application", "build"))
        self.assertEqual(cfgs.applied(self.s.dir)["name"], "Build or improve an application")
        self.assertEqual(Store.get(self.s.load(), "spa")["status"], "todo")   # applying changes the roster and the labels, never a card
        code, st = self.js("/api/configuration/clear", {})
        self.assertIsNone(st["applied"])
        self.assertIsNone(cfgs.applied(self.s.dir))

    def test_it_is_refused_while_the_setting_is_off(self):
        for path, body in (("/api/configuration/apply", {"key": "build"}), ("/api/configuration/clear", {})):
            code, err = self.js(path, body)
            self.assertEqual(code, 400)
            self.assertIn("[agents] configurations = true", err["error"])
        self.assertEqual(self.call("/api/configuration/export?key=build")[0], 400)
        self.assertIsNone(cfgs.applied(self.s.dir))


class ImportAndExport(Base):
    def test_an_imported_file_is_shown_before_anything_is_kept(self):
        self.on()
        code, shown = self.js("/api/configuration/preview", {"text": json.dumps(GOOD)})
        self.assertEqual(code, 200)
        self.assertEqual((shown["name"], shown["start"][0]["name"]), ("Mine", "Writer-1"))
        self.assertIsNone(cfgs.applied(self.s.dir))   # a preview writes nothing

    def test_a_bad_file_is_refused_with_what_is_wrong(self):
        for text, word in (("{nope", "not JSON"), (json.dumps({**GOOD, "extra": 1}), "unknown key"), (json.dumps({**GOOD, "name": ""}), "name is missing"),
                           (json.dumps({"configuration": 1, "name": "X", "roles": [{"role": "r", "names": ["ORCH"]}]}), "keeps for itself"), ("x" * 70_000, "over 64 KB")):
            code, err = self.js("/api/configuration/preview", {"text": text})
            self.assertEqual(code, 400, word)
            self.assertIn(word, err["error"])
        self.assertEqual(self.js("/api/configuration/preview", {"text": 5})[0], 400)

    def test_applying_an_imported_file_names_its_source(self):
        self.on()
        code, st = self.js("/api/configuration/apply", {"text": json.dumps(GOOD)})
        self.assertEqual((code, st["applied"]["name"], st["applied"]["source"]), (200, "Mine", "imported file"))
        code, err = self.js("/api/configuration/apply", {"text": json.dumps({**GOOD, "roles": []})})
        self.assertEqual(code, 400)
        self.assertEqual(cfgs.applied(self.s.dir)["name"], "Mine")   # the refused file changed nothing

    def test_export_is_the_file_and_only_the_file(self):
        self.on()
        code, raw, headers = self.call("/api/configuration/export?key=dream-up")
        self.assertEqual(code, 200)
        self.assertIn('filename="dream-up-an-application-or-feature.json"', headers["Content-Disposition"])
        d = json.loads(raw)
        self.assertEqual(set(d), {"configuration", "name", "description", "roles"})   # no card, no chat line, no path
        self.assertEqual(cfgs.validate(d), cfgs.builtin("dream-up"))
        self.js("/api/configuration/apply", {"key": "build"})
        code, raw, _ = self.call("/api/configuration/export?applied=1")
        self.assertEqual(json.loads(raw)["name"], "Build or improve an application")
        self.assertEqual(self.call("/api/configuration/export?key=nope")[0], 400)


class TheRenameDialog(Base):
    def setUp(self):
        super().setUp()
        self.s.add("Scout card", status="todo", task_id="sc")
        self.s.claim("sc", "Scout")

    def test_the_counts_come_first_and_change_nothing(self):
        code, r = self.js("/api/rename/plan", {"old": "Scout", "new": "Ives"})
        self.assertEqual(code, 200)
        self.assertEqual((r["plan"]["old"], r["plan"]["new"], r["plan"]["cards"]), ("Scout", "Ives", 1))
        self.assertTrue(r["lines"])
        self.assertEqual(Store.get(self.s.load(), "sc")["agent"], "Scout")

    def test_rename_then_undo(self):
        code, r = self.js("/api/rename", {"old": "Scout", "new": "Ives"})
        self.assertEqual((code, r["undo"]), (200, True))
        self.assertEqual(Store.get(self.s.load(), "sc")["agent"], "Ives")
        code, r = self.js("/api/rename/undo", {})
        self.assertEqual(code, 200)
        self.assertEqual(Store.get(self.s.load(), "sc")["agent"], "Scout")

    def test_the_refusals_reach_the_dialog_as_sentences(self):
        for body, word in (({"old": "Scout", "new": "ORCH"}, "keeps for itself"), ({"old": "Scout", "new": ""}, "1 to 40"), ({"old": "Nobody", "new": "Ives"}, "no agent named")):
            code, err = self.js("/api/rename/plan", body)
            self.assertEqual(code, 400, body)
            self.assertIn(word, err["error"])
        self.assertEqual(self.js("/api/rename", {"old": 1, "new": 2})[0], 400)
        code, err = self.js("/api/rename/undo", {})
        self.assertEqual(code, 400)   # nothing to undo yet


if __name__ == "__main__":
    unittest.main()
