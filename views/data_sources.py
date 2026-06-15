"""Data → Sources & BYOD — provenance of every built-in dataset plus ONE
consolidated bring-your-own-data page.

Three strict, schema-validated uploaders, each reusing the owning component's
loader unchanged: monthly production CSV (pec's tidy-monthly loader), fleet SCADA
CSV (esp's validate_scada_schema + loader + trained model), and injection-survey
CSV (gla's REQUIRED_COLS + GLPC fit). Bad columns produce a precise st.error and
st.stop() — never a crash. Nothing is stored server-side; files are parsed
in-memory for this browser session only.
"""
from __future__ import annotations

import io
import os
import tempfile

import pandas as pd
import streamlit as st

import core
import product_theme as pt
import theme

from views import _common

# pec's tidy monthly schema (the subset its loader requires).
_PROD_REQUIRED = ("well_id", "date", "oil_bbl", "gas_mcf", "water_bbl", "days")
_PROD_TEMPLATE = (
    "well_id,date,oil_bbl,gas_mcf,water_bbl,days\n"
    "well_A,2025-01,4200,9100,6300,31\n"
    "well_A,2025-02,3900,8800,6700,28\n")

# gla's strict injection-survey schema.
_INJ_REQUIRED = {"well_id", "date", "injection_gas_mcfd", "bopd", "bwpd"}
_INJ_TEMPLATE = ("well_id,date,injection_gas_mcfd,bopd,bwpd\n"
                 "well_001,2024-01-01,1.20,320.5,185.2\n"
                 "well_001,2024-01-02,0.80,275.3,159.4\n")


def _sources_panel() -> None:
    pt.section("Built-In Sources & Provenance",
               "What the workbench ships with, and exactly what each dataset is.")
    rows = [
        ("Monthly production — synthetic (default)", "pec modeled fleet (well_001–041)",
         "Known-ground-truth well files incl. ESP readings and dyno cards for the "
         "diagnostics; committed. The product's default universe — every lens works."),
        ("Fleet SCADA — synthetic", "esp generator (well_001–100, seed 7)",
         "Daily pump telemetry (BFPD, intake, motor temp/amps, runtime, VSD Hz, "
         "current imbalance) + labeled failures + run-life ground truth. Committed "
         "(deterministic seed 7) so the app loads with no first-run training."),
        ("Injection surveys — synthetic", "gla generator (well_001–020, seed 42)",
         "120-day histories with embedded 19-level injection surveys + true GLPC "
         "parameters. Committed (deterministic seed 42)."),
        ("Monthly production — REAL (optional)", "Colorado ECMC (COGCC) public records",
         "28 DJ Basin Niobrara/Codell horizontals (Weld Co.) under real state API ids "
         "— switch to the Real source in the sidebar. Free public data, committed. "
         "Monthly cadence — no ESP telemetry, injection surveys, or failure labels."),
    ]
    st.dataframe(pd.DataFrame(rows, columns=["Dataset", "Source", "Notes"]),
                 width="stretch", hide_index=True)
    st.caption(
        "Identity rule: the three synthetic fleets share the registry's well_0NN "
        "namespace and merge by id; REAL Colorado wells keep their state API ids "
        "and are never shown with SCADA or injection data they do not have.")


