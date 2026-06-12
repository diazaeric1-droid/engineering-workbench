"""In-app AFE authorization PREVIEW — closes the diagnose→authorize loop locally.

Deterministic, no API key, no cross-service call. Given the current well's
diagnosis, the recommended intervention, and the economics already computed in
the demo, this builds a one-page AFE authorization summary: a gross cost
estimate (from the calibrated intervention cost DB), a tangible/intangible
(IDC) split for tax, the net economics carried straight from the engineer's
risked NPV, and a recommended approver from a simple $-authority ladder.

It is a *preview* — the full Form 1213-style authorization (WI/NRI net economics,
JIB allocation, risk register, audit trail) lives in the AFE Copilot, reached via
the schema-validated diagnosis export + a deep-link from the demo.

The eight AFE intervention keys mirror src.tools.AFE_INTERVENTIONS. Gross cost
comes from src.analyzers.assumptions.INTERVENTION_DEFAULTS where calibrated; a
small fallback table covers the AFE keys that have no production-economics
default (e.g. plug & abandon), so every valid AFE key resolves to a cost.
"""
from __future__ import annotations

from typing import Any

from .analyzers import assumptions as A

# ---- $-authority ladder -----------------------------------------------------
# A standard delegation-of-authority (DOA) ladder for capital approval. Each
# tuple is (exclusive upper bound USD, approver title). The first bound the
# gross cost falls UNDER selects the approver; above the top bound -> Board.
#   < $250k   -> Foreman / Field Supervisor
#   < $1MM    -> Asset Manager
#   < $5MM    -> VP, Operations
#   >= $5MM   -> Board of Directors
AUTHORITY_LADDER: tuple[tuple[float, str], ...] = (
    (250_000, "Foreman"),
    (1_000_000, "Asset Manager"),
    (5_000_000, "VP, Operations"),
)
AUTHORITY_TOP_APPROVER = "Board of Directors"

# Gross-cost fallback for AFE keys with no calibrated production-economics
# default in INTERVENTION_DEFAULTS. Public order-of-magnitude Permian figures.
_AFE_COST_FALLBACK_USD: dict[str, float] = {
    "p_and_a": 150_000,  # plug & abandon — surface/downhole P&A + reclamation
}

# Tangible (capitalized equipment) share of gross cost, by intervention. The
# remainder is intangible drilling/service cost (IDC), which is tax-deductible
# in the year incurred. Equipment-heavy jobs (ESP swap, beam conversion) carry a
# larger tangible share; pure service jobs (acid, paraffin) are mostly IDC.
_TANGIBLE_SHARE: dict[str, float] = {
    "acid_stimulation": 0.10,
    "scale_treatment": 0.10,
    "esp_swap": 0.55,
    "esp_to_beam_conversion": 0.60,
    "rod_pump_workover": 0.35,
    "gas_lift_optimization": 0.40,
    "paraffin_treatment": 0.05,
    "p_and_a": 0.15,
}
_DEFAULT_TANGIBLE_SHARE = 0.30

# Interventions that are pure monitoring / no capital request -> no AFE needed.
_NO_AFE_INTERVENTIONS = frozenset({"monitor", "none", "no_action", "watch", ""})


def _gross_cost_usd(intervention: str) -> float:
    """Calibrated gross (all-in) cost for an AFE intervention key.

    Prefers the production-economics default; falls back to the AFE-only table.
    Returns 0.0 if the key is unknown (caller decides what that means).
    """
    d = A.intervention_defaults(intervention)
    if d is not None and d.get("cost_usd"):
        return float(d["cost_usd"])
    return float(_AFE_COST_FALLBACK_USD.get(intervention, 0.0))


def recommend_approver(gross_cost_usd: float) -> str:
    """Route a $ amount to the required approver via the authority ladder."""
    for upper, approver in AUTHORITY_LADDER:
        if gross_cost_usd < upper:
            return approver
    return AUTHORITY_TOP_APPROVER


