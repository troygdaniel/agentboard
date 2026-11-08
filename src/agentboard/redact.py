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
import base64
import binascii
import bisect
import re
import sys
from pathlib import Path

from . import tomlread

_POSSESSIVE = sys.version_info >= (3, 11)   # possessive quantifiers (x*+, x++, x?+, x{n,}+) exist from Python 3.11


def _plain_quantifiers(pattern):
    """The pattern with its possessive quantifiers made plain (x*+ -> x*), by a walk that knows what it is looking at: a + is possessive only
    when it directly follows an unescaped quantifier (* + ? or a closing brace) outside a character class. `[*+/=]{4,}`, `a\\++` (an escaped
    plus, repeated) and `x[?+]y` are left exactly as written; `[^\\s:/@]*+` and `{10,}+` lose the trailing +."""
    out, i, n, in_class, prev_quant = [], 0, len(pattern), False, False
    while i < n:
        c = pattern[i]
        if c == "\\":   # an escape: the next character is literal, never a quantifier
            out.append(pattern[i:i + 2])
            i += 2
            prev_quant = False
            continue
        if in_class:
            if c == "]":
                in_class = False
            out.append(c)
            i += 1
            prev_quant = False
            continue
        if c == "[":
            in_class = True
            out.append(c)
            i += 1
            if i < n and pattern[i] == "^":
                out.append("^")
                i += 1
            if i < n and pattern[i] == "]":   # a leading ] is a literal inside the class
                out.append("]")
                i += 1
            prev_quant = False
            continue
        if c == "+" and prev_quant:   # the possessive marker itself
            i += 1
            prev_quant = False
            continue
        if c == "{":   # a {m,n} quantifier: copy it whole
            j = pattern.find("}", i)
            if j > 0 and re.fullmatch(r"\{\d*(?:,\d*)?\}", pattern[i:j + 1]):
                out.append(pattern[i:j + 1])
                i = j + 1
                prev_quant = True
                continue
        out.append(c)
        prev_quant = c in "*+?"
        i += 1
    return "".join(out)


def _compile(pattern, flags=0):
    """re.compile, but on Python 3.9 and 3.10 the possessive quantifiers are made plain (_plain_quantifiers). They are here to stop a crafted
    text from making a pattern backtrack for seconds (test_redact_dos); without them the same patterns still match the same strings, and the
    size caps (`bound`, MAX_HIDDEN) keep the worst case small."""
    if not _POSSESSIVE:
        pattern = _plain_quantifiers(pattern)
    return re.compile(pattern, flags)

# Control (but not tab, newline, carriage return), format (zero-width, bidi, soft hyphen, tag), private-use and surrogate code points: invisible, or
# able to split a key so that a pattern no longer sees it ("sk-" + zero-width space + key): the set untrusted.text_lines drops, plus the invisible
# fillers, joiners and variation selectors. Only the COPY used for matching loses them: the text you store keeps every one it had.
_INVISIBLE = _compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\xad\u034f\u0600-\u0605\u061c\u06dd\u070f\u08e2\u115f\u1160\u17b4\u17b5\u180b-\u180e\u200b-\u200f\u202a-\u202e\u2060-\u2064"
                        r"\u2066-\u206f\u2800\u3164\ufe00-\ufe0f\ufeff\uffa0\ufff9-\ufffb\ue000-\uf8ff\ud800-\udfff\U000110bd\U000110cd\U00013430-\U0001343f\U0001bca0-\U0001bca3"
                        r"\U0001d173-\U0001d17a\U000e0001\U000e0020-\U000e007f\U000e0100-\U000e01ef\U000f0000-\U000ffffd\U00100000-\U0010fffd]")
MAX_HIDDEN = 5000    # a text with more invisible characters than this is not prose: they are dropped instead of being mapped around

