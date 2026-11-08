#!/bin/bash
# usage: bash tests/qa/suite_matrix.sh <out dir>
# Sequential suite matrix (one run at a time, so timing tests are not fighting each other): full suite per Python, then shuffled runs.
cd "$(dirname "$0")/../.." || exit 1
OUT="$1"; mkdir -p "$OUT"
for py in python3.12 python3.13; do
  echo "=== $py full suite (normal order) ==="
  env -i HOME=$HOME PATH=$PATH PYTHONPATH=src $py -W ignore -m unittest discover -s tests 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^FAILED|^OK' | tee "$OUT/full-$py.txt"
done
echo "=== python3.11 the five that failed earlier, alone ==="
env -i HOME=$HOME PATH=$PATH PYTHONPATH=src python3.11 -W ignore -m unittest tests.test_redact_dos tests.test_redact_fullwidth tests.test_redact_invisible 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^FAILED|^OK|AssertionError' | tee "$OUT/py311-redact-alone.txt"
for py in python3.14 python3.14 python3.14 python3.13 python3.12 python3.11; do
  echo "=== $py shuffled ==="
  env -i HOME=$HOME PATH=$PATH $py -W ignore tests/qa_random_order.py 2>&1 | tee -a "$OUT/shuffled.txt"
done
echo MATRIX DONE
