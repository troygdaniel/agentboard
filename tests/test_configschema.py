"""One schema for config.toml (overnight-config-validation): typos get the closest name, wrong types and ranges fall back to the default and
say so (fail closed), unsafe switches are warnings, `config show` says where every value came from, the docs page is generated from the
schema and cannot drift, plugins add their own sections, doctor carries the findings."""
import contextlib
import io
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli, configschema as cs, doctor, hud, plugins, tomlread
from agentboard import prompt as promptlib
from agentboard.store import Store

ROOT = Path(__file__).parents[1]


def uncommented_sample():
    from agentboard.cli import SAMPLE_CONFIG
    out = []
    for line in SAMPLE_CONFIG.splitlines():
        body = line[2:] if line.startswith("# ") else line
        if re.match(r"\s*(?:\[[\w.\"'-]+\]|[\w\"'-]+\s*=)", body) and "<name>" not in body:
            out.append(body)
    return "\n".join(out) + "\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.board = Path(self.tmp.name) / ".agentboard"
        Store(self.board).add("A card")
        cs._reset()
        self.addCleanup(cs._reset)

    def conf(self, text):
        (self.board / "config.toml").write_text(text)

    def findings(self, text):
        return cs.validate(tomlread.loads(text))

    def levels(self, text):
        return [(f.level, f.where) for f in self.findings(text)]


class Typos(Base):
    def test_a_misspelt_key_names_the_closest_valid_one(self):
        f = self.findings('[board]\nstale_minute = 90\n')
        self.assertEqual([(x.level, x.where) for x in f], [("WARN", "board.stale_minute")])
        self.assertIn("stale_minutes", f[0].fix)

    def test_a_misspelt_section_names_the_closest_one_and_an_unknown_one_is_only_info(self):
        f = self.findings('[chats]\ncasual = true\n')
        self.assertEqual((f[0].level, f[0].where), ("WARN", "[chats]"))
        self.assertIn("[chat]", f[0].fix)
        f = self.findings('[texts]\nenabled = true\n')
        self.assertEqual((f[0].level, f[0].where), ("INFO", "[texts]"))
        self.assertIn("plugin", f[0].text)

    def test_the_sample_config_and_the_readme_block_are_clean(self):
        f = self.findings(uncommented_sample())
        self.assertEqual([x for x in f if x.level != "WARN" or "Unsafe" not in x.text and "program" not in x.text and "copies" not in x.text and "masking" not in x.text], [],
                         "init writes a key the schema does not know, or a value out of its range")   # with every switch on, the unsafe ones are warned about, rightly
        text = (ROOT / "README.md").read_text()
        m = re.search(r"## Configuration.*?\n\n((?:    .*\n|\n)+?)Environment", text, re.S)
        block = "\n".join(l[4:] for l in m.group(1).splitlines() if "<name>" not in l and 'type = "markdown"' not in l)
        self.assertEqual(self.findings(block), [])

    def test_every_key_the_code_reads_is_in_the_schema(self):
        """A `.get("key")` on a config section in the code must be a schema key (the scan is by section helper: the few places that read config)."""
        src = (ROOT / "src" / "agentboard")
        reads = {("board", "owner"), ("board", "stale_minutes"), ("hud", "retired"), ("orch", "agents"), ("ui", "dispatch"), ("notify", "enabled"), ("notify", "sound"),
                 ("prompt", "template_file"), ("prompt", "template"), ("chat", "idle_model"), ("chat", "idle_budget_usd"), ("chat", "casual"), ("chat", "casual_per_hour"),
                 ("chat", "autopilot"), ("chat", "autopilot_every"), ("chat", "autopilot_per_hour"), ("chat", "share_every_min"), ("chat", "live_min"),
                 ("run", "claude"), ("run", "budget_usd"), ("run", "max_minutes"), ("reports", "keep_hours"), ("reports", "repo"), ("backup", "sync_dir"),
                 ("redact", "enabled"), ("redact", "phones"), ("redact", "extra"), ("voice", "words"), ("voice", "model"), ("knowledge", "files")}
        for sect, key in reads:
            self.assertIn(key, cs.SCHEMA[sect], f"{sect}.{key}")
            self.assertRegex("\n".join(p.read_text() for p in src.glob("*.py")), rf'"{key}"', f"{sect}.{key} is in the schema but no module reads it")
        code = (src / "providers.py").read_text() + (src / "prompt.py").read_text() + (src / "doctor.py").read_text()
        for key in cs.PROVIDER_KEYS:
            self.assertIn(f'"{key}"', code, key)
        # and the reverse: every provider option the code reads is a schema key (prompt.py reads label; it was missing once and config check warned on a valid file)
        read = set(re.findall(r'(?:pconf|conf|p)\.get\("([a-z_]+)"', (src / "providers.py").read_text() + (src / "prompt.py").read_text()))
        read -= {"providers", "prompt", "orch", "template", "template_file", "agents", "name", "color_hint"}   # other sections' keys read by the same files
        self.assertEqual(sorted(read - set(cs.PROVIDER_KEYS)), [], "a provider option the code reads is not in PROVIDER_KEYS")


