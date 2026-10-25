"""Backups of the board's one data file, so a bad write, a wrong delete or a cleared browser can never lose the board.

* Every save is atomic and keeps the previous version as `tasks.json.bak` (a hard link: no copy, no gap where the file is missing).
* Snapshots go to `.agentboard/backups/tasks-YYYYMMDD-HHMM.json.gz`, at most one an hour, taken by whatever saves next (and by `agentboard serve` on a timer).
  Kept: the newest of each hour for 48 hours, the newest of each day for 30 days. Files that do not have that exact name (a manual snapshot, `*-before-restore*`) are never pruned.
* Once a day, if `[backup] sync_dir` is set in config.toml (an iCloud or Google Drive folder on this Mac), the newest snapshot is copied there too and the copies are pruned to 30 days.
Everything is local files: no network. `agentboard backup | restore | verify` are the commands; the HUD shows the age of the newest snapshot."""
from __future__ import annotations

import contextlib
import gzip
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

HOURLY_KEEP_H, DAILY_KEEP_D, SYNC_KEEP_D = 48, 30, 30
EVERY_MIN = 60
SYNC_AFTER_HOUR = 2   # the nightly copy happens after 02:00 local time
STAMP = "%Y%m%d-%H%M"
AUTO = re.compile(r"^tasks-(\d{8}-\d{4})\.json(\.gz)?$")   # what pruning may touch (the .json form is a hand-made snapshot of the same name)
STALE_MIN = 120   # `verify` says the backups are stale after this long


