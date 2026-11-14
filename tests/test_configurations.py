"""Agent configurations (card agent-config-slice-2, docs/agent-configurations-design.md): the file and its validator, the shipped Day to day configuration, the setting
that gates it, `agentboard configuration show|apply|clear`, and what an applied configuration changes (the roster, the ORCH prompt, a card prompt, what an agent reads when
it claims). A throwaway board; nothing reaches a real one. The role chips on the page are checked in headless Chrome by tests/qa/roles_check.mjs."""
import contextlib
import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentboard import cli, configurations as cfgs, hud, prompt as promptlib, statefile
from agentboard.store import BoardError, Store

GOOD = {"configuration": 1, "name": "Test team", "description": "d",
        "roles": [{"role": "writer", "names": ["Writer-1", "Writer-2"], "purpose": "writes", "model": "sonnet", "size": "M", "may": ["draft"],
                   "may_not": ["place a call", "pay"], "tools": ["board"], "count": 2},
                  {"role": "checker", "names": ["Checker-1"], "purpose": "checks", "may": [], "may_not": [], "tools": []}]}


def bad(**change):
    d = json.loads(json.dumps(GOOD))
    d.update(change)
    return d


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name).resolve()
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        env["AGENTBOARD_HOME"] = str(root / "home")
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        self.s = Store(root / "proj" / ".agentboard")
        self.d = self.s.dir
        self.d.mkdir(parents=True, exist_ok=True)
        os.environ["AGENTBOARD_DIR"] = str(self.d)

    def conf(self, text):
        (self.d / "config.toml").write_text(text)

    def on(self):
        self.conf('[board]\nowner = "Pat"\n\n[agents]\nconfigurations = true\n')

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                code = cli.main(list(argv))
            except SystemExit as e:
                code = e.code
                if isinstance(code, str):
                    out.write(code)
        return code, out.getvalue()


class TheFile(Base):
    def test_a_good_file_is_kept_whole(self):
        cfg = cfgs.validate(GOOD)
        self.assertEqual([r["role"] for r in cfg["roles"]], ["writer", "checker"])
        self.assertEqual(cfgs.roster(cfg), ["Writer-1", "Writer-2", "Checker-1"])
        self.assertEqual(cfg["roles"][1]["count"], 1)   # derived from the names

    def test_what_the_board_keeps_is_itself_a_valid_file(self):
        once = cfgs.validate(GOOD)
        self.assertEqual(cfgs.validate(once), once)   # the applied copy is validated again on every read
        shipped = cfgs.builtin("day-to-day")
        self.assertEqual(cfgs.validate(shipped), shipped)

    def test_every_fault_is_named(self):
        for change, word in ((dict(configuration=2), "configuration must be 1"), (dict(name=""), "name is missing"), (dict(extra=1), "unknown key"), (dict(roles=[]), "at least one role"),
                             (dict(roles="x"), "at least one role")):
            with self.assertRaises(cfgs.ConfigurationError, msg=str(change)) as e:
                cfgs.validate(bad(**change))
            self.assertIn(word, str(e.exception))

    def test_role_faults(self):
        def role(**r):
            d = json.loads(json.dumps(GOOD))
            d["roles"][0].update(r)
            return d
        for r, word in ((dict(names=[]), "at least one name"), (dict(names=["ORCH"]), "keeps for itself"), (dict(names=["Pat"]), "keeps for itself"),
                        (dict(names=["Writer-1", "writer-1"]), "also the name"), (dict(names=['Ba"d']), "is not a name"), (dict(count=5), "count must equal"),
                        (dict(size="XL"), "S, M or L"), (dict(model="has space"), "short name"), (dict(zip=1), "unknown key"), (dict(may="x"), "must be a list"),
                        (dict(purpose="a\nb"), "one line"), (dict(may=["x"] * 13), "more than 12")):
            with self.assertRaises(cfgs.ConfigurationError, msg=str(r)) as e:
                cfgs.validate(role(**r), owner="Pat")
            self.assertIn(word, str(e.exception), str(r))

    def test_a_name_in_two_roles_and_a_role_twice(self):
        d = json.loads(json.dumps(GOOD))
        d["roles"][1]["names"] = ["Writer-1"]
        with self.assertRaises(cfgs.ConfigurationError) as e:
            cfgs.validate(d)
        self.assertIn("also the name of writer", str(e.exception))
        d = json.loads(json.dumps(GOOD))
        d["roles"][1]["role"] = "Writer"
        with self.assertRaises(cfgs.ConfigurationError) as e:
            cfgs.validate(d)
        self.assertIn("listed twice", str(e.exception))

    def test_not_json_and_not_an_object(self):
        for text in ("{nope", "[]", "3"):
            with self.assertRaises(cfgs.ConfigurationError):
                cfgs.loads(text)

    def test_many_faults_are_summarised(self):
        d = bad(extra=1, name="", configuration=9)
        d["roles"][0].update(size="Z", count=9, zip=1, model="a b")
        with self.assertRaises(cfgs.ConfigurationError) as e:
            cfgs.validate(d)
        self.assertIn("(and ", str(e.exception))


