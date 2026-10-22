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
            return {"tasks": [], "projects": []}
        except ValueError as e:
            raise BoardError(f"{self.path} is not valid JSON ({e}); fix or delete it") from e
        data.setdefault("tasks", [])
        data.setdefault("projects", [])
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

    def add(self, title, description="", status="backlog", ctx=None, task_id=None, project_id=None, blocked_by=None):
        if status not in STATUSES:
            raise BoardError(f"status must be one of {STATUSES}")
        with self.transaction() as tasks:
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
            _log(task, f"Added to {status}")
            tasks.append(task)
            return task

    def start(self, title, name, color=None, description="", task_id=None, project_id=None,
              blocked_by=None, force=False):
        """Agent announces new work: create the task already in doing, owned by name."""
        with self.transaction() as tasks:
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
            _log(task, f"Started by {name}")
            tasks.append(task)
            return task

    def claim(self, task_id, name, color=None, force=False):
        with self.transaction() as tasks:
            t = self.get(tasks, task_id)
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
            t.pop("review", None)
            t.pop("body_md", None)
            t["status_text"] = f"Claimed by {name}"
            _log(t, f"Claimed by {name}")
            t["updated"] = _now()
            return t

    def ask(self, task_id, question, body_md=None):
        """Agent flags that it is blocked on the user. Cleared by the next update.

        body_md is an optional richer markdown body (a recap, a diff, a report) shown
        in the detail panel alongside the one-line question; it is untrusted agent
        text, rendered safely by the server (see markdown.to_html) rather than here.
        """
        with self.transaction() as tasks:
            t = self.get(tasks, task_id)
            t["needs_input"] = True
            t["question"] = question
            t["status_text"] = question
            if body_md:
                t["body_md"] = body_md
            else:
                t.pop("body_md", None)
            _log(t, f"Needs input: {question}")
            t["updated"] = _now()
            return t

    def review(self, task_id, summary, body_md=None):
        """Agent reports the work complete and hands it to the user for sign-off.

        body_md is an optional richer markdown body (a recap, a diff, a report); see
        ask() for how it's handled.
        """
        with self.transaction() as tasks:
            t = self.get(tasks, task_id)
            t.pop("needs_input", None)
            t.pop("question", None)
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
            return t

    def update(self, task_id, progress=None, text=None, status=None):
        with self.transaction() as tasks:
            t = self.get(tasks, task_id)
            t.pop("needs_input", None)
            t.pop("question", None)
            t.pop("review", None)
            t.pop("body_md", None)
            if progress is not None:
                t["progress"] = max(0, min(100, int(progress)))
            if text is not None:
                t["status_text"] = text
                if status == "done":
                    t["result"] = text
            if status:
                _apply_status(t, status)
            _log(t, "Marked done" if status == "done" else text)
            t["updated"] = _now()
            return t

    def move(self, task_id, status, before_id=None):
        """Change column and/or position (used by drag-and-drop)."""
        if status not in STATUSES:
            raise BoardError(f"status must be one of {STATUSES}")
        with self.transaction() as tasks:
            t = self.get(tasks, task_id)
            tasks.remove(t)
            if t["status"] != status:
                _apply_status(t, status)
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

    def restore(self, snapshot, before_id=None):
        """Put a task back exactly as it was (undo for moves)."""
        if snapshot.get("status") not in STATUSES:
            raise BoardError(f"status must be one of {STATUSES}")
        with self.transaction() as tasks:
            tasks.remove(self.get(tasks, snapshot["id"]))
            snap = dict(snapshot)
            _insert(tasks, snap, before_id)
            return snap

    def clear_done(self):
        """Archive every Done task: hidden from the board, kept for history and the HUD."""
        with self.transaction() as tasks:
            ids = [t["id"] for t in tasks if t["status"] == "done" and not t.get("archived")]
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
            return t

    def delete(self, task_id):
        with self.transaction() as tasks:
            tasks.remove(self.get(tasks, task_id))

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
                t["project_id"] = project_id
            else:
                t.pop("project_id", None)
            t["updated"] = _now()
            self._write(data)
            return t


LOG_MAX = 200


def _log(t, text):
    """Append to the task's activity history (the card's detail view)."""
    if not text:
        return
    t.setdefault("log", []).append(
        {"at": _now(), "status": t["status"], "progress": t.get("progress", 0), "text": text})
    del t["log"][:-LOG_MAX]


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
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "task"
    tid, n = base, 2
    while tid in taken:
        tid, n = f"{base}-{n}", n + 1
    return tid


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")
