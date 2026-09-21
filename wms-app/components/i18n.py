"""UI-string translations (Swedish/English) for everything that is not a
data-driven label already covered by components/sv.py's COLUMN_LABELS/
STATUS_LABELS family (nav items, buttons, form labels, messages).

One flat key -> {"sv": ..., "en": ...} dict, so both translations for a
given string sit next to each other -- missing one language for a key is
easy to spot on read instead of drifting apart in two parallel files.

Language is stored in st.session_state, not the URL or a cookie: this app
has no server-side routing, and a per-session toggle is enough for one
operator at one terminal (same tradeoff already made for login sessions,
see auth.py's docstring)."""

from __future__ import annotations

import streamlit as st

DEFAULT_LANG = "sv"
LANGUAGES = {"sv": "Svenska", "en": "English"}

STRINGS: dict[str, dict[str, str]] = {
    # ── Navigation ───────────────────────────────────────────────────────
    "nav.items": {"sv": "Artiklar & platser", "en": "Items & locations"},
    "nav.import": {"sv": "Importera", "en": "Import"},
    "nav.stock": {"sv": "Lagersaldo", "en": "Stock"},
    "nav.receive": {"sv": "Ta emot", "en": "Receive"},
    "nav.transfer": {"sv": "Flytta", "en": "Transfer"},
    "nav.orders": {"sv": "Ordrar", "en": "Orders"},
    "nav.pick": {"sv": "Plocka", "en": "Pick"},
    "nav.reorder": {"sv": "Påfyllning", "en": "Replenishment"},
    "nav.iha": {"sv": "IHA-rapport", "en": "IHA report"},
    "nav.forecast_demo": {"sv": "Prognosmotor (demo)", "en": "Forecasting engine (demo)"},
    "nav.forecast_live": {"sv": "Prognosmotor", "en": "Forecasting engine"},

    # ── app.py: login / register / sidebar chrome ───────────────────────
    "app.brand": {"sv": "📦 WMS", "en": "📦 WMS"},
    "app.login_tab": {"sv": "Logga in", "en": "Log in"},
    "app.register_tab": {"sv": "Registrera företag", "en": "Register company"},
    "app.email_label": {"sv": "E-post", "en": "Email"},
    "app.password_label": {"sv": "Lösenord", "en": "Password"},
    "app.login_button": {"sv": "Logga in", "en": "Log in"},
    "app.company_name_label": {"sv": "Företagsnamn", "en": "Company name"},
    "app.password_register_label": {
        "sv": "Lösenord (minst 8 tecken)", "en": "Password (at least 8 characters)",
    },
    "app.register_button": {"sv": "Skapa konto", "en": "Create account"},
    "app.company_name_required_error": {
        "sv": "Ange ett företagsnamn.", "en": "Enter a company name.",
    },
    "app.register_success": {
        "sv": "Klart! Databas skapad för {name}.", "en": "Done! Database created for {name}.",
    },
    "app.menu_label": {"sv": "Meny", "en": "Menu"},
    "app.language_label": {"sv": "Språk", "en": "Language"},
    "app.logout_button": {"sv": "Logga ut", "en": "Log out"},

    # ── auth.py ──────────────────────────────────────────────────────────
    "auth.password_too_short": {
        "sv": "Lösenordet måste vara minst {n} tecken.",
        "en": "Password must be at least {n} characters.",
    },
    "auth.password_common": {
        "sv": "Det lösenordet finns på varje angripares gissningslista — välj ett annat.",
        "en": "That password is on every attacker's first-guess list — pick another.",
    },
    "auth.password_contains_email": {
        "sv": "Lösenordet får inte innehålla din e-postadress.",
        "en": "Password must not contain your email address.",
    },
    "auth.email_exists": {
        "sv": "Det finns redan ett konto med den här e-postadressen.",
        "en": "An account with this email already exists.",
    },
    "auth.login_failed": {
        "sv": "Fel e-post eller lösenord.", "en": "Incorrect email or password.",
    },

    # ── db.py ────────────────────────────────────────────────────────────
    "db.insufficient_stock": {
        "sv": "Otillräckligt saldo: {sku} på {location} har {have}, kan inte ta bort {delta}",
        "en": "Insufficient stock: {sku} at {location} has {have}, cannot remove {delta}",
    },

    # ── Shared across several pages ─────────────────────────────────────
    "common.cancel": {"sv": "Avbryt", "en": "Cancel"},
    "common.item_not_found": {
        "sv": "Ingen artikel hittades för '{code}'.", "en": "No item found for '{code}'.",
    },
    "common.no_description": {"sv": "(ingen beskrivning)", "en": "(no description)"},
    "common.need_items_locations": {
        "sv": "Lägg till minst en artikel och en lagerplats under 'Artiklar & platser' först.",
        "en": "Add at least one item and one location under 'Items & locations' first.",
    },
    "common.need_items": {
        "sv": "Lägg till artiklar under 'Artiklar & platser' först.",
        "en": "Add items under 'Items & locations' first.",
    },
    "common.no_txns": {
        "sv": "Inga transaktioner registrerade ännu. Ta emot eller plocka något "
              "under 'Ta emot' / 'Plocka' för att analysen ska ha något att räkna på.",
        "en": "No transactions recorded yet. Receive or pick something under "
              "'Receive' / 'Pick' so the analysis has something to work with.",
    },

    # ── views/items.py ───────────────────────────────────────────────────
    "items.page_title": {"sv": "Artiklar & platser", "en": "Items & locations"},
    "items.tab_items": {"sv": "Artiklar", "en": "Items"},
    "items.tab_locations": {"sv": "Lagerplatser", "en": "Locations"},
    "items.add_item_header": {"sv": "Lägg till artikel", "en": "Add item"},
    "items.sku_label": {"sv": "SKU *", "en": "SKU *"},
    "items.barcode_label": {"sv": "Streckkod", "en": "Barcode"},
    "items.description_label": {"sv": "Beskrivning", "en": "Description"},
    "items.unit_cost_label": {"sv": "Enhetskostnad", "en": "Unit cost"},
    "items.currency_label": {"sv": "Valuta", "en": "Currency"},
    "items.lead_time_label": {"sv": "Ledtid (dagar)", "en": "Lead time (days)"},
    "items.supplier_label": {"sv": "Leverantör", "en": "Supplier"},
    "items.category_label": {"sv": "Kategori", "en": "Category"},
    "items.save_item_button": {"sv": "Spara artikel", "en": "Save item"},
    "items.sku_required_error": {"sv": "SKU krävs.", "en": "SKU is required."},
    "items.item_saved": {"sv": "Artikel {sku} sparad.", "en": "Item {sku} saved."},
    "items.save_failed": {"sv": "Kunde inte spara: {error}", "en": "Could not save: {error}"},
    "items.items_header": {"sv": "Artiklar", "en": "Items"},
    "items.items_count": {"sv": "{n} artiklar", "en": "{n} items"},
    "items.add_location_header": {"sv": "Lägg till lagerplats", "en": "Add location"},
    "items.location_code_label": {
        "sv": "Platskod * (t.ex. A-01-03)", "en": "Location code * (e.g. A-01-03)",
    },
    "items.zone_label": {"sv": "Zon", "en": "Zone"},
    "items.type_label": {"sv": "Typ", "en": "Type"},
    "items.save_location_button": {"sv": "Spara plats", "en": "Save location"},
    "items.location_code_required_error": {
        "sv": "Platskod krävs.", "en": "Location code is required.",
    },
    "items.location_saved": {"sv": "Plats {code} sparad.", "en": "Location {code} saved."},
    "items.locations_header": {"sv": "Lagerplatser", "en": "Locations"},
    "items.locations_count": {"sv": "{n} platser", "en": "{n} locations"},

    # ── views/stock.py ───────────────────────────────────────────────────
    "stock.page_title": {"sv": "Lagersaldo", "en": "Stock"},
    "stock.no_stock_info": {
        "sv": "Inget saldo registrerat ännu.", "en": "No stock recorded yet.",
    },
    "stock.total_per_item_header": {"sv": "Totalt per artikel", "en": "Total per item"},
    "stock.per_location_header": {"sv": "Per lagerplats", "en": "Per location"},
    "stock.adjust_header": {"sv": "Saldojustering", "en": "Stock adjustment"},
    "stock.sku_label": {"sv": "SKU", "en": "SKU"},
    "stock.location_label": {"sv": "Plats", "en": "Location"},
    "stock.delta_label": {"sv": "Ändring (+/-)", "en": "Change (+/-)"},
    "stock.delta_help": {
        "sv": "Positivt tal ökar saldot, negativt minskar det.",
        "en": "A positive number increases stock, negative decreases it.",
    },
    "stock.reference_label": {
        "sv": "Referens/anledning (valfritt)", "en": "Reference/reason (optional)",
    },
    "stock.adjust_button": {"sv": "Justera saldo", "en": "Adjust stock"},
    "stock.delta_zero_error": {
        "sv": "Ange en ändring skild från noll.", "en": "Enter a change other than zero.",
    },
    "stock.adjusted_success": {
        "sv": "Saldo för {sku} vid {location} justerat med {delta}.",
        "en": "Stock for {sku} at {location} adjusted by {delta}.",
    },

    # ── views/receive.py ─────────────────────────────────────────────────
    "receive.page_title": {"sv": "Ta emot", "en": "Receive"},
    "receive.step1_header": {"sv": "1. Skanna artikel", "en": "1. Scan item"},
    "receive.step2_header": {"sv": "2. Bekräfta mottagning", "en": "2. Confirm receipt"},
    "receive.qty_label": {"sv": "Mängd", "en": "Quantity"},
    "receive.dock_label": {"sv": "Mottagningsplats", "en": "Receiving location"},
    "receive.putaway_location_label": {
        "sv": "Slutlig lagerplats", "en": "Final storage location",
    },
    "receive.reference_po_label": {
        "sv": "Referens (PO-nummer, valfritt)", "en": "Reference (PO number, optional)",
    },
    "receive.confirm_button": {"sv": "Bekräfta mottagning", "en": "Confirm receipt"},
    "receive.qty_must_be_positive_error": {
        "sv": "Mängden måste vara större än noll.", "en": "Quantity must be greater than zero.",
    },
    "receive.received_flash": {
        "sv": "Mottaget: {qty} st {sku} till {location}.",
        "en": "Received: {qty} pcs {sku} to {location}.",
    },

    # ── views/transfer.py ────────────────────────────────────────────────
    "transfer.page_title": {"sv": "Flytta", "en": "Transfer"},
    "transfer.no_stock_info": {
        "sv": "Inget saldo att flytta ännu. Ta emot något under 'Ta emot' först.",
        "en": "No stock to transfer yet. Receive something under 'Receive' first.",
    },
    "transfer.step1_header": {"sv": "1. Välj artikel", "en": "1. Select item"},
    "transfer.manual_select_caption": {
        "sv": "Eller välj manuellt ur listan, utan att skriva SKU:",
        "en": "Or pick manually from the list, without typing a SKU:",
    },
    "transfer.item_select_label": {"sv": "Artikel", "en": "Item"},
    "transfer.select_item_button": {"sv": "Välj artikel", "en": "Select item"},
    "transfer.step2_header": {"sv": "2. Bekräfta flytt", "en": "2. Confirm transfer"},
    "transfer.no_stock_for_sku_warning": {
        "sv": "{sku} har inget saldo på någon plats — inget att flytta.",
        "en": "{sku} has no stock at any location — nothing to transfer.",
    },
    "transfer.from_location_label": {"sv": "Från plats", "en": "From location"},
    "transfer.to_location_label": {"sv": "Till plats", "en": "To location"},
    "transfer.reference_placeholder": {
        "sv": "t.ex. omplacering, inventering", "en": "e.g. relocation, cycle count",
    },
    "transfer.confirm_button": {"sv": "Bekräfta flytt", "en": "Confirm transfer"},
    "transfer.qty_must_be_positive_error": {
        "sv": "Mängden måste vara större än noll.", "en": "Quantity must be greater than zero.",
    },
    "transfer.same_location_error": {
        "sv": "Från- och till-plats kan inte vara samma.",
        "en": "From and to location cannot be the same.",
    },
    "transfer.transferred_flash": {
        "sv": "Flyttat: {qty} st {sku} från {from_location} till {to_location}.",
        "en": "Transferred: {qty} pcs {sku} from {from_location} to {to_location}.",
    },

    # ── views/orders.py ──────────────────────────────────────────────────
    "orders.page_title": {"sv": "Ordrar", "en": "Orders"},
    "orders.tab_create": {"sv": "Skapa order", "en": "Create order"},
    "orders.tab_lines": {"sv": "Orderrader", "en": "Order lines"},
    "orders.tab_all": {"sv": "Alla ordrar", "en": "All orders"},
    "orders.create_header": {"sv": "Skapa order", "en": "Create order"},
    "orders.order_no_label": {"sv": "Ordernummer *", "en": "Order number *"},
    "orders.customer_reference_label": {
        "sv": "Kundreferens (valfritt)", "en": "Customer reference (optional)",
    },
    "orders.create_button": {"sv": "Skapa order", "en": "Create order"},
    "orders.order_no_required_error": {
        "sv": "Ordernummer krävs.", "en": "Order number is required.",
    },
    "orders.order_created": {"sv": "Order {order_no} skapad.", "en": "Order {order_no} created."},
    "orders.order_exists_error": {
        "sv": "Ordernummer {order_no} finns redan.", "en": "Order number {order_no} already exists.",
    },
    "orders.add_lines_header": {"sv": "Lägg till orderrader", "en": "Add order lines"},
    "orders.no_open_orders_info": {
        "sv": "Inga öppna ordrar. Skapa en order under fliken 'Skapa order' först.",
        "en": "No open orders. Create an order under the 'Create order' tab first.",
    },
    "orders.no_items_info": {
        "sv": "Inga artiklar. Lägg till artiklar under 'Artiklar & platser' först.",
        "en": "No items. Add items under 'Items & locations' first.",
    },
    "orders.order_label": {"sv": "Order", "en": "Order"},
    "orders.qty_label": {"sv": "Antal", "en": "Quantity"},
    "orders.add_line_button": {"sv": "Lägg till rad", "en": "Add line"},
    "orders.qty_must_be_positive_error": {
        "sv": "Antal måste vara större än noll.", "en": "Quantity must be greater than zero.",
    },
    "orders.line_added": {
        "sv": "Rad {line_no} ({sku} x{qty}) tillagd på {order_no}.",
        "en": "Line {line_no} ({sku} x{qty}) added to {order_no}.",
    },
    "orders.lines_on_order_header": {
        "sv": "Rader på {order_no}", "en": "Lines on {order_no}",
    },
    "orders.all_orders_header": {"sv": "Alla utleveransordrar", "en": "All outbound orders"},
    "orders.mark_shipped_header": {"sv": "Markera som skickad", "en": "Mark as shipped"},
    "orders.packed_order_label": {"sv": "Packad order", "en": "Packed order"},
    "orders.mark_shipped_button": {"sv": "Markera som skickad", "en": "Mark as shipped"},
    "orders.marked_shipped": {
        "sv": "{order_no} markerad som skickad.", "en": "{order_no} marked as shipped.",
    },

    # ── views/pick.py ────────────────────────────────────────────────────
    "pick.page_title": {"sv": "Plocka", "en": "Pick"},
    "pick.no_orders_info": {
        "sv": "Inga ordrar att plocka. Skapa en order under 'Ordrar' först.",
        "en": "No orders to pick. Create an order under 'Orders' first.",
    },
    "pick.order_label": {"sv": "Order", "en": "Order"},
    "pick.scan_next_header": {"sv": "Skanna nästa artikel", "en": "Scan next item"},
    "pick.sku_not_on_order_error": {
        "sv": "{sku} finns inte kvar att plocka på denna order.",
        "en": "{sku} is not left to pick on this order.",
    },
    "pick.confirm_header": {"sv": "Bekräfta plock", "en": "Confirm pick"},
    "pick.info_line": {
        "sv": "**{sku}** vid **{location}** — kvar att plocka: {remaining}",
        "en": "**{sku}** at **{location}** — remaining to pick: {remaining}",
    },
    "pick.picked_qty_label": {"sv": "Plockad mängd", "en": "Picked quantity"},
    "pick.confirm_button": {"sv": "Bekräfta plock", "en": "Confirm pick"},
    "pick.qty_must_be_positive_error": {
        "sv": "Mängden måste vara större än noll.", "en": "Quantity must be greater than zero.",
    },
    "pick.qty_exceeds_remaining_error": {
        "sv": "Kan inte plocka mer än kvarstående {remaining}.",
        "en": "Cannot pick more than the remaining {remaining}.",
    },
    "pick.picked_flash": {"sv": "Plockat: {qty} st {sku}.", "en": "Picked: {qty} pcs {sku}."},

    # ── views/reorder.py ─────────────────────────────────────────────────
    "reorder.page_title": {"sv": "Påfyllning", "en": "Replenishment"},
    "reorder.nothing_needed_success": {
        "sv": "Inget behöver beställas just nu — alla artiklar har tillräckligt saldo.",
        "en": "Nothing needs ordering right now — all items have sufficient stock.",
    },
    "reorder.items_to_order_metric": {"sv": "Artiklar att beställa", "en": "Items to order"},
    "reorder.stockout_risk_metric": {
        "sv": "Varav stockout-risk", "en": "Of which stockout risk",
    },
    "reorder.total_order_value_metric": {
        "sv": "Totalt ordervärde", "en": "Total order value",
    },
    "reorder.by_supplier_header": {"sv": "Per leverantör", "en": "By supplier"},
    "reorder.suggested_orders_header": {
        "sv": "Föreslagna beställningar", "en": "Suggested orders",
    },
    "reorder.sort_caption": {
        "sv": "Sorterat efter brådska: stockout-risk först, sedan minst lagerdagar "
              "kvar, sedan störst ordervärde.",
        "en": "Sorted by urgency: stockout risk first, then fewest days of stock "
              "left, then largest order value.",
    },

    # ── views/iha_report.py ──────────────────────────────────────────────
    "iha.page_title": {"sv": "IHA-rapport", "en": "IHA report"},
    "iha.health_score_metric": {"sv": "Lagerhälsopoäng", "en": "Inventory health score"},
    "iha.total_items_metric": {"sv": "Antal artiklar", "en": "Number of items"},
    "iha.health_score_caption": {
        "sv": "Viktat mot ABC-klass — en död A-artikel väger tyngre än en död "
              "C-artikel. 100 = allt friskt, 0 = allt dött.",
        "en": "Weighted by ABC class — a dead A item weighs more than a dead C "
              "item. 100 = everything healthy, 0 = everything dead.",
    },
    "iha.total_value_metric": {"sv": "Totalt lagervärde", "en": "Total stock value"},
    "iha.dead_stock_metric": {"sv": "Dött lager", "en": "Dead stock"},
    "iha.excess_metric": {"sv": "Överlager", "en": "Excess stock"},
    "iha.releasable_metric": {"sv": "Frigörbart kapital", "en": "Releasable capital"},
    "iha.deficit_metric": {
        "sv": "Underskott (kräver påfyllning)", "en": "Deficit (needs replenishment)",
    },
    "iha.annual_saving_metric": {
        "sv": "Årlig lagerkostnadsbesparing", "en": "Annual holding cost saving",
    },
    "iha.status_header": {"sv": "Status", "en": "Status"},
    "iha.trend_header": {"sv": "Trend", "en": "Trend"},
    "iha.insufficient_history_caption": {
        "sv": "{n} artiklar har för kort historik för att klassificeras.",
        "en": "{n} items have too little history to classify.",
    },
    "iha.supplier_analysis_header": {"sv": "Leverantörsanalys", "en": "Supplier analysis"},
    "iha.lead_time_recon_header": {
        "sv": "Ledtidsavstämning", "en": "Lead time reconciliation",
    },
    "iha.no_measured_lead_time_caption": {
        "sv": "Ingen uppmätt ledtid ännu — kräver flera mottagningar per artikel "
              "över tid. Beräkningarna använder tills vidare artikelns angivna ledtid.",
        "en": "No measured lead time yet — requires several receipts per item "
              "over time. Calculations use the item's stated lead time for now.",
    },
    "iha.measured_items_metric": {"sv": "Uppmätta artiklar", "en": "Measured items"},
    "iha.mean_gap_metric": {"sv": "Snittavvikelse (dagar)", "en": "Mean deviation (days)"},
    "iha.understated_items_metric": {
        "sv": "Underskattade artiklar", "en": "Understated items",
    },
    "iha.lead_time_gap_caption": {
        "sv": "Angiven ledtid underskattar den verkliga med mer än 5 dagar på "
              "{n} artiklar, värda {value}.",
        "en": "Stated lead time underestimates the real one by more than 5 days "
              "on {n} items, worth {value}.",
    },
    "iha.items_header": {"sv": "Artiklar", "en": "Items"},
    "iha.root_causes_header": {
        "sv": "Rotorsaker (dött lager & trögrörligt)",
        "en": "Root causes (dead stock & slow movers)",
    },
    "iha.matrix_header": {"sv": "ABC × XYZ", "en": "ABC × XYZ"},
    "iha.demand_data_caption": {
        "sv": "Efterfrågedata: {note}", "en": "Demand data: {note}",
    },

    # ── views/import_data.py ─────────────────────────────────────────────
    "import.page_title": {"sv": "Importera", "en": "Import"},
    "import.page_caption": {
        "sv": "Ladda upp en Excel- eller CSV-fil från ert affärssystem eller en "
              "gammal Excel-lista. Kolumnnamn känns igen automatiskt (svenska "
              "eller engelska) men går alltid att ändra manuellt innan något sparas.",
        "en": "Upload an Excel or CSV file from your business system or an old "
              "Excel list. Column names are recognized automatically (Swedish "
              "or English) but can always be changed manually before anything is saved.",
    },
    "import.tab_items": {"sv": "Artiklar", "en": "Items"},
    "import.tab_locations": {"sv": "Lagerplatser", "en": "Locations"},
    "import.tab_stock": {"sv": "Startsaldo", "en": "Opening stock"},
    "import.stock_info": {
        "sv": "Startsaldo bokförs som en mottagning (typ 'receive') per rad, så "
              "det hamnar i samma logg som allt annat och kan köras igenom "
              "IHA-analysen. Kör bara en gång per artikel/plats — en andra "
              "körning lägger på ovanpå, ersätter inte.",
        "en": "Opening stock is booked as a receipt ('receive') per row, so it "
              "lands in the same log as everything else and can run through the "
              "IHA analysis. Only run this once per item/location — a second run "
              "adds on top, it doesn't replace.",
    },
    "import.upload_label": {
        "sv": "Ladda upp fil med {entity}", "en": "Upload file with {entity}",
    },
    "import.parse_error": {
        "sv": "Kunde inte läsa filen: {error}", "en": "Could not read the file: {error}",
    },
    "import.empty_file_warning": {
        "sv": "Filen verkar vara tom.", "en": "The file appears to be empty.",
    },
    "import.rows_found_caption": {
        "sv": "{n} rader hittades. Kolumner i filen: {cols}",
        "en": "{n} rows found. Columns in the file: {cols}",
    },
    "import.mapping_intro": {
        "sv": "Kolumnmappning (föreslagen automatiskt, ändra vid behov):",
        "en": "Column mapping (suggested automatically, change if needed):",
    },
    "import.none_option": {"sv": "(ingen)", "en": "(none)"},
    "import.missing_required_warning": {
        "sv": "Obligatoriska fält saknar kolumn: {fields}",
        "en": "Required fields missing a column: {fields}",
    },
    "import.preview_intro": {
        "sv": "Förhandsgranskning (första 5 raderna, tolkade värden):",
        "en": "Preview (first 5 rows, parsed values):",
    },
    "import.import_button": {"sv": "Importera {entity}", "en": "Import {entity}"},
    "import.done_summary": {
        "sv": "Klart: {inserted} nya, {updated} uppdaterade, {skipped} hoppade över.",
        "en": "Done: {inserted} new, {updated} updated, {skipped} skipped.",
    },
    "import.errors_expander": {
        "sv": "{n} rader kunde inte importeras", "en": "{n} rows could not be imported",
    },

    "field.sku": {"sv": "SKU", "en": "SKU"},
    "field.barcode": {"sv": "Streckkod", "en": "Barcode"},
    "field.description": {"sv": "Beskrivning", "en": "Description"},
    "field.unit_cost": {"sv": "Enhetskostnad", "en": "Unit cost"},
    "field.currency": {"sv": "Valuta", "en": "Currency"},
    "field.supplier": {"sv": "Leverantör", "en": "Supplier"},
    "field.category": {"sv": "Kategori", "en": "Category"},
    "field.lead_time_days": {"sv": "Ledtid (dagar)", "en": "Lead time (days)"},
    "field.location_code": {"sv": "Platskod", "en": "Location code"},
    "field.zone": {"sv": "Zon", "en": "Zone"},
    "field.location_type": {
        "sv": "Typ (receiving/picking/bulk)", "en": "Type (receiving/picking/bulk)",
    },
    "field.qty": {"sv": "Antal", "en": "Quantity"},

    # ── components/barcode_input.py ─────────────────────────────────────
    "barcode.scan_label": {
        "sv": "Skanna streckkod eller ange SKU", "en": "Scan barcode or enter SKU",
    },
    "barcode.search_button": {"sv": "Sök", "en": "Search"},

    # ── components/export.py ─────────────────────────────────────────────
    "export.excel_button": {"sv": "⬇ Exportera till Excel", "en": "⬇ Export to Excel"},

    # ── views/forecast_demo.py (docs/FORECAST_SPEC.md Phase 9) ──────────
    "forecast.page_title": {"sv": "Prognosmotor -- demo", "en": "Forecasting engine -- demo"},
    "forecast.demo_data_caption": {
        "sv": "Visar resultat från den syntetiska demodatan (datagen/v1, 3 000 artiklar, 4 år) -- "
              "inte {company}s egna data. Kopplingen mot ett företags egen lagerhistorik är ett "
              "separat, senare steg (docs/FORECAST_SPEC.md Fas 10).",
        "en": "Shows results from the synthetic demo dataset (datagen/v1, 3,000 items, 4 years) -- "
              "not {company}'s own data. Wiring this against a company's own inventory history is a "
              "separate, later step (docs/FORECAST_SPEC.md Phase 10).",
    },
    "forecast.tab_overview": {"sv": "Översikt", "en": "Overview"},
    "forecast.tab_item": {"sv": "Artikelvy", "en": "Item view"},
    "forecast.tab_backtest": {"sv": "Backtest per segment", "en": "Backtest by segment"},
    "forecast.tab_policy": {"sv": "Policy & frontier", "en": "Policy & frontier"},
    "forecast.tab_alerts": {"sv": "Larm", "en": "Alerts"},
    "forecast.tab_quality": {"sv": "Datakvalitet", "en": "Data quality"},

    "forecast.overview_items_metric": {"sv": "Artiklar", "en": "Items"},
    "forecast.overview_outbound_metric": {"sv": "Utleveransrader", "en": "Outbound lines"},
    "forecast.overview_inbound_metric": {"sv": "Inleveransrader", "en": "Inbound lines"},
    "forecast.overview_segment_header": {"sv": "Efterfrågemönster (ADI/CV²-klass)", "en": "Demand pattern (ADI/CV² class)"},
    "forecast.overview_abc_header": {"sv": "ABC-fördelning", "en": "ABC distribution"},
    "forecast.overview_lifecycle_header": {"sv": "Livscykelsignaler", "en": "Lifecycle signals"},
    "forecast.overview_new_items_metric": {"sv": "Nya artiklar", "en": "New items"},
    "forecast.overview_obsolete_metric": {"sv": "Blir föråldrade", "en": "Becoming obsolete"},
    "forecast.overview_stale_metric": {"sv": "Still med lager, ingen efterfrågan", "en": "Stale with stock"},

    "forecast.item_select_label": {"sv": "Välj artikel", "en": "Select item"},
    "forecast.item_history_header": {"sv": "Efterfrågehistorik", "en": "Demand history"},
    "forecast.item_forecast_header": {"sv": "Prognosfläkt (kvantiler)", "en": "Forecast fan (quantiles)"},
    "forecast.item_forecast_caption": {
        "sv": "Modell vald automatiskt per segment via Fas 4:s backtest (bäst pinball-loss @ q90): **{model}**",
        "en": "Model chosen automatically per segment via Phase 4's backtest (best pinball loss @ q90): **{model}**",
    },
    "forecast.item_forecast_caption_fallback": {
        "sv": "Bäst i backtest för detta segment är **{winner}**, men den kräver träning över hela "
              "artikelbeståndet och kan inte köras live för en enskild artikel här -- visar istället "
              "**{model}**.",
        "en": "The backtest winner for this segment is **{winner}**, but it needs training across the "
              "whole item panel and cannot run live for a single item here -- showing **{model}** instead.",
    },
    "forecast.item_policy_header": {"sv": "Policy (Fas 6)", "en": "Policy (Phase 6)"},
    "forecast.item_not_enough_history": {
        "sv": "För lite historik för att visa en prognos för denna artikel.",
        "en": "Not enough history to show a forecast for this item.",
    },

    "forecast.backtest_header": {"sv": "Bästa modell per segment (pinball-loss @ q90, lägre är bättre)", "en": "Best model per segment (pinball loss @ q90, lower is better)"},
    "forecast.backtest_caption": {
        "sv": "Från Fas 4:s fullskaliga backtest på alla 3 000 artiklar. Se CLAUDE.md för den ärliga "
              "slutsatsen: ingen av de avancerade modellerna slår de enkla baslinjerna med den marginal "
              "specen efterfrågar, förutom en liten vinst i erratic-segmentet.",
        "en": "From Phase 4's full-scale backtest on all 3,000 items. See CLAUDE.md for the honest "
              "conclusion: none of the advanced models beat the simple baselines by the spec's target "
              "margin, except a small win in the erratic segment.",
    },

    "forecast.policy_frontier_header": {"sv": "Service-vs-lagervärde-kurva", "en": "Service-vs-stock-value frontier"},
    "forecast.policy_comparison_header": {"sv": "Policy A (ERP) mot Policy B (kvantilbaserad)", "en": "Policy A (ERP) vs. Policy B (quantile-based)"},
    "forecast.policy_fill_rate_label": {"sv": "Fyllnadsgrad", "en": "Fill rate"},
    "forecast.policy_stock_value_label": {"sv": "Lagervärde (SEK)", "en": "Stock value (SEK)"},

    "forecast.alerts_header": {"sv": "Larm (urval, 500 artiklar)", "en": "Alerts (sample, 500 items)"},
    "forecast.live_alerts_header": {"sv": "Larm (alla {n} artiklar)", "en": "Alerts (all {n} items)"},
    "forecast.alerts_caption": {
        "sv": "Se CLAUDE.md Fas 8 för varför persistent_bias/demand_shift är överkänsliga vid "
              "standardinställningarna på just den här datan -- inte redo för produktion utan justering.",
        "en": "See CLAUDE.md Phase 8 for why persistent_bias/demand_shift are over-sensitive at default "
              "settings on this data -- not production-ready without tuning.",
    },
    "forecast.alerts_severity_filter": {"sv": "Filtrera på allvarlighetsgrad", "en": "Filter by severity"},
    "forecast.alerts_none": {"sv": "Inga larm matchar filtret.", "en": "No alerts match the filter."},

    "forecast.quality_header": {"sv": "Datakvalitet (hela demodatan)", "en": "Data quality (full demo dataset)"},
    "forecast.live_quality_header": {"sv": "Datakvalitet ({n} artiklar)", "en": "Data quality ({n} items)"},
    "forecast.quality_censored_metric": {"sv": "Stockout-censurerade rader", "en": "Stockout-censored lines"},
    "forecast.quality_outlier_metric": {"sv": "Avvikande perioder (outliers)", "en": "Outlier periods"},
    "forecast.quality_oneoff_metric": {"sv": "Engångsordrar (avvikande)", "en": "One-off large orders"},
    "forecast.quality_shift_metric": {"sv": "Artiklar med nivåskifte", "en": "Items with a level shift"},
    "forecast.quality_caption": {
        "sv": "Nivåskifte-flaggan är dokumenterat OKALIBRERAD (se forecasting/cleaning.py) -- för "
              "mänsklig granskning, inte som modellinput.",
        "en": "The level-shift flag is documented as NOT CALIBRATED (see forecasting/cleaning.py) -- "
              "for human review, not as model input.",
    },

    # ── views/forecast_live.py (docs/FORECAST_SPEC.md Phase 10+, live-tenant adapter) ──
    "forecast.live_page_title": {"sv": "Prognosmotor", "en": "Forecasting engine"},
    "forecast.live_page_caption": {
        "sv": "Kör mot {company}s egna lagerdata -- inte demodatan. Se CLAUDE.md "
              "\"forecasting/data_wms.py\" för vilka fält som saknas i den levande databasen "
              "jämfört med den syntetiska demodatan (t.ex. ingen separat ordermängd för inleveranser).",
        "en": "Runs against {company}'s own inventory data -- not the demo dataset. See CLAUDE.md "
              "\"forecasting/data_wms.py\" for which fields the live database is missing compared to "
              "the synthetic demo data (e.g. no separate ordered quantity for inbound receipts).",
    },
    "forecast.live_loading_spinner": {"sv": "Läser in data...", "en": "Loading data..."},
    "forecast.live_backtest_spinner": {
        "sv": "Kör backtest (tar upp till en minut första gången, cachas sedan)...",
        "en": "Running backtest (takes up to a minute the first time, cached afterward)...",
    },
    "forecast.live_backtest_caption": {
        "sv": "Backtest kört live mot denna artikelstock -- cachas per session, inte förberäknat.",
        "en": "Backtest run live against this item stock -- cached per session, not precomputed.",
    },
    "forecast.live_no_policy_a_caption": {
        "sv": "Ingen jämförelse mot \"nuvarande ERP-parametrar\" här -- wms-appens egen artikeltabell "
              "har ingen beställningspunkt/säkerhetslager-koncept ännu (se forecasting/data_wms.py). "
              "Kurvan visar bara den kvantilbaserade policyn vid olika målnivåer.",
        "en": "No comparison against \"current ERP parameters\" here -- wms-app's own items table has "
              "no reorder-point/safety-stock concept yet (see forecasting/data_wms.py). The curve shows "
              "only the quantile-based policy at different target levels.",
    },
    "forecast.live_no_history_caption": {
        "sv": "Inga utleveranser registrerade ännu -- inget att prognostisera på.",
        "en": "No outbound deliveries recorded yet -- nothing to forecast from.",
    },
}


