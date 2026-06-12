"""Load and validate well files."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any


def _age_years(first_prod_date: str) -> float | None:
    """Years from first production to today (None if unparseable)."""
    try:
        y, m, d = (int(x) for x in first_prod_date.split("-"))
        return round((date.today() - date(y, m, d)).days / 365.25, 1)
    except Exception:
        return None


@dataclass
class WellFile:
    """Normalized representation of a single well's data package."""
    well_id: str
    api_number: str
    field: str
    operator: str
    spud_date: str
    first_prod_date: str
    completion: dict[str, Any]
    artificial_lift: dict[str, Any]
    production_history: list[dict[str, Any]]
    scada_recent: list[dict[str, Any]] = field(default_factory=list)
    dyno_cards: list[dict[str, Any]] = field(default_factory=list)
    esp_readings: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @classmethod
    def from_json(cls, path: str | Path) -> "WellFile":
        path = Path(path)
        with path.open() as f:
            raw = json.load(f)
        return cls(**raw)

    def summary(self) -> str:
        if self.production_history:
            days_on = max(row.get("day", 0) for row in self.production_history)
        else:
            days_on = 0
        lift = self.artificial_lift.get("type", "unknown")
        n_points = len(self.production_history)
        # Advertise which downhole/secondary data is available so the agent knows to
        # call the right tools (e.g. interpret_dyno_card when dyno cards are present —
        # otherwise it cannot see a beam-pump fluid pound).
        available = []
        if self.esp_readings:
            available.append(f"{len(self.esp_readings)} ESP readings")
        if self.dyno_cards:
            available.append(f"{len(self.dyno_cards)} dyno card(s)")
        if self.scada_recent:
            available.append(f"{len(self.scada_recent)} SCADA rows")
        if self.production_history and any("water_bwpd" in r for r in self.production_history):
            available.append("water/gas streams")
        extra = f" | data available: {', '.join(available)}" if available else ""
        age = _age_years(self.first_prod_date)
        age_str = f" | first prod {self.first_prod_date} (~{age:.0f} yr old)" if age is not None else ""
        return (
            f"Well {self.well_id} ({self.api_number}) | {self.field} | "
            f"{lift} | {days_on} days on production ({n_points} data points)"
            f"{age_str}{extra}"
        )
