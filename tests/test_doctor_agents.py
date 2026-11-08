"""agentboard doctor, the agents line (overnight, Nov 7): is anything connected to this board? Which agents have reported, and does the project's
CLAUDE.md or AGENTS.md carry agentboard's lines. Read-only: it reads tasks.json and one text file and writes nothing."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from agentboard import agentfiles, doctor
from agentboard.doctor import INFO, PASS

from test_doctor import FakeRunner


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proj = Path(self.tmp.name).resolve() / "proj"
        self.proj.mkdir()
        self.board = self.proj / ".agentboard"
        self.board.mkdir()
        self.tasks([])

    def tasks(self, agents):
        (self.board / "tasks.json").write_text(json.dumps({"tasks": [{"id": f"t{i}", "title": "x", "status": "doing", "agent": a} for i, a in enumerate(agents)]}))

    def lines(self):
        return [(lvl, text) for lvl, name, text in doctor.check_agents(self.board, self.proj) if name == "agents"]


class Reported(Base):
    def test_nobody_yet(self):
        self.assertEqual(self.lines()[0], (INFO, "no agent has reported to this board yet"))

    def test_names_and_a_count_once_some_have(self):
        self.tasks(["atlas", "bolt", "atlas", None, ""])
        lvl, text = self.lines()[0]
        self.assertEqual((lvl, text), (PASS, "2 agents reported to this board: atlas, bolt"))
        self.tasks(["solo"])
        self.assertEqual(self.lines()[0][1], "1 agent reported to this board: solo")

    def test_a_long_list_is_cut(self):
        self.tasks([f"agent-{i}" for i in range(9)])
        text = self.lines()[0][1]
        self.assertTrue(text.startswith("9 agents reported"))
        self.assertTrue(text.endswith(" ..."))
        self.assertEqual(text.count("agent-"), 6)

    def test_an_unreadable_or_odd_board_never_crashes(self):
        said = lambda: [t for _l, t in self.lines() if "reported" in t]   # noqa: E731
        (self.board / "tasks.json").write_text("not json")
        self.assertEqual(said(), [])                                       # unreadable: that is the files check's business
        for odd in ("[]", '{"tasks": "x"}', '{"tasks": [1, null, {"title": "no agent"}]}'):
            (self.board / "tasks.json").write_text(odd)
            self.assertEqual(said(), ["no agent has reported to this board yet"], odd)
        (self.board / "tasks.json").unlink()
        self.assertEqual(said(), [])


class TheInstructionFile(Base):
    def test_no_file(self):
        lvl, text = self.lines()[-1]
        self.assertEqual(lvl, INFO)
        self.assertIn("no CLAUDE.md or AGENTS.md here", text)
        self.assertIn("agentboard instructions", text)

    def test_a_file_without_the_lines_says_how_to_add_them(self):
        (self.proj / "CLAUDE.md").write_text("# notes\n")
        lvl, text = self.lines()[-1]
        self.assertEqual(lvl, INFO)
        self.assertIn("CLAUDE.md does not have agentboard's instructions yet", text)
        self.assertIn("agentboard init --instructions", text)

    def test_the_markers_or_a_hand_pasted_heading_count_as_having_them(self):
        for body in (f"{agentfiles.INSTR_START}\nx\n{agentfiles.INSTR_END}\n", "## Agent board\n\nmine\n"):
            (self.proj / "CLAUDE.md").write_text(body)
            self.assertEqual(self.lines()[-1], (PASS, "CLAUDE.md has agentboard's instructions"))

    def test_agents_md_is_looked_at_when_it_is_the_only_one_and_a_link_is_not(self):
        (self.proj / "AGENTS.md").write_text("## Agent board\n")
        self.assertEqual(self.lines()[-1], (PASS, "AGENTS.md has agentboard's instructions"))
        (self.proj / "AGENTS.md").unlink()
        target = Path(self.tmp.name) / "elsewhere.md"
        target.write_text("## Agent board\n")
        os.symlink(target, self.proj / "CLAUDE.md")
        self.assertIn("no CLAUDE.md or AGENTS.md here", self.lines()[-1][1])


class ReadOnly(Base):
    def test_it_changes_nothing(self):
        (self.proj / "CLAUDE.md").write_text("# notes\n")
        self.tasks(["atlas"])
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.proj.rglob("*") if p.is_file()}
        names = sorted(p.name for p in self.proj.rglob("*"))
        doctor.check_agents(self.board, self.proj)
        self.assertEqual({p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.proj.rglob("*") if p.is_file()}, before)
        self.assertEqual(sorted(p.name for p in self.proj.rglob("*")), names)

    def test_it_is_part_of_the_doctor_run_and_never_fails_it(self):
        results = doctor.run(self.board, env={}, runner=FakeRunner())
        mine = [r for r in results if r[1] == "agents"]
        self.assertEqual(len(mine), 2)
        self.assertTrue(all(r[0] in (INFO, PASS) for r in mine))
        self.assertEqual(doctor.exit_code(results, strict=False) == 1, any(r[0] == "FAIL" for r in results))


if __name__ == "__main__":
    unittest.main()
