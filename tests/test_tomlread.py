"""tomlread: tomllib where Python has it (3.11+), the small built-in reader before that. The reader is held to tomllib's answers: on a Python
that has both, every document here must give the same dict, or both must refuse it; on 3.9 and 3.10 the reader is checked against the
expected values written out. The documents are the ones the board actually reads: the config `init` writes (every option uncommented), the
README's config block, the snippets the tests write, and the TOML features each of those uses."""
import re
import sys
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from agentboard import cli, tomlread
from agentboard.tomlread import TOMLDecodeError, _Reader

ROOT = Path(__file__).parents[1]


def uncommented_sample():
    """The config `agentboard init` writes, with every option switched on (only the lines that are TOML once the # goes)."""
    out = []
    for line in cli.SAMPLE_CONFIG.splitlines():
        body = line[2:] if line.startswith("# ") else line
        if re.match(r"\s*(?:\[[\w.\"'-]+\]|[\w\"'-]+\s*=)", body) and "<name>" not in body:
            out.append(body)
    return "\n".join(out) + "\n"


def readme_block():
    text = (ROOT / "README.md").read_text()
    m = re.search(r"## Configuration.*?\n\n((?:    .*\n|\n)+?)Environment", text, re.S)
    return "\n".join(line[4:] for line in m.group(1).splitlines() if "<name>" not in line and "type = \"markdown\"" not in line) + "\n"


GOOD = {
    "sample": uncommented_sample(),
    "readme": readme_block(),
    "orch roster (inline tables)": '[orch]\nagents = [{name="AGENT-1"}, {name="AGENT-2", color = "#fff"}]\n[chat]\nautopilot_per_hour = 2\n',
    "quoted keys": '[agent_colors]\n"AGENT-1" = "#2563eb"   # a comment with "quotes"\n\'lit key\' = \'#fff\'\n',
    "dotted keys, numbers, arrays": 'a.b.c = 1\na.b.d = "x"\n[t]\nx = [1, 2,\n  3, # c\n]\nempty = []\nf = 1.5e3\nneg = -7\nbig = 1_000\nhx = 0xff\nok = true\nno = false\ninf = -inf\n',
    "strings": 's = "esc \\t \\n \\u00e9 \\" \\\\"\nml = """\nline1\nline2 \\\n   joined"""\nlit = \'C:\\path\'\nmll = \'\'\'\nraw \\n\n\'\'\'\nq = """a""quote"""\n',
    "dates and times": 'd = 2026-11-07\ndt = 2026-11-07T10:00:00\ndtz = 2026-11-07T10:00:00Z\ndto = 2026-11-07 10:00:00.5+02:00\nt = 10:00:00\n',
    "arrays of tables": '[[p]]\nn = 1\n[[p]]\nn = 2\n[p.sub]\nz = 3\n[q."dotted.name".r]\nv = 1\n',
    "empty": "",
    "only a comment": "# only a comment\n",
    "nested": 'arr = [[1,2],["a"],[]]\nit = {a = {b = 1}, c = [1]}\n',
    "quotes at the edge of literals, tabs": "a = '''x'''''\nb = '''y''''\nc = '''z'''\nt = \"tab\\there\"\nraw = \"a\tb\"\n",
    "redact": '[redact]\nextra = ["ACME-[0-9]{6}"]\nenabled = false\n',
    "backup": '[backup]\nsync_dir = "/proc/nope/agentboard"\n',
    "template with escapes": '[prompt]\ntemplate = "T: {title}\\nI: {task_id}\\nD:\\n{description}"\n',
}
BAD = ["bad toml [[[", "d = 2026-02-30\n", "d = 2026-11-07T10:00:00+25:00\n", "this is [not toml", "a = 1\na = 2\n", "[t]\n[t]\n", 'x = "unterminated\n', "x = 01\n", "x =\n", "[t]\nx = 1\n[t.y]\n[t]\n",
       "k = {a=1}\nk.b = 2\n", "x = 1 y = 2\n", "x = [1,\n", 's = "\x01"\n', "[a]\nb = 1\n[a.b]\n", "x = 1\n[x]\n", "= 1\n"]


class TheReaderAgreesWithTomllib(unittest.TestCase):
    @unittest.skipUnless(tomlread.USING_TOMLLIB, "needs a Python with tomllib (3.11+) to compare against")
    def test_every_good_document_reads_the_same(self):
        import tomllib
        for name, doc in GOOD.items():
            with self.subTest(name):
                self.assertEqual(_Reader(doc).document(), tomllib.loads(doc))

    @unittest.skipUnless(tomlread.USING_TOMLLIB, "needs a Python with tomllib (3.11+) to compare against")
    def test_every_bad_document_is_refused_by_both(self):
        import tomllib
        for doc in BAD:
            with self.subTest(doc):
                with self.assertRaises(ValueError):
                    tomllib.loads(doc)
                with self.assertRaises(TOMLDecodeError):
                    _Reader(doc).document()

    def test_the_sample_config_has_every_section_and_the_readme_block_reads(self):
        d = _Reader(GOOD["sample"]).document()
        for sect in ("providers", "ui", "chat", "run", "reports", "board", "agent_colors", "notify", "backup", "redact", "prompt"):
            self.assertIn(sect, d)
        self.assertEqual(d["providers"]["mail"]["fields"], ["from", "subject", "date", "body"])
        self.assertEqual(d["chat"]["idle_budget_usd"], 0.05)
        self.assertEqual(d["agent_colors"]["AGENT-1"], "#2563eb")
        r = _Reader(GOOD["readme"]).document()
        self.assertEqual((r["board"]["owner"], r["board"]["stale_minutes"], r["notify"]["enabled"]), ("you", 120, True))


