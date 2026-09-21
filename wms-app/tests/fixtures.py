"""Small, fast, self-contained synthetic dataset for forecasting/ tests.

Deliberately NOT a reduced invocation of datagen/v1/generera_lagerdata.py:
that script is tuned for a realistic 3,000-item/4-year demo estate (see
its own docstring), and even though it runs in a few seconds, refactoring
it into a small-preset mode is datagen v2's job (docs/FORECAST_SPEC.md
section 6, not Phase 1). Tests must not depend on data/demo/ or on running
the v1 script (working agreement: "generate a small preset... at run
time") -- this is that preset, independently written, in the same
canonical column shape load_outbound()/load_items()/load_inbound() expect.

Fixed seed -> identical output every run, same principle as the real
generator. Deliberately includes, by construction (not by chance): a
steady-demand item, an intermittent one, one clean outlier spike, one
sustained level shift, one stockout-censored line, and one item created
partway through the window (to exercise the zero-fill-from-created-date
logic in build_demand_series()).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SEED = 42
N_ITEMS = 50
MONTHS = 6


def make_small_dataset(seed: int = SEED, n_items: int = N_ITEMS, months: int = MONTHS) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    start = pd.Timestamp("2026-01-05")  # a Monday
    end = start + pd.DateOffset(months=months)
    order_dates = pd.date_range(start, end, freq="D")
    order_dates = order_dates[order_dates.dayofweek < 5]  # business days only

    article_ids = [f"A{i:04d}" for i in range(1, n_items + 1)]

    # ── items ────────────────────────────────────────────────────────────
    created = [start] * (n_items - 1) + [start + pd.DateOffset(months=months // 2)]  # last item launches mid-window
    items = pd.DataFrame({
        "article_id": article_ids,
        "description": [f"Item {i}" for i in article_ids],
        "category": rng.choice(["Verktyg", "Hydraulik", "Elektronik"], size=n_items),
        "uom": "ST",
        "supplier_id": rng.choice(["S01", "S02", "S03"], size=n_items),
        "unit_cost_sek": rng.uniform(10, 500, size=n_items).round(2),
        "moq": rng.choice([1, 5, 10], size=n_items),
        "order_multiple": 1,
        "lead_time_days": rng.integers(5, 30, size=n_items),
        "reorder_point": rng.integers(5, 50, size=n_items),
        "safety_stock": rng.integers(1, 20, size=n_items),
        "created_date": created,
        "status": "Aktiv",
    })

    # ── outbound: article 0 = steady, article 1 = intermittent w/ outlier
    #    + level shift + one censored line, rest = light random noise ──────
    rows = []
    order_id_counter = 0
    for idx, article_id in enumerate(article_ids):
        item_created = items.loc[idx, "created_date"]
        dates_for_item = order_dates[order_dates >= item_created]
        if idx == 0:
            # steady: ~5 units every few business days
            pick_dates = dates_for_item[::3]
            qtys = rng.integers(4, 7, size=len(pick_dates))
            shipped = qtys.copy()
        elif idx == 1:
            # intermittent, with one clean outlier and a sustained level
            # shift halfway through (demand roughly triples from that point)
            pick_dates = dates_for_item[::5]
            base = rng.integers(1, 4, size=len(pick_dates))
            midpoint = len(pick_dates) // 2
            base[midpoint:] = base[midpoint:] * 3 + rng.integers(0, 2, size=len(base) - midpoint)
            if len(pick_dates) > 3:
                base[3] = base.max() * 20 + 50  # unmistakable one-off spike
            qtys = base
            shipped = qtys.copy()
        elif idx == 2:
            # one deliberately censored (stockout) line
            pick_dates = dates_for_item[::4]
            qtys = rng.integers(5, 10, size=len(pick_dates))
            shipped = qtys.copy()
            if len(shipped) > 2:
                shipped[2] = max(0, qtys[2] - rng.integers(3, 5))  # partial ship
        else:
            pick_dates = dates_for_item[rng.random(len(dates_for_item)) < 0.15]
            qtys = rng.integers(1, 5, size=len(pick_dates))
            shipped = qtys.copy()

        for d, q, s in zip(pick_dates, qtys, shipped):
            order_id_counter += 1
            rows.append({
                "order_date": d,
                "order_id": f"SO{order_id_counter:06d}",
                "order_line": 1,
                "article_id": article_id,
                "customer_id": f"K{rng.integers(1, 10):04d}",
                "qty_ordered": int(q),
                "qty_shipped": int(s),
            })
    outbound = pd.DataFrame(rows)

    # ── inbound: a handful of PO lines per article, with po_date/expected/receipt ──
    inbound_rows = []
    po_counter = 0
    for idx, article_id in enumerate(article_ids):
        n_pos = rng.integers(1, 4)
        for _ in range(n_pos):
            po_counter += 1
            po_date = start + pd.Timedelta(days=int(rng.integers(0, (end - start).days - 30)))
            lead = int(items.loc[idx, "lead_time_days"])
            expected = po_date + pd.Timedelta(days=lead)
            jitter = int(rng.integers(-2, 6))  # slightly late-skewed, realistic
            receipt = expected + pd.Timedelta(days=jitter)
            qty = int(rng.integers(10, 200))
            inbound_rows.append({
                "po_number": f"PO{po_counter:06d}",
                "po_line": 1,
                "po_date": po_date,
                "supplier_id": items.loc[idx, "supplier_id"],
                "article_id": article_id,
                "qty_ordered": qty,
                "unit_price_sek": items.loc[idx, "unit_cost_sek"],
                "expected_date": expected,
                "receipt_date": receipt,
                "qty_received": qty,
                "status": "Received",
            })
    inbound = pd.DataFrame(inbound_rows)

    return {"outbound": outbound, "items": items, "inbound": inbound}
