"""Quick economics: NPV, payout, $/BOE for intervention candidates."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import econ_core

# Days/month convention matches econ_core (avoids the 360-day-year undercount).
DAYS_PER_MONTH = econ_core.DAYS_PER_MONTH


@dataclass
class InterventionEconomics:
    name: str
    treatment_cost_usd: float
    incremental_eur_bbl: float
    incremental_first_year_bbl: float
    npv_10pct_usd: float
    payout_months: float
    profitability_index: float  # discounted PV of inflows / investment (>1.0 = value-accretive)


def evaluate_intervention(
    name: str,
    treatment_cost_usd: float,
    incremental_rate_bopd: float,
    uplift_decline_per_yr: float = 0.6,
    horizon_years: int = 5,
    realized_price_per_bbl: float = 65.0,
    discount_rate: float = 0.10,
    opex_per_bbl: float = 12.0,
    prob_success: float = 1.0,
    deferred_days: float = 0.0,
    base_rate_bopd: float = 0.0,
    water_cut_pct: float = 0.0,
    water_disposal_per_bbl: float = 0.0,
) -> InterventionEconomics:
    """Risked NPV of an intervention assuming exponential decline of the uplift.

    VP-grade additions over a bare oil-NPV (all default to a no-op so the point
    estimate stays directly comparable to the Monte-Carlo path):
      - prob_success         : geological/mechanical chance the uplift is realized.
                               Inflows are risked by this; the cost is spent regardless.
      - deferred_days        : production deferred while the well is down for the job,
                               valued at the *base* rate (barrels you'd otherwise sell).
      - water_disposal_per_bbl + water_cut_pct : SWD/LOE drag. Each incremental oil bbl
                               drags water at the current cut; disposing it eats net margin.
    """
    months = np.arange(1, horizon_years * 12 + 1)
    monthly_rate = econ_core.exp_uplift_rate(incremental_rate_bopd, uplift_decline_per_yr, months)
    monthly_vol = monthly_rate * DAYS_PER_MONTH  # bbl/month

    # Net margin per incremental oil bbl, after lifting cost AND the water it drags.
    # water/oil ratio = wc/(1-wc); each incremental oil bbl carries that much water to dispose.
    wc = min(max(water_cut_pct / 100.0, 0.0), 0.999)
    wor = wc / (1.0 - wc) if wc < 1.0 else 0.0
    net_margin = (realized_price_per_bbl - opex_per_bbl) - water_disposal_per_bbl * wor
    monthly_revenue = monthly_vol * net_margin

    # Risk the inflows by chance-of-success; the capital is sunk regardless.
    p = min(max(prob_success, 0.0), 1.0)
    deferred_cost = (deferred_days * base_rate_bopd) * max(net_margin, 0.0)
    total_cost = treatment_cost_usd + deferred_cost

    # Effective-annual discounting via the shared kernel (a 10% input == 10%/yr, NOT the
    # 10.47% the old (1 + r/12)**m monthly-compounding implied). risked_npv applies the
    # chance-of-success to the revenue PV only — the capital is spent regardless.
    pv_unrisked = econ_core.discounted_pv(monthly_revenue, discount_rate)
    pv_inflows = pv_unrisked * p
    npv = econ_core.risked_npv(pv_unrisked, total_cost, p)

    # Payout uses the risk-weighted expected revenue stream.
    cumulative = np.cumsum(monthly_revenue * p)
    payout_idx = int(np.searchsorted(cumulative, total_cost))
    payout_months = float(payout_idx + 1) if payout_idx < len(months) else float("inf")

    first_year_bbl = float(monthly_vol[:12].sum())
    eur = float(monthly_vol.sum())
    # Discounted profitability index = PV of (risked) inflows / total investment.
    pi = pv_inflows / total_cost if total_cost > 0 else 0.0

    return InterventionEconomics(
        name=name,
        treatment_cost_usd=total_cost,
        incremental_eur_bbl=eur,
        incremental_first_year_bbl=first_year_bbl,
        npv_10pct_usd=npv,
        payout_months=payout_months,
        profitability_index=float(pi),
    )


@dataclass
class ESPLifeVerdict:
    recommendation: str          # "esp_swap" | "esp_to_beam_conversion"
    swap_npv_usd: float
    beam_npv_usd: float
    remaining_eur_bbl: float
    years_to_deplete: float
    rationale: str


def evaluate_esp_economic_life(
    current_oil_bopd: float,
    current_bfpd: float,
    por_min_bfpd: float,
    well_age_years: float,
    remaining_eur_bbl: float,
    *,
    realized_price_per_bbl: float = 65.0,
    opex_per_bbl: float = 12.0,
    discount_rate: float = 0.10,
    esp_workover_cost_usd: float = 325_000.0,
    esp_run_life_years: float = 2.5,
    beam_conversion_cost_usd: float = 275_000.0,
    beam_run_life_years: float = 6.0,
) -> ESPLifeVerdict:
    """Decide ESP-swap vs ESP-to-beam conversion on lifecycle economics.

    The crux a senior PE weighs: a right-size ESP swap restores rate, but on a low-rate,
    depleted, gassy well an ESP re-fails every ~2-3 yrs (each pull ≈ $325K), while a beam
    unit on the same well runs 5-8 yrs with cheap rod jobs. Over the well's *remaining
    life* the conversion's lower lift-failure cadence usually wins once the well is old and
    producing well below the ESP POR floor with thin reserves.

    Models each option as: lift the remaining EUR over its expected life, minus the
    discounted stream of lift interventions over that span.
    """
    years_to_deplete = max(remaining_eur_bbl / max(current_oil_bopd * 365.0, 1.0), 0.5)
    years_to_deplete = min(years_to_deplete, 15.0)

    margin = realized_price_per_bbl - opex_per_bbl
    gross_pv = remaining_eur_bbl * margin / (1 + discount_rate) ** (years_to_deplete / 2)

    def _lift_cost(run_life: float, per_job: float) -> float:
        # Discounted stream of lift interventions across remaining life (first job at t=0).
        n_jobs = max(1, int(np.ceil(years_to_deplete / run_life)))
        return float(sum(per_job / (1 + discount_rate) ** (i * run_life) for i in range(n_jobs)))

    swap_cost = _lift_cost(esp_run_life_years, esp_workover_cost_usd)
    beam_cost = _lift_cost(beam_run_life_years, beam_conversion_cost_usd)

    swap_npv = gross_pv - swap_cost
    beam_npv = gross_pv - beam_cost

    below_por = current_bfpd < por_min_bfpd
    old = well_age_years >= 10.0

    if beam_npv > swap_npv and below_por and old:
        rec = "esp_to_beam_conversion"
        rationale = (
            f"Well is {well_age_years:.0f} yr old, {current_bfpd:.0f} BFPD (below {por_min_bfpd:.0f} "
            f"POR floor), ~{remaining_eur_bbl/1000:.0f} MBbl left over ~{years_to_deplete:.1f} yr. "
            f"Beam conversion avoids the ~{esp_run_life_years:.1f}-yr ESP re-fail cadence "
            f"(${esp_workover_cost_usd/1000:.0f}K/pull); lifecycle NPV ${beam_npv/1e6:.2f}M vs "
            f"swap ${swap_npv/1e6:.2f}M."
        )
    else:
        rec = "esp_swap"
        rationale = (
            f"Right-size ESP swap favored: lifecycle NPV ${swap_npv/1e6:.2f}M vs beam "
            f"${beam_npv/1e6:.2f}M. Well age {well_age_years:.0f} yr / rate {current_bfpd:.0f} BFPD "
            f"do not yet justify converting to a slower-rate rod system."
        )

    return ESPLifeVerdict(
        recommendation=rec,
        swap_npv_usd=float(swap_npv),
        beam_npv_usd=float(beam_npv),
        remaining_eur_bbl=float(remaining_eur_bbl),
        years_to_deplete=float(years_to_deplete),
        rationale=rationale,
    )


def _npv_payout_vectorized(
    treatment_cost_usd: float,
    incremental_rate_bopd: np.ndarray,
    uplift_decline_per_yr: np.ndarray,
    realized_price_per_bbl: np.ndarray,
    horizon_years: int = 5,
    discount_rate: float = 0.10,
    opex_per_bbl: float = 12.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorized NPV + payout-month across many Monte-Carlo draws.

    Each input array has shape (n_trials,). Returns (npv[n], payout_months[n]) and
    uses exactly the same monthly-decline / discount math as evaluate_intervention()
    so the deterministic and stochastic paths can never diverge.
    """
    months = np.arange(1, horizon_years * 12 + 1)                  # (M,)
    # (n, M) monthly rate: exp(-decline * year_fraction), decline varies per trial.
    # econ_core.exp_uplift_rate broadcasts the per-trial qi/decline arrays into (n, M).
    rate = econ_core.exp_uplift_rate(incremental_rate_bopd, uplift_decline_per_yr, months)
    monthly_vol = rate * econ_core.DAYS_PER_MONTH                  # bbl/month, (n, M)
    margin = (realized_price_per_bbl - opex_per_bbl)[:, None]      # (n, 1)
    monthly_revenue = monthly_vol * margin                         # (n, M)
    # Same effective-annual discounting as evaluate_intervention (discounted_pv handles the
    # (n, M) batch over the last axis) so the deterministic and MC paths can never diverge.
    npv = econ_core.discounted_pv(monthly_revenue, discount_rate) - treatment_cost_usd

    # Payout: first month where cumulative net (undiscounted) revenue >= cost.
    cumulative = np.cumsum(monthly_revenue, axis=1)                # (n, M)
    reached = cumulative >= treatment_cost_usd
    any_reached = reached.any(axis=1)
    first_idx = np.argmax(reached, axis=1)                         # 0 where never reached
    payout = np.where(any_reached, first_idx + 1, np.inf).astype(float)
    return npv, payout


def simulate_intervention(
    name: str,
    treatment_cost_usd: float,
    incremental_rate_bopd: float,
    uplift_decline_per_yr: float = 0.6,
    horizon_years: int = 5,
    realized_price_per_bbl: float = 65.0,
    discount_rate: float = 0.10,
    opex_per_bbl: float = 12.0,
    prob_success: float = 1.0,
    n_trials: int = 10_000,
    rate_cv: float = 0.30,
    decline_abs_sd: float = 0.15,
    price_sd: float = 12.0,
    payout_cutoff_months: float = 24.0,
    seed: int | None = 42,
) -> dict:
    """Monte-Carlo of intervention economics over uncertain inputs.

    Uncertainty model (per the engineering judgement these are estimated under):
      - incremental_rate_bopd : lognormal, ~±30% (rate_cv) about the point estimate
                                (can't go negative, right-skewed like real uplift).
      - uplift_decline_per_yr : normal, sd = decline_abs_sd (0.15 absolute), clipped >= 0.
      - realized_price_per_bbl: normal, sd = price_sd ($12), clipped to a sane floor.
      - prob_success          : geological/mechanical chance the job works at all. Each
                                trial draws Bernoulli(prob_success); on a MISS the uplift
                                is zero and the NPV is the sunk treatment cost (-cost) — the
                                same dry-hole framing evaluate_intervention's risked_npv
                                uses. Default 1.0 keeps the bare input-uncertainty view and
                                preserves backward-compatible (rng-identical) behaviour.

    Returns P10/P50/P90 NPV, probability_of_payout (NPV>0 AND payout < cutoff),
    probability_of_loss, and a one-at-a-time tornado dict (low/high NPV swing per variable,
    others held at their point estimate). P-naming follows reserves convention: P10 =
    optimistic (high) NPV, P90 = conservative (low) NPV.
    """
    rng = np.random.default_rng(seed)

    # Lognormal for rate: choose mu/sigma so the MEAN equals the point estimate.
    sigma = np.sqrt(np.log(1 + rate_cv ** 2))
    mu = np.log(max(incremental_rate_bopd, 1e-9)) - 0.5 * sigma ** 2
    rate_draws = rng.lognormal(mean=mu, sigma=sigma, size=n_trials)

    decline_draws = np.clip(
        rng.normal(uplift_decline_per_yr, decline_abs_sd, size=n_trials), 0.0, None
    )
    price_draws = np.clip(
        rng.normal(realized_price_per_bbl, price_sd, size=n_trials),
        opex_per_bbl + 1.0, None,  # never below opex+$1 (a non-economic price is nonsense here)
    )

    npv, payout = _npv_payout_vectorized(
        treatment_cost_usd, rate_draws, decline_draws, price_draws,
        horizon_years=horizon_years, discount_rate=discount_rate, opex_per_bbl=opex_per_bbl,
    )

    # Chance-of-success: on a geological/mechanical MISS the job delivers no uplift and the
    # capital is sunk, so NPV = -treatment_cost and there is no payout. Drawn AFTER the
    # continuous inputs so that prob_success == 1.0 leaves the rng stream (and every output)
    # bit-for-bit identical to the pre-COS behaviour. (PE review #18/#16)
    p_succ = float(min(max(prob_success, 0.0), 1.0))
    if p_succ < 1.0:
        success = rng.random(n_trials) < p_succ
        npv = np.where(success, npv, -float(treatment_cost_usd))
        payout = np.where(success, payout, np.inf)

    p90, p50, p10 = (float(x) for x in np.percentile(npv, [10, 50, 90]))  # P90=low, P10=high
    prob_payout = float(np.mean((npv > 0) & (payout < payout_cutoff_months)))
    prob_loss = float(np.mean(npv < 0.0))

    # ---- tornado: one-at-a-time low/high, others at point estimate -------------
    def _scalar_npv(rate, decline, price):
        npv1, _ = _npv_payout_vectorized(
            treatment_cost_usd, np.array([rate]), np.array([decline]), np.array([price]),
            horizon_years=horizon_years, discount_rate=discount_rate, opex_per_bbl=opex_per_bbl,
        )
        return float(npv1[0])

    base = (incremental_rate_bopd, uplift_decline_per_yr, realized_price_per_bbl)
    # Use the P10/P90 draw quantiles of each variable as its low/high endpoints.
    rate_lo, rate_hi = (float(x) for x in np.percentile(rate_draws, [10, 90]))
    dec_lo, dec_hi = (float(x) for x in np.percentile(decline_draws, [10, 90]))
    prc_lo, prc_hi = (float(x) for x in np.percentile(price_draws, [10, 90]))

    tornado = {
        "incremental_rate_bopd": {
            "low_input": rate_lo, "high_input": rate_hi,
            # lower rate -> lower NPV, higher rate -> higher NPV
            "low_npv": _scalar_npv(rate_lo, base[1], base[2]),
            "high_npv": _scalar_npv(rate_hi, base[1], base[2]),
        },
        "uplift_decline_per_yr": {
            "low_input": dec_lo, "high_input": dec_hi,
            # FASTER decline (high) -> lower NPV; report swing endpoints honestly
            "low_npv": _scalar_npv(base[0], dec_lo, base[2]),
            "high_npv": _scalar_npv(base[0], dec_hi, base[2]),
        },
        "realized_price_per_bbl": {
            "low_input": prc_lo, "high_input": prc_hi,
            "low_npv": _scalar_npv(base[0], base[1], prc_lo),
            "high_npv": _scalar_npv(base[0], base[1], prc_hi),
        },
    }
    for v in tornado.values():
        v["swing"] = abs(v["high_npv"] - v["low_npv"])

    return {
        "name": name,
        "n_trials": int(n_trials),
        "treatment_cost_usd": float(treatment_cost_usd),
        "npv_p90_usd": p90,   # conservative
        "npv_p50_usd": p50,   # median
        "npv_p10_usd": p10,   # optimistic
        "npv_mean_usd": float(np.mean(npv)),
        "npv_samples": npv,  # raw per-trial NPV draws (for plotting the MC distribution)
        "probability_of_payout": prob_payout,  # NPV>0 AND payout < cutoff
        "probability_of_loss": prob_loss,      # NPV < 0 (incl. chance-of-success misses)
        "prob_success": p_succ,
        "payout_cutoff_months": float(payout_cutoff_months),
        "tornado": tornado,
        "assumptions": {
            "rate_cv": rate_cv,
            "decline_abs_sd": decline_abs_sd,
            "price_sd": price_sd,
            "prob_success": p_succ,
        },
    }
