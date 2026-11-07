"""Secrets never reach the board's files (sec-data-redact-store).

A key an agent echoes in an update, a token in a command it ran, a private key in a review body: none of it is ordinary text, and
the board copies card text into tasks.json, its .bak, every backup, the card's report, the page and the chat. So text from agents is
masked where it enters the store, and again when a report is built.

Only strings that cannot be ordinary text are masked by default: cloud and API keys with their well-known prefixes, tokens, JWTs,
private-key blocks, Authorization header values, `api_key = "…"`-style assignments, and a long hex string right after the word key,
token or secret. A commit hash, a card id, a path or a sentence is never touched. What it leaves in place is what you read:
`Authorization: Token [redacted]`, `sk-[redacted api-key]`.

    # .agentboard/config.toml
    [redact]
    enabled = true          # false turns every mask off
    phones = false          # also mask phone numbers (off: the lawyer's number on a card is meant to be read)
    extra = ["ACME-[0-9]{6}"]   # your own patterns; each match becomes [redacted]

What you type yourself (a reply, a send-back note, a chat line from the owner) is left as written: you chose to say it.
`agentboard redact` shows what is already stored; `agentboard redact --apply` masks it (after a snapshot)."""
import re
import tomllib
from pathlib import Path

PLACEHOLDER = re.compile(r"^[xX*._\-]+$|EXAMPLE|\$\{?\w|<[^>]*>|\{\w+\}|changeme|placeholder|dummy|redacted|^your[-_]", re.I)
_CACHE = {}

DEFAULTS = {"enabled": True, "phones": False, "extra": []}


def _few_kinds(s):
    """A run made of one, two or three distinct characters (ACbbbb…, 000…, aaaa…) is a placeholder, never a key."""
    return len(set(s)) <= 3


def _mask(kind):
    return f"[redacted {kind}]"


def _keep_prefix(kind, check=None):
    """Replace group 2 and keep group 1 (the part you read: `Authorization: Token `, `api_key = "`)."""
    def repl(m):
        value = m.group(2)
        if _few_kinds(value) or PLACEHOLDER.search(value) or (check and not check(value)):
            return m.group(0)
        return m.group(1) + _mask(kind)
    return repl


def _whole(kind, check=None):
    def repl(m):
        v = m.group(0)
        if _few_kinds(v.lstrip("ACSKsk-")) or PLACEHOLDER.search(v) or (check and not check(v)):
            return v
        return _mask(kind)
    return repl


def _has_letter_and_digit(v):
    return any(c.isdigit() for c in v) and any(c.isalpha() for c in v)


