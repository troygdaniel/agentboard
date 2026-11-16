"""The page at rest must not keep the browser redrawing for an animation nobody can see.

Found by measuring Now, Watch and Map on a 3,200-card board in headless Chrome: with nothing changing, the page still restyled 60 times a
second and kept the renderer busy. The cause was the lane glow, `.ln:not(.idle)...::before { animation: hlit }`. Nothing builds a lane box
with that class any more; the only element left that carries `ln` is the strip's SVG sparkline (`<polyline class="ln">`). A pseudo-element
is never drawn on an SVG shape, but the animation still runs, so the browser restyled the page on every frame to move an opacity nobody
could see. Switching it off took the page from 60 restyles a second to 1.

The check is on the CSS text, not on a browser: an animated ::before or ::after must not be aimed at a bare class that the page's own
script gives to an SVG shape."""
import re
import unittest
from pathlib import Path

from agentboard import cli

PAGE = (Path(cli.__file__).parent / "static" / "index.html").read_text()
STYLE = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", PAGE, re.S))
CSS = re.sub(r"/\*.*?\*/", "", STYLE, flags=re.S)
SVG_SHAPES = "polyline|polygon|path|circle|ellipse|rect|line|g|text"


def svg_classes():
    """Every class the page's script gives to an SVG shape it draws."""
    found = set()
    for m in re.finditer(r"<(?:%s)\b[^>]*?\bclass=\"([\w -]+)\"" % SVG_SHAPES, PAGE):
        found.update(m.group(1).split())
    return found


def rules():
    """(selector, body) for every plain CSS rule, at any depth of @media; the @keyframes blocks are skipped."""
    out = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", CSS):
        sel = m.group(1).strip()
        if sel.startswith("@") or re.fullmatch(r"[\d.]+%|from|to|[\d.]+%\s*,\s*[\d.]+%", sel):
            continue
        out.append((sel, m.group(2)))
    return out


def keyframe_props(name):
    """The CSS properties a @keyframes block animates (its braces nest, so the block is found by counting them)."""
    m = re.search(r"@keyframes\s+%s\s*\{" % re.escape(name), CSS)
    if not m:
        return None
    depth, i = 1, m.end()
    while depth and i < len(CSS):
        depth += {"{": 1, "}": -1}.get(CSS[i], 0)
        i += 1
    block = CSS[m.end():i - 1]
    return set(re.findall(r"([\w-]+)\s*:", block))


class IdleAnimations(unittest.TestCase):
    def test_the_page_draws_its_sparkline_in_svg(self):
        self.assertIn("ln", svg_classes(), "the strip's sparkline moved: this test's premise needs a new look")

    def test_no_animated_pseudo_element_is_aimed_at_an_svg_shape(self):
        shapes = svg_classes()
        bad = []
        for sel, body in rules():
            if not re.search(r"\banimation(-name)?\s*:", body) or re.search(r"\banimation(-name)?\s*:\s*none\b", body):
                continue
            for one in (s.strip() for s in sel.split(",")):
                m = re.search(r"([^\s>+~]+)::(?:before|after)$", one)   # the last compound selector, with its pseudo-element
                if not m:
                    continue
                compound = m.group(1)
                if re.match(r"[a-z]", compound):   # a tag name (div.ln) cannot be an SVG shape unless it is one of them
                    if not re.match(r"(?:%s)\b" % SVG_SHAPES, compound):
                        continue
                first = re.match(r"(?:[a-z]+)?\.([\w-]+)", compound)
                if first and first.group(1) in shapes:
                    bad.append(one)
        self.assertEqual(bad, [], "an animated ::before/::after on a class the page gives to an SVG shape: it is never drawn, yet it "
                                  "makes the browser restyle the whole page every frame")

    def test_the_ribbons_now_dot_pulses_without_repainting(self):
        """The dot at the right end of the 8-hour ribbon pulses forever, on every view. It used to animate box-shadow, which the browser can only
        do by repainting on its main thread every frame (60 restyles a second at rest). A ring that scales and fades runs on the compositor."""
        names = []
        for sel, body in rules():
            if re.match(r"#ribbon b(::before)?$", sel):
                m = re.search(r"\banimation\s*:\s*([\w-]+)\s", body)
                if m and m.group(1) != "none":
                    names.append(m.group(1))
        self.assertTrue(names, "no pulse on the ribbon's now dot: the page changed, so this check needs a new look")
        for name in names:
            props = keyframe_props(name)
            self.assertIsNotNone(props, f"@keyframes {name} is missing")
            self.assertLessEqual(props, {"transform", "opacity"}, f"@keyframes {name} animates {sorted(props)}: repaints every frame")

    def test_the_ribbons_ring_stands_still_when_motion_is_reduced(self):
        """Reduced motion shows the ring at rest (the same 4 px halo the dot always had) and stops the pulse."""
        hit = re.search(r"@media \(prefers-reduced-motion: reduce\)\s*\{[^\n]*#ribbon b::before[^{\n]*\{[^}]*animation:\s*none", PAGE)
        self.assertTrue(hit, "the reduced-motion rule does not stop the ribbon ring's animation")

    def test_the_lane_glow_still_exists_for_a_lane_box(self):
        """The fix scopes the rule to a box (div.ln); it does not delete the glow for a lane that a later page draws."""
        self.assertTrue(re.search(r"div\.ln:not\(\.idle\)", CSS), "the lane glow for a div.ln lane is gone")


if __name__ == "__main__":
    unittest.main()
