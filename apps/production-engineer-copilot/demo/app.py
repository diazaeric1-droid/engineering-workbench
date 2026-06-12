"""Streamlit demo for Production Engineer Copilot.

Multipage (``st.navigation`` + ``st.Page``): a Fleet Overview page (fleet KPIs +
a sortable per-well table with deterministic economics from the portfolio screen)
plus one drill-down page per well — the original single-well dashboard (KPI cards,
decline plot vs. type curve, ESP diagnostic multi-panel, Monte-Carlo intervention
economics, AI Review, Evals, Raw, Generate-AFE preview, and the <5-point guard).

Detection / economics stay deterministic; the AI well review is BYOK-optional
(everything else renders with no API key). Heavy loads are cached on string args.
"""
from __future__ import annotations

import json
import sys
from functools import partial
from pathlib import Path

# Ensure repo root is on sys.path so `src.*` imports work on Streamlit Cloud, and
# the demo dir so the vendored `theme` / `fleet_registry` resolve regardless of cwd
# (Streamlit adds the entrypoint dir at runtime; AppTest / other contexts may not).
DEMO_DIR = Path(__file__).resolve().parent
REPO_ROOT = DEMO_DIR.parent
for _p in (str(REPO_ROOT), str(DEMO_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# --- Self-heal stale bytecode / module cache (Streamlit Cloud) --------------
# Streamlit reuses the container across redeploys. A cached .pyc or an already-
# imported OLD module object can lack symbols added in a newer commit, which shows
# up as an ImportError at startup for a name that genuinely exists in the source.
# Purge src/ bytecode and evict any cached src modules so every submodule reloads
# from the CURRENT source on this run. (No-op on a clean container.)
import shutil as _shutil
for _pycache in (REPO_ROOT / "src").rglob("__pycache__"):
    _shutil.rmtree(_pycache, ignore_errors=True)
for _name in [m for m in sys.modules if m == "src" or m.startswith("src.")]:
    del sys.modules[_name]

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import fleet_registry
# --- warm-container module self-heal (vendored top-level modules) -----------
# Streamlit Cloud reuses the container across redeploys; a cached OLD `theme` /
# `fleet_registry` in sys.modules (or a stale .pyc) lacks symbols added in a newer
# commit -> AttributeError (e.g. theme.how_to). Drop their bytecode + evict the cached
# modules so the imports below reload from the CURRENT commit's source.
import shutil as _sh_heal
_sh_heal.rmtree(Path(__file__).resolve().parent / "__pycache__", ignore_errors=True)
for _stale in ("theme", "fleet_registry"):
    sys.modules.pop(_stale, None)

import theme
from src import __version__ as APP_VERSION
from src.agent import run_review
from src.analyzers.decline_curve import fit_decline, analyze_type_curve
try:
    # Additive data-quality diagnostic (representative-vs-anomalous points for trending).
    # Guarded so a missing/broken module can never take down the Trends tab.
    from src.analyzers.representative import classify_representative
except Exception:  # pragma: no cover - defensive
    classify_representative = None
from src.analyzers.economics import evaluate_intervention, simulate_intervention
from src.analyzers.forecast_bands import decline_forecast_bands
from src.analyzers.economics_bands import economics_bands
from src.analyzers.esp_diagnostics import evaluate_esp
from src.afe_preview import build_afe_preview
from src.analyzers import assumptions as A
from src.data_loader import WellFile
from src.portfolio import screen_well, screen_wellfile, _NON_ECONOMIC
from src.adapters.ndic import load_ndic_fleet
from src.adapters.colorado import load_colorado_fleet
from src.tools import AFE_INTERVENTIONS, export_afe_diagnosis


DATA_DIR = REPO_ROOT / "data" / "synthetic"
COLORADO_CSV = REPO_ROOT / "data" / "real" / "colorado" / "production.csv"
NDIC_CSV = REPO_ROOT / "data" / "real" / "ndic" / "production.csv"

# Data-source provenance copy (kept in one place; used by the sidebar toggle, the
# badge under each header, and the fallback warning).
_CO_DETAIL = ("Colorado ECMC (COGCC) public monthly records — DJ Basin Niobrara/Codell "
              "horizontals, Weld County (free, no subscription). Monthly cadence; no ESP telemetry.")
_REAL_DETAIL = ("North Dakota (NDIC) public monthly filings — Bakken (Williston). "
                "Monthly cadence; no ESP telemetry.")
_SYNTHETIC_DETAIL = ("Modeled wells with known ground truth (clean signatures + ESP "
                     "readings for the diagnostics).")
_UPLOAD_DETAIL = ("User-uploaded monthly production CSV. "
                  "Monthly cadence; no ESP telemetry.")

# Required columns for the BYOD CSV upload (subset that load_ndic_fleet needs).
# Optional columns (well_name, operator, field, formation) default gracefully if absent.
_UPLOAD_REQUIRED_COLS = ("well_id", "date", "oil_bbl", "gas_mcf", "water_bbl", "days")
_UPLOAD_SCHEMA_CAPTION = (
    "Expected columns: `well_id`, `date` (YYYY-MM), `oil_bbl`, `gas_mcf`, "
    "`water_bbl`, `days` (days produced). Optional: `well_name`, `operator`, "
    "`field`, `formation`. Nothing is uploaded or stored server-side — the file "
    "is processed in-memory for this browser session only."
)


# ---------- cached heavy loads (string args so they hash/cache cleanly) ------

@st.cache_data(show_spinner=False)
def _well_files(data_dir: str) -> list[str]:
    """Sorted well JSON paths (as strings) under the data dir."""
    return [str(p) for p in sorted(Path(data_dir).glob("well_*.json"))]


@st.cache_resource(show_spinner=False)
def _load_well_cached(path: str) -> WellFile:
    """Cache a single parsed WellFile. Uses cache_resource (not cache_data) because
    WellFile is a custom class — Streamlit's cache_data serializer rejects custom
    classes on Python 3.14 / newer Streamlit. Read-only here, so sharing is safe."""
    return WellFile.from_json(path)


@st.cache_resource(show_spinner=False)
def _ndic_wells(csv_path: str) -> list[WellFile]:
    """Cache the real NDIC fleet parsed from a dropped monthly-production CSV.

    cache_resource (not cache_data) because WellFile is a custom class. Returns the
    list of WellFiles; raises on a missing/empty/malformed file (caller catches)."""
    return load_ndic_fleet(csv_path)


@st.cache_resource(show_spinner=False)
def _colorado_wells(csv_path: str) -> list[WellFile]:
    """Cache the real Colorado (ECMC) DJ Basin fleet — same custom-class caching note."""
    return load_colorado_fleet(csv_path)


def _load_upload(uploaded_file) -> list[WellFile]:
    """Parse an in-memory uploaded CSV into WellFiles via the shared NDIC loader.

    Writes to a NamedTemporaryFile (required by load_ndic_fleet which needs a path),
    then deletes it. Raises ValueError with a descriptive message on bad input so
    the caller can show st.error without crashing.
    """
    import os
    import tempfile

    content = uploaded_file.getvalue()
    # Validate required columns before writing to disk (cheap header check).
    try:
        header_line = content.decode("utf-8", errors="replace").split("\n")[0]
        # Strip BOM + whitespace, normalise to lower-case for comparison
        cols_found = {c.strip().lstrip("﻿").lower() for c in header_line.split(",")}
        missing = [c for c in _UPLOAD_REQUIRED_COLS if c not in cols_found]
        if missing:
            raise ValueError(
                f"Missing required column(s): {', '.join(missing)}. "
                f"Required: {', '.join(_UPLOAD_REQUIRED_COLS)}"
            )
    except UnicodeDecodeError:
        raise ValueError("File does not appear to be a UTF-8 CSV.")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        wells = load_ndic_fleet(
            tmp_path,
            source_note="User-uploaded monthly production CSV.",
            field_default="User upload",
            operator_default="User upload",
            formation_default="Unknown",
        )
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
    return wells


def _resolve_source() -> tuple[str, list[WellFile] | None, str]:
    """Resolve the ACTIVE data source from the sidebar toggle.

    Returns ``(source, real_wells_or_None, detail)`` where source is 'real' or
    'synthetic'. The DEFAULT is real Colorado (ECMC) public data — free, no key. If a
    selected real source is missing/unparseable, falls back to synthetic with a notice
    so the app always renders.
    """
    choice = st.sidebar.radio(
        "Data source",
        ("Real — Colorado DJ Basin (ECMC)", "Synthetic (demo)",
         "Real — North Dakota (NDIC, your export)", "Upload your own CSV"),
        index=0,
        help="Real — Colorado = FREE ECMC public monthly records (DJ Basin Niobrara/Codell "
             "horizontals); the suite default. Synthetic = modeled wells with known ground "
             "truth + full ESP diagnostics. Real — North Dakota = drop your own NDIC monthly "
             "export at data/real/ndic/production.csv (NDIC bulk data is a paid subscription). "
             "Upload your own CSV = bring any monthly production CSV in the tidy schema. "
             "Real monthly data has no ESP telemetry, so the ESP panel is skipped on those wells.",
    )
    if choice.startswith("Real — Colorado"):
        if COLORADO_CSV.exists():
            try:
                wells = _colorado_wells(str(COLORADO_CSV))
                if wells:
                    return "real", wells, _CO_DETAIL
                st.sidebar.warning("Colorado extract parsed to 0 wells — showing synthetic.")
            except Exception as e:
                st.sidebar.warning(f"Could not read Colorado extract ({e}) — showing synthetic.")
        else:
            st.sidebar.warning("Colorado extract missing — showing synthetic.")
    elif choice.startswith("Real — North Dakota"):
        if NDIC_CSV.exists():
            try:
                wells = _ndic_wells(str(NDIC_CSV))
                if wells:
                    return "real", wells, _REAL_DETAIL
                st.sidebar.warning("NDIC extract parsed to 0 wells — showing synthetic.")
            except Exception as e:
                st.sidebar.warning(f"Could not read NDIC extract ({e}) — showing synthetic.")
        else:
            st.info("No NDIC extract in data/real/ndic/ — NDIC bulk data is a paid "
                    "subscription (see README). The default **Colorado** source is free real data.")
    elif choice == "Upload your own CSV":
        st.sidebar.caption(_UPLOAD_SCHEMA_CAPTION)
        uploaded = st.sidebar.file_uploader(
            "Monthly production CSV", type=["csv"], key="byod_upload",
            help="Tidy monthly CSV: well_id, date (YYYY-MM), oil_bbl, gas_mcf, water_bbl, days. "
                 "Processed in-memory — nothing is stored server-side.",
        )
        if uploaded is None:
            st.info(
                "Upload a monthly production CSV to analyze your own fleet. "
                f"{_UPLOAD_SCHEMA_CAPTION}"
            )
            st.stop()
        try:
            wells = _load_upload(uploaded)
            if wells:
                st.sidebar.success(f"Loaded {len(wells)} well(s) from upload.")
                return "real", wells, _UPLOAD_DETAIL
            st.sidebar.error("No usable wells found in the uploaded CSV.")
        except ValueError as e:
            st.error(
                f"**Could not parse the uploaded CSV.**\n\n{e}\n\n"
                f"Required columns: `{', '.join(_UPLOAD_REQUIRED_COLS)}`"
            )
            st.stop()
        except Exception as e:
            st.error(f"Unexpected error reading CSV: {e}")
            st.stop()
    return "synthetic", None, _SYNTHETIC_DETAIL


@st.cache_data(show_spinner=False)
def _eval_chip_text() -> str:
    """Read the committed blind-holdout result so the header chip never goes stale."""
    try:
        rs = json.loads((REPO_ROOT / "evals" / "results" / "holdout"
                         / "summary_holdout.json").read_text())
        sc = [r for r in rs if "recommendation_match" in r]
        if sc:
            agree = sum(1 for r in sc if r.get("recommendation_match")) / len(sc)
            return f"● {agree:.2f} blind-holdout eval ({len(sc)} cases)"
    except Exception:
        pass
    return "● eval-gated (see Evals tab)"


def _fleet_row(well: WellFile, key: str, lift: str, lateral, basin_formation: str,
               screen_row) -> dict:
    """Build one fleet-table row from a WellFile + its identity + a portfolio screen.

    Shared by the synthetic (JSON) and real (NDIC adapter) sources so both produce the
    SAME columns. ``lateral`` may be None (real NDIC has no completion lateral).
    """
    hist = well.production_history
    n = len(hist)
    oil = water = gas = gor = wc = days_on = float("nan")
    if n:
        last = hist[-1]
        oil = float(last.get("oil_bopd", float("nan")))
        water = float(last.get("water_bwpd", float("nan")))
        gas = float(last.get("gas_mcfd", float("nan")))
        days_on = int(last.get("day", 0))
        if not np.isnan(oil) and not np.isnan(water) and (oil + water) > 0:
            wc = water / (oil + water) * 100.0
        if not np.isnan(gas) and not np.isnan(oil) and oil > 0:
            gor = gas * 1000.0 / oil

    diagnosis = intervention = None
    npv = pi = float("nan")
    if screen_row is not None:
        intervention = screen_row.intervention
        diagnosis = screen_row.diagnosis
        if screen_row.intervention not in _NON_ECONOMIC:
            npv = float(screen_row.npv_usd)
            pi = float(screen_row.profitability_index)

    return {
        "Well": well.well_id,                 # display id (ED-0NNH or NDIC well name)
        "_key": key,                           # page key
        "Lift": lift or "—",
        "Lateral (ft)": lateral,
        "Basin·Formation": basin_formation,
        "Oil BOPD": round(oil, 0) if not np.isnan(oil) else None,
        "Water cut %": round(wc, 1) if not np.isnan(wc) else None,
        "GOR scf/bbl": round(gor, 0) if not np.isnan(gor) else None,
        "Days on prod": days_on if not np.isnan(days_on) else None,
        "Points": n,
        "Indicated": intervention or "—",
        "Diagnosis": diagnosis or ("insufficient data" if n < 5 else "—"),
        "Risked NPV $": round(npv, 0) if not np.isnan(npv) else None,
        "PI": round(pi, 2) if not np.isnan(pi) else None,
    }


@st.cache_data(show_spinner=False)
def _fleet_table(data_dir: str) -> pd.DataFrame:
    """Deterministic one-row-per-well fleet table for the SYNTHETIC fleet (no LLM).

    Columns: identity from the JSON + the shared fleet registry (lift, lateral,
    basin·formation), the latest-point rates / water-cut / GOR / days-on, and the
    deterministic portfolio screen's diagnosis + risked economics (NPV, PI). Wells
    with < 5 production points are kept with NaN/None rather than dropped.
    """
    rows = []
    for path in _well_files(data_dir):
        stem = Path(path).stem            # registry key, e.g. "well_007"
        meta = fleet_registry.get(stem)
        try:
            well = _load_well_cached(path)
        except Exception:
            continue
        try:
            screen_row = screen_well(path)
        except Exception:
            screen_row = None
        rows.append(_fleet_row(well, stem, meta.lift, meta.lateral_length_ft,
                               f"{meta.basin} · {meta.formation}", screen_row))
    return pd.DataFrame(rows)


def _ndic_fleet_table(wells: list[WellFile]) -> pd.DataFrame:
    """Same deterministic fleet table built from REAL NDIC WellFiles (in-memory).

    No fleet-registry join (NDIC wells aren't in the synthetic Permian registry):
    identity comes from the filing itself — lift is blank (NDIC has none), lateral is
    None, basin·formation from the well's field/formation.
    """
    rows = []
    for i, well in enumerate(wells):
        try:
            screen_row = screen_wellfile(well)
        except Exception:
            screen_row = None
        fm = well.completion.get("formation", "—")
        basin_formation = f"{well.field} · {fm}"
        rows.append(_fleet_row(well, f"ndic_{i}", well.artificial_lift.get("type", ""),
                               None, basin_formation, screen_row))
    return pd.DataFrame(rows)


# =====================================================================
# PAGE: Fleet overview
# =====================================================================

def render_overview(source: str, ndic_wells: list[WellFile] | None, detail: str) -> None:
    theme.header(
        "Production Engineer Copilot",
        subtitle="AI agent that reviews a fleet of wells — deterministic petroleum-engineering "
                 "tools + Claude. github.com/diazaeric1-droid/production-engineer-copilot",
        chips=[(f"v{APP_VERSION}", "ver"), (_eval_chip_text(), "eval"),
               ("fleet explorer", "info")],
    )
    theme.data_badge(source, detail)

    theme.how_to(
        "- **What this is** — an AI agent that reviews a fleet of wells: deterministic "
        "petroleum-engineering tools (Arps decline fit, type curve, ESP POR check, "
        "risked NPV) compute the numbers; Claude reasons over them and writes a one-page "
        "review. Every chart works with no API key.\n"
        "- **Data source toggle (sidebar)** — switch between **real Colorado ECMC** public "
        "monthly records (DJ Basin Niobrara/Codell; the free default) and **synthetic** "
        "wells with known ground truth + full ESP telemetry. Real monthly filings carry no "
        "ESP signals, so the ESP diagnostic panel is skipped on those wells.\n"
        "- **Fleet table** — one deterministic row per well; sort any column. **Diagnosis** "
        "is the indicated problem, **Indicated** is the suggested intervention, and **Risked "
        "NPV / PI** come from the portfolio screen (the same analyzers the agent uses).\n"
        "- **Drill into a well** — open any well from the **Wells** section in the sidebar "
        "for its decline vs. type curve, ESP diagnostics, Monte-Carlo economics, and AI review."
    )

    with st.expander(f"🆕 What's New in v{APP_VERSION}"):
        st.markdown(
            "- **Fleet explorer (multipage)** — a Fleet Overview plus a **drill-down page "
            "per well** (`st.navigation`): the original well dashboard (decline vs. type "
            "curve, ESP diagnostics, Monte-Carlo economics, AI review, evals, Generate-AFE).\n"
            "- **Sortable fleet table** — one deterministic row per well with lift, lateral, "
            "basin·formation, latest rates, water cut, GOR, days on production, the indicated "
            "intervention, and risked NPV / capital efficiency from the portfolio screen.\n"
            "- **Unified Upstream Copilot Suite theme** — dark + navy look with a cross-app "
            "sidebar **suite navigator** linking the PE, AFE, ESP, Digest, Deferment & Capital apps.\n"
            "- **Monte-Carlo NPV distribution** — P10/P50/P90 histogram in the Economics tab.\n"
            "- **Generate AFE** — inline one-page authorization preview + diagnosis-JSON export.\n"
            "- **Shared fleet registry** — each well carries its Permian field / formation identity.\n"
            "- **Crash fix** — wells with < 5 production points show an \"insufficient data\" panel."
        )

    table = _ndic_fleet_table(ndic_wells) if source == "real" else _fleet_table(str(DATA_DIR))
    if table.empty:
        st.info("No wells to display for the selected data source.")
        return

    # --- fleet snapshot KPIs ------------------------------------------------
    st.subheader("Fleet Snapshot")
    well_count = len(table)
    total_oil = table["Oil BOPD"].sum(skipna=True)
    avg_wc = table["Water cut %"].mean(skipna=True)
    actionable = table[table["Risked NPV $"].notna()]
    total_npv = actionable["Risked NPV $"].sum() if not actionable.empty else 0.0

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Wells", well_count)
    k2.metric("Total oil (BOPD)", f"{total_oil:,.0f}")
    k3.metric("Avg water cut", f"{avg_wc:.0f}%" if pd.notna(avg_wc) else "—")
    k4.metric("Actionable wells", f"{len(actionable)}")
    k5, k6, k7 = st.columns(3)
    avg_lat = table["Lateral (ft)"].mean(skipna=True)
    k5.metric("Avg lateral (ft)", f"{avg_lat:,.0f}" if pd.notna(avg_lat) else "—")
    k6.metric("Total risked NPV", f"${total_npv/1e6:,.1f}MM")
    best_pi = actionable["PI"].max() if not actionable.empty else float("nan")
    k7.metric("Best capital efficiency (PI)", f"{best_pi:.1f}" if pd.notna(best_pi) else "—")

    # --- sortable fleet table ----------------------------------------------
    st.subheader("Fleet Table")
    st.caption(
        "One deterministic row per well — sort any column. **Risked NPV** and **PI** come "
        "from the portfolio screen (same analyzers the agent uses, no LLM). Open a well from "
        "the **Wells** section in the sidebar to drill into its full dashboard + AI review.")
    display = table.drop(columns=["_key"])
    st.dataframe(
        display, width="stretch", hide_index=True,
        column_config={
            "Risked NPV $": st.column_config.NumberColumn("Risked NPV $", format="$%d"),
            "Oil BOPD": st.column_config.NumberColumn("Oil BOPD", format="%d"),
            "GOR scf/bbl": st.column_config.NumberColumn("GOR scf/bbl", format="%d"),
            "Lateral (ft)": st.column_config.NumberColumn("Lateral (ft)", format="%d"),
        },
    )
    st.download_button("⬇ Download fleet table (CSV)", data=display.to_csv(index=False),
                       file_name="pe_copilot_fleet.csv", mime="text/csv")

    # --- top-opportunity bar (deterministic) -------------------------------
    if not actionable.empty:
        top = actionable.sort_values("Risked NPV $", ascending=False).head(10)
        top = top.iloc[::-1]  # largest at top of horizontal bar
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=top["Risked NPV $"] / 1e6, y=top["Well"], orientation="h",
            marker_color=theme.BLUE,
            hovertemplate="%{y}: $%{x:.2f}MM risked NPV<extra></extra>",
        ))
        fig.update_layout(title="Top Intervention Opportunities (Risked NPV, $MM)",
                          xaxis_title="Risked NPV ($MM)")
        st.plotly_chart(theme.style_fig(fig, height=320, legend=False), width="stretch")
        theme.source_note(
            "Risked NPV = discounted-cash-flow NPV of the indicated intervention × "
            "chance-of-success, from the deterministic portfolio screen; values in $MM.")

    st.caption(
        "📊 Field/portfolio ranking is also available headless: "
        "`python -m src.portfolio data/synthetic/well_*.json`.")

    theme.references(["npv"])


