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


# ---------------------------------------------------------------- oracle honesty (#20)
def test_oracle_signal_capture_clamped_and_pooled():
    """PE review #20: the report must carry a POOLED OOF AUROC (ceiling-comparable), and
    signal_capture must never report >100% — a model can't beat its own attainable ceiling.
    Guards against the prior 'captures ~100% / AUROC 0.854 above ceiling 0.853' overclaim."""
    import json
    rep = json.loads(core.ESP_TRAINING_REPORT.read_text())
    assert "auroc_oof_pooled" in rep, "report must carry the pooled OOF AUROC"
    assert 0.5 < rep["auroc_oof_pooled"] <= 1.0
    # pooled OOF should not sit above the pooled ceiling (apples-to-apples)
    labels = core.esp_loader.load_labels(
        core.ESP_DATA / "labels.csv").set_index("well_id")["failed_within_30d"]
    ceiling = core.esp_oracle.compute_oracle_ceiling(labels)
    assert rep["auroc_oof_pooled"] <= ceiling.auroc + 0.02
    # a model AUROC numerically above the ceiling must clamp, not report >100%
    cap = core.esp_oracle.signal_capture(0.999, ceiling.auroc)
    assert cap["ratio"] <= 1.0 and cap["above_chance"] <= 1.0
    assert cap["at_or_above_ceiling"] is True


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


# ---------------------------------------------------------------- v0.2.0 additions
def test_gla_ground_truth_loads_with_expected_columns():
    """The Gas-Lift Optimum fit-vs-truth panel needs the committed ground-truth."""
    gt = core.gla_ground_truth()
    assert not gt.empty
    assert "well_013" in gt.index
    for col in ("q_sl", "q_max", "a", "water_cut", "true_opt_inj"):
        assert col in gt.columns


def test_esp_scores_accepts_and_reuses_model_and_features():
    """esp_scores must produce identical results whether it loads the model/features
    itself or is handed the cached ones (the perf reuse the view layer depends on)."""
    fleet = core.esp_fleet()
    features = core.esp_features.featurize_fleet(fleet)
    model = core.esp_model.ESPRiskModel.load(core.ESP_MODEL)
    probs_passed, _ = core.esp_scores(model=model, features=features)
    probs_self, _ = core.esp_scores()
    assert list(probs_passed.index) == list(probs_self.index)
    assert np.allclose(probs_passed.values, probs_self.values)


def test_well_index_accepts_precomputed_probs():
    """well_index(probs=...) must merge the passed risk Series (cache-reuse path)."""
    probs, _ = core.esp_scores()
    idx = core.well_index(probs=probs).set_index("well_id")
    # a scorable synthetic well carries the risk we passed in
    assert idx.loc["well_013", "esp_risk_30d"] == pytest.approx(float(probs["well_013"]))


# ---------------------------------------------------------------- design seed (v0.3.0)
def test_design_seed_anchors_to_well_with_honest_provenance():
    """The Design-section seed must be (a) finite + physically sane, (b) WELL-SPECIFIC
    (two different wells seed different reservoir/rate/fluid numbers), and (c) honestly
    provenanced — water cut is MEASURED for a production well, reservoir pressure is
    ASSUMED. This is what makes Nodal/Lift forward-design anchored to the selection."""
    a = core.well_design_seed("well_013")
    b = core.well_design_seed("well_017")
    for s in (a, b):
        assert s.reservoir_pressure_psia > 0 and np.isfinite(s.reservoir_pressure_psia)
        assert 0.0 <= s.water_cut_frac < 1.0
        assert s.test_rate_stb_d > 0
        # bubble point can never exceed reservoir pressure (regime guard)
        assert s.bubble_point_psia <= s.reservoir_pressure_psia + 1e-6
        assert s.glr_scf_stb > 0 and s.oil_api > 0 and s.depth_ft > 0
    # well-specific: the two wells do not collapse to identical generic constants
    assert (a.test_rate_stb_d, a.water_cut_frac) != (b.test_rate_stb_d, b.water_cut_frac)
    # provenance is honest about what came from the well vs an assumption
    assert a.provenance["water_cut_frac"] == "measured"
    assert a.provenance["reservoir_pressure_psia"] == "assumed"
    # Bubble point: 'derived' (Standing) only while it sits below reservoir pressure; when
    # the produced-GOR Standing Pb exceeds Pres we clamp it and must NOT keep calling the
    # clamped value 'derived' — it is then the assumed reservoir pressure. (#21)
    for s in (a, b):
        if s.bubble_point_clamped:
            assert s.provenance["bubble_point_psia"] == "assumed"
            assert s.bubble_point_psia == pytest.approx(s.reservoir_pressure_psia)
            assert s.bubble_point_raw_psia >= s.reservoir_pressure_psia
        else:
            assert s.provenance["bubble_point_psia"] == "derived"
            assert s.bubble_point_psia <= s.reservoir_pressure_psia + 1e-6


