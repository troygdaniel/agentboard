"""docs/ARCHITECTURE.md, CONTRIBUTING.md and docs/index.md are checked against the code: every module is in the map and every module the map
names exists; every data file the map lists is named in the source; every API path and CLI command it mentions exists; every link in the
index resolves and every document in docs/ is in the index; the README points at the index. When the code moves, these fail instead of the
pages going quietly stale."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
SRC = ROOT / "src" / "agentboard"
ARCH = (ROOT / "docs" / "ARCHITECTURE.md").read_text()
CONTRIB = (ROOT / "CONTRIBUTING.md").read_text()
INDEX = (ROOT / "docs" / "index.md").read_text()
SOURCE = "\n".join(p.read_text() for p in SRC.glob("*.py")) + (SRC / "static" / "index.html").read_text()


class TheModuleMap(unittest.TestCase):
    def test_every_module_is_in_the_map_and_every_named_module_exists(self):
        real = {p.name for p in SRC.glob("*.py")}
        named = set(re.findall(r"`([a-z_]+\.py)`", ARCH))
        self.assertEqual(sorted(real - named), [], "modules missing from docs/ARCHITECTURE.md")
        self.assertEqual(sorted(named - real), [], "docs/ARCHITECTURE.md names a module that does not exist")
        for name in ("index.html", "voice.js"):
            self.assertIn(f"`static/{name}`", ARCH)
            self.assertTrue((SRC / "static" / name).is_file())

    def test_the_constants_it_quotes_are_the_codes(self):
        from agentboard import store
        for name in ("TITLE_MAX", "DESCRIPTION_MAX", "STATUS_MAX", "BODY_MAX"):
            self.assertIn(f"`{name}` {getattr(store, name):,}", ARCH)
        self.assertIn(", ".join(f"`{s}`" for s in store.STATUSES), ARCH)
        self.assertIn("setInterval(load, 1000)", (SRC / "static" / "index.html").read_text())


class TheDataFiles(unittest.TestCase):
    def test_every_file_the_table_names_is_named_in_the_source(self):
        rows = [l for l in ARCH.splitlines() if l.startswith("| `") and "Written by" not in l]
        self.assertGreater(len(rows), 10)
        for row in rows:
            for name in re.findall(r"`[^`]*?([a-z._-]+\.(?:json|toml|lock|gz|html|md|log))`", row):
                base = name.split("/")[-1]
                if base in ("tasks-YYYYMMDD-HHMM.json.gz", "<card>-<stamp>.html", "<card>.md"):
                    continue
                self.assertIn(base.replace("tasks.json.bak", "bak"), SOURCE, f"{base} is in the table but not in the code")

    def test_the_two_user_facing_folders_are_named(self):
        self.assertIn(".agentboard/backups/", ARCH)
        self.assertIn(".agentboard/reports/", ARCH)
        self.assertIn("~/.agentboard/boards.toml", ARCH)


class TheServerSection(unittest.TestCase):
    def test_every_api_path_named_exists_in_server_py(self):
        server = (SRC / "server.py").read_text()
        paths = set(re.findall(r"`(?:GET |POST )?(/(?:api|reports|voice|b)[^` ]*)`", ARCH)) | set(re.findall(r"`(/api/[a-z-]+)`", ARCH))
        self.assertGreater(len(paths), 20)
        for p in paths:
            if "<" in p or p in ("/", "/reports/…"):   # the shapes with a placeholder are patterns in server.py (PLUGIN_PATH, BOARD_PATH), not literals
                continue
            self.assertIn(f'"{p}"', server, f"{p} is in ARCHITECTURE.md but not in server.py")

    def test_the_guards_and_headers_it_describes_are_there(self):
        server = (SRC / "server.py").read_text()
        for s in ("bad host", "bad origin", "json required", "X-Frame-Options", "nosniff", "no-referrer", "Content-Security-Policy", '"127.0.0.1"', "ThreadingHTTPServer"):
            self.assertIn(s, server)
        for status in ("403", "415", "400"):
            self.assertIn(status, ARCH)


class TheProtocolSection(unittest.TestCase):
    def test_every_cli_command_named_exists(self):
        from agentboard import cli
        import argparse
        parser = cli.build_parser() if hasattr(cli, "build_parser") else None
        if parser is None:   # find the subparser choices by running --help and reading them
            import contextlib
            import io
            out = io.StringIO()
            with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
                cli.main(["--help"])
            m = re.search(r"\{([a-z,_-]+)\}", out.getvalue())
            commands = set(m.group(1).split(","))
        else:
            commands = {a for a in parser._subparsers._group_actions[0].choices}
        named = set(re.findall(r"`agentboard ([a-z]+)", ARCH + CONTRIB))
        named |= set(re.findall(r"^- `([a-z]+)`", ARCH, re.M))
        self.assertEqual(sorted(named - commands - {"X", "N"}), [], "a command named in the docs does not exist")

    def test_the_card_fields_it_names_are_the_stores(self):
        """The field names in the protocol section's card paragraph are literals in store.py (a renamed field fails here)."""
        store = (SRC / "store.py").read_text()
        para = re.search(r"- A card is a dict with (.*?)\n- `start`", ARCH, re.S).group(1)
        names = set(re.findall(r"`([a-z_]+)`", para)) - {"STATUSES"}
        self.assertGreater(len(names), 15)
        for name in names:
            self.assertIn(f'"{name}"', store, f"ARCHITECTURE.md names a card field {name!r} that store.py never writes")
        self.assertNotIn("`parent`", para)   # the field is parent_id; `answer` is a command, the field is reply

    def test_the_plugin_api_it_lists_is_the_real_one(self):
        from agentboard import plugins
        api_methods = {n for n in dir(plugins.Api) if not n.startswith("_")}
        named = set(re.findall(r"`(add_[a-z]+|set_page)\(", ARCH))
        self.assertEqual(named, api_methods)
        for env in ("AGENTBOARD_PLUGINS", "AGENTBOARD_NO_PLUGINS", "AGENTBOARD_LOCKDOWN", "AGENTBOARD_UMASK", "AGENTBOARD_HOME"):
            self.assertIn(env, ARCH)
            self.assertIn(env, SOURCE)