# =====================================================================
# PAGE: per-well drill-down (the original single-well dashboard)
# =====================================================================

def _back_to_overview() -> None:
    target = globals().get("overview")
    try:
        st.page_link(target if target is not None else "app.py",
                     label="← Back to Fleet overview", icon="📊")
    except Exception:
        pass


def render_well(well: WellFile, *, source: str = "synthetic", detail: str = "",
                raw_path: str | None = None, key_ns: str | None = None,
                cross_link_stem: str | None = None) -> None:
    """The single-well dashboard for one WellFile. Behavior for the synthetic source is
    preserved exactly; the BYOK key + run controls live in the page body.

    ``well`` is already-resolved (synthetic from JSON, or a real NDIC adapter WellFile).
    ``raw_path`` is the JSON path for the Raw-Data tab (None for in-memory NDIC wells →
    the dataclass is serialized instead). ``key_ns`` namespaces widget keys (defaults to
    well_id). ``cross_link_stem`` enables sibling-app deep links (synthetic only)."""
    key_ns = key_ns or well.well_id
    hist = pd.DataFrame(well.production_history)

    # ---- header (title + well meta + eval chip) ----------------------------
    _well_meta = (
        f"{well.well_id} · {well.api_number} · {well.field} · "
        f"{well.completion.get('formation', '—')} · {well.artificial_lift.get('type', '—')} lift"
        " — github.com/diazaeric1-droid/production-engineer-copilot"
    )
    theme.header(
        f"Production Engineer Copilot · {well.well_id}",
        subtitle=_well_meta,
        chips=[(f"v{APP_VERSION}", "ver"), (_eval_chip_text(), "eval")],
    )
    theme.data_badge(source, detail)
    # Cross-app deep links use the well_0NN page stem (matches sibling apps'
    # url_path), not the ED-NNH well_id, so the same well opens in each sibling.
    # Only for the synthetic fleet — NDIC wells don't exist in the sibling apps.
    if cross_link_stem:
        theme.well_cross_links("pe-copilot", cross_link_stem)
    _back_to_overview()

    # ---- per-well controls (moved out of the global sidebar) ---------------
    with st.expander("⚙️ AI Well Review Controls (optional — all charts work without a key)",
                     expanded=False):
        cc1, cc2 = st.columns([1, 1])
        with cc1:
            byok_key = st.text_input(
                "🔑 Anthropic API key (optional)", type="password", key=f"byok_{key_ns}",
                help="Bring your own key — used only for this session, never stored. Powers the AI "
                     "well review. Get one at console.anthropic.com. The charts, decline fit, ESP "
                     "diagnostics, economics, and eval dashboard all work without it.")
            show_tools = st.checkbox("Show agent tool calls in review", value=True,
                                     key=f"tools_{key_ns}")
            _model_opts = {
                "Claude Sonnet 4.6 (default)": "claude-sonnet-4-6",
                "Claude Haiku (≈4× cheaper)": "claude-haiku-4-5",
            }
            _model_label = st.selectbox(
                "Model", list(_model_opts), index=0, key=f"model_{key_ns}")
            review_model = _model_opts[_model_label]
            st.caption("Haiku ≈ Sonnet quality on the eval at ~4× lower cost; "
                       "Sonnet is the verified-safe default.")
        with cc2:
            run = st.button("Run AI well review", type="primary", width="stretch",
                            key=f"run_{key_ns}")
            st.caption("Review takes ~30 sec and costs ~$0.05 of your own API credit.")
            st.markdown(
                "Claude reasons and writes; **deterministic Python tools** do the engineering "
                "math (Arps decline fit, ESP POR check, NPV/IRR). Engineering numbers stay "
                "trusted; LLM stays in its lane.")

    # ---- guard: wells with too few points can't be decline-fit -------------
    # fit_decline raises ValueError("Need at least 5 valid production points"); some
    # wells (e.g. well_040/well_041) carry only 4 points. Mirror the agent's graceful
    # "insufficient data" path instead of crashing the whole app.
    if len(hist) < 5:
        st.info(
            f"**{well.well_id}** has only {len(hist)} production point(s) — too few for a "
            "hyperbolic decline fit (need ≥ 5) or the full diagnostic dashboard. "
            "Pick another well, or add production history for this one."
        )
        theme.flag("Insufficient production history", "warn")
        return

    # ---- compute deterministic analytics once ------------------------------
    fit = fit_decline(hist["day"].values, hist["oil_bopd"].values, model="hyperbolic")
    # True type curve: fit early/established decline and extrapolate (not dragged down
    # by the degraded tail like the full-history fit is).
    tc = None
    if analyze_type_curve is not None:
        try:
            tc = analyze_type_curve(hist["day"].values, hist["oil_bopd"].values, model="hyperbolic")
        except Exception:
            tc = None

    latest_oil = float(hist["oil_bopd"].iloc[-1])
    latest_water = float(hist["water_bwpd"].iloc[-1])
    latest_gas = float(hist["gas_mcfd"].iloc[-1])
    days_on = int(hist["day"].iloc[-1])

    esp_diag = None
    if well.artificial_lift.get("type") == "ESP" and well.esp_readings:
        try:
            esp_diag = evaluate_esp(well.esp_readings, well.artificial_lift["pump_spec"])
        except Exception:
            esp_diag = None

    # ---- KPI metrics row ----------------------------------------------------
    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        tc_ref = tc.type_curve_at_last if tc else fit.last_predicted
        delta = latest_oil - tc_ref
        st.metric("Oil rate (BOPD)", f"{latest_oil:,.0f}",
                  delta=f"{delta:+,.0f} vs type curve", delta_color="normal")
    with k2:
        st.metric("Days on production", f"{days_on:,}")
    with k3:
        wc = latest_water / (latest_water + latest_oil) * 100 if (latest_water + latest_oil) > 0 else 0
        st.metric("Water cut", f"{wc:.0f}%")
    with k4:
        glr = latest_gas * 1000 / latest_oil if latest_oil > 0 else 0
        st.metric("GLR (scf/bbl)", f"{glr:,.0f}")
    with k5:
        if esp_diag:
            st.metric("ESP intake (psi)", f"{esp_diag.intake_pressure_psi:.0f}",
                      delta="IN POR" if esp_diag.in_por else "OUT OF POR",
                      delta_color="off" if esp_diag.in_por else "inverse")
        else:
            st.metric("Lift type", well.artificial_lift.get("type", "—"))

    # ---- tabs ---------------------------------------------------------------
    tab_trends, tab_econ, tab_review, tab_evals, tab_raw = st.tabs([
        "📈 Production Trends",
        "💰 Economics (Monte-Carlo)",
        "🤖 AI Review",
        "🧪 Evals",
        "📋 Raw Data",
    ])

    with tab_trends:
        _render_trends(well, hist, fit, tc, latest_oil, esp_diag, key_ns=key_ns)

    with tab_econ:
        _render_economics(well, key_ns)

    with tab_review:
        if raw_path is None:
            # The agent reads a well JSON path; real NDIC wells are in-memory only.
            # Deterministic charts/economics above already render — only the LLM
            # narrative is unavailable for this source.
            st.info("The AI well review runs on the synthetic fleet (the agent reads a "
                    "well JSON). For the real NDIC source, the **deterministic** analysis "
                    "above — decline fit, type curve, economics — still applies; monthly "
                    "public filings carry no ESP telemetry for the diagnostic panel.")
        elif run:
            try:
                with st.spinner("Agent reasoning + tool calls…"):
                    report = run_review(str(raw_path), model=review_model,
                                        verbose=show_tools, api_key=byok_key or None)
                st.markdown(report)
                st.download_button("⬇ Download review (Markdown)", report,
                                   file_name=f"{well.well_id}-review.md")
            except RuntimeError as e:
                if "ANTHROPIC_API_KEY" in str(e):
                    st.warning("Enter your **Anthropic API key** in the controls above to generate the "
                               "AI review. The deterministic analysis — decline fit, ESP diagnostics, "
                               "economics, and the eval dashboard — works without a key.")
                else:
                    raise
        else:
            st.info("☝ Open **AI well review controls** above and click **Run AI well review** to "
                    "generate the agent's full diagnosis and ranked intervention recommendations. The "
                    "charts already show what the agent's deterministic tools have computed.")

    with tab_evals:
        _render_evals()

    with tab_raw:
        if raw_path is not None:
            st.subheader("Raw Well File (JSON)")
            with open(raw_path) as f:
                st.json(json.load(f))
        else:
            # In-memory NDIC WellFile — serialize the dataclass so the tab still shows
            # the normalized record (monthly-cadence history, empty esp_readings, etc.).
            from dataclasses import asdict
            st.subheader("Normalized Well Record (From NDIC Monthly Filings)")
            st.caption("Built in-memory by the NDIC adapter — no JSON file on disk.")
            st.json(asdict(well))

    _back_to_overview()


