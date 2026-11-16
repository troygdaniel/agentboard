"""What `agentboard done` says about the card's worktree, and which merged worktrees could go (card retro-done-shows-worktrees).

A finished card used to leave its worktree on disk and nobody was told: 60 of the 62 extra agentboard worktrees in the 15 Nov retro were merged
already and still there. `done` now prints, after "<card>: done":
  - the card's own worktree and branch (found by the agent's name in the folder, or the card id in the folder or branch) and whether it is
    merged into the main checkout's branch, how far ahead it is if not, and whether it has uncommitted changes;
  - the other worktrees that are safe to remove: merged, clean, not locked, and no agent with an open card owns the folder. Each is a line
    to copy (`git worktree remove <path>`).
It is a list. The board never removes a worktree or a branch, and it never writes: every git call is read-only (`--no-optional-locks`, so even
`status` leaves the index alone) and goes through reports._git, which starts nothing under the work profile. Under the profile or the
lockdown, outside a git repository, or when git is slow or missing, it says nothing and `done` is exactly what it was.

Merged means the worktree's HEAD has nothing main lacks (`git rev-list --count main..HEAD` is 0). A fresh worktree that has no commit yet
counts as merged, which is why a folder whose agent holds an open card is never listed as removable."""
import re
import shlex
import time
from pathlib import Path

from . import lockdown, profile, reports

MAX_SHOWN = 8       # removable worktrees listed before "and N more"
BUDGET_S = 20       # stop looking after this many seconds (each git call is capped at reports.GIT_TIMEOUT_S)
BUSY = ("doing", "review", "needs_input")
_SHA = re.compile(r"[0-9a-f]{40,64}")
_BAD_PATH = re.compile(r"[\x00-\x1f\x7f]")


def parse(text):
    """The entries of `git worktree list --porcelain`: [{path, head, branch, locked, prunable, bare}]; the first is the main checkout."""
    out, cur = [], None
    for line in (text or "").splitlines():
        if line.startswith("worktree "):
            cur = {"path": line[9:], "head": "", "branch": None, "locked": False, "prunable": False, "bare": False}
            out.append(cur)
        elif cur is None:
            continue
        elif line.startswith("HEAD "):
            cur["head"] = line[5:].strip()
        elif line.startswith("branch "):
            ref = line[7:].strip()
            cur["branch"] = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref
        elif line == "bare":
            cur["bare"] = True
        elif line.startswith("locked"):
            cur["locked"] = True
        elif line.startswith("prunable"):
            cur["prunable"] = True
    return out


def _git(args, cwd):
    return reports._git(["--no-optional-locks", *args], cwd)


def _mine(entry, task):
    """Is this the card's worktree: the owner's name between dashes in the folder name, or the card id in the folder or the branch."""
    folder = Path(entry["path"]).name.lower()
    branch = (entry["branch"] or "").lower()
    cid = str(task.get("id", "")).lower()
    owner = str(task.get("agent") or "").strip().lower()
    if cid and (cid in folder or cid in branch):
        return True
    return bool(owner) and re.search(r"(?:^|-)" + re.escape(owner) + r"(?:-|$)", folder) is not None


def _busy_names(tasks, skip_id):
    """Agents (lowercase) that hold an open card other than this one: their folders are in use, however merged they look."""
    return {str(t.get("agent")).strip().lower() for t in tasks
            if t.get("agent") and t.get("status") in BUSY and not t.get("parent_id") and t.get("id") != skip_id}


def _owned_by(entry, names):
    folder = Path(entry["path"]).name.lower()
    return any(re.search(r"(?:^|-)" + re.escape(n) + r"(?:-|$)", folder) for n in names)


