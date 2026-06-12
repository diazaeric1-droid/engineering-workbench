# Changelog

## v0.1.0 — 2026-06-11

First release of **Engineering Workbench**, the per-well engineering console of
the Upstream Copilot Suite (design → diagnose → predict → optimize).

- Consolidates four component apps into one Streamlit product via the
  vendored-apps + importlib-alias-loader architecture (pattern proven in
  pe-pipeline): well-performance-studio **v0.2.2** (`wps`),
  production-engineer-copilot **v0.9.2** (`pec`), esp-failure-risk-agent
  **v0.7.3** (`esp`), well-gas-lift-advisor **v0.1.0** (`gla`).
- Seven sections / twelve pages: Fleet (Well Browser), Design (Nodal Analysis ·
  PVT & Type Curves · Artificial Lift Design), Diagnose (Decline & EUR · AI
  Well Review), Predict (Failure Risk · Run-Life), Optimize (Gas-Lift Optimum ·
  Injection Allocation), Case File (Well Case File), Data (Sources & BYOD).
- One-page **Well Case File** with per-lens availability gating and a
  downloadable markdown brief; lenses without data render explicit empty
  states, never fabricated numbers.
- Merged well identity: REAL Colorado ECMC wells (28, real state API ids,
  production only) + the synthetic `well_0NN` fleets (production / SCADA /
  injection) joined by id with availability flags.
- `core.bootstrap()` regenerates every gitignored artifact deterministically
  (ESP SCADA seed 7 + trained model + training report; gas-lift fleet seed 42).
- Enterprise presentation layer (`product_theme` masthead / context bar / KPI
  rows / pills / empty states / product switcher) on the shared suite theme;
  Material-icon `st.navigation`, global well + price-deck sidebar, BYOK key.
- 54 product tests: alias/loader contracts, cold bootstrap, four numeric
  invariants reproducing component-certified values (Vogel AOF 1095.5;
  gas-lift optimum ln(13440/1.5); calibrated ESP probabilities with a
  deterministic top-risk well; view-layer decline wrapper ≡ pec analyzer),
  navigation spec, full-app AppTest smoke, and a per-view render sweep across
  hero / real-Colorado / SCADA-only wells.
