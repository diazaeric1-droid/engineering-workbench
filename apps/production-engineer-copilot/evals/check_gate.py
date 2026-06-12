"""CI regression gate: fail the build if eval recommendation-agreement drops
below a threshold.

Parses a committed summary JSON (a list of per-case rows, each with a boolean
`recommendation_match`) and computes the overall agreement fraction. Exits non-zero
if agreement < threshold so the GitHub Actions job fails.

By default it guards the BLIND HOLDOUT (results/holdout/summary_holdout.json), which is
graded STRICTLY (exact intervention-class match, no near-miss synonym credit). The honest
strict holdout agreement is ~0.72, so the gate floors a little below that (0.70) — a real
regression-catching floor, not the phantom 1.00 the old lenient grader reported.

This intentionally reads the committed static summary (no API calls) — it is a regression
guard against the checked-in eval baseline, not a live re-run.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Guard the blind holdout (strict grade) by default; the dev summary is still selectable.
SUMMARY = Path(__file__).parent / "results" / "holdout" / "summary_holdout.json"


def agreement_from_summary(path: Path) -> tuple[float, int, int]:
    rows = json.loads(path.read_text())
    scored = [r for r in rows if "recommendation_match" in r]
    if not scored:
        raise ValueError("No scored rows (with recommendation_match) found in summary.json")
    hits = sum(1 for r in scored if r.get("recommendation_match"))
    return hits / len(scored), hits, len(scored)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.70,
                    help="Minimum recommendation agreement (default 0.70 — floors just below "
                         "the honest ~0.72 strict blind-holdout score).")
    ap.add_argument("--summary", type=Path, default=SUMMARY)
    args = ap.parse_args()

    if not args.summary.exists():
        print(f"ERROR: eval summary not found at {args.summary}", file=sys.stderr)
        return 2

    agreement, hits, total = agreement_from_summary(args.summary)
    print(f"Eval recommendation agreement: {agreement:.3f} ({hits}/{total})")
    print(f"Threshold: {args.threshold:.3f}")

    if agreement < args.threshold:
        print(f"FAIL: agreement {agreement:.3f} < threshold {args.threshold:.3f}", file=sys.stderr)
        return 1
    print("PASS: agreement meets the regression gate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
