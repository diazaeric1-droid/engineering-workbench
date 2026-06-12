"""Design → Artificial Lift Design — ESP affinity-law sizing + gas-lift sweep.

Ported from Well Performance Studio's Artificial Lift tab; the design math
(wps.lift — TDH, stages from a representative pump curve, affinity-law frequency
trim, viscosity de-rating, brake power) is vendored with only its internal import
rewritten to package-relative form (see VENDORING.md).
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
    pt.masthead("workbench", "Artificial Lift Design",
                "Size an ESP (stages · frequency · TDH · power) and sweep gas-lift "
                "injection for a target rate the well cannot reach naturally")
    _common.context()
    theme.data_badge(
        "synthetic",
        "Physics-modeled — standard design equations (Takács; Hydraulic Institute; "
        "affinity laws) on engineer-supplied inputs; illustrative pump curve, not a "
        "vendor catalog match.")

    pt.section("Well System & Design Targets")
    c1, c2, c3 = st.columns(3)
    with c1:
        l_pres = st.slider("Reservoir Pressure (psia)", 800, 8000, 3000, 50, key="l_pres")
        l_qtest = st.slider("Flow-Test Rate (STB/d)", 50, 5000, 600, 25, key="l_qtest")
        l_pwftest = st.slider("Flow-Test Pwf (psia)", 100, int(l_pres),
                              min(2200, int(l_pres) - 100), 25, key="l_pwftest")
    with c2:
        l_id = st.slider("Tubing ID (in.)", 1.0, 5.0, 2.441, 0.001, key="l_id")
        l_depth = st.slider("Tubing Depth (ft)", 2000, 16000, 8000, 100, key="l_depth")
        l_wc = st.slider("Water Cut (fraction)", 0.0, 0.99, 0.40, 0.01, key="l_wc")
        l_glr = st.slider("Formation GLR (scf/STB)", 0, 3000, 300, 25, key="l_glr")
    with c3:
        l_target = st.slider("Target Liquid Rate (STB/d)", 100, 5000, 1200, 25,
                             key="l_target")
        l_freq = st.slider("ESP Drive Frequency (Hz)", 40.0, 70.0, 60.0, 1.0,
                           key="l_freq")
        l_visc = st.slider("Fluid Viscosity (cP)", 1.0, 300.0, 5.0, 1.0, key="l_visc")
        l_whp = st.slider("Wellhead Pressure (psia)", 30, 1500, 150, 10, key="l_whp")

    if l_pwftest >= l_pres:
        st.warning("Flow-test pwf should be below reservoir pressure.")
    ipr = core.wps_nodal.vogel_ipr(
        p_res=float(l_pres), pb=float(l_pres),
        q_test=float(l_qtest), pwf_test=float(min(l_pwftest, l_pres - 1)))
    vlp_in = core.wps_nodal.VLPInputs(
        tubing_id_in=float(l_id), depth_ft=float(l_depth),
        wellhead_pressure=float(l_whp), glr_scf_stb=float(l_glr),
        water_cut=float(l_wc))
    op_nat = core.wps_nodal.operating_point(ipr, vlp_in)
    nat_q = op_nat.q_op if op_nat.converged else 0.0

    esp = core.wps_lift.design_esp(
        ipr, vlp_in, target_q_stb_d=float(l_target),
        frequency_hz=float(l_freq), fluid_viscosity_cp=float(l_visc))

    pt.section("ESP Design")
    pt.kpi_row([
        {"label": "Stages", "value": f"{esp.stages:,d}"},
        {"label": "Frequency", "value": f"{esp.frequency_hz:.0f} Hz"},
        {"label": "Total Dynamic Head", "value": f"{esp.tdh_ft:,.0f} ft"},
        {"label": "Brake Power", "value": f"{esp.bhp:,.0f} hp"},
    ])
    pt.kpi_row([
        {"label": "Natural Rate", "value": f"{nat_q:,.0f} STB/d"},
        {"label": "Rate With ESP", "value": f"{esp.op_q_stb_d:,.0f} STB/d"},
        {"label": "Pump Intake P", "value": f"{esp.pump_intake_psia:,.0f} psia"},
        {"label": "Stage Efficiency", "value": f"{esp.efficiency:.0%}"},
    ])
    if esp.meets_target:
        theme.flag(f"Design meets the {l_target:,.0f} STB/d target.", "ok")
    else:
        theme.flag(f"Design falls short of {l_target:,.0f} STB/d (reaches "
                   f"{esp.op_q_stb_d:,.0f}). Raise frequency/stages or check the IPR.",
                   "high")

    gl = core.wps_lift.gas_lift_sweep(ipr, vlp_in, inj_glr_max_scf_stb=1500.0, n=14)

    cL, cR = st.columns(2)
    with cL:
        pm = core.wps_lift.PumpModel()
        q_curve = np.linspace(200.0, pm.q_runout_bpd * 0.98, 60)
        h_curve = np.array([pm.head_per_stage(q, esp.frequency_hz) for q in q_curve])
        figp = go.Figure()
        figp.add_scatter(x=q_curve, y=h_curve,
                         name=f"Pump head/stage @ {esp.frequency_hz:.0f} Hz",
                         line=dict(color=theme.BLUE))
        figp.add_scatter(x=[esp.total_fluid_bpd], y=[esp.head_per_stage_ft],
                         name="Design point", mode="markers",
                         marker=dict(size=12, color=theme.GREEN, symbol="x",
                                     line=dict(width=2)))
        figp.update_layout(title="ESP Pump Curve (Representative)",
                           xaxis_title="Total fluid (bpd)",
                           yaxis_title="Head per stage (ft)")
        st.plotly_chart(theme.style_fig(figp, height=320), width="stretch")
    with cR:
        figg = go.Figure()
        figg.add_scatter(x=[p.inj_glr_scf_stb for p in gl.points],
                         y=[p.q_op_stb_d for p in gl.points],
                         name="Gas-lift performance", line=dict(color=theme.AMBER))
        figg.add_scatter(x=[gl.best.inj_glr_scf_stb], y=[gl.best.q_op_stb_d],
                         name="Optimum injection", mode="markers",
                         marker=dict(size=12, color=theme.GREEN, symbol="x",
                                     line=dict(width=2)))
        figg.update_layout(title="Gas-Lift Injection Sweep",
                           xaxis_title="Injection GLR added (scf/STB)",
                           yaxis_title="Operating rate q (STB/d)")
        st.plotly_chart(theme.style_fig(figg, height=320), width="stretch")

    st.caption(
        f"{esp.notes} TDH and brake horsepower per the standard Hydraulic-Institute / "
        f"Takács design equations; stages = TDH ÷ head-per-stage. Gas lift: best added "
        f"GLR {gl.best.inj_glr_scf_stb:,.0f} scf/STB lifts the well to "
        f"{gl.best.q_op_stb_d:,.0f} STB/d (~{gl.inj_rate_mscf_d_at_best:,.0f} Mscf/d "
        "injection). For the economic injection optimum on a surveyed well, see "
        "Optimize → Gas-Lift Optimum.")
    theme.source_note(
        "ESP staging via centrifugal-pump affinity laws (Q∝N, H∝N², P∝N³) on TDH; "
        "design point = total fluid (bpd) vs. head-per-stage (ft).")
    theme.references(["esp_affinity", "gas_lift"])
