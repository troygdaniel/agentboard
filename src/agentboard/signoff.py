"""ORCH's sign-off on a card in review: the facts it holds, kept on the card so the owner sees them before signing (card orch-sign-off).

Counts, hashes and results only, never message text. Every field is checked against a small pattern or a short list of words, so a
sign-off cannot carry a sentence (or a path, a key or a number), and what the board draws from it needs no cleaning of its own.

The record, as stored on the card (`signoff`):
    merged       the merge commit's hash, or None when the card is not on main yet
    ahead        how many branches are ahead of main (only with "not merged"), or None
    tests        up to four {"name": "full smoke", "result": "pass"}, result one of RESULTS
    gate         the batch gate: pass, fail or pending, or None when ORCH did not say
    verified_by  the session that ran the checks, or None
    by, at       who recorded it (ORCH) and when (the store adds both)
"""
import re

RESULTS = ("pass", "fail", "running", "pending", "skipped")
GATES = ("pass", "fail", "pending")
TESTS_MAX = 4
AHEAD_MAX = 99
_HASH = re.compile(r"[0-9a-f]{7,40}")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._/+-]{0,29}")      # "full smoke", "tests/pullout.mjs": a name, never a sentence
_WHO = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,31}")


def clean(merged=None, not_merged=False, ahead=None, tests=None, gate=None, verified_by=None):
    """The record for these facts, or a ValueError that says what to change. Exactly one of `merged` (a hash) and `not_merged`."""
    if merged and not_merged:
        raise ValueError("a card is either merged or not: give --merged <hash> or --not-merged, not both")
    if not merged and not not_merged:
        raise ValueError("say whether it is on main: --merged <hash>, or --not-merged")
    rec = {"merged": None, "ahead": None, "tests": [], "gate": None, "verified_by": None}
    if merged:
        h = str(merged).strip().lower()
        if not _HASH.fullmatch(h):
            raise ValueError("--merged takes the merge commit's hash: 7 to 40 characters of 0-9 and a-f")
        rec["merged"] = h
        if ahead is not None:
            raise ValueError("--ahead goes with --not-merged: a merged card is not behind anything")
    if ahead is not None:
        if isinstance(ahead, bool) or not isinstance(ahead, int) or not 0 <= ahead <= AHEAD_MAX:
            raise ValueError(f"--ahead is a count from 0 to {AHEAD_MAX}")
        rec["ahead"] = ahead
    tests = list(tests or [])
    if len(tests) > TESTS_MAX:
        raise ValueError(f"at most {TESTS_MAX} --test results: name the suites that matter, not every one")
    for x in tests:
        name, result = _split_test(x)
        if not _NAME.fullmatch(name):
            raise ValueError(f"a test name is a few words (letters, digits, space . _ / + -; 30 at most), not a sentence: {name[:30]!r}")
        if result not in RESULTS:
            raise ValueError(f"a test result is one of {', '.join(RESULTS)}: --test \"{name}={'|'.join(RESULTS)}\"")
        rec["tests"].append({"name": name, "result": result})
    if gate is not None:
        if gate not in GATES:
            raise ValueError(f"--gate is one of {', '.join(GATES)}")
        rec["gate"] = gate
    if verified_by is not None:
        who = str(verified_by).strip()
        if not _WHO.fullmatch(who):
            raise ValueError("--verified-by is a session name (letters, digits, space . _ -; 32 at most)")
        rec["verified_by"] = who
    return rec


def _split_test(x):
    """'full smoke=pass' or {'name': ..., 'result': ...} -> (name, result)."""
    if isinstance(x, dict):
        return str(x.get("name", "")).strip(), str(x.get("result", "")).strip().lower()
    name, sep, result = str(x).rpartition("=")
    if not sep:
        raise ValueError("a test is NAME=RESULT, e.g. --test \"full smoke=pass\"")
    return name.strip(), result.strip().lower()


def line(rec):
    """The one plain line for the card's history and ORCH's chat: 'merged 165d972, full smoke pass, gate pass'. Hashes and results only."""
    parts = ["merged " + rec["merged"]] if rec.get("merged") else ["not merged" + (f" ({rec['ahead']} ahead)" if rec.get("ahead") is not None else "")]
    parts += [f"{t['name']} {t['result']}" for t in rec.get("tests") or []]
    if rec.get("gate"):
        parts.append("gate " + rec["gate"])
    if rec.get("verified_by"):
        parts.append("verified by " + rec["verified_by"])
    return ", ".join(parts)
