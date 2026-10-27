"""One-shot agents: `agentboard run <card>` starts a non-interactive `claude -p` on a card, watches it, and moves the card on exit.

What it does, in order: builds the card's prompt (the same text as Copy prompt, plus a short rules block), finds or creates a git
worktree to work in, claims the card, launches `claude -p` with a budget cap, watches it against a wall-clock limit and a kill
switch, then moves the card to review (or ask, with the tail of the output, if it failed), records cost and duration, and removes the
worktree only if it created it and it is clean.

Permissions: the run uses the settings an interactive agent in that folder would. No flag that widens them is ever passed (no
--dangerously-skip-permissions, no --permission-mode, no --allowedTools): see test_runs.py. Per-run files live in
.agentboard/runs/<card>/<run id>/ (run.json, prompt.md, stdout.json, stderr.log)."""
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from . import prompt as promptlib
from .store import BoardError

DEFAULT_BUDGET_USD = 5.0
DEFAULT_MAX_MINUTES = 45.0
KILL_GRACE_S = 10
POLL_S = 0.4

RULES = """\

## Rules for this run

You are running unattended as `{name}`: nobody is watching this terminal, and nobody can answer a permission prompt.
Your work is judged from the card, so keep it current: `{ab} update {task_id} <percent> "<one line>"` as you go.

- Work only on this card, inside this folder. Read the repo's CLAUDE.md first and follow it.
- Finish with `{ab} review {task_id} "<one-line result>"` and stop. Never mark the card done: the user does.
- Blocked on the user? `{ab} ask {task_id} "<one-line question>"` and stop; do not guess.
- Never place calls or send texts, emails or messages to anyone, never buy or subscribe to anything, never deploy, and never
  touch production data or accounts. If the card needs one of those, ask instead.
- Do not try to widen your own permissions or work around a refused tool: say so in your review or ask.
- Reports are three lines, no more: ACTION (who must do what next), STATUS (where it stands), WHY (the one reason that matters).
- Hard limits: {minutes:g} minutes and ${budget:g}. The run is stopped when either is reached.
"""


def runs_dir(board_dir):
    return Path(board_dir) / "runs"


def run_conf(board_dir):
    try:
        c = promptlib.load_config(board_dir)
    except BoardError:
        c = {}
    r = c.get("run", {})
    return r if isinstance(r, dict) else {}


def claude_binary(board_dir):
    """$AGENTBOARD_CLAUDE, then [run] claude in config.toml, then `claude` on PATH."""
    path = os.environ.get("AGENTBOARD_CLAUDE") or run_conf(board_dir).get("claude") or shutil.which("claude")
    if not path:
        raise BoardError("claude is not on PATH (set AGENTBOARD_CLAUDE or [run] claude in config.toml)")
    return str(path)


def pid_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_run(run_dir):
    try:
        return json.loads((Path(run_dir) / "run.json").read_text())
    except (OSError, ValueError):
        return None


def write_run(run_dir, data):
    p = Path(run_dir) / "run.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, p)


def all_runs(board_dir, card=None):
    """Every run, newest first: [(run dir, run.json)]. A run recorded as running whose supervisor is gone is reported as 'lost'."""
    out = []
    base = runs_dir(board_dir)
    for cdir in sorted(base.iterdir()) if base.is_dir() else []:
        if card and cdir.name != card:
            continue
        for rdir in sorted(cdir.iterdir()) if cdir.is_dir() else []:
            r = read_run(rdir)
            if r:
                if r.get("status") == "running" and not pid_alive(r.get("supervisor_pid")):
                    r = {**r, "status": "lost"}
                out.append((rdir, r))
    out.sort(key=lambda x: x[1].get("started", ""), reverse=True)
    return out


def live_run(board_dir, card):
    return next(((d, r) for d, r in all_runs(board_dir, card) if r["status"] == "running"), None)


def _git(args, cwd, check=True):
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and p.returncode:
        raise BoardError(f"git {' '.join(args)}: {(p.stderr or p.stdout).strip()}")
    return p


def _repo_root(cwd):
    p = _git(["rev-parse", "--show-toplevel"], cwd, check=False)
    return Path(p.stdout.strip()) if p.returncode == 0 and p.stdout.strip() else None


def _in_linked_worktree(cwd):
    g = _git(["rev-parse", "--git-dir"], cwd, check=False).stdout.strip()
    c = _git(["rev-parse", "--git-common-dir"], cwd, check=False).stdout.strip()
    return bool(g and c and Path(cwd, g).resolve() != Path(cwd, c).resolve())


