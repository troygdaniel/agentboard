# By agent: a cue for the lanes past the edge

Card `ux-by-agent-hides-lanes-past-the-fifth-w`. With six or more agents the By agent lanes scroll sideways; at 1333px wide four lanes were fully
in view, the fifth cut off, and the rest (here AGENT-7, waiting on the owner) past the edge with nothing to say so: no scrollbar on an
overlay-scrollbar system, no fade, no count.

The fix draws a fade on each edge that has more lanes and a chip that counts them: `+4 more · 1 needs you ›` on the right, `‹ 2 more` on the left. The
right chip jumps to the first lane that needs the owner, else the next lane; the left chip to the nearest lane before. It is a real button, so a
keyboard reaches it, and under reduced motion it jumps without the glide. Nothing shows when every lane fits, under Load, or off the By agent view.

Throwaway board, 8 made-up agents (AGENT-7 asking a question), measured in a real browser:

| Width | Lanes fully in view | Before | After |
|---|---|---|---|
| 1333px | 4 of 8 | no sign of the other four | `+4 more · 1 needs you ›`; one click brings AGENT-7 into view, then `‹ 2 more` and `+1 more ›` |
| 1920px | 6 of 8 | no sign | `+2 more · 1 needs you ›` |
| 390px | the next lane peeks | no count | `+8 more · 1 needs you ›`; one tap lands on AGENT-7 |

Screenshots: `before-w1333-light.png` and `after-w1333-light.png` (the cue), `after-w1333-dark-hopped.png` (after one jump: both chips, the asking lane
in view), `after-w390-dark.png` and `after-w390-light-hopped.png` (phone). The counting logic is a pure function (`laneCueState`) tested in Node when
it is installed (`tests/test_lane_cue.py`); the markup, rules and wiring are checked as text.
