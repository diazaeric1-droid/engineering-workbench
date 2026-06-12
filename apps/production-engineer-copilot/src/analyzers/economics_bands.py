"""Probabilistic value: NPV P90/P50/P10 from a Monte-Carlo decline forecast.

ADDITIVE economics layer that maps the production percentiles of a
:class:`~src.analyzers.forecast_bands.ForecastBands` (the P10/P50/P90 rate fans
from the prodpy Monte-Carlo decline forecast) to **NPV P90/P50/P10** by
discounting each percentile's forecast oil stream.

It reuses the app's cited economic conventions (``src.analyzers.assumptions``)
for the price deck (realized WTI − differential), lifting cost, and the 10%
upstream discount rate, and the **same monthly-discount math** as
``src.analyzers.economics`` (``revenue / (1 + r/12) ** month``) so the
probabilistic value is consistent with the deterministic intervention NPV the
agent already reports — just driven by a forecast rate stream instead of an
uplift stream.

Convention
----------
Petroleum reserves convention: **P10 = high / optimistic, P90 = low /
conservative**. The P10 *production* fan is the largest stream, so it yields the
largest NPV → ``NPV_P10 >= NPV_P50 >= NPV_P90``. (Same direction as the EUR
bands and the existing Monte-Carlo NPV in ``economics.simulate_intervention``.)

Deterministic, no network, no API key: a given ``ForecastBands`` (itself seeded)
maps to identical NPVs every run.
"""
from __future__ import annotations

import numpy as np

from .assumptions import (
    REALIZED_PRICE_USD_PER_BBL,
    LOE_USD_PER_BBL,
    DISCOUNT_RATE,
)
from .forecast_bands import ForecastBands

__all__ = ["economics_bands"]

# numpy>=2 renamed trapz -> trapezoid; resolve without touching the removed name.
try:
    _trapezoid = np.trapezoid          # numpy >= 2.0
except AttributeError:                 # pragma: no cover - very old numpy
    _trapezoid = np.trapz

_DAYS_PER_MONTH = 365.25 / 12  # match economics.py (avoid the 360-day undercount)


def _npv_from_rate_fan(
    days: np.ndarray,
    rate_bopd: np.ndarray,
    *,
    net_price_per_bbl: float,
    opex_per_bbl: float,
    discount_annual: float,
) -> tuple[float, float]:
    """Discount one rate-vs-day forecast stream to an NPV (and undiscounted payout month).

    The forecast axis ``days`` is *days on production* continuing from the last
    history day; we re-base it to **time-from-now** (the start of the forecast)
    so discounting starts at t=0. Each forecast step's incremental oil volume is
    rate × Δt(days), valued at the net margin (price − opex) and discounted at the
    monthly-compounded rate, exactly as ``economics._npv_payout_vectorized`` does.

    Returns ``(npv_usd, payout_month)`` where ``payout_month`` is the first month
    cumulative *undiscounted* net revenue turns positive (``inf`` if never, e.g.
    a negative net margin). There is no upfront capital here (this values an
    existing producing stream, not an intervention), so NPV is simply the
    discounted net cash flow and payout is immediate when the margin is positive.
    """
    days = np.asarray(days, dtype=float)
    rate = np.asarray(rate_bopd, dtype=float)
    if days.size < 2:
        return 0.0, float("inf")

    # Re-base the forecast axis to months-from-start (forecast t0 -> 0).
    t_days = days - float(days[0])
    months = t_days / _DAYS_PER_MONTH

    # Incremental produced volume per step (trapezoid in rate over the day step).
    # bbl over [t_{i-1}, t_i] ~= 0.5*(q_{i-1}+q_i) * Δdays.
    d_days = np.diff(t_days)
    avg_rate = 0.5 * (rate[:-1] + rate[1:])
    step_vol = np.clip(avg_rate, 0.0, None) * np.clip(d_days, 0.0, None)  # (N-1,) bbl

    net_margin = float(net_price_per_bbl) - float(opex_per_bbl)
    step_revenue = step_vol * net_margin  # net $ per step

    # Discount each step at its midpoint month (monthly-compounded, like economics.py).
    mid_month = 0.5 * (months[:-1] + months[1:])
    discount = (1.0 + float(discount_annual) / 12.0) ** mid_month
    npv = float(np.sum(step_revenue / discount))

    # Payout: first step where cumulative undiscounted net revenue >= 0 (>0 capital
    # would shift this; here capital is 0 so a positive margin pays out immediately).
    cumulative = np.cumsum(step_revenue)
    reached = cumulative >= 0.0
    if net_margin > 0 and reached.any():
        payout_month = float(mid_month[int(np.argmax(reached))])
    else:
        payout_month = float("inf")
    return npv, payout_month


