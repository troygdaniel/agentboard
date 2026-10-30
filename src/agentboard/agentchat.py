"""Agent chat: agents talking to each other on the board's shared channel, opt-in and board-wide.

Three pieces. The protocol: the block every prompt carries while the switch is on (how to send a line, address a peer, give a
heads-up on a shared file, propose an action, read the inbox, look things up). The memory: `recall` searches the cards, their
updates and their history (every agent's, archived ones too) and the chat, so an agent that lost context can read it back
instead of asking. The idle drafter: `draft_reply` turns an inbox and that memory into one short reply through the local
`claude` binary on a cheaper model, for an agent with nothing to do; it prints a draft, and only posts with --send.
All of it is local: the board file and, for the drafter only, the claude binary already on the machine (the same opt-in
exception SECURITY.md lists for one-shot runs). Chat never changes a card, spends, deploys or dials; Troy approves actions."""
import json
import re
import subprocess
from datetime import datetime

from .store import CHAT_TOPICS, BoardError

PROTOCOL = """\
## Talking to other agents (agent chat is on)

The shared chat is yours to use, with Troy watching. One plain line per message; the technical part goes in --detail and shows
on tap. Say who it is for; "all" when it is for everyone. Use your own name.

    {ab} chat send "<one line>" --name {name} --to AGENT-2 --topic help          # help: a question for a peer
    {ab} chat send "<one line>" --name {name} --to all --topic learn             # learn: something you found out that others will hit
    {ab} chat send "<one line>" --name {name} --topic heads-up --file static/index.html   # heads-up: before you edit a shared file
    {ab} chat send "<one line>" --name {name} --to AGENT-2 --topic handoff --card <id>    # handoff: what is done, what is left
    ... --detail "<the technical part>"   or   --detail-file <path>              # any of them: the detail behind the line
    ... --reply-to <n>                                                           # answering message n

Read what is for you, and answer it: before claiming a card, after each review, and whenever you are blocked.

    {ab} chat inbox --name {name}                  # unread, for you or for all; remembers where you got to
    {ab} chat inbox --name {name} --wait 120       # idle: block up to 120 s for the next message, then answer it

Lost the thread on something you or a peer did earlier? The board is the shared memory: cards, updates, history, every agent's.

    {ab} recall "<a few words>"                    # matching cards, with the lines of their history that matched, and chat
    {ab} recall --card <id>                        # one card's whole history
    {ab} recall --agent AGENT-2                    # what a peer has been doing
    ... or ask: {ab} chat send "<question>" --name {name} --to ORCH --topic help

Chat never does anything. An action that is not your card's own work (spend, deploy, dial, a change outside your card) is a
proposal: Troy approves it on the board, and you do it only after that.

    {ab} chat send "<one line>" --name {name} --propose "<the action, one line>"
    {ab} chat approvals --name {name}              # proposed / approved / declined, each with its number
"""

ORCH_PROTOCOL = """\
## Agent chat is on

Agents talk to each other on the shared chat: learnings, help, heads-ups on shared files, handoffs. Read it with
`{ab} chat inbox --name ORCH` and answer questions addressed to you. Actions proposed there wait for Troy's approval on the
board (`{ab} chat approvals`); never act on a proposal yourself.
"""

TOPIC_WORD = {"status": "status", "learn": "learned", "help": "help", "heads-up": "heads-up", "handoff": "handoff"}


def protocol(board_dir, name="<your session name>"):
    from . import prompt as promptlib
    return PROTOCOL.format(ab=promptlib.agentboard_cmd(board_dir), name=name)


def is_on(board_dir):
    """The board-wide switch, read without raising: a missing board means off."""
    try:
        from .store import Store
        return Store(board_dir).chat_agents()
    except (BoardError, OSError):
        return False


# ---- memory: recall over cards, history and chat ---------------------------------------------------------------------------
STOP = set("the a an and or of to in on for with is are was were be it this that at by from as into".split())


def _words(text):
    return [w for w in re.findall(r"[a-z0-9][a-z0-9_./-]{1,}", str(text or "").lower()) if w not in STOP]


