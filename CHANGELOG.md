# Changelog

## Unreleased

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
- **`1`, `2` and `3` open Board, By agent and Load**, the same ring `[` and `]` walk, by number. Not while typing, and not in the pop-out Load window (it has no board). On the `?` list.

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
