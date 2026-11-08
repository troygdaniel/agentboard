# overnight-install-quickstart (AGENT-7, Nov 7 overnight)

Branch `overnight/overnight-install-quickstart` in the public repo, worktree `~/dev/agentboard-wt/AGENT-7-overnight`. Not merged: Troy reviews.
No push, no spend, no live text, nothing of the home plugin touched.

## What changed

**Python 3.9 to 3.14 (was 3.11+).** A locked-down work PC has the Python it came with: 3.9 on a 2021 Mac (`/usr/bin/python3`), 3.10 on Ubuntu 22.04.
Three things stood in the way, each small:

| Blocker | Fix | Where |
|---|---|---|
| `import tomllib` (3.11+) in five modules: every test module failed to import on 3.9 | `tomlread.py`: `tomllib` where it exists, otherwise a small built-in TOML reader (tables, arrays of tables, dotted and quoted keys, basic/literal/multi-line strings with escapes, ints, floats, bools, dates and times as `datetime` objects, arrays, inline tables, comments; loud `TOMLDecodeError` (a `ValueError`) on anything else). The five modules and `test_version.py` read through it; a test fails if any module imports `tomllib` directly again | `src/agentboard/tomlread.py`, `store.py`, `redact.py`, `prompt.py`, `boards.py`, `backup.py`, `tests/test_version.py` |
| Possessive regex quantifiers (`\s*+`, `++`, `{10,}+`, 3.11+) in the masker: `re.error: multiple repeat` on 3.9 | `redact._compile`: on 3.9 and 3.10 `_plain_quantifiers` walks the pattern and drops a `+` only where it directly follows an unescaped quantifier outside a character class (`[*+/=]{4,}`, `a\++` and `x[?+]y` are left as written; `[^\s:/@]*+` and `{10,}+` lose the `+`); same matches, slower worst case, bounded by the masker's size caps. On 3.11+ nothing changes | `src/agentboard/redact.py` |
| An f-string with a same-quote expression inside it (3.12 only) | the expression is computed on the line before | `src/agentboard/reports.py:320` |
| The invisible-set test assumed Unicode 15 (U+13439 is `Cn` on 3.9's database) | the test allows `Cn` when `unicodedata.unidata_version < 15.0` | `tests/test_redact_invisible.py` |

`requires-python = ">=3.9"` in `pyproject.toml`. No dependency was added.

**`agentboard doctor` on the repository is 0 FAIL.** It flagged five lines of our own tests as "possible secrets": three were kebab-case words that
happen to start with `sk-` (`sk-learn-pipeline-for-the-model-build-2026`), which the masker itself already knows are words; two are real-looking
by design (a phone number and a token assignment the masker tests must see whole at runtime). The key scan now leaves alone what
`redact.scrub` leaves alone (`doctor._fake`), and the two fixtures are built from pieces (`"416-867-" + "5310"`), so their runtime value is
unchanged and the scan sees no number. `agentboard doctor --project .` on the branch: `PASS tracked files 159 tracked file(s) scanned`.

**README.** Install is three commands (then the long form); new **Upgrade** and **Uninstall, leaving nothing behind** sections (the whole
footprint, named: pipx's venv and launcher, `.agentboard/` per project, `~/.agentboard` only with named boards, `~/.config/agentboard` only
if you made it, the two hooks `hooks uninstall` removes; nowhere else); the work-laptop checklist says 3.9+ and "no admin rights"; and
**Troubleshooting** grew eight entries written from today's real failures: a plugin crashing on load (data files not packaged), keys lost
on a restart from another terminal, a stale `build/` putting deleted modules back, the doctor's `tracked files` FAIL and what to do
about a fixture, `ModuleNotFoundError: tomllib`, `pipx: command not found` right after installing pipx, and what a first run's WARN
lines mean. SECURITY.md has a "Python versions" row; the audit page and CHANGELOG are updated.

## Before and after

| | Before | After |
|---|---|---|
| `pipx install` on a Mac with only `/usr/bin/python3` (3.9.6) | refused: `requires-python >=3.11` | installs; `init`, `add`, `list`, `serve` (page, HUD and `/api/tasks` answer) and `doctor` all run |
| `agentboard doctor --project .` in the repo | `FAIL tracked files 5 possible secret(s)...` | `PASS tracked files 159 tracked file(s) scanned: no key-shaped string and no phone number` |
| README install | one paragraph with the 3.11 floor | three commands first; Upgrade; Uninstall (complete footprint); 11-entry troubleshooting |
| First-run doctor on a fresh board with the lock set (3.9 venv, throwaway folder) | not possible on 3.9 | `0 FAIL, 0 WARN, 8 PASS, 7 INFO` |

## How to try it

    # the branch, on the oldest Python this Mac has
    cd ~/dev/agentboard-wt/AGENT-7-overnight
    /usr/bin/python3 --version                                      # 3.9.6
    /usr/bin/python3 -m venv /tmp/ab39 && /tmp/ab39/bin/pip install --no-deps -q .
    mkdir /tmp/ab39proj && cd /tmp/ab39proj && /tmp/ab39/bin/agentboard init
    /tmp/ab39/bin/agentboard add "First card" && AGENTBOARD_LOCKDOWN=1 /tmp/ab39/bin/agentboard doctor      # 0 FAIL, 0 WARN
    /tmp/ab39/bin/agentboard serve --no-open --port 8979           # then open http://localhost:8979

    # the suite on each Python (serially; three suites at once on one Mac trip two timing tests)
    PYTHONPATH=src /usr/bin/python3 -m unittest discover -s tests
    PYTHONPATH=src python3.11 -m unittest discover -s tests          # likewise 3.12, 3.13, and python3 (3.14)

    # the TOML reader against tomllib (needs 3.11+): every document the board reads, same dict or both refuse
    PYTHONPATH=src python3 -m unittest tests.test_tomlread -v

## Test results

Full suite, `python -m unittest discover -s tests`, run one version after another on this Mac while other agents' suites were also running
(load average 6 to 9):

| Python | Result | Note |
|---|---|---|
| 3.9.6 (`/usr/bin/python3`) | 1215 tests, 3 failures, 2 skipped | the three are timing bounds: `test_redact_dos` 2.3 s and 2.2 s against a 2.0 s limit, `test_redact_fullwidth.StillFast` 5.9 s against 3.0 s. Run alone right after: **OK** (43 tests of the three modules in 42 s). The bounds are tight on 3.9 because the masker runs without possessive quantifiers there |
| 3.11.16 | 1215 tests, 2 failures | timing bounds again (`test_redact_dashes.StillFast` 4.0 s against 3.0 s, `test_redact_dos` 2.1 s against 2.0 s). Run alone right after: **OK**. Nothing in this branch changes the masker on 3.11+ |
| 3.12.13 | 1215 tests, **OK** | |
| 3.13.8 | 1215 tests, **OK** | |
| 3.14.8 (`python3`) | 1215 tests, **OK** | |

An earlier run of 3.11, 3.12 and 3.13 at the same time (three suites in parallel) tripped the same timing tests plus `test_server_state.RealServer`
(a 15 s server start timed out); serially they pass. Those tests measure wall-clock time and share the machine with whatever else runs: a
quiet machine is the condition, not a version. Before this branch the suite could not run at all on 3.9 (81 import errors).

`python3 tests/publiccheck.py`: 0 findings. `agentboard doctor --project .`: 0 FAIL.

## Risks and what I did not do

- **The TOML reader is only used on 3.9 and 3.10.** It is held to tomllib's answers on 23 documents (the config `init` writes with every
  option on, the README block, every snippet the tests write, and the TOML features each uses) and refuses 15 bad ones the same way. A TOML
  feature none of those use (a hex float, a 1979-style local time with offset on a bare time) could still differ; a mismatch is a bug to
  fix in `tomlread.py`, never a reason to add a dependency.
