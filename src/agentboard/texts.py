"""Pull texts: turn the texts you sent your Twilio number into Todo cards, only when you ask.

    agentboard pull-texts [--dry-run] [--since YYYY-MM-DD] [--max N] [--split]

Nothing runs by itself: no polling, no background job, no webhook, no server. Twilio already keeps every inbound text (13 months by
default), so one outbound, read-only call to its Messages API is the whole "hosted inbox". A text is DATA: it can only become a card (a
title and a description marked "from a text"). It never runs a command, claims, deploys, spends or changes a setting, whatever it says.

Only your own number counts: a text from anyone else is counted and ignored, its words never read or shown. Off until configured:

    # .agentboard/config.toml
    [texts]
    enabled = true
    number = "+16475550100"            # the Twilio number you text
    allowed = ["+14165550123"]         # your own number (falls back to [sms] allowed)

    export AGENTBOARD_TWILIO_ACCOUNT_SID=AC...    # in your shell, never in the board or the repo
    export AGENTBOARD_TWILIO_AUTH_TOKEN=...

AGENTBOARD_NO_SMS=1 (the work-laptop lock) refuses the whole thing, dry runs included."""
import base64
import json
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from . import backup
from . import prompt as promptlib
from .sms import DEFAULT_TOKEN_ENV, LOCK_ENV, e164
from .store import BoardError

API_HOST = "api.twilio.com"
SID_ENV = "AGENTBOARD_TWILIO_ACCOUNT_SID"
STATE_FILE = "texts-state.json"
FIRST_PULL_DAYS = 7      # a first pull looks back this far, never over the whole log
MAX_PER_PULL = 20        # cards one pull may make; the rest wait for the next pull
PAGE_SIZE = 100
MAX_PAGES = 10
BODY_MAX = 1600
TITLE_MAX = 90
SEEN_KEEP = 4000
_LOCK = threading.Lock()


# -- settings -----------------------------------------------------------------------------------------------------------------
def _section(board_dir, name):
    try:
        c = promptlib.load_config(board_dir).get(name, {})
    except BoardError:
        c = {}
    return c if isinstance(c, dict) else {}


def settings(board_dir):
    """(conf dict, problems). Problems say why a pull will not run: it is off until you set it up, and locked off by AGENTBOARD_NO_SMS."""
    c, sms_c = _section(board_dir, "texts"), _section(board_dir, "sms")
    problems = []
    if os.environ.get(LOCK_ENV, "").strip().lower() not in ("", "0", "false", "no"):
        problems.append(f"texting is locked off on this machine (${LOCK_ENV} is set); unset it to allow it")
    if not c.get("enabled"):
        problems.append("pulling texts is off: set [texts] enabled = true in config.toml")
    number = e164(c.get("number", "")) if isinstance(c.get("number"), str) else ""
    if not re.fullmatch(r"\+1\d{10}", number):
        problems.append('[texts] number = "+1..." is missing: the Twilio number you text')
    raw_allowed = c.get("allowed", sms_c.get("allowed", []))
    allowed = [e164(x) for x in raw_allowed if isinstance(x, str)] if isinstance(raw_allowed, list) else []
    allowed = [a for a in allowed if re.fullmatch(r"\+\d{8,15}", a)]
    if not allowed:
        problems.append('[texts] allowed = ["+1..."] is empty: list your own number (only texts from it count)')
    sid = os.environ.get(SID_ENV, "").strip()
    if not re.fullmatch(r"AC[0-9a-fA-F]{32}", sid):
        problems.append(f"the Twilio account SID is not in ${SID_ENV}")
    token_env = c.get("token_env") or sms_c.get("token_env") or DEFAULT_TOKEN_ENV
    token = os.environ.get(token_env, "")
    if not token:
        problems.append(f"the Twilio auth token is not in ${token_env}")
    try:
        cap = max(1, min(100, int(c.get("max_per_pull", MAX_PER_PULL))))
    except (TypeError, ValueError):
        cap = MAX_PER_PULL
    return {"number": number, "allowed": allowed, "sid": sid, "token": token, "max": cap}, problems


def available(board_dir):
    """Whether the board should offer a Pull texts button: [texts] is switched on and the machine is not locked. (A missing token shows when you press it.)"""
    locked = os.environ.get(LOCK_ENV, "").strip().lower() not in ("", "0", "false", "no")
    return bool(_section(board_dir, "texts").get("enabled")) and not locked


