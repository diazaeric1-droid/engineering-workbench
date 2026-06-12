"""Arps decline curve analysis (exponential, harmonic, hyperbolic)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from scipy.optimize import curve_fit

# np.trapz was renamed to np.trapezoid in numpy 2.0 and REMOVED in newer numpy.
# Resolve without eagerly touching np.trapz (which raises AttributeError on numpy
# 2.3+ and would crash this module's import — and the whole Streamlit app — at load).
try:
    _trapezoid = np.trapezoid          # numpy >= 2.0
except AttributeError:                 # pragma: no cover - very old numpy
    _trapezoid = np.trapz


DeclineModel = Literal["exponential", "harmonic", "hyperbolic"]


@dataclass
class DeclineFit:
    model: DeclineModel
    qi: float            # initial rate (bbl/d or mcf/d)
    di: float            # initial decline rate (1/day)
    b: float             # hyperbolic exponent (0 = exp, 1 = harmonic)
    r_squared: float
    last_actual: float
    last_predicted: float
    fit_residual_pct: float  # (last actual - full-fit value at last day) / full-fit value.
                             # Quality-of-fit residual, NOT a type-curve deviation —
                             # use analyze_type_curve() for that.


@dataclass
class TypeCurveResult:
    """Benchmark of actual production against a type curve fit on early/established
    decline and extrapolated forward. This is the honest 'is the well underperforming
    its type curve' answer: the curve is NOT dragged down by the degraded tail."""
    model: DeclineModel
    established_days: int          # number of early points the type curve was fit on
    qi: float
    di: float
    b: float
    last_actual: float
    type_curve_at_last: float      # extrapolated type-curve rate at the latest day
    deviation_pct: float           # negative = actual is BELOW type curve
    cum_actual_bbl: float
    cum_type_curve_bbl: float
    deferred_bbl: float            # type-curve cum - actual cum (positive = production left behind)
    deferred_pct: float
    deferred_value_usd: float      # deferred_bbl * net margin (price - opex)


def _exponential(t, qi, di):
    return qi * np.exp(-di * t)


def _harmonic(t, qi, di):
    return qi / (1 + di * t)


def _hyperbolic(t, qi, di, b):
    return qi / np.power(1 + b * di * t, 1 / b)


def _curve(model: DeclineModel, qi: float, di: float, b: float, t: np.ndarray) -> np.ndarray:
    """Evaluate the fitted Arps model at times t (pure numpy — no scipy)."""
    if model == "exponential":
        return _exponential(t, qi, di)
    if model == "harmonic":
        return _harmonic(t, qi, di)
    return _hyperbolic(t, qi, di, max(b, 1e-6))


def fit_decline(
    days: np.ndarray,
    rates: np.ndarray,
    model: DeclineModel = "hyperbolic",
) -> DeclineFit:
    """Fit an Arps decline model to rate-time data."""
    days = np.asarray(days, dtype=float)
    rates = np.asarray(rates, dtype=float)
    mask = (rates > 0) & np.isfinite(rates)
    days, rates = days[mask], rates[mask]

    if len(days) < 5:
        raise ValueError("Need at least 5 valid production points to fit decline.")

    qi_guess = rates[0]

    if model == "exponential":
        popt, _ = curve_fit(_exponential, days, rates, p0=[qi_guess, 0.001], maxfev=5000)
        qi, di, b = popt[0], popt[1], 0.0
        predicted = _exponential(days, qi, di)
    elif model == "harmonic":
        popt, _ = curve_fit(_harmonic, days, rates, p0=[qi_guess, 0.001], maxfev=5000)
        qi, di, b = popt[0], popt[1], 1.0
        predicted = _harmonic(days, qi, di)
    else:
        popt, _ = curve_fit(
            _hyperbolic, days, rates,
            p0=[qi_guess, 0.001, 0.5],
            bounds=([0, 0, 0], [np.inf, 1, 2]),
            maxfev=5000,
        )
        qi, di, b = popt
        predicted = _hyperbolic(days, qi, di, b)

    ss_res = np.sum((rates - predicted) ** 2)
    ss_tot = np.sum((rates - rates.mean()) ** 2)
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    residual = (rates[-1] - predicted[-1]) / predicted[-1] * 100 if predicted[-1] > 0 else 0

    return DeclineFit(
        model=model,
        qi=float(qi),
        di=float(di),
        b=float(b),
        r_squared=float(r_squared),
        last_actual=float(rates[-1]),
        last_predicted=float(predicted[-1]),
        fit_residual_pct=float(residual),
    )


