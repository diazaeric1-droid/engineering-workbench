# Sample Agent Outputs

Curated examples from the v0.1 eval run (May 28, 2026). Each is the agent's raw output, lightly de-fluffed (tool-call preamble removed) but otherwise unedited.

| File | Scenario | Why it's interesting |
|---|---|---|
| [`../sample_review.md`](../sample_review.md) | ED-001H — Compound scale + gas interference + below POR | The flagship demo: agent surfaces a sequenced 3-step workover (gas stabilization → acid → ESP swap) rather than chasing single-intervention NPV |
| [`case_005_gas_interference.md`](case_005_gas_interference.md) | ED-005H — Gas interference, critical 14 psi intake | Agent correctly defers ESP swap, recommends low-cost VSD + separator service first; explicit "if Rank 1 fails, then Rank 2" sequencing |
| [`case_014_healthy_beam_pump.md`](case_014_healthy_beam_pump.md) | ED-014H — Healthy beam pump on type curve | Demonstrates the agent **not** inventing interventions when diagnostics are clean; explicit "(Hold: Acid stimulation) — would only become a candidate if..." triggers documented |
| [`case_020_p_and_a.md`](case_020_p_and_a.md) | ED-020H — Sub-economic stripper, 3.75 BOPD | Agent recommends P&A and explicitly rejects workover/stim with negative-NPV evidence; closes with regulatory + LOE considerations a VP would actually use |

## v0.1 eval summary

- **20 cases** spanning 8 intervention types
- **Primary recommendation agreement:** 18 / 20 (0.90)
- **Diagnosis keyword hit rate:** 0.90
- See [`../results/summary.json`](../results/summary.json) for per-case breakdown (note: `results/` is gitignored; regenerate locally with `python -m evals.run_evals`)

## Reproducing

```bash
python -m evals.run_evals               # full set
python -m evals.run_evals --case case_005   # single case
python -m evals.run_evals --limit 5     # smoke check
```

Reports are written to `evals/results/<case_id>.md` and a `summary.json` rollup.
