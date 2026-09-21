#!/usr/bin/env python3
"""Generates realistic demo data directly into a wms-app tenant SQLite db.

Different job than datagen/v1/generera_lagerdata.py: that script writes
standalone CSVs for the forecasting-research demo set (data/demo/, 3000
items, used by tests/test_segmentation_facit.py etc against a facit). This
script instead writes straight into a real tenant's live SQLite database
(schema/tenant.sql) via db.py, so the data shows up in the running WMS app
exactly like an ERP import would -- items, locations, stock, transactions,
orders and order_lines, not analysis CSVs.

Simulates ~N_ITEMS SKUs over ~YEARS years, week by week: demand occurs per
item according to an assigned fast/medium/slow/rare tier, stock depletes,
and a simple reorder-point/reorder-quantity policy triggers replenishment
receives with the item's own lead time (a purchase order placed, arriving
lead_time_days later, matching the po_date/expected_date columns
docs/FORECAST_SPEC.md Phase 5 added to transactions). A slice of the
"rare" tier is marked to stop moving entirely partway through the window,
so the demo has genuine dead stock for the IHA report to find -- the whole
point of this app's IHA integration.

All randomness seeded (SEED=42) -- same seed, same data, every run. Run
directly: `python3 datagen/generate_wms_demo.py <company_slug>`. Wipes and
regenerates that tenant's items/locations/stock/transactions/orders tables
first (never the directory.db or other tenants) so re-running is safe.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db  # noqa: E402

SEED = 42
N_ITEMS = 400
YEARS = 3

# share, median unit cost SEK, lognormal sigma, base weekly qty scale,
# seasonal amplitude, peak day-of-year, unit, sku prefix
CATEGORIES = {
    "Fästelement":     (0.16, 3,    0.9, 40,  0.10, 150, "ST", "FE"),
    "Kullager":        (0.10, 350,  0.9, 3,   0.05, 100, "ST", "KL"),
    "Filter":          (0.09, 180,  0.7, 4,   0.15, 300, "ST", "FI"),
    "Hydraulik":       (0.10, 900,  1.0, 2,   0.10, 120, "ST", "HY"),
    "Elkomponenter":   (0.14, 120,  1.1, 8,   0.05, 60,  "ST", "EL"),
    "Kablage":         (0.09, 60,   0.8, 15,  0.05, 60,  "M",  "KA"),
    "Smörjmedel":      (0.07, 250,  0.6, 6,   0.30, 350, "L",  "SM"),
    "Verktyg":         (0.08, 400,  1.0, 2,   0.10, 90,  "ST", "VE"),
    "Förpackning":     (0.09, 15,   0.7, 60,  0.25, 320, "ST", "FO"),
    "Reservdel motor": (0.08, 2500, 1.1, 1.5, 0.08, 200, "ST", "RM"),
}

DESCRIPTORS = {
    "Fästelement": (["Sexkantskruv", "Insexskruv", "Bricka", "Mutter", "Bult", "Pinnskruv"],
                    ["M4x10", "M5x12", "M6x16", "M6x20", "M8x25", "M8x30", "M10x35", "M10x40", "M12x50"]),
    "Kullager": (["Spårkullager", "Rullager", "Vinkelkontaktlager", "Nållager", "Sfäriskt rullager"],
                 ["6202", "6204", "6205", "6305", "6308", "22208", "NU2206"]),
    "Filter": (["Oljefilter", "Luftfilter", "Hydraulfilter", "Bränslefilter"],
               ["F10", "F20", "F30", "F40", "F60"]),
    "Hydraulik": (["Hydraulslang", "Hydraulkoppling", "Hydraulcylinder", "O-ring", "Packning"],
                  ["1/4\"", "3/8\"", "1/2\"", "3/4\"", "1\""]),
    "Elkomponenter": (["Kontaktor", "Relä", "Säkring", "Brytare", "Sensor", "Frekvensomriktare"],
                       ["10A", "16A", "25A", "32A", "63A"]),
    "Kablage": (["Kraftkabel", "Styrkabel", "Kabelskarv", "Kabelhylsa"],
                ["1.5mm²", "2.5mm²", "4mm²", "6mm²", "10mm²"]),
    "Smörjmedel": (["Hydraulolja", "Växellådsolja", "Kullagerfett", "Kedjeolja"],
                   ["1L", "5L", "20L", "60L", "200L"]),
    "Verktyg": (["Skiftnyckel", "Momentnyckel", "Hylsa", "Skruvdragarbits", "Kombinationstång"],
                ["S", "M", "L", "XL"]),
    "Förpackning": (["Kartong", "Sträckfilm", "EU-pall", "Förpackningstejp", "Etikettrulle"],
                    ["A", "B", "C", "D"]),
    "Reservdel motor": (["Packningssats", "Kolvring", "Insugsventil", "Topplockspackning", "Vattenpump"],
                        ["Std", "OS0.25", "OS0.50"]),
}

SUPPLIER_SPEC = [  # country, count, lead_time_days range
    ("SE", 4, (3, 8)), ("DE", 4, (8, 18)), ("PL", 2, (10, 22)), ("IT", 2, (12, 25)),
    ("CN", 3, (35, 60)), ("TW", 2, (30, 50)), ("US", 1, (20, 35)),
]

CUSTOMERS = [
    "Nordic Industri AB", "Volvo Group Sverige", "Sandvik Materials", "SKF Sverige AB",
    "ABB Automation", "Scania CV AB", "Atlas Copco Industrial", "Epiroc Rock Drills",
    "Hexagon Manufacturing", "Alfa Laval AB", "Boliden Mineral AB", "SSAB EMEA AB",
    "Stora Enso Sverige", "Assa Abloy Entrance", "Trelleborg Sealing", "Getinge Group",
    "Husqvarna Group", "Permobil AB", "Bufab Sverige", "Indutrade AB", "Lesjöfors AB",
    "Beijer Electronics", "Nolato AB", "Munters Group", "Camfil AB",
]

TIERS = ["A", "B", "C", "D"]
TIER_WEIGHTS = [0.15, 0.30, 0.35, 0.20]
# (weekly qty-scale multiplier range, weekly occurrence probability)
TIER_PARAMS = {
    "A": ((2.5, 5.0), 0.95),
    "B": ((0.8, 2.0), 0.45),
    "C": ((0.5, 1.5), 0.15),
    "D": ((0.3, 1.0), 0.04),
}


def _build_suppliers(rng: np.random.Generator) -> list[dict]:
    suppliers = []
    for country, count, lt_range in SUPPLIER_SPEC:
        for i in range(count):
            suppliers.append({
                "name": f"Leverantör {country}-{i + 1:02d}",
                "country": country,
                "lead_time_days": rng.uniform(*lt_range),
            })
    return suppliers


def _build_locations() -> list[dict]:
    locations = []
    for i in range(1, 4):
        locations.append({"code": f"REC-{i:02d}", "zone": "Inleverans", "location_type": "receiving"})
    for aisle in "ABCDEF":
        for shelf in range(1, 6):
            for bin_ in range(1, 5):
                locations.append({
                    "code": f"{aisle}-{shelf:02d}-{bin_:02d}",
                    "zone": f"Plock {aisle}",
                    "location_type": "picking",
                })
    for i in range(1, 16):
        locations.append({"code": f"BULK-{i:02d}", "zone": "Bulk", "location_type": "bulk"})
    return locations


def _build_items(rng: np.random.Generator, suppliers: list[dict], picking_codes: list[str],
                  start: date, end: date) -> list[dict]:
    cat_names = list(CATEGORIES)
    cat_weights = np.array([CATEGORIES[c][0] for c in cat_names])
    cat_idx = rng.choice(len(cat_names), N_ITEMS, p=cat_weights / cat_weights.sum())

    tier_idx = rng.choice(len(TIERS), N_ITEMS, p=TIER_WEIGHTS)
    homes = rng.choice(picking_codes, N_ITEMS, replace=True)

    items = []
    sku_seq = {}
    window_days = (end - start).days
    for i in range(N_ITEMS):
        cat = cat_names[cat_idx[i]]
        _, median_cost, sigma, qty_scale, seasonal_amp, peak_doy, unit, prefix = CATEGORIES[cat]
        sku_seq[prefix] = sku_seq.get(prefix, 0) + 1
        sku = f"{prefix}-{sku_seq[prefix]:05d}"

        names, sizes = DESCRIPTORS[cat]
        description = f"{rng.choice(names)} {rng.choice(sizes)}"

        supplier = suppliers[rng.integers(0, len(suppliers))]
        lead_time_days = max(1, int(round(supplier["lead_time_days"] * rng.uniform(0.85, 1.15))))
        unit_cost = round(max(0.5, median_cost * rng.lognormal(0, sigma)), 2)

        if rng.random() < 0.85:
            created = start + timedelta(days=int(rng.integers(0, 60)))
        else:
            created = start + timedelta(days=int(rng.integers(180, max(181, window_days - 60))))

        tier = TIERS[tier_idx[i]]
        obsolete = tier == "D" and rng.random() < 0.40
        stop_date = None
        if obsolete:
            earliest = created + timedelta(days=180)
            latest = end - timedelta(days=60)
            if latest > earliest:
                stop_date = earliest + timedelta(days=int(rng.integers(0, (latest - earliest).days)))

        items.append({
            "sku": sku,
            "barcode": f"7300000{i:06d}",
            "description": description,
            "unit_cost": unit_cost,
            "currency": "SEK",
            "supplier": supplier["name"],
            "category": cat,
            "lead_time_days": lead_time_days,
            "created_at": created.isoformat(),
            "_created_date": created,
            "_home_location": homes[i],
            "_tier": tier,
            "_qty_scale": qty_scale,
            "_seasonal_amp": seasonal_amp,
            "_peak_doy": peak_doy,
            "_stop_date": stop_date,
        })
    return items


def _simulate_item(item: dict, rng: np.random.Generator, end: date) -> tuple[list[tuple], list[tuple], float]:
    """Weekly reorder-point simulation for one item.

    Returns (pick_events, receive_events, ending_stock). pick_events are
    (date, qty); receive_events are (po_date, expected_date, qty).
    """
    qty_range, occ_prob = TIER_PARAMS[item["_tier"]]
    base_qty = item["_qty_scale"]
    lead_time_weeks = item["lead_time_days"] / 7.0
    mean_weekly = base_qty * float(rng.uniform(*qty_range))

    reorder_point = max(1.0, mean_weekly * lead_time_weeks * 1.8)
    reorder_qty = max(5, int(round(mean_weekly * 8)))

    stock = float(reorder_qty)  # initial seed receive at creation
    pick_events: list[tuple] = []
    receive_events: list[tuple] = [(item["_created_date"], item["_created_date"], reorder_qty)]

    pending_arrival: date | None = None
    pending_qty = 0

    current = item["_created_date"]
    while current < end:
        if item["_stop_date"] is not None and current >= item["_stop_date"]:
            occurs = False
        else:
            seasonal = 1.0 + item["_seasonal_amp"] * np.cos(
                2 * np.pi * (current.timetuple().tm_yday - item["_peak_doy"]) / 365.25
            )
            occurs = rng.random() < occ_prob

        if occurs:
            qty = max(1, int(round(rng.poisson(max(0.5, mean_weekly * seasonal)))))
            pick_qty = min(qty, stock)
            if pick_qty > 0:
                day_offset = int(rng.integers(0, 7))
                pick_events.append((current + timedelta(days=day_offset), pick_qty))
                stock -= pick_qty

        if pending_arrival is not None and current >= pending_arrival:
            stock += pending_qty
            pending_arrival = None

        if pending_arrival is None and stock <= reorder_point and item["_stop_date"] is None:
            lead = item["lead_time_days"] * (1.3 if rng.random() < 0.10 else 1.0)
            expected = current + timedelta(days=int(round(lead)))
            pending_qty = max(5, int(round(reorder_qty * rng.uniform(0.9, 1.1))))
            pending_arrival = expected
            # Only log the receive if it actually arrives within the demo
            # window -- a PO placed near `end` with a long lead time is
            # still in transit, not yet received, so no transaction row for
            # it yet (and no stock credit either, see the arrival check
            # above, which only fires while current < end).
            if expected <= end:
                receive_events.append((current, expected, pending_qty))

        current += timedelta(days=7)

    return pick_events, receive_events, stock


def generate(company_slug: str) -> None:
    rng = np.random.default_rng(SEED)
    end = date.today()
    start = end - timedelta(days=YEARS * 365)

    conn = db.get_tenant_conn(company_slug)
    conn.execute("PRAGMA foreign_keys = OFF")
    for table in ("order_lines", "orders", "transactions", "stock", "locations", "items"):
        conn.execute(f"DELETE FROM {table}")
    conn.commit()

    suppliers = _build_suppliers(rng)
    locations = _build_locations()
    picking_codes = [loc["code"] for loc in locations if loc["location_type"] == "picking"]

    conn.executemany(
        "INSERT INTO locations (code, zone, location_type) VALUES (:code, :zone, :location_type)",
        locations,
    )

    items = _build_items(rng, suppliers, picking_codes, start, end)
    conn.executemany(
        """INSERT INTO items (sku, barcode, description, unit_cost, currency, supplier,
                              category, lead_time_days, created_at)
           VALUES (:sku, :barcode, :description, :unit_cost, :currency, :supplier,
                   :category, :lead_time_days, :created_at)""",
        items,
    )

    all_picks: list[tuple[date, str, int, str]] = []  # date, sku, qty, home_location
    receive_rows = []
    stock_rows = []

    for item in items:
        pick_events, receive_events, ending_stock = _simulate_item(item, rng, end)
        for pick_date, qty in pick_events:
            all_picks.append((pick_date, item["sku"], qty, item["_home_location"]))
        for po_date, expected_date, qty in receive_events:
            receive_rows.append({
                "txn_type": "receive",
                "sku": item["sku"],
                "qty": qty,
                "from_location": None,
                "to_location": item["_home_location"],
                "reference": None,
                "user_email": "demo@barisab.com",
                "created_at": f"{expected_date.isoformat()}T08:00:00",
                "po_date": po_date.isoformat(),
                "expected_date": expected_date.isoformat(),
            })
        if ending_stock > 0:
            stock_rows.append({"sku": item["sku"], "location_code": item["_home_location"], "qty": ending_stock})

    conn.executemany(
        """INSERT INTO transactions (txn_type, sku, qty, from_location, to_location, reference,
                                     user_email, created_at, po_date, expected_date)
           VALUES (:txn_type, :sku, :qty, :from_location, :to_location, :reference,
                   :user_email, :created_at, :po_date, :expected_date)""",
        receive_rows,
    )
    conn.executemany(
        "INSERT INTO stock (sku, location_code, qty) VALUES (:sku, :location_code, :qty)",
        stock_rows,
    )
    conn.commit()

    # ---- Group historical picks into customer orders (all shipped) ------
    all_picks.sort(key=lambda row: row[0])
    live_cutoff = end - timedelta(days=7)
    historical = [p for p in all_picks if p[0] < live_cutoff]

    order_rows = []
    order_line_rows = []
    pick_txn_rows = []
    order_seq = 0
    i = 0
    rng2 = np.random.default_rng(SEED + 1)
    while i < len(historical):
        chunk_size = int(rng2.integers(3, 9))
        chunk = historical[i:i + chunk_size]
        i += chunk_size
        if not chunk:
            continue
        order_seq += 1
        order_no = f"SO-{order_seq:06d}"
        order_date = chunk[0][0]
        customer = CUSTOMERS[rng2.integers(0, len(CUSTOMERS))]
        order_rows.append({
            "order_no": order_no, "order_type": "outbound", "status": "shipped",
            "reference": customer, "created_at": f"{order_date.isoformat()}T09:00:00",
        })
        for line_no, (pick_date, sku, qty, home) in enumerate(chunk, start=1):
            order_line_rows.append({
                "order_no": order_no, "line_no": line_no, "sku": sku,
                "qty_ordered": qty, "qty_done": qty, "location_code": home,
            })
            pick_txn_rows.append({
                "txn_type": "pick", "sku": sku, "qty": qty,
                "from_location": home, "to_location": None, "reference": order_no,
                "user_email": "demo@barisab.com", "created_at": f"{pick_date.isoformat()}T13:00:00",
                "po_date": None, "expected_date": None,
            })

    # ---- Live orders (last 7 days): some open, some mid-pick ------------
    active_items = [it for it in items if it["_stop_date"] is None or it["_stop_date"] > live_cutoff]
    live_pool = list(rng2.choice(active_items, size=min(30, len(active_items)), replace=False))
    live_orders = []
    for idx, item in enumerate(live_pool):
        qty = max(1, int(round(item["_qty_scale"] * rng2.uniform(1.0, 3.0))))
        live_orders.append((item, qty))

    for batch_start in range(0, len(live_orders), 5):
        batch = live_orders[batch_start:batch_start + 5]
        if not batch:
            continue
        order_seq += 1
        order_no = f"SO-{order_seq:06d}"
        customer = CUSTOMERS[rng2.integers(0, len(CUSTOMERS))]
        is_picking = (batch_start // 5) % 3 == 0  # every third live order already partially picked
        order_rows.append({
            "order_no": order_no, "order_type": "outbound",
            "status": "picking" if is_picking else "open",
            "reference": customer,
            "created_at": f"{(end - timedelta(days=int(rng2.integers(0, 5)))).isoformat()}T09:00:00",
        })
        for line_no, (item, qty) in enumerate(batch, start=1):
            qty_done = 0
            if is_picking and rng2.random() < 0.5:
                qty_done = max(1, qty // 2)
            order_line_rows.append({
                "order_no": order_no, "line_no": line_no, "sku": item["sku"],
                "qty_ordered": qty, "qty_done": qty_done, "location_code": item["_home_location"],
            })
            if qty_done > 0:
                pick_txn_rows.append({
                    "txn_type": "pick", "sku": item["sku"], "qty": qty_done,
                    "from_location": item["_home_location"], "to_location": None, "reference": order_no,
                    "user_email": "demo@barisab.com",
                    "created_at": f"{end.isoformat()}T10:00:00",
                    "po_date": None, "expected_date": None,
                })
                conn.execute(
                    "UPDATE stock SET qty = MAX(0, qty - ?) WHERE sku = ? AND location_code = ?",
                    (qty_done, item["sku"], item["_home_location"]),
                )

    conn.executemany(
        "INSERT INTO orders (order_no, order_type, status, reference, created_at) "
        "VALUES (:order_no, :order_type, :status, :reference, :created_at)",
        order_rows,
    )
    conn.executemany(
        "INSERT INTO order_lines (order_no, line_no, sku, qty_ordered, qty_done, location_code) "
        "VALUES (:order_no, :line_no, :sku, :qty_ordered, :qty_done, :location_code)",
        order_line_rows,
    )
    conn.executemany(
        """INSERT INTO transactions (txn_type, sku, qty, from_location, to_location, reference,
                                     user_email, created_at, po_date, expected_date)
           VALUES (:txn_type, :sku, :qty, :from_location, :to_location, :reference,
                   :user_email, :created_at, :po_date, :expected_date)""",
        pick_txn_rows,
    )
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")

    _print_report(conn, start, end)
    conn.close()


def _print_report(conn, start: date, end: date) -> None:
    n_items = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    n_locations = conn.execute("SELECT COUNT(*) FROM locations").fetchone()[0]
    n_txn = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    n_receive = conn.execute("SELECT COUNT(*) FROM transactions WHERE txn_type = 'receive'").fetchone()[0]
    n_pick = conn.execute("SELECT COUNT(*) FROM transactions WHERE txn_type = 'pick'").fetchone()[0]
    n_orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    n_open = conn.execute("SELECT COUNT(*) FROM orders WHERE status IN ('open', 'picking')").fetchone()[0]
    stock_value = conn.execute(
        "SELECT ROUND(SUM(s.qty * i.unit_cost), 0) FROM stock s JOIN items i ON i.sku = s.sku"
    ).fetchone()[0]
    dead_skus = conn.execute(
        """SELECT COUNT(*) FROM items i
           WHERE NOT EXISTS (
               SELECT 1 FROM transactions t
               WHERE t.sku = i.sku AND t.txn_type = 'pick' AND t.created_at >= ?
           )"""
        , (f"{(end - timedelta(days=180)).isoformat()}T00:00:00",),
    ).fetchone()[0]

    print("=== Demodata genererad ===")
    print(f"Period: {start.isoformat()} – {end.isoformat()} ({YEARS} år)")
    print(f"Artiklar: {n_items}  |  Platser: {n_locations}")
    print(f"Transaktioner totalt: {n_txn}  (mottag: {n_receive}, plock: {n_pick})")
    print(f"Ordrar: {n_orders}  (varav öppna/plockas just nu: {n_open})")
    print(f"Lagervärde vid periodens slut: {stock_value:,.0f} SEK".replace(",", " "))
    print(f"Artiklar utan plock senaste 180 dagarna (potentiell dödlager-kandidat): {dead_skus}")


if __name__ == "__main__":
    slug = sys.argv[1] if len(sys.argv) > 1 else "testbolaget-ab"
    if not db.tenant_exists(slug):
        print(f"Ingen tenant-databas hittades för slug '{slug}' (data/tenants/{slug}.db saknas).")
        sys.exit(1)
    generate(slug)