def build_afe_preview(
    diagnosis: dict[str, Any],
    intervention: str,
    econ: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a one-page AFE authorization PREVIEW (pure / deterministic).

    Parameters
    ----------
    diagnosis : dict
        The well's diagnosis context. Recognized keys (all optional):
        ``well_id``, ``api_number``, ``field``, ``operator``,
        ``primary_diagnosis``.
    intervention : str
        Canonical AFE intervention key (one of src.tools.AFE_INTERVENTIONS),
        or a no-action sentinel ("monitor"/"none"/"") -> "no AFE required".
    econ : dict, optional
        Net economics already computed for the well. Recognized keys:
        ``npv_10pct_usd`` / ``npv_usd`` (risked NPV), ``payout_months``,
        ``incremental_rate_bopd``, ``profitability_index``. Used as-is; this
        helper does NOT recompute economics.

    Returns
    -------
    dict
        ``afe_required`` (bool) plus, when required:
        ``intervention``, ``gross_cost_usd``, ``tangible_cost_usd``,
        ``intangible_cost_usd`` (IDC), ``tangible_pct``, ``net_npv_usd``,
        ``payout_months``, ``incremental_rate_bopd``, ``profitability_index``,
        ``recommended_approver``, ``authority_basis``, identity fields, and a
        ``cost_line_items`` list (label/amount) for table rendering.
        When no AFE is needed: ``afe_required=False`` + a ``reason``.
    """
    econ = econ or {}
    key = (intervention or "").strip().lower().replace(" ", "_").replace("-", "_")

    # No-action / monitor diagnoses -> no capital request, no AFE.
    if key in _NO_AFE_INTERVENTIONS:
        return {
            "afe_required": False,
            "intervention": key or "none",
            "reason": (
                "No intervention recommended (monitor / continue base management) — "
                "no capital authorization required."
            ),
            "recommended_approver": None,
        }

    gross = _gross_cost_usd(key)
    if gross <= 0:
        # Unknown intervention with no cost basis -> cannot price an AFE.
        return {
            "afe_required": False,
            "intervention": key,
            "reason": (
                f"No calibrated cost basis for intervention {intervention!r}; "
                "cannot build an AFE preview. Use a canonical AFE intervention key."
            ),
            "recommended_approver": None,
        }

    tangible_pct = _TANGIBLE_SHARE.get(key, _DEFAULT_TANGIBLE_SHARE)
    tangible = round(gross * tangible_pct, 2)
    intangible = round(gross - tangible, 2)

    # Net economics carried straight from the engineer's risked NPV (no recompute).
    net_npv = econ.get("npv_10pct_usd", econ.get("npv_usd"))
    net_npv = float(net_npv) if net_npv is not None else None
    payout = econ.get("payout_months")
    payout = float(payout) if isinstance(payout, (int, float)) else None
    inc_rate = econ.get("incremental_rate_bopd")
    inc_rate = float(inc_rate) if isinstance(inc_rate, (int, float)) else None
    pi = econ.get("profitability_index")
    pi = float(pi) if isinstance(pi, (int, float)) else None

    approver = recommend_approver(gross)

    return {
        "afe_required": True,
        "well_id": diagnosis.get("well_id"),
        "api_number": diagnosis.get("api_number"),
        "field": diagnosis.get("field"),
        "operator": diagnosis.get("operator"),
        "primary_diagnosis": diagnosis.get("primary_diagnosis"),
        "intervention": key,
        "gross_cost_usd": round(gross, 2),
        "tangible_cost_usd": tangible,
        "intangible_cost_usd": intangible,
        "tangible_pct": tangible_pct,
        "net_npv_usd": net_npv,
        "payout_months": payout,
        "incremental_rate_bopd": inc_rate,
        "profitability_index": pi,
        "recommended_approver": approver,
        "authority_basis": (
            f"Gross AFE ${gross:,.0f} routed by delegation-of-authority ladder "
            f"(<$250k Foreman, <$1MM Asset Manager, <$5MM VP, else Board)."
        ),
        "cost_line_items": [
            {"label": "Tangible (capitalized equipment)", "amount": tangible},
            {"label": "Intangible (IDC — services, deductible)", "amount": intangible},
            {"label": "Gross AFE estimate", "amount": round(gross, 2)},
        ],
    }
