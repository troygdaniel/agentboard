"""Small text on a coloured fill reads at 4.5:1 (sweep-ux, 15 Nov). White text on the Now count's orange: the badge beside "Now" (11px bold, white) and the avatar of a direct line to an agent (white initial) sat on #e8590c,
which is 3.58:1, under the 4.5:1 that small text needs (WCAG AA). They now sit on --need-fill, the same orange mixed 20% towards black (5.1:1); the decorative uses of --need
(the aura, the dial, the ring) keep the brighter orange.

The Configuration chip's count (green on the chip's grey, light theme) was 4.41:1 and now mixes 18% black into the green. The contrast is worked out here from the page's own CSS (the light theme's tokens), so a change of either colour that drops it under 4.5 fails by name."""
import re
import unittest
from pathlib import Path

from agentboard import nav

HTML = (Path(nav.__file__).parent / "static" / "index.html").read_text()


def srgb_to_linear(c):
    c /= 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb):
    r, g, b = (srgb_to_linear(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def hex_rgb(h):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def resolve(value):
    """A CSS colour from this page as (r, g, b): a hex, var(--x) of a :root hex, or color-mix(in srgb, <colour> N%, <colour>)."""
    value = value.strip().rstrip(";")
    m = re.fullmatch(r"var\(--([\w-]+)\)", value)
    if m:
        root = re.search(r"--" + re.escape(m.group(1)) + r":\s*([^;}]+)[;}]", HTML)   # the first definition is the light theme's
        return resolve(root.group(1))
    m = re.fullmatch(r"color-mix\(in srgb,\s*(.+?)\s+(\d+)%,\s*(.+?)\)", value)
    if m:
        a, pct, b = resolve(m.group(1)), int(m.group(2)) / 100, resolve(m.group(3))
        return tuple(round(a[i] * pct + b[i] * (1 - pct)) for i in range(3))
    if value.startswith("#"):
        return hex_rgb(value)
    raise AssertionError(f"cannot work out the colour {value!r}")


def declaration(selector, prop):
    rule = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", HTML)
    m = re.search(r"(?:^|;|\s)" + prop + r":\s*([^;}]+)", rule.group(1))
    return m.group(1)


class NeedBadgeContrastTests(unittest.TestCase):
    def test_the_count_beside_now_reads_at_4_5_to_1(self):
        bg = resolve(declaration("#tab-need #need-n", "background"))
        self.assertGreaterEqual(contrast(resolve(declaration("#tab-need #need-n", "color")), bg), 4.5, f"white on rgb{bg}")

    def test_the_initial_on_a_direct_line_to_an_agent_reads_at_4_5_to_1(self):
        bg = resolve(declaration("#orch-line.direct .orch-face", "background"))
        self.assertGreaterEqual(contrast(resolve(declaration("#orch-line.direct .orch-face", "color")), bg), 4.5, f"white on rgb{bg}")

    def test_the_configuration_chips_count_reads_at_4_5_to_1_on_the_chip(self):
        fg = resolve(declaration(".ab-cfg em", "color"))
        self.assertGreaterEqual(contrast(fg, resolve("var(--chip)")), 4.5, f"rgb{fg} on the chip")

    def test_the_bright_orange_is_still_the_decorative_one(self):
        self.assertIn(":root{--need:#e8590c}", HTML)
        self.assertIn("#aura i:nth-child(1) { --c: var(--need);", HTML)


if __name__ == "__main__":
    unittest.main()
