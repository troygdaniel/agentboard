"""Wall-clock assertions that survive a loaded laptop.

The masker's speed tests say "a megabyte in under 2 s" because the quadratic bug took minutes and linear work takes about 0.05 s. The
margin is 40 to 1, yet the tests failed four times on the night of 2026-11-07 on green code, every time two test suites shared a machine at
load 15 to 20: a two-second measurement is sliced by the scheduler, a two-millisecond one is not. So a timing assertion here does two
things an `assertLess(dt, 2.0)` does not:

* it scales the limit by the machine's state at that moment: a known-linear pass (300 `str.translate` calls over a megabyte, about
  0.25 s on an idle laptop) is timed first, and the limit grows by the same factor the baseline grew (never shrinks);
* it retries: a run over the limit is measured again, up to three times, and the best time counts. Quadratic work fails every try; a
  scheduler hiccup does not survive three.

A loose absolute ceiling (`CEILING_S`) still stands whatever the baseline says, so a machine that is merely slow cannot hide minutes."""
import time

REFERENCE_S = 0.25        # the baseline pass on an idle laptop (measured 0.23 s at load 10 on 2026-11-07, M-series)
CEILING_S = 30.0          # no limit is ever stretched past this: the quadratic case took 44 s for 400 KB
TRIES = 3
_TEXT = "ab" * 500_000
_TABLE = str.maketrans("a", "b")
_factor = None


def baseline():
    """Seconds for the known-linear pass, best of two."""
    best = float("inf")
    for _ in range(2):
        t = time.perf_counter()
        for _ in range(300):
            _TEXT.translate(_TABLE)
        best = min(best, time.perf_counter() - t)
    return best


def factor(fresh=False):
    """How much slower this machine is right now than the idle reference, at least 1. Measured once per process unless `fresh`."""
    global _factor
    if _factor is None or fresh:
        _factor = max(1.0, baseline() / REFERENCE_S)
    return _factor


def limit(seconds, fresh=False):
    """`seconds` stretched by the machine's factor, capped at CEILING_S."""
    return min(CEILING_S, seconds * factor(fresh))


def timed(fn, *a, **k):
    t = time.perf_counter()
    out = fn(*a, **k)
    return time.perf_counter() - t, out


def fast(fn, seconds, *a, **k):
    """Run `fn(*a, **k)`; return (best seconds over up to TRIES tries, the first result, the limit used). The caller asserts dt < limit.
    A try under the limit ends the loop, so a fast machine pays once."""
    lim = limit(seconds)
    best, out = float("inf"), None
    for i in range(TRIES):
        dt, res = timed(fn, *a, **k)
        if i == 0:
            out = res
        best = min(best, dt)
        if best < lim:
            break
        lim = limit(seconds, fresh=True)   # the machine may have got busier: re-measure before the next try
    return best, out, lim


class Mixin:
    """`self.assertFast(fn, seconds, *args)` for a unittest.TestCase: fails with the best time, the limit and the factor."""

    def assertFast(self, fn, seconds, *a, msg=None, **k):
        dt, out, lim = fast(fn, seconds, *a, **k)
        self.assertLess(dt, lim, f"{msg or getattr(fn, '__name__', 'it')}: best of {TRIES} tries {dt:.2f}s, limit {lim:.2f}s "
                                 f"(machine factor {factor():.1f})")
        return out