class TheShippedConfiguration(Base):
    def test_day_to_day_is_valid_and_keeps_every_outside_action_for_the_owner(self):
        cfg = cfgs.builtin("day-to-day")
        self.assertEqual(cfg["name"], "Day to day")
        self.assertEqual([r["role"] for r in cfg["roles"]], ["caller", "bills", "forms", "research", "planner", "family"])
        for r in cfg["roles"]:
            for action in cfgs.OUTSIDE_ACTIONS:
                self.assertIn(action, r["may_not"], f"{r['role']} may not {action}")
            self.assertNotIn("pay", r["may"])
            self.assertTrue(r["purpose"])

    def test_the_shipped_files_name_no_person_number_or_address(self):
        for f in cfgs.BUILTIN_DIR.glob("*.json"):
            text = f.read_text()
            self.assertIsNone(re.search(r"[\w.+-]+@[\w-]+\.\w+|\b\d{3}[-. ]\d{3}[-. ]\d{4}\b|https?://", text), f.name)

    def test_the_name_may_be_spelled_loosely(self):
        self.assertEqual(cfgs.builtin("Day to day")["name"], "Day to day")
        with self.assertRaises(cfgs.ConfigurationError):
            cfgs.builtin("nope")

    def test_the_file_ships_in_the_package(self):
        self.assertIn("configurations/*.json", (Path(cfgs.__file__).parents[2] / "pyproject.toml").read_text())


class TheSettingAndTheCommand(Base):
    def test_off_by_default_and_the_command_says_how_to_turn_it_on(self):
        self.assertFalse(cfgs.enabled(self.d))
        code, out = self.run_cli("configuration")
        self.assertIn("[agents] configurations = true", out)
        code, out = self.run_cli("configuration", "apply", "day-to-day")
        self.assertIn("are off", out)
        self.assertFalse((self.d / cfgs.FILE).exists())

    def test_show_apply_and_clear(self):
        self.on()
        code, out = self.run_cli("configuration")
        self.assertIn("No configuration is applied", out)
        self.assertIn("day-to-day", out)
        code, out = self.run_cli("configuration", "show", "day-to-day")
        self.assertIn("Configuration: Day to day", out)
        self.assertFalse((self.d / cfgs.FILE).exists())   # show applies nothing
        code, out = self.run_cli("configuration", "apply", "day-to-day")
        self.assertIn("Applied: Day to day", out)
        self.assertIn("The board starts nothing", out)
        self.assertIn("Caller-1 (caller): /rename Caller-1   then   export AGENTBOARD_NAME=Caller-1", out)
        self.assertIn("tools to leave enabled in that terminal: read-only web, board", out)
        self.assertEqual(cfgs.applied(self.d)["name"], "Day to day")
        code, out = self.run_cli("configuration")
        self.assertIn("Configuration: Day to day (applied)", out)
        code, out = self.run_cli("configuration", "clear")
        self.assertIn("Removed", out)
        self.assertIsNone(cfgs.applied(self.d))
        code, out = self.run_cli("configuration", "clear")
        self.assertIn("No configuration is applied", out)

    def test_apply_a_file_and_refuse_a_bad_one(self):
        self.on()
        good = self.d.parent / "team.json"
        good.write_text(json.dumps(GOOD))
        code, out = self.run_cli("configuration", "apply", str(good))
        self.assertIn("Applied: Test team (team.json)", out)
        badf = self.d.parent / "bad.json"
        badf.write_text(json.dumps(bad(extra=1)))
        code, out = self.run_cli("configuration", "apply", str(badf))
        self.assertIn("unknown key", out)
        self.assertEqual(cfgs.applied(self.d)["name"], "Test team")   # the bad one changed nothing
        huge = self.d.parent / "huge.json"
        huge.write_text(" " * 70_000)
        code, out = self.run_cli("configuration", "apply", str(huge))
        self.assertIn("over 64 KB", out)
        code, out = self.run_cli("configuration", "apply", str(self.d.parent / "missing.json"))
        self.assertIn("cannot read", out)

    def test_a_hand_edited_applied_copy_is_not_trusted(self):
        self.on()
        self.run_cli("configuration", "apply", "day-to-day")
        d = json.loads((self.d / cfgs.FILE).read_text())
        d["configuration"]["roles"][0]["names"] = ["ORCH"]
        statefile.write(self.d / cfgs.FILE, d)
        self.assertIsNone(cfgs.applied(self.d))

    def test_turned_off_again_the_applied_one_is_ignored_not_deleted(self):
        self.on()
        self.run_cli("configuration", "apply", "day-to-day")
        self.conf('[board]\nowner = "Pat"\n')
        self.assertIsNone(cfgs.applied_if_enabled(self.d))
        self.assertTrue((self.d / cfgs.FILE).exists())

    def test_the_setting_is_in_the_schema_and_the_docs(self):
        from agentboard import configschema
        self.assertIn("configurations", configschema.SCHEMA["agents"])
        self.assertIn("[agents]", (Path(cfgs.__file__).parents[2] / "docs" / "config.md").read_text())


