# Changelog

## Unreleased

### `update ID 12.5` and `update ID 50%` no longer pretend a percent was set (Nov 15, night sweep)
A lone number that was not a whole number (`12.5`, `50%`, `1e1`, `.5`) was taken as the status line, and the command answered "ID: 0%" as though the percent had been set. It now stops with "progress is a whole number from 0 to 100, got '12.5': write 50, not 50% or 12.5" and changes nothing; with words after it the command already refused. Whole numbers, and words alone ("half done", "v2", "3 of 5 steps") work as before. `tests/test_update_percent.py` (3).
### The chat archive names its day files only from a real date (Nov 15, night sweep)
The archive took the first ten characters of a line's `at` stamp as the day file's name. On a hand-edited or copied board that could be a path piece or hold a NUL, which would have raised on the post. A stamp that is not `YYYY-MM-DD` now files the line under `chat-unknown.jsonl`, and the store swallows a ValueError or TypeError from the archive the way it already did an OSError, so a chat post never fails for the archive. Test: `tests/test_chat_archive.py` (an odd at stamp names no file elsewhere and raises nothing).
### `agentboard rename X X` is refused (Nov 15, night sweep)
Renaming an agent to the name it already has said "Renamed AG-1 to AG-1", rewrote the board's files for nothing and wrote a rename record, so the next `rename --undo` reversed that empty rename instead of the real one. It now says "AG-1 is already named that: nothing to rename" and writes nothing; a change of capitals (Scout to SCOUT) is still a rename. `tests/test_rename.py` (1 new).
### A step added to a card waiting for review takes the review back (Nov 15, night sweep)
`agentboard add "late step" --parent P` on a card handed in with `review` dropped its % to 67 and left it saying "ready for review" with a step still open: the owner read a finished card that was not. Now the review (and an ORCH sign-off on it) is withdrawn, the history says "Back at work: a new step was added (late step)", and the card is handed in again when the step is done. A card that was not in review, a question waiting on the owner, and a card already Done are left as they were. `tests/test_late_step.py` (5).
### `chat approve` and `chat decline` are the owner's, not an agent's (Nov 15, night sweep)
An agent could propose an action in the chat ("buy lock.example"), then run `agentboard chat approve N` itself, and the board recorded the approval as the owner's. `configuration accept` already refused a session that has an agent name; the two chat decisions now do the same: "only you approves or declines a proposed action: it is the owner's word, not an agent's (run it from the board's button, or from a shell with no agent name set)". ORCH is refused too (an outside action is the owner's own word). A shell with no agent name set is the owner at a terminal, and an agent still reads its answers with `chat approvals`. The name is the session's own word, so this stops the wrong caller, not a determined one; the board's button is the owner's real channel. `tests/test_chat_approve_owner.py` (4).

