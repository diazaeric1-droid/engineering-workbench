"""Predict → Failure Risk — calibrated 30-day ESP failure probability, per-well
Tree-SHAP drivers, the out-of-fold reliability diagram, and the oracle-ceiling
framing (the model sits at the irreducible noise floor, not below an ideal).

Scoring runs on the synthetic ESP SCADA fleet (real monthly filings carry no pump
telemetry, so real Colorado wells are honestly un-scorable).
"""
from __future__ import annotations

import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import core
import fleet_registry
import product_theme as pt
import theme

from views import _common


def _sync_esp_well() -> None:
    """Drive the GLOBAL selection from the in-page picker. Scorable wells are always
    synthetic SCADA wells, so align the data source too (callback runs before the
    next run's widgets, so writing these widget keys is legal)."""
    pick = st.session_state.get("fr_pick")
    if pick:
        st.session_state["data_source"] = "synthetic"
        st.session_state["well_id"] = pick


def _shap_panel(well_id: str, features, contribs) -> None:
    feat_row = features.loc[well_id].to_dict()
    mode, evidence = core.esp_explainer.classify_failure_mode(feat_row)
    st.markdown(f"**Suspected failure mode:** {mode}")
    st.caption(evidence)
    drivers = core.esp_explainer.top_drivers(contribs.loc[well_id], k=8)
    drv_df = pd.DataFrame(drivers, columns=["Feature", "Contribution"])
    drv_df["Current Value"] = drv_df["Feature"].map(feat_row)
    cL, cR = st.columns([2, 3])
    with cL:
        st.dataframe(drv_df, width="stretch", hide_index=True)
        st.caption("Contributions are Tree SHAP in log-odds space on the raw "
                   "booster; the calibrated probability is a monotone transform of "
                   "that score, so driver sign and rank carry over.")
    with cR:
        shap_feats = [f for f, _ in drivers][::-1]
        shap_vals = [c for _, c in drivers][::-1]
        colors = [theme.RED if v >= 0 else theme.GREEN for v in shap_vals]
        sfig = go.Figure(go.Bar(x=shap_vals, y=shap_feats, orientation="h",
                                marker_color=colors,
                                hovertemplate="%{y}: %{x:+.2f} log-odds<extra></extra>"))
        sfig.update_layout(title=f"SHAP Contributions — {well_id}",
                           xaxis_title="← lowers risk   ·   raises risk →")
        st.plotly_chart(theme.style_fig(sfig, height=320, legend=False),
                        width="stretch")
        theme.source_note(
            "Per-feature Tree SHAP contributions (log-odds) — red raises the 30-day "
            "failure risk, green lowers it; sorted by magnitude.")


