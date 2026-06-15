"""Optimize → Injection Allocation — fleet injection split under a compressor
capacity limit, by the equal-marginal-revenue principle (shadow-price bisection).

At the constrained optimum dNet_i/dQinj_i = λ for every well; λ is found by
bisecting on the shadow price until allocations sum to the cap — exact, not a
greedy approximation (gla.glpc.allocate_fleet, vendored byte-identical).
"""
from __future__ import annotations

import math

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

    well_inputs, unconstrained = _fleet_inputs(oil_price, gas_cost, nri)
    total_unconstrained = float(sum(unconstrained.values()))
    total_cur_inj = float(sum(w["current_q_inj"] for w in well_inputs))

    # Fleet-wide page: the global context bar shows the single SELECTED well (page
    # chrome), but every number here is fleet-level — say so, and surface the deck the
    # allocation economics actually use, including the gas cost (audit findings).
    st.caption(
        f"**Fleet-wide** — optimizing all {len(well_inputs)} gas-lift injection wells "
        f"together (the well named in the context bar above is just the global selection; "
        f"this page ignores it). Economics: **${oil_price:,.0f}/bbl** oil · "
        f"**${gas_cost:,.2f}/Mscf** gas · **{nri:.0%}** NRI — set the gas cost on "
        "Gas-Lift Optimum or the sidebar deck.")

    # Default the cap to the fleet's unconstrained demand so the page opens in a
    # sensible, mostly-unconstrained state (a tiny default cap made the headline
    # "gain" deeply negative — comparing different gas budgets).
    cap_max = float(max(60.0, round(max(total_cur_inj, total_unconstrained) * 1.3)))
    st.session_state.setdefault("comp_cap", float(math.ceil(total_unconstrained)))
    # clamp a stale stored cap (e.g. after a deck change) into the current range
    st.session_state["comp_cap"] = float(
        min(max(st.session_state["comp_cap"], 1.0), cap_max))
    comp_cap = st.slider(
        "Compressor Capacity (Mscfd total)", 1.0, cap_max, step=1.0, key="comp_cap",
        help=f"Total gas available across the fleet. Unconstrained, the fleet wants "
             f"≈{total_unconstrained:.0f} Mscfd (current total ≈{total_cur_inj:.0f}). "
             "Drop the cap below that to see curtailment and the shadow price λ.")

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

    total_alloc_inj = comp_df["Allocated (Mscfd)"].sum()
    total_cur_oil = comp_df["Current BOPD"].sum()
    total_alloc_oil = comp_df["Allocated BOPD"].sum()
    total_cur_rev = sum(
        float(core.gla_glpc.net_revenue_daily(
            w["current_q_inj"], w["params"], w["water_cut"],
            oil_price, gas_cost, nri))
        for w in well_inputs)
    # Binding derived from the ALLOCATOR's own output (audit: was recomputed from the
    # rounded per-well optima): allocate_fleet saturates the cap iff fleet demand exceeds
    # it, so the constraint binds exactly when the allocated total reaches the cap.
    binding = total_alloc_inj >= comp_cap - 1e-3

    # Honest, apples-to-apples gain: optimally re-split the SAME total gas the fleet
    # already injects (no extra compression), so it is genuinely ≥ 0.
    same_budget = core.gla_glpc.allocate_fleet(well_inputs, total_cur_inj, oil_price,
                                               gas_cost, nri)
    realloc_gain = sum(r["expected_net_rev_day"] for r in same_budget) - total_cur_rev

    # Shadow price λ = marginal $/Mscf value of compression at the cap (closed form:
    # at the optimum dNet_i/dQinj_i = λ for any well with a positive allocation).
    lam = 0.0
    if binding:
        for w in well_inputs:
            q = alloc_by_id[w["well_id"]]["allocated_q_inj"]
            if q > 0.01:
                p = w["params"]
                rev_slope = ((p.q_max - p.q_sl) * p.a * (1.0 - w["water_cut"])
                             * oil_price * nri)
                lam = max(0.0, rev_slope * math.exp(-p.a * q) - gas_cost)
                break

    # Curtailment vs the unconstrained optimum (only meaningful when the cap binds).
    unc = core.gla_glpc.allocate_fleet(well_inputs, total_unconstrained + 1.0,
                                       oil_price, gas_cost, nri)
    curtail_oil = max(0.0, sum(r["expected_q_oil"] for r in unc) - total_alloc_oil)
    curtail_rev = max(0.0, sum(r["expected_net_rev_day"] for r in unc)
                      - comp_df["Allocated Rev ($/day)"].sum())

    pt.kpi_row([
        {"label": "Current Total Injection", "value": f"{total_cur_inj:.1f} Mscfd"},
        {"label": "Allocated @ Cap", "value": f"{total_alloc_inj:.1f} Mscfd",
         "delta": f"cap {comp_cap:.0f}", "delta_color": "off"},
        {"label": "Fleet Oil @ Cap", "value": f"{total_alloc_oil:,.0f} BOPD",
         "delta": f"{total_alloc_oil - total_cur_oil:+,.0f} vs current"},
        {"label": "Reallocation Gain (same gas)", "value": f"${realloc_gain:,.0f}/day",
         "delta": f"${realloc_gain*365/1e6:.2f}MM/yr",
         "help": "Optimally re-splitting the CURRENT total injection vs the current "
                 "split — apples-to-apples, no extra compression."},
        {"label": "Marginal Value Of Gas λ",
         "value": f"${lam:,.2f}/Mscf" if binding else "—",
         "help": "Shadow price: the $/Mscf value of one more unit of compression. "
                 "Lease more while its all-in cost < λ."},
    ])
    if binding:
        st.markdown(pt.pill(
            f"cap binding — λ ${lam:,.2f}/Mscf · curtailment ≈ {curtail_oil:,.0f} "
            f"BOPD / ${curtail_rev:,.0f}/day vs the unconstrained optimum", "warn"),
            unsafe_allow_html=True)
    else:
        st.markdown(pt.pill(
            "cap not binding — every well sits at its unconstrained optimum", "ok"),
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
