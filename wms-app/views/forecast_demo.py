"""Forecasting engine demo (docs/FORECAST_SPEC.md Phase 9): Overview,
Item view (history + forecast fan + policy explanation), Backtest by
segment vs baselines, Policy comparison & frontier, Alerts, Data quality.

Deliberately shows the SYNTHETIC demo dataset (datagen/v1, data/demo/),
not the logged-in company's own live tenant data -- forecasting/ has
stayed CSV-first through every phase so far (see forecasting/data.py's
own docstring: a live-SQLite-tenant adapter is explicitly out of scope
until a real tenant has enough history to be worth forecasting, Phase 10
territory). Loading the whole 3,000-item panel and the ~155MB Phase 4
backtest results on every page load would be far too slow for a live
page, so this reads small PRECOMPUTED summaries from data/phase9/ (see
scripts/prepare_phase9_artifacts.py) for every tab except Item view,
where computing one article's own forecast live is cheap.
"""

from __future__ import annotations

import json

import altair as alt
import pandas as pd
import streamlit as st

import auth
from components.i18n import get_lang, t
from forecasting.data import build_demand_series, load_items, load_outbound, load_stock
from forecasting.explain import explain_policy
from forecasting.models.baselines import (
    moving_average_forecast, naive_forecast, seasonal_naive_forecast, ses_forecast,
)
from forecasting.models.ensemble import select_best_model_per_segment
from forecasting.models.intermittent import bootstrap_forecast, croston_forecast, sba_forecast, tsb_forecast
from forecasting.models.statistical import ets_forecast, theta_forecast
from forecasting.policy import compute_policy
from forecasting.probabilistic import build_supplier_lead_time_table, supplier_lead_time_samples
from forecasting.segmentation import build_segment_table

QUANTILES = (0.05, 0.1, 0.5, 0.8, 0.9, 0.95)
FORECAST_HORIZONS = list(range(1, 14))  # 1..13 weeks ahead, for the item-view fan

MODELS = {
    "naive": naive_forecast, "seasonal_naive": seasonal_naive_forecast,
    "moving_average": moving_average_forecast, "ses": ses_forecast,
    "croston": croston_forecast, "sba": sba_forecast, "tsb": tsb_forecast, "bootstrap": bootstrap_forecast,
    "ets": ets_forecast, "theta": theta_forecast,
}
# global_gbm can win a segment in Phase 4's backtest but needs a panel-wide
# retrain per origin (see forecasting/backtest.py:run_global_backtest's own
# docstring) -- not something a single-article live page can call, so it is
# never in MODELS. Falling back silently to moving_average while still
# CAPTIONING the page as "global_gbm" would show a number that was never
# actually computed by the model named on screen -- FALLBACK_MODEL plus the
# explicit caption logic in _render_item_view() exists so the two always
# agree.
FALLBACK_MODEL = "moving_average"


@st.cache_data(show_spinner=False)
def _load_demo_data() -> dict:
    items = load_items("data/demo/artiklar.csv")
    outbound = load_outbound("data/demo/utleverans.csv")
    stock = load_stock("data/demo/lagersaldo_manadsslut.csv")
    from forecasting.data import load_inbound
    inbound = load_inbound("data/demo/inleverans.csv")
    segment_table = build_segment_table(outbound, items, stock)
    series = build_demand_series(outbound, items, freq="W")
    lt_table = build_supplier_lead_time_table(inbound)
    return {
        "items": items, "outbound": outbound, "stock": stock, "inbound": inbound,
        "segment_table": segment_table, "series": series, "lt_table": lt_table,
    }


@st.cache_data(show_spinner=False)
def _load_overview() -> dict:
    with open("data/phase9/overview.json") as f:
        return json.load(f)


@st.cache_data(show_spinner=False)
def _load_quality() -> dict:
    with open("data/phase9/data_quality.json") as f:
        return json.load(f)


@st.cache_data(show_spinner=False)
def _load_segment_scores() -> pd.DataFrame:
    return pd.read_csv("data/phase9/segment_scores.csv")


@st.cache_data(show_spinner=False)
def _load_alerts() -> pd.DataFrame:
    return pd.read_csv("data/phase9/alerts_sample.csv")


@st.cache_data(show_spinner=False)
def _load_frontier() -> pd.DataFrame:
    return pd.read_csv("data/phase7_frontier.csv")


