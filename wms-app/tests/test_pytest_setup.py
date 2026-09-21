"""Infra smoke test, not a Phase 1 deliverable: proves the pytest wiring
(conftest.py's sys.path fix, pytest.ini's testpaths scoping, requirements-
dev.txt's pytest pin) actually works end to end before any real
forecasting/ tests are written on top of it. Safe to delete once Phase 1
adds real tests that exercise the same import path.
"""

import numpy as np
import pandas as pd


def test_repo_root_imports_resolve():
    """Bare top-level imports (the existing app's own convention -- see
    db.py, analysis_bridge.py) must work from tests/ the same way they do
    from the repo root, via conftest.py's sys.path insertion."""
    import db  # noqa: F401
    import analysis_bridge  # noqa: F401


def test_pandas_numpy_available():
    s = pd.Series(np.arange(5))
    assert s.sum() == 10


def test_fixture_free_determinism_sanity():
    """Not a real leakage/determinism test (Phase 1 adds those against
    actual forecasting code) -- just confirms a seeded RNG behaves as the
    working agreement requires (same seed -> identical output), since that
    invariant is load-bearing for every phase after this one."""
    a = np.random.default_rng(42).normal(size=10)
    b = np.random.default_rng(42).normal(size=10)
    assert np.array_equal(a, b)
