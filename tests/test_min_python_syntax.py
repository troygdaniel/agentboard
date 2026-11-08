"""The package must compile under the oldest Python the README and pyproject promise (overnight-qa-cleanroom).

On 2026-11-07 a clean-room install on Python 3.11 installed fine and then `agentboard` died with a SyntaxError: an f-string in reports.py
used the same quote inside its braces (allowed from 3.12, PEP 701), so every command and 165 tests failed on 3.11. `ast.parse(...,
feature_version=(3, 11))` on a newer interpreter does not catch that case (it is a tokenizer change), so the only honest check is the old
interpreter itself: when `python3.11` is on PATH, compile every module with it; when it is not, this test is skipped and says so.
"""
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def promised_minimum():
    m = re.search(r'requires-python\s*=\s*"\s*>=\s*(\d+)\.(\d+)', (ROOT / "pyproject.toml").read_text())
    return (int(m.group(1)), int(m.group(2))) if m else (3, 11)


class OldestPython(unittest.TestCase):
    def test_the_readme_and_pyproject_promise_the_same_minimum(self):
        mi, ma = promised_minimum()
        self.assertIn(f"Python {mi}.{ma} or newer", (ROOT / "README.md").read_text())

    def test_every_module_compiles_under_the_oldest_promised_python(self):
        mi, ma = promised_minimum()
        exe = shutil.which(f"python{mi}.{ma}")
        if exe is None:
            self.skipTest(f"python{mi}.{ma} is not on PATH: install it to check the promised minimum (brew install python@{mi}.{ma})")
        r = subprocess.run([exe, "-m", "compileall", "-q", "-f", "-o", "0", "src"] if sys.version_info >= (3, 13) else [exe, "-m", "compileall", "-q", "-f", "src"],
                           cwd=ROOT, capture_output=True, text=True, timeout=120)
        if r.returncode != 0 and "unrecognized arguments" in r.stderr:
            r = subprocess.run([exe, "-m", "compileall", "-q", "-f", "src"], cwd=ROOT, capture_output=True, text=True, timeout=120)
        bad = [l for l in (r.stdout + r.stderr).splitlines() if l.startswith("***") or "SyntaxError" in l]
        self.assertEqual(r.returncode, 0, f"python{mi}.{ma} cannot compile the package:\n" + "\n".join(bad[:10]))
