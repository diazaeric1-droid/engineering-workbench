# Changelog

## v0.3.0 — 2026-06-14

Deep senior-PE hardening: the **Design section now anchors to the selected well**,
and every remaining medium- and low-severity finding from the full audit is closed.

### Design section — anchored to the well (the headline change)
- New keystone `core.well_design_seed(well_id)` → a per-well reservoir / fluid /
  completion seed with **honest per-field provenance** (`measured` from the well's
  own production/SCADA data · `derived` via standard correlations — Standing bubble
  point, geothermal BHT, live-oil viscosity · `assumed` formation-typical). Cached
  via `_common.design_seed_cached`.
- **Nodal Analysis** now seeds every System Input from the selected well (re-seeds on
  well change, stays editable), exposes the **PVT/thermal inputs that drive the VLP**
  (oil API, gas SG, water SG, surface & bottom-hole temps) and threads them into the
  correlation, shows a **measured-vs-assumed provenance table**, warns when bubble
  point > reservoir pressure, makes the AOF KPI mode-aware, and labels the chart with
  the **actually-selected** correlation. The persisted Case-File design lens is now
  genuinely well-specific.
- **Artificial Lift Design** seeds from the well too, exposes the hidden fluid
  descriptors (API, water SG), and fixes the pump physics: the plotted curve is now
  **viscosity-corrected** so the design point sits on it, the x-range scales to the
  **frequency-scaled runout**, an out-of-runout target is flagged **infeasible with a
  capped stage count** (no more thousands-of-stages), and the gas-lift marker reports
  a true **economic optimum** + an honest **rollover/boundary** flag. "Natural Rate"
  reads "no natural flow" when applicable; the meets-target tolerance is disclosed.
- **PVT & Type Curves** seeds the fluid model from the well, reports **Bo at the
  bubble point** (not an arbitrary slider pressure), plots **Bg + gas viscosity**,
  corrects the correlation attribution, and de-duplicates the RTA data badge.

### Every other view (medium + low findings)
- **Well Browser:** in-table search + Basin / Lift / availability filters; one
  consolidated identity column (no redundant Well-Id/Well); SCADA-only wells flagged.
- **Decline & EUR:** the three Arps fits (full-history / type-curve / Monte-Carlo) are
  now each labeled; the type curve is **extrapolated past the last actual**; EUR shows
  both a reserves-style **EUR-to-economic-limit** and the full-horizon percentiles
  (reconciling the prior fan-vs-EUR mismatch); 5-point / gappy-history cases are noted.
- **AI Well Review:** SCADA-only wells get a jump-to-production picker instead of a
  dead end; honest latency estimate (~60 s Sonnet); per-run token/cost/latency panel;
  the holdout chip is derived from the artifact (no 0.72 vs 0.722 drift).
- **Failure Risk:** the threshold slider now drives the table (High flag + filter);
  the latest-reading vs windowed-score column basis is disclosed.
- **Run-Life:** OOF-vs-full-fit caption; right-censored wells flagged (`> horizon`);
  axis relabeled "run-days ahead"; per-well suspected failure mode shown.
- **Injection Allocation:** gas cost + fleet-wide scope surfaced; `binding` derived
  from the allocator's own result.
- **Well Case File:** now charted (oil-rate + GLPC sparklines), shows failure-mode
  evidence, computes a **self-contained nodal operating point from the seed**, and
  notes prodpy-unavailable / SCADA-only cases explicitly.
- **Data Sources:** monthly upload column relabeled "Latest Month Avg (BOPD)".

### Design sensitivity + probabilistic economics (decision levers)
- **Operating-point & stage-count tornadoes.** Nodal shows how the operating RATE swings
  as each uncertain seed input ranges over a plausible band (reservoir pressure ±15%, API
  ±4, tubing ID ±0.2 in, GLR ±25%, water cut ±0.10), others fixed; Lift shows the same for
  the ESP STAGE COUNT (reservoir pressure, viscosity, water cut, depth). Turns the
  seeded what-if into a "what-if with bounds" and points at the highest-value measurement
  to acquire — the question a PE asks the moment they see formation-typical assumptions.
- **Probabilistic intervention economics (Monte-Carlo).** AI Well Review and the Case File
  now show P10/P50/P90 NPV, probability-of-payout, the NPV distribution, and a tornado of
  the input swings — via `pec.simulate_intervention` (10k trials over rate/decline/price
  uncertainty) using the SAME calibrated cost/uplift the point estimate uses, so the
  probabilistic view is consistent with the headline number. Keyless, deterministic (seed 42).

### Adversarial-review fixes (caught before commit)
- **HIGH — numpy 2.x crash:** the new EUR-to-econ-limit code used `np.trapz`, removed in
  numpy 2.x (the repo runs 2.4.6 on Python 3.11); a Python-3.9 sandbox masked it. Bound to
  `np.trapezoid` with a fallback shim. (All tests now run under the repo venv.)
