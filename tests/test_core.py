"""Engineering Workbench core tests — alias loader, bootstrap, and the four
pinned numeric invariants that prove the vendored math cores are byte-faithful.

Deterministic, no API key, no network. Bootstrap runs once per session (module
fixture) and regenerates every gitignored artifact, exactly as CI does on a
fresh clone.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import core  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def bootstrapped():
    core.bootstrap(log=lambda *_a, **_k: None)
    return True


# ---------------------------------------------------------------- alias loading
def test_all_four_aliases_import_and_expose_expected_modules():
    assert core.wps_nodal.__name__ == "wps.nodal"
    assert core.pec_decline.__name__ == "pec.analyzers.decline_curve"
    assert core.esp_model.__name__ == "esp.model"
    assert core.gla_glpc.__name__ == "gla.glpc"
    # the key callables each section depends on
    assert callable(core.wps_nodal.vogel_ipr)
    assert callable(core.wps_lift.design_esp)
    assert callable(core.pec_decline.fit_decline)
    assert callable(core.pec_portfolio.screen_wellfile)
    assert callable(core.esp_features.featurize_fleet)
    assert callable(core.esp_survival_model.fit_on_labels)
    assert callable(core.esp_oracle.compute_oracle_ceiling)
    assert callable(core.gla_glpc.optimal_injection)
    assert callable(core.gla_glpc.allocate_fleet)


def test_aliases_are_distinct_packages():
    # All four "src" packages coexist under their aliases in one process.
    mods = {sys.modules["wps"], sys.modules["pec"], sys.modules["esp"], sys.modules["gla"]}
    assert len(mods) == 4
    assert "src" not in sys.modules or sys.modules["src"] not in mods


def test_esp_oracle_generator_module_pinned_to_esp_copy():
    # esp.oracle's `from data.synthetic.generate import ...` must resolve to the
    # ESP app's generator — never pec's or gla's (all three ship one).
    gen = sys.modules["data.synthetic.generate"]
    assert Path(gen.__file__).resolve() == (
        core.APP_DIRS["esp"] / "data" / "synthetic" / "generate.py").resolve()
    assert gen.N_WELLS == 100  # the ESP generator's fleet size


# ---------------------------------------------------------------- bootstrap
def test_bootstrap_produces_expected_files():
    assert core.ESP_MODEL.exists(), "trained ESP model artifact"
    assert core.ESP_TRAINING_REPORT.exists(), "training report for the oracle panel"
    assert len(list(core.ESP_DATA.glob("well_*.csv"))) == 100
    assert (core.ESP_DATA / "labels.csv").exists()
    assert len(list(core.GLA_FLEET_DIR.glob("well_*.csv"))) == 20
    assert core.GLA_GROUND_TRUTH.exists()
    assert core.PEC_COLORADO_CSV.exists(), "committed REAL Colorado extract"
    assert len(list(core.PEC_SYNTH_DIR.glob("well_*.json"))) >= 40


def test_bootstrap_is_idempotent():
    before = core.ESP_MODEL.stat().st_mtime
    core.bootstrap(log=lambda *_a, **_k: None)
    assert core.ESP_MODEL.stat().st_mtime == before  # nothing retrained


# ------------------------------------------------- numeric invariant (a): WPS Vogel
def test_invariant_wps_vogel_aof_1095_5():
    """WPS's published worked example (Beggs; Guo et al. Ch.3) through the alias:
    saturated well, p_res = 2085 psia, flow test 282 STB/d @ 1765 psia →
    AOF = 282 / 0.2575 = 1095.5 STB/d."""
    ipr = core.wps_nodal.vogel_ipr(p_res=2085.0, pb=2085.0,
                                   q_test=282.0, pwf_test=1765.0, n=400)
    assert round(ipr.aof, 1) == 1095.5
    assert abs(ipr.q_at(1765.0) - 282.0) < 1e-2  # the test point is honored


# ------------------------------------------------- numeric invariant (b): gla optimum
def test_invariant_gla_analytical_optimum_closed_form():
    """Closed-form optimum: Qinj* = ln[(q_max−q_sl)·a·(1−wc)·price·nri / gas] / a
    = ln(400·1.0·0.6·70·0.8 / 1.5) = ln(13440/1.5) ≈ 9.1005 Mscfd."""
    opt = core.gla_glpc.optimal_injection(
        core.gla_glpc.GLPCParams(q_sl=200, q_max=600, a=1.0),
        water_cut=0.40, oil_price=70.0, gas_cost_per_mscf=1.50, nri=0.80)
    assert opt.q_inj_opt == pytest.approx(math.log(13440 / 1.5) / 1.0, abs=1e-3)


# ------------------------------------------------- numeric invariant (c): esp model
def test_invariant_esp_model_probabilities_and_deterministic_top_well():
    fleet = core.esp_fleet()
    features = core.esp_features.featurize_fleet(fleet)
    model = core.esp_model.ESPRiskModel.load(core.ESP_MODEL)
    p1 = model.predict_proba(features)
    p2 = model.predict_proba(features)
    assert len(p1) == 100
    assert np.all((p1 >= 0.0) & (p1 <= 1.0))
    top1 = features.index[int(np.argmax(p1))]
    top2 = features.index[int(np.argmax(p2))]
    assert top1 == top2  # deterministic top-risk well across calls
    assert np.allclose(p1, p2)


# ------------------------------------------------- numeric invariant (d): pec decline
def test_invariant_view_wrapper_matches_pec_decline_exactly():
    """core.decline_fit_for (the view-layer wrapper every page uses) must return
    numbers IDENTICAL to calling pec's analyzer directly on the same well."""
    wid, well = sorted(core.colorado_wells().items())[0]
    days = np.array([r["day"] for r in well.production_history], dtype=float)
    rates = np.array([r.get("oil_bopd", 0.0) for r in well.production_history],
                     dtype=float)
    direct = core.pec_decline.fit_decline(days, rates, model="hyperbolic")
    wrapped = core.decline_fit_for(well)
    assert wrapped.qi == direct.qi
    assert wrapped.di == direct.di
    assert wrapped.b == direct.b
    assert wrapped.r_squared == direct.r_squared
    assert wrapped.last_predicted == direct.last_predicted