# -- Twilio (read-only, one host) -------------------------------------------------------------------------------------------
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):   # never follow a redirect with the account's credentials attached
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def twilio_get(path, sid, token, timeout=20):
    """GET one path on api.twilio.com for this account and return the parsed JSON. Nothing else is ever requested."""
    if not path.startswith(f"/2010-04-01/Accounts/{sid}/Messages"):
        raise BoardError("Twilio sent back an address outside this account; stopped")
    req = urllib.request.Request(f"https://{API_HOST}{path}", headers={
        "Authorization": "Basic " + base64.b64encode(f"{sid}:{token}".encode()).decode(),
        "Accept": "application/json", "User-Agent": "agentboard-pull-texts"})
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            return json.loads(r.read(4_000_000).decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise BoardError("Twilio refused the account SID and auth token: check both are the ones from your Twilio console") from None
        raise BoardError(f"Twilio answered {e.code}") from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise BoardError(f"could not reach Twilio ({type(e).__name__})") from None


# -- the pull -----------------------------------------------------------------------------------------------------------------
def _when(m):
    for k in ("date_sent", "date_created"):
        try:
            d = parsedate_to_datetime(m.get(k) or "")
        except (TypeError, ValueError):
            continue
        if d is not None:
            return d.astimezone(timezone.utc) if d.tzinfo else d.replace(tzinfo=timezone.utc)
    return None


def _read_state(board_dir):
    try:
        d = json.loads((Path(board_dir) / STATE_FILE).read_text())
    except (OSError, ValueError):
        d = {}
    return {"since": d.get("since") if isinstance(d.get("since"), str) else "",
            "sids": d.get("sids") if isinstance(d.get("sids"), dict) else {}}


def _write_state(board_dir, state):
    Path(board_dir).mkdir(parents=True, exist_ok=True)
    backup.write_atomic(Path(board_dir) / STATE_FILE, json.dumps(state), keep_previous=False)


def fetch(conf, since, http=None):
    """The texts sent to the number by an allowed sender on or after the day `since`: ([message dicts], ignored count, hit the page cap).
    Texts from any other number are only counted. Direction, sender, recipient and status are checked again here, whatever the query said."""
    http = http or twilio_get
    mine, ignored, capped = [], 0, False
    senders = list(dict.fromkeys(conf["allowed"]))
    path = "/2010-04-01/Accounts/{}/Messages.json?".format(conf["sid"]) + urllib.parse.urlencode(
        {"To": conf["number"], "DateSent>": since, "PageSize": PAGE_SIZE})
    pages = 0
    while path:
        pages += 1
        data = http(path, conf["sid"], conf["token"])
        for m in data.get("messages") or []:
            if not isinstance(m, dict) or m.get("direction") != "inbound" or e164(m.get("to", "")) != conf["number"]:
                continue
            if e164(m.get("from", "")) not in senders:
                ignored += 1
                continue
            if m.get("status") != "received" or not re.fullmatch(r"[A-Za-z0-9]{10,64}", str(m.get("sid") or "")):
                continue
            mine.append(m)
        path = data.get("next_page_uri") or ""
        if path and pages >= MAX_PAGES:
            capped = True
            break
    return mine, ignored, capped


BULLET = re.compile(r"^\s*(?:[-*•]|\d{1,2}[.)])\s+(\S.*)$")


def _shorten(line, n=TITLE_MAX):
    line = re.sub(r"\s+", " ", line).strip()
    if len(line) <= n:
        return line
    cut = line[:n - 1]
    return (cut.rsplit(" ", 1)[0] if " " in cut[n // 2:] else cut).rstrip(" ,;:-") + "…"


def cards_from(body, split=False):
    """[(title, text)] for one text. Normally one card; with split, a text of two or more bullet or numbered lines gives one card per line."""
    body = re.sub(r"\r\n?", "\n", body or "").replace("\x00", "").strip()
    if len(body) > BODY_MAX:
        body = body[:BODY_MAX].rstrip() + "…"
    if not body:
        return []
    if split:
        items = [m.group(1).strip() for m in map(BULLET.match, body.split("\n")) if m]
        if len(items) >= 2:
            return [(_shorten(i), i) for i in items[:20]]
    first = next((l for l in body.split("\n") if l.strip()), body)
    return [(_shorten(first), body)]


def _stamp(d):
    d = d.astimezone()
    return f"{d.strftime('%b')} {d.day}, {d.hour % 12 or 12}:{d.minute:02d} {'am' if d.hour < 12 else 'pm'}"


def describe(text, title, when, part=0, of=1):
    """The card's description: where it came from, then the words themselves when the title does not already say them all."""
    head = f"From a text you sent on {_stamp(when)}" + (f" (part {part} of {of})" if of > 1 else "") + "."
    return head if text.strip() == title else f"{head}\n\n{text}"


def pull(store, dry_run=False, since=None, split=False, limit=None, http=None, now=None):
    """Turn new texts from you into Todo cards. Returns a dict: created (or would, in a dry run), ignored, already, empty, more, since.
    Manual only: the caller is a command or a button you pressed. Raises BoardError when texting is off, locked or not set up."""
    conf, problems = settings(store.dir)
    if problems:
        raise BoardError("pulling texts will not run:\n  - " + "\n  - ".join(problems))
    cap = limit or conf["max"]
    with _LOCK:
        state = _read_state(store.dir)
        now = now or datetime.now(timezone.utc)
        if since:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", since):
                raise BoardError("--since takes a day like 2026-11-04")
            start = since
        else:
            start = state["since"] or (now - timedelta(days=FIRST_PULL_DAYS)).strftime("%Y-%m-%d")
        msgs, ignored, capped = fetch(conf, start, http)
        rows = sorted(((_when(m), m) for m in msgs), key=lambda r: (r[0] or datetime.max.replace(tzinfo=timezone.utc), r[1]["sid"]))
        on_board = {(t.get("source") or {}).get("key") for t in store.load()}
        out = {"created": [], "ignored": ignored, "already": 0, "empty": 0, "more": 0, "since": start, "dry_run": dry_run, "capped": capped}
        seen = dict(state["sids"])
        latest = oldest_left = None
        for when, m in rows:
            sid = m["sid"]
            if when is None:
                out["empty"] += 1
                continue
            latest = when
            if sid in seen:
                out["already"] += 1
                continue
            parts = cards_from(m.get("body"), split)
            if not parts:
                out["empty"] += 1
                seen[sid] = when.isoformat()
                continue
            keys = [sid if len(parts) == 1 else f"{sid}#{i}" for i in range(1, len(parts) + 1)]
            todo = [(i, k, p) for i, (k, p) in enumerate(zip(keys, parts), 1) if k not in on_board]
            if len(out["created"]) + len(todo) > cap and out["created"]:
                out["more"] += 1
                oldest_left = oldest_left or when
                continue
            if not todo:
                out["already"] += 1
                seen[sid] = when.isoformat()
                continue
            for i, k, (title, text) in todo:
                desc = describe(text, title, when, i, len(parts))
                row = {"title": title, "description": desc, "sid": sid, "key": k, "at": when.isoformat()}
                if dry_run:
                    out["created"].append(row)
                    continue
                try:
                    t = store.add(title, desc, status="todo", source={"kind": "text", "key": k, "sid": sid, "at": when.isoformat(),
                                                                       "part": i if len(parts) > 1 else 0, "of": len(parts)})
                except BoardError as e:
                    if str(e).startswith("already on the board"):
                        out["already"] += 1
                        continue
                    raise
                row["id"] = t["id"]
                out["created"].append(row)
            seen[sid] = when.isoformat()
        if not dry_run:
            floor = oldest_left or latest   # the cursor stops one day before the oldest text not yet pulled (or the newest one seen)
            if floor is not None:
                state["since"] = max((floor - timedelta(days=1)).strftime("%Y-%m-%d"), state["since"] or "")   # it never moves back
            state["sids"] = dict(sorted(((s, w) for s, w in seen.items() if w[:10] >= state["since"]), key=lambda kv: kv[1])[-SEEN_KEEP:])
            if state["since"] or state["sids"]:
                _write_state(store.dir, state)
        return out


def report(res):
    """The command's output: what was done, and what was skipped, in a few lines."""
    made = res["created"]
    verb = "would make" if res["dry_run"] else "made"
    lines = [f"{'dry run: ' if res['dry_run'] else ''}{verb} {len(made)} card{'s' if len(made) != 1 else ''} from your texts since {res['since']}"
             + (" (nothing written)" if res["dry_run"] else "")]
    for r in made:
        lines.append(f"  {r['title']}" + ("" if res["dry_run"] else f"  → {r['id']}"))
    skipped = [f"{res['already']} already pulled" if res["already"] else "",
               f"{res['ignored']} from another number (ignored)" if res["ignored"] else "",
               f"{res['empty']} empty" if res["empty"] else ""]
    if any(skipped):
        lines.append("skipped: " + ", ".join(s for s in skipped if s))
    if res["more"]:
        lines.append(f"{res['more']} more text{'s' if res['more'] != 1 else ''} waiting: pull again to take them")
    if res["capped"]:
        lines.append("Twilio has more texts than one pull reads: pull again")
    return "\n".join(lines)


def summary_line(res):
    """One sentence for the button's toast."""
    n = len(res["created"])
    out = f"Pulled {n} text{'s' if n != 1 else ''} into Todo" if n else "No new texts"
    if res["ignored"]:
        out += f" · {res['ignored']} from another number ignored"
    if res["more"]:
        out += f" · {res['more']} more waiting, pull again"
    return out