# -- atomic writes ----------------------------------------------------------------------------------------------------------------------
def write_atomic(path: Path, text: str, keep_previous: bool = True) -> None:
    """Write `text` to `path` through a temp file in the same directory, flushed to disk, then renamed over it. The previous version stays as `<path>.bak`."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if keep_previous and path.exists():
            link = f"{tmp}.bak"
            with contextlib.suppress(OSError):   # a filesystem without hard links just goes without the .bak
                os.link(path, link)
                os.replace(link, f"{path}.bak")
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    with contextlib.suppress(OSError):   # make the rename itself durable
        dfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)


# -- verify -----------------------------------------------------------------------------------------------------------------------------
def read_text(path: Path) -> str:
    path = Path(path)
    return gzip.open(path, "rt").read() if path.suffix == ".gz" else path.read_text()


def check(text: str) -> tuple[bool, str, dict]:
    """(ok, message, counts) for the text of a board file: valid JSON, a task list with unique ids and known statuses."""
    try:
        data = json.loads(text)
    except ValueError as e:
        return False, f"not valid JSON ({e})", {}
    if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
        return False, "no task list", {}
    ids = [t.get("id") for t in data["tasks"] if isinstance(t, dict)]
    if len(ids) != len(data["tasks"]) or not all(isinstance(i, str) and i for i in ids):
        return False, "a task has no id", {}
    if len(set(ids)) != len(ids):
        dup = sorted({i for i in ids if ids.count(i) > 1})
        return False, f"duplicate task ids: {', '.join(dup[:5])}", {}
    bad = sorted({t.get("status") for t in data["tasks"] if t.get("status") not in ("backlog", "todo", "doing", "done")}, key=str)
    if bad:
        return False, f"unknown status: {bad}", {}
    counts = {"tasks": len(ids), "projects": len(data.get("projects") or []), "chat": len(data.get("chat") or [])}
    return True, "ok", counts


def verify_file(path: Path) -> tuple[bool, str, dict]:
    try:
        return check(read_text(path))
    except (OSError, EOFError, gzip.BadGzipFile) as e:
        return False, f"unreadable ({e})", {}


# -- snapshots --------------------------------------------------------------------------------------------------------------------------
class Backups:
    def __init__(self, board_dir: Path, conf: dict | None = None):
        self.dir = Path(board_dir)
        self.path = self.dir / "tasks.json"
        self.snap_dir = self.dir / "backups"
        if conf is None:
            try:
                import tomllib

                conf = tomllib.loads((self.dir / "config.toml").read_text())
            except (OSError, ValueError):
                conf = {}
        sect = conf.get("backup", {}) if isinstance(conf, dict) else {}
        self.conf = sect if isinstance(sect, dict) else {}
        self.state_path = self.snap_dir / ".state.json"

    # naming
    def _name(self, when: datetime) -> str:
        return f"tasks-{when.strftime(STAMP)}.json.gz"

    @staticmethod
    def stamp(name: str) -> datetime | None:
        m = AUTO.match(name)
        return datetime.strptime(m.group(1), STAMP) if m else None

    def snapshots(self) -> list[Path]:
        """Every snapshot file (named by us or by hand), newest first."""
        if not self.snap_dir.is_dir():
            return []
        files = [p for p in self.snap_dir.iterdir() if p.is_file() and p.name.startswith("tasks-") and (p.suffix == ".gz" or p.suffix == ".json")]
        return sorted(files, key=lambda p: (p.stat().st_mtime, p.name), reverse=True)

    def latest(self) -> Path | None:
        s = self.snapshots()
        return s[0] if s else None

    def latest_auto(self) -> Path | None:
        """The newest regular snapshot (not a hand-named one such as before-restore): what `restore latest` means."""
        s = [p for p in self.snapshots() if AUTO.match(p.name)]
        return s[0] if s else self.latest()

    def age_minutes(self, now: datetime | None = None) -> float | None:
        p = self.latest()
        if p is None:
            return None
        return ((now or datetime.now()).timestamp() - p.stat().st_mtime) / 60

    # taking one
    def take(self, label: str = "", when: datetime | None = None) -> Path:
        """Snapshot tasks.json now (gzip, flushed). A label gives a name that pruning never touches."""
        when = when or datetime.now()
        text = self.path.read_text()
        self.snap_dir.mkdir(parents=True, exist_ok=True)
        name = self._name(when) if not label else f"tasks-{when.strftime(STAMP)}-{re.sub(r'[^a-z0-9]+', '-', label.lower()).strip('-')}.json.gz"
        dest = self.snap_dir / name
        fd, tmp = tempfile.mkstemp(dir=self.snap_dir, prefix=".snap-", suffix=".tmp")
        with os.fdopen(fd, "wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", mtime=int(when.timestamp())) as gz:
                gz.write(text.encode())
            raw.flush()
            os.fsync(raw.fileno())
        os.replace(tmp, dest)
        os.utime(dest, (when.timestamp(), when.timestamp()))
        return dest

    def due(self, now: datetime | None = None) -> bool:
        age = self.age_minutes(now)
        return age is None or age >= EVERY_MIN

    def tick(self, now: datetime | None = None) -> Path | None:
        """Called after saves and by the server's timer: snapshot when the newest is an hour old (only if the file is a valid board), prune, and do the nightly copy.
        Never raises: a backup problem must not stop a save."""
        now = now or datetime.now()
        taken = None
        try:
            if self.path.exists() and self.due(now):
                ok, _, _ = verify_file(self.path)
                if ok:
                    taken = self.take(when=now)
            self.prune(now)
            self.sync(now)
        except Exception:   # noqa: BLE001
            pass
        return taken

    # retention
    def prune(self, now: datetime | None = None) -> list[Path]:
        """Keep the newest snapshot of each hour for 48 hours and of each day for 30 days; delete the other auto-named ones. Hand-named files stay."""
        now = now or datetime.now()
        autos = []
        for p in self.snapshots():
            st = self.stamp(p.name)
            if st is not None:
                autos.append((st, p))
        autos.sort(key=lambda x: x[0], reverse=True)
        keep: set[Path] = set()
        hours: set[str] = set()
        days: set[str] = set()
        for st, p in autos:
            age = now - st
            hour_key, day_key = st.strftime("%Y%m%d%H"), st.strftime("%Y%m%d")
            if age <= timedelta(hours=HOURLY_KEEP_H) and hour_key not in hours:
                hours.add(hour_key)
                keep.add(p)
            if age <= timedelta(days=DAILY_KEEP_D) and day_key not in days:
                days.add(day_key)
                keep.add(p)
        gone = []
        for _, p in autos:
            if p not in keep:
                with contextlib.suppress(OSError):
                    p.unlink()
                    gone.append(p)
        return gone

    # nightly copy
    def sync_dir(self) -> Path | None:
        v = self.conf.get("sync_dir")
        return Path(v).expanduser() if isinstance(v, str) and v.strip() else None

    def _state(self) -> dict:
        try:
            return json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            return {}

    def last_sync(self) -> str | None:
        return self._state().get("last_sync")

    def sync(self, now: datetime | None = None, force: bool = False) -> Path | None:
        """Copy the newest snapshot to the sync folder once a day (after 02:00), or now with force. Returns the copy, or None when nothing was due."""
        dest_dir = self.sync_dir()
        now = now or datetime.now()
        if dest_dir is None:
            return None
        today = now.strftime("%Y%m%d")
        if not force and (now.hour < SYNC_AFTER_HOUR or self._state().get("last_sync_day") == today):
            return None
        src = self.latest()
        if src is None:
            return None
        dest_dir.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r"[^A-Za-z0-9._-]+", "-", self.dir.parent.name or "board")
        dest = dest_dir / f"agentboard-{stem}-{today}.json.gz"
        tmp = dest_dir / f".{dest.name}.tmp"
        shutil.copyfile(src, tmp)
        os.replace(tmp, dest)
        cutoff = now - timedelta(days=SYNC_KEEP_D)
        for p in dest_dir.glob(f"agentboard-{stem}-*.json.gz"):
            m = re.search(r"-(\d{8})\.json\.gz$", p.name)
            if m and datetime.strptime(m.group(1), "%Y%m%d") < cutoff:
                with contextlib.suppress(OSError):
                    p.unlink()
        self.snap_dir.mkdir(parents=True, exist_ok=True)
        write_atomic(self.state_path, json.dumps({**self._state(), "last_sync": now.strftime("%Y-%m-%dT%H:%M:%S"), "last_sync_day": today, "last_sync_path": str(dest)}), keep_previous=False)
        return dest

    # restoring
    def resolve(self, which: str) -> Path:
        if which == "latest":
            p = self.latest_auto()
            if p is None:
                raise FileNotFoundError("there are no snapshots yet")
            return p
        p = Path(which).expanduser()
        if not p.exists() and (self.snap_dir / which).exists():
            p = self.snap_dir / which
        if not p.exists() and Path(f"{self.path}.bak").exists() and which in ("bak", "previous"):
            p = Path(f"{self.path}.bak")
        if not p.exists():
            raise FileNotFoundError(f"no such backup: {which}")
        return p

    def restore(self, which: str) -> tuple[Path, Path | None]:
        """Put a snapshot back as tasks.json. The snapshot is verified first; the board as it is now is kept as a `before-restore` snapshot. Returns (source, safety copy)."""
        src = self.resolve(which)
        text = read_text(src)
        ok, msg, _ = check(text)
        if not ok:
            raise ValueError(f"{src.name} is not a good board file: {msg}")
        saved = None
        if self.path.exists() and verify_file(self.path)[0]:
            saved = self.take("before-restore")
        write_atomic(self.path, text)
        return src, saved

    def status(self, now: datetime | None = None) -> dict:
        age = self.age_minutes(now)
        return {"last_backup_min": None if age is None else int(age), "snapshots": len(self.snapshots()), "last_sync": self.last_sync(), "sync_dir": str(self.sync_dir()) if self.sync_dir() else None}


def human_age(minutes: float | None) -> str:
    if minutes is None:
        return "never"
    m = int(minutes)
    if m < 1:
        return "just now"
    if m < 90:
        return f"{m} min ago"
    if m < 48 * 60:
        return f"{m // 60} h ago"
    return f"{m // (24 * 60)} days ago"

