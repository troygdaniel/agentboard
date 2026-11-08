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


def status(board_dir):
    """The status as plain booleans, counts and minutes. Anything that cannot be read is reported as off or None, never as an error text."""
    try:
        conf = redact.settings(board_dir)
    except Exception:   # noqa: BLE001  (a broken config.toml must not break the sheet: masking then reads as its default)
        conf = dict(redact.DEFAULTS, extra=[])
    try:
        b = Backups(board_dir).status()
    except Exception:   # noqa: BLE001
        b = {}
    try:
        private = (os.stat(board_dir).st_mode & 0o077) == 0
    except OSError:
        private = False
    return {
        "lockdown": bool(lockdown.locked()),
        "profile": bool(profile.in_effect()),
        "plugins": {"allowed": plugins.disabled_reason() is None, "loaded": len(plugins.active()), "failed": len(plugins.failed())},
        "redact": {"enabled": bool(conf.get("enabled", True)), "phones": bool(conf.get("phones")), "extra": len(conf.get("extra") or [])},
        "backup": {"snapshots": int(b.get("snapshots") or 0), "last_min": b.get("last_backup_min"), "sync": bool(b.get("sync_dir")), "last_sync_min": _minutes_since(b.get("last_sync"))},
        "data_private": private,
    }
