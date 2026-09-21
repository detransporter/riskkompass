"""Shared pytest config for the tests/ suite.

Deliberately minimal for now -- forecasting-specific fixtures (a small,
fixed-seed synthetic dataset generated fresh per test run, per the working
agreement: tests must not depend on data/demo/) land alongside the
forecasting/ code that needs them. This file exists so pytest has a
rootdir-anchored conftest before that lands, and so sys.path resolution is
proven working now rather than discovered as a surprise later.
"""

from __future__ import annotations

import sys
from pathlib import Path

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
