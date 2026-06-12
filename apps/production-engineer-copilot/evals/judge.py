"""LLM-as-judge rubric scoring for well-review reports.

Keyword agreement answers "did the right phrase appear." It plateaus and misleads as
the eval grows: a report can hit the keyword and still reason badly, or reason well and
phrase the recommendation differently. This judge scores the report on four independent
axes a senior reviewer actually cares about, 1-5 each:

  - diagnosis      : did it correctly identify the well's problem from the data?
  - recommendation : is the primary recommendation the physically appropriate one?
  - economics      : are the NPV/payout/uplift numbers sane and internally consistent?
  - restraint      : did it avoid inventing interventions on a healthy well / over-claiming?

Run via `python -m evals.run_evals --judge` (needs ANTHROPIC_API_KEY). The judge is a
DIFFERENT model instance from the one under test and is given the expected label, so it
grades against the reference rather than re-deriving the answer.
"""
from __future__ import annotations

import json
import os
from datetime import date

JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "claude-sonnet-4-6")

_RUBRIC = """You are a VP of Production grading a well-review report written by a junior engineer's AI assistant.

The reference expert label for this well is:
  - expected primary recommendation: {expected}
  - expected diagnosis keywords: {keywords}

Score the report on each axis from 1 (unacceptable) to 5 (excellent):
  - diagnosis: correctly identifies the well's actual problem from the cited data.
  - recommendation: the PRIMARY recommendation is the physically appropriate intervention
    (matches the reference, or is a defensible equivalent / sequenced path).
  - economics: NPV, payout, uplift, and costs are sane, quantitative, and internally consistent.
  - restraint: avoids inventing interventions on a healthy well, avoids fabricated wells/numbers,
    flags missing data honestly.

Return ONLY a JSON object, no prose:
{{"diagnosis": <1-5>, "recommendation": <1-5>, "economics": <1-5>, "restraint": <1-5>,
  "rationale": "<one sentence>"}}

REPORT:
---
{report}
---"""


def judge_report(report: str, expected: str, keywords: list[str]) -> dict:
    """Return {diagnosis, recommendation, economics, restraint, overall, rationale}."""
    from anthropic import Anthropic
    from dotenv import load_dotenv

    load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):  # don't let an empty shell var shadow .env
        load_dotenv(override=True)
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    prompt = _RUBRIC.format(expected=expected, keywords=", ".join(keywords),
                            report=report[:8000])
    resp = client.messages.create(
        model=JUDGE_MODEL, max_tokens=400,
        system=f"Today is {date.today().isoformat()}. You are a strict, fair grader. Output only JSON.",
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    # tolerate code fences / stray prose around the JSON
    start, end = text.find("{"), text.rfind("}")
    scores = json.loads(text[start: end + 1]) if start >= 0 else {}

    axes = ["diagnosis", "recommendation", "economics", "restraint"]
    vals = [float(scores.get(a, 0) or 0) for a in axes]
    scores["overall"] = round(sum(vals) / len(vals), 2) if vals else 0.0
    return scores


if __name__ == "__main__":
    import sys
    txt = sys.stdin.read()
    print(json.dumps(judge_report(txt, "monitor", ["on type curve"]), indent=2))
