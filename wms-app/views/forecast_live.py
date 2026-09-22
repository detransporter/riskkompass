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

# forecasting/monitoring.py's own type/severity strings are internal
# identifiers (matching its alert dicts' "type"/"severity" keys), not
# meant for display -- translated here, at the UI boundary, same
# principle components/sv.py already applies for the vendored analysis/
# modules' English status values.
ALERT_SEVERITY_LABELS = {
    "sv": {"critical": "Kritiskt", "warning": "Varning", "info": "Info"},
    "en": {"critical": "Critical", "warning": "Warning", "info": "Info"},
}
ALERT_TYPE_LABELS = {
    "sv": {
        "persistent_bias": "Prognosen träffar fel",
        "coverage_breach": "Osäkerheten stämmer inte",
        "demand_shift": "Efterfrågan har förändrats",
        "obsolescence_risk": "Risk för föråldrad artikel",
        "obsolescence_recovering": "Återhämtning upptäckt",
    },
    "en": {
        "persistent_bias": "Forecast is consistently off",
        "coverage_breach": "Uncertainty range is off",
        "demand_shift": "Demand has shifted",
        "obsolescence_risk": "Risk of obsolete item",
        "obsolescence_recovering": "Recovery detected",
    },
}


@st.cache_data(show_spinner=False)
def _load_tenant_data(company_slug: str) -> dict:
    data = load_wms_tenant(company_slug)
    segment_table = build_segment_table(data["outbound"], data["items"], data["stock"])
    series = build_demand_series(data["outbound"], data["items"], freq="W")
    lt_table = build_supplier_lead_time_table(data["inbound"])
    return {**data, "segment_table": segment_table, "series": series, "lt_table": lt_table}


