"""Tests for the Monte-Carlo decline-forecast bands (prodpy)."""
import numpy as np
import pytest

from src.analyzers.forecast_bands import (
    decline_forecast_bands,
    ForecastBands,
    prodpy_decline,
)


def _synthetic_decline(qi=800.0, di=0.0025, b=0.6, n_pts=24, step=30.0, noise=0.02):
    """A clean hyperbolic rate-time history (deterministic, small wobble)."""
    days = np.arange(0, n_pts * step, step, dtype=float)
    rates = qi / np.power(1 + b * di * days, 1 / b)
    rates = rates * (1 + noise * np.sin(days / 50.0))  # mild deterministic wobble
    return days, rates


def test_prodpy_decline_loads_without_matplotlib():
    """The lazy loader returns a usable prodpy.decline namespace (Arps + FitResult)."""
    dec = prodpy_decline()
    assert getattr(dec, "Arps", None) is not None
    assert getattr(dec, "FitResult", None) is not None


def test_eur_ordering_and_finite():
    days, rates = _synthetic_decline()
    fb = decline_forecast_bands(days, rates, horizon_days=365 * 5, n=400, seed=42)
    assert isinstance(fb, ForecastBands)
    # Reserves convention: P10 (optimistic) >= P50 >= P90 (conservative).
    assert fb.eur_p10 >= fb.eur_p50 >= fb.eur_p90
    assert np.isfinite([fb.eur_p10, fb.eur_p50, fb.eur_p90]).all()
    assert fb.eur_p90 > 0
    # EUR includes the history floor.
    assert fb.eur_p90 >= fb.cum_history_bbl - 1.0


def test_rate_fan_ordered_and_finite():
    days, rates = _synthetic_decline()
    fb = decline_forecast_bands(days, rates, horizon_days=365 * 3, n=400, seed=7)
    assert fb.p10_rate.shape == fb.p50_rate.shape == fb.p90_rate.shape == fb.days.shape
    assert np.isfinite(fb.p10_rate).all()
    assert np.isfinite(fb.p50_rate).all()
    assert np.isfinite(fb.p90_rate).all()
    # The fan is ordered at every forecast time (small tolerance for float noise).
    assert np.all(fb.p10_rate >= fb.p50_rate - 1e-9)
    assert np.all(fb.p50_rate >= fb.p90_rate - 1e-9)
    assert np.all(fb.p90_rate >= 0.0)


def test_deterministic_given_seed():
    days, rates = _synthetic_decline()
    a = decline_forecast_bands(days, rates, n=300, seed=42)
    b = decline_forecast_bands(days, rates, n=300, seed=42)
    assert a.eur_p50 == b.eur_p50
    assert np.array_equal(a.p50_rate, b.p50_rate)


def test_short_series_raises_valueerror():
    """A degraded/too-short series raises ValueError (caught by the app's guard)."""
    days = np.array([0.0, 30.0, 60.0])
    rates = np.array([800.0, 700.0, 600.0])
    with pytest.raises(ValueError):
        decline_forecast_bands(days, rates, n=100)


def test_degraded_series_with_nonpositive_points_does_not_crash():
    """Non-positive / non-finite points are filtered; if >=5 valid remain it forecasts."""
    days, rates = _synthetic_decline(n_pts=10)
    # Inject some junk that the hygiene filter must drop without crashing.
    rates = rates.copy()
    rates[1] = 0.0
    rates[3] = -5.0
    rates[5] = np.nan
    fb = decline_forecast_bands(days, rates, n=200, seed=1)
    assert np.isfinite([fb.eur_p10, fb.eur_p50, fb.eur_p90]).all()
    assert fb.eur_p10 >= fb.eur_p50 >= fb.eur_p90


def test_too_few_after_filtering_raises():
    """If filtering drops below 5 valid points, raise ValueError (graceful guard)."""
    days = np.arange(0, 300, 30, dtype=float)
    rates = np.full(days.shape, -1.0)  # all non-positive -> all filtered out
    rates[0] = 800.0
    rates[1] = 700.0  # only 2 valid points survive
    with pytest.raises(ValueError):
        decline_forecast_bands(days, rates, n=100)
