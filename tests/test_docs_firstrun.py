"""What a new user is told to expect on the first run must match what the program does (card sweep-newuser, 15 Nov).

On a work laptop `agentboard doctor` prints two WARN lines that are normal there (the Stop hook is not installed; the list of modules that
could make a connection, each off under the lock), and WORK-SETUP.md says so. The README's work-laptop checklist promised "0 WARN with the
lock set", so a reviewer following it would read a correct setup as a wrong one. The README's checklist and WORK-SETUP.md must agree."""
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]


def section(text, heading):
    i = text.index(f"\n## {heading}")
    j = text.find("\n## ", i + 1)
    return text[i:j if j > 0 else None]


class TheDoctorExpectationOnAWorkLaptop(unittest.TestCase):
    def test_the_readme_checklist_does_not_promise_zero_warnings(self):
        sec = section((ROOT / "README.md").read_text(), "On a work laptop")
        self.assertIn("agentboard doctor", sec)
        self.assertNotIn("0 WARN", sec)
        self.assertIn("WORK-SETUP.md", sec, "the checklist should point at the page that names the WARN lines that are normal")

    def test_work_setup_names_the_normal_warnings_and_what_needs_fixing(self):
        text = (ROOT / "WORK-SETUP.md").read_text()
        self.assertIn("Stop hook", text)
        self.assertIn("Only a FAIL needs fixing", text)
        self.assertNotIn("0 WARN", text)


if __name__ == "__main__":
    unittest.main()
