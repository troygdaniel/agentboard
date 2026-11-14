"""Talk it through (Nov 14): a back-and-forth with ORCH about the card in front of you on Now, kept with that card, ending in a reply the
owner sends with one click. It is the board's own chat with a card attached: nothing new runs."""
import json
import socket
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from agentboard import agentchat, prompt
from agentboard.server import make_handler
from agentboard.store import Store

PAGE = (Path(__file__).resolve().parent.parent / "src" / "agentboard" / "static" / "index.html").read_text()


class Route(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(Path(self.tmp.name) / ".agentboard")
        self.s.start("Pilot hosting plan", "Wozbot", task_id="heroku")
        self.s.ask("heroku", "Approve the spend for the pilot?")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), make_handler(self.s, self.port))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.shutdown)
        self.addCleanup(self.srv.server_close)

    def post(self, path, payload):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json", "Host": f"localhost:{self.port}", "Origin": f"http://localhost:{self.port}"})
        return json.loads(urllib.request.urlopen(req, timeout=5).read())

    def test_the_owners_line_carries_its_card_to_orch(self):
        m = self.post("/api/chat", {"text": "What is this asking me?", "to": "ORCH", "card": "heroku"})
        self.assertEqual((m["card"], m["to"], m["kind"]), ("heroku", "ORCH", "user"))
        self.assertIn("(card heroku)", agentchat.chat_line(m))   # what ORCH's inbox prints: it knows which card without being told

    def test_a_line_with_no_card_is_as_before_and_a_bad_card_value_is_dropped(self):
        self.assertNotIn("card", self.post("/api/chat", {"text": "hello", "to": "ORCH"}))
        self.assertNotIn("card", self.post("/api/chat", {"text": "hello", "to": "ORCH", "card": 7}))

    def test_the_whole_round_orch_proposes_the_owner_sends(self):
        q = self.post("/api/chat", {"text": "What do you recommend?", "to": "ORCH", "card": "heroku"})
        a = self.s.chat_send("ORCH", "Pay: it is two weeks. Shall I send that?", "agent", to="you", card="heroku", propose="Yes, go with option A.", reply_to=q["seq"])
        self.assertEqual(a["action"], {"text": "Yes, go with option A.", "status": "proposed"})
        d = self.post("/api/chat-decide", {"seq": a["seq"], "decision": "approved"})   # Send this: the decision is recorded ...
        self.assertEqual(d["action"]["status"], "approved")
        self.post("/api/reply", {"id": "heroku", "text": a["action"]["text"]})            # ... and the board, not ORCH, sends the reply
        self.assertEqual(Store.get(self.s.load(), "heroku")["reply"]["text"], "Yes, go with option A.")


class Page(unittest.TestCase):
    def test_the_card_offers_it_first_and_the_slash_opens_it_on_now(self):
        self.assertIn("""<div class="you-help"><button type="button" class="you-h talk-h" data-talk="${esc(t.id)}\"""", PAGE)
        self.assertIn("if (e.key === '/' && !typing && MEFIRST && !nowWatch && !hudIsOpen() && deckTop && !mixIsOpen())", PAGE)

    def test_a_line_goes_to_orch_with_the_card(self):
        self.assertIn("await api('/api/chat', { text, to: 'ORCH', card: id });", PAGE)

    def test_only_this_cards_lines_between_the_owner_and_orch_are_shown(self):
        self.assertIn("const talkLines = id => chatMsgs.filter(m => m.card === id && ((m.kind === 'user' && String(m.to || '').toUpperCase() === 'ORCH') || (m.kind === 'agent' && String(m.sender || '').toUpperCase() === 'ORCH')));", PAGE)

    def test_the_answer_goes_to_the_conversation_not_the_bubble(self):
        self.assertIn("orchSeen = last.seq; if (last.card && last.card === talkCard) return;", PAGE)

    def test_send_this_records_the_decision_and_replies_on_the_card(self):
        block = PAGE[PAGE.index("const sd = e.target.closest?.('[data-talk-send]')"):PAGE.index("window.addEventListener('keydown', e => {   // on Now, the slash talks")]
        self.assertIn("api('/api/chat-decide', { seq: m.seq, decision: 'approved' })", block)
        self.assertIn("await quickReply(id, m.action.text)", block)

    def test_keys_typed_after_a_starter_stay_in_the_conversation(self):
        self.assertIn("if (a) { $('talk').querySelector('input').focus({ preventScroll: true }); talkSay(a.dataset.talkAsk); return; }", PAGE)

    def test_text_from_chat_is_escaped(self):
        block = PAGE[PAGE.index("function talkSync(force)"):PAGE.index("setInterval(talkSync, 350);")]
        for raw in ("${m.text}", "${m.action.text}", "${t.title}", "${said}"):
            self.assertNotIn(raw, block)
        self.assertIn("${esc(m.text)}", block)
        self.assertIn("${esc(m.action.text)}", block)

    def test_it_says_when_orch_is_away(self):
        self.assertIn("ORCH is not running. It will read this when it starts.</p>", PAGE)

    def test_walk_me_through_asks_once_per_card_you_stop_on(self):
        self.assertIn("const TALK_WALK = 'Walk me through this one.';", PAGE)
        self.assertIn("if (talkWalk && !lines.length && !talkAsked.has(t.id) && !talkBusy && Date.now() - talkSince > 1100) { talkAsked.add(t.id); talkSay(TALK_WALK); }", PAGE)
        self.assertIn("try { talkWalk = localStorage.getItem('ab-talk-walk') === '1'; } catch (e) {}", PAGE)   # remembered, and a blocked store leaves it off

    def test_orch_may_propose_the_sign_off_only_on_finished_work(self):
        self.assertIn("const talkSignoff = (t, m) => !!(t && t.review && m.action && /^sign (it )?off\\b/i.test(m.action.text));", PAGE)
        block = PAGE[PAGE.index("const sd = e.target.closest?.('[data-talk-send]')"):PAGE.index("window.addEventListener('keydown', e => {   // on Now, the slash talks")]
        self.assertIn("if (talkSignoff(byId.get(id), m)) { const ag = byId.get(id)?.agent; if (await move(id, 'done')) touch.after('drop', 'done', ag); } else { talkShut.add(id); await quickReply(id, m.action.text); }", block)

    def test_a_new_answer_marks_the_cards_button(self):
        self.assertIn("b.classList.toggle('new', b.dataset.talk !== talkCard && talkNew(b.dataset.talk))", PAGE)



class OrchKnowsHow(unittest.TestCase):
    def test_the_boot_prompt_says_how_to_answer_a_card_conversation(self):
        with tempfile.TemporaryDirectory() as d:
            text = prompt.build_orch_prompt([], Path(d))
        self.assertIn('A line that ends "(card <id>)"', text)
        self.assertIn("--card <id> --reply-to <the line's number>", text)
        self.assertIn("--propose", text)
        self.assertIn("never send it yourself", text)
        self.assertIn('"Simpler" means shorter and plainer, not more.', text)
        self.assertIn('"Walk me through this one." is the board asking', text)
        self.assertIn('`--propose "Sign off"`', text)


if __name__ == "__main__":
    unittest.main()
