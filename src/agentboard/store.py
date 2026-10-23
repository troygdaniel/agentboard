"""Task storage: one JSON file, locked and written atomically."""
import contextlib
import json
import os
import re
import tempfile
import time
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None

STATUSES = ("backlog", "todo", "doing", "done")
DIR_NAME = ".agentboard"


class BoardError(Exception):
    pass


def find_dir(start=None):
    """AGENTBOARD_DIR, else the nearest .agentboard/ walking up from start."""
    env = os.environ.get("AGENTBOARD_DIR")
    if env:
        return Path(env).expanduser().resolve()
    here = Path(start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        if (d / DIR_NAME).is_dir():
            return d / DIR_NAME
    raise BoardError("no board found; run `agentboard init` in your project (or set AGENTBOARD_DIR)")


class Store:
    def __init__(self, board_dir):
        self.dir = Path(board_dir)
        self.path = self.dir / "tasks.json"
        self.lock_path = self.dir / ".lock"

    @contextlib.contextmanager
    def _lock(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.lock_path, "a") as lf:
            if fcntl:
                fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl:
                    fcntl.flock(lf, fcntl.LOCK_UN)

    def _read(self):
        try:
            data = json.loads(self.path.read_text())
        except FileNotFoundError:
            return {"tasks": [], "projects": [], "chat": [], "chat_seq": 0}
        except ValueError as e:
            raise BoardError(f"{self.path} is not valid JSON ({e}); fix or delete it") from e
        data.setdefault("tasks", [])
        data.setdefault("projects", [])
        data.setdefault("chat", [])
        data.setdefault("chat_seq", 0)
        return data

    def _write(self, data):
        fd, tmp = tempfile.mkstemp(dir=self.dir, prefix=".tasks-", suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self.path)

    def load(self):
        with self._lock():
            return self._read()["tasks"]

    @contextlib.contextmanager
    def transaction(self):
        """Yield the task list; saved on clean exit."""
        with self._lock():
            data = self._read()
            yield data["tasks"]
            self._write(data)

    @contextlib.contextmanager
    def project_transaction(self):
        """Yield the project list; saved on clean exit."""
        with self._lock():
            data = self._read()
            yield data["projects"]
            self._write(data)

    # -- helpers used by CLI and server ------------------------------------

    @staticmethod
    def get(tasks, task_id):
        for t in tasks:
            if t["id"] == task_id:
                return t
        raise BoardError(f"no such task: {task_id}")

    def add(self, title, description="", status=None, ctx=None, task_id=None, project_id=None, blocked_by=None,
            parent_id=None):
        """Add a task. With parent_id it becomes a subtask: it follows its parent's column and owner and
        inherits its project (one level only)."""
        if status is not None and status not in STATUSES:
            raise BoardError(f"status must be one of {STATUSES}")
        title = _clean_title(title)
        if not (isinstance(ctx or [], list) and all(isinstance(c, str) for c in ctx or [])):
            raise BoardError("ctx must be a list of strings")
        with self.transaction() as tasks:
            parent = _check_parent(tasks, parent_id)
            if parent:
                if status is not None and status != parent["status"]:
                    raise BoardError(f"a subtask follows its parent ({parent['status']}); drop --status")
                status = parent["status"]
                project_id = project_id or parent.get("project_id")
            status = status or "backlog"
            tid = task_id or _unique_id(title, {t["id"] for t in tasks})
            if any(t["id"] == tid for t in tasks):
                raise BoardError(f"task id already exists: {tid}")
            if blocked_by:
                missing = [bid for bid in blocked_by if not any(x["id"] == bid for x in tasks)]
                if missing:
                    raise BoardError(f"blocked-by: no such task: {', '.join(missing)}")
            task = {
                "id": tid,
                "title": title,
                "description": description,
                "status": status,
                "progress": 0,
                "status_text": "",
                "ctx": ctx or [],
                "prompt": "",
                "created": _now(),
                "updated": _now(),
            }
            if project_id:
                task["project_id"] = project_id
            if blocked_by:
                task["blocked_by"] = list(blocked_by)
            if parent:
                task["parent_id"] = parent["id"]
                if parent.get("agent") and status == "doing":
                    task["agent"] = parent["agent"]
                    if parent.get("color"):
                        task["color"] = parent["color"]
            _log(task, f"Added to {status}")
            tasks.append(task)
            if parent:
                _touch_parent(tasks, parent)
            return task

    def start(self, title, name, color=None, description="", task_id=None, project_id=None,
              blocked_by=None, force=False, parent_id=None):
        """Agent announces new work: create the task already in doing, owned by name.

        With parent_id it is a subtask of that card (inherits its project)."""
        title = _clean_title(title)
        with self.transaction() as tasks:
            parent = _check_parent(tasks, parent_id)
            if parent:
                if not force:
                    _parent_must_be_doing(parent, {"id": "a new subtask"}, "start")
                project_id = project_id or parent.get("project_id")
            tid = task_id or _unique_id(title, {t["id"] for t in tasks})
            existing = next((t for t in tasks if t["id"] == tid), None)
            if existing:  # same agent re-announcing the same work is a no-op
                if existing.get("agent") == name and existing["status"] == "doing":
                    return existing
                raise BoardError(f"task id already exists: {tid}")
            if blocked_by:
                missing = [bid for bid in blocked_by if not any(x["id"] == bid for x in tasks)]
                if missing:
                    raise BoardError(f"blocked-by: no such task: {', '.join(missing)}")
                if not force:
                    unresolved = _unresolved_blockers(tasks, blocked_by)
                    if unresolved:
                        raise BoardError(f"cannot start: blocked by {', '.join(unresolved)} (use --force)")
            task = {
                "id": tid, "title": title, "description": description,
                "status": "doing", "progress": 5, "status_text": f"Started by {name}",
                "agent": name, "ctx": [], "prompt": "",
                "created": _now(), "updated": _now(),
            }
            if color:
                task["color"] = color
            if project_id:
                task["project_id"] = project_id
            if blocked_by:
                task["blocked_by"] = list(blocked_by)
            if parent:
                task["parent_id"] = parent["id"]
            _log(task, f"Started by {name}")
            tasks.append(task)
            if parent:
                _touch_parent(tasks, parent)
            return task

    def claim(self, task_id, name, color=None, force=False):
        with self.transaction() as tasks:
            t = self.get(tasks, task_id)
            if not force:
                _parent_must_be_doing(_parent_of(tasks, t), t, "claim")
            if t.get("agent") and t["agent"] != name and not force and t["status"] == "doing":
                raise BoardError(f"{task_id} is already claimed by {t['agent']} (use --force)")
            if t["status"] == "done" and not force:
                raise BoardError(f"{task_id} is already done (use --force to reopen)")
            if not force:
                unresolved = _unresolved_blockers(tasks, t.get("blocked_by"))
                if unresolved:
                    raise BoardError(f"{task_id} is blocked by: {', '.join(unresolved)} (use --force)")
            t["status"] = "doing"
            t["agent"] = name
            if color:
                t["color"] = color
            if t.get("progress", 0) == 0:
                t["progress"] = 5
            t.pop("needs_input", None)
            t.pop("question", None)
            t.pop("ask_child", None)
            t.pop("review", None)
            t.pop("body_md", None)
            t.pop("archived", None)   # claiming a cleared task (--force) puts it back on the board
            t["status_text"] = f"Claimed by {name}"
            _log(t, f"Claimed by {name}")
            t["updated"] = _now()
            # claiming a parent takes all of its open subtasks too (quietly: each one's own log
            # starts with its first real update, so a queued subtask doesn't read as busy)
            for k in _kids(tasks, t["id"]):
                if k["status"] != "done":
                    k["status"], k["agent"] = "doing", name
                    if color:
                        k["color"] = color
                    for f in ("needs_input", "question", "review", "body_md"):
                        k.pop(f, None)
                    k["updated"] = t["updated"]
            _recompute(tasks, t)
            return t

    def ask(self, task_id, question, body_md=None):
        """Agent flags that it is blocked on the user. Cleared by the next update.

        body_md is an optional richer markdown body (a recap, a diff, a report) shown
        in the detail panel alongside the one-line question; it is untrusted agent
        text, rendered safely by the server (see markdown.to_html) rather than here.
        """
        with self.transaction() as tasks:
            t = self.get(tasks, task_id)
            _require_doing(t, "ask")
            t["needs_input"] = True
            t["question"] = question
            t["status_text"] = question
            if body_md:
                t["body_md"] = body_md
            else:
                t.pop("body_md", None)
            _log(t, f"Needs input: {question}")
            t["updated"] = _now()
            parent = _parent_of(tasks, t)
            if parent:   # surface it on the parent card, which is what the board and HUD watch
                parent["needs_input"] = True
                parent["question"] = f"{t['title']}: {question}"
                parent["status_text"] = parent["question"]
                parent["ask_child"] = t["id"]
                parent["updated"] = t["updated"]
            return t

    def review(self, task_id, summary, body_md=None):
        """Agent reports the work complete and hands it to the user for sign-off.

        body_md is an optional richer markdown body (a recap, a diff, a report); see
        ask() for how it's handled.
        """
        with self.transaction() as tasks:
            t = self.get(tasks, task_id)
            if t.get("parent_id"):
                # subtasks have no review step: reporting one finished is just 100%, which completes it
                return self._update(tasks, t, 100, summary, None)
            _require_doing(t, "review")
            t.pop("needs_input", None)
            t.pop("question", None)
            t.pop("ask_child", None)
            t["review"] = True
            t["progress"] = 100
            t["result"] = summary
            t["status_text"] = summary
            if body_md:
                t["body_md"] = body_md
            else:
                t.pop("body_md", None)
            _log(t, f"Ready for review: {summary}")
            t["updated"] = _now()
            for k in _kids(tasks, t["id"]):   # the deliverable is ready, so any still-open subtask is too
                if k["status"] != "done":
                    _finish(k, t["updated"])
            return t

    def update(self, task_id, progress=None, text=None, status=None):
        with self.transaction() as tasks:
            return self._update(tasks, self.get(tasks, task_id), progress, text, status)

    def _update(self, tasks, t, progress, text, status):
        _parent_must_be_doing(_parent_of(tasks, t), t, "update")
        kids = _kids(tasks, t["id"])
        open_kids = [k for k in kids if k["status"] != "done"]
        if progress and open_kids:   # 0 is the documented "status line only" form, so it never claims to set a %
            raise BoardError(parent_pct_hint(t["id"], open_kids))
        resumed = bool(t.get("needs_input") or t.get("review"))
        for f in ("needs_input", "question", "review", "body_md"):
            t.pop(f, None)
        parent = _parent_of(tasks, t)
        if parent and parent.get("ask_child") == t["id"]:   # this was the question the parent was showing
            for f in ("needs_input", "question", "ask_child"):
                parent.pop(f, None)
        t.pop("ask_child", None)
        if t["status"] == "done" and not status:   # finished work stays at 100%, whatever a late update says
            progress = None
        if progress is not None and not kids:   # a parent's % is computed from its subtasks, never set
            t["progress"] = max(0, min(100, int(progress)))
        if text is not None:
            t["status_text"] = text
            if status == "done":
                t["result"] = text
        auto_done = bool(parent) and t.get("progress", 0) >= 100 and t["status"] != "done" and not status
        if auto_done:   # a subtask at 100% closes itself; no review step
            t["result"] = text or t.get("status_text") or ""
        if status:   # log after the move so the entry carries the new column
            _set_status(tasks, t, status)
            _log(t, "Marked done" if status == "done" else text)
        elif auto_done:
            _log(t, text)
            _apply_status(t, "done")
            _log(t, "Marked done")
        else:   # a progress-only update still closes an open "needs input"/"review" run in the history
            _log(t, text or ("Resumed" if resumed else None))
        t["updated"] = _now()
        if parent:
            _touch_parent(tasks, parent, text)
        return t

    def move(self, task_id, status, before_id=None, force=False):
        """Change column and/or position (used by drag-and-drop, the panel's move button,
        and Alt+arrow). Entering doing is blocked the same way claim()/start() are."""
        if status not in STATUSES:
            raise BoardError(f"status must be one of {STATUSES}")
        with self.transaction() as tasks:
            t = self.get(tasks, task_id)
            _not_a_subtask(t, "move")
            if status == "doing" and t["status"] != "doing" and not force:
                unresolved = _unresolved_blockers(tasks, t.get("blocked_by"))
                if unresolved:
                    raise BoardError(f"{task_id} is blocked by: {', '.join(unresolved)}")
            tasks.remove(t)
            if t["status"] != status:
                _set_status(tasks, t, status)
                _log(t, f"Moved to {status}")
            t["updated"] = _now()
            _insert(tasks, t, before_id)
            return t

    def next_sibling(self, task_id):
        """Id of the task that follows this one in its column (None if last)."""
        tasks = self.load()
        t = self.get(tasks, task_id)
        col = [x["id"] for x in tasks if x["status"] == t["status"]]
        i = col.index(task_id)
        return col[i + 1] if i + 1 < len(col) else None

    def restore(self, snapshot, before_id=None, kids=None):
        """Put a task back exactly as it was (undo for moves). `kids` are the snapshots of its
        subtasks, which a move may have cascaded onto."""
        if snapshot.get("status") not in STATUSES:
            raise BoardError(f"status must be one of {STATUSES}")
        with self.transaction() as tasks:
            tasks.remove(self.get(tasks, snapshot["id"]))
            snap = dict(snapshot)
            _insert(tasks, snap, before_id)
            for ks in kids or []:
                for i, x in enumerate(tasks):
                    if x["id"] == ks["id"]:
                        tasks[i] = dict(ks)
            return snap

    def clear_done(self):
        """Archive every Done task: hidden from the board, kept for history and the HUD."""
        with self.transaction() as tasks:
            parents_done = {t["id"] for t in tasks if t["status"] == "done"}
            # a finished subtask lives in its parent's card: only clear it together with a done parent
            ids = [t["id"] for t in tasks if t["status"] == "done" and not t.get("archived")
                   and (not t.get("parent_id") or t["parent_id"] in parents_done)]
            for t in tasks:
                if t["id"] in ids:
                    t["archived"] = True
            return ids

    def unarchive(self, ids):
        with self.transaction() as tasks:
            for t in tasks:
                if t["id"] in ids:
                    t.pop("archived", None)

    def set_agent_color(self, task_id, color):
        with self.transaction() as tasks:
            t = self.get(tasks, task_id)
            t["color"] = color
            for k in _kids(tasks, task_id):
                k["color"] = color
            return t

    def delete(self, task_id):
        """Remove a task; a parent takes its subtasks with it, a subtask just leaves its parent."""
        with self.transaction() as tasks:
            t = self.get(tasks, task_id)
            tasks.remove(t)
            for k in _kids(tasks, task_id):
                tasks.remove(k)
            parent = _parent_of(tasks, t)
            if parent:
                if parent.get("ask_child") == task_id:
                    for f in ("needs_input", "question", "ask_child"):
                        parent.pop(f, None)
                _touch_parent(tasks, parent)

    # -- multi-select bulk actions (board toolbar) --------------------------

    def bulk_move(self, ids, status, force=False):
        """Move several tasks to the end of a status column in one transaction.

        All-or-nothing: if any id is missing, or (moving into doing) any task is still
        blocked, the whole batch is rejected and nothing is written (the transaction
        only saves on a clean exit).
        """
        if status not in STATUSES:
            raise BoardError(f"status must be one of {STATUSES}")
        with self.transaction() as tasks:
            moved = []
            for tid in ids:
                t = self.get(tasks, tid)
                _not_a_subtask(t, "move")
                if status == "doing" and t["status"] != "doing" and not force:
                    unresolved = _unresolved_blockers(tasks, t.get("blocked_by"))
                    if unresolved:
                        raise BoardError(f"{tid} is blocked by: {', '.join(unresolved)}")
                tasks.remove(t)
                if t["status"] != status:
                    _set_status(tasks, t, status)
                    _log(t, f"Moved to {status}")
                t["updated"] = _now()
                _insert(tasks, t, None)
                moved.append(t)
            return moved

    def bulk_archive(self, ids):
        """Archive several tasks (any status) in one transaction — hidden from the
        board, kept for history, restorable with unarchive()."""
        with self.transaction() as tasks:
            touched = []
            for tid in ids:
                for t in (self.get(tasks, tid), *_kids(tasks, tid)):   # a parent's subtasks go with it
                    if not t.get("archived"):
                        t["archived"] = True
                        touched.append(t["id"])
            return touched

    def bulk_set_project(self, ids, project_id):
        """Tie (or untie, with project_id=None) several tasks to a project at once.

        Returns {id: previous project_id or None} so the caller can offer an undo.
        """
        with self._lock():
            data = self._read()
            if project_id:
                self.get_project(data["projects"], project_id)  # raises if missing
            prev = {}
            for tid in ids:
                t = self.get(data["tasks"], tid)
                for x in (t, *_kids(data["tasks"], tid)):   # subtasks inherit the parent's project
                    prev.setdefault(x["id"], x.get("project_id"))
                    if project_id:
                        x["project_id"] = project_id
                    else:
                        x.pop("project_id", None)
                    x["updated"] = _now()
            self._write(data)
            return prev

    # -- projects -------------------------------------------------------

    def load_projects(self):
        with self._lock():
            return self._read()["projects"]

    @staticmethod
    def get_project(projects, project_id):
        for p in projects:
            if p["id"] == project_id:
                return p
        raise BoardError(f"no such project: {project_id}")

    def add_project(self, name, color=None, description="", project_id=None):
        with self.project_transaction() as projects:
            pid = project_id or _unique_id(name, {p["id"] for p in projects})
            if any(p["id"] == pid for p in projects):
                raise BoardError(f"project id already exists: {pid}")
            project = {
                "id": pid,
                "name": name,
                "description": description,
                "created": _now(),
                "updated": _now(),
            }
            if color:
                project["color"] = color
            projects.append(project)
            return project

    def update_project(self, project_id, name=None, color=None, description=None):
        with self.project_transaction() as projects:
            p = self.get_project(projects, project_id)
            if name is not None:
                p["name"] = name
            if color is not None:
                p["color"] = color
            if description is not None:
                p["description"] = description
            p["updated"] = _now()
            return p

    def delete_project(self, project_id):
        """Remove the project and clear it off any tasks that referenced it."""
        with self._lock():
            data = self._read()
            self.get_project(data["projects"], project_id)  # raises if missing
            data["projects"] = [p for p in data["projects"] if p["id"] != project_id]
            for t in data["tasks"]:
                if t.get("project_id") == project_id:
                    t.pop("project_id", None)
            self._write(data)

    def set_project(self, task_id, project_id):
        """Tie (or untie, with project_id=None) a task to a project."""
        with self._lock():
            data = self._read()
            t = self.get(data["tasks"], task_id)
            if project_id:
                self.get_project(data["projects"], project_id)  # raises if missing
            for x in (t, *_kids(data["tasks"], task_id)):
                if project_id:
                    x["project_id"] = project_id
                else:
                    x.pop("project_id", None)
                x["updated"] = _now()
            self._write(data)
            return t

    # -- shared chat (agents self-organizing, visible to the user) ----------

    def chat_send(self, sender, text, kind="agent"):
        """Post a message to the shared channel. kind is 'agent' or 'user' (the human)."""
        if kind not in ("agent", "user"):
            raise BoardError("kind must be 'agent' or 'user'")
        text = (text or "").strip()
        if not text:
            raise BoardError("empty chat message")
        with self._lock():
            data = self._read()
            seq = data["chat_seq"] + 1
            data["chat_seq"] = seq
            msg = {"seq": seq, "at": _now(), "sender": sender, "text": text, "kind": kind}
            data["chat"].append(msg)
            del data["chat"][:-CHAT_MAX]
            self._write(data)
            return msg

    def chat_list(self, after=None, limit=100):
        """Messages after a given seq (for polling), or the last `limit` if after is omitted."""
        with self._lock():
            msgs = self._read()["chat"]
            if after is not None:
                return [m for m in msgs if m["seq"] > after]
            return msgs[-limit:]


LOG_MAX = 200
CHAT_MAX = 500


def _log(t, text):
    """Append to the task's activity history (the card's detail view)."""
    if not text:
        return
    t.setdefault("log", []).append(
        {"at": _now(), "status": t["status"], "progress": t.get("progress", 0), "text": text})
    del t["log"][:-LOG_MAX]


def _clean_title(title):
    if not isinstance(title, str) or not title.strip():
        raise BoardError("a task needs a title")
    return title.strip()


def _parent_must_be_doing(parent, t, verb):
    """Subtasks follow their parent: an open one can only be claimed or updated while the parent is in
    Doing (claim the parent and its open subtasks come with it). Finished subtasks are exempt."""
    if parent and t.get("status") != "done" and parent["status"] != "doing":
        raise BoardError(f"cannot {verb} {t['id']}: its parent {parent['id']} is in {parent['status']}; claim the parent first")


def _require_doing(t, verb):
    if t["status"] != "doing":
        raise BoardError(f"cannot {verb} {t['id']}: it is in {t['status']}, not doing (claim it first)")


def _kids(tasks, parent_id):
    """A task's subtasks, in board order."""
    return [x for x in tasks if x.get("parent_id") == parent_id]


def _parent_of(tasks, t):
    pid = t.get("parent_id")
    return next((x for x in tasks if x["id"] == pid), None) if pid else None


def _check_parent(tasks, parent_id):
    """The parent a new subtask would hang under; raises if it can't (missing, itself a subtask, done)."""
    if not parent_id:
        return None
    parent = next((x for x in tasks if x["id"] == parent_id), None)
    if not parent:
        raise BoardError(f"parent: no such task: {parent_id}")
    if parent.get("parent_id"):
        raise BoardError(f"{parent_id} is itself a subtask; subtasks go one level deep")
    if parent["status"] == "done":
        raise BoardError(f"{parent_id} is done; reopen it before adding subtasks")
    return parent


def _not_a_subtask(t, verb):
    if t.get("parent_id"):
        raise BoardError(f"{t['id']} is a subtask of {t['parent_id']}; subtasks {verb} with their parent")


def parent_pct_hint(task_id, open_kids):
    """Why `update <parent> <pct>` is refused, naming the subtasks to update instead. The prompt for a
    parent (prompt.py) says the same: its % is computed from its subtasks, so you do not set it."""
    ids = "  ".join(k["id"] for k in open_kids)
    return (f"{task_id}: its % is computed from its subtasks (the mean), so you do not set it. "
            f"Update the one you're on: {ids}   "
            f"(for its status line only: agentboard update {task_id} \"<text>\")")


def _recompute(tasks, parent):
    """A parent's progress is the mean of its subtasks' (done ones count as 100)."""
    kids = _kids(tasks, parent["id"])
    if kids:
        parent["progress"] = int(sum(100 if k["status"] == "done" else k.get("progress", 0) for k in kids)
                                 / len(kids) + .5)


def _touch_parent(tasks, parent, text=None):
    """A subtask changed: refresh the parent's computed %, show the latest note, bump its clock."""
    _recompute(tasks, parent)
    if text:
        parent["status_text"] = text
    parent["updated"] = _now()


def _finish(t, at):
    """Close a subtask without a review step (the parent said the deliverable is ready)."""
    if t.get("status_text"):
        t["result"] = t["status_text"]   # keep its last note as the result; marking done clears the line
    _apply_status(t, "done")
    _log(t, "Marked done")
    t["updated"] = at


def _set_status(tasks, t, status):
    """Change a task's column, taking its open subtasks along (done ones stay done)."""
    _apply_status(t, status)
    for k in _kids(tasks, t["id"]):
        if k["status"] == "done":
            continue
        if status == "done":
            _finish(k, _now())
        else:
            _apply_status(k, status)
            if status == "doing" and t.get("agent"):
                k["agent"] = t["agent"]
                if t.get("color"):
                    k["color"] = t["color"]
    _recompute(tasks, t)


def subtask_counts(tasks):
    """{parent_id: (total, done)} over every subtask, archived ones included, so a parent's
    segments keep counting work whose card was cleared from the Done column."""
    out = {}
    for x in tasks:
        pid = x.get("parent_id")
        if pid:
            n, d = out.get(pid, (0, 0))
            out[pid] = (n + 1, d + (x["status"] == "done"))
    return out


def _insert(tasks, t, before_id):
    idx = next((i for i, x in enumerate(tasks) if x["id"] == before_id), None)
    if idx is None:
        last = max((i for i, x in enumerate(tasks) if x["status"] == t["status"]), default=-1)
        idx = last + 1
    tasks.insert(idx, t)


def _apply_status(t, status):
    if status not in STATUSES:
        raise BoardError(f"status must be one of {STATUSES}")
    t["status"] = status
    if status != "done":
        t.pop("result", None)
        t.pop("archived", None)   # reopened work must not stay hidden
    if status == "done":
        t.pop("needs_input", None)
        t.pop("question", None)
        t.pop("review", None)
        t.pop("body_md", None)
        t["progress"] = 100
        t["status_text"] = ""
    elif status in ("backlog", "todo"):
        # progress is kept so work can resume; ownership is released
        t.pop("needs_input", None)
        t.pop("question", None)
        t.pop("review", None)
        t.pop("body_md", None)
        t.pop("agent", None)
        t.pop("color", None)
        if status == "backlog":
            t["progress"] = 0
            t["status_text"] = ""


def _unresolved_blockers(tasks, blocked_by):
    """Blocker ids that still exist and are not done. A missing (deleted) id no longer blocks."""
    by_id = {t["id"]: t for t in tasks}
    return [bid for bid in (blocked_by or []) if bid in by_id and by_id[bid]["status"] != "done"]


def _unique_id(title, taken):
    base = re.sub(r"[^a-z0-9]+", "-", title.lower())[:40].strip("-") or "task"
    tid, n = base, 2
    while tid in taken:
        tid, n = f"{base}-{n}", n + 1
    return tid


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")