class TheReaderOnItsOwn(unittest.TestCase):
    """What the reader must give on any Python (so 3.9 and 3.10 are tested without tomllib)."""

    def test_values(self):
        d = _Reader(GOOD["dotted keys, numbers, arrays"]).document()
        self.assertEqual(d, {"a": {"b": {"c": 1, "d": "x"}}, "t": {"x": [1, 2, 3], "empty": [], "f": 1500.0, "neg": -7, "big": 1000, "hx": 255,
                                                                 "ok": True, "no": False, "inf": float("-inf")}})
        self.assertIsInstance(d["t"]["f"], float)
        self.assertIsInstance(d["t"]["hx"], int)

    def test_strings(self):
        d = _Reader(GOOD["strings"]).document()
        self.assertEqual(d["s"], 'esc \t \n \u00e9 " \\')
        self.assertEqual(d["ml"], "line1\nline2 joined")
        self.assertEqual(d["lit"], "C:\\path")
        self.assertEqual(d["mll"], "raw \\n\n")
        self.assertEqual(d["q"], 'a""quote')

    def test_dates(self):
        d = _Reader(GOOD["dates and times"]).document()
        self.assertEqual(d["d"], date(2026, 11, 7))
        self.assertEqual(d["dt"], datetime(2026, 11, 7, 10, 0, 0))
        self.assertEqual(d["dtz"], datetime(2026, 11, 7, 10, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(d["dto"], datetime(2026, 11, 7, 10, 0, 0, 500000, tzinfo=timezone(timedelta(hours=2))))
        self.assertEqual(d["t"], time(10, 0, 0))

    def test_tables(self):
        d = _Reader(GOOD["arrays of tables"]).document()
        self.assertEqual(d, {"p": [{"n": 1}, {"n": 2, "sub": {"z": 3}}], "q": {"dotted.name": {"r": {"v": 1}}}})
        self.assertEqual(_Reader(GOOD["orch roster (inline tables)"]).document()["orch"]["agents"], [{"name": "AGENT-1"}, {"name": "AGENT-2", "color": "#fff"}])
        self.assertEqual(_Reader(GOOD["quoted keys"]).document(), {"agent_colors": {"AGENT-1": "#2563eb", "lit key": "#fff"}})
        self.assertEqual(_Reader(GOOD["empty"]).document(), {})
        self.assertEqual(_Reader(GOOD["only a comment"]).document(), {})

    def test_bad_documents_raise_a_value_error_with_a_position_and_no_text(self):
        for doc in BAD:
            with self.subTest(doc):
                with self.assertRaises(TOMLDecodeError) as cm:
                    _Reader(doc).document()
                self.assertIsInstance(cm.exception, ValueError)
                self.assertIn("line", str(cm.exception))

    def test_a_bad_date_is_the_readers_error_not_a_traceback(self):
        import agentboard.tomlread as m
        saved = m._std
        m._std = None   # the small reader, whatever Python this is: the wrapping lives in loads()
        try:
            for doc in ("d = 2026-02-30\n", "d = 2026-11-07T10:00:00+25:00\n", "t = 25:00:00\n"):
                with self.assertRaises(TOMLDecodeError):
                    m.loads(doc)
        finally:
            m._std = saved

    def test_load_reads_utf8_bytes_with_or_without_a_bom(self):
        import io
        self.assertEqual(tomlread.load(io.BytesIO(b'\xef\xbb\xbfa = "\xc3\xa9"\n')), {"a": "\u00e9"})
        self.assertEqual(tomlread.load(io.BytesIO(b'a = 1\n')), {"a": 1})

    def test_loads_picks_the_standard_library_when_there_is_one(self):
        self.assertEqual(tomlread.USING_TOMLLIB, sys.version_info >= (3, 11))
        self.assertEqual(tomlread.loads('x = [1, "a"]\n'), {"x": [1, "a"]})
        with self.assertRaises(ValueError):
            tomlread.loads("x = [")

    def test_the_board_reads_its_config_through_the_reader(self):
        """No module imports tomllib directly: every read goes through here, so 3.9 and 3.10 have no missing module."""
        src = ROOT / "src" / "agentboard"
        offenders = [p.name for p in src.glob("*.py") if p.name != "tomlread.py" and re.search(r"^\s*import tomllib\b", p.read_text(), re.M)]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
