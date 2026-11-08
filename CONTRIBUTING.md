# Contributing

agentboard is developed by its owner and a set of AI agents working in parallel, each in its own git worktree, each on a card on the board
itself. The rules below are the ones that kept that from going wrong; they apply to a person just the same. `docs/ARCHITECTURE.md` says how
the code is built; `CLAUDE.md` is the prompt the agents read, and the source of the card and chat conventions summarised here.

## Work on a card, in a worktree

- **Every piece of work is a card** on the board (`agentboard start "<title>" --name <you>` or `agentboard claim <id> --name <you>`), with at
  least two subtasks (do it, check it), a real percentage kept current, and `agentboard review` when it is ready. The owner marks it done;
  nobody marks their own card done. Ask the orchestrator one question before starting if anything is ambiguous, not during.
- **One branch per card, in its own worktree**, so parallel agents never share a working tree:

      git worktree add -b <branch> ~/dev/agentboard-wt/<your-name>-<topic> main

  Branch names in use: `wt-<AGENT>-<topic>` for ordinary cards, `sec-*` / `rev*-*` for review findings, `overnight/<card-id>` for the overnight
  pushes (those are never merged by the orchestrator; the owner reviews them). Commit only your own changes: several agents edit
  `static/index.html` at once, and another agent's unfinished work must never ride along in your commit.
- **Never a bare `git stash`.** The stash stack is shared by every worktree; a `stash pop` can take another session's changes. Make a
  temporary commit instead, or `git stash push -u -m "<unique tag>"` and `git stash apply <sha>`.
- **Hand over a hash, not a merge.** When the card is ready, the branch's commit hash goes to the orchestrator (on the card and in chat); the
  orchestrator merges into `main`, runs the suite, installs, and only then is the card done. Pushing to GitHub is the owner's act.

## The gates: what "ready" means

Run all of these on your branch before you say a card is ready. The orchestrator runs them again after the merge.

1. **The whole suite is exactly OK.** `python3 -m unittest discover -s tests` (with `PYTHONPATH=src` or an editable install). Run it alone:
   the masker's wall-clock tests trip when several suites share the machine, and that is not a failure of the code.
2. **The repo guard finds nothing.** `python3 tests/publiccheck.py`. It fails on key-shaped strings, phone numbers that are not fictional
   (area code 555, or 555-01xx), emails outside the allow-list, a real account's `/Users/<name>/` path and your private words (one per line in
   `~/.config/agentboard/private-words.txt`, outside the repo). A test that needs a real-looking value builds it from pieces (`"AKIA" + "…"`)
   so the runtime value is unchanged and the file holds no secret.
3. **`agentboard doctor --project .` has no FAIL** (its `tracked files` line is the same scan as the guard, from the installed code).
4. **A change to `static/index.html` is render-checked live**: `rm -rf build && pipx install . --force`, restart `agentboard serve`, open the
   board wide and narrow, open a card. The tests do not render the page; a bad edit once blanked the board. `CLAUDE.md` has the headless
   recipe when no browser is at hand.
5. **The version agrees in three places** when you bump it: `pyproject.toml`, `src/agentboard/__init__.py`, the README's `# prints:` line.
6. **Every documented install from a checkout removes `build/` first** (`rm -rf build && pipx install .` on one line): setuptools keeps files
   deleted from `src/` in `build/` and would reinstall them. `tests/test_install_clean.py` reads the docs for this.

## The changelog rule

Every change a user could notice gets an entry at the **top of `## Unreleased`** in `CHANGELOG.md`, in the shape the file already uses:

    ### <one sentence saying what is true now> (<Mon D>)
    - what was wrong or missing, what changed, in plain words; the cards or commits it closes
    - what is NOT covered, when there is something (the next card's title, if one exists)

No entry for a change nobody can notice (a comment, a test fixture). A release moves `Unreleased` under a version heading, bumps the
three version places, and tags `vX.Y.Z`.

## Commits and messages

- One commit per card where it can be one; the subject is a sentence saying what is true now ("Listeners: register and unregister under a
  file lock, written atomically"), the body says why and what it does not cover. A subject that only names a file or says "fix" tells the
  next reader nothing.
- The merge commit says which branch (`Merge <branch>`), so `git log` reads as the board's history.
- A commit an AI agent wrote carries the attribution trailer its tool asks for (`Co-Authored-By: …`).

## Docs

- `README.md` is for the person using the board; `docs/ARCHITECTURE.md` for the person changing it; `SECURITY.md` and the audit page for the
  person deciding whether to run it. `docs/index.md` lists every document with one line; add yours there.
- A plan or design document that shipped gets a **Status** line at the top saying built, where, and that the code (or the README) is the
  source of truth where they differ. Stale plans cost a review a whole card of corrections once.
- Screenshots and mockups in `docs/` come from a **throwaway board** (`AGENTBOARD_DIR` pointing elsewhere, made-up cards), never the live one.
- Never `git add -f .agentboard`. Never paste a real number, key or address into a test, a doc or a card description that gets committed.

## What belongs where

- The public repository is the board: no feature that texts, dials, spends or needs a credential. Those live in a separate plugin package
  (`docs/ARCHITECTURE.md`, "The plugin hook"); `test_plugins` fails if `plugins.py` names one.
- A new risky capability (starts a program, sends data) is off by default, has a config or environment key, and calls `lockdown.refuse(...)`
  first. `agentboard doctor` should be able to say whether it is on.
- Python version: see `requires-python` in `pyproject.toml`; the standard library only, no dependency, is a feature the audit relies on.
