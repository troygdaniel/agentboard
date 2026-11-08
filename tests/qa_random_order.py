"""Run the whole suite in a random order (overnight-qa-cleanroom): an order-dependent test passes only after the one that set it up.

    python3 tests/qa_random_order.py              # one shuffled run, prints the seed and the failures
    python3 tests/qa_random_order.py --seed 7     # the same order again
    python3 tests/qa_random_order.py --runs 3     # three different seeds

Exit 1 when any run fails. Tests run from the repo root with src/ on the path, the way `python -m unittest discover -s tests` does."""
import os
import random
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))


def flatten(suite):
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            yield from flatten(t)
        else:
            yield t


def main(argv):
    seed = None
    runs = 1
    if "--seed" in argv:
        seed = int(argv[argv.index("--seed") + 1])
    if "--runs" in argv:
        runs = int(argv[argv.index("--runs") + 1])
    bad = 0
    for i in range(runs):
        s = seed if seed is not None else random.SystemRandom().randrange(1_000_000)
        tests = list(flatten(unittest.defaultTestLoader.discover(str(HERE))))
        random.Random(s).shuffle(tests)
        started = time.time()
        res = unittest.TextTestRunner(stream=open(os.devnull, "w"), verbosity=0).run(unittest.TestSuite(tests))
        fails = [t.id() for t, _ in res.failures + res.errors] + [t.id() + " (unexpected success)" for t in res.unexpectedSuccesses]
        print(f"seed {s}: {res.testsRun} tests, {len(fails)} failing, {len(res.skipped)} skipped, {time.time() - started:.0f} s")
        for f in fails:
            print("  -", f)
        bad += len(fails)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