def prepare_workdir(cwd, card_id, run_id, explicit):
    """(workdir, worktree info). With an explicit --cwd, or when already inside a linked worktree or outside git, work there as is.
    From a repo's main checkout, make a fresh worktree on a new branch next to it: <repo>-wt/run-<card>-<run id>."""
    cwd = Path(cwd).resolve()
    root = _repo_root(cwd)
    if explicit or root is None or _in_linked_worktree(cwd):
        return cwd, {"created": False, "path": str(cwd)}
    branch = f"run/{card_id}-{run_id}"[:100]
    path = root.parent / f"{root.name}-wt" / f"run-{card_id}-{run_id}"[:100]
    path.parent.mkdir(parents=True, exist_ok=True)
    head = _git(["rev-parse", "HEAD"], root).stdout.strip()
    _git(["worktree", "add", "-q", "-b", branch, str(path), head], root)
    return path, {"created": True, "path": str(path), "branch": branch, "base": head, "repo": str(root)}


def cleanup_worktree(info):
    """Remove a worktree this run created, but only if nothing was left in it. Returns 'removed', 'kept: <why>' or ''."""
    if not info.get("created"):
        return ""
    path, repo = info["path"], info["repo"]
    if not Path(path).exists():
        return ""
    dirty = _git(["status", "--porcelain"], path, check=False).stdout.strip()
    ahead = _git(["rev-list", "--count", f"{info['base']}..HEAD"], path, check=False).stdout.strip()
    if dirty:
        return f"kept: uncommitted changes in {path}"
    if ahead not in ("", "0"):
        return f"kept: {ahead} commit(s) on branch {info['branch']} in {path}"
    _git(["worktree", "remove", "--force", path], repo, check=False)
    _git(["branch", "-D", info["branch"]], repo, check=False)
    return "removed"


def build_run_prompt(task, board_dir, tasks, name, budget, minutes):
    text, _warnings = promptlib.build_prompt(task, board_dir, public=False, tasks=tasks)
    return text.rstrip() + "\n" + RULES.format(name=name, ab=promptlib.agentboard_cmd(board_dir), task_id=task["id"], budget=budget, minutes=minutes)


def parse_result(stdout_text):
    """The final JSON object `claude -p --output-format json` prints (or the last JSON line). {} when there is none."""
    for chunk in (stdout_text.strip(), *reversed([l for l in stdout_text.splitlines() if l.strip().startswith("{")])):
        try:
            v = json.loads(chunk)
        except ValueError:
            continue
        if isinstance(v, dict):
            return v
    return {}


def _tail(path, n=8):
    try:
        lines = [l.rstrip() for l in Path(path).read_text(errors="replace").splitlines() if l.strip()]
    except OSError:
        return []
    return lines[-n:]


