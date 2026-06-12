# Real data — North Dakota (NDIC) Bakken monthly production

> **Note:** The suite now defaults to **free Colorado ECMC** real data (`../colorado/`). NDIC per-well monthly production is a **paid subscription** ($100/yr Basic Services), so this remains a *bring-your-own-export* path — drop your own `production.csv` here to run on real North Dakota Bakken wells.

This folder is the **drop point for a REAL public-data extract**. The app's data-source
toggle (sidebar → **Data source → "Real — North Dakota (NDIC)"**) loads
**`data/real/ndic/production.csv`** through `src/adapters/ndic.py` when that file is
present. If it is **absent**, the app falls back to the synthetic fleet and the
provenance badge stays amber (**SYNTHETIC DATA**) — so the demo never silently passes
modeled wells off as real.

The North Dakota Industrial Commission (NDIC), Dept. of Mineral Resources / Oil & Gas
Division, publishes **per-well monthly production** for every well in the state —
onshore **Williston Basin / Bakken–Three Forks**. That is the only real signal this
source carries, and what it is **missing** matters:

- **No ESP telemetry** — no intake pressure, motor temperature, or motor amps. The
  per-well **ESP-diagnostics panel does not render** for NDIC wells (handled gracefully).
- **No daily data** — only monthly totals, so the production history is at **monthly
  cadence** (one point per producing month). Short histories (< 5 months) hit the same
  "insufficient data" guard the synthetic fleet uses.
- **No failure labels** — this is raw production, not a labeled eval set, so it does not
  touch the eval / holdout numbers in any way.

## Expected CSV — `production.csv` (tidy, one row per well per month)

Columns (header row required; order-independent, matched case-insensitively):

| column      | meaning                                              | example          |
|-------------|------------------------------------------------------|------------------|
| `well_id`   | NDIC well/file (API) number — the grouping key       | `33053XXXXX`     |
| `well_name` | well name (used as the display id)                   | `SAMPLE 1-2H`    |
| `operator`  | operator of record                                   | `SAMPLE OPERATOR`|
| `field`     | NDIC field name                                      | `SAMPLE FIELD`   |
| `formation` | producing formation / pool                           | `Bakken`         |
| `date`      | production month, **`YYYY-MM`** (a day part is ok)   | `2024-01`        |
| `oil_bbl`   | **monthly** oil volume, barrels                      | `9000`           |
| `gas_mcf`   | **monthly** gas volume, mcf                          | `12000`          |
| `water_bbl` | **monthly** water volume, barrels                    | `4500`           |
| `days`      | days the well produced that month (NDIC "Days")      | `30`             |

The adapter groups rows by `well_id`, sorts months chronologically, and converts each
**monthly total → average daily rate**:

```
oil_bopd  = oil_bbl   / max(days, 1)
water_bwpd = water_bbl / max(days, 1)
gas_mcfd  = gas_mcf    / max(days, 1)
```

The `day` axis is the month index × 30 (first producing month = day 0), giving the
existing decline plot a monotonic x-axis. No `esp_readings` are produced.

## How to produce `production.csv` from an NDIC export

The genuine extract is **paid / lagged** (the public ND DMR Oil & Gas portal gates the
bulk monthly data behind a subscription, and figures lag the production month). To run
the app on real data:

1. Obtain a monthly-production export from the **ND DMR / NDIC** Oil & Gas portal
   (<https://www.dmr.nd.gov/oilgas/>) — the per-well monthly oil/gas/water + days table,
   for the wells you have access to.
2. Reshape it to the **tidy schema above** (one row per well per month) and save it as
   `data/real/ndic/production.csv`. `_TEMPLATE.csv` in this folder is the exact header
   plus two **clearly-fake placeholder rows** (`well_id = DEMO_0001`) — copy it, delete
   the demo rows, and paste your real monthly rows. **Do not commit the real extract if
   your access terms prohibit redistribution.**
3. Pick **Data source → "Real — North Dakota (NDIC)"** in the sidebar. No code change is
   needed — the adapter reads `production.csv`, the badge flips to green **REAL DATA**,
   and every well page works (minus the ESP-diagnostics panel, which monthly public data
   cannot populate).

## Files here

| file            | what it is                                                                 |
|-----------------|----------------------------------------------------------------------------|
| `_TEMPLATE.csv` | The header row + **2 clearly-fake** example rows (`DEMO_0001`). A template, **NOT real data** — do not present its values as real Bakken production. |
| `production.csv`| *(not committed)* drop your reshaped real NDIC monthly export here to go live. |
