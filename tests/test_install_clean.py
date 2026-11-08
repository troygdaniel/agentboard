"""Installing from a checkout you have used before can bring back files that were deleted from src/ (Nov 7 red-team round 2).

pip builds inside the checkout and setuptools copies into build/ without removing what is no longer in src/, so a module deleted from the source (the text features
once) was reinstalled from build/. The documented fix is to remove build/ first. Two tests keep it honest:
  1. every documented install-from-a-checkout command in the docs removes build/ first (or starts from a fresh clone, which has none);
  2. in a scratch copy, a wheel built after removing build/ no longer holds a module deleted from src/ (needs an interpreter with pip and setuptools; offline).
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).parents[1]
DOCS = ["README.md", "CLAUDE.md", "SECURITY.md"]
# an install from the current folder: `pipx install .`, `pip install .` (not `-e`, which does not copy through build/)
INSTALL_HERE = re.compile(r"\b(?:pipx|pip) install \.(?![\w/.-])")


class DocumentedCommands(unittest.TestCase):
    def test_every_install_from_a_checkout_removes_build_first_or_starts_from_a_clone(self):
        bad, seen = [], 0
        for name in DOCS:
            for i, line in enumerate((ROOT / name).read_text().splitlines(), 1):
                m = INSTALL_HERE.search(line)
                if not m:
                    continue
                seen += 1
                before = line[:m.start()]
                if "rm -rf build" not in before and "git clone" not in before:
                    bad.append(f"{name}:{i}: {line.strip()[:110]}")
        self.assertGreaterEqual(seen, 4, "the scan found no install commands: has the wording changed?")
        self.assertEqual(bad, [], "a documented install from a checkout does not remove build/ first")

    def test_the_readme_says_why(self):
        text = (ROOT / "README.md").read_text()
        self.assertIn("Always remove `build/`", text)
        self.assertIn("stale install", text)   # and that doctor warns about it

    def test_doctors_fix_removes_build_too(self):
        src = (ROOT / "src" / "agentboard" / "doctor.py").read_text()
        i = src.index("fix: pipx uninstall agentboard")
        self.assertLess(src.index("rm -rf", i), src.index("pipx install", i + 10), "doctor's fix would reinstall the same stale files")


def interpreter_with_setuptools():
    """An interpreter that can build this project offline: pip, and the setuptools the project asks for (pyproject.toml: setuptools>=68). An older one
    (macOS's /usr/bin/python3 with an empty HOME has 58) does not read the [project] table and builds an UNKNOWN-0.0.0 wheel with none of our files: that
    is a machine that cannot run this check, not a stale build."""
    for py in (sys.executable, "/usr/bin/python3", shutil.which("python3")):
        if py and Path(py).exists():
            ok = subprocess.run([py, "-c", "import setuptools, pip; raise SystemExit(0 if int(setuptools.__version__.split('.')[0]) >= 68 else 1)"], capture_output=True)
            if ok.returncode == 0:
                return py
    return None


class StaleBuildFolder(unittest.TestCase):
    def build(self, py, folder, out):
        got = subprocess.run([py, "-m", "pip", "wheel", "--no-build-isolation", "--no-deps", "--ignore-requires-python", "--disable-pip-version-check", "-q", "-w", str(out), "."],
                             cwd=folder, capture_output=True, text=True, timeout=180, env={**os.environ, "PIP_NO_INDEX": "1"})
        self.assertEqual(got.returncode, 0, got.stdout + got.stderr)
        wheels = sorted(Path(out).glob("*.whl"), key=lambda p: p.stat().st_mtime)
        return set(zipfile.ZipFile(wheels[-1]).namelist())

    def test_removing_build_first_leaves_no_module_that_was_deleted_from_src(self):
        py = interpreter_with_setuptools()
        if not py:
            self.skipTest("no interpreter with pip and setuptools to build with (offline)")
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "checkout"
            (work / "src").mkdir(parents=True)
            shutil.copy(ROOT / "pyproject.toml", work)
            shutil.copy(ROOT / "README.md", work)
            shutil.copytree(ROOT / "src" / "agentboard", work / "src" / "agentboard", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            gone = work / "src" / "agentboard" / "zz_removed_module.py"
            gone.write_text("# a module the next commit deletes\n")
            first = self.build(py, work, Path(tmp) / "out1")
            self.assertIn("agentboard/zz_removed_module.py", first, "the scratch build did not include the module it should")
            gone.unlink()                                          # the commit that deletes it
            self.build(py, work, Path(tmp) / "out2")               # a build that forgets to clean: setuptools may keep the file (the hazard, not asserted)
            shutil.rmtree(work / "build")                          # the documented step: rm -rf build
            third = self.build(py, work, Path(tmp) / "out3")
            self.assertNotIn("agentboard/zz_removed_module.py", third, "a deleted module came back even after build/ was removed")
            self.assertIn("agentboard/cli.py", third)              # and the rest is still there


if __name__ == "__main__":
    unittest.main()
