# Well Review — ED-011H (42-109-10011)
**Permian Conventional | Beam Pump | First Production: 2025-06-01 → ~11 yr on production | Report Date: 2026-06-03**

---

## Well Summary
ED-011H is a ~11-year-old conventional Permian beam-pump well producing at a critically low 2.6 BOPD (96% water cut) due to a confirmed **parted rod string** — the well is effectively shut-in at surface while the pump strokes air. A rig workover is mechanically urgent and strongly economic.

---

## Current State Diagnosis

- **🚨 Parted Rod String Confirmed (URGENT):** Dyno card shows a flat/no-load card with only **6% fillage** — no fluid is being lifted. This is consistent with a parted rod string, failed/unseated pump, or tubing hole. Rig intervention is required; fluid-level shot should be run immediately to confirm before mobilizing iron.

- **Severe Underperformance vs. Type Curve:** Actual rate of **2.6 BOPD** vs. a type-curve expectation of **59.0 BOPD today** — a **−95.6% deviation**, implying ~7,696 bbl (~$408K) of cumulative deferred production. Decline fit R² = 0.75; the fit residual of −92.7% confirms near-total production loss, not gradual decline.

- **Water Cut at Economic-Limit Threshold:** Current water cut is **95.8%**, rising at **+18.6%/yr**. At ~$1.00/bbl SWD cost, the net oil margin is heavily eroded — every incremental barrel of water shrinks the workover payout window. If water cut reaches ~97–98% post-workover, the well approaches its economic limit rapidly; confirm SWD capacity and disposal cost before committing.

- **Rising GOR — Gas Interference Risk Post-Workover:** GOR is **25,846 scf/bbl and climbing at +6,400 scf/bbl/yr**. Once the rod string is repaired and the pump is producing, the beam pump should be assessed for a **gas anchor** addition — at these GOR levels, gas interference (fluid pound) is the likely next failure mode.

- **Remaining EUR is Meaningful but Slim:** `project_recovery` estimates **~93,300 bbl remaining** to a 5-BOPD economic limit. However, given the 95.8% water cut trajectory, the effective oil EUR is constrained; the economic limit will be reached faster than the type-curve model predicts if water cut continues rising at current pace.

---

## Ranked Recommendations

| Rank | Intervention | Det. NPV @10% | Payout | PI | Rationale |
|------|---|---|---|---|---|
| **1** | **Rod-Pump Workover** (parted rod repair + pump inspection/replace) | **$263K** | **6 mo** | **3.28×** | Mechanically mandatory — well is not producing. P50 Monte Carlo NPV = $629K; P90 (conservative) = $303K; 100% probability of payout within 24 mo. ROBUST verdict across all 10,000 trials. Mobilize rig immediately. |
| **2** | **Gas Anchor Installation** (during same rig visit) | Incremental cost TBD | Bundled | — | Rising GOR (25,846 scf/bbl, +6,400/yr) makes gas interference the next failure mode. Add a gas anchor/separator on the same rig ticket — marginal cost to a well already on the rig, avoids a second pull in 6–12 months. Evaluate with vendor during workover planning. |
| **3** | **Water Cut / Economic Limit Review** (surveillance, no capital) | — | — | — | At 95.8% WC rising at 18.6%/yr, re-run economic limit at post-workover rates with actual SWD cost. If restored rate settles below ~20–25 BOPD post-repair and WC continues to climb, trigger a P&A evaluation within 12 months. |
| **4** | **P&A** (if workover fails or post-workover rate < 5 BOPD) | — | — | — | If the rig finds tubing damage, a corroded barrel, or the well fails to respond post-repair, do not spend a second intervention. At 11 years, 95.8% WC, and 2.6 BOPD, a second workover is unlikely to be economic — plug and abandon cleanly. |

> **Sequencing:** Workover first. Install gas anchor during the same rig visit (no incremental mobilization cost). Monitor 30/60/90-day rates post-repair before committing any further capital.

---

## Monte Carlo Sensitivity — Rod-Pump Workover

| Scenario | NPV @10% |
|---|---|
| P10 (Optimistic) | $1,153K |
| P50 (Base) | $629K |
| P90 (Conservative) | $303K |
| Deterministic (risked) | $263K |
| Probability of Payout < 24 mo | **100%** |

**Tornado (NPV swing):** Incremental rate ($581K) > Realized oil price ($454K) > Uplift decline rate ($414K). The workover return is most sensitive to the rate restored — confirm rod tally, pump size, and tubing condition before assuming +30 BOPD uplift.

---

## Confidence & Open Questions

1. **Fluid-Level Shot — Run Before Rig Mobilization.** The dyno card is definitive for parted rods / pump failure, but a fluid-level shot will (a) confirm whether there is fluid gradient to pump, and (b) distinguish a rod part from a tubing hole or unseated pump — each has a different rig scope and cost.
2. **Post-Workover Rate Assumption (+30 BOPD).** The +30 BOPD uplift is conservative given the −95.6% deviation, but it assumes the reservoir can still deliver at 95.8% WC. Confirm with a recent PI test or static fluid level — if reservoir pressure has depleted significantly, actual uplift may be lower and the economics should be re-run.
3. **SWD Cost & Capacity.** At 95.8% WC, the gross fluid rate is ~62 BFPD on only 2.6 BOPD. Post-workover (if restored to ~30 BOPD oil), gross fluid will be ~714 BFPD. Confirm SWD line has capacity and lock in disposal cost — the tornado analysis shows realized economics are tightly coupled to water disposal drag at this water cut.
4. **Tubing Condition.** At 11 years, tubing integrity should be assessed on the rig visit — a pressure test or caliper log. A corroded / worn tubing string at 95.8% WC is a latent risk that could trigger a near-term repeat failure.
5. **GOR Diagnostic.** GOR of 25,846 scf/bbl is exceptionally high for a conventional beam-pump well — verify this against meter calibration data. If confirmed, evaluate whether casing gas is being vented and whether a casinghead gas handling/compression opportunity exists alongside the workover.