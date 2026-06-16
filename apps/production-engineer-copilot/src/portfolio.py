"""Field / portfolio mode — rank a whole field of wells by intervention value.

A VP doesn't want one well review; they want "of my 200 wells, which handful do I
work over this quarter, and in what order?" This is a fast, fully DETERMINISTIC screen
(no LLM, no API cost): for each well it runs the same analyzers the agent uses, picks the
physically indicated intervention with the prompt's heuristics, pulls the calibrated
economics, and ranks by risked NPV and capital efficiency (profitability index).

Use it as the triage layer that decides which wells deserve a full agent review.

    python -m src.portfolio data/synthetic/well_*.json
    python -m src.portfolio --by pi data/synthetic/well_0*.json
"""
from __future__ import annotations

import argparse
import glob
import json
import warnings
from dataclasses import dataclass, asdict

import numpy as np

from .data_loader import WellFile, _age_years
from .analyzers.decline_curve import fit_decline, project_eur, analyze_type_curve, analyze_water_gas_trends
from .analyzers.esp_diagnostics import evaluate_esp
from .analyzers.dyno_card import evaluate_dyno_card
from .analyzers.economics import evaluate_intervention, evaluate_esp_economic_life
from .analyzers import assumptions as A

warnings.filterwarnings("ignore")

# interventions with no incremental-rate economics (don't rank by NPV)
_NON_ECONOMIC = {"monitor", "p&a", "insufficient_data"}


@dataclass
class PortfolioRow:
    well_id: str
    lift: str
    diagnosis: str
    intervention: str
    npv_usd: float
    payout_months: float | None
    profitability_index: float
    capital_usd: float
    remaining_eur_bbl: float


def _indicated_intervention(well: WellFile) -> tuple[str, str]:
    """Deterministic mirror of the agent's selection heuristics -> (intervention, diagnosis)."""
    hist = well.production_history
    days = np.array([r.get("day", 0) for r in hist], float)
    oil = np.array([r.get("oil_bopd", 0) for r in hist], float)
    lift = well.artificial_lift.get("type", "")

    # Insufficient data: can't fit a decline and no lift diagnostics.
    fittable = (oil > 0).sum() >= 5
    if not fittable and not well.esp_readings and not well.dyno_cards:
        return "insufficient_data", "Insufficient data to fit decline or diagnose lift"

    wg = analyze_water_gas_trends(hist) if hist else None
    last_oil = float(oil[oil > 0][-1]) if (oil > 0).any() else 0.0

    # Sub-economic old stripper -> P&A
    age = _age_years(well.first_prod_date) or 0
    if last_oil < A.ECONOMIC_LIMIT_BOPD * 2 and age >= 15:
        return "p&a", f"~{last_oil:.0f} BOPD on a {age:.0f}-yr well; below economic limit"

    if lift == "ESP" and well.esp_readings:
        d = evaluate_esp(well.esp_readings, well.artificial_lift["pump_spec"])
        ft = " ".join(d.flags).lower()
        if "high amps" in ft:
            return "scale_treatment", "High amps + degraded rate — scale/load signature"
        if "low intake" in ft:
            return "gas_separator", "Low intake pressure — gas interference"
        if not d.in_por and d.current_bfpd < d.por_min_bfpd:
            try:
                # Remaining EUR: integrate the decline FORWARD from the last observed
                # production day (not t=1), else already-produced volume is double-counted.
                eur = project_eur(fit_decline(days, oil), from_day=float(days[-1]))
            except Exception:
                eur = 0.0
            verdict = evaluate_esp_economic_life(
                current_oil_bopd=last_oil, current_bfpd=d.current_bfpd,
                por_min_bfpd=d.por_min_bfpd, well_age_years=age, remaining_eur_bbl=eur)
            return verdict.recommendation, f"Below POR ({d.current_bfpd:.0f}<{d.por_min_bfpd:.0f}); {verdict.recommendation}"
        return "monitor", "ESP in POR, no flags"

    if lift in ("Beam Pump", "Rod Pump") and well.dyno_cards:
        dc = evaluate_dyno_card(well.dyno_cards, lift)
        return dc.recommended_intervention, f"Dyno: {dc.classification} (fillage {dc.fillage_pct:.0f}%)"

    if lift == "Gas Lift" and wg and wg.gor_trend == "rising":
        return "gas_lift_optimization", "Rising GOR — liquid loading / under-injection"

    if lift == "Plunger Lift":
        try:
            tc = analyze_type_curve(days, oil)
            if tc.deviation_pct < -10:
                return "paraffin_treatment", f"{tc.deviation_pct:.0f}% below type curve — plunger/paraffin"
        except Exception:
            pass

    return "monitor", "No intervention signal"


def screen_well(path: str) -> PortfolioRow:
    """Screen a well JSON path (synthetic fleet). Thin wrapper over ``screen_wellfile``."""
    return screen_wellfile(WellFile.from_json(path))


