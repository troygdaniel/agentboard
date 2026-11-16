"""`agentboard review` looks at git (retro rec 6, card retro-review-warns-uncommitted): it warns when the tree has uncommitted changes or the
branch has nothing past main. A warning only, never a block: the line goes to the agent's stderr and, as the same words, into the card's
history. Nothing here writes to git, runs a hook or reads a file's contents; it asks git four short questions and gives up quietly (no line)
when git is missing, slow, or the folder is not a repository with a main or master branch, so a card about a letter or a phone call is
never told off.

The tree is the folder the command runs in, or the one `--tree PATH` names (a session that runs agentboard from another folder, for
example the board's own, points it at its worktree). `AGENTBOARD_TREE_CHECK=off` switches it off (the test suite sets that), and so does the master lock AGENTBOARD_LOCKDOWN (the work profile): then
no program is started at all."""
import os
import subprocess

from . import lockdown

ENV = "AGENTBOARD_TREE_CHECK"
BASES = ("main", "master")
SECONDS = 5   # each git question; a hung git must not hang a review


def _git(tree, *args):
    """Git's stdout in `tree`, or None when git failed, is missing or took too long."""
    try:
        r = subprocess.run(["git", "-C", tree, *args], capture_output=True, text=True, timeout=SECONDS)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def check(tree=None):
    """One plain line saying what is wrong with the tree, or None when nothing is (or it cannot tell)."""
    if os.environ.get(ENV, "").strip().lower() in ("off", "0", "no", "false") or lockdown.locked("tree check"):
        return None   # off by choice, or the master lock: no program is started
    tree = os.path.abspath(tree or os.getcwd())
    top = _git(tree, "rev-parse", "--show-toplevel")
    if not top:
        return None
    base = next((b for b in BASES if _git(top, "rev-parse", "--verify", "--quiet", f"refs/heads/{b}")), None)
    if base is None:
        return None
    problems = []
    changed = [ln for ln in (_git(top, "status", "--porcelain") or "").splitlines() if ln.strip()]
    if changed:
        problems.append(f"{len(changed)} uncommitted change{'s' if len(changed) != 1 else ''} in {top}")
    ahead = _git(top, "rev-list", "--count", f"{base}..HEAD")
    if ahead == "0":
        branch = _git(top, "rev-parse", "--abbrev-ref", "HEAD") or "HEAD"
        problems.append(f"{'you are on ' + base + ' itself' if branch == base else 'branch ' + branch} with nothing past {base}")
    if not problems:
        return None
    return ("; ".join(problems) + ". Commit your work on a branch before review so it can be merged "
            "(run review from the worktree, or name it with --tree PATH).")