def test_design_seed_real_and_scada_only_wells_do_not_crash():
    """A real Colorado well (production only) and a SCADA-only synthetic well (no
    production file) must both yield a usable seed — the Design pages never dead-end."""
    real_id = sorted(core.colorado_wells())[0]
    rs = core.well_design_seed(real_id)
    assert rs.source == "real" and rs.reservoir_pressure_psia > 0
    ss = core.well_design_seed("well_085")  # SCADA-only, no production JSON
    assert ss.reservoir_pressure_psia > 0 and ss.test_rate_stb_d > 0


def test_design_seed_never_fabricates_measured_provenance_on_shut_in_tail():
    """Regression: real wells often end in a zero-rate shut-in month. The seed must take
    fluids from the last PRODUCING month, never label an assumed default 'measured'."""
    for wid in sorted(core.colorado_wells()):
        s = core.well_design_seed(wid)
        if s.provenance["water_cut_frac"] == "measured":
            # measured => it came from a real producing record, so current oil is positive
            assert s.current_oil_bopd > 0.0, f"{wid}: 'measured' water cut off a zero record"
        else:
            # otherwise it must be honestly flagged assumed (no production at all)
            assert s.provenance["water_cut_frac"] == "assumed"


def test_design_seed_clamped_bubble_point_is_not_labeled_derived():
    """Regression (#21): when the produced-GOR Standing Pb exceeds reservoir pressure the
    seed clamps Pb to Pres. The clamped value is the ASSUMED reservoir pressure, so it must
    never be presented as a 'derived' correlation result. At least one synthetic well trips
    the clamp; every clamped well must carry the honest provenance + the raw Standing Pb."""
    clamped = 0
    for wid in [f"well_{i:03d}" for i in range(1, 60)]:
        try:
            s = core.well_design_seed(wid)
        except Exception:  # noqa: BLE001 — non-existent id in this fleet
            continue
        if s.bubble_point_clamped:
            clamped += 1
            assert s.provenance["bubble_point_psia"] == "assumed"
            assert s.bubble_point_psia == pytest.approx(s.reservoir_pressure_psia)
            assert s.bubble_point_raw_psia > s.reservoir_pressure_psia
        else:
            assert s.provenance["bubble_point_psia"] == "derived"
    assert clamped > 0, "expected at least one well with a clamped (saturated) bubble point"


# ---------------------------------------------------------------- lift physics (v0.3.0)
def test_lift_design_feasible_flag_and_runout_scaling():
    """ESP design must (a) expose viscosity factors + a frequency-scaled runout, and
    (b) flag an infeasible target (rate beyond pump runout) with a capped stage count
    instead of a runaway thousands-of-stages number (audit)."""
    pm = core.wps_lift.PumpModel()
    # affinity law: runout scales linearly with frequency
    assert pm.runout_bpd(60.0) == pytest.approx(pm.q_runout_bpd, rel=1e-6)
    assert pm.runout_bpd(50.0) == pytest.approx(pm.q_runout_bpd * 50.0 / 60.0, rel=1e-6)
    ipr = core.wps_nodal.vogel_ipr(p_res=3000.0, pb=3000.0, q_test=600.0, pwf_test=2200.0)
    vlp = core.wps_nodal.VLPInputs(water_cut=0.4, glr_scf_stb=300.0)
    # a target far beyond pump runout must be flagged infeasible + capped, not runaway
    huge = core.wps_lift.design_esp(ipr, vlp, target_q_stb_d=9000.0, frequency_hz=60.0)
    assert huge.feasible is False
    assert huge.stages_capped is True
    assert huge.stages <= 1000  # capped, not a nonsense five-figure count
    # a sane target is feasible and carries the viscosity de-rate factors
    ok = core.wps_lift.design_esp(ipr, vlp, target_q_stb_d=900.0, frequency_hz=60.0,
                                  fluid_viscosity_cp=50.0)
    assert 0.0 < ok.head_visc_factor <= 1.0 and 0.0 < ok.eff_visc_factor <= 1.0


