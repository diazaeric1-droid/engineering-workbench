#!/usr/bin/env python3
"""Build ``production.csv`` from Colorado ECMC (COGCC) public records — REAL DJ Basin data.

The Colorado Energy & Carbon Management Commission (ECMC, formerly COGCC) publishes
**per-well MONTHLY production** (oil bbl, gas mcf, produced water bbl, days produced)
as public records — free, no subscription, no API key. This script harvests a small,
diverse slice of **DJ Basin Niobrara/Codell horizontal** wells (Weld County) and writes
the tidy schema the suite's monthly adapter consumes:

    well_id, well_name, operator, field, formation, date, oil_bbl, gas_mcf, water_bbl, days

Two public endpoints are used:
  1. Well universe (api_county + api_seq + formation + lateral length + status):
     the statewide Wells shapefile  ── https://ecmc.state.co.us/documents/data/downloads/gis/WELLS_SHP.ZIP
  2. Per-well monthly production table (HTML, parsed with pandas.read_html):
     https://ecmc.state.co.us/cogisdb/Facility/Production?api_county_code={C}&api_seq_num={S}

Re-run to refresh or expand the slice (raise MAX_WELLS / widen the filters). Colorado
public records are redistributable, so the resulting CSV is committed to the repo.

Deps: ``pip install pandas lxml pyshp``.  Usage: ``python fetch_colorado.py``.
"""
from __future__ import annotations

import io
import re
import time
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
UA = {"User-Agent": "Mozilla/5.0 (energy-ai-pivot; public-records research)"}
SHP_URL = "https://ecmc.state.co.us/documents/data/downloads/gis/WELLS_SHP.ZIP"
PROD_URL = "https://ecmc.state.co.us/cogisdb/Facility/Production?api_county_code={c}&api_seq_num={s}"

COUNTY = "123"          # Weld County — the DJ Basin core
SPUD_MIN, SPUD_MAX = 2015, 2022
MIN_LATERAL_FT = 4000   # Max_MD - Max_TVD: clearly a horizontal
MIN_OIL_MONTHS = 12     # keep wells with a real producing history
MAX_WELLS = 28


def _get(url: str, timeout: int = 60) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def candidate_wells() -> list[dict]:
    """Diverse horizontal Niobrara/Codell producers from the public Wells shapefile."""
    import shapefile  # pyshp

    zf = zipfile.ZipFile(io.BytesIO(_get(SHP_URL, timeout=180)))
    tmp = HERE / "_shp"
    tmp.mkdir(exist_ok=True)
    for n in zf.namelist():
        (tmp / Path(n).name).write_bytes(zf.read(n))
    r = shapefile.Reader(str(tmp / next(p.stem for p in tmp.glob("*.shp"))))
    fld = [f[0] for f in r.fields[1:]]
    ix = {k: i for i, k in enumerate(fld)}

    rows = []
    for rec in r.iterRecords():
        if rec[ix["API_County"]] != COUNTY or rec[ix["Facil_Type"]] != "WELL":
            continue
        if rec[ix["Facil_Stat"]] not in ("PR", "SI", "AB"):
            continue
        field = (rec[ix["Field_Name"]] or "")
        md, tvd = rec[ix["Max_MD"]] or 0, rec[ix["Max_TVD"]] or 0
        if (md - tvd) < MIN_LATERAL_FT or md < 11000:
            continue
        if not any(k in field.upper() for k in ("NIOBRARA", "CODELL", "HORIZONTAL")):
            continue
        sp = rec[ix["Spud_Date"]]
        if not sp or not (SPUD_MIN <= sp.year <= SPUD_MAX):
            continue
        rows.append({"county": rec[ix["API_County"]], "seq": rec[ix["API_Seq"]],
                     "api": rec[ix["API_Label"]], "operator": rec[ix["Operator"]],
                     "name": rec[ix["Well_Title"]] or rec[ix["Well_Name"]],
                     "lateral": int(md - tvd)})
    # round-robin across operators for diversity, longest laterals first
    from collections import defaultdict
    by_op: dict[str, list] = defaultdict(list)
    for c in sorted(rows, key=lambda c: -c["lateral"]):
        by_op[c["operator"]].append(c)
    picked: list[dict] = []
    while len(picked) < MAX_WELLS * 2 and any(by_op.values()):
        for op in list(by_op):
            if by_op[op]:
                picked.append(by_op[op].pop(0))
    return picked


