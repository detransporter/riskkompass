# CLAUDE.md — WMS-app

Multi-tenant warehouse management system with SQLite as the system of
record, built for David's SME logistics-consulting clients. Full plan and
rationale: `/Users/davidleifsson/.claude/plans/deep-tumbling-lagoon.md`.

**Forecasting & inventory analytics module: governed by its own spec,
@docs/FORECAST_SPEC.md — read it before touching anything under
`forecasting/`, `datagen/`, or `config/forecast.yaml`.** It sets its own
working agreement (Swedish communication, one phase at a time, no claims
without backtest numbers, seeded determinism, no SQLite-only features, never
commit customer data) that supersedes the general conventions below where
the two would conflict for that code specifically. Progress against it is
tracked in that phase's own section here, not duplicated in "Status" below.

## What this is, in one paragraph

Every other lager-tool in this repo (`inventory-app`, `iha-saas`,
`inventory-demo`) is an analysis app: upload an Excel file once, get a
report. This is not that. WMS-app owns the live warehouse state — items,
locations, stock balances, and every receive/putaway/pick/pack/ship/adjust
movement — and runs the same IHA analysis logic from `iha-saas` directly
against that live transaction history instead of an uploaded file.

## Architecture decisions (don't relitigate without reading why first)

- **One SQLite file per company** (`data/tenants/<slug>.db`), not one shared
  database. SQLite has no row-level security, so isolation is physical, not
  a `WHERE company_id = ?` clause someone could forget. `data/directory.db`
  is the only shared file and holds identity only (companies, users) — never
  operational data.
- **`views/`, not `pages/`.** Streamlit auto-detects a folder literally named
  `pages/` next to the entry script and injects its own multipage sidebar
  nav — confirmed locally, it silently duplicated the app's own radio nav.
  `iha-defense/app/views/` already avoided this; do the same here. If you
  ever see a stray native Streamlit page-nav appear, this is why.
- **No ORM, no Supabase.** Plain `sqlite3` + `sqlite3.Row`, same pattern as
  `transportbokning/app.py`. Auth is local: `hashlib.pbkdf2_hmac` (stdlib,
  no `bcrypt` C-extension to build on the deploy VPS) + a `directory.db`
  users table. `auth.password_problem()` is a verbatim port of
  `iha-saas/auth.py`'s function — keep the two in sync if the policy ever
  changes.
- **`db.record_transaction()` is the only path that may write to `stock`.**
  It keeps `stock` balances and the `transactions` audit log consistent in
  one place; never `UPDATE stock` directly from a page. Insufficient-stock
  attempts raise `ValueError` rather than going negative — surface that to
  the user, don't swallow it.
- **WAL mode** is enabled per tenant connection (`PRAGMA journal_mode=WAL`
  in `schema/tenant.sql` and `db.get_tenant_conn`). Fine for a handful of
  concurrent warehouse users; if a tenant ever needs more, the schema is
  already written in the SQLite/Postgres intersection (see
  `iha-defense/data/schema.sql` for the same convention) so migrating that
  one tenant to Postgres is not a rewrite.

## IHA integration (milestone 3 — built)

`analysis/{dos_calculator,abc_classifier,segmentation,lead_time,
inventory_bridge}.py` are full, unmodified vendor copies of the
`iha-saas/analysis/` originals (zero Supabase dependencies there — pure
pandas in, pandas out). `analysis/data_merge.py` is a **trimmed** copy: only
`sales_statistics()`, `aggregate_inbound()` and the helpers they call are
kept — `guess_mapping`/`detect_role`/`SYNONYMS`/`build_canonical` from the
source file exist there to solve messy-Excel-column-name problems that
wms-app's own SQLite schema doesn't have.

`analysis_bridge.py` replaces the Excel-upload step:
`build_canonical(conn)` reads `items`/`stock`/`transactions` directly into
the same canonical column shape `iha-saas` produces from a file, then
`run_analysis(df)` runs the exact same pipeline order as
`iha-saas/pages/upload.py:_run_analysis()`:

```
calculate_dos → classify_status → classify_abc → segment
  → resolve_lead_time → compute_replenishment → compute_bridge → classify_root_cause
```

`views/iha_report.py` renders it: KPI row from the bridge summary
(total/dead/excess/releasable/deficit/annual saving), status breakdown,
ABC×XYZ matrix, root-cause expanders, and the full item table.

This is a vendored copy, not a shared package — fixes in `iha-saas/analysis/`
do not automatically propagate here. Acceptable tradeoff for now (see plan
file); revisit if both apps live long enough that the drift becomes painful.

**Deliberately not vendored:** `analysis/demand_forecast.py` (SBC
classification, ETS/Croston-SBA/TSB forecasting) and its
scipy/numba/statsmodels/statsforecast dependencies — real weight (the exact
stack behind the Streamlit Cloud build incident documented in
`iha-saas/CLAUDE.md`) for a feature outside milestone 3's scope. Add as its
own milestone later if wanted, matching those pins from
`iha-saas/requirements.txt` exactly.

**Known MVP limitation:** `analysis_bridge.build_canonical()` doesn't pass
an `order_date_col`/`promised_col` to `aggregate_inbound()` — the WMS schema
has no "ordered at" timestamp separate from "received at" yet, only a single
`receive` transaction. So `lead_time.resolve_lead_time()` almost always
falls back to `lead_time_source = "master"` (the item's own
`lead_time_days`) rather than `sku_measured`/`supplier_measured`. Honest
limitation, not a bug — fixable later by adding an inbound-order table with
both dates.

**`db.now_iso()` stores naive UTC timestamps (no `+00:00` suffix), on
purpose** — added when building this integration. The vendored analysis code
does plain (tz-naive) datetime arithmetic throughout (days-since-movement,
month-period grouping); mixing naive and tz-aware pandas Timestamps raises.
Naive-but-always-UTC was simpler than threading `tz_localize` calls through
vendored code written assuming naive dates.

**Verified 2026-09-16** with a hand-built 6-SKU, 150-day transaction history
(3 healthy items at varying DOS, one zero-demand dead-stock item, one item
picked down to an exact stockout) run through the real pipeline via script
and confirmed in the browser: every number — DOS, status, ABC tier, and the
full bridge (justified/excess/dead/deficit) — matched hand calculation
exactly, including the bridge's SEK totals down to the unit.

## Expanded IHA report + Excel export (built 2026-09-16, post-milestone-3)

Added on request after reviewing what milestone 3 deliberately left out. Four
more vendored/wired-in analyses, all "almost free" because the logic already
existed in `analysis/lead_time.py`/`segmentation.py` or was a tiny, dependency-free
file (`health_scorer.py`, 51 lines, pure pandas — vendored unchanged):

- **Lagerhälsopoäng** — `health_scorer.compute_health_score()`, ABC-weighted
  0–100 score, shown as the first metric on the report so there's one number
  to glance at before the detail.
- **Trend** — `trend_class` was already computed by `segment()` but never
  surfaced; now has its own breakdown section and a column in the item
  table. Needs **≥6 complete months** of pick history
  (`2 * TREND_WINDOW` in `segmentation.py`) or it stays `None` for every
  SKU — verified both ways: `test_analysis_bridge.py`'s fixture (4 complete
  months) asserts trend stays unclassified; a separate live-browser check
  with 230 days of history got a real item correctly classified `growing`.
