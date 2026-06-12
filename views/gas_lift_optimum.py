"""Optimize → Gas-Lift Optimum — GLPC fit, economic curve, and the analytical
optimum for the selected well (wells with injection-survey data).

Math is gla.glpc (vendored byte-identical): exponential-plateau GLPC fit and the
closed-form optimum Qinj* = ln[(q_max − q_sl)·a·(1−wc)·price·nri / gas_cost] / a.
"""
from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
import streamlit as st

import core
import product_theme as pt
import theme

from views import _common


def render() -> None:
    _common.ensure_state()
    pt.masthead("workbench", "Gas-Lift Optimum",
                "Where marginal oil revenue meets marginal gas cost — the economic "
                "injection rate for the selected well")
    _common.context()
    theme.data_badge(
        "synthetic",
        "20-well synthetic gas-lift fleet with embedded injection surveys and known "
        "ground-truth optima.")

    oil_price, nri, _disc = _common.deck()
    gas_cost = float(st.session_state.setdefault("gas_cost", 1.50))
    gas_cost = st.slider("Injection Gas Cost ($/Mscf)", 0.25, 6.0, gas_cost, 0.25,
                         key="gas_cost")

    fleet = _common.gla_fleet_cached()
    wid = _common.current_well()
    if wid not in fleet:
        pt.empty_state(
            f"{wid} has no injection-survey data — the gas-lift lens needs the "
            "synthetic injection fleet (well_001–well_020). Real Colorado monthly "
            "filings carry no injection surveys.",
            "Pick a well with the Injection flag in the Well Browser.")
        return

    df_w = fleet[wid]
    params, wc, cur_inj, opt = core.analyze_gla_well(df_w, oil_price, gas_cost, nri)
    cur_liq = float(core.gla_glpc.glpc_rate(cur_inj, params))
    cur_oil = cur_liq * (1.0 - wc)
    cur_rev = float(core.gla_glpc.net_revenue_daily(cur_inj, params, wc,
                                                    oil_price, gas_cost, nri))
    daily_gain = opt.net_revenue_per_day - cur_rev
    delta_inj = opt.q_inj_opt - cur_inj
    direction = ("Reduce" if delta_inj < -0.05
                 else ("Increase" if delta_inj > 0.05 else "Maintain"))
    status = ("Over-injected" if cur_inj > opt.q_inj_opt + 0.05
              else ("Under-injected" if opt.q_inj_opt - cur_inj > 0.05
                    else "At optimum"))

    pt.kpi_row([
        {"label": "Current Injection", "value": f"{cur_inj:.2f} Mscfd"},
        {"label": "Optimal Injection", "value": f"{opt.q_inj_opt:.2f} Mscfd",
         "delta": f"{delta_inj:+.2f} Mscfd"},
        {"label": "Oil At Optimum", "value": f"{opt.q_oil_opt:,.0f} BOPD",
         "delta": f"{opt.q_oil_opt - cur_oil:+,.0f} BOPD"},
        {"label": "Daily Gain", "value": f"${daily_gain:,.0f}/day",
         "delta": f"${daily_gain*365/1e6:.2f}MM/yr"},
        {"label": "GLPC Fit R²", "value": f"{params.r2:.3f}"},
    ])
    theme.flag(status, {"Over-injected": "high", "Under-injected": "warn",
                        "At optimum": "ok"}.get(status, "ok"))

    # ---- injection history -------------------------------------------------------
    fig_hist = go.Figure()
    fig_hist.add_trace(go.Scatter(x=df_w["date"], y=df_w["injection_gas_mcfd"],
                                  mode="lines", name="Injection rate",
                                  line=dict(color=theme.BLUE, width=1.5)))
    fig_hist.add_hline(y=opt.q_inj_opt,
                       line=dict(color=theme.GREEN, width=1.5, dash="dot"),
                       annotation_text=f"Opt {opt.q_inj_opt:.2f} Mscfd",
                       annotation_position="right")
    fig_hist.add_hline(y=cur_inj, line=dict(color=theme.AMBER, width=1.2, dash="dash"),
                       annotation_text=f"Avg {cur_inj:.2f} Mscfd",
                       annotation_position="right")
    fig_hist.update_layout(title=f"{wid} — Injection Rate History (Survey Embedded)",
                           xaxis_title="Date", yaxis_title="Injection gas (Mscfd)")
    st.plotly_chart(theme.style_fig(fig_hist, height=230), width="stretch")

    col_left, col_right = st.columns(2)
    q_range = np.linspace(0, max(opt.q_inj_display_max, cur_inj * 1.5), 200)
    with col_left:
        q_liq_curve = core.gla_glpc.glpc_rate(q_range, params)
        fig_glpc = go.Figure()
        fig_glpc.add_trace(go.Scatter(
            x=df_w["injection_gas_mcfd"], y=(df_w["bopd"] + df_w["bwpd"]),
            mode="markers", name="Field data",
            marker=dict(color=theme.GREY, size=5, opacity=0.6)))
        fig_glpc.add_trace(go.Scatter(x=q_range, y=q_liq_curve, mode="lines",
                                      name=f"GLPC fit (R²={params.r2:.3f})",
                                      line=dict(color=theme.BLUE, width=2)))
        fig_glpc.add_trace(go.Scatter(x=[opt.q_inj_opt], y=[opt.q_liq_opt],
                                      mode="markers",
                                      name=f"Optimal ({opt.q_inj_opt:.2f} Mscfd)",
                                      marker=dict(color=theme.GREEN, size=14,
                                                  symbol="star")))
        fig_glpc.add_trace(go.Scatter(
            x=[cur_inj], y=[float(core.gla_glpc.glpc_rate(cur_inj, params))],
            mode="markers", name=f"Current ({cur_inj:.2f} Mscfd)",
            marker=dict(color=theme.AMBER, size=10, symbol="diamond")))
        fig_glpc.update_layout(title="Gas-Lift Performance Curve",
                               xaxis_title="Injection gas (Mscfd)",
                               yaxis_title="Gross liquid (bopd)")
        st.plotly_chart(theme.style_fig(fig_glpc, height=330), width="stretch")
        theme.source_note(f"q_sl={params.q_sl:.0f} bopd · q_max={params.q_max:.0f} "
                          f"bopd · a={params.a:.3f} Mscfd⁻¹ (nonlinear least squares).")
    with col_right:
        net_rev = core.gla_glpc.net_revenue_daily(q_range, params, wc,
                                                  oil_price, gas_cost, nri)
        fig_econ = go.Figure()
        fig_econ.add_trace(go.Scatter(x=q_range, y=net_rev, mode="lines",
                                      name="Net revenue/day",
                                      line=dict(color=theme.BLUE, width=2),
                                      fill="tozeroy",
                                      fillcolor="rgba(79,129,189,0.08)"))
        fig_econ.add_trace(go.Scatter(x=[opt.q_inj_opt], y=[opt.net_revenue_per_day],
                                      mode="markers",
                                      name=f"Optimal ${opt.net_revenue_per_day:,.0f}/day",
                                      marker=dict(color=theme.GREEN, size=14,
                                                  symbol="star")))
        fig_econ.add_trace(go.Scatter(x=[cur_inj], y=[cur_rev], mode="markers",
                                      name=f"Current ${cur_rev:,.0f}/day",
                                      marker=dict(color=theme.AMBER, size=10,
                                                  symbol="diamond")))
        fig_econ.add_hline(y=0, line=dict(color=theme.RED, width=1, dash="dot"))
        fig_econ.update_layout(title="Net Revenue Vs. Injection Rate",
                               xaxis_title="Injection gas (Mscfd)",
                               yaxis_title="Net revenue ($/day)")
        st.plotly_chart(theme.style_fig(fig_econ, height=330), width="stretch")
        theme.source_note(
            "Net revenue = BOPD × (1 − WC) × price × NRI − Qinj × gas_cost; optimum "
            "from dNet/dQinj = 0 (closed form, no search).")

    pt.section("Recommendation")
    rec_kind = {"Reduce": "bad", "Increase": "warn", "Maintain": "ok"}[direction]
    st.markdown(
        f"{pt.pill(direction + ' injection', rec_kind)} "
        f"**{cur_inj:.2f} → {opt.q_inj_opt:.2f} Mscfd** · expected "
        f"**{opt.q_oil_opt:.0f} BOPD** (from {cur_oil:.0f}) · daily net revenue "
        f"**${opt.net_revenue_per_day:,.0f}/day** (from ${cur_rev:,.0f}/day) · gain "
        f"**${daily_gain:,.0f}/day (${daily_gain*365/1e6:.2f}MM/yr)**.",
        unsafe_allow_html=True)
    st.caption("Derived analytically — marginal revenue set equal to marginal gas "
               "cost; pure petroleum-engineering math, no LLM.")
    theme.references(["gas_lift", "npv"])
