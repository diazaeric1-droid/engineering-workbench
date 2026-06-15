"""Predict → Run-Life — the genuine trained time-to-event model.

A discrete-time logistic hazard fit on the synthetic run-life ground truth
(right-censored healthy wells included), evaluated out-of-fold with proper
survival metrics: time-dependent C-index and Integrated Brier Score versus a
Kaplan–Meier baseline. The per-well curve's SHAPE is learned from data, not a
transform of the 30-day probability.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import core
import product_theme as pt
import theme

from views import _common


def _sync_rl_well() -> None:
    """Drive the GLOBAL selection from the in-page picker (scorable wells are always
    synthetic SCADA, so align the data source too)."""
    pick = st.session_state.get("rl_pick")
    if pick:
        st.session_state["data_source"] = "synthetic"
        st.session_state["well_id"] = pick


def render() -> None:
    _common.ensure_state()
    pt.masthead("workbench", "Run-Life",
                "Discrete-time survival model — per-well hazard, survival curve, "
                "and remaining-useful-life ranking")
    _common.context()
    theme.data_badge(
        "synthetic",
        "Trained on the synthetic run-life ground truth (time_to_event_days + "
        "right-censoring) the SCADA generator emits.")

    sm = _common.survival_model_cached()
    if sm is None:
        pt.empty_state("The trained time-to-event model is unavailable (run-life "
                       "labels missing) — re-run bootstrap to regenerate the "
                       "synthetic fleet.")
        return
    metrics = _common.survival_metrics_cached()

    if metrics:
        ibs_gain = (metrics["ibs_km_baseline"] - metrics["ibs"]) / metrics["ibs_km_baseline"]
        pt.kpi_row([
            {"label": "Time-Dependent C-Index", "value": f"{metrics['c_index']:.3f}",
             "help": "Out-of-fold Harrell's C generalised to censored data; 0.5 = chance"},
            {"label": "Integrated Brier Score", "value": f"{metrics['ibs']:.4f}",
             "delta": f"{ibs_gain:+.0%} vs Kaplan–Meier",
             "help": f"KM baseline {metrics['ibs_km_baseline']:.4f}; lower is better"},
            {"label": "Wells / Events",
             "value": f"{metrics.get('n_wells', '—')} / {metrics.get('n_events', '—')}"},
        ])
        st.caption(
            "Out-of-fold survival metrics: the C-index orders comparable "
            "(earlier-failure vs later/censored) pairs correctly; the IBS beats the "
            "covariate-free Kaplan–Meier baseline, i.e. the covariates genuinely "
            "sharpen the curve.")

    features = _common.esp_features_cached()

    # ---- fleet RUL ranking -------------------------------------------------------
    pt.section("Fleet RUL Ranking — Soonest Failure First",
               "Median RUL = first day the projected survival S(t|x) crosses 50%.")
    table = core.esp_survival_model.fleet_survival_table(sm, features)
    top = table.head(12).iloc[::-1]

    # Absolute clinical RUL tiers (NOT min/max of the shown subset — a relative scale
    # painted a 45-day-RUL ESP green even though it is a near-term workover).
    def _rul_color(v: float) -> str:
        return theme.RED if v < 30 else (theme.AMBER if v < 60 else theme.GREEN)
    colors = [_rul_color(float(v)) for v in top["median_rul_days"]]
    rfig = go.Figure(go.Bar(x=top["median_rul_days"], y=top["well_id"],
                            orientation="h", marker_color=colors,
                            hovertemplate="%{y}: median RUL %{x:.0f}d<extra></extra>"))
    rfig.update_layout(title="Fleet RUL Ranking — Trained Hazard Model",
                       xaxis_title="Median remaining-useful-life (days)")
    st.plotly_chart(theme.style_fig(rfig, height=360, legend=False), width="stretch")
    theme.source_note(
        "Median RUL (days) per well from the trained discrete-time hazard model, "
        "soonest first. Color = absolute urgency: red < 30 d, amber 30–60 d, "
        "green > 60 d. Every well charted here crosses 50% survival within the model "
        "horizon — they are all workover candidates, ranked by lead time.")
    show = table.rename(columns={
        "well_id": "Well", "median_rul_days": "Median RUL (days)",
        "surv_at_horizon": f"Survival @ {sm.max_horizon}d"})
    # Right-censoring honesty (audit): wells whose median RUL never crosses 50% inside the
    # model horizon are pinned at the cap — flag them so the tail does not read as a fine
    # ranking ("13 of 25 tied at 90 d").
    show["Censored (≥ horizon)"] = show["Median RUL (days)"] >= sm.max_horizon
    n_cens = int(show["Censored (≥ horizon)"].sum())
    st.dataframe(
        show.head(25), width="stretch", hide_index=True,
        column_config={
            "Median RUL (days)": st.column_config.NumberColumn(format="%.0f"),
            "Censored (≥ horizon)": st.column_config.CheckboxColumn(
                f"≥ {sm.max_horizon}d (censored)", disabled=True),
            f"Survival @ {sm.max_horizon}d": st.column_config.ProgressColumn(
                min_value=0.0, max_value=1.0, format="%.2f")})
    if n_cens:
        st.caption(f"⚠️ {n_cens} well(s) are right-censored at the {sm.max_horizon}-day "
                   "horizon (survival never reaches 50% in-window) — their median RUL is "
                   f"a floor of ‘> {sm.max_horizon}d’, not a precise rank among themselves.")
    st.download_button("Download RUL Table (CSV)", data=show.to_csv(index=False),
                       file_name="workbench_run_life.csv", mime="text/csv")

    # ---- per-well survival + hazard ------------------------------------------------
    pt.section("Per-Well Survival & Hazard",
               "Pick any scorable well — defaults to your global selection when it "
               "has SCADA telemetry.")
    scorable = sorted(features.index)
    glob = _common.current_well()
    target = glob if glob in features.index else (scorable[0] if scorable else glob)
    if not scorable:
        pt.empty_state("No scorable SCADA wells in the fleet.")
        theme.references(["survival"])
        return
    rul_map = dict(zip(table["well_id"], table["median_rul_days"]))
    st.session_state["rl_pick"] = target
    wid = st.selectbox(
        "Well (scorable SCADA fleet)", scorable, key="rl_pick",
        format_func=lambda w: f"{w} — median RUL {int(rul_map.get(w, 0))}d",
        on_change=_sync_rl_well)
    if glob not in features.index:
        st.caption(f"The globally selected well has no SCADA telemetry, so this "
                   f"section is showing **{wid}**.")
    st.caption(
        "Headline C-index / IBS above are **out-of-fold** (held-out CV); the per-well "
        "curve and median RUL below are from the **full-fit** model (trained on the whole "
        "fleet) — standard practice, but they are not the same estimator, so read the "
        "metrics as the generalization claim and the curve as this well's fitted forecast.")

    # Failure-mode annotation, matching what the Failure-Risk page shows for the SAME well.
    try:
        mode, evidence = core.esp_explainer.classify_failure_mode(
            features.loc[wid].to_dict())
    except Exception:  # noqa: BLE001
        mode, evidence = None, ""

    days, surv_all = sm.survival_grid(features.loc[[wid]])
    surv = surv_all[0]
    hazard = sm.hazard_grid(features.loc[[wid]])[0]
    med_rul = int(sm.median_rul(features.loc[[wid]])[0])
    capped = med_rul >= sm.max_horizon

    cL, cR = st.columns(2)
    with cL:
        sfig = go.Figure()
        sfig.add_trace(go.Scatter(x=days, y=surv, mode="lines", name="S(t) survival",
                                  line=dict(color=theme.BLUE, width=3),
                                  hovertemplate="day %{x}: S=%{y:.0%}<extra></extra>"))
        sfig.add_hline(y=0.5, line_dash="dot", line_color=theme.GREY,
                       annotation_text="50%", annotation_position="right")
        if not capped:
            sfig.add_vline(x=med_rul, line_dash="dash", line_color=theme.RED,
                           annotation_text=f"median RUL ≈ {med_rul}d",
                           annotation_position="top")
        sfig.update_layout(title=f"Survival — {wid}",
                           xaxis_title="Run-days ahead",
                           yaxis_title="P(survives past day t)",
                           yaxis_range=[0, 1.02])
        st.plotly_chart(theme.style_fig(sfig, height=330), width="stretch")
    with cR:
        hfig = go.Figure()
        hfig.add_trace(go.Scatter(x=days, y=hazard, mode="lines",
                                  name="h(t|x) hazard",
                                  line=dict(color=theme.RED, width=2),
                                  hovertemplate="day %{x}: h=%{y:.2%}<extra></extra>"))
        hfig.update_layout(title=f"Daily Hazard — {wid}",
                           xaxis_title="Run-days ahead",
                           yaxis_title="P(fail on day t | survived to t)")
        st.plotly_chart(theme.style_fig(hfig, height=330), width="stretch")

    mc1, mc2 = st.columns(2)
    mc1.metric(f"Median RUL — {wid}",
               f">{sm.max_horizon}d (censored)" if capped else f"{med_rul} days")
    if mode:
        mc2.metric("Suspected Failure Mode", mode,
                   help="From the same deterministic classifier the Failure-Risk page "
                        "uses on this well's latest telemetry")
        if evidence:
            st.caption(f"**Mode evidence:** {evidence}")
    theme.source_note(
        "S(t|x) and h(t|x) from the discrete-time logistic hazard "
        "(person-period expansion; Singer & Willett 2003); median RUL = first day "
        "S(t) crosses 50%.")
    theme.references(["survival"])
