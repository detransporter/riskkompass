"""Shared pytest fixtures for the forecasting/ test suite.

Deliberately minimal for now -- Phase 1 (docs/FORECAST_SPEC.md) adds the
fixtures that actually matter (a small, fixed-seed synthetic dataset
generated fresh per test run, per the working agreement: tests must not
depend on data/demo/). This file exists so pytest has a rootdir-anchored
conftest before that lands, and so sys.path resolution is proven working
now rather than discovered as a surprise mid-Phase-1.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# tests/ sits directly under the repo root, same level as db.py, app.py,
# analysis_bridge.py -- those are imported as bare top-level modules
# throughout the existing test_*.py scripts (run via `python3 test_x.py`
# from the repo root, which puts the root on sys.path automatically).
# pytest's own rootdir insertion does not guarantee that when tests/ has
# its own conftest.py, so it is made explicit here instead of relying on
# it working by accident.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fixtures import make_small_dataset  # noqa: E402


@pytest.fixture
def small_dataset() -> dict:
    """50 items / 6 months, fixed seed -- generated fresh every call, per
    the working agreement (tests must not depend on data/demo/). See
    tests/fixtures.py for exactly what patterns it deliberately contains
    (steady/intermittent/outlier/level-shift/censored/late-launch items)."""
    return make_small_dataset()