def _render_overview() -> None:
    overview = _load_overview()
    col1, col2, col3 = st.columns(3)
    col1.metric(t("forecast.overview_items_metric"), overview["n_items"])
    col2.metric(t("forecast.overview_outbound_metric"), f"{overview['n_outbound_rows']:,}".replace(",", " "))
    col3.metric(t("forecast.overview_inbound_metric"), f"{overview['n_inbound_rows']:,}".replace(",", " "))

    st.subheader(t("forecast.overview_segment_header"))
    seg_df = pd.Series(overview["segment_counts"]).sort_values(ascending=False).reset_index()
    seg_df.columns = ["segment", "n_items"]
    st.bar_chart(seg_df.set_index("segment"))

    col4, col5 = st.columns(2)
    with col4:
        st.subheader(t("forecast.overview_abc_header"))
        abc_df = pd.Series(overview["abc_counts"]).sort_index().reset_index()
        abc_df.columns = ["abc_class", "n_items"]
        st.bar_chart(abc_df.set_index("abc_class"))
    with col5:
        st.subheader(t("forecast.overview_lifecycle_header"))
        st.metric(t("forecast.overview_new_items_metric"), overview["n_new_items"])
        st.metric(t("forecast.overview_obsolete_metric"), overview["n_becoming_obsolete"])
        st.metric(t("forecast.overview_stale_metric"), overview["n_stale_with_stock"])


def _forecast_fan(train: pd.Series, model_fn) -> pd.DataFrame:
    rows = []
    for h in FORECAST_HORIZONS:
        result = model_fn(train, h, quantiles=QUANTILES)
        row = {"horizon": h, "point": result["point"]}
        for q in QUANTILES:
            row[f"q{int(round(q * 100))}"] = result["quantiles"].get(q, result["point"])
        rows.append(row)
    return pd.DataFrame(rows)


def _render_item_view(data: dict) -> None:
    items, segment_table = data["items"], data["segment_table"]
    label_by_id = (items["article_id"] + " -- " + items["description"].fillna("")).to_dict()
    options = list(items["article_id"])
    selected = st.selectbox(t("forecast.item_select_label"), options,
                            format_func=lambda aid: label_by_id.get(aid, aid))

    item = items[items["article_id"] == selected].iloc[0]
    seg_row = segment_table[segment_table["article_id"] == selected].iloc[0]
    history = data["series"][data["series"]["article_id"] == selected].sort_values("period")

    if len(history) < 8:
        st.info(t("forecast.item_not_enough_history"))
        return

    st.subheader(t("forecast.item_history_header"))
    hist_chart_df = history[["period", "qty_ordered"]].rename(columns={"qty_ordered": "qty"})
    st.altair_chart(
        alt.Chart(hist_chart_df).mark_line(point=True).encode(
            x="period:T", y="qty:Q", tooltip=["period:T", "qty:Q"],
        ).properties(height=250),
        width="stretch",
    )

    scores = _load_segment_scores()
    selection = select_best_model_per_segment(scores, quantile=0.9)
    winning_model = selection.get(seg_row["sbc_class"], FALLBACK_MODEL)
    # winning_model may be "global_gbm" (a real Phase 4 winner for some
    # segments) or anything else not in MODELS -- the caption must name
    # whichever model actually ran, never the backtest's own winner if a
    # different one silently took its place.
    model_name = winning_model if winning_model in MODELS else FALLBACK_MODEL
    model_fn = MODELS[model_name]

    st.subheader(t("forecast.item_forecast_header"))
    if model_name == winning_model:
        st.caption(t("forecast.item_forecast_caption", model=model_name))
    else:
        st.caption(t("forecast.item_forecast_caption_fallback", winner=winning_model, model=model_name))
    train = history["qty_ordered"]
    fan = _forecast_fan(train, model_fn)
    last_period = history["period"].max()
    fan["period"] = fan["horizon"].apply(lambda h: last_period + pd.Timedelta(weeks=h))

    band = alt.Chart(fan).mark_area(opacity=0.25, color="#2F6FED").encode(
        x="period:T", y="q5:Q", y2="q95:Q",
    )
    band2 = alt.Chart(fan).mark_area(opacity=0.35, color="#2F6FED").encode(
        x="period:T", y="q10:Q", y2="q90:Q",
    )
    median = alt.Chart(fan).mark_line(color="#0E1526", strokeWidth=2).encode(
        x="period:T", y="q50:Q", tooltip=["period:T", "q50:Q", "q5:Q", "q95:Q"],
    )
    st.altair_chart((band + band2 + median).properties(height=280), width="stretch")

    st.subheader(t("forecast.item_policy_header"))
    lead_samples = supplier_lead_time_samples(data["lt_table"], item["supplier_id"])
    policy = compute_policy(
        train, lead_samples, unit_cost=item["unit_cost_sek"], abc_class=seg_row["abc_class"],
        moq=item["moq"], order_multiple=item["order_multiple"], n_simulations=300,
    )
    explanation = explain_policy(selected, item["description"], policy, seg_row["sbc_class"], train, lead_samples)
    st.info(explanation)


def _render_backtest_tab() -> None:
    st.subheader(t("forecast.backtest_header"))
    st.caption(t("forecast.backtest_caption"))
    scores = _load_segment_scores()
    scores = scores[scores["segment"] != "no_demand"]
    selection = select_best_model_per_segment(scores, quantile=0.9)
    for segment in ["smooth", "erratic", "intermittent", "lumpy"]:
        seg_scores = scores[scores["segment"] == segment].sort_values("pinball_q90")
        if seg_scores.empty:
            continue
        with st.expander(f"{segment} -- {t('forecast.item_forecast_caption', model=selection.get(segment, '?'))}"):
            st.dataframe(seg_scores, width="stretch", hide_index=True)


