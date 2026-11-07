# Timed text pull: did it meet the bar? (product check, Nov 7)

Companion to AGENT-1's page `texts-timer-morning-2026-11-07.md` (what landed, the steps for you, how to reverse). This page is only the verdict.

**Verdict: ready to merge.** 16 of the 17 acceptance lines were met in `7ae60dc`; the one gap (line 9) was fixed by AGENT-1 in `b6d0831` and I re-ran my repro: the timer now stops and says "unexpected error (IncompleteRead)". Branch `texts-timer`; I ran its full suite at `b6d0831`: 899 tests OK. The only line still partly open is 17 (narrow width not captured).

## What you do

1. After ORCH merges and installs: `export AGENTBOARD_TEXTS=1` beside your Twilio exports, restart `agentboard serve`, tick **Settings › Texts › Pull my texts every minute**. (AGENT-1's page has the detail.)
2. Top up Twilio before about Dec 6: balance US$0.89, the number fee is US$1.15.
3. Nothing else needs you. Nothing was pushed, spent, or changed on Twilio.

## The 17 lines

| # | Line | Result |
|---|------|--------|
| 1 | Off on a fresh install and after a restart until you switch it on | Met |
| 2 | `AGENTBOARD_NO_SMS=1`: no timer, no call, switch shown disabled with a reason | Met (checked on every beat) |
| 3 | Settings only; the Pull texts button still works by hand | Met |
| 4 | About once a minute, never two pulls at once | Met (a lock stops stacking) |
| 5 | One card per text ever, across restarts, flips and the button | Met |
| 6 | Only your own number counts | Met |
| 7 | A text is data; nothing runs from it; nothing texted back | Met |
| 8 | At most 20 cards a pull | Met |
| 9 | A Twilio error stops the timer with one quiet chip, no retry | Met after `b6d0831`. Before it, an error that was not a `BoardError` (for example `http.client.IncompleteRead`) left the switch on and retried every 5 seconds; now any exception stops it and the chip carries the class name only |
| 10 | After an error nothing resumes by itself | Met (any exception stops it, after `b6d0831`) |
| 11 | Plain status: Off, Pulling every minute (last pull, new count), Stopped: reason | Met |
| 12 | Cards from the timer carry the From a text chip | Met |
| 13 | Only outside call is the Twilio read; local only | Met |
| 14 | SID and token never in the board, state, chip or repo | Met (a test checks the state file; the branch has no copy of your mobile number) |
| 15 | No Twilio account or number changes, no spend | Met |
| 16 | Tests cover the list | Met (26 new) |
| 17 | Render-check in light, dark and narrow, off, on and error | Partly: light and dark done for all three states; **narrow (479px) not captured** (Chrome would not shrink). The only narrow rule is one line of CSS |

## Open, in order of weight

1. **Narrow check**: a quick look at the board at phone width after the merge.
2. **AGENT-3 sign-off** (security and QA) was still running when this was written; this page does not replace it.
3. Test count is 899 at `b6d0831` (AGENT-1's page now says the same).

## Not in this build (parked)

Texting back, replies, webhooks or a tunnel, a configurable interval, other numbers.

## To reverse this check

Nothing to reverse; this page is the only file my work added. Delete it, or `git revert` its commit.
