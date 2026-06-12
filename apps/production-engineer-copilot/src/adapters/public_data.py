"""Adapters that turn REAL public production data into the WellFile the agent reads.

The synthetic eval proves the reasoning; this proves the agent runs on the messy
shapes real data actually comes in — different column names, metric volumes, monthly
cumulatives instead of daily rates, missing channels.

Supported public schemas
-------------------------
- **Volve** (Equinor, North Sea; CC BY-NC-SA 4.0): the `MonthlyProductionData` CSV keyed
  on DATEPRD / NPD_WELL_BORE_CODE with BORE_OIL_VOL / BORE_WAT_VOL / BORE_GAS_VOL in **Sm³**
  (standard cubic metres) as **period totals**, plus AVG_DOWNHOLE_PRESSURE / _TEMPERATURE.
  Download (registration): https://www.equinor.com/energy/volve-data-sharing
- **Generic / NDIC / Texas RRC**: a tidy CSV already in field units (date, oil_bbl,
  water_bbl, gas_mcf) — point `from_generic_csv` at the column names you have.

Completion + artificial-lift details don't live in a production CSV, so they come from a
small sidecar `header` dict/JSON (formation, lateral length, lift type, pump spec).

Unit handling (the part real data forces you to get right):
  - Sm³ oil/water → bbl  : × 6.2898
  - Sm³ gas → mcf        : × 0.0353147 (Sm³→Mscf at ~1000 scf/Mcf; gas already large, so
                           we report mcf/d = Sm³ × 35.3147 / 1000)
  - period volume → average daily rate : ÷ on-stream days (ON_STREAM_HRS/24) when present,
                                         else ÷ calendar days in the period.
"""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Any

from ..data_loader import WellFile

SM3_TO_BBL = 6.2898
SM3_TO_MCF = 35.3147 / 1000.0  # Sm³ → Mscf (thousand standard cubic feet)


def _days_in_month(y: int, m: int) -> int:
    if m == 12:
        return (date(y + 1, 1, 1) - date(y, m, 1)).days
    return (date(y, m + 1, 1) - date(y, m, 1)).days


def _f(row: dict, *keys: str) -> float | None:
    """First parseable float among the candidate column names (case-insensitive)."""
    low = {k.lower(): v for k, v in row.items()}
    for k in keys:
        v = low.get(k.lower())
        if v not in (None, "", "NA", "null"):
            try:
                return float(v)
            except ValueError:
                continue
    return None


def from_volve_csv(
    csv_path: str | Path,
    header: dict[str, Any],
    well_bore_code: str | None = None,
    max_points: int = 24,
) -> WellFile:
    """Parse a Volve MonthlyProductionData-style CSV into a WellFile.

    `header` supplies identity + completion + artificial_lift (the production CSV has none):
        {well_id, api_number, field, operator, first_prod_date, completion{...},
         artificial_lift{type, pump_spec{...}}}
    `well_bore_code` filters to one producer if the CSV holds several (matched against
    WELL_BORE_CODE / NPD_WELL_BORE_CODE / NPD_WELL_BORE_NAME).
    """
    rows = list(csv.DictReader(Path(csv_path).open()))
    if well_bore_code:
        wb = well_bore_code.lower()
        rows = [r for r in rows
                if any(wb in str(v).lower() for k, v in r.items()
                       if "well_bore" in k.lower() or "wellbore" in k.lower())]
    # keep only producing months with oil volume
    hist = []
    esp_readings = []
    day0 = None
    for r in rows:
        datestr = (r.get("DATEPRD") or r.get("dateprd") or r.get("date") or "").split()[0]
        try:
            y, m, d = [int(x) for x in datestr.replace("/", "-").split("-")[:3]]
            # Volve uses DD.MM.YYYY in some exports; tolerate both orders
            if y < 100:  # got DD-MM-YYYY
                d, m, y = y, m, d
        except Exception:
            continue
        oil_sm3 = _f(r, "BORE_OIL_VOL", "oil_sm3")
        if oil_sm3 is None or oil_sm3 <= 0:
            continue
        wat_sm3 = _f(r, "BORE_WAT_VOL", "water_sm3") or 0.0
        gas_sm3 = _f(r, "BORE_GAS_VOL", "gas_sm3") or 0.0
        on_hrs = _f(r, "ON_STREAM_HRS", "on_stream_hrs")
        days = (on_hrs / 24.0) if on_hrs and on_hrs > 0 else _days_in_month(y, m)
        days = max(days, 1.0)
        cur = date(y, m, max(d, 1))
        if day0 is None:
            day0 = cur
        hist.append({
            "day": (cur - day0).days,
            "oil_bopd": round(oil_sm3 * SM3_TO_BBL / days, 1),
            "water_bwpd": round(wat_sm3 * SM3_TO_BBL / days, 1),
            "gas_mcfd": round(gas_sm3 * SM3_TO_MCF / days, 1),
        })
        # If downhole gauges exist, expose the last few as ESP-style readings.
        dhp = _f(r, "AVG_DOWNHOLE_PRESSURE")
        dht = _f(r, "AVG_DOWNHOLE_TEMPERATURE")
        if dhp is not None:
            esp_readings.append({
                "date": f"{y:04d}-{m:02d}-{max(d,1):02d}",
                "bfpd": round((oil_sm3 + wat_sm3) * SM3_TO_BBL / days),
                "intake_pressure_psi": round(dhp * 14.5038),  # bar → psi
                "motor_temp_f": round(dht * 9 / 5 + 32) if dht is not None else 0,
                "motor_amps": 0,
            })
    if not hist:
        raise ValueError("No producing months parsed from CSV (check well_bore_code / columns).")

    # thin to the most recent max_points so the decline fit isn't dominated by early plateau
    hist = hist[-max_points:]
    lift = header.get("artificial_lift", {})
    keep_esp = esp_readings[-3:] if lift.get("type") == "ESP" else []

    return WellFile(
        well_id=header["well_id"],
        api_number=header.get("api_number", "N/A"),
        field=header.get("field", "Volve (Equinor open data)"),
        operator=header.get("operator", "Equinor"),
        spud_date=header.get("spud_date", ""),
        first_prod_date=header.get("first_prod_date", ""),
        completion=header.get("completion", {}),
        artificial_lift=lift,
        production_history=hist,
        esp_readings=keep_esp,
        scada_recent=[],
        dyno_cards=[],
        notes=header.get("notes", ["Imported from Volve public production CSV (Equinor, CC BY-NC-SA 4.0)."]),
    )


