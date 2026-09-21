#!/bin/bash
# ARM smoke test for the forecasting module's dependency chain.
#
# Run ON the target server (Oracle Ampere A1 / aarch64), not locally --
# the whole point is to answer "do prebuilt wheels exist for this CPU
# architecture" for pandas/numpy/scipy, which cannot be verified from an
# x86_64/arm64-Mac dev machine. Uses its own throwaway venv; does not touch
# the app's real virtualenv or requirements files.
#
# Usage (on the server):
#   bash scripts/smoke_test_forecast_deps.sh
#
# Or copied over and run remotely in one shot from a dev machine:
#   scp -i <private_key> scripts/smoke_test_forecast_deps.sh ubuntu@<vm-ip>:~/
#   ssh -i <private_key> ubuntu@<vm-ip> "bash ~/smoke_test_forecast_deps.sh"
set -euo pipefail

VENV_DIR="/tmp/forecast_smoke_venv"
rm -rf "$VENV_DIR"

echo "== Platform =="
uname -a
python3 --version

echo
echo "== Creating throwaway venv =="
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
pip install --upgrade pip -q

echo
echo "== Installing pandas/numpy/scipy (Phase 1-3 requirement, per docs/FORECAST_SPEC.md) =="
time pip install "pandas>=2.0.0,<3.0.0" "numpy>=1.25.0,<2.2.0" "scipy<1.14.0" -q

echo
echo "== Import check =="
python3 -c "
import pandas, numpy, scipy
print('pandas', pandas.__version__)
print('numpy', numpy.__version__)
print('scipy', scipy.__version__)
"

echo
echo "== Training a small model (scipy.optimize, the actual numerical surface Phase 1-3 depends on) =="
python3 -c "
import time
import numpy as np
from scipy.optimize import minimize

rng = np.random.default_rng(42)
t = np.arange(60)
true_level, true_trend = 100.0, 2.0
y = true_level + true_trend * t + rng.normal(scale=5.0, size=t.size)

def sse(params):
    level, trend = params
    pred = level + trend * t
    return float(np.sum((y - pred) ** 2))

start = time.time()
result = minimize(sse, x0=[0.0, 0.0], method='Nelder-Mead')
elapsed = time.time() - start

print(f'fitted level={result.x[0]:.2f} (true {true_level}), trend={result.x[1]:.3f} (true {true_trend})')
print(f'converged: {result.success}, elapsed: {elapsed*1000:.1f} ms')
assert result.success, 'scipy.optimize.minimize did not converge -- something is wrong, not just slow'
assert abs(result.x[0] - true_level) < 10, 'fitted level too far from ground truth'
assert abs(result.x[1] - true_trend) < 1, 'fitted trend too far from ground truth'
print('OK: scipy numerical stack fits a real model correctly on this architecture')
"

echo
echo "== Bonus: statsforecast/numba/statsmodels chain (informs the earlier open question, not required for Phase 1-3) =="
if pip install "statsforecast>=2.0.0" "numba<0.61.0" "statsmodels<0.15.0" -q 2>/tmp/statsforecast_install.log; then
    python3 -c "
from statsforecast import StatsForecast
from statsforecast.models import AutoETS
print('statsforecast/numba/statsmodels: import OK')
"
    echo "RESULT: statsforecast chain installs and imports cleanly on this architecture"
else
    echo "RESULT: statsforecast chain FAILED to install -- see /tmp/statsforecast_install.log"
    echo "(Phase 1-3 is unaffected either way -- this only matters for the already-vendored"
    echo " analysis/demand_forecast.py, not for anything this smoke test is required to prove.)"
fi

deactivate
rm -rf "$VENV_DIR"
echo
echo "== Smoke test complete =="
