"""Engineering Workbench core — alias loader, bootstrap, and the merged well index.

The four component apps each package their logic as a top-level ``src`` package, so
they can't all be imported normally (the name collides). This module loads each app's
``src`` under a distinct alias via importlib:

    wps  → apps/well-performance-studio      (nodal · PVT · curves · RTA · lift design)
    pec  → apps/production-engineer-copilot  (decline/EUR · econ_core · AI well review)
    esp  → apps/esp-failure-risk-agent       (failure classifier · SHAP · survival · oracle)
    gla  → apps/well-gas-lift-advisor        (GLPC fit · analytical optimum · allocation)

so the whole design → diagnose → predict → optimize console runs in ONE Python process
(the same vendored-apps pattern as pe-pipeline's ``pipeline_core``). The apps are
vendored as plain directories under ``apps/`` (mirrored from their own repos, see
VENDORING.md) so the deploy is a single self-contained clone — no submodules.

Import surface notes
--------------------
* ``esp.oracle`` does ``from data.synthetic.generate import ...`` (a top-level
  namespace-package import that works in the standalone repo because the repo root is
  on sys.path). Three vendored apps carry a ``data/synthetic/generate*.py``, so that
  bare import would be ambiguous here. We pre-register the EXACT module from the ESP
  app dir under ``data.synthetic.generate`` (file-location load, same trick pec uses
  for ``prodpy.decline``) so it can never resolve to the wrong app's generator.
* ``wps.pvt`` / ``wps.curves`` / ``wps.rta`` import **bluebonnet** at module top.
  They are exposed lazily via :func:`wps_physics` so the rest of the product imports
  and runs even if bluebonnet is unavailable (the PVT & Type Curves view shows an
  empty-state instead).
* This module is importable WITHOUT streamlit — it is the same headless core the
  tests exercise.

Bootstrap
---------
The gitignored synthetic artifacts are regenerated deterministically on first run:
ESP synthetic SCADA + labels (seed 7) and the trained ESP model artifact (mirrors
``pipeline_core.ensure_esp_model``, plus a ``training_report.json`` so the oracle
panel can compare the OOF AUROC against the Bayes ceiling), and the gas-lift fleet +
ground truth (seed 42). pec's production data (REAL Colorado ECMC + synthetic JSONs)
is committed upstream and vendored as-is — bootstrap only verifies it is present.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import runpy
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
APPS_ROOT = Path(os.environ.get("WORKBENCH_APPS_ROOT", HERE / "apps"))
APP_DIRS = {
    "wps": APPS_ROOT / "well-performance-studio",
    "pec": APPS_ROOT / "production-engineer-copilot",
    "esp": APPS_ROOT / "esp-failure-risk-agent",
    "gla": APPS_ROOT / "well-gas-lift-advisor",
}

# Absorbed component versions (see VENDORING.md). pec's pyproject is the source of
# truth for its version (its src/__init__ lags at 0.9.0).
COMPONENT_VERSIONS = {
    "well-performance-studio": "0.2.4",  # lift: BEP-window + inflow-limited gates; PVT labels
    "production-engineer-copilot": "0.9.3",  # MC chance-of-success; recalibrated uplift defaults
    "esp-failure-risk-agent": "0.7.4",  # pooled-OOF AUROC; capture clamped <=100%
    "well-gas-lift-advisor": "0.2.0",  # fleet regen to realistic Mscf/d; lift-gas-margin labels
}


def _load_pkg(app_dir: Path, alias: str):
    """Load ``app_dir/src`` as a top-level package named ``alias`` so its internal
    relative imports (``from .features import ...``) resolve under that alias."""
    if alias in sys.modules:
        return sys.modules[alias]
    src = app_dir / "src"
    if not (src / "__init__.py").exists():
        raise FileNotFoundError(
            f"{alias}: missing {src}/__init__.py — the apps are vendored under apps/; "
            f"run from the repo root (or set WORKBENCH_APPS_ROOT).")
    spec = importlib.util.spec_from_file_location(
        alias, src / "__init__.py", submodule_search_locations=[str(src)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod


def _register_esp_generator() -> None:
    """Pre-register ``data.synthetic.generate`` from the ESP app dir.

    ``esp.oracle`` imports the generator's constants (N_WELLS, LABEL_NOISE_RATE,
    MASTER_SEED, …) via the top-level name ``data.synthetic.generate``. Registering
    the module by explicit file location pins it to the ESP copy — pec and gla also
    ship a ``data/synthetic/generate*.py``, so a sys.path-based resolution would be
    ambiguous. Importing the module has no side effects (generation runs only under
    ``__main__``).
    """
    if "data.synthetic.generate" in sys.modules:
        return
    gen_path = APP_DIRS["esp"] / "data" / "synthetic" / "generate.py"
    for pkg_name in ("data", "data.synthetic"):
        if pkg_name not in sys.modules:
            pkg = types.ModuleType(pkg_name)
            pkg.__path__ = []  # mark as (empty) package so submodule registration is legal
            sys.modules[pkg_name] = pkg
    spec = importlib.util.spec_from_file_location("data.synthetic.generate", gen_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["data.synthetic.generate"] = mod
    spec.loader.exec_module(mod)


# ---- register the four packages under aliases, then import the entry points ----
_load_pkg(APP_DIRS["wps"], "wps")
_load_pkg(APP_DIRS["pec"], "pec")
_load_pkg(APP_DIRS["esp"], "esp")
_load_pkg(APP_DIRS["gla"], "gla")
_register_esp_generator()

# wps — nodal + lift are pure numpy/scipy (certified physics core, v0.2.2);
# pvt/curves/rta need bluebonnet and are exposed lazily via wps_physics().
wps_nodal = importlib.import_module("wps.nodal")
wps_lift = importlib.import_module("wps.lift")

# pec — diagnose stack (REAL Colorado data + synthetic JSON fleet + econ_core).
pec_loader = importlib.import_module("pec.data_loader")
pec_decline = importlib.import_module("pec.analyzers.decline_curve")
pec_assumptions = importlib.import_module("pec.analyzers.assumptions")
pec_economics = importlib.import_module("pec.analyzers.economics")
pec_econ_core = importlib.import_module("pec.analyzers.econ_core")
pec_forecast_bands = importlib.import_module("pec.analyzers.forecast_bands")
pec_economics_bands = importlib.import_module("pec.analyzers.economics_bands")
pec_esp_diag = importlib.import_module("pec.analyzers.esp_diagnostics")
pec_portfolio = importlib.import_module("pec.portfolio")
pec_colorado = importlib.import_module("pec.adapters.colorado")
pec_ndic = importlib.import_module("pec.adapters.ndic")

# esp — predict stack (classifier + SHAP + survival + oracle ceiling).
esp_loader = importlib.import_module("esp.data_loader")
esp_features = importlib.import_module("esp.features")
esp_model = importlib.import_module("esp.model")
esp_explainer = importlib.import_module("esp.explainer")
esp_survival = importlib.import_module("esp.survival")
esp_survival_model = importlib.import_module("esp.survival_model")
esp_oracle = importlib.import_module("esp.oracle")

# gla — optimize stack (GLPC + analytical optimum + shadow-price allocation).
gla_glpc = importlib.import_module("gla.glpc")
gla_econ_core = importlib.import_module("gla.econ_core")

# pec.agent imports anthropic/rich/dotenv at module top — a comparatively slow
# import that ONLY the (BYOK) AI Well Review path needs. Load it lazily via
# pec_agent() so it never taxes cold start / first paint (perf: change #0).
_pec_agent_mod = None


def pec_agent():
    """Lazily import and return pec.agent (the anthropic-backed AI Well Review).

    Kept off the cold path — every deterministic page renders without it, so the
    anthropic/rich import only happens the first time a user runs the AI review."""
    global _pec_agent_mod
    if _pec_agent_mod is None:
        _pec_agent_mod = importlib.import_module("pec.agent")
    return _pec_agent_mod

# ---- canonical data paths ----------------------------------------------------
PEC_SYNTH_DIR = APP_DIRS["pec"] / "data" / "synthetic"
PEC_COLORADO_CSV = APP_DIRS["pec"] / "data" / "real" / "colorado" / "production.csv"
PEC_HOLDOUT_JSON = APP_DIRS["pec"] / "evals" / "results" / "holdout" / "summary_holdout.json"
ESP_DATA = APP_DIRS["esp"] / "data" / "synthetic"
ESP_MODEL = APP_DIRS["esp"] / "artifacts" / "esp_risk_model.joblib"
ESP_TRAINING_REPORT = APP_DIRS["esp"] / "artifacts" / "training_report.json"
GLA_FLEET_DIR = APP_DIRS["gla"] / "data" / "synthetic" / "fleet"
GLA_GROUND_TRUTH = APP_DIRS["gla"] / "data" / "synthetic" / "ground_truth.csv"


def wps_physics():
    """Lazily import the bluebonnet-backed WPS modules (pvt, curves, rta).

    Returns ``(pvt, curves, rta)``. Raises ImportError if bluebonnet is unavailable —
    callers (the PVT & Type Curves view) catch it and render an empty state, so the
    rest of the product keeps working without the physics engine.
    """
    pvt = importlib.import_module("wps.pvt")
    curves = importlib.import_module("wps.curves")
    rta = importlib.import_module("wps.rta")
    return pvt, curves, rta


# ---- bootstrap (gitignored data + model artifacts regenerate on first run) ----

def _run_generator(script: Path) -> None:
    """runpy a component data generator as __main__, absorbing a benign exit(0).

    gla's generate_fleet.py ends with ``sys.exit(main())`` — under runpy that
    raises SystemExit(None) AFTER the files are written. Re-raise only nonzero
    exit codes (a real failure)."""
    try:
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as exc:  # noqa: PERF203
        if exc.code not in (0, None):
            raise


def ensure_esp_data(log=print) -> None:
    """Synthetic ESP SCADA + labels (seed 7; deterministic). ~100 wells × 60 days."""
    if not any(ESP_DATA.glob("well_*.csv")):
        log("Generating synthetic ESP SCADA fleet…")
        _run_generator(ESP_DATA / "generate.py")


def ensure_esp_model(log=print) -> Path:
    """Train (or load) the ESP failure-risk artifact; mirrors pipeline_core.ensure_esp_model.

    Also writes ``artifacts/training_report.json`` with the out-of-fold CV metrics so
    the Failure Risk view can frame the model AUROC against the oracle ceiling. An
    artifact that exists but fails to load (e.g. trained under an incompatible
    sklearn/xgboost) is retrained rather than crashing the app.
    """
    if ESP_MODEL.exists():
        try:
            esp_model.ESPRiskModel.load(ESP_MODEL)
            return ESP_MODEL
        except Exception:  # noqa: BLE001 — stale/incompatible artifact: retrain below
            log("Existing ESP model artifact unreadable — retraining…")
    ensure_esp_data(log)
    log("Training the ESP failure-risk model (~30 s, one time)…")
    fleet = esp_loader.load_fleet(ESP_DATA)
    X = esp_features.featurize_fleet(fleet)
    labels = esp_loader.load_labels(ESP_DATA / "labels.csv").set_index("well_id")["failed_within_30d"]
    aligned = X.join(labels, how="inner")
    m = esp_model.ESPRiskModel()
    result = m.fit(aligned[X.columns], aligned["failed_within_30d"])
    m.save(ESP_MODEL)
    ESP_TRAINING_REPORT.parent.mkdir(parents=True, exist_ok=True)
    ESP_TRAINING_REPORT.write_text(json.dumps({
        "auroc_cv_mean": result.auroc_cv_mean,
        "auroc_cv_std": result.auroc_cv_std,
        "auroc_oof_pooled": result.auroc_oof_pooled,
        "precision_at_top10pct": result.precision_at_top10pct,
        "recall_at_top10pct": result.recall_at_top10pct,
        "brier": result.brier,
        "n_wells": result.n_wells,
        "n_positives": result.n_positives,
        "calibrated": result.calibrated,
    }, indent=2))
    return ESP_MODEL


def ensure_gla_fleet(log=print) -> None:
    """Synthetic gas-lift fleet + ground truth (seed 42; 20 wells × 120 days)."""
    if not (GLA_FLEET_DIR.exists() and any(GLA_FLEET_DIR.glob("well_*.csv"))
            and GLA_GROUND_TRUTH.exists()):
        log("Generating synthetic gas-lift fleet (injection surveys)…")
        _run_generator(APP_DIRS["gla"] / "data" / "synthetic" / "generate_fleet.py")


def ensure_pec_data(log=print) -> None:
    """pec's data is COMMITTED upstream (real Colorado CSV + synthetic well JSONs) and
    vendored as-is; regenerate the synthetic fleet only if it is somehow absent."""
    if not any(PEC_SYNTH_DIR.glob("well_*.json")):
        log("Regenerating pec synthetic well files…")
        _run_generator(PEC_SYNTH_DIR / "generate.py")
    if not PEC_COLORADO_CSV.exists():
        raise FileNotFoundError(
            f"Committed real Colorado extract missing: {PEC_COLORADO_CSV} — "
            "the vendored production-engineer-copilot copy is incomplete.")


def bootstrap(log=print) -> None:
    """Regenerate every gitignored artifact the product needs. Idempotent."""
    ensure_pec_data(log)
    ensure_esp_data(log)
    ensure_esp_model(log)
    ensure_gla_fleet(log)


# ---- production wells (pec) ---------------------------------------------------
# Stable selection keys: real Colorado wells key on their state API id
# ("05-123-40438"); synthetic wells key on the well_0NN JSON stem. The key is what
# lives in st.session_state["well_id"] and what the registry/availability merge uses.

_co_cache: dict[str, "object"] | None = None
_synth_cache: dict[str, "object"] | None = None


def colorado_wells() -> dict[str, "object"]:
    """{api_id: WellFile} for the committed REAL Colorado ECMC extract (cached)."""
    global _co_cache
    if _co_cache is None:
        wells = pec_colorado.load_colorado_fleet(str(PEC_COLORADO_CSV))
        _co_cache = {w.api_number: w for w in wells}
    return _co_cache


def pec_synthetic_wells() -> dict[str, "object"]:
    """{well_0NN: WellFile} for pec's committed synthetic fleet (cached)."""
    global _synth_cache
    if _synth_cache is None:
        _synth_cache = {
            p.stem: pec_loader.WellFile.from_json(p)
            for p in sorted(PEC_SYNTH_DIR.glob("well_*.json"))
        }
    return _synth_cache


