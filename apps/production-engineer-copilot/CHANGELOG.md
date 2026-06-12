# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.9.2] — 2026-06-11

### Added
- **BYOD CSV upload** — new "Upload your own CSV" sidebar option parses any tidy monthly-production CSV (`well_id`, `date`, `oil_bbl`, `gas_mcf`, `water_bbl`, `days`) via the existing `load_ndic_fleet` adapter (no parallel parser); validates required columns before parsing and shows a clear `st.error` listing missing columns on bad input; nothing is stored server-side.

## [0.9.1] — 2026-06-11

### Fixed
- **Discount convention bug (both NPV paths).** `economics.py` discounted with
  `(1 + r/12)**months`, compounding a 10% input to a 10.47% effective-annual rate — out of
  step with the AFE and Capital apps, which use the correct `(1 + r)**(months/12)`. The bug
  was in BOTH the deterministic `evaluate_intervention` and the Monte-Carlo
  `_npv_payout_vectorized`. Both now route through the shared, tested **`econ_core`** kernel
  (vendored byte-identical at `src/analyzers/econ_core.py`): effective-annual `discounted_pv`,
  `exp_uplift_rate`, and `risked_npv` (`pc*PV - cost`). NPV magnitudes rise slightly (less
  discounting); all dataclass fields and return shapes are unchanged, and the deterministic and
  MC paths stay consistent. Adds `test_econ_core` (11 tests) locking the conventions.
- **Remaining-EUR overstatement (~2.2x).** `project_eur` integrated the fitted decline from
  t=1 (the START of production history), re-counting every barrel already produced and
  overstating *remaining* reserves ~2.2x (e.g. 662,835 → 307,123 bbl on an 18-month synthetic
  well). It now integrates FORWARD from the last observed production day (`from_day`); the
  portfolio screen and `project_recovery` tool pass `days[-1]`. Regression test added.

### Changed
- **Honest blind-holdout grade (Phase 2).** The holdout previously reported a phantom **1.00**
  because the recommendation grader was lenient: it credited a class if any synonym appeared
  *anywhere* in the report, and its synonym sets overlapped across near-miss classes (so an
  acid-stim report scored a hit on a scale expectation, and vice-versa). The holdout is now
  graded **strictly** — the report's actual #1 recommendation must be the **exact** intervention
  class, no near-miss credit (`recommendation_matches_strict` in `run_evals.py`). The honest
  number is **0.72 (13/18)**; the five misses are genuine near-miss confusions
  (acid-stim↔scale, esp-swap↔gas-separator, monitor↔gas-lift-optimization,
  insufficient-data↔monitor). `summary_holdout.json` re-graded; the CI gate now guards the
  strict holdout at a **0.70** floor (was 0.85 on the lenient dev summary); README badge/table
  updated. The de-leak invariant was re-verified — holdout `notes` carry observations only.
  *Note: the strict number was computed by re-grading the committed real-agent predictions; a
  full live re-run of the LLM holdout needs `ANTHROPIC_API_KEY`, which this change set did not
  have (see PR notes).*

## [0.9.0] — 2026-06-07
### Added
- **Real public data is now the DEFAULT** — Colorado ECMC (COGCC) **DJ Basin Niobrara/Codell** per-well monthly production (28-well committed slice, harvested by `data/real/colorado/fetch_colorado.py`); new `src/adapters/colorado.py`. Sidebar defaults to **Real — Colorado**; NDIC retained as a bring-your-own-export path (NDIC bulk data is a paid subscription).
### Changed
- **Light theme** — suite-wide migration from dark/navy to a professional light palette (white surfaces, `plotly_white` charts, navy/blue accents retained); transparent fixed header so the title never clips. `runtime.txt` pinned to Python 3.11.

## [0.8.0] — 2026-06-06

