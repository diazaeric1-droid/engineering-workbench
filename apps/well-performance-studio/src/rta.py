"""Rate-transient analysis via bluebonnet's physics-based forecaster.

Fits a measured (or synthetic) production stream to bluebonnet's scaling solution and
forecasts EUR. The recovery-factor curve ``rf(t_scaled)`` comes from the same
``SinglePhaseReservoir`` solve as :mod:`src.curves`; bluebonnet's
:class:`~bluebonnet.forecast.ForecasterOnePhase` then regresses the two scaling
constants against the observed cumulative:

    Q(t) = M · rf(t / tau)

* ``M``   : resource in place (Mscf) — set by the asymptote of the cumulative.
* ``tau`` : time-to-BDF (years)       — set by the curvature / transient length.

``ForecasterOnePhase.fit(time_years, cum)`` runs a bounded least-squares
(``scipy.optimize.curve_fit``) and stores the fitted ``M_`` and ``tau_`` on the
instance; ``forecast_cum(time_years)`` then evaluates the model forward.

Deterministic given its inputs (synthetic series uses a fixed seed). No network.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from bluebonnet.forecast import Bounds, ForecasterOnePhase

from .curves import CurveInputs, _recovery_interpolator

# Loose but physical bounds for the regression (Mscf, years).
_DEFAULT_BOUNDS = Bounds(M=(1.0e2, 1.0e8), tau=(0.05, 50.0))


@dataclass
class RTAResult:
    """Outcome of an RTA fit."""

    m_mscf: float  # fitted resource in place (Mscf)
    tau_years: float  # fitted time-to-BDF (years)
    eur_mmscf: float  # forecast EUR over the horizon (MMscf)
    rmse_mmscf: float  # cumulative-fit RMSE (MMscf)
    history: pd.DataFrame  # observed: years, cum_mmscf
    forecast: pd.DataFrame  # modeled: years, cum_mmscf, rate_mscf_d


def synthetic_series(
    inp: CurveInputs | None = None,
    *,
    m_mscf: float = 3.2e6,
    tau_years: float = 2.4,
    n_days: int = 720,
    noise: float = 0.08,
    seed: int = 7,
) -> pd.DataFrame:
    """A built-in synthetic daily rate series (date, rate_mscf_d) for the demo.

    Generated from the physics curve at a known ``(M, tau)`` plus log-normal-ish
    multiplicative noise, so an honest RTA fit should recover the truth closely.
    """
    inp = inp or CurveInputs()
    rf, t_max = _recovery_interpolator(inp)
    rng = np.random.default_rng(seed)
    days = np.arange(1, int(n_days) + 1)
    years = days / 365.25
    cum_clean = float(m_mscf) * np.asarray(
        rf(np.minimum(years / max(tau_years, 1e-6), t_max)), dtype=float
    )
    rate_clean = np.diff(cum_clean, prepend=0.0)
    rate = np.clip(rate_clean * (1.0 + rng.normal(0.0, noise, size=rate_clean.size)), 0.0, None)
    dates = pd.date_range("2023-01-01", periods=int(n_days), freq="D")
    return pd.DataFrame({"date": dates, "rate_mscf_d": rate})


def parse_rate_csv(file) -> pd.DataFrame:
    """Parse an uploaded CSV into a clean (date, rate_mscf_d) frame.

    Accepts flexible column names: a date-like column (``date``/``time``/``day``…) and
    a rate-like column (``rate``/``q``/``gas``/``mscf``…). Falls back to the first two
    columns. Raises ``ValueError`` on unrecoverable input.
    """
    df = pd.read_csv(file)
    if df.shape[1] < 2:
        raise ValueError("CSV needs at least two columns (date, rate).")
    cols = {c.lower().strip(): c for c in df.columns}

    def _find(keys):
        for k in keys:
            for low, orig in cols.items():
                if k in low:
                    return orig
        return None

    date_col = _find(("date", "time", "day", "month", "period"))
    rate_col = _find(("rate", "q_", "qg", "gas", "mscf", "prod", "oil", "q "))
    if rate_col is None:
        # first numeric column that isn't the date
        for orig in df.columns:
            if orig == date_col:
                continue
            if pd.api.types.is_numeric_dtype(df[orig]):
                rate_col = orig
                break
    if date_col is None:
        date_col = df.columns[0]
    if rate_col is None:
        rate_col = df.columns[1]

    out = pd.DataFrame()
    out["date"] = pd.to_datetime(df[date_col], errors="coerce")
    out["rate_mscf_d"] = pd.to_numeric(df[rate_col], errors="coerce")
    out = out.dropna().reset_index(drop=True)
    if len(out) < 5:
        raise ValueError("Need at least 5 valid (date, rate) rows after cleaning.")
    return out.sort_values("date").reset_index(drop=True)


def fit_rta(
    series: pd.DataFrame,
    inp: CurveInputs | None = None,
    *,
    horizon_years: float = 15.0,
    bounds: Bounds | None = None,
) -> RTAResult:
    """Fit bluebonnet's scaling forecaster to a (date, rate_mscf_d) series.

    Returns an :class:`RTAResult` with the fitted ``M``/``tau``, forecast EUR, the fit
    RMSE, and history/forecast frames for plotting.
    """
    inp = inp or CurveInputs()
    if "date" not in series or "rate_mscf_d" not in series:
        raise ValueError("series must have 'date' and 'rate_mscf_d' columns.")
    s = series.dropna(subset=["date", "rate_mscf_d"]).sort_values("date")
    t0 = s["date"].iloc[0]
    years = (s["date"] - t0).dt.total_seconds().to_numpy() / (365.25 * 86400.0)
    # ensure strictly increasing, positive time on production (start at day ~1)
    years = years - years.min() + (1.0 / 365.25)
    rate = s["rate_mscf_d"].to_numpy(dtype=float)
    # cumulative from rate over the (uneven-tolerant) time vector
    dt_days = np.gradient(years * 365.25)
    cum_mscf = np.cumsum(np.clip(rate, 0.0, None) * dt_days)

    rf, _t_max = _recovery_interpolator(inp)
    forecaster = ForecasterOnePhase(rf, bounds or _DEFAULT_BOUNDS)
    forecaster.fit(years, cum_mscf)
    m_fit = float(forecaster.M_)
    tau_fit = float(forecaster.tau_)

    # fit quality on the history window
    cum_model_hist = forecaster.forecast_cum(years)
    rmse = float(np.sqrt(np.mean((cum_model_hist - cum_mscf) ** 2))) / 1.0e3  # MMscf

    # forward forecast
    fut_days = np.arange(1, int(365.25 * horizon_years) + 1)
    fut_years = fut_days / 365.25
    cum_fore = np.asarray(forecaster.forecast_cum(fut_years), dtype=float)
    rate_fore = np.clip(np.gradient(cum_fore, fut_days), 0.0, None)

    history = pd.DataFrame({"years": years, "cum_mmscf": cum_mscf / 1.0e3})
    forecast = pd.DataFrame(
        {
            "years": fut_years,
            "cum_mmscf": cum_fore / 1.0e3,
            "rate_mscf_d": rate_fore,
        }
    )
    return RTAResult(
        m_mscf=m_fit,
        tau_years=tau_fit,
        eur_mmscf=float(cum_fore[-1] / 1.0e3),
        rmse_mmscf=rmse,
        history=history,
        forecast=forecast,
    )
