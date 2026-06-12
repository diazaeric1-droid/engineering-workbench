# Changelog

All notable changes to Well Performance Studio are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/); versioning is semver.

## [0.2.2] — 2026-06-11
### Fixed
- **Three nodal/PVT physics corrections** (validated against published worked examples;
  the Vogel nodal AOF check is unmoved at 1095.5 vs the published ~1095):
  - **Live-oil density** — added the missing bbl→ft³ (5.615) conversion on the
    dissolved-gas mass term, so the live/saturated oil density (and the VLP hydrostatic
    head) is no longer inflated ~1.4–1.7× (previously produced oil denser than water). Now
    algebraically identical to the textbook `rho_o = (62.4·γ_o + 0.0136·Rs·γ_g)/Bo`
    (McCain/Standing): API=35, Rs=600 scf/STB, γ_g=0.75, Bo=1.30 → 45.50 lbm/ft³.
  - **Hagedorn–Brown holdup** — the primary holdup correlating group used the bare
    constant `14.7^0.10` where the local pressure ratio `(p/14.7)^0.10` belongs (Brown,
    *The Technology of Artificial Lift*). The segment pressure is now threaded into the
    holdup function (added to `_LocalProps`); the term is 1.0 at standard pressure.
  - **Gas z-factor** — the Brill & Beggs (1974) high-pressure B-term is `0.32·Ppr⁶/…`,
    not `Ppr²`; the `Ppr⁶` term restores the z upturn at high pseudo-reduced pressure.
    Now reproduces the verbatim published correlation (Ppr=2.0, Tpr=1.5 → z=0.8234,
    within ~3% of the Standing–Katz chart).
### Added
- `tests/test_worked_examples.py` — published-value pins for the oil-density, z-factor,
  and Standing Rs/Bo examples, plus the Hagedorn–Brown pressure-ratio behavior.
### Changed
- **Caching** — the expensive deterministic computations invoked by the app
  (`pvt_table`, `bubble_point`, `props_at_pressure`, `production_curve`, `vlp_curve`,
  `fit_rta`) are wrapped in `st.cache_data` with value-based `hash_funcs` for the
  (unhashable) input dataclasses and the rate-series DataFrame, so reruns no longer
  recompute on every slider nudge. `src/` stays Streamlit-free; results are unchanged.

## [0.2.1] — 2026-06-07
### Fixed
- CI smoke workflow now installs `pytest` (the unit-tests step was failing with `pytest: command not found`).
### Changed
- **Light theme** — suite-wide migration from dark/navy to a professional light palette (white surfaces, `plotly_white` charts, navy/blue accents retained); transparent fixed header so the title never clips. `runtime.txt` pinned to Python 3.11.

## [0.2.0] — 2026-06-07

Nodal (systems) analysis + artificial-lift design — two new tabs, both deterministic and
key-free, built on self-contained standard petroleum correlations (pure numpy/scipy, no
bluebonnet dependency).

### Added
- **Nodal tab** — bottom-hole-node systems analysis. **IPR** (inflow) via Vogel (1968)
  below the bubble point joined to a straight-line PI above (or a pure straight-line PI
  option); **VLP** (outflow) via a segmented multiphase pressure traverse using
  **Hagedorn–Brown (1965)** or **Beggs–Brill (1973)** with Standing/Beggs-Robinson
  black-oil properties and a Chen friction factor; the **operating point** is the IPR∩VLP
  intersection (Brent root-find, returning the stable high-rate crossing). Plots IPR, VLP,
  and the operating point; reports q_op, pwf_op, and AOF.
- **Artificial Lift tab** — **ESP design**: total dynamic head, stage count from a
  representative 60-Hz centrifugal pump curve, drive frequency via the **affinity laws**,
  a basic viscosity head/efficiency de-rate, brake horsepower, and a check of the boosted
  nodal operating point against the target. Plus a **gas-lift** injection-GLR sweep that
  finds the rate-maximizing injection rate. Plots the pump head/stage curve with the
  design point and the gas-lift performance curve.
- `src/nodal.py` and `src/lift.py` — pure numpy/scipy, import-clean, deterministic.
- Validation test against a published Vogel worked example (AOF within 1% of the
  textbook ~1095 STB/d) plus the Vogel dimensionless reference curve to machine precision,
  and tests for IPR/VLP monotonicity, a unique stable operating point, and sane ESP sizing.

### Notes
- Correlations are the standard textbook forms applied to illustrative single-well inputs
  — defensible reimplementations, not tuned field matches or vendor pump catalogs. Captions
  and the data-provenance badge state this explicitly.

## [0.1.0] — 2026-06-07

Initial release — the suite's forward-modeling "Design" app.

### Added
- **PVT tab** — black-oil + gas fluid properties vs. pressure via bluebonnet
  `fluids.Fluid` (Standing oil FVF/viscosity, Dranchuk–Abou-Kassem gas z/FVF/viscosity,
  Sutton pseudo-criticals, McCain water): Bo, Bg, oil/gas/water viscosity, z-factor,
  bubble point, and a properties-at-pressure table.
- **Physics production curve tab** — bluebonnet's 1-D scaling-solution reservoir
  simulator (`flow.SinglePhaseReservoir` over a `build_pvt_gas` table) → rate(t),
  cumulative, and EUR, scaled to a real well by movable gas in place (M) and
  time-to-BDF (τ). Optional empirical Arps overlay (exponential / hyperbolic /
  harmonic).
- **RTA tab** — fits bluebonnet's `forecast.ForecasterOnePhase` to a built-in synthetic
  rate series (or an uploaded date/rate CSV) to back out M and τ, then forecasts EUR.
  The data-provenance badge flips to "real" when a user series is uploaded.
- Thin, testable wrappers in `src/` (`pvt.py`, `curves.py`, `rta.py`) around bluebonnet;
  the Streamlit app (`demo/app.py`) stays presentation-only.
- Shared dark + navy suite theme and cross-app suite navigator.
- Optional Claude narrative (bring-your-own Anthropic key, never stored); every chart
  and number is computed deterministically with no API key.
- Deterministic `pytest` suite for the wrappers and a GitHub Actions smoke workflow
  (Python 3.11) that runs the tests and a Streamlit `AppTest` render.
