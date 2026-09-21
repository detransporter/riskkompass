# FORECAST_SPEC.md — Forecasting & Inventory Analytics Module

> Put this file in the repo (e.g. `docs/FORECAST_SPEC.md`) and reference it from `CLAUDE.md` with:
> `@docs/FORECAST_SPEC.md`

## 0. Working agreement (read first)

- The user is a senior supply chain expert (strong on inventory theory, planning parameters, data diagnosis) but does **not** write code. **Communicate in Swedish**, explain in supply-chain terms (service level, lead-time demand, safety stock, bias), not in code terms. Keep code, comments and identifiers in English.
- **Before writing any code:** inspect the existing repo (structure, SQLite schema, Streamlit pages, existing analytics such as safety stock / ABC-XYZ / dead stock) and present a short plan that maps this spec onto what already exists. Reuse and extend; do not rewrite working parts.
- Work **one phase at a time**. At the end of each phase: run all tests, commit, and give a short Swedish summary containing (a) what was built, (b) the numbers from the acceptance criteria, (c) known limitations.
- **Never claim an improvement without backtest numbers.** If a target is missed, say so plainly, investigate, and propose an adjusted target. Do not tune until a number looks good on the wrong data.
- The database is SQLite now and will move to Postgres (on-prem or Supabase) later: keep SQL portable, put all DB access behind one data-access module, no SQLite-only features in analytics code.
- All randomness seeded. Same seed -> identical output. All tunables in one config file (`config/forecast.yaml`).
- No data leakage: a forecast made at origin date T may only use data dated <= T. Add a test that proves this (e.g. shifting future data must not change past forecasts).
- Never commit customer data. Real/anonymised customer data lives outside git.

## 1. Goal

A forecasting module for an SME-focused WMS analytics layer that gives small companies the decision support of large enterprise systems. It must:

1. Forecast demand as a **distribution over the replenishment lead time**, not a point value.
2. Derive **safety stock and reorder points from quantiles**, with a per-item target service level based on economics.
3. Be **measured continuously** against simple baselines (Forecast Value Added).
4. **Prove value in a simulator**: same or better service with less stock value.
5. **Explain itself** to planners and monitor its own accuracy.

## 2. Data contract

Map onto the existing schema (adapt names; do not force a rename). Reference demo files (from the synthetic generator v1) use these columns:

| Table | Key columns |
|---|---|
| items (`artiklar.csv`) | article_id, description, category, uom, supplier_id, unit_cost_sek, moq, order_multiple, lead_time_days, reorder_point, safety_stock, created_date, status |
| outbound (`utleverans.csv`) | order_date, order_id, order_line, article_id, customer_id, qty_ordered, qty_shipped |
| inbound (`inleverans.csv`) | po_number, po_line, po_date, supplier_id, article_id, qty_ordered, unit_price_sek, expected_date, receipt_date, qty_received, status |
| stock (`lagersaldo_manadsslut.csv`) | snapshot_date, article_id, stock_qty, stock_value_sek |
| suppliers (`leverantorer.csv`) | supplier_id, supplier_name, country |
| **facit** (`facit_dolda_egenskaper.csv`) | true ABC/XYZ, obsolete flag and date, parameter quality, new-item flag. **Test-only. Must never be a model input or feature.** |

**Demand definition:** demand = `qty_ordered` (unconstrained), not `qty_shipped`. Lines where `qty_shipped < qty_ordered` mark stockout-affected (censored) periods.

## 3. Proposed structure (adapt to the repo)

```
forecasting/
  data.py            # load from DB, business calendar (Sweden), weekly/monthly aggregation
  cleaning.py        # censoring flags, outliers, level shifts, one-off large orders
  segmentation.py    # ADI/CV2 classes, lifecycle flags, ABC/XYZ
  metrics.py         # WAPE, bias, MASE, pinball loss, coverage
  backtest.py        # rolling-origin engine, per horizon and per segment
  models/
    baselines.py     # naive, seasonal naive, moving average, SES
    intermittent.py  # Croston, SBA, TSB
    statistical.py   # ETS / Theta (statsforecast or statsmodels)
    global_gbm.py     # one LightGBM model across all items
    ensemble.py       # combination + per-segment model selection by backtest
  probabilistic.py   # lead-time demand distribution, quantiles, conformal calibration
  policy.py          # quantile-based safety stock / reorder point, target quantile per item
  simulate.py        # inventory simulator to compare policies
  monitoring.py      # rolling error/bias, drift, override log, FVA, alerts
  explain.py         # plain-language explanation strings
datagen/             # synthetic data generator (see section 6)
tests/
config/forecast.yaml
```

