"""`doctor --strict` can pass on a correct work-profile machine (finding-doctor-strict-cannot-pass-on-a-w).

The README and SECURITY.md offer `agentboard doctor --strict` for a review, and the work-setup steps say two WARN lines are normal there and need
no fix: the Stop hook is not installed, and the list of modules that could make a connection (each off under the lock). --strict counted them, so
it exited 1 on every correct work setup. Under the work profile those two no longer fail --strict; any other WARN still does, a FAIL always does,
and away from the work profile --strict is as strict as before."""
import unittest

from agentboard import doctor

P, W, F = doctor.PASS, doctor.WARN, doctor.FAIL
HOOK = (W, "Stop hook", "not installed: run agentboard hooks install --user once from the board's folder, then restart sessions")
CODE = (W, "code", "modules that can make an outbound connection: lifecycle, providers; modules that can listen: server. Beyond the core (x): providers: each is off unless configured; check the lock above")
OK = (P, "listen", "127.0.0.1:8765 only")


class StrictUnderTheWorkProfile(unittest.TestCase):
    def test_the_two_expected_warns_do_not_fail_strict_under_the_work_profile(self):
        self.assertEqual(doctor.exit_code([OK, HOOK, CODE], strict=True, work=True), 0)

    def test_they_still_fail_strict_away_from_the_work_profile(self):
        self.assertEqual(doctor.exit_code([OK, HOOK, CODE], strict=True), 1)
        self.assertEqual(doctor.exit_code([OK, HOOK], strict=True, work=False), 1)

    def test_any_other_warn_fails_strict_under_the_work_profile(self):
        for other in ((W, "plugins", "ON"), (W, "config", "chat.autopilot starts a program"), (W, "watchdog", "a claim is stale"),
                      (W, "Stop hook", "~/.claude/settings.json: installed for another board"), (W, "lock", "AGENTBOARD_LOCKDOWN is not set")):
            self.assertEqual(doctor.exit_code([OK, HOOK, CODE, other], strict=True, work=True), 1, other)

    def test_a_fail_always_fails(self):
        self.assertEqual(doctor.exit_code([OK, (F, "listen", "0.0.0.0")], strict=False, work=True), 1)
        self.assertEqual(doctor.exit_code([OK, (F, "listen", "0.0.0.0")], strict=True, work=True), 1)

    def test_without_strict_a_warn_never_fails(self):
        self.assertEqual(doctor.exit_code([OK, HOOK, CODE, (W, "plugins", "ON")]), 0)

    def test_the_command_tells_exit_code_whether_the_profile_is_on(self):
        from pathlib import Path
        src = (Path(doctor.__file__).parent / "cli.py").read_text()
        self.assertIn("doctor.exit_code(results, strict=a.strict, work=bool(profilelib.sources(board)))", src)


if __name__ == "__main__":
    unittest.main()
