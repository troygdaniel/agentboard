"""The board's chat composers (chat-f8, built from docs/chat-words-design.md): a "goes to" line under each box that says who reads the
line and whether anything wakes them, a send that keeps the text until the board takes it, the refusal lines, Tab for the offered name,
and the names feed behind it. The page is not rendered here (headless Chrome does that on a throwaway board); this pins the strings and
the API."""
import json
import unittest
from pathlib import Path

from agentboard import listeners, server
from agentboard.store import Store

from tests.test_reports import HttpTests as _Http

HTML = (Path(server.__file__).parent / "static" / "index.html").read_text()


def body(fn):
    i = HTML.index(f"function {fn}(")
    return HTML[i:HTML.index("\n}\n", i)]


class TheNamesFeed(_Http):
    def test_api_chat_carries_who_a_line_can_reach(self):
        self.s.start("Export pipeline", "AGENT-2", None)
        self.s.set_chat_agents(True)
        self.s.chat_send("AGENT-3", "a status line")
        listeners.register(self.s.dir, "AGENT-4", "inbox", pid=1)
        d = json.loads(self.get("/api/chat")[1])
        self.assertEqual(d["names"], sorted(["ORCH", self.s.owner, "AGENT-2", "AGENT-3", "AGENT-4"]))
        self.assertEqual(Store(self.s.dir).known_names(), d["names"])


class TheWords(unittest.TestCase):
    def test_the_goes_to_line_is_under_each_box_and_its_height_is_reserved(self):
        for box in ("chat-goes", "thread-goes", "p-chat-goes"):
            self.assertIn(f'<div class="goes" id="{box}" aria-live="polite"', HTML)
        self.assertIn(".goes { flex: none; padding: 0 20px 12px; min-height: calc(1.4em + 12px);", HTML)
        self.assertIn('placeholder="Message ORCH, or @AGENT-2…"', HTML)
        g = body("whoReads")
        for words in ("Goes to ${who} · ${ls.word}", "`${defaultTo} only`", "`${defaultTo}, who holds this card`",
                      "Goes to everyone listening (${n}). No one owns the answer.", "Names: ${cands.slice(0, NAME_CAP).join(', ')} · Tab takes the first",
                      "No one named ${typed}. Did you mean ${close}? Tab uses it.", "No one named ${typed}. On this board: ",
                      "Add what to tell ${full} after the name."):
            self.assertIn(words, g)
        ls = body("listenState")
        self.assertIn("not listening: it reads this when its session next runs", ls)
        self.assertIn("sessions: ${n > 2 ? 'each' : 'both'} may answer", ls)

    def test_a_refused_or_failed_send_keeps_the_text_and_an_accepted_one_clears_it(self):
        s = body("sendLine")
        self.assertIn("if (w.error) { setGoes(goes, w.error, true); $(goes).dataset.hold = '1'; i.focus(); return; }", s)
        self.assertIn("try { await api('/api/chat', body); i.value = ''; showError('');", s)          # cleared only after the board took it
        self.assertIn("Not sent: the board did not answer. Your text is still here; send again.", s)
        for old in ("i.value = '';\n  try { await api('/api/chat'", "i.value = '';\n  const to = text.startsWith('@')"):
            self.assertNotIn(old, HTML)                                                             # the old order: cleared before the send
        self.assertIn("if (e.key !== 'Tab' || where !== 'drawer') return;", HTML)
        self.assertIn("chatNames = Array.isArray(d.names) ? d.names : [];", HTML)
        self.assertIn("refreshGoes();", body("renderThread"))