### Added
- **Representative-vs-anomalous data-quality diagnostic** (`src/analyzers/representative.py`) —
  classifies which `production_history` oil-rate points are **representative** for decline /
  type-curve trending vs which to **EXCLUDE** (shut-in / zero-rate days, gross outliers vs a
  robust decline-aware trend; reuses the median/MAD robust z and the Arps `fit_decline`). Surfaced
  in the per-well **Trends** tab: non-representative points are marked with a distinct ✕, plus an
  **optional** "fit on representative points only" overlay curve. **Additive & eval-safe** — it does
  NOT change `fit_decline` / `analyze_type_curve`, the agent/recommendation logic, or the default
  fit the blind-holdout eval runs through; guarded for < 5-point wells and wrapped so it never
  crashes the page.
- **Real-data option (North Dakota / NDIC)** — a sidebar "Data source" toggle (Synthetic default |
  Real — NDIC) + an NDIC adapter (`src/adapters/ndic.py`) that ingests tidy per-well **monthly**
  Bakken filings (monthly→avg-daily-rate); drops in at `data/real/ndic/production.csv` (see README +
  template). ESP diagnostics gate off gracefully on real monthly data (no public ESP telemetry).
- **Data-provenance badge** under the header (green "REAL DATA — NDIC/Bakken" vs amber "SYNTHETIC")
  so a visitor always knows what they're looking at.

## [0.7.0] — 2026-06-06

### Added
- **Fleet explorer (multipage)** — a Fleet Overview with fleet KPIs and a **sortable per-well
  table** (lift, lateral length, basin·formation from the shared registry, latest oil BOPD,
  water cut, GOR, days-on-prod, plus risked NPV / PI from the portfolio screen), and a
  **drill-down page per well** (`st.navigation`) holding the full single-well review (decline
  vs type curve, ESP diagnostics, Monte-Carlo economics, AI review, Generate-AFE). The <5-point
  insufficient-data guard is preserved per well.

## [0.6.0] — 2026-06-06

Suite-grade UX + economics depth: one upstream-copilot identity across the apps, a richer
Economics tab, and an inline AFE handoff.

### Unified "Upstream Copilot Suite" theme
- New unified dark + navy **Upstream Copilot Suite** theme applied across the app, with a
  cross-app sidebar **suite navigator** so the PE Copilot, AFE Copilot, ESP Failure-Risk,
  Digest, Deferment IQ, and Capital Optimizer read as one product family.

### Economics tab
- **Monte-Carlo NPV distribution histogram (P10/P50/P90)** in the Economics tab — the full
  risked NPV distribution, not just the point estimate.
- **"Generate AFE"** — an inline one-page authorization preview (cost split + net economics +
  authority routing) rendered in-app, with a diagnosis-JSON export and a deep-link straight
  into AFE Copilot to draft the full document.

### Shared fleet identity
- **Shared fleet registry** — each well now carries its Permian (Midland / Delaware)
  field / formation identity, consistent across the whole suite so the same well reads the
  same everywhere in the chain.

