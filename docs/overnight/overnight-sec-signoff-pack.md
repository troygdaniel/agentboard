# overnight-sec-signoff-pack: evidence

Card: `overnight-sec-signoff-pack` (AGENT-8, night of 2026-11-07). Branch `overnight/overnight-sec-signoff-pack`, built on `main` 3cec02a.
Nothing merged, nothing pushed, no spend, no live text. Docs only: no code or test changed.

## What changed

- `docs/security-signoff.md` (new): the two-page sign-off a work reviewer reads. Every line cites the file and the test that proves it;
  what could not be proved is under **Known limits**.
- this file.

## How each claim was verified

| Claim in the sign-off | How it was checked tonight |
|---|---|
| No dependencies | `pyproject.toml`: `dependencies = []`; `grep -rn "^import\|^from" src/agentboard/*.py` lists stdlib names only |
| Loopback only, one outbound-capable module | `grep -n "urllib.request\|socket\|http.client" src/agentboard/*.py` hits `providers.py` and `server.py` only; `server.py:435` binds `127.0.0.1`; `agentboard doctor` on a throwaway board printed `PASS listeners … all loopback only`, `PASS connections no open connection to another machine`, `PASS code modules that can make an outbound connection: providers; modules that can listen: server` |
| The whole suite makes no connection off the machine | full suite run under a pytest plugin that monkey-patches `socket.socket.connect`, `connect_ex` and `socket.getaddrinfo` to refuse and log any non-loopback target (source below). Result: **1184 passed, 2 failed, 0 refusals logged** (the log file stayed empty) |
| Programs the board can start, and that the master lock refuses them | `grep -n "subprocess\.\|Popen\|webbrowser" src/agentboard/*.py` (listed in the sign-off by file:line); `tests/test_lockdown.py` (7), `tests/test_lockdown_wiring.py` (9), `tests/test_plugins.py` (master lock, narrow lock) |
| Files written and their modes | a throwaway project under `AGENTBOARD_LOCKDOWN=1` with a throwaway `HOME`: `init`, `add`, `claim`, `chat send`, `hooks install`; then `find` + `stat -f %Lp`. Result: `.agentboard/` 700, every file in it 600 (`.lock`, `tasks.json`, `tasks.json.bak`, `config.toml`, `sessions.json`, `backups/` 700 with a 600 `.json.gz`); `.claude/settings.json` 644 and `.gitignore` under the user's umask by design (`private.py:56`); **nothing written under HOME**. `tests/test_file_modes.py` (14 tests) covers the same under `umask 022` |
| The two hooks | `hooks.py:99-125` (mirror), `:128-158` (stop), `:173-230` (install: absolute, shell-quoted path), `:261` (uninstall); the entry written tonight was `<install path>/agentboard hook send-message` on `PostToolUse[SendMessage]` and `<install path>/agentboard hook stop` on `Stop`; `tests/test_hook_install.py` (8 tests) |
| Request guards | `server.py:25` `MAX_BODY = 1_000_000`, `:106,127` Host allow-list, `:156` exact `application/json`, `:161` `Sec-Fetch-Site`/`Origin`; `tests/test_post_guards.py`, `test_prompt_get_guard.py`, `test_plugin_get_csrf.py`, `test_http_limits.py`, `test_page_csp.py` |
| Masker scope and gaps | `tests/test_redact*.py` (8 files); the gaps named as known limits were reproduced on main tonight in the merge review (cards `rev1107-redact-url-empty-user`, `rev1107-redact-short-basic`) |
| Transcript route | `transcript.py:45-59`: only a resolved `.jsonl` under `~/.claude/projects` is served |
| Public repo clean | `python3 tests/publiccheck.py` on this branch: `0 finding(s)` |

## Test run on this branch

First run (the machine carrying six other agents' suites, load average 16 to 20), under the hand-made socket guard:

```
2 failed, 1184 passed, 29 subtests passed in 178.27s
FAILED tests/test_redact_dos.py::EveryShapeIsLinear::test_a_megabyte_of_any_shape_prefix_is_masked_in_well_under_the_limit
FAILED tests/test_redact_fullwidth.py::StillFast::test_hostile_amounts_of_fullwidth_text
```

Both are wall-clock limits (`LIMIT = 2.0` s); rerun alone under the same load the fullwidth test passed and the dos test measured 2.06 s.
Second run, later the same night with the guard now part of the suite (`overnight-sec-nonet-guard`, same branch): **exactly green under both
runners**: pytest `1196 passed, 29 subtests passed in 199.06s`; `unittest discover -s tests` `Ran 1196 tests, OK`.

## The socket guard (to rerun the no-network proof)

Save as `sockguard.py` somewhere on `PYTHONPATH`, then `SOCKGUARD_LOG=/tmp/sockguard.log python3 -m pytest -q -p sockguard`; an empty log
means no test tried to leave the machine.

```python
import socket, os
LOG = os.environ.get("SOCKGUARD_LOG", "/tmp/sockguard.log")
_c, _cx, _g = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo
def _loop(a):
    h = a[0] if isinstance(a, tuple) else ""
    return not isinstance(a, tuple) or h in ("127.0.0.1", "localhost", "::1", "0.0.0.0", "") or h.startswith("127.")
def _note(k, a):
    open(LOG, "a").write(f"{k} {a!r}\n")
def connect(self, a):
    if not _loop(a): _note("REFUSED connect", a); raise OSError("non-loopback refused")
    return _c(self, a)
def connect_ex(self, a):
    if not _loop(a): _note("REFUSED connect_ex", a); raise OSError("non-loopback refused")
    return _cx(self, a)
def gai(h, *x, **k):
    if h not in (None, "", "localhost", "127.0.0.1", "::1", "0.0.0.0") and not str(h).startswith("127."):
        _note("REFUSED getaddrinfo", h); raise socket.gaierror("non-loopback refused")
    return _g(h, *x, **k)
socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = connect, connect_ex, gai
```

## What weakens the story (from tonight's merge review, filed as cards, not fixed here)

Update after the rebase onto main (00:0x, Nov 8): ORCH merged fixes for the listener race (7381e9e), the two masker shapes (88712d4),
the Stop hook cursor case (16a273c), the repro's live-board read (a287e1d) and the autopilot marking (e5eb381) during the night; the sign-off's
known limits were updated to match. The `[redact]` switch now has a doctor line (`overnight-sec-doctor-redact-switch`).

- HIGH `rev1107-listeners-race`: `chat-listeners.json` has no lock; concurrent waits lose entries (reliability).
- MEDIUM `rev1107-redact-url-empty-user`, `rev1107-redact-short-basic`: two credential shapes the masker misses.
- MEDIUM `rev1107-stophook-case`, `rev1107-repro-reads-live-board`, `rev1107-autopilot-marks-read`: Stop hook and receipts correctness.
- `[redact] enabled = false` in an agent-writable `config.toml` turns masking off (`redact.py:156-170`); stated as a known limit.
- Doc drift: `SECURITY.md` and `docs/security-audit-2026-11-07.md` still say "one hook" and omit the look-alike folding (cards
  `rev1107-doc-audit-one-hook`, `rev1107-doc-security-md-folding`).

## Risks of this change

None to the code. The sign-off cites line numbers of `main` 3cec02a; a later refactor moves them. `agentboard selfcheck` is named as
pending work on another branch; if that branch is not merged, drop the sentence.

## How to try it

Read `docs/security-signoff.md`; run the three commands under "Checking it yourself" on a throwaway project; compare the file table with
`find .agentboard -exec stat -f '%Lp %N' {} \;`.
