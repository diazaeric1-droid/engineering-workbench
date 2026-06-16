"""PVT wrapper around ``bluebonnet.fluids``.

Builds a black-oil + gas PVT property table from a handful of field-known inputs
(oil API, gas SG, solution GOR, reservoir temperature) using bluebonnet's published
correlations:

* oil FVF / Rs / bubble point — Standing
* oil viscosity — Beggs-Robinson
* gas FVF / viscosity / z-factor / compressibility — Dranchuk & Abou-Kassem (1975),
  Sutton pseudo-criticals
* water FVF / viscosity — McCain-family correlations

bluebonnet's :class:`~bluebonnet.fluids.Fluid` exposes ``oil_FVF``, ``oil_viscosity``,
``gas_FVF``, ``gas_viscosity``, ``water_FVF``, ``water_viscosity`` and
``pressure_bubblepoint``. The gas methods require pseudo-critical temperature/pressure,
which we derive with bluebonnet's ``make_nonhydrocarbon_properties`` +
``pseudocritical_point_Sutton`` helpers.

Deterministic, no I/O. Returns plain pandas/numpy so the app layer stays thin.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from bluebonnet.fluids import Fluid
from bluebonnet.fluids.gas import (
    make_nonhydrocarbon_properties,
    pseudocritical_point_Sutton,
)


@dataclass
class PVTInputs:
    """Reservoir-fluid inputs for a PVT table."""

    api_gravity: float = 38.0  # deg API
    gas_specific_gravity: float = 0.75  # relative to air
    solution_gor: float = 900.0  # scf/bbl
    temperature: float = 210.0  # deg F
    pressure_min: float = 500.0  # psia
    pressure_max: float = 6000.0  # psia
    n_points: int = 40
    gas_dryness: str = "wet gas"  # 'wet gas' | 'dry gas'
    n2: float = 0.0  # mole fraction
    co2: float = 0.0  # mole fraction
    h2s: float = 0.0  # mole fraction


# bluebonnet's gas correlations want the dryness as one of these exact strings.
GAS_DRYNESS_OPTIONS = ("wet gas", "dry gas")


def make_fluid(inp: PVTInputs) -> Fluid:
    """Construct a bluebonnet :class:`Fluid` from :class:`PVTInputs`."""
    return Fluid(
        temperature=float(inp.temperature),
        api_gravity=float(inp.api_gravity),
        gas_specific_gravity=float(inp.gas_specific_gravity),
        solution_gor_initial=float(inp.solution_gor),
    )


def pseudocriticals(inp: PVTInputs) -> tuple[float, float]:
    """Sutton pseudo-critical (temperature degF, pressure psia) for the gas methods."""
    nonhc = make_nonhydrocarbon_properties(inp.n2, inp.h2s, inp.co2)
    dryness = inp.gas_dryness if inp.gas_dryness in GAS_DRYNESS_OPTIONS else "wet gas"
    t_pc, p_pc = pseudocritical_point_Sutton(
        float(inp.gas_specific_gravity), nonhc, dryness
    )
    return float(t_pc), float(p_pc)


def pvt_table(inp: PVTInputs) -> pd.DataFrame:
    """Return a PVT property table (one row per pressure step).

    Columns: ``pressure`` (psia), ``Bo`` (rb/stb), ``oil_viscosity`` (cP),
    ``Bg`` (rb/scf), ``gas_viscosity`` (cP), ``z_factor`` (-),
    ``Bw`` (rb/stb), ``water_viscosity`` (cP).
    """
    fluid = make_fluid(inp)
    t_pc, p_pc = pseudocriticals(inp)
    pressure = np.linspace(
        float(inp.pressure_min), float(inp.pressure_max), int(inp.n_points)
    )

    bo = np.asarray(fluid.oil_FVF(pressure), dtype=float)
    mu_o = np.asarray(fluid.oil_viscosity(pressure), dtype=float)
    bg = np.asarray(fluid.gas_FVF(pressure, t_pc, p_pc), dtype=float)
    mu_g = np.asarray(fluid.gas_viscosity(pressure, t_pc, p_pc), dtype=float)
    bw = np.asarray(fluid.water_FVF(pressure), dtype=float)
    mu_w = np.asarray(fluid.water_viscosity(pressure), dtype=float)

    # z-factor via the same DAK routine bluebonnet uses internally for gas FVF.
    from bluebonnet.fluids.gas import z_factor_DAK

    z = np.array(
        [z_factor_DAK(float(inp.temperature), float(p), t_pc, p_pc) for p in pressure],
        dtype=float,
    )

    return pd.DataFrame(
        {
            "pressure": pressure,
            "Bo": bo,
            "oil_viscosity": mu_o,
            "Bg": bg,
            "gas_viscosity": mu_g,
            "z_factor": z,
            "Bw": bw,
            "water_viscosity": mu_w,
        }
    )


def bubble_point(inp: PVTInputs) -> float:
    """Bubble-point pressure (psia) for the fluid (Standing correlation)."""
    return float(make_fluid(inp).pressure_bubblepoint())


def props_at_pressure(inp: PVTInputs, pressure: float) -> dict[str, float]:
    """PVT properties evaluated at a single pressure (psia)."""
    fluid = make_fluid(inp)
    t_pc, p_pc = pseudocriticals(inp)
    p = float(pressure)
    # Several bluebonnet correlations iterate over `pressure` internally, so feed every
    # call a 1-element array and take element 0 — robust across the oil/gas/water methods.
    parr = np.array([p], dtype=float)

    def _scalar(arr):
        return float(np.asarray(arr).reshape(-1)[0])

    from bluebonnet.fluids.gas import z_factor_DAK

    return {
        "pressure": p,
        "Bo": _scalar(fluid.oil_FVF(parr)),
        "oil_viscosity": _scalar(fluid.oil_viscosity(parr)),
        "Bg": _scalar(fluid.gas_FVF(parr, t_pc, p_pc)),
        "gas_viscosity": _scalar(fluid.gas_viscosity(parr, t_pc, p_pc)),
        "z_factor": float(z_factor_DAK(float(inp.temperature), p, t_pc, p_pc)),
        "Bw": _scalar(fluid.water_FVF(parr)),
        "water_viscosity": _scalar(fluid.water_viscosity(parr)),
    }
