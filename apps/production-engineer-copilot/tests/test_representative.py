"""Tests for representative-vs-anomalous production-data classification (PE Copilot).

Data quality FOR trending: a shut-in/zero point and a gross outlier are flagged
non-representative, a clean point is representative, an all-clean series flags none.
This is an additive diagnostic — it must not perturb fit_decline / analyze_type_curve.
"""
import numpy as np

from src.analyzers.representative import (
    R_OUTLIER,
    R_ZERO,
    classify_representative,
)


def _clean_history(n: int = 20, qi: float = 1000.0, di: float = 0.003, b: float = 0.9):
    """A clean hyperbolic decline as a WellFile production_history list."""
    days = np.arange(1, n + 1) * 30.0
    rates = qi / np.power(1 + b * di * days, 1 / b)
    return [{"day": int(d), "oil_bopd": float(r)} for d, r in zip(days, rates)]


def test_clean_series_flags_none():
    hist = _clean_history()
    res = classify_representative(hist)
    assert res.representative.all()
    assert res.n_excluded == 0
    assert res.representative_pct == 100.0


def test_shutin_zero_point_is_non_representative():
    hist = _clean_history()
    hist[10]["oil_bopd"] = 0.0  # a production shutdown / zero-rate day
    res = classify_representative(hist)
    assert not res.representative[10]
    assert R_ZERO in res.reasons[10]
    # neighbors stay representative
    assert res.representative[9] and res.representative[11]


def test_gross_outlier_is_non_representative():
    hist = _clean_history()
    hist[14]["oil_bopd"] *= 6.0  # gross spike off the decline trend
    res = classify_representative(hist)
    assert not res.representative[14]
    assert R_OUTLIER in res.reasons[14]


def test_clean_point_stays_representative_amid_anomalies():
    hist = _clean_history()
    hist[5]["oil_bopd"] = 0.0      # shut-in
    hist[15]["oil_bopd"] *= 5.0    # outlier
    res = classify_representative(hist)
    assert res.representative[8]   # an untouched interior point
    assert res.reasons[8] == ""
    assert res.n_excluded >= 2


def test_missing_rate_is_non_representative():
    hist = _clean_history()
    hist[7]["oil_bopd"] = float("nan")
    res = classify_representative(hist)
    assert not res.representative[7]
    assert R_ZERO in res.reasons[7]


def test_short_series_does_not_crash():
    # < MIN_POINTS: still classifies zero points, skips the fit-based outlier test.
    hist = [{"day": 30, "oil_bopd": 500.0}, {"day": 60, "oil_bopd": 0.0},
            {"day": 90, "oil_bopd": 450.0}]
    res = classify_representative(hist)
    assert not res.representative[1]
    assert res.representative[0] and res.representative[2]


def test_additive_does_not_change_default_decline_fit():
    """Eval-safety guard: computing the classification must not mutate inputs or the
    default fit_decline result used by the agent / blind-holdout eval."""
    from src.analyzers.decline_curve import fit_decline
    hist = _clean_history()
    days = np.array([r["day"] for r in hist], dtype=float)
    rates = np.array([r["oil_bopd"] for r in hist], dtype=float)
    before = fit_decline(days, rates, model="hyperbolic")
    classify_representative(hist)  # diagnostic call
    after = fit_decline(days, rates, model="hyperbolic")
    assert before.qi == after.qi and before.di == after.di and before.b == after.b
    # inputs untouched
    assert np.array_equal(rates, np.array([r["oil_bopd"] for r in hist], dtype=float))
