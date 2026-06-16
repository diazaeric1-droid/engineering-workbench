"""Case File → Well Case File — every available engineering lens on one well,
on one screen, with a downloadable one-page markdown case file.

This page is the condensation argument: decline/EUR, failure risk + SHAP
drivers, the gas-lift recommendation, and the design operating point — each
rendered only where the well actually HAS the underlying data. A lens without
data renders an explicit empty state, never a fake number.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import core
import product_theme as pt
import theme

from views import _common


# ---- lens computations (None = lens unavailable; views + markdown share these) ----

def _usd_compact(x: float) -> str:
    """Compact USD: $X.XXMM above a million, else $Xk."""
    return f"${x/1e6:,.2f}MM" if abs(x) >= 1e6 else f"${x/1e3:,.0f}k"


def _decline_lens(wid: str) -> dict | None:
    well = core.production_well(wid)
    if well is None or len(well.production_history) < 5:
        return None
    fit = core.decline_fit_for(well)
    out = {
        "latest_oil": float(well.production_history[-1].get("oil_bopd", 0.0)),
        "qi": fit.qi, "b": fit.b, "r2": fit.r_squared,
        "real": core.is_real_well(wid),
    }
    try:
        hist = well.production_history
        tc = core.pec_decline.analyze_type_curve(
            np.array([r["day"] for r in hist], float),
            np.array([r.get("oil_bopd", 0.0) for r in hist], float))
        out["deviation_pct"] = tc.deviation_pct
    except Exception:  # noqa: BLE001
        out["deviation_pct"] = None
    fb = _common.forecast_bands_cached(wid)
    out["eur_available"] = fb is not None
    if fb is not None:
        out.update(eur_p90=fb.eur_p90, eur_p50=fb.eur_p50, eur_p10=fb.eur_p10)
    return out


def _risk_lens(wid: str) -> dict | None:
    features = _common.esp_features_cached()
    if core.is_real_well(wid) or wid not in features.index:
        return None
    probs, contribs = _common.esp_scores_cached()
    feat_row = features.loc[wid].to_dict()
    mode, evidence = core.esp_explainer.classify_failure_mode(feat_row)
    drivers = core.esp_explainer.top_drivers(contribs.loc[wid], k=3)
    sm = _common.survival_model_cached()
    med_rul = None
    if sm is not None:
        med_rul = int(sm.median_rul(features.loc[[wid]])[0])
    return {"risk": float(probs[wid]), "mode": mode, "evidence": evidence,
            "drivers": drivers, "median_rul": med_rul,
            "rul_capped": (sm is not None and med_rul is not None
                           and med_rul >= sm.max_horizon)}


def _gaslift_lens(wid: str, oil_price: float, gas_cost: float, nri: float) -> dict | None:
    fleet = _common.gla_fleet_cached()
    if core.is_real_well(wid) or wid not in fleet:
        return None
    params, wc, cur_inj, opt = core.analyze_gla_well(fleet[wid], oil_price,
                                                     gas_cost, nri)
    cur_oil = float(core.gla_glpc.glpc_rate(cur_inj, params)) * (1.0 - wc)
    cur_rev = float(core.gla_glpc.net_revenue_daily(cur_inj, params, wc,
                                                    oil_price, gas_cost, nri))
    delta = opt.q_inj_opt - cur_inj
    return {
        "cur_inj": cur_inj, "opt_inj": opt.q_inj_opt,
        "direction": ("Reduce" if delta < -0.05
                      else ("Increase" if delta > 0.05 else "Maintain")),
        "cur_oil": cur_oil, "opt_oil": opt.q_oil_opt,
        "daily_gain": opt.net_revenue_per_day - cur_rev, "r2": params.r2,
    }


def _design_lens(wid: str) -> dict | None:
    """Prefer the session-configured Nodal lens; otherwise auto-compute a well-specific
    operating point from the per-well design SEED so the Case File stands alone (no need
    to visit Nodal first). Either way the numbers are well-specific, not generic."""
    sess = st.session_state.get(f"nodal::{wid}")
    if sess:
        return sess
    return _design_from_seed(wid)


@st.cache_data(show_spinner=False)
def _design_from_seed(wid: str) -> dict | None:
    try:
        s = _common.design_seed_cached(wid)
        ipr = core.wps_nodal.vogel_ipr(
            p_res=s.reservoir_pressure_psia,
            pb=min(s.bubble_point_psia, s.reservoir_pressure_psia),
            q_test=s.test_rate_stb_d,
            pwf_test=min(s.test_pwf_psia, s.reservoir_pressure_psia - 1))
        vlp_in = core.wps_nodal.VLPInputs(
            tubing_id_in=s.tubing_id_in, depth_ft=s.depth_ft,
            wellhead_pressure=s.wellhead_pressure_psia, glr_scf_stb=s.glr_scf_stb,
            water_cut=s.water_cut_frac, oil_api=s.oil_api, gas_sg=s.gas_sg,
            water_sg=s.water_sg, temp_surface_f=s.temp_surface_f,
            temp_bottom_f=s.temp_bottom_f)
        vlp = core.wps_nodal.vlp_curve(vlp_in, q_max=float(ipr.aof) * 0.98, n=24)
        op = core.wps_nodal.operating_point(ipr, vlp)
        return {"q_op": float(op.q_op), "pwf_op": float(op.pwf_op),
                "converged": bool(op.converged), "aof": float(ipr.aof),
                "correlation": "hagedorn_brown", "seeded": True}
    except Exception:  # noqa: BLE001
        return None


@st.cache_data(show_spinner=False)
def _econ_lens(wid: str, oil_price: float, discount: float) -> dict | None:
    """Probabilistic economics for the indicated intervention (P10/P50/P90 NPV + payout
    probability + dominant tornado driver), via the same calibrated assumptions the AI
    Review uses. None when the well has no production or the indicated action is non-economic."""
    well = core.production_well(wid)
    if well is None:
        return None
    try:
        row = core.pec_portfolio.screen_wellfile(well)
    except Exception:  # noqa: BLE001
        return None
    if row.intervention in core.pec_portfolio._NON_ECONOMIC:
        return None
    d = core.pec_assumptions.intervention_defaults(row.intervention)
    if not d:
        return None
    # One realized price (deck WTI + basis differential) and risk by chance-of-success, so
    # this panel matches the AI Review and the risked point NPV — not a 100%-payout fantasy
    # off the raw deck price (PE review #18/#19).
    realized = float(oil_price) + float(core.pec_assumptions.REALIZED_DIFFERENTIAL)
    p_succ = float(d.get("p_success", 1.0))
    try:
        sim = core.pec_economics.simulate_intervention(
            name=row.intervention, treatment_cost_usd=d["cost_usd"],
            incremental_rate_bopd=d["uplift_bopd"], uplift_decline_per_yr=d["uplift_decline"],
            realized_price_per_bbl=realized, discount_rate=discount,
            opex_per_bbl=float(core.pec_assumptions.LOE_USD_PER_BBL),
            prob_success=p_succ, seed=42)
    except Exception:  # noqa: BLE001
        return None
    tordata = sim.get("tornado", {})
    top = max(tordata.items(), key=lambda kv: kv[1]["swing"], default=(None, None))
    return {"intervention": row.intervention, "npv_p90": sim["npv_p90_usd"],
            "npv_p50": sim["npv_p50_usd"], "npv_p10": sim["npv_p10_usd"],
            "prob_payout": sim["probability_of_payout"],
            "prob_loss": sim.get("probability_of_loss", 0.0), "prob_success": p_succ,
            "top_driver": top[0], "top_swing": (top[1]["swing"] if top[1] else 0.0)}


def _markdown_case_file(wid: str, ident: dict, deck: tuple, dec, risk, gl, des,
                        gas_cost: float = 1.50, econ=None) -> str:
    oil_price, nri, discount = deck
    deck_line = ("_Deck: "
                 f"${oil_price:,.0f}/bbl · {nri:.0%} NRI · {discount:.0%} discount"
                 + (f" · ${gas_cost:.2f}/Mscf injection gas" if gl else "")
                 + f" · generated {date.today().isoformat()} by Engineering "
                 f"Workbench v{pt.PRODUCT_VERSION}_")
    lines = [
        f"# Well Case File — {wid} ({ident['name']})",
        f"_{ident['basin_formation']} · {ident['lift']} lift · {ident['source']}_",
        deck_line, "",
    ]
    lines.append("## Decline & EUR")
    if dec:
        lines.append(f"- Latest oil rate **{dec['latest_oil']:,.0f} BOPD** · Arps "
                     f"qi {dec['qi']:,.0f} BOPD, b {dec['b']:.2f}, R² {dec['r2']:.3f}")
        if dec.get("deviation_pct") is not None:
            lines.append(f"- Type-curve deviation **{dec['deviation_pct']:+.0f}%**")
        if "eur_p50" in dec:
            lines.append(f"- EUR P90/P50/P10: {dec['eur_p90']/1000:,.0f} / "
                         f"{dec['eur_p50']/1000:,.0f} / {dec['eur_p10']/1000:,.0f} MBO "
                         "(prodpy Monte-Carlo, seed 42)")
        lines.append(f"- Data: {'REAL — Colorado ECMC monthly filings' if dec['real'] else 'synthetic (known ground truth)'}")
    else:
        lines.append("- _Lens unavailable — needs monthly production history (≥ 5 points)._")
    lines.append("")
    lines.append("## Failure Risk (30-Day, Calibrated)")
    if risk:
        lines.append(f"- 30-day failure probability **{risk['risk']:.0%}** · suspected "
                     f"mode **{risk['mode']}**")
        for f, v in risk["drivers"]:
            lines.append(f"- Driver: {f} ({v:+.2f} log-odds)")
        if risk.get("median_rul") is not None:
            rul = (f">{risk['median_rul']}" if risk["rul_capped"]
                   else f"{risk['median_rul']}")
            lines.append(f"- Median RUL (trained hazard model): **{rul} days**")
    else:
        lines.append("- _Lens unavailable — needs fleet SCADA (synthetic well_0NN "
                     "fleet only; real monthly filings carry no pump telemetry)._")
    lines.append("")
    lines.append("## Gas-Lift Optimum")
    if gl:
        lines.append(f"- **{gl['direction']} injection {gl['cur_inj']:.2f} → "
                     f"{gl['opt_inj']:.2f} Mscfd** (GLPC R² {gl['r2']:.3f})")
        lines.append(f"- Expected oil {gl['cur_oil']:.0f} → **{gl['opt_oil']:.0f} BOPD** · "
                     f"gain **${gl['daily_gain']:,.0f}/day**")
        lines.append(f"- Economics behind the gain: ${gas_cost:.2f}/Mscf injection "
                     f"gas, ${oil_price:,.0f}/bbl, {nri:.0%} NRI")
    else:
        lines.append("- _Lens unavailable — needs an injection survey (synthetic "
                     "gas-lift fleet well_001–well_020)._")
    lines.append("")
    lines.append("## Probabilistic Economics (Monte-Carlo)")
    if econ:
        lines.append(f"- Indicated **{econ['intervention']}** · NPV P90/P50/P10: "
                     f"{econ['npv_p90']/1e3:,.0f} / {econ['npv_p50']/1e3:,.0f} / "
                     f"{econ['npv_p10']/1e3:,.0f} k$ · P(payout) **{econ['prob_payout']:.0%}** "
                     f"· P(loss) **{econ.get('prob_loss', 0.0):.0%}**")
        if econ.get("top_driver"):
            lines.append(f"- Largest NPV swing driven by **{econ['top_driver']}** "
                         f"(±${econ['top_swing']/1e3:,.0f}k) — 10k-trial Monte-Carlo risked "
                         f"by the {econ.get('prob_success', 1.0):.0%} chance-of-success, seed 42")
    else:
        lines.append("- _Lens unavailable — needs a production well with an economic "
                     "indicated intervention._")
    lines.append("")
    lines.append("## Design Operating Point (Nodal)")
    if des:
        if des["converged"]:
            lines.append(f"- Operating point **{des['q_op']:,.0f} STB/d @ "
                         f"{des['pwf_op']:,.0f} psia** ({des['correlation']}) · AOF "
                         f"{des['aof']:,.0f} STB/d")
        else:
            lines.append(f"- No natural IPR∩VLP intersection at the configured system "
                         f"(AOF {des['aof']:,.0f} STB/d) — artificial-lift candidate")
        _src = ("auto-computed from the well's seeded design inputs"
                if des.get("seeded") else "engineer-supplied Nodal session inputs")
        lines.append(f"- _{_src} — a forward-design what-if, not a tuned field match._")
    else:
        lines.append("- _Lens unavailable — the nodal solve did not converge for this "
                     "well's seeded inputs._")
    lines.append("")
    lines.append("---")
    lines.append("_Deterministic outputs from vendored, certified component cores "
                 "(wps · pec · esp · gla). No LLM involved in any number above._")
    return "\n".join(lines)


def render() -> None:
    _common.ensure_state()
    wid = _common.current_well()
    ident = _common.well_identity(wid)
    pt.masthead("workbench", "Well Case File",
                "Every available engineering lens on one screen — the one-page "
                "answer to \"what do we know about this well?\"")
    _common.context()
    _common.provenance_badge(wid)

    av = core.availability(wid)
    st.markdown(
        " ".join([
            pt.pill("production", "ok") if av["production"] else pt.pill("no production", "muted"),
            pt.pill("SCADA", "ok") if av["scada"] else pt.pill("no SCADA", "muted"),
            pt.pill("injection survey", "ok") if av["injection"] else pt.pill("no injection survey", "muted"),
        ]), unsafe_allow_html=True)
    if not av["production"]:
        st.warning(
            "This well has no production stream"
            + (" (a SCADA-only synthetic well, well_042–well_100)" if av["scada"] else "")
            + " — the Decline/EUR and Gas-Lift lenses below will be unavailable. The "
            "Failure-Risk and Design lenses still render. Pick a production-bearing well "
            "in the Well Browser for a full case file.")

    deck = _common.deck()
    oil_price, nri, _discount = deck
    gas_cost = float(st.session_state.get("gas_cost", 1.50))

    dec = _decline_lens(wid)
    risk = _risk_lens(wid)
    gl = _gaslift_lens(wid, oil_price, gas_cost, nri)
    des = _design_lens(wid)
    econ = _econ_lens(wid, oil_price, _discount)

    # ---- four lenses, two columns ------------------------------------------------
    c1, c2 = st.columns(2)
    with c1:
        pt.section("Decline & EUR", "Diagnose — pec analyzers on this well's production.")
        if dec:
            pt.kpi_row([
                {"label": "Latest Oil", "value": f"{dec['latest_oil']:,.0f} BOPD"},
                {"label": "Arps b / R²", "value": f"{dec['b']:.2f} / {dec['r2']:.3f}"},
                {"label": "Vs Type Curve",
                 "value": (f"{dec['deviation_pct']:+.0f}%"
                           if dec.get("deviation_pct") is not None else "—")},
            ])
            if dec.get("eur_available"):
                pt.kpi_row([
                    {"label": "EUR P90", "value": f"{dec['eur_p90']/1000:,.0f} MBO"},
                    {"label": "EUR P50", "value": f"{dec['eur_p50']/1000:,.0f} MBO"},
                    {"label": "EUR P10", "value": f"{dec['eur_p10']/1000:,.0f} MBO"},
                ])
            else:
                st.caption("⚠️ EUR omitted — the Monte-Carlo forecast engine (prodpy) is "
                           "unavailable in this environment, so probabilistic EUR/NPV "
                           "could not be computed. The deterministic fit above stands.")
            # Decline sparkline (audit: the Case File was chart-free).
            _well = core.production_well(wid)
            _hist = _well.production_history if _well is not None else []
            if len(_hist) >= 2:
                _h = pd.DataFrame(_hist)
                _f = go.Figure(go.Scatter(
                    x=_h["day"], y=_h["oil_bopd"], mode="lines",
                    line=dict(color=theme.BLUE, width=1.6), fill="tozeroy",
                    fillcolor="rgba(79,129,189,0.10)"))
                _f.update_layout(title="Oil Rate History", xaxis_title=None,
                                 yaxis_title="BOPD", showlegend=False)
                st.plotly_chart(theme.style_fig(_f, height=180), width="stretch")
        else:
            pt.empty_state("Lens unavailable — needs monthly production history "
                           "(≥ 5 points).")

        pt.section("Gas-Lift Optimum", "Optimize — GLPC fit on this well's injection survey.")
        if gl:
            pt.kpi_row([
                {"label": "Injection", "value": f"{gl['cur_inj']:.2f} → {gl['opt_inj']:.2f}",
                 "help": "Current → economic optimum, Mscfd"},
                {"label": "Action", "value": gl["direction"]},
                {"label": "Daily Gain", "value": f"${gl['daily_gain']:,.0f}"},
            ])
            st.caption(f"Expected oil {gl['cur_oil']:.0f} → {gl['opt_oil']:.0f} BOPD "
                       f"at the optimum (GLPC R² {gl['r2']:.3f}); injection gas "
                       f"${gas_cost:.2f}/Mscf.")
            # GLPC sparkline with current vs optimum injection points (audit: chart-free).
            _fleet = _common.gla_fleet_cached()
            if wid in _fleet:
                _p, _wc, _ci, _opt = core.analyze_gla_well(_fleet[wid], oil_price,
                                                           gas_cost, nri)
                _q = np.linspace(0.0, max(_opt.q_inj_display_max, _ci * 1.5, 1.0), 80)
                _liq = core.gla_glpc.glpc_rate(_q, _p)
                _g = go.Figure()
                _g.add_trace(go.Scatter(x=_q, y=_liq, mode="lines", name="GLPC",
                                        line=dict(color=theme.BLUE, width=2)))
                _g.add_trace(go.Scatter(
                    x=[gl["opt_inj"]], y=[float(core.gla_glpc.glpc_rate(gl["opt_inj"], _p))],
                    mode="markers", name="Optimum",
                    marker=dict(color=theme.GREEN, size=12, symbol="star")))
                _g.add_trace(go.Scatter(
                    x=[gl["cur_inj"]], y=[float(core.gla_glpc.glpc_rate(gl["cur_inj"], _p))],
                    mode="markers", name="Current",
                    marker=dict(color=theme.AMBER, size=9, symbol="diamond")))
                _g.update_layout(title="Gas-Lift Performance Curve",
                                 xaxis_title="Injection gas (Mscfd)",
                                 yaxis_title="Gross liquid (blpd)")
                st.plotly_chart(theme.style_fig(_g, height=200), width="stretch")
        else:
            pt.empty_state("Lens unavailable — needs an injection survey "
                           "(synthetic gas-lift fleet only).")

    with c2:
        pt.section("Failure Risk", "Predict — calibrated classifier + trained survival model.")
        if risk:
            rul_val = "—"
            if risk.get("median_rul") is not None:
                rul_val = (f">{risk['median_rul']} d" if risk["rul_capped"]
                           else f"{risk['median_rul']} d")
            pt.kpi_row([
                {"label": "30-Day Risk", "value": f"{risk['risk']:.0%}"},
                {"label": "Suspected Mode", "value": risk["mode"]},
                {"label": "Median RUL", "value": rul_val},
            ])
            if risk.get("evidence"):
                st.caption(f"**Mode evidence:** {risk['evidence']}")
            st.markdown("**Top 3 SHAP drivers**")
            st.dataframe(pd.DataFrame(risk["drivers"],
                                      columns=["Feature", "Log-Odds"]),
                         width="stretch", hide_index=True)
        else:
            pt.empty_state("Lens unavailable — needs fleet SCADA (synthetic "
                           "well_0NN fleet; real monthly filings carry no pump "
                           "telemetry).")

        pt.section("Design Operating Point", "Design — nodal IPR∩VLP from this session.")
        if des:
            pt.kpi_row([
                {"label": "Operating Rate",
                 "value": f"{des['q_op']:,.0f} STB/d" if des["converged"] else "no flow"},
                {"label": "Operating Pwf",
                 "value": f"{des['pwf_op']:,.0f} psia" if des["converged"] else "—"},
                {"label": "AOF", "value": f"{des['aof']:,.0f} STB/d"},
            ])
            _src = ("auto-computed from the well's seeded design inputs"
                    if des.get("seeded") else "from your Design → Nodal session inputs")
            st.caption(f"Correlation: {des['correlation']} · {_src}; a forward-design "
                       "what-if, not a tuned field match.")
        else:
            pt.empty_state("Lens unavailable — the nodal solve did not converge for "
                           "this well's seeded inputs; open Design → Nodal Analysis to "
                           "configure it.")

    # ---- probabilistic economics (full-width, the capital decision) --------------
    pt.section("Probabilistic Economics", "Capital — Monte-Carlo NPV of the indicated "
               "intervention (same calibrated assumptions as the AI Well Review).")
    if econ:
        pt.kpi_row([
            {"label": "Indicated", "value": econ["intervention"]},
            {"label": "NPV P90", "value": _usd_compact(econ["npv_p90"]),
             "help": "Conservative (P90)"},
            {"label": "NPV P50", "value": _usd_compact(econ["npv_p50"])},
            {"label": "NPV P10", "value": _usd_compact(econ["npv_p10"]),
             "help": "Optimistic (P10)"},
            {"label": "P(payout)", "value": f"{econ['prob_payout']:.0%}"},
            {"label": "P(loss)", "value": f"{econ.get('prob_loss', 0.0):.0%}",
             "help": f"NPV<0, incl. the {1 - econ.get('prob_success', 1.0):.0%} chance the "
                     "job misses and the capital is sunk."},
        ])
        if econ.get("top_driver"):
            st.caption(f"Largest NPV swing driven by **{econ['top_driver']}** "
                       f"(±{_usd_compact(econ['top_swing'])}). 10k-trial Monte-Carlo over "
                       "rate/decline/price uncertainty, RISKED by the "
                       f"{econ.get('prob_success', 1.0):.0%} chance-of-success (seed 42); "
                       "see Diagnose → AI Well Review for the full distribution + tornado.")
    else:
        pt.empty_state("Lens unavailable — needs a production well whose indicated "
                       "intervention is economic (monitor / P&A / insufficient-data wells "
                       "have no intervention NPV).")

    # ---- the downloadable one-pager ---------------------------------------------
    md = _markdown_case_file(wid, ident, deck, dec, risk, gl, des, gas_cost, econ)
    pt.section("One-Page Case File",
               "The same lenses as a portable markdown brief.")
    st.download_button("Download Case File (Markdown)", md,
                       file_name=f"{wid}-case-file.md", mime="text/markdown")
    with st.expander("Preview Case File"):
        st.markdown(md)

    theme.source_note(
        "Lenses render only where this well has the underlying dataset "
        "(production / SCADA / injection / session design inputs) — an unavailable "
        "lens says so instead of showing fabricated numbers.")
    theme.references(["arps", "monte_carlo", "prms", "shap", "survival",
                      "gas_lift", "nodal", "npv"])
