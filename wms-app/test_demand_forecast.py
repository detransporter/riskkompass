"""
test_demand_forecast.py
Smoke test for the vendored forecasting engine (analysis/demand_forecast.py,
analysis/simulation.py) and the new analysis_bridge.build_demand_history()
bridge that feeds it from SQLite instead of Supabase's sku_demand_history.

Verifies the actual data-shape contract, not just that imports resolve:
build_demand_history() must produce exactly the (sku, period, qty) long
format classify_sbc()/select_forecast_method() require, with pre-launch
months absent (not zero) and in-window no-demand months present as zero --
see analysis_bridge.py's docstring for why that distinction matters.

Usage: python3 test_demand_forecast.py
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

import auth
import db
from analysis.demand_forecast import classify_sbc, forecast_dead_stock_risk, select_forecast_method
from analysis.simulation import simulate
from analysis_bridge import build_canonical, build_demand_history, run_analysis

TEST_COMPANY_NAME = "__test_demand_forecast_smoke__"
TODAY = datetime(2026, 9, 20)


def fail(msg):
    print(f"FAIL: {msg}")
    sys.exit(1)


def cleanup(slug):
    conn = db.get_directory_conn()
    conn.execute(
        "DELETE FROM users WHERE company_id IN (SELECT id FROM companies WHERE slug = ?)", (slug,)
    )
    conn.execute("DELETE FROM companies WHERE slug = ?", (slug,))
    conn.commit()
    conn.close()
    path = db.tenant_db_path(slug)
    if path.exists():
        path.unlink()
    for suffix in ("-wal", "-shm"):
        extra = Path(str(path) + suffix)
        if extra.exists():
            extra.unlink()


def _backdated_txn(conn, txn_type, sku, qty, days_ago, from_loc=None, to_loc=None):
    ts = (TODAY - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S")
    conn.execute(
        "INSERT INTO transactions "
        "(txn_type, sku, qty, from_location, to_location, reference, user_email, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (txn_type, sku, qty, from_loc, to_loc, "test-forecast", "test@forecastsmoke.local", ts),
    )
    if txn_type == "receive":
        conn.execute(
            "INSERT INTO stock (sku, location_code, qty) VALUES (?,?,?) "
            "ON CONFLICT(sku, location_code) DO UPDATE SET qty = qty + excluded.qty",
            (sku, to_loc, qty),
        )
    elif txn_type == "pick":
        conn.execute("UPDATE stock SET qty = qty - ? WHERE sku=? AND location_code=?", (qty, sku, from_loc))


def main():
    db.init_directory_db()
    user, err = auth.register_company(TEST_COMPANY_NAME, "test@forecastsmoke.local", "SakertLosen2026")
    if err:
        fail(f"register_company failed: {err}")
    slug = user.company_slug

    try:
        conn = db.get_tenant_conn(slug)

        conn.execute(
            "INSERT INTO items (sku, description, unit_cost, currency, supplier, lead_time_days, created_at) "
            "VALUES ('SKU-SMOOTH', 'Steady demand item', 100.0, 'SEK', 'Leverantör A', 10, ?)",
            (TODAY.strftime("%Y-%m-%dT%H:%M:%S"),),
        )
        conn.execute(
            "INSERT INTO items (sku, description, unit_cost, currency, supplier, lead_time_days, created_at) "
            "VALUES ('SKU-NEW', 'Just launched, short history', 50.0, 'SEK', 'Leverantör B', 5, ?)",
            (TODAY.strftime("%Y-%m-%dT%H:%M:%S"),),
        )
        conn.execute("INSERT INTO locations (code, zone, location_type) VALUES ('A-01', 'A', 'picking')")
        conn.commit()

        # SKU-SMOOTH: steady ~30 units/month picks over 10 months -- enough
        # history to clear MIN_PERIODS_FOR_ETS (7) but not
        # MIN_PERIODS_FOR_SEASONAL_ETS (24), so it should route through
        # classify_sbc -> "smooth" -> non-seasonal ETS.
        _backdated_txn(conn, "receive", "SKU-SMOOTH", 300, 305, to_loc="A-01")
        for months_ago in range(9, -1, -1):
            days_ago = months_ago * 30
            qty = 28 + (months_ago % 3) * 2  # small, deterministic variation: 28/30/32
            if days_ago == 0:
                continue  # today itself: leave some stock on hand
            _backdated_txn(conn, "pick", "SKU-SMOOTH", qty, days_ago, from_loc="A-01")

        # SKU-NEW: launched 20 days ago, one small pick -- too short for any
        # forecast (< MIN_PERIODS_FOR_FORECAST periods), should be absent
        # from the forecast output entirely, not given a fabricated one.
        _backdated_txn(conn, "receive", "SKU-NEW", 50, 20, to_loc="A-01")
        _backdated_txn(conn, "pick", "SKU-NEW", 5, 10, from_loc="A-01")
        conn.commit()

        # ── build_demand_history: the actual contract under test ──────────
        canonical_df, _note = build_canonical(conn)
        history = build_demand_history(canonical_df)

        if list(history.columns) != ["sku", "period", "qty"]:
            fail(f"build_demand_history: unexpected columns {list(history.columns)}")

        smooth_periods = history.loc[history["sku"] == "SKU-SMOOTH", "period"]
        if len(smooth_periods) < 7:
            fail(f"build_demand_history: expected >=7 periods for SKU-SMOOTH, got {len(smooth_periods)}")
        print(f"OK  build_demand_history: SKU-SMOOTH has {len(smooth_periods)} observed periods")

        # No period before the item's own first transaction (305 days ago,
        # i.e. ~10 months back) should appear -- a SKU never existed before
        # its own launch, so those months must be absent, not zero.
        earliest = pd.Timestamp(smooth_periods.min()) if len(smooth_periods) else None
        cutoff = pd.Timestamp(TODAY) - pd.Timedelta(days=305 + 31)
        if earliest is not None and earliest < cutoff:
            fail(f"build_demand_history: SKU-SMOOTH has a period ({earliest}) before its own launch")
        print(f"OK  build_demand_history: no pre-launch periods leaked in (earliest={earliest})")

        # ── classify_sbc: SKU-SMOOTH's steady monthly picks should read as smooth ──
        sbc = classify_sbc(history)
        smooth_class = sbc.loc[sbc["sku"] == "SKU-SMOOTH", "sbc_class"]
        if smooth_class.empty or smooth_class.iloc[0] != "smooth":
            fail(f"classify_sbc: expected SKU-SMOOTH to classify as 'smooth', got {smooth_class.tolist()}")
        print(f"OK  classify_sbc: SKU-SMOOTH classified as 'smooth' "
              f"(adi={sbc.loc[sbc['sku']=='SKU-SMOOTH','adi'].iloc[0]:.2f}, "
              f"cv2={sbc.loc[sbc['sku']=='SKU-SMOOTH','cv2'].iloc[0]:.3f})")

        # ── select_forecast_method: real forecast should come back for SKU-SMOOTH ──
        forecasts = select_forecast_method(history, sbc, horizon=3, level=80)
        smooth_fc = forecasts[forecasts["sku"] == "SKU-SMOOTH"]
        if smooth_fc.empty:
            fail("select_forecast_method: SKU-SMOOTH produced no forecast rows")
        if len(smooth_fc) != 3:
            fail(f"select_forecast_method: expected 3 horizon rows for SKU-SMOOTH, got {len(smooth_fc)}")
        if not smooth_fc["method"].isin(["ets", "ets_seasonal"]).all():
            fail(f"select_forecast_method: expected SKU-SMOOTH routed to ETS, got methods {smooth_fc['method'].tolist()}")
        avg_fc = smooth_fc["forecast"].mean()
        if not (15 <= avg_fc <= 45):
            fail(f"select_forecast_method: SKU-SMOOTH forecast {avg_fc:.1f}/month is implausible "
                 f"against observed ~28-32/month history")
        print(f"OK  select_forecast_method: SKU-SMOOTH -> method={smooth_fc['method'].iloc[0]}, "
              f"avg forecast={avg_fc:.1f}/month (observed history ~28-32/month)")

        if "SKU-NEW" in forecasts["sku"].values:
            fail("select_forecast_method: SKU-NEW has too little history and should not appear in output")
        print("OK  select_forecast_method: SKU-NEW (too short history) correctly absent, not fabricated")

        # ── forecast_dead_stock_risk: needs today's status from the full pipeline ──
        analyzed_df, _bridge = run_analysis(canonical_df)
        current = analyzed_df[["sku", "stock_qty", "status"]]
        risk = forecast_dead_stock_risk(forecasts, current)
        smooth_risk = risk.loc[risk["sku"] == "SKU-SMOOTH", "risk"]
        if smooth_risk.empty:
            fail("forecast_dead_stock_risk: SKU-SMOOTH missing from output")
        if smooth_risk.iloc[0] not in ("none", "emerging", "confirmed", "recovering"):
            fail(f"forecast_dead_stock_risk: unexpected risk value {smooth_risk.iloc[0]!r}")
        print(f"OK  forecast_dead_stock_risk: SKU-SMOOTH -> risk={smooth_risk.iloc[0]!r} "
              f"(current_status={risk.loc[risk['sku']=='SKU-SMOOTH','current_status'].iloc[0]!r})")

        # ── simulation.py: sanity check against the analyzed (post-run_analysis) df ──
        sim = simulate(analyzed_df, lt_reduction=0.20)
        if sim["baseline_required"] < 0 or sim["simulated_required"] < 0:
            fail(f"simulate: negative required capital, baseline={sim['baseline_required']}, "
                 f"simulated={sim['simulated_required']}")
        if sim["simulated_required"] > sim["baseline_required"] + 1.0:
            fail("simulate: shortening lead time by 20% should not INCREASE required capital "
                 f"(baseline={sim['baseline_required']:.0f}, simulated={sim['simulated_required']:.0f})")
        print(f"OK  simulate: 20% shorter lead time -> required capital "
              f"{sim['baseline_required']:.0f} -> {sim['simulated_required']:.0f} SEK "
              f"(delta={sim['delta']:.0f})")

        conn.close()
    finally:
        cleanup(slug)

    print("\nALL demand_forecast/simulation CHECKS PASSED")


if __name__ == "__main__":
    main()