def get_lang() -> str:
    return st.session_state.get("lang", DEFAULT_LANG)


def set_lang(lang: str) -> None:
    st.session_state["lang"] = lang


def t(key: str, **kwargs) -> str:
    """Look up `key` in the current language, falling back to Swedish (and
    then the raw key) if a translation is missing -- a missing key should
    degrade to visible-but-ugly, never crash the page."""
    entry = STRINGS.get(key)
    if entry is None:
        return key
    text = entry.get(get_lang()) or entry.get(DEFAULT_LANG, key)
    return text.format(**kwargs) if kwargs else text


def language_switcher() -> None:
    """Renders the sv/en toggle. Deliberately does NOT call st.rerun() --
    Streamlit already reruns the script on a widget change, and any code
    below this call in the same pass sees the updated language immediately
    via get_lang(). An extra explicit rerun here aborts that pass before
    later widgets (e.g. the sidebar nav radio) are instantiated, which
    made Streamlit garbage-collect their session state as "not rendered
    this run" and silently reset the page selection on every language
    switch -- reproduced live, fixed by removing the redundant rerun."""
    lang = get_lang()
    codes = list(LANGUAGES.keys())
    choice = st.radio(
        t("app.language_label"), codes, index=codes.index(lang),
        format_func=lambda code: LANGUAGES[code],
        horizontal=True, key="lang_switcher",
    )
    if choice != lang:
        set_lang(choice)