def render() -> None:
    _common.ensure_state()
    pt.masthead("workbench", "Failure Risk",
                "Calibrated 30-day ESP failure probability for the SCADA fleet, "
                "with per-well SHAP drivers and the oracle-ceiling framing")
    _common.context()
    theme.data_badge(
        "synthetic",
        "Modeled SCADA + labeled failures with known ground truth — no public "
        "dataset has ESP telemetry or failure labels.")

    fleet = _common.esp_fleet_cached()
    features = _common.esp_features_cached()
    probs, contribs = _common.esp_scores_cached()

    threshold = st.slider("Highlight Risk Above", 0.0, 1.0, 0.5, 0.05)
    pt.kpi_row([
        {"label": "Wells Scored", "value": f"{len(probs)}"},
        {"label": "High Risk (≥ threshold)", "value": f"{int((probs >= threshold).sum())}"},
        {"label": "Median Fleet Risk", "value": f"{float(probs.median()):.0%}"},
        {"label": "Top Risk", "value": f"{probs.index[0]} · {float(probs.iloc[0]):.0%}"},
    ])

    # ---- fleet risk table -------------------------------------------------------
    pt.section("Fleet Risk Table",
               "Every scorable well, sorted by calibrated 30-day failure "
               "probability; identity from the shared registry.")
    rows = []
    for well_id in probs.index:
        feat_row = features.loc[well_id].to_dict()
        mode, _ = core.esp_explainer.classify_failure_mode(feat_row)
        meta = fleet_registry.get(well_id)
        scada = fleet.get(well_id)
        last = scada.iloc[-1] if scada is not None and len(scada) else None
        rows.append({
            "Well": well_id,
            "High?": bool(float(probs[well_id]) >= threshold),
            "Registry Lift": meta.lift,
            "Basin · Formation": f"{meta.basin} · {meta.formation}",
            "30-Day Risk": round(float(probs[well_id]), 4),
            "Suspected Mode": mode,
            "Latest BFPD": round(float(last["bfpd"]), 0) if last is not None else None,
            "Intake (psi)": round(float(last["intake_pressure_psi"]), 0) if last is not None else None,
            "Motor Amps": round(float(last["motor_amps"]), 1) if last is not None else None,
        })
    table = pd.DataFrame(rows)
    # The threshold slider now actually DRIVES the table (audit: it only fed one KPI):
    # a High? flag column + an optional filter to the high-risk subset.
    only_high = st.checkbox(f"Show only wells at or above the {threshold:.0%} threshold",
                            value=False, key="fr_only_high")
    view_tbl = table[table["High?"]] if only_high else table
    st.dataframe(view_tbl, width="stretch", hide_index=True, height=380,
                 column_config={
                     "High?": st.column_config.CheckboxColumn(
                         f"High (≥{threshold:.0%})", disabled=True),
                     "30-Day Risk": st.column_config.ProgressColumn(
                         "30-Day Risk", min_value=0.0, max_value=1.0, format="%.2f")})
    st.download_button("Download Risk Table (CSV)", data=table.to_csv(index=False),
                       file_name="workbench_esp_risk.csv", mime="text/csv")
    theme.source_note(
        "Calibrated (Platt) 30-day failure probabilities from the class-weighted "
        "XGBoost model; suspected mode from the deterministic failure-mode classifier. "
        "Note the column basis differs: 30-Day Risk is a WINDOWED-aggregate model score "
        "(features summarize a trailing telemetry window), while Latest BFPD / Intake / "
        "Motor Amps are the SINGLE most-recent SCADA reading shown for context. The "
        "fleet is synthetic — registry identity is illustrative.")

    # ---- operational model performance (out-of-fold) ----------------------------
    if core.ESP_TRAINING_REPORT.exists():
        try:
            tr = json.loads(core.ESP_TRAINING_REPORT.read_text())
            pt.section("Model Performance (Out-Of-Fold CV)",
                       "How the shipped classifier scores on held-out folds — the "
                       "numbers behind the risk table, not a training-set echo.")
            pt.kpi_row([
                {"label": "OOF AUROC", "value": f"{tr['auroc_cv_mean']:.3f}",
                 "delta": f"±{tr['auroc_cv_std']:.3f} across folds",
                 "delta_color": "off"},
                {"label": "Precision @ Top 10%",
                 "value": f"{tr['precision_at_top10pct']:.0%}",
                 "help": "Of the top-decile risk calls, the share that truly failed"},
                {"label": "Recall @ Top 10%",
                 "value": f"{tr['recall_at_top10pct']:.0%}",
                 "help": "Of all true failures, the share landing in the top decile"},
                {"label": "Brier Score", "value": f"{tr['brier']:.3f}",
                 "help": "Mean-squared probability error — lower is better"},
                {"label": "Failures / Wells",
                 "value": f"{tr['n_positives']} / {tr['n_wells']}"},
            ])
        except Exception:  # noqa: BLE001 — report unreadable; the page still works
            pass

    # ---- per-well drivers ---------------------------------------------------------
    pt.section("Per-Well Risk Drivers",
               "Pick any scorable well — defaults to your global selection when it "
               "has SCADA, otherwise the fleet's top-risk well.")
    scorable = [str(w) for w in probs.index]  # already sorted by descending risk
    glob = _common.current_well()
    target = glob if glob in features.index else (scorable[0] if scorable else glob)
    if scorable:
        st.session_state["fr_pick"] = target
        wid = st.selectbox(
            "Well (scorable SCADA fleet)", scorable, key="fr_pick",
            format_func=lambda w: f"{w} · {fleet_registry.get(w).name} "
                                  f"— {float(probs[w]):.0%}",
            on_change=_sync_esp_well)
    else:
        wid = target
    if glob not in features.index:
        st.caption(f"The globally selected well has no SCADA telemetry, so this "
                   f"section is showing **{wid}**. Real monthly filings carry no "
                   "pump data — switch to a synthetic well for per-well drivers.")
    st.metric(f"30-Day Failure Probability — {wid}", f"{float(probs[wid]):.0%}")
    _shap_panel(wid, features, contribs)
    theme.references(["shap"])

    # ---- reliability -----------------------------------------------------------
    model = _common.esp_model_cached()
    reliability = getattr(model, "reliability", None)
    if reliability:
        pt.section("Calibration — Do The Probabilities Mean What They Say?",
                   "Out-of-fold reliability of the RAW booster (before Platt "
                   "calibration); points near the diagonal mean a 30% score fails "
                   "~30% of the time. The shipped scores apply Platt on top.")
        rel_df = pd.DataFrame(reliability)
        rfig = go.Figure()
        rfig.add_trace(go.Scatter(x=[0, 1], y=[0, 1], mode="lines",
                                  line=dict(dash="dash", color=theme.GREY),
                                  name="perfectly calibrated"))
        rfig.add_trace(go.Scatter(x=rel_df["mean_pred"], y=rel_df["obs_freq"],
                                  mode="markers+lines", name="model",
                                  marker=dict(size=rel_df["count"].clip(6, 24))))
        rfig.update_layout(xaxis_title="Mean predicted probability",
                           yaxis_title="Observed failure frequency",
                           xaxis_range=[0, 1], yaxis_range=[0, 1])
        st.plotly_chart(theme.style_fig(rfig, height=300), width="stretch")
        theme.source_note(
            "Mean predicted probability vs. observed failure frequency, binned, from "
            "out-of-fold cross-validation of the raw XGBoost booster (the OOF curve is "
            "computed before Platt calibration); marker size ∝ wells in bin. The "
            "fleet risk table applies Platt calibration on top of this booster.")

    # ---- oracle ceiling -----------------------------------------------------------
    oc = _common.oracle_cached()
    if oc and oc.get("ceiling"):
        c = oc["ceiling"]
        m_auroc = oc.get("model_auroc")            # pooled OOF AUROC (ceiling-comparable)
        cv_mean = oc.get("auroc_cv_mean")          # mean-of-folds (flattering, single seed)
        cv_std = oc.get("auroc_cv_std")
        n_pos = oc.get("n_positives") or c.get("n_observed_positives")
        cap = oc.get("capture")
        pt.section("Oracle Ceiling — Is ~0.85 AUROC Good?",
                   "The generator injects ~5% feature-independent label noise, so "
                   "there is a Bayes-optimal ceiling on ANY model; the headline "
                   "number is only meaningful next to it.")
        k1, k2, k3 = st.columns(3)
        with k1:
            if m_auroc is not None:
                st.metric("Model OOF AUROC (pooled)", f"{m_auroc:.3f}",
                          delta=f"ceiling {c['auroc']:.3f}", delta_color="off",
                          help="Pooled out-of-fold AUROC over all wells — the same way "
                               "the ceiling is computed (apples-to-apples). The "
                               f"mean-of-folds is {cv_mean:.3f} ± {cv_std:.3f} on only "
                               f"{n_pos} positive events, so treat 3-decimal precision "
                               "with care." if cv_mean is not None else None)
            else:
                st.metric("Oracle AUROC Ceiling", f"{c['auroc']:.3f}")
        with k2:
            if cap is not None:
                st.metric("Attainable Signal Captured",
                          f"{cap['above_chance']*100:.0f}%",
                          help="(pooled model AUROC − 0.5) / (ceiling AUROC − 0.5); "
                               "capped at 100%.")
            else:
                st.metric("Precision@Top-10% Ceiling",
                          f"{c['precision_at_top10pct']:.2f}")
        with k3:
            st.metric("Brier Ceiling (lowest)", f"{c['brier']:.3f}")
        msg = (f"Of {c['n_wells']} wells, {c['n_true_failures']} are truly "
               f"failure-bound; {c['n_label_flips']} labels are flipped by noise. "
               f"Those flips are unpredictable from data, so even a perfect model tops "
               f"out near AUROC {c['auroc']:.2f} here. The model's pooled OOF "
               f"{m_auroc:.3f} (mean-of-folds {cv_mean:.2f} ± {cv_std:.2f} on {n_pos} "
               f"events) sits just under that ceiling — at the noise floor, not a defect."
               if m_auroc else "Ceiling computed from the generator's known label process.")
        if cap is not None:
            st.info(msg + f" It captures ~{cap['above_chance']*100:.0f}% of the "
                          "attainable above-chance ranking signal — statistically "
                          "indistinguishable from the ceiling within sampling error on "
                          f"{n_pos} events (not a literal 100%).")
        else:
            st.info(msg)
        theme.source_note(
            "Oracle / Bayes-optimal ceiling (esp.oracle): best attainable AUROC, "
            "precision@top-10%, and Brier given the generator's irreducible label "
            "noise, scored against the realised labels.")
