"""Diagnose → AI Well Review — the tool-use one-page well review (BYOK), grounded
by the same deterministic analyzers the keyless panels show.

Everything above the review button renders with NO key: the deterministic
portfolio screen (diagnosis + indicated intervention + risked economics) and the
water/gas trend flags. The Claude review (pec.agent.run_review — Claude reasons,
deterministic Python tools do the math) needs the session Anthropic key.

Honest eval: the committed blind holdout grades the agent at 0.722 recommendation
agreement under STRICT exact-class matching — surfaced verbatim, not rounded up.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import core
import product_theme as pt
import theme

from views import _common


def render() -> None:
    _common.ensure_state()
    pt.masthead("workbench", "AI Well Review",
                "One-page well review: Claude reasons over deterministic "
                "petroleum-engineering tool outputs",
                chips=[(f"v{pt.PRODUCT_VERSION}", "ver"),
                       ("0.72 blind holdout (strict)", "eval")])
    _common.context()

    wid = _common.current_well()
    well = core.production_well(wid)
    if well is None:
        pt.empty_state(
            f"{wid} has no production history — the well review needs monthly "
            "production (real Colorado wells or the synthetic well_0NN fleet).",
            "Pick a well with the Production flag in the Well Browser.")
        return

    _common.provenance_badge(wid)

    # ---- deterministic screen (keyless) ----------------------------------------
    pt.section("Deterministic Screen (No Key Required)",
               "The same analyzers the agent calls as tools — Arps fit, water/gas "
               "trends, ESP POR check, risked NPV — run here directly.")
    try:
        row = core.pec_portfolio.screen_wellfile(well)
    except Exception as exc:  # noqa: BLE001
        row = None
        st.warning(f"Portfolio screen unavailable for this well: {exc}")

    if row is not None:
        econ_ok = row.intervention not in core.pec_portfolio._NON_ECONOMIC
        pt.kpi_row([
            {"label": "Indicated Intervention", "value": row.intervention},
            {"label": "Risked NPV", "value": f"${row.npv_usd:,.0f}" if econ_ok else "—"},
            {"label": "Profitability Index",
             "value": f"{row.profitability_index:.2f}" if econ_ok else "—"},
            {"label": "Remaining EUR", "value": f"{row.remaining_eur_bbl/1000:,.0f} MBO"},
        ])
        st.markdown(f"**Diagnosis:** {row.diagnosis}")

    try:
        wg = core.pec_decline.analyze_water_gas_trends(well.production_history)
        flags = wg.flags or []
        cols = st.columns(3)
        cols[0].metric("Water Cut", f"{wg.latest_water_cut_pct:.0f}%",
                       delta=f"{wg.water_cut_slope_pct_per_yr:+.1f}%/yr",
                       delta_color="inverse")
        cols[1].metric("GOR", f"{wg.latest_gor_scf_per_bbl:,.0f} scf/bbl",
                       delta=f"{wg.gor_slope_scf_per_bbl_per_yr:+,.0f}/yr",
                       delta_color="inverse")
        cols[2].metric("Trend Flags", f"{len(flags)}")
        for f in flags:
            theme.flag(f, "warn")
    except Exception:  # noqa: BLE001
        pass

    if well.artificial_lift.get("type") == "ESP" and well.esp_readings:
        try:
            d = core.pec_esp_diag.evaluate_esp(well.esp_readings,
                                               well.artificial_lift["pump_spec"])
            pt.section("ESP Health (Deterministic POR Check)")
            pt.kpi_row([
                {"label": "Current BFPD", "value": f"{d.current_bfpd:,.0f}"},
                {"label": "POR Window",
                 "value": f"{d.por_min_bfpd:,.0f}–{d.por_max_bfpd:,.0f}"},
                {"label": "Intake Pressure", "value": f"{d.intake_pressure_psi:,.0f} psi"},
                {"label": "In POR", "value": "yes" if d.in_por else "NO"},
            ])
            for f in d.flags:
                theme.flag(f, "high")
        except Exception:  # noqa: BLE001
            pass
    elif not core.is_real_well(wid):
        st.caption("No ESP telemetry in this well's file — the POR check is skipped.")
    else:
        st.caption("Real monthly filings carry no ESP telemetry — the POR check is "
                   "skipped for Colorado wells.")

    # ---- honest-eval note -------------------------------------------------------
    pt.section("How Good Is The Agent? (Honest Eval)")
    st.markdown(
        f"{pt.pill('blind holdout 0.722', 'warn')} {core.blind_holdout_note()} "
        "Earlier soft grading scored the same outputs 1.00 — the strict number is "
        "the one that survives scrutiny, and the committed eval artifact is the "
        "source of truth.", unsafe_allow_html=True)

    # ---- BYOK review --------------------------------------------------------------
    pt.section("Run The AI Review (BYOK)",
               "Claude writes the one-page review; the deterministic tools above do "
               "all the math. The key lives in this session only.")
    api_key = str(st.session_state.get("anthropic_key", "") or "")
    model = st.selectbox("Model", ("claude-sonnet-4-6", "claude-haiku-4-5"), index=0,
                         help="Haiku is ~4x cheaper and near-Sonnet on the eval; "
                              "Sonnet is the verified default.")
    run = st.button("Run AI Well Review", type="primary",
                    disabled=not api_key,
                    help=None if api_key else
                    "Enter your Anthropic API key in the sidebar to enable.")
    if not api_key:
        st.info("No API key set — add one in the sidebar (session-only, never "
                "stored) to generate the narrative review. Every panel above is "
                "deterministic and already rendered without it.")
    if run and api_key:
        target = well if core.is_real_well(wid) else str(core.PEC_SYNTH_DIR / f"{wid}.json")
        try:
            with st.spinner("Agent reasoning + tool calls (~30 s)…"):
                report = core.pec_agent.run_review(target, model=model,
                                                   verbose=False, api_key=api_key)
            st.markdown(report)
            st.download_button("Download Review (Markdown)", report,
                               file_name=f"{wid}-review.md")
        except Exception as exc:  # noqa: BLE001 — network/credential dependent
            st.error(f"Review failed: {exc}")

    theme.references(["arps", "npv", "prms"])