def from_generic_csv(
    csv_path: str | Path,
    header: dict[str, Any],
    col_map: dict[str, str] | None = None,
    max_points: int = 24,
) -> WellFile:
    """Parse a tidy field-unit CSV (NDIC / Texas RRC / operator export) into a WellFile.

    col_map maps logical -> actual column names, e.g.
        {"date": "ReportDate", "oil_bbl": "Oil", "water_bbl": "Wtr", "gas_mcf": "Gas"}
    Volumes are assumed monthly totals in field units (bbl, mcf); we convert to daily rates.
    """
    col_map = col_map or {"date": "date", "oil_bbl": "oil_bbl",
                          "water_bbl": "water_bbl", "gas_mcf": "gas_mcf"}
    rows = list(csv.DictReader(Path(csv_path).open()))
    hist, day0 = [], None
    for r in rows:
        datestr = str(r.get(col_map["date"], "")).split()[0]
        try:
            parts = [int(x) for x in datestr.replace("/", "-").split("-")[:3]]
            y, m, d = (parts + [1, 1, 1])[:3]
        except Exception:
            continue
        oil = _f(r, col_map["oil_bbl"])
        if oil is None:
            continue
        days = _days_in_month(y, m)
        cur = date(y, m, max(d, 1))
        day0 = day0 or cur
        hist.append({
            "day": (cur - day0).days,
            "oil_bopd": round(oil / days, 1),
            "water_bwpd": round((_f(r, col_map.get("water_bbl", "")) or 0.0) / days, 1),
            "gas_mcfd": round((_f(r, col_map.get("gas_mcf", "")) or 0.0) / days, 1),
        })
    if not hist:
        raise ValueError("No rows parsed (check col_map).")
    hist = hist[-max_points:]
    return WellFile(
        well_id=header["well_id"], api_number=header.get("api_number", "N/A"),
        field=header.get("field", "Public dataset"), operator=header.get("operator", "Public"),
        spud_date=header.get("spud_date", ""), first_prod_date=header.get("first_prod_date", ""),
        completion=header.get("completion", {}), artificial_lift=header.get("artificial_lift", {}),
        production_history=hist, esp_readings=[], scada_recent=[], dyno_cards=[],
        notes=header.get("notes", ["Imported from public production CSV."]),
    )


def load_with_header(csv_path: str | Path, header_path: str | Path, schema: str = "volve") -> WellFile:
    """Convenience: load a CSV + its sidecar header JSON. schema in {'volve','generic'}."""
    header = json.loads(Path(header_path).read_text())
    if schema == "volve":
        return from_volve_csv(csv_path, header, well_bore_code=header.get("well_bore_code"))
    return from_generic_csv(csv_path, header, col_map=header.get("col_map"))
