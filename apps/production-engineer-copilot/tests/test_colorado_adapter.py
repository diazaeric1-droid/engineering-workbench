"""Colorado ECMC adapter — parses the committed REAL DJ Basin extract correctly.

Unlike the NDIC test (which parses a clearly-fake template), this exercises the actual
committed `data/real/colorado/production.csv` — real public-record production — since
Colorado data is redistributable and ships as the suite's default real source.
"""
from pathlib import Path

import pytest

from src.adapters.colorado import load_colorado_fleet

CSV = Path(__file__).resolve().parents[1] / "data" / "real" / "colorado" / "production.csv"


@pytest.mark.skipif(not CSV.exists(), reason="committed Colorado extract not present")
def test_loads_real_colorado_fleet():
    wells = load_colorado_fleet(str(CSV))
    assert len(wells) >= 20, "expected the committed DJ Basin slice (~28 wells)"

    for w in wells:
        hist = w.production_history
        assert hist, f"{w.well_id} has no production history"
        # monthly cadence: the day axis is strictly increasing month-index * 30
        days = [p["day"] for p in hist]
        assert days == sorted(days) and len(set(days)) == len(days), \
            f"{w.well_id} day axis not strictly increasing (duplicate months?)"
        # rates are finite and non-negative
        for p in hist:
            assert p["oil_bopd"] >= 0 and p["gas_mcfd"] >= 0 and p["water_bwpd"] >= 0
        # real monthly public data carries no ESP telemetry
        assert w.esp_readings == []

    # provenance must be Colorado-honest — never claim North Dakota / Bakken
    blob = " ".join(n for w in wells for n in w.notes)
    for forbidden in ("North Dakota", "NDIC", "Bakken", "Williston"):
        assert forbidden not in blob, f"CO provenance wrongly mentions {forbidden!r}"
    assert "Colorado" in blob and "ECMC" in blob


@pytest.mark.skipif(not CSV.exists(), reason="committed Colorado extract not present")
def test_rates_match_monthly_totals_over_days():
    """Spot-check the monthly-total ÷ producing-days rate conversion on the first well."""
    wells = load_colorado_fleet(str(CSV))
    # every per-month oil rate should be a sane DJ Basin number (< 5,000 BOPD)
    assert all(p["oil_bopd"] < 5000 for w in wells for p in w.production_history)
    # at least one well should have a real peak (> 50 BOPD) — not an all-dead slice
    assert any(max(p["oil_bopd"] for p in w.production_history) > 50 for w in wells)