def _render_policy_tab() -> None:
    st.subheader(t("forecast.policy_frontier_header"))
    frontier = _load_frontier()
    numeric = frontier[~frontier["target_service_level"].isin(["policy_a", "policy_b"])].copy()
    numeric["fill_rate"] = numeric["fill_rate"].astype(float)
    numeric["stock_value"] = numeric["stock_value"].astype(float)
    points = frontier[frontier["target_service_level"].isin(["policy_a", "policy_b"])].copy()
    points["fill_rate"] = points["fill_rate"].astype(float)
    points["stock_value"] = points["stock_value"].astype(float)

    curve = alt.Chart(numeric).mark_line(point=True, color="#5B6270").encode(
        x=alt.X("stock_value:Q", title=t("forecast.policy_stock_value_label")),
        y=alt.Y("fill_rate:Q", title=t("forecast.policy_fill_rate_label"), scale=alt.Scale(zero=False)),
        tooltip=["target_service_level", "fill_rate", "stock_value"],
    )
    markers = alt.Chart(points).mark_point(size=200, filled=True, color="#E5484D").encode(
        x="stock_value:Q", y="fill_rate:Q", tooltip=["target_service_level", "fill_rate", "stock_value"],
    )
    st.altair_chart((curve + markers).properties(height=350), width="stretch")

    st.subheader(t("forecast.policy_comparison_header"))
    sim = pd.read_csv("data/phase7_simulation_results.csv")
    sim["stock_value_a"] = sim["avg_stock_a"] * sim["unit_cost"]
    sim["stock_value_b"] = sim["avg_stock_b"] * sim["unit_cost"]

    # Demand-weighted, matching CLAUDE.md's own Phase 7 report exactly --
    # a plain per-item mean() would silently give a DIFFERENT fill rate
    # number for the same segment (a low-volume item's 100% fill rate
    # would count as much as a high-volume item's 80%), which would make
    # this page contradict the numbers already reported to the user
    # elsewhere for no real reason.
    def _weighted_summary(df: pd.DataFrame) -> pd.Series:
        total_demand = df["total_demand"].sum()
        return pd.Series({
            "fill_rate_a": (df["fill_rate_a"] * df["total_demand"]).sum() / total_demand if total_demand else float("nan"),
            "fill_rate_b": (df["fill_rate_b"] * df["total_demand"]).sum() / total_demand if total_demand else float("nan"),
            "stock_value_a": df["stock_value_a"].sum(),
            "stock_value_b": df["stock_value_b"].sum(),
            "n_items": len(df),
        })

    summary = sim.groupby("sbc_class").apply(_weighted_summary, include_groups=False).reset_index()
    st.dataframe(summary, width="stretch", hide_index=True)


def _render_alerts_tab() -> None:
    st.subheader(t("forecast.alerts_header"))
    st.caption(t("forecast.alerts_caption"))
    alerts = _load_alerts()
    if alerts.empty:
        st.info(t("forecast.alerts_none"))
        return
    severities = sorted(alerts["severity"].unique())
    chosen = st.multiselect(t("forecast.alerts_severity_filter"), severities, default=severities)
    filtered = alerts[alerts["severity"].isin(chosen)]
    if filtered.empty:
        st.info(t("forecast.alerts_none"))
        return
    st.dataframe(filtered, width="stretch", hide_index=True)


def _render_quality_tab() -> None:
    st.subheader(t("forecast.quality_header"))
    quality = _load_quality()
    col1, col2 = st.columns(2)
    col1.metric(t("forecast.quality_censored_metric"),
               f"{quality['n_censored_lines']:,} / {quality['n_censored_total_lines']:,}".replace(",", " "))
    col1.metric(t("forecast.quality_outlier_metric"), quality["n_outlier_periods"])
    col2.metric(t("forecast.quality_oneoff_metric"), quality["n_one_off_periods"])
    col2.metric(t("forecast.quality_shift_metric"),
               f"{quality['n_articles_with_level_shift']} / {quality['n_total_articles']}")
    st.caption(t("forecast.quality_caption"))


def render(user: auth.User) -> None:
    st.title(t("forecast.page_title"))
    st.caption(t("forecast.demo_data_caption", company=user.company_name))

    data = _load_demo_data()
    tabs = st.tabs([
        t("forecast.tab_overview"), t("forecast.tab_item"), t("forecast.tab_backtest"),
        t("forecast.tab_policy"), t("forecast.tab_alerts"), t("forecast.tab_quality"),
    ])
    with tabs[0]:
        _render_overview()
    with tabs[1]:
        _render_item_view(data)
    with tabs[2]:
        _render_backtest_tab()
    with tabs[3]:
        _render_policy_tab()
    with tabs[4]:
        _render_alerts_tab()
    with tabs[5]:
        _render_quality_tab()
