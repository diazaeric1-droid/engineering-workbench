# Real / public-data wells

The synthetic eval set proves the agent's *reasoning*. This folder proves it ingests the
**messy shapes real production data actually arrives in** — foreign column names, metric
volumes (Sm³), monthly cumulatives instead of daily rates, missing channels — via
`src/adapters/public_data.py`.

## Run a real-format review

```bash
python -m src.agent --well "volve:data/real/volve_15-9-F-12_monthly.csv"   # see agent --help
# or in Python:
python - <<'PY'
from src.adapters.public_data import load_with_header
from src.tools import ToolExecutor
w = load_with_header("data/real/volve_15-9-F-12_monthly.csv",
                     "data/real/volve_15-9-F-12_header.json", schema="volve")
print(w.summary())
PY
```

## Files

| File | What it is |
|---|---|
| `volve_15-9-F-12_monthly.csv` | Volve `MonthlyProductionData` **schema** (DATEPRD, BORE_OIL_VOL/WAT/GAS in Sm³, ON_STREAM_HRS, AVG_DOWNHOLE_PRESSURE/TEMPERATURE …). **Representative volumes** for one real Volve producer, so the adapter is exercised on the real column layout + units without redistributing the gated dataset. |
| `volve_15-9-F-12_header.json` | Completion + artificial-lift sidecar (a production CSV has none). |

## Honest note on the data

The **adapter** is real and handles the real Volve schema (Sm³→bbl ×6.2898, Sm³ gas→mcf,
period-volume→daily-rate ÷ on-stream days, bar→psi for downhole gauges). The **volumes in
the committed CSV are representative**, not the literal Equinor file — the full Volve dataset
is ~40k files behind registration and a non-commercial licence, so it isn't redistributed
here. To run on the genuine data:

1. Register and download from Equinor: <https://www.equinor.com/energy/volve-data-sharing>
   (also mirrored on Kaggle). Licence: **CC BY-NC-SA 4.0** (non-commercial).
2. Drop the real `MonthlyProductionData` CSV in this folder and point the adapter at it with
   the matching `well_bore_code` in the header JSON. No code change needed — the columns match.

For US public data, `from_generic_csv` reads tidy field-unit exports (date, oil_bbl, water_bbl,
gas_mcf) from **North Dakota DMR/NDIC** or the **Texas Railroad Commission** — pass a `col_map`.
