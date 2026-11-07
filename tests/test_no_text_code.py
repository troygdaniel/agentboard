"""agentboard holds no texting code (it moved to a separate home-only plugin, Nov 7) and no real phone number or account SID.

Two guards, both fail loudly:
  1. nothing under src/agentboard mentions Twilio, SMS or pull-texts, and the two modules that were removed stay gone;
  2. no tracked text file holds a phone-number-shaped string (other than a fictional one: area code 555, or 555-01xx) or an
     account SID ("AC" and 32 hex digits). Docs and mockups use +1 555 0100, tests build fake values from parts.
"""
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
SRC = ROOT / "src" / "agentboard"
BANNED = re.compile(r"twilio|\bsms\b|pull-texts|pull_texts", re.I)
PHONE = re.compile(r"(?<![\d.])\+?1?[ .-]?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}(?!\d)")
SID = re.compile(r"\bAC[0-9a-fA-F]{32}\b")
BINARY = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".mp3", ".wav", ".pdf", ".svg", ".webp"}
THIS = Path(__file__).name
# no exceptions: agentboard doctor's own test builds the real-looking number it needs from pieces at run time, so no file holds one
ALLOWED = {}


def tracked():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\n")
    return [ROOT / f for f in out if f and (ROOT / f).suffix.lower() not in BINARY and (ROOT / f).is_file()]


def read(path):
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def find_banned(root):
    bad = []
    for f in sorted(Path(root).rglob("*")):
        if not f.is_file() or "__pycache__" in f.parts or f.suffix in (".pyc", ".png", ".ico"):
            continue
        text = read(f)
        if text is None:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            m = BANNED.search(line)
            if m:
                bad.append(f"{f.name}:{i}: {m.group(0)}")
    return bad


class NoTextingCode(unittest.TestCase):
    def test_the_source_never_mentions_twilio_sms_or_pull_texts(self):
        self.assertEqual(find_banned(SRC), [], "texting code or its name is back in src/agentboard; it lives in the home-only plugin")

    def test_the_removed_modules_stay_gone(self):
        for name in ("texts.py", "sms.py"):
            self.assertFalse((SRC / name).exists(), name)

    def test_the_scan_catches_a_mention_in_any_kind_of_source_file(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a.py").write_text("x = 1\n# api.Twilio.com\n")
            (Path(d) / "page.html").write_text("<script>fetch('/api/pull-texts')</script>\n")
            (Path(d) / "b.py").write_text("import sms\n")
            (Path(d) / "ok.py").write_text("# plugins, text-born cards, SMSless\n")
            found = find_banned(d)
        self.assertEqual(sorted(x.split(":")[0] for x in found), ["a.py", "b.py", "page.html"])


class NoRealNumbers(unittest.TestCase):
    def test_every_phone_shaped_string_is_fictional(self):
        bad = []
        for f in tracked():
            if f.name in (THIS, "test_public_repo_clean.py"):   # that file's own fixtures are secret- and number-shaped on purpose
                continue
            text = read(f)
            if text is None:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                for m in PHONE.finditer(line):
                    d = re.sub(r"\D", "", m.group(0))[-10:]
                    fictional = d[:3] == "555" or (d[3:6] == "555" and d[6:8] == "01")
                    rel = f.relative_to(ROOT).as_posix()
                    if not fictional and m.group(0).strip() not in ALLOWED.get(rel, ()):
                        bad.append(f"{rel}:{i}: {m.group(0).strip()}")
        self.assertEqual(bad, [], "a real-looking phone number is committed; use +1 555 0100")

    def test_no_account_sid_is_committed(self):
        bad = []
        for f in tracked():
            if f.name == THIS:
                continue
            text = read(f)
            if text is None:
                continue
            bad += [f"{f.relative_to(ROOT)}: {m.group(0)}" for m in SID.finditer(text)]
        self.assertEqual(bad, [])

    def test_the_scan_itself_catches_what_it_should(self):
        self.assertTrue(PHONE.search("call 416-555-0123 now"))
        self.assertTrue(PHONE.search("+14165550123"))
        self.assertTrue(SID.search("AC" + "0" * 32))
        self.assertFalse(SID.search("AC" + "0" * 31))


if __name__ == "__main__":
    unittest.main()
