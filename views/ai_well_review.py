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

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import core
import product_theme as pt
import theme

from views import _common


def _usd(x: float) -> str:
    """Compact USD: $X.XXMM above a million, else $Xk."""
    return f"${x/1e6:,.2f}MM" if abs(x) >= 1e6 else f"${x/1e3:,.0f}k"


def _probabilistic_econ_panel(row) -> None:
    """Keyless Monte-Carlo economics for the indicated intervention — P10/P50/P90 NPV, the
    payout/loss probabilities, the NPV distribution, and a tornado of the input swings. The
    MC is RISKED by chance-of-success (Bernoulli per trial → NPV = −cost on a miss), uses the
    realized (differential-adjusted) price the headline uses, and the deterministic risked
    NPV is overlaid so the base case visibly sits inside the bands. (core.pec_economics)."""
    defaults = core.pec_assumptions.intervention_defaults(row.intervention)
    if not defaults:
        return
    oil_price, nri, discount = _common.deck()
    # ONE realized price for both paths: the deck is WTI; apply the basis/quality
    # differential once so the MC and the deterministic headline cannot diverge (#19).
    realized = float(oil_price) + float(core.pec_assumptions.REALIZED_DIFFERENTIAL)
    opex = float(core.pec_assumptions.LOE_USD_PER_BBL)
    p_succ = float(defaults.get("p_success", 1.0))
    common = dict(
        name=row.intervention, treatment_cost_usd=defaults["cost_usd"],
        incremental_rate_bopd=defaults["uplift_bopd"],
        uplift_decline_per_yr=defaults["uplift_decline"],
        realized_price_per_bbl=realized, discount_rate=discount, opex_per_bbl=opex)
    try:
        sim = core.pec_economics.simulate_intervention(prob_success=p_succ, seed=42, **common)
        det = core.pec_economics.evaluate_intervention(prob_success=p_succ, **common)
    except Exception:  # noqa: BLE001
        return
    det_npv = float(det.npv_10pct_usd)

    pt.section("Probabilistic Intervention Economics (Monte-Carlo)",
               "10,000 trials over uncertain incremental rate (±lognormal), uplift decline, "
               f"and realized price, RISKED by the {p_succ:.0%} chance-of-success — same "
               "calibrated cost/uplift/price the risked point estimate above uses.")
    pt.kpi_row([
        {"label": "NPV P90", "value": _usd(sim["npv_p90_usd"]),
         "help": "Conservative — 90% chance of exceeding"},
        {"label": "NPV P50", "value": _usd(sim["npv_p50_usd"])},
        {"label": "NPV P10", "value": _usd(sim["npv_p10_usd"]),
         "help": "Optimistic — 10% chance of exceeding"},
        {"label": "P(payout)", "value": f"{sim['probability_of_payout']:.0%}",
         "help": f"NPV>0 AND payout < {sim['payout_cutoff_months']:.0f} months"},
        {"label": "P(loss)", "value": f"{sim.get('probability_of_loss', 0.0):.0%}",
         "help": f"NPV<0, including the {1 - p_succ:.0%} chance the job simply misses "
                 "(geologic/mechanical) and the capital is sunk."},
    ])

    cL, cR = st.columns(2)
    with cL:
        samples = np.asarray(sim["npv_samples"], float) / 1e6
        hfig = go.Figure(go.Histogram(x=samples, nbinsx=40, marker_color=theme.BLUE,
                                      opacity=0.85))
        hfig.add_vline(x=0, line=dict(color=theme.RED, width=1, dash="dot"))
        hfig.add_vline(x=det_npv / 1e6,
                       line=dict(color=theme.GREEN, width=2, dash="dash"),
                       annotation_text="Risked NPV (det.)", annotation_position="top")
        hfig.update_layout(title="NPV Distribution (10k trials, COS-risked)",
                           xaxis_title="NPV ($MM)", yaxis_title="Trials", showlegend=False)
        st.plotly_chart(theme.style_fig(hfig, height=300, legend=False), width="stretch")
    with cR:
        tdata = sim.get("tornado", {})
        order = sorted(tdata.items(), key=lambda kv: kv[1]["swing"])  # asc for h-bars
        labels = {"incremental_rate_bopd": "Incremental rate",
                  "uplift_decline_per_yr": "Uplift decline", "realized_price_per_bbl": "Price"}
        tfig = go.Figure()
        for var, t in order:
            left = min(t["low_npv"], t["high_npv"]) / 1e6
            right = max(t["low_npv"], t["high_npv"]) / 1e6
            tfig.add_trace(go.Bar(
                y=[labels.get(var, var)], x=[right - left], base=[left], orientation="h",
                marker_color=theme.AMBER, showlegend=False,
                hovertemplate=f"{labels.get(var, var)}: {left:.2f}–{right:.2f} $MM<extra></extra>"))
        tfig.add_vline(x=det_npv / 1e6,
                       line=dict(color=theme.GREEN, width=2, dash="dash"))
        tfig.update_layout(title="Tornado — NPV Swing By Input (success case)",
                           xaxis_title="NPV ($MM)", yaxis_title=None, bargap=0.35)
        st.plotly_chart(theme.style_fig(tfig, height=300, legend=False), width="stretch")

    st.caption(
        f"Cost ${defaults['cost_usd']/1e3:,.0f}k · uplift {defaults['uplift_bopd']:.0f} BOPD "
        f"@ {defaults['uplift_decline']:.0%}/yr decline · ${realized:,.0f}/bbl realized "
        f"(${oil_price:,.0f} WTI {core.pec_assumptions.REALIZED_DIFFERENTIAL:+.0f} basis) · "
        f"{discount:.0%} discount · ${opex:,.0f}/bbl LOE · {p_succ:.0%} chance-of-success. "
        f"Each trial draws Bernoulli({p_succ:.2f}); a miss zeros the uplift and books −cost, "
        "so P(payout)/P(loss) are honest and the distribution is consistent with the risked "
        "point NPV (green line = deterministic risked NPV; the green spike at −cost is the "
        "miss mass). Tornado spans the success-case input swings. Seed 42; no LLM, no key.")