def economics_bands(
    fb: ForecastBands,
    *,
    price: float = REALIZED_PRICE_USD_PER_BBL,
    nri: float = 1.0,
    opex_per_bbl: float = LOE_USD_PER_BBL,
    discount_annual: float = DISCOUNT_RATE,
) -> dict:
    """Map a forecast's P10/P50/P90 production fans to NPV P90/P50/P10.

    Parameters
    ----------
    fb : ForecastBands
        Output of :func:`src.analyzers.forecast_bands.decline_forecast_bands`.
        Supplies the forecast time axis (``days``) and the three rate fans.
    price : float
        Realized oil price ($/bbl). Defaults to the cited realized price
        (WTI − Midland/Delaware differential) in ``assumptions.py``. In the app
        this is wired to the sidebar / Economics-tab realized-price input so the
        probabilistic value tracks the same deck the deterministic NPV uses.
    nri : float
        Net revenue interest (0–1). Revenue is taken net of royalty: the operator
        keeps ``price * nri`` per gross barrel. Default 1.0 (8/8ths, gross = net).
    opex_per_bbl : float
        Lifting cost ($/bbl). Defaults to the cited Permian LOE in ``assumptions``.
    discount_annual : float
        Annual discount rate; monthly-compounded internally to match the app's
        existing economics. Defaults to the cited 10% upstream hurdle.

    Returns
    -------
    dict
        ``npv_p90_usd`` (conservative) ≤ ``npv_p50_usd`` (median) ≤ ``npv_p10_usd``
        (optimistic), plus matching payout months, the inputs used, and a short
        ``basis`` string for the UI/citation. All NPVs are finite.

    Notes
    -----
    Reserves convention is enforced: the larger production fan (P10) gives the
    larger NPV, and the returned ordering ``npv_p10 >= npv_p50 >= npv_p90`` is
    guaranteed (a tiny float crossing is clamped, mirroring forecast_bands).
    """
    net_price = float(price) * float(np.clip(nri, 0.0, 1.0))

    def _npv(rate_fan):
        return _npv_from_rate_fan(
            fb.days, rate_fan,
            net_price_per_bbl=net_price,
            opex_per_bbl=opex_per_bbl,
            discount_annual=discount_annual,
        )

    # P10 production fan -> optimistic NPV; P90 production fan -> conservative NPV.
    npv_p10, pay_p10 = _npv(fb.p10_rate)
    npv_p50, pay_p50 = _npv(fb.p50_rate)
    npv_p90, pay_p90 = _npv(fb.p90_rate)

    # Enforce the reserves ordering NPV_P10 >= NPV_P50 >= NPV_P90 against any tiny
    # float crossing (the production fans are already ordered, so this is a guard).
    npv_p50 = min(npv_p50, npv_p10)
    npv_p90 = min(npv_p90, npv_p50)

    return {
        "npv_p90_usd": float(npv_p90),   # conservative (low production)
        "npv_p50_usd": float(npv_p50),   # median
        "npv_p10_usd": float(npv_p10),   # optimistic (high production)
        "payout_months_p90": float(pay_p90),
        "payout_months_p50": float(pay_p50),
        "payout_months_p10": float(pay_p10),
        "net_price_per_bbl": float(net_price),
        "price_per_bbl": float(price),
        "nri": float(np.clip(nri, 0.0, 1.0)),
        "opex_per_bbl": float(opex_per_bbl),
        "discount_annual": float(discount_annual),
        "model": fb.model,
        "basis": (
            f"NPV of the forecast oil stream at ${float(price):,.0f}/bbl × NRI "
            f"{float(np.clip(nri,0.0,1.0)):.2f} − ${float(opex_per_bbl):,.0f}/bbl LOE, "
            f"{float(discount_annual)*100:.0f}% discount (monthly), "
            f"cited assumptions.py · prodpy {fb.model} MC fan"
        ),
    }
