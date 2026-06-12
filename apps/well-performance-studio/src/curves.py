"""Physics-based production curve via bluebonnet's scaling-solution simulator.

Forward model for an unconventional (fracture-dominated, transient-linear → BDF) gas
well. The workflow is bluebonnet's canonical scaling solution:

1. ``bluebonnet.fluids.build_pvt_gas`` → a gas PVT table (z, viscosity,
   compressibility, pseudopressure vs pressure).
2. ``bluebonnet.flow.FlowProperties`` wraps that table (initial pressure ``p_i``).
3. ``bluebonnet.flow.SinglePhaseReservoir(nx, p_frac, p_i, fluid).simulate(t)`` solves
   the 1-D pseudopressure-diffusion PDE on scaled time and yields a *recovery-factor*
   curve ``rf(t_scaled)`` via ``recovery_factor_interpolator()``.

The scaling solution is dimensionless: a single physics curve is converted to a real
well by two scaling constants —

* ``M``   : resource-in-place / movable gas (Mscf) — scales recovery → cumulative.
* ``tau`` : time to boundary-dominated flow (years) — scales dimensionless → real time.

So cumulative ``Q(t) = M · rf(t/tau)`` and rate is its time-derivative. An optional
Arps hyperbolic curve is provided purely as an empirical overlay for comparison.

Deterministic, no I/O. The reservoir solve depends only on the inputs below.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
from bluebonnet.fluids import build_pvt_gas
from bluebonnet.flow import FlowProperties, SinglePhaseReservoir


@dataclass
class CurveInputs:
    """Reservoir / fluid / completion scaling inputs for the forward curve."""

    # fluid
    gas_specific_gravity: float = 0.70
    temperature: float = 230.0  # deg F
    gas_dryness: str = "dry gas"
    n2: float = 0.0
    co2: float = 0.0
    h2s: float = 0.0
    # reservoir / completion
    pressure_initial: float = 6500.0  # psia
    pressure_fracface: float = 1200.0  # flowing bottomhole / frac-face (psia)
    resource_mmscf: float = 4000.0  # movable gas in place, MMscf (=> M in Mscf)
    tau_years: float = 3.0  # time-to-BDF (years)
    # numerics / horizon
    nx: int = 40  # spatial nodes in the scaling solve
    years: float = 20.0  # forecast horizon
    n_time: int = 400


def _recovery_interpolator(inp: CurveInputs):
    """Build bluebonnet's scaled recovery-factor interpolator + its domain max."""
    gas_values = {
        "N2": inp.n2,
        "H2S": inp.h2s,
        "CO2": inp.co2,
        "Gas Specific Gravity": float(inp.gas_specific_gravity),
        "Reservoir Temperature (deg F)": float(inp.temperature),
    }
    dryness = inp.gas_dryness if inp.gas_dryness in ("wet gas", "dry gas") else "dry gas"
    pvt = build_pvt_gas(
        gas_values, dryness, maximum_pressure=float(inp.pressure_initial) + 2000.0
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        flow = FlowProperties(pvt, float(inp.pressure_initial))
        reservoir = SinglePhaseReservoir(
            nx=int(inp.nx),
            pressure_fracface=float(inp.pressure_fracface),
            pressure_initial=float(inp.pressure_initial),
            fluid=flow,
        )
        # Solve on a generous scaled-time window so real-time tau scaling stays in-domain.
        t_scaled = np.linspace(0.0, 8.0, 320)
        reservoir.simulate(t_scaled)
    return reservoir.recovery_factor_interpolator(), float(t_scaled.max())


def production_curve(inp: CurveInputs) -> pd.DataFrame:
    """Forward production curve.

    Returns a DataFrame with columns ``days``, ``years``, ``rate_mscf_d`` (Mscf/day),
    and ``cum_mmscf`` (cumulative, MMscf).
    """
    rf, t_max = _recovery_interpolator(inp)
    m_mscf = float(inp.resource_mmscf) * 1.0e3  # MMscf -> Mscf (resource in place, M)
    tau = max(float(inp.tau_years), 1e-6)

    days = np.linspace(1.0, 365.25 * float(inp.years), int(inp.n_time))
    years = days / 365.25
    t_scaled = np.minimum(years / tau, t_max)
    cum_mscf = m_mscf * np.asarray(rf(t_scaled), dtype=float)  # cumulative, Mscf
    # daily rate in Mscf/day from the cumulative gradient (dQ/dt, t in days)
    rate_mscf_d = np.gradient(cum_mscf, days)
    rate_mscf_d = np.clip(rate_mscf_d, 0.0, None)

    return pd.DataFrame(
        {
            "days": days,
            "years": years,
            "rate_mscf_d": rate_mscf_d,
            "cum_mmscf": cum_mscf / 1.0e3,  # Mscf -> MMscf for display
        }
    )


def eur_mmscf(inp: CurveInputs) -> float:
    """Estimated ultimate recovery over the horizon, MMscf."""
    return float(production_curve(inp)["cum_mmscf"].iloc[-1])


def arps_overlay(
    qi_mscf_d: float, di_annual: float, b: float, years: float, n: int = 400
) -> pd.DataFrame:
    """Empirical Arps hyperbolic overlay (not physics) for visual comparison.

    qi_mscf_d : initial rate (Mscf/day)
    di_annual : initial nominal decline (1/yr)
    b         : hyperbolic exponent (0 = exponential, 1 = harmonic)
    """
    days = np.linspace(1.0, 365.25 * float(years), int(n))
    t_yr = days / 365.25
    di = max(float(di_annual), 1e-9)
    qi = float(qi_mscf_d)
    b = float(b)
    if abs(b) < 1e-6:
        # exponential
        rate = qi * np.exp(-di * t_yr)
        cum_yr = qi * 365.25 * (1.0 - np.exp(-di * t_yr)) / di  # Mscf
    elif abs(b - 1.0) < 1e-6:
        # harmonic (b == 1): cumulative has a log form, not the (1-b) power form
        rate = qi / (1.0 + di * t_yr)
        cum_yr = qi * 365.25 / di * np.log1p(di * t_yr)  # Mscf
    else:
        # hyperbolic
        rate = qi * (1.0 + b * di * t_yr) ** (-1.0 / b)
        cum_yr = (
            qi
            * 365.25
            / (di * (1.0 - b))
            * (1.0 - (1.0 + b * di * t_yr) ** (1.0 - 1.0 / b))
        )
    return pd.DataFrame(
        {
            "days": days,
            "years": t_yr,
            "rate_mscf_d": np.clip(rate, 0.0, None),
            "cum_mmscf": cum_yr / 1.0e3,
        }
    )
