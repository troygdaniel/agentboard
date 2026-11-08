# overnight-sec-timing-tests-load: evidence

Card: `overnight-sec-timing-tests-load` (AGENT-8, night of 2026-11-07), filed from `overnight-sec-signoff-file-table` as the next
improvement in the area. Branch `overnight/overnight-sec-signoff-pack` (fourth commit). Nothing merged, nothing pushed, no spend, no live text.

## Why

`tests/test_redact_dos.py` and `tests/test_redact_fullwidth.py` assert that the masker handles a megabyte of hostile text in under 2 s
(3 s for fullwidth). Linear work takes about 0.05 s, the quadratic bug they guard against took minutes, so the margin is 40 to 1. Yet the
pair failed four times tonight on green code, each time two test suites shared this laptop at load 15 to 20 (2.06 s against 2.0). Every
"full suite exactly OK" line in the sign-off packs had to carry a footnote. A timing test that measures the scheduler instead of the code
is noise a reviewer learns to ignore, which is worse than no test.

## What changed

- `tests/timing.py` (new). Two ideas, both plain:
  1. the limit is scaled by the machine's state **at that moment**: a known-linear pass (300 `str.translate` calls over a megabyte,
     0.25 s on an idle laptop) is timed first, and the limit grows by the same factor the baseline grew, never shrinks;
  2. a run over the limit is tried again, up to three times, and the best time counts. Quadratic work fails every try; a scheduler hiccup
     does not survive three. The baseline is re-measured before each retry in case the machine got busier.
  A ceiling of 30 s stands whatever the baseline says (the quadratic case took 44 s for 400 KB), so a slow machine cannot hide minutes.
  `Mixin.assertFast(fn, seconds, *args)` is the one call the tests make; its failure message gives the best time, the limit and the factor.
- `tests/test_redact_dos.py`: every `assertLess(dt, LIMIT)` became `assertFast(...)`; the two server-side measurements taken in threads use
  `limit(LIMIT)` (scaled, not retried). The hostile inputs, the caps and the content checks are unchanged.
- `tests/test_redact_fullwidth.py::StillFast`: the same; its unused `time` import is gone.
- `CHANGELOG.md`: one line.

## Proof: two full suites at once, on purpose

Started within seconds of each other on the same laptop, with the other agents' work still running (load average 19 at the end):

```
PYTHONPATH=src python -m pytest -q                      1204 passed, 29 subtests passed in 217.28s
PYTHONPATH=src python -m unittest discover -s tests      Ran 1204 tests in 215.205s   OK
```

Both exactly green. The same pair of runs earlier tonight, before this change, failed the two wall-clock tests both times (see
`overnight-sec-signoff-file-table.md` and `overnight-sec-signoff-pack.md`). `python3 tests/publiccheck.py`: 0 findings.

## How to try it

```
cd <worktree>; PYTHONPATH=src python3 -m pytest -q tests/test_redact_dos.py tests/test_redact_fullwidth.py       # 28 passed
```
The helper's own behaviour, checked tonight with a throwaway TestCase: `assertFast(lambda: time.sleep(0.3), 0.05)` fails after three tries
with `best of 3 tries 0.31s, limit 0.05s (machine factor 1.0)`; `assertFast(lambda: None, 0.05)` passes. A quadratic masker would fail the
same way, with a time in the tens of seconds and the 30 s ceiling as the limit.

Measured while two full suites were running (load 10 to 15): the baseline came out at 0.23 s, factor 1.0. So on this laptop the retry is
what carries the tests through contention, and the factor is for a machine that is slow all the time (CI, an old box); both are kept.

## Risks

- A genuinely slow regression that is still linear (say 10x) now passes on a machine whose baseline is 10x slow too. That is the intended
  trade: the tests guard against the quadratic class, not against a constant; the 30 s ceiling and the `about 0.05 s per MB` comment stay.
- The reference (0.25 s) was measured on one M-series laptop at load 10 with best-of-two; on an idle machine the factor is 1.0 and nothing
  changes. On a much slower CI box the factor is above 1 and the limits stretch, which is the point.
- `assertFast` calls the function up to three times; every call site passed to it is idempotent (scrub, parse, an add on a throwaway store,
  the assertRaises lambdas).