def _ym(v) -> str | None:
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", str(v))
    return f"{int(m.group(3)):04d}-{int(m.group(1)):02d}" if m else None


def _num(x) -> float:
    v = pd.to_numeric(x, errors="coerce")
    return 0.0 if pd.isna(v) else float(v)


def _clean_formation(rows: pd.Series) -> str:
    s = set()
    for f in rows.astype(str):
        u = f.upper()
        if "NIOBRARA" in u:
            s.add("Niobrara")
        if any(k in u for k in ("CODELL", "FORT HAYS", "CARLILE")):
            s.add("Codell")
    if {"Niobrara", "Codell"} <= s:
        return "Niobrara-Codell"
    return "Niobrara" if "Niobrara" in s else ("Codell" if s else "Niobrara")


def fetch_well(c: dict) -> list[dict]:
    """One well → tidy monthly rows (aggregated across commingled formation rows)."""
    tables = pd.read_html(io.StringIO(_get(PROD_URL.format(c=c["county"], s=c["seq"])).decode("utf-8", "replace")))
    prod = next((t for t in tables if any("Oil Produced" in str(x) for x in t.columns)
                 and any("Days Produced" in str(x) for x in t.columns)), None)
    if prod is None or len(prod) < 18:
        return []
    meta = {}
    for t in tables:
        if "Facility Name/Number" in " ".join(str(x) for x in t.values.flatten()):
            v = t.values.tolist()
            meta = dict(zip([str(x).strip().rstrip(":") for x in v[0]], [str(x).strip() for x in v[1]]))
            break
    col = lambda name: next((x for x in prod.columns if name in str(x)), None)
    cd, co, cg, cw, cdy, cf = (col("First of Month"), col("Oil Produced"), col("Gas Produced"),
                               col("Water Volume"), col("Days Produced"), col("Formation"))
    rec = []
    for _, rr in prod.iterrows():
        d = _ym(rr[cd])
        if not d:
            continue
        rec.append({"date": d, "oil_bbl": _num(rr[co]), "gas_mcf": _num(rr[cg]),
                    "water_bbl": _num(rr[cw]), "days": _num(rr[cdy]),
                    "formation": str(rr[cf]) if cf else "Niobrara"})
    g = pd.DataFrame(rec)
    if g.empty:
        return []
    fm = _clean_formation(g["formation"])
    agg = g.groupby("date").agg(oil_bbl=("oil_bbl", "sum"), gas_mcf=("gas_mcf", "sum"),
                                water_bbl=("water_bbl", "sum"), days=("days", "max")).reset_index().sort_values("date")
    # trim leading pre-first-oil months
    nz = agg.index[agg.oil_bbl > 0]
    if len(nz):
        agg = agg.loc[nz[0]:]
    if int((agg.oil_bbl > 0).sum()) < MIN_OIL_MONTHS:
        return []
    name = meta.get("Facility Name/Number") or c["name"]
    op = meta.get("Current Operator Name") or c["operator"]
    fld = meta.get("Field") or "DJ HORIZONTAL NIOBRARA"
    return [{"well_id": c["api"], "well_name": name, "operator": op, "field": fld,
             "formation": fm, "date": r.date, "oil_bbl": round(r.oil_bbl, 1),
             "gas_mcf": round(r.gas_mcf, 1), "water_bbl": round(r.water_bbl, 1),
             "days": int(round(r.days))} for r in agg.itertuples()]


def main() -> None:
    out: list[dict] = []
    kept = 0
    for c in candidate_wells():
        try:
            rows = fetch_well(c)
        except Exception as e:  # noqa: BLE001
            print(f"  skip {c['api']}: {e}")
            continue
        if rows:
            out.extend(rows)
            kept += 1
            print(f"  + {c['api']}  {rows[0]['well_name'][:30]:30}  {len(rows)} months")
        time.sleep(0.3)
        if kept >= MAX_WELLS:
            break
    df = pd.DataFrame(out).sort_values(["well_id", "date"])
    dest = HERE / "production.csv"
    df.to_csv(dest, index=False)
    print(f"\nwrote {dest}  ({df.well_id.nunique()} wells, {len(df)} monthly rows, "
          f"{df.date.min()}..{df.date.max()})")


if __name__ == "__main__":
    main()
