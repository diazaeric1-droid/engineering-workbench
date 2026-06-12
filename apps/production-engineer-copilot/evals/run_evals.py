"""Run the agent against the eval set and compute agreement rate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml
from rich.console import Console
from rich.table import Table

from src.agent import run_review


CASES_FILE = Path(__file__).parent / "cases.yaml"
RESULTS_DIR = Path(__file__).parent / "results"


# Synonym groups — a recommendation matches if ANY of the listed phrases appear in the report.
# Keys are the strings used in cases.yaml's expected_primary_recommendation field.
RECOMMENDATION_SYNONYMS = {
    "acid_stimulation": ["acid stimulation", "acid stim", "matrix acidiz", "diverted acid"],
    "scale_treatment": ["scale treatment", "scale inhibitor", "scale squeeze", "acid stim", "acidize", "chemical treatment"],
    "esp_swap": ["esp swap", "pump swap", "right-siz", "replace the esp", "esp replacement"],
    "esp-to-beam_conversion": ["esp-to-beam", "esp to beam", "beam pump conversion", "convert to beam"],
    "gas_separator": ["gas separator", "downhole separator", "vsd frequency", "gas-lock mitigation"],
    "gas_lift_optimization": ["gas lift optimization", "injection rate", "lift optimization", "valve check", "deliquification"],
    "pump-off_controller": ["pump-off controller", "pump off controller", "poc", "rod string evaluation"],
    "paraffin_treatment": ["paraffin", "hot oil", "wax treatment", "wireline plunger"],
    "workover": ["workover", "rig", "rod replacement", "well intervention"],
    "monitor": ["continue routine surveillance", "no intervention", "monitor", "routine surveillance", "no action warranted"],
    "p&a": ["p&a", "plug and abandon", "abandonment", "abandon the well"],
    "insufficient_data": ["insufficient data", "more data", "cannot recommend", "not enough data",
                          "additional data", "data gap", "unable to fit", "too few points",
                          "request additional", "need more"],
}

KEYWORD_SYNONYMS = {
    "low intake pressure": ["intake pressure", "low intake", "intake = ", "intake at "],
    "below POR": ["below por", "outside por", "below the por", "below the preferred operating range"],
    "high amps": ["high amps", "over-amp", "amp overload", "amperage above", "high amperage"],
    "fluid pound": ["fluid pound", "incomplete fillage", "low fillage", "pump-off", "poor fillage"],
    "parted rods": ["parted rod", "rod string failure", "broken rod", "flat card", "no fluid load"],
    "liquid loading": ["liquid loading", "loading up", "slugging", "turner velocity"],
    "p&a candidate": ["p&a", "plug and abandon", "uneconomic", "stripper well"],
    "end of ESP": ["end of esp", "esp economic life", "esp run life", "re-fail", "refail",
                   "lifecycle", "beam conversion", "convert to beam"],
    "insufficient data": ["insufficient data", "more data", "too few", "cannot fit",
                          "unable to fit", "not enough data", "data gap"],
    "more data": ["more data", "additional data", "request", "need more", "pending"],
    "pump-off": ["pump-off", "pump off", "poc", "fillage", "fluid pound"],
}


def _matches_with_synonyms(text: str, term: str, synonym_map: dict[str, list[str]]) -> bool:
    text_l = text.lower()
    term_l = term.lower()
    if term_l in text_l:
        return True
    for synonym in synonym_map.get(term, []):
        if synonym.lower() in text_l:
            return True
    return False


def keyword_hit_rate(report: str, keywords: list[str]) -> float:
    if not keywords:
        return 1.0
    hits = sum(1 for kw in keywords if _matches_with_synonyms(report, kw, KEYWORD_SYNONYMS))
    return hits / len(keywords)


def recommendation_matches(report: str, expected: str) -> bool:
    """LENIENT match: expected recommendation (or any synonym) appears ANYWHERE in the report.

    Kept for the dev set and the confusion-matrix extraction, but NOT used to grade the blind
    holdout — it is too generous in two ways that together inflated the holdout to a phantom
    1.00: (1) substring-anywhere credits a class even when the report *discusses and rejects*
    it lower down, and (2) the synonym sets deliberately OVERLAP across near-miss classes
    (e.g. ``scale_treatment`` lists "acid stim", ``esp_swap`` shares vocabulary with
    ``gas_separator``), so an acid-stim report scores a hit on the scale expectation and vice
    versa. Use :func:`recommendation_matches_strict` for an honest, exact-class grade.
    """
    return _matches_with_synonyms(report, expected.replace("_", " "), RECOMMENDATION_SYNONYMS) or \
           _matches_with_synonyms(report, expected, RECOMMENDATION_SYNONYMS)


def _canonical_class(label: str) -> str:
    """Normalise a recommendation class for EXACT comparison.

    Collapses the underscore/hyphen/space spelling differences (``esp-to-beam_conversion`` vs
    ``esp to beam conversion``) so the comparison is on the class identity only. Near-miss
    classes that share treatment vocabulary (acid stim vs scale; esp swap vs gas separator)
    stay DISTINCT — that distinction is exactly what the honest grade must preserve.
    """
    return label.strip().lower().replace("_", " ").replace("-", " ").replace("  ", " ")


def recommendation_matches_strict(report: str, expected: str) -> bool:
    """STRICT, honest grade: the report's actual #1 recommendation must be EXACTLY the
    expected intervention class.

    No substring-anywhere credit and no near-miss synonym leakage: we extract the report's
    primary recommendation with :func:`predicted_label` (which reads the #1 row of the
    recommendations section) and require an exact canonical-class match. A report that lands
    on a neighbouring class — even one sharing chemistry/vocabulary — is scored WRONG, which
    is the point of a blind holdout.
    """
    return _canonical_class(predicted_label(report)) == _canonical_class(expected)


def predicted_label(report: str) -> str:
    """Best-effort extraction of the report's PRIMARY recommendation, for the confusion
    matrix. Scans only the top of the 'Ranked recommendations' section (where rank #1 lives)
    and returns the canonical label whose synonym appears earliest. Falls back to scanning
    the whole report. Returns 'unknown' if nothing matches."""
    text_l = report.lower()
    # Prefer the recommendations section so we read the #1 row, not an option discussed lower.
    anchor = text_l.find("recommend")
    window = text_l[anchor: anchor + 600] if anchor >= 0 else text_l

    best_label, best_pos = "unknown", 10**9
    for label, syns in RECOMMENDATION_SYNONYMS.items():
        for phrase in [label.replace("_", " ")] + syns:
            pos = window.find(phrase.lower())
            if 0 <= pos < best_pos:
                best_label, best_pos = label, pos
    if best_label != "unknown":
        return best_label
    # whole-report fallback
    for label, syns in RECOMMENDATION_SYNONYMS.items():
        if recommendation_matches(report, label):
            return label
    return "unknown"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                        help="Run only the first N cases (useful for quick checks)")
    parser.add_argument("--case", type=str, default=None,
                        help="Run a single case by id (e.g., case_005)")
    parser.add_argument("--holdout", action="store_true",
                        help="Run the BLIND holdout set (evals/holdout_cases.yaml). Report this "
                             "number as the headline — the dev set is what the prompt was tuned on.")
    parser.add_argument("--judge", action="store_true",
                        help="Also score each report 1-5 on 4 rubric axes with an LLM judge "
                             "(requires ANTHROPIC_API_KEY; adds cost).")
    parser.add_argument("--lenient", action="store_true",
                        help="Grade with the legacy substring/synonym matcher instead of the "
                             "strict exact-class grade. The blind holdout grades STRICT by "
                             "default (exact intervention-class match, no near-miss credit); "
                             "this flag is for debugging / comparing against the old number.")
    args = parser.parse_args()

    # The blind holdout is graded STRICTLY by default (exact #1-recommendation class match,
    # no synonym-overlap / substring-anywhere credit). The dev set keeps the lenient grade it
    # was tuned against unless --lenient/--strict is overridden. --lenient forces lenient.
    strict_grade = args.holdout and not args.lenient

    console = Console()
    RESULTS_DIR.mkdir(exist_ok=True)

    cases_file = CASES_FILE.parent / "holdout_cases.yaml" if args.holdout else CASES_FILE
    results_dir = RESULTS_DIR / "holdout" if args.holdout else RESULTS_DIR
    results_dir.mkdir(parents=True, exist_ok=True)
    summary_name = "summary_holdout.json" if args.holdout else "summary.json"

    judge_fn = None
    if args.judge:
        from evals.judge import judge_report  # lazy import (needs the SDK + key)
        judge_fn = judge_report

    with cases_file.open() as f:
        cases = yaml.safe_load(f)["cases"]

    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
    if args.limit:
        cases = cases[: args.limit]

    table = Table(title="Eval results")
    table.add_column("Case", style="cyan")
    table.add_column("Pattern")
    table.add_column("Keyword", justify="right")
    table.add_column("Recommendation", justify="center")

    total_keyword = 0.0
    total_recommend = 0
    summary_rows = []

    if judge_fn:
        table.add_column("Judge", justify="right")
    confusion: dict[tuple[str, str], int] = {}

    for case in cases:
        console.print(f"\n[bold cyan]Running {case['id']} ({case.get('notes', '')})...[/]")
        try:
            report = run_review(case["well_file"])
        except Exception as e:
            console.print(f"[red]FAILED: {e}[/]")
            row = [case["id"], case.get("notes", ""), "ERR", "ERR"]
            if judge_fn:
                row.append("ERR")
            table.add_row(*row)
            summary_rows.append({"id": case["id"], "error": str(e)})
            continue

        out_path = results_dir / f"{case['id']}.md"
        out_path.write_text(report)

        kw_rate = keyword_hit_rate(report, case.get("expected_diagnosis_keywords", []))
        expected_raw = case["expected_primary_recommendation"]
        expected = expected_raw.replace("_", " ").lower()
        predicted = predicted_label(report)
        lenient_match = recommendation_matches(report, expected_raw)
        strict_match = recommendation_matches_strict(report, expected_raw)
        # The headline `recommendation_match` is STRICT on the holdout, lenient on the dev set.
        rec_match = strict_match if strict_grade else lenient_match
        confusion[(expected_raw, predicted)] = confusion.get((expected_raw, predicted), 0) + 1

        row_data = {
            "id": case["id"],
            "notes": case.get("notes", ""),
            "lift": case.get("lift", ""),
            "archetype": case.get("archetype", ""),
            "expected": expected,
            "predicted": predicted,
            "keyword_hit_rate": kw_rate,
            # Headline grade (strict on holdout); both raw signals kept for auditability.
            "recommendation_match": rec_match,
            "strict_match": strict_match,
            "lenient_match": lenient_match,
            "grade_mode": "strict" if strict_grade else "lenient",
        }

        judge_cell = ""
        if judge_fn:
            try:
                scores = judge_fn(report, expected_raw, case.get("expected_diagnosis_keywords", []))
                row_data["judge"] = scores
                judge_cell = f"{scores.get('overall', 0):.1f}"
            except Exception as e:  # judge is best-effort; never fail the run on it
                row_data["judge_error"] = str(e)
                judge_cell = "ERR"

        row = [case["id"], case.get("notes", "")[:30], f"{kw_rate:.0%}", "✓" if rec_match else "✗"]
        if judge_fn:
            row.append(judge_cell)
        table.add_row(*row)
        total_keyword += kw_rate
        total_recommend += int(rec_match)
        summary_rows.append(row_data)

    n = len(cases)
    console.print(table)
    grade_label = "STRICT exact-class" if strict_grade else "lenient synonym"
    console.print(
        f"\n[bold]Overall ({'HOLDOUT' if args.holdout else 'dev'}, {grade_label}):[/] "
        f"keyword {total_keyword / n:.0%} · "
        f"recommendation {total_recommend}/{n} ({total_recommend / n:.0%})"
    )

    # ---- per-class metrics --------------------------------------------------
    by_class: dict[str, list[bool]] = {}
    for r in summary_rows:
        if "recommendation_match" in r:
            by_class.setdefault(r["expected"], []).append(r["recommendation_match"])
    cls_table = Table(title="Per-class recommendation agreement")
    cls_table.add_column("Expected class", style="cyan")
    cls_table.add_column("Agreement", justify="right")
    cls_table.add_column("n", justify="right")
    for cls, hits in sorted(by_class.items(), key=lambda kv: sum(kv[1]) / len(kv[1])):
        cls_table.add_row(cls, f"{sum(hits) / len(hits):.0%}", str(len(hits)))
    console.print(cls_table)

    # ---- confusion matrix (expected -> predicted) ---------------------------
    miss_rows = [(e, p, c) for (e, p), c in sorted(confusion.items()) if e.replace("_", " ") != p.replace("_", " ")]
    if miss_rows:
        conf_table = Table(title="Confusion (where predicted ≠ expected)")
        conf_table.add_column("Expected", style="cyan")
        conf_table.add_column("Predicted", style="red")
        conf_table.add_column("count", justify="right")
        for e, p, c in miss_rows:
            conf_table.add_row(e, p, str(c))
        console.print(conf_table)

    out_summary = results_dir / summary_name
    out_summary.write_text(json.dumps(summary_rows, indent=2))
    console.print(f"\n[dim]Reports saved to {results_dir}/, summary in {summary_name}[/]")


if __name__ == "__main__":
    main()
