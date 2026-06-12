"""Tests for the in-app AFE authorization preview (src/afe_preview.py).

All deterministic — no API key, no cross-service call.
"""
from src.afe_preview import (
    build_afe_preview,
    recommend_approver,
    AUTHORITY_TOP_APPROVER,
)
from src.tools import AFE_INTERVENTIONS

_DIAG = {
    "well_id": "WELL-001",
    "api_number": "42-000-00000",
    "field": "Delaware",
    "operator": "Operator (synthetic)",
    "primary_diagnosis": "Below type curve; scale indicated",
}
_ECON = {"npv_10pct_usd": 1_250_000.0, "payout_months": 8.0,
         "incremental_rate_bopd": 120.0, "profitability_index": 2.4}


def test_returns_expected_keys_and_positive_cost():
    p = build_afe_preview(_DIAG, "acid_stimulation", _ECON)
    assert p["afe_required"] is True
    for key in (
        "intervention", "gross_cost_usd", "tangible_cost_usd",
        "intangible_cost_usd", "net_npv_usd", "payout_months",
        "recommended_approver", "authority_basis", "cost_line_items",
        "well_id", "api_number", "field", "operator",
    ):
        assert key in p, f"missing key {key}"
    # known intervention -> cost > 0
    assert p["gross_cost_usd"] > 0
    # tangible + intangible == gross (no rounding drift on this case)
    assert round(p["tangible_cost_usd"] + p["intangible_cost_usd"], 2) == p["gross_cost_usd"]
    # net economics carried straight from the engineer's input (no recompute)
    assert p["net_npv_usd"] == _ECON["npv_10pct_usd"]
    assert p["payout_months"] == _ECON["payout_months"]


def test_all_afe_keys_price_a_cost():
    # Every canonical AFE key (incl. p_and_a, which has no production default)
    # must resolve to a positive gross cost.
    for key in AFE_INTERVENTIONS:
        p = build_afe_preview(_DIAG, key, _ECON)
        assert p["afe_required"] is True, key
        assert p["gross_cost_usd"] > 0, key


def test_authority_ladder_mapping():
    assert recommend_approver(200_000) == "Foreman"
    assert recommend_approver(800_000) == "Asset Manager"
    assert recommend_approver(3_000_000) == "VP, Operations"
    # boundaries are exclusive upper bounds
    assert recommend_approver(250_000) == "Asset Manager"
    assert recommend_approver(1_000_000) == "VP, Operations"
    assert recommend_approver(5_000_000) == AUTHORITY_TOP_APPROVER
    assert recommend_approver(12_000_000) == AUTHORITY_TOP_APPROVER


def test_authority_routing_flows_into_preview():
    # esp_swap calibrated cost is $325k -> Asset Manager tier.
    p = build_afe_preview(_DIAG, "esp_swap", _ECON)
    assert p["gross_cost_usd"] == 325_000
    assert p["recommended_approver"] == "Asset Manager"


def test_monitor_diagnosis_yields_no_afe():
    for sentinel in ("monitor", "none", "", "no_action"):
        p = build_afe_preview(_DIAG, sentinel, _ECON)
        assert p["afe_required"] is False
        assert p["recommended_approver"] is None
        assert "reason" in p


def test_missing_econ_is_tolerated():
    p = build_afe_preview(_DIAG, "paraffin_treatment", None)
    assert p["afe_required"] is True
    assert p["net_npv_usd"] is None
    assert p["payout_months"] is None
    # cost + routing still resolve without economics
    assert p["gross_cost_usd"] > 0
    assert p["recommended_approver"] == "Foreman"
