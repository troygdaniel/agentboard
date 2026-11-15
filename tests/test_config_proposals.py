"""ORCH proposes a configuration change; the owner accepts or ignores it (card agent-config-slice-3b, docs/agent-configurations-design.md: a suggestion, never applied by itself).
`agentboard configuration propose|proposals|accept|ignore`, configproposals.py. A throwaway board; nothing reaches a real one."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from agentboard import cli, configproposals as cp, configurations as cfgs, prompt as promptlib, statefile
from agentboard.store import BoardError, Store

WHY = "5 of the last 9 cards were reviewed twice"


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
        (self.d / "config.toml").write_text('[board]\nowner = "Pat"\n\n[agents]\nconfigurations = true\n')
        os.environ["AGENTBOARD_DIR"] = str(self.d)
        cfgs.apply(self.d, cfgs.builtin("day-to-day"), "day-to-day")

    def add_name(self, name="Caller-2", role="caller", why=WHY, by="ORCH", **kw):
        return cp.propose(self.d, by, "add-name", {"role": role, "name": name}, why, "Pat", **kw)

    def run_cli(self, *argv, name=None):
        env = {"AGENTBOARD_NAME": name} if name else {}
        out = io.StringIO()
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            if not name:
                os.environ.pop("AGENTBOARD_NAME", None)
            try:
                code = cli.main(list(argv))
            except SystemExit as e:
                code = e.code
                if isinstance(code, str):
                    out.write(code)
        return code, out.getvalue()


class Propose(Base):
    def test_a_proposal_changes_nothing(self):
        before = (cfgs.applied(self.d), self.s.known_names())
        rec = self.add_name()
        self.assertEqual((rec["id"], rec["status"], rec["by"]), (1, "proposed", "ORCH"))
        self.assertEqual((cfgs.applied(self.d), self.s.known_names()), before)
        self.assertEqual(cp.pending(self.d)[0]["change"], {"role": "caller", "name": "Caller-2"})

    def test_only_orch_proposes(self):
        for who in (None, "", "Caller-1", "Pat"):
            with self.assertRaises(BoardError, msg=str(who)) as e:
                self.add_name(by=who)
            self.assertIn("only ORCH", str(e.exception))
        self.assertEqual(self.add_name(by="orch")["id"], 1)   # case does not matter

    def test_off_means_off(self):
        (self.d / "config.toml").write_text('[board]\nowner = "Pat"\n')
        with self.assertRaises(BoardError) as e:
            self.add_name()
        self.assertIn("are off", str(e.exception))

    def test_a_reason_is_needed_and_is_kept_short_and_clean(self):
        for why in ("", "   ", None):
            with self.assertRaises(BoardError):
                self.add_name(why=why)
        rec = self.add_name(why="x " * 300)
        self.assertLessEqual(len(rec["why"]), cp.WHY_MAX)
        rec = self.add_name(name="Caller-3", why="line one\nline two   spaced")
        self.assertEqual(rec["why"], "line one line two spaced")   # one line

    def test_refusals_for_a_change_that_cannot_work(self):
        for role, name, word in (("nobody", "Caller-2", "no role named"), ("caller", "Caller-1", "also the name of caller"), ("caller", "caller-1", "also the name of caller"),
                                 ("caller", "Bills-1", "Bills-1 is also the name of"), ("caller", "ORCH", "keeps for itself"), ("caller", "Pat", "keeps for itself"),
                                 ("caller", 'Ba"d', "the new name is 1 to 40"), ("caller", "", "the new name is 1 to 40")):
            with self.assertRaises(BoardError, msg=f"{role} {name}") as e:
                self.add_name(name=name, role=role)
            self.assertIn(word, str(e.exception), f"{role} {name}")
        self.assertEqual(cp.read(self.d), [])

    def test_a_name_a_card_holder_already_has_is_refused(self):
        self.s.add("x", task_id="x1")
        self.s.claim("x1", "Scout")
        with self.assertRaises(BoardError):
            self.add_name(name="Scout")

    def test_a_role_that_is_full_is_refused(self):
        for i in range(2, 9):
            self.add_name(name=f"Caller-{i}", why=f"{WHY} {i}")
            cp.accept(self.d, i - 1, "Pat")
        with self.assertRaises(BoardError) as e:
            self.add_name(name="Caller-9")
        self.assertIn("more than 8 names", str(e.exception))

    def test_no_configuration_applied_means_nothing_to_add_to(self):
        cfgs.clear(self.d)
        with self.assertRaises(BoardError) as e:
            self.add_name()
        self.assertIn("no configuration is applied", str(e.exception))

    def test_apply_kind(self):
        with self.assertRaises(BoardError) as e:
            cp.propose(self.d, "ORCH", "apply", {"configuration": "day-to-day"}, WHY, "Pat")
        self.assertIn("already applied", str(e.exception))
        with self.assertRaises(BoardError) as e:
            cp.propose(self.d, "ORCH", "apply", {"configuration": "nope"}, WHY, "Pat")
        self.assertIn("day-to-day", str(e.exception))   # says what ships
        cfgs.clear(self.d)
        rec = cp.propose(self.d, "ORCH", "apply", {"configuration": "Day to day"}, WHY, "Pat")
        self.assertEqual(rec["change"], {"configuration": "day-to-day"})
        with self.assertRaises(BoardError):
            cp.propose(self.d, "ORCH", "bogus", {}, WHY, "Pat")

    def test_the_same_change_is_not_asked_twice_while_it_waits(self):
        self.add_name()
        with self.assertRaises(BoardError) as e:
            self.add_name(name="CALLER-2")
        self.assertIn("already proposed (#1)", str(e.exception))
        self.assertEqual(self.add_name(name="Caller-3")["id"], 2)   # a different change is fine

    def test_ids_count_up_and_only_the_last_50_are_kept(self):
        for i in range(60):
            statefile.update(cp.path(self.d), lambda d, i=i: (d if isinstance(d, list) else []) + [{"id": i + 1, "at": "2026-11-14T10:00:00", "by": "ORCH", "kind": "apply", "change": {"configuration": f"k{i}"}, "why": "w", "status": "ignored", "decided_at": "2020-01-01T00:00:00"}], default=[])
        rec = self.add_name()
        self.assertEqual(rec["id"], 61)
        self.assertEqual(len(cp.read(self.d)), cp.MAX_KEPT)

    def test_a_damaged_file_is_skipped(self):
        cp.path(self.d).write_text(json.dumps([{"id": "x"}, 5, {"id": 1, "kind": "zzz", "status": "proposed", "change": {}}]))
        self.assertEqual(cp.read(self.d), [])
        self.assertEqual(self.add_name()["id"], 2)   # past the id the damaged line carried
        cp.path(self.d).write_text("{nope")
        self.assertEqual(cp.read(self.d), [])


class Decide(Base):
    def test_accept_adds_the_name_to_the_role_and_the_roster(self):
        self.add_name()
        rec, cfg = cp.accept(self.d, 1, "Pat")
        self.assertEqual(rec["status"], "accepted")
        caller = next(r for r in cfg["roles"] if r["role"] == "caller")
        self.assertEqual((caller["names"], caller["count"]), (["Caller-1", "Caller-2"], 2))
        self.assertEqual(cfgs.applied(self.d), cfg)
        self.assertIn("Caller-2", self.s.known_names())
        self.assertEqual(cfgs.role_of(cfg, "caller-2")["role"], "caller")
        self.assertIn("+ Caller-2", json.loads((self.d / cfgs.FILE).read_text())["source"])
        self.assertEqual(cp.read(self.d)[0]["status"], "accepted")
        self.assertTrue(cp.read(self.d)[0]["decided_at"])

    def test_accept_switches_the_configuration(self):
        cfgs.clear(self.d)
        cp.propose(self.d, "ORCH", "apply", {"configuration": "day-to-day"}, WHY, "Pat")
        rec, cfg = cp.accept(self.d, 1, "Pat")
        self.assertEqual(cfgs.applied(self.d)["name"], "Day to day")

    def test_only_the_owner_accepts_or_ignores(self):
        self.add_name()
        for who in ("ORCH", "Caller-1", "orch"):
            for fn in (cp.accept, cp.ignore):
                with self.assertRaises(BoardError, msg=f"{who} {fn.__name__}") as e:
                    fn(self.d, 1, "Pat", who)
                self.assertIn("owner's word", str(e.exception))
        self.assertEqual(cp.pending(self.d)[0]["id"], 1)   # still waiting
        cp.ignore(self.d, 1, "Pat", "Pat")   # the owner by name is fine, and so is no name at all
        self.add_name(name="Caller-3")
        cp.accept(self.d, 2, "Pat", None)

    def test_a_decided_one_cannot_be_decided_again(self):
        self.add_name()
        cp.ignore(self.d, 1, "Pat")
        for fn in (cp.accept, cp.ignore):
            with self.assertRaises(BoardError) as e:
                fn(self.d, 1, "Pat")
            self.assertIn("already ignored", str(e.exception))
        for bad in ("x", None, 99):
            with self.assertRaises(BoardError):
                cp.accept(self.d, bad, "Pat")

    def test_an_ignored_proposal_is_not_repeated_for_a_week(self):
        t0 = datetime(2026, 11, 14, 10, 0)
        self.add_name(now=t0)
        cp.ignore(self.d, 1, "Pat", now=t0)
        with self.assertRaises(BoardError) as e:
            self.add_name(now=t0 + timedelta(days=3))
        self.assertIn("ignored this on 2026-11-14", str(e.exception))
        self.assertEqual(self.add_name(now=t0 + timedelta(days=8))["id"], 2)

    def test_accept_is_refused_if_the_ground_moved(self):
        self.add_name()
        self.s.add("x", task_id="x1")
        self.s.claim("x1", "Caller-2")   # an agent took the name meanwhile
        with self.assertRaises(BoardError) as e:
            cp.accept(self.d, 1, "Pat")
        self.assertIn("has become a name", str(e.exception))
        self.assertEqual(cp.pending(self.d)[0]["status"], "proposed")   # nothing applied, nothing marked
        self.assertEqual(next(r for r in cfgs.applied(self.d)["roles"] if r["role"] == "caller")["names"], ["Caller-1"])
        cfgs.clear(self.d)
        self.s.add("y", task_id="y1")
        with self.assertRaises(BoardError):
            cp.accept(self.d, 1, "Pat")

    def test_off_means_off_for_accept_too(self):
        self.add_name()
        (self.d / "config.toml").write_text('[board]\nowner = "Pat"\n')
        with self.assertRaises(BoardError):
            cp.accept(self.d, 1, "Pat")


class TheOrchPrompt(Base):
    def test_it_says_how_and_that_it_is_a_suggestion(self):
        text = promptlib.build_orch_prompt([], self.d)
        self.assertIn("configuration propose --add-name QA-2 --role qa", text)
        self.assertIn("Never apply one yourself", text)

    def test_it_lists_what_waits_and_what_was_ignored(self):
        self.add_name()
        self.add_name(name="Caller-3")
        cp.ignore(self.d, 2, "Pat")
        text = promptlib.build_orch_prompt([], self.d)
        self.assertIn("Waiting for", text)
        self.assertIn("#1 Add Caller-2 to the caller role", text)
        self.assertIn("Ignored lately, do not repeat: #2 Add Caller-3", text)

    def test_with_the_setting_off_the_prompt_says_nothing_of_it(self):
        (self.d / "config.toml").write_text('[board]\nowner = "Pat"\n')
        self.assertNotIn("configuration propose", promptlib.build_orch_prompt([], self.d))


class CommandLine(Base):
    def test_the_whole_conversation(self):
        code, out = self.run_cli("configuration", "propose", "--add-name", "Caller-2", "--role", "caller", "--why", WHY, name="ORCH")
        self.assertFalse(code, out)
        self.assertIn("Proposed #1: Add Caller-2 to the caller role", out)
        self.assertIn("Nothing has changed. Pat accepts or ignores it", out)
        code, out = self.run_cli("configuration", "proposals")
        self.assertIn("#1  proposed  Add Caller-2 to the caller role", out)
        code, out = self.run_cli("configuration", "accept", "1", name="ORCH")
        self.assertIn("owner's word", out)
        code, out = self.run_cli("configuration", "accept", "1")
        self.assertIn("Accepted #1", out)
        self.assertIn("/rename Caller-2", out)
        code, out = self.run_cli("configuration", "propose", "--add-name", "Caller-3", "--role", "caller", "--why", WHY, name="ORCH")
        code, out = self.run_cli("configuration", "ignore", "2")
        self.assertIn("Ignored #2", out)
        self.assertIn("7 days", out)
        code, out = self.run_cli("configuration", "proposals")
        self.assertIn("accepted", out)
        self.assertIn("ignored", out)

    def test_apply_proposal_and_its_flags(self):
        cfgs.clear(self.d)
        code, out = self.run_cli("configuration", "propose", "--apply", "day-to-day", "--why", WHY, name="ORCH")
        self.assertIn("Switch to the day-to-day configuration", out)
        code, out = self.run_cli("configuration", "accept", "1")
        self.assertIn("Applied: Day to day", out)
        code, out = self.run_cli("configuration", "propose", name="ORCH")
        self.assertIn("propose one change", out)
        code, out = self.run_cli("configuration", "propose", "--apply", "x", "--add-name", "y", "--why", "z", name="ORCH")
        self.assertIn("propose one change", out)
        code, out = self.run_cli("configuration", "proposals")
        self.assertIn("accepted", out)

    def test_no_proposals_yet(self):
        code, out = self.run_cli("configuration", "proposals")
        self.assertIn("No proposals", out)


class Export(Base):
    def test_export_prints_a_file_that_validates_and_round_trips(self):
        code, out = self.run_cli("configuration", "export")
        self.assertFalse(code, out)
        d = json.loads(out)
        self.assertEqual(set(d), {"configuration", "name", "description", "roles"})   # the validated fields only
        self.assertEqual(cfgs.loads(out), cfgs.applied(self.d))
        code, out = self.run_cli("configuration", "export", "build")
        self.assertEqual(json.loads(out)["name"], "Build or improve an application")

    def test_export_reflects_an_accepted_proposal(self):
        self.add_name()
        cp.accept(self.d, 1, "Pat")
        code, out = self.run_cli("configuration", "export")
        caller = next(r for r in json.loads(out)["roles"] if r["role"] == "caller")
        self.assertEqual(caller["names"], ["Caller-1", "Caller-2"])

    def test_export_to_a_file_never_overwrites(self):
        target = self.d.parent / "mine.json"
        code, out = self.run_cli("configuration", "export", "-o", str(target))
        self.assertIn("Wrote Day to day", out)
        self.assertEqual(cfgs.loads(target.read_text())["name"], "Day to day")
        code, out = self.run_cli("configuration", "export", "-o", str(target))
        self.assertIn("already exists", out)
        self.assertEqual(cfgs.loads(target.read_text())["name"], "Day to day")   # untouched
        code, out = self.run_cli("configuration", "export", "build", "-o", str(self.d.parent / "no-such-folder" / "x.json"))
        self.assertIn("cannot write", out)

    def test_an_exported_file_can_be_shown_and_applied_back(self):
        target = self.d.parent / "team.json"
        self.run_cli("configuration", "export", "-o", str(target))
        cfgs.clear(self.d)
        code, out = self.run_cli("configuration", "show", str(target))
        self.assertIn("Configuration: Day to day", out)
        self.assertIsNone(cfgs.applied(self.d))   # show applies nothing
        code, out = self.run_cli("configuration", "apply", str(target))
        self.assertIn("Applied: Day to day", out)

    def test_nothing_applied_and_no_name_says_what_to_do(self):
        cfgs.clear(self.d)
        code, out = self.run_cli("configuration", "export")
        self.assertIn("no configuration is applied", out)
        self.assertIn("day-to-day", out)


if __name__ == "__main__":
    unittest.main()
