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
REPLY_MAX = 300

HELP = ("add: <title> | later: <title> | done <id> | start <id> | review <id> | todo <id> | later <id> | status | list | help. "
        "<id> can be the first letters.")


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
    return out + (" Up: " + ", ".join(names) + "." if names else "")


def apply(store, text):
    """Run one command text against the board and return the one-line reply. Never raises for a bad command."""
    try:
        return _apply(store, text)
    except BoardError as e:
        return f"No: {e}"[:REPLY_MAX]


def _apply(store, text):
    raw = (text or "").strip()
    if not raw:
        return HELP
    m = re.match(r"^([A-Za-z]+)\s*[:\-]?\s*(.*)$", raw, re.S)
    cmd, arg = (m.group(1).lower(), m.group(2).strip()) if m else ("", raw)
    if cmd in ("help", "?", "commands"):
        return HELP
    if cmd in ("status", "s"):
        return status_line(store)
    if cmd in ("list", "ls"):
        doing = [t for t in store.load() if t["status"] == "doing" and not t.get("archived") and not t.get("parent_id")][:5]
        return ("Doing: " + "; ".join(f"{t['id']} {t.get('progress', 0)}%" for t in doing)) if doing else "Nothing in progress."
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
    return f"Don't know '{cmd}'. {HELP}"[:REPLY_MAX]


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
