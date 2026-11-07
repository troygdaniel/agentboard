# Morning summary: the board pulls your texts once a minute (overnight, Nov 6–7)

Card: `add-a-todo-board-card-to-setup-agent-boa` (AGENT-1 dev; AGENT-3 QA + security, AGENT-2 design, AGENT-4 product; ORCH merges).
Branch `texts-timer` off `main` (5738913), three commits: 7ae60dc, b6d0831, 5806616, worktree `~/dev/agentboard-texts-timer`. Nothing pushed, nothing spent, Twilio untouched.

## What you must do (two minutes)

1. In the terminal that runs the board, next to your two Twilio exports, add the new second key and restart the board once ORCH has merged and installed:

       export AGENTBOARD_TEXTS=1
       agentboard serve

   Without it there is now **no** Pull texts button, switch, chip or `pull-texts` command on that machine (your work laptop can never turn it on from the board).
2. Settings (gear or `m`) › **Texts** › tick **Pull my texts every minute**. Text yourself; a Todo card appears within about a minute, no press needed.
3. Twilio balance is US$0.89 and the number costs US$1.15 on ~Dec 6: top up or set auto-recharge before then, or the number lapses. (Your account; nobody else touches it.)

## What landed

- **The timer.** `agentboard serve` runs the same `pull-texts` by itself about every 60 s while the switch is on. OFF on a fresh install; the switch is server side (`.agentboard/texts-state.json`, key `auto`), so it is one switch for every browser and holds across restarts and with the tab closed. The Pull texts button still works by hand.
- **Settings › Texts.** One row: the switch and a plain status line (Off · Pulling every minute, last 2m ago, 1 new · Stopped: reason). Hidden entirely unless both keys turn; shown disabled with the reason when `AGENTBOARD_NO_SMS=1`.
- **Header chip.** "● Texts 2m ago" (green) while it runs, "● Texts stopped" (amber) after an error; press it to open Settings. Under 600px only the dot. No toast, no sound, no popup for a timed pull or its error.
- **Any error stops it.** Refused sign-in, no network, any 4xx/5xx, a variable gone: the switch goes off, the reason is kept (variable names, never values), nothing retries until you switch it on again.
- **Two keys for anything texts (your rule, built in).** `AGENTBOARD_TEXTS=1` (machine) **and** `[texts] enabled = true` (board); `AGENTBOARD_NO_SMS=1` beats both. All of it goes through one function, `texts.allowed()`, checked on every beat, on the switch, on the button and on the command, so the follow-up card `texts-optin-worklaptop-lock` can tighten it in one place. The timer thread is not even started without the key.
- Same rules as before: your own number only, a text is data (it only becomes a card), one card per text ever (a restart, a flip or the button never makes a twin), at most 20 cards a pull, the one read-only call to `api.twilio.com`, nothing texted back.

## Checked

- 905 tests pass (32 new in `tests/test_texts_timer.py`: off by default, restart keeps the switch, lock on the tick and the switch, once per text across restart/flip/button, stranger ignored and never stored, 401 stops with no retry, network error stops, an unexpected error (not a BoardError) stops too, vanished token stops and names the variable only, no two pulls at once, state file has no secrets, the endpoint on/off/locked/no-key, the page's switch and chip, SECURITY.md updated).
- Render-checked on a throwaway board with a fake Twilio (no network): Settings row Off, On (with last pull), Stopped (amber line), header chip in all three, light and dark. **Narrow (479px) was not captured**: the Chrome window would not shrink below its minimum in this session; the only narrow rule is one line of CSS (the chip keeps its dot and drops its words under 600px) and the sheet already fits narrow widths.
- The live board at :8765 was not touched; your `.agentboard/config.toml` is unchanged.

## How to reverse each piece

- Stop the timer: untick the switch (or delete the `auto` key in `.agentboard/texts-state.json`). Stop everything texts on a machine: unset `AGENTBOARD_TEXTS` (or set `AGENTBOARD_NO_SMS=1`).
- Remove the feature: `git revert` the one commit on `texts-timer`; the state file's extra keys are ignored by the old code.
- Files touched: `src/agentboard/texts.py`, `src/agentboard/server.py`, `src/agentboard/static/index.html`, `tests/test_texts_timer.py`, `tests/test_pull_texts.py` (the second key in the test env), `README.md`, `SECURITY.md`, `CHANGELOG.md`, `docs/texts-auto-mockup.html`, this page.

## Open

- AGENT-3 asked for 404 (not 400) from the texts endpoints when the keys are off, and a one-line "Text messages: off" note in Settings: left for their follow-up card, as they said.
- A configurable interval, replies, webhooks and other numbers are out of scope (parked, per the card).
