# Engineering Workbench

**Every engineering lens on one well.** The per-well engineering console of the
Upstream Copilot Suite: **design → diagnose → predict → optimize**, condensed
from four production-grade applications into one, with a one-page **Well Case
File** that assembles every available lens for the selected well — and says so
honestly when a lens has no data instead of inventing numbers.

Part of the consolidated operator trio: **Operations Center** (surveillance ·
loss accounting · triage) · **Engineering Workbench** (this app) · **Capital
Desk** (authorize · program · screen).

## Module Map

| Section | Page | What it does | Core |
|---|---|---|---|
| Fleet | Well Browser | Merged well table across all data domains with per-domain availability flags + ESP risk where scorable; row click sets the global well | registry + all four |
| Design | Nodal Analysis | Vogel IPR × Hagedorn-Brown / Beggs-Brill VLP → operating point (stored to the Case File design lens) | `wps.nodal` |
| Design | PVT & Type Curves | Black-oil PVT, bluebonnet scaling-solution production curves, RTA (lazy-imports bluebonnet; degrades to an empty state without it) | `wps.pvt/curves/rta` |
| Design | Artificial Lift Design | ESP affinity-law sizing (stages · Hz · TDH · hp) + gas-lift injection sweep | `wps.lift` |
| Diagnose | Decline & EUR | Arps fit + type-curve deviation + prodpy Monte-Carlo P90/P50/P10 EUR & NPV on the session deck — REAL Colorado data by default | `pec.analyzers` |
| Diagnose | AI Well Review | Deterministic screen (diagnosis · intervention · risked NPV) keyless; BYOK Claude tool-use review on top | `pec.portfolio/agent` |
| Predict | Failure Risk | Calibrated 30-day failure probabilities, per-well Tree-SHAP drivers, OOF reliability diagram, oracle-ceiling framing | `esp.model/explainer/oracle` |
| Predict | Run-Life | Trained discrete-time hazard model: per-well survival + hazard curves, median-RUL fleet ranking, OOF C-index / IBS | `esp.survival_model` |
| Optimize | Gas-Lift Optimum | GLPC scatter + fit + economic curve + closed-form optimal injection recommendation | `gla.glpc` |
| Optimize | Injection Allocation | Fleet injection split under a compressor cap — equal-marginal-revenue shadow-price bisection (exact) | `gla.glpc` |
| Case File | Well Case File | Decline/EUR · failure risk + top-3 SHAP · gas-lift recommendation · design operating point, one screen + downloadable markdown one-pager | all four |
| Data | Sources & BYOD | Provenance of every built-in dataset + three strict-schema uploads (production / fleet SCADA / injection survey), templates included, nothing stored server-side | component loaders |

## Built On

| Component | Version | Contribution |
|---|---|---|
| [well-performance-studio](https://github.com/diazaeric1-droid) | v0.2.2 | Nodal analysis, PVT, physics curves, RTA, lift design. `nodal.py` carries three June-2026 physics corrections (live-oil density 5.615 conversion; Hagedorn-Brown local-pressure holdup group; Brill & Beggs Ppr⁶ z-factor term), each pinned to published worked examples — treated as a **certified core** and vendored with `nodal.py` byte-identical. |
| [production-engineer-copilot](https://github.com/diazaeric1-droid) | v0.9.2 | Decline/EUR + type curve, Monte-Carlo forecast & economics bands, the suite `econ_core` DCF convention, the deterministic portfolio screen, and the Claude tool-use well review. Ships **committed REAL Colorado ECMC production** (28 DJ Basin Niobrara/Codell horizontals, real state API ids). |
| [esp-failure-risk-agent](https://github.com/diazaeric1-droid) | v0.7.3 | Calibrated 30-day failure classifier (XGBoost + Platt), Tree-SHAP drivers, trained discrete-time survival model, and the oracle/Bayes-ceiling analysis. |
| [well-gas-lift-advisor](https://github.com/diazaeric1-droid) | v0.1.0 | GLPC fitting, the closed-form economic injection optimum, and exact fleet allocation under a compressor limit. |

## Architecture

**Vendored components + alias loader.** Each component repo is copied under
`apps/` (no submodules — one self-contained clone) and its `src/` package is
loaded under a distinct alias (`wps` · `pec` · `esp` · `gla`) by `core.py`'s
importlib loader, so all four run in **one Python process** — the same pattern
proven in pe-pipeline. The presentation layer (`app.py`, `views/`,
`product_theme.py`) is new; the **math/ML cores are unchanged** (three of four
components byte-identical; one two-line import rewrite — see `VENDORING.md`).

The honest numbers travel with the components:

- **Physics validation** — wps v0.2.2's corrected correlations are pinned to
  published values (e.g. the Vogel worked example AOF = 1095.5 STB/d, asserted
  through the `wps` alias in this repo's tests).
- **Oracle ceiling** — the ESP generator injects ~5% feature-independent label
  noise, so a Bayes-optimal ceiling exists: model OOF AUROC **0.854** vs
  computed ceiling **0.853** ⇒ the model captures ~**100% of attainable
  signal** (it sits at the noise floor, not below an ideal). Reproduced from
  scratch by `core.bootstrap()` on every fresh clone.
- **Honest eval** — the AI Well Review reports the **blind-holdout 0.722**
  recommendation agreement under strict exact-class grading (18 held-out
  cases), read from the committed eval artifact.
- **Survival model** — out-of-fold time-dependent C-index ≈ 0.86 with an IBS
  that beats the Kaplan–Meier baseline by ~13–16%, computed live from the
  regenerated run-life ground truth.

`core.py` is importable without Streamlit (the tests run it headless) and owns
`bootstrap()`: gitignored synthetic artifacts (ESP SCADA + labels, the trained
ESP model, the gas-lift fleet + ground truth) regenerate deterministically on
first run.

## Run Locally

```bash
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py        # bootstrap runs on first launch (~30 s)
```

Python is pinned to **3.11** (`runtime.txt`) because bluebonnet —
well-performance-studio's physics engine — supports ≤ 3.11.

Tests (54, including four numeric invariants pinning component values and a
per-page AppTest render sweep):

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

## Data Identity (read this before quoting a number)

- **REAL** — `pec` ships committed Colorado ECMC (COGCC) public monthly
  production: 28 DJ Basin horizontals under their real state API ids
  (`05-123-…`). Public filings carry **production only** — the workbench never
  shows SCADA, injection, or failure-risk numbers for a real well.
- **Synthetic** — three modeled fleets share the registry's `well_0NN`
  namespace and merge by id: pec's well files (well_001–041, with ESP readings
  and dyno cards), esp's SCADA fleet (well_001–100, labeled failures +
  run-life ground truth), gla's injection fleet (well_001–020, embedded
  surveys + true optima). Availability flags in the Well Browser and Case File
  state exactly which domains each well carries.
- **BYOK** — the optional Anthropic key is session-only and powers one page;
  every chart and number on every page is deterministic without it.
