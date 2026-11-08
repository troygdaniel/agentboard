"""Offline repros of the board-chat loss paths (docs/conversation-reliability-analysis.md). A THROWAWAY board in a temp folder, real `agentboard`
processes as the fake sessions, fake text only. Nothing touches a real board (AGENTBOARD_DIR points at the temp folder), nothing is sent anywhere.

    python3 tests/chat_repro.py          # about a minute; prints one line per loss path (R1 to R11), the ids the analysis uses

Not a unit test (the name does not start with test_): it is the evidence, and the starting point of the QA card that turns each line into a test."""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
sys.dont_write_bytecode = True
sys.path.insert(0, SRC)
from agentboard import cursors, hooks, listeners  # noqa: E402
from agentboard.store import BoardError, Store  # noqa: E402

TMP = Path(tempfile.mkdtemp())
BOARD = TMP / ".agentboard"
BOARD.mkdir()
(BOARD / "config.toml").write_text('[board]\nowner = "Troy"\n')
S = Store(BOARD)
S.add("seed card")
ENV = {"HOME": str(TMP), "PATH": os.environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": SRC, "AGENTBOARD_DIR": str(BOARD)}
OUT = []


def say(tag, text):
    print(f"{tag:5} {text}", flush=True)
    OUT.append((tag, text))


def cli(*args, name=None, env=None, stdout=subprocess.PIPE, stdin=None):
    e = dict(ENV, **(env or {}))
    if name:
        e["AGENTBOARD_NAME"] = name
    return subprocess.Popen([sys.executable, "-m", "agentboard", *args], env=e, stdout=stdout, stderr=subprocess.STDOUT, stdin=stdin, text=True)


def run(*args, name=None, env=None, input=None):
    e = dict(ENV, **(env or {}))
    if name:
        e["AGENTBOARD_NAME"] = name
    r = subprocess.run([sys.executable, "-m", "agentboard", *args], env=e, capture_output=True, text=True, input=input, timeout=60)
    return r.returncode, (r.stdout + r.stderr).strip()


def owner_says(text, to=None):
    return S.chat_send("Troy", text, kind="user", to=to)


# ---- R1: a healthy session -------------------------------------------------------------------------------------------------------------
lat = []
for i in range(6):
    p = cli("chat", "inbox", "--name", f"R1-{i}", "--wait", "30", name=f"R1-{i}")
    time.sleep(1.2)
    t0 = time.time()
    owner_says("ping", to=f"R1-{i}")
    p.wait(timeout=20)
    lat.append(time.time() - t0)
say("R1", f"healthy wait, default poll 2 s: wake latency min {min(lat):.1f} s, max {max(lat):.1f} s over {len(lat)} lines (the process exits with the line)")

# ---- R2: read before seen ----------------------------------------------------------------------------------------------------------------
p = cli("chat", "inbox", "--name", "R2", "--wait", "30", name="R2", stdout=subprocess.DEVNULL)   # the session died / never read the output
time.sleep(1.2)
m = owner_says("did you get this?", to="R2")
p.wait(timeout=20)
cur = cursors.get(BOARD, "R2")
code, again = run("chat", "inbox", "--name", "R2", name="R2")
say("R2", f"line #{m['seq']} printed to a reader that was gone: cursor now {cur} (the board counts it READ); the next inbox says: {again!r} -> the line is lost for good")

# ---- R3: a stopped wait ------------------------------------------------------------------------------------------------------------------
p = cli("chat", "inbox", "--name", "R3", "--wait", "600", name="R3")
time.sleep(1.2)
before = listeners.is_listening(BOARD, "R3")
os.kill(p.pid, signal.SIGKILL)
p.wait()
time.sleep(0.2)
m = owner_says("are you there?", to="R3")
stale = json.loads((BOARD / listeners.FILE).read_text()).get("R3")
say("R3", f"wait killed (the user typed in the terminal / the session ended): listening before={before}, after={listeners.is_listening(BOARD, 'R3')} (stale file entry still there: {bool(stale)}); "
          f"line #{m['seq']} waits unread for as long as nobody looks: {len(S.chat_inbox('R3', after=cursors.get(BOARD, 'R3')))} unread")

# ---- R4: two sessions with one name -----------------------------------------------------------------------------------------------------
a = cli("chat", "inbox", "--name", "R4", "--wait", "600", name="R4")
time.sleep(1.2)
b = cli("chat", "inbox", "--name", "R4", "--wait", "3", name="R4")   # a second AGENT-N row: same name, shorter wait
time.sleep(1.2)
entry = listeners.listening(BOARD).get("R4")
owner_says("one line, two sessions", to="R4")
oa, ob = a.communicate(timeout=20)[0], b.communicate(timeout=20)[0]
got = sum(1 for o in (oa, ob) if "one line, two sessions" in o)
say("R4a", f"two sessions named R4 and one line to R4: {got} of 2 sessions got it (both will answer); the registry held {1 if entry else 0} entry for the pair while both ran")
a = cli("chat", "inbox", "--name", "R4", "--wait", "600", name="R4")
time.sleep(1.2)
b = cli("chat", "inbox", "--name", "R4", "--wait", "2", name="R4")
b.communicate(timeout=20)
say("R4b", f"the second one's wait ends (timeout): the first is still running (pid alive={listeners.alive(a.pid)}) but the board says listening={listeners.is_listening(BOARD, 'R4')} -> a false 'nobody is listening' warning")
a.kill()
a.wait()

# ---- R5: server restart ------------------------------------------------------------------------------------------------------------------
n = len(Store(BOARD).chat_list(limit=1000))
say("R5", f"chat, cursors and listeners are files in the board folder; a second Store (what a restarted server is) sees all {n} lines. The server keeps no chat state in memory (only the autopilot timer): a restart loses nothing")

# ---- R6: a name nobody has --------------------------------------------------------------------------------------------------------------
S.set_chat_agents(True)
for typo in ("AGENT-33", "Agent 3", "agent3 "):
    try:
        m = S.chat_send("R6", "hello?", kind="agent", to=typo)
        res = "accepted silently"
    except BoardError as e:
        res = f"refused: {str(e)[:60]}"
    say("R6", f"line to {typo!r}: {res}; nobody named that is listening, nothing tells the sender")
S.set_chat_agents(False)

# ---- R7: reads at the same instant -------------------------------------------------------------------------------------------------
lost_total, runs_total = 0, 0
for rnd in range(8):
    names = [f"R7-{rnd}-{i}" for i in range(20)]
    owner_says("to everyone", to="all")
    go = time.time() + 6
    code = ("import sys,time,os; sys.argv=['agentboard','chat','inbox','--name',os.environ['AGENTBOARD_NAME']]; from agentboard.cli import main; "
            f"time.sleep(max(0,{go}-time.time())); main(sys.argv[1:])")
    procs = []
    for n in names:
        e = dict(ENV, AGENTBOARD_NAME=n)
        procs.append(subprocess.Popen([sys.executable, "-c", code], env=e, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    for p in procs:
        p.wait(timeout=60)
    cur = cursors.read(BOARD)
    lost_total += sum(1 for n in names if cursors.key(n) not in cur)
    runs_total += len(names)
say("R7", f"{runs_total} sessions reading at the same instant (8 rounds of 20): {lost_total} cursor updates lost (chat-cursors.json: a locked, forward-only, atomic write since rev1107-stophook-case; before it, 39 of 160 were lost). A lost cursor means the same lines come again and the 'read' receipt is wrong; it never loses a line")

# ---- R8: more unread than one read shows --------------------------------------------------------------------------------------------------
for i in range(60):
    owner_says(f"line {i}", to="R8")
code, out = run("chat", "inbox", "--name", "R8", name="R8")
shown = len([l for l in out.splitlines() if l.startswith("#")])
code2, out2 = run("chat", "inbox", "--name", "R8", name="R8")
say("R8", f"60 unread lines: one read shows {shown} and moves the cursor past all 60; the next read says {out2!r} -> {60 - shown} lines lost silently (default --limit)")

# ---- R9: the log keeps 500 ---------------------------------------------------------------------------------------------------------------
for i in range(520):
    S.chat_send("R9-bulk", f"filler {i}", kind="agent")
first = S.chat_list(limit=1000)[0]["seq"]
say("R9", f"after 520 more lines the log starts at #{first}: a session whose cursor is older than that (away for ~500 lines) never sees what was cut")

# ---- R10: replies the board refuses while agent chat is off ------------------------------------------------------------------------------------
S.set_chat_agents(False)
cases = [
    ("plain one-line reply to the owner", dict(text="done", to="Troy")),
    ("reply to the owner with --reply-to (a threaded reply)", dict(text="done", to="Troy", reply_to=owner_says("question?", to="R10")["seq"])),
    ("reply to the owner with --topic status", dict(text="done", to="Troy", topic="status")),
    ("reply to the owner with --topic help", dict(text="need help", to="Troy", topic="help")),
    ("two-line reply to the owner (the second line becomes a detail)", dict(text="done\nhere is more")),
    ("reply to the owner with --detail", dict(text="done", to="Troy", detail="the long part")),
    ("a reply over 300 characters, told to use --detail", dict(text="x" * 320, to="Troy")),
    ("reply to the owner naming a card", dict(text="done", to="Troy", card=S.load()[0]["id"])),
    ("a line to ORCH (agent to agent)", dict(text="done", to="ORCH")),
    ("a line to all", dict(text="done", to="all")),
]
for label, kw in cases:
    kw2 = dict(kw)
    text = kw2.pop("text")
    row = []
    for flag in (False, True):
        S.set_chat_agents(flag)
        try:
            S.chat_send("R10", text, kind="agent", **kw2)
            row.append("posts")
        except BoardError:
            row.append("REFUSED")
    say("R10", f"{label:62} agent chat off: {row[0]:8} on: {row[1]}")
S.set_chat_agents(False)

# ---- R11: the Stop hook --------------------------------------------------------------------------------------------------------------------
payload = json.dumps({"session_id": "abc", "stop_hook_active": False})
owner_says("unread thread line", to="R11")
code, o1 = run("hook", "stop", input=payload, env={"AGENTBOARD_DIR": ""}, name="R11")       # a home-folder session: no board in its environment
code, o2 = run("hook", "stop", input=payload, name=None)                                       # board found, but the session never said who it is
code, o3 = run("hook", "stop", input=payload, name="R11")                                      # board and name known, an unread owner line
listeners.register(BOARD, "R11b", "inbox", pid=os.getpid())
code, o4 = run("hook", "stop", input=payload, name="R11b")                                     # listening, nothing unread
say("R11", f"stop hook: no board in env -> {o1[:40]!r}; board but no name -> {o2[:40]!r}; name + unread owner line -> {'BLOCKS: ' + o3[:70] if o3 else 'nothing'}; name + listening + nothing unread -> {o4[:30]!r}")
say("R11", "the hook only works where it is installed and where the session can find the board: check `agentboard hooks status --project <folder>` for each folder sessions start in")

print("\nDONE", TMP)
