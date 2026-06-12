---
title: Production Engineer Copilot
emoji: 🛢️
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: true
license: mit
---

# Production Engineer Copilot

> An open-source AI agent that performs a complete well review — decline analysis, artificial lift diagnostics, intervention recommendations, and economics — in 60 seconds.

Built by a Staff Production Engineer (ex-OXY, ex-Shell) who spent 9 years doing this work by hand.

[![Live Demo](https://img.shields.io/badge/demo-live-brightgreen)](https://pe-copilot.streamlit.app)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue)](https://www.python.org/)
[![Eval](https://img.shields.io/badge/eval-0.72%20strict%20blind%20holdout-blue)](evals/sample_review.md)

**Try it now → [pe-copilot.streamlit.app](https://pe-copilot.streamlit.app)**

---

## What it does

Drop in a well file (decline curve data, dyno cards or ESP readings, last 30 days of SCADA, completion details). The agent returns:

1. **Current state diagnosis** — is the well performing to type curve? Where is it deviating and why?
2. **Ranked intervention candidates** — acid stim, ESP swap, ESP-to-beam conversion, P&A, etc.
3. **Quick economics** — incremental BOE, treatment cost, NPV, payout time
4. **Interactive chat** — "why acid over a workover?" "what's the second-best option?"

Output is a one-page review that mirrors the format you'd hand to a VP Production on a Monday morning.

**See real samples:**
- [`evals/sample_review.md`](evals/sample_review.md) — flagship demo: Delaware Basin ESP with compound scale + gas + below-POR signature; agent surfaces a sequenced 3-step workover
- [`evals/samples/case_005_gas_interference.md`](evals/samples/case_005_gas_interference.md) — gas-interference well: agent defers ESP swap, recommends low-cost VSD + separator first
- [`evals/samples/case_014_healthy_beam_pump.md`](evals/samples/case_014_healthy_beam_pump.md) — healthy beam pump: agent correctly recommends "continue surveillance" rather than inventing interventions
- [`evals/samples/case_020_p_and_a.md`](evals/samples/case_020_p_and_a.md) — sub-economic stripper: agent recommends P&A with explicit negative-NPV evidence
- [Index of all samples](evals/samples/README.md)

## Why this exists

Production engineers spend 30–50% of their time on routine well reviews. The work is pattern-heavy, data-driven, and follows a repeatable framework — which makes it a textbook case for agentic AI. This repo is a reference implementation of that pattern, designed to be forked and adapted to your operator's data sources.

## Quick start

```bash
git clone https://github.com/diazaeric1-droid/production-engineer-copilot
cd production-engineer-copilot
pip install -e .
cp .env.example .env  # add your ANTHROPIC_API_KEY
python -m src.agent --well data/synthetic/well_001.json
```

For the interactive demo:
```bash
streamlit run demo/app.py
```

## Architecture

```
┌──────────────┐      ┌─────────────────┐      ┌──────────────────┐
│  Well File   │ ───> │  Agent Loop     │ ───> │  Review (MD)     │
│  (JSON/CSV)  │      │  (Claude + tools)│      │  + interactive   │
└──────────────┘      └─────────────────┘      └──────────────────┘
                              │
                ┌─────────────┼──────────────┐
                ▼             ▼              ▼
         decline_curve   esp_diagnostics   economics
         (Arps fit +     (POR + thrust)    (risked NPV +
          type curve +   dyno_card          ESP economic
          water/GOR)     (fillage class)    life)
```

The agent has access to deterministic analyzers (no hallucinated math) and uses Claude as the reasoning layer to decide which to call and how to synthesize results.

## Evaluation

A **41-case parameterized dev set** plus a **blind 18-case holdout**, spanning every
intervention type (acid stim, scale treatment, ESP swap, ESP-to-beam conversion, gas
separator, gas-lift optimization, pump-off controller, paraffin treatment, workover, P&A,
healthy-well "continue surveillance" controls) and boundary cases (two-signal scale-with-gas,
sequenced acid-then-swap, and insufficient-data wells where the correct answer is *"get more
data"*).

Two design choices make the number honest:
- **No answer leak.** Each well file's `notes` carry only raw field observations + distractors —
  never the diagnosis or recommendation. Expert labels live only in `cases.yaml`, which the
  agent never sees. The agent must reason from tool signals, not parrot the notes (enforced by
  a unit-test invariant). Every archetype's discriminating signal is verified reachable from the
  deterministic tools alone.
- **Blind holdout.** The prompt is tuned on the dev set; the holdout (separate seed + id range)
  is run once and reported as the headline. A defensible holdout number beats an inflated
  self-graded one.

```bash
python -m evals.run_evals                 # 41-case dev set (+ per-class + confusion matrix)
python -m evals.run_evals --holdout       # blind 18-case holdout — the headline number
python -m evals.run_evals --judge         # add LLM-as-judge rubric scores (diagnosis/rec/econ/restraint)
python data/synthetic/generate.py --both  # regenerate dev + holdout wells
python -m evals.make_human_grading_sheet  # blind sheet for an inter-rater PE panel
```

Scoring goes beyond keyword-match: per-class agreement, an expected→predicted confusion
matrix, and an optional 1-5 LLM-as-judge rubric (diagnosis / recommendation / economics /
restraint), so systematic confusions surface instead of hiding in one blended number.

**Current:**

| Set | Recommendation agreement | Diagnosis keyword hit rate |
|---|---|---|
| Dev (41 cases, lenient synonym grade) | 41 / 41 (1.00) | 0.87 |
| **Blind holdout (18 cases, strict exact-class grade)** | **13 / 18 (0.72)** | 0.92 |

The blind holdout is graded **strictly**: the report's actual #1 recommendation must be the
**exact** intervention class, with no credit for near-miss classes that share treatment
vocabulary. An earlier build reported a phantom **1.00** here — the recommendation grader was
lenient (it credited a class if any synonym appeared *anywhere* in the report, and its synonym
sets overlapped across neighbouring classes, so an acid-stim report scored a hit on a scale
expectation and vice-versa). Tightening to an exact-class grade drops the honest number to
**0.72 (13/18)**: the five misses are real near-miss confusions (acid-stim↔scale,
esp-swap↔gas-separator, monitor↔gas-lift-optimization, insufficient-data↔monitor) the lenient
grader was hiding. The CI gate floors at **0.70** against this strict number, and the dev set
is still the lenient signal the prompt was tuned against. *Caveat for honesty:* these are
synthetic wells with clean, separable signatures; real wells have overlapping, noisier ones —
the next credibility step is real operator data and the blind inter-rater PE panel
(`make_human_grading_sheet.py`), not a higher synthetic number.

## Beyond the synthetic score (v0.5)

The synthetic agreement is saturated; these levers prove it's real, harden it, and show value.

- **Runs on real public data.** `src/adapters/public_data.py` ingests the **Volve** (Equinor open
  North Sea dataset) and generic **NDIC / Texas RRC** schemas — handling Sm³→bbl, monthly→daily
  rates, bar→psi. The agent reviewed real Volve producer 15/9-F-12 and correctly flagged a subsea
  ESP running at half its POR floor with a rising 54% water cut (`evals/real_reviews/`). See
  [`data/real/README.md`](data/real/README.md) to point it at the genuine dataset.
- **Field / portfolio mode.** `python -m src.portfolio data/synthetic/well_*.json` ranks a whole
  field by **risked NPV / capital efficiency** — the "which of my 200 wells do I work over this
  quarter" triage a VP actually wants — fully deterministic, no API cost.
- **Cited economics.** `src/analyzers/assumptions.py` is a single, source-tagged source of truth
  (EIA price deck, SPE artificial-lift run-life, public LOE/SWD/cost ranges); the agent pulls it
  via a tool and risks every NPV by chance-of-success, deferred production, and water-disposal drag.
- **Robustness eval** (`python -m evals.adversarial`): **5/5** — resists prompt injection (notes
  ordering a P&A or a false all-clear) and degrades gracefully on missing/garbage/mislabeled data.
  Self-consistency 2/3 on a borderline well; `run_review(temperature=0)` for reproducible decoding.
- **Model accuracy/cost frontier** (`python -m evals.model_frontier`): Haiku and Sonnet both **100%**
  on a per-class subset, but **Haiku is ~4× cheaper (~$0.03/review) and ~2.4× faster** → the right
  default for this task.

| Model | Agreement | $/review | Latency |
|---|---|---|---|
| Claude Haiku 4.5 | 100% (12/12) | **$0.029** | 22.5s |
| Claude Sonnet 4.6 | 100% (12/12) | $0.117 | 54.7s |

## Roadmap

- [x] v0.1 — Decline curve + ESP diagnostics + economics + intervention heuristics + 20-case eval @ 0.90
- [x] v0.1 — Streamlit interactive demo
- [x] v0.4 — Dyno-card interpretation tool (closes the pump-off gap) + ESP-economic-life evaluator (closes the ESP-to-beam gap)
- [x] v0.4 — De-leaked + parameterized generator, 41-case dev set, blind 18-case holdout, boundary cases
- [x] v0.4 — Water-cut/GOR trend tool, VP-grade risked economics, LLM-as-judge + confusion matrix + inter-rater sheet
- [x] v0.5 — Multi-well portfolio mode (rank a field of wells by risked intervention NPV)
- [x] v0.5 — Real public-data adapter (Volve / NDIC / RRC), cited economics, adversarial + model-cost evals
- [ ] v0.6 — Connect to common SCADA/historian APIs (PI, Ignition)
- [ ] v0.7 — Chain into AFE Copilot — well review → intervention selection → draft AFE in one workflow

## License

MIT. Built for the community; use it however helps you.

## Contact

Eric Diaz II — [LinkedIn](https://www.linkedin.com/in/eric-a-diaz2) — diaz.a.eric1@gmail.com

Available for senior AI engineering roles and selective consulting engagements with E&P operators.
