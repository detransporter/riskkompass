#!/bin/bash
# Runs the whole test suite with one command: the existing standalone
# test_*.py scripts at the repo root (own tenant, own cleanup, no pytest),
# and the pytest suite under tests/ (forecasting/'s fixtures and
# parametrized tests -- see docs/FORECAST_SPEC.md). Exits non-zero on the
# first failure in either suite.
set -e
cd "$(dirname "$0")"

echo "== standalone test_*.py scripts =="
for f in test_*.py; do
    echo "--- $f ---"
    python3 "$f"
done

echo
echo "== pytest (tests/) =="
python3 -m pytest tests/ -v

echo
echo "ALL TESTS PASSED (standalone + pytest)"
