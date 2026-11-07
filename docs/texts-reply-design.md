# Texts reply: wording and the Settings switch

**Status: design only, nothing built.** It follows `docs/texts-reply-plan.md` and uses the plan's recommended answer to each of its four open points; the last section says what changes if Troy answers differently. Mockups (light, dark, narrow, and a live Settings sheet to click through): `docs/texts-reply-design-mockup.html`, with `docs/texts-reply-design-light.png`, `-dark.png` and `-narrow.png`. Every example is a made-up card. All code stays in the home plugin.

## What the board says back

Board voice: plain ASCII, no emoji, no links, no exclamation marks, no "I", no sign-off, no apology. It states what happened, then stops. Cut to 320 characters.

| Case | Reply |
|------|-------|
| One card | `Added: Buy toothpaste` |
| A text that made 3 cards | `Added 3: Buy toothpaste; Call the vet; Renew the pass` |
| 8 cards from one pull (burst) | `Also added 5: Call the vet; Renew the pass; Pay Hydro; and 2 more` (after 3 texts have their own reply) |
| Question, one match | `Added: Is the backup tested? Answer: 2026-11-02 Backup restore check - restored 12 cards from a copy, all matched.` |
| Question, two matches | `Added: What did we decide on invoices? Answer: 1) 2026-10-28 Invoice numbering - one counter, no gaps; 2) 2026-10-21 Late fee wording - 30 days, plain text.` |
| Question, no match | `Added: Is the backup tested? Answer: no match in cards or reports.` |
| Long title | `Added: Rewrite the onboarding checklist so that new hires see the three...` |

The rules behind the table:

- **"Added:" first, always.** It says what the board did (made a card). The card lands in Todo, so the sender never has to wonder.
- **The word "Answer:"** separates the ack from the answer. The plan used ` - `, but card titles can hold a dash, so the line could not be read back unambiguously.
- **Numbers only when there are two matches.** One match is a sentence; two are `1) ... ; 2) ...`.
- **Cuts end in `...`** at a word boundary: the title at 60 characters, each snippet at about 110, the whole reply at 320 (cut last, so the reply never ends mid-word).
- **Dates are `YYYY-MM-DD`**, as on the cards and reports.
- **No match says so**, and says where it looked: `no match in cards or reports.` Silence would read as "broken".
- **A title is data, not wording.** The cleaning from the plan still applies, in its order: it can change how a title reads, and the build should keep it readable:
  - A masked key (`[redacted api-key]` on the card) loses its brackets and reads `redacted api-key`.
  - Curly quotes and dashes become plain ones; a character outside the alphabet is dropped; `http://` and `www.` links become `(link)`.

## The switch

**Where:** Settings, in the existing **Texts** group, under "Pull my texts every minute". One row, built on the segmented control the sheet already uses for Off / Subtle / Full (same classes, same look, so the build adds no new component).

**Label:** `Text me back`. Three positions:

| Position | Means | Costs |
|----------|-------|-------|
| **Off** (default, and after every restart) | Texts become cards and get no reply | nothing |
| **Dry run** | Everything except the send: the board builds the reply it would send and shows the latest one, marked not sent | nothing |
| **Send** | Replies go out as real texts from your Twilio number | **money** |

