"""Optimize → Injection Allocation — fleet injection split under a compressor
capacity limit, by the equal-marginal-revenue principle (shadow-price bisection).

At the constrained optimum dNet_i/dQinj_i = λ for every well; λ is found by
bisecting on the shadow price until allocations sum to the cap — exact, not a
greedy approximation (gla.glpc.allocate_fleet, vendored byte-identical).
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import core
import product_theme as pt
import theme

from views import _common


@st.cache_data(show_spinner=False)
def _fleet_inputs(oil_price: float, gas_cost: float, nri: float):
    """Per-well GLPC fits + optima for the whole injection fleet (cached on deck)."""
    fleet = core.gla_fleet()
    well_inputs, unconstrained = [], {}
    for well_id, df_i in fleet.items():
        params_i, wc_i, cur_i, opt_i = core.analyze_gla_well(
            df_i, oil_price, gas_cost, nri)
        well_inputs.append({"well_id": well_id, "params": params_i,
                            "water_cut": wc_i, "current_q_inj": cur_i})
        unconstrained[well_id] = opt_i.q_inj_opt
    return well_inputs, unconstrained


def render() -> None:
    _common.ensure_state()
    pt.masthead("workbench", "Injection Allocation",
                "Optimal fleet injection split under a compressor capacity limit "
                "— equal marginal revenue across wells")
    _common.context()
    theme.data_badge(
        "synthetic",
        "20-well synthetic gas-lift fleet with embedded injection surveys.")

    oil_price, nri, _disc = _common.deck()
    gas_cost = float(st.session_state.get("gas_cost", 1.50))
    comp_cap = st.slider("Compressor Capacity (Mscfd total)", 1.0, 60.0,
                         float(st.session_state.setdefault("comp_cap", 20.0)), 1.0,
                         key="comp_cap",
                         help="Total gas available for injection across the fleet.")

    well_inputs, unconstrained = _fleet_inputs(oil_price, gas_cost, nri)
    alloc = core.gla_glpc.allocate_fleet(well_inputs, comp_cap, oil_price,
                                         gas_cost, nri)
    alloc_by_id = {r["well_id"]: r for r in alloc}

    rows = []
    for w in well_inputs:
        wid = w["well_id"]
        cur = w["current_q_inj"]
        a = alloc_by_id[wid]
        cur_oil = float(core.gla_glpc.glpc_rate(cur, w["params"])) * (1.0 - w["water_cut"])
        rows.append({
            "Well": wid,
            "Current Inj (Mscfd)": round(cur, 2),
            "Allocated (Mscfd)": a["allocated_q_inj"],
            "Unconstrained Opt (Mscfd)": round(unconstrained[wid], 2),
            "Current BOPD": round(cur_oil, 1),
            "Allocated BOPD": a["expected_q_oil"],
            "Allocated Rev ($/day)": a["expected_net_rev_day"],
        })
    comp_df = pd.DataFrame(rows).sort_values("Allocated Rev ($/day)", ascending=False)

    total_cur_inj = comp_df["Current Inj (Mscfd)"].sum()
    total_alloc_inj = comp_df["Allocated (Mscfd)"].sum()
    total_cur_oil = comp_df["Current BOPD"].sum()
    total_alloc_oil = comp_df["Allocated BOPD"].sum()
    total_alloc_rev = comp_df["Allocated Rev ($/day)"].sum()
    total_cur_rev = sum(
        float(core.gla_glpc.net_revenue_daily(
            w["current_q_inj"], w["params"], w["water_cut"],
            oil_price, gas_cost, nri))
        for w in well_inputs)
    rev_gain = total_alloc_rev - total_cur_rev
    binding = sum(unconstrained.values()) > comp_cap + 1e-6

    pt.kpi_row([
        {"label": "Current Total Injection", "value": f"{total_cur_inj:.1f} Mscfd"},
        {"label": "Allocated Injection", "value": f"{total_alloc_inj:.1f} Mscfd",
         "delta": f"cap {comp_cap:.0f} Mscfd", "delta_color": "off"},
        {"label": "Current Fleet Oil", "value": f"{total_cur_oil:,.0f} BOPD"},
        {"label": "Allocated Fleet Oil", "value": f"{total_alloc_oil:,.0f} BOPD",
         "delta": f"{total_alloc_oil - total_cur_oil:+,.0f}"},
        {"label": "Reallocation Gain", "value": f"${rev_gain:,.0f}/day",
         "delta": f"${rev_gain*365/1e6:.2f}MM/yr"},
    ])
    st.markdown(
        (pt.pill("constraint binding — shadow price λ > 0", "warn") if binding
         else pt.pill("constraint not binding — every well at its optimum", "ok")),
        unsafe_allow_html=True)

    fig = go.Figure()
    fig.add_trace(go.Bar(x=comp_df["Well"], y=comp_df["Current Inj (Mscfd)"],
                         name="Current", marker_color=theme.GREY))
    fig.add_trace(go.Bar(x=comp_df["Well"], y=comp_df["Allocated (Mscfd)"],
                         name="Allocated (constrained)", marker_color=theme.BLUE))
    fig.add_trace(go.Bar(x=comp_df["Well"], y=comp_df["Unconstrained Opt (Mscfd)"],
                         name="Unconstrained optimum", marker_color=theme.GREEN,
                         opacity=0.5))
    fig.update_layout(title=f"Gas Injection Allocation (cap = {comp_cap:.0f} Mscfd)",
                      barmode="group", xaxis_title="Well",
                      yaxis_title="Injection gas (Mscfd)")
    st.plotly_chart(theme.style_fig(fig, height=350), width="stretch")
    theme.source_note(
        "Equal-marginal-revenue allocation: dNet_i/dQinj_i = λ at the constrained "
        "optimum; λ solved by bisection on the shadow price (exact). If the sum of "
        "unconstrained optima fits the cap, the constraint is not binding.")

    st.dataframe(comp_df, width="stretch", hide_index=True)
    st.download_button("Download Allocation (CSV)", data=comp_df.to_csv(index=False),
                       file_name="workbench_allocation.csv", mime="text/csv")
    theme.references(["gas_lift", "npv"])
