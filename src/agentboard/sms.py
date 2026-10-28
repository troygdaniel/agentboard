"""Text the board: a tiny inbound-SMS (Twilio webhook) endpoint with its own port, so a tunnel can point at it and nothing else.

    agentboard sms serve [--port 8766]       # POST /sms (Twilio), GET /health
    agentboard sms try "add: buy toothpaste" # run a command text locally, no Twilio, no network

Off until config.toml says so ([sms] enabled = true) AND the Twilio auth token is in the environment (never in a file in the board).
Every request must carry a valid X-Twilio-Signature, come from an allowlisted number, and have a MessageSid not seen before.
It only ever replies in the HTTP response (TwiML): it never calls the Twilio API, so there is nothing to spend beyond the text itself."""
import base64
import hashlib
import hmac
import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs
from xml.sax.saxutils import escape

from . import backup
from . import prompt as promptlib
from .store import BoardError

MAX_BODY = 16_000
SEEN_TTL_S = 7 * 24 * 3600
SEEN_MAX = 2000
DEFAULT_TOKEN_ENV = "AGENTBOARD_TWILIO_AUTH_TOKEN"
LOCK_ENV = "AGENTBOARD_NO_SMS"   # set on a machine (a work laptop) where texting must never start, whatever any config says
REPLY_MAX = 160   # one sentence, one idea

HELP = "Text a task to add it. Ask: status, ready, blocked, today, asks, or status of <card or agent>. Answer: reply <text>."
YES_NO = {"yes", "no", "y", "n", "ok", "okay", "go", "stop", "yep", "nope", "sure", "approve", "approved", "reject", "later", "now"}
QUESTION_START = {"what", "whats", "what's", "which", "who", "how", "where", "when", "is", "are", "any", "anything", "show", "tell"}


# -- config -------------------------------------------------------------------------------------------------------------------
def e164(n):
    """'416-555-0123', '(416) 555 0123', '+1 416 555 0123' -> '+14165550123'. Anything else is returned stripped, so it can never match by accident."""
    digits = re.sub(r"\D", "", n or "")
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return "+" + digits if (n or "").strip().startswith("+") and digits else (n or "").strip()


def load_conf(board_dir):
    try:
        c = promptlib.load_config(board_dir).get("sms", {})
    except BoardError:
        c = {}
    return c if isinstance(c, dict) else {}


def settings(board_dir):
    """(conf dict, problems). Problems say why the endpoint will not start: it is off by default."""
    c = load_conf(board_dir)
    problems = []
    if os.environ.get(LOCK_ENV, "").strip().lower() not in ("", "0", "false", "no"):
        problems.append(f"texting is locked off on this machine (${LOCK_ENV} is set); unset it to allow it")
    if not c.get("enabled"):
        problems.append("texting is off: set [sms] enabled = true in config.toml")
    allowed = [e164(x) for x in c.get("allowed", []) if isinstance(x, str)]
    if not allowed:
        problems.append('[sms] allowed = ["+1..."] is empty: list the number(s) that may text the board')
    url = c.get("public_url", "")
    if not (isinstance(url, str) and url.startswith("https://")):
        problems.append("[sms] public_url must be the https URL Twilio calls (e.g. https://<tunnel>/sms): it is part of the signature")
    token = os.environ.get(c.get("token_env") or DEFAULT_TOKEN_ENV, "")
    if not token:
        problems.append(f"the Twilio auth token is not in ${c.get('token_env') or DEFAULT_TOKEN_ENV}")
    return {"allowed": allowed, "public_url": url, "token": token, "rate_per_hour": int(c.get("rate_per_hour", 30)), "name": c.get("name", "Troy")}, problems


# -- the signature ------------------------------------------------------------------------------------------------------------
def signature(token, url, params):
    """Twilio's: base64(HMAC-SHA1(token, url + for each POST field sorted by name: name + value))."""
    data = url
    for k in sorted(params):
        for v in sorted(params[k]):
            data += k + v
    return base64.b64encode(hmac.new(token.encode(), data.encode(), hashlib.sha1).digest()).decode()


def valid_signature(token, url, params, header):
    return bool(token and header) and hmac.compare_digest(signature(token, url, params), header)


# -- replay and rate ----------------------------------------------------------------------------------------------------------
_LOCK = threading.Lock()   # one process serves the webhook: two texts at once must not lose each other's record


