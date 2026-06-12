"""Tests for the North Dakota (NDIC) public-data adapter.

Parses the committed (clearly-fake) `data/real/ndic/_TEMPLATE.csv` and asserts the
monthly-total -> average-daily-rate conversion and the WellFile shape real NDIC data
implies (monthly cadence, NO ESP telemetry)."""
from pathlib import Path

import pytest

from src.adapters.ndic import load_ndic_fleet
from src.data_loader import WellFile

# Repo-root-relative so it works whether pytest runs from the repo root or elsewhere.
TEMPLATE = Path(__file__).resolve().parent.parent / "data" / "real" / "ndic" / "_TEMPLATE.csv"


def test_template_parses_to_at_least_one_wellfile():
    wells = load_ndic_fleet(TEMPLATE)
    assert len(wells) >= 1
    assert all(isinstance(w, WellFile) for w in wells)


def test_monthly_to_daily_rate_math():
    """Jan: oil 9000 bbl / 30 days = 300 BOPD; gas 12000/30 = 400 mcfd; water 4500/30 = 150 BWPD.
    Feb: oil 8100 bbl / 28 days = 289.3 BOPD (rounded 1 dp)."""
    well = load_ndic_fleet(TEMPLATE)[0]
    hist = well.production_history
    assert len(hist) == 2  # two monthly rows in the template

    jan = hist[0]
    assert jan["oil_bopd"] == pytest.approx(300.0, abs=0.05)    # 9000 / 30
    assert jan["gas_mcfd"] == pytest.approx(400.0, abs=0.05)    # 12000 / 30
    assert jan["water_bwpd"] == pytest.approx(150.0, abs=0.05)  # 4500 / 30

    feb = hist[1]
    assert feb["oil_bopd"] == pytest.approx(8100 / 28, abs=0.05)  # ~289.3, divides by PRODUCING days


def test_monthly_cadence_day_axis():
    """The day axis is monthly: first producing month = day 0, the next ~30 days later."""
    hist = load_ndic_fleet(TEMPLATE)[0].production_history
    assert hist[0]["day"] == 0
    assert hist[1]["day"] == 30


def test_no_esp_or_lift_data_real_ndic_has_none():
    """Real NDIC monthly filings carry no ESP telemetry and no artificial-lift record,
    so the ESP-diagnostics panel has nothing to render (graceful, by design)."""
    well = load_ndic_fleet(TEMPLATE)[0]
    assert well.esp_readings == []
    assert well.artificial_lift == {}
    assert well.dyno_cards == []


def test_identity_from_filing():
    well = load_ndic_fleet(TEMPLATE)[0]
    assert well.api_number == "DEMO_0001"           # NDIC file/API number is the row key
    assert well.completion.get("formation") == "Bakken"
    assert well.first_prod_date == "2024-01"        # earliest producing month


def test_missing_file_raises_valueerror():
    with pytest.raises(ValueError):
        load_ndic_fleet(TEMPLATE.parent / "does_not_exist.csv")