def analyze_type_curve(
    days: np.ndarray,
    rates: np.ndarray,
    model: DeclineModel = "hyperbolic",
    established_frac: float = 0.4,
    price_per_bbl: float = 65.0,
    opex_per_bbl: float = 12.0,
) -> TypeCurveResult:
    """Build a type curve from the well's ESTABLISHED decline and measure how far
    actual production has fallen below it (rate deviation today + cumulative deferred).

    Method — iterative degraded-tail trimming (robust to noise):
      1. Fit the full history.
      2. If the last kept point sits materially below its own fit, the well has departed
         from its established decline there — peel that point off and refit. Repeat.
      3. The remaining (clean) early window is the type curve; extrapolate it forward.

    This fixes the failure mode of a fixed early-window fit: extrapolating an Arps fit
    from a handful of noisy early points over hundreds of days is wildly unstable (a
    HEALTHY well can read tens of percent above or below "type curve" purely from fit
    noise). Trimming only a genuinely degraded tail means a healthy, on-curve well keeps
    all its points → type curve == full fit → deviation ≈ 0, while a rolled-over well
    still exposes its real deferred production. `established_frac` is retained only as the
    floor on how much history the clean window must keep.
    """
    days = np.asarray(days, dtype=float)
    rates = np.asarray(rates, dtype=float)
    mask = (rates > 0) & np.isfinite(rates)
    days, rates = days[mask], rates[mask]
    if len(days) < 6:
        raise ValueError("Need at least 6 valid production points for type-curve analysis.")

    # A point is "below its established decline" if it falls >12% under the trend of the
    # points BEFORE it — safely outside typical multiplicative noise (~5%), so healthy wells
    # don't trim. Testing each tail point against a fit that EXCLUDES it (leave-one-out) is
    # the key: a fit that includes the point would just bend down to absorb the degradation
    # (b collapses to chase the tail) and never flag the break.
    below_tol = 0.88
    min_keep = max(6, int(round(len(days) * established_frac)))

    keep = len(days)
    while keep > min_keep:
        fit_excl = fit_decline(days[: keep - 1], rates[: keep - 1], model=model)
        pred_last = float(_curve(model, fit_excl.qi, fit_excl.di, fit_excl.b, days[keep - 1: keep])[0])
        if pred_last > 0 and rates[keep - 1] < below_tol * pred_last:
            keep -= 1   # this tail point has departed from the established trend; drop it
        else:
            break

    fit = fit_decline(days[:keep], rates[:keep], model=model)
    n_est = keep
    tc = _curve(model, fit.qi, fit.di, fit.b, days)
    tc_last = float(tc[-1])
    deviation = (rates[-1] - tc_last) / tc_last * 100 if tc_last > 0 else 0.0

    cum_actual = float(_trapezoid(rates, days))
    cum_tc = float(_trapezoid(tc, days))
    deferred = cum_tc - cum_actual
    deferred_pct = (deferred / cum_tc * 100) if cum_tc > 0 else 0.0
    deferred_value = max(0.0, deferred) * (price_per_bbl - opex_per_bbl)

    return TypeCurveResult(
        model=model,
        established_days=int(n_est),
        qi=float(fit.qi),
        di=float(fit.di),
        b=float(fit.b),
        last_actual=float(rates[-1]),
        type_curve_at_last=tc_last,
        deviation_pct=float(deviation),
        cum_actual_bbl=cum_actual,
        cum_type_curve_bbl=cum_tc,
        deferred_bbl=float(deferred),
        deferred_pct=float(deferred_pct),
        deferred_value_usd=float(deferred_value),
    )


