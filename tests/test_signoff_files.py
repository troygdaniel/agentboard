"""The file table in docs/security-signoff.md stays true: every path the board writes in a day's work is named there, with the mode
the table gives, and nothing is written under HOME.

A reviewer trusts the table only if it cannot drift (chat-listeners.json and server-<pid>.json arrived on Nov 7 without a word in
SECURITY.md). So a scripted session does a day's work on a throwaway project with a throwaway HOME, under a normal umask, and this test
walks everything it made. A new file fails with its name: add it to the table (and say what it holds), or stop writing it."""
import os
import re
import stat
import unittest
from pathlib import Path

from test_file_modes import Session, mode

ROOT = Path(__file__).resolve().parents[1]
SIGNOFF = ROOT / "docs" / "security-signoff.md"


def table_rows():
    """[(names, mode)] from the 'Every file the board writes' table: the backtick names in the first column and the mode column."""
    text = SIGNOFF.read_text()
    start = text.index("## Every file the board writes")
    end = text.index("\n## ", start + 10)
    rows = []
    for line in text[start:end].splitlines():
        if not line.startswith("| `") or line.startswith("| File"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        names = re.findall(r"`([^`]+)`", cells[0])
        rows.append((names, cells[2]))
    return rows


def pattern_for(name):
    """A documented name as a regex over a path relative to the project: <stamp>, <pid>, <card>, <id> are wildcards; a trailing / is a folder."""
    name = name.replace("<project>/", "")
    folder = name.endswith("/")
    rx = re.escape(name.rstrip("/"))
    for ph in ("stamp", "pid", "card", "id"):
        rx = rx.replace(re.escape(f"<{ph}>"), r"[^/]+")
    rx = rx.replace(re.escape("{"), "(?:").replace(re.escape("}"), ")").replace(",", "|")   # {a,b} alternatives
    return re.compile(rx + ("(/.*)?" if folder else "") + "$")


def documented(rel):
    """The table row that names this relative path, or None. A folder is documented when a documented path lies inside it (the table
    names `backups/tasks-<stamp>.json.gz`, not the backups folder itself)."""
    rows = table_rows()
    for names, m in rows:
        for n in names:
            if pattern_for(n).match(rel):
                return (n, m)
    for names, m in rows:
        for n in names:
            if n.replace("<project>/", "").startswith(rel + "/"):
                return (n, m)
    return None


class TheTableIsTrue(unittest.TestCase):
    def setUp(self):
        self.s = Session()
        self.addCleanup(self.s.close)
        # .agentboard/sessions.json is written when a command runs inside a Claude Code session (it has CLAUDE_CODE_SESSION_ID); the table must be checked the same
        # way wherever the suite runs, so the scripted day is given a session id of its own
        self.s.env["CLAUDE_CODE_SESSION_ID"] = "test-session-for-the-signoff-table"
        self.s.run("init", "add 'A card' -d 'words' --status todo --id a-card", "claim a-card --name AGENT-1", "add 'step' --parent a-card",
                   "update step 50 working", "ask a-card 'a question?'", "review a-card 'a result' --body 'a body'",
                   "chat send 'hello' --name AGENT-1 --to 'the user'", "backup", "hooks install")

    def written(self):
        """Every file and folder made under the project (relative posix paths), the board folder first."""
        out = []
        for dp, dns, fns in os.walk(self.s.work):
            for n in dns + fns:
                out.append((Path(dp) / n).relative_to(self.s.work).as_posix())
        return sorted(out)

    def test_the_day_made_the_interesting_files(self):
        names = set(self.written())
        for want in (".agentboard", ".agentboard/tasks.json", ".agentboard/tasks.json.bak", ".agentboard/config.toml", ".agentboard/.lock",
                     ".agentboard/sessions.json", ".agentboard/backups", ".agentboard/reports", ".gitignore", ".claude/settings.json"):
            self.assertIn(want, names)
        self.assertTrue(any(n.startswith(".agentboard/backups/tasks-") for n in names), names)
        self.assertTrue(any(n.startswith(".agentboard/reports/") and n.endswith(".html") for n in names), names)

    def test_every_path_written_is_in_the_table(self):
        missing = [p for p in self.written() if p != ".agentboard" and documented(p.removeprefix(".agentboard/") if p.startswith(".agentboard/") else p) is None]
        self.assertEqual(missing, [], f"written by the board but not in docs/security-signoff.md: {missing}")

    def test_the_mode_in_the_table_is_the_mode_on_disk(self):
        for p in self.written():
            path = self.s.work / p
            if p.startswith(".agentboard"):
                want = 0o700 if path.is_dir() else 0o600
                row = documented(p.removeprefix(".agentboard/")) if p != ".agentboard" else (".agentboard/", "700")
                self.assertIn(oct(want)[2:], row[1], f"{p}: table says {row[1]!r}, disk is {oct(mode(path))}")
                self.assertEqual(mode(path), want, f"{p} is {oct(mode(path))}")
            elif p.startswith(".claude"):   # settings.json: agentboard creates it 0600, an existing file keeps its mode (hooks.write_settings)
                row = documented(p)
                self.assertIn("0600", row[1], f"{p}: the table should say a created file is 0600")
                self.assertIn("keeps its mode", row[1], f"{p}: the table should say an existing file keeps its mode")
                if path.is_file():
                    self.assertEqual(mode(path), 0o600, f"{p} is {oct(mode(path))} (created by hooks install in this session)")
            else:   # .gitignore follows the user's umask, 022 in the scripted session
                row = documented(p)
                self.assertIn("umask", row[1], f"{p}: the table should say it follows your umask")
                if path.is_file():
                    self.assertEqual(mode(path), 0o644, f"{p} is {oct(mode(path))}")

    def test_an_existing_settings_file_keeps_its_mode_and_its_copies_are_in_the_table(self):
        s = Session()
        self.addCleanup(s.close)
        (s.work / ".claude").mkdir()
        (s.work / ".claude" / "settings.json").write_text("{}\n")
        os.chmod(s.work / ".claude" / "settings.json", 0o644)
        s.run("init", "hooks install")
        for name in ("settings.json", "settings.json.orig", "settings.json.bak"):
            p = s.work / ".claude" / name
            self.assertTrue(p.is_file(), name)
            self.assertIsNotNone(documented(f".claude/{name}"), f".claude/{name} is not in the table")
        self.assertEqual(mode(s.work / ".claude" / "settings.json"), 0o644)   # the team's file keeps the mode it had

    def test_nothing_is_written_under_home(self):
        made = [str(p.relative_to(self.s.home)) for p in self.s.home.rglob("*")]
        self.assertEqual(made, [], f"the board wrote under HOME: {made}")

    def test_the_table_names_exactly_two_home_files_the_registry_and_the_machine_profile(self):
        names = [n for row in table_rows() for n in row[0] if n.startswith("~/")]
        self.assertEqual(names, ["~/.agentboard/boards.toml", "~/.config/agentboard/profile"])

    def test_profile_work_writes_the_one_machine_file_the_table_names_and_nothing_else_under_home(self):
        s = Session()
        self.addCleanup(s.close)
        s.run("init", "profile work")
        made = sorted(str(p.relative_to(s.home)) for p in s.home.rglob("*"))
        self.assertEqual(made, [".config", ".config/agentboard", ".config/agentboard/profile"])
        self.assertEqual(mode(s.home / ".config" / "agentboard" / "profile"), 0o600)
        self.assertEqual(mode(s.home / ".config" / "agentboard"), 0o700)
        self.assertEqual((s.home / ".config" / "agentboard" / "profile").read_text().strip(), "work")


class TheParser(unittest.TestCase):
    def test_the_table_is_found_and_has_rows(self):
        rows = table_rows()
        self.assertGreater(len(rows), 8)
        self.assertIn("tasks.json", [n for r in rows for n in r[0]])

    def test_placeholders_and_folders(self):
        self.assertTrue(pattern_for("<project>/.claude/{settings.json,settings.json.orig,settings.json.bak}").match(".claude/settings.json.orig"))
        self.assertTrue(pattern_for("backups/tasks-<stamp>.json.gz").match("backups/tasks-20261107-2316.json.gz"))
        self.assertTrue(pattern_for("server-<pid>.json").match("server-4242.json"))
        self.assertTrue(pattern_for("runs/<card>/<id>/{run.json,prompt.md,stdout.json,stderr.log}").match("runs/a-card/r1/stderr.log"))
        self.assertTrue(pattern_for("<project>/.agentboard/").match(".agentboard/anything/below"))
        self.assertFalse(pattern_for("tasks.json").match("tasks.json.bak"))
        self.assertFalse(pattern_for("reports/<card>.html").match("reports/x.json"))

    def test_an_undocumented_file_is_reported_and_a_documented_folder_is_not(self):
        self.assertIsNone(documented("chat-nobody.json"))
        self.assertIsNone(documented("reports/x.json"))
        self.assertEqual(documented("backups")[0], "backups/tasks-<stamp>.json.gz")
        self.assertEqual(documented(".claude")[0], "<project>/.claude/{settings.json,settings.json.orig,settings.json.bak}")


if __name__ == "__main__":
    unittest.main()
