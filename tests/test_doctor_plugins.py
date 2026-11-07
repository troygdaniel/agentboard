"""agentboard doctor's plugins line: the gate and the installed entry-point names, read from metadata only. Nothing is imported or run."""
import os
import sys
import unittest
from unittest import mock

from agentboard import doctor, plugins


class EP:
    """An entry point as importlib.metadata lists it. Loading one would run plugin code, so load() fails the test."""
    def __init__(self, name, value):
        self.name, self.value = name, value

    def load(self):
        raise AssertionError("doctor loaded a plugin")


class PluginsLine(unittest.TestCase):
    def setUp(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def line(self, eps, **env):
        with mock.patch.dict(os.environ, env), mock.patch("importlib.metadata.entry_points", return_value=eps) as found:
            r = doctor.check_plugins()
        found.assert_called_once_with(group=plugins.GROUP)
        self.assertEqual(len(r), 1)
        return r[0]

    HOME = [EP("home", "agentboard_home:register")]

    def test_no_key_is_a_pass_that_names_what_is_installed_but_not_loaded(self):
        r = self.line(self.HOME)
        self.assertEqual((r[0], r[1]), (doctor.PASS, "plugins"))
        self.assertIn("off", r[2])
        self.assertIn("nothing is looked up, imported or run", r[2])
        self.assertIn("installed but not loaded: home (agentboard_home)", r[2])

    def test_nothing_installed_says_so(self):
        self.assertIn("none are installed", self.line([])[2])
        self.assertEqual(self.line([])[0], doctor.PASS)

    def test_every_lock_keeps_it_a_pass_even_with_the_key_set(self):
        for env in ({"AGENTBOARD_PLUGINS": "1", "AGENTBOARD_LOCKDOWN": "1"}, {"AGENTBOARD_PLUGINS": "1", "AGENTBOARD_NO_PLUGINS": "1"},
                    {"AGENTBOARD_PLUGINS": "true"}, {"AGENTBOARD_PLUGINS": "2"}):
            r = self.line(self.HOME, **env)
            self.assertEqual(r[0], doctor.PASS, env)
            self.assertIn("locked" if "LOCKDOWN" in str(env) or "NO_PLUGINS" in str(env) else "off", r[2])

    def test_with_the_key_set_and_no_lock_it_is_a_warning_naming_the_code_that_runs(self):
        r = self.line(self.HOME, AGENTBOARD_PLUGINS="1")
        self.assertEqual(r[0], doctor.WARN)
        self.assertIn("home (agentboard_home)", r[2])
        self.assertIn("runs inside agentboard", r[2])
        self.assertEqual(self.line([], AGENTBOARD_PLUGINS="1")[0], doctor.INFO)

    def test_nothing_is_ever_imported_or_loaded(self):
        sys.modules.pop("agentboard_home", None)
        self.line(self.HOME, AGENTBOARD_PLUGINS="1")
        self.line(self.HOME)
        self.assertNotIn("agentboard_home", sys.modules)        # (EP.load raising would already have failed the test)
        self.assertEqual(plugins.active(), [])                  # and the plugin registry was never touched

    def test_unreadable_metadata_is_not_a_crash(self):
        with mock.patch("importlib.metadata.entry_points", side_effect=RuntimeError("odd dist")):
            self.assertEqual(doctor.check_plugins()[0][0], doctor.PASS)
        with mock.patch.dict(os.environ, {"AGENTBOARD_PLUGINS": "1"}), mock.patch("importlib.metadata.entry_points", side_effect=RuntimeError("odd dist")):
            self.assertEqual(doctor.check_plugins()[0][0], doctor.WARN)

    def test_the_whole_report_carries_the_line(self):
        from tests.test_doctor import FakeRunner
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d, mock.patch("importlib.metadata.entry_points", return_value=self.HOME), \
                mock.patch.object(Path, "home", return_value=Path(d) / "home"):
            board = Path(d) / "proj" / ".agentboard"
            board.mkdir(parents=True)
            names = [r[1] for r in doctor.run(board, env={}, runner=FakeRunner())]
        self.assertIn("plugins", names)


if __name__ == "__main__":
    unittest.main()
