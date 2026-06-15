"""Diagnose → Decline & EUR — Arps fit, type-curve benchmark, prodpy Monte-Carlo
P90/P50/P10 bands, and probabilistic NPV on the session price deck.

The synthetic well_0NN fleet is the product default; real Colorado ECMC production
is available from the sidebar data-source toggle. The deterministic fit goes through
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

# numpy 2.x removed np.trapz (renamed to np.trapezoid); the repo runs numpy 2.4.6 on
# Python 3.11. Bind the available name once so the EUR integral never AttributeErrors.
_trapezoid = getattr(np, "trapezoid", None) or np.trapz


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
        {"label": "qᵢ (full-history fit)", "value": f"{fit.qi:,.0f} BOPD"},
        {"label": "b (full-history fit)", "value": f"{fit.b:.2f}"},
        {"label": "R² (full-history fit)", "value": f"{fit.r_squared:.3f}"},
        {"label": "Days On Production", "value": f"{int(hist['day'].iloc[-1]):,}"},
    ])
    # The page shows THREE Arps fits with their own (qi, b, R²) — label which is which so
    # the numbers never read as one contradictory set (audit finding):
    #   1. KPI above   = full-HISTORY hyperbolic fit (core.decline_fit_for).
    #   2. dashed line = early/established-points TYPE CURVE (a deliberately different fit
    #      so a degraded tail doesn't drag the benchmark down).
    #   3. P-fan below = prodpy Monte-Carlo fit (its own R², reported with the fan).
    st.caption(
        "Three fits, three purposes: the KPIs above are the **full-history** hyperbolic "
        "fit; the dashed **type curve** is fit on early/established points only (the "
        "benchmark); the **Monte-Carlo fan** below carries its own prodpy fit R². They "
        "differ by design — they are not the same fit reported three ways.")

    # ---- decline plot vs type curve -------------------------------------------
    pt.section("Production Decline Vs. Type Curve",
               "The dashed type curve is fit on the established early decline and "
               "extended PAST the last actual — it is not dragged down by a degraded tail.")
    # Extrapolate the type curve a few years PAST the last actual so the dashed line is
    # genuinely a forward type curve, not just an over-history overlay (audit finding).
    last_actual_day = float(hist["day"].max())
    fwd_to = last_actual_day + 5 * 365.0
    days_dense = np.linspace(float(hist["day"].min()), fwd_to, 180)
    curve_qi, curve_di, curve_b = (tc.qi, tc.di, tc.b) if tc else (fit.qi, fit.di, fit.b)
    fit_curve = curve_qi / np.power(
        1 + curve_b * curve_di * days_dense, 1 / max(curve_b, 1e-6))
    tc_label = (f"Type curve (b={curve_b:.2f}, fit on first {tc.established_days} pts)"
                if tc else f"Full-history fit (b={fit.b:.2f}, R²={fit.r_squared:.3f})")

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hist["day"], y=hist["oil_bopd"],
                             mode="markers+lines", name="Actual oil rate",
                             marker=dict(size=7, color=theme.BLUE),
                             line=dict(color=theme.BLUE, width=1.5)))
    fig.add_trace(go.Scatter(x=days_dense, y=fit_curve, mode="lines", name=tc_label,
                             line=dict(color=theme.AMBER, width=2, dash="dash")))
    fig.add_vline(x=last_actual_day, line=dict(color=theme.GREY, width=1, dash="dot"),
                  annotation_text="last actual", annotation_position="top")
    fig.update_layout(xaxis_title="Days on production",
                      yaxis_title="Oil rate (BOPD)", hovermode="x unified")
    st.plotly_chart(theme.style_fig(fig, height=360), width="stretch")
    note_tc = ("the dashed type curve is fit on early/established points and extended "
               "5 yr past the last actual." if tc else
               "with no separable established-tail (≤ a handful of points), the dashed "
               "line is the full-history fit extended forward — the early-points type "
               "curve benchmark is unavailable for this well.")
    theme.source_note(
        "Hyperbolic Arps decline fit (pec analyzer, non-linear least squares); "
        f"{note_tc} Rates in BOPD vs. days on production.")
    if tc is None:
        st.caption("⚠️ Type-curve benchmark unavailable (this well lacks enough "
                   "established early points to fit a separate type curve), so the "
                   "‘vs type curve’ deviation and deferred-barrels readouts are omitted.")

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
            # Anchor the fan to the last OBSERVED day: the band starts from the last
            # valid-rate day, which on a shut-in-tail well sits months before the last
            # actual point — so the forecast would visibly backtrack under the markers.
            last_day = float(hist["day"].max())
            fan_days = np.asarray(fb.days, dtype=float)
            m = fan_days >= last_day
            if int(m.sum()) < 2:  # degenerate — show the whole fan rather than nothing
                m = np.ones_like(fan_days, dtype=bool)
            fd = fan_days[m]
            p10 = np.asarray(fb.p10_rate, float)[m]
            p50 = np.asarray(fb.p50_rate, float)[m]
            p90 = np.asarray(fb.p90_rate, float)[m]

            fig_fan = go.Figure()
            fig_fan.add_trace(go.Scatter(x=hist["day"], y=hist["oil_bopd"],
                                         mode="markers", name="Actual oil rate",
                                         marker=dict(size=6, color=theme.BLUE)))
            fig_fan.add_trace(go.Scatter(x=fd, y=p10, mode="lines",
                                         name="P10 (optimistic)",
                                         line=dict(color=theme.GREEN, width=1)))
            fig_fan.add_trace(go.Scatter(x=fd, y=p90, mode="lines",
                                         name="P90 (conservative)",
                                         line=dict(color=theme.RED, width=1),
                                         fill="tonexty",
                                         fillcolor="rgba(79,129,189,0.20)"))
            fig_fan.add_trace(go.Scatter(x=fd, y=p50, mode="lines",
                                         name="P50 (median)",
                                         line=dict(color=theme.AMBER, width=2)))
            fig_fan.update_layout(title="P10/P50/P90 Rate Fan",
                                  xaxis_title="Days on production",
                                  yaxis_title="Oil rate (BOPD)",
                                  hovermode="x unified")
            st.plotly_chart(theme.style_fig(fig_fan, height=340), width="stretch")
            econ_lim = float(core.pec_assumptions.ECONOMIC_LIMIT_BOPD)
            theme.source_note(
                "Arps decline fit with Monte-Carlo P90/P50/P10 bands (prodpy, "
                f"R²={fb.r_squared:.3f}, seed 42). The rate fan starts at the last "
                f"observed point and is drawn to where the P50 path reaches the "
                f"{econ_lim:.0f} BOPD economic limit (its visual endpoint).")
        with eur_col:
            # EUR reconciliation (audit): the prodpy EUR percentiles integrate the FULL
            # forecast horizon, but the fan is shown only to the economic limit — so a PE
            # reading "P50 EUR" off a fan that stops at the econ limit would mis-read it.
            # Show BOTH, clearly labeled: the reserves-style EUR-to-economic-limit on the
            # P50 path (history cum + ∫P50 over the displayed-to-econ-limit fan), and the
            # full-horizon percentile EURs.
            econ_fc_cum = float(_trapezoid(np.asarray(fb.p50_rate, float),
                                           np.asarray(fb.days, float)))
            eur_p50_econ = fb.cum_history_bbl + max(econ_fc_cum, 0.0)
            st.metric("EUR P50 — to economic limit",
                      f"{eur_p50_econ/1000:,.0f} MBO",
                      help=f"Reserves-style: history cum + ∫P50 forecast to the "
                           f"{core.pec_assumptions.ECONOMIC_LIMIT_BOPD:.0f} BOPD econ "
                           "limit (the fan's endpoint).")
            pt.kpi_row([
                {"label": "EUR P90 (full horizon)", "value": f"{fb.eur_p90/1000:,.0f} MBO",
                 "help": "Conservative — 90% chance of exceeding; integrates the full "
                         "Monte-Carlo horizon (no econ-limit cut)"},
                {"label": "EUR P50 (full horizon)", "value": f"{fb.eur_p50/1000:,.0f} MBO"},
                {"label": "EUR P10 (full horizon)", "value": f"{fb.eur_p10/1000:,.0f} MBO",
                 "help": "Optimistic — 10% chance of exceeding; full horizon"},
            ])
            st.caption(
                f"History cum ≈ {fb.cum_history_bbl/1000:,.0f} MBO. The econ-limit EUR is "
                "the bookable number; the full-horizon percentile EURs integrate every "
                "sampled curve to the model horizon (they sit above the econ-limit EUR). "
                "History cum is a trapezoidal integral of the reported monthly stream — "
                "on a gappy/shut-in tail treat it as approximate.")

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