class Types(Base):
    def test_a_wrong_type_or_range_is_a_fail_and_the_default_applies(self):
        text = '[board]\nstale_minutes = "x"\n[chat]\nautopilot_every = 5\nidle_budget_usd = inf\n[redact]\nenabled = "no"\n'
        f = self.findings(text)
        self.assertEqual({x.where for x in f if x.level == "FAIL"}, {"board.stale_minutes", "chat.autopilot_every", "chat.idle_budget_usd", "redact.enabled"})
        self.assertIn("default 120 used", [x.fix for x in f if x.where == "board.stale_minutes"][0])
        cleaned, _ = cs.clean(tomlread.loads(text))
        self.assertEqual(cleaned["board"]["stale_minutes"], 120)
        self.assertEqual(cleaned["chat"]["autopilot_every"], 180)
        self.assertEqual(cleaned["chat"]["idle_budget_usd"], 0.05)
        self.assertIs(cleaned["redact"]["enabled"], True)   # "no" is not false: masking stays on

    def test_the_board_runs_on_the_cleaned_config(self):
        self.conf('[board]\nstale_minutes = "x"\nowner = 12\n[ui]\ndispatch = "false"\n[unknown]\nx = 1\n[chat]\nnothing_here = 1\n')
        conf = promptlib.load_config(self.board)
        self.assertEqual(hud.stale_minutes(conf), 120)
        self.assertEqual(conf["board"]["owner"], "you")
        self.assertIs(conf["ui"]["dispatch"], True)
        self.assertEqual(conf["unknown"], {"x": 1})           # kept: a plugin may read it
        self.assertEqual(conf["chat"]["nothing_here"], 1)      # kept, reported by check
        self.assertEqual(promptlib.load_config(self.board, raw=True)["board"]["stale_minutes"], "x")

    def test_choices_and_bools_as_strings(self):
        f = self.findings('[providers.docs]\ntype = "markdwn"\npath = "CLAUDE.md"\n')
        self.assertEqual([(x.level, x.where) for x in f], [("FAIL", "providers.docs.type")])
        self.assertIn("markdown", f[0].fix)
        self.assertEqual(self.levels('[notify]\nenabled = "true"\n'), [("FAIL", "notify.enabled")])
        self.assertEqual(self.levels('[chat]\nautopilot_every = true\n'), [("FAIL", "chat.autopilot_every")])   # a bool is not an int here

    def test_roster_and_colours(self):
        self.assertEqual(self.levels('[orch]\nagents = [{name = "AGENT-1"}, {name = "AGENT-2", color = "#2563eb"}]\n'), [])
        self.assertEqual(self.levels('[orch]\nagents = [{nmae = "AGENT-1"}]\n'), [("WARN", "orch.agents[0].nmae")])
        self.assertEqual(self.levels('[agent_colors]\n"AGENT-1" = "#2563eb"\n"AGENT-2" = "tomato"\n'), [])
        self.assertEqual(self.levels('[agent_colors]\n"AGENT-1" = 3\n'), [("FAIL", "agent_colors.AGENT-1")])


class Unsafe(Base):
    def test_unsafe_switches_are_warnings_not_errors(self):
        f = self.findings('[redact]\nenabled = false\n[chat]\nautopilot = true\n[backup]\nsync_dir = "/tmp/x"\n[run]\nclaude = "/usr/local/bin/claude"\n')
        self.assertEqual({x.level for x in f}, {"WARN"})
        self.assertEqual({x.where for x in f}, {"redact.enabled", "chat.autopilot", "backup.sync_dir", "run.claude"})
        self.assertIn("masking is OFF", [x.text for x in f if x.where == "redact.enabled"][0])
        cleaned, _ = cs.clean(tomlread.loads('[redact]\nenabled = false\n'))
        self.assertIs(cleaned["redact"]["enabled"], False)   # allowed: the owner's choice, reported, not overridden

    def test_a_private_string_is_never_in_a_finding(self):
        f = self.findings('[backup]\nsync_dir = "/Volumes/secret-place/x"\n[board]\nowner = 7\n')
        self.assertNotIn("secret-place", " ".join(x.text + x.fix for x in f))