def _render_trends(well, hist, fit, tc, latest_oil, esp_diag, key_ns: str = "") -> None:
    col_a, col_b = st.columns([3, 2])

    with col_a:
        st.subheader("Production Decline vs. Hyperbolic Type Curve")

        # ADDITIVE data-quality diagnostic: classify which points are representative for
        # trending (vs shut-ins / zero days, gross outliers). Does NOT change `fit`/`tc`
        # — those remain the trusted default the agent + eval use. Fully guarded.
        rep = None
        if classify_representative is not None:
            try:
                rep = classify_representative(well.production_history)
            except Exception:
                rep = None

        show_rep_fit = False
        if rep is not None and rep.n_excluded > 0 and rep.n_representative >= 5:
            show_rep_fit = st.checkbox(
                "Overlay a fit on representative points only", value=False,
                key=f"repfit_{key_ns}",
                help="Diagnostic overlay — refits the decline EXCLUDING the "
                     f"{rep.n_excluded} non-representative point(s). The default fit "
                     "above (used by the AI review + economics) is unchanged.")

        days_dense = np.linspace(hist["day"].min(), hist["day"].max(), 100)
        curve_qi, curve_di, curve_b = (
            (tc.qi, tc.di, tc.b) if tc else (fit.qi, fit.di, fit.b)
        )
        fit_curve = curve_qi / np.power(1 + curve_b * curve_di * days_dense, 1 / max(curve_b, 1e-6))
        tc_label = (
            f"Type curve (b={curve_b:.2f}, fit on first {tc.established_days} pts)"
            if tc else f"Fit (b={fit.b:.2f}, R²={fit.r_squared:.3f})"
        )
        today_below = (tc.deviation_pct < -10) if tc else (fit.fit_residual_pct < -10)

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=hist["day"], y=hist["oil_bopd"], mode="markers+lines", name="Actual oil rate",
            marker=dict(size=10, color=theme.BLUE), line=dict(color=theme.BLUE, width=2)))
        fig.add_trace(go.Scatter(
            x=days_dense, y=fit_curve, mode="lines", name=tc_label,
            line=dict(color=theme.AMBER, width=2, dash="dash")))

        # Mark non-representative points (excluded from trending) with a distinct ✕.
        if rep is not None and rep.n_excluded > 0:
            ex = rep.excluded_mask
            fig.add_trace(go.Scatter(
                x=hist["day"].to_numpy()[ex], y=hist["oil_bopd"].to_numpy()[ex],
                mode="markers", name="Non-representative (excluded)",
                marker=dict(size=14, color=theme.RED, symbol="x",
                            line=dict(width=2, color=theme.RED))))

        # Optional overlay: refit on representative points only (diagnostic, never the default).
        if show_rep_fit and rep is not None:
            try:
                keep = rep.representative
                rep_fit = fit_decline(rep.days[keep], rep.rates[keep], model="hyperbolic")
                rep_curve = rep_fit.qi / np.power(
                    1 + rep_fit.b * rep_fit.di * days_dense, 1 / max(rep_fit.b, 1e-6))
                fig.add_trace(go.Scatter(
                    x=days_dense, y=rep_curve, mode="lines",
                    name=f"Fit on representative only (b={rep_fit.b:.2f}, R²={rep_fit.r_squared:.3f})",
                    line=dict(color=theme.GREEN, width=2, dash="dot")))
            except Exception:
                st.caption("Could not refit on representative points only.")

        fig.add_trace(go.Scatter(
            x=[hist["day"].iloc[-1]], y=[latest_oil], mode="markers", name="Today",
            marker=dict(size=18, color=theme.RED if today_below else theme.GREEN,
                       symbol="circle-open", line=dict(width=3)), showlegend=False))
        fig.update_layout(xaxis_title="Days on production", yaxis_title="Oil rate (BOPD)",
                          hovermode="x unified")
        st.plotly_chart(theme.style_fig(fig, height=380), width="stretch")
        theme.source_note(
            "Hyperbolic Arps decline fit; the dashed type curve is fit on early/established "
            "points and extrapolated. Rates in BOPD vs. days on production.")

        if rep is not None and rep.n_excluded > 0:
            reasons = ", ".join(sorted(rep.reason_counts)) if rep.reason_counts else "—"
            st.caption(
                f"🧹 Data quality: **{rep.n_excluded}** of {rep.n_points} points "
                f"({rep.representative_pct:.0f}% representative) flagged "
                f"non-representative for trending — {reasons}. These are excluded from "
                "the optional representative-only overlay; the default fit above is unchanged.")

    with col_b:
        st.subheader("Fit Summary")
        c1, c2 = st.columns(2)
        with c1:
            st.metric("Initial rate (qᵢ)", f"{fit.qi:,.0f} BOPD")
            st.metric("Decline (Dᵢ)", f"{fit.di:.4f}/day")
        with c2:
            st.metric("Hyperbolic b", f"{fit.b:.2f}")
            st.metric("R²", f"{fit.r_squared:.3f}")

        st.markdown("##### Performance vs. Type Curve")
        if tc is None:
            st.markdown(
                "<div style='color:#aaa; font-size:0.85rem;'>Not enough history for a "
                "type-curve benchmark.</div>", unsafe_allow_html=True)
        else:
            deviation = tc.deviation_pct
            deferred_note = (
                f"<div style='margin-top:0.4rem; color:#aaa; font-size:0.85rem;'>"
                f"Actual {tc.last_actual:.0f} BOPD vs type curve {tc.type_curve_at_last:.0f} BOPD · "
                f"deferred ≈ {tc.deferred_bbl/1000:,.1f} MBO (${tc.deferred_value_usd/1e6:,.1f}MM) "
                f"vs the early-time type curve</div>"
            )
            if deviation < -10:
                st.markdown(
                    f"<div class='flag-high'>⚠ Underperforming type curve by {abs(deviation):.0f}%</div>"
                    f"{deferred_note}", unsafe_allow_html=True)
            elif deviation > 10:
                st.markdown(
                    f"<div class='flag-ok'>✓ Outperforming type curve by {deviation:.0f}%</div>"
                    f"{deferred_note}", unsafe_allow_html=True)
            else:
                st.markdown(
                    f"<div class='flag-ok'>✓ On type curve ({deviation:+.1f}%)</div>"
                    f"{deferred_note}", unsafe_allow_html=True)

    # ESP diagnostic multi-panel
    if esp_diag and well.esp_readings:
        st.divider()
        st.subheader("ESP Diagnostic Signals (Last 5 Days)")

        readings = pd.DataFrame(well.esp_readings)
        readings["date"] = pd.to_datetime(readings["date"])

        fig_esp = make_subplots(
            rows=2, cols=2, subplot_titles=(
                "BFPD vs. POR Window", "Intake Pressure (psi)",
                "Motor Temp (°F)", "Motor Amps (A)"),
            vertical_spacing=0.18, horizontal_spacing=0.10)
        fig_esp.add_trace(go.Scatter(
            x=readings["date"], y=readings["bfpd"], mode="lines+markers",
            line=dict(color=theme.BLUE, width=2), marker=dict(size=8),
            showlegend=False), row=1, col=1)
        fig_esp.add_hrect(y0=esp_diag.por_min_bfpd, y1=esp_diag.por_max_bfpd,
                          fillcolor=theme.GREEN, opacity=0.15, line_width=0, row=1, col=1)
        intake_color = theme.RED if readings["intake_pressure_psi"].iloc[-1] < 50 else theme.BLUE
        fig_esp.add_trace(go.Scatter(
            x=readings["date"], y=readings["intake_pressure_psi"], mode="lines+markers",
            line=dict(color=intake_color, width=2), marker=dict(size=8),
            showlegend=False), row=1, col=2)
        fig_esp.add_hline(y=50, line_dash="dash", line_color=theme.AMBER, row=1, col=2)
        temp_color = theme.RED if readings["motor_temp_f"].iloc[-1] > 320 else theme.BLUE
        fig_esp.add_trace(go.Scatter(
            x=readings["date"], y=readings["motor_temp_f"], mode="lines+markers",
            line=dict(color=temp_color, width=2), marker=dict(size=8),
            showlegend=False), row=2, col=1)
        nameplate = well.artificial_lift["pump_spec"].get("motor_amps_nameplate", 0)
        amp_color = theme.RED if readings["motor_amps"].iloc[-1] > nameplate * 1.15 else theme.BLUE
        fig_esp.add_trace(go.Scatter(
            x=readings["date"], y=readings["motor_amps"], mode="lines+markers",
            line=dict(color=amp_color, width=2), marker=dict(size=8),
            showlegend=False), row=2, col=2)
        if nameplate:
            fig_esp.add_hline(y=nameplate, line_dash="dash", line_color=theme.AMBER,
                              annotation_text="Nameplate", row=2, col=2)
        fig_esp.update_layout(showlegend=False)
        st.plotly_chart(theme.style_fig(fig_esp, height=380, legend=False), width="stretch")

        if esp_diag.flags:
            flag_html = " ".join(f"<div class='flag-high'>⚠ {f}</div>" for f in esp_diag.flags)
            st.markdown(f"**Active ESP flags:** {flag_html}", unsafe_allow_html=True)
        else:
            st.markdown("<div class='flag-ok'>✓ ESP operating within all thresholds</div>",
                        unsafe_allow_html=True)

    # ---- Probabilistic decline forecast (Monte-Carlo, prodpy) --------------
    _render_forecast_bands(well, hist)

    theme.references(["arps", "dca_lib", "fetkovich", "monte_carlo", "prms"])