@st.cache_data(show_spinner=False)
def _compute_order_recommendations(company_slug: str) -> pd.DataFrame:
    """One row per article: current stock, reorder point, recommended
    order quantity, and a traffic-light status -- the plain "what do I
    need to order" answer, no model names or statistical terms anywhere
    in this table. compute_policy() itself is unchanged (Phase 6); this
    just runs it for every article and packages the result for a
    non-technical reader. Fast enough (a few seconds for a few hundred
    items) to not need the ~1-minute backtest this page's other tabs
    depend on -- a purchasing manager should not have to wait for a
    statistical validation run just to see what to order today.
    """
    data = _load_tenant_data(company_slug)
    items, segment_table = data["items"], data["segment_table"]
    stock_by_article = data["stock"].set_index("article_id")["stock_qty"]
    series_by_article = {aid: g.sort_values("period")["qty_ordered"] for aid, g in data["series"].groupby("article_id")}

    rows = []
    for _, item in items.iterrows():
        article_id = item["article_id"]
        history = series_by_article.get(article_id)
        if history is None or len(history) < 8:
            continue
        seg_row = segment_table[segment_table["article_id"] == article_id]
        abc_class = seg_row.iloc[0]["abc_class"] if not seg_row.empty else None
        lead_samples = supplier_lead_time_samples(data["lt_table"], item["supplier_id"])
        policy = compute_policy(
            history, lead_samples, unit_cost=item["unit_cost_sek"], abc_class=abc_class,
            moq=item["moq"], order_multiple=item["order_multiple"], n_simulations=200,
        )
        current_stock = float(stock_by_article.get(article_id, 0.0))
        reorder_point = policy["reorder_point"]
        if current_stock <= reorder_point:
            status = "now"
        elif current_stock <= reorder_point * 1.3:
            status = "soon"
        else:
            status = "ok"
        rows.append({
            "article_id": article_id, "description": item["description"], "status": status,
            "current_stock": current_stock, "reorder_point": reorder_point,
            "order_quantity": policy["order_quantity"],
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    status_order = {"now": 0, "soon": 1, "ok": 2}
    df["_sort"] = df["status"].map(status_order)
    return df.sort_values("_sort").drop(columns="_sort").reset_index(drop=True)


def _render_policy_kpis(policy: dict, lead_samples) -> None:
    col1, col2, col3 = st.columns(3)
    col1.metric(t("forecast.kpi_reorder_point"), f"{policy['reorder_point']:.0f}")
    col2.metric(t("forecast.kpi_safety_stock"), f"{policy['safety_stock']:.0f}")
    col3.metric(t("forecast.kpi_order_qty"), f"{policy['order_quantity']:.0f}")
    col4, col5 = st.columns(2)
    col4.metric(t("forecast.kpi_service_level"), f"{policy['target_service_level']:.0%}")
    if len(lead_samples) >= 2:
        col5.metric(t("forecast.kpi_lead_time"), f"{int(min(lead_samples))}–{int(max(lead_samples))} d")


def _render_order_recommendations(data: dict, company_slug: str) -> None:
    st.subheader(t("forecast.orders_header"))

    with st.spinner(t("forecast.orders_spinner")):
        recs = _compute_order_recommendations(company_slug)
    if recs.empty:
        st.info(t("forecast.item_not_enough_history"))
        return

    status_label = {"now": t("forecast.orders_status_now"), "soon": t("forecast.orders_status_soon"),
                    "ok": t("forecast.orders_status_ok")}
    status_icon = {"now": "\U0001F534", "soon": "\U0001F7E1", "ok": "\U0001F7E2"}
    display = recs.copy()
    display["Status"] = display["status"].map(lambda s: f"{status_icon[s]} {status_label[s]}")
    display = display.rename(columns={
        "article_id": t("forecast.orders_col_article"), "description": t("forecast.orders_col_description"),
        "current_stock": t("forecast.orders_col_stock"), "reorder_point": t("forecast.orders_col_reorder_point"),
        "order_quantity": t("forecast.orders_col_order_qty"),
    })
    display = display[[t("forecast.orders_col_article"), t("forecast.orders_col_description"), "Status",
                       t("forecast.orders_col_stock"), t("forecast.orders_col_reorder_point"),
                       t("forecast.orders_col_order_qty")]]

    n_now = (recs["status"] == "now").sum()
    n_soon = (recs["status"] == "soon").sum()
    col1, col2, col3 = st.columns(3)
    col1.metric(status_label["now"], n_now)
    col2.metric(status_label["soon"], n_soon)
    col3.metric(status_label["ok"], (recs["status"] == "ok").sum())

    st.dataframe(display.round(0), width="stretch", hide_index=True)

    st.divider()
    items = data["items"]
    label_by_id = (items["article_id"] + " -- " + items["description"].fillna("")).to_dict()
    selected = st.selectbox(t("forecast.orders_explain_header"), list(recs["article_id"]),
                            format_func=lambda aid: label_by_id.get(aid, aid), key="orders_explain_select")
    item = items[items["article_id"] == selected].iloc[0]
    seg_row = data["segment_table"][data["segment_table"]["article_id"] == selected].iloc[0]
    series_by_article = {aid: g.sort_values("period")["qty_ordered"] for aid, g in data["series"].groupby("article_id")}
    history = series_by_article.get(selected)
    lead_samples = supplier_lead_time_samples(data["lt_table"], item["supplier_id"])
    policy = compute_policy(history, lead_samples, unit_cost=item["unit_cost_sek"], abc_class=seg_row["abc_class"],
                            moq=item["moq"], order_multiple=item["order_multiple"], n_simulations=200)
    _render_policy_kpis(policy, lead_samples)
    with st.expander(t("forecast.explain_details_label")):
        st.write(explain_policy(selected, item["description"], policy, seg_row["sbc_class"], history, lead_samples))


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

    st.subheader(t("forecast.item_forecast_header_simple"))
    train = history["qty_ordered"]
    fan = _forecast_fan(train, model_fn)
    last_period = history["period"].max()
    fan["period"] = fan["horizon"].apply(lambda h: last_period + pd.Timedelta(weeks=h))

    y_title = t("forecast.item_forecast_y_axis")
    band = alt.Chart(fan).mark_area(opacity=0.25, color="#2F6FED").encode(
        x=alt.X("period:T", title=None), y=alt.Y("q5:Q", title=y_title), y2="q95:Q")
    band2 = alt.Chart(fan).mark_area(opacity=0.35, color="#2F6FED").encode(
        x=alt.X("period:T", title=None), y=alt.Y("q10:Q", title=y_title), y2="q90:Q")
    median = alt.Chart(fan).mark_line(color="#0E1526", strokeWidth=2).encode(
        x=alt.X("period:T", title=None), y=alt.Y("q50:Q", title=y_title),
        tooltip=["period:T", "q50:Q", "q5:Q", "q95:Q"],
    )
    st.altair_chart((band + band2 + median).properties(height=280), width="stretch")

    st.subheader(t("forecast.item_policy_header"))
    lead_samples = supplier_lead_time_samples(data["lt_table"], item["supplier_id"])
    policy = compute_policy(
        train, lead_samples, unit_cost=item["unit_cost_sek"], abc_class=seg_row["abc_class"],
        moq=item["moq"], order_multiple=item["order_multiple"], n_simulations=300,
    )
    _render_policy_kpis(policy, lead_samples)
    with st.expander(t("forecast.explain_details_label")):
        st.write(explain_policy(selected, item["description"], policy, seg_row["sbc_class"], train, lead_samples))
        st.caption(t("forecast.item_forecast_caption", model=model_name))


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

    lang = get_lang()
    severity_labels = ALERT_SEVERITY_LABELS[lang]
    type_labels = ALERT_TYPE_LABELS[lang]
    alerts["severity_label"] = alerts["severity"].map(severity_labels).fillna(alerts["severity"])
    alerts["type_label"] = alerts["type"].map(type_labels).fillna(alerts["type"])

    severities = sorted(alerts["severity_label"].unique())
    chosen = st.multiselect(t("forecast.alerts_severity_filter"), severities, default=severities)
    filtered = alerts[alerts["severity_label"].isin(chosen)]
    display = (filtered if not filtered.empty else alerts.head(0))[["severity_label", "type_label", "message"]]
    display = display.rename(columns={
        "severity_label": t("forecast.alerts_col_severity"), "type_label": t("forecast.alerts_col_type"),
        "message": t("forecast.alerts_col_message"),
    })
    st.dataframe(display, width="stretch", hide_index=True)


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
        t("forecast.tab_orders"), t("forecast.tab_overview"), t("forecast.tab_item"),
        t("forecast.tab_backtest"), t("forecast.tab_policy"), t("forecast.tab_alerts"),
        t("forecast.tab_quality"),
    ])
    with tabs[0]:
        _render_order_recommendations(data, user.company_slug)
    with tabs[1]:
        _render_overview(data)
    with tabs[2]:
        _render_item_view(data, user.company_slug)
    with tabs[3]:
        st.caption(t("forecast.technical_tab_caption"))
        _render_backtest_tab(data, user.company_slug)
    with tabs[4]:
        st.caption(t("forecast.technical_tab_caption"))
        _render_policy_tab(data)
    with tabs[5]:
        _render_alerts_tab(data, user.company_slug)
    with tabs[6]:
        _render_quality_tab(data)
