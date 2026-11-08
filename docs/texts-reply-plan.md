# Texts reply: the plan

**Status: built (Nov 7, 2026) in the home plugin, `agentboard-home/src/agentboard_home/reply.py`; that repo's README is the source of truth for what runs. This plan is kept as the record of the rules and the open points; where it differs from the build, the build wins (noted inline).** It settled the rules so `texts-reply-design` (wording, Settings switch) and `texts-reply-build` (the code) can start, and `texts-reply-security` has something to attack. Three points need a yes from you: see **Open points** at the end. All code goes in the home plugin (`agentboard-home`, kept outside this repo). Nothing here touches agentboard itself: its test still fails if "twilio", "sms" or "pull-texts" ever appears under `src/agentboard`.

## What changes

Today the board only **listens**: every 15 seconds (once a minute when this was written) it reads your texts from Twilio and turns each into a card. It sends nothing, and the timer's acceptance list says so ("nothing texted back").

A reply is the board's **first send**. Every reply is one billed outbound text, so it gets its own machine key, its own board key and its own Settings switch. Turning on the pull never turns on replies.

## The five rules, and what keeps each one

| # | Rule | Kept by |
|---|------|---------|
| 1 | Every new text gets a short ack with the card title it made | One reply per text, sent after its card exists. Texts that make no card (empty) get none |
| 2 | A question gets an answer from `lookup` over **cards and reports only** | Two explicit calls, `only="cards"` and `only="reports"`. Never `only=None`: that searches every source a plugin added, notes included. Notes are off (see Open point 2). No model is involved: the answer is a keyword search, not generated text |
| 3 | Plain data, runs nothing, 320 characters at most, only to the allowed number | The reply is a string and nothing reads it back. The recipient is the sender of that text, checked against `allowed` again at send time, never a number found in a text |
| 4 | Daily cap, default 20; at the cap replies **pause** and resume the next day by themselves | A counter in the reply ledger, checked and written **before** each send. No record, no send. The cap is not an error: the control stays on Send, a text that arrives while paused gets its card and `skipped: limit` in the ledger (never a reply, not even tomorrow), and the count starts over with the Mac's calendar day. Only a failed send or a tripped loop guard **stops** (Troy's call, 2026-11-07; the design doc's open point 1) |
| 5 | A reply never triggers another reply | Five layers, below |

## How one pull replies

1. `pull()` makes the cards exactly as today and saves its own state first. It also hands the reply step, in memory only, each **new** text's sender, words and time (never written to disk, never in the page's answer).
2. The reply step runs only if all of these hold: machine key, board key, no lock, the Settings switch on, no halt. Otherwise it does nothing and says nothing.
3. For each new text, oldest first: skip it if its time is before the moment the switch was turned on (so turning replies on never answers old texts), if its message id is already in the ledger, or if it echoes a recent reply (rule 5).
4. Build the reply (next section), clean it, mask secrets, cut it to 320.
5. Check the daily cap. Write the ledger entry (`sending`, count + 1). Only then send. Record the outgoing message id, or the error.
6. Any send error stops **replies** (not pulling) with a one-line reason, and nothing retries until you switch replies on again. A crash between the write and the send leaves `sending` in the ledger, which counts as done: a missing ack is better than a double-billed one.

If one pull makes cards from more than 3 texts, the first 3 get their own reply and the rest share one: `Also added 5: a; b; c; and 2 more`. A dictation burst should not eat the day's cap.

`agentboard pull-texts` (the command) never replies. `--dry-run` prints the replies it **would** send, marked "not sent", so the wording can be checked with no spend. The **Pull texts** button and the timer reply only while the switch is on.

## What a reply says

Board voice, plain ASCII, no links, no emoji. Examples use made-up cards.