def _render_forecast_bands(well, hist) -> None:
    """Monte-Carlo P10/P50/P90 decline forecast (rate fan + EUR + NPV) via prodpy.

    ADDITIVE: a fan/EUR/NPV uncertainty view layered on top of the deterministic
    decline fit. Fully guarded — any prodpy/fit issue (or a too-short series) hides
    the section rather than crashing the page. Reuses the same realized-price deck
    the Economics tab uses (sidebar/Economics input, cited assumptions default) so
    the probabilistic value is consistent with the deterministic NPV.
    """
    # Mirror the decline analyzer's insufficient-data guard (need >= 5 points).
    if len(hist) < 5:
        return
    try:
        days = hist["day"].values
        rates = hist["oil_bopd"].values
        fb = decline_forecast_bands(
            days, rates,
            horizon_days=365 * 5, n=500, seed=42,
            model="hyperbolic", step_days=30.0,
            econ_limit_bopd=float(A.ECONOMIC_LIMIT_BOPD),
        )
    except Exception:
        # prodpy missing, fit failure, degenerate series, etc. — hide gracefully.
        return

    st.divider()
    st.subheader("Probabilistic Decline Forecast (Monte-Carlo, prodpy)")
    st.caption(
        "500 Arps parameter draws from the fitted (qᵢ, Dᵢ) sampling distribution "
        f"(prodpy {fb.model}, R²={fb.r_squared:.3f}), seeded → deterministic. Shaded "
        "band = P90–P10 rate fan, line = P50. Reserves convention: P90 conservative ≤ "
        "P50 ≤ P10. Truncated at the {:.0f} BOPD economic limit.".format(
            float(A.ECONOMIC_LIMIT_BOPD)))

    fan_col, eur_col = st.columns([3, 2])

    with fan_col:
        fig_fan = go.Figure()
        # History (actual) for context.
        fig_fan.add_trace(go.Scatter(
            x=hist["day"], y=hist["oil_bopd"], mode="markers",
            name="Actual oil rate",
            marker=dict(size=7, color=theme.BLUE)))
        # Shaded P90–P10 band: draw P10 (upper), then fill down to P90 (lower).
        fig_fan.add_trace(go.Scatter(
            x=fb.days, y=fb.p10_rate, mode="lines", name="P10 (optimistic)",
            line=dict(color=theme.GREEN, width=1)))
        fig_fan.add_trace(go.Scatter(
            x=fb.days, y=fb.p90_rate, mode="lines", name="P90 (conservative)",
            line=dict(color=theme.RED, width=1),
            fill="tonexty", fillcolor="rgba(79,129,189,0.20)"))
        fig_fan.add_trace(go.Scatter(
            x=fb.days, y=fb.p50_rate, mode="lines", name="P50 (median)",
            line=dict(color=theme.AMBER, width=2)))
        fig_fan.update_layout(
            xaxis_title="Days on production", yaxis_title="Oil rate (BOPD)",
            hovermode="x unified", title="P10/P50/P90 Rate Fan")
        st.plotly_chart(theme.style_fig(fig_fan, height=360), width="stretch")
        theme.source_note(
            "Arps decline fit with Monte-Carlo P90/P50/P10 bands; rates in BOPD. "
            "P90 = conservative, P10 = optimistic (SPE-PRMS).")

    with eur_col:
        st.markdown("##### EUR Bands (History Cum + Forecast)")
        e1, e2, e3 = st.columns(3)
        e1.metric("EUR P90", f"{fb.eur_p90/1000:,.0f} MBO",
                  help="Conservative — 90% chance of exceeding")
        e2.metric("EUR P50", f"{fb.eur_p50/1000:,.0f} MBO", help="Median estimate")
        e3.metric("EUR P10", f"{fb.eur_p10/1000:,.0f} MBO",
                  help="Optimistic — 10% chance of exceeding")
        st.caption(
            f"History cum ≈ {fb.cum_history_bbl/1000:,.0f} MBO · forecast to "
            f"{fb.days[-1]/365:,.1f} yr on production.")

        # ---- Probabilistic value — NPV P90/P50/P10 -------------------------
        # Reuse the Economics tab's realized-price input if the visitor set one,
        # else the cited realized-price assumption. Keeps the deck consistent.
        price = float(st.session_state.get(
            f"mcp_{well.well_id}", A.REALIZED_PRICE_USD_PER_BBL))
        try:
            eb = economics_bands(
                fb, price=price, nri=1.0,
                opex_per_bbl=float(A.LOE_USD_PER_BBL),
                discount_annual=float(A.DISCOUNT_RATE),
            )
        except Exception:
            eb = None

        if eb is not None:
            st.markdown("##### Probabilistic Value — NPV P90/P50/P10")
            v1, v2, v3 = st.columns(3)
            v1.metric("NPV P90", f"${eb['npv_p90_usd']/1e6:,.1f}MM",
                      help="Conservative remaining-stream value")
            v2.metric("NPV P50", f"${eb['npv_p50_usd']/1e6:,.1f}MM", help="Median")
            v3.metric("NPV P10", f"${eb['npv_p10_usd']/1e6:,.1f}MM",
                      help="Optimistic")
            st.caption(
                f"PV of the forecast oil stream @ ${price:,.0f}/bbl − "
                f"${A.LOE_USD_PER_BBL:,.0f}/bbl LOE, {A.DISCOUNT_RATE*100:.0f}% "
                "discount (cited assumptions.py). No upfront capital — values the "
                "existing producing stream, not an intervention.")


