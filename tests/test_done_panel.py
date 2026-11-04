"""The Done panel (Nov 4): a finished card keeps its body, the body splits into Changed / Checked / Next, a ```flow block draws a
diagram, /api/task carries the pieces, and the prompts ask agents for the shape."""
import contextlib
import io
import json
import os
import re
import socket
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from agentboard import cli, markdown as mdlib, nav, prompt
from agentboard.server import _group_files, make_handler
from agentboard.store import Store

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()
BODY = """An opening line before the shape.

## Changed
- Closing a held card leaves a reply
- Undo, send back, move and remove say what happened
## Checked
- 675 tests pass · render clean
## Next
- ORCH: pipx install, restart serve
```flow
You mark done -> Card gets a reply -> Agent wakes
store: 2
tests: 23
```
A trailing note.
"""


class FlowTests(unittest.TestCase):
    def test_a_flow_line_is_boxes_and_arrows_and_a_bar_line_is_a_bar(self):
        svg = mdlib.flow_svg(["A -> B -> C", "tests: 23", "store: 2"])
        self.assertTrue(svg.startswith('<svg class="flow"'))
        self.assertEqual(svg.count("<rect"), 3 + 2)          # three boxes, two bars
        self.assertEqual(svg.count("<path"), 4)              # two arrows: a line and a head each
        self.assertIn("var(--surface)", svg)                 # the page's colours, so it follows the theme
        self.assertIn("var(--info)", svg)
        self.assertIn(">23<", svg)

    def test_text_is_escaped_and_an_empty_block_falls_back_to_code(self):
        svg = mdlib.flow_svg(["<b>&x</b> -> y"])
        self.assertNotIn("<b>", svg)
        self.assertIn("&lt;b&gt;&amp;x", svg)
        self.assertEqual(mdlib.flow_svg(["   ", "no arrows here"]), "")
        html = mdlib.to_html("```flow\nno arrows here\n```")
        self.assertIn("<pre><code", html)

    def test_to_html_draws_a_flow_fence_inline(self):
        html = mdlib.to_html("before\n\n```flow\nA -> B\n```\n\nafter")
        self.assertIn('<svg class="flow"', html)
        self.assertNotIn("<pre>", html)
        self.assertIn("<p>after</p>", html)


class SectionTests(unittest.TestCase):
    def test_the_template_splits_into_its_parts(self):
        s = mdlib.sections(BODY)
        self.assertTrue(s["has"])
        self.assertIn("Closing a held card", s["changed"])
        self.assertIn("675 tests pass", s["checked"])
        self.assertIn("pipx install", s["next"])
        self.assertIn('<svg class="flow"', s["flow"])
        self.assertEqual(s["rest"], "<p>An opening line before the shape.</p>")
        self.assertIn("A trailing note.", s["next"])   # after the flow block but still under Next: markdown's reading
        for k in ("changed", "checked", "next"):
            self.assertNotIn("<h2>", s[k])   # the heading itself is the label, not content

    def test_spellings_and_bold_headings_count(self):
        s = mdlib.sections("**Did**\n- a\n\n### Tested (all)\n- b\n\n## Then\n- c\n")
        self.assertIn("<li>a</li>", s["changed"])
        self.assertIn("<li>b</li>", s["checked"])
        self.assertIn("<li>c</li>", s["next"])

    def test_a_body_without_the_shape_is_all_rest(self):
        s = mdlib.sections("just a note\n\n- one\n- two\n\n## Other heading\ntext")
        self.assertFalse(s["has"])
        self.assertIn("<li>one</li>", s["rest"])
        self.assertIn("<h2>Other heading</h2>", s["rest"])
        self.assertEqual(s["flow"], "")

    def test_a_heading_inside_a_code_fence_is_not_a_section(self):
        s = mdlib.sections("## Changed\n- a\n```\n## Checked\nnot a heading\n```\n")
        self.assertFalse(s["checked"])
        self.assertIn("## Checked", s["changed"])

    def test_escaping_holds_in_every_part(self):
        s = mdlib.sections("## Changed\n- <img src=x onerror=1>\n## Next\n<script>x</script>")
        self.assertNotIn("<img", s["changed"])
        self.assertNotIn("<script>", s["next"])


class StoreKeepsBodyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        self.s.start("Card", "alice")
        self.s.add("step", parent_id="card")
        self.s.review("card", "ACTION Troy: restart", body_md=BODY)   # one line: a second line would become part of the body

    def test_marking_done_by_move_keeps_the_body(self):
        self.s.move("card", "done")
        self.assertEqual(Store.get(self.s.load(), "card")["body_md"], BODY)

    def test_marking_done_by_update_and_by_the_cli_keeps_the_body(self):
        self.s.update("card", status="done")
        self.assertEqual(Store.get(self.s.load(), "card")["body_md"], BODY)

    def test_a_plain_update_still_drops_it_and_reopening_keeps_it(self):
        self.s.move("card", "done")
        self.s.move("card", "doing")
        self.assertEqual(Store.get(self.s.load(), "card")["body_md"], BODY)   # reopened: the account of the work stays until the agent reports again
        self.s.update("card", 0, "back at it")
        self.assertNotIn("body_md", Store.get(self.s.load(), "card"))


class GroupTests(unittest.TestCase):
    def test_files_group_at_the_shallowest_telling_depth(self):
        self.assertEqual(_group_files(["src/a/x.py", "src/a/y.py", "tests/t.py"]), [("src", 2), ("tests", 1)])
        self.assertEqual(_group_files(["src/a/x.py", "src/b/y.py"]), [("src/a", 1), ("src/b", 1)])
        self.assertEqual(_group_files(["README.md"]), [("README.md", 1)])
        self.assertEqual(_group_files([]), [])


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        self.s.start("Card", "alice")
        self.s.add("step", parent_id="card")
        self.s.ask("card", "Which one?")
        self.s.reply("card", "Go ahead")
        self.s.review("card", "ACTION Troy: restart", body_md=BODY)
        self.s.move("card", "done")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), make_handler(self.s, self.port))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.shutdown)

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
            return json.loads(r.read())

    def test_the_task_carries_sections_checks_and_a_git_summary(self):
        t = self.get("/api/task?id=card")
        self.assertTrue(t["sections"]["has"])
        self.assertIn('<svg class="flow"', t["sections"]["flow"])
        self.assertEqual(t["checks"], ["675 tests pass"])
        self.assertIn("git", t)   # {} without a repo, never missing
        self.assertIsInstance(t["git"], dict)
        self.assertEqual(t["status"], "done")
        self.assertIn("Go ahead", [l["text"] for l in t["log"]])   # the panel pairs it with the question

    def test_a_card_in_review_gets_the_git_summary_too(self):
        self.s.start("Reviewed", "bob")
        self.s.add("s", parent_id="reviewed")
        self.s.review("reviewed", "ready", body_md="## Changed\n- x")
        t = self.get("/api/task?id=reviewed")
        self.assertIn("git", t)
        self.assertTrue(t["sections"]["has"])

    def test_a_subtask_gets_no_git_summary_and_the_list_stays_light(self):
        t = self.get("/api/task?id=step")
        self.assertNotIn("git", t)
        tasks = self.get("/api/tasks")["tasks"]
        self.assertNotIn("sections", tasks[0])


class PromptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        env["AGENTBOARD_DIR"] = str(self.s.dir)
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def test_every_card_prompt_and_the_instructions_ask_for_the_shape(self):
        self.s.add("Plain", status="todo")
        text, _ = prompt.build_prompt(Store.get(self.s.load(), "plain"), self.s.dir, tasks=self.s.load())
        for piece in ("## Changed", "## Checked", "## Next", "```flow", "A -> B -> C"):
            self.assertIn(piece, text)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["instructions"])
        self.assertIn("## Changed", out.getvalue())
        self.assertIn("```flow", out.getvalue())


class PanelMarkupTests(unittest.TestCase):
    def test_the_done_branch_exists_and_reads_in_the_agreed_order(self):
        self.assertIn("function doneHtml(t, parsed, sawText, kids, head, btns)", HTML)
        m = re.search(r"if \(\(t\.status === 'done' \|\| rv\) && !t\.parent_id\) \{.*?\n  \}", HTML, re.S)
        self.assertTrue(m)   # a card up for review reads the same way, with its controls
        self.assertIn("doneHtml(t, parsed, sawText, kids, head, rv ? btns : '')", HTML)
        body = re.search(r"function doneHtml.*?\n\}\n", HTML, re.S).group(0)
        order = [body.index(x) for x in ("${sentence}", "${grid}", "${diagram}", "${ticks}", "${qa}", "${where}", "${pathStrip(t)}", '<details class="dfold">')]
        self.assertEqual(order, sorted(order))   # sentence, Changed/Checked/Next, the diagram, the ticks, your call, where, path, then the fold

    def test_the_fold_holds_the_old_sections_and_closes(self):
        self.assertIn("${desc}${tl}${details}${prompt}</details>", HTML)

    def test_state_notes_never_show_as_your_call(self):
        self.assertIn("!/^(Sent back|Title changed|Description )/.test(e.text || '')", HTML)


if __name__ == "__main__":
    unittest.main()
