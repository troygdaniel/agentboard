"""GET /api/settings (settings-ui-tabs phase 2: the Security and Backup and data tabs). The rule is `agentboard config show`'s: on or off, counts and ages,
never a path, a pattern, a name or a secret. So every value in the answer is a boolean, a whole number or null; the route sits behind the Host check like
every other; no route changes any of it; and the page only reads it, naming the key or the command that changes each row."""
import json
import os
import re
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from agentboard import nav, server, settingsview
from agentboard.store import Store

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()
SECRET_PATTERN = "SECRET-PATTERN-ABC123"
SECRET_DIR = "/tmp/secret-sync-folder-xyz"


def leaves(x):
    if isinstance(x, dict):
        for v in x.values():
            yield from leaves(v)
    else:
        yield x


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        env["AGENTBOARD_HOME"] = str(Path(self.tmp.name) / "home")
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        self.proj = Path(self.tmp.name) / "proj"
        self.proj.mkdir()
        self.dir = self.proj / ".agentboard"
        self.dir.mkdir(mode=0o700)
        self.s = Store(self.dir)
        os.chmod(self.dir, 0o700)

    def config(self, text):
        (self.dir / "config.toml").write_text(text)


class TheAnswerIsOnlyBooleansCountsAndMinutes(Base):
    def test_nothing_that_is_a_string_leaves_the_module(self):
        self.config(f'[redact]\nextra = ["{SECRET_PATTERN}"]\nphones = true\n[backup]\nsync_dir = "{SECRET_DIR}"\n')
        r = settingsview.status(self.dir)
        self.assertEqual({type(v).__name__ for v in leaves(r)} - {"bool", "int", "NoneType"}, set())

    def test_no_pattern_path_or_name_can_be_in_the_json(self):
        self.config(f'[redact]\nextra = ["{SECRET_PATTERN}"]\n[backup]\nsync_dir = "{SECRET_DIR}"\n')
        text = json.dumps(settingsview.status(self.dir))
        for needle in (SECRET_PATTERN, "secret-sync", "/tmp", str(self.dir), self.tmp.name, "/"):
            self.assertNotIn(needle, text)

    def test_the_pattern_and_the_sync_folder_are_a_count_and_a_flag(self):
        self.config(f'[redact]\nextra = ["{SECRET_PATTERN}", "ANOTHER-ONE"]\nphones = true\n[backup]\nsync_dir = "{SECRET_DIR}"\n')
        r = settingsview.status(self.dir)
        self.assertEqual(r["redact"], {"enabled": True, "phones": True, "extra": 2})
        self.assertIs(r["backup"]["sync"], True)


class TheValues(Base):
    def test_a_fresh_board_reads_masking_on_private_no_lock_and_no_plugins(self):
        r = settingsview.status(self.dir)
        self.assertEqual((r["lockdown"], r["profile"], r["redact"]["enabled"], r["data_private"]), (False, False, True, True))
        self.assertEqual(r["plugins"], {"allowed": False, "loaded": 0, "failed": 0})
        self.assertIs(r["backup"]["sync"], False)

    def test_masking_off_is_reported_as_off(self):
        self.config("[redact]\nenabled = false\n")
        self.assertIs(settingsview.status(self.dir)["redact"]["enabled"], False)

    def test_a_broken_config_does_not_break_the_answer(self):
        self.config("this is = = not toml [[[")
        r = settingsview.status(self.dir)
        self.assertIs(r["redact"]["enabled"], True)   # the default, not an error

    def test_lockdown_is_on_when_the_variable_is_and_plugins_follow_the_gate(self):
        with mock.patch.dict(os.environ, {"AGENTBOARD_LOCKDOWN": "1"}):
            r = settingsview.status(self.dir)
        self.assertIs(r["lockdown"], True)
        self.assertIs(r["plugins"]["allowed"], False)
        with mock.patch.dict(os.environ, {"AGENTBOARD_PLUGINS": "1"}):
            self.assertIs(settingsview.status(self.dir)["plugins"]["allowed"], True)

    def test_a_data_folder_others_can_read_is_not_private(self):
        os.chmod(self.dir, 0o755)
        self.assertIs(settingsview.status(self.dir)["data_private"], False)
        os.chmod(self.dir, 0o700)
        self.assertIs(settingsview.status(self.dir)["data_private"], True)

    def test_the_last_backup_is_minutes_and_the_snapshots_a_count(self):
        self.s.add("A card")   # a write makes a snapshot
        r = settingsview.status(self.dir)["backup"]
        self.assertIsInstance(r["snapshots"], int)
        self.assertTrue(r["last_min"] is None or isinstance(r["last_min"], int))


