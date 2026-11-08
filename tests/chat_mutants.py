"""Break the chat fixes one at a time in a scratch copy of the package and see whether tests/test_chat_e2e.py notices (card chat-q1). Never touches the repo.

    python3 tests/chat_mutants.py            # every mutant, about 20 s each
    python3 tests/chat_mutants.py cursor     # those whose name contains 'cursor'

A mutant that SURVIVES is a guard the end-to-end tests do not see: add a scenario, or say here why it cannot be seen."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
M = [
    ("a print moves the seen cursor (the R2 loss)", "cli.py", 'cursors.deliver(s.dir, name, msgs[-1]["seq"])   # DELIVERED', 'cursors.advance(s.dir, name, msgs[-1]["seq"])   # DELIVERED'),
    ("a delivered line is never shown again", "cursors.py", "RESHOW_S = 300", "RESHOW_S = 10 ** 9"),
    ("a second wait under a name replaces the first", "listeners.py", 'd[k] = [r for r in d.get(k, []) if r.get("pid") != pid] + [{', 'd[k] = [{'),
    ("the wake file never moves", "store.py", "            chatwake.bump(self.dir, to)   # the wake file moves", "            pass   # the wake file moves"),
    ("an unknown name is accepted", "store.py", 'if unknown and kind == "agent" and via != "mirror":', 'if False:'),
    ("an answer to the owner counts as agent talk", "store.py", "talk = bool(to and not to_owner) or bool(files and not to_owner)", "talk = bool(to) or bool(files)"),
    ("inbox shows the newest page and skips the older", "cli.py", "(unread[:a.limit], unread[a.limit:])", "(unread[-a.limit:], [])"),
    ("the hook ignores --dir", "cli.py", '        os.environ["AGENTBOARD_DIR"] = a.dir', '        pass'),
    ("the mirror posts for any session", "hooks.py", "    sender = known_name(store.dir, payload)\n    if sender is None:\n        return None", "    sender = resolve_sender(store.dir, payload)"),
    ("the pristine settings copy is never made", "hooks.py", 'if not os.path.exists(f"{target}.orig"):', "if False:"),
    ("the stop hook ignores an unread line", "hooks.py", "    if unread:\n        last = unread[-1]", "    if False:\n        last = unread[-1]"),
    ("a confirmed delivery is not recorded as seen", "cursors.py", "    advance(board_dir, name, p[\"seq\"])\n    return p[\"seq\"]", "    return p[\"seq\"]"),
    ("the wait polls instead of watching the wake file (slow)", "cli.py", "chatwake.sleep_until_change(s.dir, a.interval, max(0.0, min(chatwake.NET_S, deadline - time.time())))", "time.sleep(5)"),
]
only = sys.argv[1] if len(sys.argv) > 1 else None
out = []
for name, f, old, new in M:
    if only and only not in name:
        continue
    d = Path(tempfile.mkdtemp())
    shutil.copytree(REPO / "src", d / "src", ignore=shutil.ignore_patterns("__pycache__"))
    p = d / "src" / "agentboard" / f
    s = p.read_text()
    if s.count(old) != 1:
        out.append((name, f"MUTANT DID NOT APPLY ({s.count(old)} matches)"))
        continue
    p.write_text(s.replace(old, new))
    # the harness runs the sessions with the scratch copy: it reads agentboard's location from the import
    env = {"HOME": os.environ["HOME"], "PATH": os.environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": f"{d / 'src'}:{REPO / 'tests'}"}
    try:
        r = subprocess.run([sys.executable, "-W", "ignore", "-m", "unittest", "test_chat_e2e"], env=env, capture_output=True, text=True, timeout=400, cwd=d)
        fails = [l.split(" (")[0].replace("FAIL: ", "").replace("ERROR: ", "") for l in r.stderr.splitlines() if l.startswith(("FAIL:", "ERROR:"))]
        out.append((name, f"KILLED by {len(fails)}: {', '.join(fails[:2])}" if fails else ("SURVIVED" if r.returncode == 0 else "FAILED TO RUN: " + r.stderr.strip().splitlines()[-1][:80])))
    except subprocess.TimeoutExpired:
        out.append((name, "TIMEOUT (counts as killed)"))
    shutil.rmtree(d, ignore_errors=True)
for n, v in out:
    print(f"{n:58} {v}")