def _production_upload() -> None:
    pt.section("Monthly Production CSV (pec Loader)",
               "Tidy monthly schema; parsed by the same adapter that reads the "
               "NDIC/Colorado public filings.")
    st.caption("Required columns: `" + "`, `".join(_PROD_REQUIRED) +
               "`. Optional: `well_name`, `operator`, `field`, `formation`. "
               "`date` is YYYY-MM.")
    st.download_button("Download Production Template (CSV)", _PROD_TEMPLATE,
                       file_name="workbench_production_template.csv",
                       mime="text/csv", key="tpl_prod")
    up = st.file_uploader("Monthly production CSV", type=["csv"], key="up_prod")
    if up is None:
        return
    content = up.getvalue()
    header = content.decode("utf-8", errors="replace").split("\n")[0]
    cols = {c.strip().lstrip("﻿").lower() for c in header.split(",")}
    missing = [c for c in _PROD_REQUIRED if c not in cols]
    if missing:
        st.error(f"Production CSV is missing required column(s): "
                 f"**{', '.join(missing)}**. Required: {', '.join(_PROD_REQUIRED)}. "
                 "Download the template above for a known-good example.")
        st.stop()
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        wells = core.pec_ndic.load_ndic_fleet(
            tmp_path, source_note="User-uploaded monthly production CSV.",
            field_default="User upload", operator_default="User upload",
            formation_default="Unknown")
    except ValueError as exc:
        st.error(f"Could not parse the production CSV: {exc}")
        st.stop()
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    st.success(f"Parsed {len(wells)} well(s) — in-memory only, nothing stored.")
    rows = []
    for w in wells:
        hist = w.production_history
        fit_note = "fit-ready" if len(hist) >= 5 else f"only {len(hist)} point(s)"
        # oil_bopd here is the latest MONTH's average daily rate (oil_bbl / days), not a
        # spot daily reading — label the cadence honestly (audit finding).
        rows.append({"Well": w.well_id, "Months": len(hist),
                     "Latest Month Avg (BOPD)": hist[-1]["oil_bopd"] if hist else None,
                     "Decline Fit": fit_note})
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True,
                 column_config={"Latest Month Avg (BOPD)":
                                st.column_config.NumberColumn(format="%.0f")})
    st.info("📤 **Your upload** — parsed by pec's monthly adapter for this browser "
            "session only. This is your own data of unverified provenance, not the "
            "certified Colorado set; nothing is stored server-side.")


def _scada_upload() -> None:
    pt.section("Fleet SCADA CSV (esp Loader + Trained Model)",
               "One long/tidy CSV for the whole fleet (one row per well-day); "
               "scored with the exact trained model + feature pipeline.")
    req = ", ".join(f"`{c}`" for c in core.esp_loader.UPLOAD_REQUIRED_COLUMNS)
    opt = ", ".join(f"`{c}`" for c in core.esp_loader.UPLOAD_OPTIONAL_COLUMNS)
    st.caption(f"Required columns: {req}. Optional (backfilled with healthy "
               f"defaults): {opt}. Each well needs ~30–60 days of history.")
    st.download_button(
        "Download SCADA Template (CSV)",
        core.esp_loader.scada_template_frame().to_csv(index=False),
        file_name="workbench_scada_template.csv", mime="text/csv", key="tpl_scada")
    up = st.file_uploader("Fleet SCADA CSV", type=["csv"], key="up_scada")
    if up is None:
        return
    try:
        head = pd.read_csv(io.BytesIO(up.getvalue()), nrows=0)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not read the uploaded CSV: {exc}")
        st.stop()
    missing = core.esp_loader.validate_scada_schema(head)
    if missing:
        st.error("SCADA CSV is missing required column(s): "
                 f"**{', '.join(missing)}**. Required: "
                 f"{', '.join(core.esp_loader.UPLOAD_REQUIRED_COLUMNS)}. Download "
                 "the template above for the exact format.")
        st.stop()
    try:
        df = pd.read_csv(io.BytesIO(up.getvalue()), parse_dates=["date"])
        fleet = core.esp_loader.load_fleet_from_frame(df)
        features = core.esp_features.featurize_fleet(fleet)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not process the SCADA CSV: {exc}. Check that `date` parses "
                 "and the channel columns are numeric.")
        st.stop()
    if not len(features):
        st.error("No wells found after parsing — ensure at least one `well_id` "
                 "with SCADA rows.")
        st.stop()
    model = _common.esp_model_cached()
    probs = pd.Series(model.predict_proba(features), index=features.index,
                      name="risk").sort_values(ascending=False)
    st.success(f"Scored {len(probs)} uploaded well(s) with the trained model — "
               "in-memory only, nothing stored.")
    out = pd.DataFrame({"Well": probs.index, "30-Day Risk": probs.values.round(4)})
    st.dataframe(out, width="stretch", hide_index=True,
                 column_config={"30-Day Risk": st.column_config.ProgressColumn(
                     "30-Day Risk", min_value=0.0, max_value=1.0, format="%.2f")})
    st.info("📤 **Your upload** — scored in-session with the trained model; the "
            "registry's synthetic identity is NOT joined onto your wells, and nothing "
            "is stored server-side.")