def recall(tasks, chat, query="", agent=None, card=None, limit=10, log_lines=6):
    """Rows for what the board remembers about `query`: cards whose title, description, status, result or history mention the
    words (each with the history lines that matched), and chat lines that do. `agent` keeps one agent's cards; `card` returns
    that one card with its whole history. Archived and done cards count: they are the memory."""
    words = _words(query)
    rows = []
    for t in tasks:
        if card and t["id"] != card:
            continue
        if agent and (t.get("agent") or "").lower() != agent.lower():
            continue
        log = [e for e in t.get("log", []) if isinstance(e, dict)]
        if card:
            score, hits = 1, log
        else:
            head = " ".join(str(t.get(k) or "") for k in ("id", "title", "description", "status_text", "result", "agent")).lower()
            score = sum(3 if w in str(t.get("title") or "").lower() else 1 for w in words if w in head)
            hits = [e for e in log if any(w in str(e.get("text") or "").lower() for w in words)] if words else []
            score += min(len(hits), 3)
            if not score and words:
                continue
            if not words and not agent:
                continue
        rows.append({"kind": "card", "id": t["id"], "title": t["title"], "status": t["status"], "agent": t.get("agent") or "",
                     "updated": t.get("updated") or "", "archived": bool(t.get("archived")), "score": score,
                     "line": str(t.get("result") or t.get("status_text") or "")[:200],
                     "log": [{"at": e.get("at", ""), "status": e.get("status", ""), "progress": e.get("progress"), "text": str(e.get("text") or "")[:200], "by": e.get("by")}
                             for e in (hits if not card else log)[-(log_lines if not card else 200):]]})
    if words and not card:
        for m in chat:
            blob = (m.get("text", "") + " " + str(m.get("detail") or "")).lower()
            if agent and m.get("sender", "").lower() != agent.lower():
                continue
            if any(w in blob for w in words):
                rows.append({"kind": "chat", "seq": m["seq"], "at": m.get("at", ""), "sender": m.get("sender", ""), "to": m.get("to"),
                             "topic": m.get("topic"), "text": m.get("text", ""), "detail": m.get("detail"), "score": 1})
    rows.sort(key=lambda r: (-r["score"], r.get("updated") or r.get("at") or ""), reverse=False)
    rows.sort(key=lambda r: -r["score"])
    return rows[:limit] if not card else rows


def recall_lines(rows):
    """The same rows as text for a terminal: one line per card, its matching history under it; chat lines likewise."""
    out = []
    for r in rows:
        if r["kind"] == "card":
            flag = " (archived)" if r["archived"] else ""
            out.append(f"card  {r['id']}  [{r['status']}]  {r['agent'] or 'unassigned'}  {r['updated'][:16]}  {r['title']}{flag}")
            if r["line"]:
                out.append(f"      {r['line']}")
            for e in r["log"]:
                pct = f" {e['progress']}%" if e.get("progress") is not None else ""
                who = f" ({e['by']})" if e.get("by") else ""
                out.append(f"      {str(e['at'])[5:16]}  {e['status']}{pct}{who}  {e['text']}")
        else:
            to = f" -> {r['to']}" if r.get("to") else ""
            topic = f" ({r['topic']})" if r.get("topic") else ""
            out.append(f"chat  #{r['seq']}  {r['sender']}{to}{topic}  {str(r['at'])[5:16]}  {r['text']}")
            if r.get("detail"):
                out.append("      " + r["detail"].splitlines()[0][:200])
    return out


def chat_line(m):
    """One chat message for a terminal: number, time, who, to whom, topic, the line; the detail and the action under it."""
    who = f"{m['sender']} (you)" if m.get("kind") == "user" else m["sender"]
    to = f" -> {m['to']}" if m.get("to") else ""
    topic = f" [{m['topic']}]" if m.get("topic") and m["topic"] != "status" else ""
    head = f"#{m['seq']} [{m['at']}] {who}{to}{topic}: {m['text']}"
    extra = []
    if m.get("card"):
        extra.append(f"card {m['card']}")
    if m.get("files"):
        extra.append("files " + ", ".join(m["files"]))
    if m.get("reply_to"):
        extra.append(f"re #{m['reply_to']}")
    out = [head + (f"   ({'; '.join(extra)})" if extra else "")]
    if m.get("detail"):
        out += ["    " + l for l in m["detail"].splitlines()[:12]]
    if m.get("action"):
        a = m["action"]
        out.append(f"    proposes: {a['text']}  [{a['status']}" + (f" by {a['by']} {a['decided_at']}" if a.get("by") else "") + "]")
    return "\n".join(out)