def _state(entry, base_sha, repo):
    """('merged'|'ahead'|'unknown', commits ahead, dirty True|False|None). Reads only; the folder is not touched when it is not merged."""
    if not base_sha or not _SHA.fullmatch(entry["head"] or ""):
        return "unknown", 0, None
    n = _git(["rev-list", "--count", f"{base_sha}..{entry['head']}"], repo)
    if n is None or not n.strip().isdigit():
        return "unknown", 0, None
    if int(n) > 0:
        return "ahead", int(n), None
    out = _git(["status", "--porcelain"], entry["path"])
    return "merged", 0, (None if out is None else bool(out.strip()))


def _cmd(entry):
    return "git worktree remove " + shlex.quote(entry["path"])


def report(board_dir, tasks, task_id, repo=None):
    """The lines `done` prints after "<card>: done"; [] when there is nothing to say or git cannot be asked (see the module note)."""
    if lockdown.locked() or profile.in_effect():
        return []
    task = next((t for t in tasks if t.get("id") == task_id), None)
    if task is None or task.get("parent_id"):   # a subtask has no worktree of its own
        return []
    if repo is None:
        c = reports.conf(board_dir)
        repo = Path(c["repo"]).expanduser() if c.get("repo") else Path(board_dir).resolve().parent
    repo = Path(repo)
    if not repo.is_dir():
        return []
    listing = _git(["worktree", "list", "--porcelain"], repo)
    entries = [e for e in parse(listing) if not _BAD_PATH.search(e["path"])]
    if len(entries) < 2 or entries[0]["bare"]:   # no linked worktree at all (or a bare repo: no main branch to compare with)
        return []
    main, linked = entries[0], entries[1:]
    base_sha = main["head"] if main["branch"] and _SHA.fullmatch(main["head"] or "") else None
    base = main["branch"] or "the main checkout's branch"
    deadline = time.monotonic() + BUDGET_S
    busy = _busy_names(tasks, task_id)
    lines, mine_paths, removable, kept, cut = [], set(), [], 0, False
    for e in linked:
        if time.monotonic() > deadline:
            cut = True
            break
        if e["prunable"] or not Path(e["path"]).is_dir():
            continue   # the folder is gone: `git worktree prune`, not the board's business
        is_mine = _mine(e, task)
        in_use = (not is_mine) and _owned_by(e, busy)
        if in_use or (not is_mine and e["locked"]):
            kept += 1
            continue
        state, ahead, dirty = _state(e, base_sha, repo)
        safe = state == "merged" and dirty is False and not e["locked"]
        if is_mine:
            mine_paths.add(e["path"])
            lines.append(f"this card's worktree: {e['path']} (branch {e['branch'] or 'detached'})")
            if state == "ahead":
                lines.append(f"  NOT merged into {base}: {ahead} commit{'s' if ahead != 1 else ''} ahead; keep it")
            elif state == "unknown":
                lines.append(f"  cannot tell whether it is merged into {base}: look before removing it")
            elif e["locked"]:
                lines.append(f"  merged into {base}, but locked: `git worktree unlock` it first")
            elif dirty:
                lines.append(f"  merged into {base}, but it has uncommitted changes: keep it until they are saved or dropped")
            elif dirty is None:
                lines.append(f"  merged into {base}; its changes could not be read: look before removing it")
            else:
                lines.append(f"  merged into {base} and clean: {_cmd(e)}")
        elif safe:
            removable.append(e)
        else:
            kept += 1
    if not mine_paths:
        who = task.get("agent") or task_id
        lines.append(f"no worktree found for this card ({who}): nothing of it left on disk")
    if removable:
        lines.append(f"merged and clean, no agent with an open card in them (the board never removes anything): {len(removable)}")
        for e in removable[:MAX_SHOWN]:
            lines.append(f"  {_cmd(e)}   # branch {e['branch'] or 'detached'}")
        if len(removable) > MAX_SHOWN:
            lines.append(f"  and {len(removable) - MAX_SHOWN} more")
    if kept:
        lines.append(f"{kept} other worktree{'s' if kept != 1 else ''} not listed: not merged, changed, locked, in use, or unreadable")
    if cut:
        lines.append(f"stopped after {BUDGET_S} s: the rest were not checked")
    return lines