# (kind, pattern, replacement function). Order matters: a private-key block first, then headers, then the rest.
SHAPES = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S), lambda m: _mask("private-key")),
    ("auth-header", re.compile(r"(Authorization:\s*(?:Token|Bearer|Basic)\s+)([A-Za-z0-9._=+/~-]{10,})", re.I), _keep_prefix("secret")),
    ("jwt", re.compile(r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{10,}+\.[A-Za-z0-9_-]{10,}+\.[A-Za-z0-9_-]{10,}+"), _whole("jwt")),   # lookbehind + possessive: the text eyJeyJeyJ... was quadratic (44 s for 400 KB)
    ("aws-key", re.compile(r"AKIA[0-9A-Z]{16}"), _whole("aws-key")),
    ("api-key", re.compile(r"sk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}"), _whole("api-key")),
    ("github-token", re.compile(r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}"), _whole("github-token")),
    ("slack-token", re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}"), _whole("slack-token")),
    ("account-sid", re.compile(r"(?<![A-Za-z0-9])(?:AC|SK)[0-9a-f]{32}(?![A-Za-z0-9])"), _whole("account-sid")),
    ("key-hex", re.compile(r"((?:api[_-]?key|key|token|secret|passwd|password)\W{1,4})([0-9a-fA-F]{32,64})(?![0-9a-fA-F])", re.I), _keep_prefix("hex")),
    ("assigned-secret", re.compile(r"((?:api[_-]?key|secret|passwd|password|auth[_-]?token|access[_-]?token|client[_-]?secret)[\"']?\s*[:=]\s*[\"']?)([A-Za-z0-9/+_=.~-]{16,})", re.I),
     _keep_prefix("secret", _has_letter_and_digit)),
]

PHONE = re.compile(r"(?<![\d.])(?:\(?[2-9]\d{2}\)?[ .-]\d{3}[ .-]\d{4}|\+1[ ]?\d{10})(?!\d)")


def _fictional(num):
    d = re.sub(r"\D", "", num)
    d = d[1:] if len(d) == 11 and d[0] == "1" else d
    return d[:3] == "555" or (d[3:6] == "555" and d[6:].startswith("01"))


def settings(board_dir):
    """[redact] from config.toml (cached by the file's modification time), with the defaults filled in."""
    out = dict(DEFAULTS, extra=[])
    if board_dir is None:
        return out
    path = Path(board_dir) / "config.toml"
    try:
        mt = path.stat().st_mtime_ns
    except OSError:
        return out
    hit = _CACHE.get(str(path))
    if hit and hit[0] == mt:
        return hit[1]
    try:
        sect = tomllib.loads(path.read_text()).get("redact", {})
    except (OSError, ValueError):
        sect = {}
    if isinstance(sect, dict):
        out["enabled"] = sect.get("enabled", True) is not False
        out["phones"] = sect.get("phones") is True
        out["extra"] = [p for p in sect.get("extra", []) if isinstance(p, str) and p] if isinstance(sect.get("extra"), list) else []
    _CACHE[str(path)] = (mt, out)
    return out


def _extras(conf):
    rxs = []
    for p in conf["extra"]:
        try:
            rxs.append(re.compile(p))
        except re.error:
            rxs.append(re.compile(re.escape(p)))
    return rxs


def head(text, limit):
    """The text cut to `limit` characters at a word boundary (a token cut in half is never left to look like half a key)."""
    if not isinstance(text, str) or len(text) <= limit:
        return text
    cut = text[:limit]
    if not text[limit].isspace():
        tail = cut[-256:]
        i = max(tail.rfind(" "), tail.rfind("\n"), tail.rfind("\t"))
        if i >= 0:
            cut = cut[:len(cut) - len(tail) + i]
    return cut


def scrub(text, board_dir=None, conf=None, found=None, bound=None):
    """The text with secret-shaped strings masked. Anything that is not a string comes back as it was. `found`, when given a list,
    gets (kind, first four characters) for each thing masked. `bound`: look at no more than this many characters (the rest is
    dropped), so the work stays small however large the text; callers pass twice the cap they are about to apply."""
    if not isinstance(text, str) or not text:
        return text
    if bound:
        text = head(text, bound)
    conf = conf or settings(board_dir)
    if not conf["enabled"]:
        return text

    def note(kind, fn):
        def wrapped(m):
            r = fn(m)
            if found is not None and r != m.group(0):
                found.append((kind, m.group(0)[:4]))
            return r
        return wrapped
    for kind, rx, fn in SHAPES:
        text = rx.sub(note(kind, fn), text)
    if conf["phones"]:
        text = PHONE.sub(note("phone", lambda m: m.group(0) if _fictional(m.group(0)) else _mask("phone")), text)
    for rx in _extras(conf):
        text = rx.sub(note("extra", lambda m: _mask("match")), text)
    return text


TASK_TEXT_FIELDS = ("title", "description", "result", "status_text", "question", "body_md")


def scrub_task(task, board_dir):
    """A copy of a card with its prose fields and log lines masked (for a report built from older data)."""
    conf = settings(board_dir)
    if not conf["enabled"]:
        return task
    out = dict(task)
    for f in TASK_TEXT_FIELDS:
        if isinstance(out.get(f), str):
            out[f] = scrub(out[f], conf=conf)
    if isinstance(out.get("log"), list):
        out["log"] = [dict(e, text=scrub(e.get("text"), conf=conf)) if isinstance(e, dict) else e for e in out["log"]]
    return out


def scrub_data(data, board_dir, apply=False, owner=None):
    """Walk a whole board file (cards, their log lines, chat). Returns [(where, kind, first four characters)] for everything that is
    secret-shaped; with apply=True the data is changed in place. What the owner typed (their log lines, their chat lines) is skipped."""
    conf = settings(board_dir)
    hits = []
    if not conf["enabled"]:
        return hits

    def one(where, d, key):
        v = d.get(key)
        found = []
        new = scrub(v, conf=conf, found=found)
        for kind, head in found:
            hits.append((where, kind, head))
        if apply and new != v:
            d[key] = new
    for t in data.get("tasks", []):
        for f in TASK_TEXT_FIELDS:
            one(f"card {t.get('id')} {f}", t, f)
        for i, e in enumerate(t.get("log", [])):
            if isinstance(e, dict) and not (owner and e.get("by") == owner):
                one(f"card {t.get('id')} log #{i + 1}", e, "text")
    for m in data.get("chat", []):
        if isinstance(m, dict) and m.get("kind") != "user":
            for f in ("text", "detail"):
                one(f"chat #{m.get('seq')} {f}", m, f)
    return hits