### Robustness fix
- **Crash fix:** wells with fewer than 5 production points now render an "insufficient data"
  panel (mirroring the agent's graceful path) instead of erroring out the dashboard on the
  hyperbolic decline fit.

### Maintenance
- Swept the deprecated `use_container_width` (→ `width="stretch"`); now requires
  **streamlit ≥ 1.50**.

## [0.5.0] — 2026-06-04

Beyond the saturated synthetic score: prove it on real data, harden it, show PE value.

### Real public data (`src/adapters/public_data.py`)
- Adapter that ingests the **Volve** (Equinor open North Sea dataset, CC BY-NC-SA 4.0)
  `MonthlyProductionData` schema and the generic **NDIC / Texas RRC** field-unit schema, with
  the real-world wrangling: Sm³→bbl (×6.2898), Sm³ gas→mcf, period-volume→daily-rate ÷ on-stream
  days, bar→psi for downhole gauges. `run_review` now accepts a pre-built `WellFile`.
- Ran a real-format review end-to-end on Volve producer 15/9-F-12 (`evals/real_reviews/`): the
  agent correctly flagged the subsea ESP running far below POR (4,094 vs 8,000 BFPD floor) with a
  rising 54% water cut, on type curve, ~4.2 MMbbl remaining. `data/real/` ships a schema-faithful
  sample + license/sourcing docs (the gated 40k-file dataset isn't redistributed).

### Field / portfolio mode (`src/portfolio.py`)
- Fully deterministic field screen (no API) — ranks a whole field by **risked NPV / capital
  efficiency**, picking the indicated intervention per well from the same analyzers. The VP
  "which of my 200 wells do I work over this quarter" deliverable + a fleet capital/NPV total.

### Calibrated, cited economics (`src/analyzers/assumptions.py`)
- Single source of truth for price deck (EIA STEO), LOE/SWD, discount rate, and per-intervention
  cost / uplift / decline / chance-of-success / downtime (SPE + public operator ranges), each with
  a source. New `get_intervention_assumptions` tool feeds the agent sourced numbers to risk the NPV
  with (P(success), deferred production, SWD drag) instead of inventing them.

### Robustness & model economics
- **Adversarial eval** (`evals/adversarial.py`): **5/5 probes pass** — resists two prompt-injection
  attempts (a note ordering a P&A; a note ordering a false all-clear) and degrades gracefully on
  missing ESP readings, a physically-impossible rate, and a mislabeled lift type. **Self-consistency:
  2/3** runs agreed on a borderline gas-vs-scale well (67%) — honest weak spot; `run_review(temperature=0)`
  added for reproducible decoding as the fix.
- **Model accuracy/cost frontier** (`evals/model_frontier.py`): on a 12-case per-class subset,
  **Haiku and Sonnet both score 100%**, but Haiku is **~4× cheaper ($0.029 vs $0.117/review) and
  ~2.4× faster (22.5s vs 54.7s)** → Haiku is the right default for this task.

### Demo
- Eval dashboard tab upgraded: dev + **blind-holdout** headline, per-class agreement table.

## [0.4.0] — 2026-06-03

Eval-credibility + domain-depth overhaul. The headline number is now earned by
reasoning, not by keyword-matching a leaked answer.

### Closed the two known eval misses at the root
- New **dyno-card interpretation tool** (`interpret_dyno_card`) classifies the latest
  dynamometer card into fluid-pound/pump-off, parted rods (flat card), gas interference,
  or healthy full fillage — the primary downhole diagnostic for beam pumps, which the
  decline curve is blind to. Closes the pump-off miss (the signal existed in the data but
  no tool read it, and `well.summary()` now advertises which data is available).
- New **ESP economic-life evaluator** (`evaluate_esp_economic_life`) decides ESP-swap vs
  ESP-to-beam conversion on *lifecycle* economics (remaining EUR net of the ESP re-fail
  cadence vs a beam unit's longer run life). The ESP-to-beam wells are now genuinely old,
  depleted, and below POR, so the conversion is reachable by reasoning instead of by a
  contradicted age heuristic. Closes the esp-to-beam miss.

### Made a larger sample actually mean something
- **De-leaked the generator:** well-file `notes` now carry only raw field observations +
  distractors — never the diagnosis or recommendation. Expert labels live only in
  `cases.yaml` (which the agent never sees). Enforced by a unit-test invariant.
- **Parameterized every archetype** over bounded reservoir/lift distributions (qi, Di, b,
  intake pressure, amps, water cut, GOR, fillage, age) so each case is a distinct realistic
  point, not a hand-tuned singleton.
- **Boundary / ambiguous cases:** scale-with-gas-distractor, sequenced acid-then-swap, and
  insufficient-data (correct answer = "get more data", not a fabricated call).
- Scaled the dev set to **41 cases**; added a **blind 18-case holdout** (`--holdout`,
  separate seed + id range) — tune on dev, report the holdout number as the headline.

### Upgraded scoring beyond keyword-match
- **LLM-as-judge** rubric (`evals/judge.py`, `run_evals --judge`) scores each report 1-5 on
  diagnosis / recommendation / economics / restraint.
- **Per-class agreement table + confusion matrix** (expected → predicted) so systematic
  confusions are visible instead of hidden in a single blended number.
- **Blind human-grading sheet** generator (`evals/make_human_grading_sheet.py`) for an
  inter-rater PE panel — the most defensible metric for the flagship narrative.

### Domain depth
- `analyze_water_gas_trends`: water-cut and GOR levels + least-squares trends (drives
  interventions the oil-rate curve hides). Healthy-well water-cut flag tuned to 8%/yr so
  maturing wells stay clean.
- VP-grade risked economics in `evaluate_intervention`: chance-of-success, deferred
  production during the job, and SWD/water-disposal drag on net margin (all default to a
  no-op so the point estimate stays comparable to the Monte-Carlo path).
- ESP physics: optional `frequency_hz` / `discharge_pressure_psi` readings and a thrust
  (down/up/neutral) call; a low-Hz-at-below-POR flag confirms the pump is already turned
  down (strengthens a swap/conversion over "just slow it down").

### Correctness fixes surfaced during the live re-run
- **Type-curve analyzer was noise-unstable** — the fixed early-window Arps fit made HEALTHY
  wells read anywhere from −38% to +68% "off type curve," which drove the agent to recommend
  acid stim on a perfectly healthy well. Replaced with **leave-one-out degraded-tail trimming**:
  fit the full history and peel back only points that have genuinely departed from the
  established decline (tested against a fit that EXCLUDES them, so the fit can't bend to absorb a
  break). Healthy wells now read ~0%; real roll-overs still expose deferred production. Regression
  test added. This is a production-credibility fix, not just an eval fix.
- **Empty `ANTHROPIC_API_KEY` shadowing** — `load_dotenv()` would not override a blank env var
  exported by the shell, yielding a cryptic SDK auth error. `agent.py` / `judge.py` now fall back
  to `.env` and raise a clear message if the key is truly missing.
- **Insufficient-data escalation** — the agent defaulted a data-poor well to "continue
  monitoring" (which implies a confirmed-healthy well). Prompt hardened so it must state
  "insufficient data to make a recommendation" and list the data needed, rather than a false
  all-clear.

### Results (v0.4)
- Dev (41 cases): **41/41 (1.00)** recommendation agreement, 0.87 diagnosis-keyword.
- Blind holdout (18 cases): **18/18 (1.00)** recommendation agreement, 0.92 diagnosis-keyword.
- Per-class agreement 100% across all twelve recommendation classes on both sets. Up from the
  prior 0.90 on 20 hand-tuned wells whose notes leaked the answer. CI gate (≥0.85) passes.
- Honest caveat: synthetic wells with clean, separable signatures; real-data + the inter-rater
  PE panel are the next credibility step, not a higher synthetic number.

## [0.3.3] — 2026-06-02

- Self-heal stale Streamlit bytecode cache at startup: purge `src/` `__pycache__`
  and evict cached `src` modules so newly-added functions reload from current source
  after a redeploy. Fixes the startup ImportError cascade seen after adding new
  symbols to existing modules (the app no longer needs a manual Reboot to pick them up).

## [0.3.2] — 2026-06-02

- Resilience: `analyze_type_curve` (added to the pre-existing decline module) is now
  imported defensively, so a stale Streamlit bytecode cache serving an old
  `decline_curve.pyc` degrades gracefully to the plain fit instead of taking the app
  down. Clear the cache fully with a Reboot (Manage app → Reboot).

## [0.3.1] — 2026-06-02

- Hotfix: decline-curve module crashed on import under numpy ≥ 2.3 (where `np.trapz`
  was removed), taking the whole app down. Resolve `np.trapezoid` without eagerly
  touching the removed `np.trapz` alias.

## [0.3.0] — 2026-06-02

- True type-curve benchmark (early-window fit + cumulative deferred bbl/$)
- Monte-Carlo intervention economics (P10/P50/P90 + tornado sensitivity)
- Eval dashboard (20-case agreement, confusion breakdown, $/review) + CI regression gate
- Structured, validated diagnosis export for AFE-Copilot chaining
- Fixed payout off-by-one; replaced mislabeled "rate of return" with discounted profitability index

## [0.2.0]

- Initial public demo
</content>
</invoke>
