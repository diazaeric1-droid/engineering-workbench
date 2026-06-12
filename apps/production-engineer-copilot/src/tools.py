"""Tool definitions exposed to the Claude agent.

The agent calls these as tools (not LLM math). Each tool wraps a deterministic
analyzer so reasoning happens in the LLM and engineering math stays trusted.
"""
from __future__ import annotations

import json
import math
from typing import Any

import numpy as np

from .analyzers.decline_curve import (
    fit_decline, project_eur, analyze_type_curve, analyze_water_gas_trends,
)
from .analyzers.economics import (
    evaluate_intervention, simulate_intervention, evaluate_esp_economic_life,
)
from .analyzers.esp_diagnostics import evaluate_esp
from .analyzers.dyno_card import evaluate_dyno_card
from .analyzers import assumptions as A
from .data_loader import WellFile


# Tool schemas for Claude (Anthropic tool-use API)
TOOL_SCHEMAS = [
    {
        "name": "fit_decline_curve",
        "description": (
            "Fit an Arps decline model to the well's production history. "
            "Returns initial rate, decline rate, hyperbolic b, R², the full-fit "
            "residual, and a type_curve block: a type curve fit on early/established "
            "decline and extrapolated forward, giving today's rate deviation and the "
            "cumulative deferred production (bbl and $) vs that type curve "
            "(negative deviation = underperforming)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "enum": ["exponential", "harmonic", "hyperbolic"],
                    "default": "hyperbolic",
                },
            },
        },
    },
    {
        "name": "evaluate_esp_health",
        "description": (
            "Evaluate the ESP's operating health: is it within the Preferred "
            "Operating Range (POR)? Are there flags on intake pressure, motor "
            "temperature, or amperage? Returns likely failure modes."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "evaluate_intervention",
        "description": (
            "Run RISKED economics on a proposed intervention (acid stim, ESP swap, "
            "ESP-to-beam conversion, workover). Returns NPV @ 10%, payout in "
            "months, incremental EUR, and discounted profitability index "
            "(PV of inflows / investment; >1.0 = value-accretive). Pass the optional "
            "risk inputs for a VP-grade number: prob_success (chance of success), "
            "deferred_days + base_rate_bopd (production lost while down for the job), "
            "and water_cut_pct + water_disposal_per_bbl (SWD drag on net margin)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Intervention name"},
                "treatment_cost_usd": {"type": "number"},
                "incremental_rate_bopd": {
                    "type": "number",
                    "description": "Expected initial uplift in oil rate (bbl/d)",
                },
                "uplift_decline_per_yr": {"type": "number", "default": 0.6},
                "prob_success": {
                    "type": "number",
                    "description": "Chance of success 0-1 (e.g. 0.75 for a stim). Default 1.0.",
                },
                "deferred_days": {
                    "type": "number",
                    "description": "Days the well is down for the job (deferred production).",
                },
                "base_rate_bopd": {
                    "type": "number",
                    "description": "Current oil rate, used to value deferred production.",
                },
                "water_cut_pct": {
                    "type": "number",
                    "description": "Current water cut %, drives SWD drag on the uplift barrels.",
                },
                "water_disposal_per_bbl": {
                    "type": "number",
                    "description": "Water disposal cost $/bbl (Permian SWD ~$0.5-1.5).",
                },
            },
            "required": ["name", "treatment_cost_usd", "incremental_rate_bopd"],
        },
    },
    {
        "name": "simulate_intervention_economics",
        "description": (
            "Monte-Carlo (~10,000 trials) of an intervention's economics over "
            "uncertain inputs: incremental rate (lognormal ±30%), uplift decline "
            "(±0.15 abs), and realized price (sd ~$12). Returns P10/P50/P90 NPV "
            "(P10=optimistic, P90=conservative), probability of payout (NPV>0 AND "
            "payout < 24 months), and a tornado sensitivity (NPV swing per variable). "
            "Use this when the deterministic NPV is borderline or the user asks about "
            "risk / downside / confidence in an intervention's economics."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Intervention name"},
                "treatment_cost_usd": {"type": "number"},
                "incremental_rate_bopd": {
                    "type": "number",
                    "description": "Expected initial uplift in oil rate (bbl/d)",
                },
                "uplift_decline_per_yr": {"type": "number", "default": 0.6},
            },
            "required": ["name", "treatment_cost_usd", "incremental_rate_bopd"],
        },
    },
    {
        "name": "project_recovery",
        "description": (
            "Project remaining recoverable oil to an economic limit using the "
            "fitted decline. Call fit_decline_curve first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "economic_limit_bopd": {"type": "number", "default": 5.0},
            },
        },
    },
    {
        "name": "interpret_dyno_card",
        "description": (
            "Interpret the most recent dynamometer card for a rod-lifted (beam pump) "
            "well. Classifies the card into an actionable failure mode — fluid pound / "
            "pump-off, parted rods (flat card), gas interference, or healthy full "
            "fillage — and returns the implied severity and recommended intervention. "
            "This is the PRIMARY downhole diagnostic for beam pumps; the decline curve "
            "alone cannot see a pump-off or a parted rod. ALWAYS call this for a beam "
            "pump well that has dyno_cards."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "analyze_water_gas_trends",
        "description": (
            "Compute water-cut and gas-oil-ratio (GOR) levels and trends over the "
            "production history. Surfaces watering-out (economic-limit / lift-sizing "
            "impact) and gassing-up (gas-interference / liquid-loading risk) that the "
            "oil-rate decline curve hides. Call this on every well — many interventions "
            "are driven by the water or gas stream, not the oil rate."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_intervention_assumptions",
        "description": (
            "Look up the project's CALIBRATED, source-cited economic defaults for an "
            "intervention — all-in cost, typical oil uplift, uplift decline, chance of "
            "success, and job downtime — plus the standard price deck, LOE, and SWD cost. "
            "Use these instead of inventing numbers; feed them into evaluate_intervention "
            "(pass prob_success, deferred_days, water_cut_pct, water_disposal_per_bbl for a "
            "risked NPV). Sources: EIA STEO price deck, SPE artificial-lift literature, "
            "public operator cost ranges."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "intervention": {
                    "type": "string",
                    "description": "Intervention name (e.g. 'acid_stimulation', 'esp_swap', 'gas_separator')",
                },
            },
            "required": ["intervention"],
        },
    },
    {
        "name": "evaluate_esp_economic_life",
        "description": (
            "For an ESP well producing BELOW its POR floor, decide ESP-swap vs "
            "ESP-to-beam conversion on LIFECYCLE economics (not a single-job NPV). "
            "Compares lifting the remaining reserves under each option net of the "
            "expected lift-failure cadence — an ESP re-fails every ~2-3 yr at ~$325K/pull, "
            "a beam unit runs 5-8 yr on cheap rod jobs. Use this whenever the well is "
            "below POR and you are weighing a right-size swap against a beam conversion. "
            "Call fit_decline_curve and project_recovery first to get remaining EUR."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "remaining_eur_bbl": {
                    "type": "number",
                    "description": "Remaining recoverable oil (bbl), from project_recovery",
                },
                "well_age_years": {
                    "type": "number",
                    "description": "Years since first production",
                },
            },
            "required": ["remaining_eur_bbl", "well_age_years"],
        },
    },
]


