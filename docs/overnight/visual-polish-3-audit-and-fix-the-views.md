# Overnight: visual polish 3, the views round 2 skipped

Card `visual-polish-3-audit-and-fix-the-views`, branch `overnight/visual-polish-3-audit-and-fix-the-views`. It sits on top of
`overnight/overnight-ux-visual-polish` (round 2, evidence in `overnight-ux-visual-polish.md`), so it needs that branch under it. **Nothing is merged.**

Round 2 audited the board, a card's panel, the ORCH drawer, Later and Settings. This round runs the same measured audit (`tools/ux_audit.py`, now
taking a list of views) over what it left out: By agent, an agent's thread, Load, the Summary and Reports pages, one card's report, the shortcuts sheet,
the error strip and the panel's conversation tab. Light and dark, 1280 and 390 wide, a throwaway board with made-up cards.

## What the audit found, and what changed

| # | Finding (measured) | Fix |
|---|--------------------|-----|
| 1 | **Mark done on a card's report: 2.22:1 in dark** (white text on the mint green) | A token for the text on green, `--on-ok`: near-black in dark, white in light; both clear 4.5:1 |
| 2 | **Report and Reports links: 4.35:1 in light** | The light link colour is the board's own blue (`#1d4ed8`, 7:1) |
| 3 | **Go ahead / Hold quick-reply pills: 4.41 and 4.42:1 in light** | Mixed toward the text colour, the same recipe the receipts use |
| 4 | **The Reports list read as slugs**: "make-the-backup-restore-safe-on-a-clean", cut mid-word, in a bare bullet list, links 18px tall | The card's title is the link; the id and the time sit under it; each row is a 24px target with a rule between |
| 5 | **Targets under 24px**: the agent names in By agent (20px), the error strip's close (21x19), the brand link on the server-rendered pages (23px), the report-list links (18px) | All 24px |

| 6 | **The agent thread's header lost the card title at phone width**: "on ..." and nothing else (a title too long for the line was dropped whole, because an inline button is not cut by the line's ellipsis). Found while reviewing chat-f8 at 390px | The card line is a flex row: the title shrinks with its own ellipsis and the state ("up for review", "waiting on you") stays |

Report files are written once, with their CSS inline, so **reports written before this change keep the old colours until they age out (24 hours)**;
a report written now has the new ones. The audit's "after" run used a report written after the change.

## Before / after

| Measure (9 views, both themes, 390 and 1280 wide) | Before | After |
|---|---|---|
| Text below its contrast floor | 7 (Mark done, 4 report links, Go ahead, Hold) | 0 |
| Targets under 24px | 5 kinds: lane names, error close, brand link, list links, 1 inline link | 1 inline link (exempt: it sits in a sentence) |
| Controls with no accessible name | 0 | 0 |
| Horizontal overflow | none | none |
| Full test suite | 1194 | **1204, OK** (10 new: 3 in `tests/test_reports.py`, 7 in `tests/test_visual_polish.py`); `tests/publiccheck.py`: 0 findings |

Screenshots (`r3-before-*` and `r3-after-*`, same made-up board; the "after" report is a newer one, hence different text):

| View | Before | After |
|------|--------|-------|
| Reports list, wide, light | `r3-before-reports-wide-light.png` | `r3-after-reports-wide-light.png` |
| Reports list, narrow, dark | `r3-before-reports-narrow-dark.png` | `r3-after-reports-narrow-dark.png` |
| A card's report, wide, dark | `r3-before-report-wide-dark.png` | `r3-after-report-wide-dark.png` |
| Agent thread header, narrow, light | `r3-before-thread-head-narrow-light.png` | `r3-after-thread-head-narrow-light.png` |

(The thread-header pair comes from two different made-up boards: the "before" from the chat-f8 review board, the "after" from this round's.)

## How to try it

Same as round 2 (`overnight-ux-visual-polish.md`): a throwaway board, `agentboard serve`, then open `/reports` and a report. The audit:
`python3 docs/overnight/tools/ux_audit.py 9334 http://127.0.0.1:8791/ byagent,thread,load,summary,reports,report,shortcuts,error,panelconv > out.json`.
A view name list audits only those views (no focus walk, motion or layout-shift section); with none given it runs the five board views and the full set.

## Risks

- The Reports list now reads each report file's `<title>` (the first 4KB) to show the card's title; a file that cannot be read falls back to the card id.
  The title is escaped on the way out (a test pins that).
- Mark done on a *done* card's report still shows a Mark done button (see below).

## Seen and left alone

- **A report for a card that is already done still offers Mark done and Send back.** Harmless, but a done card's report is a record; hiding the controls
  there is a small product call, not a visual one.
- **Two reports per card at the same minute** (one on review, one on done) appear as two rows with the same title. The sweep keeps the newest per card
  after 24 hours; the list could say "ready for review" / "done" on each row if the state were in the file name.
- By agent, the thread, Load, the shortcuts sheet and the panel's conversation tab came out clean (contrast, names, targets) apart from the items above.