def _render_economics(well, key_ns: str | None = None) -> None:
    key_ns = key_ns or well.well_id
    st.subheader("Monte-Carlo Intervention Economics")
    st.caption(
        "Runs ~10,000 trials over uncertain inputs — incremental rate (lognormal ±30%), "
        "uplift decline (±0.15 abs), realized price (sd ~$12) — through the same NPV math "
        "the agent's deterministic tool uses. P10 = optimistic, P90 = conservative.")

    c1, c2, c3 = st.columns(3)
    with c1:
        mc_name = st.text_input("Intervention", value="Acid stimulation", key=f"mcn_{key_ns}")
        mc_cost = st.number_input("Treatment cost ($)", value=150_000, step=10_000, min_value=1_000,
                                  key=f"mcc_{key_ns}")
    with c2:
        mc_rate = st.number_input("Incremental rate (BOPD)", value=120.0, step=10.0, min_value=0.0,
                                  key=f"mcr_{key_ns}")
        mc_decline = st.number_input("Uplift decline (/yr)", value=0.6, step=0.05, min_value=0.0,
                                     key=f"mcd_{key_ns}")
    with c3:
        mc_price = st.number_input("Realized price ($/bbl)", value=65.0, step=1.0, min_value=1.0,
                                   key=f"mcp_{key_ns}")
        mc_trials = st.select_slider("Trials", options=[1_000, 5_000, 10_000, 20_000], value=10_000,
                                     key=f"mct_{key_ns}")

    sim = simulate_intervention(
        name=mc_name, treatment_cost_usd=float(mc_cost), incremental_rate_bopd=float(mc_rate),
        uplift_decline_per_yr=float(mc_decline), realized_price_per_bbl=float(mc_price),
        n_trials=int(mc_trials), seed=42)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("P90 NPV (conservative)", f"${sim['npv_p90_usd']/1e6:,.2f}MM")
    m2.metric("P50 NPV (median)", f"${sim['npv_p50_usd']/1e6:,.2f}MM")
    m3.metric("P10 NPV (optimistic)", f"${sim['npv_p10_usd']/1e6:,.2f}MM")
    m4.metric("P(payout)", f"{sim['probability_of_payout']*100:.0f}%",
              help=f"Fraction of trials with NPV>0 AND payout < {sim['payout_cutoff_months']:.0f} months")

    econ_csv_df = pd.DataFrame([{
        "intervention": mc_name,
        "treatment_cost_usd": mc_cost,
        "incremental_rate_bopd": mc_rate,
        "uplift_decline_per_yr": mc_decline,
        "realized_price_per_bbl": mc_price,
        "n_trials": mc_trials,
        "npv_p90_usd": sim["npv_p90_usd"],
        "npv_p50_usd": sim["npv_p50_usd"],
        "npv_p10_usd": sim["npv_p10_usd"],
        "npv_mean_usd": sim["npv_mean_usd"],
        "probability_of_payout": sim["probability_of_payout"],
    }])
    st.download_button("⬇ Download economics results (CSV)", data=econ_csv_df.to_csv(index=False),
                       file_name="pe_copilot_economics.csv", mime="text/csv")

    npv_samples = sim["npv_samples"] / 1e6
    fig_dist = go.Figure()
    fig_dist.add_trace(go.Histogram(x=npv_samples, nbinsx=60, marker=dict(color=theme.BLUE),
                                    name="NPV trials", showlegend=False))
    for x_usd, color, tag in (
        (sim["npv_p90_usd"], theme.RED, "P90"),
        (sim["npv_p50_usd"], theme.BLUE, "P50"),
        (sim["npv_p10_usd"], theme.GREEN, "P10"),
    ):
        fig_dist.add_vline(x=x_usd / 1e6, line_dash="dash", line_color=color,
                           annotation_text=tag, annotation_position="top")
    fig_dist.update_layout(title="Monte-Carlo NPV Distribution",
                           xaxis_title="NPV ($MM)", yaxis_title="Trials")
    st.plotly_chart(theme.style_fig(fig_dist, height=300, legend=False), width="stretch")
    theme.source_note(
        "Monte-Carlo trials of intervention NPV (10% discounted cash flow) over uncertain "
        "inputs; dashed lines = P90/P50/P10, values in $MM. P90 = conservative, P10 = optimistic.")

    tdata = sim["tornado"]
    base_npv = sim["npv_p50_usd"]
    order = sorted(tdata, key=lambda k: tdata[k]["swing"])
    labels = {
        "incremental_rate_bopd": "Incremental rate",
        "uplift_decline_per_yr": "Uplift decline",
        "realized_price_per_bbl": "Realized price",
    }
    fig_t = go.Figure()
    for var in order:
        d = tdata[var]
        lo, hi = d["low_npv"], d["high_npv"]
        left, right = min(lo, hi), max(lo, hi)
        fig_t.add_trace(go.Bar(
            y=[labels.get(var, var)], x=[right - left], base=[left], orientation="h",
            marker=dict(color=theme.BLUE), showlegend=False,
            hovertemplate=(
                f"{labels.get(var, var)}<br>"
                f"low NPV: ${left/1e6:,.2f}MM<br>high NPV: ${right/1e6:,.2f}MM<br>"
                f"swing: ${d['swing']/1e6:,.2f}MM<extra></extra>")))
    fig_t.add_vline(x=base_npv, line_dash="dash", line_color=theme.AMBER,
                    annotation_text="P50", annotation_position="top")
    fig_t.update_layout(title="Tornado — NPV Sensitivity (One-at-a-Time)",
                        xaxis_title="NPV ($)", bargap=0.4)
    st.plotly_chart(theme.style_fig(fig_t, height=300, legend=False), width="stretch")

    verdict = (
        "ROBUST" if sim["npv_p90_usd"] > 0 and sim["probability_of_payout"] > 0.8
        else "MARGINAL" if sim["npv_p50_usd"] > 0
        else "HIGH RISK"
    )
    chip = "flag-ok" if verdict == "ROBUST" else "flag-high"
    st.markdown(
        f"<div class='{chip}'>Risk verdict: {verdict}</div> "
        f"<span style='color:#aaa; font-size:0.85rem;'>"
        f"mean NPV ${sim['npv_mean_usd']/1e6:,.2f}MM over {sim['n_trials']:,} trials</span>",
        unsafe_allow_html=True)

    # ---- AFE-Copilot chaining export ---------------------------------------
    st.divider()
    st.markdown("##### ⬇ Export AFE Diagnosis (For AFE-Copilot)")
    st.caption(
        "Emits a validated JSON object matching AFE-Copilot's AFEDiagnosis schema — "
        "the pe→afe chain. Pick the canonical intervention; identity fields come from the well.")
    af1, af2 = st.columns(2)
    with af1:
        afe_interv = st.selectbox("Intervention (AFE key)", AFE_INTERVENTIONS,
                                  index=AFE_INTERVENTIONS.index("acid_stimulation"),
                                  key=f"afei_{key_ns}")
    with af2:
        afe_diag = st.text_input("Primary diagnosis",
                                 value="Below type curve; mechanical degradation indicated",
                                 key=f"afed_{key_ns}")
    try:
        afe_obj = export_afe_diagnosis(well, {
            "intervention": afe_interv,
            "primary_diagnosis": afe_diag,
            "incremental_rate_bopd": float(mc_rate),
            "expected_uplift_decline_per_yr": float(mc_decline),
        })
        st.download_button(
            "⬇ Export AFE diagnosis (for AFE-Copilot)",
            data=json.dumps(afe_obj, indent=2),
            file_name=f"{well.well_id}-afe-diagnosis.json",
            mime="application/json", key=f"afedl_{key_ns}")
        with st.expander("Preview AFE Diagnosis JSON"):
            st.json(afe_obj)
    except ValueError as e:
        st.warning(f"Cannot build AFE diagnosis: {e}")

    # ---- In-app AFE authorization preview ----------------------------------
    st.divider()
    st.markdown("##### 📝 Authorize — Generate AFE Preview")
    st.caption(
        "Closes the diagnose→authorize loop in-app: a one-page AFE authorization "
        "preview from the selected intervention's calibrated cost (no cross-service "
        "call, no API key). Routes the $ amount to the required approver, then open "
        "the AFE Copilot to draft & track the full authorization.")
    if st.button("Generate AFE", type="primary", key=f"gen_afe_{key_ns}"):
        st.session_state[f"_show_afe_{key_ns}"] = True
    if st.session_state.get(f"_show_afe_{key_ns}"):
        afe_defaults = A.intervention_defaults(afe_interv)
        afe_cost = float(afe_defaults["cost_usd"]) if afe_defaults else float(mc_cost)
        afe_econ_obj = evaluate_intervention(
            name=afe_interv, treatment_cost_usd=afe_cost, incremental_rate_bopd=float(mc_rate),
            uplift_decline_per_yr=float(mc_decline), realized_price_per_bbl=float(mc_price),
            prob_success=(afe_defaults["p_success"] if afe_defaults else 1.0))
        afe_econ = {
            "npv_10pct_usd": afe_econ_obj.npv_10pct_usd,
            "payout_months": afe_econ_obj.payout_months,
            "incremental_rate_bopd": float(mc_rate),
            "profitability_index": afe_econ_obj.profitability_index,
        }
        afe_diag_ctx = {
            "well_id": well.well_id, "api_number": well.api_number,
            "field": well.field, "operator": getattr(well, "operator", None),
            "primary_diagnosis": afe_diag,
        }
        preview = build_afe_preview(afe_diag_ctx, afe_interv, afe_econ)

        if not preview.get("afe_required"):
            theme.flag(f"No AFE required — {preview.get('reason', '')}", "warn")
        else:
            ci1, ci2, ci3 = st.columns(3)
            ci1.metric("Gross AFE estimate", f"${preview['gross_cost_usd']/1e3:,.0f}K")
            ci2.metric("Tangible (capitalized)", f"${preview['tangible_cost_usd']/1e3:,.0f}K",
                       help=f"{preview['tangible_pct']*100:.0f}% of gross — capitalized equipment")
            ci3.metric("Intangible (IDC)", f"${preview['intangible_cost_usd']/1e3:,.0f}K",
                       help="Intangible drilling/service cost — deductible in-year")

            ne1, ne2, ne3 = st.columns(3)
            npv = preview.get("net_npv_usd")
            ne1.metric("Net risked NPV @10%", f"${npv/1e6:,.2f}MM" if npv is not None else "—")
            payout = preview.get("payout_months")
            ne2.metric("Payout", f"{payout:.0f} mo" if payout is not None and payout != float("inf")
                       else "no payout")
            pi = preview.get("profitability_index")
            ne3.metric("Profitability index", f"{pi:.2f}" if pi is not None else "—")

            theme.flag(
                f"Authority routing: {preview['recommended_approver']} "
                f"(gross ${preview['gross_cost_usd']:,.0f})",
                "ok" if (npv is not None and npv > 0) else "warn")
            st.caption(preview["authority_basis"])
            with st.expander("AFE Preview Detail (Line Items + Identity)"):
                st.json(preview)

        st.markdown(
            "🔗 [Open in AFE Copilot](https://afe-copilot.streamlit.app) "
            "to draft & track the full authorization (WI/NRI net economics, JIB "
            "allocation, risk register, audit trail).")

    theme.references(["npv"])


