"""What must never be committed to this public repo (sec-data-public-repo-guard).

    python3 tests/publiccheck.py [repo folder]       # exit 1 and a list of file:line:kind when something is found

It reads every tracked text file (git ls-files) and looks for: secret-shaped strings (cloud and API keys, tokens, private-key blocks,
Authorization headers, assigned secrets), phone numbers that are not obviously fictional (area code 555, exchange 555 with a line
in 0100-0199, or the song's 867-5309/5310), email addresses outside a small allow-list, absolute home paths of a real account, and your own private words.

It never prints what it found, only where, what kind, and the first four characters.

Your private words (family names, employer, other projects) must not live in this repo, so they are read from a file outside it:
$AGENTBOARD_PRIVATE_WORDS, else ~/.config/agentboard/private-words.txt, one word or regex per line (blank lines and # comments are
skipped). Without the file that one check is skipped; the others always run."""
import sys
from pathlib import Path

try:
    from agentboard import repoguard
except ImportError:   # run as a script from a checkout with no install: the package is in ../src
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from agentboard import repoguard

# One source for the shapes and the allow rules (src/agentboard/repoguard.py): `agentboard doctor` reads the same, so the two never disagree.
PLACEHOLDER, SECRET_SHAPES, PHONE, EMAIL, EMAIL_OK, HOME, HOME_OK, SKIP_SUFFIX, MAX_BYTES = (
    repoguard.PLACEHOLDER, repoguard.SECRET_SHAPES, repoguard.PHONE, repoguard.EMAIL, repoguard.EMAIL_OK, repoguard.HOME, repoguard.HOME_OK,
    repoguard.SKIP_SUFFIX, repoguard.MAX_BYTES)
mask, ordinary_word, fictional_phone, private_words, tracked_files, scan_text, scan = (
    repoguard.mask, repoguard.ordinary_word, repoguard.fictional_phone, repoguard.private_words, repoguard.tracked_files, repoguard.scan_text, repoguard.scan)


if __name__ == "__main__":
    root = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1])
    res = scan(root)
    if res is None:
        sys.exit(f"{root} is not a git repository")
    for f, no, kind, sample in res:
        print(f"{f}:{no}: {kind} ({sample})")
    print(f"{len(res)} finding(s)" + ("" if private_words() else "  (private words file not found: that check was skipped)"))
    sys.exit(1 if res else 0)
