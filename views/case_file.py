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
import streamlit as st

import core
import product_theme as pt
import theme

from views import _common


# ---- lens computations (None = lens unavailable; views + markdown share these) ----

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
    return st.session_state.get(f"nodal::{wid}")


def _markdown_case_file(wid: str, ident: dict, deck: tuple, dec, risk, gl, des) -> str:
    oil_price, nri, discount = deck
    lines = [
        f"# Well Case File — {wid} ({ident['name']})",
        f"_{ident['basin_formation']} · {ident['lift']} lift · {ident['source']}_",
        f"_Deck: ${oil_price:,.0f}/bbl · {nri:.0%} NRI · {discount:.0%} discount · "
        f"generated {date.today().isoformat()} by Engineering Workbench "
        f"v{pt.PRODUCT_VERSION}_", "",
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
    else:
        lines.append("- _Lens unavailable — needs an injection survey (synthetic "
                     "gas-lift fleet well_001–well_020)._")
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
        lines.append("- _Engineer-supplied design inputs (session), not a tuned field match._")
    else:
        lines.append("- _Lens unavailable — configure and run Design → Nodal Analysis "
                     "for this well in this session._")
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

    deck = _common.deck()
    oil_price, nri, _discount = deck
    gas_cost = float(st.session_state.get("gas_cost", 1.50))

    dec = _decline_lens(wid)
    risk = _risk_lens(wid)
    gl = _gaslift_lens(wid, oil_price, gas_cost, nri)
    des = _design_lens(wid)

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
            if "eur_p50" in dec:
                pt.kpi_row([
                    {"label": "EUR P90", "value": f"{dec['eur_p90']/1000:,.0f} MBO"},
                    {"label": "EUR P50", "value": f"{dec['eur_p50']/1000:,.0f} MBO"},
                    {"label": "EUR P10", "value": f"{dec['eur_p10']/1000:,.0f} MBO"},
                ])
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
                       f"at the optimum (GLPC R² {gl['r2']:.3f}).")
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
            st.caption(f"Correlation: {des['correlation']} · engineer-supplied "
                       "session inputs, not a tuned field match.")
        else:
            pt.empty_state("Lens unavailable — configure and run Design → Nodal "
                           "Analysis for this well in this session.")

    # ---- the downloadable one-pager ---------------------------------------------
    md = _markdown_case_file(wid, ident, deck, dec, risk, gl, des)
    pt.section("One-Page Case File",
               "The same four lenses as a portable markdown brief.")
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