def production_well(well_id: str):
    """WellFile for a selection key, or None if the well has no production data."""
    if well_id in colorado_wells():
        return colorado_wells()[well_id]
    return pec_synthetic_wells().get(well_id)


def is_real_well(well_id: str) -> bool:
    """True for a REAL Colorado ECMC well. Real wells NEVER carry SCADA / injection."""
    return well_id in colorado_wells()


# ---- SCADA wells (esp) ----------------------------------------------------------

def esp_fleet() -> dict[str, "object"]:
    """{well_id: SCADA DataFrame} for the bootstrapped synthetic ESP fleet."""
    return esp_loader.load_fleet(ESP_DATA)


def esp_scores(model=None, features=None):
    """(probs descending pd.Series, SHAP contribs DataFrame) for the whole ESP fleet.

    Accepts an already-loaded ``model`` and ``features`` so the Streamlit layer can
    reuse its caches (esp_model_cached / esp_features_cached) instead of re-loading
    the joblib and re-featurizing the 100-well fleet on every risk page (perf #0)."""
    import pandas as pd
    if features is None:
        features = esp_features.featurize_fleet(esp_fleet())
    if model is None:
        model = esp_model.ESPRiskModel.load(ESP_MODEL)
    probs = pd.Series(model.predict_proba(features), index=features.index,
                      name="risk").sort_values(ascending=False)
    contribs = model.feature_contributions(features)
    return probs, contribs


