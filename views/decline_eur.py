"""Diagnose → Decline & EUR — Arps fit, type-curve benchmark, prodpy Monte-Carlo
P90/P50/P10 bands, and probabilistic NPV on the session price deck.

REAL Colorado ECMC production is the product default (green badge); the synthetic
fleet is available from the same well selector. The deterministic fit goes through
``core.decline_fit_for`` — the view-layer wrapper the test suite pins as
numerically identical to calling pec's analyzer directly.
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
    pt.masthead("workbench", "Decline & EUR",
                "Hyperbolic Arps decline, type-curve deviation, and a seeded "
                "Monte-Carlo EUR / NPV fan for the selected well")
    _common.context()

    wid = _common.current_well()
    well = core.production_well(wid)
    if well is None:
        pt.empty_state(
            f"{wid} has no production history in the workbench — the decline lens "
            "needs monthly production (real Colorado wells or the synthetic "
            "well_0NN fleet).",
            "Pick a well with the Production flag in the Well Browser.")
        return

    _common.provenance_badge(wid)

    hist = pd.DataFrame(well.production_history)
    if len(hist) < 5:
        pt.empty_state(
            f"{wid} has only {len(hist)} production point(s) — too few for a "
            "hyperbolic decline fit (need ≥ 5).",
            "Pick a longer-history well in the Well Browser.")
        return

    fit = core.decline_fit_for(well)
    tc = None
    try:
        tc = core.pec_decline.analyze_type_curve(
            hist["day"].values, hist["oil_bopd"].values, model="hyperbolic")
    except Exception:  # noqa: BLE001 — short/odd histories
        tc = None

    latest_oil = float(hist["oil_bopd"].iloc[-1])
    pt.kpi_row([
        {"label": "Latest Oil Rate", "value": f"{latest_oil:,.0f} BOPD",
         "delta": (f"{latest_oil - tc.type_curve_at_last:+,.0f} vs type curve"
                   if tc else None)},
        {"label": "Initial Rate qᵢ", "value": f"{fit.qi:,.0f} BOPD"},
        {"label": "Hyperbolic b", "value": f"{fit.b:.2f}"},
        {"label": "Fit R²", "value": f"{fit.r_squared:.3f}"},
        {"label": "Days On Production", "value": f"{int(hist['day'].iloc[-1]):,}"},
    ])

    # ---- decline plot vs type curve -------------------------------------------
    pt.section("Production Decline Vs. Type Curve",
               "The dashed type curve is fit on the established early decline and "
               "extrapolated — it is not dragged down by a degraded tail.")
    days_dense = np.linspace(hist["day"].min(), hist["day"].max(), 100)
    curve_qi, curve_di, curve_b = (tc.qi, tc.di, tc.b) if tc else (fit.qi, fit.di, fit.b)
    fit_curve = curve_qi / np.power(
        1 + curve_b * curve_di * days_dense, 1 / max(curve_b, 1e-6))
    tc_label = (f"Type curve (b={curve_b:.2f}, fit on first {tc.established_days} pts)"
                if tc else f"Fit (b={fit.b:.2f}, R²={fit.r_squared:.3f})")

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hist["day"], y=hist["oil_bopd"],
                             mode="markers+lines", name="Actual oil rate",
                             marker=dict(size=7, color=theme.BLUE),
                             line=dict(color=theme.BLUE, width=1.5)))
    fig.add_trace(go.Scatter(x=days_dense, y=fit_curve, mode="lines", name=tc_label,
                             line=dict(color=theme.AMBER, width=2, dash="dash")))
    fig.update_layout(xaxis_title="Days on production",
                      yaxis_title="Oil rate (BOPD)", hovermode="x unified")
    st.plotly_chart(theme.style_fig(fig, height=360), width="stretch")
    theme.source_note(
        "Hyperbolic Arps decline fit (pec analyzer, non-linear least squares); the "
        "dashed type curve is fit on early/established points and extrapolated. "
        "Rates in BOPD vs. days on production.")

    if tc is not None:
        dev = tc.deviation_pct
        note = (f"Actual {tc.last_actual:.0f} BOPD vs type curve "
                f"{tc.type_curve_at_last:.0f} BOPD · deferred ≈ "
                f"{tc.deferred_bbl/1000:,.1f} MBO vs the early-time type curve.")
        if dev < -10:
            theme.flag(f"Underperforming type curve by {abs(dev):.0f}% — {note}", "high")
        elif dev > 10:
            theme.flag(f"Outperforming type curve by {dev:.0f}% — {note}", "ok")
        else:
            theme.flag(f"On type curve ({dev:+.1f}%) — {note}", "ok")

    # ---- Monte-Carlo bands + probabilistic NPV --------------------------------
    pt.section("Probabilistic Forecast — P90/P50/P10 (Monte-Carlo, prodpy)",
               "500 seeded Arps parameter draws; shaded band = P90–P10 rate fan. "
               "Reserves convention: P90 conservative ≤ P50 ≤ P10 (SPE-PRMS).")
    fb = _common.forecast_bands_cached(wid)
    if fb is None:
        pt.empty_state("Monte-Carlo bands unavailable for this well (prodpy fit "
                       "failed or the series is degenerate). The deterministic fit "
                       "above still stands.")
    else:
        fan_col, eur_col = st.columns([3, 2])
        with fan_col:
            fig_fan = go.Figure()
            fig_fan.add_trace(go.Scatter(x=hist["day"], y=hist["oil_bopd"],
                                         mode="markers", name="Actual oil rate",
                                         marker=dict(size=6, color=theme.BLUE)))
            fig_fan.add_trace(go.Scatter(x=fb.days, y=fb.p10_rate, mode="lines",
                                         name="P10 (optimistic)",
                                         line=dict(color=theme.GREEN, width=1)))
            fig_fan.add_trace(go.Scatter(x=fb.days, y=fb.p90_rate, mode="lines",
                                         name="P90 (conservative)",
                                         line=dict(color=theme.RED, width=1),
                                         fill="tonexty",
                                         fillcolor="rgba(79,129,189,0.20)"))
            fig_fan.add_trace(go.Scatter(x=fb.days, y=fb.p50_rate, mode="lines",
                                         name="P50 (median)",
                                         line=dict(color=theme.AMBER, width=2)))
            fig_fan.update_layout(title="P10/P50/P90 Rate Fan",
                                  xaxis_title="Days on production",
                                  yaxis_title="Oil rate (BOPD)",
                                  hovermode="x unified")
            st.plotly_chart(theme.style_fig(fig_fan, height=340), width="stretch")
            theme.source_note(
                "Arps decline fit with Monte-Carlo P90/P50/P10 bands (prodpy, "
                f"R²={fb.r_squared:.3f}, seed 42, truncated at the "
                f"{core.pec_assumptions.ECONOMIC_LIMIT_BOPD:.0f} BOPD economic limit).")
        with eur_col:
            pt.kpi_row([
                {"label": "EUR P90", "value": f"{fb.eur_p90/1000:,.0f} MBO",
                 "help": "Conservative — 90% chance of exceeding"},
                {"label": "EUR P50", "value": f"{fb.eur_p50/1000:,.0f} MBO"},
                {"label": "EUR P10", "value": f"{fb.eur_p10/1000:,.0f} MBO",
                 "help": "Optimistic — 10% chance of exceeding"},
            ])
            st.caption(f"History cum ≈ {fb.cum_history_bbl/1000:,.0f} MBO · "
                       f"forecast to {fb.days[-1]/365:,.1f} yr on production.")

            oil_price, nri, discount = _common.deck()
            try:
                eb = core.pec_economics_bands.economics_bands(
                    fb, price=oil_price, nri=nri,
                    opex_per_bbl=float(core.pec_assumptions.LOE_USD_PER_BBL),
                    discount_annual=discount)
            except Exception:  # noqa: BLE001
                eb = None
            if eb is not None:
                pt.kpi_row([
                    {"label": "NPV P90", "value": f"${eb['npv_p90_usd']/1e6:,.1f}MM"},
                    {"label": "NPV P50", "value": f"${eb['npv_p50_usd']/1e6:,.1f}MM"},
                    {"label": "NPV P10", "value": f"${eb['npv_p10_usd']/1e6:,.1f}MM"},
                ])
                st.caption(
                    f"PV of the forecast oil stream @ ${oil_price:,.0f}/bbl × "
                    f"{nri:.0%} NRI − ${core.pec_assumptions.LOE_USD_PER_BBL:,.0f}/bbl "
                    f"LOE, {discount:.0%} discount (pec economics convention). Values "
                    "the existing producing stream — no upfront capital.")

    theme.references(["arps", "dca_lib", "monte_carlo", "prms", "npv"])
