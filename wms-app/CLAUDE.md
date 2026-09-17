# CLAUDE.md — WMS-app

Multi-tenant warehouse management system with SQLite as the system of
record, built for David's SME logistics-consulting clients. Full plan and
rationale: `/Users/davidleifsson/.claude/plans/deep-tumbling-lagoon.md`.

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

## All UI text in Swedish (built 2026-09-17)

On request: every English string a user could actually see was found and
translated. The vendored `analysis/*.py` files have English column names,
status values, and prose baked in (that's the source, unchanged per the
vendoring rule above) — so translation happens in **`components/sv.py`**,
one layer between the analysis output and `st.dataframe`/`st.error`/etc.,
never inside `analysis/*.py` itself:

- `STATUS_LABELS`, `STATUS_REASON_LABELS`, `TREND_LABELS`,
  `ORDER_STATUS_LABELS`, `POLICY_LABELS`, `ROOT_CAUSE_LABELS` /
  `ROOT_CAUSE_ACTIONS` — value-translation dicts, applied with
  `.map(...).fillna(original)` so an unmapped value degrades to the raw
  value instead of `NaN`.
- `COLUMN_LABELS` + `rename_columns(df)` — one shared header-rename map
  applied to every `st.dataframe()`/`excel_download_button()` call
  app-wide (`views/items.py`, `stock.py`, `orders.py`, `pick.py`,
  `transfer.py`, `iha_report.py`). Unknown columns pass through
  untouched, so it's safe to apply blindly rather than enumerating each
  table's exact columns.
- `supplier_flags_sv()` — a parallel Swedish reimplementation of
  `lead_time.supplier_flags()`, not a wrapper around it (the source
  returns English sentences, not translatable fragments). Imports
  `CONCENTRATION_LIMIT`/`ON_TIME_TARGET` from the vendored file so the
  trigger thresholds can't drift between the two.
- `translate_demand_note()` — regex-based, because `data_merge.py`'s
  `sales_statistics()` returns a free-text English note, not a structured
  value. Only handles the two note shapes reachable from wms-app's
  SQL-fed pipeline (`sales_statistics()`'s "wide format" shape is
  unreachable here — see analysis_bridge.py). Falls back to the raw
  string, untranslated, if the vendored wording ever changes and the
  regex stops matching — a silent pass-through was judged better than a
  crash for a caption line.
- `db.py`'s `record_transaction`/`_adjust_stock` `ValueError` messages
  (e.g. "Otillräckligt saldo: ...") were translated directly at the
  source, not through the sv.py layer — `db.py` isn't a vendored file,
  nothing stops editing it directly. No test asserts on the exact message
  text, only `except ValueError`, so this was safe to change freely.

**Verified, not just "translated and hoped":** `test_analysis_bridge.py`
asserts `supplier_flags_sv()` produces the Swedish concentration-risk
flag (and *not* the English one) and that `translate_demand_note()`
actually transforms a real note produced by `build_canonical()` rather
than silently no-op'ing. Live browser walkthrough confirmed Swedish text
in: item table headers/values, root-cause expanders, ABC×XYZ policy
column, supplier analysis table + warning banner, order status column,
and the `Otillräckligt saldo` error message triggered through the real
Saldojustering form (not just read from source).

**Deliberately still not done** (flagged to David, not started): demand
forecasting (`demand_forecast.py` — heavy scipy/numba/statsmodels/statsforecast
chain, the exact stack behind a real Streamlit Cloud incident documented in
`iha-saas/CLAUDE.md`). PDF/PPT export not started either; PPT in particular
is a substantial module in `iha-saas` (915 lines/39 functions with
matplotlib-rendered charts), not a quick add.

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

## Deployment (not yet built — milestone 4)

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
- **Milestone 4 (deployment) — not started.** Needs David to create the
  Oracle Cloud account himself (requires a card at signup, even though free)
  and confirm where `barisab.com` DNS is managed before this can proceed.

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
