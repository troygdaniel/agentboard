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


class LoadAndPluginChecks(unittest.TestCase):
    """With plugins ON, doctor loads them as the server does and runs each plugin's own checks (api.add_doctor). With plugins off it loads
    nothing. A plugin's lines are shaped by the core: the name is prefixed, the text is one masked line, a bad shape or an exception is a FAIL."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTBOARD_")}
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        plugins._reset()
        self.addCleanup(plugins._reset)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.board = Path(self.tmp.name) / ".agentboard"
        self.board.mkdir()

    def load_with(self, register, name="thing"):
        class LiveEP:
            def __init__(self):
                self.name, self.value = name, f"{name}:register"

            def load(self):
                return register
        with mock.patch.dict(os.environ, {"AGENTBOARD_PLUGINS": "1"}), mock.patch("importlib.metadata.entry_points", return_value=[LiveEP()]):
            return doctor.check_plugin_load(self.board)

    def test_off_or_locked_loads_nothing_and_adds_no_line(self):
        def register(api):
            raise AssertionError("loaded while off")
        for env in ({}, {"AGENTBOARD_PLUGINS": "1", "AGENTBOARD_LOCKDOWN": "1"}, {"AGENTBOARD_PLUGINS": "1", "AGENTBOARD_NO_PLUGINS": "1"}):
            with mock.patch.dict(os.environ, env), mock.patch("importlib.metadata.entry_points", side_effect=AssertionError("looked up")):
                self.assertEqual(doctor.check_plugin_load(self.board), [])

    def test_a_plugin_that_loads_is_a_pass_and_its_checks_are_prefixed_with_its_name(self):
        def register(api):
            api.add_doctor(lambda board_dir: [("PASS", "env", f"the env file is fine (board {board_dir.name})"), ("WARN", "Server Keys!", "restart it")])
        r = self.load_with(register)
        self.assertEqual(r[0], (doctor.PASS, "plugin", "plugin thing loads (the same load `agentboard serve` does)"))
        self.assertEqual(r[1], (doctor.PASS, "thing:env", "the env file is fine (board .agentboard)"))
        self.assertEqual(r[2], (doctor.WARN, "thing:serverkeys", "restart it"))

    def test_a_plugin_that_fails_to_load_is_one_fail_with_the_error_class_only(self):
        def register(api):
            raise FileNotFoundError("/opt/someone/secret/page.js")
        r = self.load_with(register)
        self.assertEqual(len(r), 1)
        self.assertEqual((r[0][0], r[0][1]), (doctor.FAIL, "plugin"))
        self.assertIn("plugin thing failed to load: FileNotFoundError", r[0][2])
        self.assertNotIn("/opt/someone", r[0][2])

    def test_a_check_that_raises_or_returns_a_bad_shape_is_a_fail_not_a_crash(self):
        def register(api):
            api.add_doctor(lambda b: (_ for _ in ()).throw(KeyError("texts")))
            api.add_doctor(lambda b: [("LOUD", "x", "y"), ("PASS", "ok", 5), "nope"])
            api.add_doctor(lambda b: 42)
        r = self.load_with(register)
        self.assertEqual(r[1], (doctor.FAIL, "thing", "its doctor check raised KeyError"))
        self.assertEqual([x[0] for x in r[2:5]], [doctor.FAIL] * 3)
        self.assertEqual(r[5], (doctor.FAIL, "thing", "its doctor check raised TypeError"))

    def test_a_plugin_line_is_one_masked_visible_line_and_is_cut(self):
        key = "AKIA" + "ABCDEFGHIJKLMNO7"
        def register(api):
            api.add_doctor(lambda b: [("INFO", "env", f"key\u200b {key} in\nhome.env\x07 " + "x" * 2000)])
        r = self.load_with(register)
        self.assertEqual(len(r), 2)
        text = r[1][2]
        self.assertNotIn(key, text)
        self.assertNotIn("\n", text)
        self.assertNotIn("\x07", text)
        self.assertNotIn("\u200b", text)
        self.assertLessEqual(len(text), doctor.PLUGIN_LINE_MAX)

    def test_too_many_lines_are_cut_with_a_count(self):
        def register(api):
            api.add_doctor(lambda b: [("INFO", "n", str(i)) for i in range(doctor.PLUGIN_LINES_MAX + 3)])
        r = self.load_with(register)
        self.assertEqual(len(r), 1 + doctor.PLUGIN_LINES_MAX + 1)
        self.assertEqual(r[-1], (doctor.INFO, "thing", "and 3 more line(s) not shown"))

    def test_add_doctor_wants_a_callable(self):
        api = plugins.Api(plugins.Plugin("thing"))
        with self.assertRaises(ValueError):
            api.add_doctor("not a function")
        self.assertEqual(plugins.doctor_checks(), [])

    def test_the_whole_report_runs_the_plugin_checks_only_with_the_key(self):
        from tests.test_doctor import FakeRunner
        from pathlib import Path
        def register(api):
            api.add_doctor(lambda b: [("PASS", "env", "fine")])
        class LiveEP:
            name, value = "thing", "thing:register"
            def load(self):
                return register
        with mock.patch.object(Path, "home", return_value=Path(self.tmp.name) / "home"), mock.patch("importlib.metadata.entry_points", return_value=[LiveEP()]):
            names = [r[1] for r in doctor.run(self.board, env={}, runner=FakeRunner())]
            self.assertNotIn("thing:env", names)
            with mock.patch.dict(os.environ, {"AGENTBOARD_PLUGINS": "1"}):
                names = [r[1] for r in doctor.run(self.board, env={"AGENTBOARD_PLUGINS": "1"}, runner=FakeRunner())]
            self.assertIn("plugin", names)
            self.assertIn("thing:env", names)


if __name__ == "__main__":
    unittest.main()
