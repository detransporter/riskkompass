import streamlit as st
import pandas as pd
import numpy as np
import io

st.set_page_config(
    page_title="Riskkompass",
    page_icon="⚠️",
    layout="wide"
)

# ── CSS ──────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Syne:wght@400;600;700;800&display=swap');

html, body, [class*="css"] {
    font-family: 'Syne', sans-serif;
    background-color: #0f0f0f;
    color: #e8e3d8;
}

.stApp { background-color: #0f0f0f; }

h1, h2, h3 { font-family: 'Syne', sans-serif; font-weight: 800; }

.header-block {
    border-left: 4px solid #d4501a;
    padding: 1.2rem 1.6rem;
    background: #1a1a1a;
    margin-bottom: 2rem;
}
.header-block h1 { font-size: 2rem; margin: 0; color: #e8e3d8; }
.header-block p  { font-family: 'DM Mono', monospace; font-size: 0.78rem;
                   color: #888; margin: 0.4rem 0 0 0; letter-spacing: 0.05em; }

.scenario-bar {
    background: #1a1a1a;
    border: 1px solid #2a2a2a;
    border-radius: 4px;
    padding: 1rem 1.2rem;
    margin-bottom: 1.5rem;
}
.scenario-bar h4 { margin: 0 0 0.3rem 0; font-size: 0.85rem;
                   text-transform: uppercase; letter-spacing: 0.1em; color: #888; }
.scenario-bar .val { font-family: 'DM Mono', monospace; font-size: 1.4rem;
                     color: #d4501a; font-weight: 500; }

.kpi-card {
    background: #1a1a1a;
    border: 1px solid #2a2a2a;
    border-radius: 4px;
    padding: 1.2rem;
    text-align: center;
}
.kpi-label { font-size: 0.72rem; text-transform: uppercase;
             letter-spacing: 0.12em; color: #666; margin-bottom: 0.4rem; }
.kpi-value { font-family: 'DM Mono', monospace; font-size: 1.8rem; font-weight: 500; }
.kpi-red   { color: #e05252; }
.kpi-amber { color: #e0a952; }
.kpi-green { color: #52a887; }
.kpi-blue  { color: #5288e0; }

.risk-high   { color: #e05252; font-weight: 600; }
.risk-medium { color: #e0a952; font-weight: 600; }
.risk-low    { color: #52a887; font-weight: 600; }

.section-title {
    font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.15em;
    color: #555; border-bottom: 1px solid #2a2a2a;
    padding-bottom: 0.5rem; margin: 2rem 0 1rem 0;
}

.stButton>button {
    background: #d4501a; color: #fff; border: none;
    font-family: 'Syne', sans-serif; font-weight: 700;
    letter-spacing: 0.05em; border-radius: 2px;
    padding: 0.6rem 1.4rem;
}
.stButton>button:hover { background: #b84016; }

.stDataFrame { font-family: 'DM Mono', monospace; font-size: 0.82rem; }

.info-box {
    background: #1a1a1a; border-left: 3px solid #5288e0;
    padding: 0.8rem 1rem; border-radius: 2px;
    font-family: 'DM Mono', monospace; font-size: 0.8rem; color: #aaa;
    margin-bottom: 1rem;
}

div[data-testid="stSidebar"] { background: #111; border-right: 1px solid #1e1e1e; }
div[data-testid="stSidebar"] label { color: #aaa !important; }
</style>
""", unsafe_allow_html=True)

# ── HEADER ───────────────────────────────────────────────────────────────────
st.markdown("""
<div class="header-block">
  <h1>⚠ Riskkompass</h1>
  <p>HORMUZSTREDET-SCENARIO · SCM INTERNATIONAL · DAVID LEIFSSON</p>
</div>
""", unsafe_allow_html=True)

# ── SIDEBAR — Scenario-inställningar ─────────────────────────────────────────
with st.sidebar:
    st.markdown("### Scenario")

    scenario = st.selectbox("Välj scenario", [
        "Basfall — Vapenvila inom 2 mån (lead time +40%)",
        "Förlängt krig — Hormuz stängt (lead time +80%)",
        "Worst case — Dubbelstrypning Hormuz+Röda havet (lead time +150%)"
    ])

    scenario_multipliers = {
        "Basfall — Vapenvila inom 2 mån (lead time +40%)": 1.40,
        "Förlängt krig — Hormuz stängt (lead time +80%)": 1.80,
        "Worst case — Dubbelstrypning Hormuz+Röda havet (lead time +150%)": 2.50
    }
    lt_multiplier = scenario_multipliers[scenario]
    lt_increase_pct = int((lt_multiplier - 1) * 100)

    st.markdown("---")
    st.markdown("### Parametrar")
    service_level = st.slider("Servicenivå (%)", 90, 99, 95)
    z_score = {90: 1.28, 91: 1.34, 92: 1.41, 93: 1.48, 94: 1.56,
               95: 1.65, 96: 1.75, 97: 1.88, 98: 2.05, 99: 2.33}[service_level]

    dead_stock_days = st.slider("Dött lager definieras som (dagar utan rörelse)", 60, 180, 120)
    slow_mover_days = st.slider("Slow mover-gräns (dagar)", 30, 90, 60)

    st.markdown("---")
    st.markdown("""
    <div style='font-family:DM Mono,monospace;font-size:0.72rem;color:#444;'>
    ABC-klassificering<br>A = topp 80% av värde<br>B = nästa 15%<br>C = sista 5%
    </div>
    """, unsafe_allow_html=True)

# ── SCENARIO-INDIKATOR ───────────────────────────────────────────────────────
col1, col2, col3 = st.columns(3)
scenario_colors = {1.40: "#52a887", 1.80: "#e0a952", 2.50: "#e05252"}
sc = scenario_colors[lt_multiplier]

with col1:
    st.markdown(f"""
    <div class="scenario-bar">
      <h4>Aktivt scenario</h4>
      <div class="val" style="color:{sc};">Lead time ×{lt_multiplier}</div>
    </div>""", unsafe_allow_html=True)
with col2:
    st.markdown(f"""
    <div class="scenario-bar">
      <h4>Lead time-ökning</h4>
      <div class="val" style="color:{sc};">+{lt_increase_pct}%</div>
    </div>""", unsafe_allow_html=True)
with col3:
    st.markdown(f"""
    <div class="scenario-bar">
      <h4>Servicenivå</h4>
      <div class="val" style="color:#5288e0;">{service_level}% (z={z_score})</div>
    </div>""", unsafe_allow_html=True)

# ── DATA-INMATNING ────────────────────────────────────────────────────────────
st.markdown('<div class="section-title">Datainmatning</div>', unsafe_allow_html=True)

tab_upload, tab_manual = st.tabs(["📂 Ladda upp CSV/Excel", "✏️ Manuell inmatning"])

df = None

with tab_upload:
    st.markdown("""
    <div class="info-box">
    Förväntade kolumner: artikel_nr, beskrivning, abc_klass, 
    lead_time_dagar, efterfragan_snitt_dag, efterfragan_std_dag, 
    lager_saldo, enhetspris_sek, dagar_utan_rorelse
    </div>
    """, unsafe_allow_html=True)

    uploaded = st.file_uploader("Ladda upp fil", type=["csv", "xlsx"])

    REQUIRED_COLS = [
        "artikel_nr", "beskrivning", "abc_klass", "lead_time_dagar",
        "efterfragan_snitt_dag", "efterfragan_std_dag", "lager_saldo",
        "enhetspris_sek", "dagar_utan_rorelse"
    ]

    if uploaded:
        try:
            if uploaded.name.endswith(".csv"):
                # Detektera svensk CSV (semikolon + komma-decimal)
                raw_bytes = uploaded.read()
                uploaded.seek(0)
                first_line = raw_bytes.decode("utf-8", errors="replace").split("\n")[0]
                if first_line.count(";") > first_line.count(","):
                    df_raw = pd.read_csv(uploaded, sep=";", decimal=",")
                else:
                    df_raw = pd.read_csv(uploaded)
            else:
                df_raw = pd.read_excel(uploaded)

            missing_cols = [c for c in REQUIRED_COLS if c not in df_raw.columns]
            if missing_cols:
                st.error(f"Filen saknar kolumner: {', '.join(missing_cols)}")
                st.info("Ladda ned Excel-mallen nedan för korrekt format.")
            else:
                df = df_raw.copy()
                st.success(f"✓ {len(df)} artiklar inlästa")
        except Exception as e:
            st.error(f"Kunde inte läsa filen: {e}")

    # Mallnedladdning
    st.markdown("**Ladda ned exempelmall:**")
    sample = pd.DataFrame({
        "artikel_nr":           ["ART-001", "ART-002", "ART-003", "ART-004", "ART-005"],
        "beskrivning":          ["Hydraulpump A", "O-ring kit", "Styrenhet X200", "Kabelstam 4m", "Filter HEPA"],
        "abc_klass":            ["A", "C", "A", "B", "B"],
        "lead_time_dagar":      [45, 14, 60, 30, 21],
        "efterfragan_snitt_dag":[2.5, 15.0, 0.8, 4.0, 3.2],
        "efterfragan_std_dag":  [0.8, 4.0, 0.3, 1.2, 0.9],
        "lager_saldo":          [80, 120, 25, 90, 45],
        "enhetspris_sek":       [4500, 85, 12000, 320, 680],
        "dagar_utan_rorelse":   [12, 45, 8, 130, 55],
    })
    buf = io.BytesIO()
    sample.to_excel(buf, index=False)
    st.download_button("⬇ Ladda ned Excel-mall", buf.getvalue(),
                       "mall_riskkompass.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

with tab_manual:
    st.markdown("Fyll i artiklar manuellt (max 20 för demo):")

    n_articles = st.number_input("Antal artiklar", 1, 20, 5)

    manual_data = []
    col_headers = st.columns([1.2, 2, 0.8, 1, 1.2, 1.2, 1, 1.2, 1])
    headers = ["Artikel nr", "Beskrivning", "ABC", "LT (dagar)",
               "Eftfr. snitt/dag", "Eftfr. std/dag", "Saldo", "Pris (SEK)", "Dagar u. rör."]
    for col, h in zip(col_headers, headers):
        col.markdown(f"**{h}**")

    defaults = [
        ("ART-001", "Hydraulpump A",   "A", 45, 2.5, 0.8,  80, 4500, 12),
        ("ART-002", "O-ring kit",       "C", 14, 15.0, 4.0, 120,  85, 45),
        ("ART-003", "Styrenhet X200",   "A", 60, 0.8, 0.3,  25, 12000, 8),
        ("ART-004", "Kabelstam 4m",     "B", 30, 4.0, 1.2,  90,  320, 130),
        ("ART-005", "Filter HEPA",      "B", 21, 3.2, 0.9,  45,  680, 55),
    ]

    for i in range(n_articles):
        d = defaults[i] if i < len(defaults) else ("", "", "B", 30, 1.0, 0.3, 50, 500, 10)
        cols = st.columns([1.2, 2, 0.8, 1, 1.2, 1.2, 1, 1.2, 1])
        art   = cols[0].text_input("", d[0], key=f"art_{i}", label_visibility="collapsed")
        desc  = cols[1].text_input("", d[1], key=f"desc_{i}", label_visibility="collapsed")
        abc   = cols[2].selectbox("", ["A","B","C"], index=["A","B","C"].index(d[2]),
                                  key=f"abc_{i}", label_visibility="collapsed")
        lt    = cols[3].number_input("", 1, 365, d[3], key=f"lt_{i}", label_visibility="collapsed")
        mu    = cols[4].number_input("", 0.0, 500.0, float(d[4]), key=f"mu_{i}", label_visibility="collapsed")
        sig   = cols[5].number_input("", 0.0, 200.0, float(d[5]), key=f"sig_{i}", label_visibility="collapsed")
        saldo = cols[6].number_input("", 0, 10000, d[6], key=f"sal_{i}", label_visibility="collapsed")
        pris  = cols[7].number_input("", 0, 500000, d[7], key=f"pr_{i}", label_visibility="collapsed")
        dagar = cols[8].number_input("", 0, 730, d[8], key=f"dag_{i}", label_visibility="collapsed")

        manual_data.append({
            "artikel_nr": art, "beskrivning": desc, "abc_klass": abc,
            "lead_time_dagar": lt, "efterfragan_snitt_dag": mu,
            "efterfragan_std_dag": sig, "lager_saldo": saldo,
            "enhetspris_sek": pris, "dagar_utan_rorelse": dagar
        })

    if st.button("Kör analys →"):
        df = pd.DataFrame(manual_data)

# ── ANALYS ────────────────────────────────────────────────────────────────────
if df is not None and len(df) > 0:

    # Beräkna
    df = df.copy()
    df["lead_time_ny"] = df["lead_time_dagar"] * lt_multiplier

    # Säkerhetslager: z * sigma * sqrt(LT)
    df["ss_original"] = z_score * df["efterfragan_std_dag"] * np.sqrt(df["lead_time_dagar"])
    df["ss_ny"]       = z_score * df["efterfragan_std_dag"] * np.sqrt(df["lead_time_ny"])
    df["ss_delta"]    = df["ss_ny"] - df["ss_original"]

    # ROP (reorder point)
    df["rop_original"] = df["efterfragan_snitt_dag"] * df["lead_time_dagar"] + df["ss_original"]
    df["rop_ny"]       = df["efterfragan_snitt_dag"] * df["lead_time_ny"]    + df["ss_ny"]

    # DOS (days of stock)
    df["dos"] = np.where(df["efterfragan_snitt_dag"] > 0,
                         df["lager_saldo"] / df["efterfragan_snitt_dag"], 999)

    # Stockout-risk: saldo under ny ombeställningspunkt
    df["stockout_risk"] = df["lager_saldo"] < df["rop_ny"]

    # Överlager / dött lager
    df["dott_lager"]  = df["dagar_utan_rorelse"] >= dead_stock_days
    df["slow_mover"]  = (df["dagar_utan_rorelse"] >= slow_mover_days) & (~df["dott_lager"])

    # Akut inköpsbehov
    df["inkopsbehov_antal"]    = np.maximum(0, df["rop_ny"] - df["lager_saldo"])
    df["inkopsbehov_sek"]      = df["inkopsbehov_antal"] * df["enhetspris_sek"]

    # Kapitalbindning
    df["kapital_sek"]          = df["lager_saldo"] * df["enhetspris_sek"]
    df["kapital_dott_sek"]     = np.where(df["dott_lager"],  df["kapital_sek"], 0)
    df["kapital_slow_sek"]     = np.where(df["slow_mover"],  df["kapital_sek"], 0)
    df["extra_ss_kapital_sek"] = df["ss_delta"] * df["enhetspris_sek"]

    # ABC-klassificering baserad på årsförbrukningsvärde (korrekt metod)
    df["forbrukning_arsv"] = df["efterfragan_snitt_dag"] * 365 * df["enhetspris_sek"]
    total_forb = df["forbrukning_arsv"].sum()
    df_sorted = df.sort_values("forbrukning_arsv", ascending=False).copy()
    df_sorted["cum_andel"] = df_sorted["forbrukning_arsv"].cumsum() / total_forb if total_forb > 0 else 0
    df_sorted["abc_beraknad"] = np.where(df_sorted["cum_andel"] <= 0.80, "A",
                                np.where(df_sorted["cum_andel"] <= 0.95, "B", "C"))
    df = df.merge(df_sorted[["artikel_nr", "abc_beraknad"]], on="artikel_nr", how="left")

    # Risklabel
    def risk_label(row):
        if row["stockout_risk"] and row["abc_klass"] == "A":
            return "KRITISK"
        elif row["stockout_risk"]:
            return "HÖG"
        elif row["dos"] < (row["lead_time_ny"] * 1.5):
            return "MEDEL"
        else:
            return "LÅG"
    df["risk"] = df.apply(risk_label, axis=1)

    # ── KPI-SAMMANFATTNING ────────────────────────────────────────────────────
    st.markdown('<div class="section-title">Sammanfattning</div>', unsafe_allow_html=True)

    k1, k2, k3, k4, k5 = st.columns(5)

    n_stockout      = df["stockout_risk"].sum()
    n_dott          = df["dott_lager"].sum()
    kap_dott        = df["kapital_dott_sek"].sum()
    extra_kap_ss    = df["extra_ss_kapital_sek"].sum()
    tot_inkopsbehov = df["inkopsbehov_sek"].sum()

    with k1:
        pct = int(n_stockout / len(df) * 100)
        st.markdown(f"""
        <div class="kpi-card">
          <div class="kpi-label">Artiklar i stockout-risk</div>
          <div class="kpi-value kpi-red">{n_stockout} <span style='font-size:1rem'>({pct}%)</span></div>
        </div>""", unsafe_allow_html=True)
    with k2:
        st.markdown(f"""
        <div class="kpi-card">
          <div class="kpi-label">Dött / slow-mover lager</div>
          <div class="kpi-value kpi-amber">{n_dott + df['slow_mover'].sum()}</div>
        </div>""", unsafe_allow_html=True)
    with k3:
        st.markdown(f"""
        <div class="kpi-card">
          <div class="kpi-label">Kapital i dött lager</div>
          <div class="kpi-value kpi-amber">{kap_dott:,.0f} kr</div>
        </div>""", unsafe_allow_html=True)
    with k4:
        st.markdown(f"""
        <div class="kpi-card">
          <div class="kpi-label">Extra SS-kapital som krävs</div>
          <div class="kpi-value kpi-blue">{extra_kap_ss:,.0f} kr</div>
        </div>""", unsafe_allow_html=True)
    with k5:
        st.markdown(f"""
        <div class="kpi-card">
          <div class="kpi-label">Akut inköpsbehov</div>
          <div class="kpi-value kpi-red">{tot_inkopsbehov:,.0f} kr</div>
        </div>""", unsafe_allow_html=True)

    # ── RISKFÖRDELNING ────────────────────────────────────────────────────────
    st.markdown('<div class="section-title">Riskfördelning</div>', unsafe_allow_html=True)

    risk_order  = ["KRITISK", "HÖG", "MEDEL", "LÅG"]
    risk_colors = {"KRITISK": "#e05252", "HÖG": "#e0a952", "MEDEL": "#e0c852", "LÅG": "#52a887"}
    risk_counts = df["risk"].value_counts().reindex(risk_order, fill_value=0).reset_index()
    risk_counts.columns = ["Risk", "Antal"]

    chart_cols = st.columns(len(risk_order))
    for col, (_, row) in zip(chart_cols, risk_counts.iterrows()):
        pct_r = int(row["Antal"] / len(df) * 100)
        color = risk_colors[row["Risk"]]
        col.markdown(f"""
        <div style="background:#1a1a1a;border:1px solid #2a2a2a;border-top:3px solid {color};
                    border-radius:4px;padding:1rem;text-align:center;">
          <div style="font-size:0.7rem;text-transform:uppercase;letter-spacing:0.12em;color:#666;">{row['Risk']}</div>
          <div style="font-family:'DM Mono',monospace;font-size:2rem;font-weight:500;color:{color};">{row['Antal']}</div>
          <div style="font-family:'DM Mono',monospace;font-size:0.8rem;color:#555;">{pct_r}% av artiklar</div>
        </div>""", unsafe_allow_html=True)

    # ── STOCKOUT-RISK TABELL ──────────────────────────────────────────────────
    st.markdown('<div class="section-title">Artiklar i stockout-risk</div>', unsafe_allow_html=True)

    df_stockout = df[df["stockout_risk"]].copy()
    if len(df_stockout) > 0:
        display_so = df_stockout[[
            "artikel_nr", "beskrivning", "abc_klass", "risk",
            "dos", "lead_time_dagar", "lead_time_ny",
            "lager_saldo", "rop_ny", "inkopsbehov_antal", "inkopsbehov_sek"
        ]].copy()
        display_so.columns = [
            "Artikel", "Beskrivning", "ABC", "Risk",
            "DOS (dagar)", "LT original", "LT nytt (scenario)",
            "Saldo", "ROP nytt", "Inköp (antal)", "Akut inköp (SEK)"
        ]
        display_so["DOS (dagar)"]        = display_so["DOS (dagar)"].round(1)
        display_so["LT nytt (scenario)"] = display_so["LT nytt (scenario)"].round(0).astype(int)
        display_so["ROP nytt"]           = display_so["ROP nytt"].round(0).astype(int)
        display_so["Inköp (antal)"]      = display_so["Inköp (antal)"].round(0).astype(int)
        display_so["Akut inköp (SEK)"]   = display_so["Akut inköp (SEK)"].apply(lambda x: f"{x:,.0f}")
        display_so = display_so.sort_values("Risk")
        st.dataframe(display_so, use_container_width=True, hide_index=True)
    else:
        st.markdown('<div class="info-box">Inga artiklar i stockout-risk under detta scenario.</div>',
                    unsafe_allow_html=True)

    # ── DÖTT LAGER ────────────────────────────────────────────────────────────
    st.markdown('<div class="section-title">Överlager & dött lager</div>', unsafe_allow_html=True)

    df_dott = df[df["dott_lager"] | df["slow_mover"]].copy()
    if len(df_dott) > 0:
        df_dott["Status"] = np.where(df_dott["dott_lager"], "DÖTT LAGER", "SLOW MOVER")
        display_d = df_dott[[
            "artikel_nr", "beskrivning", "abc_klass", "Status",
            "dagar_utan_rorelse", "lager_saldo", "kapital_sek"
        ]].copy()
        display_d.columns = ["Artikel", "Beskrivning", "ABC", "Status",
                              "Dagar utan rörelse", "Saldo", "Kapital (SEK)"]
        display_d["Kapital (SEK)"] = display_d["Kapital (SEK)"].apply(lambda x: f"{x:,.0f}")
        st.dataframe(display_d, use_container_width=True, hide_index=True)

        tot_dott = df_dott["kapital_sek"].sum()
        st.markdown(f"""
        <div class="info-box">
        Totalt kapital bundet i dött lager / slow movers: <strong>{tot_dott:,.0f} SEK</strong>
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown('<div class="info-box">Inga slow movers eller dött lager identifierat.</div>',
                    unsafe_allow_html=True)

    # ── REKOMMENDERADE SÄKERHETSLAGERNIVÅER ──────────────────────────────────
    st.markdown('<div class="section-title">Rekommenderade säkerhetslagernivåer</div>',
                unsafe_allow_html=True)

    display_ss = df[[
        "artikel_nr", "beskrivning", "abc_klass",
        "lead_time_dagar", "lead_time_ny",
        "ss_original", "ss_ny", "ss_delta",
        "rop_original", "rop_ny", "extra_ss_kapital_sek"
    ]].copy()
    display_ss.columns = [
        "Artikel", "Beskrivning", "ABC",
        "LT original (d)", "LT nytt (d)",
        "SS original", "SS nytt", "SS delta",
        "ROP original", "ROP nytt", "Extra kapital (SEK)"
    ]
    for col in ["SS original","SS nytt","SS delta","ROP original","ROP nytt"]:
        display_ss[col] = display_ss[col].round(0).astype(int)
    display_ss["LT nytt (d)"] = display_ss["LT nytt (d)"].round(0).astype(int)
    display_ss["Extra kapital (SEK)"] = display_ss["Extra kapital (SEK)"].apply(lambda x: f"{x:,.0f}")
    st.dataframe(display_ss, use_container_width=True, hide_index=True)

    # ── ABC-AVVIKELSE ─────────────────────────────────────────────────────────
    df_abc_diff = df[df["abc_klass"] != df["abc_beraknad"]][
        ["artikel_nr", "beskrivning", "abc_klass", "abc_beraknad", "forbrukning_arsv"]
    ].copy()
    if len(df_abc_diff) > 0:
        st.markdown('<div class="section-title">ABC-avvikelser (inmatad vs beräknad)</div>',
                    unsafe_allow_html=True)
        df_abc_diff.columns = ["Artikel", "Beskrivning", "ABC (inmatad)", "ABC (beräknad)", "Årsförbrukning (SEK)"]
        df_abc_diff["Årsförbrukning (SEK)"] = df_abc_diff["Årsförbrukning (SEK)"].apply(lambda x: f"{x:,.0f}")
        st.dataframe(df_abc_diff, use_container_width=True, hide_index=True)
        st.markdown("""
        <div class="info-box">
        ABC beräknas på årsförbrukningsvärde (efterfrågan/dag × 365 × pris).
        Avvikelser kan indikera felaktig manuell klassificering.
        </div>""", unsafe_allow_html=True)

    # ── EXPORT ────────────────────────────────────────────────────────────────
    st.markdown('<div class="section-title">Exportera</div>', unsafe_allow_html=True)

    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Rådata + beräkningar", index=False)
        if len(df_stockout) > 0:
            df_stockout.to_excel(writer, sheet_name="Stockout-risk", index=False)
        if len(df_dott) > 0:
            df_dott.to_excel(writer, sheet_name="Dött lager", index=False)
        display_ss.to_excel(writer, sheet_name="Säkerhetslagernivåer", index=False)

    scenario_slug = scenario.split("—")[0].strip().replace(" ", "_").lower()
    st.download_button(
        "⬇ Ladda ned analysrapport (Excel)",
        out.getvalue(),
        f"riskkompass_{scenario_slug}.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    st.markdown("""
    <div style='margin-top:3rem;font-family:DM Mono,monospace;font-size:0.7rem;color:#333;'>
    SCM International · David Leifsson · Riskkompass · Hormuz/Röda havet-scenario 2026
    </div>""", unsafe_allow_html=True)

else:
    st.markdown("""
    <div class="info-box" style="margin-top:2rem;">
    Ladda upp en fil eller fyll i manuell data och klicka "Kör analys →" för att se resultaten.
    </div>""", unsafe_allow_html=True)
