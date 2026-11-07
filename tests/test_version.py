"""The version is written in three places a person reads: pyproject.toml (what pip installs), __init__.py (what --version prints and
doctor reports) and the README's --version line. They must agree: a release bumps all three, and this fails the day one is forgotten."""
import re
import tomllib
import unittest
from pathlib import Path

import agentboard

ROOT = Path(agentboard.__file__).resolve().parents[2]


class VersionAgrees(unittest.TestCase):
    def test_init_matches_pyproject(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
        self.assertEqual(agentboard.__version__, project["version"], "bump src/agentboard/__init__.py together with pyproject.toml")

    def test_the_readme_says_what_version_prints(self):
        m = re.search(r"agentboard --version\s+# prints: (\S+)", (ROOT / "README.md").read_text())
        self.assertIsNotNone(m, "README.md lost its '# prints:' line for agentboard --version")
        self.assertEqual(m.group(1), agentboard.__version__)

    def test_it_looks_like_a_version(self):
        self.assertRegex(agentboard.__version__, r"^\d+\.\d+\.\d+$")

    def test_the_cli_prints_it(self):
        import contextlib
        import io
        from agentboard import cli
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            with self.assertRaises(SystemExit):
                cli.main(["--version"])
        self.assertIn(agentboard.__version__, out.getvalue())


if __name__ == "__main__":
    unittest.main()
