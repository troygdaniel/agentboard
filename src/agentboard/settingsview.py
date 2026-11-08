"""What the Settings sheet's Security and Backup and data tabs show (docs/settings-tabs-design.md): one read-only status, GET /api/settings.

The rule is `agentboard config show`'s: on or off, counts and ages, never a path, a pattern, a name or a secret. So the whole answer is booleans,
whole numbers and nulls: no string leaves this module (a test pins that, and that nothing from a config or a folder name can be in it). The route
sits behind the server's Host check like every other; there is no route that changes any of it, and the page cannot: each row names the key or the
command that does."""
import os
from datetime import datetime

from . import lockdown, plugins, profile, redact
from .backup import Backups


def _minutes_since(stamp):
    """Whole minutes since an ISO timestamp, or None when there is none or it cannot be read."""
    if not stamp:
        return None
    try:
        return max(0, int((datetime.now() - datetime.fromisoformat(str(stamp))).total_seconds() // 60))
    except (TypeError, ValueError):
        return None


def _backup(board_dir):
    """The backup block, each field on its own: a snapshot folder that cannot be read must not turn the sync flag off, and an odd `sync_dir` must not
    turn the snapshot count to zero (`sync_dir = "~nosuchuser/x"` makes Path.expanduser raise; the flag is read from the config string, not from that)."""
    snapshots, last_min, sync, last_sync_min = 0, None, False, None
    try:
        b = Backups(board_dir)
    except Exception:   # noqa: BLE001
        return {"snapshots": 0, "last_min": None, "sync": False, "last_sync_min": None}
    try:
        snapshots = len(b.snapshots())
    except Exception:   # noqa: BLE001
        pass
    try:
        age = b.age_minutes()
        last_min = None if age is None else max(0, int(age))   # a snapshot dated in the future is "just now", not minus millions
    except Exception:   # noqa: BLE001
        pass
    try:
        v = b.conf.get("sync_dir")
        sync = isinstance(v, str) and bool(v.strip()) and not lockdown.locked("backup-sync")
    except Exception:   # noqa: BLE001
        pass
    try:
        last_sync_min = _minutes_since(b.last_sync())
    except Exception:   # noqa: BLE001
        pass
    return {"snapshots": snapshots, "last_min": last_min, "sync": sync, "last_sync_min": last_sync_min}


def status(board_dir):
    """The status as plain booleans, counts and minutes. Anything that cannot be read is reported as off or None, never as an error text."""
    try:
        conf = redact.settings(board_dir)
    except Exception:   # noqa: BLE001  (a broken config.toml must not break the sheet: masking then reads as its default)
        conf = dict(redact.DEFAULTS, extra=[])
    try:
        private = (os.stat(board_dir).st_mode & 0o077) == 0
    except OSError:
        private = False
    return {
        "lockdown": bool(lockdown.locked()),
        "profile": bool(profile.in_effect()),
        "plugins": {"allowed": plugins.disabled_reason() is None, "loaded": len(plugins.active()), "failed": len(plugins.failed())},
        "redact": {"enabled": bool(conf.get("enabled", True)), "phones": bool(conf.get("phones")), "extra": len(conf.get("extra") or [])},
        "backup": _backup(board_dir),
        "data_private": private,
    }
