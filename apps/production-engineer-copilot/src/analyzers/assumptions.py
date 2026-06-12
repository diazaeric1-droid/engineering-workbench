"""Cited economic & engineering assumptions — the single source of truth.

Every default price, cost, decline, and chance-of-success used by the economics and
the agent comes from here, with a source on each line so a reviewer can challenge the
number instead of guessing where it came from. These are public, order-of-magnitude
Permian/Delaware figures circa 2024-2025 — tune per operator before taking to AFE.

Sources (public, order-of-magnitude — not operator-confidential):
  - EIA Short-Term Energy Outlook (WTI price deck) — eia.gov/outlooks/steo
  - EIA Permian regional drilling productivity & operating-cost commentary
  - SPE literature on artificial-lift run life & intervention response
    (e.g., ESP run-life studies; rod-pump vs ESP economics on stripper wells)
  - Operator public investor decks (well cost / LOE ranges, SWD $/bbl)
Each value is a defensible midpoint, not a precise truth; ranges are given where they
matter to a decision.
"""
from __future__ import annotations

# ---- Prices & carrying costs ------------------------------------------------
WTI_PRICE_USD_PER_BBL = 70.0          # EIA STEO 2024-25 WTI midpoint (~$70-80)
REALIZED_DIFFERENTIAL = -5.0          # Midland/Delaware basis + quality diff (~-$3 to -$6)
REALIZED_PRICE_USD_PER_BBL = WTI_PRICE_USD_PER_BBL + REALIZED_DIFFERENTIAL  # ~$65 net

LOE_USD_PER_BBL = 12.0                # Permian lease operating expense (~$8-15/bbl, EIA/operator decks)
SWD_USD_PER_BBL_WATER = 0.75          # Saltwater disposal (~$0.50-1.50/bbl water; piped vs trucked)
DISCOUNT_RATE = 0.10                  # Standard 10% corporate hurdle for upstream NPV

# ---- Per-intervention defaults ---------------------------------------------
# cost_usd      : all-in workover/treatment cost (midpoint of the realistic range)
# uplift_bopd   : typical initial incremental oil rate
# uplift_decline: exponential decline of the uplift (1/yr)
# p_success     : chance the modeled uplift is realized (geologic + mechanical)
# deferred_days : well downtime for the job (deferred production cost)
INTERVENTION_DEFAULTS = {
    # Matrix/diverted acid: response varies widely; ~60-75% of wells respond meaningfully.
    "acid_stimulation":        {"cost_usd": 165_000, "uplift_bopd": 130, "uplift_decline": 0.75, "p_success": 0.70, "deferred_days": 3},
    # Scale squeeze ± acid: high success when scale is confirmed; protects the pump first.
    "scale_treatment":         {"cost_usd": 120_000, "uplift_bopd": 110, "uplift_decline": 0.70, "p_success": 0.80, "deferred_days": 2},
    # Right-size ESP swap: uplift mostly from POR restoration, not added drawdown.
    "esp_swap":                {"cost_usd": 325_000, "uplift_bopd": 100, "uplift_decline": 0.60, "p_success": 0.85, "deferred_days": 5},
    # ESP-to-beam conversion: lower steady-state rate, long run life, cheap rod jobs.
    "esp_to_beam_conversion":  {"cost_usd": 275_000, "uplift_bopd": 40,  "uplift_decline": 0.40, "p_success": 0.85, "deferred_days": 7},
    # Gas separator / downhole gas handling: fixes interference, not reservoir.
    "gas_separator":           {"cost_usd": 90_000,  "uplift_bopd": 70,  "uplift_decline": 0.55, "p_success": 0.75, "deferred_days": 3},
    # Gas-lift optimization: injection-rate / valve work; cheap, moderate uplift.
    "gas_lift_optimization":   {"cost_usd": 60_000,  "uplift_bopd": 60,  "uplift_decline": 0.50, "p_success": 0.75, "deferred_days": 1},
    # Pump-off controller: surface controller; protects rods, modest rate effect.
    "pump_off_controller":     {"cost_usd": 45_000,  "uplift_bopd": 25,  "uplift_decline": 0.45, "p_success": 0.90, "deferred_days": 1},
    # Paraffin / hot oil + wireline: restores cycle efficiency on plunger/rod wells.
    "paraffin_treatment":      {"cost_usd": 35_000,  "uplift_bopd": 40,  "uplift_decline": 0.60, "p_success": 0.80, "deferred_days": 1},
    # Rod-pump workover (parted rods etc.): restore to pre-failure rate.
    "rod_pump_workover":       {"cost_usd": 110_000, "uplift_bopd": 80,  "uplift_decline": 0.50, "p_success": 0.90, "deferred_days": 4},
    "workover":                {"cost_usd": 110_000, "uplift_bopd": 80,  "uplift_decline": 0.50, "p_success": 0.90, "deferred_days": 4},
}

# ---- Artificial-lift run life (for ESP economic-life / swap-vs-beam) ---------
ESP_RUN_LIFE_YEARS = 2.5              # SPE ESP run-life studies: ~2-3 yr median on gassy/scaling wells
BEAM_RUN_LIFE_YEARS = 6.0            # Rod systems commonly 5-8 yr between major jobs
ESP_WORKOVER_COST_USD = 325_000
BEAM_CONVERSION_COST_USD = 275_000

# ---- Economic limit ---------------------------------------------------------
ECONOMIC_LIMIT_BOPD = 5.0            # Typical stripper abandonment threshold (varies w/ LOE & price)


def intervention_defaults(name: str) -> dict | None:
    """Look up calibrated defaults for an intervention by canonical key (loose match)."""
    key = (name or "").strip().lower().replace(" ", "_").replace("-", "_")
    if key in INTERVENTION_DEFAULTS:
        return INTERVENTION_DEFAULTS[key]
    for k, v in INTERVENTION_DEFAULTS.items():
        if k in key or key in k:
            return v
    return None