- **Leverantörsanalys** — `lead_time.supplier_scorecard()` +
  `supplier_flags()`, wired in for the first time. Verified live: two
  suppliers where one holds 90% of inventory value correctly triggered the
  `>40%` concentration-risk flag. The flag *text* is hardcoded English in
  the vendored source; the UI calls `components/sv.py:supplier_flags_sv()`
  instead (a parallel Swedish implementation, same thresholds imported from
  `lead_time.py` so they can't drift) — see "All UI text in Swedish" below.
- **Ledtidsavstämning** — `lead_time.lead_time_reconciliation()`. Given the
  known MVP limitation documented above (no inbound order-date tracking),
  this always reports `measured_skus: 0` today — the UI shows an explicit
  explanatory caption instead of a confusing empty section rather than
  hiding the section outright, so it's clear the feature exists and why
  it's not populated yet.
- **Excel export** — `components/export.py:excel_download_button()`, same
  `io.BytesIO` + `st.download_button` pattern as `iha-saas/pages/results.py`.
  Added to the IHA report's item table and supplier scorecard, and to both
  Lagersaldo tables. Requires `openpyxl` (added to `requirements.txt`).
  Verified by actually downloading a file through the browser and loading
  it back with `openpyxl` — real file, correct headers, correct data, not
  just "the button renders."

## UI language: Swedish + English (built 2026-09-17, extended 2026-09-18)

All UI text was first translated to Swedish (2026-09-17), then extended to a
live sv/en language switcher (2026-09-18) after David asked "kan vi har wms
på svenska och engelska?". Two layers, kept separate on purpose:

**`components/i18n.py`** — free-standing UI strings (nav labels, buttons,
form labels, messages, errors) that don't come from the analysis pipeline.
One flat `STRINGS` dict, `{key: {"sv": ..., "en": ...}}`, looked up via
`t(key, **kwargs)` which reads the language from `st.session_state["lang"]`
(default `"sv"`) and falls back to Swedish-then-the-raw-key if a translation
is ever missing, so a gap degrades to visible-but-ugly rather than a crash.
`language_switcher()` renders the sv/en radio (used on both the login
screen and the sidebar) and writes the chosen language straight to session
state — **deliberately does not call `st.rerun()`**, see the pitfall below.

**`components/sv.py`** — translation of data-driven labels coming out of
the vendored `analysis/*.py` pipeline (English column names, status values,
prose — unchanged per the vendoring rule above). Every `*_LABELS` dict now
has an `_EN` twin (e.g. `STATUS_LABELS` / `STATUS_LABELS_EN`), selected via
a `*_labels(lang)` helper (`status_labels`, `trend_labels`,
`order_status_labels`, `policy_labels`, `root_cause_labels`,
`root_cause_actions`). `rename_columns(df, lang)`, `supplier_flags_sv(df,
lang)`, and `translate_demand_note(note, lang)` all default `lang="sv"` so
every pre-existing call site (and `test_analysis_bridge.py`, which asserts
Swedish output) kept working unchanged; view code now passes
`lang=get_lang()` explicitly. `translate_demand_note` just returns the note
unchanged for `lang="en"` — the vendored note is already English prose, so
only the Swedish path needs the regex rewrite.

`auth.py` (`password_problem`, `register_company`, `login`) and
`db.record_transaction`/`_adjust_stock` (the "Otillräckligt saldo" /
"Insufficient stock" error) both grew an explicit `lang: str = "sv"`
parameter, called with `lang=get_lang()` from `app.py`/the views. Default
stays `"sv"` so `test_auth.py`/`test_db.py` (which only assert
`except ValueError`/truthy-error, never exact text) needed no changes.

**`views/import_data.py`'s field tuples changed shape**: `ITEM_FIELDS` /
`LOCATION_FIELDS` / `STOCK_FIELDS` used to be `(field, swedish_label,
required)`; the label is now looked up at render time via `t(FIELD_LABEL_KEYS[field])`
instead, so the tuples are just `(field, required)`. `guess_mapping()`'s
unpacking was updated to match. `test_import.py` passes these constants
straight through to `guess_mapping()` without inspecting their shape, so it
needed no changes — worth knowing if that test ever gets extended to check
field labels directly.

**Pitfall hit and fixed live (important if touching `app.py`'s sidebar
again):** the sidebar nav (`st.radio` over the page list) lost its
selection — visibly and functionally — every time the language was
switched. Root-caused in the browser, not guessed:
1. `language_switcher()` originally called `st.rerun()` the moment it
   detected a change. That aborts the *current* script pass immediately,
   before the nav radio widget (rendered later in the same sidebar block)
   ever executes. Streamlit garbage-collects session state for widgets not
   rendered in a completed run, so the nav radio's remembered page was
   wiped — reruns landed back on the first page. **Fix: don't call
   `st.rerun()` there at all.** Streamlit already reruns the script on any
   widget change; code below the language switcher in the same pass
   already sees the new language via `get_lang()`, no manual rerun needed.
2. Even after that fix, the nav radio's *visual* selection (which circle
   is filled) still went blank on a language switch, even though the
   correct page kept rendering — Streamlit's radio/selectbox reconciles a
   keyed widget's selection against its *rendered option text*, and
   `format_func` changing that text between reruns (Swedish → English
   labels) desyncs the frontend highlight independent of the underlying
   value (confirmed this isn't an int-vs-string identity issue either).
   **Fix:** track the current page in `st.session_state["current_page_id"]`
   ourselves, and key the radio as `f"nav_radio_{lang}_{current}"` — a
   composite key that changes whenever language *or* page changes, forcing
   Streamlit to treat it as a fresh widget mount that always honors the
   explicit `index=` we pass, rather than trying to reconcile stale
   frontend state against newly-translated labels.

**Verified live in the browser, not just read from source:** registered a
company in English (full register form translated), confirmed the language
choice persists into the logged-in session (sidebar, nav, page titles),
seeded 200+ real transactions and ran the IHA report end to end in both
languages (health score, KPIs, status/trend breakdowns, ABC×XYZ matrix,
supplier analysis + concentration-risk warning banner, Excel export button
label), and specifically re-tested the nav-desync pitfall above by
navigating to IHA-rapport → switching to English → confirming both the page
content *and* the sidebar highlight stayed correct, then switching languages
repeatedly while also changing pages to confirm normal navigation still
works. Full test suite (`test_db.py`, `test_auth.py`, `test_orders_pick.py`,
`test_transfer.py`, `test_analysis_bridge.py`, `test_import.py`) re-run and
passing after every step of this change.

**Deliberately still not done** (flagged to David, not started): demand
forecasting (`demand_forecast.py` — heavy scipy/numba/statsmodels/statsforecast
chain, the exact stack behind a real Streamlit Cloud incident documented in
`iha-saas/CLAUDE.md`). PDF/PPT export not started either; PPT in particular
is a substantial module in `iha-saas` (915 lines/39 functions with
matplotlib-rendered charts), not a quick add. Language choice is
per-browser-session only (same limitation as login — lost on a hard
refresh), not saved per user account; see the "per användarkonto" option
David didn't pick when asked.

## Påfyllningslista (`views/reorder.py` — built 2026-09-17)

Standalone page ("Påfyllning" in the sidebar, between Plocka and IHA-rapport
— checked daily, not read top-to-bottom like the analysis report). No new
analysis: `reorder_df(df)` in `views/reorder.py` is a pure function (no
Streamlit calls, directly unit-testable) that filters the already-computed
`run_analysis()` output to `order_qty > 0` and sorts by
`(stockout_risk desc, dos asc, order_value_sek desc)` — safety first, then
urgency, then dollar impact.

**The nuance worth remembering:** a "healthy" DOS status and "needs
reordering" are different questions with different answers. Verified live
with real data: SKU-A2 had `status = healthy` (normal DOS) but still showed
up on the reorder list with `order_qty = 60`, because current stock had
dropped below the replenishment target (`rop` + 30 days buffer) even though
the DOS-based status classifier hadn't flagged it. The docstring in
`reorder.py` calls this out explicitly so a future reader doesn't "fix" it
as a bug.

Grouped-by-supplier subtotal table included (same rationale as the IHA
report's Leverantörsanalys — a buyer places one PO per supplier, not one
per SKU). Excel export via the same `components/export.py` helper as
everywhere else.

**Read-only by design.** No "mark as ordered" — that would need open-PO
tracking the schema doesn't have (see the lead-time reconciliation
limitation above). The same SKU reappears tomorrow if nothing was actually
ordered or received; `render()`'s docstring says so explicitly.

**Verified**, not just read from source: `test_analysis_bridge.py` asserts
on the exact fixture values inspected beforehand (not guessed) —
`SKU-STOCKOUT` (order_qty=129, stockout_risk) must sort *ahead of*
`SKU-A2` (order_qty=60, no stockout risk) despite a *smaller* SEK value
(19,350 vs 48,000), proving urgency outranks dollar size in the sort.
`SKU-DEAD` must never appear. Live browser walkthrough confirmed the same
two rows in the same order, correct Swedish column headers throughout
(caught and fixed two real bugs this way: `order_value_sek` was missing
from `COLUMN_LABELS`, and the supplier-subtotal table had a stray lowercase
"leverantör" header from renaming a column before `rename_columns()` ran
instead of after), and a real Excel download reloaded with `openpyxl` to
confirm correct headers and data.

## Stock transfers (`views/transfer.py` — built 2026-09-16, post-milestone-3)

Added after the three planned milestones, on request: a standalone "Flytta"
page for moving stock between two locations for reasons unrelated to
receiving (reorganizing, cycle-count corrections). No new schema or
transaction type was needed — `db.record_transaction`'s `putaway` type
already models "move qty from `from_location` to `to_location`" exactly;
`receive.py` was already calling it internally as the second half of a
combined receive+putaway. This page just exposes that same call as its own
scan-driven flow (same two-step scan → confirm shape as receive.py/pick.py),
showing current per-location stock for the scanned SKU so the operator can
see where to move *from* before choosing a destination.

Validates `from_location != to_location` before calling
`record_transaction` (a same-location "transfer" would net to zero stock
change but still add a confusing log row — same reasoning receive.py
already documents for skipping a same-location putaway). Insufficient-stock
`ValueError` from `record_transaction` is caught and shown as a page error,
same pattern as every other write path in this app.

Verified live: scanned an item with 160 units at A-01-01, moved 60 to a new
location B-02-01, confirmed the stock view split correctly to 100/60 across
the two locations with the total unchanged.

**Manual selection, no scanner required.** The scan field already accepted
typed SKUs (`db.find_item_by_code` checks barcode OR sku), but on request a
second option was added: a dropdown ("Eller välj manuellt ur listan") below
the scan form, populated from `_items_with_stock()` (only SKUs that
currently have stock somewhere -- no point listing an item with nothing to
move). Selecting + clicking "Välj artikel" sets the same `_PENDING_KEY`
session state the scan path sets, so step 2 (confirm) is identical either
way. Verified live: picking SKU-100 from the dropdown landed on the same
confirm screen as scanning it would.

## Demand forecasting engine (steps 1–2 built 2026-09-20, not yet exposed in the UI)

Ported from `iha-saas` on request, after David flagged the existing ABC/DOS/
XYZ/root-cause analysis as purely diagnostic ("en snapshot av verkligheten")
and asked specifically for the forecasting engine to go deeper than "medel
plus svängning" (ETS is literally an exponentially weighted moving average;
Croston/SBA/TSB are literally average demand size ÷ average interval — an
accurate, not unfair, characterization of what was there before this).
Research and a phased roadmap live in a Claude Artifact built during that
conversation (not part of this repo) before any code changed — read that
first if extending this further, it has the paradigm comparison (global ML
models / time-series foundation models / hierarchical reconciliation) and
why foundation-model cold-start forecasting (Chronos-Bolt, CPU-only, ARM
compatibility unverified) is flagged as the highest-leverage next step, not
yet attempted here.

**What was actually done here is steps 1–2 of that roadmap only:** the data
bridge and a straight vendor of the engine, not a new UI page, not the ETS
conformal-interval extension, not the FVA/backtesting harness, not the
Chronos spike. Those remain open.

