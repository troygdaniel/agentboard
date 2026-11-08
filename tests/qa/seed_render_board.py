"""Seed a throwaway board for the render check (overnight-qa-cleanroom): mixed cards, six agents, asks, reviews, done cards, chat lines.

    python3 tests/qa/seed_render_board.py <scratch dir> src     # then: AGENTBOARD_DIR=<scratch>/proj/.agentboard python3 -m agentboard serve --no-open --port <port>

Everything is made up. The scratch dir must not exist yet, or hold the marker a previous run wrote; nothing else is touched."""
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]).expanduser().resolve()
SRC = str(Path(sys.argv[2]).resolve())
MARK = ".agentboard-qa-scratch"
home = Path.home().resolve()
if ROOT in (Path("/"), home) or ROOT.name == ".agentboard" or (home not in ROOT.parents and not str(ROOT).startswith(("/tmp", "/private/tmp", "/var/folders"))):
    sys.exit(f"seed: refusing to use {ROOT} as the scratch dir")
if ROOT.exists() and not (ROOT.is_dir() and (ROOT / MARK).is_file()):
    sys.exit(f"seed: {ROOT} exists and is not a scratch dir this script made: refusing to delete it")
if ROOT.exists():
    shutil.rmtree(ROOT)
PROJ = ROOT / "proj"
PROJ.mkdir(parents=True)
(ROOT / MARK).write_text("made by tests/qa/seed_render_board.py: safe to delete\n")
(ROOT / "home").mkdir()
os.umask(0o077)
ENV = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
ENV.update({"PYTHONPATH": SRC, "HOME": str(ROOT / "home"), "AGENTBOARD_DIR": str(PROJ / ".agentboard")})
subprocess.run(["git", "init", "-q", "."], cwd=PROJ, check=True)


def cli(*a, name=None, user=False):
    env = dict(ENV)
    if name:
        env["AGENTBOARD_NAME"] = name
    subprocess.run([sys.executable, "-m", "agentboard", *a, *(["--user"] if user else [])], cwd=PROJ, env=env, capture_output=True, text=True)


cli("init")
sys.path.insert(0, SRC)
from agentboard.store import Store   # noqa: E402
s = Store(PROJ / ".agentboard")
random.seed(4)
verbs = ["Fix", "Review", "Write", "Test", "Design", "Refactor"]
things = ["the parser", "the HUD legend", "backups", "chat receipts", "the docs", "the drag handles", "keyboard focus", "the Done panel"]
ids = []
for i in range(36):
    t = s.add(f"{random.choice(verbs)} {random.choice(things)} {i:02d}", "Seeded on a throwaway board for the render check.\n\n- a detail line\n- another, with `code`\n\n"
              + ("A long paragraph of filler text to see how the panel wraps. " * random.randint(1, 6)))
    ids.append(t["id"])
ids.append(s.add("A very long card title that goes on and on to see how the card wraps at narrow widths without breaking the column layout at all", "long")["id"])
ids.append(s.add("Tiny", "")["id"])
agents = ["AGENT-1", "AGENT-2", "AGENT-3", "AGENT-4", "GENERAL", "ORCH"]
for n, cid in enumerate(ids[:18]):
    name = agents[n % len(agents)]
    cli("claim", cid, name=name)
    cli("add", "do it", "--parent", cid)
    cli("add", "check it", "--parent", cid)
    subs = [t["id"] for t in s.load() if t.get("parent") == cid]
    if subs:
        cli("update", subs[0], str(random.choice([25, 50, 75, 100])), f"{name} working", name=name)
    if n % 5 == 0:
        cli("ask", cid, f"{name}: which port should this use?", name=name)
    elif n % 5 == 1:
        cli("review", cid, f"{name}: done, please check", name=name)
for cid in ids[18:26]:
    cli("done", cid)
for cid in ids[26:30]:
    cli("move", cid, "todo")
for name in agents:
    cli("chat", "send", f"{name} is on the render board, shout if you need me", name=name)
cli("chat", "send", "ORCH: nice work everyone, keep the titles short", user=True)
cli("hooks", "install")
print(f"seeded {len(s.load())} cards in {PROJ / '.agentboard'}")
