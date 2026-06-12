"""Markdown report builder (optional helper if you want to bypass the LLM
for deterministic report assembly during development)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ReviewSection:
    heading: str
    body: str


def assemble(sections: list[ReviewSection]) -> str:
    return "\n\n".join(f"## {s.heading}\n\n{s.body}" for s in sections)