_gla_truth_cache = None


def gla_ground_truth():
    """Committed gas-lift ground-truth table indexed by well_id (cached).

    Columns: q_sl, q_max, a, water_cut, true_opt_inj, current_inj, over_injected —
    the generator's KNOWN parameters/optimum per injection well. The Gas-Lift Optimum
    view uses this to show fit-vs-truth (parameter recovery), the page's strongest
    demonstrable claim. Returns an empty frame if the artifact is absent."""
    global _gla_truth_cache
    if _gla_truth_cache is None:
        import pandas as pd
        _gla_truth_cache = (pd.read_csv(GLA_GROUND_TRUTH).set_index("well_id")
                            if GLA_GROUND_TRUTH.exists() else pd.DataFrame())
    return _gla_truth_cache


# ---- injection wells (gla) -------------------------------------------------------

def gla_fleet() -> dict[str, "object"]:
    """{well_id: injection-survey DataFrame} for the bootstrapped gas-lift fleet."""
    import pandas as pd
    fleet = {}
    for p in sorted(GLA_FLEET_DIR.glob("well_*.csv")):
        fleet[p.stem] = pd.read_csv(p, parse_dates=["date"])
    return fleet


def analyze_gla_well(df, oil_price: float, gas_cost: float, nri: float):
    """Fit the GLPC + compute the economic optimum for one injection-survey frame.

    Ported verbatim from the Gas-Lift Advisor demo's ``_analyze_well`` (the math is
    entirely in gla.glpc). Returns ``(GLPCParams, water_cut, current_inj, WellOptimum)``.
    """
    import numpy as np
    q_inj = df["injection_gas_mcfd"].values.astype(float)
    bopd = df["bopd"].values.astype(float)
    bwpd = df["bwpd"].values.astype(float)
    q_liq = bopd + bwpd

    mask = q_inj > 0.05
    if int(mask.sum()) >= 4:
        params = gla_glpc.fit_glpc(q_inj[mask], q_liq[mask])
    else:
        q_sl = float(np.percentile(q_liq, 10))
        q_max = float(q_liq.max()) * 1.1
        params = gla_glpc.GLPCParams(q_sl=q_sl, q_max=q_max, a=1.0, r2=0.0)

    liq_sum = q_liq.sum()
    water_cut = float(bwpd.sum() / liq_sum) if liq_sum > 0 else 0.5
    current_inj = float(df["injection_gas_mcfd"].tail(7).mean())
    opt = gla_glpc.optimal_injection(params, water_cut, oil_price, gas_cost, nri)
    return params, water_cut, current_inj, opt


