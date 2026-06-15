"""Fleet → Well Browser — the registry-enriched merged well table plus a per-well
drill-down card.

One row per well across all three data domains (production / SCADA / injection),
joined by well_id with per-domain availability flags. The active data source (sidebar)
scopes the universe: the synthetic well_0NN demo fleet (default) or the real Colorado
ECMC ids. Pick any well from the in-page selector to drive every other page.

DATA IDENTITY: real Colorado ECMC wells (state API ids) carry production only — they
are never shown with SCADA or injection data. The synthetic well_0NN fleets
(pec · esp · gla) share the registry identity, so their flags merge by id.
"""
from __future__ import annotations

import math

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import core
import fleet_registry
import product_theme as pt
import theme

from views import _common


def _sync_pick() -> None:
    """Drive the GLOBAL well selection from the in-page selector.

    Runs as an on_change callback (before any widget instantiates on the next run),
    so writing the widget-backed ``well_id`` here is legal."""
    pick = st.session_state.get("wb_pick")
    if pick:
        st.session_state["well_id"] = pick


def _num(v) -> bool:
    try:
        return v is not None and math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def _identity_rows(well_id: str) -> list[tuple[str, str]]:
    """Compact identity/completion table for the drill-down card."""
    if core.is_real_well(well_id):
        w = core.colorado_wells()[well_id]
        comp = getattr(w, "completion", {}) or {}
        al = getattr(w, "artificial_lift", {}) or {}
        return [
            ("Well", w.well_id),
            ("State API id", well_id),
            ("Operator", comp.get("operator", "—")),
            ("Field", comp.get("field", "—")),
            ("Basin · Formation", f"DJ Basin (CO) · {comp.get('formation', '—')}"),
            ("Lift", al.get("type", "") or "—"),
            ("Provenance", "REAL — Colorado ECMC monthly filings"),
        ]
    m = fleet_registry.get(well_id)
    rows = [
        ("Well", m.name),
        ("Id", well_id),
        ("Basin · Area", f"{m.basin} · {m.area}"),
        ("Formation", m.formation),
        ("Lift", m.lift),
        ("Lateral length", f"{m.lateral_length_ft:,} ft"),
        ("First production", m.first_prod),
        ("Peer group", m.peer_group),
        ("Provenance", "Synthetic — shared well_0NN registry identity"),
    ]
    return rows


def _drilldown_card(sel: str, idx_all: pd.DataFrame) -> None:
    av = core.availability(sel)
    st.markdown(f"### {core.well_label(sel)}")
    st.markdown(" ".join([
        pt.pill("production", "ok") if av["production"] else pt.pill("no production", "muted"),
        pt.pill("SCADA", "ok") if av["scada"] else pt.pill("no SCADA", "muted"),
        pt.pill("injection survey", "ok") if av["injection"] else pt.pill("no injection", "muted"),
        pt.pill("REAL data", "info") if core.is_real_well(sel) else pt.pill("synthetic", "warn"),
    ]), unsafe_allow_html=True)

    row = idx_all[idx_all["well_id"] == sel]
    row = row.iloc[0] if len(row) else None
    if row is not None:
        pt.kpi_row([
            {"label": "Latest Oil",
             "value": f"{row['latest_oil_bopd']:,.0f} BOPD" if _num(row["latest_oil_bopd"]) else "—",
             "help": "Latest monthly oil rate (production data)"},
            {"label": "Latest BFPD",
             "value": f"{row['latest_bfpd']:,.0f}" if _num(row["latest_bfpd"]) else "—",
             "help": "Latest daily total fluid (SCADA)"},
            {"label": "ESP Risk 30d",
             "value": f"{row['esp_risk_30d']:.0%}" if _num(row["esp_risk_30d"]) else "—",
             "help": "Calibrated 30-day failure probability where SCADA exists"},
        ])

    left, right = st.columns([2, 3])
    with left:
        st.dataframe(pd.DataFrame(_identity_rows(sel), columns=["Field", "Value"]),
                     width="stretch", hide_index=True)
        if not core.is_real_well(sel):
            meta = fleet_registry.get(sel)
            if getattr(meta, "storyline", ""):
                st.caption(f"**Storyline:** {meta.storyline}")
    with right:
        well = core.production_well(sel)
        hist = well.production_history if well is not None else []
        if len(hist) >= 2:
            h = pd.DataFrame(hist)
            fig = go.Figure(go.Scatter(
                x=h["day"], y=h["oil_bopd"], mode="lines",
                line=dict(color=theme.BLUE, width=1.6), fill="tozeroy",
                fillcolor="rgba(79,129,189,0.10)"))
            fig.update_layout(title="Oil Rate History (BOPD vs. days on production)",
                              xaxis_title=None, yaxis_title="BOPD", showlegend=False)
            st.plotly_chart(theme.style_fig(fig, height=210), width="stretch")
        else:
            pt.empty_state("No production history for this well — open Decline & EUR "
                           "or the Case File once a production well is selected.")

    st.caption("This well drives every page. Jump to **Decline & EUR**, **Failure "
               "Risk**, **Gas-Lift Optimum**, or the **Well Case File** to see each "
               "lens — availability pills above say which lenses have data.")