- **MEDIUM — design seed honesty:** `well_design_seed` took the literal last production
  record, so a shut-in-tail well fabricated an "assumed" water cut/GOR labeled "measured";
  now it uses the last *producing* month (and falls back to honestly-assumed when there is
  no production).
- **LOW:** live-oil viscosity evaluated at the bubble point (consistent dissolved gas), not
  reservoir pressure; the Lift Stages tooltip no longer claims "exceeds runout" on a feasible
  TDH-capped design; the gas-lift fit-validation table labels params `blpd` (gross liquid),
  matching the rest of the page.

### Infra, perf & honesty
- Context bar now carries the **gas cost** (so Gas-Lift / Injection pages can't
  contradict the global deck). Heavy pandas frames moved from `cache_resource` to
  `cache_data` (copy-on-return — no shared-singleton mutation risk).
- App self-heal (`rmtree __pycache__` + module eviction) is gated to **once per
  session** (was every rerun); views are **lazily imported per navigation**.
- Removed dead vendored plumbing (`suite_nav`, `well_cross_links`, `SUITE_APPS`,
  `header`, `setup_page`, `how_to`) and the duplicate block-container padding rule.
- **67 tests** (was 54): new numeric-invariant pins for the design seed (incl. a
  shut-in-tail provenance regression guard), lift physics (feasibility / runout / viscosity
  / gas-lift economics), the probabilistic-economics engine (ordering / determinism /
  tornado), survival metrics vs the KM baseline, PVT sanity, and a committed-artifacts
  cold-start guard. CI no longer bootstraps twice. WPS component → 0.2.3 (lift.py physics).

## v0.2.0 — 2026-06-14

Pre-PE-review hardening pass: faster load, a synthetic-first demo experience,
real well-level drill-down, and a sweep of correctness / honesty fixes from a
full per-page audit.

### Performance & first load
- **No more "first-time setup" banner.** The deterministic synthetic artifacts
  (ESP SCADA + labels, gas-lift fleet + ground truth, trained ESP model +
  training report) are now **committed** instead of regenerated on every cold
  start, so the app opens with no ~30 s ESP-training step. `core.bootstrap()`
  still self-heals an environment that is genuinely missing them (and retrains a
  model artifact that fails to load under a different sklearn/xgboost).
- The sidebar well list is built from a cached, glob-only id list instead of
  reparsing 100+ SCADA/injection CSVs on every rerun.
- `esp_scores` reuses the cached model + features (was loaded/featurized up to
  ~2.5× on first risk page); `anthropic` is imported lazily (BYOK path only);
  Artificial Lift Design and the RTA built-in series are now cached.

### Data & navigation
- **Synthetic demo fleet is the default universe** (opens on the flagship well
  `well_013`, which has production + SCADA + injection so every page has data).
  Real Colorado ECMC remains available as an optional secondary source.
- The **Production Data Source** toggle now actually **scopes** the well list and
  Well Browser (it previously only re-picked a well and filtered nothing).

### Drill-down & well pickers
- **Well Browser**: new per-well **drill-down card** (registry/completion
  metadata, latest-rate KPIs, oil-rate sparkline, availability pills) + an
  in-page selector to retarget the workbench to **any** well. Removed the
  positional row-click selection that **selected the wrong well after the table
  was sorted**.
- **Gas-Lift Optimum**: added the missing **in-page well picker** (never blank;
  defaults to an analyzable injection well) + a **fitted-vs-ground-truth**
  parameter-recovery panel.
- **Failure Risk**: added an in-page picker over scorable wells (no longer
  silently swaps to the top-risk well behind a mismatched header).

### Correctness & honesty fixes (from the audit)
- **Injection Allocation**: sensible default compressor cap (was far below
  demand, which displayed a −$34.8k/day "gain"); now shows the **shadow price λ**
  and an apples-to-apples **same-gas reallocation gain**.
- **Run-Life**: RUL bars colored by absolute lead-time tiers (red <30 d / amber
  30–60 d / green >60 d) instead of a relative scale that painted a 45-day well
  green.
- **Decline & EUR**: Monte-Carlo fan now starts at the last observed point (no
  longer backtracks under actuals on shut-in-tail wells); EUR vs economic-limit
  wording corrected.
- **AI Well Review**: generated review + download now persist (the download click
  no longer discards the paid result); eval/model framing scoped honestly to the
  measured model.
- **Failure Risk** reliability diagram relabeled as the raw booster's OOF curve
  (the shipped scores apply Platt on top).
- **Well Case File**: the injection gas cost behind the gas-lift dollar figures
  is now shown on-screen and in the exported brief.
- **Nodal / Artificial Lift Design**: labeled as engineer-supplied design
  scenarios (inputs are not auto-loaded from the well file).
- **Sources & BYOD**: synthetic provenance leads; user uploads no longer carry
  the green "REAL DATA" badge (shown as in-session uploads of your own data).

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
