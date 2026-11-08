"""The master lock for a machine that must run none of the risky parts (a work laptop): AGENTBOARD_LOCKDOWN=1.

One small function every risky path calls first, so a copied config.toml cannot switch those paths on. What counts as risky is the
caller's business: a caller passes its own name ("claude", "providers", "backup", ...) and refuses to start when the lock is on.
This module knows no feature names and holds no list of them.

Rules (the same as every other hard-off variable on this board):
  - fail closed: the lock is ON unless the variable is unset or one of "", "0", "false", "no" (any case, spaces ignored);
    "1", "true", "yes", "2", or any other word means locked;
  - the environment is read on every call and never cached, so a test (or a shell) can flip it and nothing can race it;
  - the lock is all or nothing: the feature name only goes into the message.

    from . import lockdown
    lockdown.refuse("claude")        # raises BoardError when locked; returns None when not
    if lockdown.locked("backup"):    # or ask and handle it yourself
        return
"""
import os

ENV = "AGENTBOARD_LOCKDOWN"
_OFF = ("", "0", "false", "no")


def env_on(name, env=None):
    """Is a hard-off variable on: anything but unset, "", 0, false or no. The one rule for every lock here, the plugin gate and doctor
    (`env` lets doctor judge another shell's environment)."""
    return (os.environ if env is None else env).get(name, "").strip().lower() not in _OFF


def locked(feature=None):
    """True when this machine is locked down. `feature` is for the caller's own readability; the answer does not depend on it."""
    return env_on(ENV)


def refuse(feature):
    """Raise BoardError saying `feature` is locked off, when it is; do nothing when it is not."""
    if locked(feature):
        from .store import BoardError   # imported here, not at the top: store imports backup, and backup imports this module
        raise BoardError(f"{feature} is locked off on this machine (${ENV} is set); unset it to allow it")
