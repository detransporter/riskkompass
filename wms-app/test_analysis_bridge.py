"""
test_analysis_bridge.py
Regression test for analysis_bridge.py: builds a hand-designed, multi-month
transaction history with known DOS/status/ABC/bridge outcomes and checks
the real pipeline (build_canonical -> run_analysis) against them exactly.

This is the test that protects the vendored IHA analysis modules (copied
from iha-saas) against a mismatch between what they expect and what
analysis_bridge.build_canonical() actually feeds them from SQLite -- see
CLAUDE.md "IHA integration". The expected numbers below were hand-verified
against this exact transaction data during milestone 3 (2026-09-16): DOS,
status, ABC tier and every bridge total matched a manual calculation to the
SEK. If this test starts failing after changing analysis_bridge.py or any
vendored analysis/*.py file, recompute by hand before "fixing" the numbers
to make it pass -- the numbers ARE the spec here.

Usage: python3 test_analysis_bridge.py
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import auth
import db
from analysis.health_scorer import summary_stats
from analysis.lead_time import lead_time_reconciliation, supplier_flags, supplier_scorecard
from analysis_bridge import build_canonical, run_analysis
from components.sv import supplier_flags_sv, translate_demand_note

TEST_COMPANY_NAME = "__test_analysis_bridge_smoke__"
TODAY = datetime(2026, 9, 16)


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
        (txn_type, sku, qty, from_loc, to_loc, "test-demand", "test@bridgesmoke.local", ts),
    )
    if txn_type == "receive":
        conn.execute(
            "INSERT INTO stock (sku, location_code, qty) VALUES (?,?,?) "
            "ON CONFLICT(sku, location_code) DO UPDATE SET qty = qty + excluded.qty",
            (sku, to_loc, qty),
        )
    elif txn_type == "pick":
        conn.execute("UPDATE stock SET qty = qty - ? WHERE sku=? AND location_code=?", (qty, sku, from_loc))


def _current_stock(conn, sku, loc):
    row = conn.execute("SELECT qty FROM stock WHERE sku=? AND location_code=?", (sku, loc)).fetchone()
    return row["qty"] if row else 0.0


def _check_close(label, got, want, tol=1.0):
    if abs(got - want) > tol:
        fail(f"{label}: expected ~{want}, got {got}")
    print(f"OK  {label} = {got} (expected ~{want})")


def main():
    db.init_directory_db()
    user, err = auth.register_company(TEST_COMPANY_NAME, "test@bridgesmoke.local", "SakertLosen2026")
    if err:
        fail(f"register_company failed: {err}")
    slug = user.company_slug

    try:
        conn = db.get_tenant_conn(slug)
        conn.execute("INSERT INTO locations (code, zone, location_type) VALUES ('A-01', 'A', 'picking')")

        # SKU-A1 + SKU-A2 are both sourced from "Leverantör A" -- together they
        # carry ~90% of total inventory value, which should trip the
        # supplier_flags() concentration-risk threshold (>40%).
        items = [
            ("SKU-A1", "Toppmotor 5000", 1000.0, 14, "Leverantör A"),
            ("SKU-A2", "Kraftpaket 3000", 800.0, 21, "Leverantör A"),
            ("SKU-B1", "Standardventil", 200.0, 10, "Leverantör B"),
            ("SKU-C1", "Klämma liten", 50.0, 7, "Leverantör B"),
            ("SKU-DEAD", "Utgått fäste", 300.0, 30, "Leverantör B"),
            ("SKU-STOCKOUT", "Hetsåld packning", 150.0, 5, "Leverantör B"),
        ]
        for sku, desc, cost, lt, supplier in items:
            conn.execute(
                "INSERT INTO items (sku, description, unit_cost, currency, lead_time_days, supplier, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (sku, desc, cost, "SEK", lt, supplier, db.now_iso()),
            )
        conn.commit()

        _backdated_txn(conn, "receive", "SKU-A1", 1950, 200, to_loc="A-01")
        _backdated_txn(conn, "receive", "SKU-A2", 1150, 200, to_loc="A-01")
        _backdated_txn(conn, "receive", "SKU-B1", 800, 200, to_loc="A-01")
        _backdated_txn(conn, "receive", "SKU-C1", 190, 200, to_loc="A-01")
        _backdated_txn(conn, "receive", "SKU-DEAD", 100, 300, to_loc="A-01")
        _backdated_txn(conn, "receive", "SKU-STOCKOUT", 550, 200, to_loc="A-01")

        # Steady daily picks for 150 days at different rates -- gives each
        # SKU a real, measurable demand pattern (>=3 complete months).
        rates = {"SKU-A1": 10, "SKU-A2": 6, "SKU-B1": 4, "SKU-C1": 1}
        for days_ago in range(150, 0, -1):
            for sku, base_rate in rates.items():
                qty = base_rate + (days_ago % 3) - 1
                if qty > 0:
                    _backdated_txn(conn, "pick", sku, float(qty), days_ago, from_loc="A-01")

        # SKU-STOCKOUT: sold steadily until 10 days ago, then ran out exactly.
        for days_ago in range(150, 10, -1):
            qty = 3 + (days_ago % 2)
            _backdated_txn(conn, "pick", "SKU-STOCKOUT", float(qty), days_ago, from_loc="A-01")
        remaining = _current_stock(conn, "SKU-STOCKOUT", "A-01")
        if remaining > 0:
            _backdated_txn(conn, "pick", "SKU-STOCKOUT", remaining, 10, from_loc="A-01")

        conn.commit()

        # Sanity-check the fixture itself before trusting the pipeline output
        # -- if these fail, the bug is in this test's setup, not the pipeline.
        _check_close("fixture: SKU-A1 remaining stock", _current_stock(conn, "SKU-A1", "A-01"), 450)
        _check_close("fixture: SKU-A2 remaining stock", _current_stock(conn, "SKU-A2", "A-01"), 250)
        _check_close("fixture: SKU-B1 remaining stock", _current_stock(conn, "SKU-B1", "A-01"), 200)
        _check_close("fixture: SKU-C1 remaining stock", _current_stock(conn, "SKU-C1", "A-01"), 40)
        _check_close("fixture: SKU-STOCKOUT remaining stock", _current_stock(conn, "SKU-STOCKOUT", "A-01"), 0)
        _check_close("fixture: SKU-DEAD remaining stock", _current_stock(conn, "SKU-DEAD", "A-01"), 100)

        # ── Run the real pipeline ──────────────────────────────────────────
        canon, note = build_canonical(conn)
        if canon.empty:
            fail("build_canonical returned an empty frame")
        print(f"build_canonical note: {note}")
        result, bridge = run_analysis(canon)
        by_sku = result.set_index("sku")

        # ── components/sv.py: the Swedish UI must never leak the vendored
        # module's raw English note text ──────────────────────────────────
        note_sv = translate_demand_note(note)
        if note_sv == note:
            fail(f"translate_demand_note did not translate a real build_canonical() note "
                 f"(regex pattern is out of sync with data_merge.py's wording): {note!r}")
        if "Observed window" in note_sv or "complete months" in note_sv:
            fail(f"translate_demand_note left English text in the translated note: {note_sv!r}")
        print(f"OK  translate_demand_note: {note_sv!r}")

        expected_status = {
            "SKU-A1": "healthy", "SKU-A2": "healthy", "SKU-B1": "healthy",
            "SKU-C1": "healthy", "SKU-DEAD": "dead_stock", "SKU-STOCKOUT": "stockout_risk",
        }
        for sku, want in expected_status.items():
            got = by_sku.loc[sku, "status"]
            if got != want:
                fail(f"status[{sku}]: expected {want!r}, got {got!r}")
            print(f"OK  status[{sku}] = {got}")

        expected_abc = {"SKU-A1": "A", "SKU-A2": "B"}
        for sku, want in expected_abc.items():
            got = by_sku.loc[sku, "abc_class"]
            if got != want:
                fail(f"abc_class[{sku}]: expected {want!r}, got {got!r}")
            print(f"OK  abc_class[{sku}] = {got}")

        expected_value_sek = {
            "SKU-A1": 450000.0, "SKU-A2": 200000.0, "SKU-B1": 40000.0,
            "SKU-C1": 2000.0, "SKU-DEAD": 30000.0, "SKU-STOCKOUT": 0.0,
        }
        for sku, want in expected_value_sek.items():
            got = by_sku.loc[sku, "value_sek"]
            if abs(got - want) > 1:
                fail(f"value_sek[{sku}]: expected {want}, got {got}")
            print(f"OK  value_sek[{sku}] = {got}")

        _check_close("bridge total_value", bridge["total_value"], 722000)
        _check_close("bridge dead", bridge["dead"], 30000)
        _check_close("bridge excess", bridge["excess"], 0)
        _check_close("bridge deficit", bridge["deficit"], 879550, tol=5)
        _check_close("bridge justified_cycle", bridge["justified_cycle"], 692000)
        _check_close("bridge cash_from_dead", bridge["cash_from_dead"], 7500)
        _check_close("bridge annual_holding_saving", bridge["annual_holding_saving"], 6600)

        # ── health_scorer.py ────────────────────────────────────────────
        stats = summary_stats(result)
        if stats["total_skus"] != 6:
            fail(f"summary_stats total_skus: expected 6, got {stats['total_skus']}")
        if not (0 < stats["health_score"] < 100):
            fail(f"health_score should be strictly between 0 and 100 for a mixed estate, got {stats['health_score']}")
        print(f"OK  summary_stats: health_score={stats['health_score']}, total_skus={stats['total_skus']}")

        # ── lead_time.py: supplier_scorecard + supplier_flags ───────────
        scorecard = supplier_scorecard(result)
        if set(scorecard["supplier"]) != {"Leverantör A", "Leverantör B"}:
            fail(f"supplier_scorecard: expected suppliers A and B, got {set(scorecard['supplier'])}")
        a_row = scorecard[scorecard["supplier"] == "Leverantör A"].iloc[0]
        _check_close("supplier A value_sek (SKU-A1 + SKU-A2)", a_row["value_sek"], 650000)
        if a_row["value_share"] <= 0.40:
            fail(f"Leverantör A should hold >40% of value (concentration risk), got {a_row['value_share']:.2%}")
        print(f"OK  supplier_scorecard: Leverantör A holds {a_row['value_share']:.0%} of inventory value")

        flags = supplier_flags(scorecard)
        if not any("Concentration risk" in f and "Leverantör A" in f for f in flags):
            fail(f"supplier_flags should raise a concentration-risk flag for Leverantör A, got: {flags}")
        print("OK  supplier_flags raises concentration risk for Leverantör A")

        # components/sv.py:supplier_flags_sv() -- the Swedish UI-facing version.
        # Same trigger condition, translated text, used by views/iha_report.py.
        flags_sv = supplier_flags_sv(scorecard)
        if not any("Koncentrationsrisk" in f and "Leverantör A" in f for f in flags_sv):
            fail(f"supplier_flags_sv should raise a Swedish concentration-risk flag, got: {flags_sv}")
        if any("Concentration risk" in f for f in flags_sv):
            fail(f"supplier_flags_sv leaked the English vendored wording: {flags_sv}")
        print("OK  supplier_flags_sv raises the same flag in Swedish")

        # ── lead_time.py: reconciliation (honest zero, no order-date data yet) ──
        recon = lead_time_reconciliation(result)
        if recon.get("measured_skus", -1) != 0:
            fail(f"lead_time_reconciliation: expected measured_skus=0 (no order-date data fed in), got {recon}")
        print("OK  lead_time_reconciliation correctly reports 0 measured SKUs (no inbound order-date tracking yet)")

        # ── segmentation.py: trend needs >=6 complete months (2*TREND_WINDOW) ──
        # This fixture only has 4 complete months (150 days, trimmed at both
        # ends) -- classify_trend() correctly leaves trend_class as None for
        # everyone rather than guessing from a too-short window. The populated
        # case (trend_class actually set) is exercised live in the browser
        # with a longer transaction history, not here.
        trend_known = result["trend_class"].notna().sum()
        if trend_known != 0:
            fail(f"expected trend_class to be None for all SKUs (only 4 complete months < 6 required), "
                 f"got {trend_known} classified -- either the fixture grew more history or classify_trend changed")
        print("OK  trend_class correctly stays unclassified with only 4 complete months of history")

        conn.close()
    finally:
        cleanup(slug)

    print("\nALL analysis_bridge CHECKS PASSED")


if __name__ == "__main__":
    main()