# Dashes and minus signs that look like a hyphen: every Unicode "Pd" (dash punctuation) character, plus the minus signs and the hyphen bullet.
# "sk" + U+2010 + key is a key to the eye and to whatever normalises it later, but not to a pattern that wants "-". Only the COPY used for
# matching folds them to "-", one for one (so every position stays the same); the text you store keeps the dash it had ("pages 3-5" is not a key).
_DASH_RANGES = ((0x058A, 0x058A), (0x05BE, 0x05BE), (0x1400, 0x1400), (0x1806, 0x1806), (0x2010, 0x2015), (0x2E17, 0x2E17), (0x2E1A, 0x2E1A),
                (0x2E3A, 0x2E3B), (0x2E40, 0x2E40), (0x2E5D, 0x2E5D), (0x301C, 0x301C), (0x3030, 0x3030), (0x30A0, 0x30A0), (0xFE31, 0xFE32),
                (0xFE58, 0xFE58), (0xFE63, 0xFE63), (0xFF0D, 0xFF0D), (0x10D6E, 0x10D6E), (0x10EAD, 0x10EAD),          # category Pd
                (0x02D7, 0x02D7), (0x2043, 0x2043), (0x207B, 0x207B), (0x208B, 0x208B), (0x2212, 0x2212), (0x2796, 0x2796))   # minus signs, hyphen bullet
_DASHES = {c: "-" for lo, hi in _DASH_RANGES for c in range(lo, hi + 1)}
# The fullwidth forms of ASCII (U+FF01 to U+FF5E, "_" "=" ":" and the letters and digits among them) are the same characters shifted by 0xFEE0, which is
# what a normaliser (NFKC) turns them back into: "api_key" + a fullwidth "=" + a value is an assignment to the eye and to the next program that reads it.
_FOLD = {**{c: chr(c - 0xFEE0) for c in range(0xFF01, 0xFF5F)}, **_DASHES}      # one for one, like the dashes (the fullwidth hyphen is in both and agrees)

PLACEHOLDER = _compile(r"^[xX*._\-]+$|EXAMPLE|\$\{?\w|<[^>]*>|\{\w+\}|changeme|placeholder|dummy|redacted|^your[-_]", re.I)
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


def _token_like(v):
    """For the value after "Authorization: Bearer": generated-looking (a letter and a digit, base64 padding), or long and mixed-case. A plain
    word, a kebab-case phrase or a short name is not a token, so it is never erased."""
    return _secret_like(v) or (len(v) >= 20 and any(c.isupper() for c in v) and any(c.islower() for c in v))


def _basic_like(v):
    """For the value after "Authorization: Basic": base64 of user:password, so any value that decodes to something with a colon in it. Short
    ones (user:letmein is dXNlcjpsZXRtZWlu: no digit, no padding, 16 characters) have nothing else generated-looking about them. Words and
    kebab-case phrases do not decode (a hyphen is not base64), and a plain word that happens to be valid base64 has no colon behind it."""
    if _token_like(v):
        return True
    try:
        raw = base64.b64decode(v + "=" * (-len(v) % 4), validate=True)
    except (binascii.Error, ValueError):
        return False
    return b":" in raw


def _auth_header(m):
    """Authorization: Token|Bearer|Basic VALUE. Bearer and Token keep the rule they always had (a value that looks generated); Basic is always a
    credential, so it is judged by what it decodes to and may be short."""
    scheme, value = m.group(1).split()[-1].lower(), m.group(2)
    basic = scheme == "basic"
    if len(value) < (4 if basic else 10) or _few_kinds(value) or PLACEHOLDER.search(value) or not (_basic_like(value) if basic else _token_like(value)):
        return m.group(0)
    return m.group(1) + _mask("secret")


_UUID = _compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_WORDY = _compile(r"[a-z0-9]+(?:[_.-][a-z0-9]+)+")    # snake_case and kebab-case names: identifiers, not keys