def _injection_upload() -> None:
    pt.section("Injection Survey CSV (gla Loader)",
               "Daily injection + rates per well; needs injection-rate variation "
               "(a survey) for the GLPC fit to identify the curve.")
    st.caption("Required columns: `" + "`, `".join(sorted(_INJ_REQUIRED)) + "`.")
    st.download_button("Download Injection Template (CSV)", _INJ_TEMPLATE,
                       file_name="workbench_injection_template.csv",
                       mime="text/csv", key="tpl_inj")
    up = st.file_uploader("Injection survey CSV", type=["csv"], key="up_inj")
    if up is None:
        return
    try:
        df = pd.read_csv(io.BytesIO(up.getvalue()), parse_dates=["date"])
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not read the uploaded CSV: {exc}")
        st.stop()
    missing = _INJ_REQUIRED - set(df.columns)
    if missing:
        st.error(f"Injection CSV is missing required column(s): "
                 f"**{', '.join(sorted(missing))}**. Required: "
                 f"{', '.join(sorted(_INJ_REQUIRED))}. Download the template above "
                 "for the exact format.")
        st.stop()
    oil_price, nri, _disc = _common.deck()
    gas_cost = float(st.session_state.get("gas_cost", 1.50))
    rows = []
    for wid, grp in df.groupby("well_id"):
        try:
            params, wc, cur_inj, opt = core.analyze_gla_well(
                grp.reset_index(drop=True), oil_price, gas_cost, nri)
        except Exception:  # noqa: BLE001 — degenerate group
            continue
        rows.append({"Well": str(wid), "GLPC R²": round(params.r2, 3),
                     "Water Cut": round(wc, 3),
                     "Current Inj (Mscfd)": round(cur_inj, 2),
                     "Optimal Inj (Mscfd)": opt.q_inj_opt,
                     "Oil At Optimum (BOPD)": opt.q_oil_opt})
    if not rows:
        st.error("No analyzable wells in the uploaded CSV (each well needs ≥ 4 "
                 "rows with injection > 0.05 Mscfd, or a recognizable baseline).")
        st.stop()
    st.success(f"Fit {len(rows)} well(s) — in-memory only, nothing stored.")
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    st.info("📤 **Your upload** — GLPC fit + optimum at "
            f"${oil_price:,.0f}/bbl, ${gas_cost:.2f}/Mscf, {nri:.0%} NRI, for this "
            "session only. Your own data, not the certified set; nothing is stored.")


def render() -> None:
    _common.ensure_state()
    pt.masthead("workbench", "Sources & BYOD",
                "Where every built-in number comes from, plus strict-schema "
                "uploads for your own production, SCADA, and injection data")
    _common.context()

    _sources_panel()

    st.caption("All three uploaders parse in-memory for this browser session only — "
               "**nothing is uploaded or stored server-side.**")
    tab_prod, tab_scada, tab_inj = st.tabs(
        ["Production CSV", "Fleet SCADA CSV", "Injection Survey CSV"])
    with tab_prod:
        _production_upload()
    with tab_scada:
        _scada_upload()
    with tab_inj:
        _injection_upload()

    theme.references(["arps", "shap", "gas_lift"])
