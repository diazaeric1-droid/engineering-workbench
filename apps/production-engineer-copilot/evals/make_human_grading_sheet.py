"""Build a BLIND human-grading sheet so 1-3 real production engineers can score the
agent's reports independently — the inter-rater number is the most defensible metric
for the flagship narrative ("a panel of PEs agreed with N% of the agent's calls").

It anonymizes each report behind a random-but-deterministic code (no case id, no expected
label visible) and emits:
  - evals/human_grading/<code>.md         : the report to read
  - evals/human_grading/grading_sheet.csv : one row per report with blank score columns
  - evals/human_grading/ANSWER_KEY.csv    : code -> case id + expected label (grader must NOT open)

Usage:
    python -m evals.make_human_grading_sheet                 # from evals/results/
    python -m evals.make_human_grading_sheet --holdout       # from evals/results/holdout/
"""
from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path

import yaml

HERE = Path(__file__).parent


def _code(case_id: str) -> str:
    # Deterministic 6-char code (stable across runs, no Math.random needed).
    return "R" + hashlib.sha1(case_id.encode()).hexdigest()[:5].upper()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdout", action="store_true")
    args = ap.parse_args()

    cases_file = HERE / ("holdout_cases.yaml" if args.holdout else "cases.yaml")
    results_dir = HERE / "results" / ("holdout" if args.holdout else "")
    out_dir = HERE / "human_grading"
    out_dir.mkdir(parents=True, exist_ok=True)

    cases = yaml.safe_load(cases_file.read_text())["cases"]

    grading_rows = []
    answer_rows = []
    n = 0
    for case in cases:
        report_path = results_dir / f"{case['id']}.md"
        if not report_path.exists():
            continue
        code = _code(case["id"])
        (out_dir / f"{code}.md").write_text(report_path.read_text())
        grading_rows.append({
            "code": code,
            "diagnosis_1to5": "", "recommendation_1to5": "",
            "economics_1to5": "", "restraint_1to5": "",
            "would_you_accept_this_call_Y_N": "", "grader_notes": "",
        })
        answer_rows.append({
            "code": code, "case_id": case["id"],
            "expected_primary_recommendation": case["expected_primary_recommendation"],
            "archetype": case.get("archetype", ""),
        })
        n += 1

    with (out_dir / "grading_sheet.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(grading_rows[0].keys()))
        w.writeheader(); w.writerows(grading_rows)
    with (out_dir / "ANSWER_KEY.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(answer_rows[0].keys()))
        w.writeheader(); w.writerows(answer_rows)

    print(f"Wrote {n} anonymized reports + grading_sheet.csv + ANSWER_KEY.csv to {out_dir}/")
    print("Hand graders the <code>.md files and grading_sheet.csv. Keep ANSWER_KEY.csv closed.")


if __name__ == "__main__":
    main()
