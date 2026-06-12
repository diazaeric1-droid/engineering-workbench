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
    rmin, rmax = top["median_rul_days"].min(), top["median_rul_days"].max()
    span = max(rmax - rmin, 1e-9)
    colors = [theme.RED if (v - rmin) / span < 0.34
              else (theme.AMBER if (v - rmin) / span < 0.67 else theme.GREEN)
              for v in top["median_rul_days"]]
    rfig = go.Figure(go.Bar(x=top["median_rul_days"], y=top["well_id"],
                            orientation="h", marker_color=colors,
                            hovertemplate="%{y}: median RUL %{x:.0f}d<extra></extra>"))
    rfig.update_layout(title="Fleet RUL Ranking — Trained Hazard Model",
                       xaxis_title="Median remaining-useful-life (days)")
    st.plotly_chart(theme.style_fig(rfig, height=360, legend=False), width="stretch")
    theme.source_note(
        "Median RUL (days) per well from the trained discrete-time hazard model, "
        "soonest first; bar color flags urgency (red = soonest).")
    st.dataframe(table.head(25), width="stretch", hide_index=True)

    # ---- per-well survival + hazard ------------------------------------------------
    wid = _common.current_well()
    pt.section("Per-Well Survival & Hazard")
    if wid not in features.index:
        pt.empty_state(
            f"{wid} is not scorable — the run-life lens needs fleet SCADA, which "
            "only the synthetic well_0NN fleet carries.",
            "Pick a SCADA well in the Well Browser.")
        theme.references(["survival"])
        return

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
                           xaxis_title="Days from today",
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
                           xaxis_title="Days from today",
                           yaxis_title="P(fail on day t | survived to t)")
        st.plotly_chart(theme.style_fig(hfig, height=330), width="stretch")

    st.metric(f"Median RUL — {wid}",
              f">{sm.max_horizon}d" if capped else f"{med_rul} days")
    theme.source_note(
        "S(t|x) and h(t|x) from the discrete-time logistic hazard "
        "(person-period expansion; Singer & Willett 2003); median RUL = first day "
        "S(t) crosses 50%.")
    theme.references(["survival"])