class Show(Base):
    def test_effective_says_where_each_value_came_from(self):
        eff = cs.effective(tomlread.loads('[board]\nowner = "Alex"\nstale_minutes = "x"\n'))
        self.assertEqual(eff["board"]["owner"], ("Alex", "file"))
        self.assertEqual(eff["board"]["stale_minutes"], (120, "default (file value invalid)"))
        self.assertEqual(eff["chat"]["autopilot_every"], (180, "default"))
        self.assertEqual(eff["providers"], {"(none)": ({}, "default")})

    def test_the_commands(self):
        self.conf('[board]\nowner = "Alex"\nstale_minute = 90\n[chat]\nautopilot_every = 1\n')
        def run(*argv):
            out = io.StringIO()
            with mock.patch.dict(os.environ, {"AGENTBOARD_DIR": str(self.board)}), contextlib.redirect_stdout(out):
                try:
                    cli.main(list(argv))
                    code = 0
                except SystemExit as e:
                    code = e.code
            return code, out.getvalue()
        code, text = run("config", "check")
        self.assertEqual(code, 1)
        self.assertIn("board.stale_minute", text)
        self.assertIn("did you mean 'stale_minutes'", text)
        self.assertIn("chat.autopilot_every", text)
        self.assertIn("1 invalid value(s)", text)
        code, text = run("config", "show")
        self.assertEqual(code, 0)
        self.assertRegex(text, r"board\.owner\s+Alex\s+file")
        self.assertRegex(text, r"chat\.autopilot_every\s+180\s+default \(file value invalid\)")
        self.assertIn("AGENTBOARD_LOCKDOWN", text)
        code, text = run("config", "docs")
        self.assertEqual(code, 0)
        self.assertTrue(text.startswith("# config.toml: every key"))
        self.conf('[board]\nowner = "Alex"\n')
        code, text = run("config", "check")
        self.assertEqual(code, 0)
        self.assertIn("every key is one the board reads", text)

    def test_show_prints_no_secret_path_or_number(self):
        """xr-config-show-prints-secrets: a [redact] extra pattern may be the secret itself, a [knowledge] path is private, a plugin's string may be a
        phone number. Only numbers, booleans and a few named strings are printed."""
        key = "AKIA" + "Q3J7F2KX9WPLM4ZT"
        cs.register("thing", {"number": cs.Field("str", meaning="a phone number"), "cap": cs.Field("int", 20, "a day")})
        self.conf(f'[redact]\nextra = ["{key}", "ACME-[0-9]{{6}}"]\n[knowledge]\nfiles = ["/Volumes/secret-place/notes.md"]\n[board]\nowner = "Alex"\n'
                  f'[backup]\nsync_dir = "/Volumes/secret-place/sync"\n[thing]\nnumber = "+1 416 555 0199"\ncap = 7\n[agent_colors]\n"AGENT-1" = "#2563eb"\n')
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"AGENTBOARD_DIR": str(self.board)}), contextlib.redirect_stdout(out):
            cli.main(["config", "show"])
        text = out.getvalue()
        for secret in (key, "ACME", "secret-place", "555 0199", "416"):
            self.assertNotIn(secret, text)
        self.assertRegex(text, r"redact\.extra\s+\(2 entries, not shown\)")
        self.assertRegex(text, r"knowledge\.files\s+\(1 entry, not shown\)")
        self.assertRegex(text, r"backup\.sync_dir\s+\(set, not shown\)")
        self.assertRegex(text, r"thing\.number\s+\(set, not shown\)")
        self.assertRegex(text, r"thing\.cap\s+7")
        self.assertRegex(text, r"board\.owner\s+Alex")
        self.assertRegex(text, r"agent_colors\.AGENT-1\s+#2563eb")
        self.assertEqual(cs.shown("prompt", "template", "x" * 10), "(set, not shown)")
        self.assertEqual(cs.shown("board", "owner", "a\nb"), "(set, not shown)")

    def test_an_invalid_value_with_no_default_is_kept_for_the_readers_own_message(self):
        cleaned, f = cs.clean(tomlread.loads('[providers.docs]\ntype = "markdwn"\npath = "CLAUDE.md"\n'))
        self.assertEqual(cleaned["providers"]["docs"]["type"], "markdwn")   # prompt.py says "unknown type markdwn", not None
        self.assertEqual([x.level for x in f], ["FAIL"])

    def test_the_docs_page_is_the_schema(self):
        self.assertEqual((ROOT / "docs" / "config.md").read_text(), cs.docs(), "docs/config.md is stale: run `agentboard config docs > docs/config.md`")
        page = cs.docs()
        for sect in cs.SCHEMA:
            self.assertIn(f"## `[{sect}]`", page)
        self.assertIn("`stale_minutes` | int 1..100000 | 120 |", page)


