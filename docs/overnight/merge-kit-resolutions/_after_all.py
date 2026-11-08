"""Cross-branch fixups, applied once after every branch is merged (the kit runs this as its last step). Each branch's suite was green
on its own; together four pins stop being true. Every fixup checks that it applies and says what it changed; all are idempotent.

1. docs/ARCHITECTURE.md (docs-architecture) pins the module map against src/: the other branches add modules. Rows are added for them.
2. docs/security-signoff.md (sec-signoff-pack) pins the file table against what the board writes: main's chat-f7 added chat-wake.json.
3. tests/test_tomlread.py (install-quickstart) wants no `import tomllib` outside the reader: selfcheck.py (sec-workpc-profile) has one.
4. tests/test_doctor.py pins the report at 20 lines; four branches each add a doctor line, so the combined report is 21. The cap moves to 24.
5. docs/index.md (docs-architecture) pins every docs/*.md and every docs/ folder: the other branches add documents (security-signoff.md,
   the overnight folder). Rows are added for what is missing.
6. selfcheck.py (sec-workpc-profile) keeps a table of the modules allowed to start a program and a list of real payloads for every POST
   route: main's repoguard.py (read-only git, like doctor's) and the routes /api/demo (first-run) and /api/watchdog-fix (watchdog) are
   added to them."""
import re
import sys
from pathlib import Path

ROOT = Path(sys.argv[1])
ROWS = {   # module -> one line for the map, from each branch's own evidence doc
    "agentfiles.py": "Finds CLAUDE.md or AGENTS.md in a project and whether it carries agentboard's agent block (`init --instructions`, the doctor's agents line).",
    "demo.py": "The sample cards `init --demo` and `POST /api/demo` seed on a new board, and the welcome text a bare `agentboard` prints.",
    "guards.py": "The work profile's socket and subprocess guards: with the profile on, nothing but loopback connects and no program starts.",
    "profile.py": "The work-PC profile: read from the environment, a machine file or config; `apply()` sets the lock and no-plugins before anything loads.",
    "selfcheck.py": "`agentboard selfcheck`: a static scan of the package plus a live audit of a throwaway (or the running) server, as PASS/FAIL lines.",
    "statefile.py": "One way to write the small JSON state files beside tasks.json: atomic replace, flock'd read-modify-write, a sweep of stale temp files.",
    "tomlread.py": "`loads()`/`load()` for config.toml and pyproject: tomllib when Python has it, a hand parser on 3.9 and 3.10.",
    "watchdog.py": "The agent protocol's watchdog: the ways a board is stuck between agents, each with its one fix (`agentboard watchdog`, the Load strip, a doctor line).",
}

def arch():
    p = ROOT / "docs" / "ARCHITECTURE.md"
    if not p.exists():
        return
    s = p.read_text()
    real = {q.name for q in (ROOT / "src" / "agentboard").glob("*.py")}
    named = set(re.findall(r"`([a-z_0-9]+\.py)`", s))
    missing = sorted(real - named)
    if not missing:
        return
    anchor = re.search(r"^\| `cursors\.py` \|.*\n", s, re.M) or re.search(r"^\| `store\.py` \|.*\n", s, re.M)
    rows = "".join(f"| `{m}` | {ROWS.get(m, 'Added on an overnight branch; see its evidence doc under docs/overnight/.')} |\n" for m in missing)
    s = s[:anchor.end()] + rows + s[anchor.end():] if anchor else s + "\n" + rows
    p.write_text(s)
    print(f"ARCHITECTURE.md: module map rows added for {', '.join(missing)}")

def signoff_table():
    p = ROOT / "docs" / "security-signoff.md"
    if not p.exists():
        return
    s = p.read_text()
    if "chat-wake.json" in s or "chatwake.py" not in "".join(q.name for q in (ROOT / "src" / "agentboard").glob("*.py")):
        return
    old = "| `sessions.json`, `chat-cursors.json`, `chat-delivered.json`, `chat-listeners.json`, `server-<pid>.json` |"
    if old in s:
        s = s.replace(old, "| `sessions.json`, `chat-cursors.json`, `chat-delivered.json`, `chat-listeners.json`, `chat-wake.json`, `server-<pid>.json` |", 1)
        p.write_text(s)
        print("security-signoff.md: chat-wake.json added to the state-file row (600)")

