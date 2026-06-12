"""Dynamometer-card interpretation for rod-lifted (beam pump) wells.

A dyno card is the surface/downhole load-vs-position trace of a sucker-rod pump.
Its *shape* and the implied pump fillage are the primary downhole diagnostic for
beam pumps — the decline curve alone cannot see a fluid pound, a parted rod, or a
gas-locked pump. This analyzer classifies the card into the failure modes a
production engineer acts on, so the agent has a deterministic signal instead of
guessing from rate.

Input cards are dicts with at least:
    {"date": ..., "pattern": <free-text>, "fillage_pct": <0-100>}
optionally with "peak_load_lb", "min_load_lb", "card_area_pct" (vs full card).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DynoDiagnosis:
    classification: str            # canonical failure-mode label
    fillage_pct: float
    severity: str                  # "none" | "watch" | "act" | "urgent"
    flags: list[str]
    likely_issues: list[str]
    recommended_intervention: str  # canonical intervention key (matches AFE map)


# Fillage thresholds (% of pump barrel filled with liquid each stroke).
_FULL_FILLAGE = 85.0     # at/above this the pump is healthy
_POUND_FILLAGE = 70.0    # below this, incomplete fillage -> fluid pound / pump-off
_PARTED_FILLAGE = 20.0   # near-zero load -> no fluid being lifted (parted rods / hole in barrel)


def _keyword(pattern: str, *words: str) -> bool:
    p = (pattern or "").lower()
    return any(w in p for w in words)


def evaluate_dyno_card(dyno_cards: list[dict], lift_type: str = "Beam Pump") -> DynoDiagnosis:
    """Classify the most recent dyno card into an actionable failure mode.

    Decision order is by severity: parted/flat card first (rig job), then
    fluid pound / pump-off (controller or stroke change), then gas interference,
    then healthy.
    """
    if not dyno_cards:
        raise ValueError("No dyno cards provided.")

    latest = dyno_cards[-1]
    fillage = float(latest.get("fillage_pct", 0.0))
    pattern = str(latest.get("pattern", ""))

    flags: list[str] = []
    issues: list[str] = []

    # --- 1. Flat / no-load card => parted rods or pump/barrel failure (urgent) ---
    flat_signal = _keyword(pattern, "flat", "parted", "no fluid load", "no load")
    if fillage <= _PARTED_FILLAGE or flat_signal:
        flags.append(f"FLAT/NO-LOAD CARD (fillage {fillage:.0f}%)")
        issues.append(
            "No fluid being lifted — parted rod string, unseated/failed pump, or hole in "
            "tubing. Confirm with fluid-level shot; rig intervention required."
        )
        return DynoDiagnosis(
            classification="parted_rods",
            fillage_pct=fillage,
            severity="urgent",
            flags=flags,
            likely_issues=issues,
            recommended_intervention="rod_pump_workover",
        )

    # --- 2. Gas interference: rounded top, gas in the barrel (not pure pound) -----
    gas_signal = _keyword(pattern, "gas interference", "gas-lock", "gas lock", "rounded")
    if gas_signal and fillage < _FULL_FILLAGE:
        flags.append(f"GAS INTERFERENCE SIGNATURE (fillage {fillage:.0f}%)")
        issues.append(
            "Gas in the pump barrel compresses on the upstroke and delays valve action. "
            "Consider tubing/gas anchor, lower SPM, or insert a downhole gas separator "
            "before assuming worn pump."
        )
        return DynoDiagnosis(
            classification="gas_interference",
            fillage_pct=fillage,
            severity="act",
            flags=flags,
            likely_issues=issues,
            recommended_intervention="pump_off_controller",
        )

    # --- 3. Fluid pound / pump-off: incomplete fillage, sharp downstroke drop -----
    pound_signal = _keyword(pattern, "fluid pound", "pound", "pump-off", "pump off", "incomplete fillage")
    if fillage < _POUND_FILLAGE or pound_signal:
        severity = "urgent" if fillage < 50 else "act"
        flags.append(f"FLUID POUND / POOR FILLAGE (fillage {fillage:.0f}%)")
        issues.append(
            "Pump is outrunning inflow — incomplete fillage causes fluid pound, accelerating "
            "rod/pump fatigue. Install a pump-off controller (POC) or reduce SPM to match inflow; "
            "evaluate downsizing the plunger if chronic."
        )
        return DynoDiagnosis(
            classification="fluid_pound_pumpoff",
            fillage_pct=fillage,
            severity=severity,
            flags=flags,
            likely_issues=issues,
            recommended_intervention="pump_off_controller",
        )

    # --- 4. Healthy / full fillage --------------------------------------------------
    flags.append(f"FULL FILLAGE (fillage {fillage:.0f}%)")
    issues.append("Card shape and fillage are healthy — no downhole pump intervention indicated.")
    return DynoDiagnosis(
        classification="healthy",
        fillage_pct=fillage,
        severity="none",
        flags=flags,
        likely_issues=issues,
        recommended_intervention="monitor",
    )