# Valid interventions for the AFE-Copilot handoff. MUST stay in sync with
# afe-copilot/src/cost_db.py COST_TEMPLATES keys — this is the pe→afe contract.
AFE_INTERVENTIONS = (
    "acid_stimulation",
    "scale_treatment",
    "esp_swap",
    "esp_to_beam_conversion",
    "rod_pump_workover",
    "gas_lift_optimization",
    "paraffin_treatment",
    "p_and_a",
)

# Map free-text / report phrasing -> canonical AFE intervention key. Order matters:
# more specific signatures first (e.g. esp-to-beam before plain esp).
_AFE_PHRASE_MAP = [
    ("esp-to-beam", "esp_to_beam_conversion"),
    ("esp to beam", "esp_to_beam_conversion"),
    ("beam pump conversion", "esp_to_beam_conversion"),
    ("convert to beam", "esp_to_beam_conversion"),
    ("scale", "scale_treatment"),
    ("acid", "acid_stimulation"),
    ("matrix acid", "acid_stimulation"),
    ("esp swap", "esp_swap"),
    ("pump swap", "esp_swap"),
    ("replace the esp", "esp_swap"),
    ("right-siz", "esp_swap"),
    ("gas lift", "gas_lift_optimization"),
    ("injection rate", "gas_lift_optimization"),
    ("paraffin", "paraffin_treatment"),
    ("hot oil", "paraffin_treatment"),
    ("wax", "paraffin_treatment"),
    ("parted rod", "rod_pump_workover"),
    ("rod string", "rod_pump_workover"),
    ("workover", "rod_pump_workover"),
    ("rod replacement", "rod_pump_workover"),
    # A pump-off controller / POC is a rod-system optimization; the AFE cost bucket
    # closest to it in the contract is the rod-pump workover template.
    ("pump-off controller", "rod_pump_workover"),
    ("pump off controller", "rod_pump_workover"),
    ("poc", "rod_pump_workover"),
    ("plug and abandon", "p_and_a"),
    ("p&a", "p_and_a"),
    ("abandon", "p_and_a"),
]