# ---------------------------------------------------------------- merged identity
def test_well_index_merges_domains_with_honest_flags():
    idx = core.well_index().set_index("well_id")
    # 28 real CO wells + the union of the synthetic fleets
    assert (idx["source"] == "real").sum() == 28
    # REAL wells must never claim SCADA or injection data (hard requirement).
    real = idx[idx["source"] == "real"]
    assert not real["has_scada"].any()
    assert not real["has_injection"].any()
    assert real["has_production"].all()
    # a hero well that exists in all three synthetic fleets
    w13 = idx.loc["well_013"]
    assert bool(w13["has_production"]) and bool(w13["has_scada"]) and bool(w13["has_injection"])
    # esp-only wells (well_041..100) have SCADA but no production/injection
    w85 = idx.loc["well_085"]
    assert bool(w85["has_scada"]) and not bool(w85["has_production"])


def test_well_choices_real_first_then_synthetic():
    choices = core.well_choices()
    assert choices[0].startswith("05-")          # CO state API id
    assert choices[28].startswith("well_")       # synthetic block follows
    assert len(choices) == 28 + len(set(core.pec_synthetic_wells())
                                    | set(core.esp_fleet())
                                    | set(core.gla_fleet()))


def test_availability_flags_per_well():
    assert core.availability("well_013") == {
        "production": True, "scada": True, "injection": True}
    co = sorted(core.colorado_wells())[0]
    assert core.availability(co) == {
        "production": True, "scada": False, "injection": False}
    assert core.availability("well_085")["scada"] is True
    assert core.availability("well_085")["production"] is False


def test_blind_holdout_note_reads_committed_artifact():
    note = core.blind_holdout_note()
    assert "0.722" in note
    assert "18" in note