### `analysis/demand_forecast.py`, `analysis/simulation.py` — vendored unchanged
Byte-for-byte copies from `iha-saas/analysis/`, same rule as every other
vendored file in `analysis/` (never edit; re-vendor on upstream changes).
`demand_forecast.py` classifies each SKU by demand pattern (Syntetos-Boylan:
smooth/intermittent/erratic/lumpy) and routes to ETS (smooth) or
Croston-SBA/TSB (everything else), plus `forecast_dead_stock_risk()` —
compares the forecast against today's `classify_status()` verdict and flags
`emerging` (healthy today, forecast says decline — the signal trailing DOS
can't see yet), `confirmed`, `recovering`, `none`. `simulation.py` is the
policy-scenario engine (`simulate()`): four levers (service level, lead
time, lead-time reliability, batch size), recomputes *required* capital
under different policies — "what happens if we shorten Supplier X's lead
time by 20%" answered in SEK, not stock on hand.

**Correction to the earlier research artifact, found while reading the code
closely enough to actually wire it up:** Croston/SBA/TSB already use
`statsforecast`'s `ConformalIntervals` (calibrated, not naively parametric)
— the artifact originally suggested adding this as a quick win, which was
wrong. The real remaining gap is the **ETS branch**, which still only uses
AutoETS's native parametric interval. Since ETS is what runs for "smooth"
demand — plausibly the most common class for steady B2B SME consumption —
that is the actual next opportunity for tighter, better-calibrated forecast
bands, not a generic "add conformal prediction" task.

### `analysis_bridge.py:build_demand_history()` — the new piece
`demand_forecast.py` wants a long-format `(sku, period, qty)` history with
explicit zero rows for no-demand months but months before a SKU's own first
transaction *absent entirely* (not zero — it didn't exist yet). That is a
different shape from `build_canonical()`'s per-item summary row, and
critically it is **not re-derived from scratch** here: it reads
`demand_monthly_full`, a column `build_canonical()` already gets for free
via `data_merge.sales_statistics()` (Shape 3, the `dmin`/`dmax`
launch-masking logic documented in that file — `before_launch` mask on the
SKU × month pivot). `build_demand_history()` just melts that existing dict
column into the long rows `demand_forecast.py` wants, so the two vendored
IHA and forecasting pipelines can never disagree about which months a SKU
"existed" in — they read the exact same masked matrix.

### Dependencies — same pins as iha-saas, ARM compatibility unverified
`requirements.txt` gained `statsforecast`/`scipy`/`numba`/`statsmodels` at
the same version pins already proven working in `iha-saas/requirements.txt`
(see that file and its CLAUDE.md for the Streamlit Cloud OOM incident these
pins avoid — specific to that platform's build environment, not the
libraries, but the pins matter regardless of host). Installed and verified
importing cleanly on this dev machine (`pip install`, then a live import of
every new symbol). **Not yet verified on the Oracle ARM (aarch64) VPS** this
app actually deploys to — do a clean-install check there before relying on
this in production, per the still-open item in the research artifact.

### Verification
`test_demand_forecast.py` — own throwaway tenant, real transaction data (a
steady ~30-units/month SKU over 8 observed months, plus a just-launched SKU
with only two transactions). Checks the actual contract end to end, not
just that imports resolve: `build_demand_history()` produces exactly the
`(sku, period, qty)` shape with no pre-launch periods leaking in;
`classify_sbc()` reads the steady SKU as `smooth`; `select_forecast_method()`
routes it to ETS and returns a forecast within a plausible range of its real
history (avg ~30.3/month against an observed ~28–32/month), while the
short-history SKU is correctly absent rather than given a fabricated
forecast; `forecast_dead_stock_risk()` agrees the healthy SKU has no
emerging risk; `simulate()` shows required capital genuinely drop (not a
degenerate 0→0) when lead time is shortened 20%, confirmed against a SKU
deliberately kept in the *healthy* DOS range — an earlier fixture draft
accidentally left it overstocked into `dead_stock` territory, which zeroes
out required capital by `simulation.py`'s own "a dead item requires
nothing" rule and made the simulate() check trivially pass without
exercising the actual lever logic; tightening the fixture caught that.
Full existing suite (`test_db.py` through `test_import.py`) re-run and
still passing after this change.

### Still open (not built)
New `views/forecast.py` page, the ETS conformal-interval extension, the
FVA/backtesting harness, the Chronos-Bolt ARM spike — all as scoped in the
research artifact, none started.

### Superseded 2026-09-21 by @docs/FORECAST_SPEC.md
The ad-hoc roadmap above (steps 1–2 from a Claude Artifact) is now governed
by a formal spec instead: **@docs/FORECAST_SPEC.md**, with its own working
agreement, phase numbering (1–10), and acceptance criteria — read it before
touching `forecasting/`, `datagen/`, or `config/forecast.yaml`. The vendored
`analysis/demand_forecast.py`/`analysis/simulation.py` and
`analysis_bridge.py:build_demand_history()` above are unaffected and still
current; the spec's Phase 4 ("models per segment") is where they get
reused, not replaced.

**Phase 1 (data layer + demand cleaning) — done, verified 2026-09-21.**
Three prerequisites done first, per the spec owner's explicit instruction:
- `datagen/v1/generera_lagerdata.py` — the reference synthetic generator
  (3,000 items/4 years, `facit_dolda_egenskaper.csv` ground truth),
  supplied by David, placed unmodified. Its `OUT_DIR` is a hardcoded
  `/home/claude/lagerdata` path from wherever it was originally written —
  do not edit it to fix this (Phase-1-and-later code should redirect via a
  throwaway copy when it needs to actually run the generator, same as this
  session did to produce `data/demo/`); reworking `OUT_DIR` into a real
  parameter is datagen v2's job (spec section 6), not Phase 1's.
- **Schema migration**: `transactions` gained nullable `po_date`/
  `expected_date` columns (spec Phase 5 needs a real order date to compute
  actual lead time). `schema/tenant.sql` has them for new tenants;
  `db._migrate_tenant_db()` idempotently `ALTER TABLE`s them into existing
  ones on every `get_tenant_conn()` call, verified against a simulated
  pre-migration database (old schema → connect → columns appear, existing
  row untouched, second call is a no-op). `db.record_transaction()` takes
  them as optional kwargs; nothing in the app UI writes them yet (a receive
  form field is a natural fast-follow, deliberately not done here — the
  spec owner asked for exactly three prerequisites, not four).
- **pytest**, scoped to `tests/` only via `pytest.ini` (`requirements-dev.txt`,
  dev-only, pytest pinned there not in production requirements). The
  existing `test_*.py` standalone scripts at the repo root are untouched, a
  deliberate parallel convention, not a migration — `run_tests.sh` runs
  both suites with one command and one exit code.

**Dependency split, also done first:** `requirements-forecast.txt` now
holds `statsforecast`/`scipy`/`numba`/`statsmodels` (moved out of
`requirements.txt`, which stays core-app-only — nothing under `views/`
imports forecasting code yet, so the app must keep running without this
file installed, per the spec's "degrade gracefully" guardrail).
`lightgbm`/conformal-helper deliberately NOT added yet (commented out in
that file) — Phase 1–3 only need pandas/numpy/scipy.

**ARM smoke test: written, deliberately not run.** `scripts/
smoke_test_forecast_deps.sh` (venv install + import + a real scipy.optimize
fit, plus a bonus statsforecast-chain check) exists and is ready, but David
hit friction getting into the Oracle console / SSH access on 2026-09-21 and
asked to skip it rather than debug that now. Decision: fold ARM
verification into the real deployment step instead of a separate
standalone check — installing this app's actual dependencies on the VM
will surface the same pandas/numpy/scipy wheel-availability question
automatically, no extra SSH session needed just to find out early. ARM
compatibility for this dependency chain is still genuinely unverified as
of this note — do not claim it works until the real install happens.

`forecasting/data.py` (loaders for the spec's outbound/inbound/items/stock
CSV contract, a dependency-free Swedish public-holiday calendar via Gauss's
Easter algorithm, `build_demand_series()`) and `forecasting/cleaning.py`
(`flag_censored`/`flag_outliers`/`flag_one_off_large_orders`/
`flag_level_shifts`) are CSV-first against `datagen/`'s synthetic estate,
not DB-first against wms-app's live schema — a live tenant has at most a
few weeks of real history right now, nowhere near enough to develop or
validate a forecasting pipeline against. A live-schema adapter is future
work, same adapter-not-rewrite shape as `analysis_bridge.py`.

**Two real bugs found and fixed while verifying against the full 3,000-item
demo set, not just the small pytest fixture** (`tests/fixtures.py`, 50
items/6 months/fixed seed — generated fresh per test run, never reads
`data/demo/`, per the working agreement):
1. `series.groupby(...).apply(fn)` where `fn` returns a `pd.Series` is
   ambiguous with exactly one group — observed transposing a single
   article's boolean flags into a one-row DataFrame instead of aligning
   them back to the original rows, silently wrong for every single-article
   case. Fixed by replacing every such call in `cleaning.py` with an
   explicit per-group loop + `pd.concat` (`_concat_per_article()`), which
   has no such ambiguity regardless of group count.
2. `flag_level_shifts()` flagged **99.5% of all 3,000 demo articles** at
   least once before a fix — a ratio between two near-zero rolling-window
   means (routine for a low-volume/intermittent article) is noise, not
   signal, and was swinging past the shift threshold on essentially random
   single small orders. Fixed with a `min_window_qty` floor (both windows
   must clear it before a ratio is even computed); rate dropped to 65.5%
   of articles / 9.33% of rows — still not backtest-validated (no ground
   truth to check against until a later phase), reported as a first-pass
   heuristic, not a validated result.

**Real-data numbers** (full demo set, 449,456 outbound lines / 3,000
items, measured on this dev machine): `build_demand_series()` 0.19s → 600,032
article-week rows; `flag_censored` <0.01s, 18,227 lines (4.1%) — the demo
generator's own reported fill rate (~0.96) matches; `flag_outliers` 0.31s,
1,291 rows (0.22%); `flag_one_off_large_orders` 1.52s, 2,671 rows (0.45%);
`flag_level_shifts` 0.84s, 55,964 rows (9.33%, post-fix). Total pipeline
well under the spec's "a few minutes" bound.

**Leakage tests** (`tests/test_leakage.py`, the working agreement's
explicit requirement): `build_demand_series()` and `flag_censored()` are
leakage-safe by construction, proven by shifting-future-data tests, not
just asserted. `flag_level_shifts()` is also safe (strictly backward-
looking rolling windows). `flag_outliers()`/`flag_one_off_large_orders()`
are demonstrated to leak — future data in the same batch can flip a past
period's flag — a real, proven property of using batch median/MAD or
mean/std, documented prominently in `cleaning.py` so Phase 2's backtest
does not reuse a batch run across rolling origins by accident.

**Test count:** 7 standalone scripts + 28 pytest tests, one command
(`./run_tests.sh`), all passing.

**Point-in-time (`as_of`), added 2026-09-21:** every `cleaning.py` function
now takes an optional `as_of` cutoff — filters its input to `period <= as_of`
BEFORE computing anything, so future data literally never enters the
calculation (not "computed on everything, then trimmed"). Proven, not just
implemented: `tests/test_leakage.py` shows `flag_outliers(full, as_of=T)` /
`flag_one_off_large_orders(full, as_of=T)` reproduce the past-only run
exactly. `flag_censored`'s `as_of` differs deliberately — it zeroes out
rows after the cutoff rather than omitting them, keeping the returned
Series aligned with the input's own index (a uniform calling convention
for `backtest.py`, which calls all four the same way). `CALIBRATED_FOR_MODELING`
(a frozenset in `cleaning.py`) marks which flags are safe as model input —
`flag_level_shifts` is deliberately excluded until calibrated against
`datagen` v2 data with injected shifts (see its docstring's "NOT
CALIBRATED" warning); any future generic "build features from every
flag_*" code must check against this constant, not just skip it by
convention.

### Phase 2 (metrics + backtest + baselines) — done, verified 2026-09-21

`forecasting/metrics.py` (WAPE, bias, MASE, pinball loss, interval
coverage — every expected value in `tests/test_metrics.py` independently
verified by direct execution before being written into an assertion, not
hand-derived and trusted). `forecasting/models/baselines.py` (naive,
seasonal naive, moving average, SES) and `forecasting/models/intermittent.py`
(Croston, SBA) — hand-written pure pandas/numpy, deliberately **not** the
statsforecast-based versions already vendored in `analysis/demand_forecast.py`:
Phase 1–3 stays on pandas/numpy/scipy only, per the spec owner's explicit
scope call. `forecasting/backtest.py`: rolling-origin engine, one row per
(article, origin, horizon, model); horizon is both the fixed set (4/13/26
weeks) and a lead-time-aligned one (`lead_time_horizon_periods()`, ceil((lead
time + review period)/period length)) per article. Its own leakage safety
is proven directly (`tests/test_backtest.py`), not inherited by assumption
from `cleaning.py`'s: a huge spike placed after an origin does not change
that origin's forecast.

**Performance tuning, done honestly:** the naive per-origin/per-model
Python loop measured ~8 min for the full 3,000-item demo set at
`origin_step=13` (quarterly origins) — over the spec's "a few minutes"
bound. Profiling showed no single model was the bottleneck (all ~2.7s per
100 articles/1 model, including Croston) — it's loop overhead, not
per-call math. Fixed by widening to `origin_step=26` (semi-annual), a
defensible choice on its own merits, not just a speed hack: ~4 min for the
full set, 472,434 backtest rows, all 6 baselines × 3 horizons.

**Segment classification reused, not reimplemented:** SBC class
(smooth/intermittent/erratic/lumpy) via the already-vendored
`analysis/demand_forecast.py:classify_sbc()`, columns renamed
(`article_id`→`sku`, `qty_ordered`→`qty`) to match its contract — same
"reuse and extend" principle as `build_demand_history()`'s reuse of
`demand_monthly_full`. Distribution across the demo set: lumpy 1,420,
intermittent 1,266, erratic 261, smooth 13, unclassifiable 29, no-demand
11 — this demo estate is overwhelmingly intermittent/lumpy, worth knowing
before reading too much into the smooth segment's small n=73 backtest
rows.

**Baseline results, lead-time-aligned horizon, full demo set** — the
actual per-segment WAPE/bias/pinball-q90/FVA table lives in this session's
chat report to David, not duplicated here; headline findings only:
- SBA wins on WAPE in 3 of 4 segments (smooth/erratic/lumpy); plain moving-average
  wins on the largest segment (intermittent, n=7,813 backtest rows) —
  genuinely counter to `analysis/demand_forecast.py`'s own SBC_METHOD
  routing, which sends intermittent to Croston-SBA. Not a contradiction to
  "fix" reflexively — that routing was never itself backtested (its own
  docstring says so: "a reasoned default, not a backtested one"), so this
  is the first real evidence either way, on synthetic (not real) data.
- WAPE exceeds 1.0 for most segments except smooth (total error exceeds
  total actual demand) — plausible, not obviously broken, for genuinely
  lumpy/intermittent weekly demand at this granularity, but flagged
  explicitly rather than glossed over.
- Pinball loss is NOT comparable across segments (unlike WAPE) — it is not
  scale-normalized, so a high-volume smooth article's absolute pinball
  values dwarf a low-volume intermittent one's. Only meaningful comparing
  models within the same segment.

**Not done / explicitly deferred:** MASE not reported (needs a
scale-consistent in-sample benchmark decision not yet made); category/supplier
segment cuts (only SBC class reported, per what's most relevant to
comparing baseline model fitness); ABC/XYZ segment cuts (Phase 3, not
built); results not persisted to a table/CSV per the spec's Phase 2
suggestion, nor a Streamlit page yet (both explicitly out of scope for
"stop after Phase 2 and report the numbers").

**Not committed.** Phase 2 code, tests, and config changes are sitting
uncommitted, same as everything else in this repo per the standing rule:
never commit without being asked for that specific piece of work.

**ARM smoke test: written, deliberately not run** (see
`scripts/smoke_test_forecast_deps.sh`) — David hit friction with Oracle
console/SSH access on 2026-09-21 and asked to skip it. Decision: fold ARM
verification into the real deployment step instead. Still genuinely
unverified as of this note.

### Phase 3 (segmentation + lifecycle) — done, verified 2026-09-21

`forecasting/segmentation.py:build_segment_table()` — almost entirely
composition of already-vendored, already-tested classifiers, not new
logic: `analysis/data_merge.py:sales_statistics()` for per-article demand
stats (column-renamed sku↔article_id), `analysis/abc_classifier.py`,
`analysis/segmentation.py:classify_xyz/classify_trend`, and
`analysis/demand_forecast.py:classify_sbc()` (via
`forecasting/data.py:build_demand_series()`, already built in Phase 1).
New code here is genuinely small: the adapter/merge logic, plus three
lifecycle flags (`is_new_item`, `is_becoming_obsolete`, `is_stale_with_stock`).

**Validated against `datagen/v1`'s `facit_dolda_egenskaper.csv`
(`tests/test_segmentation_facit.py`) — two of three *(initial)* spec
targets NOT met, investigated and reported honestly rather than tuned to
pass (working agreement: "never claim an improvement without backtest
numbers... if a target is missed, say so plainly"):**

- **ABC agreement 87.7%** vs 90% target — close; real methodology
  difference (facit uses strict trailing-365-day demand value, this
  reuses `sales_statistics()`'s whole-observed-window average, the SAME
  convention `analysis_bridge.py` already uses for the live wms-app
  pipeline — changing it here would diverge from that established
  pattern, not fix a bug). XYZ agreement (not a gated spec metric, but
  measured alongside): 97.8%.
- **Obsolescence recall/precision 72.4%/36.9%** vs 80%/70% targets.
  First pass (`trend_class` alone) was much worse: 90.6% recall but only
  13.9% precision — it fired on 1,326 of 3,000 articles (44%) because a
  routine gap in sporadic ordering looks identical to genuine decline in
  a single recent-vs-prior 3-month window, on this intermittent/lumpy-
  dominated demo set. Added a `days_since_last_movement >= RECENCY_DEAD`
  gate (reusing the exact constant `analysis/segmentation.py` already
  uses for the same "routine gap vs genuinely dead" problem elsewhere,
  not a new arbitrary threshold) — real improvement, still short of
  spec's targets. A properly principled fix is a forecast-based signal
  (`analysis/demand_forecast.py:forecast_dead_stock_risk()`, Phase 4+),
  not further threshold-chasing now — see `flag_obsolescence()`'s
  docstring for the full investigation.
- **New-item recall 0%** vs 95% target — NOT a detector failure.
  `datagen/v1`'s `is_new_item` is a permanent generation-time archetype
  label (10% of articles, `created_date` placed anywhere across the whole
  simulation window) — measured: up to 1,425 days before the dataset's
  own "now", mean ~828 days. No signal derivable from ordinary
  demand/items data can recover a label definitionally decoupled from
  recency. This is a `datagen` v2 item (spec section 6: "new-product
  ramp-up" as a demand PATTERN with actual recency, not just a static
  label) — flagged for whoever revisits that generator, not something to
  fix in segmentation code.

Test assertions pin the MEASURED baseline (with the gap to the original
target documented in comments), not the original spec numbers — a
permanently-red test for a known, already-investigated gap is a worse
signal than a regression guard against further backsliding.

Full test suite: 77 passing (7 standalone + 70 pytest) — 5 new this
phase. Not committed, same standing rule as Phase 2.

### Phase 4 (models per segment, ensemble, global model) — done, verified 2026-09-21

Built: `forecasting/models/statistical.py` (ETS/Theta via statsforecast —
requires `brew install libomp` on macOS for the lightgbm import elsewhere
in this phase, unrelated native-dependency gap, fixed once); TSB and an
empirical bootstrap added to `forecasting/models/intermittent.py`;
`forecasting/models/global_gbm.py` (one LightGBM model trained across the
whole panel per origin/horizon/quantile — lags, rolling stats, Swedish
calendar, category/item attributes; direct multi-horizon quantile
regression, not recursive); `forecasting/backtest.py:run_global_backtest`
(a structurally separate loop from `run_backtest()` — the global model
trains once per origin across every article, which the per-article
`model_fn(train, horizon)` loop cannot express); `forecasting/models/ensemble.py`
(per-segment model selection by pinball-loss@q0.9, plus a plain
equal-weight `combine_forecasts()`).

**Full backtest, honestly reported — Phase 4's acceptance criteria are
NOT met on this demo data (working agreement: "if a target is missed, say
so plainly, investigate, and propose an adjusted target", not tune until
a number looks good):**

Ran all 10 per-article models (Phase 2 baselines + Croston/SBA/TSB/ETS/
Theta/bootstrap) on the full 3,000-item demo set, plus `global_gbm` on a
500-item subset (retraining a panel-wide model at every origin/horizon/
quantile is far more expensive than a per-article statsforecast call — a
500-item subset keeps this runnable in ~1 minute instead of an estimated
tens of minutes; ~27 min total for the full run: 1,571.6s per-article +
62.2s global, 1,587,498 backtest rows). Scored by pinball loss @ q0.9
(the spec's own stated acceptance quantile) per SBC segment vs. best
Phase 2 baseline:

| Segment | Best model | FVA vs best baseline | Spec target |
|---|---|---|---|
| erratic | Croston/SBA/TSB (tied) | **+1.5%** | ≥5% |
| intermittent | moving_average (no Phase 4 model won) | **+0.0%** | ≥3% |
| lumpy | moving_average (no Phase 4 model won) | **+0.0%** | ≥3% |
| smooth | moving_average (global_gbm lost) | **−14.4%** (global_gbm worse) | ≥5% |

None of Phase 4's more sophisticated models beat the Phase 2 baselines by
the spec's margins; two segments show literally zero improvement from any
candidate model over plain `moving_average`.

**A real bug caught and fixed before reporting, not glossed over:** the
first run's printed summary showed global_gbm at **+64.5% FVA on
smooth** — investigated because it looked too good given global_gbm ran
on n=78 rows vs. the baseline's n=668 for that segment. Cause: `smooth`
has only 13 articles in the whole demo set, and the 500-item global
subset happened to contain only 2 of them — the +64.5% was comparing
global_gbm's score on those 2 easy articles against the *full-population*
baseline average across all 13, not a like-for-like comparison. Re-scored
the baseline on the exact same (article, origin, horizon) keys global_gbm
actually predicted: moving_average is *better* there (21.8 vs. 25.0),
i.e. global_gbm actually loses on smooth too (−14.4%, the corrected
number in the table above). `scripts/run_phase4_backtest.py` now always
does this matched-keys comparison, not the original full-population one —
future runs of this script are already fixed, this was not a one-off
manual correction.

**Also observed, not a code bug:** ETS produces a handful of very large
individual errors within the `erratic` segment when an article gets a
genuine one-off huge order (e.g. actual=10,931 vs. forecast≈430 for one
article) — pinball loss @ q90 is asymmetric and penalizes under-predicting
a high quantile heavily, so a few such weeks dominate ETS's segment-average
score (4,939.9 vs. ~29-30 for every other model in that segment). Only
1.0% of ETS's erratic-segment rows have forecast > 1000; this is the
segment's own extreme-tail behaviour showing up in the metric, not ETS
diverging on ordinary data.

**Working theory, not yet tested:** `datagen/v1`'s per-article demand
generator produces something close to a stationary rate with Poisson-ish
noise around it (see its own KONFIGURATION section) — plausible that a
moving average is already close to optimal on data with no real
exploitable trend/seasonal structure per item, and that Croston/SBA/TSB's
and global_gbm's actual edge (if any) would only show up on data with
genuine regime structure: real customer data (Phase 10), or a `datagen`
v2 generator with deliberate trend/seasonality/level-shift patterns per
article (spec section 6). Not investigated further this phase — flagged
as the first thing to check before concluding these methods don't work.

**Not done / explicitly deferred:** global_gbm not run on the full
3,000-item set (see runtime note above); no hyperparameter tuning on
global_gbm (`LGB_PARAMS` in `global_gbm.py` are untuned defaults);
lead-time-aligned horizon not covered by `run_global_backtest` (fixed
horizons only — a shared panel-wide model retrained per distinct
per-article lead time would fragment the training set per origin, judged
not worth the complexity for a Phase 4 baseline; documented in that
function's own docstring).

Full test suite: 104 passing (7 standalone + 97 pytest) — 17 new this
phase (`tests/test_global_gbm.py`, `tests/test_ensemble.py`, plus the TSB/
ETS/Theta/bootstrap additions to `tests/test_models.py`), including a
leakage test that exercises the actual panel-training path (not just
feature engineering) for the global model. Committed
(`1c5fd79`, pushed).

### Phase 5 (probabilistic lead-time demand, conformal calibration) — done, verified 2026-09-21

Built `forecasting/probabilistic.py`: lead-time demand distribution via
Monte Carlo (draw a lead time from its own empirical per-supplier
distribution — `receipt_date - po_date` from `inleverans.csv`, "Open"
lines excluded since they have no observed outcome yet, partial
deliveries KEPT since the time-to-receipt is still real even when the
quantity fell short — bootstrap that many periods of demand from the
article's own recent history, same empirical-bootstrap mechanism
`forecasting/models/intermittent.py:bootstrap_forecast()` already uses
for lumpy demand, sum, repeat 500-1000x, take empirical quantiles), plus
a small hand-written conformal calibration (conformalized quantile
regression, Romano/Patterson/Candes 2019 — the finite-sample-exact
correction-quantile formula, not mapie, per `requirements-forecast.txt`'s
own note that this was always the plan).

**Unlike Phase 4, this phase's results are a genuine win — reported with
the same rigor either way, not oversold either direction:**

`scripts/run_phase5_coverage.py` tests against **real historical PO
receipts**, not synthetic ground truth on both sides: for all 22,018
receivable PO lines with enough article history, predicts the lead-time
demand distribution using ONLY data dated before that PO was placed
(the article's demand history AND the supplier's lead-time sample both
point-in-time filtered — `tests/test_probabilistic.py` proves the
supplier filter specifically, since that one is easy to get wrong), then
checks whether what the article's demand ACTUALLY summed to over that
PO's REALIZED lead time + a 7-day review period fell inside the
predicted interval. Calibration/test split is BY TIME (first 60%
chronologically fits the conformal correction, last 40%, 8,808 events,
is what coverage is reported against) — not a random split, which would
leak "what a typical week looks like" across the boundary.

Nominal 90% interval (q5-q95), against the spec's 87-93% target:

| Segment | Raw coverage | Calibrated coverage | n (test set) |
|---|---|---|---|
| smooth | 87.7% (in range) | 92.1% | 114 |
| erratic | 86.4% (just below) | **92.3%** | 2,012 |
| intermittent | 94.9% (over, not under) | 94.9% (no correction fit) | 2,189 |
| lumpy | 90.4% (in range) | 91.3% | 4,482 |
| **ALL** | **90.6% (in range)** | **91.5%** | 8,808 |

The overall number (90.6% raw, before any calibration) already lands
inside the spec's 87-93% band. Per segment: smooth and lumpy are already
in range raw; erratic is 0.6pp short raw but conformal calibration pulls
it to 92.3%; intermittent OVER-covers (94.9%) rather than under-covers —
exactly the direction the spec's "no systematic under-coverage on
intermittent items" guardrail cares about, so this is a pass on the
guardrail even though it sits above the tight 87-93% band (a wider-than-
strictly-needed interval on intermittent, not a dangerous one). The
conformal correction for intermittent came out at ~0 on the calibration
set, so nothing pulled it back toward the band — worth a closer look
later if a tighter intermittent interval matters operationally, not
urgent given the guardrail itself is satisfied.

**Caveat, stated plainly:** `smooth` has only 13 articles in the whole
demo set (114 test-set events total) — read that row's numbers as a
much smaller-sample result than the other three.

**Also computed, not spec-gated:** the 80% interval (q10-q90) sits
further from its analogous target (75-83% raw across segments,
83% ALL) — the spec only states an explicit target for the 90% case, so
this is reported for completeness, not treated as a miss.

**Not done / explicitly deferred:** `lead_time_demand_distribution()`'s
recent-history bootstrap window (`recent_window=52` weeks) is a fixed
default, not itself backtested against alternatives; the conformal
correction is a single scalar per segment (not conditional on volume or
article-level covariates — full conformalized quantile regression can
condition on more than just the segment, a refinement, not required to
hit this phase's stated accept criterion); Phase 5's `policy.py`
(safety stock / reorder point FROM these quantiles) is Phase 6, not
started.

Full test suite: 118 passing (7 standalone + 111 pytest) — 14 new this
phase (`tests/test_probabilistic.py`), including a leakage test proving a
delivery received after `as_of` cannot appear in the lead-time sample
used to predict at that `as_of`. Not committed, same standing rule as
every phase before it.

### Phase 6 (policy from quantiles) — done, verified 2026-09-21

Built `forecasting/policy.py` (target service level via the newsvendor
critical ratio Cu/(Cu+Co), reorder point = the lead-time demand
distribution's quantile AT that service level, safety stock = that
quantile minus the distribution's MEAN -- reusing Phase 5's Monte Carlo
machinery unchanged rather than a normal-distribution safety-stock
formula that would not fit this intermittent/lumpy-dominated estate;
EOQ-based order quantity, MOQ/order-multiple rounding, always up never
down) and `forecasting/explain.py` (one Swedish paragraph per item,
built entirely from real numbers already computed -- target service
level and why, SBC segment plus coefficient of variation, the
supplier's own observed lead-time spread with its actual sample count,
and the real reorder-point/safety-stock/order-quantity figures -- no
template placeholders, a driver that isn't available is left out of the
sentence rather than faked).

**Margin fallback used for 100% of items, stated plainly, not hidden:**
the demo CSV data contract (`forecasting/data.py`'s `_ITEMS_COLS`) has no
selling-price/margin column at all, so every one of the 3,000 demo items
falls back to the ABC-tier service level (95%/90%/85% for A/B/C -- the
same numbers CLAUDE.md's own "Inventory Analysis Standards" section
already quotes to clients, not invented for this module). A real
customer dataset with margin data would exercise `critical_ratio()`'s
margin-based branch instead -- unit-tested directly
(`test_critical_ratio_hand_computed`, `test_compute_policy_uses_margin_when_available`)
even though nothing in the demo data reaches it.

**Completeness check on the full 3,000-item demo set
(`scripts/run_phase6_policy.py`), the phase's actual accept criterion --
"explanations exist for all items and reference real drivers":**

- **3,000/3,000 items succeeded, 0 errors** -- every item got both a
  policy and a non-empty, driver-referencing explanation (asserted
  directly in the script, not eyeballed).
- ABC service-level split: A=95% (556 items), B=90% (815), C=85%
  (1,629) -- matches the configured tiers exactly.
- Safety stock as a share of expected lead-time demand, by segment:
  smooth 69% (median 67%), erratic 89% (median 84%), lumpy 137% (median
  113%), intermittent 146% (median 126%). Directionally exactly what
  inventory theory predicts -- the more variable/sparse the demand
  pattern, the bigger the safety buffer has to be RELATIVE to the
  expected quantity, and intermittent/lumpy (the segments Phase 3 found
  dominate this estate) need the largest relative buffers of all. A
  sanity check this codebase's own numbers pass, not just a plausible
  story.
- 0/3,000 items fell back to the review-period-only lead-time
  distribution (`n_lead_time_samples < 5`) -- every supplier in the demo
  data has enough delivery history for a real empirical lead-time
  spread, so `MIN_LEAD_TIME_SAMPLES`'s fallback path is unit-tested
  directly rather than exercised on this dataset.

**Not done / explicitly deferred:** `config/forecast.yaml`'s new
`probabilistic:`/`policy:` sections are documented but not actually
wired to a `load_config()` call inside `probabilistic.py`/`policy.py` --
matches every earlier phase's own established pattern (module-level
Python defaults mirror the yaml; nothing in `forecasting/` calls
`load_config()` yet, Phase 1 through 6 alike), not a regression specific
to this phase; a config-loading wire-up is a one-time cross-cutting
change better done once, across every module, than piecemeal here.
Stockout cost as an alternative to margin (spec says "selling margin OR
stockout cost") not implemented -- margin was the more directly available
concept to wire up given the demo data has neither, and a real customer
dataset is far more likely to have a knowable selling price than an
explicit stockout-cost estimate; can be added as a second optional
`critical_ratio()` input later without changing its fallback behaviour.

Full test suite: 140 passing (7 standalone + 133 pytest) — 22 new this
phase (`tests/test_policy.py`, `tests/test_explain.py`). Committed
(`9ef8f91`, pushed).

### Phase 7 (simulation as proof of value) — done, verified 2026-09-21

Built `forecasting/simulate.py`: periodic-review inventory simulation
(weekly, matching every other module's granularity) that replays each
article's REAL historical demand under a reorder-point trigger, applying
demand each period (unfulfilled demand is lost, not backordered),
placing a replenishment when stock crosses the trigger, arriving after a
lead time drawn from that supplier's own empirical distribution.
`compare_policies()` runs policy A (the item's existing ERP
`reorder_point`, already in `artiklar.csv`) and policy B (Phase 6's
quantile-based reorder point) with the SAME order quantity and the SAME
seeded lead-time draw sequence for both -- isolating the one thing this
phase is actually testing (is the trigger point better calibrated) from
everything else (order sizing, lead-time luck) that a naive A/B
comparison could otherwise conflate.

**Full demo set (3,000 items, `scripts/run_phase7_simulation.py`),
demand-weighted:**

| | Fill rate A (ERP) | Fill rate B (Phase 6) | Stock value A | Stock value B |
|---|---|---|---|---|
| **ALL** | 91.8% | **93.4%** | 34.6M SEK | **34.2M SEK** |
| smooth (n=13) | 97.2% | 97.7% | 220k | 219k |
| erratic (n=261) | 90.0% | 92.4% | 9.58M | 9.25M |
| intermittent (n=1,266) | 93.7% | 93.3% | 8.26M | **7.85M** |
| lumpy (n=1,420) | 93.2% | **94.1%** | 16.47M | 16.81M |

Overall, policy B strictly dominates policy A on this demo set -- higher
fill rate AND lower stock value at the same time, not a trade-off,
meeting the spec's Phase 7 accept criterion in its stronger form ("higher
fill rate at equal stock value" undersells this result; B beats A on
both axes at once here). Reported segment-by-segment rather than just
the headline number because the picture is NOT uniform, and pretending
otherwise would violate the working agreement:
- **smooth, erratic**: clean wins, both axes improve.
- **intermittent**: NOT a clean win -- fill rate is very slightly lower
  (93.3% vs 93.7%, −0.4pp) in exchange for meaningfully less stock value
  (−4.9%). A real trade-off, stated as one, not spun as a win.
- **lumpy**: the opposite trade -- higher fill rate (+0.9pp) bought with
  more stock value (+2.1%).

**Service-vs-stock-value frontier**, policy B re-run at fixed service
levels 80/85/90/95/98% (see the script's own docstring for why "the
baselines" in the spec's phrasing is interpreted this way -- Phase 2's
"baselines" were forecast MODELS, a different concept that does not
translate to a policy-level frontier):

| Target | Fill rate | Stock value |
|---|---|---|
| 80% | 91.5% | 25.6M |
| 85% | 92.2% | 28.0M |
| 90% | 93.0% | 31.3M |
| 95% | 93.9% | 36.7M |
| 98% | 94.5% | 43.2M |

Monotonic in both directions as it should be. Policy A (91.8%/34.6M) and
policy B's own mixed-ABC-tier point (93.4%/34.2M) both land where the
curve predicts they should relative to the single-level points around
them -- an internal-consistency check this result passes, not just a
plausible-looking number.

**Stated per the spec's own instruction:** this demo data comes from a
synthetic simulator (`datagen/v1`), so this proves the MACHINERY is
internally correct (a quantile-based trigger genuinely outperforms a
static ERP one when both are tested fairly on the same demand and lead
times) -- it does not prove real-world performance. That is explicitly
Phase 10's job, not claimed here.

**Not done / explicitly deferred:** `n_orders_placed` (ordering
frequency/cost) computed by `simulate_policy()` but not yet rolled into
the portfolio summary printed by the script -- available in
`data/phase7_simulation_results.csv` for a future ordering-cost
comparison, not aggregated here since neither policy's order QUANTITY
differs (only the trigger does, by this phase's own design), so ordering
frequency differences are a secondary effect worth a closer look later,
not the headline result.

Full test suite: 147 passing (7 standalone + 140 pytest) — 7 new this
phase (`tests/test_simulate.py`). Committed (`55ff2c1`, pushed).

### Phase 8 (monitoring and alerts) — done, verified 2026-09-21

Built `forecasting/monitoring.py`: rolling WAPE/bias per (article, model)
over a trailing window of origins, persistent-bias streak detection,
coverage-breach detection (reusing Phase 5's own coverage-event shape),
an obsolescence-risk categorizer (emerging/confirmed/recovering/none --
same four-way shape as the older, superseded
`analysis/demand_forecast.py:forecast_dead_stock_risk()`, reimplemented
against this module's own contracts rather than bridging two
incompatible forecasting engines, see that function's docstring for why),
a simple OR-based auto-retrain trigger, and a manual-override log with
Forecast Value Added of human overrides vs. the model. Adds no new
forecasting logic of its own -- every signal is built from tables Phases
1-5 already produce.

**A real bug caught by investigating a surprising number, same discipline
Phase 3 and Phase 4 already applied -- not glossed over:**

`scripts/run_phase8_monitoring.py` first computed obsolescence risk using
`naive_forecast` (repeats the last observed value) as the "fresh
forecast" -- for the intermittent/lumpy demand dominating this estate,
naive is 0 after any single empty period, which is routine, not a risk
signal. Result: 1,657/3,000 articles (55%) flagged "emerging" risk --
implausibly high, investigated rather than reported as-is. Root cause:
the EXACT same false-positive trap Phase 3's `flag_obsolescence()`
docstring already documents in detail (trend_class alone flagging 44% of
articles before a recency gate fixed it) -- a routine gap in sporadic
ordering looking identical to genuine decline. Fix: swap in TSB
(`forecasting/models/intermittent.py:tsb_forecast`), which was
specifically built in Phase 4 to decay gracefully rather than flip to
zero on a routine gap -- the right already-built tool, not a new
invented threshold. Corrected result: **623/3,000 (21%) flagged
"emerging"**, a 62% reduction, with "confirmed" (398→396) essentially
unchanged as expected (it is already gated by Phase 3's own
`is_becoming_obsolete`, which has its own recency gate) -- consistent
with a real fix, not a cosmetic one.

**Two signals reported honestly as over-sensitive at their DEFAULT
thresholds on this dataset, not silently tuned without a way to validate
the tuning:**
- **Persistent bias** (`bias_threshold=0.20`, `min_consecutive=3` on
  `moving_average`'s own 4-week-horizon backtest rows): flags **2,149 of
  2,981 articles (72%)**. Investigated the underlying numbers directly
  (not assumed) -- this is NOT a near-zero-denominator artifact (actual
  demand in the sampled flagged article ranges 1-46, not near zero); it
  is that a 20% relative-bias threshold over only ~13-14 quarterly-ish
  origins is simply very easy to cross by sampling noise alone on demand
  this volatile (the erratic/lumpy segments Phase 3 already measured as
  dominant here). Unlike Phase 3's obsolescence flag, there is no facit
  to calibrate a better threshold against -- reported as "too sensitive
  to use as-is at these defaults, needs real per-segment tuning before
  deployment" rather than picking a new number with nothing to validate
  it against.
- **Demand shift**: reuses Phase 1's `flag_level_shifts` unchanged,
  which is already explicitly documented as "NOT CALIBRATED... first-pass
  heuristic for human review only" in its own docstring. Flags 1,966/3,000
  (66%) here -- a known, already-documented limitation surfacing again in
  a new context, not a new problem introduced by this phase.
- **Coverage breach**: 0 segments flagged at the ±5-percentage-point
  operational tolerance used here (vs. Phase 5's tighter 87-93% research
  band) -- `erratic`'s 86.4% raw coverage (just under Phase 5's tighter
  band) still falls inside this wider, deliberately more lenient
  operational tolerance, so it does not fire an alert. Consistent with
  Phase 5's own numbers, not a contradiction -- a monitoring alert and a
  research acceptance criterion are allowed different tolerances on
  purpose (an alert firing on every minor statistical wobble would be
  useless in practice).

**Manual override FVA**: no real override history exists in the demo
data (nothing has ever overridden a forecast), so this is demonstrated
with two constructed examples rather than backtested -- one override that
genuinely improved on the model (FVA +20) and one that made things worse
(FVA −20), both directions shown deliberately, not just the flattering
one.

**Not done / explicitly deferred:** `should_retrain()`'s three inputs are
combined with a plain OR, not a weighted score (stated as a deliberate,
simple choice in the function's own docstring, not a placeholder);
override log is an in-memory list of dicts, not wired to a persistent
table -- forecasting/ has no database layer of its own (see
forecasting/data.py's docstring), a live override log against wms-app's
SQLite tenant schema is a separate adapter for whoever builds the
Streamlit alerts page (Phase 9), not built here.

Full test suite: 167 passing (7 standalone + 160 pytest) — 20 new this
phase (`tests/test_monitoring.py`). Not committed yet, same standing
rule as every phase before it.

### Phase 9 (Streamlit pages) — done, verified 2026-09-21

Built `views/forecast_demo.py` (all 6 spec tabs: Overview, Item view,
Backtest by segment, Policy & frontier, Alerts, Data quality), wired into
`app.py`'s router and `components/i18n.py`'s sv/en strings, same
`render(user)` pattern every other page already follows. Deliberately
shows the SYNTHETIC demo dataset, not the logged-in company's own tenant
data -- forecasting/ has stayed CSV-first through every phase (see
forecasting/data.py's own docstring), a live-tenant adapter is Phase 10
territory, and the page says so explicitly in its own caption rather than
implying it is showing the company's real numbers.

Heavy intermediate files (Phase 4's backtest results alone are ~155MB)
are precomputed ONCE by `scripts/prepare_phase9_artifacts.py` into small
summary files under `data/phase9/` -- the live page never loads the big
files, only the "Item view" tab computes anything on the fly (one
article's own forecast, cheap).

**Two real bugs caught by actually clicking through the page in a
browser, not just checking it imports without error** (this is why "run
it and look" matters, not just "does the code parse"):

1. **Model name shown didn't match the model actually used.** The Item
   view's model registry (`MODELS` dict) was missing `seasonal_naive_forecast`
   -- when a segment's Phase 4 backtest winner was `seasonal_naive`, the
   page silently substituted `moving_average` while the caption still
   said "seasonal_naive". Fixed by registering the missing model AND
   adding explicit fallback-aware captioning (`FALLBACK_MODEL` +
   `forecast.item_forecast_caption_fallback`) for the one case that
   genuinely can't run live: `global_gbm` needs a panel-wide retrain per
   origin (see Phase 4's `run_global_backtest` docstring), so the page
   now says outright "the backtest winner needs the whole panel, showing
   X instead" rather than quietly showing a different model under the
   winner's name.
2. **The "best model per segment" itself was NON-DETERMINISTIC.** Several
   baselines tie EXACTLY on this demo data (`naive`/`moving_average`/
   `seasonal_naive`/`ses` all score 4.520776 on the lumpy segment -- a
   real, already-documented Phase 4 finding, not a rare edge case).
   `select_best_model_per_segment()`'s `sort_values()` used pandas'
   default (non-stable) sort, so which of the four tied models "won" and
   got displayed depended on incidental row order, not on any real
   difference in score -- reproduced live: the Backtest tab and the Item
   view disagreed on lumpy's winner across two page loads of the exact
   same underlying data. Fixed in `forecasting/models/ensemble.py` with
   an explicit alphabetical tie-break
   (`sort_values([loss_col, "model"], kind="stable")`) and a new
   regression test that checks two different input row orderings resolve
   to the same winner. This was a real reproducibility bug in code that
   had been sitting since Phase 4 -- undetected until a UI actually
   displayed the value to a human across multiple loads.

A third, smaller inconsistency was also caught and fixed the same way:
the Policy & frontier tab's comparison table computed a plain per-item
`mean()` fill rate, which silently gives a DIFFERENT number than the
demand-weighted average CLAUDE.md's own Phase 7 section already reports
for the same segments -- fixed to demand-weight identically, so the page
now agrees with itself.

**Not done / explicitly deferred:** no live wiring to a real tenant's own
SQLite data (explicitly Phase 10, per forecasting/data.py's own scope);
the manual-override/FVA mechanism from Phase 8 is not exposed in the UI
(no real override history exists to show yet); alerts are a fixed
500-item sample, not the full 3,000 (matches Phase 8's own script scope).

No new tests this phase specifically for `views/forecast_demo.py` (a
Streamlit page under `st.tabs`/`st.altair_chart` is not unit-testable the
way the rest of forecasting/ is -- verified instead by actually running
the app and clicking through all 6 tabs plus the sv/en toggle, per this
session's own "run it in a browser before calling it done" standard);
`forecasting/models/ensemble.py`'s tie-break fix DOES have a new
regression test. Full test suite: 168 passing (7 standalone + 161
pytest). Committed (`06455a9`, pushed).

### Phase 10 (validation on real data) — done, verified 2026-09-21

Chose the M3 competition dataset (Makridakis & Hibon 2000) over M5
(several GB, far heavier) and over `carparts` (the spec's own suggested
intermittent-demand alternative -- not available without either
installing an unvetted third-party package or guessing at a URL, and the
user picked M3 explicitly when asked). Downloaded directly via `curl`
from Zenodo (`data/m3/m3_monthly_dataset.zip`, ~330KB, a specific real
URL read out of the `datasetsforecast` PyPI package's own source rather
than invented) after `pip install datasetsforecast` was itself blocked by
the session's auto-mode classifier as an unvetted-package supply-chain
risk -- avoided entirely by writing a ~50-line self-contained `.tsf`
parser (`forecasting/datasets/m3.py`) instead of taking the dependency.

**Scope stated honestly up front, not discovered as a surprise
afterward:** M3 is a bare (series, date, value) benchmark with no items/
inbound/lead-time/stock data at all. Only Phases 2-4 (forecasting
accuracy + SBC segmentation) can be validated against it --
`scripts/run_phase10_m3_validation.py` says so in its own docstring and
its own printed output. Phases 5-7 need real PO/lead-time data this
dataset does not have; genuinely out of scope, not a gap in the script.
`global_gbm` also skipped -- its value is pooling across item attributes
(category, cost, lead time) M3 doesn't provide either.

**This is the result that finally tests Phase 4's own "working theory"
directly, not just repeats it:** Phase 4's report speculated that the
synthetic demo data might be too close to stationary noise for advanced
models to show any real edge over `moving_average`, and proposed testing
that on real data as "the first thing to check before concluding these
methods don't work." M3 is exactly that test, and the result is a clean,
strong confirmation:

| Segment | Best model | FVA vs best baseline | (Phase 4's synthetic-data FVA, for comparison) |
|---|---|---|---|
| erratic (n=35 series) | theta | **+19.5%** | +1.5% |
| smooth (n=1,392 series) | theta | **+42.2%** | (not a real segment on the synthetic set) |

Theta wins BOTH real segments decisively -- not a coincidence: Theta
(Assimakopoulos & Nikolopoulos 2000) was one of the strongest performers
in the ORIGINAL M3 competition itself, so a Theta win on M3 specifically
is closer to an expected textbook result than a lucky roll, a genuine
sanity check this codebase's pipeline passes. The near-total absence of
intermittent/lumpy series (1,392 smooth + 35 erratic out of 1,427, vs.
the demo set's lumpy/intermittent-dominated mix) reflects M3's own real
domain mix (demographic/micro/macro/industry/finance series, mostly
regular monthly values) rather than anything about the pipeline.

**A real bug found and fixed BECAUSE this was real data, not synthetic
data with bounded, generator-controlled variance:** the first run showed
`ets`'s pinball loss at 1,559,473 in the erratic segment -- roughly 1,000x
every other model. Investigated directly (not assumed): a specific
series' AutoETS-derived q90 quantile reached 1.7e10 against a training
series that never exceeded ~13,000 and a point forecast near 2,450 --
AutoETS's own internal variance estimate genuinely blowing up on that
series, not an arithmetic bug in `forecasting/models/statistical.py`'s
wrapper, but not a usable number for anything downstream either (a
`policy.py` reorder point inheriting a 17-billion-unit quantile would be
absurd). Fixed with `SANITY_BOUND_MULTIPLIER` (caps every quantile at
20x the largest value ever observed in training) and a regression test
reproducing the exact numbers found. Corrected result: `ets`'s
erratic-segment pinball loss dropped to 1,861.87 -- back in the same
ballpark as every other model, Theta's own numbers unaffected (the bug
was ETS-specific). This is exactly the kind of finding synthetic data,
bounded by its own generator's own parameters, was never going to
surface -- real data's job in this phase, working as intended.

Full test suite: 176 passing (7 standalone + 169 pytest) — 8 new this
phase (4 in `tests/test_m3_loader.py`, 4 new `_clip_to_sane_bound` tests
in `tests/test_models.py`). Committed (`d0ed8ef`, pushed) — the
FORECAST_SPEC.md-numbered phases (1-10) are now all done, with all ten
committed and pushed.

### Live-tenant adapter (`forecasting/data_wms.py`) — done, verified 2026-09-21

Not a FORECAST_SPEC.md-numbered phase -- the spec's own Phase 1-10 plan
never named this step, but every phase's docstring (from Phase 1 onward)
flagged the same gap: forecasting/ stayed CSV-first against `datagen/v1`
synthetic data the whole way through, and "a loader for wms-app's live
SQLite tenant schema is a natural, separate adapter to add once a tenant
has enough history to be worth forecasting" (forecasting/data.py's own
words). Testbolaget AB's demo tenant (400 items, 3 years of generated
history, see the wms-app demo-data section above) is exactly that --
enough history to be worth it -- so this wires it up.

`forecasting/data_wms.py` maps wms-app's live SQLite tables (`items`,
`orders`/`order_lines`, `transactions`, `stock`) onto the EXACT column
shapes `forecasting/data.py`'s CSV loaders already produce, so every
downstream function (`build_demand_series`, `build_segment_table`,
`run_backtest`, `build_supplier_lead_time_table`, `compute_policy`,
`simulate_policy`, `forecasting/monitoring.py`) runs unmodified against a
real tenant's own data -- zero changes needed to any file Phases 1-8
already built. Real gaps in the live schema, stated in the adapter's own
docstring rather than silently faked: no separate ordered-vs-received
quantity for inbound receipts (qty_ordered = qty_received, since the live
schema has no PO-line concept at all), and no reorder_point/safety_stock/
moq/order_multiple columns on the live items table (defaults: moq=1,
order_multiple=1, reorder_point=safety_stock=0) -- which in turn means
Phase 7's "policy A vs policy B" comparison has no real policy A to
compare against for a wms-app tenant; the live Streamlit page says so
rather than fabricating one.

`views/forecast_live.py` -- same 6 tabs as the demo page
(`views/forecast_demo.py`), but computed LIVE per tenant rather than from
precomputed files: at a few hundred items (not 3,000), the full
10-model backtest takes ~60s (`st.cache_data`-cached per session, so
only the first tab visit pays that cost, confirmed live: the second
visit to a cached tab was instant). The Policy & frontier tab shows only
the frontier curve, not a policy-A comparison, per the gap above.

**Two real bugs caught by actually clicking through in a browser against
Testbolaget AB's real data, not by reading the code** -- both were
literal copy-paste survivors from `views/forecast_demo.py`'s i18n
strings, which hardcode "500 artiklar"/"hela demodatan" because that
page's own artifacts really are a fixed 500-item alert sample and the
full demo set. Reused verbatim in the live page, both captions were
simply FALSE there (Testbolaget AB has 400 items total, no 500-item
sample, and it is not "the demo dataset"). Fixed with two new,
count-aware keys (`forecast.live_alerts_header`, `forecast.live_quality_header`)
instead of the shared demo-page ones. A worthwhile reminder that reusing
UI copy across two data sources needs the same scrutiny as reusing code
-- a string that is accurate in one context can be silently wrong in
another.

Full test suite: 182 passing (7 standalone + 175 pytest) — 6 new
(`tests/test_data_wms.py`, using a real throwaway tenant DB, same pattern
`test_db.py` already established, not a mocked path). Committed
(`4ec4dc2`, pushed).

### Live-page UX simplification — done, verified 2026-09-21

User feedback after actually testing `views/forecast_live.py` against
Testbolaget AB in a browser: "det är svårt att förstå prognosen för en
användare, det måste bli lättare eller enklare" -- confirmed the
"användare" in question is a CLIENT'S OWN staff (e.g. an inköpschef),
not David himself. The page as built for Phase 9 was written for
someone validating the forecasting engine (pinball loss, ADI/CV² class,
model names, raw quantile-labeled charts) -- exactly wrong for the
actual target audience CLAUDE.md's own "Målgrupp" section names
(non-technical SME purchasing/operations staff).

Added a new, FIRST/default tab, "Beställningsförslag" (Order
recommendations): one row per article -- current stock, reorder point,
suggested order quantity, and a traffic-light status (🔴 Beställ nu /
🟡 Beställ snart / 🟢 OK, sorted most-urgent-first) -- zero model names,
zero statistical terms anywhere in this table. A "Varför?" picker below
it surfaces `forecasting/explain.py`'s existing plain-Swedish paragraph
per article (that function was already fine; nothing needed to change
there, this was a presentation problem, not a content problem).

Simplified the existing "Artikelvy" tab rather than replacing it:
- Forecast-fan chart: y-axis was auto-labeled "q5, q95, q10, q90, q50" by
  Altair (the literal field names) -- now explicitly titled "Antal".
  Header changed from "Prognosfläkt (kvantiler)" to "Vad kan hända
  framöver?", with a one-line plain-language caption replacing the
  headline model-name caption. The model name itself moved into a
  collapsed "Teknisk detalj" expander -- still available, not deleted,
  just not the first thing a non-technical reader sees.
- "Policy (Fas 6)" header (literal internal phase-numbering jargon) ->
  "Rekommendation för denna artikel".
- Alerts tab: `type`/`severity` columns were raw English identifiers
  (`persistent_bias`, `warning`) from `forecasting/monitoring.py`'s own
  internal alert-dict keys -- translated to plain Swedish/English at the
  UI boundary (`ALERT_TYPE_LABELS`/`ALERT_SEVERITY_LABELS` in
  `views/forecast_live.py`), same principle `components/sv.py` already
  applies for the vendored `analysis/` modules' English status values.

The four remaining tabs (Backtest per segment, Policy & frontier, Larm,
Datakvalitet) are left as-is, deliberately -- they are genuinely for
validating/monitoring the engine, a real (if secondary) audience this
session already confirmed exists. Each now carries an explicit caption
("Den här fliken är till för uppföljning/validering... inte för dagliga
beställningsbeslut") so a non-technical user who wanders in knows they've
left the simple view, rather than being confused by pinball-loss numbers
with no explanation.

Not backported to `views/forecast_demo.py` -- that page's own caption
already states its audience is David himself exploring the synthetic
demo estate, not a client's staff; the same simplification would be
worth doing if that page's audience ever changes, not assumed needed now.

No new automated tests this round (a UI copy/layout change, not new
logic -- `forecasting/explain.py` and `forecasting/policy.py`, which
`_compute_order_recommendations()` calls unchanged, already have their
own test coverage from Phase 6). Verified by running the app and
clicking through both the order-recommendations table and the simplified
item view against Testbolaget AB's real data.

### Live-page second simplification pass — done, verified 2026-09-22

Follow-up in the same session: after the first pass above, David pointed
at a Power BI/Aimplan dashboard screenshot as a reference for "this is
much simpler" -- the gap was not jargon this time (that was already
fixed), it was sheer TEXT VOLUME. Every KPI on the page was still wrapped
in a full sentence or a caption underneath it, where the reference image
had none of that: just numbers in tiles and clean charts, no narration.

Replaced the single dense Swedish paragraph (still the output of
`forecasting/explain.py:explain_policy()`, itself unchanged) with a row
of plain `st.metric()` tiles -- Beställningspunkt, Säkerhetslager,
Orderkvantitet, Målservicenivå, Ledtid -- in both the new order-
recommendations tab and the item-detail tab (`_render_policy_kpis()`,
one shared helper, not duplicated). The full sentence is still there,
just moved into a collapsed "Läs mer" expander for whoever wants the
prose reasoning rather than just the numbers.

Also cut caption text that was explaining the page to itself rather than
to the user: the forecast-fan chart's caption sentence removed (the
tiles now speak for themselves); the page's own top-level caption
shortened from a two-sentence paragraph that literally named a source
file ("Se CLAUDE.md \"forecasting/data_wms.py\" för vilka fält...") down
to one line ("Baserat på {company}s egna lagerdata.") -- a client's own
staff has no reason to be pointed at this repository's internal
documentation.

Same "leave the four analytical tabs alone" decision as the first pass --
this round only touched the two tabs a non-technical user actually
works from.

## Deployment (milestone 4 — in progress)

Target: **0 kr/month.** Oracle Cloud "Always Free" ARM VPS (not Streamlit
Cloud — it has no persistent disk, and this app's whole point is to own a
disk-backed database) + the subdomain `wms.barisab.com` (David already owns
`barisab.com`) + Caddy for free automatic HTTPS. Fallback if Oracle's free
tier is hard to provision: Hetzner CX22 (~4.5 EUR/month). Full detail in the
plan file's "Drift" section, including the daily SQLite `.backup` + rclone
cron plan — do not skip backups when building milestone 4, a VPS disk
failure with no backup is total data loss for every tenant.

## Status

- **Milestone 1 (foundations) — done, verified 2026-09-16.** Registration,
  login, per-tenant DB creation/isolation, item/location CRUD, stock view,
  manual stock adjustment with insufficient-stock rejection — all tested
  through both a scripted DB-layer check and a live browser walkthrough.
- **Milestone 2 (receive/pick/orders with barcode scanning) — done, verified
  2026-09-16.** `views/receive.py`, `views/orders.py`, `views/pick.py`,
  `components/barcode_input.py`, `components/flash.py`. Full lifecycle
  tested live in the browser: receive 200 units (dock ≠ putaway location, so
  both a `receive` and a `putaway` transaction fire), create an order with a
  line, partial pick (25) confirms order status flips `open → picking`, the
  final pick (35) auto-flips `picking → packed`, "Markera som skickad" flips
  `packed → shipped`, and the stock view lands on the correct final balance
  (140 = 200 − 60). Also confirmed a barcode scan resolves to the correct
  open order line and pre-fills the confirm quantity to whatever remains.
- **Milestone 3 (IHA integration) — done, verified 2026-09-16.** See "IHA
  integration" above for the full verification detail.
- **Milestone 4 (deployment) — in progress, started 2026-09-18.** Oracle
  Cloud Free Tier account created, `wms-app` Ampere A1 (VM.Standard.A1.Flex,
  Always Free-eligible) instance being provisioned in Sweden Central
  (Stockholm) — David working through the Networking/SSH-key steps of the
  console wizard directly. Not yet reached: instance running, app installed,
  DNS (`wms.barisab.com`) pointed at it, HTTPS via Caddy.
- **Demand forecasting — steps 1–2 of the roadmap done, 2026-09-20.** See
  "Demand forecasting engine" above. Vendored engine + the new
  `build_demand_history()` bridge, verified with a real end-to-end test —
  not yet exposed as an app page.

## Barcode scanning (milestone 2 — built)

No camera code. `components/barcode_input.py:barcode_scan_form()` is a
single-widget `st.form` — Streamlit auto-submits a form on Enter when it has
exactly one input, which is exactly what a USB/Bluetooth scanner sends after
typing the code, so no JS glue was needed. `db.find_item_by_code()` resolves
either a barcode or a bare SKU, since an operator can also type one by hand.

Both receive.py and pick.py use the same two-step shape: a scan only ever
identifies a match and stashes it in `st.session_state` (`receive_pending` /
`pick_pending`); the actual `db.record_transaction()` call only happens
after an explicit qty confirmation, so a mis-scan can never move stock by
itself. `components/flash.py` carries a success/error message across the
`st.rerun()` that step needs, since a bare `st.success()` right before rerun
never reaches the user otherwise — this pattern is shared by both pages and
will be needed again in milestone 3 if reports get a similar interaction.