### The agent's own report file is read only when it is a regular file (Nov 15, night sweep)
A symlink placed at `reports/<card>.md` was followed, so the report page could show a file from outside the board, and a FIFO there would have blocked the page build for good. `reports.extras_md` now opens the file without following a final symlink and reads it only when it is a regular file, the rule `lookup` already applied to the same files. Test: `tests/test_reports.py` (the agent's own markdown file is read only when it is a regular file).
### `agentboard insights` survives a log entry with no text string (Nov 15, night sweep)
A hand-edited or copied board with a number (or null) where a log entry's text belongs made `agentboard insights` die with a traceback; the other readers were fine. The reader now treats such an entry as an empty line. Test: `tests/test_insights.py` (a log entry whose text is not a string is skipped, not fatal).
### `agentboard chat tail` prints every line of an odd board (Nov 15, night sweep)
A hand-edited board whose chat line held a string where the proposal dict belongs made `chat tail` die with a traceback before printing the rest. A line is now printed for whatever shape a stored message has: a proposal that is not a dict is left out, one missing fields shows what it has, and files or detail of the wrong type are ignored. Test: `tests/test_chat_line_odd.py` (5).
### A card id typed with `--id` must be a short safe word (Nov 15, night sweep)
`agentboard add "x" --id "../../esc"`, `--id "a/b"`, `--id "Has Space"` and an 80-character id were all accepted, then reached the places that build a path or a link from the id (`reports/<id>-<stamp>.html`, `reports/<id>.md`, `runs/<id>/`, the page's `#<id>`). Now `add --id` and `start --id` take 1 to 64 letters, digits, dots, hyphens or underscores, starting with a letter or digit, and say so when it is not. Ids the board makes from a title are untouched, and so are the ids already on a board. Nothing was written outside the board's folder before (the report's temp name happened to stop it), so this closes the door rather than a hole. `tests/test_id_shape.py` (5); the whole suite (2,616 tests) passes.
### Undo can no longer write a card the board cannot read, and no save can (Nov 15, night sweep)
`POST /api/restore` (the page's Undo) took a whole card from the client and checked its status only. A card with a number or nothing for an id was written with a 200, and then every read of the board answered 500 (`card 104 has no id; run agentboard verify`) until someone repaired `tasks.json` by hand. Two guards: every save now checks the cards exactly as the loader does and refuses with `this change would leave card N ..., which the board could not read again; nothing was saved`, whatever asked for it; and Undo checks the shape of the card and of each subtask it is given (an id, a title, text where readers expect text, a progress from 0 to 100, a log that is a list of entries). A board that reads today still saves today: the save rules are the loader's own. `tests/test_restore_shape.py` (7; five fail without the fix).

### One lone half of an emoji in a title no longer breaks the Story page and `agentboard list` (Nov 15, night sweep)
A title cut in the middle of an emoji by a page (`"\ud83d"`, which is valid JSON) or a byte that was not UTF-8 on a command line was kept as a lone surrogate. Every reader that turns text into UTF-8 then failed: `/story` answered 500 and `agentboard list` raised, for everyone, until someone edited `tasks.json`. Every stored text goes through `redact.scrub`, which now replaces a lone surrogate with U+FFFD (also with the masker switched off); a whole emoji, accents and Persian marks are untouched. `tests/test_lone_surrogates.py` (4); the four fail without the line.
### A config.toml that is not UTF-8 now says which file and why (Nov 15, night sweep)
An editor that saved `owner = "José"` in Latin-1 made every command print only `decoding with 'utf-8-sig' codec failed` (no file named), and the HUD and `/api/config` answered 500 with the same line. The TOML reader let the codec's error out instead of its own, so the one place that names the file to fix never saw it. It now says `.../config.toml is not valid config (the file is not UTF-8 text ...); fix or delete it`, as for a typo in the file. `tests/test_config_not_utf8.py` (4).
### A new card no longer takes the id of an archived one, so clearing it cannot erase the old card (Nov 15, night sweep)
A card's id is a slug of its title, unique among the cards on the board, and the archive was left out. Titles repeat (a subtask called "Run the tests" under every card), so a new card got the id of an archived one; when it was cleared in turn the archive kept one card for that id, the newest, and the first card's history, report and lessons were replaced without a word. `unarchive` of the old id dropped it from the archive too, because a live card held the id. New ids now avoid every id in `archive.json` (a subtask whose short name is taken gets its parent's id in front, as it already did for live cards), and an id given by hand cannot be an archived one. A damaged `archive.json` does not stop a new card. `tests/test_archived_id_reuse.py` (5; four fail without the fix). Cards already in the archive are not touched.
### Three side fields are masked for secrets too (Nov 15, night sweep)
Every text an agent hands the store is masked on the way in (redact.py); three small fields were not. A card's `ctx` entries (`add --ctx`) are now masked like the title. A `claim --model` that looks like a key is refused with the claim untouched, and a key in `$AGENTBOARD_MODEL` is ignored rather than recorded. The `to` name on an agent's chat line is masked (a real name is unchanged; a mirrored line to an unknown name keeps it masked). Test: `tests/test_redact_side_fields.py` (6).
### An ask or a review with no first line is refused (Nov 15, night sweep)
`agentboard ask ID ""` put "waiting on user: " on the card with nothing to answer, and `agentboard review ID "" --next nothing` handed in a card with no sentence; the 140-character limit on the first line had no lower bound. Both now stop with "an ask needs a first line: say the one thing the user must do or know, and put the rest in --body". A subtask's review (its 100%) and a plain `update` are as before. `tests/test_hand_in.py` (1 new).
### The security sign-off table names every file again (Nov 15, night sweep)
Thirteen files the board writes were missing from the table in `docs/security-signoff.md`: the archive, the rename records, night mode, the configuration files, the server tick's awake and asleep files, the insights files (agent states, the chat archive), the server log and a detached run's supervisor log, plus the lock files beside the state files. They are listed now with what they hold and their mode. The scripted day in `tests/test_signoff_files.py` turns insights on, renames an agent, starts night mode and clears a done card, so the files a day makes are the ones the table is checked against; the files only the server tick writes are checked by name.
### An agent name that can draw a second chat line or move the cursor is refused (Nov 15, night sweep)
`--name`, `--to` and `$AGENTBOARD_NAME` went into chat lines, card owners and lists as typed. A newline in a name forged a whole extra line (`#999 [..] ORCH -> all: ...`) in `chat send`'s echo, `chat tail` and `chat inbox`, which agents read as input; an ESC byte reached the terminal; a bidi override reordered a line on the page. A name is now one line of plain text of at most 80 characters (no control character, line or paragraph separator or bidi override), checked before any command runs and again where a chat line is made, so the page's chat box is covered too. Ordinary names, accents and non-Latin names are untouched. The refusal says which option and does not echo the name. `tests/test_agent_name_control_chars.py` (9; eight fail without the fix).

### A command provider can no longer be made to run card text (Nov 15, night sweep)
A `type = "command"` provider filled `{arg}` and then `{title}`. An arg that was the text `{title}` was quoted, and the card's title was then pasted inside those quotes, so a quote in the title ended the string and the rest ran as shell. Both come from a card (its `--ctx` and its title).
- Both placeholders are now filled in one pass: text that arrives through one value is never read again as a placeholder. Only boards with a command provider set up were exposed; none ships.
- Checked: `tests/test_provider_command_quoting.py` (the case fails on the old code).
### The agent's own report file is masked on the page (Nov 15, night sweep)
A card's text is masked for secrets on the way in; the hand-written `reports/<card>.md` an agent may add never passes the store, and the report page showed it as written, so a key pasted there reached the page. `reports.extras_md` now runs the same scrub (`redact.scrub`) before the page is built; `lookup` already did. Test: `tests/test_reports.py` (the agent's own markdown file is masked like every other agent text).
### One agent can no longer release, move or remove another agent's card (Nov 15, night sweep)
`update`, `ask`, `review` and `checkpoint` have always refused a card another agent holds, but `release`, `move`, `rm` and `wrapup --apply` took any name: on a scratch board one session sent every Doing card of another back to Todo (`release --agent AG-1`), moved a held card to Done, and deleted it. The same rule now covers them.
- **Who passes:** the holder, ORCH, the owner and a terminal with no session name; a card nobody holds stays anyone's to move (the queue is fixed that way). A subtask answers to its parent's holder. `release` checks every card before it releases the first, so a refusal leaves none half done.
- **`wrapup --ask` and `--apply`** are ORCH's and the owner's, like `night on`; plain `wrapup`, `--last` and `--json` still read for anyone.
- The refusal names the holder and who may: "mine is held by AG-1: only AG-1, ORCH or the owner can release it". Not covered: `edit` (an agent may still annotate a card); the name is the session's own word, as for `update`, so this stops a wrong card, not a determined session. `tests/test_held_card_guard.py` (10).

### A night queue: agents take the next card themselves (Nov 15, card retro-night-queue, retro rec 13)
Off by default; with the switch off, or never used, nothing on the board changes. When the owner (or ORCH, at their word) turns Night on, ORCH lines up specified Todo cards and an agent with a free hand takes the next one itself instead of waiting for a message.
- **The switch:** `agentboard night on [--until HH:MM]`, `off`, `status`, and a **Night queue** row in Settings > Agents and chat. It ends by itself at 08:00 unless told another time. While it is on the header shows a chip (`Night · 3 queued · until 08:00`); turning it on or off posts one line to the chat.
- **The queue:** `agentboard night queue add ID... [--first]`, `remove`, `clear`, and no word to list it. Only a Todo card nobody holds can be queued; a card waiting on another is listed `blocked by ...` and skipped until that one is done. A worker agent cannot turn the switch on or edit the queue.
- **The take:** `agentboard night next --name NAME` claims the first ready card exactly as `claim` does (subtasks, role, log), plus a log line "Taken from the night queue", and prints the night rules: no push, no spend, no live restarts, no personal cards. It refuses while night mode is off or ended, and while the agent still holds a card it has not handed in. Two agents at once never take the same card.
- **Where:** `src/agentboard/night.py`, state in `.agentboard/night.json` (no new key in `tasks.json`), `GET` and `POST /api/night`. Design: `docs/night-queue-design.md` and `docs/night-queue-mockup.html`.
- Checked: `tests/test_night.py` (22 checks: the switch and its end, the queue rules, the take, two takers at once, the commands, the routes, the page markup) and `node tests/qa/night_check.mjs` in headless Chrome on a throwaway board (23 checks: off by default, the chip, the row and the queue really on screen, a title with markup staying text, a take followed by the page, 390 px wide, off again, no console errors).
### The board no longer says "ORCH is not running" while ORCH is busy (Nov 15)
The board called ORCH running only while a `chat inbox --wait` was open, with 90 seconds of grace. A wait ends the moment a line arrives, and ORCH cannot open the next one until its tool call ends, so a merge plus a full test run showed "ORCH is not running" and a Start ORCH button while ORCH was hard at work; the prompt got pasted into the live session.
- **A sign of life is any board command a named session runs,** a wait opened or closed, and the SendMessage and Stop hooks. They write the time to `.agentboard/chat-presence.json` (names and times only, at most one write per name every 10 seconds).
- **The line says "ORCH is not running" only after a quiet longer than `[orch] presence_grace_s`** (600 seconds by default, 30 to 86400), and an open wait still counts at once. The Watch tab's listening dot is unchanged: it still means a wait is open now.
- Checked: `tests/test_orch_presence.py` (stamp, throttle, what writes it, the two endpoints, the page logic) and a render-check on a throwaway board. Not covered: an ORCH that is running but has not touched the board for the whole grace (a very long job with no board command) still shows as away; raise `presence_grace_s` for that.

### A Dev crew configuration ships, with one block of rules every role's prompt carries (Nov 15, retro rec 5)
The crew had no configuration of its own, and the rules it learned the hard way (no git stash, no pkill by pattern, no backtick in a shell string, no amend after a hash is sent, Chrome only through the lock, touched suites only) lived in a memory folder and in chat, in no role's prompt.
- **`dev-crew` ships** beside build, dream-up and day-to-day: builder (BuildBot, TaskMaster-1 to 5), designer (DreamBot), gate (Gate-1: the one full suite per merged batch) and tester (Tester-1: reads a change cold). Every role may not merge, push, install or restart the board; ORCH keeps those jobs and is not a role in the file (the board keeps that name).
- **`shared_rules`:** a new optional field, up to 12 one-line rules, written once and printed once in every role's card prompt and in the claim output, after that role's own lines; ORCH's prompt lists them and `configuration show` prints them. A file without the field, and an agent with no role, get the prompt as it was.
- **A proposed new name keeps the rules:** accepting `propose --add-name` used to rebuild the configuration from its roles only; it now carries `shared_rules` over (a test, with a control that fails without the fix).
- **Off until you turn it on:** `[agents] configurations = true`, then `agentboard configuration apply dev-crew`. Nothing here changes a live board, installs or restarts it.
- Checked: `tests/test_configurations.py`, `tests/test_configuration_board.py`, `tests/test_config_proposals.py`; the shipped file is scanned for a person, number or address.
### `agentboard done` says what the card left on disk (Nov 15)
60 of the 62 extra agentboard worktrees in the 15 Nov retro were merged already and still on disk; nothing told anyone. After `<card>: done` the command now prints the card's worktree and branch, whether it is merged into main (or how many commits ahead it is, or that it has uncommitted changes or is locked), and a list of the other worktrees that are merged, clean and held by no agent with an open card, each as a `git worktree remove <path>` line to copy.
- **A list, never a removal:** the board does not remove a worktree or a branch, and every git call it makes for this is read-only (`--no-optional-locks`). Outside git, under the work profile or the lockdown, `done` prints what it printed before. A failure in the list cannot stop the close.
- **Which repo:** the board's own (`[reports] repo`, else the board's parent folder); `agentboard done ID --repo /absolute/path` asks about another, checked before the card closes.
- Not covered: a fresh worktree with no commit yet counts as merged, so the list leaves out any folder whose agent holds an open card; removing is still yours (card retro-done-shows-worktrees, retro recommendation 11). `tests/test_done_worktrees.py` (23).
### `review` warns when the work is not committed (Nov 15, retro rec 6)
A card could be sent to review, and closed, with its work still uncommitted or on a branch with nothing past main; the command never looked at git. Now `agentboard review` asks git four short questions about the folder you run it in, or the one `--tree PATH` names, and prints one plain line on stderr when it finds either: uncommitted changes (counted, new files included, ignored ones not) or a branch with nothing past `main` (or `master`). The same words go into the card's history as `Review warning: ...`. It is a warning only: the review always goes through. It says nothing outside a git repository, in one without a `main` or `master`, when git is missing or slow, on a subtask, or with `AGENTBOARD_TREE_CHECK=off` (the test suite sets that, in `tests/netguard.py`), or under the master lock `AGENTBOARD_LOCKDOWN` (the work profile), where it starts no program; `selfcheck`'s table of files that may start a program gains `treecheck.py`, with that reason. Run `review` from your worktree, or pass `--tree`, because a session run from the main checkout is on main with nothing past it. Test: `tests/test_review_tree_check.py` (18).
### The whole chat is kept, with counts per day and sender (Nov 15)
The live chat holds its last 500 lines; the Nov 15 retro had to rebuild 1,100 older ones from hourly snapshots. With `[insights] enabled = true` the board now appends every chat line, as posted, to `.agentboard/chat-archive/chat-YYYY-MM-DD.jsonl` (one file a day, never rewritten) and keeps `chat-archive/counts.json`: lines per day and sender, and the last archived number, so a line is never written twice. The first archive copies the lines the live file still holds. Nothing on the board reads it (not an agent command, not lookup, not the server): it is for the owner's own retro scripts. A failed archive write never fails a post. Test: `tests/test_chat_archive.py` (13).

### A Todo or Later card can be deleted again (Nov 15)
The card's panel kept Delete (and Copy prompt, Back to Todo, Stop run) inside the closed "More" fold since Nov 12, so a card nobody had started showed no way to delete it. The buttons now sit under the fold, always visible, for Later, Todo and Doing cards the way they already did for a card in review or done. Test: `node tests/qa/delete_cards_check.mjs` (34 checks: the Later drawer, the Map's Todo and Doing columns, wide and 390 px; it fails on the old page) and a page pin in `tests/test_you_line.py`.

### The details panel is readable (Nov 14)
The panel beside a card on Watch (and beside the pile) showed a task as one wall of text, and on Watch a second open cut it off mid-line with no way to read the rest.
- **One sentence to a line:** a long plain paragraph in the task or in the agent's report is split into its sentences, each on its own line. A paragraph with markup in it, and a short one, are left as they were. "e.g.", "i.e." and "vs." do not end a sentence.
- **Cut, with a Show all that works:** the task shows about seven lines with a fade, then **Show all** / **Show less**. On Watch the button was missing after the first open (the panel was drawn from what was kept and never measured); it is measured now, and again once the panel has opened to its width.
- **Calmer labels:** each section label (The task, Lately, ...) has a thin rule after it, in the page's own line colour, so light and dark both follow.
- Checked: `tests/test_details_panel.py` (6) and `node tests/qa/details_panel_check.mjs` in headless Chrome on a throwaway board (the split, the cut, Show all and Show less, a second open, a short task, the labels, dark, 390 px).

### Agent configurations on the board: the picker, the header chip and the Rename dialog (Nov 14, slice 3 of the agent configurations)
Until now a configuration and a rename were command-line only. The board has the same two things, the way the approved mock-up drew them. Nothing here starts a program: the owner types the terminals, and the board reflects them.
- **Settings > Agents and chat > Configuration:** the shipped configurations (Build or improve an application, Dream up an application or feature, Day to day), each role with what it may and may not do, **Apply to this board** (the roster and the role labels; no card, claim or chat line changes), **Remove**, and the terminals to type with a Copy button. With `[agents] configurations` off the section says how to turn it on.
- **Two more configurations ship:** `build` (dev x2, qa, architect, designer; nobody merges, pushes or installs) and `dream-up` (brainstormer, mockups, proof of concept, tester). A test scans every shipped file for a person, number or address.
- **The header chip** names the applied configuration and how many of its agents are listening (`Configuration: Dream up · 0 of 4 listening`); a click opens Settings.
- **Rename…** on an agent's row in Settings and on its thread head opens a small dialog: the counts first (cards, history fields, chat lines, state files, `config.toml`, what stays as written), a refused name says why and keeps Rename off, Esc closes only the dialog, and the result says what to type in that agent's terminal and offers Undo. Behind it: `POST /api/rename/plan|rename|undo`, the functions the command line runs.
- **New endpoints** (all behind the host and origin checks): `GET /api/configurations` (what ships, what is applied, the terminals), `POST /api/configuration/preview|apply|clear`, `GET /api/configuration/export`. An imported file is validated before it is shown or kept (unknown keys refused, 64 KB at most); export is the file only, never a card, a chat line or a path. The import and export buttons are the next slice (3b).
- **Test tool:** `tests/qa/boardchrome.mjs`'s `ev()` now awaits a promise inside the page before it stringifies (a bare `fetch(...).then(...)` used to come back as `{}`, which is truthy: one check in `tests/qa/watch_alive_check.mjs` passed without reading anything, and now reads `/api/config`); `startBoard` also returns `stopServer()` and `startServer()`.
- Checked: `tests/test_configuration_board.py` (20), and `node tests/qa/config_board_check.mjs` in headless Chrome on a throwaway board (28 checks: the picker, Apply changing no card, the chip, Remove, the setting off, the dialog's counts, refusal, focus, Esc, Rename and Undo moving the cards, 390 px wide, no console errors).

### A shipped configuration name is no longer hidden by a folder of that name (Nov 14, fix for slice 3b)
- `agentboard configuration export build` (and `show`, `apply`) read a `build/` folder in the current directory as the file to import, so the board's own checkout could not name the Build configuration. A bare shipped name (`build`, `day-to-day`) is now the shipped one; a file is named with a `.json` ending or a path. Test: `tests/test_config_proposals.py` (31).

### Fewer flaky tests, and a run no longer loses its minutes to a sleep (Nov 14)
Four tests failed on a busy Mac and passed on a rerun; one of the causes was in the product. `docs/FLAKES.md` lists each with how often it hit, why, and what was done.
- **The board's server asks the kernel to queue 256 waiting connections, not Python's 5** (the OS caps it at 128). A burst of connections no longer gets reset before the server can answer it. `agentboard selfcheck`'s flood check now opens its connections in groups, reads them all at once, and tries again when the kernel reset some; its pass condition (exactly 128 held, the rest refused with 503) is unchanged. With the server slowed by 3 ms a connection the old check failed 3 of 3 times and the new one passes 3 of 3.
- **`agentboard run` times its minute limit on a clock that does not tick while the Mac sleeps.** A run that was going when the Mac slept used up its limit on waking and was stopped before its agent had written anything.
- **Tests wait for what they are waiting for:** the selfcheck subprocess limit stretches with the machine's load; the two listener-list tests wait for the listener to appear instead of guessing at 0.3 s.
- Checked: `tests/test_workprofile.py` (a new slow-accept test), `tests/test_runs.py` (a one-hour wall-clock jump mid-run, and its control), `tests/test_no_reply.py`, `tests/test_server_hardening.py`; the whole suite alone.

### Agent configurations, slice 3b: ORCH's suggestions, export and import (Nov 14; off by default, with `[agents] configurations = true`)
Built on the board side of slice 3 (the Build and Dream-up configurations, the export/preview/apply endpoints and the picker are that card's).
- **ORCH suggests, you decide.** `agentboard configuration propose --add-name QA-2 --role qa --why "<counts>"` (one more name on a role of the applied configuration) or `--apply build` writes a line in `.agentboard/configuration-proposals.json` and changes nothing else. Only ORCH proposes; **only the owner applies**, with `accept N` or `ignore N` or the board's Accept and Ignore (`POST /api/configuration/proposal`); a shell with an agent name set is refused, and the file is validated again on Accept. An ignored suggestion is not asked again for 7 days, a change already waiting, a configuration already applied and a name already on the board are refused up front, and the ORCH prompt says how to propose and what waits or was ignored.
- **Export and import.** `agentboard configuration export [NAME] [-o FILE]` prints or writes the file (the applied one by default; an existing file is never overwritten). On the page, `cfgAddons.importButton()` opens a dialog: pick a file, the board validates it and shows its roles, what each may not do and the terminals you would type, and applies only on **Apply** (Esc leaves; a file over 64 KB or with an unknown key is refused in plain words). `show FILE` then `apply FILE` does the same from the command line.
- **For the picker panel:** `cfgAddons.proposalsHtml(state)`, `cfgAddons.importButton()` and `cfgAddons.exportHref(key)` return the pieces, and the document gets a `cfg-changed` event after a change; `GET /api/configurations` now carries `proposals`.
- **`agentboard selfcheck`** now sends real payloads to the configuration and rename routes (preview, apply, the owner's Accept, clear, rename, its counts and Undo) on its throwaway board, so the work-profile audit stays green with them.
- Checked: `tests/test_config_proposals.py` (30), `tests/test_config_proposals_board.py` (7) and `node tests/qa/cfg_addons_check.mjs` (34 checks, 390 px and wide).

### Watch: a state word on every tile, and a sleeping board is not silence (Nov 14, slice 1 of docs/status-visibility-design.md)
Checking Watch, Now, ORCH and each agent for status was a ritual; the board held the answer but showed only percent and "doing", and it called every agent silent after the Mac slept. This is the first slice, as the owner approved the design and then shaped it on seeing it: Watch keeps its 3x3 tiles, no strip of counts.
- **One state word in one colour on each tile**, at its top right: working, silent, presumed gone, blocked, waiting on you, in review (a resting agent keeps its "Resting" tile). The tile is tinted in the hue of its word: working green, silent orange, gone or blocked red, waiting on you amber, in review blue. How long since the agent was heard shows when you hover or focus the tile, so a tile stays calm. The words are not about software: a call to book or a bill to pay reads the same as a build. A card in review waits on ORCH until ORCH has recorded its sign-off, then on you, but only on a board where ORCH signs off at all; on any other it waits on you.
- **A sleeping board is not silence:** the server notes the stretches it was not running (`.agentboard/asleep.jsonl`, two times and nothing else, with or without `[insights]`). The HUD, the tiles' "heard" clock, the silent mark and every "has it gone quiet?" check on the page (the Now pile, Watch, By agent) count an agent's quiet in awake minutes only, and Watch says "Board asleep 2 h 05 (04:20 to 06:25) · not counted as silence" in one quiet line when it applies. The roll-up and the watchdog still count the card's raw age; they are not part of slice 1.
- `/api/hud` carries a `status` block (a row per agent with its state word and who it waits on, the five counts, the latest sleep) and each agent a `quiet_min`; no new route, no new setting. The five counts are kept for the later digest; the page does not draw them. Not built (slices 2 to 4): the shared queues and "In queue", the track per kind of card, the six-hour strips, the digest and the Ask box.
- Checked: `tests/test_status.py` (31: the sleep record, the rule on the same card with and without a sleep, every state word, who waits on whom, the counts and their order, `/api/hud`, the server tick, the page source); render-check wide, narrow, light and dark against a throwaway board.

### Insights: the model on a card and its size, so the board can say what goes faster where (Nov 14, same flag as insights v0)
The board could not say which model or agent does a kind of card faster, or whether "a small card" was small: nothing recorded either. This adds the two small captures the design asked of agents (one name, one letter) and the two rules they unlock.
- **Model:** `agentboard claim ID --model <name>` and `agentboard start ... --model <name>` put a short model name on the card; `AGENTBOARD_MODEL` set once per session is read at claim, only with `[insights] enabled = true`. A claim with no model clears the last one's, so a card never carries a model that did not claim it. A bad `--model` (more than 60 characters, or anything but letters, digits and `. _ : / + -`) refuses the claim; a bad value in the environment is ignored.
- **Size:** `agentboard add "<title>" --size S|M|L` (and `start --size`) records an estimate, in either case. With insights on, the first review records `actual_size` from the card's own time since its first claim: S under 1 h, M under 3 h, L more. Lines changed stay outside the server (the design's opt-in git reader).
- **`agentboard insights` has three more observations:** *Estimates miss* (fires when at least 40% of the sized cards came out bigger than estimated; cards from before the capture use their build time), and *Kind of card against agent* and *against model* (within one kind of card, two agents or models with at least 5 cards each: fires when one's median build time is under 70% of the other's; otherwise "not enough data", which is most boards for now). Counts, kinds, ids and the names the sentence is about; no title or note text.
- An explicit `--model` or `--size` is kept even with insights off (as a closing reason is); the environment is never read then, so a board with it off writes what it always did.
- Not covered: nothing asks the agents to set `AGENTBOARD_MODEL` or `--size` yet (the instructions text is unchanged: ORCH decides the rollout); the opt-in git reader for lines changed.
- Checked: `tests/test_model_size.py` (34: the helpers, claim and start, the environment on and off, add and the command, the actual size at the first review and only the first, both rules on hand-counted cards), `tests/test_insights.py` unchanged apart from the rule list.

### Watch feels alive: a connection dot and an honest pulse per agent (Nov 14)
On Watch the rings can sit still for a long time, and a still screen looked the same whether the board had lost its connection or the agents were idle. Two signals now, both read from data the page already has: no new request, and the percent never moves for a pulse.
- **A connection dot in the header (Watch, Now and the rest):** `Live · updated 3s ago` while the page's own poll answers, amber `Slow` after 5 s without an answer or a failed poll, red `Reconnecting… last update 14:07` after 3 failed polls in a row or 15 s of silence. While it is red the Watch tiles freeze and dim, so a quiet screen is never mistaken for busy agents. It says the change once to a screen reader. A hidden browser tab is not a lost board: the clock starts again when it comes back. The old `Disconnected; retrying` chip is still there and is hidden while the dot is red.
- **Each Watch tile says how long since its agent was heard:** `heard 8s ago` in the agent's colour with a steady pulse (under a minute), `heard 4m ago` with a slower, dimmer pulse (a minute up to the limit), and from the limit an amber ring, no pulse, `last heard 12m ago` and a QUIET tag. The line is never hidden, and the tiles age in place on the poll's beat without a redraw. The old small age at the top right of a tile is gone.
- **`[board] silent_minutes`** (default 10, 1 to 100000) sets where a tile goes amber; `/api/config` carries it to the page.
- **Reduced motion:** the same colours with a static ring and dot, no animation.
- Checked: `tests/test_watch_alive.py`, and the page rendered in headless Chrome on a throwaway board (light, dark, 390 px wide, a server stopped mid-session).

### Insights: one rework event, so the board can say why work comes back (Nov 14, same flag as insights v0)
The "Be simpler" replies, reopened cards and second reports were the only trace of work coming back: the dedicated Send back had 0 uses on 2,878 cards, and nothing said why a card returned. With `[insights] enabled = true` every path that sends a card back now writes one log line, `Rework: <code>`, with a code from a closed list and nothing else (never the note or the reply).
- **Five codes:** `sent-back` (the owner's Send back), `be-simpler` (the Be simpler button on a card in review), `changes-asked` (any other reply to a card in review; the board cannot tell a change from a question, so every reply to a report counts), `reopened` (a card moved out of Done) and `re-reviewed` (the agent reported finished again with no request on the card since its last report). A report that follows one of the first four is that request coming back and adds no second line; with the flag off the log is exactly what it was.
- **`agentboard insights` has a sixth rule, *Work comes back*:** the share of cards reported finished that were reviewed twice, sent back, reopened or answered with a change request (fires at 20%, needs 5 cards), the reasons counted, and each kind of card with at least 5 cards. Cards from before the switch show as "no reason recorded". Counts, kinds and ids only; the board's own words are never printed.
- Not covered: a change asked for in chat shows only if the agent then reports the card finished again; the model and size captures (#6, #8) are the next insights cards.
- Checked: `tests/test_rework.py` (30: the codes, flag off writes nothing, each path writes one line, a request and its report are one rework, counts only, the rule on hand-counted cards, the command on a throwaway board), `tests/test_insights.py` and `tests/test_agentstates.py` unchanged apart from the rule list; the whole suite alone.

### Agent configurations: roles on the board, and an approval card for outside actions (Nov 14, slice 2; off by default)
Slice 2 of `docs/agent-configurations-design.md`. With `[agents] configurations = true`, a small JSON file names the agents and their roles; you pick it, you start the terminals, and the board reflects them.
- **`agentboard configuration show|apply|clear [NAME|FILE]`.** `day-to-day` ships with the board (caller, bills, forms, research, planner, family: each may research, draft and plan; none may place a call, send a message, pay or submit a form on its own). The file is validated (unknown keys, names the board keeps for itself, a name in two roles and counts that disagree are refused); the applied copy is `.agentboard/configuration.json`, validated again on every read. Applying changes the roster and labels only, and starts nothing.
- **A role chip** beside the name on Now, Map and Watch (working, waiting and resting tiles); the compact Load strip has the role in its tooltip. None without a configuration, and a phone shows the name only on a card.
- **The role in the prompts:** a card held by an agent that has a role gets a role block (what it is, may and may not do, the tools to leave enabled, the approval rule); `claim` and `start` print it to the agent; the ORCH prompt lists the roles and the rule. The configured names are on the roster (the HUD, `known_names`, the ORCH prompt) but not on the chat autopilot's.
- **The approval card for an action outside the board:** `chat send ... --propose "<action>" --outside --target --say --money --shares` is the chat's own proposal (one decision, Approve and Decline, `chat approvals` for the agent) with the four things an outside action must state, addressed to you by default, and an approval that is for that one action and **lapses 30 minutes after the ask**: `chat_decide` refuses a late yes or no and records nothing. The bubble reads *Needs your word · nothing has been done* with **Approve this action** / **Not now**. It differs from the design's wording (built on `ask`): the proposal already had the one-decision record and the agent-side read, so it is extended instead of a second mechanism.
- **Fixed on the way:** Approve and Decline did nothing in an agent's thread (only the ORCH drawer listened); they work in both now.
- Checked: `tests/test_configurations.py` (26), `tests/test_outside_approval.py` (13), `node tests/qa/roles_check.mjs` (35 checks, wide and 390 px) and `node tests/qa/approval_check.mjs` (18). Pictures: `docs/agent-configurations/`.

### ORCH signs off on a card, with its evidence (Nov 14)
The owner signed off two cards that ORCH knew were not merged yet; ORCH had the facts and the board did not show them. A card in review now carries ORCH's sign-off next to its review state, and signing first tells ORCH.
- **`agentboard signoff <id>`** (ORCH): records what ORCH holds, as hashes, counts and results only: `--merged <hash>` or `--not-merged --ahead <n>`, up to four `--test "<suite>=pass|fail|running|pending|skipped"`, `--gate pass|fail|pending`, `--verified-by <name>`. Every field is checked against a small pattern, so no message text can be stored. Only ORCH (or the owner at a terminal) can run it; an agent cannot sign off its own work.
- **The card shows one row under the agent's sentence, in three states:** green `ORCH signed off` (merged hash, the tests, the batch gate, who verified, the time), amber `ORCH: not merged` (branches ahead, suite running, gate pending), grey `ORCH has not signed this yet`. The detail panel shows the same row. A new review, the card going back to work, to Todo or Later, or a send-back drops it; done keeps it as the record.
- **Signing off without ORCH:** pressing Mark done on a review card whose sign-off is missing or says not merged still works, and the toast says `Signed off without ORCH: not merged yet. ORCH has been told.` ORCH gets one chat line with the card and the state (no message text). The bulk move says how many.
- **`agentboard done` by ORCH goes through the sign-off:** on a card in review it needs a sign-off that says merged, recorded first or in the same command (`done <id> --merged <hash> --test ... --gate ...`). An agent's own `done` still works as before, with a warning on stderr when ORCH has not recorded a merge. ORCH's boot prompt carries the command.
- Checked: `tests/test_orch_signoff.py` (19: the record, the command, who may run it, what drops it, ORCH's done, the heads-up and the bulk line, the row's code), and the board rendered in headless Chrome on a throwaway board.

### Rename an agent: `agentboard rename OLD NEW` (Nov 14, slice 1 of agent configurations)
Approved in `docs/agent-configurations-design.md`. A name can change without losing anything: the cards it holds or held (and their claims), its chat, its read position, its colour and its place in the roster all move to the new name; the words of a line that say the old name stay as written.
- **`agentboard rename OLD NEW [--dry-run]`** rewrites each card's `agent`, each log line's `by` and `actor`, a `learned` note's `by`, each chat line's `sender` and `to` (live board and archive, after a snapshot called before-rename), the keys of `chat-cursors.json`, `chat-delivered.json`, `chat-listeners.json` and `chat-autopilot.json`, the name in `sessions.json`, the roster entry in `config.toml`, and the colour (a pinned colour moves; otherwise the palette slot the old name had is pinned for the new one). `--dry-run` prints the counts and the config lines and writes nothing.
- **The old name keeps working.** `.agentboard/aliases.json` is written first, so a rename that was cut short is finished by running it again, and `--name`, `--to` and `$AGENTBOARD_NAME` holding the old name mean the new one (one step before any command runs) until a day after its last use. `agentboard rename --undo` runs the last rename the other way and drops the alias; the board keeps the last 20 in `renames.json`.
- **Refused:** a name another agent has or has had (a card, a line, a state file), ORCH, `all`, `you`, the owner's name, anything but letters, digits, space, dot, hyphen and underscore (the name is written into `config.toml` as text, and that edit is read back as TOML before it replaces the file), and an old name nobody has.
- **No board button yet** (the picker and the Rename dialog are slice 3). `agent_slot()` moved from `cli.py` to `names.py`; `cli.agent_slot` still works, and `agentboard spawn` reads a pinned `var(--aN)` colour as that slot's hex.
- Checked: `tests/test_rename.py` (37: the alias rules, every place a name lives, undo, the refusals, the command line).

### Insights: agent state history (Nov 14, same flag as insights v0)
With `[insights] enabled = true` the server now notes once a minute what each agent is doing and appends a line to `.agentboard/agent-states.jsonl` when it changes, plus a heartbeat every 15 minutes (a gap is then time nobody watched, not a long state). States: working, quiet, abandoned, waiting (every open card is a question to the owner), review, listening (no open card and a wait running: waiting for work) and away. A card in review no longer hides the agent's work on another card, as the HUD's own label does. A line is a name, a state word and a time: no text.
- **`agentboard insights` reads it**: a fifth observation, *waiting for work* (per agent, once 8 hours were watched; fires at a quarter of the time), the night gaps say where their hours went (waiting for work, waiting for the owner, away) and the card-in-hand share shows the measured split, instead of listing what the board cannot see. With no history each says so.
- Checked: `tests/test_agentstates.py` (30: the state rule, the sampler on a throwaway board, the server thread, intervals, the rules on hand-built lines), `tests/test_insights.py` (42), and `node tests/qa/states_check.mjs` (a real `serve` on a throwaway board: the flag turned on while it runs, the next tick writes a line per agent and nothing else, `insights` prints the new row; 6 checks).

### Insights v0: how the agents are used, from the board's own records (Nov 14, off by default)
The retrospective of the Long Haul build (95 cards in 40 hours) had to rebuild every timing from logs, chat snapshots and git; `docs/insights-design.md` says what the board should record instead. This is its smallest first build (card `agentboard-insights-v0`).
- **`[insights] enabled = true` in `config.toml` turns on three captures**, and with it off the board writes exactly what it always did: a card made with blockers logs "Blocked by ..." (only `edit` did), a card whose last blocker finishes gets "Unblocked: every blocker is done", the name that made a card is kept as `actor` on its `Added` entry (not `by`, which the page shows as a human), and a card closed without a reason is `closed_as: shipped`. `agentboard done ID --reason shipped|duplicate|not-reproduced|superseded|not-needed` records one (kept even with the flag off).
- **`agentboard insights [--since 7d|24h|all] [--agent NAME] [--prefix ID_START] [--json]`** prints four observations with their numbers: blocked cards wait, a few cards hold the hours, the nights are idle, a card in hand. Each says "not enough data" under 5 cards, names what the board cannot see, and suggests a change; counts, timings and card ids only, read-only, no outside request, no program started.
- Checked: `tests/test_insights.py` (42 tests, hand-counted cards); on a copy of the Long Haul board the shares match the retrospective's for all seven agents and the blocked wait is 3.13 h (26 claimed cards), as in the retro.

### Talk it through: an answer lands in its question's thread; a handled line is not delivered again (Nov 14)
Two bugs in the board's conversation with ORCH. An answer ORCH sent with a plain `chat send` (no `--to`, `--card` or `--reply-to`) never showed in the Talk it through box and went to every agent's inbox; ORCH had to send it again with all three. And a line that ORCH had already acted on was printed to it again by a later `chat inbox`, "printed to you 10 min ago and never confirmed: shown again".
- **A plain answer is threaded.** `chat send` from an agent with no recipient, card or reply-to answers the owner's latest unanswered line to that agent (within 30 minutes, and about the same card or none): it is addressed to the owner, replies to that line, and carries its card, so it shows in the conversation under the question and reaches no other inbox. An answer that names its question with `--reply-to` takes that question's card. A line to an agent, a line about another card, an announcement after the question was answered, and a question older than 30 minutes stay as written.
- **A session that came back has read what it was shown.** A delivery now records which session it went to (the first ancestor process of the command that is not a shell: the agent runtime, or a terminal tab's login). That session running any board command, with or without `--name`, or its next `chat inbox`, confirms the delivery whatever its age. The five-minute rule still applies to a different session taking over the name, and to a session that cannot be told. A session may name itself with `AGENTBOARD_SESSION` (like `AGENTBOARD_NAME`); the lookup is a read-only `ps` in `lifecycle.py`, where the work profile's program-start table already allows one, and an unavailable or refused `ps` just means an unknown session.
- Checked: `tests/test_talk_thread.py`, `tests/test_session_receipts.py` (the busy session, the gone reader, the session key) and `node tests/qa/talk_check.mjs` (the box in headless Chrome, 12 checks; red before the fix).

### Esc leaves a text field (Nov 14)
Typing to ORCH (the line at the bottom, the chat drawer, the Ask ORCH box in Talk it through) or parking an idea in Later left you in the field: the board's keys did not work again until you reached for the mouse, and Esc closed the drawer or the conversation under you in the same press.
- **The first Esc in a text field leaves it and keeps what you typed**; the board's keys (`?`, `l`, `n`, `s`, the arrows) work again at once. The next Esc closes the layer under it, as before: the conversation, the sheet, the drawer, the card.
- **Left as they were:** the new-task field (its Esc closes its sheet), the card editor (its Esc cancels the edit), the settings search while it has text (the first Esc clears it), a select, a switch and a slider.
- **An IME composing is never interrupted:** an Esc with `isComposing` set goes to the IME, closes no panel and blurs nothing.
- Checked in headless Chrome on a throwaway board with real key events (`node tests/qa/esc_field_check.mjs`, 30 checks); `tests/test_esc_leaves_field.py` pins the handler.

### A restart keeps the keys the board was started with (Nov 14)
A board started with extra `AGENTBOARD_*` settings in its environment (a plugin's keys) lost them when `agentboard restart` was run from a plain shell: the new server got that shell's environment and nothing else, and a feature went quietly off until someone noticed.
- **`agentboard restart` reads the old server's `AGENTBOARD_*` environment before stopping it** (its own process: `/proc/<pid>/environ` on Linux, `ps -E` on macOS) and keeps every setting this shell lacks; this shell still wins where it sets one. The one line names what was kept, never a value. `--fresh` takes this shell's environment only.
### Talk it through: a conversation on the card (Nov 14)
The owner still went to ORCH's terminal to be walked through the cards one by one, and to talk until it was clear what a card wanted. The line at the bottom showed one answer and let it go.
- **Talk it through** on the open card of Now (`/`, or the first button under the card): a conversation with ORCH opens beside the card. Each line goes to ORCH with the card attached, so the card never has to be named, and ORCH's answers about that card collect there. Four starter questions are offered: what is this asking me, say it simpler, what do you recommend, what happens if I say no.
- **It ends in an action.** When what you want is clear, ORCH proposes the reply for the card's agent. **Send this** sends it (the board sends it, not ORCH), the card leaves the pile, and the conversation moves to the next card. **Change it** rewords it first.
- **It follows you down the pile**, and a card you already talked about opens with its conversation. `Esc` closes it.
- **ORCH's boot prompt says how**: a line ending "(card <id>)" is answered about that card only, in one or two plain sentences, with `--card`, and the reply goes in `--propose` once the owner is clear. An ORCH started from an older prompt answers in the bubble as before, so copy a fresh prompt.
- **Walk me through** (later the same day): a switch at the top of the conversation. While it is on, the board asks ORCH about each card as you reach it, and ORCH says what the card wants and what it would do, with the reply ready to send. A card you only pass on the way down the pile is not asked about. The switch is remembered.
- **Sign off from the conversation**: on finished work that needs nothing from you, ORCH proposes the sign-off itself. The button reads **Sign off** and closes the card; **Not yet** keeps it open.
- **A dot on Talk it through** when ORCH has answered about a card and you have not looked.
- Nothing new runs and no new route: it is the board's chat (`POST /api/chat` now takes the `card` a line is about). While ORCH is away the conversation says so and keeps your line for it.
### Starting the day: ORCH, one click away (Nov 13)
Finding the ORCH prompt took a trip to the drawer, and nothing said that ORCH was not running.
- **The board says when ORCH is away.** It already knows who is listening. When ORCH has not listened for 90 seconds, the line at the bottom reads "ORCH is not running" and shows **Start ORCH**. What you type there is still kept, and a note says ORCH will read it when it starts.
- **Copy prompt, where you are.** Start ORCH opens a small panel over the line: **Copy prompt** (the same prompt as before), then paste it into a new agent session, whichever agent you use. The panel opens by itself once a day, unless the page already shows the offer. An empty Now or Watch carries the same button in the middle of the page.
- **"ORCH is here"** shows the moment the pasted session starts listening, and the panel closes itself.
- **`agentboard orch`** prints the same prompt in a terminal, so `claude -n ORCH "$(agentboard orch)"` starts Claude Code with it loaded. The panel offers that line as an extra.
- The board starts nothing: it gives you words to paste. A board with `[ui] dispatch = false` shows none of this.
- **`d` on Now and Watch**: the card keys (`c` copy, `d` done, `b` back to Todo) act on the card in front of you on Now and on the selected card on Watch. They used to need the pointer over a card, so on those tabs they did nothing.
- **A Todo card on Map keeps its height**: its Copy and Later buttons lie over the right end of the title on hover or focus, and take no room of their own. The column no longer jumps as the pointer crosses it.
- **Start ORCH could swallow its own click**: the button hid as soon as it took focus, so in some browsers the press never landed. It now hides only while you type in the line.
- **Work-computer audit** (the same day): a locked-down board was driven through every view, action and daily command in a browser with site storage blocked and the clipboard refused, with a hostile card, review and chat line on it. No outside request, no script from card text, no crash, and the lock refused what it should. Four things fixed: with site storage blocked, the Start ORCH panel, the greeting and the Start of day sheet opened on every page load (the panel covered the card's buttons), so they now stay shut when the browser cannot remember, and the panel never opens over something in use; Settings no longer tells a locked machine to switch on plugins or the sync copy (it says they are locked off), and a browser that refuses the clipboard is told that `agentboard orch` prints the same prompt.
### Handed in, and said in one line (Nov 13)
Two things kept sending the owner to an agent's terminal: work that was finished and never handed in, and a question or result that took a paragraph to say.
- **The last step says "hand it in".** When an agent's update finishes a card's last subtask, the CLI prints the exact `review` command. Before that session goes quiet, the Stop hook says it once more if the card is still at 100% and not up for review. This is the commonest way a card ended up as "Close it" on the board.
- **One line first.** The first line of an `ask` or a `review` is 140 characters at most; a longer one is refused and the message says to put the rest in `--body`. Later lines and the body are not limited, and a subtask or a plain `update` is not held to it.
- **"Be simpler" is a rule agents know**: the reporting rule in every prompt, `agentboard instructions` and this repo's CLAUDE.md now says that an owner's "Be simpler" means say it again shorter, one line, the one thing they must do. That is what the board's **Simpler** button sends.
### Now, Watch, Map: a new front page (Nov 13)
The board was organised around cards in columns; the owner's day is a loop of clearing what waits, then watching the work. The front page follows the loop.
- **Three tabs, three keys**: **Now** (`1`, the pile of cards waiting on you, the old Needs you), **Watch** (`2`, new) and **Map** (`3`, the board). The bare address opens Now. The By agent lanes have no tab and no key; `/agents` still draws them.
- **Watch** is the whole team as large cards, six to a page: working agents first (a ring that fills, what the agent is doing right now, one segment per step), then agents waiting on you (dashed, in the colour of what they need, with a count), then idle agents, resting. The arrows walk the cards; past the left or right edge the next page slides in, and a dot under the cards pulses when something changed on a page you are not on. Cards never change place: a change shows as a change (an outline, the ring growing, the number counting, a "+7%").
- **A card on Watch opens where it is**: Enter or a click lifts it out of its slot with its details beside it, and it goes back to its slot when closed. A card waiting on you opens as the card itself, so it can be answered from Watch.
- **Clearing the last card flows into Watch**, with one quiet flourish and how long the pile took.
- **One step at a time**: a review whose `## Next` lists several things shows "Step 1 of 3" with only that step, **Done · next step** and **I'm stuck** (asks the agent for help with that step only). After the last step it is a plain sign-off.
- **Simpler, Later, Why?** on the open card: Simpler asks the agent to say it in one line; Later sends the card to the end of the pile; Why? opens the details. **Sign off all** appears when two or more sign-offs report passing tests.
- **One line to ORCH** at the bottom of every view (`/`); ORCH's answer rises out of it.
- **Keys cut to what is used**: `1 2 3`, the arrows, `Enter` (details, on Now and on Watch), `Space Space`, `r` (reply), `/`, `Esc`, `?`. Gone: `j k`, `[ ]`, `a`, `h`, `t`, `e`, `f`, `m`, and Left/Right as a second way to open details. Load opens from its link in the agent strip and Settings from the gear.
- **Life**: the cards on screen travel between tabs to where they live in the next view; slow glows behind every tab warm with the share of cards waiting on you; the ring behind the pile carries one light per waiting card and turns as you move; a greeting once a day; a small burst in the agent's colour when you clear a card; the browser tab's icon shows the number waiting, or a tick. All of it stops under reduced motion.
- **Sound**: eight new Touch cues for what you do (a tab change with its direction, a Watch card rising and settling in its agent's notes, a page turn panned to its side, a step climbing a note each time, stuck, later, the batch run). An agent's step and ORCH's answer keep to the board's existing cues.
- **Fewer trips** (later the same day). The line at the bottom writes to anyone: `@` offers the names, Tab takes the first, the line shows whose face you are writing to, and plain words still go to ORCH. A line any agent writes to you rises out of it as a bubble with its name; a click answers that agent. Coming back to the tab after a minute or more shows one line of what changed (how many now need you, finished, moved forward), with **Show me** when something needs you. A card with several steps shows them as dots. On Watch an agent holding several cards is one card ("+1 more"). The details end with **Everything on this card ›**, which opens the full panel.
- **Your marks are kept on the card**: which step you are on and what you put off with Later are saved by the board (`POST /api/owner-mark`), so they are the same after a reload and on another screen. Neither counts as activity (no history line, and the card's last-update time does not move), and both end with the wait they were made in: the agent's next question or report, or the card leaving Doing. A card put off reads **Not later** to bring it back.
### The You line, and a calmer board: every card says what you owe it; each fact is said once (Nov 12)
A card in Doing used to say what it needed only when its agent had asked or handed it in. "Nothing needed" was never stated, and "abandoned?" was the board asking you a question.
- **Every Doing card carries one You line, in the same place**, and the side panel opens with the same thing as a block: **Answer** (the question), **Sign off** (the result), **Do this, then sign off** (the agent's `## Next` line, when it wrote one that is not "nothing"), **Close it** (at 100% and never handed in: Mark done or Nudge), **Check on it** (quiet past the stale threshold: Nudge or Release), or **Nothing**, greyed. The "abandoned?" corner text is gone from Doing cards: the line says which of the two cases it is.
- **Each fact once.** The lane's state word, the caption under each ring, the wait rule's verb and time, and the header's abandoned, working and quiet counts are gone: the card's You line, the ring and the strip already say them. The header keeps its two filters as bare numbers (to answer, to sign off) and says "All clear" when nothing waits.
- **Colour says the state**: a card that needs you has one soft wash of its colour from the corner (red to answer, green to sign off, orange to check on) in place of the outlined, pulsing box; a card that needs nothing is a dim outline.
- **Subtasks are drawn**: one segment per subtask, each filled as far as that step has got. The rows are folded on every card and open on a click; the count shows on hover and is still read out.
- **Words only where you act.** The reply box is one quiet line until you click into it. An ask shows the agent's own options, or one Go ahead. Todo cards are titles: Copy prompt, Later and the queued time appear on hover or focus (always, where there is no hover), and a blocked card is a lock whose blocker shows on hover. The Board page's watchdog strip is one line, "Between agents: 2 vanished · 4 stuck", that opens on a click. The panel shows what you do, how far the card is and its subtasks; activity, description, blockers, prompt, Copy prompt and Delete are behind **More**.
- **Needs you** shows the same You line in its header, and its key hints are four key glyphs with tooltips.
- **Needs you is calmer.** The line above the pile keeps the count ("7 of 17"), what the card holds in Todo, and a quiet card's reason and fix; the You line, the agent and the waiting time are no longer repeated there, since the open card says all three. The open card leads with the You line and the sentence, and its name moved to the top of the details. A strip is a face and a sentence, with the waiting time on hover. The key hints and the rail's arrows show on hover or focus (an armed "Space again" always shows), "Top of the pile" and "Last one" are gone, the details toggle is a chevron, the agent strip is dimmed on this tab, and the empty pile says "All clear".
- **Needs you, details: "The task" is formatted.** The card's description was one escaped paragraph, so a task with headings, lists or steps read as a blurb. It is now rendered the way an agent's report is (headings, lists, numbered steps, code, bold; never raw HTML), and a long one is cut with a fade and **Show all**.
- **Every review says what you do next.** `agentboard review <id> "<result>" --next "<one line>"` (or a `## Next` section in the body; `--next nothing` when nothing is needed). `--next` becomes the report's Next section, which is the line the card leads with. A review with neither is refused and the message says how to add it; a subtask, which has no review step, is not asked. Every card prompt, `agentboard instructions` and this repo's CLAUDE.md show the flag and state the rule.
### Sound overhaul: Scenes, Quiet hours, a Cues level and a live meter, three new layers (Nov 12)
Today's sound is the default and is what a fresh browser already is (the Classic scene); every new sound or look starts off, and the cues, the volume limiter and the per-view switch sounds are untouched.
- **Settings > Sound > Scenes**: one click sets the sound layers, the bed and the Cues level together. **Classic** is today's sound; **Focus** has no bed, light Touch and a soft chime for what finishes; **Control room** is the whole instrument (bed, heartbeat, each agent's call, echo, chimes, a stereo stage, the bed ducking under a cue); **Night** is rain and a slow tide under quiet cues with no Touch. A scene never touches Volume, Quiet hours or the looks; change anything by hand and the picker reads "Your own mix", and putting it back reads as the scene again.
- **Quiet hours** (off; Settings > Sound, above everything else there): a sleep schedule, default 22:00 to 07:00 and across midnight. Inside it every sound is silent, the bed fades out and returns after, and desktop notifications drop their own sound. The one thing that still sounds is a card asking you something: softly (30% of its level) and at most once every 15 minutes. **Quiet until morning** starts a window now that ends at the schedule's end time. A **chip in the header** says "Quiet until 07:00" and one click ends it (a scheduled window is skipped until its end). Hear it is let through for a few seconds.
- **Cues level and a live Output meter** (Settings > Sound, beside Volume): Cues is a level for the main sounds on their own (a card asking, starting, finishing), 0 to 100%, default 100% which is today's level; Touch and each layer keep theirs. Output reads what is about to go out, before the limiter: green is comfortable, amber near full scale, red where the limiter works, the peak falling away slowly so a short sound still shows. It reads the master bus through an analyser, only while Settings is open on the Sound tab, and slower under reduced motion.
- **Three new layers**, each off until chosen, each with a level and a Hear it: **Stage** places sounds in the stereo field (work starting leans left, finishing right, a card dropped in Todo sounds left and in Done right, each agent has its own place; an ask stays in the middle); **Humanize** varies a repeated sound a little each time (pitch about 1%, level 12%, a few ms) so a busy board does not sound like a machine; **Day bookends** play a falling phrase when you press End of day and a rising one when Start of day opens.
### Start of day: yesterday's wrap-up opens by itself; one handler for 1, 2 and 3 (Nov 12)
- **The wrap-up ORCH saved opens as a Start of day sheet, once, on the first load of a new day**: the one sentence, what waits on you, the cards to start with (numbered, best first, with the hand-off line), what is still running, and what finished and what it learned. A row opens its card and says where it stands now when it has moved since (picked up by an agent, done, gone). It never opens over something in use: a card or Load being open, a field being typed in, another sheet, a page opened at a card's link; a wrap-up from today, or one this browser already showed, stays shut. `Esc`, the × or Got it closes it (and marks it seen); **`w`** opens the last one any time (it says so when none was saved). `wrapup --apply` now saves the page as data beside the markdown, and `GET /api/wrapup` serves the newest.
- **One handler for `1`, `2` and `3`.** An earlier one (Board, By agent, Load) and the newer one (Board, By agent, Needs you) both ran, and the `?` sheet listed the keys twice. The newer one stays, and the sheet lists them once.

### End of day: checkpoint, wrap up, start tomorrow with the right card (Nov 12)
- **`agentboard wrapup`** (ORCH, read-only) says where every Doing card stands tonight and what happens to it, under one first sentence: the action first, then one fact. Each card is one of four: *finish* (at 100% but never handed in), *needs* (an ask or a review waiting on you: it stays), *carry* (goes back to Todo tonight, in the order to start tomorrow: nearest done first, a card with a checkpoint ahead of a tie) and *running* (its agent is listening and worked on it lately: left alone; `--all` counts these too). It also lists what finished today and what it learned.
- **`wrapup --ask`** leaves each agent that owes something a note on its card, the reply `answer` prints, so a waiting agent wakes with it: a checkpoint for a card going back to Todo, a review (with a Learned section) for a card at 100%. One note per card, and none for a card that already has its hand-off.
- **`wrapup --apply`**, on your word, releases the carry cards (best first on top of Todo, each keeping its progress, history and what it learned) and saves the page to `.agentboard/wrapups/<date>.md`; **`wrapup --last`** prints the newest one, to read first thing next morning. A card waiting on you never moves.
- **`agentboard checkpoint ID "<done so far · the next step · what you learned>" [--body-file F]`** is the agent's hand-off note on a card it still holds. Progress and the column stay; the note becomes the status line (the body, its account), the card's clock restarts, and a later release keeps it as what the agent learned. Refused for a card waiting on you and for another agent's card.
- **An End of day button in the ORCH drawer** sends ORCH one line (run `wrapup`, tell me its first sentence, ask each agent for a checkpoint, release nothing until I say go). The ORCH boot prompt, `agentboard instructions` and the repo's CLAUDE.md say how each side does its part.

### Back to Todo keeps what the agent learned; done cards teach; a roll-up for ORCH (Nov 12)
- **A card sent back to Todo or Later keeps what its agent had learned.** The progress, the history and the last status line were kept already; the agent's account of the work (its body, which a move to Todo used to drop), the question it was waiting on and who had it now stay on the card as a `learned` note. A card that bounces more than once keeps the earlier account when the new agent left none. A bare claim that learned nothing writes nothing. An undo puts the card back exactly as it was; the watchdog's release keeps it too.
- **The next agent starts from it.** The card's prompt gains an "Earlier work on this card" section (the last agent, its %, its last status, the question it waited on, its notes quoted as data, and `agentboard recall --card <id>` for the whole history). A custom prompt template gets it as `{earlier}` and is otherwise left alone. The card says "Resumes at 70% · atlas" in Todo, and its panel shows a "Carried over" block.
- **Easier to send back.** `b` sends the card you point at, or have focused, or have open, back to the top of Todo (next up), with an Undo toast; the open card's panel has a Back to Todo button; `Alt` + `←` and a drag still work and now keep the same notes. Not for a subtask (it goes with its parent) or a card not in Doing. On the `?` list.
- **Done cards are worth learning from.** A review body is asked for a `## Learned` section (a decision and why, a trap hit, where the work lives); the done card shows it as its own row, and a card that was sent back on the way shows what each earlier agent learned. `recall` searches both.
- **`agentboard rollup`** is the whole board in one page for ORCH or the owner: who waits on a person, what each agent holds (with %, subtasks and how long quiet), what is stuck, the Todo queue with what earlier agents learned ("↩ resumes at 60%"), what finished lately and what it learned, and the moves that follow. `--hours N`, `--json`. Read-only.
- **`agentboard release ID ... | --agent NAME`** sends Doing cards back to the top of Todo with their progress and notes (a held card tells its agent it is no longer theirs, as a drag does). The ORCH boot prompt now has a Roll up, redistribute section (rollup, release, hand Todo cards to idle agents on the owner's word, rollup again) and both commands in its cheat-sheet.

### Needs you: a third tab, the cards waiting on you as a pile you move through (Nov 11)
- The tab row is now **Board**, **By agent**, **Needs you**, and the keys `1`, `2`, `3` open them (`[`, `]` and `a` still work). The address is `/need`, and Back
  and Forward follow it. The count on the tab is what is waiting on you; a hairline under it runs down as you clear it.
- Needs you shows one card at a time: the board's own card, open in the middle, with its own reply box, quick answers and Mark done. The cards before it are
  strips above, the cards after it strips below (the agent, what it asks or reports in a line, how long it has waited, a tick when its result names passing
  tests), three each way and then "5 more below". Asks come first, then sign-offs, the one holding the most Todo cards first. It does not wrap: the ends say
  "Top of the pile" and "Last one". A column of circles on the left is the map: one per card in the agent's colour, a ring on the one that is open.
- Moving: `↑` `↓`, `Home` `End`, a click on a strip or a circle, a mouse wheel (one card a notch), or a two-finger scroll or a finger on a touch screen, which the
  pile follows continuously and settles from. Nothing is redrawn to move: the same cards change height, so a move is one motion and a second key press
  retargets it. The open card stays at the same height on the screen.
- Answering: on the card as anywhere else. `Enter` puts you in the reply box. `Space` shows which answer it would send (Go ahead, or Mark done for a sign-off)
  and a second `Space` within three seconds sends it; one key never answers. An answered card gets a tick, leaves to the right, and the next one opens where it
  stood. After the last: "Nothing needs you".
- After the asks and the sign-offs, a third group: cards the watchdog calls stuck (the agent went quiet past the stale threshold and nothing will wake it;
  a quiet agent that is still listening is not one). The line above the pile says so and carries the watchdog's own fix, **Release to Todo**; `Space` twice does
  the same. The tab's count includes them.
- An agent that left several stuck cards behind gets a second button on any of them, **Release all N of its**: one press sends every stuck one back to
  Todo and ticks each. Its open questions, sign-offs and finished cards stay where they are.
- The same group takes every card the board marks "abandoned?" (no update past the stale threshold), also when its agent still has a wait running, which the
  watchdog does not flag. A card at 100% that was never handed in offers **Mark done** first.
- What you cleared this session shows as ticks above the map, with a tally. The last sign-off can be undone from its tick (the same restore as the toast's
  Undo, without the seven seconds); an answer or a release cannot. The ticks stay on "Nothing needs you".
- Details: `→` (or "Details ›") opens a panel beside the card with the Todo cards it holds, the tests the agent wrote down, the agent's own report, the task and
  the last things that happened; `←` closes it, and the choice is remembered. The card's detail panel still opens with a click.
- The gauge strip now sits above all three tabs, in one fixed order. On Needs you the agents with nothing for you go grey and a gauge moves the pile to that
  agent's card; from the Board a gauge takes you to that agent's lane.
- By agent, under a waiting agent's name: a hairline rule with a run as long as the wait, `answer · 4 h · holds 3` or `sign off · 2 d · frees 1`. "holds" counts
  the Todo cards blocked behind that card (they wait until it is done, not until you answer). Hover or focus the card, or click `holds 3` to pin it, and Todo
  dims except for those cards; a blocked Todo card lights the card it waits on, on the Board too. A gauge and its lane light each other.
- **Load** and **Story** are no longer tabs. Load is the overlay it always was: `h`, the `Load ›` link at the end of the gauge strip, or `/hud`; the tab of the
  view under it stays lit. Story is a link in the Done column, before Summary and Reports, and the summary, reports and story pages show the same three tabs.
- Sound, in the Touch layer (so only with sound on and that layer on): each card you pass turns with a breath of paper and a note in its agent's voice, by
  key, wheel, scroll or finger; the ends of the pile give a low bump; the details slide; the first `Space` is a rising pair and its cancel a falling tone; an
  answer leaving is a sweep and two notes in the agent's voice; clearing the last card is a short rising chord.
- No new request beyond `/api/task` for the open card's details (the feed the card panel already reads), no dependency, nothing started. Light and dark; no
  motion at all under reduced motion.
- Not covered: it has only run on sample boards, never a long-lived one; on a phone the open card starts low on the screen; the passing-tests tick reads the
  one-line result, not the full report; an empty board with no agent has no gauge strip, so Load is then reached with `h` or `/hud` only.

### Story items open their card (Nov 9)
- Every card on the Story page is now a link to that card on the board, with its panel (details, history) open: each dot in the flow, the sentence on a theme card
  (the card it is about), and each row under "Needs you" (with a chevron, since touch has no hover). Click, Tab then Enter, and a tap all work; a dot keeps its
  16 px look with a 24 px tap area, and each has a name for a screen reader (title and stage). Back returns to the Story. The days are counts, so they link nowhere.
  Same look in light, dark and a phone width; no new request, nothing started, so the work profile is unchanged.

### Story: the work in plain words, five scenes you scroll, a fourth tab (Nov 9)
- New page `/story` and a **Story** tab next to Load (on the board, the Done summary, the reports list and every card report). Scene 1 is one sentence and a ring
  (finished in 7 days, in progress, waiting); scene 2 a flow Waiting, Working, Done with every card a dot in its theme's colour; scene 3 a card per theme with a
  one-line sentence and "n of m done"; scene 4 only what is waiting on you, or a calm "nothing"; scene 5 what was finished each day for 14 days.
- Built from the board's own cards with fixed templates in `story.py`: no model call, no network, no program started, so the work profile serves it exactly as
  a home machine does (a test builds it with every subprocess and socket made to fail). A theme is a work area named by a word several titles share
  (the Done summary's rule), else the agent on the cards. Backlog ("Later") is parked, so it is not in the story; a subtask belongs to its card.
- Light, dark, a 390px phone (the flow stacks, the pager hides), and reduced motion (no entrance animation at all, nothing hidden before it). Without script
  everything is visible. The tab row on the board still fits four tabs at 390px. (`ux-story-view`)
- Not covered: an "Explain simply" button (the card's optional later step; it would be off by default and locked off on the work profile); a choice of window
  (7 days and 14 days are fixed).

### By agent: a Load strip across the top (Nov 9)
- By agent now opens with a slim strip above the lanes: one gauge per agent (a ring for the share of the last hour the agent was at work, coloured by what it is
  doing now: working, ask, review, quiet; its name and the percentage beside it) and one trend line of how many agents were working, minute by minute, over the
  last hour. A gauge scrolls to that agent's lane, moves focus to the lane's name and lets the lane flash once; an idle agent's gauge is dimmed and does nothing.
  More gauges than fit swipe or scroll sideways, and the edge with more behind it fades. A **Load ›** link opens the Load view, which is unchanged (so is its tab).
  The strip shows on By agent only, never on the Board or under Load, reads the same `/api/hud` feed Load reads (polled every 5 s while By agent is on show,
  stopped everywhere else), and adds no dependency and no outside request, so the work profile keeps it. Light, dark, 390 and 1440 wide; no motion under
  reduced motion. (`ux-load-into-by-agent`; before and after in `docs/load-strip/`)
### The work profile no longer advertises the microphone command (Nov 9)
- `agentboard --help` on a work-profile (locked-down) machine listed `dictate: records the mic, transcribes on this Mac (whisper.cpp)` in a profile that promises
  no microphone. The command is refused there already (`voice is locked off on this machine`); now its row is left out of the command list while the lock is on.
  Typing it still gives that message, and a machine without the lock lists it as before. (`work-ready-ux`: first run on the work profile, walked wide and narrow,
  light and dark: no console errors, nothing leaves the machine, no other home-only wording found)
- Not covered: the command name still shows in the `{init,profile,...}` usage line, which argparse builds from every command.

### Settings in tabs: General, Sound, Agents and chat, and a tab for each plugin, with search (Nov 8)
- The Settings sheet was one 480px column of 19 sound and look controls, 2,164px tall; the settings that were not sound sat below the fold. It is now 720px
  wide with a tab list on the left (the screen, with a strip of tabs, on a phone): **General** (Theme, the Look rows, the board's owner and stale minutes),
  **Sound** (the old sheet's layers, in two columns), **Agents and chat** (agent chat on or off with the command that changes it, and who is listening),
  and a tab for each plugin that registers one (`AB.settingsTab(id, label, {order})`; a tab with nothing in it is not drawn; `AB.settings` still works and
  shows as a More tab). A search box finds a setting on any tab (`/` focuses it, Enter opens it); `/#settings/<tab>` opens the sheet on a tab; the last tab
  is remembered per browser; the tab list is a real tablist (arrows, Home, End). No setting was removed or renamed. **Security** and **Backup and data** show
  read-only status (lockdown, work profile, secret masking, plugins; last backup, sync copy, whether the data folder is private) from a new `GET /api/settings`:
  booleans, counts and minutes only, never a path, a pattern or a secret, behind the same Host check as every route, with no route that changes anything; each row
  names the key or the command that does. (`settings-ui-tabs`; `docs/settings-tabs-design.md`)

### Boring start, stop, restart and status (Nov 8, branch overnight/overnight-rel-server-lifecycle)
- New commands: `agentboard status` (running or not: pid, port, since, uptime, plugins, lockdown; stale server files cleaned; exit 1 when
  nothing runs), `agentboard stop` (SIGTERM, then a wait until the server has finished what it was doing), `agentboard restart` (same port,
  this shell's environment), and `agentboard serve --background` (detached, output to `.agentboard/server.log`, rolled at 2 MB).
- `agentboard serve` ends cleanly on SIGTERM: in-flight requests finish, the state file is removed, "agentboard: stopped" is printed. A taken
  port says who holds it (this board's server, another board's, or something else) and the next step.
- New route `/api/health` (loopback, no board data) and a doctor line about stale server files. `stop` signals only a process whose command
  line is an `agentboard serve`.

### The board at thousands of cards: a poll that finds nothing new costs nothing, the HUD builds ten times faster, budgets in a test (Nov 8, overnight)
- Every open page polls `/api/tasks`, `/api/hud` and `/api/chat` once a second. On a 5,000-card board each poll parsed the 10 MB board file again and the HUD rebuilt in half a second, whether or not anything had changed. The server now keeps what each route derives from `tasks.json` until the file changes (its mtime, size and inode; every save is a new inode, so nothing can go stale), sends an `ETag`, and answers `304` with no body to a page that sends `If-None-Match`; the page does. A board that is still costs a hash per second; a change is seen on the very next poll.
- `hud.build` parsed every timestamp with `strptime` (130,000 calls per poll at 5,000 cards); the one stamp parser (`store.parse_stamp`) now tries `fromisoformat` first, ten times faster, with the old parser as the fallback. A claim or update no longer re-reads the whole board after its commit to see whether a report is due (`maybe_report` looks at what the store just wrote).
- The Todo column draws its first 200 cards and a Show more button past that, like Done; a 1,500-card queue took 350 ms a redraw.
- `tests/test_perf_budgets.py`: a 1,000-card board with 2,000 chat lines against a real server, budgets of about three times the measured cost for the store, each polled route cold, cached and 304, payload sizes, the HUD build and 10,000 chat lines, scaled by the machine's state as `tests/timing.py` does. `tests/perf_bench.py` prints the numbers (and, with `--browser`, first paint in headless Chrome; with `--soak`, N fake agents posting every second for M minutes).

### config.toml you can trust: one schema, `agentboard config show | check | docs`, invalid values fall back to the default and say so (Nov 8, overnight)
- Tonight several settings silently did the wrong thing: a typo in a key was ignored, a value of the wrong type fell through to whatever the reader did with it, a switch could turn a safety feature off without a word. `configschema.py` is now the one place that says what config.toml may hold: every core key with its type, range, default and meaning. `load_config` hands every module that reads through it the cleaned config, so an invalid core value is its default (never a guess) and those readers need not guard against a string where an int should be (`redact.settings` and the backups read the file themselves and keep their own guards); unknown keys and sections are kept as written (a plugin reads its own) and reported by `config check` and `doctor`.
- `agentboard config check` lists unknown keys with the closest valid name, wrong types, out-of-range values (exit 1 on an invalid one) and unsafe switches as warnings (`[redact] enabled = false`, the `claude` rounds, a sync folder, a different `claude` binary); `agentboard config show` prints every setting that applies and where it came from (default, file, or default because the file's value is invalid) plus which `AGENTBOARD_*` variables are set (never their values); `agentboard doctor` carries the same findings as `schema` lines. `agentboard config docs` prints the reference page, and `docs/config.md` is that output: a test fails when they differ.
- A plugin registers its own section with `api.add_config(section, {key: Field})`; it joins the checks and the docs while the plugin is loaded.

### Python 3.9 to 3.14, a three-command install, upgrade and uninstall written down, doctor passes on the repo (Nov 7, overnight)
- The floor drops from 3.11 to 3.9 (the Python a 2021 Mac or Ubuntu 22.04 already has): `tomlread.py` uses `tomllib` where it exists and a small built-in TOML reader before that (tables, arrays of tables, dotted and quoted keys, all string forms, numbers, dates, arrays, inline tables; checked against tomllib on the config `init` writes, the README's block and every snippet the tests write), the masker's possessive quantifiers become plain ones on 3.9 and 3.10 (same matches, slower worst case, bounded by the size caps), and one f-string that needed 3.12 is split. The suite runs on 3.9, 3.11, 3.12, 3.13 and 3.14.
- README: install is three commands, then Upgrade and Uninstall sections (the whole footprint: pipx's venv, `.agentboard/` per project, `~/.agentboard` for named boards, `~/.config/agentboard` for private words, the hooks `hooks uninstall` removes; nowhere else), and a troubleshooting list written from the Nov 7 failures (a plugin crashing on load, keys lost on a restart, a stale `build/`, the doctor's tracked-files FAIL, first-run WARNs).
- `agentboard doctor` on this repository is 0 FAIL: the key scan now leaves alone what the masker itself knows is words (`sk-learn-pipeline-for-the-model`), and the two test fixtures that are real-looking by design (a phone number, a token assignment) are built from pieces.

### Developer docs: ARCHITECTURE.md, CONTRIBUTING.md and a documents index, checked by a test (Nov 8, overnight)
- `docs/ARCHITECTURE.md`: the module map (every module, grouped by layer), the data files and who writes them, a request's path through the server (guards, headers, routes), the agent protocol in `store.py` terms, the plugin hook, the security model on one page, and how to run the tests. `CONTRIBUTING.md`: cards and worktrees, the gates before "ready", the changelog rule, commits, where things belong. `docs/index.md` lists every document with one line; the README links all three.
- `tests/test_docs_architecture.py` holds the pages to the code: every module is in the map and every named module exists, every data file named is in the source, every API path is in `server.py`, every CLI command exists, the plugin API listed is `plugins.Api`, every link in the index resolves and every document is in it.

### The agent protocol heals itself: `agentboard watchdog`, a strip on the HUD, a doctor line (Nov 8)
- A board gets stuck between agents in a handful of ways and each used to need a person to notice and know the fix: a card claimed
  and never worked, a card whose holder vanished (no update, no wait running, no chat), two cards for one piece of work, a card held
  by one agent with subtasks held by another, a subtask whose parent was deleted, a subtask in Doing while its parent is not, two
  sessions answering to one name, an agent that never said who it is (so the Stop hook and the mirror cannot reach its session).
  `agentboard watchdog` finds all of them in one pass, numbered, each with its one fix; `--fix N` (or `all`) does it and says what
  moved: release to Todo (history kept, holder cleared, open subtasks along), release every card of a vanished agent, merge the
  twin into its keeper (a named snapshot first), hand the subtasks to the card's holder, make an orphan a card of its own, a subtask
  follows its parent's column. Every fix is one history line marked "the watchdog, for <owner>". The two with no board-side fix say
  what to run. Nothing happens unasked.
- The Load view shows the findings in a strip above the lanes, one row each with its button; `/api/hud` carries them and
  `/api/watchdog-fix` does one. `agentboard doctor` gains a `watchdog` line: WARN with the counts, PASS when the board is clean (so `doctor --strict` exits 1 while a claim is
  stale or an agent has vanished). `watchdog --fix all` reports a row an earlier fix in the same run already covered as "already done" and
  goes on; `--fix abc` is refused with the accepted forms. The Board page shows the same rows under the Doing header (`/api/tasks` carries `watchdog` when there
  is something to show). ORCH's prompt and `agentboard instructions` name the command (an agent reports a stuck card to ORCH and never
  releases a peer's claim itself). The tasks feed caches the findings for a few seconds between polls.
- A claim refused because another agent holds the card now says what to do (ask ORCH, or `agentboard watchdog` if that agent is
  gone) instead of only "use --force". Card `overnight-rel-agent-protocol`; evidence in `docs/overnight/overnight-rel-agent-protocol.md`.
- An `update`, `review` or `ask` from a session whose name is another agent's is refused with the same fix: the quiet form of two
  agents on one card, where the second never claims and just writes on it. The name is the session's `AGENTBOARD_NAME` (the three
  commands take no `--name`), so this is a guard against accidental cross-writes, not enforcement: a nameless caller, the holder, ORCH,
  the owner and a card with no holder are let through, and two sessions under one name both pass. `agentboard instructions` and ORCH's
  prompt say the rule. Card `overnight-rel-agent-protocol-3`; evidence in `docs/overnight/overnight-rel-agent-protocol-3.md`.

### The test suite itself refuses to leave the machine (Nov 7)
- `tests/netguard.py` is loaded by both runners before any test runs (pytest through `tests/conftest.py`, `unittest discover` through `tests/test_net_guard.py`) and makes any `connect`, `connect_ex` or name lookup to a non-loopback target fail with an error that names the test, so a change that adds an outbound call fails the suite the same day. Loopback, the unspecified address, `localhost` and AF_UNIX paths pass; `AGENTBOARD_TEST_NET=1` switches it off for a run that must reach the network (nothing in the suite does). Ten tests cover the guard itself.
- `docs/security-signoff.md`: a two-page sign-off for a reviewer on a managed machine, every claim cited to a file and a test, with the known limits listed. Documentation; the audit page and `SECURITY.md` are unchanged.
- The masker's wall-clock tests (`test_redact_dos.py`, `test_redact_fullwidth.py`) no longer fail on a busy laptop: `tests/timing.py` scales each limit by a same-moment linear baseline and tries a slow run up to three times (best time counts), under a 30 s ceiling. Quadratic work still fails every try; a scheduler hiccup no longer fails green code (it did four times on Nov 7 with two suites running at once).
- `agentboard doctor` has a `masking` line: FAIL when `[redact] enabled = false` in config.toml has switched secret masking off (the fix line says what to delete), WARN when the default was changed (phone numbers added, or patterns of your own, counted and never printed), PASS otherwise. `config.toml` is writable by anything that runs as you, so the switch deserved a line a reviewer sees.
- `tests/test_signoff_files.py` keeps the sign-off's file table true: a scripted day on a throwaway project and HOME, then every path the board wrote must be named in the table with the mode the table gives, and nothing may appear under HOME. A new state file fails the suite with its name until the table says what it holds.

### By agent no longer hides lanes past the edge: a fade and a "+4 more" chip (Nov 8)
- With six or more agents the lanes scroll sideways under a scrollbar that overlay-scrollbar systems hide, so a lane past the right edge had no
  sign it was there, and an agent waiting on you could go unseen. Each edge that has more now fades, and a chip counts what is past it
  (`+4 more · 1 needs you ›`, `‹ 2 more`), says when one needs you or is ready for review, and jumps to the lane that needs you first, else the next.
  Nothing shows when every lane fits, under Load, or off the By agent view. A keyboard reaches the chips; reduced motion jumps without the glide.
  (`ux-by-agent-hides-lanes-past-the-fifth-w`; `docs/by-agent-lane-cue/`)

### `agentboard doctor` and the repo guard read one set of rules, so the doctor's standing FAIL on fixtures is gone (Nov 8)
- The doctor's `tracked files` scan and `tests/publiccheck.py` carried two copies of the secret shapes and the allow rules, and they disagreed: the doctor showed a FAIL all day on seven fixture keys inside tests that the guard, rightly, allowed (plain words after `sk-`, the song's phone number, a key of one repeated letter). A standing FAIL trains people to ignore the doctor. Both now read `src/agentboard/repoguard.py`: the same shapes (keys, tokens, private keys, Authorization headers, assigned secrets, phone numbers, emails, home paths, the owner's private words) and the same allow rules. A real-looking key still FAILs wherever it sits, a test file included; a fixture the guard lets through is a PASS. The doctor's kind names are now the guard's (`aws-key`, `assigned-secret`, `phone number`); emails and home paths, which only the guard checked before, are WARN lines in the doctor too.

### Five small findings of the Nov 7 merge review (Nov 8)
- One rule for a hard-off variable: `lockdown.env_on(name, env=None)`; doctor and the plugin gate use it instead of their own copies of
  the off-words. (`rev1107-doctor-dup-env`)
- A config path with an embedded NUL (`template_file`, a markdown or file-tail provider) made `prompt`, `/api/prompt` and `doctor`
  crash under lockdown with a `ValueError`; it now reads as outside the project, as any unreadable path does. (`rev1107-lockdown-nul-crash`)
- The masker treated a lower-case hex run with one dash or dot as a kebab-case word, so `token=<hex>-<hex>`, `key: <hex>.<hex>`,
  `sk-live-<hex>` and a Mailgun-style `key-<32 hex>` passed. A segment with three or more digits is not a word now; identifiers
  (`task-queue-implementation-notes`, `user_profile_cache_v2_final`) and dates in prose are untouched. (`rev1107-redact-wordy-hex`)
- Three small masker gaps: a zero-length owner pattern no longer duplicates the invisible character around it; `agentboard redact` walks a
  chat line's `files` and its proposed action too; a key-shaped session name is masked before it reaches `sessions.json`, the listener
  file or the cursor file; a cut-off PEM with `Proc-Type`/`DEK-Info` header lines is masked through them. (`rev1107-redact-small-gaps`)
- One stamp parser, `store.parse_stamp`, replaces four copies (hud, the chat, the cursors, the CLI); the Stop hook's `known_name` is
  `resolve_sender` without the fallback; `REASON_MAX` is the cap it says it is (600, the same length as before). The cursor file itself
  became one locked module earlier (`cursors.py`). (`rev1107-cursor-file-dup`)

### Nine lines where the board and the terminal did not match the chat design (Nov 8)
- `chat send --to` a name nobody has posts nothing and exits 1: `Not sent: no one named AGENT-33. Closest: AGENT-3. Send again with
  --to AGENT-3.` (or `Names on this board: ORCH, AGENT-1, …`); the name is checked before the agent-chat switch; the roster in
  `[orch] agents` counts as known names. The switch-off and over-the-limit refusals read as the design wrote them, and a long line to
  the owner now says `Sent, cut at 300 characters: the rest is in the detail.` The owner's own typo from the board is still posted and
  marked (the composer stops it first).
- Receipts: `Nobody is listening for AGENT-4.` (`…for ORCH: it reads the board at its next check.`); a listening-but-busy agent is
  muted, not amber: `AGENT-5 is listening but busy: it reads this when its step ends.`; after the Nudge, `ORCH asked 2m ago to message
  it`. The composer's `On this board:` list puts ORCH first and leaves the owner's own name out, and an exact `@AGENT-2` with no space
  counts as a complete name. Found by AGENT-2's check of chat-f8 against `docs/chat-words-design.md`.

### The chat box says who reads the line, and a refused send keeps your text (Nov 8)
- Under each chat box (the ORCH drawer, an agent's thread, a card's chat) one small line now says who the line goes to and whether
  anything wakes them: `Goes to ORCH · listening`, `Goes to AGENT-2 · not listening: it reads this when its session next runs` (amber),
  `Goes to AGENT-1 · 2 sessions: both may answer` (amber), `Goes to everyone listening (4). No one owns the answer.`, and while a name
  is being typed, `Names: AGENT-1, AGENT-2 · Tab takes the first`. A name nobody has is stopped, not sent: `No one named AGENT-33. Did
  you mean AGENT-3? Tab uses it.`; a name alone gets `Add what to tell AGENT-2 after the name.`; and when the board does not answer,
  `Not sent: the board did not answer. Your text is still here; send again.` The box used to be cleared before the board answered, so a
  refused send lost what you typed; now the text stays until the send is taken. `/api/chat` carries `names` (who a line can reach).
  The words and layout are AGENT-2's design, `docs/chat-words-design.md`; fix F8 of `docs/conversation-reliability-analysis.md`.

### An offline install path for a locked-down PC (Nov 8)
- The README's two install commands both reach PyPI for build tools the first time: pipx upgrades its own pip before it looks at the
  package (so `pipx install agentboard.whl` fails offline too), and `pip install .` downloads setuptools for its isolated build. On a work
  PC with no package index neither works. The README now has an "Offline" paragraph: build the pure-Python wheel once on any machine
  (`python3 -m pip wheel --no-deps -w dist .`), then `python3 -m venv` + `pip install --no-index <wheel>` on the offline one. The wheel is to
  be attached to every tagged release from here on (release checklist: `rm -rf build && python3 -m pip wheel --no-deps -w dist .`, upload
  `dist/agentboard-<version>-py3-none-any.whl`). Found by the overnight clean room (`qa-offline-install-needs-index`).

### A line to a name nobody has is said so (Nov 7)
- `chat send --to AGENT-33` (or `Agent 3`, or `agent3 ` with a stray space) was accepted without a word, and the sender thought it
  was sent (`tests/chat_repro.py` R6). Known names are ORCH, the owner, every card holder, every chat sender and every listener, any
  case. A line to any other name still posts (a new session may not have spoken yet) but is marked: the terminal prints "nobody named
  AGENT-33 has spoken or is listening; did you mean AGENT-3?", the board shows a "no such name yet" chip on the line with the same
  words in its tooltip, and the API returns `to_unknown` and `closest`. Fix F5 of `docs/conversation-reliability-analysis.md`.

### The masker's wall-clock tests measure the code, not the scheduler (Nov 7)
- `test_redact_dos.py` and `test_redact_fullwidth.py` asserted a megabyte of hostile text is masked in under 2 s (3 s fullwidth); linear work takes 0.05 s and the quadratic bug took minutes, yet the pair failed four times on Nov 7 on green code whenever two test suites shared a laptop at load 15 to 20. `tests/timing.py` now scales each limit by a same-moment linear baseline (300 `str.translate` passes over a megabyte, 0.25 s idle), tries a slow run up to three times and keeps the best, and never stretches a limit past 30 s. Quadratic work still fails every try. Inputs, caps and content checks are unchanged; two full suites run at once at load 19 were both exactly green.

### Messages to agents get a reply: listeners, receipts, a Stop hook and a nudge through ORCH (Nov 7, 64e2bca)
- A line typed to an agent used to sit in its inbox until something woke the session. Now every prompt tells a session to keep `agentboard chat inbox --name X --wait 3600` running between cards, the board lists who does (`.agentboard/chat-listeners.json`, by pid), and each line you send one agent carries a receipt in the ORCH drawer, the agent's thread and the card panel: **delivered** (in its inbox), **read** (its wait printed it), **answered** (it wrote back). After a minute unread the line says whether the agent is listening and, when it is not, offers **Nudge via ORCH**: the board asks ORCH, in its own thread, to message that session. `agentboard hooks install` now adds a second hook, Stop, that tells a session about to go quiet with an unread line from you (or no wait running) before it does, once.

### An unknown command gets one line saying a plugin's command is not available here (Nov 7, 63dbf9b)
- `agentboard texts-pending` from a plain shell said only "invalid choice". When the word is no core command and plugins are off or locked, the CLI adds one line to stderr: plugins are off (and why), so a command a plugin adds is not available here; run it from the board's shell, with its environment.

### An answer to the owner is never refused by the agent-chat switch (Nov 7)
- With agent chat off, `chat send` refused a threaded reply (`--reply-to`), a `--topic help` line, a `--detail`, a two-line answer and a
  proposal even when the line was for the owner, and a line over 300 characters was refused with "put the rest in --detail", which was
  refused too. The agent saw an error and answered in its terminal (loss path 1 of `docs/conversation-reliability-analysis.md`, repro R10).
  Now a line addressed to the owner, or to no one (the owner's thread), is never agent-to-agent talk, whatever its topic, detail or reply,
  and is never refused for its length: over the limit it is cut at a word, ends in an ellipsis, and the rest goes to the top of the detail.
- Still behind the switch: a line to an agent, ORCH or `all`, a heads-up about files, and an unaddressed reply to another agent's line.
  A long line to an agent is still refused. The refusal, the switch-off notice, `chat agents status` and the README say so.

### Two sessions under one name are two listeners, not one (Nov 7)
- The listener file kept one entry per name, so two sessions named alike overwrote each other: one line to the name woke both and
  both answered, and when the shorter-lived one ended the board said nobody was listening while the other still was, and offered a
  Nudge for it (`tests/chat_repro.py` R4a, R4b). Now each process is its own entry under the name (an older file still reads), a
  session removes only its own, "listening" holds while any is left, and the board shows an amber "N sessions" chip on the name in
  the thread head and under your line's receipt. A second wait starting under a live name is told so in its terminal (not in the chat: a
  line to the name would wake both waits). The Stop hook no longer counts one of the board's own notices as an unanswered owner line.
  Fix F4 of `docs/conversation-reliability-analysis.md`.

### Receipts in two steps: delivered when printed, seen when the session acts (Nov 7)
- `chat inbox --wait` advanced the agent's cursor the moment it printed, so a line printed to a session that had died, or never read
  its output, counted as read and never came back; the panel said "read" for a line no model saw (`tests/chat_repro.py` R2). Now
  printing records DELIVERED (the seq and the time, `chat-delivered.json`), and the cursor (SEEN) moves only when that name next does
  anything on the board (any command with `--name`, `agentboard me`, or another inbox read). A delivered line not confirmed within 5
  minutes is shown again by the next `chat inbox`, with one line saying so. The Stop hook tells a session that printed a line and did
  nothing to answer it. The chat panel's receipt reads sent / delivered / seen / answered; "sent" carries the 60 s nobody-is-listening
  warning and the Nudge, "delivered" turns amber after 5 minutes unseen. Fix F3 of `docs/conversation-reliability-analysis.md`.

### `chat inbox` reads oldest-first and loses nothing (Nov 7)
- `chat inbox` showed the newest 50 unread lines and moved the cursor past all of them: with 60 unread, the 10 oldest were never shown
  (`tests/chat_repro.py` R8). It now shows the oldest `--limit` (default 50; `0` for all), moves the cursor only to the last line it
  showed, and ends with "(N more unread, from #seq: run it again)". The idle drafter and the autopilot read everything unread as
  before. Together with the locked, forward-only cursor write (`cursors.py`) this is fix F2 of `docs/conversation-reliability-analysis.md`:
  R7 loses 0 of 160 concurrent cursor updates, R8 loses 0 of 60 lines; a test runs twelve real processes reading one line at once.

### The chat repro script no longer reads the real board for one probe (Nov 7)
- `tests/chat_repro.py` ran its R11 probe (`hook stop` with no board in the environment) with `AGENTBOARD_DIR` set to an empty string,
  which `find_dir` treats as unset: run from the repo root as documented, the probe walked up to the repo's own `.agentboard/` and read
  the real chat, cursors and listeners, against the script's promise and the analysis doc's "no board in env -> does nothing". Every
  process the script starts now runs from the temp folder, the script refuses to start under a real board, and the doc says what R11
  measures. Found by the Nov 7 merge review (`rev1107-repro-reads-live-board`).

### The autopilot no longer marks a line read or answered for a session that never saw it (Nov 7)
- With `[chat] autopilot` on, the board drafting a reply for an idle agent moved that agent's chat cursor to the newest line and
  posted with `reply_to`, so the panel showed read and answered, and the Stop hook saw nothing unread, for a line the agent's
  session never saw. The board now keeps its own marker per agent (`seen` in `chat-autopilot.json`) and never touches the session's
  cursor; the panel counts only a real line (not one marked auto) as an answer. Off by default; found by the Nov 7 merge review
  (`rev1107-autopilot-marks-read`).

### One chat cursor per name, whatever the case, and the Stop hook reads it too (Nov 7)
- `chat-cursors.json` (where each session got to in the chat) was read and written by four modules, each by the exact-case name
  and none under a lock. `agentboard me --name AGENT-4` plus `chat inbox --name agent-4` left the cursor under one spelling while
  the Stop hook looked it up by the other, so every owner line to that name in the 500-line log (lines to an earlier session with the
  reused name included) blocked the stop at every turn end. Now `cursors.py` is the one place: the key is the name lower-cased, a
  write takes a file lock and only moves forward, the file is replaced atomically, and an older mixed-case file reads as the highest
  seq per name. The CLI (`chat inbox`, `chat idle`, `answer --wait`), the idle drafter, the receipts and the Stop hook all go through
  it. Found by the Nov 7 merge review (`rev1107-stophook-case`); the repro's R7 (twenty readers waking on one line) loses no update.

### The listener file survives twenty waits waking at once (Nov 7)
- `chat-listeners.json` (who has a `chat inbox --wait` or `answer --wait` running) was read, changed and written back with no lock
  and a plain write: a line to `all` woke every wait at the same instant, each exited and re-registered, and most registrations
  vanished (20 threads registering at once left 0 of 20), so the panel said agents were not listening and offered Nudge for sessions
  whose wait was running; a reader could also catch half a file. Register and unregister now run under one file lock
  (`.agentboard/.listeners.lock`) and the file is replaced atomically, with no `.bak`. Found by the Nov 7 merge review
  (`rev1107-listeners-race`); tests run twenty threads and twelve processes at once.

### `agentboard doctor` loads the plugins the server would, and lets each add its own checks (Nov 7)
- On the home Mac a plugin crashed on load for hours (data files missing from the installed package) and every test passed, because nothing checked the installed copy the way the server uses it. With plugins ON, doctor now loads them exactly as `agentboard serve` does and prints `FAIL plugin <name> failed to load: <ErrorClass>` (the class only, never the message) or `PASS plugin <name> loads`. With plugins off or locked it still imports nothing.
- A plugin can register read-only checks of its own setup: `api.add_doctor(fn)`, `fn(board_dir) -> [(level, name, text)]`. Doctor prints them as `<plugin>:<name>` lines; the text is made one visible line, secret-masked and cut, a bad shape or an exception becomes one FAIL naming the class, and at most 40 lines per plugin are shown. The home plugin uses it for its env file, data files, server keys and config sections.

### The audit page and SECURITY.md say what was decided (Nov 7)
- The login fix (`sec-local-token`) is no longer "held": the owner decided not to merge it, so the board has no login and the docs now say that plainly (the branch is parked, not deleted). The page also stops listing the two secret-masking cards as open; both are done. Documentation only.

### Fullwidth look-alikes no longer hide a key from the masker (Nov 7)
- A fullwidth underscore in a `ghp_` key, a fullwidth `=` after `api_key`, a fullwidth `:` after `token`, or fullwidth letters in an `AKIA` key passed through unmasked, for the same reason as the dashes: the patterns want ASCII, and whatever normalises the text later (the reply filter, a search) would show it whole. The masker now also folds the fullwidth block (U+FF01 to U+FF5E) to ASCII on the copy it matches on, one for one, and masks the original by the matched span. Japanese and Chinese punctuation (`，` `：` `（）` `！` `？`), fullwidth words and prices are never rewritten. As with dashes, inside a masked match the part that is kept (an assignment's name) reads in ASCII.
- Not covered: the other compatibility forms a normaliser turns into ASCII (mathematical bold letters, circled digits, superscripts: about 1,000 characters). A key written in them is not a working key.

### A look-alike dash no longer hides a key from the masker (Nov 7)
- `sk` + a Unicode hyphen (U+2010, U+2011, an en or em dash, the minus sign U+2212, a fullwidth hyphen) + the key passed through unmasked, so the board kept it in cards, reports, chat and the Terminal tab, and anything that later turns those dashes into plain ones (the reply filter) would show it whole. The masker now folds every Unicode dash and minus sign to `-` on the copy it matches on, one for one, and masks the original by the matched span: only secrets change, and `pages 3-5` with an en dash, a date written with en dashes or `sk-learn` stay exactly as written. One side effect, as with invisible characters: inside a masked match, the part that is kept (an assignment's name) reads with plain hyphens.
- Not covered, on its own card: other look-alikes (fullwidth underscore, equals sign, colon and letters).

### The masker no longer erases ordinary words (Nov 7)
- Masking happens on the way in, so what it removes is gone for good. `Authorization: Bearer|Basic|Token` masked any word of 10+ characters after it (`unauthorised-deletion` vanished from a review): it now masks only values that look generated (a letter and a digit, base64 padding, or a long mixed-case token). The `sk-` shape erased the tail of kebab-case words (`task-queue-implementation-notes` became `ta[redacted api-key]`, likewise `risk-`, `disk-`, `ask-`): what follows `sk-` must now look like a key. A `-----BEGIN … PRIVATE KEY-----` with no end line used to swallow the rest of the text: it now takes the block's base64 lines and stops where the prose starts (a whole block, even an encrypted one, still goes to its end line). A hex string after `monkey:` is no longer read as after `key:`.
- A key glued to other letters (`xAKIA…`) is still masked: no boundary rule is an escape hatch.

### Invisible characters no longer hide a key from the masker (Nov 7)
- `sk-` + a zero-width space + the key, or `Authorization:` + a zero-width space + ` Bearer …`, passed through unmasked (as did a bidi override or a soft hyphen inside a pasted key). The masker now matches on a copy without control, format, private-use and filler characters and masks the original by the matched span, so only secrets change: a ZWJ in an emoji, a ZWNJ in Persian or a soft hyphen in ordinary text is stored exactly as written. A text with thousands of invisible characters is cleaned of them instead of mapped (it is not prose).

### `agentboard start` masks secrets too (Nov 7)
- `start`, the way every agent begins a card, skipped the masker: a key in its title or description was stored whole, and because a card id is a slug of the title the lower-cased key also landed in the id, in report file names and in lookups. The title, description (now capped like `add`) and agent name are masked before the id is made.
- Found by the same sweep: a chat message's `propose` text, its `files` and its sender, the SendMessage mirror (which cut the first line to 300 characters before masking and could leave half a key), and the history lines that quote an older card's title ("Title changed from …", "Blocked by …").
- A test runs every write path (add, subtask, start, claim, edit, update, ask, review, chat, the mirror, the CLI) with key-shaped values and looks at every byte the board keeps: `tasks.json`, the `.bak`, the snapshots and the reports.

### The masker knows more shapes (Nov 7)
- Now also masked: Stripe `sk_live_`/`rk_live_`/`whsec_`, Google `AIza…` (also as `?key=` in a URL), Slack webhook URLs, npm and SendGrid tokens, the password in `scheme://user:password@host` (a documented `user:password@host` placeholder is left), `aws_secret_access_key = …`, a bare `Bearer …`, and `key`, `auth`, `token`, `credentials` assignments or URL parameters whose value looks generated (20+ characters, a letter and a digit, not a lower-case identifier). The Terminal tab masks them too. Short passwords such as `hunter2` are not caught: nothing tells them from ordinary text.
- The repo guard (`tests/publiccheck.py`) learned the prefix-shaped ones.

### The masker can no longer freeze the board (Nov 7)
- One POST of 198 KB of `eyJeyJeyJ…` froze the server for 9.9 s (400 KB took 44 s, 1 MB about four minutes): the token-shaped pattern for a JWT restarted at every `eyJ` inside a long run, and the masker ran on whole bodies before they were cut to their caps. The pattern is now linear, the masker looks at no more than twice a field's cap, and the Terminal tab cuts each line the same way. A real JWT is still found. A regression test times every shape at 1 MB.

### Round-2 fixes: file reads under the lock, doctor checks the running server and the plugins (Nov 7)
- **A copied `config.toml` can no longer pull files from outside the project into card prompts when `AGENTBOARD_LOCKDOWN` is set**: the `markdown` and `file-tail` providers and `[prompt] template_file` refuse a path that resolves (symlinks followed) outside the project folder; inside it they work as before. `agentboard doctor` lists the files config reads (names only) and warns about any outside the project.
- **`agentboard doctor` checks the lock against the running server**, not only its own shell: `agentboard serve` writes `server-<pid>.json` (0600) in the board folder when it starts (lock on or off, plugin gate, port, plugin names; no environment value) and removes it on a normal exit. A server started without the lock now shows a WARN even when the shell running doctor has it.
- **`agentboard doctor` has a plugins line**: PASS when no plugin can load (and which are installed), WARN naming the code that runs when `AGENTBOARD_PLUGINS=1`. Nothing is loaded to find out.

### The Nov 7 security audit: verdict, work-laptop checklist, SECURITY.md (Nov 7)
- **`docs/security-audit-2026-11-07.md`** is the one-page verdict of the five overnight audits (network, install, the page and API, data and secrets, a red-team re-check): safe to run on a managed work laptop with `AGENTBOARD_LOCKDOWN=1` set, what is still open (the board has no login; the owner decided not to merge the key-cookie lock), what was re-checked by hand and what was not, and a checklist of what to install, set, check and not enable.
- **`SECURITY.md`** now says what the master lock refuses, how to check a machine (`agentboard doctor` and the one-line commands), the known gaps, and what changed since Oct 24; the README's "On a work laptop" section matches.

### Doctor: calmer about an empty folder, and it spots a stale install (Nov 7)
- **An empty board folder** no longer prints "0 of 0 entries … can be read by any user" as a FAIL: it says the folder is empty. A folder others can list but whose files are private now says exactly that (still a FAIL, as before) instead of counting zero readable entries; a symlink's own mode is ignored.
- **New line `install`** (a WARN, so the exit status rules are unchanged): a file the installed copy carries but the source it was installed from no longer has (texts.py and sms.py once lingered in site-packages from a stale build folder) is named, with the fix `pipx uninstall agentboard; pipx install <repo>`. It reads two folders, runs nothing, and says INFO when it cannot tell where the copy came from.

### Secrets are masked on the way in (Nov 7)
- A key an agent echoes, a token in a command it ran, a private key in a review body is now stored as `[redacted …]`. Before, it was copied verbatim into `tasks.json`, the `.bak`, every backup, the card's report, the page and the chat. Reports mask older cards again when built.
- Only unmistakable secrets: prefixed cloud and API keys, tokens, JWTs, private-key blocks, `Authorization:` values, `api_key = "…"`, a long hex string after key/token/secret. A commit hash, an id, a path, code or a phone number is never touched, and what you type yourself is left alone. `[redact]` in `config.toml`: `enabled = false`, `phones = true`, `extra = [...]`.
- **The Terminal tab and `/api/transcript` mask them too**: a command shown without a description, a URL with a key, a line you typed, the assistant's text, an error line and a question's option chips. Ordinary lines read exactly as before; the session's own `.jsonl` is never rewritten. Same `[redact]` setting.
- `agentboard redact` lists what the board already holds (where and what kind, never the value); `--apply` masks it after a snapshot.

### Lookup (Nov 7)
- **`agentboard lookup "words"`**: a read-only search of done and archived cards and the board's reports; the best few matches with source, date and a short snippet (`--in`, `--limit`, `--list-sources`, `--json`). Writes nothing, opens no socket, starts no program; snippets are cleaned and printed as quoted data.
- **`api.add_source(name, help, search)`** in the plugin hook: a plugin can add a source to `lookup`. With plugins off, or under `AGENTBOARD_LOCKDOWN`, there are none. Core code never opens a file named in `config.toml`.
- `agentboard doctor` shows how many notes files a board lists under `[knowledge] files` (file names only, never the folder).

### The text features moved out of agentboard (Nov 7)
- **Pulling your texts into cards (the command, the Pull texts button, the once-a-minute timer) and the inbound-SMS webhook are no longer part of agentboard.** They live in a separate package kept outside this repository, loaded through the plugin hook only on a machine that switches it on. agentboard now contains no Twilio code, no texting code and no timer; `src/agentboard` has a test that fails if that changes, and another that fails if a real-looking phone number or account SID is committed.
- **Cards made from a text keep their guard**: such a card (its `source` says `text`) still reaches an agent as quoted words, never as instructions, in prompts, `list`, `recall` and `report`.
- Earlier commits on GitHub still contain the removed code; history was not rewritten.

### The version string (Nov 7)
- `agentboard --version` (and `agentboard doctor`) said 0.3.0 while the package was 0.3.1: `__init__.py` was not bumped with `pyproject.toml`. They agree now, and `tests/test_version.py` fails if `pyproject.toml`, `__init__.py` or the README's `--version` line drift apart again.

### A guard for the public repo (Nov 7)
- `tests/publiccheck.py` (and a test that runs it) fails when a tracked file holds a secret-shaped string, a phone number that is not fictional, an email outside a small allow-list, a real account's home path, or one of your own private words (kept in `~/.config/agentboard/private-words.txt`, outside the repo). It prints where, never what. Found and fixed: one absolute home path in a doc.

### Board files are private (Nov 7)
- Only `tasks.json`, its `.bak` and the snapshots were mode 0600; reports (every review body), `config.toml` (phone numbers), `sessions.json`, the chat files, run logs and the folders were readable by any other account, and a Mac home folder is not private. Now the command line and `serve` run with umask 077, `serve` tightens what is already there, and the daily `sync_dir` copy is private too.
- Programs the board starts for you (`claude -p` runs, provider commands) and files meant for others (the project's `.gitignore`, `.claude/settings.json`, `summary --html`) keep your umask. `AGENTBOARD_UMASK=022` turns it off for a shared folder.

### A plugin hook (Nov 7)
- **One generic extension point.** A separate package can add CLI commands, API routes under its own `/api/x/<name>/`, a state block on the board's poll, a background thread, and a page script (its style rides in it: the page's Content-Security-Policy allows no stylesheet files). It loads only when this machine says `AGENTBOARD_PLUGINS=1`; `AGENTBOARD_NO_PLUGINS=1` and `AGENTBOARD_LOCKDOWN=1` both stop it, even after the board started. With none allowed nothing is looked up, imported or shown, and the board is the board it was. `agentboard plugins` says which.
- **The page's side is one small object, `window.AB`:** a header slot, a Settings slot, a card-chip hook, the poll's plugin state, and `api`/`toast`/`esc`/`ago`. A plugin that throws is caught there and cannot break the page.

### POST guards: exact JSON type, Sec-Fetch-Site (Nov 7)
- A POST's media type must be exactly `application/json` (parameters allowed); a CORS-simple type that merely contains the words (`text/plain;charset=application/json`) gets 415, so a cross-site POST now needs a preflight the server never answers. A browser's `Sec-Fetch-Site` other than `same-origin`/`none` gets 403. curl, the CLI and the tests send neither header and are unchanged.

### HTTP limits: a stalled client is dropped, card text has caps (Nov 7)
- The board's request handler has a 15 s socket timeout: a client that declares a body and never sends it no longer pins a server thread.
- A title is refused past 200 characters (put the rest in the description); description (20,000), status line / ask / review one-liners (1,000), markdown body (60,000) and a send-back note (2,000) are cut at their cap. One huge field can no longer slow every client's 1 Hz poll.

### Building a prompt is refused for a cross-site GET (Nov 7)
- `GET /api/prompt` and `/api/orch-prompt` run the card's context providers (a configured shell command, an http GET), so a browser that marks the request `Sec-Fetch-Site: cross-site` (an `<img>` on another page) gets 403 and nothing runs. The Copy prompt button, the CLI and curl are unchanged. README now says not to wrap `{arg}`/`{title}` in quotes in a command provider.

### The transcript route opens the path it checked (Nov 7)
- `transcript.read()` resolves a registered path once (`~` expanded, symlinks followed) and opens that same Path; before, the check used the resolved path and `open()` the raw string, so a `~` path looked for a literal `~` folder under the working directory. Harmless then, closed now, with tests for `~`, relative, outside and symlinked paths.

### The card panel has tabs: Summary, Conversation, Terminal (Nov 6)
- **Every tab of a held card wears the compact head** the side panel had (avatar, agent name, its state and last update, the card it is on), not the card's title block, so the content gets the room. The title form still takes its place while you edit the title (`e`); a subtask or an unheld card keeps the title block.
- **Three tabs under the open card's title**, for a card an agent holds: **Summary** is the card as before; **Conversation** is that agent's thread (your exchange since its current card) with a composer; **Terminal** is its session. One click, or `t` to cycle (on the `?` list). The agent pill still works, as a shortcut to Conversation.
- **Conversation shows the question the terminal asked last**: Claude Code's own question prompt with its options as chips, or the agent's last line when it ends in a question mark. A chip or a typed line goes to the agent as a board message, read at its next wait; the block says to answer in its window to unblock it this minute.
- **A dot on Conversation** when the agent wrote to you since you last looked, its card needs your input, or its terminal asked something you have not seen. It clears when you look. No sound, no popup.
- **Where a card opens**: needs input on Conversation; review or done on Summary; otherwise the tab you used last (remembered in this browser).
- **Terminal keeps your place**: it follows the newest line until you scroll up, then shows **Jump to latest**; a redraw never moves you, and the minute tick never redraws Conversation or Terminal.

### ORCH's terminal, and threads that read as the current conversation (Nov 6)
- **The ORCH drawer has Conversation and Terminal tabs**, the same read-only well the agents' panels have, for ORCH's own session. ORCH's prompt now says `agentboard me --name ORCH` once, so the board knows which session it is.
- **A thread is what passed between you and that one name**: your lines to it, its lines to you. Its status lines, its mirrored messages to other sessions and lines to everyone stay out; the ORCH drawer reads the same way.
- **It starts at the card the agent is on now** (the last 24 h when it holds none, and for ORCH); older lines wait behind one **Show earlier · n** link at the top.
- Addressing the owner by the words a prompt uses for an unnamed one (`--to "the user"`, `you`) counts as addressing them, so an agent's answer posts with the agents-talk switch off on an unnamed board too.

### The Terminal tab: the raw session, one click away (Nov 6)
- **An agent's panel has two tabs**: Conversation (as before) and **Terminal**, the session's transcript drawn in a dark mono well as it scrolls: what you typed, the agent's text, each tool call as one muted line, a tool error in red, with the time of each. It polls the board every 3 s only while the tab is showing, redraws only when something changed, and follows the end unless you scrolled up.
- **The foot says how fresh it is**: last line n ago (amber when quiet), the file and its size, and that it is read only. A session that has not registered a transcript yet gets a plain line saying so and why.
- **Read only in this version**: the composer hides on the Terminal tab; nothing goes into the session from here. Typing into it and starting sessions from the board come later.

### Talk to one agent, outside any card (Nov 6)
- **A thread per agent.** Press the agent's pill at the top of an open card, or an agent's name at the head of its lane on By agent, and a panel opens on the right with that agent's conversation: what it said on the board, what you said to it, and a composer. The chip on a card keeps its job (the filter).
- **The head says where it is**: state (working, ask, review, quiet, idle), last update, the card it is on with a link, and whether that card waits on you or is up for review.
- **Its open question sits in the thread** with the card's own answer chips and an Open the card button; the answer lands on the card as before.
- **A message there wakes the agent.** `agentboard answer <id> --wait` now also returns when you send the card's agent a message on the board, prints it (with "message from … on the board" on stderr, and how to answer), and marks it read; a card reply still comes first. Every card prompt and `agentboard instructions` say so, and tell the agent to answer with `chat send … --to <you>`.

### The session's transcript, registered and served read only (Nov 6)
- **`claim` and `start` record where the session's transcript is**: found from `$CLAUDE_CODE_SESSION_ID` under `~/.claude/projects`, or given with `--transcript <path>` / `$AGENTBOARD_TRANSCRIPT`; kept in `.agentboard/sessions.json` against the session, newest per name.
- **`/api/transcript?agent=<name>`** tails that file (the last 1.5 MB) and returns the last 300 conversation lines: what the person typed, the agent's text, each tool call as one muted line (`Read src/x.py`, `Bash Run the tests`), a tool error's first line. Thinking, tool output and subagent lines never show. Read only, 127.0.0.1 only, and it fails soft: no file, no registration or a path outside `~/.claude/projects` gives no lines and says why.
- Groundwork for the Terminal tab; no UI in this change.

### The ORCH drawer: talk to ORCH from the Todo column (Nov 6)
- **The Chat button left the header.** An **ORCH** button sits in the Todo column's head (Board, By agent and Load alike); press it and a drawer slides out from the left over Todo. It is the chat, read as a conversation with ORCH: what ORCH said, what you said to ORCH or to everyone, the board's notices. Typing there addresses ORCH; `@AGENT-2 …` still reaches someone else. The unread count rides the button.
- **The drawer's head is the back arrow and ORCH, nothing else.** The whole channel (agents' own lines) and the agents-talk setting stay in the CLI: `agentboard chat tail`, `agentboard chat agents on`. Approvals and details still show on the lines the drawer carries.
- **ORCH answers you there.** Addressing the board's owner is no longer counted as agent-to-agent talk, so `agentboard chat send "…" --name ORCH --to Troy` posts with the switch off. The ORCH prompt now tells it to keep `agentboard chat inbox --name ORCH --wait 3600` running and what to do with "add a card", "assign", "move to Later", "what is everyone doing" and a message for a busy agent.
- **An empty board says how to start.** The centre of a board with no cards shows three steps: start Claude, `/rename ORCH`, press **Copy prompt** and paste it there. The ORCH prompt button left the header; Copy prompt is in that third step and in the drawer's head, for re-pasting after a `/clear`.
- The board, its cards and the Done panel are unchanged.

### "Needs your input" clears once the agent has your answer (Nov 4)
- **The red state ends at the first of two things**: the agent reads your reply (`agentboard answer`), or it next reports on the card, which now includes an update on any of its subtasks. Before, only an update on the card itself cleared it, and an agent's progress arrives as subtask updates, so a question asked on the card stayed red (card, header count, By agent lane, Load, right panel) for as long as the agent kept working, long after it had read "Go ahead".
- **Until then nothing changes**: your reply alone leaves it red with "You replied Go ahead, AGENT-1 reads it next", and an agent that neither reads nor reports keeps it red. A state note ("Restored by you") never ends a question by being read. A question asked on a subtask clears as before, when that subtask updates, and now also when its answer is read.
- **The card's history says why**: "Reply read", or the subtask's note when its update ended the question, so the panel's Latest no longer says "Needs input" after the red is gone.

### The finished card reads in one glance (Nov 4)
- **A Done card's panel is laid out, not dumped**: the agent's sentence first, large, with chips that answer the glance (Next: who, the test count it found, commits · files), then **Changed / Checked / Next**, then the diagram, then the subtasks as ticks, your decisions as question → answer ("Go ahead"), where it changed as one bar from git, and the card's path as a strip of states with times. The description, the full note, the activity log and the prompt sit under a closed Details.
- **Agents write a short shape on review** (`## Changed`, `## Checked`, `## Next`, an optional ```` ```flow ```` block); every card prompt and `agentboard instructions` show it. A card without the shape still renders from what the board has: the sentence, the note (faded only where it is cut off), the ticks, the tests it can find, git.
- **```flow draws a small diagram with no library and no outside request**: `A -> B -> C` is boxes and arrows, `label: 12` is a bar; escaped inline SVG in the page's own colours, so it follows light and dark. Works in any body and in reports.
- **Marking done keeps the body.** It used to be wiped on done (and the panel had nothing to show); now it stays, and reopening keeps it until the agent reports again.
- `/api/task` carries `sections`, `checks` and (for done cards) a cached `git` summary; the task list stays light.

### The agent hears when you close its card (Nov 4)
- **Closing a held card tells its agent.** Mark done (the button, `d`, a drag, a multi-select or `agentboard done`) leaves a reply on the card in the same slot a typed answer uses: "Done by Troy: the card is closed, you are free to go idle or take the next card." An agent waiting with `agentboard answer <id> --wait` wakes with it (who and when on stderr); one that is not waiting finds it, unread, with `answer`.
- **The other changes that left an agent guessing say so the same way**: undo of a close ("Reopened by Troy: the card is back in review, not closed"), a drag back to Doing, send back (now opens with the state, then your note), a move out of Doing ("no longer yours, stop work on it"), undo of a move or a removal ("back in Doing and yours again"), and a removal (`answer --wait` prints a Removed line and exits; a wrong id still errors).
- **Nothing new for you.** These replies are tagged as state notes: the board never shows them as "You replied", never hides an ask's quick chips, and there is no popup, sound or config.
- **Agents now wait after `review`**, not only after `ask`: the card, parent and subtask prompts and `agentboard instructions` say to start `answer <id> --wait --timeout 3600` in the background and end the turn.

### Gorgeous and satisfying: Lively, Chimes, more ambience, From the future (Nov 4)
Every pick here is a setting that defaults to the current look, and every new sound starts off. Before/after shots: `docs/gorgeous-2026-11-04/`.
- **Settings > Look > Lively** (off): the small moments move. A card you moved settles with a ring of the column's colour once it is drawn where you sent it (after its glide, never under it); a count rolls to its new number; a finished subtask ticks itself in, its check drawing; a changed % pops and its bar flashes once; an empty column breathes and its line arrives when the column empties; the header's counts bump; the toast springs up; the open card's sections step in; the drop line pulses and the column under a drag lights in its colour (red for another agent's lane). Reduced motion turns all of it off.
- **Settings > Look > From the future** (Off / Subtle / Full; off, one click back): a HUD from a game set some years on. *Subtle* is a still look: holographic panels (a tint of the page's info colour, a lit edge, corner brackets), a scanline veil at 8%, monospace readouts for the column heads, a glow on the lit tab and the bars. *Full* adds a light that travels the live columns' top edge, a header readout from the board's own poll (the clock, who works, who waits, the link; from 1500px wide, the first thing to give way), the far glows following the pointer, a tilt on a hovered card, a boot sequence at the foot of the page on a page load (no pointer taken; a key or a click ends it) and a scan sweep on a view change. Nothing is hidden, nothing new polls the server, every movement is a transform or a 2px strip, and reduced motion stops all of it while keeping the still look. Light and dark both carry it; Calm cards still wins on the cards.
- **Settings > Sound > Chimes** (off): small sounds for the small moments. A tick per finished subtask in its agent's voice (after the done cue, as its answer), a rising note at 25, 50 and 75%, a settle when a column empties, a tiny tick when a count changes, a blip when the toast arrives. One per render, the most telling first; nothing on a first render, on your own move or when a cue played in the same breath. All under the quietest cue, through the shared buses.
- **Settings > Ambience > Deep space and Tide** (off): two more layers on the bed. Deep space is a low drone, a thin shimmer and a distant ping now and then; Tide is slow swells that build, draw back and wander from side to side.
- **Settings > Effects > Duck the bed** (off): the bed and every ambient layer dip for a moment under each cue, so a cue stands clear of them; the level is how deep the dip goes. The cues, Touch, the volume and the limiter are untouched.
- **Settings > Effects > Future sound** (off, silent while the look is off): a sweep and a rising chord as the page boots (with the first click or key), a scan blip on a view change, a holographic shhk as a card opens and the reverse as it closes.
- **Fixed**: a page opened straight at `#/hud` or at a card's hash threw on its first render (a variable declared after it), which also left Load's Agents column empty until a later tick.
- **Settings and the shortcuts sheet have a close button**: on a phone the only way out was Esc or a tap on the dim edge.
- **`1`, `2` and `3` open Board, By agent and Needs you** (Load while that was the third view), the same ring `[` and `]` walk, by number. Not while typing, and not in the pop-out Load window (it has no board). On the `?` list.

### Drag and drop on By agent and Load (Nov 4)
- **Cards drag on every view**, with Board's own lift, drop line, sounds, glide and Undo toast (one set of handlers now): By agent's Todo column and agent lanes, Load's Todo column and Doing pane. A lane is Doing.
- **A drop never changes who holds a card.** Another agent's lane shows a red outline and no insertion line, and the drop springs back with a toast ("stays with AGENT-1: drop it in its own lane, or on Todo"). A Todo card with no agent dropped on a lane goes to Doing under Unassigned, and the toast says so. Reordering inside a lane works.
- There is no Done target on By agent or Load (Board only); `d` still marks the card under the pointer done.

### Calm cards, a Look switch (Nov 4)
- **Settings > Look > Calm cards**, off until you choose it: a Doing or lane card is a plain card (the agent's stripe and the status word stay) with no orange fill, border or glow while it runs. An ask, review or abandoned card keeps its coloured edge, since that one carries meaning. The current look is the default; the switch is there to compare the two in one click (the card-colours question).

### Polls no longer steal, reset or wipe; nothing hides without a way to read it (Nov 4)
- **Typing in a reply box no longer freezes the rest of the page**: only the board's redraw waits for you; the status pill, the asks, the open card and the chat keep running.
- **The open card is not rebuilt under your hand**: a focused control inside it (an armed "Click again to delete", a "copied" label, the subtask or blocker field, a picker) and any text you have selected hold the once-a-minute rebuild, and a change arriving while a field is in use waits for the next poll. The minute tick on the board waits while text is selected too.
- **The Later box is built once**: what you typed, the caret and a composition in progress survive the list below it updating. **The drawer and its count show everything parked** whatever the filter says (they said "Nothing parked" under an agent filter).
- **Hovering an agent pill no longer flickers** on every changed poll: the highlight is put back after a redraw.
- **Clipped text carries its full text as a tooltip**: the card's time and stale text, the queued time, a subtask row, the toast, a chat card chip, the agent pill on Load.
- **The Report chip shows whenever a report exists**, not only on ask, review and done cards. **Done folds back**: "Show N more" becomes "Show fewer".
- **By agent shows Doing cards that have no agent** in an Unassigned lane, last; they were shown on no view but the Board.

### Nothing hides under Load, nothing in the header moves (Nov 4)
- **The toast shows on Load** (it was drawn under the overlay, so "Moved… Undo" and its countdown were invisible there), and **the error strip too**: it floats under the header on every view, has an × to dismiss it, and no longer pushes the board down when it appears.
- **The header stays put.** Above the phone width it never wraps to a second line (the counts appearing or changing used to push the board and Load's top edge down), the counts shrink with an ellipsis before anything else gives, their numbers are tabular, the Later button fits three digits, and ORCH keeps its slot from the first paint instead of appearing a moment later.
- **The bulk bar floats** over the board's foot (and above Load): opening it no longer shrinks every column; the toast steps up over it.
- **Cards glide only when their column or order changed.** A card that merely shifted because the card above it grew (a reply box arriving, a note going) stays still, so a background poll moves nothing.
- **Load keeps each column's scroll** across closing and opening; the Done ribbon's week count no longer narrows the day bars when it gains a digit; a telemetry row on Load no longer lifts on hover like a card you could open.
- **Settings has a Look section** (Motion lives there, not under Sound), the Ambience heading says "plays with the ambient bed" (there is no AMB control any more), and **the gear shows a small badge while sound is off**, the only sign of it outside Settings.

### Every shortcut works on every view (Nov 4)
- **On Load the arrows and `j` / `k` walk the Todo column as well as Doing**, `←` / `→` cross between them, and **`Alt` + `←` / `→` move the card you are on between Todo and Doing** (there was no way to move a card to Todo from Load). The same on By agent: `Alt` + `←` takes a lane card to Todo, `→` brings a Todo card into Doing, `↑` / `↓` reorder within the column.
- **The arrows no longer crash** when the card under focus is not in the grid (a Later card, a chat chip, the board under Load): they start the walk instead.
- **A poll no longer steals keyboard focus**: on Load, focus stays on the card in the pane you were in instead of jumping to the board's copy underneath; on any view, focus on a control inside a card (Copy prompt, Later, Mark done, a name chip, a quick reply, a subtask row) comes back to that same control after a redraw.
- **The selection works on Load**: shift-click and `Shift` + `↑` / `↓` paint there too, the bulk bar floats above Load (and over the board's foot, so opening it no longer shrinks every column), and `Esc` clears the selection before it closes Load.
- **`Alt` + arrows never fire while you type** in a reply box (`Option` + `←` moves the cursor again). **`Esc` peels one layer at a time**: a field inside the open card loses focus first, a sheet over the card closes first, then the card, then the selection, then Load; `Esc` in the new-task field no longer closes the open card with it.
- **`m` and `s` work inside Settings** (a switch or a slider is not typing); `c` checks for an open sheet like `d` does, and a telemetry row on Load no longer counts as a card for either; the pop-out window keeps `?`, `e` and the arrows; opening a card closes Chat like it closes Later.
- The shortcuts sheet says what the handlers do (Space, `⌘` + `Enter`, the editor's keys, where `Alt` + arrows work) and a test keeps it so.

### Projects are gone (Nov 4)
- **Projects are removed entirely**: the coloured pill and dot on cards, the project filter, the panel's Project select, the bulk Assign, `agentboard project …`, `--project` on `add` and `start`, and the project routes. Cards are coloured by status and by agent only. A board file from before still loads; its project list is dropped on the next save and a card's old `project_id` is ignored.
- **The Done summary groups by agent** instead of by project (`/summary?agent=<name>`, `agentboard summary --agent`): one tile per agent on the work map, the mindmap by agent, "Unassigned" for a card with none.

### Load's telemetry is Board cards; the Board's Todo no longer fades on a pill hover (Nov 4)
- **The Agents column on Load**: each agent is a Board card, the same pill, type, spacing and colours as a Doing card, holding only what telemetry alone knows: the age and the agent's hour of load (the bar). The card's border and edge take the agent's state the Board's way (ask, review, abandoned, working). Nothing the Doing card beside it says is repeated: no big name, no state word, no status or ask text, no notes, no title, no %. Every agent shows, idle ones too (a quiet card with a dimmed bar); the idle fold, its toggle and its remembered collapse are gone. The Queue is the last card with its chart; the legend and the time axis sit in the column's foot. The whole of Load is in the Board's type now, no monospace.
- **Board: hovering an agent pill no longer fades the Todo column.** The hover lights that agent's cards and dims only *other agents'* cards; a card with no agent (all of Todo) stays as it is. It dimmed every card that was not that agent's, so the pointer crossing a pill faded Todo to near nothing. The "Show only AGENT-2" hint is now the page's own, above the pill, instead of the browser's tooltip under the pointer over the card's next line.

### Load sits on the Board's grid and follows the theme (Nov 3)
- **Load's three columns use the Board's own tracks**: Todo, Doing and the telemetry sit exactly where Board's Todo, Doing and Done sit (same left, right, top and bottom at every window width), so flipping Board ↔ Load moves nothing but the content. The telemetry is Done's width now and **re-flows by its own width**: under 760px the hour bar goes under the text and the AGENT LOAD title goes (the time axis says it); under 480px the state sits under the name and the type steps down. The column scrolls when the rows outgrow it.
- **Load follows the theme like Board and By agent.** It sits on the page's own background (dots and glows) instead of its black backdrop with blur, grid lines and scanlines; the Todo and Doing columns take the theme like the Board's; the telemetry panel is the Board's column panel and its text, lines and state colours come from the page's tokens, so the light theme gets a light Load. The dark theme looks as it did (it already mapped its status colours onto the HUD's neons).

### The shortcuts work on Load (Nov 3)
- **On Load the arrows and `j` / `k` walk the Doing cards, `Enter` opens one, and `c`, `d` and `u` act on the card you are on.** Only `[`, `]`, `m`, `s`, `c`, `d`, `u`, `f` and `h` did anything there before; the arrows, `j` / `k`, `?`, `l`, `a`, `e` and `n` were silent, because Load swallowed every other key.
- **`?` and `l` open the shortcut list and the Later list over Load, `e` edits the open card's title, `a` goes to By agent, and `n` closes Load to show the new-task field** (the field lives on the board). `Shift` + arrows (the selection bar) and `Alt` + arrows (moving a card between columns) stay off on Load, and the list now says so. The pop-out Load window keeps its short list: it has no board.
- **One `Esc` no longer closes a card and Load together**: it closes the card, and the next one closes Load. Typing in a reply box on Load fires none of these.

### Load has the Todo column; the telemetry stops repeating the cards (Nov 3)
- **Load draws the Todo column** left of Doing: the same column, cards and width as Board and By agent (one function draws all three), dark like the rest of Load. Its cards glide across on the switch like the Doing cards, Copy prompt and the panel work on them, and nothing drags. Narrow windows stack Todo, Doing, telemetry, each as tall as its content.
- **The telemetry rows no longer repeat what the Doing card beside them says**: the task title, the progress chart and the % are gone from a working agent's row (an idle agent, which has no card there, keeps its last card's title). A row keeps the agent, its state, the one-line ask or status, the last notes, the age and the 60-minute load bar, so it is shorter and sits nearer the cards.
- **On the way**: the agent name on a card stays whole while a narrow card shortens its status text; the telemetry title keeps to one line beside the new column (the subtitle goes under 1700px, the waiting flag takes its own line under 1500px); the legend wraps between words, never inside one.

### By agent: review and ask cards fit a lane; two more Motion pairings (Nov 3)
- **A review or ask card no longer runs off the edge of its By agent lane.** The Send button drops under the reply field when the card is narrow, and a long status line ("abandoned? no update 12h ago") ends in an ellipsis instead of past the card. By agent already draws the Board's Doing card design (the same tint, border and glow by state), so the cards match; this was the one visible gap.
- **In a lane the card's status text sits on the left**, where the agent chip would be (the lane already names the agent), instead of floating alone at the right. With a Report chip in the row it stays to the right of that.
- **Motion (the Mix layer, off until you choose it) now covers By agent and review**: a lane that appears because an agent just started slides in as its card glides over and settles; a card that reaches review has its edge bar draw itself in, green, with the review chime. A view switch does not count as a new lane. The sounds are the ones already there; nothing changes with Motion off. Not taken (your call left to me): a state dot in the lane header, the agent's colour on the lane panel, a tick per finished subtask, a dim for a quiet agent, a brighten when the panel opens.

### Load's Doing column sits where Board's does (Nov 3)
- **The Live bar under the tabs is gone from Load**, with its alert chips (backup age, abandoned, needs input, to review, quiet, average time to ship). It pushed Load's Doing column 42px lower than Board and By agent draw theirs, so switching to Load jumped. The overlay now uses the board's own gutters, and the Doing column has the same top, left edge and bottom on all three views at every width, down to a phone. The header's summary and its Disconnected chip carry the counts and the connection state; `f` still toggles fullscreen.

### Load no longer looks selected after you close it (Nov 3)
- **Closing Load with Esc or `h` no longer puts a whitish focus ring round the Load tab.** It sat there while Board or By agent was the open tab, so it read as if Load were selected. Only the open tab is lit now.

### `d` marks a card done and `u` undoes (Nov 3)
- **Press `d` to mark a card done**: the same move the Mark done button makes, on the card `c` would copy (the one you pointed at or focused last, else the selected one, else the open one), in any view and any column. A card with subtasks takes them along; a subtask says it goes with its parent; a done card says it is already done. One settle sound once it has landed. Ignored while typing, with Cmd or Ctrl held, and behind an open sheet.
- **Press `u` to undo what the toast offers**, for as long as its toast shows (7 seconds): a move between columns, a done, a **delete** (the card and its subtasks come back, new), Archive and Clear, and the bulk move and project changes. The toast now says `Undone: …`, with one short falling sound, whether you pressed `u` or the Undo button. With nothing on offer it does nothing, quietly. Not covered: a reply, an edit, a copy, a send-back (made on the report page).
- **Fixed on the way**: the keys that act on a card (`c`, `d`, `u`) no longer count as keyboard use when deciding between the pointer and the focused card, so a card under the pointer is not passed over for one that merely has focus.

### Agents wait for your reply in the background; an unread reply is kept (Nov 3)
- **After an `ask`, the card prompt and `agentboard instructions` tell the agent to start `agentboard answer "$ID" --wait --timeout 3600` as a background command and end its turn.** The session is woken when you reply and the command prints your answer, so an agent no longer sits idle until you type in its terminal. A tool that cannot run background commands runs it in the foreground.
- **An unread reply is no longer erased.** `update` and `review` used to delete a reply before the agent had read it; now `answer` marks the reply read (`read_at`), and only a read reply is cleared by the next `update` or `review`. A new `ask` or a `claim` still replaces it, since the question changed.
- **`answer` says when the reply was left**, on stderr (`(replied 2026-11-03 18:23 by Alex, 4 min ago)`), so `$(agentboard answer ...)` still captures only the reply.

### Settings on every view; a tidier header and Load bar; volume (Nov 3)
- **One gear in the header, in the same place on Board, By agent and Load**, opens Settings (`m`): what was the Mix sheet, now with the Sound and Ambient bed switches and a Volume slider above the Touch, Ambience and Effects layers. `s` still flips sound on any view.
- **Volume**: 100% is the usual level and the default; nothing changes until you raise it. Up to 300% goes through a limiter (-3 dBFS, 20:1) and a ceiling that never reaches full scale, so a raised volume cannot clip. Saved in the browser.
- **The header lost the project dropdown, the Filter field (and the `/` key), the Live block and the speaker button.** The who chips and the needs-input / to-review counts still filter; an active filter shows as before with a clear control next to it. A small amber chip appears only while the server is unreachable.
- **Load's bar keeps LIVE and the alert chips**: Pop out, Close, Mix, SND and AMB are gone (`h`, Escape and the tabs close it; `f` still toggles fullscreen; `/hud` still opens the pop-out).

### By agent as polished as the Board, and Motion (Nov 3)
- **By agent's lanes draw their cards the way the Board's Doing column does**: the status-tinted fill (orange running, green review, red ask), the status border and shadow, the hover glow, and a lit column head. It is one rule for both now, so no new colour was added and a change to Doing's look carries to the lanes.
- **Motion**, a Mix layer that is off until you choose it: look and sound move together. An agent's card that changes column lands at the end of its glide with the Touch settle (pitched by the column, in the agent's voice); a card reaching Done draws its check in; the view crossfades for the swish. Your own moves do not get the settle (they sounded when you made them). Off, nothing on the page changes.

### Every card gets subtasks, always (Nov 3)
- **The card prompt (Copy prompt) now tells the agent to add subtasks as soon as it starts**: at least two, even on a tiny card (do it, check it), and to report progress on the subtasks, since the card's % is their mean. No description needs the line pasted in any more. A card that already has subtasks keeps its list; custom templates are left alone.
- **The protocol says it plainly**: the Subtasks part of `agentboard instructions` (and the repo's CLAUDE.md) say "always, at start", and the ORCH boot prompt says never to paste the line into a card.
- **The terminal nudges**: `claim` and `start` on a card with no subtasks print one line saying to add them; `review` on one with none warns but still goes through; `add` of a top-level card reminds ORCH (on stderr, so scripts reading its output are unaffected).
- **The board flags it**: a Doing card with no subtasks shows a small amber "No subtasks yet" line under its bar, and it clears when the first one is added.

### `c` copies a card's prompt; Chat has no key (Nov 3)
- **Press `c` to copy the prompt of any card**, in any column and any view (Board, By agent, Load, the Later drawer): the one you pointed at or focused last, else the single selected card, else the card open in the panel. A Todo card's Copy button flips to its Copied state, as when clicked; any other card says which one it copied. Ignored while typing and with Cmd or Ctrl held. It is on the `?` list.
- **One copy path, one sound**: the key, the card's Copy button and the panel's Copy button all go through the same function and make the same short "copied" blip (off with the sound toggle).
- **Chat lost its key**: it is reached by its button only, and the shortcut is gone from its title and the `?` list.

### Load shows the Doing cards (Nov 3)
- **The left of Load is the Doing column**: the same cards as Board and By agent, in the same design, with their subtasks folded; the telemetry and agent-load grid stays on the right as it was. The cards follow the board's filter, and their reply box, Mark done and click-to-open work as they do on the board. A narrow window stacks the cards above the grid.
- **They glide into place**: opening Load slides the Doing cards from where they sit on the board (or the By agent lanes) into the pane, and closing it slides them back, the way Board and By agent already trade places. One swish per switch, nothing more; the bed plays through.

### Load switches with the same one sound as the other tabs (Nov 3)
- **Opening or closing Load plays the tab swish, the same simple sound as flipping Board and By agent**, instead of its rising and falling chimes. Every switch sounds once: the tabs, `[`, `]`, `a`, `h`, Escape, Back and Forward alike, and never a swish and a chime together. The ambient bed plays straight through, and the other cues did not change.

### Board and By agent switch in place (Nov 3)
- **Flipping between Board and By agent no longer reloads the page**: the tabs, `a`, `[` and `]` redraw the board where it is, the way Load already opened and closed. The sound plays straight through, the open card and the filter stay, and the address bar and Back button still follow the view.

### Touch: the sounds of using the board (Nov 3)
- **A thin layer of UI sounds for what your hands do**, synthesized like the cues and played through the same buses (compressor, reverb send), so it reads as one instrument: a soft tick when a card takes keyboard focus; a rising pair when a card's panel opens and a falling pair when it closes, in that card's agent's voice; a lift when you pick a card up and a settle when you drop it, pitched by the column it lands in (Todo low, Doing mid, Done high; dropped back where it was, nothing); a faint click per Alt+arrow step; one swish for a tab change (the tabs, `[`, `]` and `a` alike); a quiet slide in and out for Later, Chat, Mix and the shortcuts sheet; a two-pitch click on the theme, sound, notifications and AMB switches, up for on and down for off; a tick when the filter's match count changes (nothing per keystroke); a confirm blip when a prompt is copied; a tick that rises a semitone per card selected and falls when one leaves; one low tone for a failed save or a dropped connection, never again on every poll.
- **Every one of them is at most 40% of the quietest cue and 20 to 120 ms**, only ever on your own action (never on a poll or a re-render), one per action. Mark done keeps its done cue, adding a task its added cue: nothing plays twice.
- **One Mix row, Touch, on by default with its own level**, so the whole set turns down or off in one place; SND OFF still silences everything. The cues and the bed did not change.

### Sounds on every view (Nov 3)
- **The ambient bed and the Mix layers (Rain, Wind, Pad, Pulse) play on Board and By agent too**, not only while Load is open. The sound is the same as before; opening or closing Load no longer starts or stops it.
- **One bed at a time**: with several pages or windows open, the one you start or come back to plays and the others hush; when it closes the next visible one picks it up. Cues are unchanged: Board and By agent play the board's cues, Load plays its own, never both.
- **`s` turns sound on or off on every view**, and the sound button shows the saved state as soon as the page loads (it only caught up after Load was opened).
- A fresh page waits for your first click or key before the bed starts (browsers insist); clicking the tabs to switch views carries that over.
- Pulse and the console chatter follow who is working on Board and By agent too, by the same rule By agent's lane colours use.

### Full width (Nov 3)
- **The board uses the whole browser window**: the 1800 px cap is gone, so Board, By agent and Load fill a 2560 or 3440 px screen, and the top bar stays where it is (no longer centred) on every view and width.
- The columns grow with the window and the cards fill them, on the Board (Doing, Done) and on By agent alike.
- Load's text column stops at 760 px from 1800 px up and the hour bar takes the rest.

### Todo column in both views (Nov 2)
- **By agent now has the Todo column**, the same one as on the board: one function draws both, so they cannot drift. It is narrower than before (about 17% of the width, 220 to 270 px, the Doing and Done columns get the rest), its cards are narrower too, and they no longer say *Unassigned*. Copy prompt, Later and the queued time sit in one wrapping foot row instead of floating over the title; an assigned card shows its agent's name with the time in the foot row; a project shows as a dot in the corner.
- The assigned Todo cards that waited at the foot of an agent's column as *next up* are gone: they are in the Todo column now, so no card is drawn twice.
- Stacked (a phone or a narrow window) the Todo cards keep their narrow look (340 px at most) instead of stretching across the screen.
- **By agent's header button is Later, like the Board's**: the Todo drawer is gone (Todo is a column now), so the header is the same in both views and By agent gets the Park an idea box.

### The owner's name is a setting, not the code
- **`[board] owner` in config.toml** names the human on this board; it is **"you"** until you set it. The board, the HUD, report pages, the summary page, the dictation hints and every prompt (card, subtask, parent, run, instructions, ORCH, agent chat) read it, so nothing in the app names a particular person. Prompts say "the user" until it is set, and "they" for the pronoun. `/api/config` and `/api/hud` carry it to the page.
- **`[voice] words`** adds names to the dictation hints (the old built-in list of one person's project names is gone).
- A card that says "ACTION you: ..." or "ACTION <your name>: ..." lands in the owner's row on Load either way.

### Sound
- **Mix** (the Mix button in Load, key `m` anywhere): extra sound layers on top of the usual sound, each with its own switch and level, saved in that browser and **off until you choose it**. The sound you had is the default and did not change. Ambience, played with AMB in Load: Rain, Wind, Pad, Pulse (a heartbeat that quickens as more agents work). Effects, board and Load: Echo, Signatures (each agent's three-note call when it starts or finishes), All clear (a chord when the last card waiting on you is answered), Hourly chime. A **Hear it** button plays any layer for a few seconds before you switch it on.

### UX polish (Nov 2)
- **Load:** the idle rows are readable (their status was at 30% opacity; text is now 4.5:1 or better, still quieter than working by colour), and the Queue row stays pinned at the bottom of the list when the open idle rows push it below the fold.
- **Click areas:** the subtask toggle, the Done column's Summary / Reports / Clear and the card's Report link keep their look but are about 30px to hit.
- **Later drawer:** no repeated "Unassigned" on every row.
- **Small labels** (the day-group count, the chat topic chip, the By agent state tag, the idle fold count) reach 4.5:1 in both themes.
- **Cards and the panel** say "14% overall" for a parent's percent instead of a sigma (the CLI `list` keeps its Σ).

### Load
- The idle agents on Load are **open by default** (Nov 2), so the default view shows them without a click. The IDLE row still folds them away, and a collapse is remembered in that browser.
- The **HUD** tab is now **Load** (its address is still `/hud`, key `h`). Load no longer draws a top bar of its own: the board's header stays on screen and Load opens right under it, so Board, By agent and Load share one nav, item for item, at every width (before, Load's copy sat 12px further in between 600 and 900px, up to 24px lower below 980px, and had different items). Load's own controls (LIVE, alerts, sound, ambient, pop out, close) sit in a thin bar under the nav. The pop-out window keeps the header too. Later and Chat open over Load, Esc closes them first, and the Later and Todo buttons share one width so ORCH no longer moves between Board and By agent.

### By agent
- A fifth tab, **By agent** (`/agents`, key `a`): the board's cards as swimlane columns, Queue first, one per agent with a card in Doing (state in the header, assigned Todo cards as *next up* ghosts), then one Idle column from the HUD's roster. Todo and Done are counts in the bar. One agent per screen on a phone. Chosen from `docs/doing-by-agent-mockup.html` (option B).

### Removed (Nov 1)
- **Assign, Hand to… and the Your move strip.** You paste the card's prompt into an agent and the agent claims the card itself, so the picker (`/api/assign`, `/api/hand`, `/api/agents`), Unassign, the card holder set before a claim, the `ORCH: you assigned <id> to <agent>; hand it over.` chat line and the matching ORCH prompt rule are gone. Asks and reviews stay on their cards and in the panel that opens for them; an agent gone quiet keeps its warning on the card and the HUD. Queued prompts no longer rewrite the session name.

### Colour belongs to the agent, not the card (Nov 1)
- Cards no longer carry a colour. `start`, `claim`, `run` and `chat send` still accept `--color` (and `AGENTBOARD_COLOR` is read nowhere) but ignore it; nothing is stored, a claim no longer copies a colour to its subtasks, chat bubbles take the sender's colour by name, and `/api/color` is gone. Existing cards keep an unused `color` field.
- The board picks one hue per agent name from a six-colour palette clear of the status hues (orange running, green review, red ask); `[agent_colors]` in config.toml overrides a name. Same colours on the board, the HUD and the chat. Before, AGENT-1 to AGENT-5 were all green because each card brought its own.
- The agent's name sits in a pill tinted with its colour, with a solid avatar disc; the name is 14px bold in the same place on every card, and Unassigned is no longer faint.
- The ORCH prompt, card prompts, `agentboard instructions` and the README no longer tell agents to pass a colour; the ORCH roster lists names only (a colour in `[orch] agents` is ignored).

### Agent chat (opt-in)
- Agents can talk to each other on the shared chat once the owner turns it on (**Agents talk** in the Chat panel, or `agentboard chat agents on`; default off, board-wide, stored in the board file). Messages gain `--to`, `--topic` (status, learn, help, heads-up, handoff), `--detail` / `--detail-file`, `--card`, `--file`, `--reply-to` and `--propose`; the panel shows one line per message in the agent's colour, the detail on tap, chips for the card and files, and Approve / Decline on a proposed action (`agentboard chat approve|decline <n>`; agents read the decision with `chat approvals`). Chat never changes anything itself.
- Said casually: with `[chat] casual = true`, `agentboard serve` gives each agent line a spoken version on the cheap model (same facts, one friendly line), shown as the bubble with the line as written behind **As written**; `agentboard chat casual [--once]` by hand; `casual_per_hour` caps it.
- The real conversation, mirrored: `agentboard hooks install` adds a Claude Code hook (PostToolUse on SendMessage) that posts each message a session sends to another session on the chat, as that session, to whom it went, the rest behind Detail (`msg` chip). Sessions are named by their first `claim`, `start`, `chat` or `agentboard me --name`; `agentboard hook send-message` is the hook's command, always exit 0.
- Signal over noise: the board never speaks for an agent that spoke or touched a card in the last `live_min` minutes (default 20); drafts know the date and each card's age, treat done cards and day-old asks as closed, never post a bare acknowledgement, and end an answer with a question back; a share must tie to a card a colleague is on right now, to that agent, or it is not posted.
- The drafts speak like colleagues (short sentences, contractions, names, no lists, code only in the detail), and an idle agent with nothing to answer offers one thing from its own finished work every `share_every_min` minutes (default 60) as a *learned* line to all; `chat idle --share` by hand.
- Autopilot: with `[chat] autopilot = true`, `agentboard serve` drafts a reply on the cheaper model for every `[orch] agents` name that is idle and has unread chat, every `autopilot_every` seconds (default 180), capped at `autopilot_per_hour` (default 12); the lines are marked **auto** and show in that agent's own inbox. `agentboard chat autopilot [--once]` runs the rounds by hand.
- Flipping the switch posts one line to the chat telling ORCH and running agents what to run; the ORCH prompt says how ORCH takes part (open the channel, `chat inbox --name ORCH --wait 300` when idle, answer, name who takes a handoff, never act on a proposal).
- `agentboard chat inbox --name X [--wait N]` (unread for X, cursor kept per name), `chat tail --for X`, `agentboard recall` (the board as shared memory: cards, updates, history and chat matching a few words, one card's history, one agent's cards), and `agentboard chat idle` (one reply drafted from the inbox and the memory through the local `claude` binary on `[chat] idle_model`, default `haiku`, `--send` to post). The prompts (card, run, ORCH, instructions) carry the protocol only while the switch is on. Lines that arrive together are revealed one at a time in the panel.

### Round two (ux-six)
- **Desktop notifications from the tab.** A bell in the top bar; on, the board uses the browser's Notification API (local only) while the tab is in the background: an ask at once and again every 15 minutes while it waits, a review once, an agent gone quiet once. Clicking one brings the tab back and opens the card. Stored as the `agentboard-notify` preference.
- **Edit in place on the card.** In the panel the title and the description are editable where they are (click, or `e` for the title); Save or ⌘↵, Esc cancels; one log line per change, marked as yours. The subtask list ends in an add row (Enter adds a subtask under the card), and a Blocked by row takes any open card by its title and shows the blockers as chips with a remover. Agents and columns never change this way. New: `Store.edit`, `POST /api/edit`.
- **Assign and Hand to… put the prompt on the clipboard.** Picking an agent also copies the card's prompt, which now names that agent (`claim <id> --name "AGENT-3" --color …`) while the card waits in Todo with a holder; the one step left is the paste into that agent's terminal. `agentboard prompt <id>` says the same.
- **Hand to… on quiet cards.** The Your move row of an agent gone quiet (and the panel of any live card) opens the same picker as Assign, idle agents first, without the current holder; one pick sends the card to the top of Todo under the new agent, clears its ask/review state, releases the old agent, takes the open subtasks along, and tells ORCH in the chat (`ORCH: you handed <id> from <old> to <new>; hand it over.`). "Nobody yet" sends it back to Todo unassigned. The panel of a queued card gets Assign / Reassign. New: `Store.hand_to`, `POST /api/hand`.
- **Quick replies on asks.** The options an ask names become one-tap chips (`3 or 5?` gives 3 and 5; `x, y or z?`, `(1) … (2) …` lists and yes/no questions likewise), plus Go ahead, Hold and Your call on every ask. On the Your move row the chips replace the Reply button and sit beside a small typed box; on the card and in the panel they sit above the reply box. A tap sends the reply the usual way (`/api/reply`, read with `agentboard answer`).

### Five UX ideas (ux-five)
- **HUD: one chart per agent, idle agents folded.** Each active row carries a stepped chart of its card's % over the last hour with a tick per update, on the same axis as the load track; `/api/hud` adds `chart` per agent and an `idle` fold. Idle agents collapse into one row of chips (name, how long ago, signed off today) that opens on click. `[orch] agents` peers with no card yet show as idle.
- **Assign from a Todo card.** An Assign button on every Todo card opens a picker of agents, idle ones first (from the HUD's view plus `[orch] agents`), then the busy ones with what they hold; a click hands the card to that agent (it stays in Todo with that holder until the agent claims it), and Unassign takes it back. The hook: the board posts one line to the shared chat (`ORCH: you assigned <id> to <agent>; hand it over.`), which ORCH follows; the ORCH prompt says to act on it. New: `Store.assign`, `POST /api/assign`, `GET /api/agents`.
- **One top bar.** The board, the HUD, the Done summary, the reports list and every card report share one bar: the brand and four tabs (Board, HUD, Summary, Reports), the current page lit, every link under the board's own `/b/<name>` prefix. On the board the HUD tab is the old HUD button; in the HUD the Board tab closes it (or opens the board from the pop-out). Report pages now follow the board's chosen theme too. New module `nav.py`.
- **Done column: a 7-day ribbon and day groups.** Under the Done header, one bar per day (today at the right) as tall as that day's finished cards, with the count and the weekday; click a day to see only its cards. The column groups cards by calendar day (Today, Yesterday, then the weekday and date, Earlier past the week), each group with its count.
- **Your move strip.** Every card that needs you sits in one strip under the header, asks first, then reviews, then agents gone quiet, each with its action right there (Reply, Mark done, Send back, Open, To Todo) and a bar of how long it has waited. Hidden when nothing needs you.

### Keep it simple
- The ORCH prompt (Copy ORCH, and the one-shot and instructions variants) gains a named `Keep it simple` block that ORCH must copy word for word into every card description and assignment it writes: one sentence, one idea, detail on demand. Instructed only; nothing checks it.
- `agentboard update`, `ask` and `review` take a first line plus a body: `--body` / `--body-file`, or a multi-line text whose first line is the sentence and the rest the body. On the card the sentence is the large first line and the rest sits behind a collapsed `Details` fold.

### Voice
- Mic buttons on the add-card box, the chat box and the reply boxes (on the card and in the panel): record in the browser, transcribe on this Mac with whisper.cpp through `POST /api/transcribe`, text inserted at the caret. `agentboard dictate [--paste] [--file f] [--mic i]` does the same for a terminal: Enter, speak, Enter, text on the clipboard. Local only: no browser speech API, no upload, no account; hidden when `whisper-cli` or a model is missing. `[voice] model` / `AGENTBOARD_WHISPER_MODEL` pick the model.

### Done summary
- A Summary button on the Done column header opens `/summary` (`?since=1d|7d|30d|all`, `&project=<id>`): the finished cards as a page about the work itself. One number and three plain facts; a bar of the kinds of change (added, fixed, improved, tested, documented, explored; from the titles and asks); a work map (projects split into work areas found from shared title words, sized by cards, coloured by the main kind; click an area for its cards); each project as collapsed work areas with one row per card (title, outcome with numbers in bold) that opens to the ask, the full result, the timeline and links to the card and its report. Search and a kind filter scope the whole page; inline SVG only, both themes, phone width. Copy text (markdown), Copy Mermaid (a mindmap of projects and areas) and Save as HTML. `agentboard summary [--since 7d] [--project id] [--html path] [--mermaid]`.
- An opened card is readable, not a blob: a numbered ask becomes a step chain plus the items, an ACTION/STATUS/WHY result becomes three coloured bands, other text is one sentence per line; paths, flags and files in code style, numbers bold, asides muted, a leading name as a chip. "How it went" is a bar of the time the card spent in each status, with the timeline folded under it.

### Card reports
- A card entering review or done gets an HTML report in `.agentboard/reports/` (action first, then number tiles for commits, tests and files, a few built points, a short timeline, commits with links, bars of where it changed, numbered steps to try it, Mark done / Send back; no run-on paragraphs). A report button on the card, a list at `/reports/`, `agentboard reports [--purge]`, and an ageing sweep (`[reports] keep_hours`, default 24; the newest per card always stays). `POST /api/send-back` sends a card back with a note the agent reads with `agentboard answer`.

### One sentence to the owner
- Every prompt (Copy prompt, run prompt, instructions snippet, ORCH prompt) ends with the reporting rule: one sentence, the ACTION first then one fact; no action needed = one line of status; more = one sentence then offer the detail. The ORCH prompt now says agents report to the owner directly, when ORCH may speak to them, daytime vs sleep assigning, and what is never done without their own words.
- Ask and review cards show that sentence as the first line, large, with a reply box on the card. The reply is stored on the card and read with `agentboard answer <id> [--wait]`; it clears when the agent moves on.

### One-shot agents
- `agentboard run <card>` runs a card with a non-interactive `claude -p` in its own git worktree, under a hard time limit and a spend cap, with a per-run log in `.agentboard/runs/`. On exit the card moves to review (or ask, with the tail of the output), records cost and duration, and the worktree is removed if clean. `agentboard runs` lists runs, `runs --kill CARD` and the card's Stop run button stop one, `--detach` returns at once. Permission settings are never widened. A `▶ run` badge shows on the card.

### Several boards
- `agentboard board new | add | list | use | rm` and a registry in `~/.agentboard/boards.toml`; `--board NAME` / `AGENTBOARD_BOARD` pick a board from any folder. One `agentboard serve` serves every registered board at `/b/<name>/` (and `/b/<name>/hud`); the default board's links are unchanged. A header dropdown switches boards and a per-board colour tints the header. Snapshots and `sync_dir` stay per board.

### New cards on top
- `agentboard add` and both web Add forms put the new card at the top of Todo or Backlog (not the bottom). Column order is still the stored list order, so drag-reorder and Alt+arrow keep working; existing cards keep their order; Doing and subtasks still append.

### Header
- ORCH sits on the left beside Later and Chat. The Auto / Light / Dark word becomes one 44px icon button (half circle, sun, moon) that cycles the same three modes, with a tooltip and an aria-label naming the mode. README screenshots retaken.

### Status colours
- Card colour follows status: orange while doing, green at review, muted when done, red edge on ask. The agent's colour is now a thin left stripe on the board. The HUD's working colour is orange and waiting-on-you is red.

## v0.3.1 (2026-10-25)

### Backups
- Atomic saves with a `.bak` of the previous file; hourly snapshots in `.agentboard/backups/` (48 hourly, 30 daily); optional nightly
  copy to a synced folder (`[backup] sync_dir`); `agentboard backup | verify | restore`; the HUD shows the age of the newest snapshot.

### Twins
- `start` reuses a card the same agent already holds instead of creating `<id>-2`; `claim` on a held card is a no-op;
  `agentboard dedupe [--apply]` merges existing twins.

## v0.3.0 (2026-10-24)

Since v0.2.0 (63 commits). Still Python 3.11+, standard library only, local only.

### HUD (`/hud`)
- One grid: every agent is one full-width row with its name and state, the text that matters
  (the ask in full, or the agent's own status line), its last notes, and on the right the card
  title, the 60-minute load bar and the progress line. One header, one time axis, the queue as the
  last row. Panel fills the window; rows share the spare height.
- Attention rows: a card that needs a person lights its agent's row (red: needs an answer or a
  sign-off; amber: the agent went quiet; cyan: the ask names another agent), rows that need you
  sort first, and clicking one opens the card.
- `/api/hud` gains `actions`: every ask / review / abandoned card as a "who must do what" row,
  parsed from the ACTION / STATUS / WHY report shape agents write.
- `[hud] retired = ["AGENT-5"]` in `config.toml` hides retired agents from the HUD (cards and
  history untouched).
- Type one step larger; lanes no longer rebuild every second; contrast fixes; narrow screens
  stack the load bar under the text.

### Board
- Readable card detail panel: ACTION band (who must act, in colour), STATUS chips, formatted
  timeline with time-ago and progress, light markdown (bold, bullets, inline code, tables), copy
  buttons on commands and links, Mark done / Reply (replies land on the card log as the user).
- Numbered steps written as "(1) … (2) …" or "1. … 2. …" render one step per line, markers kept.
- Subtasks: child cards under a parent (one level), the parent's % computed from them, a single
  total bar with a checklist, prompts that tell a subtask agent what to do.
- Dependencies (`--blocked-by`), projects (named, coloured, with a filter), bulk select / move /
  archive / assign, Later drawer from the left, columns keep their scroll position, header wraps
  instead of squeezing, undo logs a "Restored" entry.
- `agentboard tail` (live terminal feed), `agentboard wait` (block until a status), `agentboard
  report` (daily recap by agent), chat channel (`chat send` / `chat tail --follow`), opt-in macOS
  notifications on ask / review, rich markdown bodies on ask / review (`--body`, `--body-file`).
- `agentboard init` now adds `.agentboard/` to the project's `.gitignore`.
- Bug hunt across store, server, prompt, markdown and wait; parent % refused instead of dropped;
  natural sort of agent names (AGENT-2 before AGENT-10).

### Docs
- README rewritten for what exists now: install, the HUD, the ACTION / STATUS / WHY report shape,
  the orchestrator + agents workflow, config keys, CLI reference, a work-laptop section.
- SECURITY.md re-checked against this release.

## v0.2.0 (2026-10-20)
- First public release: board, HUD with per-agent swimlanes, prompts and context providers,
  local-only audit (SECURITY.md).
