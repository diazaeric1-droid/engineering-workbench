"""Representative-vs-anomalous production-data classification (data quality FOR
decline / type-curve trending).

Before fitting a decline or type curve you first decide which historical points are
*representative* of the well's real producing behavior and which to EXCLUDE so they
don't bias the fit: shut-in / zero-rate days, metering dropouts, and gross outliers
versus a robust decline-aware trend. (This is the cleaning step WellProductivity.jl
describes as "anomaly detection to filter non-representative data points, e.g.
production shutdowns" — reimplemented here in Python.)

ADDITIVE & EVAL-SAFE: this module is a *diagnostic* only. It does NOT touch
``fit_decline`` / ``analyze_type_curve`` or the agent's recommendation logic, and the
default fit the blind-holdout eval runs through is unchanged. The UI may optionally
offer a "fit on representative points only" overlay, but the trusted default fit stays
exactly as-is.

Deterministic, dependency-light (numpy). Reuses the Arps decline math in
``decline_curve`` for the decline-aware trend rather than re-deriving it, and uses the
standard median/MAD robust z-score for the outlier test.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .decline_curve import _curve, fit_decline

# Tunables (deterministic). A point is non-representative if ANY of these fire.
ZERO_RATE_EPS = 1e-6      # rate at/below this is a zero / shut-in day
ROBUST_Z_OUTLIER = 4.0    # |robust z| beyond this vs the decline-aware trend → outlier
MIN_POINTS = 5            # below this we don't attempt a fit-based outlier test

# Reason codes (stable strings; a point may carry several, joined by "; ").
R_ZERO = "zero_or_shutin"     # zero / near-zero rate or missing rate (shut-in / no data)
R_OUTLIER = "robust_outlier"  # gross outlier vs a robust decline-aware trend


@dataclass
class RepresentativeResult:
    """Per-point representative classification over a well's oil-rate history."""
    days: np.ndarray              # day index per point (input order)
    rates: np.ndarray             # oil_bopd per point (NaN preserved)
    representative: np.ndarray    # bool mask, True = keep for trending
    reasons: list[str]            # "" when representative, else "; "-joined reason codes
    n_points: int
    n_representative: int
    n_excluded: int
    representative_pct: float
    reason_counts: dict[str, int] = field(default_factory=dict)

    @property
    def excluded_mask(self) -> np.ndarray:
        return ~self.representative


def _robust_z_last(values: np.ndarray) -> float:
    """Signed robust z-score of the LAST element vs the preceding ones, using
    median + MAD (0.6745·(x−med)/MAD). MAD==0 falls back to std; a constant series
    has no outlier (returns 0). The standard robust statistic — same formulation the
    sibling Digest app uses — kept local so this package has no cross-repo import."""
    y = np.asarray(values, dtype=float)
    y = y[np.isfinite(y)]
    if len(y) < 3:
        return 0.0
    point = float(y[-1])
    baseline = y[:-1]
    med = float(np.median(baseline))
    mad = float(np.median(np.abs(baseline - med)))
    if mad <= 1e-9:
        std = float(np.std(baseline))
        return 0.0 if std <= 1e-9 else (point - med) / std
    return 0.6745 * (point - med) / mad


def _decline_aware_residuals(days: np.ndarray, rates: np.ndarray) -> np.ndarray | None:
    """Per-point residual ratio (actual / fitted) against an Arps fit, so the outlier
    test is relative to the DECLINE-expected level (a steep healthy decliner shouldn't
    read its low late points as outliers). Reuses ``fit_decline`` + ``_curve``.

    Returns a residual-ratio array aligned to the input, or ``None`` if a fit isn't
    feasible (caller then falls back to a flat robust z on the rates)."""
    finite = np.isfinite(rates) & (rates > 0)
    if finite.sum() < MIN_POINTS:
        return None
    try:
        fit = fit_decline(days[finite], rates[finite], model="hyperbolic")
        pred = _curve("hyperbolic", fit.qi, fit.di, fit.b, days)
    except Exception:
        return None
    with np.errstate(divide="ignore", invalid="ignore"):
        resid = np.where((pred > 0) & np.isfinite(rates), rates / pred, np.nan)
    return resid


def classify_representative(history: list[dict], rate_key: str = "oil_bopd") -> RepresentativeResult:
    """Classify each point of a WellFile ``production_history`` as representative vs.
    non-representative for decline / type-curve trending.

    Parameters
    ----------
    history
        ``WellFile.production_history`` — a list of row dicts each with a ``day`` and an
        oil-rate key (default ``oil_bopd``).
    rate_key
        Rate field to classify on (default ``"oil_bopd"``).

    Returns
    -------
    RepresentativeResult
        Per-point ``representative`` mask + ``reasons`` and a small summary. A flagged
        point is one to EXCLUDE from a fit (shut-in / zero / missing rate, or a gross
        outlier vs the robust decline-aware trend).

    Deterministic. Wells with < ``MIN_POINTS`` points still classify zero/missing points,
    but skip the fit-based outlier test (too little data to fit a trend)."""
    days = np.array([row.get("day", i) for i, row in enumerate(history)], dtype=float)
    rates = np.array([row.get(rate_key, np.nan) for row in history], dtype=float)
    n = len(rates)

    resid = _decline_aware_residuals(days, rates)
    z_basis = resid if resid is not None else rates.astype(float)

    representative = np.ones(n, dtype=bool)
    reasons: list[str] = [""] * n
    for i in range(n):
        r = rates[i]
        pt: list[str] = []
        if not np.isfinite(r) or r <= ZERO_RATE_EPS:
            pt.append(R_ZERO)
        else:
            this_val = z_basis[i]
            others = z_basis[:i][np.isfinite(z_basis[:i])]
            if np.isfinite(this_val) and len(others) >= 2:
                rz = _robust_z_last(np.append(others, this_val))
                if abs(rz) >= ROBUST_Z_OUTLIER:
                    pt.append(R_OUTLIER)
        if pt:
            representative[i] = False
            reasons[i] = "; ".join(pt)

    n_excl = int((~representative).sum())
    reason_counts: dict[str, int] = {}
    for rs in reasons:
        for code in (c for c in rs.split("; ") if c):
            reason_counts[code] = reason_counts.get(code, 0) + 1

    return RepresentativeResult(
        days=days,
        rates=rates,
        representative=representative,
        reasons=reasons,
        n_points=n,
        n_representative=n - n_excl,
        n_excluded=n_excl,
        representative_pct=round((n - n_excl) / n * 100.0, 1) if n else 100.0,
        reason_counts=reason_counts,
    )
