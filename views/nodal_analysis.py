"""Design → Nodal Analysis — Vogel/PI IPR × Hagedorn-Brown / Beggs-Brill VLP.

Ported from Well Performance Studio's Nodal tab; the physics core (wps.nodal,
v0.2.2 with the three June-2026 corrections, validated against published worked
examples) is vendored byte-identical. The computed operating point is stored in
session state so the Well Case File can show the design lens for this well.

Every System Input is seeded from the selected well's design seed
(``_common.design_seed_cached``) — measured where the well file carries it, derived
via a standard correlation, or a formation-typical assumption otherwise — so the
operating point is an honest what-if anchored to the selected well rather than a
generic default mislabeled with the well's name. The seed map is surfaced on-page
so the engineer can see (and override) exactly which inputs came from data.
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

_CORR_LABEL = {"hagedorn_brown": "Hagedorn–Brown", "beggs_brill": "Beggs–Brill"}
_PROV_PILL = {"measured": "ok", "derived": "info", "assumed": "warn", "n/a": "muted"}
_PROV_WORD = {
    "measured": "Read from the well's own production / SCADA data.",
    "derived": "Computed from measured values via a standard correlation "
               "(Standing bubble point, geothermal BHT, live-oil viscosity).",
    "assumed": "Formation-typical engineering estimate — the public well file does "
               "not carry it. Confirm or override before you trust the number.",
    "n/a": "Not applicable for this well (no production history).",
}


def _hash_inputs(obj) -> tuple:
    return dataclasses.astuple(obj)


@st.cache_data(show_spinner=False, hash_funcs={"wps.nodal.VLPInputs": _hash_inputs})
def _vlp_curve(inp, q_max: float = 4000.0, n: int = 26):
    return core.wps_nodal.vlp_curve(inp, q_max=q_max, n=n)


@st.cache_data(show_spinner=False)
def _op_sensitivity(mode, p_res, pb, q_test, pwf_test, j, tubing_id, depth, glr, wc,
                    whp, api, gsg, wsg, tsurf, tbh, corr):
    """One-at-a-time sensitivity of the operating RATE to the uncertain seed inputs.

    The seed marks reservoir pressure, oil API, tubing ID, etc. as ASSUMED (formation-
    typical) — the operating point swings on them, so a senior PE's next question is "how
    much?". For each variable we recompute q_op at a low/high endpoint with the others held
    at the current value; the result is a tornado. Cached on the scalar inputs."""
    base = dict(p_res=p_res, pb=pb, q_test=q_test, pwf_test=pwf_test, j=j,
                tubing_id=tubing_id, depth=depth, glr=glr, wc=wc, whp=whp,
                api=api, gsg=gsg, wsg=wsg, tsurf=tsurf, tbh=tbh)

    def q_of(**ov):
        d = {**base, **ov}
        pres = float(d["p_res"]); pbb = float(min(d["pb"], pres))
        try:
            if mode == "vogel":
                ipr = core.wps_nodal.vogel_ipr(
                    p_res=pres, pb=pbb, q_test=float(d["q_test"]),
                    pwf_test=float(min(d["pwf_test"], pres - 1)))
            else:
                ipr = core.wps_nodal.straight_line_ipr(p_res=pres, j=float(d["j"]))
            v = core.wps_nodal.VLPInputs(
                tubing_id_in=float(d["tubing_id"]), depth_ft=float(d["depth"]),
                wellhead_pressure=float(d["whp"]), glr_scf_stb=float(d["glr"]),
                water_cut=float(d["wc"]), oil_api=float(d["api"]), gas_sg=float(d["gsg"]),
                water_sg=float(d["wsg"]), temp_surface_f=float(d["tsurf"]),
                temp_bottom_f=float(d["tbh"]), correlation=corr)
            vc = core.wps_nodal.vlp_curve(v, q_max=float(ipr.aof) * 0.98, n=22)
            op = core.wps_nodal.operating_point(ipr, vc)
            return float(op.q_op) if op.converged else 0.0
        except Exception:  # noqa: BLE001 — a perturbed point may be infeasible
            return 0.0

    base_q = q_of()
    specs = [
        ("Reservoir pressure", "p_res", p_res * 0.85, p_res * 1.15, "psia", 0),
        ("Oil gravity (API)", "api", max(api - 4, 10.0), min(api + 4, 60.0), "°API", 0),
        ("Tubing ID", "tubing_id", max(tubing_id - 0.2, 1.0),
         min(tubing_id + 0.2, 5.0), "in", 2),
        ("Producing GLR", "glr", glr * 0.75, glr * 1.25, "scf/STB", 0),
        ("Water cut", "wc", max(wc - 0.10, 0.0), min(wc + 0.10, 0.99), "frac", 2),
    ]
    rows = []
    for lab, key, lo, hi, unit, dec in specs:
        rows.append({"var": lab, "unit": unit, "dec": dec,
                     "lo_in": float(lo), "hi_in": float(hi),
                     "q_lo": q_of(**{key: lo}), "q_hi": q_of(**{key: hi})})
    return float(base_q), rows


def _seed_slider_defaults(seed, wid: str) -> None:
    """Pre-seed every key-backed System-Input widget from the well's design seed.

    Runs once per well selection (sentinel ``nodal_seeded_well``). Writing to
    session_state BEFORE the widgets instantiate is the supported way to set a
    slider/selectbox default without the "cannot set a widget value after
    instantiation" warning (per the project widget-state convention).
    """
    if st.session_state.get("nodal_seeded_well") == wid:
        return
    p_res = float(round(seed.reservoir_pressure_psia / 50.0) * 50.0)
    p_res = float(min(max(p_res, 800.0), 8000.0))
    pb = float(min(max(round(seed.bubble_point_psia / 50.0) * 50.0, 200.0), 8000.0))
    q_test = float(min(max(round(seed.test_rate_stb_d / 25.0) * 25.0, 50.0), 5000.0))
    # Flow-test pwf must sit strictly below reservoir pressure for the slider.
    pwf_cap = float(max(p_res - 100.0, 100.0))
    pwf_test = float(min(max(round(seed.test_pwf_psia / 25.0) * 25.0, 100.0), pwf_cap))
    j_seed = max(seed.test_rate_stb_d / max(p_res - seed.test_pwf_psia, 1.0), 0.1)

    st.session_state["n_pres"] = p_res
    st.session_state["n_pb"] = pb
    st.session_state["n_qtest"] = q_test
    st.session_state["n_pwftest"] = pwf_test
    st.session_state["n_j"] = float(min(max(round(j_seed, 1), 0.1), 10.0))
    st.session_state["n_id"] = float(min(max(seed.tubing_id_in, 1.0), 5.0))
    st.session_state["n_depth"] = int(min(max(round(seed.depth_ft / 100.0) * 100.0,
                                              2000.0), 16000.0))
    st.session_state["n_glr"] = int(min(max(round(seed.glr_scf_stb / 25.0) * 25.0,
                                            0.0), 3000.0))
    st.session_state["n_wc"] = float(min(max(round(seed.water_cut_frac, 2), 0.0), 0.99))
    st.session_state["n_whp"] = int(min(max(round(seed.wellhead_pressure_psia / 10.0)
                                            * 10.0, 30.0), 1500.0))
    st.session_state["n_api"] = float(min(max(round(seed.oil_api, 1), 10.0), 60.0))
    st.session_state["n_gsg"] = float(min(max(round(seed.gas_sg, 2), 0.55), 1.20))
    st.session_state["n_wsg"] = float(min(max(round(seed.water_sg, 2), 1.0), 1.20))
    st.session_state["n_tsurf"] = int(min(max(round(seed.temp_surface_f), 40), 200))
    st.session_state["n_tbh"] = int(min(max(round(seed.temp_bottom_f), 80), 400))
    st.session_state["nodal_seeded_well"] = wid


def _provenance_table(seed) -> None:
    """Compact 'Seeded from well — measured vs assumed' expander built from the seed."""
    prov = seed.provenance or {}
    rows = [
        ("Reservoir pressure", f"{seed.reservoir_pressure_psia:,.0f} psia",
         prov.get("reservoir_pressure_psia", "assumed")),
        ("Bubble point",
         (f"{seed.bubble_point_psia:,.0f} psia  (Standing Pb "
          f"{seed.bubble_point_raw_psia:,.0f} > Pres → modeled saturated)"
          if getattr(seed, "bubble_point_clamped", False)
          else f"{seed.bubble_point_psia:,.0f} psia"),
         prov.get("bubble_point_psia", "derived")),
        ("Flow-test rate", f"{seed.test_rate_stb_d:,.0f} STB/d",
         prov.get("test_rate_stb_d", "assumed")),
        ("Flow-test pwf", f"{seed.test_pwf_psia:,.0f} psia",
         prov.get("test_pwf_psia", "assumed")),
        ("Tubing ID", f"{seed.tubing_id_in:.3f} in", prov.get("tubing_id_in", "assumed")),
        ("Tubing depth", f"{seed.depth_ft:,.0f} ft", prov.get("depth_ft", "assumed")),
        ("Producing GLR", f"{seed.glr_scf_stb:,.0f} scf/STB",
         prov.get("glr_scf_stb", "assumed")),
        ("Water cut", f"{seed.water_cut_frac:.0%}", prov.get("water_cut_frac", "assumed")),
        ("Wellhead pressure", f"{seed.wellhead_pressure_psia:,.0f} psia",
         prov.get("wellhead_pressure_psia", "assumed")),
        ("Oil gravity", f"{seed.oil_api:.0f}° API", prov.get("oil_api", "assumed")),
        ("Gas SG", f"{seed.gas_sg:.2f}", prov.get("gas_sg", "assumed")),
        ("Water SG", f"{seed.water_sg:.2f}", prov.get("water_sg", "assumed")),
        ("Surface temp", f"{seed.temp_surface_f:.0f} °F",
         prov.get("temp_surface_f", "assumed")),
        ("Bottom-hole temp", f"{seed.temp_bottom_f:.0f} °F",
         prov.get("temp_bottom_f", "derived")),
    ]
    n_meas = sum(1 for _, _, p in rows if p == "measured")
    n_der = sum(1 for _, _, p in rows if p == "derived")
    n_asm = sum(1 for _, _, p in rows if p == "assumed")
    src = "this well's production / SCADA data" if seed.has_production else \
        "the fleet registry (no production file — formation typicals only)"
    with st.expander(
            f"Seeded from well — {n_meas} measured · {n_der} derived · {n_asm} assumed "
            f"(click to inspect / confirm)"):
        st.caption(
            f"Sliders above were pre-filled from {src}. "
            "**Measured** = read from the well; **derived** = standard correlation; "
            "**assumed** = formation-typical estimate you should confirm. Editing any "
            "slider overrides the seed for this session.")
        df = pd.DataFrame(
            [(lab, val, p.capitalize(), _PROV_WORD.get(p, "")) for lab, val, p in rows],
            columns=["Input", "Seeded value", "Provenance", "What that means"])
        st.dataframe(df, hide_index=True, width="stretch",
                     column_config={
                         "What that means": st.column_config.TextColumn(width="large")})
        pills = " ".join(
            pt.pill(f"{lab}: {p}", _PROV_PILL.get(p, "muted"))
            for lab, _, p in rows if p in ("measured", "derived"))
        if pills:
            st.markdown(
                "Data-anchored inputs (not free assumptions): " + pills,
                unsafe_allow_html=True)


def render() -> None:
    _common.ensure_state()
    pt.masthead("workbench", "Nodal Analysis",
                "Operating point at the bottom-hole node — Vogel/PI inflow versus "
                "multiphase tubing outflow, seeded from the selected well",
                chips=[("anchored to selected well", "info"),
                       ("editable what-if", "info")])
    _common.context()
    theme.data_badge(
        "synthetic",
        "Physics-modeled — standard nodal correlations (Vogel / Hagedorn-Brown / "
        "Beggs-Brill) on inputs seeded from the selected well; not a tuned field match.")

    wid = _common.current_well()
    seed = _common.design_seed_cached(wid)
    _seed_slider_defaults(seed, wid)

    st.caption(
        f"Forward-design scenario for **{wid} · {seed.name}** ({seed.formation}). The "
        "System Inputs below are pre-filled from this well — measured where its file "
        "carries the value, derived via a standard correlation, or a formation-typical "
        "assumption otherwise (see the seed table under the inputs). Edit any slider to "
        "explore; the operating point and the design lens it stores on the Well Case "
        "File are a what-if anchored to this well, not a history match.")

    pt.section("System Inputs",
               "Seeded from the selected well's reservoir / tubing / fluid descriptors "
               "— override any value to run a what-if.")
    c1, c2, c3 = st.columns(3)
    with c1:
        n_pres = st.slider("Reservoir Pressure (psia)", 800, 8000, step=50, key="n_pres")
        n_pb = st.slider("Bubble Point (psia)", 200, 8000, step=50, key="n_pb")
        n_ipr_mode = st.radio("IPR Model", ("Vogel (test point)", "Straight-line PI"),
                              key="n_ipr_mode")
    with c2:
        if n_ipr_mode == "Vogel (test point)":
            n_qtest = st.slider("Flow-Test Rate (STB/d)", 50, 5000, step=25, key="n_qtest")
            # Cap the pwf slider at reservoir pressure so the test point stays valid even
            # after the well (and thus the seeded p_res) changes.
            pwf_max = max(int(n_pres) - 25, 125)
            if st.session_state.get("n_pwftest", 0) > pwf_max:
                st.session_state["n_pwftest"] = float(pwf_max)
            n_pwftest = st.slider("Flow-Test Pwf (psia)", 100, pwf_max, step=25,
                                  key="n_pwftest")
        else:
            n_j = st.slider("Productivity Index J (STB/d/psi)", 0.1, 10.0, step=0.1,
                            key="n_j")
        n_id = st.slider("Tubing ID (in.)", 1.0, 5.0, step=0.001, key="n_id")
        n_depth = st.slider("Tubing Depth (ft)", 2000, 16000, step=100, key="n_depth")
    with c3:
        n_glr = st.slider("Producing GLR (scf/STB)", 0, 3000, step=25, key="n_glr")
        n_wc = st.slider("Water Cut (fraction)", 0.0, 0.99, step=0.01, key="n_wc")
        n_whp = st.slider("Wellhead Pressure (psia)", 30, 1500, step=10, key="n_whp")
        n_corr = st.selectbox(
            "VLP Correlation", ("hagedorn_brown", "beggs_brill"),
            format_func=lambda s: _CORR_LABEL[s], key="n_corr")

    with st.expander("Fluid & thermal PVT (seeded — drives Rs/Bo/density in the VLP)"):
        f1, f2, f3 = st.columns(3)
        with f1:
            n_api = st.slider("Oil Gravity (° API)", 10.0, 60.0, step=1.0, key="n_api")
            n_gsg = st.slider("Gas SG (air = 1)", 0.55, 1.20, step=0.01, key="n_gsg")
        with f2:
            n_wsg = st.slider("Water SG (water = 1)", 1.0, 1.20, step=0.01, key="n_wsg")
            n_tsurf = st.slider("Surface Temp (°F)", 40, 200, step=5, key="n_tsurf")
        with f3:
            n_tbh = st.slider("Bottom-Hole Temp (°F)", 80, 400, step=5, key="n_tbh")
        st.caption(
            "These PVT/thermal descriptors set the solution gas (Standing Rs), oil FVF "
            "and the in-situ densities that build the hydrostatic column — first-order "
            "VLP inputs the page previously froze at light-oil defaults. Seeded from the "
            "well (API/gas SG/water SG formation-typical; surface temp assumed; BHT "
            "derived from a geothermal gradient).")

    _provenance_table(seed)

    # --- regime / consistency guards ------------------------------------------
    # The seed caps Standing Pb at reservoir pressure; surface that here (both when the
    # user pushes the slider above Pres and when the *seeded default* was already clamped)
    # so a fully-saturated well is never shown with Pb == Pres as if it were derived.
    clamped_default = (bool(getattr(seed, "bubble_point_clamped", False))
                       and abs(float(n_pb) - float(n_pres)) < 1.0)
    if n_pb > n_pres:
        st.warning(
            f"Bubble point ({n_pb:,} psia) exceeds reservoir pressure ({n_pres:,} psia)"
            " — capping it at reservoir pressure and modeling a fully saturated "
            "(solution-gas-drive) reservoir. Lower the bubble point if the reservoir is "
            "undersaturated.")
    elif clamped_default:
        st.info(
            f"Bubble point shown at reservoir pressure ({n_pres:,} psia): the Standing Pb "
            f"from the seeded producing GOR ({seed.gor_scf_stb:,.0f} scf/STB) is "
            f"{seed.bubble_point_raw_psia:,.0f} psia — above static pressure — so this well "
            "is modeled fully saturated (solution-gas drive). The produced GOR overstates "
            "solution Rs for high-GOR wells; lower the GOR or bubble point if the reservoir "
            "is undersaturated.")
    pb_eff = float(min(n_pb, n_pres))

    if n_ipr_mode == "Vogel (test point)":
        if n_pwftest >= n_pres:
            st.warning("Flow-test pwf should be below reservoir pressure.")
        ipr = core.wps_nodal.vogel_ipr(
            p_res=float(n_pres), pb=pb_eff,
            q_test=float(n_qtest), pwf_test=float(min(n_pwftest, n_pres - 1)))
    else:
        ipr = core.wps_nodal.straight_line_ipr(p_res=float(n_pres), j=float(n_j))

    vlp_in = core.wps_nodal.VLPInputs(
        tubing_id_in=float(n_id), depth_ft=float(n_depth),
        wellhead_pressure=float(n_whp), glr_scf_stb=float(n_glr),
        water_cut=float(n_wc), oil_api=float(n_api), gas_sg=float(n_gsg),
        water_sg=float(n_wsg), temp_surface_f=float(n_tsurf),
        temp_bottom_f=float(n_tbh), correlation=n_corr)
    vlp = _vlp_curve(vlp_in, q_max=float(ipr.aof) * 0.98, n=26)
    op = core.wps_nodal.operating_point(ipr, vlp)

    corr_label = _CORR_LABEL[n_corr]
    is_vogel = n_ipr_mode == "Vogel (test point)"
    # AOF is the physical open-flow potential for Vogel (curve bends to a finite rate at
    # pwf=0). For a straight-line PI it is J*p_res — the single-phase line extrapolated
    # below the bubble point, where free gas would actually break out; an upper bound, not
    # a real AOF. Label it honestly rather than presenting it with Vogel's authority.
    kpis = [
        {"label": "Operating Rate",
         "value": f"{op.q_op:,.0f} STB/d" if op.converged else "no flow"},
        {"label": "Operating Pwf",
         "value": f"{op.pwf_op:,.0f} psia" if op.converged else "—"},
    ]
    if is_vogel:
        kpis.append({"label": "AOF", "value": f"{ipr.aof:,.0f} STB/d",
                     "help": "Absolute open-flow potential — Vogel rate at pwf = 0."})
    else:
        kpis.append({
            "label": "AOF (upper bound)", "value": f"{ipr.aof:,.0f} STB/d",
            "help": "J × p_res: the linear PI extrapolated to pwf = 0. Ignores "
                    "below-bubble-point gas breakout, so it overstates the true open-"
                    "flow potential — treat as an upper bound, not a Vogel AOF."})
    kpis.append({"label": "Correlation", "value": corr_label})
    pt.kpi_row(kpis)

    if not is_vogel:
        if pb_eff > 0 and op.converged and op.pwf_op < pb_eff:
            theme.flag(
                f"Operating pwf ({op.pwf_op:,.0f} psia) is below the bubble point "
                f"({pb_eff:,.0f} psia): free gas breaks out at the perfs, so the "
                "straight-line PI overstates inflow here. Switch to the Vogel model for "
                "the saturated regime.", "warn")
        else:
            theme.source_note(
                "Straight-line PI is valid only while flowing pressure stays above the "
                "bubble point (single-phase liquid inflow). The AOF shown is the line "
                "extrapolated to pwf = 0 — an upper bound.")

    if not op.converged:
        theme.flag("No IPR∩VLP intersection — the reservoir cannot lift this column "
                   "(needs artificial lift). See Artificial Lift Design.", "warn")

    # Persist the design lens for the Case File (keyed to the selected well, and now
    # genuinely well-specific). Stash the seeded inputs + correlation so the Case File
    # can show the real per-well numbers behind the operating point.
    st.session_state[f"nodal::{wid}"] = {
        "q_op": float(op.q_op), "pwf_op": float(op.pwf_op),
        "converged": bool(op.converged), "aof": float(ipr.aof),
        "correlation": n_corr, "ipr_mode": "vogel" if is_vogel else "pi",
        "p_res": float(n_pres), "pb": pb_eff, "tubing_id_in": float(n_id),
        "depth_ft": float(n_depth), "glr_scf_stb": float(n_glr),
        "water_cut": float(n_wc), "whp_psia": float(n_whp),
        "oil_api": float(n_api), "gas_sg": float(n_gsg), "water_sg": float(n_wsg),
        "temp_surface_f": float(n_tsurf), "temp_bottom_f": float(n_tbh),
        "seeded_from": wid,
    }

    fig = go.Figure()
    fig.add_scatter(x=ipr.q, y=ipr.pwf,
                    name=f"IPR (inflow — {'Vogel' if is_vogel else 'straight-line PI'})",
                    line=dict(color=theme.BLUE))
    fig.add_scatter(x=vlp.q, y=vlp.pwf, name=f"VLP (outflow — {corr_label})",
                    line=dict(color=theme.AMBER))
    if pb_eff > 0 and is_vogel:
        fig.add_hline(y=pb_eff, line=dict(color=theme.GREY, width=1, dash="dot"),
                      annotation_text="bubble point", annotation_position="top right")
    if op.converged:
        fig.add_scatter(x=[op.q_op], y=[op.pwf_op], name="Operating point",
                        mode="markers",
                        marker=dict(size=13, color=theme.GREEN, symbol="x",
                                    line=dict(width=2)))
    fig.update_layout(
        title=f"Nodal Plot — {seed.name}: IPR × {corr_label} VLP at the bottom-hole node",
        xaxis_title="Liquid rate q (STB/d)",
        yaxis_title="Flowing BHP, pwf (psia)")
    st.plotly_chart(theme.style_fig(fig, height=420), width="stretch")
    theme.source_note(
        f"Operating point = intersection of the {'Vogel' if is_vogel else 'straight-line PI'}"
        f" IPR (inflow) and the {corr_label} VLP (outflow), seeded from {wid}; BHP in "
        "psia, liquid rate in STB/d. Stored to the Case File design lens for the "
        "selected well.")

    # ---- sensitivity to the assumed inputs (the "how much do the assumptions matter?"
    # question a PE asks the moment they see formation-typical seeds) ------------------
    if op.converged and op.q_op > 0:
        pt.section("Operating-Point Sensitivity — How Much Do The Assumptions Move It?",
                   "One-at-a-time swing in the operating RATE as each uncertain input "
                   "ranges over a plausible band, the others held at the values above. "
                   "The widest bars are where a better measurement would pay off most.")
        base_q, srows = _op_sensitivity(
            "vogel" if is_vogel else "pi", float(n_pres), pb_eff,
            float(n_qtest) if is_vogel else 0.0,
            float(n_pwftest) if is_vogel else 0.0,
            float(n_j) if not is_vogel else 0.0, float(n_id), float(n_depth),
            float(n_glr), float(n_wc), float(n_whp), float(n_api), float(n_gsg),
            float(n_wsg), float(n_tsurf), float(n_tbh), n_corr)
        srows = sorted(srows, key=lambda r: abs(r["q_hi"] - r["q_lo"]))  # asc for h-bars
        tfig = go.Figure()
        for r in srows:
            lo_q, hi_q = r["q_lo"], r["q_hi"]
            left, right = min(lo_q, hi_q), max(lo_q, hi_q)
            tfig.add_trace(go.Bar(
                y=[r["var"]], x=[right - left], base=[left], orientation="h",
                marker_color=theme.BLUE, showlegend=False,
                hovertemplate=(f"{r['var']}: %{{base:.0f}}–{right:.0f} STB/d<br>"
                               f"input {r['lo_in']:.{r['dec']}f}–{r['hi_in']:.{r['dec']}f} "
                               f"{r['unit']}<extra></extra>")))
        tfig.add_vline(x=base_q, line=dict(color=theme.GREEN, width=2, dash="dash"),
                       annotation_text=f"base {base_q:,.0f}", annotation_position="top")
        tfig.update_layout(title="Operating-Rate Tornado (STB/d)",
                           xaxis_title="Operating liquid rate q (STB/d)",
                           yaxis_title=None, bargap=0.35)
        st.plotly_chart(theme.style_fig(tfig, height=300, legend=False), width="stretch")
        top = max(srows, key=lambda r: abs(r["q_hi"] - r["q_lo"]))
        swing = abs(top["q_hi"] - top["q_lo"])
        st.caption(
            f"Most sensitive to **{top['var']}**: the operating rate moves "
            f"**{swing:,.0f} STB/d** ({min(top['q_lo'], top['q_hi']):,.0f}–"
            f"{max(top['q_lo'], top['q_hi']):,.0f}) as it ranges "
            f"{top['lo_in']:.{top['dec']}f}–{top['hi_in']:.{top['dec']}f} {top['unit']}. "
            "Where that input is a formation-typical assumption, a real measurement is the "
            "highest-value data to acquire before trusting the operating point.")
        theme.source_note(
            "One-at-a-time sensitivity: each input perturbed to a plausible low/high "
            "(reservoir pressure ±15%, API ±4, tubing ID ±0.2 in, GLR ±25%, water cut "
            "±0.10) with all others fixed; bars show the resulting operating-rate span.")

    nodal_df = pd.DataFrame({
        "rate_stb_d_ipr": ipr.q, "pwf_psia_ipr": ipr.pwf,
        "rate_stb_d_vlp": list(vlp.q) + [None] * max(0, len(ipr.q) - len(vlp.q)),
        "pwf_psia_vlp": list(vlp.pwf) + [None] * max(0, len(ipr.q) - len(vlp.q)),
    })
    # Header metadata so an exported curve is traceable to its method + the well it came
    # from (audit: the CSV carried no correlation/well provenance).
    meta = (f"# well={wid} ({seed.name}); ipr={'vogel' if is_vogel else 'straight_line_pi'};"
            f" vlp_correlation={n_corr}; p_res={n_pres}psia; pb={pb_eff:.0f}psia;"
            f" tubing_id={n_id}in; depth={n_depth}ft; glr={n_glr}scf/stb; wc={n_wc};"
            f" whp={n_whp}psia; oil_api={n_api}; gas_sg={n_gsg}; water_sg={n_wsg};"
            f" t_surf={n_tsurf}F; t_bh={n_tbh}F\n")
    st.download_button(
        "Download Curves (CSV)", data=meta + nodal_df.to_csv(index=False),
        file_name=f"workbench_nodal_{wid}.csv", mime="text/csv")

    theme.references(["vogel", "hagedorn_brown", "beggs_brill", "nodal"])