def screen_wellfile(well: WellFile, realized_price_per_bbl: float | None = None) -> PortfolioRow:
    """Deterministic screen of an in-memory ``WellFile`` (synthetic OR real adapter output).

    Identical logic to ``screen_well`` — extracted so adapter-built wells (e.g. NDIC
    monthly fleet) get the SAME diagnosis + risked economics without a JSON round-trip.

    ``realized_price_per_bbl`` lets a caller (e.g. the AI Well Review at a live price deck)
    drive the risked NPV off the same price its other panels use, so the headline number
    cannot silently diverge from a deck-responsive Monte-Carlo. ``None`` keeps the calibrated
    default (REALIZED_PRICE_USD_PER_BBL) — preserving the CLI / portfolio-ranking behaviour.
    """
    intervention, diagnosis = _indicated_intervention(well)
    oil = np.array([r.get("oil_bopd", 0) for r in well.production_history], float)
    last_oil = float(oil[oil > 0][-1]) if (oil > 0).any() else 0.0
    try:
        _days = np.array([r["day"] for r in well.production_history], float)
        # Remaining EUR integrated FORWARD from the last observed day (not t=1).
        eur = project_eur(fit_decline(_days, oil), from_day=float(_days[-1]))
    except Exception:
        eur = 0.0
    wg = analyze_water_gas_trends(well.production_history) if well.production_history else None
    wc = wg.latest_water_cut_pct if wg else 0.0

    if intervention in _NON_ECONOMIC:
        return PortfolioRow(well.well_id, well.artificial_lift.get("type", ""), diagnosis,
                            intervention, 0.0, None, 0.0, 0.0, round(eur))

    d = A.intervention_defaults(intervention) or {"cost_usd": 150_000, "uplift_bopd": 80,
                                                  "uplift_decline": 0.6, "p_success": 0.8, "deferred_days": 3}
    _price_kw = ({} if realized_price_per_bbl is None
                 else {"realized_price_per_bbl": float(realized_price_per_bbl)})
    econ = evaluate_intervention(
        name=intervention, treatment_cost_usd=d["cost_usd"], incremental_rate_bopd=d["uplift_bopd"],
        uplift_decline_per_yr=d["uplift_decline"], prob_success=d["p_success"],
        deferred_days=d["deferred_days"], base_rate_bopd=last_oil,
        water_cut_pct=wc, water_disposal_per_bbl=A.SWD_USD_PER_BBL_WATER, **_price_kw)
    payout = econ.payout_months if np.isfinite(econ.payout_months) else None
    return PortfolioRow(well.well_id, well.artificial_lift.get("type", ""), diagnosis,
                        intervention, round(econ.npv_10pct_usd), payout,
                        round(econ.profitability_index, 2), round(econ.treatment_cost_usd), round(eur))


def rank(paths: list[str], by: str = "npv") -> list[PortfolioRow]:
    rows = [screen_well(p) for p in paths]
    key = {"npv": lambda r: r.npv_usd, "pi": lambda r: r.profitability_index,
           "eur": lambda r: r.remaining_eur_bbl}.get(by, lambda r: r.npv_usd)
    return sorted(rows, key=key, reverse=True)


def main():
    ap = argparse.ArgumentParser(description="Rank a field of wells by intervention value.")
    ap.add_argument("wells", nargs="+", help="Well JSON paths (globs allowed)")
    ap.add_argument("--by", choices=["npv", "pi", "eur"], default="npv",
                    help="Rank by risked NPV (default), capital efficiency (pi), or remaining EUR")
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of a table")
    args = ap.parse_args()

    paths = []
    for w in args.wells:
        paths.extend(sorted(glob.glob(w)) or [w])
    rows = rank(paths, by=args.by)

    if args.json:
        print(json.dumps([asdict(r) for r in rows], indent=2))
        return

    try:
        from rich.console import Console
        from rich.table import Table
        t = Table(title=f"Field intervention ranking ({len(rows)} wells, by {args.by.upper()})")
        for c in ["#", "Well", "Lift", "Intervention", "Risked NPV", "Payout", "PI", "Capital", "Rem. EUR"]:
            t.add_column(c)
        capital = npv = 0.0
        for i, r in enumerate(rows, 1):
            capital += r.capital_usd; npv += r.npv_usd
            t.add_row(str(i), r.well_id, r.lift, r.intervention,
                      f"${r.npv_usd/1e6:,.2f}M" if r.npv_usd else "—",
                      f"{r.payout_months:.0f}mo" if r.payout_months else "—",
                      f"{r.profitability_index:.1f}" if r.profitability_index else "—",
                      f"${r.capital_usd/1e3:,.0f}K" if r.capital_usd else "—",
                      f"{r.remaining_eur_bbl/1e3:,.0f}MBbl")
        Console().print(t)
        actionable = [r for r in rows if r.intervention not in _NON_ECONOMIC]
        Console().print(f"[bold]{len(actionable)} actionable wells[/] · total capital "
                        f"${capital/1e6:,.1f}M · total risked NPV ${npv/1e6:,.1f}M")
    except ImportError:
        for i, r in enumerate(rows, 1):
            print(f"{i:>2} {r.well_id:10} {r.lift:10} {r.intervention:22} NPV ${r.npv_usd/1e6:6.2f}M  PI {r.profitability_index:4.1f}")


if __name__ == "__main__":
    main()
