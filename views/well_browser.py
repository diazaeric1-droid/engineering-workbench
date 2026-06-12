"""Fleet → Well Browser — the registry-enriched merged well table.

One row per well across all three data domains (production / SCADA / injection),
joined by well_id with per-domain availability flags. Selecting a well here drives
every other page (session-state ``well_id``).

DATA IDENTITY: real Colorado ECMC wells (state API ids) carry production only —
they are never shown with SCADA or injection data. The synthetic well_0NN fleets
(pec · esp · gla) share the registry identity, so their flags merge by id.
"""
from __future__ import annotations

import streamlit as st

import core
import product_theme as pt
import theme

from views import _common


def _on_row_select() -> None:
    """Dataframe row-selection callback → set the GLOBAL well selection.

    Runs before any widget instantiates on the next run, so writing the
    widget-backed ``well_id`` key here is legal (an inline write after the
    sidebar selectbox exists would raise StreamlitAPIException).
    """
    ev = st.session_state.get("browser_table")
    try:
        rows = list(ev.selection.rows)
    except Exception:  # noqa: BLE001 — no selection event
        rows = []
    order = st.session_state.get("_browser_order") or []
    if rows and 0 <= rows[0] < len(order):
        st.session_state["well_id"] = order[rows[0]]


def render() -> None:
    _common.ensure_state()
    pt.masthead("workbench", "Well Browser",
                "Every well the workbench knows, merged by well_id with per-domain "
                "data availability")
    _common.context()

    idx = _common.well_index_cached()

    n_real = int((idx["source"] == "real").sum())
    pt.kpi_row([
        {"label": "Wells", "value": f"{len(idx)}"},
        {"label": "Real (CO ECMC)", "value": f"{n_real}",
         "help": "Colorado ECMC public monthly production — DJ Basin horizontals"},
        {"label": "With Production", "value": f"{int(idx['has_production'].sum())}"},
        {"label": "With SCADA", "value": f"{int(idx['has_scada'].sum())}",
         "help": "Synthetic ESP fleet — daily pump telemetry"},
        {"label": "With Injection Survey", "value": f"{int(idx['has_injection'].sum())}",
         "help": "Synthetic gas-lift fleet — 120-day injection surveys"},
    ])

    pt.section("Selected Well",
               "Click a table row below (or use the sidebar selectbox) to retarget "
               "every page — Decline & EUR, Failure Risk, Gas-Lift Optimum, and the "
               "Case File all follow the selection.")
    sel = _common.current_well()
    av = core.availability(sel)
    st.markdown(f"**{core.well_label(sel)}**")
    pills = [
        pt.pill("production", "ok") if av["production"] else pt.pill("no production", "muted"),
        pt.pill("SCADA", "ok") if av["scada"] else pt.pill("no SCADA", "muted"),
        pt.pill("injection survey", "ok") if av["injection"] else pt.pill("no injection", "muted"),
        pt.pill("REAL data", "info") if core.is_real_well(sel) else pt.pill("synthetic", "warn"),
    ]
    st.markdown(" ".join(pills), unsafe_allow_html=True)

    pt.section("Merged Fleet Table",
               "Sort any column; click a row to select that well. Availability "
               "flags say which lenses the Case File can render; ESP risk appears "
               "only where the well is scorable (synthetic SCADA).")
    show = idx.rename(columns={
        "well_id": "Well Id", "well": "Well", "source": "Source", "basin": "Basin",
        "formation": "Formation", "lift": "Lift", "has_production": "Production",
        "has_scada": "SCADA", "has_injection": "Injection",
        "latest_oil_bopd": "Latest Oil (BOPD)", "latest_bfpd": "Latest BFPD",
        "esp_risk_30d": "ESP Risk 30d",
    })
    st.session_state["_browser_order"] = show["Well Id"].tolist()
    st.dataframe(
        show, width="stretch", hide_index=True, height=460,
        key="browser_table", on_select=_on_row_select, selection_mode="single-row",
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
                       file_name="workbench_fleet.csv", mime="text/csv")
    theme.source_note(
        "Identity: real wells from Colorado ECMC monthly filings (state API ids); "
        "synthetic well_0NN identity from the shared fleet registry. Latest oil rate "
        "from monthly production; latest BFPD from daily SCADA; ESP risk = calibrated "
        "30-day failure probability where SCADA exists.")
    st.caption(
        "Real Colorado wells carry **production only** — public monthly filings have no "
        "ESP telemetry or injection surveys, so those lenses stay honestly unavailable "
        "for real ids.")
