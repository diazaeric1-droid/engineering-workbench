"""Locks the HONEST blind-holdout grade (Phase 2).

The blind holdout used to report a phantom 1.00 because the recommendation grader was
lenient in two compounding ways: it credited a class if any synonym appeared ANYWHERE in
the report (even while that option was discussed and rejected), and its synonym sets
deliberately OVERLAP across near-miss classes (acid stim vs scale, esp swap vs gas
separator). The strict grader requires the report's actual #1 recommendation to be EXACTLY
the expected intervention class. These tests pin that behaviour and the resulting number so
the honesty fix can't silently regress. All deterministic — no API key.
"""
import json
from pathlib import Path

from evals.run_evals import (
    recommendation_matches,
    recommendation_matches_strict,
    _canonical_class,
)

HOLDOUT_SUMMARY = Path(__file__).resolve().parents[1] / "evals" / "results" / "holdout" / "summary_holdout.json"


def _report_recommending(primary: str) -> str:
    """A minimal report whose #1 recommendation row names `primary`."""
    return (
        "## Well review\n\n"
        "## Ranked recommendations\n"
        f"1. {primary} — primary action, highest expected value.\n"
        "2. Continue routine surveillance otherwise.\n"
    )


def test_strict_rejects_acid_vs_scale_near_miss_that_lenient_accepts():
    # An ESP scale well (expected scale_treatment) whose report leads with ACID stim.
    report = _report_recommending("Acid stimulation")
    # Lenient is fooled: scale_treatment's synonyms include "acid stim".
    assert recommendation_matches(report, "scale_treatment") is True
    # Strict is honest: the #1 recommendation is acid stim, not scale -> WRONG.
    assert recommendation_matches_strict(report, "scale_treatment") is False
    # And it credits the genuinely-correct class.
    assert recommendation_matches_strict(report, "acid_stimulation") is True


def test_strict_rejects_insufficient_data_graded_as_monitor():
    # An insufficient-data well where the report instead says to monitor.
    report = _report_recommending("Continue routine surveillance — monitor")
    assert recommendation_matches_strict(report, "insufficient_data") is False
    assert recommendation_matches_strict(report, "monitor") is True


def test_strict_credits_exact_class_match():
    for cls, phrase in [
        ("gas_separator", "Install a downhole gas separator"),
        ("esp_swap", "Right-size ESP swap"),
        ("workover", "Workover rig to replace the parted rod string"),
        ("p&a", "Plug and abandon — uneconomic stripper"),
    ]:
        report = _report_recommending(phrase)
        assert recommendation_matches_strict(report, cls) is True, cls


def test_canonical_class_collapses_spelling_but_keeps_near_miss_distinct():
    assert _canonical_class("esp-to-beam_conversion") == _canonical_class("esp to beam conversion")
    # Near-miss classes must NOT collapse into one another.
    assert _canonical_class("acid_stimulation") != _canonical_class("scale_treatment")
    assert _canonical_class("esp_swap") != _canonical_class("gas_separator")


def test_committed_holdout_summary_is_strictly_graded_and_honest():
    rows = json.loads(HOLDOUT_SUMMARY.read_text())
    scored = [r for r in rows if "recommendation_match" in r]
    assert scored, "no scored holdout rows"
    # The committed summary must be strict-graded.
    assert all(r.get("grade_mode") == "strict" for r in scored)
    # Headline equals the strict signal row-by-row (no lenient leakage into the headline).
    assert all(bool(r["recommendation_match"]) == bool(r["strict_match"]) for r in scored)
    agreement = sum(1 for r in scored if r["recommendation_match"]) / len(scored)
    # Honest: NOT the old phantom 1.00, and at/above the CI gate floor.
    assert agreement < 1.0, "holdout is back at a suspicious 1.00 — grade leaked again"
    assert agreement >= 0.70, f"holdout {agreement:.3f} fell below the honest gate floor"