class Plugins(Base):
    def test_a_plugin_adds_its_section_and_a_core_one_is_refused(self):
        api = plugins.Api(plugins.Plugin("thing"))
        api.add_config("thing", {"on": cs.Field("bool", False, "switch"), "cap": cs.Field("int", 20, "a day", min=1, max=100)})
        with self.assertRaises(ValueError):
            api.add_config("board", {"x": cs.Field("int", 1)})
        with self.assertRaises(ValueError):
            api.add_config("other", {"x": "not a field"})
        self.assertEqual(self.levels('[thing]\non = true\ncap = 500\n'), [("FAIL", "thing.cap")])
        self.assertEqual(self.levels('[thing]\non = true\ncap = 50\n'), [])
        self.assertEqual(cs.effective(tomlread.loads('[thing]\ncap = 50\n'))["thing"], {"on": (False, "default"), "cap": (50, "file")})
        self.assertIn("## `[thing]` (plugin)", cs.plugin_docs())


class Doctor(Base):
    def test_doctor_carries_the_findings(self):
        from tests.test_doctor import FakeRunner
        self.conf('[board]\nstale_minute = 90\n[chat]\nautopilot_every = 1\n')
        with mock.patch("importlib.metadata.entry_points", return_value=[]), mock.patch.object(Path, "home", return_value=Path(self.tmp.name) / "home"):
            lines = [(l, n, t) for l, n, t in doctor.run(self.board, env={}, runner=FakeRunner()) if n == "schema"]
        self.assertEqual([l for l, _n, _t in lines], ["WARN", "FAIL"])
        self.assertIn("stale_minute", lines[0][2])
        self.conf('[board]\nowner = "Alex"\n')
        with mock.patch("importlib.metadata.entry_points", return_value=[]), mock.patch.object(Path, "home", return_value=Path(self.tmp.name) / "home"):
            lines = [(l, n, t) for l, n, t in doctor.run(self.board, env={}, runner=FakeRunner()) if n == "schema"]
        self.assertEqual([l for l, _n, _t in lines], ["PASS"])


class TheProfileKey(Base):
    """[board] profile is written by `agentboard init` on a managed PC and read by profile.py: doctor must know it (it warned "not a key the board reads"),
    and teaching the schema about it must never turn a mistyped value from a lock into a hole."""

    def test_the_key_init_writes_is_a_known_key(self):
        self.assertEqual(cs.validate(tomlread.loads('[board]\nprofile = "work"\n')), [])
        self.assertEqual(cs.validate(tomlread.loads('[board]\nprofile = "off"\n')), [])
        got = cs.validate(tomlread.loads('[board]\nprofil = "work"\n'))   # a real typo is still caught, with the closest name
        self.assertEqual([(f.level, f.where, f.fix) for f in got], [("WARN", "board.profil", "did you mean 'profile'?")])

    def test_doctor_has_no_schema_warning_for_a_board_init_made_on_a_managed_pc(self):
        from tests.test_doctor import FakeRunner
        self.conf('[board]\nprofile = "work"            # the work-PC profile\n')
        with mock.patch("importlib.metadata.entry_points", return_value=[]), mock.patch.object(Path, "home", return_value=Path(self.tmp.name) / "home"):
            lines = [(l, n, t) for l, n, t in doctor.run(self.board, env={}, runner=FakeRunner()) if n == "schema"]
        self.assertEqual([l for l, _n, _t in lines], ["PASS"])

    def test_a_mistyped_value_still_means_work_the_schema_never_cleans_it_away(self):
        from agentboard import profile
        env = {"HOME": str(Path(self.tmp.name) / "home"), "XDG_CONFIG_HOME": str(Path(self.tmp.name) / "xdg")}
        for raw in ('"work"', '"Work "', '"yes"', "true", "1", "5", '["x"]', '{ a = 1 }'):
            with self.subTest(profile=raw):
                self.conf(f"[board]\nprofile = {raw}\n")
                cleaned, _f = cs.clean(tomlread.loads(f"[board]\nprofile = {raw}\n"))
                self.assertEqual(cleaned["board"]["profile"], tomlread.loads(f"x = {raw}\n")["x"])   # kept as written: no default replaces it
                with mock.patch.dict(os.environ, env, clear=True):
                    profile._ENV0.update(seen=False, value=None)
                    self.assertEqual([w for w, _t in profile.sources(self.board)], ["board"])
        for raw in ('"off"', '"home"', '"no"', '"false"', '"0"', '""'):
            with self.subTest(profile=raw):
                self.conf(f"[board]\nprofile = {raw}\n")
                with mock.patch.dict(os.environ, env, clear=True):
                    profile._ENV0.update(seen=False, value=None)
                    self.assertEqual(profile.sources(self.board), [])


if __name__ == "__main__":
    unittest.main()
