"""Smoke tests for the deterministic analyzers."""
import glob
import json

import numpy as np
import pytest

from src.analyzers.decline_curve import fit_decline, project_eur, analyze_water_gas_trends
from src.analyzers.economics import (
    evaluate_intervention, simulate_intervention, evaluate_esp_economic_life,
)
from src.analyzers.esp_diagnostics import evaluate_esp
from src.analyzers.dyno_card import evaluate_dyno_card


def test_fit_decline_recovers_known_curve():
    days = np.arange(30, 1000, 30)
    qi_true, di_true, b_true = 1000, 0.003, 0.9
    rates = qi_true / np.power(1 + b_true * di_true * days, 1 / b_true)
    fit = fit_decline(days, rates, model="hyperbolic")
    assert fit.r_squared > 0.99
    assert abs(fit.qi - qi_true) / qi_true < 0.05


def test_remaining_eur_integrates_forward_from_last_day_not_t1():
    """Regression: remaining EUR must integrate the fitted decline FORWARD from the LAST
    observed production day, not from t=1 (the start of history).

    Integrating from t=1 re-counts every barrel already produced over the history window —
    a ~2.2x overstatement here. The fix passes ``from_day=days[-1]`` so only the volume
    still to come (last day -> economic limit) is counted.
    """
    qi_true, di_day, elim = 1000.0, 0.0015, 5.0  # exponential, 1/day decline, econ limit
    # ~18 months of monthly history; the from-t=1 value is ~2.2x the true forward EUR.
    days = np.arange(0, 18 * 30, 30, dtype=float)
    rates = qi_true * np.exp(-di_day * days)
    fit = fit_decline(days, rates, model="exponential")
    last_day = float(days[-1])

    # Analytic targets, both as the same daily sum project_eur uses internally.
    t_all = np.arange(1, 365 * 30)
    q_all = qi_true * np.exp(-di_day * t_all)
    from_t1_analytic = float(q_all[q_all >= elim].sum())          # the BUG's value
    t_fwd = np.arange(int(round(last_day)), 365 * 30)
    q_fwd = qi_true * np.exp(-di_day * t_fwd)
    forward_analytic = float(q_fwd[q_fwd >= elim].sum())          # the CORRECT value

    remaining = project_eur(fit, economic_limit_bopd=elim, from_day=last_day)

    # Matches the forward integral (fit recovers qi/di near-exactly -> tight tolerance).
    assert remaining == pytest.approx(forward_analytic, rel=1e-3)
    # And is decisively NOT the inflated from-t=1 value (~2.2x larger).
    assert from_t1_analytic / forward_analytic > 2.0
    assert remaining < 0.6 * from_t1_analytic

    # Sanity: the legacy default (from_day=0) still reproduces the old from-t=1 total,
    # so the parameter is the only behaviour switch.
    assert project_eur(fit, economic_limit_bopd=elim) == pytest.approx(from_t1_analytic, rel=1e-3)


def test_esp_flags_below_por():
    readings = [{"bfpd": 1200, "intake_pressure_psi": 30, "motor_temp_f": 300, "motor_amps": 70}]
    spec = {"por_min_bfpd": 1800, "por_max_bfpd": 3400, "motor_temp_max_f": 350, "motor_amps_nameplate": 65}
    diag = evaluate_esp(readings, spec)
    assert not diag.in_por
    assert any("BELOW POR" in f for f in diag.flags)


def test_intervention_economics_positive_npv():
    econ = evaluate_intervention(
        name="Acid Stim",
        treatment_cost_usd=150_000,
        incremental_rate_bopd=120,
    )
    assert econ.npv_10pct_usd > 0
    assert econ.payout_months < 12


def test_risk_inputs_reduce_npv_monotonically():
    base = evaluate_intervention("X", 150_000, 120).npv_10pct_usd
    # Each risk lever should only ever lower NPV vs the unrisked base.
    assert evaluate_intervention("X", 150_000, 120, prob_success=0.5).npv_10pct_usd < base
    assert evaluate_intervention("X", 150_000, 120, deferred_days=10, base_rate_bopd=200).npv_10pct_usd < base
    assert evaluate_intervention("X", 150_000, 120, water_cut_pct=80,
                                 water_disposal_per_bbl=1.5).npv_10pct_usd < base


def test_dyno_card_classification():
    assert evaluate_dyno_card([{"pattern": "Incomplete fillage", "fillage_pct": 55}]).classification == "fluid_pound_pumpoff"
    assert evaluate_dyno_card([{"pattern": "Flat card, no fluid load", "fillage_pct": 5}]).classification == "parted_rods"
    assert evaluate_dyno_card([{"pattern": "Full card", "fillage_pct": 95}]).classification == "healthy"


