# Is agentboard safe on a managed work laptop? The security audit, 7 Nov 2026

**Verdict: safe to run there, with the settings in the checklist below. One decision belongs to the board's owner (the board has no login), and two jobs are the owner's, outside the code (a key kept in a plain file, and one private word list).** Written against `main` at 0d92375 (v0.3.1). Nothing here is a claim about your organization's own policies; check those yourself.

## In plain words

- **Nothing leaves the laptop by itself.** The board listens on `127.0.0.1` only (one port, 8765), makes no outside request, has no dependencies, no install scripts, no telemetry and no update check. Its page loads nothing from the internet.
- **The things that could reach out are all off until you switch them on:** the `claude` rounds and `agentboard run` (they start the `claude` program, which talks to Anthropic), the `command` and `http` providers, the `[backup] sync_dir` copy, voice, and plugins. **`export AGENTBOARD_LOCKDOWN=1` in the shell profile refuses every one of them**, even if a copied `config.toml` says otherwise. `agentboard doctor` says whether it is on.
- **The texting features are not in the code any more.** They live in a separate package, outside this repository, that only a machine that wants it installs. A test fails if the words "twilio", "sms" or "pull-texts" ever come back into `src/agentboard`.
- **Hostile text on a card cannot run script in the page** (the one HIGH finding, a quote in card text, is fixed; I re-ran the attack in a browser). Secrets pasted into cards, chat or the Terminal tab are masked before they are stored. The board's files are readable only by you.

## What is still open, ranked

1. **MEDIUM, the owner's decision: the board has no login (`sec-local-token`).** Any program running as the same user on the laptop, or a browser extension, can read and change every card through `localhost:8765`. Websites cannot (the Host, Origin and content-type checks block them). The fix is written and tested (branch `sec-web`, commit 5a707ed, 979 tests, browser-tested) but **held, because it changes how the board is used:** after the merge an open tab shows "Disconnected" until `agentboard open` is run once per browser; agents that drive the board in a browser need the same; the CLI is unaffected. `agentboard serve --no-token` turns it off (it prints NOT locked); `git revert 5a707ed` undoes it. *My view, not a finding: turn it on for a work laptop, where other software runs as the same user; leave it off on a personal machine if the extra step is a nuisance. I did not review that branch's code in this pass.*
2. **MEDIUM, the owner's, outside the code: a key kept in a plain file that agent sessions load** (a `CLAUDE.md`, a shell file) travels in every transcript and can show on the board. The data audit found one such key; it is on the owner's card, not here. Move any such key to the keychain or an environment variable and rotate it.
3. **LOW, the owner's: create `~/.config/agentboard/private-words.txt`** (one word per line: family names, an employer, other project names). The public-repo check (`tests/publiccheck.py`, also a test) reads it to catch private words before a push; without the file that one check is skipped. I did not create it. The file lives outside the repo.
4. **LOW, bookkeeping:** the two secret-masking cards (`sec-data-redact-store`, `sec-data-redact-transcript`) are still open on the board, but both changes are in `main` (c70667d and 56dceb8) and I tested the first one.

**Plain statement on history:** the public `main` still contains the old text code in earlier commits (history was not rewritten). The shipped tree does not. Nothing secret is in it: credentials came from the environment, and every phone number in the repo is a fictional 555 one. A reviewer who opens old commits can read the code.

## How it was checked

Five audits ran overnight against `main`, each read-only on a throwaway board: network, install, web (page and API), data (secrets and privacy), and a red-team re-check of the fixes. Their findings became cards; every real one is merged except item 1.

| Audit | Verdict | Fixed and merged |
|---|---|---|
| Network | safe: no connection beyond 127.0.0.1 in 854 tests or a live serve, under a socket guard | the master lock (`AGENTBOARD_LOCKDOWN`), headless `claude` rounds with no tools |
| Install | safe with fixes: nothing runs at install; a copied `config.toml` or `tasks.json` could start programs or make a file | the lock; git-range option injection; hooks install writes the full path |
| Web | safe with fixes: a quote in card text ran script in the page (HIGH) | escaping; Content-Security-Policy and no framing; exact JSON type; timeouts and size caps; prompt GET side effect; transcript path |
| Data | safe with fixes: repo clean, but secrets pasted into cards were kept and most files were world-readable | file modes 0600/0700; secret masking (store, reports, Terminal tab); the public-repo scan |
| Red-team | one fix had not reached `main` (the hooks path), found and merged; two lows fixed | |

