## Agent board

This project tracks agent work on a shared board (`agentboard`). When you begin a distinct piece of work:

    ID=$(agentboard start "<short title>" --name "<your session name>" [--color <color>])
    agentboard update "$ID" <0-100> "<one-line status>"     # your REAL % done, updated every time it changes
    agentboard review "$ID" "<one-line result>"                # work complete -> the USER signs off and marks it done
    agentboard ask "$ID" "<one-line question>"                 # ONLY if blocked on the user; keep working after they answer

The percentage is what the list and HUD show at a glance, without anyone opening the card — keep
it current. Call `update` again whenever your estimate changes, not just at fixed checkpoints, and
walk it back if you discover more work than you thought; don't leave it sitting at a stale number.

Add `--body "<markdown>"` (or `--body-file <path>` for multi-line content) to `review`/`ask`
for a proper recap, diff, or report — it renders as formatted markdown in the detail panel,
which opens automatically when your card needs input or is ready for review.

NEVER mark your own task done. Finish with `review` and stop. Run
`agentboard done "$ID"` only if the user explicitly tells you to.

If you are handed a task id instead, run `agentboard claim <id> --name "<your session name>"`.
Use your own session name (and color, if you have one) so people can tell agents apart.
Create one task per deliverable, not per command. Keep titles short and status lines to one line.

Before claiming or starting a card, if anything about it is ambiguous, ask your orchestrator/coordinating
session a one-line question (e.g. via SendMessage) and wait for its answer first. It has visibility into
the whole board and can often answer without bothering the user; it escalates to them if it can't. This
is a one-time check before you start, not an ongoing back-and-forth once work is underway.

## Projects

Group related tasks under a project so they show up together on the board:

    agentboard project add "<name>" [--color <color>] [--description "..."]   # prints its id
    agentboard project list
    agentboard project assign <task_id> <project_id>     # tie any existing card to a project
    agentboard project unassign <task_id>                 # untie it
    agentboard add "<title>" --project <project_id>       # or tie it at creation time
    agentboard start "<title>" --name "<you>" --project <project_id>

## Talking to other agents

Coordinating with another agent — who's on what, asking for a hand, splitting or handing off
work — goes in the shared chat, not only a private message, so the user can see it and jump in:

    agentboard chat send "<message>" --name "<your session name>"
    agentboard chat tail                                   # catch up, including the user jumping in
    agentboard chat tail --follow                           # keep watching live (Ctrl+C stops)

Write it like a quick Slack message to a teammate, not a status report: short, plain, skimmable in
a second — what you're doing or what you need, then stop.

    Good:          "grabbing the HUD legend task, shout if you're already on it"
    Good:          "done with the scroll-jump fix, up for review"
    Over-formal:   "I have completed the scroll-jump bug fix. The render() function's focus-restore
                    logic now uses preventScroll:true. The card is ready for your review."

Got a lot to say (a commit audit, a multi-part handoff)? Say it briefly and point at the card/task
id for the detail — don't paste the whole report inline.

Check it when you're blocked on coordinating with another agent, same as you'd check for a reply
to a private message. Use a private message instead only for something that genuinely shouldn't
be visible on the board.

## Dependencies

Declare a task is blocked by another so parallel agents don't collide on ordering:

    agentboard add "<title>" --blocked-by <task_id>            # repeat --blocked-by for more than one
    agentboard start "<title>" --name "<you>" --blocked-by <task_id>
    agentboard claim <id> --name "<you>"                        # refuses while a blocker isn't done (--force to override)

The card shows a lock with a link to each unresolved blocker; it clears on its own once the blocker is marked done.

## Sync

Block until another task reaches a point you need, instead of polling `list` or pinging chat:

    agentboard wait <task_id>                       # default target: done
    agentboard wait <task_id> --status review        # or: stop as soon as it's up for review
    agentboard wait <task_id> --timeout 300           # give up and exit nonzero after 5 minutes

`review` and `needs_input` always end the wait early even when they weren't the target you asked
for, since both mean progress is stalled on a human, not on more waiting.

## Verifying UI changes to src/agentboard/static/index.html

After editing the static file: `cd ~/dev/agentboard && pipx install . --force`, then kill and
restart `agentboard serve` (the pipx venv's copy is what actually serves `localhost:8765` — editing
`src/` alone does nothing live). Confirm with
`md5 <pipx venv static/index.html> <src static/index.html>` — they must match.

If the Claude-in-Chrome extension isn't connected, drive headless Chrome directly over the DevTools
Protocol instead of giving up on live verification:
1. `pip3 install --target /tmp/qa_pylibs websocket-client`
2. Launch: `Google\ Chrome --headless=new --disable-gpu --remote-debugging-port=<port> "--remote-allow-origins=*" --user-data-dir=<throwaway dir> about:blank` — both flags are required (recent Chrome needs `--remote-allow-origins=*` or it 403s the websocket handshake). Pick a port nobody else is using; other agent sessions doing the same thing can collide on the default.
3. `PUT http://localhost:<port>/json/new?<url>` to open a tab, connect the returned `webSocketDebuggerUrl`, send `Page.enable`, then drive it with `Runtime.evaluate` (click buttons, read DOM/computed state) and `Page.captureScreenshot`.
4. For anything beyond a read-only check against the real board, seed a **throwaway** board first: a separate `AGENTBOARD_DIR` + port with synthetic `tasks.json` data, so you're not writing test data into the real board. Tear down the Chrome process, temp server, and temp dirs when done.
5. A DOM-order/computed-value assertion (not just a screenshot) is the real test — screenshots are a sanity check on top of it, not a substitute.

