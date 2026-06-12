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
    "well-performance-studio": "0.2.2",
    "production-engineer-copilot": "0.9.2",
    "esp-failure-risk-agent": "0.7.3",
    "well-gas-lift-advisor": "0.1.0",
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

# pec.agent imports anthropic/rich/dotenv at module top — all pinned in
# requirements.txt, so an eager import keeps the AI Well Review path one-hop.
pec_agent = importlib.import_module("pec.agent")

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


def esp_scores():
    """(probs descending pd.Series, SHAP contribs DataFrame) for the whole ESP fleet."""
    fleet = esp_fleet()
    features = esp_features.featurize_fleet(fleet)
    model = esp_model.ESPRiskModel.load(ESP_MODEL)
    import pandas as pd
    probs = pd.Series(model.predict_proba(features), index=features.index,
                      name="risk").sort_values(ascending=False)
    contribs = model.feature_contributions(features)
    return probs, contribs


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

def well_index():
    """One row per well across ALL data domains, merged by well_id with availability
    flags. Identity comes from the shared fleet_registry for synthetic ``well_0NN``
    wells, and from the (real) WellFile header for Colorado wells.

    DATA-IDENTITY GUARANTEE: real Colorado wells carry has_scada=False and
    has_injection=False — the synthetic SCADA / injection fleets share the well_0NN
    namespace only, and nothing here ever joins them onto a real well id.
    """
    import pandas as pd
    sys.path.insert(0, str(HERE)) if str(HERE) not in sys.path else None
    import fleet_registry

    co = colorado_wells()
    synth = pec_synthetic_wells()
    scada = esp_fleet()
    inj = gla_fleet()

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
