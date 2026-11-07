# Overnight UX overhaul, 4 Nov 2026: the morning summary

Everything below is on the branch `claude/dreamy-allen-3s1xpf`, pushed, in seven commits on top of main at 543638b. Main was not
touched. Each commit is one unit and reverts on its own: `git revert <hash>`. Every pick that is a matter of taste sits behind a
switch that defaults to the current look. The ranked list that drove the night is `docs/ux-review-2026-11-04.md`.

## Action first

Run the review on the card when you are up (this session could not reach your board):

    AGENTBOARD_DIR=<board dir> agentboard review agentboard-ux-review-overhaul "Overnight: projects gone, shortcuts on every view, nothing hides under Load or moves on a poll; 7 commits on claude/dreamy-allen-3s1xpf, main untouched" --body-file docs/ux-overnight-2026-11-04.md

Then try the branch for a day before merging: `git checkout claude/dreamy-allen-3s1xpf && pipx install . --force` and restart `agentboard serve`.

## The picks, and how to reverse each

| # | Pick | Why | Reverse |
|---|------|-----|---------|
| 1 | **Projects removed entirely** (your answer last night) | the colour carried no meaning you wanted; the feature had a hidden filter and a panel select nobody used | `git revert e14e6a9 6d73807`. Old board files keep working either way: a project list in `tasks.json` is dropped on the next save, a card's `project_id` is ignored |
| 2 | **The Done summary groups by agent** ("Unassigned" for a card with none), `/summary?agent=` and `summary --agent` | it grouped by project and needed a new axis; by agent reads as "who did what" | part of 6d73807; grouping into one bucket of work areas is the other option, a small change in `summary.collect` |
| 3 | **Alt+arrows on Load and By agent move between Todo and Doing only** (a lane is Doing) | Load and By agent have no Done column; "done" is `d` | `git revert 90b6e5a` reverts all shortcut work; to narrow just this, drop the `['todo', 'doing']` branch in the card-area keydown |
| 4 | **Esc clears a selection before it closes Load** | a selection is the lighter layer | one line in the Esc chain |
| 5 | **The bulk bar floats** (bottom centre, above Load) instead of sitting above the board | opening it shrank every column by 74px | the `#bulkbar` rule in 8e5f99c |
| 6 | **The error strip floats** under the header with an × | it pushed the board down and hid under Load | the `#error` rules in 8e5f99c |
| 7 | **The header never wraps above 900px**; the counts shrink with an ellipsis first; ORCH keeps its slot while hidden | the counts appearing moved the board and Load's top edge | the `@media (min-width: 901px)` header rule in 8e5f99c |
| 8 | **Cards glide only when their column or order changed** | every card below a growing card glided on background polls | the `beforeOrder` guard in 8e5f99c |
| 9 | **Motion moved to a Look section** in Settings; **Calm cards** added there, off | Motion is a look, not a sound; Calm cards answers the card-colours question without changing the default | the Look section in 8e5f99c; Calm cards is a59a4ec and does nothing while off |
| 10 | **The Report chip shows whenever a report exists** | a Doing card with a report hid it | one line in 9ee745f |
| 11 | **By agent gets an Unassigned lane** for Doing cards with no agent | those cards were on no view but the Board | one line in `byAgentHtml` (9ee745f) |
| 12 | **The Later drawer ignores the filter** | it said "Nothing parked" under an agent filter | `renderLater(parked)` in 9ee745f |
| 13 | **The minute rebuild waits while text is selected or a control inside the open card has focus** | copying a long ask and an armed Delete kept resetting | the two guards in `refreshPanel` (9ee745f) |

## The commits

| Hash | What |
|------|------|
| 10cec32 | the ranked list (`docs/ux-review-2026-11-04.md`) |
| 6d73807 | projects gone from the store, CLI, API, HUD feed, backups and docs; the Done summary by agent; old board files still load |
| e14e6a9 | projects gone from the page: no pill, dot, filter, panel select or bulk assign |
| 90b6e5a | every shortcut on every view: Load's arrows walk Todo and Doing, Alt+arrows on Load and By agent, no arrow crash, focus survives a poll in every pane and on controls inside a card, the selection on Load with a floating bar, Esc one layer at a time, m and s inside Settings, c/d aim the same way, the pop-out keeps ?, e and the arrows, the sheet matches the handlers |
| 8e5f99c | the toast and the error strip above Load, the strip with an ×, the header that stays put, glides only on real moves, Load keeps its scroll, no lift on telemetry rows, the Look section, the sound-off badge on the gear |
| 9ee745f | the status pill and chat keep running while you type, the open card is not rebuilt under your hand, the Later box is built once, the pill highlight survives a redraw, tooltips on clipped text, the Report chip, Show fewer, the drawer ignores the filter, the Unassigned lane |
| a59a4ec | Calm cards (Look, off) |

## What was checked, after every commit

- The unit suite: 622 tests. The only failures are the three `test_core.NotifyTests` that call macOS `osascript`; they fail the same way on main in this Linux container.
- A screenshot tour of every surface (Board, By agent, Load, the open card, Later, Chat, Settings, the shortcuts sheet, a selection), light and dark, 1400px and 420px, with no page errors.
- Headless Chromium checks, each asserting DOM state and computed style, not pixels: Touch (80 sounds, one per gesture, nothing on a poll), Motion (14), keyboard on every view (21), layers and header (13), polls and hidden information (14), Calm cards (1). A box-for-box layout diff against the previous commit after each of them; the only intended movements were the header's reserved slots in 8e5f99c.
- New source tests pin every rule: `test_no_projects`, `test_keys_everywhere`, `test_layers_header`, `test_polls_and_hidden`, plus the updated `test_summary`, `test_load_keys`, `test_load_same_cards`, `test_config_icon`.

## Left for you, with why

- **Chat rebuilds its body on every new message** (focus on Approve/Decline is lost, an expanded thread jumps). An append-only renderer is a day's work with its own risks; a card of its own.
- **By agent lanes re-divide the width when a lane appears.** Animating grid tracks needs a different layout; Motion already slides a new lane in.
- **A lane's "quiet" rule differs from Load's server state** for the same agent. One clock has to win; your call.
- **Card descriptions stay hidden on cards.** A "has details" glyph would add the kind of visual information you are cutting; the panel shows them.
- **The docs/ mockup pages** from earlier rounds still show project pills; they are history, left as they are.
- **The board card** (claim, subtasks, progress) was not updated: no Remote Control folder was shared with this session. The review command above puts this file on it.

## If something looks wrong in the morning

Every change is on the branch only. `git checkout main` is the board as you left it. To keep most of the night and drop one thing, `git revert <hash>` from the table above and re-run `python3 -m unittest discover -s tests`.
