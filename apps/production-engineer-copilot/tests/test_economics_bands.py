"""Tests for the probabilistic NPV bands (NPV P90/P50/P10 from a forecast)."""
import numpy as np
import pytest

from src.analyzers.forecast_bands import decline_forecast_bands
from src.analyzers.economics_bands import economics_bands
from src.analyzers import assumptions as A


def _bands(seed=42, n=400):
    days = np.arange(0, 24 * 30, 30, dtype=float)
    qi, di, b = 800.0, 0.0025, 0.6
    rates = qi / np.power(1 + b * di * days, 1 / b) * (1 + 0.02 * np.sin(days / 50.0))
    return decline_forecast_bands(days, rates, horizon_days=365 * 5, n=n, seed=seed)


def test_npv_ordering_and_finite():
    fb = _bands()
    eb = economics_bands(fb, price=65.0, nri=0.875, opex_per_bbl=12.0, discount_annual=0.10)
    # Reserves convention: NPV_P10 (optimistic) >= NPV_P50 >= NPV_P90 (conservative).
    assert eb["npv_p10_usd"] >= eb["npv_p50_usd"] >= eb["npv_p90_usd"]
    assert np.isfinite(
        [eb["npv_p90_usd"], eb["npv_p50_usd"], eb["npv_p10_usd"]]
    ).all()
    # A profitable producing stream at $65 oil should carry positive value.
    assert eb["npv_p90_usd"] > 0


def test_defaults_pull_from_assumptions():
    fb = _bands()
    eb = economics_bands(fb)
    assert eb["price_per_bbl"] == A.REALIZED_PRICE_USD_PER_BBL
    assert eb["opex_per_bbl"] == A.LOE_USD_PER_BBL
    assert eb["discount_annual"] == A.DISCOUNT_RATE


def test_nri_scales_revenue():
    fb = _bands()
    full = economics_bands(fb, price=65.0, nri=1.0)
    partial = economics_bands(fb, price=65.0, nri=0.80)
    # Lower NRI keeps fewer barrels -> lower NPV at every percentile.
    assert partial["npv_p50_usd"] < full["npv_p50_usd"]
    assert partial["net_price_per_bbl"] < full["net_price_per_bbl"]


def test_deterministic_given_same_bands():
    fb = _bands(seed=42)
    a = economics_bands(fb, price=65.0)
    b = economics_bands(fb, price=65.0)
    assert a["npv_p50_usd"] == b["npv_p50_usd"]
    assert a["npv_p10_usd"] == b["npv_p10_usd"]


def test_below_opex_price_is_not_value_accretive():
    """A price under lifting cost yields non-positive NPV and no payout."""
    fb = _bands()
    eb = economics_bands(fb, price=5.0, opex_per_bbl=12.0)  # net margin < 0
    assert eb["npv_p10_usd"] <= 0
    assert eb["npv_p10_usd"] >= eb["npv_p90_usd"] - 1e-6  # ordering still holds
    assert eb["payout_months_p50"] == float("inf")


def test_short_series_propagates_valueerror_through_pipeline():
    """A too-short series raises in forecast_bands; economics_bands never sees it."""
    days = np.array([0.0, 30.0, 60.0])
    rates = np.array([800.0, 700.0, 600.0])
    with pytest.raises(ValueError):
        fb = decline_forecast_bands(days, rates, n=100)
        economics_bands(fb)  # unreachable — guard fires upstream
