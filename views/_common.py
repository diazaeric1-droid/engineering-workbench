"""Shared view-layer helpers: session-state access, the global context bar, and
cached heavy loads. Views import this instead of duplicating plumbing.

Caches live here (not in core.py) because they are Streamlit concerns; core stays
importable headless. Every cached function is keyed on hashable args only.
"""
from __future__ import annotations

import streamlit as st

import core
import fleet_registry
import product_theme as pt
import theme

# ---- session-state contract (defaults set in app.py; mirrored here so each view
# also renders standalone under AppTest.from_function) ----------------------------

def ensure_state() -> None:
    ss = st.session_state
    ss.setdefault("oil_price", 70.0)
    ss.setdefault("nri", 0.80)
    ss.setdefault("discount", 0.10)
    ss.setdefault("data_source", "real")
    ss.setdefault("anthropic_key", "")
    if not ss.get("well_id"):
        choices = core.well_choices()
        ss["well_id"] = choices[0] if choices else ""


def deck() -> tuple[float, float, float]:
    ss = st.session_state
    return float(ss["oil_price"]), float(ss["nri"]), float(ss["discount"])


def current_well() -> str:
    return str(st.session_state.get("well_id", ""))


def well_identity(well_id: str) -> dict:
    """Identity strings for the context bar: name, basin/formation, lift, source."""
    if core.is_real_well(well_id):
        w = core.colorado_wells()[well_id]
        return {
            "name": w.well_id,
            "basin_formation": f"DJ Basin (CO) · {w.completion.get('formation', '—')}",
            "lift": w.artificial_lift.get("type", "") or "—",
            "source": "REAL — Colorado ECMC",
        }
    meta = fleet_registry.get(well_id)
    return {
        "name": meta.name,
        "basin_formation": f"{meta.basin} · {meta.formation}",
        "lift": meta.lift,
        "source": "Synthetic (registry)",
    }


def context() -> None:
    """The standard global context bar under every masthead."""
    oil, nri, disc = deck()
    wid = current_well()
    ident = well_identity(wid) if wid else {"name": "—", "basin_formation": "—",
                                            "lift": "—", "source": "—"}
    pt.context_bar([
        ("Well", f"{wid} · {ident['name']}" if wid else "—"),
        ("Formation", ident["basin_formation"]),
        ("Lift", ident["lift"]),
        ("Deck", f"${oil:,.0f}/bbl · {nri:.0%} NRI · {disc:.0%} disc."),
        ("Data", ident["source"]),
    ])


# ---- cached heavy loads ----------------------------------------------------------

@st.cache_resource(show_spinner=False)
def esp_scores_cached():
    """(probs desc Series, Tree-SHAP contribs DataFrame) for the synthetic ESP fleet."""
    return core.esp_scores()


@st.cache_resource(show_spinner=False)
def esp_model_cached():
    return core.esp_model.ESPRiskModel.load(core.ESP_MODEL)


@st.cache_resource(show_spinner=False)
def esp_fleet_cached():
    return core.esp_fleet()


@st.cache_resource(show_spinner=False)
def esp_features_cached():
    return core.esp_features.featurize_fleet(esp_fleet_cached())


@st.cache_resource(show_spinner=False)
def survival_model_cached():
    """Trained discrete-time hazard model on the synthetic run-life ground truth."""
    labels = core.esp_loader.load_labels(core.ESP_DATA / "labels.csv")
    if not {"time_to_event_days", "event_observed"} <= set(labels.columns):
        return None
    return core.esp_survival_model.fit_on_labels(esp_features_cached(), labels)


@st.cache_data(show_spinner=False)
def survival_metrics_cached() -> dict | None:
    """Out-of-fold survival metrics (time-dependent C-index, IBS vs KM baseline)."""
    try:
        return core.esp_survival_model.evaluate_from_disk(
            str(core.ESP_DATA), str(core.ESP_DATA / "labels.csv")).as_dict()
    except Exception:  # noqa: BLE001
        return None


@st.cache_data(show_spinner=False)
def oracle_cached() -> dict | None:
    """Oracle / Bayes ceiling + the model's share of attainable signal."""
    import json
    try:
        labels = core.esp_loader.load_labels(
            core.ESP_DATA / "labels.csv").set_index("well_id")["failed_within_30d"]
        ceiling = core.esp_oracle.compute_oracle_ceiling(labels)
        model_auroc = None
        if core.ESP_TRAINING_REPORT.exists():
            model_auroc = json.loads(core.ESP_TRAINING_REPORT.read_text()).get("auroc_cv_mean")
        cap = (core.esp_oracle.signal_capture(model_auroc, ceiling.auroc)
               if model_auroc else None)
        return {"ceiling": ceiling.as_dict(), "model_auroc": model_auroc, "capture": cap}
    except Exception:  # noqa: BLE001
        return None


@st.cache_resource(show_spinner=False)
def gla_fleet_cached():
    return core.gla_fleet()


@st.cache_data(show_spinner=False)
def well_index_cached():
    return core.well_index()


@st.cache_data(show_spinner=False)
def forecast_bands_cached(well_id: str):
    """Monte-Carlo P10/P50/P90 decline forecast for one production well (seeded)."""
    import numpy as np
    well = core.production_well(well_id)
    if well is None or len(well.production_history) < 5:
        return None
    days = np.array([r["day"] for r in well.production_history], float)
    rates = np.array([r.get("oil_bopd", 0.0) for r in well.production_history], float)
    try:
        return core.pec_forecast_bands.decline_forecast_bands(
            days, rates, horizon_days=365 * 5, n=500, seed=42,
            model="hyperbolic", step_days=30.0,
            econ_limit_bopd=float(core.pec_assumptions.ECONOMIC_LIMIT_BOPD))
    except Exception:  # noqa: BLE001 — prodpy missing / degenerate series
        return None


def provenance_badge(well_id: str) -> None:
    """Green REAL badge for Colorado wells, amber synthetic otherwise."""
    if core.is_real_well(well_id):
        theme.data_badge("real", core.pec_colorado.CO_SOURCE_NOTE)
    else:
        theme.data_badge(
            "synthetic",
            "Modeled well with known ground truth (shared well_0NN registry identity).")