class TheIndex(unittest.TestCase):
    def test_every_markdown_document_is_in_the_index_and_every_link_resolves(self):
        docs = {p.name for p in (ROOT / "docs").glob("*.md") if p.name != "index.md"}
        for name in docs:
            self.assertIn(f"]({name})", INDEX, f"docs/{name} is not in docs/index.md")
        for target in re.findall(r"\]\(([^)]+)\)", INDEX):
            self.assertTrue((ROOT / "docs" / target).resolve().exists(), f"docs/index.md links to {target}, which does not exist")
        for top in ("README.md", "CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md", "CLAUDE.md"):
            self.assertIn(f"](../{top})", INDEX)
        for folder in (p.name for p in (ROOT / "docs").iterdir() if p.is_dir()):
            self.assertIn(f"docs/{folder}/", INDEX, f"docs/{folder}/ is not in docs/index.md")

    def test_the_readme_points_at_the_index_and_contributing(self):
        readme = (ROOT / "README.md").read_text()
        self.assertIn("docs/index.md", readme)
        self.assertIn("CONTRIBUTING.md", readme)

    def test_contributing_names_the_gates_that_exist(self):
        for s in ("tests/publiccheck.py", "unittest discover -s tests", "agentboard doctor", "rm -rf build && pipx install", "CHANGELOG.md", "## Unreleased"):
            self.assertIn(s, CONTRIB)
        self.assertTrue((ROOT / "tests" / "test_install_clean.py").is_file())
        self.assertTrue((ROOT / "tests" / "test_version.py").is_file())
        self.assertTrue((ROOT / "tests" / "timing.py").is_file())


if __name__ == "__main__":
    unittest.main()
