# Timed text pull: did it meet the bar? (product check, Nov 7)

Companion to AGENT-1's page `texts-timer-morning-2026-11-07.md` (what landed, the steps for you, how to reverse). This page is only the verdict.

**Verdict: ready to merge after one small fix.** 16 of the 17 acceptance lines are met in code and tests; line 9 has one gap, on card `texts-timer-unexpected-error-stops`. Branch `texts-timer`, commit `7ae60dc`; I ran its full suite: 898 tests OK.

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
| 9 | A Twilio error stops the timer with one quiet chip, no retry | **Gap**: an error that is not a `BoardError` (for example `http.client.IncompleteRead`) leaves the switch on and the loop retries every 5 seconds with no chip. Verified with a short repro. Fix is a few lines in `texts.tick` |
| 10 | After an error nothing resumes by itself | Met for the errors it catches |
| 11 | Plain status: Off, Pulling every minute (last pull, new count), Stopped: reason | Met |
| 12 | Cards from the timer carry the From a text chip | Met |
| 13 | Only outside call is the Twilio read; local only | Met |
| 14 | SID and token never in the board, state, chip or repo | Met (a test checks the state file; the branch has no copy of your mobile number) |
| 15 | No Twilio account or number changes, no spend | Met |
| 16 | Tests cover the list | Met (25 new) |
| 17 | Render-check in light, dark and narrow, off, on and error | Partly: light and dark done for all three states; **narrow (479px) not captured** (Chrome would not shrink). The only narrow rule is one line of CSS |

## Open, in order of weight

1. **Line 9 gap**: card `texts-timer-unexpected-error-stops`, unassigned. AGENT-1 and AGENT-3 have been told. It is a few lines and one test; best done before the merge.
2. **Narrow check**: a quick look at the board at phone width after the merge.
3. **AGENT-3 sign-off** (security and QA) was still running when this was written; this page does not replace it.
4. AGENT-1's page says 871 tests; the branch has 898. Cosmetic, told to AGENT-1.

## Not in this build (parked)

Texting back, replies, webhooks or a tunnel, a configurable interval, other numbers.

## To reverse this check

Nothing to reverse; this page is the only file my work added. Delete it, or `git revert` its commit.
