"""The rules every agent-facing text repeats, written once.

Agents are told how to work in six places: `agentboard instructions` (what goes in a project's CLAUDE.md or AGENTS.md), the prompt on every card
(Copy prompt, in three shapes: a plain card, a subtask and a parent), the one-shot run prompt, the ORCH boot prompt, the agent-chat protocol, and the
Stop hook's messages. They used to carry their own copies of the same rules, and the copies drifted: the chat protocol waited 120 seconds where the
card prompt said 3600, a one-shot run was told both "start a background wait" and "finish and stop", the instructions said `--force` was fine for a
blocked card, and the reporting rule had four wordings. Now each rule is defined here and every text is built from these pieces, so the words
cannot differ. `tests/test_prompts_agree.py` generates every prompt and checks they all carry the same rules and that none contradicts another.

Every function returns text that may still hold the placeholders {owner} and {Owner} (the human's name, filled by `prompt.say`) and, in the card
templates, {ab} and {task_id} (filled by `prompt.build_prompt`): pass the placeholder itself as an argument to keep it for later."""

import shlex

WAIT_S = 3600    # how long one `answer --wait` or `chat inbox --wait` blocks before it is started again: one number for every text


# -- the commands, so the numbers and flags cannot differ between texts -----------------------------------------------------------
def answer_wait_cmd(ab, card):
    return f"{ab} answer {card} --wait --timeout {WAIT_S}"


def inbox_wait_cmd(ab, name):
    return f"{ab} chat inbox --name {name} --wait {WAIT_S}"


def reply_cmd(ab, name, owner="{owner_cli}", reply_to=None):
    """The command that answers the human on the board. `owner` is a placeholder to fill later ({owner_cli}) or the human's name, which is quoted
    for the shell here (`--to` takes one word). `reply_to` is the number of the line being answered (the Stop hook knows it), so the answer threads."""
    to = owner if owner.startswith("{") else shlex.quote(owner)
    return f'{ab} chat send "<one line>" --name {name} --to {to}' + (f" --reply-to {reply_to}" if reply_to is not None else "")


REPLY_TO_HERE = "<the line's number>"   # in a prompt, the placeholder for the number of the line being answered (an answer names the line it answers)


# -- reporting ---------------------------------------------------------------------------------------------------------------------
REPORT_TEXT = (
    "Report to {owner} in one sentence, one idea: the ACTION they must take first, then one fact. If nothing is needed from them, one line of\n"
    "status. If more is unavoidable, one sentence, then offer the detail. Put that sentence on the card (agentboard ask/review/update text)\n"
    "so {owner} answers you there, and in your terminal. Put detail in `--body` (it shows under Details on the card), never in the first line."
)
REPORT_RULE = "## Reporting to {owner}\n\n" + REPORT_TEXT + "\n"


# -- finishing and waiting: one wording for an attended agent -----------------------------------------------------------------------
def wake(ab, card, name, after):
    """What to do right after `review` or `ask`: wait in the background, and what wakes the session. The full wording is for `review`; after an
    `ask` it is the same wait, said short."""
    if after == "ask":
        return (f"After `ask`, wait the same way: start `{answer_wait_cmd(ab, card)}` as a background command (in Claude Code, Bash with\n"
                "run_in_background) and end your turn. It prints {owner}'s reply, and then you carry on.")
    return (f"After `{after}`, do not sit idle: start `{answer_wait_cmd(ab, card)}` as a background command\n"
            "(in Claude Code, Bash with run_in_background) and end your turn. It wakes you, and prints what happened, when {owner} replies, sends the card\n"
            "back, closes it (\"Done by {owner}\"), moves it or removes it, or writes to you on the board (your thread, outside any card). A closed card\n"
            f"means you are free to go idle or take the next card; a message gets an answer, `{reply_cmd(ab, name, reply_to=REPLY_TO_HERE)}`, and then you start the wait again.\n"
            "A tool that cannot run background commands runs it in the foreground instead. If it times out with no reply, say you are still waiting.")


def reachable(ab, name):
    """What to do between cards, or any time the session would go quiet with nothing running."""
    return ("Between cards, and any other time you would go quiet with nothing running, keep yourself reachable the same way:\n"
            f"`{inbox_wait_cmd(ab, name)}` as a background command. It prints the next line {{owner}}\n"
            "sends you and exits, and that wakes you. Nothing else does. When it ends, start it again. The board shows who is listening,\n"
            "and a Stop hook reminds a session that is about to go quiet without one.")


def never_done(ab, card):
    return f"NEVER mark your own task done: run `{ab} done {card}` ONLY if {{owner}} explicitly tells you to."


def unattended_end(after):
    """What an unattended one-shot run (`agentboard run`, claude -p) does in place of waiting: it ends when the agent does, and nothing wakes it."""
    return (f"This is an unattended one-shot run: after `{after}`, stop. The run ends when you do and nothing can wake you afterwards, "
            "so do not start a background wait.")


# -- working with other agents and the shell: the lessons that cost real time ---------------------------------------------------------
_TAKE = "- Take only the cards you are handed or have claimed by name. With an ORCH running, that is the cards it assigns: do not claim a card because it sits in Todo."
_SHARE = ("- Other agents work in the same project. In a git project, work in your own worktree on your own branch (`git worktree add ../<project>-<card> -b <branch>`),\n"
          "  never edit the main checkout, never use `git stash` (every worktree shares one stash), and commit only your own changes.")
_SHARE_RUN = "- This run already has a folder of its own: stay in it, edit nothing outside it, and never use `git stash` (every worktree shares one stash)."
_BLOCKED = "- A card with an unfinished blocker will not claim. Do not use `--force`: tell your orchestrator in one line, and take another card."
_QUOTING = "- Never put a backtick or `$(` inside a double-quoted command argument: the shell runs it. Use single quotes, or put long text in a file and pass `--body-file`."


def working_rules(unattended=False):
    """The four lessons that cost real time, as a section. An unattended one-shot run is already in a worktree the board made, so it is told to stay
    in it instead of making its own (the one rule that differs, and it differs on purpose)."""
    return "## Working rules\n\n" + "\n".join([_TAKE, _SHARE_RUN if unattended else _SHARE, _BLOCKED, _QUOTING]) + "\n"


WORKING_RULES = working_rules()

ORCH_ONE_ID = "`done` takes one card id, and a second word after it is the note, not another card: run it once for each card."