def project_eur(
    fit: DeclineFit,
    economic_limit_bopd: float = 5.0,
    horizon_days: int = 365 * 30,
    from_day: float = 0.0,
) -> float:
    """Remaining recovery to economic limit (bbl), integrated FORWARD from ``from_day``.

    The Arps fit is parameterised in days-since-first-production, so ``fit.qi`` is the rate
    at t=0 (the START of production history). Integrating from t=1 therefore re-counts every
    barrel already produced during the history window — a ~2-3x overstatement of *remaining*
    reserves. To get remaining EUR, pass ``from_day`` = the LAST observed production day
    (``days[-1]``); the curve is then integrated from there to the economic limit.

    ``from_day=0`` (the default) keeps the legacy "total EUR from first production" behaviour
    for any caller that genuinely wants cumulative-from-start, but every *remaining*-reserves
    caller in this app passes the last history day.
    """
    start = max(int(round(from_day)), 1)
    t = np.arange(start, horizon_days)
    if fit.model == "exponential":
        q = _exponential(t, fit.qi, fit.di)
    elif fit.model == "harmonic":
        q = _harmonic(t, fit.qi, fit.di)
    else:
        q = _hyperbolic(t, fit.qi, fit.di, fit.b)
    above_limit = q[q >= economic_limit_bopd]
    return float(above_limit.sum())


@dataclass
class WaterGasTrend:
    """Water-cut and GOR levels + trends over the production history.

    Many interventions are driven by the water and gas streams, not the oil rate:
    a rising water cut shifts the economic limit and the right-size lift target; a
    rising GOR flags gas interference / liquid-loading risk on artificial lift.
    """
    latest_water_cut_pct: float
    water_cut_slope_pct_per_yr: float     # +ve = watering out
    latest_gor_scf_per_bbl: float
    gor_slope_scf_per_bbl_per_yr: float   # +ve = gassing up
    water_cut_trend: str                  # "rising" | "flat" | "falling"
    gor_trend: str
    flags: list[str]


def _slope_per_year(days: np.ndarray, values: np.ndarray) -> float:
    """Least-squares slope of values vs time, returned per *year* (days are in days)."""
    if len(days) < 2:
        return 0.0
    m = np.isfinite(values)
    if m.sum() < 2:
        return 0.0
    slope_per_day = float(np.polyfit(days[m], values[m], 1)[0])
    return slope_per_day * 365.0


def analyze_water_gas_trends(history: list[dict]) -> WaterGasTrend:
    """Compute water-cut and GOR levels and trends from a production history.

    Each row needs oil_bopd, water_bwpd, gas_mcfd. Water cut = water/(oil+water);
    GOR = gas (scf) / oil (bbl) with gas in mcf -> *1000.
    """
    days = np.array([r.get("day", 0) for r in history], dtype=float)
    oil = np.array([r.get("oil_bopd", 0.0) for r in history], dtype=float)
    water = np.array([r.get("water_bwpd", 0.0) for r in history], dtype=float)
    gas = np.array([r.get("gas_mcfd", 0.0) for r in history], dtype=float)

    liquid = oil + water
    wc = np.where(liquid > 0, water / liquid * 100.0, 0.0)
    gor = np.where(oil > 0, gas * 1000.0 / oil, 0.0)

    wc_slope = _slope_per_year(days, wc)
    gor_slope = _slope_per_year(days, gor)

    def _trend(slope: float, eps: float) -> str:
        return "rising" if slope > eps else "falling" if slope < -eps else "flat"

    flags: list[str] = []
    latest_wc = float(wc[-1]) if len(wc) else 0.0
    latest_gor = float(gor[-1]) if len(gor) else 0.0
    if latest_wc > 90:
        flags.append(f"HIGH WATER CUT ({latest_wc:.0f}%) — near economic limit, SWD-cost sensitive")
    # 8%/yr threshold: a few %/yr of water-cut creep is normal maturation, not a problem
    # signal. Only flag a genuinely steep climb so healthy wells stay clean.
    if wc_slope > 8:
        flags.append(f"WATER CUT RISING (+{wc_slope:.1f}%/yr) — re-check economic limit & lift sizing")
    if gor_slope > 200:
        flags.append(f"GOR RISING (+{gor_slope:.0f} scf/bbl/yr) — gas-interference / loading risk")

    return WaterGasTrend(
        latest_water_cut_pct=latest_wc,
        water_cut_slope_pct_per_yr=wc_slope,
        latest_gor_scf_per_bbl=latest_gor,
        gor_slope_scf_per_bbl_per_yr=gor_slope,
        water_cut_trend=_trend(wc_slope, 1.0),
        gor_trend=_trend(gor_slope, 50.0),
        flags=flags,
    )
