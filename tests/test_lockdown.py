"""The master lock (AGENTBOARD_LOCKDOWN): fail closed, read on every call, generic."""
import os
import unittest
from pathlib import Path
from unittest import mock

from agentboard import lockdown
from agentboard.store import BoardError


def env(value):
    """The environment with the lock set to `value`, or removed when None."""
    return mock.patch.dict(os.environ, {} if value is None else {lockdown.ENV: value}, clear=False)


class LockdownTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop(lockdown.ENV, None)   # a shell that already has the lock set must not leak into these tests
        self.addCleanup(os.environ.pop, lockdown.ENV, None)

    def test_unset_and_the_off_words_do_not_lock(self):
        self.assertFalse(lockdown.locked())
        for v in ("", "0", "false", "no", "FALSE", "No", "  0  ", " "):
            with env(v):
                self.assertFalse(lockdown.locked("x"), repr(v))

    def test_anything_else_locks_it_fails_closed(self):
        for v in ("1", "true", "yes", "2", "on", "locked", "maybe", "off", "00", "nope"):
            with env(v):
                self.assertTrue(lockdown.locked("x"), repr(v))

    def test_read_on_every_call_never_cached(self):
        self.assertFalse(lockdown.locked())
        with env("1"):
            self.assertTrue(lockdown.locked())
        self.assertFalse(lockdown.locked())
        os.environ[lockdown.ENV] = "1"
        self.assertTrue(lockdown.locked())
        os.environ[lockdown.ENV] = "0"
        self.assertFalse(lockdown.locked())

    def test_the_feature_name_does_not_change_the_answer(self):
        with env("1"):
            self.assertEqual({lockdown.locked(f) for f in (None, "claude", "providers", "a-plugin", "")}, {True})

    def test_refuse_raises_with_the_name_and_the_variable_only_when_locked(self):
        lockdown.refuse("claude")   # not locked: returns None
        with env("1"):
            with self.assertRaises(BoardError) as cm:
                lockdown.refuse("claude")
        self.assertIn("claude", str(cm.exception))
        self.assertIn("AGENTBOARD_LOCKDOWN", str(cm.exception))

    def test_the_module_is_generic_it_names_no_feature_of_the_core(self):
        src = Path(lockdown.__file__).read_text().lower()
        for word in ("twilio", "sms", "pull-texts", "texts"):
            self.assertNotIn(word, src)


if __name__ == "__main__":
    unittest.main()
