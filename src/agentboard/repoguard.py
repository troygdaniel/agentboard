"""What must never be committed to a public repository, in one place for the two tools that look: `tests/publiccheck.py` (before a push) and
`agentboard doctor`'s `tracked files` line (on any machine). They used to carry two copies of the rules, and the copies disagreed: the doctor
showed a standing FAIL on fixture keys that the guard, rightly, allowed (a kebab-case phrase after `sk-`, the song's phone number, a key that
is one letter repeated). A standing FAIL trains people to ignore the doctor, which matters most on a work PC. Now there is one set of shapes
and one set of allow rules, and both tools read them from here.

The shapes: cloud and API keys, tokens, private-key blocks, Authorization headers, assigned secrets, a key word before 40 hex; phone numbers
that are not obviously fictional (area code 555, exchange 555 with a line in 0100-0199, or the song's 867-5309/5310); email addresses outside a
small allow-list; absolute home paths of a real account; and the owner's private words, read from a file OUTSIDE the repo
($AGENTBOARD_PRIVATE_WORDS, else ~/.config/agentboard/private-words.txt, one word or regex per line).

The allow rules (what is a fixture, not a secret): a placeholder word in the match (example, fake, dummy, xxxx, <...>, {name}, redacted, a run of
zeros), a value made of one to three distinct characters (ACbbbb..., AKIAXXXX...), and plain words that happen to start like a key
(`sk-learn-pipeline-for-the-model`, "Authorization: Bearer unauthorised-deletion"): the same rule the board's masker (redact.py) uses.

Nothing here prints what it found: a hit is a file, a line, a kind and the first four characters."""
import os
import re
import subprocess
from pathlib import Path

PLACEHOLDER = re.compile(r"x{4,}|\.{3}|<[^>]*>|\$\{?\w+|\{\w+\}|example|your[-_ ]?|fake|dummy|placeholder|changeme|redacted|0{8,}", re.I)

SECRET_SHAPES = {
    "aws-key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "api-key (sk-)": re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    "github-token": re.compile(r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}"),
    "slack-token": re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}"),
    "account-sid": re.compile(r"(?<![A-Za-z0-9])(?:AC|SK)[0-9a-f]{32}(?![A-Za-z0-9])"),
    "stripe-key": re.compile(r"(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{20,}"),
    "google-key": re.compile(r"(?<![A-Za-z0-9_-])AIza[0-9A-Za-z_-]{35}(?![0-9A-Za-z_-])"),
    "npm-token": re.compile(r"(?<![A-Za-z0-9_])npm_[A-Za-z0-9]{36}(?![A-Za-z0-9])"),
    "sendgrid-key": re.compile(r"(?<![A-Za-z0-9_-])SG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}"),
    "slack-webhook": re.compile(r"hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]{8,}"),
    "private-key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "auth-header": re.compile(r"Authorization:\s*(?:Token|Bearer|Basic)\s+[A-Za-z0-9._=+/-]{10,}", re.I),
    "assigned-secret": re.compile(r"(?:api[_-]?key|secret|passwd|password|auth[_-]?token)[\"']?\s*[:=]\s*[\"']([A-Za-z0-9/+_=.-]{16,})[\"']", re.I),
    "key-word + 40 hex": re.compile(r"(?<![A-Za-z])(?:key|token|secret)\W{1,4}[0-9a-f]{40}(?![0-9a-f])", re.I),
}
# the shapes that are a secret beyond doubt when they are not a placeholder: a FAIL for doctor. The rest (an assignment, a hex run after a
# key word, a phone number, an email, a home path, a private word) are worth a look: a WARN.
CERTAIN = {"aws-key", "api-key (sk-)", "github-token", "slack-token", "account-sid", "stripe-key", "google-key", "npm-token", "sendgrid-key", "slack-webhook",
           "private-key", "auth-header"}
PHONE = re.compile(r"(?<![\d.])(?:\(?[2-9]\d{2}\)?[ .-]\d{3}[ .-]\d{4}|\+1[ ]?\d{10})(?![\d])")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
EMAIL_OK = re.compile(r"@(?:[\w.-]*\.)?example\.(?:com|org|net)$|@[\w.-]*\.invalid$|@users\.noreply\.github\.com$|@localhost$|^git@github\.com$|^noreply@anthropic\.com$", re.I)
HOME = re.compile(r"(?<![\w])/(?:Users|home)/([A-Za-z0-9._-]+)/")
HOME_OK = {"you", "user", "username", "name", "me", "alice", "bob", "carol", "example", "runner", "vscode", "shared", "guest", "owner-example", "x", "u"}
SKIP_SUFFIX = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".gz", ".zip", ".woff", ".woff2", ".mp3", ".wav"}
MAX_BYTES = 2_000_000

