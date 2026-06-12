# Real data — Colorado ECMC (COGCC) DJ Basin monthly production

This is the suite's **default REAL data source**. `production.csv` here is **genuine
public-record production** — not synthetic — loaded through `src/adapters/colorado.py`
whenever the sidebar **Data source** is set to **"Real — Colorado DJ Basin (ECMC)"**
(the default). The provenance badge shows green **REAL DATA**.

## Why Colorado (and not North Dakota / Bakken)

The original target was NDIC (North Dakota / Bakken). On investigation, **NDIC's
per-well monthly production is paywalled** — a $100/yr "Basic Services" subscription —
so it cannot be a free, committable default. **Colorado ECMC** (Energy & Carbon
Management Commission, formerly COGCC) publishes the **same grain of data for free**:
per-well, per-month oil/gas/water + producing days, as public records (Colorado Open
Records Act). The wells here are **DJ Basin Niobrara / Codell horizontals in Weld
County** — onshore unconventional wells directly analogous to a Bakken/Permian
horizontal program. NDIC remains available as a bring-your-own-export option (see
`../ndic/README.md`).

## What's in this slice

- **28 wells**, ~2,000 well-months, spanning **2016–2026**.
- **17 operators** (Noble/Chevron-legacy, PDC, Extraction, Bonanza Creek, Kerr-McGee,
  Crestone, HighPoint, and independents) — a realistic mixed fleet.
- Formations: **Niobrara**, **Codell**, and commingled **Niobrara-Codell**.
- Horizontal laterals ~4,000–16,000 ft; peak rates ~190–850 BOPD.

## What real monthly data does NOT carry (matters for the apps)

- **No ESP telemetry** (no intake pressure / motor temp / amps) → the per-well
  **ESP-diagnostics panel is skipped** for these wells (handled gracefully).
- **No daily data** — monthly cadence (one point per producing month). The decline /
  type-curve and economics still run; short histories hit the same insufficient-data guard.
- **No failure labels** — raw production, not a labeled eval set, so it never touches the
  blind-holdout eval numbers.

## Schema — `production.csv` (tidy, one row per well per month)

`well_id, well_name, operator, field, formation, date (YYYY-MM), oil_bbl, gas_mcf, water_bbl, days`

Identical to the NDIC tidy schema, so both real sources share one adapter.

## How `production.csv` was built (reproducible)

`fetch_colorado.py` (in this folder) harvests it from two **free public ECMC endpoints**:

1. The statewide **Wells shapefile** (`…/downloads/gis/WELLS_SHP.ZIP`) → the well universe
   with API number, formation, lateral length, and status; filtered to Weld County
   horizontal Niobrara/Codell producers spudded 2015–2022, sampled across operators.
2. The per-well **monthly production page**
   (`…/cogisdb/Facility/Production?api_county_code=…&api_seq_num=…`) → parsed with
   `pandas.read_html`, commingled formation-rows summed per month, leading pre-first-oil
   months trimmed.

Re-run to refresh or expand: `pip install pandas lxml pyshp && python fetch_colorado.py`
(raise `MAX_WELLS` / widen the filters). Colorado public records are redistributable, so
the resulting CSV is committed.
