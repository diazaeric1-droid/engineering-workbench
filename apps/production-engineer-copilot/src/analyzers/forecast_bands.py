"""Monte-Carlo decline-forecast uncertainty bands (P10/P50/P90 rate + EUR).

ADDITIVE forecast/visualization layer built on the **prodpy** package
(jshiriyev/production-data-analysis, MIT) — its `prodpy.decline.Arps` Arps
fitter (linearized seed + non-linear `curve_fit`) and analytic rate/cumulative
models. This module does NOT touch the existing `decline_curve` analyzer
(`fit_decline` / `analyze_type_curve`), which the blind-holdout eval depends on.

Method
------
1. Fit the rate-time history with prodpy's `Arps.fit` → a `FitResult` carrying
   the best-fit (qi, di) AND their fitted standard errors (qi_error, di_error)
   from the non-linear covariance.
2. Monte-Carlo: draw ``n`` (qi, di) parameter pairs from the fitted sampling
   distribution (Student-t scaled by the fitted std errors, the same t-interval
   basis prodpy's own ``Arps.simulate`` uses), seeded for determinism.
3. Evaluate each sampled curve's rate and cumulative through prodpy's analytic
   model over the forecast horizon, then take per-time percentiles across the
   ensemble → a P10/P50/P90 rate fan and P10/P50/P90 EUR (history cum + forecast).

Convention
----------
Petroleum reserves convention: **P10 = high / optimistic, P90 = low /
conservative**, so at any forecast time ``P10 >= P50 >= P90`` for the rate and
likewise for EUR. (P10 means "10% chance of exceeding" → the larger number.)

Determinism: a fixed ``seed`` (default 42) → identical bands every run. No
network, no API key.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import threading
from dataclasses import dataclass

import numpy as np

__all__ = ["ForecastBands", "decline_forecast_bands", "prodpy_decline"]


# ---------------------------------------------------------------------------
# prodpy.decline loader
# ---------------------------------------------------------------------------
# prodpy's top-level ``__init__`` eagerly imports ``prodpy.onepage`` (needs
# matplotlib) and ``prodpy._allocate`` (needs lasio) — heavy optional deps we do
# NOT want to pull into this Streamlit app. The ``prodpy.decline`` SUBPACKAGE,
# however, only needs numpy + scipy (already deps). So we load the four decline
# leaf modules directly from prodpy's install dir, registering lightweight parent
# package objects in ``sys.modules`` so prodpy's own intra-package imports
# (``from prodpy.decline import Hyperbolic``) still resolve — all WITHOUT ever
# executing the heavy ``prodpy/__init__.py``.
_LOCK = threading.Lock()
_DECLINE = None  # cached prodpy.decline namespace once loaded


def prodpy_decline():
    """Return the real ``prodpy.decline`` namespace (Arps, FitResult, models).

    Loaded lazily and cached. Raises ImportError if prodpy isn't installed (the
    caller in the app guards this with try/except and hides the section).
    """
    global _DECLINE
    if _DECLINE is not None:
        return _DECLINE
    with _LOCK:
        if _DECLINE is not None:
            return _DECLINE

        # If the full package already imported cleanly (e.g. matplotlib present),
        # just use it — no need for the direct-load path.
        if "prodpy.decline" in sys.modules and getattr(
            sys.modules["prodpy.decline"], "Arps", None
        ) is not None:
            _DECLINE = sys.modules["prodpy.decline"]
            return _DECLINE

        spec = importlib.util.find_spec("prodpy")
        if spec is None or not spec.submodule_search_locations:
            raise ImportError("prodpy is not installed")
        pkg_dir = list(spec.submodule_search_locations)[0]
        dec_dir = os.path.join(pkg_dir, "decline")
        if not os.path.isdir(dec_dir):
            raise ImportError("prodpy.decline not found in prodpy install")

        import types

        # Register lightweight parent packages (no __init__ executed). Use
        # setdefault so we never clobber a real, already-imported prodpy.
        prodpy_pkg = sys.modules.get("prodpy")
        if prodpy_pkg is None or not hasattr(prodpy_pkg, "__path__"):
            prodpy_pkg = types.ModuleType("prodpy")
            prodpy_pkg.__path__ = [pkg_dir]
            sys.modules["prodpy"] = prodpy_pkg
        dec_pkg = types.ModuleType("prodpy.decline")
        dec_pkg.__path__ = [dec_dir]
        sys.modules["prodpy.decline"] = dec_pkg

        def _load(modname: str, filename: str):
            mspec = importlib.util.spec_from_file_location(
                modname, os.path.join(dec_dir, filename)
            )
            mod = importlib.util.module_from_spec(mspec)
            sys.modules[modname] = mod
            mspec.loader.exec_module(mod)
            return mod

        # Load the models FIRST and expose them on the package so _arps's
        # ``from prodpy.decline import Exponential/Hyperbolic/Harmonic`` resolves.
        exp = _load("prodpy.decline._exponential", "_exponential.py")
        hyp = _load("prodpy.decline._hyperbolic", "_hyperbolic.py")
        har = _load("prodpy.decline._harmonic", "_harmonic.py")
        dec_pkg.Exponential = exp.Exponential
        dec_pkg.Hyperbolic = hyp.Hyperbolic
        dec_pkg.Harmonic = har.Harmonic
        arps = _load("prodpy.decline._arps", "_arps.py")
        dec_pkg.Arps = arps.Arps
        dec_pkg.FitResult = arps.FitResult

        _DECLINE = dec_pkg
        return _DECLINE


# ---------------------------------------------------------------------------
# result container
# ---------------------------------------------------------------------------
@dataclass
class ForecastBands:
    """P10/P50/P90 Monte-Carlo decline forecast over a horizon.

    Time axes are in *days on production* (continuing from the last history day).
    Rates are in the input rate unit (BOPD). EURs are cumulative volume (bbl):
    history cumulative + the forecast cumulative to the end of the horizon.
    """
    model: str
    n_samples: int                      # MC draws actually used (post-filter)
    days: np.ndarray                    # forecast time axis (len H)
    p10_rate: np.ndarray               # high / optimistic rate fan (len H)
    p50_rate: np.ndarray               # median rate fan
    p90_rate: np.ndarray               # low / conservative rate fan
    eur_p10: float                      # high / optimistic EUR (bbl)
    eur_p50: float                      # median EUR (bbl)
    eur_p90: float                      # low / conservative EUR (bbl)
    qi: float                           # deterministic best-fit qi
    di: float                           # deterministic best-fit di (1/day)
    b: float                            # Arps exponent used
    r_squared: float                    # prodpy non-linear fit R^2
    cum_history_bbl: float              # trapezoidal cum of the supplied history

    def as_eur_dict(self) -> dict:
        """EUR P10/P50/P90 as a plain dict (handy for st.metric rows)."""
        return {"p10": self.eur_p10, "p50": self.eur_p50, "p90": self.eur_p90}


# numpy>=2 renamed trapz -> trapezoid; resolve without touching the removed name.
try:
    _trapezoid = np.trapezoid          # numpy >= 2.0
except AttributeError:                 # pragma: no cover - very old numpy
    _trapezoid = np.trapz


def _percentiles_high_to_low(samples_2d: np.ndarray):
    """Per-column (P10, P50, P90) with the petroleum convention P10 >= P50 >= P90.

    ``samples_2d`` is (n_draws, n_times). numpy's ``percentile(.., 90)`` is the
    statistical upper value; we MAP statistical-90th -> P10 (optimistic) and
    statistical-10th -> P90 (conservative) so the returned p10 >= p50 >= p90.
    """
    p10 = np.nanpercentile(samples_2d, 90, axis=0)   # optimistic
    p50 = np.nanpercentile(samples_2d, 50, axis=0)
    p90 = np.nanpercentile(samples_2d, 10, axis=0)   # conservative
    # Guard against tiny float crossings from interpolation/NaNs so the ordering
    # invariant the UI + tests rely on always holds.
    p50 = np.minimum(p50, p10)
    p90 = np.minimum(p90, p50)
    return p10, p50, p90


def decline_forecast_bands(
    days,
    rates,
    horizon_days: float = 365 * 5,
    n: int = 500,
    *,
    seed: int = 42,
    model: str = "hyperbolic",
    step_days: float = 30.0,
    econ_limit_bopd: float = 0.0,
) -> ForecastBands:
    """Monte-Carlo P10/P50/P90 decline forecast (rate fan + EUR) via prodpy.

    Parameters
    ----------
    days, rates : array-like
        Rate-time history (days on production, BOPD). Non-positive / non-finite
        points are dropped (same hygiene as the decline analyzer).
    horizon_days : float
        How far past the last history day to forecast (default 5 years).
    n : int
        Monte-Carlo parameter draws (default 500). Deterministic given ``seed``.
    seed : int
        RNG seed → reproducible bands.
    model : {"hyperbolic","exponential","harmonic"}
        Arps model handed to prodpy.
    step_days : float
        Forecast sampling step in days (default monthly).
    econ_limit_bopd : float
        Optional economic-limit rate; the forecast is truncated where the P50
        sampled rate drops below it (0 = forecast the full horizon).

    Returns
    -------
    ForecastBands

    Raises
    ------
    ValueError
        Fewer than 5 valid points (mirrors the app's insufficient-data guard).
    ImportError / RuntimeError
        If prodpy can't be loaded or the fit fails (the app guards both).
    """
    days = np.asarray(days, dtype=float)
    rates = np.asarray(rates, dtype=float)
    mask = (rates > 0) & np.isfinite(rates) & np.isfinite(days)
    days, rates = days[mask], rates[mask]
    if len(days) < 5:
        raise ValueError("Need at least 5 valid production points to forecast.")

    dec = prodpy_decline()
    Arps = dec.Arps

    # Shift to t0 = 0 for a well-conditioned fit, then map back when forecasting.
    t0 = float(days[0])
    t_hist = days - t0

    b_by_model = {"exponential": 0.0, "hyperbolic": 0.5, "harmonic": 1.0}
    b = b_by_model.get(model, 0.5)

    arps = Arps(di=0.01, qi=float(rates[0]), mode=model)
    fit = arps.fit(t_hist, rates)   # prodpy FitResult: qi, di, qi_error, di_error, n, r2

    qi_hat, di_hat = float(fit.qi), float(fit.di)
    qi_err = float(fit.qi_error) if np.isfinite(fit.qi_error) else 0.0
    di_err = float(fit.di_error) if np.isfinite(fit.di_error) else 0.0
    dof = max(int(fit.n) - 2, 1)

    # --- Monte-Carlo parameter ensemble -----------------------------------
    # Draw from the fitted Student-t sampling distribution of each parameter
    # (the same t-interval basis prodpy's Arps.simulate uses for single
    # percentiles). Seeded for determinism; clipped to keep qi/di physical.
    rng = np.random.default_rng(seed)
    n = max(int(n), 50)
    t_qi = rng.standard_t(dof, size=n)
    t_di = rng.standard_t(dof, size=n)
    qi_draws = qi_hat + t_qi * qi_err
    di_draws = di_hat + t_di * di_err
    # Keep parameters in the physical/positive domain prodpy's models require.
    qi_draws = np.clip(qi_draws, 1e-6, None)
    di_draws = np.clip(di_draws, 1e-9, None)
    # Always include the deterministic best fit as one ensemble member so P50 is
    # anchored to the actual fit even at small n.
    qi_draws[0], di_draws[0] = qi_hat, di_hat

    # --- forecast time axis (continues from the last history day) ----------
    last_t = float(t_hist[-1])
    step = max(float(step_days), 1.0)
    horizon = float(max(horizon_days, step))
    fc_t = np.arange(last_t, last_t + horizon + step, step, dtype=float)
    if fc_t.size < 2:
        fc_t = np.array([last_t, last_t + step], dtype=float)

    # Cumulative of the supplied history (trapezoid) → the EUR floor.
    cum_hist = float(_trapezoid(rates, days)) if len(days) > 1 else 0.0

    # Evaluate every sampled curve's rate + incremental cumulative over the
    # horizon. Cumulative forecast volume = N(t) - N(last_t) so EUR =
    # history cum + forecast-from-now cum (no double count of history).
    rate_samples = np.empty((n, fc_t.size), dtype=float)
    eur_samples = np.empty(n, dtype=float)
    base_model = arps.model  # underlying prodpy model instance (carries b)
    for i in range(n):
        m = base_model.with_params(di=float(di_draws[i]), qi=float(qi_draws[i]))
        q = np.asarray(m.q(fc_t), dtype=float)
        rate_samples[i, :] = q
        N = np.asarray(m.N(fc_t), dtype=float)
        fc_cum = float(N[-1] - N[0])
        if not np.isfinite(fc_cum) or fc_cum < 0:
            fc_cum = 0.0
        eur_samples[i] = cum_hist + fc_cum

    rate_samples = np.where(np.isfinite(rate_samples), rate_samples, np.nan)

    p10_rate, p50_rate, p90_rate = _percentiles_high_to_low(rate_samples)

    # Optional economic-limit truncation: cut the fan where the MEDIAN drops
    # below the limit (keeps all three bands on the same time axis).
    fc_days = fc_t + t0
    if econ_limit_bopd and econ_limit_bopd > 0:
        keep = p50_rate >= econ_limit_bopd
        if keep.any():
            # keep through the first sub-limit point for a clean visual endpoint
            last_idx = int(np.argmax(np.cumsum(keep) == keep.sum()))
            cut = min(last_idx + 1, fc_t.size)
            cut = max(cut, 2)
            fc_days = fc_days[:cut]
            p10_rate, p50_rate, p90_rate = p10_rate[:cut], p50_rate[:cut], p90_rate[:cut]

    eur_samples = eur_samples[np.isfinite(eur_samples)]
    if eur_samples.size == 0:
        eur_p10 = eur_p50 = eur_p90 = cum_hist
    else:
        eur_p10 = float(np.percentile(eur_samples, 90))   # optimistic
        eur_p50 = float(np.percentile(eur_samples, 50))
        eur_p90 = float(np.percentile(eur_samples, 10))   # conservative
        eur_p50 = min(eur_p50, eur_p10)
        eur_p90 = min(eur_p90, eur_p50)

    return ForecastBands(
        model=model,
        n_samples=int(n),
        days=np.asarray(fc_days, dtype=float),
        p10_rate=np.asarray(p10_rate, dtype=float),
        p50_rate=np.asarray(p50_rate, dtype=float),
        p90_rate=np.asarray(p90_rate, dtype=float),
        eur_p10=eur_p10,
        eur_p50=eur_p50,
        eur_p90=eur_p90,
        qi=qi_hat,
        di=di_hat,
        b=float(b),
        r_squared=float(fit.r2) if np.isfinite(fit.r2) else 0.0,
        cum_history_bbl=cum_hist,
    )