def selfcheck_tomllib():
    p = ROOT / "src" / "agentboard" / "selfcheck.py"
    if not p.exists() or not (ROOT / "src" / "agentboard" / "tomlread.py").exists():
        return
    s = p.read_text()
    s2 = re.sub(r"^(\s*)import tomllib\b", r"\1from . import tomlread as tomllib", s, flags=re.M)
    if s2 != s:
        p.write_text(s2)
        print("selfcheck.py: import tomllib -> from . import tomlread as tomllib (the 3.9 floor's rule)")

def doctor_cap():
    p = ROOT / "tests" / "test_doctor.py"
    if not p.exists():
        return
    s = p.read_text()
    old = "        self.assertLessEqual(len(text.splitlines()), 20)\n"
    if old in s:
        p.write_text(s.replace(old, "        self.assertLessEqual(len(text.splitlines()), 24)   # the overnight branches each add a line (agents, watchdog, masking, profile)\n", 1))
        print("test_doctor.py: the report's line cap 20 -> 24")

DOC_ROWS = {
    "security-signoff.md": "The two-page security sign-off: what was checked on the night of Nov 7-8, how, and what a reviewer can rerun.",
}

def docs_index():
    p = ROOT / "docs" / "index.md"
    if not p.exists():
        return
    s = p.read_text()
    added = []
    for q in sorted((ROOT / "docs").glob("*.md")):
        if q.name != "index.md" and f"]({q.name})" not in s:
            s = s.rstrip("\n") + f"\n| [docs/{q.name}]({q.name}) | {DOC_ROWS.get(q.name, 'Added on an overnight branch; see the first lines of the document.')} |\n"
            added.append(q.name)
    for d in sorted(x for x in (ROOT / "docs").iterdir() if x.is_dir()):
        if f"docs/{d.name}/" not in s:
            s = s.rstrip("\n") + f"\n\nThe folder `docs/{d.name}/` holds " + ("the overnight quality push's evidence, one file per card, and the merge kit (see its README.md)." if d.name == "overnight" else "further documents; see its own README.") + "\n"
            added.append(d.name + "/")
    if added:
        p.write_text(s)
        print(f"docs/index.md: rows added for {', '.join(added)}")

def selfcheck_tables():
    p = ROOT / "src" / "agentboard" / "selfcheck.py"
    if not p.exists():
        return
    s = p.read_text()
    changed = []
    if (ROOT / "src" / "agentboard" / "repoguard.py").exists() and '"repoguard.py"' not in s and '    "doctor.py": ' in s:
        s = s.replace('    "doctor.py": ', '    "repoguard.py": "read-only git queries (ls-files) for the repo guard the doctor and the tests share; a command, never the server",\n    "doctor.py": ', 1)
        changed.append("repoguard.py allowed to run read-only git")
    anchor = '        go("/api/clear-done", {})\n'
    if anchor in s:
        add = ""
        if "/api/demo" in (ROOT / "src" / "agentboard" / "server.py").read_text() and 'go("/api/demo"' not in s:
            add += '        go("/api/demo", {})                                      # the empty board\'s sample cards (first-run)\n'
        if "/api/watchdog-fix" in (ROOT / "src" / "agentboard" / "server.py").read_text() and 'go("/api/watchdog-fix"' not in s:
            add += ('        with contextlib.suppress(Exception):                    # a twin card, the one fix the watchdog can do on a fresh board\n'
                    '            S.start("Selfcheck twin", "AGENT-9", None)\n'
                    '            S.start("Selfcheck twin", "AGENT-9", None, task_id="selfcheck-twin-2")\n'
                    '        go("/api/watchdog-fix", {"action": "merge", "id": "selfcheck-twin-2"})\n')
        if add:
            s = s.replace(anchor, anchor + add, 1)
            changed.append("real payloads for /api/demo and /api/watchdog-fix")
    if changed:
        p.write_text(s)
        print("selfcheck.py: " + "; ".join(changed))

def server_os_import():
    """server-lifecycle's /api/health does `import os` inside the GET router; perf-scale imports os at the module top and calls os.stat
    earlier in the same function, so the local import makes `os` a function local and every /api/hud raises UnboundLocalError. The
    module-level import is kept and the local one dropped (the author's one-line fix; this is the stopgap until it lands)."""
    p = ROOT / "src" / "agentboard" / "server.py"
    if not p.exists():
        return
    s = p.read_text()
    if re.search(r"^import os$", s, re.M) and re.search(r"^\s+import os$", s, re.M):
        s2 = re.sub(r"^\s+import os\n", "", s, flags=re.M)
        p.write_text(s2)
        print("server.py: a local `import os` inside the router dropped (os is imported at the top)")

arch(); signoff_table(); selfcheck_tomllib(); doctor_cap(); docs_index(); selfcheck_tables(); server_os_import()
