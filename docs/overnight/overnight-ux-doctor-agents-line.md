# Overnight: doctor says whether agents are connected (overnight-ux-doctor-agents-line)

Branch `overnight/overnight-ux-doctor-agents-line` (worktree `~/dev/agentboard-on-ux3`), stacked on `overnight/overnight-ux-nav-and-panel-words`, which is
stacked on `overnight/overnight-ux-init-agent-instructions` and `overnight/overnight-ux-firstrun`. Merge them in that order. Nothing merged, nothing pushed.

## Why

After `init` and `serve`, a new user's next question is "is anything connected?". Nothing answered it: the board just stays empty until an agent runs
`agentboard start`. `agentboard doctor` already checks the install, the locks, the config and the hooks; it now checks the connection too.

## What changed

`agentboard doctor` gains an **agents** line (two lines at most), read-only:

    INFO  agents  no agent has reported to this board yet
    INFO  agents  CLAUDE.md does not have agentboard's instructions yet: `agentboard init --instructions` adds them (an agent reads them from there)

and once things are connected:

    PASS  agents  2 agents reported to this board: atlas, bolt
    PASS  agents  CLAUDE.md has agentboard's instructions

- The first line reads the cards' agent names from `tasks.json` (up to six names, then "..."); no agent yet is INFO, never a FAIL.
- The second looks at the project's `CLAUDE.md` (else `AGENTS.md`): PASS when it holds the marked block or a hand-pasted `## Agent board` heading, otherwise INFO with the
  command that fixes it; with neither file it says how to make one. A symlinked file is ignored, as `init` ignores it.
- It reads one JSON file and one text file and writes nothing (a test compares every byte and mtime before and after).
- The CLAUDE.md helpers (find the file, has the lines, append) moved from `cli.py` into `agentboard/agentfiles.py` so `init` and `doctor` share one copy; `init`'s behaviour is
  unchanged (its 14 tests pass as written, apart from the names they import).

## Try it

    cd ~/dev/agentboard-on-ux3 && rm -rf build && pipx install . --force
    mkdir /tmp/try && cd /tmp/try && agentboard init --no-demo --no-instructions && agentboard doctor | grep agents
    printf '# Notes\n' > CLAUDE.md && agentboard doctor | grep agents      # says how to add the lines
    agentboard init --instructions && agentboard start "Try it" --name me && agentboard doctor | grep agents

## Checks

- `tests/test_doctor_agents.py`: 11 tests (nobody yet, names and count, a long list cut at six, an unreadable or odd `tasks.json`, no file, a file without the lines,
  the marker and the heading, AGENTS.md alone, a symlink ignored, read-only to the byte, part of `doctor.run` and never a FAIL).
- 12 mutants of the new code (each line dropped, the cut removed, the plural wrong, an empty agent counted, the heading or the link rule bent, a crash on an odd board, the
  check left out of `run`, a FAIL instead of an INFO), all caught.
- The existing `test_doctor` (all of it) and `test_init_instructions` still pass; the second only needed its imports renamed.

## Risks

`doctor` output grows by two lines. Anything that parses it by position would notice; the line format (`LEVEL  name  text`) and the summary are unchanged.

- Full suite on this branch: **1251 tests, OK**; `python3 tests/publiccheck.py`: 0 findings.