class Seen:
    """MessageSids already handled (and when commands ran, for the hourly cap), kept in .agentboard/sms-state.json."""

    def __init__(self, board_dir):
        self.path = os.path.join(str(board_dir), "sms-state.json")

    def _read(self):
        try:
            return json.loads(Path(self.path).read_text())
        except (OSError, ValueError):
            return {"sids": {}, "times": []}

    def check_and_record(self, sid, rate_per_hour, now=None):
        """'ok' (recorded), 'replay' or 'rate'. A replayed MessageSid is never applied twice."""
        with _LOCK:
            return self._check(sid, rate_per_hour, now or time.time())

    def _check(self, sid, rate_per_hour, now):
        d = self._read()
        d["sids"] = {k: v for k, v in d.get("sids", {}).items() if now - v < SEEN_TTL_S}
        d["times"] = [t for t in d.get("times", []) if now - t < 3600]
        if sid in d["sids"]:
            return "replay"
        if len(d["times"]) >= rate_per_hour:
            return "rate"
        d["sids"][sid] = now
        d["times"].append(now)
        if len(d["sids"]) > SEEN_MAX:
            d["sids"] = dict(sorted(d["sids"].items(), key=lambda kv: kv[1])[-SEEN_MAX:])
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        backup.write_atomic(Path(self.path), json.dumps(d), keep_previous=False)
        return "ok"


# -- the commands -------------------------------------------------------------------------------------------------------------
def _resolve(store, ref, statuses=None):
    ref = ref.strip().lower()
    tasks = [t for t in store.load() if not t.get("archived") and not t.get("parent_id") and (statuses is None or t["status"] in statuses)]
    exact = [t for t in tasks if t["id"] == ref]
    if exact:
        return exact[0]
    hits = [t for t in tasks if t["id"].startswith(ref)] if ref else []
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise BoardError(f"no card starting with '{ref}'")
    raise BoardError("which one? " + ", ".join(t["id"] for t in hits[:4]))


def status_line(store):
    tasks = [t for t in store.load() if not t.get("archived") and not t.get("parent_id")]
    n = lambda st: sum(1 for t in tasks if t["status"] == st)
    asks = [t for t in tasks if t["status"] == "doing" and t.get("needs_input")]
    revs = [t for t in tasks if t["status"] == "doing" and t.get("review")]
    out = f"{n('doing')} doing, {len(asks)} need you, {len(revs)} to review, {n('todo')} todo, {n('backlog')} later."
    names = [t["id"] for t in asks + revs][:3]
    return _clip(out + (" Up: " + ", ".join(names) + "." if names else ""))


def apply(store, text):
    """Run one command text against the board and return the one-line reply. Never raises for a bad command."""
    try:
        return _apply(store, text)
    except BoardError as e:
        return f"No: {e}"[:REPLY_MAX]


def _clip(text, n=REPLY_MAX):
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    return t if len(t) <= n else t[:n - 1].rstrip() + "…"


def _open(store):
    return [t for t in store.load() if not t.get("archived") and not t.get("parent_id")]


def _asks(store):
    return [t for t in _open(store) if t["status"] == "doing" and t.get("needs_input")]


def _ready(store):
    return [t for t in _open(store) if t["status"] == "doing" and t.get("review")]


def _find(store, ref):
    """Cards a loose reference names: an id or its first letters, an agent's name, or words from the title. [] when nothing."""
    ref = re.sub(r"[?.!]+$", "", ref.strip().lower())
    ref = re.sub(r"^(the|my|card|agent|on|of)\s+", "", ref)
    tasks = _open(store)
    if not ref:
        return []
    for pick in (lambda t: t["id"] == ref, lambda t: t["id"].startswith(ref),
                 lambda t: (t.get("agent") or "").lower() == ref and t["status"] == "doing",
                 lambda t: all(w in t["id"] or w in t["title"].lower() for w in ref.split())):
        hits = [t for t in tasks if pick(t)]
        if hits:
            return hits
    return []


def card_line(t):
    where = {"todo": "in Todo", "backlog": "in Later", "done": "done"}.get(t["status"], "")
    if t["status"] == "doing":
        where = "needs you" if t.get("needs_input") else "ready for review" if t.get("review") else f"{t.get('progress', 0)}%"
        if t.get("agent"):
            where += f" ({t['agent']})"
    note = t.get("question") if t.get("needs_input") else t.get("status_text")
    return _clip(f"{t['id']}: {where}" + (f", {note}" if note else ""))


def what_status(store, ref):
    hits = _find(store, ref)
    if not hits:
        return f"I can't find '{_clip(ref, 30)}'. Try the card id or the agent's name."
    if len(hits) == 1:
        return card_line(hits[0])
    return _clip(f"{len(hits)} cards: " + "; ".join(f"{t['id']} {t.get('progress', 0)}%" for t in hits[:3]))


def what_ready(store):
    r = _ready(store)
    return _clip("Ready for review: " + ", ".join(t["id"] for t in r) + ".") if r else "Nothing is waiting for your review."


