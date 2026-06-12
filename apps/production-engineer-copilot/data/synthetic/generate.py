"""Generate a diverse synthetic well dataset for evals.

Design principles (v0.4):
  1. PARAMETERIZED — every archetype draws its reservoir/lift parameters from bounded
     distributions, so each case is a distinct point in a realistic range rather than a
     single hand-tuned well. This is what makes a larger N a real test instead of N copies.
  2. NO ANSWER LEAK — the well-file `notes` carry only raw FIELD OBSERVATIONS (rates,
     pressures, dates, offset behavior) plus distractors. They never state the diagnosis or
     the recommended intervention. The expert label lives ONLY in cases.yaml, which the agent
     never sees. The agent must reason from tool signals, not parrot the notes.
  3. BOUNDARY CASES — includes ambiguous / two-signal / insufficient-data wells where a
     junior and a senior reviewer diverge. These are where real acceptance rate lives.
  4. BLIND HOLDOUT — `--holdout` emits a separate family (different seed + id range) into
     data/synthetic/holdout/ and evals/holdout_cases.yaml. Tune the prompt on the dev set;
     run the holdout ONCE and report THAT number.

Usage:
    python data/synthetic/generate.py            # dev set -> well_0NN.json + evals/cases.yaml
    python data/synthetic/generate.py --holdout  # blind set -> holdout/ + evals/holdout_cases.yaml
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

OUT = Path(__file__).parent
STANDARD_DAYS = [30, 60, 90, 120, 180, 240, 300, 365, 450, 540, 630, 720, 810, 900, 990]


# ---------- production-history helpers --------------------------------------

def hyperbolic_history(
    rng: np.random.Generator,
    qi: float, di: float, b: float,
    days: list[int] = STANDARD_DAYS,
    noise: float = 0.05,
    water_ratio0: float = 0.5, water_ratio_slope: float = 1 / 1500,
    gor0: float = 1.8, gor_slope: float = -1 / 2000,
) -> list[dict]:
    """Hyperbolic oil decline with configurable water-cut and GOR trends.

    water_bwpd = oil * (water_ratio0 + slope*day);  gas_mcfd = oil * (gor0 + gor_slope*day).
    Positive gor_slope => gassing up (gas-interference / loading signal).
    """
    out = []
    for d in days:
        oil = qi / ((1 + b * di * d) ** (1 / b)) * (1 + rng.normal(0, noise))
        water = oil * max(water_ratio0 + water_ratio_slope * d, 0.0)
        gas = oil * max(gor0 + gor_slope * d, 0.0)
        out.append({"day": d, "oil_bopd": round(max(oil, 0), 1),
                    "water_bwpd": round(max(water, 0), 1),
                    "gas_mcfd": round(max(gas, 0), 1)})
    return out


def underperform(history: list[dict], from_day: int, factor: float) -> list[dict]:
    for row in history:
        if row["day"] >= from_day:
            row["oil_bopd"] = round(row["oil_bopd"] * factor, 1)
    return history


def _esp_reading(date, bfpd, intake, temp, amps, freq=None, disch=None) -> dict:
    r = {"date": date, "bfpd": round(bfpd), "intake_pressure_psi": round(intake),
         "motor_temp_f": round(temp), "motor_amps": round(amps)}
    if freq is not None:
        r["frequency_hz"] = round(freq)
    if disch is not None:
        r["discharge_pressure_psi"] = round(disch)
    return r


def _f(rng, lo, hi):  # uniform float
    return float(rng.uniform(lo, hi))


# ---------- scenario builders (idx, rng) ------------------------------------
# Each returns a well dict whose notes are observation-only (no diagnosis / answer).

def esp_below_por(idx, rng):
    qi = _f(rng, 1000, 1300)
    bfpd = _f(rng, 1450, 1740)             # below a 1800 POR floor
    intake = _f(rng, 55, 90)               # NOT low (rules out gas)
    amps = _f(rng, 55, 64)                 # within nameplate (rules out scale)
    return {
        "well_id": f"ED-{idx:03d}H", "api_number": f"42-109-{10000 + idx}",
        "field": "Delaware Basin (synthetic)", "operator": "Synthetic Operator LLC",
        "spud_date": "2022-04-10", "first_prod_date": "2022-07-01",
        "completion": {"lateral_length_ft": 9800, "stages": 48, "proppant_lb_per_ft": 2300,
                       "fluid_bbl_per_ft": 52, "formation": "Wolfcamp B"},
        "artificial_lift": {"type": "ESP", "installed_date": "2024-01-15",
            "pump_spec": {"model": "REDA 538-D2700N", "stages": 180,
                          "por_min_bfpd": 1800, "por_max_bfpd": 3400,
                          "motor_temp_max_f": 350, "motor_amps_nameplate": 65}},
        "production_history": underperform(
            hyperbolic_history(rng, qi, _f(rng, 0.0032, 0.0038), _f(rng, 0.8, 0.95)), 720, _f(rng, 0.7, 0.82)),
        "esp_readings": [
            _esp_reading("2026-05-21", bfpd + 70, intake + 6, _f(rng, 285, 300), amps, freq=_f(rng, 52, 58)),
            _esp_reading("2026-05-25", bfpd, intake, _f(rng, 288, 300), amps + 2, freq=_f(rng, 52, 58)),
        ],
        "scada_recent": [], "dyno_cards": [],
        "notes": [f"Pump rate ~{bfpd:.0f} BFPD on last test; intake ~{intake:.0f} psi.",
                  "Annual subsurface review pulled this well for inspection."],
    }


def esp_gas_interference(idx, rng):
    bfpd = _f(rng, 1900, 2200)
    intake = _f(rng, 12, 28)               # LOW intake => gas
    amps = _f(rng, 50, 58)
    return {
        "well_id": f"ED-{idx:03d}H", "api_number": f"42-109-{10000 + idx}",
        "field": "Midland Basin (synthetic)", "operator": "Synthetic Operator LLC",
        "spud_date": "2021-08-22", "first_prod_date": "2021-11-15",
        "completion": {"lateral_length_ft": 10200, "stages": 50, "proppant_lb_per_ft": 2500,
                       "fluid_bbl_per_ft": 58, "formation": "Wolfcamp A"},
        "artificial_lift": {"type": "ESP", "installed_date": "2023-06-10",
            "pump_spec": {"model": "Centrilift FC-2200", "stages": 200,
                          "por_min_bfpd": 1500, "por_max_bfpd": 3000,
                          "motor_temp_max_f": 350, "motor_amps_nameplate": 60}},
        # Rising GOR (positive gor_slope) so analyze_water_gas_trends flags gassing-up.
        "production_history": hyperbolic_history(rng, _f(rng, 1200, 1400), 0.004, 0.9,
                                                 gor0=1.4, gor_slope=1 / 1200),
        "esp_readings": [
            _esp_reading("2026-05-21", bfpd, intake + 4, _f(rng, 315, 325), amps + 3, freq=_f(rng, 56, 60)),
            _esp_reading("2026-05-25", bfpd - 120, intake, _f(rng, 320, 330), amps, freq=_f(rng, 56, 60)),
        ],
        "scada_recent": [], "dyno_cards": [],
        "notes": [f"Last intake reading {intake:.0f} psi. Casing pressure up ~30 psi over two weeks.",
                  "High-GLR area of the field. No downhole separator on this completion."],
    }


def esp_scale(idx, rng):
    amps_nom = 65
    amps = _f(rng, amps_nom * 1.2, amps_nom * 1.35)   # HIGH amps => scale/load
    intake = _f(rng, 85, 100)
    return {
        "well_id": f"ED-{idx:03d}H", "api_number": f"42-109-{10000 + idx}",
        "field": "Delaware Basin (synthetic)", "operator": "Synthetic Operator LLC",
        "spud_date": "2021-05-01", "first_prod_date": "2021-08-01",
        "completion": {"lateral_length_ft": 10800, "stages": 54, "proppant_lb_per_ft": 2400,
                       "fluid_bbl_per_ft": 55, "formation": "Bone Spring 3rd"},
        "artificial_lift": {"type": "ESP", "installed_date": "2023-09-15",
            "pump_spec": {"model": "REDA 538-D2700N", "stages": 180,
                          "por_min_bfpd": 1800, "por_max_bfpd": 3400,
                          "motor_temp_max_f": 350, "motor_amps_nameplate": amps_nom}},
        "production_history": underperform(
            hyperbolic_history(rng, _f(rng, 1150, 1300), 0.0038, 0.88), 810, _f(rng, 0.68, 0.78)),
        "esp_readings": [
            _esp_reading("2026-05-21", _f(rng, 2100, 2300), intake + 4, _f(rng, 328, 338), amps - 3, freq=60),
            _esp_reading("2026-05-25", _f(rng, 2050, 2250), intake, _f(rng, 332, 342), amps, freq=60),
        ],
        "scada_recent": [], "dyno_cards": [],
        "notes": ["High-calcium-carbonate area. Last inhibitor batch logged ~4 months ago.",
                  "Motor amps stepping up week over week on the trend sheet."],
    }


def esp_normal(idx, rng):
    return {
        "well_id": f"ED-{idx:03d}H", "api_number": f"42-109-{10000 + idx}",
        "field": "Delaware Basin (synthetic)", "operator": "Synthetic Operator LLC",
        "spud_date": "2023-02-10", "first_prod_date": "2023-05-01",
        "completion": {"lateral_length_ft": 10500, "stages": 52, "proppant_lb_per_ft": 2400,
                       "fluid_bbl_per_ft": 55, "formation": "Wolfcamp A"},
        "artificial_lift": {"type": "ESP", "installed_date": "2024-08-01",
            "pump_spec": {"model": "REDA 538-D2700N", "stages": 180,
                          "por_min_bfpd": 1800, "por_max_bfpd": 3400,
                          "motor_temp_max_f": 350, "motor_amps_nameplate": 65}},
        "production_history": hyperbolic_history(rng, _f(rng, 1100, 1200), 0.0032, 0.92),
        "esp_readings": [
            _esp_reading("2026-05-21", _f(rng, 2350, 2450), _f(rng, 120, 140), _f(rng, 283, 290), _f(rng, 60, 64), freq=58),
            _esp_reading("2026-05-25", _f(rng, 2330, 2430), _f(rng, 120, 138), _f(rng, 284, 290), _f(rng, 60, 64), freq=58),
        ],
        "scada_recent": [], "dyno_cards": [],
        "notes": ["Routine quarterly surveillance pull. No operator complaints logged."],
    }


def esp_to_beam_candidate(idx, rng):
    """OLD, depleted, below-POR ESP well — lifecycle economics favor beam conversion.

    Aged to 14-17 yr so the ESP re-fail cadence (every ~2-3 yr) dominates the decision,
    which is what makes a conversion beat a swap. The agent should reach this via
    evaluate_esp_economic_life, NOT from the notes.
    """
    bfpd = _f(rng, 620, 880)
    return {
        "well_id": f"ED-{idx:03d}H", "api_number": f"42-109-{10000 + idx}",
        "field": "Midland Basin (synthetic)", "operator": "Synthetic Operator LLC",
        "spud_date": "2009-06-01", "first_prod_date": "2009-09-01",
        "completion": {"lateral_length_ft": 7200, "stages": 18, "proppant_lb_per_ft": 1200,
                       "fluid_bbl_per_ft": 30, "formation": "Spraberry"},
        "artificial_lift": {"type": "ESP", "installed_date": "2024-02-15",
            "pump_spec": {"model": "REDA 400-series", "stages": 140,
                          "por_min_bfpd": 1500, "por_max_bfpd": 3000,
                          "motor_temp_max_f": 350, "motor_amps_nameplate": 55}},
        # Old, depleted: low qi, low GOR, high/rising water cut.
        "production_history": underperform(
            hyperbolic_history(rng, _f(rng, 500, 650), 0.0022, 0.6,
                               water_ratio0=1.2, water_ratio_slope=1 / 900,
                               gor0=0.7, gor_slope=-1 / 4000), 540, _f(rng, 0.45, 0.6)),
        "esp_readings": [
            _esp_reading("2026-05-21", bfpd + 30, _f(rng, 70, 85), _f(rng, 300, 312), _f(rng, 42, 48), freq=_f(rng, 40, 44)),
            _esp_reading("2026-05-25", bfpd, _f(rng, 68, 82), _f(rng, 302, 312), _f(rng, 41, 47), freq=_f(rng, 40, 44)),
        ],
        "scada_recent": [], "dyno_cards": [],
        "notes": [f"Rate ~{bfpd:.0f} BFPD; VSD already near minimum frequency.",
                  "Several offset wells in this section run rod lift."],
    }


def beam_pump_pumpoff(idx, rng):
    return {
        "well_id": f"ED-{idx:03d}H", "api_number": f"42-109-{10000 + idx}",
        "field": "Permian conventional (synthetic)", "operator": "Synthetic Operator LLC",
        "spud_date": "2015-03-01", "first_prod_date": "2015-06-01",
        "completion": {"lateral_length_ft": 0, "stages": 0, "proppant_lb_per_ft": 0,
                       "fluid_bbl_per_ft": 0, "formation": "San Andres"},
        "artificial_lift": {"type": "Beam Pump", "installed_date": "2019-04-10",
            "pump_spec": {"model": "C-228D-200-74", "stroke_in": 74, "spm": 6.5, "plunger_in": 1.75}},
        "production_history": hyperbolic_history(rng, _f(rng, 110, 130), 0.001, 0.5, noise=0.08),
        "esp_readings": [], "scada_recent": [],
        "dyno_cards": [{"date": "2026-05-25",
                        "pattern": "Incomplete fillage, sharp load drop on the downstroke.",
                        "fillage_pct": round(_f(rng, 48, 64))}],
        "notes": ["Pumping-unit cycle counter trending up over the last month.",
                  "Operator requested a surveillance review."],
    }


def beam_pump_normal(idx, rng):
    w = beam_pump_pumpoff(idx, rng)
    w["dyno_cards"] = [{"date": "2026-05-25", "pattern": "Full, well-shaped card.",
                        "fillage_pct": round(_f(rng, 90, 98))}]
    w["notes"] = ["Annual integrity check due. No production complaints."]
    return w


def beam_pump_parted_rods(idx, rng):
    w = beam_pump_pumpoff(idx, rng)
    w["production_history"] = underperform(w["production_history"], 900, 0.05)
    w["dyno_cards"] = [{"date": "2026-05-25", "pattern": "Flat card, no fluid load.",
                        "fillage_pct": round(_f(rng, 2, 10))}]
    w["notes"] = ["Production dropped to near zero over a single day.",
                  "Surface unit still stroking."]
    return w


def gas_lift_liquid_loading(idx, rng):
    return {
        "well_id": f"ED-{idx:03d}H", "api_number": f"42-109-{10000 + idx}",
        "field": "GoM Offshore (synthetic)", "operator": "Synthetic Operator LLC",
        "spud_date": "2018-09-01", "first_prod_date": "2019-02-15",
        "completion": {"lateral_length_ft": 0, "stages": 0, "proppant_lb_per_ft": 0,
                       "fluid_bbl_per_ft": 0, "formation": "Pliocene"},
        "artificial_lift": {"type": "Gas Lift", "installed_date": "2019-02-15",
            "pump_spec": {"injection_rate_mscfd_design": 1500, "valve_count": 6}},
        # Rising GOR + degraded tail = loading signature.
        "production_history": underperform(
            hyperbolic_history(rng, _f(rng, 720, 880), 0.0028, 0.8, gor0=1.5, gor_slope=1 / 1000), 720, _f(rng, 0.5, 0.62)),
        "esp_readings": [], "scada_recent": [], "dyno_cards": [],
        "notes": ["Tubing-head pressure cycling at surface; intermittent liquid slugs to the separator.",
                  "Lift-gas metering station flagged possible under-injection."],
    }


def gas_lift_normal(idx, rng):
    w = gas_lift_liquid_loading(idx, rng)
    w["production_history"] = hyperbolic_history(rng, _f(rng, 700, 800), 0.003, 0.85)
    w["notes"] = ["Stable THP, steady separator rate. Routine surveillance."]
    return w


def plunger_lift_sticking(idx, rng):
    return {
        "well_id": f"ED-{idx:03d}H", "api_number": f"42-109-{10000 + idx}",
        "field": "Eagle Ford (synthetic)", "operator": "Synthetic Operator LLC",
        "spud_date": "2017-11-01", "first_prod_date": "2018-02-01",
        "completion": {"lateral_length_ft": 7500, "stages": 30, "proppant_lb_per_ft": 1800,
                       "fluid_bbl_per_ft": 40, "formation": "Eagle Ford"},
        "artificial_lift": {"type": "Plunger Lift", "installed_date": "2020-06-01",
            "pump_spec": {"plunger_type": "Bypass", "cycles_per_day_target": 24}},
        "production_history": underperform(
            hyperbolic_history(rng, _f(rng, 270, 330), 0.002, 0.7), 810, _f(rng, 0.55, 0.65)),
        "esp_readings": [], "scada_recent": [], "dyno_cards": [],
        "notes": ["Plunger arrival times erratic; cycle count down ~40% month over month.",
                  "Cooler weather onset; tubing temperature survey overdue."],
    }


def low_recovery_p_and_a_candidate(idx, rng):
    base = _f(rng, 2.5, 4.5)
    return {
        "well_id": f"ED-{idx:03d}H", "api_number": f"42-109-{10000 + idx}",
        "field": "Permian marginal (synthetic)", "operator": "Synthetic Operator LLC",
        "spud_date": "2005-01-15", "first_prod_date": "2005-04-01",
        "completion": {"lateral_length_ft": 0, "stages": 0, "proppant_lb_per_ft": 0,
                       "fluid_bbl_per_ft": 0, "formation": "Spraberry"},
        "artificial_lift": {"type": "Beam Pump", "installed_date": "2010-01-01",
            "pump_spec": {"model": "C-114D-143-64", "stroke_in": 64, "spm": 5, "plunger_in": 1.5}},
        "production_history": [{"day": d, "oil_bopd": round(base + rng.normal(0, 0.4), 1),
                                "water_bwpd": 90, "gas_mcfd": 8} for d in STANDARD_DAYS],
        "esp_readings": [], "scada_recent": [],
        "dyno_cards": [{"date": "2026-05-25", "pattern": "Low fluid load.", "fillage_pct": round(_f(rng, 60, 75))}],
        "notes": [f"~{base:.0f} BOPD against ~90 BWPD for the last 6 months.",
                  "Lease operating cost sheet attached; last pulling job was a repair."],
    }


def acid_stim_candidate(idx, rng):
    """Classic scale/skin signature: low intake + HIGH amps (both signals present)."""
    amps_nom = 65
    return {
        "well_id": f"ED-{idx:03d}H", "api_number": f"42-109-{10000 + idx}",
        "field": "Delaware Basin (synthetic)", "operator": "Synthetic Operator LLC",
        "spud_date": "2021-12-01", "first_prod_date": "2022-03-15",
        "completion": {"lateral_length_ft": 10500, "stages": 52, "proppant_lb_per_ft": 2400,
                       "fluid_bbl_per_ft": 55, "formation": "Wolfcamp A"},
        "artificial_lift": {"type": "ESP", "installed_date": "2023-08-01",
            "pump_spec": {"model": "REDA 538-D2700N", "stages": 180,
                          "por_min_bfpd": 1800, "por_max_bfpd": 3400,
                          "motor_temp_max_f": 350, "motor_amps_nameplate": amps_nom}},
        "production_history": underperform(
            hyperbolic_history(rng, _f(rng, 1150, 1300), 0.004, 0.9), 810, _f(rng, 0.68, 0.76)),
        "esp_readings": [
            _esp_reading("2026-05-21", _f(rng, 1650, 1750), _f(rng, 34, 42), _f(rng, 298, 306), amps_nom * 1.2, freq=60),
            _esp_reading("2026-05-25", _f(rng, 1600, 1700), _f(rng, 30, 38), _f(rng, 300, 308), amps_nom * 1.25, freq=60),
        ],
        "scada_recent": [], "dyno_cards": [],
        "notes": ["Intake pressure stepping down while amps step up on the trend sheet.",
                  "Three months since the last chemical treatment on this well."],
    }


# ---------- boundary / ambiguous cases --------------------------------------

def esp_scale_with_gas_distractor(idx, rng):
    """Two signals: dominant HIGH-amp scale load + a secondary mild low-intake.
    Senior call is scale treatment first (mechanical work re-fails if scale untreated).
    Tests robustness to a distractor signal."""
    w = esp_scale(idx, rng)
    # add a mild gas distractor: nudge intake down a bit but keep amps clearly high
    for r in w["esp_readings"]:
        r["intake_pressure_psi"] = round(_f(rng, 46, 58))
    w["notes"] = ["Amps elevated and stepping up; intake pressure somewhat low.",
                  "Some gas breakout noted on a recent fluid shot."]
    return w


def esp_acid_then_swap_sequenced(idx, rng):
    """Skin/scale damage AND below-POR: the right path is a sequenced workover
    (treat first, then right-size). Either 'scale/acid' or 'esp swap' phrasing is
    acceptable as primary; label keyed to the lead step (scale treatment)."""
    w = acid_stim_candidate(idx, rng)
    for r in w["esp_readings"]:
        r["bfpd"] = round(_f(rng, 1500, 1700))   # also below POR
    w["notes"] = ["Below typical pump throughput with amps up and intake down.",
                  "Combined remedial + lift-sizing review requested."]
    return w


def insufficient_data_well(idx, rng):
    """Too little history to fit a decline and no lift diagnostics — the correct answer
    is to ask for more data, NOT to invent an intervention. Tests honesty/restraint."""
    days = [30, 60, 90, 120]
    return {
        "well_id": f"ED-{idx:03d}H", "api_number": f"42-109-{10000 + idx}",
        "field": "Delaware Basin (synthetic)", "operator": "Synthetic Operator LLC",
        "spud_date": "2025-11-01", "first_prod_date": "2026-01-15",
        "completion": {"lateral_length_ft": 10000, "stages": 50, "proppant_lb_per_ft": 2400,
                       "fluid_bbl_per_ft": 55, "formation": "Wolfcamp A"},
        "artificial_lift": {"type": "ESP", "installed_date": "2026-01-15",
            "pump_spec": {"model": "REDA 538-D2700N", "stages": 180,
                          "por_min_bfpd": 1800, "por_max_bfpd": 3400,
                          "motor_temp_max_f": 350, "motor_amps_nameplate": 65}},
        "production_history": [{"day": d, "oil_bopd": round(_f(rng, 900, 1100) * (1 - d / 4000), 1),
                                "water_bwpd": round(_f(rng, 400, 600), 1),
                                "gas_mcfd": round(_f(rng, 1500, 1900), 1)} for d in days],
        "esp_readings": [],   # no readings -> ESP health cannot be evaluated
        "scada_recent": [], "dyno_cards": [],
        "notes": ["New well; only four monthly tests available so far.",
                  "Downhole gauge install pending; no ESP card yet."],
    }


# ---------- scenario registry -----------------------------------------------
# (builder, dev_count, holdout_count, expected_recommendation, keywords)
SCENARIOS = [
    (acid_stim_candidate,            2, 1, "acid_stimulation",          ["below POR", "low intake pressure", "scale"]),
    (esp_below_por,                  4, 2, "esp_swap",                  ["below POR", "downthrust"]),
    (esp_gas_interference,           4, 2, "gas_separator",             ["low intake pressure", "gas interference"]),
    (esp_scale,                      3, 1, "scale_treatment",           ["scale", "high amps"]),
    (esp_normal,                     3, 1, "monitor",                   ["on type curve", "in POR"]),
    (esp_to_beam_candidate,          3, 1, "esp-to-beam_conversion",    ["below POR", "end of ESP"]),
    (beam_pump_pumpoff,              3, 1, "pump-off_controller",       ["fluid pound", "pump-off"]),
    (beam_pump_normal,               2, 1, "monitor",                   ["normal", "fillage"]),
    (beam_pump_parted_rods,          2, 1, "workover",                  ["parted rods", "rig"]),
    (gas_lift_liquid_loading,        3, 1, "gas_lift_optimization",     ["liquid loading", "slugging"]),
    (gas_lift_normal,                2, 1, "monitor",                   ["stable", "on type curve"]),
    (plunger_lift_sticking,          2, 1, "paraffin_treatment",        ["plunger", "paraffin"]),
    (low_recovery_p_and_a_candidate, 2, 1, "p&a",                       ["uneconomic", "p&a candidate"]),
    # boundary / ambiguous
    (esp_scale_with_gas_distractor,  2, 1, "scale_treatment",           ["scale", "high amps"]),
    (esp_acid_then_swap_sequenced,   2, 1, "scale_treatment",           ["below POR", "scale"]),
    (insufficient_data_well,         2, 1, "insufficient_data",         ["insufficient data", "more data"]),
]


def _emit(holdout: bool):
    seed = 1234 if holdout else 42
    rng = np.random.default_rng(seed)
    out_dir = OUT / "holdout" if holdout else OUT
    out_dir.mkdir(exist_ok=True)
    prefix = "hold" if holdout else "well"
    cases_name = "holdout_cases.yaml" if holdout else "cases.yaml"

    header = f"# Auto-generated by data/synthetic/generate.py {'--holdout' if holdout else ''}".rstrip()
    lines = [header,
             "# Labels live here ONLY; the agent never sees this file. Well-file notes are observation-only.",
             "cases:"]

    idx = 1
    count_key = 2 if holdout else 1
    for entry in SCENARIOS:
        builder, dev_count, hold_count, rec, keywords = entry
        n = hold_count if holdout else dev_count
        for _ in range(n):
            well = builder(idx, rng)
            (out_dir / f"{prefix}_{idx:03d}.json").write_text(json.dumps(well, indent=2))
            rel = f"data/synthetic/{'holdout/' if holdout else ''}{prefix}_{idx:03d}.json"
            lines.append(
                f"  - id: case_{idx:03d}\n"
                f"    well_file: {rel}\n"
                f"    expected_primary_recommendation: {rec}\n"
                f"    expected_diagnosis_keywords: {json.dumps(keywords)}\n"
                f"    lift: {well['artificial_lift']['type']}\n"
                f"    archetype: {builder.__name__}\n"
                f"    notes: {builder.__name__}"
            )
            idx += 1

    cases_path = OUT.parent.parent / "evals" / cases_name
    cases_path.write_text("\n".join(lines) + "\n")
    print(f"Wrote {idx - 1} wells to {out_dir} and {cases_path.name}.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdout", action="store_true",
                    help="Emit the blind holdout set (separate seed + id range)")
    ap.add_argument("--both", action="store_true", help="Emit both dev and holdout sets")
    args = ap.parse_args()
    if args.both:
        _emit(holdout=False)
        _emit(holdout=True)
    else:
        _emit(holdout=args.holdout)


if __name__ == "__main__":
    main()
