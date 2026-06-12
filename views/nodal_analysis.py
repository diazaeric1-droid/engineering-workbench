"""Design → Nodal Analysis — Vogel IPR × Hagedorn-Brown / Beggs-Brill VLP.

Ported from Well Performance Studio's Nodal tab; the physics core (wps.nodal,
v0.2.2 with the three June-2026 corrections, validated against published worked
examples) is vendored byte-identical. The computed operating point is stored in
session state so the Well Case File can show the design lens for this well.
"""
from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import core
import product_theme as pt
import theme

from views import _common


def _hash_inputs(obj) -> tuple:
    return dataclasses.astuple(obj)


@st.cache_data(show_spinner=False, hash_funcs={"wps.nodal.VLPInputs": _hash_inputs})
def _vlp_curve(inp, q_max: float = 4000.0, n: int = 26):
    return core.wps_nodal.vlp_curve(inp, q_max=q_max, n=n)


def render() -> None:
    _common.ensure_state()
    pt.masthead("workbench", "Nodal Analysis",
                "Operating point at the bottom-hole node — Vogel inflow versus "
                "multiphase tubing outflow")
    _common.context()
    theme.data_badge(
        "synthetic",
        "Physics-modeled — standard nodal correlations (Vogel / Hagedorn-Brown / "
        "Beggs-Brill) on engineer-supplied inputs; not a tuned field match.")

    pt.section("System Inputs",
               "Reservoir, tubing, and fluid descriptors a production engineer "
               "would have for a single well.")
    c1, c2, c3 = st.columns(3)
    with c1:
        n_pres = st.slider("Reservoir Pressure (psia)", 800, 8000, 3500, 50, key="n_pres")
        n_pb = st.slider("Bubble Point (psia)", 200, 8000, 3500, 50, key="n_pb")
        n_ipr_mode = st.radio("IPR Model", ("Vogel (test point)", "Straight-line PI"),
                              key="n_ipr_mode")
    with c2:
        if n_ipr_mode == "Vogel (test point)":
            n_qtest = st.slider("Flow-Test Rate (STB/d)", 50, 5000, 800, 25, key="n_qtest")
            n_pwftest = st.slider("Flow-Test Pwf (psia)", 100, int(n_pres),
                                  min(2500, int(n_pres) - 100), 25, key="n_pwftest")
        else:
            n_j = st.slider("Productivity Index J (STB/d/psi)", 0.1, 10.0, 1.0, 0.1,
                            key="n_j")
        n_id = st.slider("Tubing ID (in.)", 1.0, 5.0, 2.441, 0.001, key="n_id")
        n_depth = st.slider("Tubing Depth (ft)", 2000, 16000, 8000, 100, key="n_depth")
    with c3:
        n_glr = st.slider("Producing GLR (scf/STB)", 0, 3000, 400, 25, key="n_glr")
        n_wc = st.slider("Water Cut (fraction)", 0.0, 0.99, 0.30, 0.01, key="n_wc")
        n_whp = st.slider("Wellhead Pressure (psia)", 30, 1500, 150, 10, key="n_whp")
        n_corr = st.selectbox(
            "VLP Correlation", ("hagedorn_brown", "beggs_brill"),
            format_func=lambda s: {"hagedorn_brown": "Hagedorn–Brown",
                                   "beggs_brill": "Beggs–Brill"}[s], key="n_corr")

    if n_ipr_mode == "Vogel (test point)":
        if n_pwftest >= n_pres:
            st.warning("Flow-test pwf should be below reservoir pressure.")
        ipr = core.wps_nodal.vogel_ipr(
            p_res=float(n_pres), pb=float(min(n_pb, n_pres)),
            q_test=float(n_qtest), pwf_test=float(min(n_pwftest, n_pres - 1)))
    else:
        ipr = core.wps_nodal.straight_line_ipr(p_res=float(n_pres), j=float(n_j))

    vlp_in = core.wps_nodal.VLPInputs(
        tubing_id_in=float(n_id), depth_ft=float(n_depth),
        wellhead_pressure=float(n_whp), glr_scf_stb=float(n_glr),
        water_cut=float(n_wc), correlation=n_corr)
    vlp = _vlp_curve(vlp_in, q_max=float(ipr.aof) * 0.98, n=26)
    op = core.wps_nodal.operating_point(ipr, vlp)

    pt.kpi_row([
        {"label": "Operating Rate", "value": f"{op.q_op:,.0f} STB/d" if op.converged else "no flow"},
        {"label": "Operating Pwf", "value": f"{op.pwf_op:,.0f} psia" if op.converged else "—"},
        {"label": "AOF", "value": f"{ipr.aof:,.0f} STB/d",
         "help": "Absolute open-flow potential (rate at pwf = 0)"},
        {"label": "Correlation", "value": "Hagedorn–Brown" if n_corr == "hagedorn_brown" else "Beggs–Brill"},
    ])
    if not op.converged:
        theme.flag("No IPR∩VLP intersection — the reservoir cannot lift this column "
                   "(needs artificial lift). See Artificial Lift Design.", "warn")

    # Persist the design lens for the Case File (keyed to the selected well).
    st.session_state[f"nodal::{_common.current_well()}"] = {
        "q_op": float(op.q_op), "pwf_op": float(op.pwf_op),
        "converged": bool(op.converged), "aof": float(ipr.aof),
        "correlation": n_corr,
    }

    fig = go.Figure()
    fig.add_scatter(x=ipr.q, y=ipr.pwf, name="IPR (inflow — reservoir)",
                    line=dict(color=theme.BLUE))
    fig.add_scatter(x=vlp.q, y=vlp.pwf, name="VLP (outflow — tubing)",
                    line=dict(color=theme.AMBER))
    if op.converged:
        fig.add_scatter(x=[op.q_op], y=[op.pwf_op], name="Operating point",
                        mode="markers",
                        marker=dict(size=13, color=theme.GREEN, symbol="x",
                                    line=dict(width=2)))
    fig.update_layout(title="Nodal Plot — Pressure Vs. Rate At The Bottom-Hole Node",
                      xaxis_title="Liquid rate q (STB/d)",
                      yaxis_title="Flowing BHP, pwf (psia)")
    st.plotly_chart(theme.style_fig(fig, height=420), width="stretch")
    theme.source_note(
        "Operating point = intersection of the Vogel IPR (inflow) and Hagedorn-Brown / "
        "Beggs-Brill VLP (outflow); BHP in psia, liquid rate in STB/d. Stored to the "
        "Case File design lens for the selected well.")

    nodal_df = pd.DataFrame({
        "rate_stb_d_ipr": ipr.q, "pwf_psia_ipr": ipr.pwf,
        "rate_stb_d_vlp": list(vlp.q) + [None] * max(0, len(ipr.q) - len(vlp.q)),
        "pwf_psia_vlp": list(vlp.pwf) + [None] * max(0, len(ipr.q) - len(vlp.q)),
    })
    st.download_button("Download Curves (CSV)", data=nodal_df.to_csv(index=False),
                       file_name="workbench_nodal.csv", mime="text/csv")

    theme.references(["vogel", "hagedorn_brown", "beggs_brill", "nodal"])