def _render_evals() -> None:
    st.subheader("Eval Dashboard — 41-Case Dev + Blind Holdout")
    st.caption(
        "Reads the committed eval artifacts (evals/results/summary.json, holdout/summary_holdout.json, "
        "case_*.md). No API calls — this is the checked-in baseline the CI regression gate guards. "
        "Wells are de-leaked (the answer is not in the data); the holdout is a blind set the prompt "
        "was not tuned on.")

    EVAL_RESULTS = REPO_ROOT / "evals" / "results"
    summary_path = EVAL_RESULTS / "summary.json"

    def _agreement(p):
        if not p.exists():
            return None
        try:
            rs = json.loads(p.read_text())
        except Exception:
            return None
        sc = [r for r in rs if "recommendation_match" in r]
        if not sc:
            return None
        hits = sum(1 for r in sc if r.get("recommendation_match"))
        kw = [r["keyword_hit_rate"] for r in rs if "keyword_hit_rate" in r]
        return {"hits": hits, "n": len(sc), "agree": hits / len(sc),
                "kw": (sum(kw) / len(kw) if kw else 0.0)}

    holdout = _agreement(EVAL_RESULTS / "holdout" / "summary_holdout.json")

    if not summary_path.exists():
        st.info("No eval summary found at `evals/results/summary.json`. "
                "Run `python -m evals.run_evals` to generate it.")
        return

    try:
        rows = json.loads(summary_path.read_text())
    except Exception as e:
        rows = None
        st.warning(f"Could not parse summary.json: {e}")

    if not rows:
        return

    scored = [r for r in rows if "recommendation_match" in r]
    n = len(scored) if scored else len(rows)
    rec_hits = sum(1 for r in scored if r.get("recommendation_match"))
    agreement = rec_hits / n if n else 0.0
    kw_vals = [r["keyword_hit_rate"] for r in rows if "keyword_hit_rate" in r]
    kw_rate = sum(kw_vals) / len(kw_vals) if kw_vals else 0.0
    errors = [r for r in rows if "error" in r]

    e1, e2, e3, e4 = st.columns(4)
    e1.metric("Dev agreement", f"{agreement*100:.0f}%", f"{rec_hits}/{n}")
    if holdout:
        e2.metric("Blind holdout agreement", f"{holdout['agree']*100:.0f}%",
                  f"{holdout['hits']}/{holdout['n']}",
                  help="The credible number — a held-out set the prompt was not tuned on.")
    else:
        e2.metric("Keyword hit rate", f"{kw_rate*100:.0f}%")
    e3.metric("Keyword hit rate", f"{kw_rate*100:.0f}%")
    e4.metric("Cases", f"{len(rows)}" + (f" + {holdout['n']} blind" if holdout else ""))

    if errors:
        st.warning(f"{len(errors)} case(s) errored during the last run.")

    st.markdown("##### Per-Class Recommendation Agreement")
    cls = {}
    for r in scored:
        c = cls.setdefault(r.get("expected", "—"), [0, 0])
        c[1] += 1
        c[0] += int(bool(r.get("recommendation_match")))
    cls_df = pd.DataFrame(
        [{"expected class": k, "agreement": f"{h/n2*100:.0f}%", "n": n2}
         for k, (h, n2) in sorted(cls.items(), key=lambda kv: kv[1][0] / kv[1][1])])
    st.dataframe(cls_df, width="stretch", hide_index=True)

    st.markdown("##### Per-Case Results")
    table_rows = []
    for r in rows:
        table_rows.append({
            "case": r.get("id", "—"),
            "notes": r.get("notes", ""),
            "expected": r.get("expected", "—"),
            "keyword_hit": (f"{r['keyword_hit_rate']*100:.0f}%" if "keyword_hit_rate" in r else "—"),
            "recommendation": (
                "✅ pass" if r.get("recommendation_match")
                else "❌ miss" if "recommendation_match" in r
                else ("⚠ error" if "error" in r else "—")),
        })
    st.dataframe(pd.DataFrame(table_rows), width="stretch", hide_index=True)

    st.markdown("##### Recommendation Breakdown (Expected → Pass / Miss)")
    conf = {}
    for r in scored:
        exp = r.get("expected", "—")
        bucket = conf.setdefault(exp, {"pass": 0, "miss": 0})
        bucket["pass" if r.get("recommendation_match") else "miss"] += 1
    if conf:
        conf_df = pd.DataFrame([
            {"expected": k, "pass": v["pass"], "miss": v["miss"], "n": v["pass"] + v["miss"]}
            for k, v in sorted(conf.items())])
        st.dataframe(conf_df, width="stretch", hide_index=True)
        misses = conf_df[conf_df["miss"] > 0]
        if not misses.empty:
            st.caption("Outstanding misses concentrate in: " + ", ".join(misses["expected"].tolist()))
    else:
        st.caption("No recommendation_match field in summary rows — breakdown unavailable.")

    st.markdown("##### Case Report")
    case_ids = [r.get("id") for r in rows if r.get("id")]
    if case_ids:
        pick = st.selectbox("View a case report", case_ids)
        md_path = EVAL_RESULTS / f"{pick}.md"
        if md_path.exists():
            st.markdown(md_path.read_text())
        else:
            st.info(f"No saved report for {pick} (expected `{md_path.name}`).")