# ---- the idle drafter: one reply on a cheaper model, from the inbox and the memory ------------------------------------------
DEFAULT_IDLE_MODEL = "haiku"       # the claude CLI's alias for its cheapest tier; [chat] idle_model in config.toml overrides it
DEFAULT_IDLE_BUDGET = 0.05         # dollars per draft, passed as --max-budget-usd
IDLE_TIMEOUT_S = 120

DRAFT_PROMPT = """\
You are {name}, one of several coding agents sharing a board with Troy (the human) and ORCH (the orchestrator). You have no
card right now. Below are the chat messages waiting for you and what the board remembers about recent work. Write ONE reply,
plain words, as a quick message to a teammate.

Rules: one line of at most 200 characters. If a technical detail helps, put it after a line that says DETAIL: (a few lines at
most). Start with TO: <name or all> and TOPIC: <learn|help|heads-up|handoff|status>. Never propose spending, deploying,
dialling or changing anything outside a card; if asked to, say Troy must approve it. If nothing needs a reply, answer exactly
NOTHING.

Messages for you (newest last):
{inbox}

What the board remembers (cards, updates, history):
{memory}
"""


def idle_conf(board_dir):
    from . import prompt as promptlib
    try:
        c = promptlib.load_config(board_dir).get("chat", {})
    except BoardError:
        c = {}
    return c if isinstance(c, dict) else {}


def parse_draft(text):
    """{'to', 'topic', 'text', 'detail'} from the model's answer, or None when it said NOTHING (or nothing usable)."""
    lines = [l.rstrip() for l in str(text or "").strip().splitlines()]
    if not lines or lines[0].strip().upper() == "NOTHING":
        return None
    out = {"to": None, "topic": None, "text": "", "detail": None}
    body = []
    for l in lines:
        m = re.match(r"^\s*(TO|TOPIC|DETAIL)\s*:\s*(.*)$", l, re.I)
        if m and m.group(1).upper() == "TO" and not out["to"]:
            out["to"] = m.group(2).strip() or None
        elif m and m.group(1).upper() == "TOPIC" and not out["topic"]:
            t = m.group(2).strip().lower()
            out["topic"] = t if t in CHAT_TOPICS else None
        elif m and m.group(1).upper() == "DETAIL":
            body.append("DETAIL:" + m.group(2))
        else:
            body.append(l)
    joined = "\n".join(body).strip()
    text, _, detail = joined.partition("DETAIL:")
    out["text"] = " ".join(text.split())[:200]
    out["detail"] = detail.strip() or None
    return out if out["text"] else None


def draft_reply(store, name, claude, model=None, budget=None, inbox=None, limit=8):
    """Ask the cheaper model for one reply to `name`'s inbox, with the board's memory for context. Returns parse_draft()'s
    dict or None. Only the local claude binary is run; the prompt goes on stdin, no permission is widened."""
    conf = idle_conf(store.dir)
    model = model or conf.get("idle_model") or DEFAULT_IDLE_MODEL
    budget = float(budget if budget is not None else conf.get("idle_budget_usd", DEFAULT_IDLE_BUDGET))
    inbox = inbox if inbox is not None else store.chat_inbox(name)[-limit:]
    if not inbox:
        return None
    tasks = store.load()
    words = " ".join(m["text"] for m in inbox)
    mem = recall(tasks, [], words, limit=4, log_lines=3) + recall(tasks, [], "", agent=name, limit=3, log_lines=3)
    prompt = DRAFT_PROMPT.format(name=name, inbox="\n".join(chat_line(m) for m in inbox) or "(none)",
                                 memory="\n".join(recall_lines(mem)) or "(nothing yet)")
    argv = [claude, "-p", "--output-format", "json", "--model", str(model), "--max-budget-usd", f"{budget:g}"]
    try:
        p = subprocess.run(argv, input=prompt, capture_output=True, text=True, timeout=IDLE_TIMEOUT_S)
    except OSError as e:
        raise BoardError(f"could not run claude: {e}") from e
    except subprocess.TimeoutExpired:
        raise BoardError("claude took too long to draft a reply") from None
    if p.returncode != 0:
        raise BoardError("claude failed to draft a reply: " + (p.stderr or p.stdout).strip().splitlines()[-1:][0] if (p.stderr or p.stdout).strip() else "claude failed to draft a reply")
    text = p.stdout
    try:   # the JSON result's text, else the raw output
        obj = json.loads(text.strip().splitlines()[-1])
        text = obj.get("result", "") if isinstance(obj, dict) else text
    except ValueError:
        pass
    return parse_draft(text)
