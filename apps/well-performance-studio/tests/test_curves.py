"""Deterministic physics-curve tests: declines, monotone cumulative, positive EUR."""
import numpy as np

from src.curves import CurveInputs, arps_overlay, eur_mmscf, production_curve


def test_production_curve_columns_and_finite():
    df = production_curve(CurveInputs())
    assert set(["days", "years", "rate_mscf_d", "cum_mmscf"]).issubset(df.columns)
    assert np.isfinite(df.to_numpy()).all()


def test_cumulative_is_monotonic_nondecreasing():
    df = production_curve(CurveInputs())
    assert (df["cum_mmscf"].diff().fillna(0.0) >= -1e-6).all()


def test_rate_declines_over_time():
    df = production_curve(CurveInputs())
    # late-time rate is below the early-time (post-peak) rate
    assert df["rate_mscf_d"].iloc[5] > df["rate_mscf_d"].iloc[-1]


def test_eur_is_positive_and_finite():
    eur = eur_mmscf(CurveInputs())
    assert np.isfinite(eur) and eur > 0


def test_eur_scales_linearly_with_resource():
    # bluebonnet's recovery factor is a *scaled* quantity (it asymptotes slightly above
    # 1.0, not a 0-1 fraction), so EUR is not capped at M — but Q = M * rf(t/tau) means
    # EUR scales linearly in the resource-in-place M, all else equal.
    e1 = eur_mmscf(CurveInputs(resource_mmscf=2000.0))
    e2 = eur_mmscf(CurveInputs(resource_mmscf=4000.0))
    assert np.isclose(e2 / e1, 2.0, rtol=1e-3)


def test_more_resource_gives_more_eur():
    lo = eur_mmscf(CurveInputs(resource_mmscf=2000.0))
    hi = eur_mmscf(CurveInputs(resource_mmscf=8000.0))
    assert hi > lo


def test_curve_is_deterministic():
    a = production_curve(CurveInputs()).to_numpy()
    b = production_curve(CurveInputs()).to_numpy()
    assert np.allclose(a, b)


def test_arps_overlay_all_b_regimes_finite_and_declining():
    for b in (0.0, 0.5, 1.0):  # exponential, hyperbolic, harmonic
        df = arps_overlay(15000.0, 0.7, b, 20.0)
        assert np.isfinite(df.to_numpy()).all(), f"b={b} produced non-finite values"
        assert df["rate_mscf_d"].iloc[0] > df["rate_mscf_d"].iloc[-1]
        assert df["cum_mmscf"].iloc[-1] > 0
        assert (df["cum_mmscf"].diff().fillna(0.0) >= -1e-6).all()
