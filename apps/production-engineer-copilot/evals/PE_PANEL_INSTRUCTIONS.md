# PE Inter-Rater Grading Panel — Instructions

## What this is

A **blind inter-rater agreement panel.** One to three real production engineers
independently read ~20 of the agent's well reports and record what *they* would
recommend, with no knowledge of the agent's call or the "expected" label.

We then measure how often the panel's calls match the agent's. That number —
*"a panel of PEs agreed with N% of the agent's recommendations"* — is the most
defensible credibility credential we have. The synthetic holdout is already
saturated (18/18 = 1.00), so a higher synthetic score proves nothing; an
independent human panel does. It also gives an inter-rater baseline (how often
two PEs agree with *each other*), which is the honest ceiling for "agreement."

## The artifact (already generated)

Regenerate any time with (from the repo root):

```bash
.venv/bin/python -m evals.make_human_grading_sheet --holdout   # 18 holdout reports
.venv/bin/python -m evals.make_human_grading_sheet             # 41 dev reports (if a larger panel is wanted)
```

Output lands in `evals/human_grading/`:

| File | Who sees it | Contents |
|---|---|---|
| `R<code>.md` (×18) | **Grader** | One anonymized well report. Filename is a deterministic hash code — no case id. |
| `grading_sheet.csv` | **Grader** | One blank row per code: `code, diagnosis_1to5, recommendation_1to5, economics_1to5, restraint_1to5, would_you_accept_this_call_Y_N, grader_notes`. |
| `ANSWER_KEY.csv` | **Owner only — keep closed** | `code → case_id, expected_primary_recommendation, archetype`. Used only to score after grading. |

**Blindness verified:** the grader-facing files contain no `case_id`, no
`expected_*` label, and no `archetype`. The score columns ship empty. The
report bodies do contain the agent's *own* narrative recommendation — that is
intentional: the grader's job is to read the agent's reasoning and decide
whether they would accept the call.

> Caveat (known, not blocking): report headers carry sequential well names
> (`ED-001H`…`ED-018H`) and API numbers (`42-109-1000N`) that track case order.
> They reveal *ordering*, never the expected label, so blindness to the answer
> holds. Don't fix this by editing analyzer/eval code; if it matters for a
> formal panel, shuffle/strip headers in a post-step.

## How to grade

1. Hand each grader the `R<code>.md` files and a copy of `grading_sheet.csv`.
   **Do not share `ANSWER_KEY.csv`.**
2. For each report, the grader:
   - Reads the well summary, diagnosis, and ranked recommendations.
   - Decides their **own primary recommendation** for the well (e.g. `esp_swap`,
     `scale_treatment`, `acid_stimulation`, `gas_separator`, `monitor`,
     `workover`, `p&a`, `pump-off_controller`, `gas_lift_optimization`,
     `paraffin_treatment`, `esp-to-beam_conversion`, `insufficient_data`).
   - Records it. Two ways, pick one:
     - **Simplest:** write the recommendation in `grader_notes`, plus `Y/N` in
       `would_you_accept_this_call_Y_N` (would you sign off on the agent's call).
     - **Fuller:** also score `diagnosis / recommendation / economics / restraint`
       1–5 (5 = exactly what I'd write; 1 = wrong/unsafe). "Restraint" =
       did it avoid recommending unnecessary intervention on a healthy well.
3. One row per code, all ~20 codes. ~5–10 min per report; budget ~2–3 hrs.
4. Save the filled sheet as `grading_sheet__<grader-initials>.csv` in
   `evals/human_grading/` (one file per grader so inter-rater can be computed).

## How agreement is computed

After grading, join each grader's call back to the agent's via the key:

- `grading_sheet__<initials>.csv` gives `code → grader recommendation`.
- `ANSWER_KEY.csv` gives `code → case_id`.
- `evals/results/holdout/summary_holdout.json` gives `case_id → predicted`
  (the agent's recommendation) and `expected` (the ground-truth label).

Two numbers fall out:

1. **PE↔agent agreement** — fraction of codes where the grader's recommendation
   matches the agent's `predicted`. This is the headline credential.
2. **PE↔PE inter-rater agreement** — with ≥2 graders, the fraction where the
   graders agree *with each other* (and Cohen's/Fleiss' κ if you want a
   chance-corrected figure). This is the honest ceiling: the agent can't be
   expected to beat the rate at which two humans agree.

Optionally also report **PE↔ground-truth** (grader vs. `expected`) to show the
panel itself is competent on these cases. Normalize label spelling/spacing
(e.g. `esp_swap` vs `esp swap`) before matching.

> Scoring is a small post-hoc join — it does **not** require touching any
> eval/agent/analyzer code. A throwaway pandas snippet over the three files
> above produces all three rates.

## Status

- Sheet generated: **18 anonymized holdout reports + blank grading sheet + closed answer key**, in `evals/human_grading/`.
- **Blocked on a human.** The actual grading must be done by a real production
  engineer — Eric, and ideally one or two PE peers for the inter-rater number.
  Nothing here is auto-gradable; that's the whole point.