# =====================================================================
# Shared setup (runs every rerun) + navigation
# =====================================================================

theme.setup_page("Production Engineer Copilot", icon="⛽")
theme.suite_nav("pe-copilot")

# Resolve the active data source ONCE per rerun (renders the sidebar radio), so both
# the overview and the per-well page list reflect the same source. Switching the radio
# triggers a Streamlit rerun, which rebuilds the Wells section for the chosen source.
_source, _ndic_wells, _detail = _resolve_source()

overview = st.Page(
    partial(render_overview, _source, _ndic_wells, _detail),
    title="Fleet Overview", icon="📊", default=True)

if _source == "real" and _ndic_wells:
    # Real NDIC fleet: one page per in-memory WellFile (no JSON path, no cross-links).
    wells = [
        st.Page(
            partial(render_well, w, source=_source, detail=_detail,
                    raw_path=None, key_ns=f"ndic_{i}", cross_link_stem=None),
            title=w.well_id, url_path=f"ndic_{i}")
        for i, w in enumerate(_ndic_wells)
    ]
else:
    # Synthetic fleet: per-well JSON pages (behavior unchanged from before).
    _paths = _well_files(str(DATA_DIR))
    if not _paths:
        st.error("No well files found in data/synthetic/")
        st.stop()
    wells = [
        st.Page(
            partial(render_well, _load_well_cached(p), source="synthetic",
                    detail=_SYNTHETIC_DETAIL, raw_path=p, key_ns=Path(p).stem,
                    cross_link_stem=Path(p).stem),
            title=Path(p).stem, url_path=Path(p).stem)
        for p in _paths
    ]

st.navigation({"Fleet": [overview], "Wells": wells}).run()
