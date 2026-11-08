"""By agent with more lanes than fit (6+ agents): the lanes scroll sideways under a scrollbar that overlay-scrollbar systems hide, so a lane past the
edge, one that needs you, had no sign it was there. An edge fade and a chip ("+4 more · 1 needs you") now say so and jump to it; nothing shows when
every lane fits. The counting logic is a pure function and runs in Node when it is installed; the markup, rules and wiring are checked as text."""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


def rule(selector):
    m = re.search(r"(?:^|\n)\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", HTML)
    return m.group(1) if m else None


class TheCueIsWiredIn(unittest.TestCase):
    def test_the_cue_sits_after_the_board_with_a_fade_and_a_chip_on_each_side(self):
        m = re.search(r'<main class="board" id="board"[^>]*></main>\s*<div id="lane-cue" hidden>(.*?)</div>', HTML, re.S)
        self.assertIsNotNone(m, "the cue follows the board in the markup, so a keyboard reaches the chips after the lanes")
        body = m.group(1)
        self.assertEqual(len(re.findall(r'<span class="lane-fade [lr]" aria-hidden="true">', body)), 2)
        self.assertEqual(len(re.findall(r'<button type="button" class="lane-chip [lr]" hidden>', body)), 2)

    def test_it_is_drawn_over_the_board_and_gone_off_the_by_agent_view_and_under_load(self):
        self.assertIn("position: fixed", rule("#lane-cue"))
        self.assertIn("pointer-events: none", rule("#lane-cue"))
        hide = rule("#lane-cue[hidden], body:not(.byagent) #lane-cue, body:has(#hud.open) #lane-cue")
        self.assertIn("display: none", hide)
        self.assertIn("pointer-events: auto", rule(".lane-chip"))

    def test_the_fade_is_calm_and_the_chip_words_mix_toward_the_text_for_contrast(self):
        self.assertIn("@media (prefers-reduced-motion: reduce) { .lane-fade { transition: none; } }", HTML)
        self.assertIn("color-mix(in srgb, var(--err) 78%, var(--text))", rule(".lane-chip .need"))
        self.assertIn("color-mix(in srgb, var(--ok) 78%, var(--text))", rule(".lane-chip .ready"))

    def test_it_is_redrawn_after_every_render_and_on_scroll_and_resize(self):
        self.assertRegex(HTML, r"k\.scrollTop = scrolls\[c\.dataset\.status\] \|\| 0; \}\);\n\s*laneCue\(\);")
        for ev in ("$('board').addEventListener('scroll', laneCue", "addEventListener('resize', laneCue)", "addEventListener('scroll', laneCue"):
            self.assertIn(ev, HTML)

    def test_the_chip_jumps_to_the_first_lane_that_needs_you_else_the_next(self):
        self.assertIn("const target = dir > 0 ? (s.needs[0] || s.right[0]) : s.left[s.left.length - 1];", HTML)
        self.assertIn("matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'", HTML)

    def test_the_chip_says_what_it_counts_for_a_screen_reader(self):
        self.assertIn("more ${n === 1 ? 'agent' : 'agents'} to the right", HTML)
        self.assertIn("Scroll right.", HTML)
        self.assertIn("Scroll left.", HTML)


@unittest.skipUnless(shutil.which("node"), "node is not installed: the counting logic is checked as text only")
class TheCountingLogic(unittest.TestCase):
    """laneCueState(lanes, boardRect) from the page itself, run in Node with fake lanes (a rect and the state word on the lane's header)."""

    @classmethod
    def setUpClass(cls):
        edge = re.search(r"const LANE_EDGE = \d+, LANE_FADE_W = \d+;", HTML).group(0)
        fn = re.search(r"function laneCueState\(lanes, br\) \{.*?\n\}\n", HTML, re.S).group(0)
        cls.src = edge + "\n" + fn

    def run_cases(self, cases):
        script = self.src + """
const mk = (left, right, state) => ({ getBoundingClientRect: () => ({ left, right }), querySelector: () => ({ className: state }) });
const out = JSON.parse(process.argv[1]).map(c => {
  const lanes = c.lanes.map(l => mk(l[0], l[1], l[2] || 'working'));
  const s = laneCueState(lanes, { left: c.board[0], right: c.board[1] });
  return { right: s.right.map(l => lanes.indexOf(l)), left: s.left.map(l => lanes.indexOf(l)), needs: s.needs.map(l => lanes.indexOf(l)), ready: s.ready.map(l => lanes.indexOf(l)) };
});
console.log(JSON.stringify(out));
"""
        r = subprocess.run(["node", "-e", script, json.dumps(cases)], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_eight_lanes_in_a_narrow_board_count_the_ones_past_the_right_edge(self):
        lanes = [[i * 238, i * 238 + 220] for i in range(8)]   # 220px lanes, 18px gaps
        (r,) = self.run_cases([{"board": [0, 1277], "lanes": lanes}])
        self.assertEqual(r["right"], [5, 6, 7])   # lane 5 ends at 1410, lane 4 at 1172
        self.assertEqual(r["left"], [])

    def test_when_everything_fits_nothing_is_counted(self):
        (r,) = self.run_cases([{"board": [0, 1000], "lanes": [[0, 220], [238, 458], [476, 696]]}])
        self.assertEqual((r["right"], r["left"]), ([], []))

    def test_a_lane_a_few_pixels_over_the_edge_does_not_count(self):
        (r,) = self.run_cases([{"board": [0, 1000], "lanes": [[0, 500], [510, 1003]]}])   # 3px over: within the 4px tolerance
        self.assertEqual(r["right"], [])
        (r,) = self.run_cases([{"board": [0, 1000], "lanes": [[0, 500], [510, 1006]]}])   # 6px over: counts
        self.assertEqual(r["right"], [1])

    def test_a_scrolled_board_counts_both_sides(self):
        lanes = [[-500, -280], [-262, -42], [-24, 196], [214, 434], [452, 672], [690, 910], [928, 1148], [1166, 1386]]
        (r,) = self.run_cases([{"board": [0, 1000], "lanes": lanes}])
        self.assertEqual(r["left"], [0, 1, 2])   # lane 2 starts at -24: partly out
        self.assertEqual(r["right"], [6, 7])

    def test_needs_you_and_ready_are_counted_only_among_the_lanes_to_the_right(self):
        lanes = [[-300, -80, "ask"], [0, 220, "working"], [240, 460, "review"], [1100, 1320, "ask"], [1340, 1560, "review"], [1580, 1800, "working"]]
        (r,) = self.run_cases([{"board": [0, 1000], "lanes": lanes}])
        self.assertEqual(r["left"], [0])
        self.assertEqual(r["right"], [3, 4, 5])
        self.assertEqual(r["needs"], [3])   # the one at the left (index 0) is not "to the right"
        self.assertEqual(r["ready"], [4])


if __name__ == "__main__":
    unittest.main()
