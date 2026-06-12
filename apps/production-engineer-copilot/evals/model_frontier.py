"""Model accuracy/cost frontier — is Opus worth it, or is Haiku good enough?

Runs a representative SUBSET of the eval (one case per recommendation class by default)
across several Claude models and reports, per model: recommendation agreement, mean
tokens, mean latency, and estimated $/review. The point is the frontier — the cheapest
model that holds the accuracy — not another headline number.

    python -m evals.model_frontier                    # default subset, default models
    python -m evals.model_frontier --per-class 1 --models claude-haiku-4-5-20251001,claude-sonnet-4-6

Needs ANTHROPIC_API_KEY. Cost scales with (models × subset size).
"""
from __future__ import annotations

import argparse
import json
from collections import OrderedDict
from pathlib import Path

import yaml
from rich.console import Console
from rich.table import Table

from src.agent import run_review
from evals.run_evals import recommendation_matches

CASES_FILE = Path(__file__).parent / "cases.yaml"

# Approx public list price, USD per 1M tokens (input, output). Update as pricing changes.
PRICING = {
    "haiku":  (1.0, 5.0),
    "sonnet": (3.0, 15.0),
    "opus":   (15.0, 75.0),
}
DEFAULT_MODELS = ["claude-haiku-4-5-20251001", "claude-sonnet-4-6"]


def _price(model: str) -> tuple[float, float]:
    for k, v in PRICING.items():
        if k in model:
            return v
    return (3.0, 15.0)


def _subset(per_class: int) -> list[dict]:
    cases = yaml.safe_load(CASES_FILE.read_text())["cases"]
    by_class: "OrderedDict[str, list]" = OrderedDict()
    for c in cases:
        by_class.setdefault(c["expected_primary_recommendation"], []).append(c)
    out = []
    for _, group in by_class.items():
        out.extend(group[:per_class])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-class", type=int, default=1, help="Cases per recommendation class")
    ap.add_argument("--models", type=str, default=",".join(DEFAULT_MODELS))
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "results" / "model_frontier.json")
    args = ap.parse_args()

    console = Console()
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    subset = _subset(args.per_class)
    console.print(f"[bold]Frontier:[/] {len(subset)} cases × {len(models)} models "
                  f"= {len(subset)*len(models)} reviews")

    results = []
    for model in models:
        hits = n = in_tok = out_tok = 0
        lat = 0.0
        cost = 0.0
        pin, pout = _price(model)
        for c in subset:
            try:
                report, stats = run_review(c["well_file"], model=model, return_stats=True)
            except Exception as e:
                console.print(f"[red]{model} {c['id']} FAILED: {e}[/]")
                continue
            n += 1
            hits += int(recommendation_matches(report, c["expected_primary_recommendation"]))
            in_tok += stats["input_tokens"]; out_tok += stats["output_tokens"]
            lat += stats["latency_s"]
            cost += stats["input_tokens"] / 1e6 * pin + stats["output_tokens"] / 1e6 * pout
            console.print(f"[dim]{model.split('-')[1]:7} {c['id']} "
                          f"{'✓' if recommendation_matches(report, c['expected_primary_recommendation']) else '✗'} "
                          f"{stats['input_tokens']+stats['output_tokens']} tok {stats['latency_s']}s[/]")
        if n:
            results.append({
                "model": model, "agreement": hits / n, "hits": hits, "n": n,
                "mean_tokens": round((in_tok + out_tok) / n), "mean_latency_s": round(lat / n, 1),
                "cost_per_review_usd": round(cost / n, 4),
            })

    t = Table(title="Model accuracy / cost frontier")
    for col in ["Model", "Agreement", "Mean tokens", "Mean latency", "$/review"]:
        t.add_column(col)
    for r in results:
        t.add_row(r["model"], f"{r['agreement']*100:.0f}% ({r['hits']}/{r['n']})",
                  f"{r['mean_tokens']:,}", f"{r['mean_latency_s']}s", f"${r['cost_per_review_usd']:.4f}")
    console.print(t)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2))
    console.print(f"[dim]Saved {args.out}[/]")


if __name__ == "__main__":
    main()
