"""Svenska visningsetiketter för data som kommer från de vendrade
analysmodulerna i analysis/ -- källfilerna där har engelska kolumnnamn,
statusvärden och prosa (se CLAUDE.md "IHA integration": de är kopior av
iha-saas och ändras inte). Allt som faktiskt visas för användaren ska ändå
vara på svenska, så översättningen sker här, ett steg innan rendering,
istället för i de vendrade filerna.
"""

from __future__ import annotations

import re

import pandas as pd

from analysis.lead_time import CONCENTRATION_LIMIT, ON_TIME_TARGET

STATUS_LABELS = {
    "healthy": "Frisk",
    "slow_mover": "Trög",
    "dead_stock": "Dött lager",
    "stockout_risk": "Stockout-risk",
}

STATUS_REASON_LABELS = {
    "dos": "Lagernivå (DOS)",
    "recency": "Ingen rörelse",
    "no_demand": "Ingen efterfrågan",
    "stockout": "Stockout",
}

TREND_LABELS = {
    "new": "Ny",
    "growing": "Växande",
    "stable": "Stabil",
    "declining": "Avtagande",
    "stopped": "Stannat",
}

# Order-livscykeln (schema/tenant.sql:orders.status) -- inte samma
# vokabulär som STATUS_LABELS ovan, som gäller artikelns lagerhälsa.
ORDER_STATUS_LABELS = {
    "open": "Öppen",
    "picking": "Plockas",
    "packed": "Packad",
    "shipped": "Skickad",
    "received": "Mottagen",
    "cancelled": "Avbruten",
}

# Nycklar matchar de korta policy-strängarna i analysis/segmentation.py:POLICY_MATRIX.
POLICY_LABELS = {
    "Automate": "Automatisera",
    "Forecast + buffer": "Prognos + buffert",
    "Manual control": "Manuell kontroll",
    "Automate + alert": "Automatisera + larm",
    "Order to demand": "Beställ mot efterfrågan",
    "Bulk, rarely": "Stororder, sällan",
    "Stop stocking": "Sluta lagerhålla",
    "–": "–",
}

# Nycklar matchar analysis/inventory_bridge.py:ROOT_CAUSES.
ROOT_CAUSE_LABELS = {
    "bought_after_death": "Köpt efter att efterfrågan upphörde",
    "moq_overbuy": "Överköpt / minsta orderkvantitet",
    "demand_collapse": "Efterfrågan kollapsade",
    "phase_out": "Utfasad, aldrig nedtrappad",
    "erratic_demand": "Oförutsägbar efterfrågan",
    "overstocked_healthy": "Överlagrad, säljer fortfarande",
    "unknown": "Inte fastställd",
}

ROOT_CAUSE_ACTIONS = {
    "bought_after_death": (
        "Den senaste leveransen kom efter att artikeln redan slutat säljas. "
        "Ett inköpsproblem, inte ett prognosproblem — en varning vid inleverans "
        "på artiklar utan rörelse stoppar upprepning."
    ),
    "moq_overbuy": (
        "En enda leverans täckte mer än ett års behov. Minsta orderkvantiteter "
        "eller mängdrabatter skapar det döda lagret. Omförhandla kvantiteten "
        "innan priset."
    ),
    "demand_collapse": (
        "Artikeln sålde normalt och föll sedan bort. Inget var fel med inköpet "
        "då — felet är att ingen agerade när efterfrågan vände. Det är vad "
        "trendvyn är till för."
    ),
    "phase_out": (
        "Ingen rörelse på över ett år med lager kvar på hyllan. Produkten "
        "fasades ut kommersiellt men fick aldrig en nedtrappningsplan."
    ),
    "erratic_demand": (
        "Ryckig, svårprognostiserad efterfrågan buffrad med lager. För "
        "lågvärdesartiklar är det fel avvägning — beställ mot efterfrågan "
        "istället för att hålla lager."
    ),
    "overstocked_healthy": (
        "Artikeln säljer bra, det finns bara för mycket av den. "
        "Beställningsparametrarna är fel — den billigaste kategorin att fixa."
    ),
    "unknown": (
        "Inte tillräckligt med historik för att fastställa en orsak. Betyder "
        "oftast att det saknas daterad försäljnings- eller inleveransdata för "
        "artikeln."
    ),
}

# Kolumnrubriker som återkommer i flera tabeller runt om i appen. Bara kända
# namn byts ut -- rename(columns=..., errors="ignore") gör det säkert att
# applicera brett utan att räkna upp varje tabells exakta kolumner.
COLUMN_LABELS = {
    "sku": "SKU",
    "description": "Beskrivning",
    "abc_class": "ABC-klass",
    "xyz_class": "XYZ-klass",
    "trend_class": "Trend",
    "status": "Status",
    "status_reason": "Orsak",
    "stock_qty": "Saldo",
    "value_sek": "Lagervärde (SEK)",
    "dos": "Lagerdagar (DOS)",
    "safety_stock": "Säkerhetslager",
    "rop": "Beställningspunkt",
    "order_qty": "Föreslagen orderkvantitet",
    "supplier": "Leverantör",
    "skus": "Antal artiklar",
    "lt_days": "Ledtid (dagar)",
    "lt_sigma": "Ledtidsspridning (dagar)",
    "value_share": "Andel av lagervärde",
    "dead_share": "Andel dött lager",
    "lt_cv": "Ledtidsvariation",
    "policy": "Rekommenderad policy",
    "antal_artiklar": "Antal artiklar",
    "lagervärde": "Lagervärde (SEK)",
    "trend": "Trend",
    "location_code": "Lagerplats",
    "from_location": "Från plats",
    "to_location": "Till plats",
    "zone": "Zon",
    "qty": "Antal",
    "totalt_saldo": "Totalt saldo",
    "code": "Platskod",
    "location_type": "Typ",
    "barcode": "Streckkod",
    "unit_cost": "Enhetskostnad",
    "currency": "Valuta",
    "category": "Kategori",
    "lead_time_days": "Ledtid (dagar)",
    "created_at": "Skapad",
    "order_no": "Ordernummer",
    "order_type": "Ordertyp",
    "reference": "Referens",
    "line_no": "Radnummer",
    "qty_ordered": "Beställt antal",
    "qty_done": "Plockat antal",
    "lead_time_used": "Använd ledtid (dagar)",
    "lead_time_sigma": "Ledtidsspridning (dagar)",
    "lead_time_gap": "Avvikelse mot angiven ledtid",
    "remaining": "Kvar att plocka",
    "order_value_sek": "Ordervärde (SEK)",
}


