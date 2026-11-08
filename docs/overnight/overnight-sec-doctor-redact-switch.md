# overnight-sec-doctor-redact-switch: evidence

Card: `overnight-sec-doctor-redact-switch` (AGENT-8, night of 2026-11-07), filed from `overnight-sec-timing-tests-load`. Branch
`overnight/overnight-sec-signoff-pack` (fifth commit). Nothing merged, nothing pushed, no spend, no live text.

## Why

The sign-off lists as a known limit that `[redact] enabled = false` in the board's `config.toml` turns the secret masker off for every write
path, silently, and that file can be edited by any process running as you (an agent included). Tonight's merge review found the same switch
also disables the home plugin's SMS masker and the facts "secret" rule (cards `rev1107-sms-redact-config`, `rev1107-facts-redact-config`).
Nothing told the owner. `agentboard doctor` is the place a reviewer looks.

## What changed

- `src/agentboard/doctor.py`: `check_redact(board_dir)`, run after the config check. It reads `redact.settings` (the same reader the masker
  uses, so what doctor says is what the masker does) and prints one line:
  - `FAIL  masking  secret masking is OFF: [redact] enabled = false in config.toml, so keys and tokens agents write reach tasks.json, the
    backups, the reports and the page as written; fix: delete that line (or set it to true)`
  - `WARN  masking  secret masking is on with changes from the default: phone numbers are masked too (phones = true); N pattern(s) of your
    own are added (extra = [...]); make sure they are yours` (a pattern is never printed: it may be the secret itself)
  - `PASS  masking  secret masking is on with the default shapes ([redact] in config.toml is absent or unchanged)`
  A config that cannot be read is a WARN with the error's class name only. `redact` joined the known sections, so it no longer appears
  under "other sections, not checked here". Doctor stays read-only.
- `tests/test_doctor.py`: two tests (the three states, the fix line, no pattern printed, the line is part of `doctor.run`, `redact` is known).
- `docs/security-signoff.md` known limit 2 cites the check; `README.md` doctor paragraph names it; `CHANGELOG.md` one line.

## Seen on a throwaway board

```
PASS  masking        secret masking is on with the default shapes ([redact] in config.toml is absent or unchanged)
# after appending [redact] enabled = false to config.toml:
FAIL  masking        secret masking is OFF: [redact] enabled = false in config.toml, so keys and tokens agents write reach tasks.json, the backups, the reports and the page as written; fix: delete that line (or set it to true)
1 FAIL, 1 WARN, 10 PASS, 5 INFO        exit 1
# with phones = true instead:
WARN  masking        secret masking is on with changes from the default: phone numbers are masked too (phones = true); make sure they are yours
```

## Tests

```
PYTHONPATH=src python -m pytest -q        1206 passed, 29 subtests passed in 200.11s   (exactly green; tests/test_doctor.py 46 passed)
```
`python3 tests/publiccheck.py`: 0 findings.

## Risks

- A board whose owner turned masking off on purpose now sees a FAIL on every doctor run and exit code 1. That is the intended reading: on
  a managed machine masking off is a finding; at home the owner knows why and can ignore one line.
- The check trusts `redact.settings`' cache (keyed by the file's mtime), the same as the masker, so the two cannot disagree.