def _coerce_intervention(value: str) -> str:
    """Map a possibly-loose intervention string to a valid AFE key, or raise."""
    v = (value or "").strip().lower().replace(" ", "_")
    if v in AFE_INTERVENTIONS:
        return v
    text = (value or "").lower()
    for phrase, key in _AFE_PHRASE_MAP:
        if phrase in text:
            return key
    raise ValueError(
        f"Cannot map intervention {value!r} to a valid AFE intervention. "
        f"Must be one of: {', '.join(AFE_INTERVENTIONS)}"
    )


def export_afe_diagnosis(well: WellFile, review: dict[str, Any]) -> dict:
    """Emit a validated dict matching AFE-Copilot's AFEDiagnosis schema EXACTLY.

    This is the pe→afe chaining contract. `review` carries the engineer's (or
    agent's) selected intervention and economics; `well` supplies identity fields.
    Output keys/types are exactly what afe-copilot AFEDiagnosis.from_json() consumes:
      {well_id, api_number, field, operator, intervention, primary_diagnosis,
       incremental_rate_bopd, expected_uplift_decline_per_yr, requested_by}

    `intervention` is validated/coerced to one of the eight AFE keys.
    Raises ValueError if the intervention cannot be resolved.
    """
    intervention = _coerce_intervention(str(review.get("intervention", "")))

    try:
        rate = float(review.get("incremental_rate_bopd"))
    except (TypeError, ValueError):
        raise ValueError("incremental_rate_bopd is required and must be numeric.")
    if rate < 0:
        raise ValueError("incremental_rate_bopd must be >= 0.")

    decline = review.get("expected_uplift_decline_per_yr", 0.6)
    try:
        decline = float(decline)
    except (TypeError, ValueError):
        decline = 0.6

    operator = (
        review.get("operator")
        or getattr(well, "operator", None)
        or "Operator (synthetic)"
    )
    diagnosis = str(review.get("primary_diagnosis") or "").strip()
    if not diagnosis:
        raise ValueError("primary_diagnosis is required (free-form text).")

    return {
        "well_id": well.well_id,
        "api_number": well.api_number,
        "field": well.field,
        "operator": str(operator),
        "intervention": intervention,
        "primary_diagnosis": diagnosis,
        "incremental_rate_bopd": rate,
        "expected_uplift_decline_per_yr": decline,
        "requested_by": str(review.get("requested_by") or "Senior Production Engineer"),
    }