# ---- view-layer decline wrapper (pinned by a numeric-invariant test) -------------

def decline_fit_for(well) -> "object":
    """The product's single decline-fit entry point: hyperbolic Arps via pec.

    A thin, argument-stable wrapper over ``pec.analyzers.decline_curve.fit_decline``
    so every view (Decline & EUR, Case File) fits the SAME way; the test suite pins
    this wrapper's output as numerically identical to calling the pec function
    directly on the same well.
    """
    import numpy as np
    hist = well.production_history
    days = np.array([r.get("day", 0) for r in hist], dtype=float)
    rates = np.array([r.get("oil_bopd", 0.0) for r in hist], dtype=float)
    return pec_decline.fit_decline(days, rates, model="hyperbolic")


def blind_holdout_note() -> str:
    """The honest-eval line for the AI Well Review page, read from the committed
    holdout artifact (0.722 under strict exact-class grading on 18 blind cases)."""
    try:
        rows = json.loads(PEC_HOLDOUT_JSON.read_text())
        scored = [r for r in rows if "recommendation_match" in r]
        agree = sum(1 for r in scored if r.get("recommendation_match")) / len(scored)
        return (f"Blind holdout: {agree:.3f} recommendation agreement on "
                f"{len(scored)} held-out cases under STRICT exact-class grading "
                "(the prompt was never tuned on these cases).")
    except Exception:  # noqa: BLE001
        return ("Blind holdout: 0.722 recommendation agreement under strict "
                "exact-class grading (committed eval artifact unavailable).")


