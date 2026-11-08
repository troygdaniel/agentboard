# overnight-config-validation (AGENT-7, Nov 8 overnight)

Branch `overnight/overnight-config-validation` in the public repo, worktree `~/dev/agentboard-wt/AGENT-7-config`, rebased onto `overnight/combined-11` at 59b848e (the eleven reviewed branches plus the merge kit's fixups; Nov 8). Not
merged: Troy reviews. No push, no spend, no live text.

## What changed

| Piece | Where |
|---|---|
| **One schema**: every core section and key with type, default, range, choices, meaning and an "unsafe" note; `[providers.<name>]` and `[agent_colors]` as tables of entries; `[orch] agents` as a list of tables. | `src/agentboard/configschema.py` (`SCHEMA`, `PROVIDER_KEYS`, `Field`) |
| **Fail closed**: `prompt.load_config` hands every module the cleaned config (`configschema.clean`): an invalid core value is its default, with a finding that says so; unknown keys and sections pass through (a plugin reads its own). `load_config(raw=True)` is the file as written, for the check. | `prompt.py` |
| **`agentboard config check`**: unknown section or key with the closest valid name (difflib), wrong type, out of range, a choice misspelt (`markdwn` → `markdown`), unsafe switches as WARN; exit 1 on an invalid value. **`config show`**: every applying value with its source (default / file / default because invalid) and which `AGENTBOARD_*` variables are set (never a value). **`config docs`**: the reference page. | `cli.py` (`cmd_config`) |
| **doctor** carries the findings as `schema` lines (PASS when clean). | `doctor.py` (`check_config_schema`) |
| **Plugins** add their own section: `api.add_config(section, {key: Field})`; refused for a core section. | `plugins.py` |
| **Docs generated from the schema**: `docs/config.md` is `config docs`' output; `test_configschema.test_the_docs_page_is_the_schema` fails when they differ. The README's configuration section points at it. | `docs/config.md`, `README.md` |
| **Tests** (15): typos and their suggestions, unknown sections (INFO when no close name: a plugin's), the sample config `init` writes and the README block are clean, every key the code reads is in the schema and every schema key is read somewhere, types and ranges fall back to defaults and the board runs on the cleaned config, choices, roster and colours, unsafe switches are warnings (and `[redact] enabled = false` stays the owner's choice, reported), no private string in a finding, `effective` sources, the three commands, the docs page, plugin sections, doctor's lines. | `tests/test_configschema.py` |

## Before and after

| | Before | After |
|---|---|---|
| `[board] stale_minute = 90` (typo) | ignored, no message; the default applied without a word | `WARN board.stale_minute is not a key the board reads (did you mean 'stale_minutes'?)` in `config check` and `doctor` |
| `[chat] autopilot_every = 5` | accepted; the server clamps to 30 in one place and not in another | `FAIL ... must be int 30..86400; it is out of range (default 180 used)`; every reader sees 180 |
| `[board] stale_minutes = "x"` | each reader had its own guard (`hud.stale_minutes` caught it, others would have raised) | one guard, the default, one finding |
| `[redact] enabled = "no"` | `is not False` → masking on, silently | `FAIL ... must be bool, not a string (default True used)` |
| `[redact] enabled = false` | silent | `WARN redact.enabled masking is OFF for this board's cards ...` (allowed: the owner's choice) |
| `[providers.docs] type = "markdwn"` | a prompt build error later | `FAIL providers.docs.type must be one of markdown, file-tail, http, command (did you mean 'markdown'?)` |
| "what does this board run with?" | read config.toml and the code | `agentboard config show`: value and source per key, `AGENTBOARD_*` set/unset |
| "what keys exist?" | the README's short list and `SAMPLE_CONFIG`'s comments, drifting | `docs/config.md`, generated; a test pins it |

## How to try it

    cd ~/dev/agentboard-wt/AGENT-7-config
    PYTHONPATH=src python3 -m unittest tests.test_configschema -v
    mkdir /tmp/cfgdemo && cd /tmp/cfgdemo && PYTHONPATH=~/dev/agentboard-wt/AGENT-7-config/src python3 -m agentboard init
    printf '[board]\nstale_minute = 90\n[chat]\nautopilot_every = 5\n[redact]\nenabled = false\n' >> .agentboard/config.toml
    PYTHONPATH=~/dev/agentboard-wt/AGENT-7-config/src python3 -m agentboard config check     # exit 1, three lines
    PYTHONPATH=~/dev/agentboard-wt/AGENT-7-config/src python3 -m agentboard config show      # chat.autopilot_every 180 default (file value invalid)
    PYTHONPATH=~/dev/agentboard-wt/AGENT-7-config/src python3 -m agentboard doctor | grep "schema"

## Test results

Full suite on the branch (`python3`, 3.14), run alone: **Ran 1300 tests, OK** (1285 on `main` plus the 15 schema tests). `python3 tests/publiccheck.py`: 0 findings. The schema module alone: 15 tests in under a second.

## Risks and what I did not do

- **`redact.settings` reads config.toml itself** (its own cache by mtime), not through `load_config`, so the masker's `[redact]` reading is unchanged by
  the cleaning; its own `is not False` rule already fails closed for a wrong type. The check reports the section like any other.
- **Plugin sections are unknown to a plain shell**: `config check` from a shell without `AGENTBOARD_PLUGINS=1` reports `[texts]`, `[facts]` as INFO
  ("a plugin's, when the plugin is loaded?"), not as errors. The home plugin does not yet call `api.add_config`; that is a one-card follow-up in the
  home repo (its sections, with `reply_cap` 1..100, would then be range-checked here too).
- **Unknown keys are kept**, by design: a later version or a plugin may read them. The report is the protection, not deletion.
- **`config show` prints numbers, booleans and four named strings** (`board.owner`, `chat.idle_model`, `notify.sound`, `agent_colors.*`); every other string, every list and every plugin value is `(set, not shown)`, so a `[redact] extra` pattern, a `[knowledge]` path or a plugin's phone number never reaches the terminal; findings never quote a string value either.
- Not done: a `config set key value` command (the file is small and hand-edited by design), and migrating every module's own `.get(...)` default to the
  schema's (the defaults agree today; `test_every_key_the_code_reads_is_in_the_schema` is the net).

## After the rebase onto overnight/combined-11 (de06986)

- `doctor.py` keeps both the combined tree's `check_redact` (`masking` line: FAIL when `[redact] enabled = false`) and `check_config_schema`
  (`schema` lines); `prompt.load_config` reads through the combined tree's `tomlread` and then cleans. The schema's own WARN on
  `redact.enabled = false` stays (it is the schema's view; the `masking` FAIL is the doctor's verdict).
- The 15 schema tests and the doctor, lockdown and source-hygiene tests pass on the rebased tree; the full suite result is below.
- `docs/ARCHITECTURE.md` and `docs/index.md` (from the architecture branch, now in the combined tree) gained the `configschema.py` row, the `add_config`
  call and the `docs/config.md` entry, because `test_docs_architecture` asked for them: the drift test did its job on the first merge.
- **Suite on the rebased branch**: at de06986 `Ran 1603 tests`, 7 failures and 1 error: the three `test_docs_architecture` ones above (fixed), and the
  `test_workprofile` / `test_signoff_files` ones that are on the bare combined tree too (work profile fixed by the kit's 59b848e; the sign-off mode test,
  `.claude/settings.json is 0o600`, is the open cross-review card on the data-integrity branch). After moving onto 59b848e: `test_workprofile` 63 OK,
  `test_docs_architecture` and `test_configschema` 27 OK; `test_signoff_files` fails on the bare 59b848e the same way.

## After the 06:00 cross-review (AGENT-8: xr-config-show-prints-secrets HIGH, xr-config-check-label-and-tomllib)

- **`config show` printed too much**: only six sections' strings were hidden, so a `[redact] extra` pattern (which may be the secret itself), a
  `[knowledge]` path and any plugin string (a phone number) came out verbatim. Now `configschema.shown` prints numbers, booleans and an allowlist
  of four strings; everything else is `(set, not shown)` or `(N entries, not shown)`. A test feeds a key, a path and a phone-shaped plugin value
  and asserts none appears.
- `label` is a provider key (`prompt.py` reads it; `config check` warned on a valid file). The schema-to-code test now runs both ways: every
  provider option the code reads must be in `PROVIDER_KEYS`.
- The tests use `tomlread.loads` (no unguarded `tomllib`, for the 3.9 floor). An invalid value with no default (a provider `type`) is kept as
  written by `clean`, so the reader's own message names it (`unknown type markdwn`, not `None`). The CHANGELOG says which readers go through
  `load_config` and that the reporting is on demand (`check`, `doctor`, `show`).