**What I re-checked myself on `main` 0d92375** (a throwaway board and server, nothing else touched): `agentboard doctor` (0 FAIL; 1 WARN only when the lock is unset, 0 WARN with it set); the serve process held one socket, `127.0.0.1` only; the board folder is mode 700 and its files 600; the page carries the Content-Security-Policy, `X-Frame-Options: DENY`, `nosniff` and no-referrer; a foreign Origin, a wrong Host, `Sec-Fetch-Site: cross-site` and a non-JSON POST are refused (403/403/403/415) and a 201-character title is refused; hostile card text (`"><img onerror=…>`, `' onmouseover='…'`, `<script>`) showed as words with no script run and no handler attribute in a real browser; a fake API key and AWS key typed into a status line came back as `[redacted …]` and were in no file; with the lock set `agentboard run` refuses, a command provider is skipped (the prompt still builds and says why), nothing is copied to `sync_dir`, and plugins report "locked"; `hooks install` wrote the full path; `agentboard lookup` left the board folder unchanged; `src/agentboard` holds no "twilio" or "sms"; `tests/publiccheck.py` reports 0 findings (its private-words check skipped, see item 3); and the test suite passes (1,004 tests).

**What I did not check:** anything on the work laptop itself; the `claude` program's own traffic, your browser or other apps; Linux and Windows; the voice tools (`whisper`, `ffmpeg`) by running them; the chat rounds' refusal under the lock by running them (I rely on the red-team and the tests); `sec-local-token`'s code; the owner's live `config.toml` and board (not opened, as agreed). Each audit lists its own gaps on its card.

## Work-laptop checklist

**Install** (needs `git`, Python 3.11+, `pipx`; no other dependency)
1. Clone from a copy you have reviewed and pin the commit: `git clone <repo> && cd agentboard && git checkout <reviewed commit>`. If pip must use a mirror, the only package fetched while building is `setuptools>=68`.
2. `pipx install .` (not from a URL on the laptop). Nothing runs at install; there is no setup script, no `.pth` file, no lock file.

**Set, in the shell profile that starts `agentboard serve`**
```
export AGENTBOARD_LOCKDOWN=1      # the master lock: no claude rounds, no run, no command/http providers, no sync copy, no voice, no plugins
export AGENTBOARD_NO_PLUGINS=1    # belt and braces: plugins off even if the master lock is ever unset
```
Do **not** set `AGENTBOARD_PLUGINS` or `AGENTBOARD_TEXTS`. (`AGENTBOARD_NO_SMS=1` only matters on a machine that has the separate texting package; a work laptop never gets it.)

**Check, any time (all read-only, none uses the network)**
```
agentboard doctor                       # want: 0 FAIL, 0 WARN, "PASS lock ... LOCKDOWN is on"; paste it into the review
agentboard plugins                      # want: plugins: locked: $AGENTBOARD_LOCKDOWN is set
lsof -nP -a -p $(pgrep -f "agentboard serve" | head -1) -i     # want one line: 127.0.0.1:8765 (LISTEN), nothing else
ls -ld .agentboard; ls -l .agentboard   # want drwx------ and -rw------- (mode 700 / 600)
grep -rniE "twilio|sms" src/agentboard  # want no output (run in the checkout)
python3 tests/publiccheck.py            # want 0 finding(s), in the checkout, before any push
```

**Do not enable on the laptop**
- `command` or `http` providers in `config.toml`, `[backup] sync_dir`, `[chat] casual` or `autopilot`, `agentboard run`, voice/dictate, any plugin. (The lock refuses them anyway.)
- `agentboard hooks install` in a repo you do not own: it adds one hook to that project's `.claude/settings.json`.
- Agents that read email or web pages and then write into the board: their text becomes card text. It is escaped and masked, but it is untrusted.
- Keep the live board (`.agentboard/`, git-ignored by `init`) out of any repo you push, and take screenshots only from a throwaway board.

## Where to look
`SECURITY.md` (the standing audit, how each check was made, what is opt-in), `README.md` "On a work laptop", `agentboard doctor`, and the cards `sec-audit-network`, `sec-audit-install`, `sec-audit-web`, `sec-audit-data`, `sec-verify-merged-fixes` on the board.