Preferred libraries (check they install cleanly; keep dependencies modest): pandas, numpy, scipy, statsforecast (or statsmodels), lightgbm, a conformal-prediction helper (e.g. MAPIE, or a small own implementation), pytest.

## 4. Phases and acceptance criteria

Targets marked *(initial)* are starting points. If they prove unrealistic, report it and propose adjusted values. Do not game them.

### Phase 1 — Data layer and demand cleaning
- Load outbound/inbound/items/stock through the data-access module; build weekly and monthly demand series per article (zero-filled, from item creation date).
- Flag censored periods (`qty_shipped < qty_ordered`), outliers, one-off large orders, promotion-like spikes, level shifts.
- **Accept:** unit tests; on demo data the censoring flags cover the known stockout lines; series are complete (no gaps) and start at item creation.

### Phase 2 — Metrics and backtest harness (build this before any model)
- Rolling-origin backtest. Forecast horizon is **lead-time aligned** (the item's lead time + review period), plus fixed horizons 4 / 13 / 26 weeks.
- Metrics: WAPE, bias (%), MASE, **pinball loss at q = 0.5/0.8/0.9/0.95**, interval coverage. Report per segment (ABC, XYZ, ADI/CV2 class, category, supplier).
- Baselines first: naive, seasonal naive, moving average (several windows), SES, Croston/SBA.
- Results stored in a table/CSV and shown on a Streamlit page.
- **Accept:** baselines run on the full 3,000-item demo set in a few minutes; results reproducible; leakage test passes.

### Phase 3 — Segmentation and lifecycle
- Syntetos–Boylan classification with ADI cutoff 1.32 and CV² cutoff 0.49 -> smooth / erratic / intermittent / lumpy.
- Lifecycle flags: new item (short history), **obsolescence detection** (demand decay), stale/no-demand-but-stock. Keep ABC/XYZ consistent with the existing implementation.
- **Accept (*initial*), measured against `facit` in tests only:** ABC agreement >= 90 %; obsolete-item detection recall >= 80 % and precision >= 70 %; new-item flag recall >= 95 %.

### Phase 4 — Models per segment, ensemble, global model
- Candidates: ETS/Theta (smooth/erratic), Croston/SBA/TSB (intermittent), bootstrap or negative binomial (lumpy), global LightGBM across all items (lags, rolling stats, Swedish calendar incl. holiday/summer effects, category and item attributes, price/promo flags), cold-start via category analogues and hierarchical pooling (category -> article).
- Combination forecasts; per-segment model selection decided **by backtest**, stored with the result.
- **Accept (*initial*):** never worse than the best baseline in any segment; pinball loss at q=0.9 improves >= 5 % on smooth/erratic and >= 3 % on intermittent/lumpy versus the best baseline; report FVA per segment.

### Phase 5 — Probabilistic lead-time demand and calibration
- Build the **lead-time demand distribution** per item: demand distribution over (lead time + review period) with lead-time variability taken **empirically from inbound data** (expected vs actual receipt date, per supplier). Handle partial deliveries.
- Calibrate quantiles with conformal prediction.
- **Accept:** nominal 90 % intervals achieve 87–93 % empirical coverage in backtest, per segment; no systematic under-coverage on intermittent items.

### Phase 6 — Policy from quantiles
- Safety stock = target quantile of lead-time demand minus expected lead-time demand. Reorder point and order quantity respect MOQ / order multiple / EOQ from config.
- **Target service per item from economics** (newsvendor / critical ratio): selling margin or stockout cost, holding cost rate (default 22 %/yr) and ordering cost (default 400 SEK), all overridable per item/category. Fall back to ABC-based defaults when margin is unknown.
- `explain.py` produces a one-paragraph Swedish explanation per item (why this safety stock, what drives it, what changed).
- **Accept:** unit tests on known distributions; explanations exist for all items and reference real drivers (variability, lead-time uncertainty, intermittency).

### Phase 7 — Simulation as proof of value
- `simulate.py` replays history with **policy A = current ERP parameters** (reorder_point / safety_stock in the data) vs **policy B = new module**. Report fill rate, average stock value, stockout events, turns, dead-stock share; draw the **service-vs-stock-value frontier** for A, B and the baselines.
- **Accept (*initial*):** on the demo set, B reaches equal fill rate with lower stock value, or higher fill rate at equal stock value, overall and in most segments. State clearly that the demo data comes from a simulator, so this proves correctness, not real-world performance (see Phase 10).

### Phase 8 — Monitoring and alerts
- Rolling forecast error and bias per item; drift detection; auto-retrain trigger.
- Table for **manual overrides** (who, when, old/new value, reason) and **Forecast Value Added** of human overrides vs the model.
- Exception-based alerts (persistent bias, coverage breach, unexpected demand shift, obsolescence risk) with explanations.

### Phase 9 — Streamlit pages
Overview · Item view (history, forecast fan with quantiles, explanation) · Backtest by segment vs baselines · Policy comparison and frontier · Alerts · Data quality. Follow the existing app's structure and style.

### Phase 10 — Validation on real data
- Loaders for public datasets (e.g. M5 retail, a real intermittent spare-parts dataset such as *carparts*) mapped onto the data contract, with the same backtest and reports.
- An import path for anonymised customer data (files kept outside git), with a data-quality report before any modelling.
- **Accept:** the segment-level FVA table exists for at least one real dataset. Do not present synthetic-only results as evidence of real-world accuracy.

## 5. Guardrails

- `facit` is only for tests and demo scoring, never for training, features or model selection.
- No leakage; features use only data <= origin date.
- Vectorised code; document runtime for the full demo set; keep it usable on a laptop.
- Every model choice, parameter and result is stored so a planner can ask "why this number?".
- Small SMEs have short histories: prefer methods that pool information across items and degrade gracefully to simple baselines.

## 6. Synthetic data generator v2 (`datagen/`)

Start from the existing v1 script (`generera_lagerdata.py`, produces 3,000 items / 4 years; place it in `datagen/v1/`). Refactor into a configurable package, then extend:

- **Config file** with scale presets: small (300 items / 2 y), medium (3,000 / 4 y), large (20,000 / 5 y), plus a fixed `seed`.
- **Archetypes:** spare parts (many intermittent/lumpy items, long tail), distributor (fast movers, seasonality, promotions), manufacturing components (BOM-driven lumpy demand, long lead times, MOQ). Selectable per run.
- **Demand patterns** with known parameters: smooth, erratic, intermittent, lumpy, trend, seasonality (per category), level shift, promotion spikes, new-product ramp-up, obsolescence, customer concentration.
- **Realism layers:** stockout censoring, supplier disruptions and partial deliveries, price changes/inflation, ordering-parameter mistakes (too high / too low / stale), MOQ effects.
- **Data-error injection**, logged in a separate error facit: duplicate lines, late postings, negative quantities/returns, wrong unit of measure (x100), missing dates, merged/renamed articles.
- **Outputs:** CSV files as in v1, **and** direct load into the WMS SQLite schema. Separate `facit_*.csv`. Fixed seed -> byte-identical output.
- **Sanity report** printed after each run: fill rate, turns, share of items with > 365 days cover, dead-stock share, on-time delivery rate, row counts.
- **`make demo`** (or equivalent script): generate the demo database and launch the Streamlit app.
- **Accept:** determinism test (same seed twice -> identical hashes); sanity report within plausible bands; error facit lists every injected error.

## 7. Suggested first prompt to Claude Code

> Read `docs/FORECAST_SPEC.md` and inspect this repo. Do **not** write code yet. Give me (in Swedish) a plan: what already exists that maps to the spec, what is missing, the order you propose, and any questions. Then wait for my approval before starting Phase 1.