class ToolExecutor:
    """Executes tool calls against a single well's data. Stateful across the agent loop."""

    def __init__(self, well: WellFile):
        self.well = well
        self._last_fit = None
        self._last_fit_last_day = 0.0  # last observed production day of the fitted history

    def dispatch(self, name: str, args: dict[str, Any]) -> str:
        try:
            result = getattr(self, f"_tool_{name}")(**args)
            return json.dumps(result, default=float, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e), "tool": name})

    def _tool_fit_decline_curve(self, model: str = "hyperbolic") -> dict:
        history = self.well.production_history
        days = np.array([row["day"] for row in history])
        rates = np.array([row["oil_bopd"] for row in history])
        fit = fit_decline(days, rates, model=model)
        self._last_fit = fit
        self._last_fit_last_day = float(days[-1]) if len(days) else 0.0
        out = {
            "model": fit.model,
            "qi_bopd": fit.qi,
            "di_per_day": fit.di,
            "b": fit.b,
            "r_squared": fit.r_squared,
            "last_actual_bopd": fit.last_actual,
            "last_predicted_bopd": fit.last_predicted,
            # Quality-of-fit residual on the full history (NOT a type-curve call).
            "fit_residual_pct": fit.fit_residual_pct,
        }
        # True type-curve benchmark: fit early/established decline, extrapolate, and
        # measure rate deviation today + cumulative deferred production.
        try:
            tc = analyze_type_curve(days, rates, model=model)
            out["type_curve"] = {
                "deviation_pct": round(tc.deviation_pct, 1),
                "type_curve_bopd_today": round(tc.type_curve_at_last, 1),
                "deferred_bbl": round(tc.deferred_bbl, 0),
                "deferred_pct": round(tc.deferred_pct, 1),
                "deferred_value_usd": round(tc.deferred_value_usd, 0),
                "established_on_n_points": tc.established_days,
                "interpretation": (
                    "Underperforming type curve" if tc.deviation_pct < -10
                    else "Outperforming type curve" if tc.deviation_pct > 10
                    else "On type curve"
                ),
            }
        except ValueError as e:
            out["type_curve"] = {"error": str(e)}
        return out

    def _tool_evaluate_esp_health(self) -> dict:
        if self.well.artificial_lift.get("type") != "ESP":
            return {"applicable": False, "reason": "Well is not on ESP"}
        diag = evaluate_esp(self.well.esp_readings, self.well.artificial_lift["pump_spec"])
        return {
            "applicable": True,
            "in_por": diag.in_por,
            "current_bfpd": diag.current_bfpd,
            "por_window_bfpd": [diag.por_min_bfpd, diag.por_max_bfpd],
            "intake_pressure_psi": diag.intake_pressure_psi,
            "motor_temp_f": diag.motor_temp_f,
            "motor_amps": diag.motor_amps,
            "flags": diag.flags,
            "likely_issues": diag.likely_issues,
            "frequency_hz": diag.frequency_hz,
            "discharge_pressure_psi": diag.discharge_pressure_psi,
            "thrust": diag.thrust,
        }

    def _tool_interpret_dyno_card(self) -> dict:
        lift = self.well.artificial_lift.get("type", "")
        if not self.well.dyno_cards:
            return {"applicable": False,
                    "reason": "No dyno cards in data package (request a recent card)."}
        diag = evaluate_dyno_card(self.well.dyno_cards, lift_type=lift)
        return {
            "applicable": True,
            "classification": diag.classification,
            "fillage_pct": diag.fillage_pct,
            "severity": diag.severity,
            "flags": diag.flags,
            "likely_issues": diag.likely_issues,
            "recommended_intervention": diag.recommended_intervention,
        }

    def _tool_analyze_water_gas_trends(self) -> dict:
        if not self.well.production_history:
            return {"error": "No production history."}
        t = analyze_water_gas_trends(self.well.production_history)
        return {
            "latest_water_cut_pct": round(t.latest_water_cut_pct, 1),
            "water_cut_slope_pct_per_yr": round(t.water_cut_slope_pct_per_yr, 2),
            "water_cut_trend": t.water_cut_trend,
            "latest_gor_scf_per_bbl": round(t.latest_gor_scf_per_bbl, 0),
            "gor_slope_scf_per_bbl_per_yr": round(t.gor_slope_scf_per_bbl_per_yr, 0),
            "gor_trend": t.gor_trend,
            "flags": t.flags,
        }

    def _tool_get_intervention_assumptions(self, intervention: str) -> dict:
        d = A.intervention_defaults(intervention)
        market = {
            "realized_price_usd_per_bbl": A.REALIZED_PRICE_USD_PER_BBL,
            "wti_price_usd_per_bbl": A.WTI_PRICE_USD_PER_BBL,
            "loe_usd_per_bbl": A.LOE_USD_PER_BBL,
            "swd_usd_per_bbl_water": A.SWD_USD_PER_BBL_WATER,
            "discount_rate": A.DISCOUNT_RATE,
            "economic_limit_bopd": A.ECONOMIC_LIMIT_BOPD,
            "source": "EIA STEO price deck; Permian LOE/SWD public ranges; SPE artificial-lift literature",
        }
        if d is None:
            return {"intervention": intervention, "found": False,
                    "note": "No calibrated default; use engineering judgement.", "market": market}
        return {
            "intervention": intervention, "found": True,
            "cost_usd": d["cost_usd"], "typical_uplift_bopd": d["uplift_bopd"],
            "uplift_decline_per_yr": d["uplift_decline"], "prob_success": d["p_success"],
            "deferred_days": d["deferred_days"], "market": market,
        }

    def _tool_evaluate_esp_economic_life(self, remaining_eur_bbl: float,
                                         well_age_years: float) -> dict:
        if self.well.artificial_lift.get("type") != "ESP":
            return {"applicable": False, "reason": "Well is not on ESP"}
        if not self.well.esp_readings:
            return {"error": "No ESP readings to read current rate from."}
        spec = self.well.artificial_lift["pump_spec"]
        latest = self.well.esp_readings[-1]
        current_bfpd = latest.get("bfpd", 0.0)
        current_oil = self._last_fit.last_actual if self._last_fit else current_bfpd
        verdict = evaluate_esp_economic_life(
            current_oil_bopd=current_oil,
            current_bfpd=current_bfpd,
            por_min_bfpd=spec.get("por_min_bfpd", 0.0),
            well_age_years=well_age_years,
            remaining_eur_bbl=remaining_eur_bbl,
        )
        return {
            "applicable": True,
            "recommendation": verdict.recommendation,
            "swap_lifecycle_npv_usd": round(verdict.swap_npv_usd, 0),
            "beam_lifecycle_npv_usd": round(verdict.beam_npv_usd, 0),
            "remaining_eur_bbl": round(verdict.remaining_eur_bbl, 0),
            "years_to_deplete": round(verdict.years_to_deplete, 1),
            "rationale": verdict.rationale,
        }

    def _tool_evaluate_intervention(self, **kwargs) -> dict:
        econ = evaluate_intervention(**kwargs)
        return {
            "name": econ.name,
            "treatment_cost_usd": econ.treatment_cost_usd,
            "first_year_incremental_bbl": econ.incremental_first_year_bbl,
            "incremental_eur_bbl": econ.incremental_eur_bbl,
            "npv_10pct_usd": econ.npv_10pct_usd,
            # None (not Infinity) when the intervention never pays out — keeps the
            # tool output valid JSON for any downstream strict parser.
            "payout_months": econ.payout_months if math.isfinite(econ.payout_months) else None,
            "profitability_index": round(econ.profitability_index, 2),
            "recommendation": (
                "STRONG" if econ.npv_10pct_usd > 100_000 and econ.payout_months < 12
                else "MARGINAL" if econ.npv_10pct_usd > 0
                else "REJECT"
            ),
        }

    def _tool_simulate_intervention_economics(self, **kwargs) -> dict:
        sim = simulate_intervention(**kwargs)
        # Round for compact, readable tool output (the agent reasons over these).
        return {
            "name": sim["name"],
            "n_trials": sim["n_trials"],
            "treatment_cost_usd": round(sim["treatment_cost_usd"], 0),
            "npv_p90_conservative_usd": round(sim["npv_p90_usd"], 0),
            "npv_p50_median_usd": round(sim["npv_p50_usd"], 0),
            "npv_p10_optimistic_usd": round(sim["npv_p10_usd"], 0),
            "npv_mean_usd": round(sim["npv_mean_usd"], 0),
            "probability_of_payout": round(sim["probability_of_payout"], 3),
            "payout_cutoff_months": sim["payout_cutoff_months"],
            "tornado_swing_usd": {
                k: round(v["swing"], 0) for k, v in sim["tornado"].items()
            },
            "risk_verdict": (
                "ROBUST" if sim["npv_p90_usd"] > 0 and sim["probability_of_payout"] > 0.8
                else "MARGINAL" if sim["npv_p50_usd"] > 0
                else "HIGH RISK"
            ),
        }

    def _tool_project_recovery(self, economic_limit_bopd: float = 5.0) -> dict:
        if self._last_fit is None:
            return {"error": "Call fit_decline_curve first."}
        # Remaining EUR: integrate the fitted decline FORWARD from the last observed
        # production day, not from t=1 (which double-counts already-produced volume).
        eur = project_eur(
            self._last_fit,
            economic_limit_bopd=economic_limit_bopd,
            from_day=self._last_fit_last_day,
        )
        return {"remaining_eur_bbl": eur, "economic_limit_bopd": economic_limit_bopd}
