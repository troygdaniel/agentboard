# Overnight: UX / UI visual polish, round 2

Card `overnight-ux-visual-polish`, branch `overnight/overnight-ux-visual-polish` (2 commits on top of `3cec02a`). **Nothing is merged.**

The board was already in good shape, so this round measured first and changed only what the numbers or the screenshots showed. The audit
(`tools/ux_audit.py`) drives headless Chrome over a throwaway board with made-up cards, in light and dark at 1280 and 390 wide, over five views
(board, card panel, ORCH drawer, Later, Settings), and scores contrast (computed colours, alpha-composited), tap targets (counting `::after`
hit areas), accessible names, horizontal overflow, header height, a keyboard Tab walk, reduced motion and layout shift.

> **Correction (8 Nov).** The audit this page describes only looked inside the first screenful: its visibility test required an element to sit in the
> viewport, so everything below the fold went unchecked, and the "before" counts below undercount. The cross-review `xr-polish3-summary-link-colour`
> found one result of that (the Summary page; see `visual-polish-3-audit-and-fix-the-views.md`, which carries the fixed tool and a whole-page re-run of the
> "after" state over 14 views: 0 contrast failures). The six fixes here stand; the claim that nothing else was wrong does not.

## What changed

| # | Finding (measured) | Fix |
|---|--------------------|-----|
| 1 | The Touch switch had **no accessible name**: its checkbox shared the id `mix-touch` with the section holding it, so its `<label for>` pointed at the section | Switch ids are `lyr-<layer>`; a test pins that no section id is reused |
| 2 | **Reduced motion**: with live agents, 2 infinite avatar glows kept running (`.top .who .av.live` out-ranked the `.av.live` rule in the reduced-motion block) | The two selectors are in the reduced-motion block; running long/infinite animations 2 -> 0 |
| 3 | **Contrast**: Copy prompt on a Todo card was 3.35:1 in dark (`opacity: .75` on muted text) | Full opacity (the base rule is opacity 0, hover-only, so it is set to 1, not dropped: caught in a screenshot, now a test) |
| 4 | **Tap targets under 24px** (WCAG 2.5.8): the header's "needs input" / "to review" counts (16px), 7 Settings sliders (16px) | Counts 24px (`line-height`; the header row is taller, nothing moves), sliders 24px |
| 5 | **Phone header** took 4 rows, 185px before the first card (logo + tabs, Later alone, counts, icons alone) | 3 rows, 152px: logo + tabs, Later with the icons on the right, counts last. Above 600px nothing changes |
| 6 | **Settings** switches and sliders in the browser's default blue next to a black-and-white page; the Volume name sat 13px left of every other name | `accent-color: var(--accent)`; a fixed 18px first column; switches 16px |

## Before / after

| Measure (390 / 1280 wide, both themes) | Before | After |
|---|---|---|
| Text below its contrast floor | 1 | 0 |
| Controls with no accessible name | 1 | 0 |
| Targets under 24px (hit areas counted) | 2 counts, 7 sliders, 8 switches (13px), 1 inline link | 8 switches (16px; the label is the larger target), 1 inline link |
| Header height at 390 | 185px | 152px |
| Infinite animations under reduced motion (live agents) | 2 | 0 |
| Keyboard focus ring on every stop of a 70-stop Tab walk | yes | yes (unchanged) |
| Layout shift (load, open a drawer, open a card) | 0 | 0 (unchanged) |
| Horizontal overflow, any view | none | none (unchanged) |
| Full test suite | 1186 tests | **1194 tests, OK** (8 new, in `tests/test_visual_polish.py`); `tests/publiccheck.py`: 0 findings |

Screenshots, same made-up board, `before-*` on `3cec02a` and `after-*` on the branch:

| View | Before | After |
|------|--------|-------|
| Board, narrow, light | `before-board-narrow-light.png` | `after-board-narrow-light.png` |
| Board, narrow, dark | `before-board-narrow-dark.png` | `after-board-narrow-dark.png` |
| Board, wide, light | `before-board-wide-light.png` | `after-board-wide-light.png` |
| Board, wide, dark | `before-board-wide-dark.png` | `after-board-wide-dark.png` |
| Settings, narrow, light | `before-settings-narrow-light.png` | `after-settings-narrow-light.png` |
| Settings, narrow, dark | `before-settings-narrow-dark.png` | `after-settings-narrow-dark.png` |

The wide board is the same by design (item 3 aside): the polish is in the phone header and Settings.

## How to try it

```
git checkout overnight/overnight-ux-visual-polish
mkdir /tmp/ab-try && cd /tmp/ab-try
PYTHONPATH=<repo>/src python3 -m agentboard init && PYTHONPATH=<repo>/src python3 -m agentboard demo
AGENTBOARD_DIR=/tmp/ab-try/.agentboard PYTHONPATH=<repo>/src python3 -m agentboard serve --port 8791
```

Open http://127.0.0.1:8791/ at a phone width (390) and open Settings (the gear). To repeat the audit: `pip3 install --target /tmp/qa_pylibs websocket-client`,
then `python3 docs/overnight/tools/ux_audit.py 9334 http://127.0.0.1:8791/ > audit.json` (about 3 minutes; it only reads the board it is given).
`tools/shots.py` takes the screenshots.

## Risks and judgement calls

- **Tab order on a phone.** The counts line is drawn last on a phone but comes before the icons in the markup, so a keyboard on a phone
  reaches its two links before the bell, theme and gear. Moving the markup would break the wide header, where the order is right.
- **Black and white switches** replace the browser's blue (taste; one line to revert: the `accent-color` rule).
- **8 switches stay under 24px** (16px). Their labels are the real target and toggle them; WCAG 2.5.8 accepts an equivalent control.
- The audit measures computed colours over a flat backdrop; text on a gradient is flagged as approximate (none failed).

## Seen and left alone

- **The ORCH drawer's box clips its placeholder on a phone** ("Tell ORCH what you want… (@AGENT-"). The chat chain belongs to AGENT-5 (chat-f8);
  `docs/chat-words-design.md` already replaces it with `Message ORCH, or @AGENT-2…`.
- **Twelve different corner radii** (1 to 16px, and the pill): a token scale would be tidier but visibly changes nothing.
- The Load (HUD) view and By agent were screenshotted but not audited in depth this pass.