def test_lift_design_flags_inflow_limited_and_bep_window():
    """PE review #8/#6: a target at/above the reservoir AOF is INFLOW-limited (distinct
    from a runout/lift limit) and must not emit a stage count off a clamped pwf=0 inflow;
    and the design must expose a BEP operating-window ratio so an out-of-window (e.g.
    severe downthrust) design is flagged rather than passing as a bare 'meets target'."""
    ipr = core.wps_nodal.vogel_ipr(p_res=3000.0, pb=3000.0, q_test=600.0, pwf_test=2200.0)
    vlp = core.wps_nodal.VLPInputs(water_cut=0.4, glr_scf_stb=300.0)
    aof = float(ipr.aof)
    lim = core.wps_lift.design_esp(ipr, vlp, target_q_stb_d=aof, frequency_hz=60.0)
    assert lim.inflow_limited is True
    assert lim.meets_target is False
    assert lim.aof_stb_d == pytest.approx(aof, rel=1e-6)
    # a small target is not inflow-limited but sits well below the BEP window (downthrust)
    low = core.wps_lift.design_esp(ipr, vlp, target_q_stb_d=0.25 * aof, frequency_hz=60.0)
    assert low.inflow_limited is False
    assert low.q_bep_at_freq_bpd > 0 and low.bep_ratio > 0
    assert low.bep_ratio < 0.70 and low.bep_ok is False


def test_gas_lift_sweep_economics_and_rollover_flags():
    """gas_lift_sweep stays backward compatible (no prices -> no econ optimum) and,
    when prices are supplied, returns an economic optimum + an honest rollover flag."""
    ipr = core.wps_nodal.vogel_ipr(p_res=3000.0, pb=3000.0, q_test=600.0, pwf_test=2200.0)
    vlp = core.wps_nodal.VLPInputs(water_cut=0.4, glr_scf_stb=300.0)
    base = core.wps_lift.gas_lift_sweep(ipr, vlp, n=10)
    assert base.econ is None and isinstance(base.rollover, bool)
    econ = core.wps_lift.gas_lift_sweep(ipr, vlp, n=10, oil_price=70.0,
                                        gas_cost=1.5, nri=0.8)
    assert econ.econ is not None
    assert 0.0 <= econ.econ.inj_glr_scf_stb <= base.points[-1].inj_glr_scf_stb + 1e-6