class WhatAnAppliedConfigurationChanges(Base):
    def setUp(self):
        super().setUp()
        self.on()
        self.run_cli("configuration", "apply", "day-to-day")

    def test_the_roster_includes_the_names_and_keeps_the_listed_ones_first(self):
        self.conf('[board]\nowner = "Pat"\n[agents]\nconfigurations = true\n[orch]\nagents = [{name = "Wren"}, {name = "caller-1"}]\n')
        self.assertEqual(cfgs.merge(["Wren", "caller-1"], self.d)[:2], ["Wren", "caller-1"])
        self.assertEqual(len(cfgs.merge(["Wren", "caller-1"], self.d)), 7)   # caller-1 is not added twice
        self.assertEqual(hud.roster(promptlib.load_config(self.d)), ["Wren", "caller-1"])   # the autopilot's roster is the listed one only

    def test_a_line_can_be_sent_to_a_configured_agent_before_it_speaks(self):
        self.assertIn("Bills-1", self.s.known_names())

    def test_the_orch_prompt_lists_the_roles_and_the_rule(self):
        text = promptlib.build_orch_prompt([], self.d)
        self.assertIn("- Caller-1 (caller)", text)
        self.assertIn("Configuration: Day to day", text)
        self.assertIn("proposed to", text)
        self.assertIn("lapses after 30 minutes", text)

    def test_without_the_setting_the_orch_prompt_is_as_it_was(self):
        self.conf('[board]\nowner = "Pat"\n')
        text = promptlib.build_orch_prompt([], self.d)
        self.assertNotIn("Caller-1", text)
        self.assertNotIn("Configuration:", text)

    def test_a_card_held_by_a_configured_agent_gets_its_role_block(self):
        self.s.add("Book a table", task_id="t1")
        self.s.claim("t1", "Caller-1")
        text, _ = promptlib.build_prompt(Store.get(self.s.load(), "t1"), self.d, tasks=self.s.load())
        self.assertIn("## Your role: caller (Day to day)", text)
        self.assertIn("You may not, on your own: place a call; send a message; pay; submit a form", text)
        self.assertIn("lapses after 30 minutes", text)

    def test_an_agent_with_no_role_and_an_unclaimed_card_get_the_prompt_as_it_was(self):
        self.s.add("Plain", task_id="t2")
        text, _ = promptlib.build_prompt(Store.get(self.s.load(), "t2"), self.d, tasks=self.s.load())
        self.assertNotIn("Your role", text)
        self.s.claim("t2", "Someone")
        text, _ = promptlib.build_prompt(Store.get(self.s.load(), "t2"), self.d, tasks=self.s.load())
        self.assertNotIn("Your role", text)

    def test_claiming_prints_the_role_and_starting_prints_it_on_stderr(self):
        self.s.add("Book a table", task_id="t1")
        code, out = self.run_cli("claim", "t1", "--name", "Caller-1")
        self.assertIn("claimed t1 as Caller-1", out)
        self.assertIn("## Your role: caller", out)
        code, out = self.run_cli("start", "Another job", "--name", "Research-1")
        self.assertIn("## Your role: research", out)
        code, out = self.run_cli("start", "Third job", "--name", "Someone-Else")
        self.assertNotIn("Your role", out)

    def test_a_configured_name_cannot_be_taken_by_a_rename(self):
        self.s.add("x", task_id="x1")
        self.s.claim("x1", "Scout")
        from agentboard import rename
        with self.assertRaises(BoardError) as e:
            rename.apply(self.s, "Scout", "Bills-1")
        self.assertIn("already on this board", str(e.exception))

    def test_the_role_chips_data_is_lowercased_and_empty_without_one(self):
        cfg = cfgs.applied_if_enabled(self.d)
        roles = cfgs.roles_by_name(cfg)
        self.assertEqual(roles["Caller-1"]["role"], "caller")
        self.conf('[board]\nowner = "Pat"\n')
        self.assertIsNone(cfgs.applied_if_enabled(self.d))


if __name__ == "__main__":
    unittest.main()
