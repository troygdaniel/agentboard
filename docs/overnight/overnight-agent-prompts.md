# Overnight: one source for every agent prompt (overnight-agent-prompts)

Branch `overnight/overnight-agent-prompts` (worktree `~/dev/agentboard-on-prompts`), on top of main at 8b07a0d. Nothing merged, nothing pushed.
The full before and after text of every prompt is in `docs/overnight/agent-prompts/before/` and `.../after/` (made on a throwaway board).

## The short version

Agents are told how to work in more than a dozen places, and the copies had drifted: three different wait lengths, a one-shot run told both to start a background
wait and to stop, `--force` offered for blocked cards, four wordings of the reporting rule, a command (`--to the user`) that the CLI refuses, and none of the lessons from
tonight. Now every rule is written once in `src/agentboard/rules.py`, every prompt is built from it, and `tests/test_prompts_agree.py` generates all of them and fails
if one drifts or contradicts another.

## What was inventoried (every text an agent reads)

| # | Text | Where it is built | Used for |
|---|---|---|---|
| 1 | `agentboard instructions` | `cli.INSTRUCTIONS` | what goes in a project's CLAUDE.md or AGENTS.md |
| 2 | the card prompt, three shapes (plain, subtask, parent) and a text card | `prompt.DEFAULT_TEMPLATE`, `_SUBTASK_MID`, `_PARENT_MID` | Copy prompt on a card |
| 3 | the unattended run prompt | `runs.build_run_prompt` (card prompt + `runs.RULES`) | `agentboard run`, `claude -p` |
| 4 | the ORCH boot prompt | `prompt.ORCH_TEMPLATE` | the ORCH button |
| 5 | the agent-chat protocol and ORCH's part of it | `agentchat.PROTOCOL`, `ORCH_PROTOCOL` | rides along while agent chat is on |
| 6 | the board's own announcement when agent chat is switched on | `store.set_chat_agents` | a line in the chat |
| 7 | the Stop hook's three messages | `hooks.stop_decision` | blocks a session about to go quiet |
| 8 | the hint `answer --wait` prints after a board message | `cli.cmd_answer` | stderr of the wait |
| 9 | the idle drafter's prompts (draft, share) | `agentchat.DRAFT_PROMPT`, `SHARE_PROMPT` | headless drafting of chat lines (a different job; checked, not rewritten) |
| 10 | this repo's own CLAUDE.md | a checked-in copy | every session that works on agentboard |

## What disagreed (before)

| # | Contradiction or gap | Where |
|---|---|---|
| C1 | The wait length was 120 s in the chat protocol, 300 s in ORCH's part of it and in the board's announcement, and 3600 s everywhere else | 5, 6 vs 1, 2, 4, 7 |
| C2 | A one-shot run was told to "start `answer --wait` in the background and end your turn" (the card prompt) and, a page later, to "finish with `review` and stop" (the run rules); with agent chat on it was also given the chat protocol's blocking inbox | 3 |
| C3 | The run rules told it to read and follow the repo's CLAUDE.md, which says to wait after `review` | 3 vs 10 |
| C4 | The Dependencies section said a blocked card claims with `--force`: the opposite of the rule that a blocked card is never forced without ORCH | 1, 10 |
| C5 | The reporting rule was written four ways (instructions, `REPORT_RULE`, the ORCH prompt, the run rules) and the ORCH copy lacked the `--body` sentence; the run prompt carried it twice | 1-4 |
| C6 | The wake-and-wait paragraph had five variants of different completeness (the subtask one lacked the foreground fallback and the timeout line) | 1, 2 |
| C7 | `--to {owner}` printed `--to the user` on a board with the default owner, which `chat send` refuses ("unrecognized arguments: user"): the command word is `you`, not the prose | 1, 2, 4, 8 |
| C8 | This repo's own CLAUDE.md was an older copy: no wake rules, "finish with `review` and stop" where the instructions say "then wait", no `--body` shape | 10 vs 1 |
| C9 | The unattended run was told to make its own worktree (if it followed the new rule) although the board had already made one | new rule vs 3 |
| G1-G4 | Not said anywhere: work in your own worktree and never edit the main checkout (and no `git stash`); do not claim a card because it sits in Todo; a blocked card is not forced; never put a backtick in a double-quoted argument | tonight's lessons |
| G5 | Not said to ORCH: `done` takes one id (a second word is the note, not another card) | tonight's lesson |