The row's about line: `After a text becomes a card, texts you back from your Twilio number: the card's title, or a short answer from finished cards and reports (never notes). One reply per text, 320 characters at most, only to your own number. Off again after every restart.`

### Choosing Send

Send never arms on one click. Clicking it opens a box under the row; the control stays where it was until you confirm:

> **Turn on sending?**
> Each reply is a real text, billed by Twilio. A long one can bill as up to 3. At most 20 a day. Only texts that arrive after you confirm get a reply.
> Tip: keep auto-recharge off in Twilio, so your balance is a hard limit.
> `Turn on sending`  `Not now`

- Focus lands on **Not now**, so a stray Enter cannot arm it. Escape also cancels.
- The box is amber-edged and inline, not a dialog, and it never uses a browser confirm.
- The same box guards Off to Send. Dry run to Send needs it too: that is the step that spends.
- Leaving Send (to Dry run or Off) needs no confirmation.
- The limit shown is the configured cap, not a fixed 20.

### The lines (what the row says under the control)

| State | Line | Tone |
|-------|------|------|
| Off | `Off. Texts become cards but get no reply.` | muted |
| Dry run, nothing yet | `Dry run: nothing is sent. The first new text will show its reply here.` | muted |
| Dry run | `Dry run: nothing is sent. Latest reply it would have sent, 2m ago:` then the reply in a quoted box tagged `not sent` | muted |
| Send | `Sending replies · 3 of 20 sent today · last 4m ago. Each one is billed.` | normal |
| Send, pull timer off | `Replies are on, but nothing pulls by itself. They go out when you press Pull texts.` | normal |
| Paused (daily limit) | `Paused: 20 of 20 sent today. Replies resume tomorrow; texts that arrive meanwhile get none.` | amber |
| Stopped (a send failed) | `Stopped: Twilio refused a reply (HTTP 400, code 21610). Switch it on again to retry.` The control is back on Off. | amber |
| Stopped (cannot record) | `Stopped: could not record replies. Switch it on again to retry.` | amber |
| Not set up | `Needs AGENTBOARD_TEXTS_REPLY=1 and [texts] reply = true.` Names only what is missing. Control disabled | muted |
| Locked | `Locked off (AGENTBOARD_NO_SMS).` Control disabled | muted |

No machine key at all: the row is not drawn (the plan's rule).

## The header chip

No second chip. The Texts chip that already shows the last pull carries the reply state after a dot, so the header stays as wide as today:

| State | Chip |
|-------|------|
| Replies off | `Texts 2m` (unchanged) |
| Dry run | `Texts 2m · dry run`, ring dot |
| Send | `Texts 2m · reply 4m` (time of the last reply), solid dot |
| Paused | `Texts 2m · replies paused`, amber |
| Stopped | `Texts 2m · replies stopped`, amber |

The day's count is **not** in the chip text (a number that changes all day is noise); it is in the chip's tooltip and in the Settings line. Under 600px the words go and the dot stays, as now; the ring, solid and amber dots keep the three states apart, and the tooltip carries the words.

## What the page is sent

The plan's `{show, available, on, line, sent_today, cap, error}` becomes:

```
{show, available, locked, mode: "off" | "dry" | "send", line,
 sent_today, cap, last_at, paused: "" | "cap", error, sample}
```

- `on` becomes `mode`, because there are now three positions.
- `sample` is the latest dry-run reply (at most 320 characters, already cleaned and masked), held **in memory only**, set only in dry-run mode, and empty in Send mode. It holds nothing the page does not already show: the title of a card, and an excerpt of a finished card or report. It is never written to disk. `texts-reply-security` should confirm that.
- `last_at` is the time of the last reply, with no words; the same for sent and would-have-sent.

## Copy elsewhere that must change

The Pull row's about line says `...and nothing is texted back.` It stops being true when the switch exists. When the reply row is drawn it should read `...and nothing is texted back unless you switch on Text me back below.` The timer's acceptance list (`nothing texted back`) is the same sentence.

## Narrow

Below 420px the segmented control moves under its label (a full-width row of three buttons would not fit beside it), left-aligned. The chip drops to its dot (existing rule). Nothing else changes.

## Where Troy's four answers change this

| Plan's open point | Recommended (designed for) | If the answer differs |
|---|---|---|
| 1. First send? | Yes, behind the three keys | **No:** the machine key stays unset and none of this is drawn; the design and the dry-run wording are kept for later. |
| 2. Notes in answers | Not in v1 | **Yes:** a separate switch with its own key; the row's about line, the no-match line (`cards or reports`) and the confirm box each gain `notes`. Not designed here. |
| 3. Question scope | Finished cards and reports | **Open cards too:** a new answer form (`Open now: ...`), and `no match in cards or reports` becomes `no match`. Not designed here. |
| 4. Switch after a restart | Off | **Remembered:** the about line drops its last sentence. I would still remember Dry run only, never Send: a reboot must not leave a billed switch armed. |

## Where I chose and the plan is silent

For ORCH and the build to confirm:

1. **The daily limit pauses, it does not stop.** The plan lists it with the errors, which need a flip. A switch that must be re-armed every morning is a nuisance, and the limit is not an error, so the design pauses and resumes at midnight; texts that arrive while paused get no reply (the ledger records `skipped: limit`). If the plan meant a flip, the Paused row becomes a Stopped one.
2. **Dry run in the page, not only the command.** The plan has `--dry-run` as a flag. A Settings position needs it to run on each pull, send nothing, spend nothing, write nothing, and keep the latest reply in memory.
3. **Turning Dry run or Send on starts from that moment**, as the plan says for the switch. Texts a dry run already saw do not get a reply when you move to Send.
4. **"Answer:" and the single match without a number** differ from the plan's examples (see the first table).

## Not designed

A mark on the card that says it was replied to; any setting for the wording; a reply to anyone but you; a count-down to the limit in the chip.
