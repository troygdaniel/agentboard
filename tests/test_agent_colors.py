"""One colour per agent name, never per card: the palette slots the board page and `agentboard spawn` agree on."""
import re
import tempfile
import unittest
from pathlib import Path

from agentboard import cli
from agentboard.store import Store

PAGE = (Path(cli.__file__).parent / "static" / "index.html").read_text()


class SlotTests(unittest.TestCase):
    def test_the_named_agents_each_get_their_own_slot(self):
        self.assertEqual([cli.agent_slot(f"AGENT-{n}") for n in (1, 2, 3, 4)], [1, 2, 3, 4])
        self.assertEqual((cli.agent_slot("GENERAL"), cli.agent_slot("ORCH")), (5, 6))

    def test_other_names_get_a_stable_slot_inside_the_palette(self):
        for name in ("AGENT-5", "AGENT-0", "AGENT-12", "atlas", "Acme-ORCH"):
            slot = cli.agent_slot(name)
            self.assertIn(slot, range(1, len(cli.AGENT_PALETTE) + 1), name)
            self.assertEqual(slot, cli.agent_slot(name))

    def test_the_palette_keeps_clear_of_the_status_hues(self):
        # orange running, green review, red ask: no agent hue may sit in those bands, or a quiet card reads as needing attention
        import colorsys
        for hex_ in cli.AGENT_PALETTE:
            r, g, b = (int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5))
            hue = colorsys.rgb_to_hsv(r, g, b)[0] * 360
            self.assertFalse(hue < 55 or hue > 345 or 90 < hue < 170, f"{hex_} is at {hue:.0f} degrees")


class PageMatchesTests(unittest.TestCase):
    """The board page and the CLI each hold the palette; this keeps the two copies from drifting apart."""
    def test_the_page_palette_is_the_cli_palette(self):
        m = re.search(r"--a1: (#\w{6}); --a2: (#\w{6}); --a3: (#\w{6}); --a4: (#\w{6}); --a5: (#\w{6}); --a6: (#\w{6});", PAGE)
        self.assertEqual(list(m.groups()), cli.AGENT_PALETTE)

    def test_the_page_fixed_slots_are_the_cli_fixed_slots(self):
        m = re.search(r"const AGENT_SLOT = \{ GENERAL: (\d), ORCH: (\d) \};", PAGE)
        self.assertEqual((int(m.group(1)), int(m.group(2))), (cli.AGENT_SLOTS["GENERAL"], cli.AGENT_SLOTS["ORCH"]))

    def test_the_page_never_reads_a_card_colour(self):
        self.assertIn("const colorOf = t => agentColor(t.agent);", PAGE)


class NoCardColourTests(unittest.TestCase):
    def test_a_colour_passed_to_start_claim_and_chat_is_never_stored(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d) / ".agentboard")
            card = s.start("Parent", "AGENT-1", "green")
            child = s.add("Child", parent_id=card["id"])   # a subtask of a coloured parent used to copy the colour
            queued = s.add("Queued", status="todo")
            claimed = s.claim(queued["id"], "AGENT-2", "red")
            msg = s.chat_send("AGENT-2", "on it", color="blue")
            for name, thing in (("started card", card), ("subtask", child), ("claimed card", claimed), ("chat message", msg)):
                self.assertNotIn("color", thing, name)


if __name__ == "__main__":
    unittest.main()
