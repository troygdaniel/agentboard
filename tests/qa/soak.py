"""Soak a throwaway board (overnight-qa-cleanroom): hundreds of cards, many fake agents working at once through the CLI, the server
restarted again and again, every page and API read after each restart, backups, chat and hook flows. Prints PASS/FAIL lines.

    python3 tests/qa/soak.py <scratch dir> src [--cards 400] [--agents 12] [--restarts 10] [--port 8976]   # from the repo root

Everything lives under <root dir>; nothing touches a real board. Uses the CLI as a subprocess (what agents do) for the agent work and the
Store for bulk seeding."""
import json
import os
import random
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(sys.argv[1]).expanduser().resolve()
SRC = str(Path(sys.argv[2]).resolve())   # absolute: the agents' subprocesses run from the scratch dir
MARK = ".agentboard-qa-scratch"   # the scratch dir is the only thing this script deletes, and only one it made itself (the marker says so)
home = Path.home().resolve()
if ROOT in (Path("/"), home) or ROOT.name == ".agentboard" or home not in ROOT.parents and not str(ROOT).startswith(("/tmp", "/private/tmp", "/var/folders")):
    sys.exit(f"soak: refusing to use {ROOT} as the scratch dir (give a fresh folder under your home or /tmp)")
if ROOT.exists() and not (ROOT.is_dir() and (ROOT / MARK).is_file()):
    sys.exit(f"soak: {ROOT} exists and is not a scratch dir this script made (no {MARK} inside): refusing to delete it")
opts = {"--cards": 400, "--agents": 12, "--restarts": 10, "--port": 8790}
for k in opts:
    if k in sys.argv:
        opts[k] = int(sys.argv[sys.argv.index(k) + 1])
N_CARDS, N_AGENTS, N_RESTARTS, PORT = opts["--cards"], opts["--agents"], opts["--restarts"], opts["--port"]
if ROOT.exists():
    shutil.rmtree(ROOT)
PROJ = ROOT / "proj"
PROJ.mkdir(parents=True)
(ROOT / MARK).write_text("made by tests/qa/soak.py: safe to delete\n")
BOARD = PROJ / ".agentboard"
ENV = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
ENV.update({"PYTHONPATH": SRC, "HOME": str(ROOT / "home"), "AGENTBOARD_DIR": str(BOARD), "PYTHONDONTWRITEBYTECODE": "1"})
(ROOT / "home").mkdir()
os.umask(0o077)   # the CLI and server set this for themselves (private.py); the seeding below goes through the Store directly, so match them
sys.path.insert(0, SRC)
results = []


def step(name, ok, note=""):
    results.append((name, bool(ok), note))
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{note}]" if note else ""), flush=True)


def cli(*args, name=None, check=False, timeout=60, stdin=None):
    env = dict(ENV)
    if name:
        env["AGENTBOARD_NAME"] = name
    r = subprocess.run([sys.executable, "-m", "agentboard", *args], cwd=PROJ, env=env, capture_output=True, text=True, timeout=timeout, input=stdin)
    if check and r.returncode != 0:
        raise RuntimeError(f"agentboard {' '.join(args)} -> {r.returncode}: {r.stderr.strip()[:300]}")
    return r


def get(path, timeout=10):
    t0 = time.time()
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=timeout) as r:
        body = r.read()
        return r.status, body, time.time() - t0


def tasks():
    d = json.loads((BOARD / "tasks.json").read_text())
    return d["tasks"] if isinstance(d, dict) else d   # the file is {"tasks": [...], ...}


def valid_json(path):
    try:
        json.loads(Path(path).read_text())
        return True
    except (OSError, ValueError):
        return False


# -- init and seed --------------------------------------------------------------------------------------------------------------------
subprocess.run(["git", "init", "-q", "."], cwd=PROJ, check=True)
r = cli("init")
step("init", r.returncode == 0 and (BOARD / "tasks.json").exists(), r.stderr.strip()[:120])
from agentboard.store import Store   # noqa: E402  (after init, so the dir exists)
s = Store(BOARD)
t0 = time.time()
for i in range(N_CARDS):
    s.add(f"Soak card {i:04d}: {random.choice(['fix', 'review', 'write', 'test', 'deploy'])} {random.choice(['the parser', 'the HUD', 'backups', 'chat', 'the docs'])}",
          f"seeded for the soak, card {i}\n\n" + "line of detail\n" * random.randint(0, 20))
seed_s = time.time() - t0
step(f"seed {N_CARDS} cards through the Store", len(tasks()) >= N_CARDS, f"{seed_s:.1f} s")
r = cli("list")
step("list with hundreds of cards", r.returncode == 0 and r.stdout.count("\n") >= N_CARDS, f"{r.stdout.count(chr(10))} lines")

