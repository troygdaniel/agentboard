"""By agent: the live-count tick must not throw on an agent column (data-status "agent:NAME" has no status list in `by`).
Found by AGENT-2: every re-render after the first threw a TypeError ("by[k] is undefined"). The tick block is lifted verbatim out of index.html and run in node with fake columns."""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

HTML = Path(__file__).resolve().parents[1] / "src" / "agentboard" / "static" / "index.html"


def tick_block() -> str:
    m = re.search(r"if \(!firstRender\) \$\('board'\)\.querySelectorAll\('\.col'\)\.forEach\(col => \{.*?\n  \}\);\n", HTML.read_text(), re.S)
    assert m, "the live-count tick block moved or changed shape: update this test"
    return m.group(0)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the page's own code")
class TickTests(unittest.TestCase):
    def tick(self, cols, by, last):
        js = """
const firstRender = false, by = %s, lastCounts = %s;
const cols = %s.map(k => { const cnt = { classList: { add() { this.added = true; }, added: false } };
  return { dataset: { status: k }, querySelector: () => cnt, cnt }; });
const $ = () => ({ querySelectorAll: () => cols });
%s
console.log(JSON.stringify(cols.map(c => [c.dataset.status, c.cnt.classList.added])));
""" % (json.dumps(by), json.dumps(last), json.dumps(cols), tick_block())
        out = subprocess.run(["node", "-e", js], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        return dict(json.loads(out.stdout))

    def test_agent_columns_are_skipped_and_status_columns_still_tick(self):
        by = {"todo": [1, 2], "doing": [1], "done": []}
        got = self.tick(["agent:AGENT-1", "agent:AGENT-2", "todo", "doing", "done"], by, {"todo": 1, "doing": 1, "done": 0})
        self.assertEqual(got, {"agent:AGENT-1": False, "agent:AGENT-2": False, "todo": True, "doing": False, "done": False})

    def test_a_re_render_of_by_agent_does_not_throw(self):
        for _ in range(2):   # the old code threw from the second render on, once lastCounts was set
            self.tick(["agent:AGENT-1"], {"todo": [], "doing": []}, {"todo": 0, "doing": 0})


if __name__ == "__main__":
    unittest.main()
