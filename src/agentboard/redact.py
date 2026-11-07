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
import bisect
import re
import tomllib
from pathlib import Path

# Control (but not tab, newline, carriage return), format (zero-width, bidi, soft hyphen, tag), private-use and surrogate code points: invisible, or
# able to split a key so that a pattern no longer sees it ("sk-" + zero-width space + key): the set untrusted.text_lines drops, plus the invisible
# fillers, joiners and variation selectors. Only the COPY used for matching loses them: the text you store keeps every one it had.
_INVISIBLE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\xad\u034f\u0600-\u0605\u061c\u06dd\u070f\u08e2\u115f\u1160\u17b4\u17b5\u180b-\u180e\u200b-\u200f\u202a-\u202e\u2060-\u2064"
                        r"\u2066-\u206f\u2800\u3164\ufe00-\ufe0f\ufeff\uffa0\ufff9-\ufffb\ue000-\uf8ff\ud800-\udfff\U000110bd\U000110cd\U00013430-\U0001343f\U0001bca0-\U0001bca3"
                        r"\U0001d173-\U0001d17a\U000e0001\U000e0020-\U000e007f\U000e0100-\U000e01ef\U000f0000-\U000ffffd\U00100000-\U0010fffd]")
MAX_HIDDEN = 5000    # a text with more invisible characters than this is not prose: they are dropped instead of being mapped around

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


def _secret_like(v):
    """A value that looks generated: a letter and a digit together, or base64 padding. Plain words never do."""
    return _has_letter_and_digit(v) or v.endswith("=")


_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_WORDY = re.compile(r"[a-z0-9]+(?:[_.-][a-z0-9]+)+")    # snake_case and kebab-case names: identifiers, not keys


def _random_like(v):
    """For a generic name (key, auth, token): long, a letter and a digit, and not a lower-case identifier like user_profile_cache_v2_final."""
    if _UUID.fullmatch(v):
        return True
    return len(v) >= 20 and _has_letter_and_digit(v) and not _WORDY.fullmatch(v)


_PASSWORD_WORDS = {"password", "pass", "passwd", "pwd", "secret", "user", "username", "token", "changeme", "yourpassword", "your-password", "mypassword"}


def _url_password(m):
    """scheme://user:PASSWORD@host: the password goes, the rest stays; a documented placeholder (user:password@host) is left."""
    value = m.group(2)
    if value.lower() in _PASSWORD_WORDS or PLACEHOLDER.search(value) or re.fullmatch(r"[*xX\u2022.\-]+", value):
        return m.group(0)
    return m.group(1) + _mask("password") + m.group(3)


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
    ("stripe-key", re.compile(r"(?<![A-Za-z0-9])(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{20,}"), _whole("stripe-key")),
    ("webhook-secret", re.compile(r"(?<![A-Za-z0-9])whsec_[A-Za-z0-9+/=]{20,}"), _whole("webhook-secret")),
    ("google-key", re.compile(r"(?<![A-Za-z0-9_-])AIza[0-9A-Za-z_-]{35}(?![0-9A-Za-z_-])"), _whole("google-key")),
    ("slack-webhook", re.compile(r"(?:https?://)?hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+"), _whole("slack-webhook")),
    ("npm-token", re.compile(r"(?<![A-Za-z0-9_])npm_[A-Za-z0-9]{36}(?![A-Za-z0-9])"), _whole("npm-token")),
    ("sendgrid-key", re.compile(r"(?<![A-Za-z0-9_-])SG\.[A-Za-z0-9_-]{16,}+\.[A-Za-z0-9_-]{16,}+"), _whole("sendgrid-key")),
    ("url-password", re.compile(r"(://[^\s:/@]++:)([^\s@/]++)(@)"), _url_password),
    ("bearer", re.compile(r"(?<![A-Za-z])(Bearer\s++)([A-Za-z0-9._~+/=-]{20,}+)"), _keep_prefix("secret", _secret_like)),
    ("key-hex", re.compile(r"((?:api[_-]?key|key|token|secret|passwd|password)\W{1,4})([0-9a-fA-F]{32,64})(?![0-9a-fA-F])", re.I), _keep_prefix("hex")),
    ("assigned-secret", re.compile(r"((?:aws[_-]?secret[_-]?access[_-]?key|secret[_-]?access[_-]?key|api[_-]?key|apikey|secret[_-]?key|secret|passwd|password|pwd|auth[_-]?token|access[_-]?token|refresh[_-]?token|client[_-]?secret|app[_-]?secret|private[_-]?token|signing[_-]?(?:key|secret))[\"']?\s*+[:=]\s*+[\"']?)([A-Za-z0-9/+_=.~-]{16,}+)", re.I),
     _keep_prefix("secret", _has_letter_and_digit)),
    ("generic-secret", re.compile(r"((?<![A-Za-z0-9])(?:key|auth|token|credentials?|access[_-]?key)[\"']?\s*+[:=]\s*+[\"']?)([A-Za-z0-9/+_=.~-]{20,}+)", re.I),
     _keep_prefix("secret", _random_like)),
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


def _sub_visible(rx, repl, text):
    """rx.sub(repl, text), but matching on a copy without the invisible characters and replacing in the original by the matched span:
    a key that carries a zero-width space is masked whole, and everything else (a ZWJ in an emoji, a ZWNJ in Persian) stays as written."""
    hidden = [m.start() for m in _INVISIBLE.finditer(text)]
    if not hidden:
        return rx.sub(repl, text)
    clean = _INVISIBLE.sub("", text)
    q = [p - j for j, p in enumerate(hidden)]     # q[j]: the clean index where the j-th hidden character was taken out

    def orig(c):
        return c + bisect.bisect_right(q, c)       # clean index to original index: add the hidden characters before it
    out, last = [], 0
    for m in rx.finditer(clean):
        r = repl(m)
        if r == m.group(0):                        # left as it is: the original, invisible characters and all, stays
            continue
        a, b = orig(m.start()), orig(m.end() - 1) + 1
        out.append(text[last:a])
        out.append(r)
        last = b
    out.append(text[last:])
    return "".join(out)


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
    if sum(1 for _ in _INVISIBLE.finditer(text)) > MAX_HIDDEN:
        text = _INVISIBLE.sub("", text)
    for kind, rx, fn in SHAPES:
        text = _sub_visible(rx, note(kind, fn), text)
    if conf["phones"]:
        text = _sub_visible(PHONE, note("phone", lambda m: m.group(0) if _fictional(m.group(0)) else _mask("phone")), text)
    for rx in _extras(conf):
        text = _sub_visible(rx, note("extra", lambda m: _mask("match")), text)
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