# -- many agents at once through the CLI -----------------------------------------------------------------------------------------------
ids = [t["id"] for t in tasks() if t.get("status") in ("todo", "backlog")]
random.shuffle(ids)
errors, lock = [], threading.Lock()


def agent(n, mine):
    name = f"AGENT-{n}"
    try:
        for cid in mine:
            cli("claim", cid, name=name, check=True)
            for pct in (25, 50, 75):
                cli("update", cid, str(pct), f"{name} at {pct}", name=name, check=True)
            cli("chat", "send", f"{name} is on {cid}", name=name)
            if n % 3 == 0:
                cli("ask", cid, f"{name} needs a word on {cid}", name=name)
            else:
                cli("review", cid, f"{name} finished {cid}", name=name, check=True)
    except Exception as e:   # noqa: BLE001
        with lock:
            errors.append(f"{name}: {e}")


per = max(1, min(6, len(ids) // N_AGENTS))
threads = [threading.Thread(target=agent, args=(n + 1, ids[n * per:(n + 1) * per])) for n in range(N_AGENTS)]
t0 = time.time()
for th in threads:
    th.start()
for th in threads:
    th.join()
work_s = time.time() - t0
step(f"{N_AGENTS} agents x {per} cards each through the CLI at once", not errors, f"{work_s:.0f} s; " + ("; ".join(errors[:3]) if errors else "no CLI error"))
after = {t["id"]: t for t in tasks()}
touched = [cid for cid in ids[:N_AGENTS * per]]
def settled(t):   # ask leaves the card doing at 75 with needs_input; review leaves it doing at 100 with the review flag
    return t.get("status") == "doing" and ((t.get("progress") == 75 and t.get("needs_input")) or (t.get("progress") == 100 and t.get("review")))
lost = [cid for cid in touched if not settled(after[cid])]
step("no agent's update was lost (every touched card is at its last state: asked at 75, or in review at 100)", not lost, f"{len(lost)} off: {lost[:5]}")
step("tasks.json is valid JSON after the burst", valid_json(BOARD / "tasks.json"))
step("tasks.json.bak exists and is valid", valid_json(BOARD / "tasks.json.bak"))
r = cli("chat", "tail", name="ORCH")
step("chat tail shows the agents' lines", r.returncode == 0 and r.stdout.count("is on") >= N_AGENTS, f"{r.stdout.count('is on')} lines")
cli("chat", "inbox", "--name", "AGENT-1", "--limit", "0")   # read ALL of it (a plain read shows one page), so the wait below starts with nothing unread
r = cli("chat", "inbox", "--name", "AGENT-1", "--wait", "3")
step("chat inbox --wait with nothing unread exits 1 at the timeout", r.returncode == 1, f"exit {r.returncode}; printed: " + " | ".join(r.stdout.strip().splitlines()[-2:])[:200])


def wake():
    time.sleep(1.5)
    cli("chat", "send", "AGENT-2: have a look at the parser", name="ORCH")


threading.Thread(target=wake).start()
t0 = time.time()
r = cli("chat", "inbox", "--name", "AGENT-2", "--wait", "20")
step("chat inbox --wait wakes on a line for the agent", r.returncode == 0 and "parser" in r.stdout and time.time() - t0 < 15, f"exit {r.returncode}, {time.time() - t0:.1f} s")
r = cli("doctor")
doc_fail = [l for l in (r.stdout + r.stderr).splitlines() if l.startswith("FAIL")]
step("doctor runs on the soaked board with no FAIL line", r.returncode == 0 and not doc_fail, "; ".join(doc_fail)[:200] or (r.stdout + r.stderr).strip().splitlines()[-1][:120])

# -- the server: restarts, pages, APIs, timings ---------------------------------------------------------------------------------------
PAGES = ["/", "/hud", "/index.html", "/api/tasks", "/api/hud", "/api/chat", "/api/boards", "/api/config"]   # the GET routes (state and chat-agents are POST)
slow, bad, tracebacks = [], [], 0
log = ROOT / "serve.log"
for i in range(N_RESTARTS):
    with open(log, "a") as lf:
        p = subprocess.Popen([sys.executable, "-m", "agentboard", "serve", "--no-open", "--port", str(PORT)], cwd=PROJ, env=ENV, stdout=lf, stderr=subprocess.STDOUT)
    up = False
    for _ in range(100):
        try:
            get("/api/tasks", timeout=2)
            up = True
            break
        except Exception:   # noqa: BLE001
            time.sleep(0.1)
    if not up:
        bad.append(f"restart {i}: never came up")
    else:
        for path in PAGES:
            try:
                st, body, dt = get(path)
                if st != 200 or not body:
                    bad.append(f"restart {i} {path}: {st} {len(body)} bytes")
                if dt > 2:
                    slow.append(f"{path} {dt:.1f}s")
                if path.startswith("/api/"):
                    json.loads(body)
            except Exception as e:   # noqa: BLE001
                bad.append(f"restart {i} {path}: {e.__class__.__name__}: {str(e)[:80]}")
        # a few writes through the API while it runs: move, edit
        cid = random.choice(touched)
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/edit", data=json.dumps({"id": cid, "title": f"edited at restart {i}"}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=10) as r:
                r.read()
        except Exception as e:   # noqa: BLE001
            bad.append(f"restart {i} POST /api/edit: {e.__class__.__name__}: {str(e)[:120]}")
        if not valid_json(BOARD / "tasks.json"):
            bad.append(f"restart {i}: tasks.json invalid while serving")
    p.terminate()
    try:
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill()
        bad.append(f"restart {i}: server did not stop on SIGTERM")
tracebacks = log.read_text(errors="replace").count("Traceback")
step(f"{N_RESTARTS} restarts: came up, every page and API answered 200 with JSON where expected", not bad, "; ".join(bad[:4]))
step("no page or API took over 2 s", not slow, "; ".join(slow[:5]))
step("server log has no Traceback", tracebacks == 0, f"{tracebacks} tracebacks")
step("tasks.json valid after all restarts", valid_json(BOARD / "tasks.json"))
snaps = list((BOARD / "backups").glob("tasks-*.json.gz")) if (BOARD / "backups").exists() else []
step("a backup snapshot exists", len(snaps) >= 1, f"{len(snaps)} snapshots")
r = cli("verify")
step("agentboard verify on the soaked board", r.returncode == 0, (r.stdout + r.stderr).strip().splitlines()[-1][:120] if (r.stdout + r.stderr).strip() else "")
r = cli("backup")
step("agentboard backup", r.returncode == 0, (r.stdout + r.stderr).strip()[:120])

# -- hooks with fake sessions --------------------------------------------------------------------------------------------------------
r = cli("hooks", "install")
settings = PROJ / ".claude" / "settings.json"
step("hooks install writes .claude/settings.json with both hooks", r.returncode == 0 and settings.exists() and "PostToolUse" in settings.read_text() and '"Stop"' in settings.read_text(), r.stderr.strip()[:120])
sid = "sess-fake-0001"
r = cli("chat", "agents", "on", name="ORCH")   # the mirror posts only while agent chat is on (by design); the owner turns it on
step("chat agents on (the owner's switch)", r.returncode == 0, (r.stdout + r.stderr).strip()[:120])
cli("me", "--name", "AGENT-9", "--session", sid, name="AGENT-9")
payload = {"session_id": sid, "hook_event_name": "PostToolUse", "tool_name": "SendMessage",
           "tool_input": {"to": "ORCH", "message": "AGENT-9: the soak hook line\nmore detail here", "summary": "soak"}}
r = cli("hook", "send-message", stdin=json.dumps(payload))
tail = cli("chat", "tail", name="ORCH").stdout
step("hook send-message mirrors the line to chat as the session's name", r.returncode == 0 and "soak hook line" in tail and "AGENT-9" in tail, f"exit {r.returncode}; {r.stderr.strip()[:100]}")
r = cli("hook", "send-message", stdin="not json at all {{{")
step("hook send-message with garbage on stdin exits 0 quietly", r.returncode == 0 and not r.stderr.strip(), f"exit {r.returncode}")
cli("chat", "send", "AGENT-9: please answer this before you stop", name="ORCH")
r = cli("hook", "stop", stdin=json.dumps({"session_id": sid, "hook_event_name": "Stop", "stop_hook_active": False}))
out = r.stdout.strip()
blocked = False
try:
    blocked = json.loads(out).get("decision") == "block"
except ValueError:
    pass
step("hook stop blocks once when the owner's line is unread", r.returncode == 0 and blocked, out[:160])
r = cli("hook", "stop", stdin=json.dumps({"session_id": sid, "hook_event_name": "Stop", "stop_hook_active": True}))
step("hook stop never blocks twice in a row (stop_hook_active)", r.returncode == 0 and "block" not in r.stdout, r.stdout.strip()[:120])

# -- the summary -----------------------------------------------------------------------------------------------------------------------
fails = [n for n, ok, _ in results if not ok]
print(f"\nSOAK: {len(results) - len(fails)} of {len(results)} checks passed; cards {len(tasks())}; agents {N_AGENTS}; restarts {N_RESTARTS}")
for n in fails:
    print("  FAIL", n)
(ROOT / "soak-results.json").write_text(json.dumps(results, indent=1))
sys.exit(1 if fails else 0)