def _holdout_agreement() -> float:
    """Strict blind-holdout recommendation agreement, computed from the committed
    artifact — the SAME source core.blind_holdout_note() reads, so the headline chip
    and the eval note can never silently diverge (audit: chip hardcoded 0.72)."""
    import json
    try:
        rows = json.loads(core.PEC_HOLDOUT_JSON.read_text())
        scored = [r for r in rows if "recommendation_match" in r]
        return sum(1 for r in scored if r.get("recommendation_match")) / len(scored)
    except Exception:  # noqa: BLE001
        return 0.722


def _jump_to_production_well() -> None:
    """Retarget the app to a production-bearing well chosen from the dead-end picker."""
    pick = st.session_state.get("aiwr_jump")
    if pick:
        st.session_state["data_source"] = "real" if core.is_real_well(pick) else "synthetic"
        st.session_state["well_id"] = pick


def render() -> None:
    _common.ensure_state()
    pt.masthead("workbench", "AI Well Review",
                "One-page well review: Claude reasons over deterministic "
                "petroleum-engineering tool outputs",
                chips=[(f"v{pt.PRODUCT_VERSION}", "ver"),
                       (f"{_holdout_agreement():.2f} blind holdout (strict)", "eval")])
    _common.context()

    wid = _common.current_well()
    well = core.production_well(wid)
    if well is None:
        pt.empty_state(
            f"{wid} has no production history — the well review needs monthly "
            "production. The synthetic SCADA-only wells (well_042–well_100) carry pump "
            "telemetry but no production stream, so this lens cannot run on them.",
            "Jump to a production-bearing well below, or pick one in the Well Browser.")
        prod_wells = [w for w in _common.synthetic_well_ids()
                      if core.production_well(w) is not None]
        if prod_wells:
            default = "well_013" if "well_013" in prod_wells else prod_wells[0]
            st.session_state["aiwr_jump"] = default
            st.selectbox("Jump to a production-bearing well", prod_wells,
                         key="aiwr_jump", format_func=core.well_label,
                         on_change=_jump_to_production_well)
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

    # ---- probabilistic intervention economics (keyless Monte-Carlo) -------------
    if row is not None and row.intervention not in core.pec_portfolio._NON_ECONOMIC:
        _probabilistic_econ_panel(row)

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
        "source of truth. This strict number is measured on the default model "
        "(**claude-sonnet-4-6**).", unsafe_allow_html=True)

    # ---- BYOK review --------------------------------------------------------------
    pt.section("Run The AI Review (BYOK)",
               "Claude writes the one-page review; the deterministic tools above do "
               "all the math. The key lives in this session only.")
    api_key = str(st.session_state.get("anthropic_key", "") or "")
    model = st.selectbox(
        "Model", ("claude-sonnet-4-6", "claude-haiku-4-5"), index=0,
        help="Sonnet is the verified default — the 0.722 strict-holdout number above "
             "is measured on Sonnet. Haiku is ~4× cheaper and matched Sonnet on the "
             "smaller LENIENT dev frontier, but carries no strict-holdout number of "
             "its own.")
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
        # Honest latency estimate: the committed model frontier shows Sonnet averages
        # ~55-60 s for the full tool-use loop (Haiku is faster) — not "~30 s" (audit).
        est = "~60 s" if model == "claude-sonnet-4-6" else "~25 s"
        try:
            with st.spinner(f"Agent reasoning + tool calls ({est} on {model})…"):
                report, stats = core.pec_agent().run_review(
                    target, model=model, verbose=False, api_key=api_key,
                    return_stats=True)
            # Persist so the rendered review + download button survive the rerun the
            # download click triggers (a paid LLM call must not be thrown away).
            st.session_state["ai_review"] = {"well": wid, "model": model,
                                             "report": report, "stats": stats}
        except Exception as exc:  # noqa: BLE001 — network/credential dependent
            st.error(f"Review failed: {exc}")

    stored = st.session_state.get("ai_review")
    if stored and stored.get("well") == wid:
        st.caption(f"Generated review — {wid} · {stored['model']} (session only).")
        stats = stored.get("stats") or {}
        if stats:
            # rough cost: Sonnet $3/MTok in, $15/MTok out (claude-api skill pricing).
            rate = {"claude-sonnet-4-6": (3.0, 15.0),
                    "claude-haiku-4-5": (1.0, 5.0)}.get(stored["model"], (3.0, 15.0))
            cost = (stats.get("input_tokens", 0) * rate[0]
                    + stats.get("output_tokens", 0) * rate[1]) / 1e6
            pt.kpi_row([
                {"label": "Latency", "value": f"{stats.get('latency_s', 0):.0f} s"},
                {"label": "Tool Calls", "value": f"{stats.get('tool_calls', 0)}"},
                {"label": "Tokens (in / out)",
                 "value": f"{stats.get('input_tokens', 0):,} / "
                          f"{stats.get('output_tokens', 0):,}"},
                {"label": "Est. Cost", "value": f"${cost:,.3f}",
                 "help": "Anthropic list price for the selected model × tokens used"},
            ])
        st.markdown(stored["report"])
        st.download_button("Download Review (Markdown)", stored["report"],
                           file_name=f"{wid}-review.md", key="dl_ai_review")

    theme.references(["arps", "npv", "prms"])