def render() -> None:
    _common.ensure_state()
    pt.masthead("workbench", "Well Browser",
                "Every well in the active data source, merged by well_id with "
                "per-domain data availability — drill down to drive the workbench")
    _common.context()

    source = st.session_state.get("data_source", "synthetic")
    src_key = "real" if source == "real" else "synthetic"
    idx_all = _common.well_index_cached()
    idx = idx_all[idx_all["source"] == src_key].reset_index(drop=True)
    if idx.empty:  # defensive: never show a blank page
        idx = idx_all.reset_index(drop=True)

    pt.kpi_row([
        {"label": "Wells (this source)", "value": f"{len(idx)}"},
        {"label": "With Production", "value": f"{int(idx['has_production'].sum())}"},
        {"label": "With SCADA", "value": f"{int(idx['has_scada'].sum())}",
         "help": "Synthetic ESP fleet — daily pump telemetry"},
        {"label": "With Injection Survey", "value": f"{int(idx['has_injection'].sum())}",
         "help": "Synthetic gas-lift fleet — 120-day injection surveys"},
        {"label": "Source",
         "value": ("Synthetic demo fleet" if src_key == "synthetic"
                   else "Real — Colorado ECMC")},
    ])

    # ---- in-page selector + drill-down card -------------------------------------
    choices = _common.well_choices_for(source)
    pt.section("Selected Well",
               "Pick any well in this source to retarget every page; switch the data "
               "source in the sidebar to browse the other universe.")
    sel = _common.current_well()
    if sel not in choices:
        sel = choices[0] if choices else sel
    # keep the in-page picker synced to the global selection each run
    if choices:
        st.session_state["wb_pick"] = sel
        st.selectbox("Drill down to a well", choices, key="wb_pick",
                     format_func=core.well_label, on_change=_sync_pick)
        sel = _common.current_well()
        _drilldown_card(sel, idx_all)

    # ---- merged fleet table (scan / filter / sort / export) ---------------------
    pt.section("Merged Fleet Table",
               "Filter and scan any column, then pick the well above to drive the app. "
               "Availability flags say which lenses the Case File can render; ESP "
               "risk appears only where the well is scorable (synthetic SCADA).")

    # In-page filters (audit: the ~128-row table had no filter/search). These scope the
    # TABLE scan only — the drill-down picker above always sees the full source so you
    # can still target any well.
    f1, f2, f3 = st.columns([2, 1.4, 1.4])
    query = f1.text_input("Search well / name / formation", key="wb_query",
                          placeholder="e.g. well_017, Wolfcamp, 05-123…").strip().lower()
    basins = sorted(idx["basin"].dropna().unique().tolist())
    lifts = sorted(idx["lift"].dropna().unique().tolist())
    sel_basins = f2.multiselect("Basin", basins, key="wb_basins")
    sel_lifts = f3.multiselect("Lift", lifts, key="wb_lifts")
    avail = st.multiselect(
        "Data availability (require all selected)", ["Production", "SCADA", "Injection"],
        key="wb_avail",
        help="A well with SCADA but NO production dead-ends on Decline/EUR, AI Review "
             "and the Case File's production lenses — filter to 'Production' to avoid that.")

    filt = idx
    if query:
        hay = (filt["well_id"].astype(str) + " " + filt["well"].astype(str) + " "
               + filt["formation"].astype(str)).str.lower()
        filt = filt[hay.str.contains(query, regex=False)]
    if sel_basins:
        filt = filt[filt["basin"].isin(sel_basins)]
    if sel_lifts:
        filt = filt[filt["lift"].isin(sel_lifts)]
    if "Production" in avail:
        filt = filt[filt["has_production"]]
    if "SCADA" in avail:
        filt = filt[filt["has_scada"]]
    if "Injection" in avail:
        filt = filt[filt["has_injection"]]

    # Consolidated identity (audit: redundant Well Id / Well). One stable key column
    # ("Well" = the selection key everything uses) + a separate human Name, built the
    # same way for real vs synthetic so the two columns are never duplicative.
    disp = filt.copy()
    disp["name"] = [w.split(" · ", 1)[1] if " · " in str(w) else str(w)
                    for w in disp["well"]]
    show = disp[[
        "well_id", "name", "source", "basin", "formation", "lift",
        "has_production", "has_scada", "has_injection",
        "latest_oil_bopd", "latest_bfpd", "esp_risk_30d",
    ]].rename(columns={
        "well_id": "Well", "name": "Name", "source": "Source", "basin": "Basin",
        "formation": "Formation", "lift": "Lift", "has_production": "Production",
        "has_scada": "SCADA", "has_injection": "Injection",
        "latest_oil_bopd": "Latest Oil (BOPD)", "latest_bfpd": "Latest BFPD",
        "esp_risk_30d": "ESP Risk 30d",
    })
    n_scada_only = int(((~filt["has_production"]) & filt["has_scada"]).sum())
    st.caption(f"Showing **{len(show)}** of {len(idx)} wells in this source"
               + (f" · {n_scada_only} are SCADA-only (no production — they drive only "
                  "the Failure-Risk / Run-Life lenses)" if n_scada_only else ""))
    st.dataframe(
        show, width="stretch", hide_index=True, height=420,
        column_config={
            "Production": st.column_config.CheckboxColumn("Production", disabled=True),
            "SCADA": st.column_config.CheckboxColumn("SCADA", disabled=True),
            "Injection": st.column_config.CheckboxColumn("Injection", disabled=True),
            "Latest Oil (BOPD)": st.column_config.NumberColumn(format="%.0f"),
            "Latest BFPD": st.column_config.NumberColumn(format="%.0f"),
            "ESP Risk 30d": st.column_config.ProgressColumn(
                "ESP Risk 30d", min_value=0.0, max_value=1.0, format="%.2f"),
        })
    st.download_button("Download Fleet Table (CSV)", data=show.to_csv(index=False),
                       file_name=f"workbench_fleet_{src_key}.csv", mime="text/csv")
    if src_key == "synthetic":
        theme.source_note(
            "Synthetic well_0NN demo fleet (shared registry identity). Latest oil rate "
            "from monthly production; latest BFPD from daily SCADA; ESP risk = "
            "calibrated 30-day failure probability where SCADA exists. Known ground "
            "truth backs the design/diagnose/predict/optimize lenses.")
    else:
        theme.source_note(
            "Real Colorado ECMC monthly filings (state API ids), production only. "
            "Public monthly data has no ESP telemetry or injection surveys, so the "
            "Failure-Risk and Gas-Lift lenses stay honestly unavailable for real "
            "wells — switch to the synthetic source for full coverage.")