| Case | Reply |
|------|-------|
| One card | `Added: Buy toothpaste` |
| Split text, 3 cards | `Added 3: Buy toothpaste; Call the vet; Renew the pass` (cut with `and 1 more` to fit) |
| Question, with matches | `Added: Is the backup tested? - 1) 2026-11-02 Backup restore check: restored 12 cards from a copy, all matched` |
| Question, no match | `Added: Is the backup tested? - No match in cards or reports.` |

- The ack part is the card title cut to 60 characters; the answer gets the rest, at most 2 matches (date and title only: the build dropped the snippet as a security fix, since a description or report is not for an SMS).
- A **question** is a text that ends with `?`, starts with `?`, or starts with `lookup:`. Plain rules, no guessing. A false positive costs one harmless "No match".
- A question still makes a card (rule 1). `lookup` only reads finished cards and reports, so it answers "what did we do about X", not "what is in Review now". See Open point 3.
- Every reply goes through the same steps. As built the order is filter, mask, filter (`reply.clean`): strip control and invisible characters and keep only the text alphabet first, THEN mask secrets (`redact.scrub`, forced on), then filter once more, so a key that a visible non-text character hid from the masker is masked once the filter has reassembled it; the plan's order was mask first. The filter: keep only letters, digits, space and ordinary punctuation (`. , : ; ! ? ' " ( ) - + = / * & % # @ $ _ < >`) after turning curly quotes and dashes into plain ones, and turn `http://` and `www.` links into `(link)`, then cut to 320. That is the basic text alphabet, so 320 characters is at most 3 billed segments. One emoji or `|`, `[`, `{` would make the count jump (an emoji alone: up to 5).

## Keys and limits

