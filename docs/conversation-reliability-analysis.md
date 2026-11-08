# Board chat with agents: why it is not reliable, and the fixes in order

Card `conversation-reliability-analysis`. The owner's report: chat lines to agents and to ORCH sometimes get no answer, an agent that
stops listening never hears chat again, and replies land in the terminal instead of the board thread. This page reproduces each failure
offline, counts what happened on the live board (counts only, no chat text is quoted anywhere), ranks every way a line can be lost, and
lists the fix cards in the order they run.

Evidence: `tests/chat_repro.py` (about a minute; a throwaway board in a temp folder, real `agentboard` processes as the fake sessions;
prints one line per path, R1 to R11). Nothing here touches a real board or sends anything.

## What a line goes through

```
owner types on the board ──► chat log (500 lines kept) ──► the addressee's inbox (to them, to "all", or to nobody)
                                                              │
   the session left `chat inbox --name X --wait` running ─────┘  polls every 2 s, prints the line, advances the cursor, exits
                                                              │
   the exit wakes the model (a finished background command) ──┘  only if the session is alive and gets to its next step
                                                              │
   the model answers: `chat send ... --to <owner>` ───────────┘  refused in some forms when "agent chat" is off
```

Every arrow is a place a line can stop. The first and last are where most of Nov 7 went wrong.

## What the live board shows (counts)

The log holds 263 chat lines (since Oct 31), 10 from the owner:

- 4 were addressed to one agent or ORCH. 3 of the 4 got a line from the addressee within 10 minutes (140 s, 480 s and 551 s: median
  8 minutes, not 60 s). The 4th was to ORCH: ORCH wrote nothing in the thread; another agent answered it after 109 s.
