"""Forecasting engine against a tenant's OWN live data
(docs/FORECAST_SPEC.md Phase 10+, the live-tenant adapter every earlier
phase's docstring flagged as future work -- see forecasting/data_wms.py).

Same conceptual tabs as views/forecast_demo.py, computed LIVE (this
tenant's item count is small enough -- hundreds, not 3,000 -- that the
demo page's "precompute into small files" architecture isn't needed
here; the backtest itself is the slow part, ~1 minute for a few hundred
items with all 10 per-article models, cached per session via
st.cache_data so only the first tab visit pays that cost).

No "policy A (current ERP) vs policy B" comparison here, unlike Phase 7's
demo-set report -- forecasting/data_wms.py's own docstring explains why:
wms-app's live items table has no reorder_point/safety_stock/moq/
order_multiple concept of its own, so there is no real "policy A" to
compare against for a live tenant. The Policy & frontier tab here shows
only the frontier curve (policy B at different target service levels).
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

import auth
from components.i18n import get_lang, t
from forecasting.data import build_demand_series
from forecasting.data_wms import load_wms_tenant
from forecasting.explain import explain_policy
from forecasting.cleaning import flag_censored, flag_level_shifts, flag_one_off_large_orders, flag_outliers
from forecasting.backtest import run_backtest
from forecasting.models.baselines import (
    moving_average_forecast, naive_forecast, seasonal_naive_forecast, ses_forecast,
)
from forecasting.models.ensemble import select_best_model_per_segment, score_models_by_segment
from forecasting.models.intermittent import bootstrap_forecast, croston_forecast, sba_forecast, tsb_forecast
from forecasting.models.statistical import ets_forecast, theta_forecast
from forecasting.monitoring import detect_persistent_bias, generate_alerts, obsolescence_risk, rolling_error_by_origin
from forecasting.policy import compute_policy
from forecasting.probabilistic import build_supplier_lead_time_table, supplier_lead_time_samples
from forecasting.segmentation import build_segment_table
from forecasting.simulate import simulate_policy

QUANTILES = (0.05, 0.1, 0.5, 0.8, 0.9, 0.95)
FORECAST_HORIZONS = list(range(1, 14))
FRONTIER_SERVICE_LEVELS = [0.80, 0.85, 0.90, 0.95, 0.98]
FIXED_HORIZONS = (4, 13, 26)
ORIGIN_STEP = 26
MIN_TRAIN_PERIODS = 8

MODELS = {
    "naive": naive_forecast, "seasonal_naive": seasonal_naive_forecast,
    "moving_average": moving_average_forecast, "ses": ses_forecast,
    "croston": croston_forecast, "sba": sba_forecast, "tsb": tsb_forecast, "bootstrap": bootstrap_forecast,
    "ets": ets_forecast, "theta": theta_forecast,
}


@st.cache_data(show_spinner=False)
def _load_tenant_data(company_slug: str) -> dict:
    data = load_wms_tenant(company_slug)
    segment_table = build_segment_table(data["outbound"], data["items"], data["stock"])
    series = build_demand_series(data["outbound"], data["items"], freq="W")
    lt_table = build_supplier_lead_time_table(data["inbound"])
    return {**data, "segment_table": segment_table, "series": series, "lt_table": lt_table}


@st.cache_data(show_spinner=False)
def _run_backtest(company_slug: str) -> pd.DataFrame:
    data = _load_tenant_data(company_slug)
    return run_backtest(
        data["series"], data["items"], MODELS, fixed_horizons=FIXED_HORIZONS,
        min_train_periods=MIN_TRAIN_PERIODS, origin_step=ORIGIN_STEP, quantiles=QUANTILES,
    )


def _forecast_fan(train: pd.Series, model_fn) -> pd.DataFrame:
    rows = []
    for h in FORECAST_HORIZONS:
        result = model_fn(train, h, quantiles=QUANTILES)
        row = {"horizon": h, "point": result["point"]}
        for q in QUANTILES:
            row[f"q{int(round(q * 100))}"] = result["quantiles"].get(q, result["point"])
        rows.append(row)
    return pd.DataFrame(rows)


def _render_overview(data: dict) -> None:
    seg = data["segment_table"]
    col1, col2, col3 = st.columns(3)
    col1.metric(t("forecast.overview_items_metric"), len(data["items"]))
    col2.metric(t("forecast.overview_outbound_metric"), f"{len(data['outbound']):,}".replace(",", " "))
    col3.metric(t("forecast.overview_inbound_metric"), f"{len(data['inbound']):,}".replace(",", " "))

    st.subheader(t("forecast.overview_segment_header"))
    seg_counts = seg["sbc_class"].value_counts().sort_values(ascending=False)
    st.bar_chart(seg_counts)

    col4, col5 = st.columns(2)
    with col4:
        st.subheader(t("forecast.overview_abc_header"))
        st.bar_chart(seg["abc_class"].value_counts().sort_index())
    with col5:
        st.subheader(t("forecast.overview_lifecycle_header"))
        st.metric(t("forecast.overview_new_items_metric"), int(seg["is_new_item"].sum()))
        st.metric(t("forecast.overview_obsolete_metric"), int(seg["is_becoming_obsolete"].sum()))
        st.metric(t("forecast.overview_stale_metric"), int(seg["is_stale_with_stock"].sum()))


def _render_item_view(data: dict, company_slug: str) -> None:
    items, segment_table = data["items"], data["segment_table"]
    label_by_id = (items["article_id"] + " -- " + items["description"].fillna("")).to_dict()
    selected = st.selectbox(t("forecast.item_select_label"), list(items["article_id"]),
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

    with st.spinner(t("forecast.live_backtest_spinner")):
        backtest_results = _run_backtest(company_slug)
    scores = score_models_by_segment(backtest_results, data["segment_table"].set_index("article_id")["sbc_class"],
                                     quantile=0.9)
    selection = select_best_model_per_segment(scores, quantile=0.9)
    model_name = selection.get(seg_row["sbc_class"], "moving_average")
    if model_name not in MODELS:
        model_name = "moving_average"
    model_fn = MODELS[model_name]

    st.subheader(t("forecast.item_forecast_header"))
    st.caption(t("forecast.item_forecast_caption", model=model_name))
    train = history["qty_ordered"]
    fan = _forecast_fan(train, model_fn)
    last_period = history["period"].max()
    fan["period"] = fan["horizon"].apply(lambda h: last_period + pd.Timedelta(weeks=h))

    band = alt.Chart(fan).mark_area(opacity=0.25, color="#2F6FED").encode(x="period:T", y="q5:Q", y2="q95:Q")
    band2 = alt.Chart(fan).mark_area(opacity=0.35, color="#2F6FED").encode(x="period:T", y="q10:Q", y2="q90:Q")
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


def _render_backtest_tab(data: dict, company_slug: str) -> None:
    st.subheader(t("forecast.backtest_header"))
    st.caption(t("forecast.live_backtest_caption"))
    with st.spinner(t("forecast.live_backtest_spinner")):
        backtest_results = _run_backtest(company_slug)
    scores = score_models_by_segment(
        backtest_results, data["segment_table"].set_index("article_id")["sbc_class"], quantile=0.9,
    )
    scores = scores[scores["segment"] != "no_demand"]
    selection = select_best_model_per_segment(scores, quantile=0.9)
    for segment in sorted(scores["segment"].dropna().unique()):
        seg_scores = scores[scores["segment"] == segment].sort_values("pinball_q90")
        if seg_scores.empty:
            continue
        with st.expander(f"{segment} -- {t('forecast.item_forecast_caption', model=selection.get(segment, '?'))}"):
            st.dataframe(seg_scores, width="stretch", hide_index=True)


def _render_policy_tab(data: dict) -> None:
    st.subheader(t("forecast.policy_frontier_header"))
    st.caption(t("forecast.live_no_policy_a_caption"))
    items, segment_table = data["items"], data["segment_table"]
    series_by_article = {aid: g.sort_values("period")["qty_ordered"] for aid, g in data["series"].groupby("article_id")}

    frontier_rows = []
    for target in FRONTIER_SERVICE_LEVELS:
        fr_rows = []
        for _, item in items.iterrows():
            demand_periods = series_by_article.get(item["article_id"])
            if demand_periods is None or len(demand_periods) < 10:
                continue
            lead_samples = supplier_lead_time_samples(data["lt_table"], item["supplier_id"])
            policy = compute_policy(demand_periods, lead_samples, unit_cost=item["unit_cost_sek"],
                                    abc_class=None, margin_per_unit=None, n_simulations=150)
            # override the target service level for this sweep point
            from forecasting.probabilistic import lead_time_demand_distribution
            dist = lead_time_demand_distribution(demand_periods, lead_samples, quantiles=(target,), n_simulations=150)
            rp = dist["quantiles"][target]
            order_qty = policy["order_quantity"]
            if order_qty <= 0:
                continue
            sim = simulate_policy(demand_periods.to_numpy(), rp, order_qty, lead_samples, initial_stock=rp + order_qty)
            fr_rows.append({"fill_rate": sim["fill_rate"], "stock_value": sim["avg_stock"] * item["unit_cost_sek"],
                            "total_demand": sim["total_demand"]})
        fr_df = pd.DataFrame(fr_rows)
        total_demand = fr_df["total_demand"].sum()
        weighted_fill = (fr_df["fill_rate"] * fr_df["total_demand"]).sum() / total_demand if total_demand else float("nan")
        frontier_rows.append({"target_service_level": target, "fill_rate": weighted_fill,
                              "stock_value": fr_df["stock_value"].sum()})

    frontier = pd.DataFrame(frontier_rows)
    chart = alt.Chart(frontier).mark_line(point=True, color="#5B6270").encode(
        x=alt.X("stock_value:Q", title=t("forecast.policy_stock_value_label")),
        y=alt.Y("fill_rate:Q", title=t("forecast.policy_fill_rate_label"), scale=alt.Scale(zero=False)),
        tooltip=["target_service_level", "fill_rate", "stock_value"],
    )
    st.altair_chart(chart.properties(height=350), width="stretch")


def _render_alerts_tab(data: dict, company_slug: str) -> None:
    st.subheader(t("forecast.live_alerts_header", n=len(data["items"])))
    with st.spinner(t("forecast.live_backtest_spinner")):
        backtest_results = _run_backtest(company_slug)

    ma_4w = backtest_results[(backtest_results["model"] == "moving_average") & (backtest_results["horizon_type"] == "4w")].copy()
    ma_4w["origin_period"] = pd.to_datetime(ma_4w["origin_period"])
    rolling = rolling_error_by_origin(ma_4w, window=4)
    bias_flags = detect_persistent_bias(rolling, bias_threshold=0.20, min_consecutive=3)
    bias_flagged = set(bias_flags["article_id"])

    series_for_shift = data["series"]
    shift_flags = flag_level_shifts(series_for_shift)
    shift_flagged = set(series_for_shift.loc[shift_flags, "article_id"].unique())

    series_by_article = {aid: g.sort_values("period")["qty_ordered"] for aid, g in data["series"].groupby("article_id")}
    alert_rows = []
    for _, row in data["segment_table"].iterrows():
        article_id = row["article_id"]
        history = series_by_article.get(article_id)
        if history is None or history.empty:
            continue
        pb = article_id in bias_flagged
        ds = article_id in shift_flagged
        forecast_point = tsb_forecast(history, horizon=4)["point"]
        risk = obsolescence_risk(bool(row["is_becoming_obsolete"]), forecast_point)
        pb_row = bias_flags[bias_flags["article_id"] == article_id].iloc[0].to_dict() if pb else None
        alert_rows.extend(generate_alerts(article_id, row.get("description"), pb_row, None, ds, risk))

    alerts = pd.DataFrame(alert_rows)
    if alerts.empty:
        st.info(t("forecast.alerts_none"))
        return
    severities = sorted(alerts["severity"].unique())
    chosen = st.multiselect(t("forecast.alerts_severity_filter"), severities, default=severities)
    filtered = alerts[alerts["severity"].isin(chosen)]
    st.dataframe(filtered if not filtered.empty else alerts.head(0), width="stretch", hide_index=True)


def _render_quality_tab(data: dict) -> None:
    st.subheader(t("forecast.live_quality_header", n=len(data["items"])))
    outbound, series = data["outbound"], data["series"]
    censored = flag_censored(outbound)
    outliers = flag_outliers(series)
    one_off = flag_one_off_large_orders(series)
    shifts = flag_level_shifts(series)

    col1, col2 = st.columns(2)
    col1.metric(t("forecast.quality_censored_metric"), f"{int(censored.sum())} / {len(censored)}")
    col1.metric(t("forecast.quality_outlier_metric"), int(outliers.sum()))
    col2.metric(t("forecast.quality_oneoff_metric"), int(one_off.sum()))
    n_shifted = series.loc[shifts, "article_id"].nunique() if shifts.any() else 0
    col2.metric(t("forecast.quality_shift_metric"), f"{n_shifted} / {data['items']['article_id'].nunique()}")
    st.caption(t("forecast.quality_caption"))


def render(user: auth.User) -> None:
    st.title(t("forecast.live_page_title"))
    st.caption(t("forecast.live_page_caption", company=user.company_name))

    with st.spinner(t("forecast.live_loading_spinner")):
        data = _load_tenant_data(user.company_slug)

    if data["items"].empty:
        st.info(t("common.need_items"))
        return
    if data["outbound"].empty:
        st.info(t("forecast.live_no_history_caption"))
        return

    tabs = st.tabs([
        t("forecast.tab_overview"), t("forecast.tab_item"), t("forecast.tab_backtest"),
        t("forecast.tab_policy"), t("forecast.tab_alerts"), t("forecast.tab_quality"),
    ])
    with tabs[0]:
        _render_overview(data)
    with tabs[1]:
        _render_item_view(data, user.company_slug)
    with tabs[2]:
        _render_backtest_tab(data, user.company_slug)
    with tabs[3]:
        _render_policy_tab(data)
    with tabs[4]:
        _render_alerts_tab(data, user.company_slug)
    with tabs[5]:
        _render_quality_tab(data)
