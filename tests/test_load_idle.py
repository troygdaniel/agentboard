"""Load shows every agent, idle ones too, as cards in the Agents column (Nov 4): the idle fold, its toggle and its remembered
collapse are gone; an idle agent's card is the quiet one (its hour bar dimmed), still there."""
import unittest
from pathlib import Path

from agentboard import cli

PAGE = (Path(cli.__file__).parent / "static" / "index.html").read_text()


class LoadIdleTests(unittest.TestCase):
    def test_there_is_no_idle_fold_any_more(self):
        for gone in ("idleOpen", "h-fold", "agentboard-idle", "h-idle", "h-fchip", "h-fold-card"):
            self.assertNotIn(gone, PAGE, gone)
        self.assertIn("const agents = teleOrder(d.agents);", PAGE)                       # every agent, in the telemetry order
        self.assertIn("const key = agents.map(a => a.name).join('|');", PAGE)            # the list is rebuilt only when the agents change

    def test_an_idle_agent_is_a_quiet_card(self):
        self.assertIn("r.dataset.status = a.state === 'idle' ? 'done' : 'doing';", PAGE)
        self.assertIn(".h-row.idle .ln-track { opacity: .55; }", PAGE)
        self.assertIn("const CARD_STATE = { waiting: 'ask', review: 'review', abandoned: 'abandoned', quiet: 'abandoned', working: 'livebar', idle: '' };", PAGE)


if __name__ == "__main__":
    unittest.main()
