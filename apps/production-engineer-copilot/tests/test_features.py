"""Tests for the v0.5 feature set: calibrated assumptions, real-data adapter,
portfolio screen. All deterministic — no API."""
import csv
from pathlib import Path

import pytest

from src.analyzers import assumptions as A
from src.adapters.public_data import from_volve_csv, SM3_TO_BBL
from src.portfolio import screen_well, rank, _indicated_intervention
from src.data_loader import WellFile

REPO = Path(__file__).parent.parent


def test_assumptions_lookup_and_market():
    d = A.intervention_defaults("esp_swap")
    assert d["cost_usd"] > 0 and 0 < d["p_success"] <= 1
    # loose match
    assert A.intervention_defaults("ESP-to-Beam Conversion")["uplift_decline"] > 0
    assert A.intervention_defaults("nonsense_xyz") is None
    # realized price = WTI + differential
    assert A.REALIZED_PRICE_USD_PER_BBL == A.WTI_PRICE_USD_PER_BBL + A.REALIZED_DIFFERENTIAL


def test_volve_adapter_unit_conversion(tmp_path):
    # One month, 1000 Sm3 oil over 31 calendar days -> ~ (1000*6.2898/31) bopd.
    csv_path = tmp_path / "v.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["DATEPRD", "WELL_BORE_CODE", "ON_STREAM_HRS",
                    "BORE_OIL_VOL", "BORE_WAT_VOL", "BORE_GAS_VOL"])
        w.writerow(["2014-01-01", "NO 15/9-F-12", "744", "1000", "500", "180000"])
        w.writerow(["2014-02-01", "NO 15/9-F-12", "672", "900", "480", "150000"])
        w.writerow(["2014-03-01", "NO 15/9-F-12", "744", "820", "470", "130000"])
        w.writerow(["2014-04-01", "NO 15/9-F-12", "720", "760", "460", "120000"])
        w.writerow(["2014-05-01", "NO 15/9-F-12", "744", "700", "455", "110000"])
        w.writerow(["2014-06-01", "NO 15/9-F-12", "720", "650", "450", "100000"])
    header = {"well_id": "15/9-F-12", "first_prod_date": "2008-02-12",
              "artificial_lift": {"type": "ESP", "pump_spec": {"por_min_bfpd": 8000, "por_max_bfpd": 30000}}}
    w = from_volve_csv(csv_path, header, well_bore_code="15/9-F-12")
    assert len(w.production_history) == 6
    # first month: 1000 Sm3 over 744 on-stream hrs (=31 days) -> ~202.9 bopd
    expected = 1000 * SM3_TO_BBL / 31
    assert abs(w.production_history[0]["oil_bopd"] - expected) < 1.0
    # rates decline month over month
    assert w.production_history[0]["oil_bopd"] > w.production_history[-1]["oil_bopd"]


def test_portfolio_screen_picks_sane_interventions():
    # esp_scale well -> scale_treatment with positive NPV
    scale_wells = sorted((REPO / "data" / "synthetic").glob("well_011.json"))
    assert scale_wells
    row = screen_well(str(scale_wells[0]))
    assert row.intervention == "scale_treatment"
    assert row.npv_usd > 0 and row.capital_usd > 0

    # esp_normal well -> monitor, no capital
    row2 = screen_well(str(REPO / "data" / "synthetic" / "well_014.json"))
    assert row2.intervention == "monitor"
    assert row2.capital_usd == 0


def test_portfolio_rank_orders_by_npv():
    paths = [str(p) for p in sorted((REPO / "data" / "synthetic").glob("well_0[0-1]*.json"))]
    rows = rank(paths, by="npv")
    npvs = [r.npv_usd for r in rows]
    assert npvs == sorted(npvs, reverse=True)
