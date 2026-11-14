"""Rename an agent (card agentboard-rename-agent, docs/agent-configurations-design.md): `agentboard rename OLD NEW` and the alias that keeps the old name working.

A throwaway board; nothing reaches a real one. What is pinned: every place a name lives moves (cards, log fields, chat, archive, the five state files, the roster
and the colour in config.toml), the words of a line do not, the alias is written first so a half-done rename can be finished by running it again, the old name
keeps working at the command line for a day and no longer after, --dry-run writes nothing, --undo puts it all back, and the refusals (a taken name, the reserved
names, the owner's name, a bad character, a name nobody has)."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from agentboard import cli, cursors, listeners, names, rename
from agentboard.store import BoardError, Store

CONFIG = '[board]\nowner = "Pat"\n\n[orch]\nagents = [\n  {name = "Scout", color = "green"},\n  {name = "Wren", color = "blue"},\n]\n'


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
        os.environ["AGENTBOARD_DIR"] = str(self.d)
        self.d.mkdir(parents=True, exist_ok=True)
        (self.d / "config.toml").write_text(CONFIG)

    def seed(self):
        """Scout holds one open card and one done card, wrote a chat line and was written to; Wren holds a card that mentions Scout in words."""
        s = self.s
        s.add("Open card", task_id="open1")
        s.claim("open1", "Scout")
        s.add("Shipped card", task_id="done1")
        s.claim("done1", "Scout")
        s.update("done1", 100, "all done")
        s.move("done1", "done")
        s.add("Wren card", task_id="wren1")
        s.claim("wren1", "Wren")
        s.update("wren1", 30, "waiting on Scout's branch")
        s.chat_send("Scout", "scout checking in", kind="agent")
        s.chat_send("Pat", "Scout, how is it going?", kind="user", to="Scout")
        s.chat_send("Wren", "Scout's card is the one to read", kind="agent")
        cursors.advance(self.d, "Scout", 2)
        cursors.deliver(self.d, "Scout", 3)
        listeners.register(self.d, "Scout", "inbox", pid=os.getpid())
        (self.d / "sessions.json").write_text(json.dumps({"sid-1": {"name": "Scout", "at": "2026-11-14T10:00:00"}, "sid-2": {"name": "Wren", "at": "2026-11-14T10:00:00"}}))
        (self.d / "chat-autopilot.json").write_text(json.dumps({"hour": "2026-11-14T10", "count": 1, "shared": {"Scout": "2026-11-14T10:00:00"}, "seen": {"scout": 3}}))

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                code = cli.main(list(argv))
            except SystemExit as e:
                code = e.code
                if isinstance(code, str):   # `agentboard: <the refusal>` is what the shell would have shown
                    out.write(code)
        return code, out.getvalue()

    def card(self, cid):
        return next(t for t in self.s.load_all() if t["id"] == cid)

    def snapshot(self):
        return {p.name: p.read_bytes() for p in self.d.iterdir() if p.is_file() and not p.name.endswith((".lock", ".bak"))}


class Aliases(Base):
    def test_resolves_the_old_name_and_leaves_others(self):
        names.add(self.d, "Scout", "Ives")
        self.assertEqual(names.resolve(self.d, "Scout"), "Ives")
        self.assertEqual(names.resolve(self.d, "scout"), "Ives")   # case does not matter
        self.assertEqual(names.resolve(self.d, "Wren"), "Wren")
        self.assertEqual(names.resolve(self.d, ""), "")

    def test_a_chain_is_followed_and_flattened(self):
        names.add(self.d, "Scout", "Ives")
        names.add(self.d, "Ives", "Wren2")
        self.assertEqual(names.resolve(self.d, "Scout"), "Wren2")
        self.assertEqual(json.loads((self.d / names.FILE).read_text())["scout"]["to"], "Wren2")   # the old link was moved to the newest name

    def test_renaming_back_makes_the_name_live_again(self):
        names.add(self.d, "Scout", "Ives")
        names.add(self.d, "Ives", "Scout")
        self.assertEqual(names.resolve(self.d, "Scout"), "Scout")
        self.assertEqual(names.resolve(self.d, "Ives"), "Scout")

    def test_a_loop_stops(self):
        (self.d / names.FILE).write_text(json.dumps({"a": {"from": "a", "to": "b", "at": "2026-11-14T10:00:00"}, "b": {"from": "b", "to": "a", "at": "2026-11-14T10:00:00"}}))
        self.assertIn(names.resolve(self.d, "a", now=datetime(2026, 11, 14, 11, 0)), ("a", "b"))   # it returns, whatever it lands on

    def test_an_alias_dies_a_day_after_its_last_use(self):
        t0 = datetime(2026, 11, 14, 10, 0)
        names.add(self.d, "Scout", "Ives", now=t0)
        self.assertEqual(names.resolve(self.d, "Scout", now=t0 + timedelta(hours=23)), "Ives")   # used: the day starts again from here
        self.assertEqual(names.resolve(self.d, "Scout", now=t0 + timedelta(hours=23 + 23)), "Ives")
        self.assertEqual(names.resolve(self.d, "Scout", now=t0 + timedelta(hours=23 + 23 + 25)), "Scout")   # unused for more than a day: gone

    def test_use_is_noted_at_most_every_ten_minutes(self):
        t0 = datetime(2026, 11, 14, 10, 0)
        names.add(self.d, "Scout", "Ives", now=t0)
        names.resolve(self.d, "Scout", now=t0 + timedelta(minutes=3))
        self.assertEqual(json.loads((self.d / names.FILE).read_text())["scout"]["used"], "2026-11-14T10:00:00")
        names.resolve(self.d, "Scout", now=t0 + timedelta(minutes=12))
        self.assertEqual(json.loads((self.d / names.FILE).read_text())["scout"]["used"], "2026-11-14T10:12:00")

    def test_a_damaged_file_is_ignored(self):
        (self.d / names.FILE).write_text("{not json")
        self.assertEqual(names.resolve(self.d, "Scout"), "Scout")
        (self.d / names.FILE).write_text(json.dumps({"scout": "Ives", "x": {"to": 5}}))
        self.assertEqual(names.resolve(self.d, "Scout"), "Scout")

    def test_the_palette_slot_has_not_moved(self):
        self.assertEqual([names.agent_slot(f"AGENT-{n}") for n in (1, 2, 3, 4)], [1, 2, 3, 4])
        self.assertEqual((names.agent_slot("GENERAL"), names.agent_slot("ORCH")), (5, 6))


class Rename(Base):
    def test_everything_a_name_touches_moves(self):
        self.seed()
        p = rename.apply(self.s, "Scout", "Ives")
        self.assertEqual((p["cards"], p["open"]), (2, 1))
        self.assertEqual({self.card(c)["agent"] for c in ("open1", "done1")}, {"Ives"})
        self.assertEqual(self.card("wren1")["agent"], "Wren")
        chat = self.s._read()["chat"]
        self.assertEqual([m["sender"] for m in chat], ["Ives", "Pat", "Wren"])
        self.assertEqual(chat[1]["to"], "Ives")
        self.assertEqual(cursors.read(self.d), {"ives": 2})
        self.assertEqual(list(cursors.read_delivered(self.d)), ["ives"])
        self.assertEqual(list(listeners._read(self.d)), ["Ives"])
        self.assertEqual({r["name"] for r in json.loads((self.d / "sessions.json").read_text()).values()}, {"Ives", "Wren"})
        auto = json.loads((self.d / "chat-autopilot.json").read_text())
        self.assertEqual((list(auto["shared"]), list(auto["seen"])), (["Ives"], ["ives"]))

    def test_words_are_history_and_stay(self):
        self.seed()
        rename.apply(self.s, "Scout", "Ives")
        self.assertEqual(self.card("wren1")["status_text"], "waiting on Scout's branch")
        self.assertEqual(self.s._read()["chat"][2]["text"], "Scout's card is the one to read")
        self.assertEqual(self.s._read()["chat"][0]["text"], "scout checking in")

    def test_log_fields_the_learned_note_and_the_archive_move(self):
        self.seed()
        data = self.s._read()
        t = next(t for t in data["tasks"] if t["id"] == "open1")
        t["log"].append({"at": "2026-11-14T10:00:00", "status": "doing", "progress": 5, "text": "Sent back: redo", "by": "Scout", "actor": "scout"})
        t["learned"] = {"by": "Scout", "at": "2026-11-14T10:00:00"}
        self.s._write(data)
        self.s.clear_done()   # done1 goes to archive.json
        self.assertTrue(any(t["id"] == "done1" for t in self.s.load_archived()))
        p = rename.apply(self.s, "Scout", "Ives")
        t = self.card("open1")
        self.assertEqual((t["log"][-1]["by"], t["log"][-1]["actor"], t["learned"]["by"]), ("Ives", "Ives", "Ives"))
        self.assertEqual(self.card("done1")["agent"], "Ives")
        self.assertEqual(p["log_lines"], 2)   # the log line, and the learned note

    def test_a_snapshot_is_taken_before_the_rewrite(self):
        self.seed()
        rename.apply(self.s, "Scout", "Ives")
        self.assertTrue(any("before-rename" in p.name for p in (self.d / "backups").iterdir()))

    def test_config_roster_and_colour(self):
        self.seed()
        rename.apply(self.s, "Scout", "Ives")
        from agentboard import tomlread
        conf = tomlread.loads((self.d / "config.toml").read_text())
        self.assertEqual([a["name"] for a in conf["orch"]["agents"]], ["Ives", "Wren"])
        self.assertEqual(conf["orch"]["agents"][0]["color"], "green")   # the rest of the entry is untouched
        self.assertEqual(conf["agent_colors"]["Ives"], f"var(--a{names.agent_slot('Scout')})")   # the colour Scout had
        self.assertTrue((self.d / "config.toml.bak").exists())
        self.assertIn('owner = "Pat"', (self.d / "config.toml").read_text())

    def test_an_existing_pin_moves_with_the_name(self):
        (self.d / "config.toml").write_text(CONFIG + '\n[agent_colors]\n"Scout" = "#2563eb"   # blue\nWren = "#7c3aed"\n')
        self.seed()
        rename.apply(self.s, "Scout", "Ives")
        text = (self.d / "config.toml").read_text()
        self.assertIn('"Ives" = "#2563eb"   # blue', text)
        self.assertNotIn('"Scout"', text.split("[agent_colors]")[1])
        self.assertIn('Wren = "#7c3aed"', text)

    def test_no_pin_when_the_new_name_gets_the_same_slot(self):
        slot = names.agent_slot("Scout")
        twin = next(f"Ives{i}" for i in range(500) if names.agent_slot(f"Ives{i}") == slot)
        self.seed()
        rename.apply(self.s, "Scout", twin)
        self.assertNotIn("agent_colors", (self.d / "config.toml").read_text())

    def test_a_config_it_cannot_edit_safely_is_left_alone_and_says_so(self):
        (self.d / "config.toml").write_text('[board]\nowner = "Pat"\n[orch]\nagents = [ {color = "green", name = "Scout"} ]\n')
        self.seed()
        p = rename.apply(self.s, "Scout", "Ives")
        self.assertEqual(self.card("open1")["agent"], "Ives")   # the board itself moved
        self.assertTrue(any("by hand" in n for n in p["notes"]))
        self.assertIn('name = "Scout"', (self.d / "config.toml").read_text())

    def test_dry_run_writes_nothing(self):
        self.seed()
        before = self.snapshot()
        p = rename.plan(self.s, "Scout", "Ives")
        self.assertEqual(p["cards"], 2)
        self.assertEqual(self.snapshot(), before)
        code, out = self.run_cli("rename", "Scout", "Ives", "--dry-run")
        self.assertIn("Would rename Scout to Ives", out)
        self.assertIn("Nothing was changed", out)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.d / names.FILE).exists())

    def test_a_half_finished_rename_is_finished_by_running_it_again(self):
        self.seed()
        names.add(self.d, "Scout", "Ives")   # the first step, then the process died
        p = rename.apply(self.s, "Scout", "Ives")
        self.assertTrue(p["resume"])
        self.assertEqual(self.card("open1")["agent"], "Ives")
        self.assertEqual(cursors.read(self.d), {"ives": 2})
        with self.assertRaises(BoardError) as e:   # and a third run has nothing left to do
            rename.plan(self.s, "Scout", "Ives")
        self.assertIn("nothing is left", str(e.exception))

    def test_a_case_only_rename_is_allowed(self):
        self.seed()
        rename.apply(self.s, "Scout", "SCOUT")
        self.assertEqual(self.card("open1")["agent"], "SCOUT")

    def test_the_second_rename_of_a_name_follows_the_chain(self):
        self.seed()
        rename.apply(self.s, "Scout", "Ives")
        rename.apply(self.s, "Ives", "Marlowe")
        self.assertEqual(self.card("open1")["agent"], "Marlowe")
        self.assertEqual(names.resolve(self.d, "Scout"), "Marlowe")


class Undo(Base):
    def test_undo_puts_everything_back(self):
        self.seed()
        before = {"cards": [self.card(c)["agent"] for c in ("open1", "done1", "wren1")], "chat": [(m["sender"], m.get("to")) for m in self.s._read()["chat"]],
                  "cursors": cursors.read(self.d), "config": (self.d / "config.toml").read_text(), "listeners": list(listeners._read(self.d))}
        rename.apply(self.s, "Scout", "Ives")
        p = rename.undo(self.s)
        self.assertEqual((p["old"], p["new"]), ("Ives", "Scout"))
        self.assertEqual([self.card(c)["agent"] for c in ("open1", "done1", "wren1")], before["cards"])
        self.assertEqual([(m["sender"], m.get("to")) for m in self.s._read()["chat"]], before["chat"])
        self.assertEqual(cursors.read(self.d), before["cursors"])
        self.assertEqual(list(listeners._read(self.d)), before["listeners"])
        self.assertEqual((self.d / "config.toml").read_text(), before["config"])   # the pinned colour and the roster name are as they were
        self.assertEqual(names.resolve(self.d, "Scout"), "Scout")
        self.assertEqual(names.resolve(self.d, "Ives"), "Scout")   # the terminal that already typed /rename Ives still works for a day

    def test_undo_twice_says_there_is_nothing_to_undo(self):
        self.seed()
        rename.apply(self.s, "Scout", "Ives")
        rename.undo(self.s)
        with self.assertRaises(BoardError) as e:
            rename.undo(self.s)
        self.assertIn("no rename to undo", str(e.exception))

    def test_undo_moves_a_pin_back_that_the_rename_moved(self):
        (self.d / "config.toml").write_text(CONFIG + '\n[agent_colors]\n"Scout" = "#2563eb"\n')
        self.seed()
        rename.apply(self.s, "Scout", "Ives")
        rename.undo(self.s)
        self.assertIn('"Scout" = "#2563eb"', (self.d / "config.toml").read_text())

    def test_cli_undo_dry_run_and_names(self):
        self.seed()
        self.run_cli("rename", "Scout", "Ives")
        code, out = self.run_cli("rename", "--undo", "--dry-run")
        self.assertIn("Would rename Ives to Scout", out)
        self.assertEqual(self.card("open1")["agent"], "Ives")   # a dry run changed nothing
        code, out = self.run_cli("rename", "--undo", "Scout")
        self.assertIn("takes no names", out)
        code, out = self.run_cli("rename", "--undo")
        self.assertIn("Renamed Ives to Scout", out)
        self.assertEqual(self.card("open1")["agent"], "Scout")


class Refusals(Base):
    def setUp(self):
        super().setUp()
        self.seed()

    def refused(self, old, new, *words):
        with self.assertRaises(BoardError) as e:
            rename.apply(self.s, old, new)
        for w in words:
            self.assertIn(w, str(e.exception))
        self.assertEqual(self.card("open1")["agent"], "Scout")   # nothing moved

    def test_a_name_another_agent_has(self):
        self.refused("Scout", "Wren", "already on this board")
        self.refused("Scout", "wren", "already on this board")   # case does not matter

    def test_a_name_that_only_a_state_file_remembers(self):
        listeners.register(self.d, "Ghost", "inbox", pid=os.getpid())
        self.refused("Scout", "Ghost", "already on this board")

    def test_the_reserved_names_and_the_owner(self):
        self.refused("Scout", "ORCH", "keeps for itself")
        self.refused("Scout", "all", "keeps for itself")
        self.refused("Scout", "Pat", "keeps for itself")   # the owner of this board
        self.refused("Scout", "you", "keeps for itself")
        with self.assertRaises(BoardError):
            rename.apply(self.s, "ORCH", "Boss")
        with self.assertRaises(BoardError):
            rename.apply(self.s, "Pat", "Boss")

    def test_a_bad_name(self):
        for bad in ("", " ", 'Ba"d', "a\nb", "x" * 41, "-lead", "back\\slash", "comma,name"):
            with self.assertRaises(BoardError, msg=repr(bad)):
                rename.apply(self.s, "Scout", bad)
        self.assertEqual(self.card("open1")["agent"], "Scout")

    def test_a_name_nobody_has(self):
        with self.assertRaises(BoardError) as e:
            rename.apply(self.s, "Nobody", "Zed")
        self.assertIn("no agent named Nobody", str(e.exception))
        self.assertIn("Scout", str(e.exception))   # and says who is here

    def test_an_old_name_that_still_works_as_an_alias(self):
        rename.apply(self.s, "Scout", "Ives")
        with self.assertRaises(BoardError) as e:
            rename.apply(self.s, "Wren", "Scout")
        self.assertIn("alias", str(e.exception))
        with self.assertRaises(BoardError) as e:
            rename.apply(self.s, "Scout", "Zed")
        self.assertIn("already Ives", str(e.exception))


class CommandLine(Base):
    def test_the_old_name_keeps_working_after_a_rename(self):
        self.seed()
        self.run_cli("rename", "Scout", "Ives")
        os.environ["AGENTBOARD_NAME"] = "Scout"   # the terminal that has not been renamed yet
        code, out = self.run_cli("update", "open1", "60", "still going")
        self.assertFalse(code, out)
        self.assertEqual(self.card("open1")["progress"], 60)
        self.assertEqual(os.environ["AGENTBOARD_NAME"], "Ives")   # a child of this command (a one-shot run) is told the new name

    def test_name_and_to_flags_follow_the_alias(self):
        self.seed()
        self.run_cli("rename", "Scout", "Ives")
        os.environ.pop("AGENTBOARD_NAME", None)
        code, out = self.run_cli("chat", "send", "from the old name", "--name", "Scout")
        self.assertFalse(code, out)
        self.assertEqual(self.s._read()["chat"][-1]["sender"], "Ives")
        data = self.s._read()
        data["chat_agents"] = True   # agent-to-agent talk is off until the owner turns it on
        self.s._write(data)
        code, out = self.run_cli("chat", "send", "to the old name", "--name", "Wren", "--to", "Scout")
        self.assertFalse(code, out)
        self.assertEqual(self.s._read()["chat"][-1].get("to"), "Ives")

    def test_a_wait_under_the_old_name_registers_as_the_new_one(self):
        self.seed()
        self.run_cli("rename", "Scout", "Ives")
        self.run_cli("chat", "inbox", "--name", "Scout")
        self.assertNotIn("Scout", listeners._read(self.d))

    def test_an_expired_alias_is_not_followed(self):
        self.seed()
        names.add(self.d, "Zed", "Wren", now=datetime.now() - timedelta(days=3))
        os.environ["AGENTBOARD_NAME"] = "Zed"
        self.run_cli("update", "wren1", "50", "x")
        self.assertEqual(os.environ["AGENTBOARD_NAME"], "Zed")   # not Wren: the day is up

    def test_without_an_alias_file_nothing_is_read(self):
        os.environ["AGENTBOARD_NAME"] = "Anyone"
        with mock.patch.object(names, "resolve") as resolve:
            cli._canon_names(SimpleNamespace(cmd="update", name="Anyone", to=None))
        resolve.assert_not_called()

    def test_help_and_usage(self):
        code, out = self.run_cli("rename")
        self.assertIn("give the old and the new name", out)
        code, out = self.run_cli("rename", "--help")
        self.assertIn("--dry-run", out)


if __name__ == "__main__":
    unittest.main()