def test_esp_economic_life_old_vs_young():
    # Old, depleted, below-POR -> beam conversion.
    old = evaluate_esp_economic_life(current_oil_bopd=40, current_bfpd=800, por_min_bfpd=1500,
                                     well_age_years=15, remaining_eur_bbl=90_000)
    assert old.recommendation == "esp_to_beam_conversion"
    # Young, healthy reserves -> right-size swap.
    young = evaluate_esp_economic_life(current_oil_bopd=95, current_bfpd=900, por_min_bfpd=1800,
                                       well_age_years=3, remaining_eur_bbl=340_000)
    assert young.recommendation == "esp_swap"


def test_type_curve_healthy_well_reads_on_curve():
    """Regression guard: a clean hyperbolic decline (no degradation) must read ~0%
    deviation. A fixed early-window fit used to swing healthy wells tens of percent
    off and trigger phantom stim recommendations — the degraded-tail-trimming method
    fixes that."""
    from src.analyzers.decline_curve import analyze_type_curve
    days = np.array([30, 60, 90, 120, 180, 240, 300, 365, 450, 540, 630, 720, 810, 900, 990], float)
    rng = np.random.default_rng(0)
    qi, di, b = 1150.0, 0.0032, 0.92
    clean = qi / (1 + b * di * days) ** (1 / b) * (1 + rng.normal(0, 0.05, len(days)))
    assert abs(analyze_type_curve(days, clean).deviation_pct) < 12

    # And a genuinely degraded tail must still read clearly below curve.
    degraded = clean.copy()
    degraded[-3:] *= 0.6
    assert analyze_type_curve(days, degraded).deviation_pct < -10


def test_water_gas_trends_detect_gassing_up():
    hist = [{"day": d, "oil_bopd": 100 - d * 0.02, "water_bwpd": 50,
             "gas_mcfd": 150 + d * 0.5} for d in range(30, 1000, 60)]
    t = analyze_water_gas_trends(hist)
    assert t.gor_trend == "rising"


def test_eval_well_notes_do_not_leak_the_answer():
    """The de-leak invariant: a well file's notes must NOT contain the diagnosis or the
    recommended intervention — the agent has to reason from tool signals, not parrot."""
    banned = ["suspect", "downthrust", "scale signature", "gas interference", "liquid loading",
              "p&a candidate", "paraffin", "pump-off", "parted rod", "end of esp", "uneconomic",
              "diagnos", "recommend", "stimulation", " acid", "intervention", "economic life"]
    wells = glob.glob("data/synthetic/**/*.json", recursive=True)
    assert wells, "no synthetic wells found"
    for fp in wells:
        notes = " ".join(json.load(open(fp)).get("notes", [])).lower()
        leaks = [b for b in banned if b in notes]
        assert not leaks, f"{fp} leaks {leaks} in notes: {notes!r}"


def test_monte_carlo_percentile_ordering_and_centering():
    sim = simulate_intervention(
        name="Acid Stim",
        treatment_cost_usd=150_000,
        incremental_rate_bopd=120,
        n_trials=10_000,
        seed=7,
    )
    # P90 (conservative) < P50 (median) < P10 (optimistic).
    assert sim["npv_p90_usd"] < sim["npv_p50_usd"] < sim["npv_p10_usd"]
    # Stochastic median should sit near the deterministic NPV (same math, mean-preserving draws).
    det = evaluate_intervention(
        name="Acid Stim", treatment_cost_usd=150_000, incremental_rate_bopd=120,
    ).npv_10pct_usd
    assert abs(sim["npv_p50_usd"] - det) / abs(det) < 0.25
    assert 0.0 <= sim["probability_of_payout"] <= 1.0
    assert set(sim["tornado"]) == {
        "incremental_rate_bopd", "uplift_decline_per_yr", "realized_price_per_bbl"
    }
    # Rate is the dominant driver -> largest tornado swing for this strong case.
    swings = {k: v["swing"] for k, v in sim["tornado"].items()}
    assert swings["incremental_rate_bopd"] == max(swings.values())


def test_export_afe_diagnosis_schema():
    from src.tools import export_afe_diagnosis, AFE_INTERVENTIONS

    class _W:
        well_id = "ED-001H"
        api_number = "42-109-12345"
        field = "Delaware Basin"
        operator = "Synthetic Operator"

    out = export_afe_diagnosis(_W(), {
        "intervention": "scale inhibitor squeeze + acid stimulation",
        "primary_diagnosis": "Scale + low intake + below POR",
        "incremental_rate_bopd": 220,
        "expected_uplift_decline_per_yr": 0.7,
    })
    assert set(out) == {
        "well_id", "api_number", "field", "operator", "intervention",
        "primary_diagnosis", "incremental_rate_bopd",
        "expected_uplift_decline_per_yr", "requested_by",
    }
    assert out["intervention"] in AFE_INTERVENTIONS
    assert out["intervention"] == "scale_treatment"
    assert out["incremental_rate_bopd"] == 220.0