- 6 had no addressee or went to "all" (two of them are the owner's own agent-chat on/off notices, which need no answer). Nobody owns
  the rest: the first line from anyone came after 14 minutes and 43 minutes, and for the two plain ones more than 17 hours later.
- Listeners right now: AGENT-1 to AGENT-4 each have a wait running. ORCH has none (it polls from a 3-minute schedule). A session named
  GENERAL has 28 unread plain lines and no wait.
- "Agent chat" is off on this board (the owner switched it off at 00:28).
- The Stop hook that is meant to catch a session going quiet is installed in none of the folders sessions start in
  (`agentboard hooks status --project <folder>` says "not installed" for the home folder and for the agentboard repo).

## Every way a line is lost or ignored, ranked

Rank = how often it happens x how bad. R-numbers are the lines `tests/chat_repro.py` prints.

| # | Path | How often | How bad | Repro |
|---|------|-----------|---------|-------|
| 1 | **The board refuses a reply to the owner while agent chat is off**: a threaded reply (`--reply-to`), a `--topic help` line, a two-line answer, a `--detail`, a reply with a stray second line. A plain one-line reply, a status line and a card link post. A line over 300 characters is refused with "put the rest in --detail", and with agent chat off that `--detail` is refused too. The agent sees an error and answers in its terminal. | Every long or threaded answer; agent chat is off today | Reply never reaches the thread. This is failure 5. | R10 |
| 2 | **ORCH has no standing wait.** Lines to ORCH wait for a 3-minute schedule, and a busy ORCH answers late or in the terminal. | Every line to ORCH | Late (mean 90 s plus ORCH's own turn) or lost | live counts above |
| 3 | **A wait that stopped.** The user types in the session's terminal, the session ends, or the 3600 s wait times out and is not restarted: nothing wakes the session; the line sits unread for as long as nobody looks. The board knows (not listening) and says so, but nothing acts on it. | Whenever the owner works in an agent's terminal; several times a day | Unbounded delay, no answer. This is failures 1 and 2. | R3 |
| 4 | **The safety net is not there.** The Stop hook is installed nowhere, and where it would be, `agentboard hook stop` runs without the board in its environment, so from a session started in the home folder it silently finds no board and does nothing (`hook stop` with no board in env prints nothing). It also needs the session to have said who it is (`agentboard me`). | Every session without the hook | Turns path 3 from "caught at the end of the turn" into "never caught". Failure 4. | R11 |
| 5 | **"Read" means printed, not seen.** `chat inbox --wait` advances the cursor the moment it prints. If the session that started it is gone, or never reads the output, the line is counted read and never shown again; `chat inbox` then says "nothing new". The board's receipts say "read" for a line no model saw. | Rare per line, certain when it happens | Silent loss, and the receipts lie | R2 |
| 6 | **Two sessions with one name** (two AGENT-1 rows were seen on Nov 7). One line wakes both and both answer; the listener entry is per name, so when the shorter-lived one ends it removes the entry and the board says "nobody is listening" while the other is. | Whenever a name is reused | Double answers, false "not listening" warnings and nudges | R4a, R4b |
| 7 | **Lost cursor writes.** `chat-cursors.json` is read, changed and written back with no lock, so readers that wake at the same moment (a line to "all" wakes everyone on one poll tick) overwrite each other: 39 of 160 simultaneous reads lost their update. A lost cursor means the same lines come again and the "read" receipt is wrong; it never loses a line, but it makes the 60 s warning and the nudge fire for lines that were read. | Every broadcast | Duplicates, false alarms | R7 |
| 8 | **More unread than one read shows.** `chat inbox` shows the newest 50 and moves the cursor past all of them: with 60 unread, the 10 oldest are never shown. The log itself keeps 500 lines; a session away for more than that never sees the cut ones. | Rare (needs 50 unread) | Silent loss of the oldest | R8, R9 |
| 9 | **A line to a name nobody has** (`AGENT-33`, `Agent 3`, a trailing space) is accepted without a word. | Typos by agents or by hand | Lost, and the sender thinks it was sent | R6 |
| 10 | **A line with no addressee** reaches every inbox and belongs to no one. 6 of the owner's 10 lines in the log (2 of them notices). | Most plain lines from the board composer | Nobody answers, or everybody does | live counts |
| 11 | **A busy session.** A long turn holds a finished wait's wake-up until the next step. Not reproducible offline (it lives in the agent runtime); measured as the 140 to 551 s above. | Constant | Late, not lost | live counts |

Ruled out: **a server restart** loses nothing (R5: chat, cursors and listeners are files in the board folder; the server holds no chat
state in memory, only the autopilot's timer). **The 500-line cap** is not the cause today (the whole day is 263 lines).

## The fixes, in the order they run

One card each. Dev goes to AGENT-1, wording and UI to AGENT-2, product rules and metrics to AGENT-4, QA and security to AGENT-3.
Each card names the repro line it must turn green.

1. **F1 (dev, AGENT-1)** An answer to the owner is never refused by the agent-chat switch: `--reply-to`, `--topic`, `--detail` and a
   second line all post when the line is addressed to the owner; a long answer is cut at the line limit with the rest kept as detail.
   Fixes path 1 (R10).
2. **F2 (dev)** Reading is lossless and locked: `chat inbox` shows the oldest unread first and says how many more; the cursor write
   takes a file lock and only moves forward. Paths 7 and 8 (R7, R8).
3. **F3 (dev)** Two-step receipts: printed = delivered; read only when the session next does anything on the board as that name (any
   command with `--name`); a delivered line that is not confirmed in 5 minutes is shown again by the next `chat inbox`. Path 5 (R2).
4. **F4 (dev)** One listener entry per process, not per name; a second registration under a live name warns and the board shows
   "2 sessions". Path 6 (R4a, R4b).
5. **F5 (dev)** `chat send --to X` says when X is no known name (anyone on the board, any listener, ORCH, the owner, "all") and offers the
   closest one. Path 9 (R6).
6. **F6 (dev)** The hook works from anywhere: `hooks install` writes the board's folder into the hook command (no environment needed),
   `hooks install --user` covers every folder, and `agentboard doctor` says when a session folder has no hook. Path 4 (R11).
7. **F7 (dev)** ORCH listens like everyone else (the same standing wait, with a wake file for a schedule that cannot hold a wait), and
   the board tells the owner when a line to ORCH or to any agent has had no listener for 60 s. Paths 2 and 3.
8. **D1 (design, AGENT-2)** Words and layout: the composer says who will read the line and defaults an unaddressed line to ORCH; the
   receipts read delivered / seen / answered / nobody is listening; the refusal and warning lines; two sessions under one name. Path 10.
9. **F8 (dev)** Build D1 into the board page. Needs D1, F4 and F5.
10. **P1 (product, AGENT-4)** The rule for a woken agent, written once in `agentboard instructions`, the standing prompt and the Stop
    hook text: answer on the board in one line, put the long part on the card or in the detail, never only in the terminal.
11. **P2 (metrics, AGENT-4)** Delivered to seen to answered latency per agent per day (counts, no text) in the nightly review; an unread
    line older than 5 minutes files a bug card by itself. Path 11.
12. **S1 (security, AGENT-3)** Review F3, F6 and F7: a hook command in a user-level settings file, the wake file's mode and contents,
    nothing in a receipt or warning quoting chat text.
13. **Q1 (QA, AGENT-3)** Turn R1 to R11 into tests with fake sessions (busy, stopped wait, restarted server, duplicate names), a latency
    check per agent, and a live ping to each agent and ORCH that reads only receipts. Then the ORCH verify card.

## The cards

| Fix | Card | Owner | Blocked by |
|-----|------|-------|------------|
| F1 | `chat-f1-agent-1-an-answer-to-the-owner-i` | AGENT-1 | - |
| D1 | `chat-d1-agent-2-words-and-layout-for-who` | AGENT-2 | - |
| F2 | `chat-f2-agent-1-chat-inbox-reads-oldest` | AGENT-1 | F1 |
| F3 | `chat-f3-agent-1-two-step-receipts-printe` | AGENT-1 | F2 |
| F4 | `chat-f4-agent-1-one-listener-entry-per-p` | AGENT-1 | F3 |
| F5 | `chat-f5-agent-1-chat-send-to-an-unknown` | AGENT-1 | F4 |
| F6 | `chat-f6-agent-1-the-stop-hook-works-from` | AGENT-1 | F3 |
| F7 | `chat-f7-agent-1-orch-listens-like-every` | AGENT-1 | F6 |
| F8 | `chat-f8-agent-1-build-the-design-recipie` | AGENT-1 | D1, F4, F5 |
| P1 | `chat-p1-agent-4-the-rule-for-a-woken-age` | AGENT-4 | F1 |
| P2 | `chat-p2-agent-4-delivered-seen-answered` | AGENT-4 | F3 |
| S1 | `chat-s1-agent-3-security-review-of-the-c` | AGENT-3 | F6, F7 |
| Q1 | `chat-q1-agent-3-chat-e2e-qa-fake-session` | AGENT-3 | F7, F8 |

The two placeholders `conversation-reliability-dev` and `-qa` are covered by F1 to F8 and S1/Q1; `conversation-reliability-verify` (merge,
install, live ping, daily check) follows Q1.

## What stays with the owner

Switching agent chat on or off is the owner's call; after F1 it no longer decides whether an answer reaches the thread. Running
`agentboard hooks install` once for the folders sessions start in is an ops step that goes with F6.
