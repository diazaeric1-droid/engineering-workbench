"""North Dakota (NDIC) public-data adapter — REAL Bakken monthly production → WellFile.

The North Dakota Industrial Commission (Dept. of Mineral Resources / Oil & Gas
Division) publishes **per-well MONTHLY production** for every well in the state
(onshore Williston Basin / Bakken-Three Forks). Each row is a month of volumes:

    oil (bbl), gas (mcf), water (bbl), and the number of days the well produced.

That is the *real* shape of this public data — and what it does **not** contain
matters as much as what it does:

- **No ESP telemetry** (no intake pressure / motor temp / amps) — so a WellFile
  built here carries ``esp_readings=[]`` and the app's ESP-diagnostic panel simply
  does not render (handled gracefully upstream).
- **No daily data** — only monthly totals, so the production history is at
  **monthly cadence** (one point per producing month).
- **No failure labels** — this is raw production, not a labeled eval set.

This adapter is the WIRING that goes live the moment a real NDIC monthly extract is
dropped at ``data/real/ndic/production.csv`` (the portal export is paid / lagged, so
the repo ships only a clearly-fake ``_TEMPLATE.csv`` — see that folder's README). The
app's default data source stays synthetic; the provenance badge tells the truth about
which set is active.

Expected TIDY CSV schema (one row per well per month)
-----------------------------------------------------
    well_id, well_name, operator, field, formation, date, oil_bbl, gas_mcf, water_bbl, days

- ``date`` is ``YYYY-MM`` (a day component is tolerated but ignored).
- Volumes are **monthly totals in field units** (bbl, mcf).
- ``days`` = days the well produced that month (NDIC's "Days" column); rates use
  ``max(days, 1)`` so a zero/blank never divides by zero.

Monthly total → average daily rate:
    oil_bopd  = oil_bbl   / max(days, 1)
    water_bwpd = water_bbl / max(days, 1)
    gas_mcfd  = gas_mcf    / max(days, 1)
"""
from __future__ import annotations

import csv
from pathlib import Path

from ..data_loader import WellFile

# Logical column -> the tidy NDIC export header we read.
NDIC_COLUMNS = (
    "well_id", "well_name", "operator", "field", "formation",
    "date", "oil_bbl", "gas_mcf", "water_bbl", "days",
)


def _num(value, default: float = 0.0) -> float:
    """Parse a possibly-blank/comma-formatted numeric cell to float (default on failure)."""
    if value is None:
        return default
    s = str(value).strip().replace(",", "")
    if s in ("", "NA", "N/A", "null", "None"):
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _year_month(datestr: str) -> tuple[int, int] | None:
    """Parse 'YYYY-MM' (or 'YYYY-MM-DD', 'YYYY/MM') to (year, month); None if unparseable."""
    s = str(datestr).strip().split()[0].replace("/", "-")
    parts = s.split("-")
    if len(parts) < 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def _month_index(y: int, m: int, y0: int, m0: int) -> int:
    """Whole months elapsed from (y0, m0) to (y, m) — the monthly-cadence day-axis key."""
    return (y - y0) * 12 + (m - m0)


def load_ndic_fleet(
    csv_path: str | Path,
    days_per_month: int = 30,
    *,
    source_note: str = (
        "Imported from North Dakota (NDIC) public monthly production filings "
        "(Williston Basin / Bakken). Monthly cadence; no ESP telemetry, no daily "
        "data, no failure labels in the source."
    ),
    field_default: str = "Williston Basin (NDIC)",
    operator_default: str = "NDIC public filing",
    formation_default: str = "Bakken / Three Forks",
) -> list[WellFile]:
    """Parse a tidy NDIC monthly-production CSV into one ``WellFile`` per well.

    Groups rows by ``well_id``, sorts each well's months chronologically, converts
    every month's totals to an **average daily rate**, and builds a monthly-cadence
    ``production_history`` whose ``day`` axis is the month index times ``days_per_month``
    (so the first producing month is day 0, the next ~30, etc. — a sensible x-axis for
    the existing decline plot, which only needs a monotonic day index).

    No ESP readings, dyno cards, or SCADA are produced — real NDIC public data has none,
    so ``esp_readings`` stays empty and the ESP-diagnostic panel is skipped upstream.

    Returns wells sorted by ``well_id``. Raises ``ValueError`` if the file yields no
    usable rows (missing/empty file, wrong columns, or no parseable dates).
    """
    path = Path(csv_path)
    if not path.exists():
        raise ValueError(f"NDIC CSV not found: {path}")

    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError(f"NDIC CSV has no data rows: {path}")

    # Group rows by well_id, keeping the (year, month, row) for each producing month.
    grouped: dict[str, dict] = {}
    for r in rows:
        # case-insensitive column access so a slightly different export header still reads
        low = {(k or "").strip().lower(): v for k, v in r.items()}
        well_id = str(low.get("well_id", "")).strip()
        ym = _year_month(low.get("date", ""))
        if not well_id or ym is None:
            continue
        g = grouped.setdefault(well_id, {
            "well_name": str(low.get("well_name", "") or "").strip(),
            "operator": str(low.get("operator", "") or "").strip(),
            "field": str(low.get("field", "") or "").strip(),
            "formation": str(low.get("formation", "") or "").strip(),
            "months": [],
        })
        g["months"].append((ym[0], ym[1], low))

    wells: list[WellFile] = []
    for well_id in sorted(grouped):
        g = grouped[well_id]
        months = sorted(g["months"], key=lambda t: (t[0], t[1]))
        if not months:
            continue
        y0, m0 = months[0][0], months[0][1]

        hist = []
        for (y, m, low) in months:
            days = max(_num(low.get("days"), 0.0), 1.0)  # never divide by zero
            oil = _num(low.get("oil_bbl"))
            water = _num(low.get("water_bbl"))
            gas = _num(low.get("gas_mcf"))
            hist.append({
                "day": _month_index(y, m, y0, m0) * days_per_month,
                "oil_bopd": round(oil / days, 1),
                "water_bwpd": round(water / days, 1),
                "gas_mcfd": round(gas / days, 1),
            })

        formation = g["formation"] or formation_default
        completion = {"formation": formation}
        first_prod = f"{y0:04d}-{m0:02d}"
        notes = [
            source_note,
            f"{len(hist)} producing month(s); rates are monthly-total ÷ producing days.",
        ]

        wells.append(WellFile(
            well_id=g["well_name"] or well_id,
            api_number=well_id,                       # NDIC file/API number is the row key
            field=g["field"] or field_default,
            operator=g["operator"] or operator_default,
            spud_date="",
            first_prod_date=first_prod,
            completion=completion,
            artificial_lift={},                        # NDIC publishes no lift / ESP data
            production_history=hist,
            esp_readings=[],                           # real NDIC has none
            scada_recent=[],
            dyno_cards=[],
            notes=notes,
        ))

    if not wells:
        raise ValueError(
            f"No usable wells parsed from {path} — check the columns "
            f"({', '.join(NDIC_COLUMNS)}) and that 'date' is YYYY-MM.")
    return wells