# ---- merged well index (the Fleet → Well Browser backbone) -----------------------

def well_index(probs=None):
    """One row per well across ALL data domains, merged by well_id with availability
    flags. Identity comes from the shared fleet_registry for synthetic ``well_0NN``
    wells, and from the (real) WellFile header for Colorado wells.

    DATA-IDENTITY GUARANTEE: real Colorado wells carry has_scada=False and
    has_injection=False — the synthetic SCADA / injection fleets share the well_0NN
    namespace only, and nothing here ever joins them onto a real well id.

    ``probs`` (an ESP-risk Series) may be passed in so the Streamlit layer can reuse
    its cached scores instead of recomputing them here (perf #0)."""
    import pandas as pd
    sys.path.insert(0, str(HERE)) if str(HERE) not in sys.path else None
    import fleet_registry

    co = colorado_wells()
    synth = pec_synthetic_wells()
    scada = esp_fleet()
    inj = gla_fleet()

    if probs is None:
        try:
            probs, _ = esp_scores()
        except Exception:  # noqa: BLE001 — model not bootstrapped yet
            probs = {}

    rows = []
    for api_id, w in sorted(co.items()):
        hist = w.production_history
        last_oil = float(hist[-1]["oil_bopd"]) if hist else float("nan")
        rows.append({
            "well_id": api_id, "well": w.well_id, "source": "real",
            "basin": "DJ Basin (CO)", "formation": w.completion.get("formation", "—"),
            "lift": w.artificial_lift.get("type", "") or "—",
            "has_production": True, "has_scada": False, "has_injection": False,
            "latest_oil_bopd": last_oil, "latest_bfpd": float("nan"),
            "esp_risk_30d": float("nan"),
        })

    synth_ids = sorted(set(synth) | set(scada) | set(inj))
    for wid in synth_ids:
        meta = fleet_registry.get(wid)
        w = synth.get(wid)
        hist = w.production_history if w else []
        last_oil = float(hist[-1]["oil_bopd"]) if hist else float("nan")
        sc = scada.get(wid)
        last_bfpd = float(sc["bfpd"].iloc[-1]) if sc is not None and len(sc) else float("nan")
        risk = float(probs[wid]) if wid in getattr(probs, "index", []) else float("nan")
        rows.append({
            "well_id": wid, "well": f"{wid} · {meta.name}", "source": "synthetic",
            "basin": meta.basin, "formation": meta.formation, "lift": meta.lift,
            "has_production": w is not None, "has_scada": sc is not None,
            "has_injection": wid in inj,
            "latest_oil_bopd": last_oil, "latest_bfpd": last_bfpd,
            "esp_risk_30d": risk,
        })
    return pd.DataFrame(rows)


def well_choices() -> list[str]:
    """Ordered selection keys for the global well selectbox: real Colorado wells
    first (the product's default data source), then the synthetic well_0NN fleet."""
    co = sorted(colorado_wells())
    synth = sorted(set(pec_synthetic_wells()) | set(esp_fleet()) | set(gla_fleet()))
    return co + synth


def well_label(well_id: str) -> str:
    """Display label for a selection key (name + provenance tag)."""
    co = colorado_wells()
    if well_id in co:
        return f"{well_id} · {co[well_id].well_id} (real)"
    import fleet_registry
    return f"{well_id} · {fleet_registry.get(well_id).name}"


def availability(well_id: str) -> dict:
    """Per-domain availability flags for one well (drives Case File lens gating)."""
    return {
        "production": production_well(well_id) is not None,
        "scada": (not is_real_well(well_id)) and (ESP_DATA / f"{well_id}.csv").exists(),
        "injection": (not is_real_well(well_id)) and (GLA_FLEET_DIR / f"{well_id}.csv").exists(),
    }


