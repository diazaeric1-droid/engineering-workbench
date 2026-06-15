"""Design → Artificial Lift Design — ESP affinity-law sizing + gas-lift sweep.

Ported from Well Performance Studio's Artificial Lift tab; the design math
(wps.lift — TDH, stages from a representative pump curve, affinity-law frequency
trim, viscosity de-rating, brake power) is vendored with only its internal import
rewritten to package-relative form (see VENDORING.md).

The design inputs are SEEDED from the selected well's design seed
(_common.design_seed_cached) so the forward-design what-if is anchored to the well
shown in the context bar, not generic constants. Each seeded input is paired with a
measured / derived / assumed provenance tag (see the "Where these inputs come from"
expander). The engineer can override any input; the seed only sets the starting point.
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


@st.cache_data(show_spinner=False)
def _design(p_res, q_test, pwf_test, tubing_id, depth, whp, glr, wc,
            target, freq, visc, oil_api, water_sg, oil_price, gas_cost, nri):
    """All of the ESP/gas-lift physics, cached on the scalar inputs. Previously each
    of the sliders re-marched the Hagedorn-Brown VLP ~120× (design_esp) + 14×
    (gas_lift_sweep) on every drag (~1.7 s). (perf #0)"""
    ipr = core.wps_nodal.vogel_ipr(
        p_res=float(p_res), pb=float(p_res),
        q_test=float(q_test), pwf_test=float(min(pwf_test, p_res - 1)))
    vlp_in = core.wps_nodal.VLPInputs(
        tubing_id_in=float(tubing_id), depth_ft=float(depth),
        wellhead_pressure=float(whp), glr_scf_stb=float(glr), water_cut=float(wc),
        oil_api=float(oil_api), water_sg=float(water_sg))
    op_nat = core.wps_nodal.operating_point(ipr, vlp_in)
    esp = core.wps_lift.design_esp(
        ipr, vlp_in, target_q_stb_d=float(target),
        frequency_hz=float(freq), fluid_viscosity_cp=float(visc))
    gl = core.wps_lift.gas_lift_sweep(
        ipr, vlp_in, inj_glr_max_scf_stb=1500.0, n=14,
        oil_price=float(oil_price), gas_cost=float(gas_cost), nri=float(nri))
    return op_nat, esp, gl


@st.cache_data(show_spinner=False)
def _stage_sensitivity(p_res, q_test, pwf_test, tubing_id, depth, whp, glr, wc,
                       target, freq, visc, oil_api, water_sg):
    """One-at-a-time swing in the ESP STAGE COUNT vs the uncertain drivers — the same
    'how much do the assumptions matter?' lens as Nodal, applied to the design deliverable.
    Reservoir pressure sets the intake (→ TDH); viscosity de-rates head/stage; water cut +
    depth set the column. Cached on the scalar inputs."""
    base = dict(p_res=p_res, q_test=q_test, pwf_test=pwf_test, tubing_id=tubing_id,
                depth=depth, whp=whp, glr=glr, wc=wc, target=target, freq=freq,
                visc=visc, oil_api=oil_api, water_sg=water_sg)

    def stages_of(**ov):
        d = {**base, **ov}
        try:
            ipr = core.wps_nodal.vogel_ipr(
                p_res=float(d["p_res"]), pb=float(d["p_res"]), q_test=float(d["q_test"]),
                pwf_test=float(min(d["pwf_test"], d["p_res"] - 1)))
            vlp = core.wps_nodal.VLPInputs(
                tubing_id_in=float(d["tubing_id"]), depth_ft=float(d["depth"]),
                wellhead_pressure=float(d["whp"]), glr_scf_stb=float(d["glr"]),
                water_cut=float(d["wc"]), oil_api=float(d["oil_api"]),
                water_sg=float(d["water_sg"]))
            esp = core.wps_lift.design_esp(
                ipr, vlp, target_q_stb_d=float(d["target"]), frequency_hz=float(d["freq"]),
                fluid_viscosity_cp=float(d["visc"]))
            return int(esp.stages), bool(esp.feasible)
        except Exception:  # noqa: BLE001
            return 0, False

    base_stages, _ = stages_of()
    specs = [
        ("Reservoir pressure", "p_res", p_res * 0.85, p_res * 1.15, "psia", 0),
        ("Fluid viscosity", "visc", max(visc * 0.5, 1.0), visc * 2.0, "cP", 0),
        ("Water cut", "wc", max(wc - 0.10, 0.0), min(wc + 0.10, 0.99), "frac", 2),
        ("Tubing depth", "depth", max(depth - 1000.0, 2000.0),
         min(depth + 1000.0, 16000.0), "ft", 0),
    ]
    rows = []
    for lab, key, lo, hi, unit, dec in specs:
        s_lo, f_lo = stages_of(**{key: lo})
        s_hi, f_hi = stages_of(**{key: hi})
        rows.append({"var": lab, "unit": unit, "dec": dec, "lo_in": float(lo),
                     "hi_in": float(hi), "s_lo": s_lo, "s_hi": s_hi,
                     "feasible": f_lo and f_hi})
    return int(base_stages), rows


_PROV_KIND = {"measured": "ok", "derived": "info", "assumed": "warn", "n/a": "muted"}
_PROV_LABEL = {
    "measured": "Read from the well's own production / SCADA data.",
    "derived": "Computed from measured values via a standard correlation.",
    "assumed": "Formation-typical engineering estimate (not in the public well file).",
    "n/a": "Not available for this well.",
}


def render() -> None:
    _common.ensure_state()
    pt.masthead("workbench", "Artificial Lift Design",
                "Size an ESP (stages · frequency · TDH · power) and sweep gas-lift "
                "injection for a target rate the well cannot reach naturally")
    _common.context()

    wid = _common.current_well()
    seed = _common.design_seed_cached(wid)
    oil_price, nri, _disc = _common.deck()
    gas_cost = _common.gas_cost()

    theme.data_badge(
        "synthetic",
        "Physics-modeled — standard design equations (Takács; Hydraulic Institute; "
        "affinity laws). Inputs are SEEDED from the selected well's design seed "
        "(measured where the well file has it, derived via correlation, else "
        "formation-typical); illustrative pump curve, not a vendor catalog match.")
    st.caption(
        f"Forward-design scenario for **{wid} · {seed.name}** "
        f"({seed.formation}). Inputs below are pre-filled from this well's design seed "
        "and re-seed when you change the selected well; override any of them to explore "
        "a what-if. This is a design study for the selected well, not a history-matched "
        "model of it.")

    # ---- per-well seeding: set widget defaults BEFORE the widgets instantiate, gated on
    # a sentinel so a well change re-seeds but user edits within a well are preserved ----
    target_seed = _target_seed(seed)
    if st.session_state.get("ld_seeded_well") != wid:
        st.session_state["l_pres"] = int(np.clip(round(seed.reservoir_pressure_psia), 800, 8000))
        st.session_state["l_qtest"] = int(np.clip(round(seed.test_rate_stb_d), 50, 5000))
        st.session_state["l_pwftest"] = int(np.clip(
            round(seed.test_pwf_psia), 100, st.session_state["l_pres"] - 1))
        st.session_state["l_id"] = float(np.clip(seed.tubing_id_in, 1.0, 5.0))
        st.session_state["l_depth"] = int(np.clip(round(seed.depth_ft), 2000, 16000))
        st.session_state["l_wc"] = float(np.clip(round(seed.water_cut_frac, 2), 0.0, 0.99))
        st.session_state["l_glr"] = int(np.clip(round(seed.glr_scf_stb), 0, 3000))
        st.session_state["l_target"] = int(np.clip(round(target_seed), 100, 5000))
        st.session_state["l_freq"] = float(np.clip(
            round(seed.esp_frequency_hz) if seed.esp_frequency_hz else 60.0, 40.0, 70.0))
        st.session_state["l_visc"] = float(np.clip(round(seed.fluid_viscosity_cp), 1.0, 300.0))
        st.session_state["l_whp"] = int(np.clip(
            round(seed.wellhead_pressure_psia / 10.0) * 10, 30, 1500))
        st.session_state["l_api"] = float(np.clip(round(seed.oil_api, 1), 10.0, 60.0))
        st.session_state["l_wsg"] = float(np.clip(round(seed.water_sg, 3), 1.0, 1.20))
        st.session_state["ld_seeded_well"] = wid

    pt.section("Well System & Design Targets",
               "Pre-filled from the selected well's design seed — override to explore "
               "a what-if. See provenance below.")
    c1, c2, c3 = st.columns(3)
    with c1:
        l_pres = st.slider("Reservoir Pressure (psia)", 800, 8000, step=50, key="l_pres")
        l_qtest = st.slider("Flow-Test Rate (STB/d)", 50, 5000, step=25, key="l_qtest")
        l_pwftest = st.slider("Flow-Test Pwf (psia)", 100, int(l_pres), step=25,
                              key="l_pwftest")
    with c2:
        l_id = st.slider("Tubing ID (in.)", 1.0, 5.0, step=0.001, key="l_id")
        l_depth = st.slider("Tubing Depth (ft)", 2000, 16000, step=100, key="l_depth")
        l_wc = st.slider("Water Cut (fraction)", 0.0, 0.99, step=0.01, key="l_wc")
        l_glr = st.slider("Formation GLR (scf/STB)", 0, 3000, step=25, key="l_glr")
    with c3:
        l_target = st.slider("Target Liquid Rate (STB/d)", 100, 5000, step=25,
                             key="l_target")
        l_freq = st.slider("ESP Drive Frequency (Hz)", 40.0, 70.0, step=1.0,
                           key="l_freq")
        l_visc = st.slider("Fluid Viscosity (cP)", 1.0, 300.0, step=1.0, key="l_visc")
        l_whp = st.slider("Wellhead Pressure (psia)", 30, 1500, step=10, key="l_whp")

    # Fluid descriptors that drive TDH / brake-HP (audit: hidden API / SG defaults).
    cf1, cf2, _cf3 = st.columns(3)
    with cf1:
        l_api = st.slider("Oil Gravity (°API)", 10.0, 60.0, step=0.5, key="l_api",
                          help="Drives the fluid gradient → TDH, stage count, and brake "
                               "HP. Lower API (heavy oil) = heavier column = more head.")
    with cf2:
        l_wsg = st.slider("Water Specific Gravity", 1.0, 1.20, step=0.005, key="l_wsg",
                          help="Produced-water SG; raises the fluid gradient with water "
                               "cut.")

    with st.expander("Where these inputs come from (measured · derived · assumed)"):
        _provenance_table(seed, target_seed)

    if l_pwftest >= l_pres:
        st.warning("Flow-test pwf should be below reservoir pressure.")
    op_nat, esp, gl = _design(
        l_pres, l_qtest, l_pwftest, l_id, l_depth, l_whp, l_glr, l_wc,
        l_target, l_freq, l_visc, l_api, l_wsg, oil_price, gas_cost, nri)
    nat_q = op_nat.q_op if op_nat.converged else None

    pt.section("ESP Design")
    pt.kpi_row([
        {"label": "Stages", "value": (f"{esp.stages:,d}+" if esp.stages_capped
                                      else f"{esp.stages:,d}"),
         # stages_capped fires either because the target is past runout (infeasible) OR
         # because a feasible design simply needs more than MAX_STAGES of head — distinguish
         # them so the tooltip never points at a runout flag that isn't shown.
         "help": ("TDH ÷ viscosity-corrected head-per-stage." if not esp.stages_capped
                  else ("Capped — target exceeds the pump's runout (see flag below)."
                        if not esp.feasible
                        else f"Capped at {core.wps_lift.MAX_STAGES} stages — required TDH "
                             "exceeds this pump series; select a higher-head pump."))},
        {"label": "Frequency", "value": f"{esp.frequency_hz:.0f} Hz"},
        {"label": "Total Dynamic Head", "value": f"{esp.tdh_ft:,.0f} ft"},
        {"label": "Brake Power", "value": (f"{esp.bhp:,.0f} hp" if esp.feasible else "—"),
         "help": None if esp.feasible else "Undefined above pump runout."},
    ])
    pt.kpi_row([
        {"label": "Natural Rate",
         "value": (f"{nat_q:,.0f} STB/d" if nat_q is not None else "no natural flow"),
         "help": ("The reservoir cannot lift this tubing column unaided — the premise "
                  "for artificial lift." if nat_q is None else
                  "Nodal operating rate with no pump installed.")},
        {"label": "Rate With ESP", "value": f"{esp.op_q_stb_d:,.0f} STB/d"},
        {"label": "Pump Intake P", "value": f"{esp.pump_intake_psia:,.0f} psia"},
        {"label": "Stage Efficiency", "value": f"{esp.efficiency:.0%}",
         "help": f"Viscosity de-rate at {l_visc:.0f} cP: head ×{esp.head_visc_factor:.2f}, "
                 f"eff ×{esp.eff_visc_factor:.2f}."},
    ])

    tol_pct = (1.0 - esp.meets_target_tol) * 100.0
    if not esp.feasible:
        theme.flag(
            f"Target {l_target:,.0f} STB/d ({esp.total_fluid_bpd:,.0f} bpd total fluid) "
            f"exceeds this pump's runout of {esp.runout_bpd:,.0f} bpd at {l_freq:.0f} Hz. "
            "Head per stage collapses to ~0 and the stage count is unbounded — select a "
            "larger pump series or raise the drive frequency.", "high")
    elif esp.meets_target:
        theme.flag(f"Design meets the {l_target:,.0f} STB/d target "
                   f"(within {tol_pct:.0f}% — reaches {esp.op_q_stb_d:,.0f} STB/d at the "
                   "boosted operating point).", "ok")
    else:
        theme.flag(f"Design falls short of {l_target:,.0f} STB/d (reaches "
                   f"{esp.op_q_stb_d:,.0f}, below the {esp.meets_target_tol:.0%} tolerance). "
                   "Raise frequency/stages or check the IPR.", "high")

    cL, cR = st.columns(2)
    with cL:
        pm = core.wps_lift.PumpModel()
        # x-range scaled to the frequency-shifted runout AND far enough right to keep the
        # design point on-plot; curve uses the SAME viscosity de-rate as the design point.
        x_max = max(pm.runout_bpd(esp.frequency_hz) * 0.98, esp.total_fluid_bpd * 1.05)
        q_curve = np.linspace(200.0, x_max, 60)
        h_curve = np.array([pm.head_per_stage_visc(q, esp.frequency_hz, l_visc)
                            for q in q_curve])
        figp = go.Figure()
        figp.add_scatter(
            x=q_curve, y=h_curve,
            name=(f"Head/stage @ {esp.frequency_hz:.0f} Hz"
                  + (f" (visc-derated ×{esp.head_visc_factor:.2f})"
                     if esp.head_visc_factor < 0.999 else "")),
            line=dict(color=theme.BLUE))
        figp.add_vline(x=esp.runout_bpd, line=dict(color=theme.GREY, dash="dot"),
                       annotation_text="runout", annotation_position="top")
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
        # technical max: honest label depending on whether it is an interior rollover
        tech_name = ("Rate rollover (max)" if gl.rollover
                     else "Max swept (still rising — no rollover)")
        figg.add_scatter(x=[gl.best.inj_glr_scf_stb], y=[gl.best.q_op_stb_d],
                         name=tech_name, mode="markers",
                         marker=dict(size=11, color=theme.GREY, symbol="circle-open",
                                     line=dict(width=2)))
        if gl.econ is not None:
            figg.add_scatter(x=[gl.econ.inj_glr_scf_stb], y=[gl.econ.q_op_stb_d],
                             name="Economic optimum (max net $)", mode="markers",
                             marker=dict(size=12, color=theme.GREEN, symbol="x",
                                         line=dict(width=2)))
        figg.update_layout(title="Gas-Lift Injection Sweep",
                           xaxis_title="Injection GLR added (scf/STB)",
                           yaxis_title="Operating rate q (STB/d)")
        st.plotly_chart(theme.style_fig(figg, height=320), width="stretch")

    # honest gas-lift caption
    if gl.econ is not None:
        gl_msg = (
            f"Economic optimum: add **{gl.econ.inj_glr_scf_stb:,.0f} scf/STB** "
            f"(~{gl.inj_rate_mscf_d_at_econ:,.0f} Mscf/d) → {gl.econ.q_op_stb_d:,.0f} "
            f"STB/d for **${gl.econ_net_usd_d:,.0f}/d** net (incremental oil @ "
            f"${oil_price:,.0f}/bbl × {nri:.0%} NRI − gas @ ${gas_cost:,.2f}/Mcf). ")
    else:
        gl_msg = ""
    if not gl.rollover:
        gl_msg += (
            f"Production is still rising at the max swept injection "
            f"({gl.best.inj_glr_scf_stb:,.0f} scf/STB → {gl.best.q_op_stb_d:,.0f} STB/d) "
            "— no physical rate rollover within the swept range, so the technical 'max' "
            "is a sweep boundary, not an optimum. The economic optimum (diminishing-"
            "returns knee) is the real operating choice. ")
    else:
        gl_msg += (
            f"Rate rolls over at {gl.best.inj_glr_scf_stb:,.0f} scf/STB "
            f"({gl.best.q_op_stb_d:,.0f} STB/d). ")

    cap_note = ("" if esp.feasible else
                f" Stage count is capped at {core.wps_lift.MAX_STAGES} — the target "
                "exceeds pump runout (see flag above).")
    st.caption(
        f"{esp.notes}{cap_note} TDH and brake horsepower per the standard "
        "Hydraulic-Institute / Takács design equations; stages = TDH ÷ "
        f"viscosity-corrected head-per-stage. {gl_msg}For the full economic injection "
        "optimum on a surveyed well, see Optimize → Gas-Lift Optimum.")
    theme.source_note(
        "ESP staging via centrifugal-pump affinity laws (Q∝N, H∝N², P∝N³) on TDH; the "
        "plotted pump curve and the green design point share one viscosity head de-rate "
        "and the x-range tracks the frequency-scaled runout, so the design point always "
        "lies on its own curve. Gas-lift economic optimum = injection rate maximizing "
        "incremental oil revenue minus lift-gas cost at the page deck.")

    # ---- stage-count sensitivity to the uncertain inputs --------------------------
    if esp.feasible:
        pt.section("Stage-Count Sensitivity — How Much Do The Assumptions Move The Design?",
                   "One-at-a-time swing in the required ESP stage count as each uncertain "
                   "driver ranges over a plausible band, the others held at the values "
                   "above. The widest bar is where a real measurement most changes the pump.")
        base_st, srows = _stage_sensitivity(
            float(l_pres), float(l_qtest), float(l_pwftest), float(l_id), float(l_depth),
            float(l_whp), float(l_glr), float(l_wc), float(l_target), float(l_freq),
            float(l_visc), float(l_api), float(l_wsg))
        srows = [r for r in srows if r["feasible"]]
        if srows:
            srows = sorted(srows, key=lambda r: abs(r["s_hi"] - r["s_lo"]))
            tfig = go.Figure()
            for r in srows:
                left, right = min(r["s_lo"], r["s_hi"]), max(r["s_lo"], r["s_hi"])
                tfig.add_trace(go.Bar(
                    y=[r["var"]], x=[right - left], base=[left], orientation="h",
                    marker_color=theme.BLUE, showlegend=False,
                    hovertemplate=(f"{r['var']}: {left:.0f}–{right:.0f} stages<br>"
                                   f"input {r['lo_in']:.{r['dec']}f}–"
                                   f"{r['hi_in']:.{r['dec']}f} {r['unit']}<extra></extra>")))
            tfig.add_vline(x=base_st, line=dict(color=theme.GREEN, width=2, dash="dash"),
                           annotation_text=f"base {base_st}", annotation_position="top")
            tfig.update_layout(title="ESP Stage-Count Tornado",
                               xaxis_title="Required stages", yaxis_title=None, bargap=0.35)
            st.plotly_chart(theme.style_fig(tfig, height=260, legend=False),
                            width="stretch")
            top = max(srows, key=lambda r: abs(r["s_hi"] - r["s_lo"]))
            st.caption(
                f"Most sensitive to **{top['var']}**: the design swings "
                f"**{abs(top['s_hi'] - top['s_lo'])} stages** "
                f"({min(top['s_lo'], top['s_hi'])}–{max(top['s_lo'], top['s_hi'])}) over "
                f"{top['lo_in']:.{top['dec']}f}–{top['hi_in']:.{top['dec']}f} {top['unit']}. "
                "Confirm that input before committing the pump order.")
            theme.source_note(
                "Each driver perturbed to a plausible low/high (reservoir pressure ±15%, "
                "viscosity ×0.5–×2, water cut ±0.10, depth ±1000 ft) with the others fixed; "
                "bars show the resulting stage-count span (feasible perturbations only).")

    theme.references(["esp_affinity", "gas_lift"])


def _target_seed(seed) -> float:
    """A defensible design target for the well: restore toward its early-life potential.

    Prefer the measured flow-test rate (the rate the well demonstrably delivered) and aim
    a touch above current production; floor at the current liquid rate so the target is
    never below what the well already makes. Falls back to 1.2× current liquid or the
    test rate when production is absent.
    """
    cur_liq = float(seed.current_oil_bopd + seed.current_water_bwpd)
    test = float(seed.test_rate_stb_d)
    # aim at the larger of (the flow-test/IPR-anchored rate) and (a modest uplift on
    # current production) — i.e. restore toward early-life deliverability.
    candidate = max(test, cur_liq * 1.25 if cur_liq > 0 else test)
    return float(np.clip(candidate, 100.0, 5000.0))


def _provenance_table(seed, target_seed: float) -> None:
    """Render the seed's measured / derived / assumed provenance as a labeled table."""
    prov = seed.provenance or {}
    rows = [
        ("Reservoir pressure", f"{seed.reservoir_pressure_psia:,.0f} psia",
         prov.get("reservoir_pressure_psia", "assumed")),
        ("Flow-test rate", f"{seed.test_rate_stb_d:,.0f} STB/d",
         prov.get("test_rate_stb_d", "assumed")),
        ("Flow-test pwf", f"{seed.test_pwf_psia:,.0f} psia",
         prov.get("test_pwf_psia", "assumed")),
        ("Tubing ID", f"{seed.tubing_id_in:.3f} in.", prov.get("tubing_id_in", "assumed")),
        ("Tubing depth", f"{seed.depth_ft:,.0f} ft", prov.get("depth_ft", "assumed")),
        ("Water cut", f"{seed.water_cut_frac:.0%}", prov.get("water_cut_frac", "assumed")),
        ("Formation GLR", f"{seed.glr_scf_stb:,.0f} scf/STB",
         prov.get("glr_scf_stb", "assumed")),
        ("Wellhead pressure", f"{seed.wellhead_pressure_psia:,.0f} psia",
         prov.get("wellhead_pressure_psia", "assumed")),
        ("Fluid viscosity", f"{seed.fluid_viscosity_cp:,.0f} cP",
         prov.get("fluid_viscosity_cp", "derived")),
        ("Oil gravity", f"{seed.oil_api:.1f} °API", prov.get("oil_api", "assumed")),
        ("Water SG", f"{seed.water_sg:.3f}", prov.get("water_sg", "assumed")),
        ("ESP drive frequency",
         (f"{seed.esp_frequency_hz:.0f} Hz" if seed.esp_frequency_hz else "—"),
         "measured" if seed.esp_frequency_hz else "assumed"),
        ("Design target (seeded)", f"{target_seed:,.0f} STB/d", "derived"),
    ]
    df = pd.DataFrame(
        [{"Input": r[0], "Seeded value": r[1],
          "Source": r[2].capitalize(),
          "Meaning": _PROV_LABEL.get(r[2], "")} for r in rows])
    st.dataframe(df, hide_index=True, width="stretch")
    counts = {k: sum(1 for r in rows if r[2] == k)
              for k in ("measured", "derived", "assumed")}
    chips = " ".join(
        pt.pill(f"{counts[k]} {k}", _PROV_KIND[k]) for k in ("measured", "derived", "assumed")
        if counts[k])
    st.markdown(chips, unsafe_allow_html=True)
    st.caption(
        "Measured = read from the well's own production / SCADA data · Derived = computed "
        "from measured values via a standard correlation (Standing bubble point, "
        "geothermal BHT, live-oil viscosity) · Assumed = formation-typical estimate (the "
        "public well file does not carry it). Override any input above to depart from the "
        "seed; the design target is seeded toward the well's early-life deliverability.")
