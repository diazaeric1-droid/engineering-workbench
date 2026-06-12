"""Colorado ECMC (COGCC) public-data adapter — REAL DJ Basin monthly production → WellFile.

The Colorado Energy & Carbon Management Commission (ECMC, formerly COGCC) publishes
**per-well MONTHLY production** — oil (bbl), gas (mcf), produced water (bbl), and days
produced — as **free public records** (no subscription, no API key). This is the suite's
default REAL data source: DJ Basin **Niobrara / Codell horizontals** in Weld County —
onshore unconventional wells directly analogous to a Bakken/Permian horizontal program.

The monthly extract is the EXACT tidy schema the shared monthly parser consumes, so this
is a thin wrapper over :func:`src.adapters.ndic.load_ndic_fleet` — only the provenance copy
differs. The data carries the SAME gaps as any public monthly filing:

- **No ESP telemetry** — the per-well ESP-diagnostics panel is skipped for these wells.
- **No daily data** — monthly cadence (one point per producing month).
- **No failure labels** — raw production, not a labeled eval set.

See ``data/real/colorado/README.md`` and ``fetch_colorado.py`` for how ``production.csv``
is built from the ECMC public endpoints (it is committed because CO public records are
redistributable).
"""
from __future__ import annotations

from pathlib import Path

from ..data_loader import WellFile
from .ndic import load_ndic_fleet

CO_SOURCE_NOTE = (
    "Imported from Colorado ECMC (COGCC) public monthly production records "
    "(DJ Basin / Niobrara-Codell horizontals, Weld County). Monthly cadence; no ESP "
    "telemetry, no daily data, no failure labels in the source."
)


def load_colorado_fleet(csv_path: str | Path, days_per_month: int = 30) -> list[WellFile]:
    """Parse a tidy Colorado ECMC monthly-production CSV into one ``WellFile`` per well.

    Identical parse/grouping/rate-conversion to the NDIC path (same schema), with
    Colorado-correct provenance baked into each ``WellFile`` so nothing claims to be
    North Dakota Bakken. Raises ``ValueError`` on an empty/malformed file.
    """
    return load_ndic_fleet(
        csv_path,
        days_per_month,
        source_note=CO_SOURCE_NOTE,
        field_default="DJ Basin (Colorado ECMC)",
        operator_default="Colorado ECMC public record",
        formation_default="Niobrara",
    )
