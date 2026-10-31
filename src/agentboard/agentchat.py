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
from datetime import datetime, timedelta

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

A message you send another session (SendMessage) is mirrored to this chat by a hook, so Troy sees the real conversation: run
`{ab} hooks install` once per project if `{ab} hooks status` says it is not there, and say who you are once (`{ab} me --name {name}`
or any claim/start/chat with --name) so the mirror carries your name.

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
## Agent chat is on: you take part

Agents talk to each other on the shared chat: learnings, help, heads-ups on shared files, handoffs. You are in it too.

- Now: post one line to all saying the chat is open and what it is for:
      {ab} chat send "chat is open: learnings, help, heads-ups on shared files, handoffs; one line each" --name ORCH --to all
- Whenever you are idle, read what is for you and answer it; this blocks until something arrives, then repeat it:
      {ab} chat inbox --name ORCH --wait 300
- A handoff with no taker: name who takes the card, in one line (--to that agent, --topic handoff, --card <id>).
- A help question for you: answer from the board (`{ab} recall "<words>"`) in one line, detail in --detail.
- When Troy flips the switch on with agents already running, tell each one to run `{ab} instructions` and follow its
  "Talking to other agents" section with its own name.
- Your messages to agents (SendMessage) are mirrored to the chat by a hook: run `{ab} hooks install` once per project
  (`{ab} hooks status` says whether it is there) and `{ab} me --name ORCH` once, so the mirror carries your name.
- Proposals (`{ab} chat approvals`) wait for Troy's approval on the board. Never act on one yourself, and never let an
  agent act on one; approval shows there, not in the chat.
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
                             for e in (log if (card or (agent and not words)) else hits)[-(log_lines if not card else 200):]]})   # one card, or one agent's cards: the history itself
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


