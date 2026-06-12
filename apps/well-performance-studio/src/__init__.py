"""Well Performance Studio — thin, testable wrappers around the bluebonnet engine.

The forward-modeling ("Design") app of the Upstream Copilot Suite. Everything in
``src`` is deterministic and import-clean (no Streamlit, no network, no API key) so
the same physics can be unit-tested in CI and reused headless.

bluebonnet (pip, Wahaj Khan / SPE) provides the physics for the PVT / curve / RTA tabs:
    * ``bluebonnet.fluids``  — black-oil / gas PVT correlations (Standing, DAK, Sutton)
    * ``bluebonnet.flow``    — 1-D scaling-solution reservoir simulator
    * ``bluebonnet.forecast``— physics-based rate-transient fit / forecast

The nodal-analysis (``nodal.py``) and artificial-lift (``lift.py``) modules are
self-contained pure-numpy/scipy reimplementations of the standard textbook correlations
(Vogel IPR, Hagedorn–Brown / Beggs–Brill multiphase VLP, ESP affinity-law sizing) — no
bluebonnet dependency.
"""

__version__ = "0.2.2"