# ---- per-well DESIGN SEED (the Design section's anchor to the selected well) ------
# The Nodal / Lift / PVT pages are forward-design what-ifs, but their inputs should be
# SEEDED from the selected well instead of generic slider constants (audit: nodal/lift
# "ignore the selected well"). The honest move a senior PE expects is to seed every
# input from the well's OWN data where it exists and flag the rest as engineering
# assumptions: water cut / GLR / GOR / current rates / (ESP) intake pressure & drive
# frequency are MEASURED in the well file; bubble point / fluid viscosity / BHT are
# DERIVED from those via standard correlations; reservoir pressure / depth / API /
# tubing ID / WHP are ASSUMED from formation-typical values (no public field gives
# them). `well_design_seed` returns all of it plus a per-field provenance map so the
# view can render a measured-vs-assumed table — not a fabricated per-well result.

from dataclasses import dataclass as _dc, field as _dc_field  # noqa: E402


# Formation-typical reservoir context (TVD ft, oil API, pressure gradient psi/ft).
# Used ONLY to seed ASSUMED inputs the public well file does not carry; clearly
# labeled "assumed (formation-typical)" in the seed provenance. Permian + DJ Basin +
# a GoM/other fallback. Values are representative midpoints from public basin studies.
_FORMATION_CONTEXT = {
    "spraberry":   (8200.0, 38.0, 0.46),
    "wolfcamp a":  (9500.0, 40.0, 0.52),
    "wolfcamp b":  (9800.0, 41.0, 0.52),
    "wolfcamp c":  (10000.0, 41.0, 0.52),
    "wolfcamp":    (9500.0, 40.0, 0.50),
    "bone spring": (10500.0, 42.0, 0.50),
    "avalon":      (9200.0, 42.0, 0.49),
    "san andres":  (5000.0, 32.0, 0.43),
    "grayburg":    (4600.0, 33.0, 0.43),
    "clearfork":   (6200.0, 36.0, 0.45),
    "niobrara":    (7000.0, 42.0, 0.45),
    "codell":      (7200.0, 41.0, 0.45),
    "pliocene":    (9000.0, 28.0, 0.46),  # GoM-style, heavier oil
    "miocene":     (11000.0, 30.0, 0.47),
}
_FORMATION_DEFAULT = (8000.0, 38.0, 0.47)


def _formation_context(formation: str) -> tuple[float, float, float]:
    """(TVD ft, API, gradient psi/ft) for a formation name, with a sane default."""
    key = (formation or "").strip().lower()
    if key in _FORMATION_CONTEXT:
        return _FORMATION_CONTEXT[key]
    for name, ctx in _FORMATION_CONTEXT.items():  # loose contains-match
        if name in key or key in name:
            return ctx
    return _FORMATION_DEFAULT


def _standing_bubble_point(gor_scf_stb: float, gas_sg: float, api: float,
                           temp_f: float) -> float:
    """Bubble-point pressure (psia), Standing (1947) — the inverse of the Rs
    correlation wps.nodal uses. Pb = 18.2·[(Rs/γg)^0.83·10^(0.00091·T−0.0125·API) − 1.4]."""
    rs = max(float(gor_scf_stb), 1.0)
    sg = max(float(gas_sg), 0.55)
    a = 0.00091 * float(temp_f) - 0.0125 * float(api)
    pb = 18.2 * ((rs / sg) ** 0.83 * 10.0 ** a - 1.4)
    return float(pb)


@_dc
class WellDesignSeed:
    """Per-well seed for the Design section (nodal / lift / PVT), with provenance.

    Every numeric field is paired with an entry in ``provenance`` whose value is one of
    ``"measured"`` (read from the well's own production/SCADA data), ``"derived"``
    (computed from measured values via a standard correlation), or ``"assumed"``
    (formation-typical engineering estimate — the public well file does not carry it).
    The Design views pre-fill their sliders from this and surface the provenance map so
    the operating point is an honest what-if anchored to the selected well, not a generic
    default mislabeled with the well's name.
    """

    well_id: str
    name: str
    lift_type: str
    formation: str
    source: str  # 'synthetic' | 'real'
    has_production: bool
    # reservoir / IPR
    reservoir_pressure_psia: float
    bubble_point_psia: float
    test_rate_stb_d: float
    test_pwf_psia: float
    # wellbore / completion
    depth_ft: float
    pump_depth_ft: float
    tubing_id_in: float
    wellhead_pressure_psia: float
    # fluids
    water_cut_frac: float
    glr_scf_stb: float
    gor_scf_stb: float
    oil_api: float
    gas_sg: float
    water_sg: float
    temp_surface_f: float
    temp_bottom_f: float
    fluid_viscosity_cp: float
    # current state (measured latest)
    current_oil_bopd: float
    current_water_bwpd: float
    current_gas_mcfd: float
    # ESP telemetry (measured, where present)
    esp_frequency_hz: float | None
    esp_intake_psi: float | None
    provenance: dict = _dc_field(default_factory=dict)
    # raw (uncapped) Standing Pb and whether it was clamped to reservoir pressure. When
    # the produced-GOR Standing Pb lands above the formation-typical reservoir pressure the
    # well is modeled fully saturated and bubble_point_psia is pinned to Pres; these fields
    # let the Design views disclose that instead of showing Pb == Pres as a "derived" value.
    bubble_point_raw_psia: float = 0.0
    bubble_point_clamped: bool = False