## What changed

- **`src/agentboard/rules.py` (new)**: the one source. The wait length (`WAIT_S = 3600`), the three commands that carry it (`answer_wait_cmd`, `inbox_wait_cmd`, `reply_cmd`), the reporting rule,
  the finish-and-wait paragraph (`wake`: full after `review`, short after `ask`), `reachable`, `never_done`, the unattended-run ending, the four working rules, and ORCH's one-id rule.
- **Built from it**: the instructions, the three card shapes, the run prompt, the ORCH prompt, the chat protocol, the board's announcement, the Stop hook's messages and the
  `answer --wait` hint. No other module spells out a wait length.
- **The unattended run** is its own variant on purpose: `build_prompt(..., attended=False)` swaps the background-wait paragraphs for "after `review`, stop; nothing can wake you", drops the chat
  protocol, tells it to stay in the folder the board made (not to create a worktree), and says to follow the repo's CLAUDE.md "except where it says to wait".
- **`--to` gets the right word**: `{owner_cli}` is the board's name for the human (`you`, or the owner's name quoted for the shell); `{owner}` stays the prose ("the user", or the name).
  The Stop hook's prose no longer reads "you wrote to you".
- **CLAUDE.md** is regenerated from `agentboard instructions` (the shared sections) with its two repo-only sections kept after them, and a test fails when it drifts again.
- **Shorter where it could be**: the percentage and "ask first" paragraphs were tightened, the after-`ask` wait is said in two lines, the run prompt no longer repeats the reporting rule.

Words per prompt (the same fake board; `wc -w`):

| Text | Before | After |
|---|---:|---:|
| instructions | 1343 | 1514 |
| card, plain | 832 | 896 |
| card, subtask | 792 | 879 |
| card, parent | 791 | 880 |
| run prompt | 1068 | 835 |
| ORCH | 1032 | 1069 |
| chat protocol | 662 | 662 |
| total | 6520 | 6735 |

The total is 3 percent longer, not shorter: the five new rules (about 130 words in each prompt an agent works from) outweigh what the tightening and the de-duplication took out. The run prompt, which carried
the most repetition, is 19 percent shorter.

### The worst contradiction, before and after (the run prompt; the card prompt's wait paragraph, then the run rules)

Before:

    After `review`, do not sit idle: start `agentboard answer notes --wait --timeout 3600` as a background command ... and end your turn.
    ...
    ## Rules for this run
    - Finish with `agentboard review notes "<one-line result>"` and stop. Never mark the card done: the user does.

After:

    Finish with `review` — the user signs off and moves the card to done. This is an unattended one-shot run: after `review`, stop. The run ends
    when you do and nothing can wake you afterwards, so do not start a background wait.
    ...
    - Work only on this card, inside this folder. Read the repo's CLAUDE.md first and follow it, except where it says to wait after `review` or `ask`: this run does not wait.

## Checks

- **`tests/test_prompts_agree.py`** (37 tests, run for a board whose owner is "you" and for one called "Sam Jones"): every prompt carries the reporting rule, the wake paragraph, `reachable`, `never_done` and the working
  rules word for word from `rules.py`, each exactly once; every wait in every text is one length, and no module hard-codes one; the run prompt never says to wait, an attended prompt never says to just stop;
  `--force` is only ever mentioned to be refused; `done` is only ever for the owner's say-so; no command says `--to the user`; the hook messages and the announcement use the shared commands; the idle
  drafters carry no protocol of their own; this repo's CLAUDE.md contains the current instructions word for word.