def _wordy(v):
    """A snake_case or kebab-case identifier (task-queue-implementation-notes, user_profile_cache_v2_final, risk-assessment-2026-plan):
    lower-case segments joined by _ . or -. A segment that mixes letters with three or more digits (a1b2c3d4e5f6, the halves of
    key-<32 hex>) is a token with a dash in it, not a word; a plain number (2026) is a word."""
    return bool(_WORDY.fullmatch(v)) and not any(sum(c.isdigit() for c in seg) >= 3 and any(c.isalpha() for c in seg) for seg in re.split(r"[_.-]", v))


def _api_key_like(v):
    """For sk-...: what follows the prefix looks generated, not like words (task-queue-implementation-notes)."""
    body = re.sub(r"^sk-(?:ant-|proj-)?", "", v)
    return _has_letter_and_digit(body) and not _wordy(body)


def _random_like(v):
    """For a generic name (key, auth, token): long, a letter and a digit, and not a lower-case identifier like user_profile_cache_v2_final."""
    if _UUID.fullmatch(v):
        return True
    return len(v) >= 20 and _has_letter_and_digit(v) and not _wordy(v)


_PASSWORD_WORDS = {"password", "pass", "passwd", "pwd", "secret", "user", "username", "token", "changeme", "yourpassword", "your-password", "mypassword"}


def _url_password(m):
    """scheme://user:PASSWORD@host: the password goes, the rest stays; a documented placeholder (user:password@host) is left."""
    value = m.group(2)
    if value.lower() in _PASSWORD_WORDS or PLACEHOLDER.search(value) or re.fullmatch(r"[*xX\u2022.\-]+", value):
        return m.group(0)
    return m.group(1) + _mask("password") + m.group(3)