def what_asks(store):
    a = _asks(store)
    if not a:
        return "Nothing is waiting on your answer."
    t = a[0]
    more = f" (+{len(a) - 1} more)" if len(a) > 1 else ""
    return _clip(f"{t['id']} asks: {t.get('question')}{more}")


def what_blocked(store):
    by_id = {t["id"]: t for t in store.load()}
    out = []
    for t in _open(store):
        if t["status"] == "done":
            continue
        on = [b for b in t.get("blocked_by") or [] if b in by_id and by_id[b]["status"] != "done"]
        if on:
            out.append(f"{t['id']} waits on {', '.join(on)}")
    return _clip("Blocked: " + "; ".join(out[:3]) + ".") if out else "Nothing is blocked."


def what_today(store):
    today = datetime.now().strftime("%Y-%m-%d")
    started = reviewed = done = 0
    for t in _open(store):
        for e in t.get("log", []):
            if not str(e.get("at", "")).startswith(today) or e.get("by"):
                continue
            txt = str(e.get("text", ""))
            if txt.startswith("Claimed by") or txt.startswith("Started"):
                started += 1
            elif txt.startswith("Ready for review"):
                reviewed += 1
            elif e.get("status") == "done":
                done += 1
    if not (started or reviewed or done):
        return "Nothing has moved today."
    return f"Today: {started} started, {reviewed} sent to review, {done} done."


def answer_ask(store, ref, text):
    """Send Troy's words to an ask card: the agent reads them with `agentboard answer`."""
    asks = _asks(store)
    if ref:
        hits = [t for t in asks if t["id"] == ref.lower() or t["id"].startswith(ref.lower())]
    else:
        hits = asks
    if not hits:
        raise BoardError("nothing is asking you" if not ref else f"no ask matches '{ref}'")
    if len(hits) > 1:
        raise BoardError("which one? " + ", ".join(t["id"] for t in hits[:3]) + ": text 'reply <id> <answer>'")
    store.reply(hits[0]["id"], text, by="Troy (text)")
    return f"Sent to {hits[0].get('agent') or 'the agent'} on {hits[0]['id']}."


def _apply(store, text):
    raw = (text or "").strip()
    if not raw:
        return HELP
    low = raw.lower().rstrip("?!. ")
    m = re.match(r"^([A-Za-z']+)\s*[:\-]?\s*(.*)$", raw, re.S)
    cmd, arg = (m.group(1).lower(), m.group(2).strip()) if m else ("", raw)
    # answering an ask
    if cmd in ("reply", "answer", "re"):
        first, _, rest = arg.partition(" ")
        if rest and any(t["id"] == first.lower() or t["id"].startswith(first.lower()) for t in _asks(store)):
            return answer_ask(store, first, rest.strip())
        if not arg:
            raise BoardError("reply what? e.g. reply yes")
        return answer_ask(store, "", arg)
    if low in YES_NO or re.fullmatch(r"[1-9a-d]", low):
        if _asks(store):
            return answer_ask(store, "", raw)
    # questions
    if cmd in ("help", "?", "commands"):
        return HELP
    if cmd in ("status", "s") and not arg or low in ("status", "how are things", "how's it going", "hows it going"):
        return status_line(store)
    if cmd in ("ready", "review") and not arg or re.search(r"\b(ready|waiting)\b.*\breview\b|\bwhat.*\bto review\b", low):
        return what_ready(store)
    if cmd in ("asks", "ask", "needs", "question", "questions") and not arg or re.search(r"\b(needs? me|asking me|waiting on me|my answer)\b", low):
        return what_asks(store)
    if cmd in ("blocked", "blocks", "blockers") or re.search(r"\bblock(s|ed|ing)\b", low):
        return what_blocked(store)
    if cmd in ("today", "changed", "recap") and not arg or re.search(r"\b(changed|happened|done|moved)\b.*\btoday\b|\btoday\b", low) and cmd in QUESTION_START:
        return what_today(store)
    qm = re.match(r"^(?:status|state|progress|how(?:'s| is)?|where(?:'s| is)?|what(?:'s| is)?)\s+(?:of\s+|on\s+|up with\s+|the status of\s+)?(.+?)(?:\s+(?:doing|going|status))?$", low)
    if (cmd in ("status", "state", "progress", "how", "where", "what", "whats", "what's") or raw.endswith("?")) and qm:
        return what_status(store, qm.group(1))
    if raw.endswith("?") and re.match(r"^(\S+)\s+status$", low):
        return what_status(store, low.split()[0])
    if cmd in ("list", "ls"):
        doing = [t for t in store.load() if t["status"] == "doing" and not t.get("archived") and not t.get("parent_id")][:5]
        return _clip("Doing: " + "; ".join(f"{t['id']} {t.get('progress', 0)}%" for t in doing)) if doing else "Nothing in progress."
    # commands that change a card
    if cmd == "add" or (cmd == "later" and arg and not _looks_like_id(store, arg)):
        if not arg:
            raise BoardError("add what? e.g. add: buy toothpaste")
        status = "backlog" if cmd == "later" else "todo"
        t = store.add(arg[:200], status=status)
        return f"Added to {'Later' if status == 'backlog' else 'Todo'}: {t['id']}"
    if cmd in ("done", "finish"):
        t = _resolve(store, arg, ("todo", "doing", "backlog"))
        store.update(t["id"], status="done")
        return f"{t['id']}: done"
    if cmd in ("start", "doing"):
        t = _resolve(store, arg, ("todo", "backlog"))
        store.move(t["id"], "doing")
        return f"{t['id']}: doing"
    if cmd == "review":
        t = _resolve(store, arg, ("doing",))
        store.review(t["id"], "Marked ready from a text")
        return f"{t['id']}: ready for review"
    if cmd in ("todo", "queue"):
        t = _resolve(store, arg, ("backlog", "doing"))
        store.move(t["id"], "todo")
        return f"{t['id']}: todo"
    if cmd == "later":
        t = _resolve(store, arg, ("todo", "doing"))
        store.move(t["id"], "backlog")
        return f"{t['id']}: later"
    if raw.endswith("?") or (cmd in QUESTION_START and len(raw.split()) > 1):
        return "I can't answer that one. " + HELP
    if len(raw.split()) == 1:   # one unknown word is more likely a typo than a task
        return _clip(f"Don't know '{cmd}'. To add it as a task, text 'add: {raw}'.")
    t = store.add(raw[:200], status="todo")   # plain words are a new card, top of Todo
    return f"Added to Todo: {t['id']}"