class TheRoute(Base):
    def setUp(self):
        super().setUp()
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
            self.port = sk.getsockname()[1]
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), server.make_handler(self.s, self.port))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def request(self, method="GET", host=None, body=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/settings", data=body, method=method, headers={"Content-Type": "application/json"})
        if host:
            req.add_header("Host", host)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            e.close()
            return e.code, None

    def test_it_answers_json_for_our_own_host(self):
        status, d = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(set(d), {"lockdown", "profile", "plugins", "redact", "backup", "data_private"})

    def test_a_foreign_host_is_refused_like_every_other_route(self):
        self.assertEqual(self.request(host="evil.example")[0], 403)

    def test_nothing_can_change_it_from_http(self):
        for method in ("POST", "PUT", "DELETE"):
            status, _ = self.request(method, body=b"{}")
            self.assertNotEqual(status, 200, method)


class ThePageOnlyReadsIt(unittest.TestCase):
    def test_the_tabs_are_drawn_only_once_the_status_has_been_read(self):
        self.assertIn("settingsTab('security', 'Security', { order: 60, pane: $('pane-security'), icon: SET_ICON.security, has: () => !!settingsInfo });", HTML)
        self.assertIn("settingsTab('backup', 'Backup and data', { order: 70, pane: $('pane-backup'), icon: SET_ICON.backup, has: () => !!settingsInfo });", HTML)
        self.assertIn("const r = await fetch('/api/settings', { cache: 'no-store' }); if (!r.ok) return; settingsInfo = await r.json();", HTML)
        self.assertIn("renderStatusRows(); syncSettingsTabs();", HTML)

    def test_the_page_never_writes_to_it(self):
        self.assertNotRegex(HTML, r"api\('/api/settings'")
        fn = re.search(r"async function loadSettingsInfo\(\) \{.*?\n\}\n", HTML, re.S).group(0)
        self.assertNotIn("POST", fn)
        rows = re.search(r"function renderStatusRows\(\) \{.*?\n\}\n", HTML, re.S).group(0)
        self.assertNotIn("api(", rows)
        self.assertNotIn('type="checkbox"', rows)
        self.assertNotIn("<button", rows)   # read-only: no control, only the key or the command that changes each row

    def test_each_row_names_the_key_or_the_command_that_changes_it(self):
        rows = re.search(r"function renderStatusRows\(\) \{.*?\n\}\n", HTML, re.S).group(0)
        for named in ("AGENTBOARD_LOCKDOWN", "agentboard profile work", "[redact]", "AGENTBOARD_PLUGINS", "agentboard selfcheck", "agentboard backup", "[backup] sync_dir", "agentboard doctor"):
            self.assertIn(named, rows)

    def test_a_masking_that_is_off_and_a_folder_others_can_read_are_amber(self):
        self.assertIn("ro('Secret masking', I.redact.enabled ? 'on' : 'OFF', mask, !I.redact.enabled)", HTML)
        self.assertIn("I.data_private ? 'private' : 'readable by others'", HTML)
        self.assertIn("var(--warn)", re.search(r"\.mix-row \.val\.warn b \{([^}]*)\}", HTML).group(1))


if __name__ == "__main__":
    unittest.main()