- **27 mutants** (each wait length put back, a paragraph dropped from a prompt, the run prompt attended again, the chat protocol in a run, `--force` invited again, `--to {owner}`, the hook's prose, the shared
  command unquoted, a rule worded differently so CLAUDE.md goes stale, and more), all caught.
- Nine existing tests pinned the old wording and were updated on purpose (the 120 and 300 second waits, "sends you a message on the board" now "writes to you on the board", the `ask`/`review` paragraph split in two,
  the run prompt carrying the reporting rule twice, a source check that looked for a sentence in `runs.py`).
- Compiled with a real Python 3.11 (an f-string with nested quotes would pass on 3.12 and fail there).
- Full suite and `python3 tests/publiccheck.py`: see the end of this file.

## Rebased onto overnight/combined-11 (Nov 8, 04:00)

The branch is now one commit on `overnight/combined-11` at 59b848e (it was on main 8b07a0d; the old tip 8759582 is kept as the local branch `backup/agent-prompts-8759582`). The conflicts were in `prompt.py` (7), `hooks.py` (4), `agentchat.py` (1) and `store.py` (1), and
three things from the merged tree had to be carried through the one source:

- **Threaded answers.** The merged tree added `--reply-to <the line's number>` to every instruction that answers a board message (and the Stop hook passes the real number). `rules.reply_cmd` now takes `reply_to`, `rules.REPLY_TO_HERE` is the placeholder every prompt uses, the hook calls `rules.reply_cmd(..., reply_to=seq)`, and the hint `answer --wait` prints after a board message now names the line too (`reply_to=msgs[-1]['seq']`).
- **The ORCH chat-wake paragraph** ("the wait watches one small file, `chat-wake.json` ...") is kept as merged, with its wait command from `rules.inbox_wait_cmd`; its `--to` word is `{owner_cli}`.
- **The Stop hook's prose**: the merged tree says "the board's owner" for a board whose human is called "you"; that wording is kept (my version said "the user"), and `tests/test_prompts_agree.py` follows it.

Also: `rules.py` is in `docs/ARCHITECTURE.md`'s module map (a test requires it), CLAUDE.md was regenerated from `agentboard instructions` again (it now carries the merged tree's threading lines), and the test that checked the card template for `--reply-to` (`test_receipts_age`) now checks `rules.wake`, the ORCH template and the instructions, because the card prompts take that paragraph from `rules.py`.

Suite on the rebased branch: **1625 tests, 1624 OK**. The one failure, `test_signoff_files.TheTableIsTrue.test_the_mode_in_the_table_is_the_mode_on_disk` (`.claude/settings.json` is 0600, the table says 0644), is not from this branch: it fails the same way on `overnight/combined-11` at 59b848e itself.

## Try it

    cd ~/dev/agentboard-on-prompts && rm -rf build && pipx install . --force
    agentboard instructions | less            # the same text a project's CLAUDE.md gets
    agentboard prompt <card id>               # a card prompt; compare with docs/overnight/agent-prompts/before/
    python -m unittest tests.test_prompts_agree

## Risks

1. **Existing projects keep their old pasted copy** of the instructions until someone pastes the new one (or runs `agentboard init --instructions` once that lands); the new rules reach agents through the card prompt first.
2. **`--to you`** is what `chat send` needs on a default board, but it reads oddly in prose; a board with `[board] owner` set gets its name.
3. The working rules tell agents to use a worktree "in a git project": a team that does not want that must change `rules.working_rules`, in one place.
4. The prompts are 3 percent longer overall. If that matters more than the four new rules, the cheapest cuts are the `flow` diagram paragraph and the Dependencies and Sync sections of the instructions.
5. `hooks.py` and `cli.py` are also edited by AGENT-1's chat-f7 and hooks-known-only branches: expect a small conflict in `hooks.py`'s `stop_decision` (keep both; mine only swaps literals for `rules.*` calls and adds `who`).

- Full suite before the rebase: **1273 tests, OK**; after it, see the section above; `python3 tests/publiccheck.py`: 0 findings; 27 of 27 mutants caught after the final trims.
