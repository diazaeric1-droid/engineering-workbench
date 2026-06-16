"""Optimize → Gas-Lift Optimum — GLPC fit, economic curve, and the analytical
optimum for the selected well (wells with injection-survey data).

Math is gla.glpc (vendored byte-identical): exponential-plateau GLPC fit and the
closed-form optimum Qinj* = ln[(q_max − q_sl)·a·(1−wc)·price·nri / gas_cost] / a.
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


def _sync_gl_well() -> None:
    """Drive the GLOBAL selection from the in-page gas-lift picker. Gas-lift wells
    are always synthetic, so also align the data source so the sidebar selectbox
    keeps the pick (callback runs before the next run's widgets, so this is legal)."""
    pick = st.session_state.get("gl_pick")
    if pick:
        st.session_state["data_source"] = "synthetic"
        st.session_state["well_id"] = pick


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

    fleet = _common.gla_fleet_cached()
    inj_wells = sorted(fleet)
    if not inj_wells:
        pt.empty_state("The synthetic gas-lift fleet is unavailable — re-run "
                       "bootstrap to regenerate the injection surveys.")
        return

    # ---- in-page well picker (request #3b): always lands on an analyzable well ---
    glob = _common.current_well()
    target = (glob if glob in fleet
              else ("well_013" if "well_013" in fleet else inj_wells[0]))
    c_well, c_gas = st.columns([2, 1])
    with c_well:
        st.session_state["gl_pick"] = target  # keep picker synced to global
        wid = st.selectbox(
            "Well (gas-lift injection fleet)", inj_wells, key="gl_pick",
            format_func=core.well_label, on_change=_sync_gl_well,
            help="The gas-lift lens needs injection-survey data — only the synthetic "
                 "fleet (well_001–well_020) carries it. Picking here retargets the "
                 "rest of the workbench too.")
    with c_gas:
        st.session_state.setdefault("gas_cost", 1.50)
        gas_cost = st.slider("Injection Gas Cost ($/Mscf)", 0.25, 6.0, step=0.25,
                             key="gas_cost")
    oil_price, nri, _disc = _common.deck()
    if glob not in fleet:
        st.caption(f"The globally selected well has no injection survey, so this page "
                   f"is showing **{core.well_label(wid)}**. Pick another above to "
                   "compare.")

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
        {"label": "Current Injection", "value": f"{cur_inj:,.0f} Mscfd"},
        {"label": "Optimal Injection", "value": f"{opt.q_inj_opt:,.0f} Mscfd",
         "delta": f"{delta_inj:+,.0f} Mscfd"},
        {"label": "Oil At Optimum", "value": f"{opt.q_oil_opt:,.0f} BOPD",
         "delta": f"{opt.q_oil_opt - cur_oil:+,.0f} BOPD"},
        {"label": "Lift-Gas Margin Gain", "value": f"${daily_gain:,.0f}/day",
         "delta": f"${daily_gain*365/1e6:.2f}MM/yr",
         "help": "Gain in oil revenue net of injection-gas cost from moving to the "
                 "optimum. Excludes LOE / compression opex / water disposal — it is the "
                 "incremental lift-gas margin, not a full project NPV."},
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
                       annotation_text=f"Opt {opt.q_inj_opt:,.0f} Mscfd",
                       annotation_position="right")
    fig_hist.add_hline(y=cur_inj, line=dict(color=theme.AMBER, width=1.2, dash="dash"),
                       annotation_text=f"Avg {cur_inj:,.0f} Mscfd",
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
                                      name=f"Optimal ({opt.q_inj_opt:,.0f} Mscfd)",
                                      marker=dict(color=theme.GREEN, size=14,
                                                  symbol="star")))
        fig_glpc.add_trace(go.Scatter(
            x=[cur_inj], y=[float(core.gla_glpc.glpc_rate(cur_inj, params))],
            mode="markers", name=f"Current ({cur_inj:,.0f} Mscfd)",
            marker=dict(color=theme.AMBER, size=10, symbol="diamond")))
        fig_glpc.update_layout(title="Gas-Lift Performance Curve",
                               xaxis_title="Injection gas (Mscfd)",
                               yaxis_title="Gross liquid (blpd)")
        st.plotly_chart(theme.style_fig(fig_glpc, height=330), width="stretch")
        theme.source_note(
            f"GLPC is fit on GROSS LIQUID (oil + water): q_sl={params.q_sl:.0f} blpd · "
            f"q_max={params.q_max:.0f} blpd · a={params.a:.3f} Mscfd⁻¹ (nonlinear least "
            f"squares). Oil = liquid × (1 − WC), WC={wc:.0%}; the economics below convert "
            "liquid → oil before pricing.")
    with col_right:
        net_rev = core.gla_glpc.net_revenue_daily(q_range, params, wc,
                                                  oil_price, gas_cost, nri)
        fig_econ = go.Figure()
        fig_econ.add_trace(go.Scatter(x=q_range, y=net_rev, mode="lines",
                                      name="Oil revenue − lift-gas cost",
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
        fig_econ.update_layout(title="Oil Revenue (Net Of Lift-Gas) Vs. Injection Rate",
                               xaxis_title="Injection gas (Mscfd)",
                               yaxis_title="Oil revenue − lift-gas cost ($/day)")
        st.plotly_chart(theme.style_fig(fig_econ, height=330), width="stretch")
        theme.source_note(
            "Objective = BOPD × (1 − WC) × price × NRI − Qinj × gas_cost (oil revenue net "
            "of injection-gas cost only — it does NOT subtract LOE, compression opex, or "
            "water disposal, so it is the lift-gas margin, not a full net revenue). The "
            "injection optimum from dNet/dQinj = 0 (closed form) is unchanged by those "
            "fixed per-bbl costs.")

    # ---- fit validation vs known ground truth -----------------------------------
    truth = core.gla_ground_truth()
    if wid in getattr(truth, "index", []):
        t = truth.loc[wid]
        pt.section("Fit Validation — Recovered Vs. Known Ground Truth",
                   "This synthetic fleet ships the generator's TRUE GLPC parameters, "
                   "so the live fit is checked directly — parameter recovery, not a "
                   "claim about the live-deck optimum.")
        spec = [("q_sl (blpd)", params.q_sl, float(t["q_sl"]), 1),
                ("q_max (blpd)", params.q_max, float(t["q_max"]), 1),
                ("a (Mscfd⁻¹)", params.a, float(t["a"]), 5),
                ("Water cut", wc, float(t["water_cut"]), 3)]
        val_df = pd.DataFrame([
            {"Parameter": name, "Fitted": round(fv, nd), "True": round(tv, nd),
             "Error %": (round((fv - tv) / tv * 100, 1) if tv else float("nan"))}
            for name, fv, tv, nd in spec])
        true_params = core.gla_glpc.GLPCParams(
            q_sl=float(t["q_sl"]), q_max=float(t["q_max"]), a=float(t["a"]))
        true_opt = core.gla_glpc.optimal_injection(
            true_params, float(t["water_cut"]), oil_price, gas_cost, nri)
        opt_abs_err = abs(opt.q_inj_opt - true_opt.q_inj_opt)
        cval, ckpi = st.columns([3, 2])
        with cval:
            st.dataframe(val_df, width="stretch", hide_index=True,
                         column_config={"Error %": st.column_config.NumberColumn(
                             format="%.1f%%")})
        with ckpi:
            pt.kpi_row([
                {"label": "Optimum (fitted)", "value": f"{opt.q_inj_opt:,.0f} Mscfd"},
                {"label": "Optimum (true params)",
                 "value": f"{true_opt.q_inj_opt:,.0f} Mscfd",
                 "delta": f"{opt.q_inj_opt - true_opt.q_inj_opt:+,.0f}"},
            ])
            st.caption(f"At the current deck the fitted-curve optimum lands within "
                       f"**{opt_abs_err:,.0f} Mscfd** of the optimum from the TRUE "
                       "parameters — fit error barely moves the recommendation.")
        theme.source_note(
            "Parameter recovery vs. the generator's committed ground_truth.csv; the "
            "optimum comparison recomputes both at the SAME live deck, isolating fit "
            "error from economic assumptions.")

    pt.section("Recommendation")
    rec_kind = {"Reduce": "bad", "Increase": "warn", "Maintain": "ok"}[direction]
    st.markdown(
        f"{pt.pill(direction + ' injection', rec_kind)} "
        f"**{cur_inj:,.0f} → {opt.q_inj_opt:,.0f} Mscfd** · expected "
        f"**{opt.q_oil_opt:,.0f} BOPD** (from {cur_oil:,.0f}) · oil revenue net of "
        f"lift-gas **${opt.net_revenue_per_day:,.0f}/day** (from ${cur_rev:,.0f}/day) · "
        f"gain **${daily_gain:,.0f}/day (${daily_gain*365/1e6:.2f}MM/yr)** — lift-gas "
        "margin only, before LOE / compression / water disposal.",
        unsafe_allow_html=True)
    st.caption("Derived analytically — marginal revenue set equal to marginal gas "
               "cost; pure petroleum-engineering math, no LLM.")
    theme.references(["gas_lift", "npv"])