def rename_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Byt ut kända engelska kolumnnamn mot svenska, för visning. Okända
    kolumner lämnas orörda -- säkert att applicera på vilken tabell som helst."""
    return df.rename(columns=COLUMN_LABELS)


def supplier_flags_sv(scorecard: pd.DataFrame) -> list[str]:
    """Svensk version av analysis/lead_time.py:supplier_flags() -- samma
    logik och tröskelvärden (importerade från lead_time.py så de aldrig kan
    gå isär), bara texten är översatt istället för forkad in i den vendrade
    filen."""
    if scorecard.empty:
        return []

    flags: list[str] = []
    top = scorecard.iloc[0]
    if top["value_share"] > CONCENTRATION_LIMIT:
        flags.append(
            f"**Koncentrationsrisk** — {top.iloc[0]} står för "
            f"{top['value_share']*100:.0f}% av lagervärdet "
            f"({top['value_sek']/1e6:.1f} MSEK). Över {CONCENTRATION_LIMIT*100:.0f}% "
            "blir en enskild leverantörs bortfall ett verksamhetskritiskt problem."
        )

    if "on_time_rate" in scorecard.columns:
        late = scorecard[(scorecard["on_time_rate"].notna())
                         & (scorecard["on_time_rate"] < ON_TIME_TARGET)]
        late = late.nlargest(3, "value_sek")
        for _, r in late.iterrows():
            flags.append(
                f"**{r.iloc[0]}** levererar i tid {r['on_time_rate']*100:.0f}% av "
                f"gångerna (mål {ON_TIME_TARGET*100:.0f}%), på {r['value_sek']/1e6:.1f} "
                "MSEK i lager. Varje sen leverans betalas med säkerhetslager."
            )

    if "lt_cv" in scorecard.columns:
        erratic = scorecard[(scorecard["lt_cv"] > 0.5) & (scorecard["value_sek"] > 0)]
        erratic = erratic.nlargest(3, "value_sek")
        for _, r in erratic.iterrows():
            flags.append(
                f"**{r.iloc[0]}** har oförutsägbar ledtid — {r['lt_days']:.0f} dagar "
                f"i snitt men en spridning på ±{r['lt_sigma']:.0f} dagar. Det är "
                "oförutsägbarheten, inte längden, som tvingar upp bufferten."
            )

    if "dead_share" in scorecard.columns:
        dead = scorecard[(scorecard["dead_share"] > 0.30)
                         & (scorecard["value_sek"] > scorecard["value_sek"].sum() * 0.05)]
        for _, r in dead.nlargest(3, "dead_value_sek").iterrows():
            flags.append(
                f"**{r.iloc[0]}** — {r['dead_share']*100:.0f}% av det ni har hos den "
                f"här leverantören är dött lager ({r['dead_value_sek']/1e6:.1f} MSEK). "
                "Se över minsta orderkvantiteter innan ni omförhandlar priset."
            )

    return flags


# Matchar de två notistexterna sales_statistics() i analysis/data_merge.py
# faktiskt kan producera när den matas från transaktionsloggen (alltid
# daterade rader -- "no dates" och "wide format"-grenarna är inte nåbara
# härifrån, bara den "long with dates"-grenen). Regex istället för att
# ändra den vendrade filen -- se modulens docstring.
_OBSERVED_WINDOW_RE = re.compile(
    r"Observed window: (\d+) days \(([\d-]+) → ([\d-]+)\), (\d+) complete months\.(.*)"
)
_LOW_DATA_RE = re.compile(
    r" Fewer than (\d+) complete months.*"
)
_NO_DATES_RE = re.compile(r"No dates — assumed a ([\d.]+)-year window\..*")


def translate_demand_note(note: str) -> str:
    """Svensk version av den datakvalitetsnotis sales_statistics() returnerar.
    Faller tillbaka till originaltexten oöversatt om formatet någonsin ändras
    i den vendrade filen, hellre än att krascha eller visa fel siffror."""
    no_dates = _NO_DATES_RE.match(note)
    if no_dates:
        return (
            f"Inga datum i transaktionerna — antog ett {no_dates.group(1)}-årigt fönster. "
            "Efterfrågevariation kunde inte mätas; säkerhetslagret räknas på ett schablonvärde."
        )

    match = _OBSERVED_WINDOW_RE.match(note)
    if not match:
        return note

    span, start, end, months, rest = match.groups()
    out = f"Observerad period: {span} dagar ({start} → {end}), {months} fullständiga månader."
    if _LOW_DATA_RE.match(rest):
        out += (
            " Färre än 3 fullständiga månader — efterfrågevariationen är osäker "
            "och säkerhetslagret räknas tills vidare på ett schablonvärde."
        )
    return out
