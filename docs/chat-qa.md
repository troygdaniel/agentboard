# Chat QA: the end-to-end suite, the live check, and what they prove

Card `chat-q1`. The loss paths in [`conversation-reliability-analysis.md`](conversation-reliability-analysis.md) (R1 to R11) were fixed one card at a time; this
page is the test that keeps them fixed, and the check ORCH runs on the real board.

## The suite: `tests/test_chat_e2e.py` (about a minute)

```
PYTHONPATH=src:tests python3 -m unittest test_chat_e2e          # or as part of the whole suite
```

Fake sessions are **real `agentboard chat inbox --wait` processes** started in a folder with no board in it, as agents start them, so a test can leave one
busy, kill it, run two under one name, or let it read late. The server is the real one on a free loopback port (and, for the restart test, a real
`agentboard serve` process killed with SIGKILL). The receipt a line shows is **the page's own `receiptOf`**, extracted from `static/index.html` and run in
node, so a change to the page that breaks a state fails here instead of in front of the owner. Nothing leaves 127.0.0.1; no real board is read.

| Class | Loss path | Proves |
|---|---|---|
| WakeAndLatency | R1, the 3-minute poll | five waiting sessions (four agents and ORCH) hear a line within 2.5 s, median under 1.5 s; a line to `all` reaches each once; ORCH on a schedule learns of a post in one stat of the wake file, which holds a counter and a name, never the words |
| ReceiptsTellTheTruth | R2, R3, R11 | a busy session shows delivered, then late after 5 minutes, then the line comes AGAIN with the reason on its next read, then seen when it acts on the board, then answered when it replies to that line; a reader that was gone does not lose the line; a stopped wait is `sent` then at 75 s `late, listening: false` (the page's "Nobody is listening" and Nudge) and history after a day; the Stop hook blocks an agent with an unread line from any folder and leaves a non-agent session alone |
| OneNameTwoSessions | R4 | two waits under one name count 2, the second is told at once, and the shorter-lived one ending does not take the other's entry |
| WrongNames | R6 | a line to a name nobody has is refused with the closest known name (three spellings); a known name in another case goes |
| ManyReadersAndManyLines | R7, R8, R9 | twelve sessions printing at the same instant, then acting at the same instant, lose no delivery record and no cursor; sixty unread lines come out oldest first across two reads, none lost; **R9 (a log cut at 500 lines is silent) is an expected failure with its own card** |
| TheServerRestarts | R5 | a SIGKILLed server loses no line and no receipt, and a line posted by the CLI while it was down is delivered |
| WhatAnAgentMayAnswer | R10 | with agent chat off, plain, threaded, topic, two-line, detail, long and card-linked answers to the owner all post; agent-to-agent still needs the switch |
| TheHooksAtUserLevel | R11 | `hooks install --user` bakes the board folder in; only registered agents are mirrored; the user's original settings survive install, a re-install for another board and uninstall (`.orig`) |
| LatencyPerAgent | the latency check | for a fast, a slow and a gone reader: delivery under 4 s each; the slow one is `late` after 5 minutes, the gone one stays `delivered` and never becomes `seen`, the fast one is `seen` once it acts |
| TheLiveCheckScript | the live check | `tests/chat_live_check.py` is read-only by default, prints no words, and `--send --yes` posts one ping per listener and ORCH |

`tests/chat_mutants.py` breaks each fix in a scratch copy (a print that moves the seen cursor, no re-show, a second wait replacing the first, a wake file that
never moves, an unknown name accepted, an answer to the owner counted as agent talk, newest-page inbox, a hook that ignores `--dir`, a mirror for any
session, no pristine settings copy, a stop hook that ignores an unread line, a confirmation that is not recorded, a wait that polls) and says whether the
suite notices. All 13 mutants are killed (each by one to seven tests).

## The live check: `tests/chat_live_check.py`

```
python3 tests/chat_live_check.py                  # read-only: who is listening (sessions), and the state of each recent line to one name
python3 tests/chat_live_check.py --send --yes     # also post ONE harmless line to each listening agent and ORCH, watch their receipts 30 s
```

It prints names, counts, ages and states, never a line's words. Without `--send` it writes nothing. `--send` posts a line the whole board sees and that wakes
every agent it names, so it runs only when ORCH or the owner says so (card `conversation-reliability-verify`).

What the first read-only run on the real board (Nov 8, 05:30) showed: AGENT-1 to AGENT-6 and AGENT-8 each listening with one session; **ORCH not listening**,
so a line to ORCH reaches it only through the wake file on its schedule; the four recent lines to one name were `seen` or `wrote back`.

## Known gaps

- The board records when a line was **delivered** but not when it was **seen** or **answered**, so the latency check can time delivery only. A real
  seen/answered latency needs those two times recorded (the metrics card `chat-p2`).
- The Nudge (the owner's click that asks ORCH to message a session) is checked as far as the board: that the line is marked and the wake file moves. What
  ORCH's SendMessage does next is outside the board.
- A busy session is simulated by not acting on a delivered line (time is moved for the page's clock and the delivery record's stamp). How long a real
  model's turn takes is not measurable offline.