def well_design_seed(well_id: str) -> WellDesignSeed:
    """Build a :class:`WellDesignSeed` for ``well_id`` from its own data + correlations.

    Measured where the well file has it (water cut, GLR/GOR, current rates, ESP intake
    pressure & drive frequency), derived where a standard correlation applies (bubble
    point via Standing; BHT from a geothermal gradient; live-oil viscosity), and assumed
    from formation-typical values otherwise (reservoir pressure, depth, API, tubing ID,
    wellhead pressure). Always returns a usable seed — falls back to registry identity +
    formation typicals for SCADA-only wells with no production file.
    """
    prov: dict[str, str] = {}
    real = is_real_well(well_id)
    source = "real" if real else "synthetic"

    # identity + formation
    if real:
        w = colorado_wells().get(well_id)
        name = w.well_id if w else well_id
        formation = (w.completion.get("formation", "") if w else "") or "—"
        lift_type = (w.artificial_lift.get("type", "") if w else "") or "—"
    else:
        try:
            sys.path.insert(0, str(HERE)) if str(HERE) not in sys.path else None
            import fleet_registry
            meta = fleet_registry.get(well_id)
            name, formation, lift_type = meta.name, meta.formation, meta.lift
        except Exception:  # noqa: BLE001
            name, formation, lift_type = well_id, "—", "—"
        w = pec_synthetic_wells().get(well_id)

    depth_typ, api_typ, grad_typ = _formation_context(formation)

    # --- assumed (formation-typical) reservoir/wellbore context ---
    depth_ft = float(depth_typ);          prov["depth_ft"] = "assumed"
    oil_api = float(api_typ);             prov["oil_api"] = "assumed"
    reservoir_pressure_psia = float(depth_ft * grad_typ); prov["reservoir_pressure_psia"] = "assumed"
    gas_sg = 0.75;                        prov["gas_sg"] = "assumed"
    water_sg = 1.05;                      prov["water_sg"] = "assumed"
    wellhead_pressure_psia = 150.0;       prov["wellhead_pressure_psia"] = "assumed"

    # --- measured current state + fluids (from the well's own production history) ---
    # Use the most recent PRODUCING record, not literally hist[-1]: real wells often end
    # in a shut-in tail (oil=water=0). Taking the zero record would silently fall back to
    # the assumed water cut / floored GOR yet still label them "measured" — fabricating the
    # very provenance the seed exists to keep honest. Skip back to the last positive-liquid
    # month; if the well never produced liquid, treat it as no-production.
    hist = w.production_history if w is not None else []
    last = next((r for r in reversed(hist)
                 if (float(r.get("oil_bopd", 0.0) or 0.0)
                     + float(r.get("water_bwpd", 0.0) or 0.0)) > 0), None)
    if last is not None:
        oil = float(last.get("oil_bopd", 0.0) or 0.0)
        water = float(last.get("water_bwpd", 0.0) or 0.0)
        gas_mcfd = float(last.get("gas_mcfd", 0.0) or 0.0)
        liq = oil + water
        water_cut = float(water / liq) if liq > 0 else 0.30
        gor = float(gas_mcfd * 1000.0 / oil) if oil > 0 else 0.0
        glr = float(gas_mcfd * 1000.0 / liq) if liq > 0 else 0.0
        prov["water_cut_frac"] = "measured"
        prov["gor_scf_stb"] = "derived"
        prov["glr_scf_stb"] = "derived"
        prov["current_oil_bopd"] = prov["current_water_bwpd"] = "measured"
        prov["current_gas_mcfd"] = "measured"
    else:
        oil = water = gas_mcfd = liq = 0.0
        water_cut, gor, glr = 0.30, 400.0, 400.0
        prov["water_cut_frac"] = prov["gor_scf_stb"] = prov["glr_scf_stb"] = "assumed"
        prov["current_oil_bopd"] = prov["current_water_bwpd"] = prov["current_gas_mcfd"] = "n/a"
    water_cut = float(min(max(water_cut, 0.0), 0.99))
    gor = float(min(max(gor, 50.0), 5000.0))
    glr = float(min(max(glr, 50.0), 5000.0))

    # --- derived (correlations from measured/assumed) ---
    temp_surface_f = 100.0; prov["temp_surface_f"] = "assumed"
    temp_bottom_f = float(70.0 + 0.013 * depth_ft)  # ~1.3 degF/100 ft geothermal
    prov["temp_bottom_f"] = "derived"
    # NOTE: `gor` here is the well's *produced* (total) GOR used as a proxy for solution
    # Rs. For high-GOR wells the produced GOR overstates Rs, so the Standing Pb below often
    # lands above the formation-typical reservoir pressure; when it does we clamp Pb to Pres
    # and flag it (the clamped value is the assumed Pres, not a correlation output).
    bubble_point_raw = _standing_bubble_point(gor, gas_sg, oil_api, temp_bottom_f)
    bubble_point_clamped = bool(bubble_point_raw > reservoir_pressure_psia)
    bubble_point_psia = float(min(max(bubble_point_raw, 200.0), reservoir_pressure_psia))
    bubble_point_raw_psia = float(max(bubble_point_raw, 200.0))
    # Honest provenance: a clamped Pb is the assumed reservoir pressure, not a derived value.
    prov["bubble_point_psia"] = "assumed" if bubble_point_clamped else "derived"
    try:
        # Evaluate at the bubble point: _live_oil_visc is the SATURATED correlation (it
        # dissolves Rs at the pressure passed in). At reservoir pressure (p > Pb) it would
        # over-dissolve gas vs the well's actual GOR and read too low; the bubble point is
        # where dissolved gas is consistent with the produced GOR.
        mu = wps_nodal._live_oil_visc(bubble_point_psia, temp_bottom_f,
                                      oil_api, gas_sg)
        fluid_viscosity_cp = float(min(max(mu, 1.0), 300.0))
    except Exception:  # noqa: BLE001
        fluid_viscosity_cp = 5.0
    prov["fluid_viscosity_cp"] = "derived"

    # tubing ID: 2-7/8" by default, 3-1/2" for higher-rate wells (assumed)
    tubing_id_in = 2.992 if (oil + water) > 800.0 else 2.441
    prov["tubing_id_in"] = "assumed"
    pump_depth_ft = float(max(depth_ft - 500.0, 100.0))
    prov["pump_depth_ft"] = "assumed"

    # --- IPR test point: prefer a MEASURED ESP suction reading, else a producing point ---
    esp_freq = esp_intake = None
    esp_readings = getattr(w, "esp_readings", None) if w is not None else None
    if esp_readings:
        r = esp_readings[-1]
        esp_freq = float(r.get("frequency_hz", 0.0) or 0.0) or None
        esp_intake = float(r.get("intake_pressure_psi", 0.0) or 0.0) or None
        bfpd = float(r.get("bfpd", 0.0) or 0.0)
        # anchor the IPR to the measured (rate, suction pressure) point; project the
        # intake pressure down to the perfs by the static fluid gradient (intake is set
        # above the perforations).
        if bfpd > 0 and esp_intake:
            grad = 0.433 * ((1 - water_cut) * (141.5 / (131.5 + oil_api))
                            + water_cut * water_sg)
            test_rate_stb_d = float(bfpd)
            test_pwf_psia = float(min(esp_intake + grad * (depth_ft - pump_depth_ft),
                                      reservoir_pressure_psia - 50.0))
            prov["test_rate_stb_d"] = "measured"
            prov["test_pwf_psia"] = "derived"
        else:
            test_rate_stb_d = float(liq) if liq > 0 else 600.0
            test_pwf_psia = float(0.5 * reservoir_pressure_psia)
            prov["test_rate_stb_d"] = "measured" if liq > 0 else "assumed"
            prov["test_pwf_psia"] = "assumed"
    else:
        test_rate_stb_d = float(liq) if liq > 0 else 600.0
        test_pwf_psia = float(0.5 * reservoir_pressure_psia)
        prov["test_rate_stb_d"] = "measured" if liq > 0 else "assumed"
        prov["test_pwf_psia"] = "assumed"

    return WellDesignSeed(
        well_id=well_id, name=name, lift_type=lift_type, formation=formation,
        source=source, has_production=bool(hist),
        reservoir_pressure_psia=reservoir_pressure_psia,
        bubble_point_psia=bubble_point_psia,
        test_rate_stb_d=test_rate_stb_d, test_pwf_psia=test_pwf_psia,
        depth_ft=depth_ft, pump_depth_ft=pump_depth_ft,
        tubing_id_in=tubing_id_in, wellhead_pressure_psia=wellhead_pressure_psia,
        water_cut_frac=water_cut, glr_scf_stb=glr, gor_scf_stb=gor,
        oil_api=oil_api, gas_sg=gas_sg, water_sg=water_sg,
        temp_surface_f=temp_surface_f, temp_bottom_f=temp_bottom_f,
        fluid_viscosity_cp=fluid_viscosity_cp,
        current_oil_bopd=float(oil), current_water_bwpd=float(water),
        current_gas_mcfd=float(gas_mcfd),
        esp_frequency_hz=esp_freq, esp_intake_psi=esp_intake,
        provenance=prov,
        bubble_point_raw_psia=bubble_point_raw_psia,
        bubble_point_clamped=bubble_point_clamped,
    )