def _stop(proc, grace=KILL_GRACE_S):
    """Stop the claude process group: SIGTERM, then SIGKILL after the grace period."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    t0 = time.time()
    while proc.poll() is None and time.time() - t0 < grace:
        time.sleep(0.1)
    if proc.poll() is None:
        with_suppress(lambda: os.killpg(proc.pid, signal.SIGKILL))
        proc.wait()


def with_suppress(fn):
    try:
        fn()
    except (ProcessLookupError, PermissionError, OSError):
        pass


def check_startable(store, card_id, name, force=False):
    tasks = store.load()
    t = store.get(tasks, card_id)
    if t.get("parent_id"):
        raise BoardError(f"{card_id} is a subtask: run its parent")
    if t["status"] == "done":
        raise BoardError(f"{card_id} is already done")
    if live_run(store.dir, card_id):
        raise BoardError(f"{card_id} already has a run in progress (`agentboard runs`; stop it with `agentboard runs --kill {card_id}`)")
    if t.get("agent") and t["agent"] != name and t["status"] == "doing" and not force:
        raise BoardError(f"{card_id} is claimed by {t['agent']} (use --force)")
    return t


def run_card(store, card_id, *, name=None, color=None, cwd=None, budget=None, minutes=None, force=False, log=print):
    """Run one card to the end in the foreground. Returns the final run record."""
    conf = run_conf(store.dir)
    name = name or os.environ.get("AGENTBOARD_NAME") or "oneshot"
    budget = float(budget if budget is not None else conf.get("budget_usd", DEFAULT_BUDGET_USD))
    minutes = float(minutes if minutes is not None else conf.get("max_minutes", DEFAULT_MAX_MINUTES))
    if budget <= 0 or minutes <= 0:
        raise BoardError("budget and time limit must be positive")
    claude = claude_binary(store.dir)
    task = check_startable(store, card_id, name, force)

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    rdir = runs_dir(store.dir) / card_id / run_id
    rdir.mkdir(parents=True, exist_ok=True)
    workdir, wt = prepare_workdir(cwd or os.getcwd(), card_id, run_id, explicit=bool(cwd))
    try:
        prompt = build_run_prompt(task, store.dir, store.load(), name, budget, minutes)
    except BaseException:
        cleanup_worktree(wt)
        raise
    (rdir / "prompt.md").write_text(prompt)
    rec = {"card": card_id, "id": run_id, "name": name, "status": "running", "supervisor_pid": os.getpid(), "pid": None,
           "started": datetime.now().isoformat(timespec="seconds"), "cwd": str(workdir), "worktree": wt, "budget_usd": budget,
           "max_minutes": minutes, "dir": str(rdir), "claude": claude}
    write_run(rdir, rec)

    killed = {"flag": False}
    in_main = threading.current_thread() is threading.main_thread()
    old = signal.signal(signal.SIGTERM, lambda *_: killed.update(flag=True)) if in_main else None   # `agentboard runs --kill` signals the supervisor (the KILL file does the same)
    proc = None
    claimed = False
    try:
        store.claim(card_id, name, color, force=force)
        claimed = True
        store.set_run(card_id, {"status": "running", "id": run_id, "pid": None, "supervisor_pid": os.getpid(), "started": rec["started"],
                                "budget_usd": budget, "max_minutes": minutes, "dir": str(rdir)}, f"One-shot run {run_id} started as {name} (limit {minutes:g} min, ${budget:g})")
        env = {**os.environ, "AGENTBOARD_DIR": str(store.dir), "AGENTBOARD_NAME": name, "AGENTBOARD_RUN": run_id}
        env.pop("AGENTBOARD_BOARD", None)
        if color:
            env["AGENTBOARD_COLOR"] = color
        argv = [claude, "-p", "--output-format", "json", "--max-budget-usd", f"{budget:g}", "--name", name]
        out_f, err_f = open(rdir / "stdout.json", "wb"), open(rdir / "stderr.log", "wb")
        t0 = time.time()
        proc = subprocess.Popen(argv, cwd=workdir, env=env, stdin=subprocess.PIPE, stdout=out_f, stderr=err_f, start_new_session=True)
        out_f.close()
        err_f.close()
        proc.stdin.write(prompt.encode())
        proc.stdin.close()
        rec["pid"] = proc.pid
        write_run(rdir, rec)
        store.set_run(card_id, {"pid": proc.pid})
        reason = ""
        while proc.poll() is None:
            if killed["flag"] or (rdir / "KILL").exists():
                reason = "killed"
            elif time.time() - t0 > minutes * 60:
                reason = "timeout"
            if reason:
                _stop(proc)
                break
            time.sleep(POLL_S)
        duration = round(time.time() - t0, 1)
        code = proc.returncode
    except BaseException as e:
        if proc is not None and proc.poll() is None:
            _stop(proc, grace=2)
        if proc is None:   # never launched: leave nothing behind, and tell the board if the card was already claimed
            note = cleanup_worktree(wt)
            write_run(rdir, {**rec, "status": "failed", "ended": datetime.now().isoformat(timespec="seconds"), "error": str(e)})
            if claimed:
                with_suppress(lambda: store.set_run(card_id, {"status": "failed"}, f"One-shot run could not start: {e}"))
                with_suppress(lambda: store.ask(card_id, f"Run could not start: {e}"))
        raise
    finally:
        if in_main:
            signal.signal(signal.SIGTERM, old)

    result = parse_result((rdir / "stdout.json").read_text(errors="replace"))
    cost = result.get("total_cost_usd")
    is_error = bool(result.get("is_error")) or code not in (0, None) or not result
    status = reason or ("failed" if is_error else "finished")
    note = cleanup_worktree(wt)
    rec.update({"status": status, "exit_code": code, "duration_s": duration, "cost_usd": cost, "ended": datetime.now().isoformat(timespec="seconds"),
                "worktree_cleanup": note, "result": (result.get("result") or "")[:2000], "subtype": result.get("subtype")})
    write_run(rdir, rec)
    _conclude(store, card_id, rec, rdir, log)
    return rec


def _fmt_dur(s):
    s = int(s or 0)
    return f"{s // 60}m{s % 60:02d}s" if s >= 60 else f"{s}s"


def _conclude(store, card_id, rec, rdir, log):
    """Move the card: review when the run finished cleanly (unless the agent already reported), ask with the output tail when it did not."""
    cost = rec.get("cost_usd")
    facts = f"{_fmt_dur(rec['duration_s'])}" + (f", ${cost:.2f}" if isinstance(cost, (int, float)) else "")
    run_info = {"status": rec["status"], "ended": rec["ended"], "duration_s": rec["duration_s"], "cost_usd": cost, "exit_code": rec["exit_code"], "dir": str(rdir)}
    if rec["worktree_cleanup"].startswith("kept"):
        run_info["worktree"] = rec["worktree_cleanup"]
    card = store.get(store.load(), card_id)
    if rec["status"] == "finished":
        store.set_run(card_id, run_info, f"One-shot run finished ({facts})")
        if card["status"] == "doing" and not card.get("review") and not card.get("needs_input"):
            summary = (rec.get("result") or "Run finished.").strip().splitlines()[0][:200]
            body = f"**One-shot run finished** in {facts}.\n\n{rec.get('result', '')}\n\nLog: `{rdir}`"
            if rec["worktree_cleanup"].startswith("kept"):
                body += f"\n\nWorktree {rec['worktree_cleanup']}"
            store.review(card_id, f"{summary} ({facts})", body)
        log(f"{card_id}: run finished ({facts})")
        return
    why = {"killed": "stopped by the kill switch", "timeout": f"stopped at the {rec['max_minutes']:g}-minute limit",
           "failed": f"failed (exit {rec['exit_code']}{', ' + rec['subtype'] if rec.get('subtype') else ''})"}[rec["status"]]
    tail = _tail(rdir / "stderr.log") or _tail(rdir / "stdout.json")
    store.set_run(card_id, run_info, f"One-shot run {why} ({facts})")
    if card["status"] == "doing":
        body = f"**One-shot run {why}** after {facts}.\n\nLast lines of output:\n\n```\n" + "\n".join(tail) + f"\n```\n\nLog: `{rdir}`"
        if rec["worktree_cleanup"].startswith("kept"):
            body += f"\n\nWorktree {rec['worktree_cleanup']}"
        store.ask(card_id, f"Run {why}; see the tail of its output", body)
    log(f"{card_id}: run {why} ({facts})")


def kill_run(board_dir, card):
    """The kill switch: ask the live run's supervisor to stop (it stops claude, moves the card to ask and cleans up). If the
    supervisor is gone, stop claude directly. Returns what happened."""
    live = live_run(board_dir, card)
    if not live:
        lost = [(d, r) for d, r in all_runs(board_dir, card) if r["status"] == "lost"]
        if not lost:
            raise BoardError(f"{card} has no run in progress")
        d, r = lost[0]
        if pid_alive(r.get("pid")):
            with_suppress(lambda: os.killpg(r["pid"], signal.SIGKILL))
        write_run(d, {**r, "status": "killed", "ended": datetime.now().isoformat(timespec="seconds")})
        return "supervisor was gone; stopped claude directly"
    d, r = live
    (Path(d) / "KILL").write_text("kill\n")   # works even if the signal cannot be delivered
    if r["supervisor_pid"] != os.getpid():   # (the KILL file is enough when the supervisor is a thread of this very process)
        with_suppress(lambda: os.kill(r["supervisor_pid"], signal.SIGTERM))
    return f"asked run {r['id']} to stop"


def list_lines(board_dir):
    rows = []
    for d, r in all_runs(board_dir):
        cost = r.get("cost_usd")
        dur = r.get("duration_s")
        if r["status"] == "running":
            started = datetime.fromisoformat(r["started"])
            dur = (datetime.now() - started).total_seconds()
        rows.append(f"{r['card']:<30} {r['status']:<9} {r['name']:<10} {_fmt_dur(dur):>7}  {('$%.2f' % cost) if isinstance(cost, (int, float)) else '-':>6}  {r['id']}")
    return rows


def detach(argv_tail, board_dir, card_id):
    """Start `agentboard run ...` (without --detach) in its own session and return at once (what ORCH uses)."""
    base = runs_dir(board_dir) / card_id
    base.mkdir(parents=True, exist_ok=True)
    out = open(base / "supervisor.log", "ab")
    env = {**os.environ, "AGENTBOARD_DIR": str(board_dir)}
    env.pop("AGENTBOARD_BOARD", None)
    p = subprocess.Popen([sys.executable, "-m", "agentboard", "run", card_id, *argv_tail], stdout=out, stderr=out,
                         stdin=subprocess.DEVNULL, start_new_session=True, env=env, cwd=os.getcwd())
    out.close()
    return p.pid, base / "supervisor.log"