def _looks_like_id(store, arg):
    try:
        _resolve(store, arg, ("todo", "doing"))
        return True
    except BoardError:
        return False


# -- the request --------------------------------------------------------------------------------------------------------------
def twiml(text):
    return f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{escape(text[:REPLY_MAX])}</Message></Response>'.encode()


def handle_request(store, conf, params, header, now=None):
    """(http status, body bytes, log line) for one Twilio POST. Order: signature, sender, replay and rate, then the command.
    Anything refused gets no text back, so a stranger learns nothing."""
    sig_ok = valid_signature(conf["token"], conf["public_url"], params, header)
    if not sig_ok:
        return 403, b"", "refused: bad signature"
    sender = e164((params.get("From") or [""])[0])
    if sender not in conf["allowed"]:
        return 403, b"", "refused: sender not allowed"
    sid = (params.get("MessageSid") or params.get("SmsSid") or [""])[0]
    if not re.match(r"^[A-Za-z0-9]{10,64}$", sid):
        return 403, b"", "refused: no usable MessageSid"
    seen = Seen(store.dir).check_and_record(sid, conf["rate_per_hour"], now)
    if seen == "replay":
        return 200, twiml("Already handled that one."), f"replay ignored: {sid}"
    if seen == "rate":
        return 200, twiml("Too many commands this hour; try again later."), "rate limited"
    body = (params.get("Body") or [""])[0]
    reply = apply(store, body)
    return 200, twiml(reply), f"{sid}: {body[:60]!r} -> {reply[:80]!r}"


def make_handler(store, conf, log=print):
    class Handler(BaseHTTPRequestHandler):
        server_version = "agentboard-sms"

        def log_message(self, *args):
            pass

        def _send(self, code, body=b"", ctype="text/xml; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self._send(200 if self.path == "/health" else 404, b"ok" if self.path == "/health" else b"", "text/plain")

        def do_POST(self):
            if self.path.split("?")[0] != "/sms":
                self._send(404)
                return
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if n < 0 or n > MAX_BODY:
                    self._send(413)
                    return
                params = parse_qs(self.rfile.read(n).decode("utf-8", "replace"), keep_blank_values=True)
            except (ValueError, UnicodeError):
                self._send(400)
                return
            code, body, line = handle_request(store, conf, params, self.headers.get("X-Twilio-Signature", ""))
            log(f"sms: {code} {line}")
            self._send(code, body)

    return Handler


def serve(store, port=8766):
    conf, problems = settings(store.dir)
    if problems:
        raise BoardError("the SMS endpoint will not start:\n  - " + "\n  - ".join(problems))
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(store, conf))
    print(f"agentboard sms: listening on http://127.0.0.1:{port}/sms for {conf['public_url']}\n"
          f"  board: {store.dir}\n  allowed: {', '.join(conf['allowed'])}\n  Ctrl+C to stop")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