def _age(stamp, now=None):
    t = _t(str(stamp or "")[:19])
    if not t:
        return ""
    m = int(((now or datetime.now()) - t).total_seconds() // 60)
    return "just now" if m < 1 else f"{m}m ago" if m < 60 else f"{m // 60}h ago" if m < 1440 else f"{m // 1440}d ago"


def recall_lines(rows, now=None):
    """The same rows as text for a terminal: one line per card, its matching history under it; chat lines likewise."""
    out = []
    for r in rows:
        if r["kind"] == "card":
            flag = " (archived)" if r["archived"] else ""
            out.append(f"card  {r['id']}  [{r['status']}]  {r['agent'] or 'unassigned'}  {r['updated'][:16]} ({_age(r['updated'], now)})  {r['title']}{flag}")
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
    if m.get("via") == "idle":
        extra.append("auto")
    if m.get("via") == "mirror":
        extra.append("mirrored")
    out = [head + (f"   ({'; '.join(extra)})" if extra else "")]
    if m.get("detail"):
        out += ["    " + l for l in m["detail"].splitlines()[:12]]
    if m.get("action"):
        a = m["action"]
        out.append(f"    proposes: {a['text']}  [{a['status']}" + (f" by {a['by']} {a['decided_at']}" if a.get("by") else "") + "]")
    return "\n".join(out)


# ---- casual: the same line in a spoken tone, for the panel --------------------------------------------------------------------
DEFAULT_CASUAL_PER_HOUR = 60
CASUAL_MIN_CHARS = 24          # a line this short is already a line

CASUAL_PROMPT = """\
Rewrite the message below as ONE line a colleague would say out loud across a desk: friendly, plain, short sentences,
contractions, the other person's name if there is one. Same facts, same names, same numbers and card ids; add nothing, drop
nothing that matters. No lists, no headings, no code, no quotes, no labels like ACTION or STATUS. At most 200 characters. If it
already reads that way, return it exactly as it is. Answer with the line only.

From {sender}{to}:
{text}
"""


def casual_eligible(m):
    """Agents' lines and mirrored messages get a spoken version; Troy's own lines, the board's notices and the drafter's
    (already in the voice) do not. A line that has one, or was looked at and left, is done."""
    return (m.get("kind") == "agent" and m.get("via") in (None, "mirror") and "said" not in m
            and len(m.get("text", "")) >= CASUAL_MIN_CHARS)


def casual_line(claude, model, budget, m):
    to = f" to {m['to']}" if m.get("to") else ""
    text = m["text"] + ((" " + m["detail"].splitlines()[0]) if m.get("detail") and len(m["text"]) < 60 else "")
    argv = [claude, "-p", "--output-format", "json", "--model", str(model), "--max-budget-usd", f"{budget:g}"]
    try:
        p = subprocess.run(argv, input=CASUAL_PROMPT.format(sender=m["sender"], to=to, text=text), capture_output=True, text=True, timeout=IDLE_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise BoardError(f"could not run claude: {e}") from e
    if p.returncode != 0:
        raise BoardError("claude failed to rephrase")
    out = p.stdout
    try:
        obj = json.loads(out.strip().splitlines()[-1])
        out = obj.get("result", "") if isinstance(obj, dict) else out
    except ValueError:
        pass
    line = " ".join(str(out or "").strip().strip('"').split())
    return line[:300]


def casual_once(store, claude, model=None, budget=None, per_hour=None, now=None, limit=10, log=None):
    """One round: give up to `limit` eligible messages (newest first) their spoken version, within the hourly cap.
    Returns the messages it touched. Shares the autopilot's state file for the cap."""
    now = now or datetime.now()
    conf = idle_conf(store.dir)
    model = model or conf.get("idle_model") or DEFAULT_IDLE_MODEL
    budget = float(budget if budget is not None else conf.get("idle_budget_usd", DEFAULT_IDLE_BUDGET))
    per_hour = int(per_hour if per_hour is not None else conf.get("casual_per_hour", DEFAULT_CASUAL_PER_HOUR))
    p = store.dir / "chat-casual.json"
    try:
        d = json.loads(p.read_text())
    except (OSError, ValueError):
        d = {}
    hour = now.strftime("%Y-%m-%dT%H")
    count = d.get("count", 0) if d.get("hour") == hour else 0
    done = []
    for m in [m for m in reversed(store.chat_list(limit=200)) if casual_eligible(m)][:limit]:
        if count >= per_hour:
            break
        try:
            said = casual_line(claude, model, budget, m)
        except BoardError as e:
            if log:
                log(f"casual: #{m['seq']}: {e}")
            break
        count += 1
        try:
            p.write_text(json.dumps({"hour": hour, "count": count}))
        except OSError:
            pass
        done.append(store.chat_set_said(m["seq"], said))
        if log:
            log(f"casual: #{m['seq']} {m['sender']}: {done[-1]['said'] or '(as written)'}")
    return done


# ---- the idle drafter: one reply on a cheaper model, from the inbox and the memory ------------------------------------------
DEFAULT_IDLE_MODEL = "haiku"       # the claude CLI's alias for its cheapest tier; [chat] idle_model in config.toml overrides it
DEFAULT_IDLE_BUDGET = 0.05         # dollars per draft, passed as --max-budget-usd
IDLE_TIMEOUT_S = 120

VOICE = """\
How to write: like two colleagues at a desk, not a report. Short sentences. Contractions. Say the other person's name. No lists,
no headings, no quotes around words. No code, paths or flags in the line; those go after DETAIL:. The line must read aloud as
speech. One idea per message. Never propose spending, deploying, dialling or changing anything outside a card; if asked to, say
Troy must approve it first."""

DRAFT_PROMPT = """\
You are {name}, one of several coding agents sharing a board with Troy (the human) and ORCH (the orchestrator). You have no
card right now. Today is {today}. Below are the chat messages waiting for you and what the board remembers about recent work.
Write ONE reply to the message that most needs you.

{voice}

Only say something that adds information. If your reply would only acknowledge, thank, agree, or say that you are idle or have
no card, answer exactly NOTHING. A card marked done, and any ask or question older than a day, is closed: never raise it as if
it were open. When you answer a question, end with one specific question back if there is a real one, so the thread can go on;
do not invent one. If nothing needs a reply, answer exactly NOTHING.

Format: start with TO: <name or all> and TOPIC: <learn|help|heads-up|handoff|status>, then the line (at most 200 characters),
then optionally DETAIL: and a few lines of the technical part.

Messages for you (newest last):
{inbox}

What the board remembers (cards, updates, history; the age is since the last change):
{memory}
"""

SHARE_PROMPT = """\
You are {name}, one of several coding agents sharing a board with Troy (the human) and ORCH (the orchestrator). You have no
card right now and nothing to answer. Today is {today}. Offer ONE thing from your own work that bears on what a colleague is
doing right now: a gotcha you hit, how something is actually wired, what a tool or service turned out to need. It must come
from your own history below, it must tie to one of the cards in progress below (say whose, and end with a short question to
them), and it must not repeat what the chat already says. If nothing you know touches what anyone is on, answer exactly NOTHING.
A generic tip nobody is about to need is NOTHING.

{voice}

Format: start with TO: <that agent's name> and TOPIC: learn, then the line (at most 200 characters), then optionally DETAIL:
and a few lines of the technical part.

Your own work (cards, updates, history, newest last; the age is since the last change):
{memory}

What the others are on right now:
{doing}

What the chat already says (newest last):
{chat}
"""


def idle_conf(board_dir):
    from . import prompt as promptlib
    try:
        c = promptlib.load_config(board_dir).get("chat", {})
    except BoardError:
        c = {}
    return c if isinstance(c, dict) else {}


def parse_draft(text):
    """{'to', 'topic', 'text', 'detail'} from the model's answer, or None when it said NOTHING (or nothing usable). The labels
    may sit on their own lines or run on inside the first line (TO: AGENT-2 TOPIC: help. the message…), as the model likes."""
    t = str(text or "").strip()
    if not t or t.upper().startswith("NOTHING"):
        return None
    out = {"to": None, "topic": None, "text": "", "detail": None}
    m = re.search(r"\bTO\s*:\s*([\w-]+)", t)
    if m:
        out["to"] = m.group(1)
        t = t[:m.start()] + t[m.end():]
    m = re.search(r"\bTOPIC\s*:\s*([A-Za-z-]+)", t)
    if m:
        topic = m.group(1).lower()
        out["topic"] = topic if topic in CHAT_TOPICS else None
        t = t[:m.start()] + t[m.end():]
    parts = re.split(r"\bDETAIL\s*:", t, maxsplit=1)
    body = re.sub(r"^[\s.,:;-]+", "", parts[0])
    out["text"] = " ".join(body.split())[:200]
    out["detail"] = parts[1].strip() or None if len(parts) > 1 else None
    return out if out["text"] else None


# ---- the autopilot: the drafter, run by the board itself for every idle agent with unread chat -------------------------------
DEFAULT_AUTOPILOT_EVERY = 180      # seconds between rounds
DEFAULT_AUTOPILOT_PER_HOUR = 12    # drafts an hour, over every agent: the spend ceiling is this times idle_budget_usd


def _cursors_path(store):
    return store.dir / "chat-cursors.json"


def read_cursors(store):
    try:
        d = json.loads(_cursors_path(store).read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def write_cursor(store, name, seq):
    cur = read_cursors(store)
    cur[name] = max(int(seq), cur.get(name, 0) if isinstance(cur.get(name), int) else 0)
    try:
        _cursors_path(store).write_text(json.dumps(cur))
    except OSError:
        pass


def _hour_count(store, now):
    """The autopilot's little state file: drafts this hour, and when each agent last shared something unprompted."""
    p = store.dir / "chat-autopilot.json"
    try:
        d = json.loads(p.read_text())
    except (OSError, ValueError):
        d = {}
    hour = now.strftime("%Y-%m-%dT%H")
    shared = d.get("shared") if isinstance(d.get("shared"), dict) else {}
    return p, (d.get("count", 0) if d.get("hour") == hour else 0), hour, shared


def _t(s):
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
    except (TypeError, ValueError):
        return None


def idle_agents(tasks, roster):
    """Roster agents with no card in Doing: the ones with time to talk."""
    busy = {t.get("agent") for t in tasks if t.get("status") == "doing" and t.get("agent")}
    return [n for n in roster if n and n not in busy]


DEFAULT_SHARE_EVERY_MIN = 60     # an idle agent with nothing to answer offers one thing from its own work this often, at most
DEFAULT_LIVE_MIN = 20            # an agent that spoke or touched a card this recently is awake: the board does not speak for it


def awake(tasks, chat, name, now, live_min):
    """Has `name` itself said or done anything in the last live_min minutes? (Its own real lines and card changes; not auto lines.)"""
    since = now - timedelta(minutes=live_min)
    if any(m.get("sender") == name and not m.get("via") and (_t(m.get("at")) or datetime.min) >= since for m in chat):
        return True
    return any(t.get("agent") == name and (_t(t.get("updated")) or datetime.min) >= since for t in tasks)


def autopilot_once(store, claude, roster, model=None, budget=None, per_hour=None, now=None, log=None, share_every_min=None, live_min=None):
    """One round: for each idle roster agent with unread chat, one draft on the cheaper model, posted as that agent with
    via=idle (shown as auto on the board; the agent's own session sees it in its inbox). The board never answers itself:
    an auto line is not a prompt for another round, so two idle agents cannot chatter at each other; real sessions may
    answer auto lines, and the hourly cap bounds the spend. Returns the messages posted."""
    now = now or datetime.now()
    conf = idle_conf(store.dir)
    per_hour = int(per_hour if per_hour is not None else conf.get("autopilot_per_hour", DEFAULT_AUTOPILOT_PER_HOUR))
    if not store.chat_agents():
        return []
    tasks = store.load()
    cursors = read_cursors(store)
    posted = []
    share_every_min = float(share_every_min if share_every_min is not None else conf.get("share_every_min", DEFAULT_SHARE_EVERY_MIN))
    live_min = float(live_min if live_min is not None else conf.get("live_min", DEFAULT_LIVE_MIN))
    recent = store.chat_list(limit=200)
    p, count, hour, shared = _hour_count(store, now)
    for name in idle_agents(tasks, roster):
        if count >= per_hour:
            break
        if awake(tasks, recent, name, now, live_min):   # its real session is talking or working: let it speak for itself
            continue
        after = cursors.get(name)
        inbox = [m for m in store.chat_inbox(name, after=after if isinstance(after, int) else None) if not m.get("via")]   # the board never answers itself (auto lines, its own notices)
        sharing = not inbox
        mine = None
        if sharing:   # nothing to answer: offer one thing from its own work, once in a while, and only if it has a history
            last = _t(shared.get(name))
            if share_every_min <= 0 or (last and (now - last).total_seconds() < share_every_min * 60):
                continue
            mine = own_history(store, name)
            doing = doing_now(tasks, recent, name)
            if not mine or not doing:   # nothing of its own to offer, or nobody on anything to tie it to: the model is not asked
                continue
        try:
            d = draft_share(store, name, claude, model=model, budget=budget, mine=mine, doing=doing) if sharing else draft_reply(store, name, claude, model=model, budget=budget, inbox=inbox)
        except BoardError as e:
            if log:
                log(f"autopilot: {name}: {e}")
            continue
        if sharing:
            shared[name] = now.strftime("%Y-%m-%dT%H:%M:%S")
        else:
            write_cursor(store, name, store.chat_list(limit=1)[-1]["seq"] if store.chat_list(limit=1) else inbox[-1]["seq"])
        count += 1
        try:
            p.write_text(json.dumps({"hour": hour, "count": count, "shared": shared}))
        except OSError:
            pass
        if not d:
            continue
        if sharing:
            m = store.chat_send(name, d["text"], to=d["to"] or "all", topic="learn", detail=d["detail"], via="idle")
        else:
            asked = next((m for m in reversed(inbox) if m.get("to") == name), inbox[-1])
            m = store.chat_send(name, d["text"], to=d["to"], topic=d["topic"], detail=d["detail"], reply_to=asked["seq"], via="idle")
        posted.append(m)
        if log:
            log("autopilot: " + chat_line(m).splitlines()[0])
    return posted


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
    prompt = DRAFT_PROMPT.format(name=name, voice=VOICE, today=datetime.now().strftime("%A %d %B %Y, %H:%M"),
                                 inbox="\n".join(chat_line(m) for m in inbox) or "(none)",
                                 memory="\n".join(recall_lines(mem)) or "(nothing yet)")
    return _ask_model(claude, model, budget, prompt)


def doing_now(tasks, chat, name=None):
    """One line per card in Doing (not `name`'s own): who, what, how far, and the files its heads-ups named."""
    files = {}
    for m in chat:
        if m.get("topic") == "heads-up" and m.get("files"):
            files.setdefault(m.get("card") or m.get("sender"), set()).update(m["files"])
    out = []
    for t in tasks:
        if t.get("status") != "doing" or t.get("parent_id") or not t.get("agent") or t["agent"] == name:
            continue
        fs = sorted(files.get(t["id"], set()) | files.get(t["agent"], set()))
        out.append(f"{t['agent']}: {t['title']} ({t.get('progress', 0)}%, {t.get('status_text') or 'no status yet'})" + (f"  files: {', '.join(fs)}" if fs else ""))
    return out


def own_history(store, name):
    """What `name` itself did: its cards with their history (the only thing it may share as its own)."""
    return recall(store.load(), [], "", agent=name, limit=6, log_lines=6)


def draft_share(store, name, claude, model=None, budget=None, recent_chat=12, mine=None, doing=None):
    """One thing from `name`'s own history that the others would not know, in the chat's voice, or None. Only its own cards
    feed the prompt, so it cannot speak for a peer; the recent chat is there so it does not repeat what was said."""
    conf = idle_conf(store.dir)
    model = model or conf.get("idle_model") or DEFAULT_IDLE_MODEL
    budget = float(budget if budget is not None else conf.get("idle_budget_usd", DEFAULT_IDLE_BUDGET))
    mine = own_history(store, name) if mine is None else mine
    if not mine:
        return None
    chat = store.chat_list(limit=200)
    doing = doing_now(store.load(), chat, name) if doing is None else doing
    if not doing:   # nobody is on anything: nothing to tie a share to
        return None
    prompt = SHARE_PROMPT.format(name=name, voice=VOICE, today=datetime.now().strftime("%A %d %B %Y, %H:%M"), memory="\n".join(recall_lines(mine)),
                                 doing="\n".join(doing), chat="\n".join(chat_line(m).splitlines()[0] for m in chat[-recent_chat:]) or "(nothing yet)")
    d = _ask_model(claude, model, budget, prompt)
    if d:
        d["topic"] = "learn"
        if not d["to"] or d["to"].lower() == "all":
            d["to"] = "all"
    return d


def _ask_model(claude, model, budget, prompt):
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