_WORDY = re.compile(r"[a-z0-9]+(?:[_.-][a-z0-9]+)+")


def mask(s):
    return s[:4] + "…(" + str(len(s)) + " chars)"


def _has_letter_and_digit(v):
    return any(c.isdigit() for c in v) and any(c.isalpha() for c in v)


def ordinary_word(kind, hit):
    """A look-alike that is plain words: sk- inside task-queue-implementation-notes, or a kebab-case phrase after "Authorization: Bearer". The same
    rule the board's masker (agentboard/redact.py) uses, so the guard and the masker agree on what a key looks like."""
    if kind == "api-key (sk-)":
        body = re.sub(r"^sk-(?:ant-|proj-)?", "", hit)
        return not _has_letter_and_digit(body) or bool(_WORDY.fullmatch(body))
    if kind == "auth-header":
        value = hit.split()[-1]
        generated = _has_letter_and_digit(value) or value.endswith("=") or (len(value) >= 20 and any(c.isupper() for c in value) and any(c.islower() for c in value))
        return not generated
    return False


def fictional_phone(m):
    digits = re.sub(r"\D", "", m)
    digits = digits[1:] if len(digits) == 11 and digits[0] == "1" else digits
    area, exch, line = digits[:3], digits[3:6], digits[6:]
    return area == "555" or (exch == "555" and line.startswith("01")) or exch + line in ("8675309", "8675310")   # 867-5309: the song's number, a well-known fake


def allowed(kind, whole, hit):
    """Is this match a fixture rather than a secret: a placeholder word in it, a value of one to three distinct characters, or plain words."""
    core = max(re.findall(r"[A-Za-z0-9/+_=.-]{8,}", hit) or [hit], key=len)   # the secret part: a key word before it does not count
    return bool(PLACEHOLDER.search(whole)) or len(set(core)) <= 3 or ordinary_word(kind, whole)


def private_words():
    """Compiled regexes from the words file outside the repo, or [] when there is none."""
    path = os.environ.get("AGENTBOARD_PRIVATE_WORDS") or str(Path.home() / ".config" / "agentboard" / "private-words.txt")
    try:
        lines = Path(path).read_text().splitlines()
    except OSError:
        return []
    out = []
    for ln in lines:
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            try:
                out.append(re.compile(ln, re.I))
            except re.error:
                out.append(re.compile(re.escape(ln), re.I))
    return out


def scan_text(text, words=()):
    """[(line number, kind, masked sample)] for one file's text, allow rules applied."""
    found = []
    for no, line in enumerate(text.splitlines(), 1):
        for kind, rx in SECRET_SHAPES.items():
            for m in rx.finditer(line):
                hit = m.group(1) if rx.groups else m.group(0)
                if allowed(kind, m.group(0), hit):
                    continue
                found.append((no, kind, mask(hit)))
        for m in PHONE.finditer(line):
            if not fictional_phone(m.group(0)):
                found.append((no, "phone number", mask(m.group(0))))
        for m in EMAIL.finditer(line):
            if not EMAIL_OK.search(m.group(0)):
                found.append((no, "email address", mask(m.group(0))))
        for m in HOME.finditer(line):
            if m.group(1).lower() not in HOME_OK:
                found.append((no, "home path of a real account", mask(m.group(0))))
        for rx in words:
            m = rx.search(line)
            if m:
                found.append((no, "private word", mask(m.group(0))))
    return found


def certain(kind):
    """A kind that is a secret beyond doubt once the allow rules let it through (doctor's FAIL); the others are a WARN."""
    return kind in CERTAIN


def tracked_files(root):
    r = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return [Path(root) / n for n in r.stdout.split("\0") if n]


def readable(path):
    """The text of a tracked file worth scanning, or None (a picture, a link, too big, binary)."""
    if path.suffix.lower() in SKIP_SUFFIX or path.is_symlink() or not path.is_file():
        return None
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\0" in raw[:4096]:
        return None
    return raw.decode("utf-8", "replace")


def scan(root, words=None):
    """[(relative file, line, kind, masked sample)] over every tracked text file, or None when root is not a git repo."""
    files = tracked_files(root)
    if files is None:
        return None
    words = private_words() if words is None else words
    out = []
    for f in files:
        text = readable(f)
        if text is None:
            continue
        for no, kind, sample in scan_text(text, words):
            out.append((f.relative_to(root).as_posix(), no, kind, sample))
    return out