# ---------------------------------------------------------------- probabilistic econ (#2)
def test_simulate_intervention_ordered_deterministic_with_tornado():
    """The probabilistic-economics engine behind the AI Review / Case File MC panels:
    P90<=P50<=P10, payout probability in [0,1], a tornado with a positive swing per input,
    npv_samples for the histogram, and bit-for-bit determinism on a fixed seed."""
    d = core.pec_assumptions.intervention_defaults("acid_stimulation")
    kw = dict(name="acid_stimulation", treatment_cost_usd=d["cost_usd"],
              incremental_rate_bopd=d["uplift_bopd"], uplift_decline_per_yr=d["uplift_decline"],
              realized_price_per_bbl=70.0, discount_rate=0.10, opex_per_bbl=12.0, seed=42)
    s1 = core.pec_economics.simulate_intervention(**kw)
    s2 = core.pec_economics.simulate_intervention(**kw)
    assert s1["npv_p90_usd"] <= s1["npv_p50_usd"] <= s1["npv_p10_usd"]
    assert 0.0 <= s1["probability_of_payout"] <= 1.0
    assert len(s1["npv_samples"]) == s1["n_trials"] == 10_000
    assert set(s1["tornado"]) == {"incremental_rate_bopd", "uplift_decline_per_yr",
                                  "realized_price_per_bbl"}
    assert all(t["swing"] >= 0 for t in s1["tornado"].values())
    assert s1["npv_p50_usd"] == s2["npv_p50_usd"]  # deterministic on the seed
    # default prob_success=1.0 leaves the rng stream identical (no COS draw) — backward compat
    assert s1.get("probability_of_loss", 0.0) >= 0.0

    # chance-of-success path (PE review #18): a miss books -cost, so P(loss) >= the miss
    # rate and P(payout) drops below the all-success case.
    risky = core.pec_economics.simulate_intervention(prob_success=0.70, **kw)
    assert risky["prob_success"] == pytest.approx(0.70)
    assert risky["probability_of_loss"] >= 0.25  # ~30% miss mass at -cost (plus economic misses)
    assert risky["probability_of_payout"] <= s1["probability_of_payout"]
    # the risked deterministic NPV should sit within the MC P90..P10 band (reconciliation #16)
    det = core.pec_economics.evaluate_intervention(
        name="acid_stimulation", treatment_cost_usd=d["cost_usd"],
        incremental_rate_bopd=d["uplift_bopd"], uplift_decline_per_yr=d["uplift_decline"],
        realized_price_per_bbl=70.0, discount_rate=0.10, opex_per_bbl=12.0, prob_success=0.70)
    assert risky["npv_p90_usd"] <= det.npv_10pct_usd <= risky["npv_p10_usd"]


# ---------------------------------------------------------------- survival metrics pin
def test_survival_metrics_beat_km_baseline():
    """Run-Life headline numbers: out-of-fold C-index orders better than chance and the
    IBS beats the covariate-free Kaplan-Meier baseline (the page's central claim)."""
    res = core.esp_survival_model.evaluate_from_disk(
        str(core.ESP_DATA), str(core.ESP_DATA / "labels.csv")).as_dict()
    assert 0.5 < res["c_index"] <= 1.0
    assert res["ibs"] < res["ibs_km_baseline"]


# ---------------------------------------------------------------- committed artifacts
def test_committed_artifacts_present_so_cold_start_is_fast():
    """The deterministic artifacts are COMMITTED, so a fresh checkout needs no first-run
    training and CI need not bootstrap twice. If this fails, cold start regressed."""
    assert core.ESP_MODEL.exists() and core.ESP_TRAINING_REPORT.exists()
    assert any(core.ESP_DATA.glob("well_*.csv"))
    assert core.GLA_FLEET_DIR.exists() and any(core.GLA_FLEET_DIR.glob("well_*.csv"))
    assert core.GLA_GROUND_TRUTH.exists()
    assert any(core.PEC_SYNTH_DIR.glob("well_*.json"))


# ---------------------------------------------------------------- PVT numeric (bluebonnet)
def test_pvt_table_and_bubble_point_are_sane():
    """PVT lens numerics (skipped where bluebonnet is unavailable): bubble point is a
    positive pressure and the PVT table returns finite Bo / viscosity / z over the range."""
    try:
        pvt, _curves, _rta = core.wps_physics()
    except Exception:  # noqa: BLE001 — bluebonnet absent on this runtime
        pytest.skip("bluebonnet unavailable")
    inp = pvt.PVTInputs(api_gravity=38.0, gas_specific_gravity=0.75,
                        solution_gor=900.0, temperature=210.0)
    pb = pvt.bubble_point(inp)
    assert 100.0 < pb < 10000.0
    df = pvt.pvt_table(inp)
    for col in ("Bo", "oil_viscosity", "Bg", "gas_viscosity", "z_factor"):
        assert col in df.columns and np.all(np.isfinite(df[col].values))
    assert (df["z_factor"] > 0).all()