| Setting | Meaning |
|---|---|
| `AGENTBOARD_TEXTS_REPLY=1` / `=send` | New machine key, separate from `AGENTBOARD_TEXTS=1`. As built: `1` allows Off and Dry run (nothing is sent), `send` allows Send too. Unset or anything else: the reply step does not exist, the switch is not drawn |
| `[texts] reply = true` | The board's key. Off in a copied config |
| Settings switch **Text me back** | Held in memory only, so it is **off after every restart** (stricter than the pull timer's switch, which survives one). It is also the moment replies start: older texts get none |
| `[texts] reply_cap = 20` | Replies a day, counted as the Mac's calendar day. Clamped to 1 to 100 in code, so a copied config cannot raise it past 100. A send that failed after it left still counts |
| `AGENTBOARD_NO_SMS=1`, `AGENTBOARD_LOCKDOWN=1` | The existing locks. Both refuse replies at the next beat, whatever the keys say |

All gates stay in one function (the existing test checks that) and are read on every beat.

## Loop guard (rule 5)

A reply must never cause a reply, even if a phone, a carrier or a bridge echoes it back. Five independent layers, each tested:

1. **Direction.** The pull only reads messages addressed **to** the board's number and marked inbound. A reply goes **from** that number, so it cannot enter the pull.
2. **Ledger of sent ids.** Every reply's Twilio message id is recorded. The pull skips any id in the ledger, even if it somehow looks inbound.
3. **Echo check.** The ledger keeps a short hash (never the words) of the last 20 replies. An incoming text whose cleaned words match one gets its card but **no reply**.
4. **Own number.** If `allowed` lists the board's own number, replies refuse to start, and a text from that number is never replied to.
5. **One reply per text, ever.** The text's message id goes in the ledger before the send. The send function is called from one place only (the reply step after a pull), never from a reply's result, and no delivery-status callback or webhook is set.

Behind them, the daily cap bounds anything nobody thought of: at the worst, 20 replies of 3 segments each.

## Spend guard

- One function sends, to one address, with a fixed set of fields. `POST https://api.twilio.com/2010-04-01/Accounts/<your account>/Messages.json` with `To`, `From`, `Body` and nothing else (no media, no callback address). No redirect is followed. The path is checked before the call, the same way the read path is.
- The credentials are the ones the pull already uses, from the environment only.
- Errors name the HTTP status and Twilio's numeric error code, never a body, header or credential.
- A low or empty Twilio balance makes sends fail. That stops replies with the reason; pulling goes on.
- Optional, outside the code: keep auto-recharge off in the Twilio console, so the balance itself is a hard ceiling.

## What it keeps

One new file in the board folder, `texts-replies.json`, mode 0600, written atomically, with no words, numbers or credentials:

```
{"day": "2026-11-07", "sent": 3,
 "done": {"<incoming message id>": "<outgoing id> | sending | skipped: <why>"},
 "out": ["<outgoing ids, last 500>"], "echo": ["<short hashes of the last 20 replies>"], "error": ""}
```

If the file cannot be read or written, nothing is sent and the switch goes off with that reason.

## What the page shows (input for `texts-reply-design`)

The state the page gets: `{show, available, on, line, sent_today, cap, error}`. No number, id or word of a text.

| State | Line |
|-------|------|
| Not available | `Needs AGENTBOARD_TEXTS_REPLY=1 and [texts] reply = true` (or `Locked off (...)`) |
| Off (the default, and after every restart) | `Off` |
| On | `Replying to new texts · 3 of 20 sent today` |
| Paused (the daily cap) | `Paused: 20 of 20 sent today. Replies resume tomorrow; texts that arrive meanwhile get none.` (amber; the control stays on Send) |
| Stopped | `Stopped: Twilio refused a reply (HTTP 400, code 21610)` / `Stopped: could not record replies` |

Wording to settle in the design card: the switch label, the cost hint ("sends texts, costs a little"), and whether the header chip shows the day's count.

## Tests the build needs

Fake Twilio only; the existing matrix tests already fail on any outbound connection, and this adds the one allowed POST.

- Each rule above, and each of the five loop layers. The loop test makes a fake Twilio that **echoes every send back as an incoming text** and runs 50 ticks: at most one reply per real text, and nothing after the cap.
- Keys: each of machine key, board key, switch, locks off, one at a time: no send. `1` exactly.
- A restart turns the switch off. Turning it on does not answer older texts.
- Cap: the 21st reply is not sent, and the cards are still made. A config of 500 clamps to 100. A failed send counts.
- A notes file is listed and holds the question's word: the reply never contains it. A secret-shaped string in a card title is masked in the reply. A link is replaced. A non-ASCII character is gone. 320 characters at most.
- Send errors (401, 400 with code 21610, a timeout, a bad body) each stop replies, name no credential, and do not stop pulling.
- A ledger that cannot be written: no send.
- The only POST has one host, one path and the three fields. The core still has no texting words.
- `--dry-run` sends nothing and writes nothing.

## What the red-team (`texts-reply-security`) should try

An echo or auto-reply bridge on the allowed number; a text crafted to look like a reply or a command; a title with a key, a link, invisible characters or 10,000 characters; a copied config that raises the cap or turns replies on; a ledger deleted, truncated or made a link; two servers on one board; the clock changing across midnight; notes listed under `[knowledge]` and queried by text.

## Not in v1

Replies to anyone but the allowed number; answers about what is open right now (Todo, Doing, Review); notes in answers; any model-written text; a command text that changes the board (the older webhook has a few; this path stays data-only); a tunnel or webhook; picture or link messages; a configurable per-minute rate.

## Open points

1. **Go on the board's first send?** Recommended: yes, behind the three switches above. It is the first thing the board does that spends money. A balance that runs out stops replies with a refused-send line; pulling carries on.
2. **Notes in answers.** Recommended: leave the switch out of v1 entirely. Twilio keeps message bodies in its logs, sent ones as well as incoming, and the notes hold private detail. Notes stay searchable by `agentboard lookup --in notes` on the Mac. If you want the switch later, it becomes its own card with its own machine key.
3. **Question scope.** Recommended: v1 answers from finished cards and reports (the rule as written). If you also want "what is waiting on me" by text, that is a second source (the open cards) and its own small card.
4. **Switch after a restart.** Recommended: off after every restart (a reboot means one tap to resume). The alternative is to remember it like the pull timer does.