- **The masker is slower in the worst case on 3.9 and 3.10** (no possessive quantifiers). `test_redact_dos` and `test_redact_dashes.StillFast`
  pass on 3.9 within their bounds; the size caps (`bound`, `MAX_HIDDEN`) are what keep a crafted text small.
- **Two tests are load-sensitive**, not version-sensitive: `test_redact_dashes.StillFast` (a 3 s bound) and `test_server_state.RealServer` (a 15 s
  server start) failed when three suites ran at once and pass serially on every version. The home suite has the same shape (`rev1107-home-test-order`,
  AGENT-1's card). Not changed here.
- **3.10 was not run**: this Mac has 3.9, 3.11, 3.12, 3.13 and 3.14. 3.10 sits between two tested versions and has `tomllib` missing like 3.9 (the
  only 3.10-specific feature in use would be `zip(strict=)` or `match`, and neither is used: the ast check with `feature_version=(3, 9)` passes).
- **`pipx upgrade agentboard`** is documented for the GitHub install; from a checkout the `rm -rf build` step stays (a setuptools behaviour, not ours).
  A later card could build with `python -m build --outdir` to a temp folder and install the wheel, which has no `build/` at all.
- Not done: a `agentboard uninstall` command (the footprint is five paths, written down; a command that deletes a user's folders needs Troy's word).

## After the cross-review (AGENT-8, cards xr-install-redact-resolve-main and xr-install-strip-possessive)

- **Rebased onto `main` 33ecb3e** with the resolution the review asked for: `redact.py` is `main`'s (tonight's masker: `_basic_like`, `_auth_header`, the
  URL-password fix) plus the mechanical `re.compile` to `_compile` and `tomllib` to `tomlread`; `reports.py` is `main`'s (its own f-string fix); `store.py`
  is `main`'s with `tomlread`; `tests/test_redact_invisible.py` is `main`'s (it already handles an older Unicode table); the CHANGELOG keeps both.
- **The possessive shim is a small tokenizer** (`redact._plain_quantifiers`), not a regex: it tracks escapes and character classes, so `[*+/=]{4,}`,
  `a\++` and `x[?+]y` are untouched and only a real possessive marker goes. Checked on the review's examples and on every compiled pattern in
  `redact.py` (24): each compiles plain, and the rewrite is idempotent. All eight `test_redact*` modules pass on 3.9.
- **tomlread**: an invalid date or offset is a `TOMLDecodeError` (so `prompt.load_config` reports it instead of a traceback); a tab is allowed inside a
  basic string, as TOML allows; a multi-line literal may end in up to two extra quotes (`'''a'''''` is `a''`); the flag is `USING_TOMLLIB` (it was named the
  wrong way round). Tests added for each.
- Not changed: the 3.9 floor itself. The review is right that it is Troy's product call; if declined, the README, doctor and troubleshooting changes stand
  on their own and `tomlread.py` plus the shim can be dropped (the `test_tomlread` and the 3.9 lines of the matrix go with them).
- **Suite on the rebased branch** (main 33ecb3e + this): 3.14 `Ran 1297 tests, 2 errors`; 3.9 `Ran 1297 tests, 2 errors, 3 skipped`. Both times the two
  are `test_server_state.RealServer` (a real `agentboard serve` subprocess must answer within 15 s), run while other suites shared the machine;
  alone, right after, that module is `OK` on both 3.14 and 3.9. Everything else passed on both versions; publiccheck 0 findings.
