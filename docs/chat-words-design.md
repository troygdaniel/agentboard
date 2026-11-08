# Chat: who reads a line, and what became of it

**Status: design only, nothing built.** Card `chat-d1-agent-2-words-and-layout-for-who`; it answers loss paths 5, 6, 9 and 10 of `docs/conversation-reliability-analysis.md` and is the input to F8. Mockup (light, dark, narrow, every state): `docs/chat-words-design-mockup.html`, with `chat-words-design-light.png`, `-dark.png` and `-narrow.png`. Every line in it is made up; no real chat text is in this repo.

## The vocabulary, once

The same word means the same thing in the composer, the receipt, the agent's head and the terminal.

| Word | Means |
|------|-------|
| **listening** | a wait of its own is running: a line wakes it |
| **not listening** | no wait is running: nothing on the board wakes it |
| **2 sessions** | more than one live session answers to this name (N for more) |
| **sent** | on the board, in its inbox, nothing has printed it |
| **delivered** | a session printed it |
| **seen** | that session has done something on the board as that name since |
| **answered** | it wrote back to you |

`sent` is the one new word. Once F3 gives `delivered` its true meaning (printed, not merely in the inbox), the first 60 seconds of a line would have no word at all, and a line with no word reads as broken.

Receipts and warnings carry names, states and times. **Never a quote of the line.**

## 1. Under the box: who will read this

One line under every chat box (the ORCH drawer, an agent's thread, a card's chat), in the small muted size, shape `Goes to NAME · state`. It follows what is typed.

| Typed | Line |
|-------|------|
| nothing (drawer) | `Goes to ORCH · listening` (the box says `Message ORCH, or @AGENT-2…`) |
| `@AGENT-2 can you…` | `Goes to AGENT-2 · listening` |
| same, no wait running | `Goes to AGENT-2 · not listening: it reads this when its session next runs` (amber) |
| same, two sessions | `Goes to AGENT-1 · 2 sessions: both may answer` (amber) |
| `@AG` (still typing the name) | `Names: AGENT-1, AGENT-2, AGENT-3 · Tab takes the first` |
| `@all …` | `Goes to everyone listening (4). No one owns the answer.` |
| an agent's thread | `Goes to AGENT-2 only · listening` |
| a card's chat | `Goes to AGENT-2, who holds this card · listening` |

**The board never sends a line with no reader.** The drawer's default is ORCH. A name that is not on the board is stopped (section 3), not quietly turned into an ORCH line.

## 2. The receipt under a line you sent

Right-aligned under your bubble, a small uppercase word. Nothing here changes how a line to everyone (`@all`) reads: it has no receipt.

| State | Under the bubble | Look |
|-------|------------------|------|
| sent | `SENT` | muted |
| sent, 60 s, agent not listening | `SENT` `Nobody is listening for AGENT-4.` `[Nudge via ORCH]` | amber |
| sent, 60 s, ORCH not listening | `SENT` `Nobody is listening for ORCH. Type in its terminal, or Copy prompt starts one.` (no Nudge: it goes through ORCH) | amber |
| sent, 60 s, listening but busy | `SENT` `AGENT-3 is listening but busy: it reads this when its step ends.` | muted |
| after the Nudge | `SENT` `Nobody is listening for AGENT-4.` `ORCH asked 2m ago to message it` | amber, no button |
| delivered | `DELIVERED` | muted |
| delivered, 5 min, not seen | `DELIVERED` `Not seen in 5 min: it comes again with the next inbox read.` | amber |
| seen | `SEEN` | blue |
| answered | `ANSWERED` | green |
| any state, two sessions | the word, then `2 sessions` | amber chip |

The 60 s and 5 min are the analysis's numbers (RECEIPT_WARN_S and F3). A state never goes backwards on screen: the words only move right.

## 3. A send that does not go

The line replaces the "goes to" line, stays until the next keystroke, and **the text stays in the box**. Today the box is cleared before the board answers (`i.value = ''` runs first), so a refused send loses what you typed; F8 must keep the text until the send is accepted.

On the board (amber, one line, what happened then what to type):

| Case | Line |
|------|------|
| unknown name | `No one named AGENT-33. Did you mean AGENT-3? Tab uses it.` |
| unknown, nothing close | `No one named Bob. On this board: ORCH, AGENT-1, AGENT-2, AGENT-3.` (six names, then `and 2 more`) |
| only a name | `Add what to tell AGENT-2 after the name.` |
| the board did not take it | `Not sent: the board did not answer. Your text is still here; send again.` |

In the terminal (what an agent's `chat send` prints; exit code 1 when nothing was posted):

| Case | Line |
|------|------|
| unknown name | `Not sent: no one named AGENT-33. Closest: AGENT-3. Send again with --to AGENT-3.` |
| unknown, nothing close | `Not sent: no one named Bob. Names on this board: ORCH, AGENT-1, AGENT-2.` |
| agent chat off, agent to agent | `Not sent: agent chat is off, so agents post one-line status only. A line to the owner still goes; to reach another agent, the owner runs: agentboard chat agents on` |
| over the limit, agent to agent | `Not sent: 412 characters, the limit is 300. Shorten it, or keep the rest in --detail.` |
| over the limit, to the owner (after F1) | `Sent, cut at 300 characters: the rest is in the detail.` |

## 4. Two sessions under one name

One amber chip, `2 sessions` (`3 sessions` and so on), after the name wherever the name shows: the agent's thread head, its lane in By agent, its receipts, the "goes to" line. Its tooltip is the whole explanation and the fix:

> Two sessions answer to AGENT-1. A line reaches both and both may answer. Rename one with /rename in that session.

- The thread head keeps its two lines as they are; the chip sits on the name, so the status line does not repeat it.
- `listening` is true while either session is waiting; `nobody is listening` appears only when both are gone, so the false warning from path 6 cannot happen.
- No per-session identity (no pid, no id) is shown; the board cannot tell the owner which is which, only that there are two.
- The chip goes away by itself when one session ends.

## For F8

- One small function, `whoReads(text, defaultTo)`, returns `{to, state, error}`; the three forms call it on every keystroke. The names come from F5's list; until it exists, use the board's agents, the listeners, ORCH and the owner.
- Keep the text in the box until the board accepts the send (section 3).
- `receiptOf` gains `sent` and renames `read` to `seen`; the table in section 2 is the copy.
- The 2-session count needs F4's per-process listeners to arrive as `listening[name].sessions`.
- Reserve the "goes to" line's height so the box does not jump as the line changes; on a narrow screen it may wrap to two lines.
- Light and dark use only the board's tokens (`--warn`, `--info`, `--ok`, `--muted`); the mockup copies the board's own `.cmsg-rcpt`, `.chat-form` and `.chip` rules, so each piece maps to one class.

## Where I chose and the analysis is silent

For ORCH to confirm:

1. **`sent` is a new word** (above). The alternative is to keep `delivered` for "in the inbox" and call a printed line `read`; that is the reading that makes receipts lie today.
2. **A wrong name is blocked, never rerouted.** Sending `@AGENT-33 …` to ORCH instead would answer the typo with a line ORCH does not understand.
3. **`@all` stays possible but is labelled**, and has no receipt. The board never sends a line with no addressee.
4. **A busy listener is muted, not amber.** A session that is listening and mid-step is normal; amber is kept for "nobody is listening" and "delivered but not seen in 5 min".
5. **The Nudge keeps its name and its place**; only the sentence around it changes.

## Not designed

A per-session name or colour for two sessions; a count-down to the 60 s warning; a sound or badge for a line that went unseen; the Stop hook's own wording (card P1).