# (kind, pattern, replacement function). Order matters: a private-key block first, then headers, then the rest.
SHAPES = [
    ("private-key", _compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----(?:(?:(?!-----(?:BEGIN|END) )[\s\S]){0,10000}?-----END [A-Z ]*PRIVATE KEY-----|(?:\s*+(?:[A-Za-z][A-Za-z-]{1,20}: [^\n]{0,120}|[A-Za-z0-9+/=]{16,}+))*+)"), lambda m: _mask("private-key")),   # to its END line, or (cut off) through its header lines (Proc-Type, DEK-Info) and base64 lines: the sentences after it stay
    ("auth-header", _compile(r"(Authorization:\s*+(?:Token|Bearer|Basic)\s++)([A-Za-z0-9._=+/~-]{4,}+)", re.I), _auth_header),
    ("jwt", _compile(r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{10,}+\.[A-Za-z0-9_-]{10,}+\.[A-Za-z0-9_-]{10,}+"), _whole("jwt")),   # lookbehind + possessive: the text eyJeyJeyJ... was quadratic (44 s for 400 KB)
    ("aws-key", _compile(r"AKIA[0-9A-Z]{16}"), _whole("aws-key")),
    ("api-key", _compile(r"sk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}+"), _whole("api-key", _api_key_like)),
    ("github-token", _compile(r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}"), _whole("github-token")),
    ("slack-token", _compile(r"xox[abprs]-[A-Za-z0-9-]{10,}+"), _whole("slack-token")),
    ("account-sid", _compile(r"(?<![A-Za-z0-9])(?:AC|SK)[0-9a-f]{32}(?![A-Za-z0-9])"), _whole("account-sid")),
    ("stripe-key", _compile(r"(?<![A-Za-z0-9])(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{20,}"), _whole("stripe-key")),
    ("webhook-secret", _compile(r"(?<![A-Za-z0-9])whsec_[A-Za-z0-9+/=]{20,}"), _whole("webhook-secret")),
    ("google-key", _compile(r"(?<![A-Za-z0-9_-])AIza[0-9A-Za-z_-]{35}(?![0-9A-Za-z_-])"), _whole("google-key")),
    ("slack-webhook", _compile(r"(?:https?://)?hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+"), _whole("slack-webhook")),
    ("npm-token", _compile(r"(?<![A-Za-z0-9_])npm_[A-Za-z0-9]{36}(?![A-Za-z0-9])"), _whole("npm-token")),
    ("sendgrid-key", _compile(r"(?<![A-Za-z0-9_-])SG\.[A-Za-z0-9_-]{16,}+\.[A-Za-z0-9_-]{16,}+"), _whole("sendgrid-key")),
    ("url-password", _compile(r"(://[^\s:/@]*+:)([^\s@/]++)(@)"), _url_password),   # the user may be empty: redis://:PASSWORD@host
    ("bearer", _compile(r"(?<![A-Za-z])(Bearer\s++)([A-Za-z0-9._~+/=-]{20,}+)"), _keep_prefix("secret", _secret_like)),
    ("key-hex", _compile(r"((?<![A-Za-z])(?:api[_-]?key|key|token|secret|passwd|password)\W{1,4})([0-9a-fA-F]{32,64})(?![0-9a-fA-F])", re.I), _keep_prefix("hex")),
    ("assigned-secret", _compile(r"((?:aws[_-]?secret[_-]?access[_-]?key|secret[_-]?access[_-]?key|api[_-]?key|apikey|secret[_-]?key|secret|passwd|password|pwd|auth[_-]?token|access[_-]?token|refresh[_-]?token|client[_-]?secret|app[_-]?secret|private[_-]?token|signing[_-]?(?:key|secret))[\"']?\s*+[:=]\s*+[\"']?)([A-Za-z0-9/+_=.~-]{16,}+)", re.I),
     _keep_prefix("secret", _has_letter_and_digit)),
    ("generic-secret", _compile(r"((?<![A-Za-z0-9])(?:key|auth|token|credentials?|access[_-]?key)[\"']?\s*+[:=]\s*+[\"']?)([A-Za-z0-9/+_=.~-]{20,}+)", re.I),
     _keep_prefix("secret", _random_like)),
]

PHONE = _compile(r"(?<![\d.])(?:\(?[2-9]\d{2}\)?[ .-]\d{3}[ .-]\d{4}|\+1[ ]?\d{10})(?!\d)")


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
        sect = tomlread.loads(path.read_text()).get("redact", {})
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
            rxs.append(_compile(p))
        except re.error:
            rxs.append(_compile(re.escape(p)))
    return rxs


def _sub_visible(rx, repl, text):
    """rx.sub(repl, text), but matching on a copy without the invisible characters and with every Unicode dash folded to "-" and every fullwidth ASCII form folded to ASCII, and replacing
    in the original by the matched span: a key that carries a zero-width space or an en dash is masked whole, and everything else (a ZWJ in
    an emoji, a ZWNJ in Persian, the dash in "pages 3-5") stays as written. One exception: the part of a MATCH that is kept (the name in
    `x–api–key: KEY`) comes out of the folded copy, so it reads with plain hyphens and ASCII (`x-api-key: [redacted secret]`); the tests say so."""
    view = text if text.isascii() else text.translate(_FOLD)         # one for one: every index is the same in both
    hidden = [m.start() for m in _INVISIBLE.finditer(view)]
    if not hidden and view == text:
        return rx.sub(repl, text)
    clean = _INVISIBLE.sub("", view) if hidden else view
    q = [p - j for j, p in enumerate(hidden)]     # q[j]: the clean index where the j-th hidden character was taken out

    def orig(c):
        return c + bisect.bisect_right(q, c)       # clean index to original index: add the hidden characters before it
    out, last = [], 0
    for m in rx.finditer(clean):
        r = repl(m)
        if r == m.group(0):                        # left as it is: the original, invisible characters and dashes and all, stays
            continue
        a = orig(m.start())
        b = a if m.end() == m.start() else orig(m.end() - 1) + 1   # a zero-length match (an owner pattern like z*) inserts, it never swallows the character after it
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
        v = d[key] if isinstance(d, list) else d.get(key)
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
            files = m.get("files")
            if isinstance(files, list):
                for i in range(len(files)):
                    if isinstance(files[i], str):
                        one(f"chat #{m.get('seq')} file #{i + 1}", files, i)
            act = m.get("action")
            if isinstance(act, dict):
                one(f"chat #{m.get('seq')} action", act, "text")
    return hits
