# Well Review — ED-014H (42-109-10014)
**Eagle Ford | Plunger Lift | First Prod: 2018-02-01 (~8.3 yr) | Review Date: 2026-06-03**

---

## Well Summary
ED-014H is an ~8-year-old Eagle Ford plunger-lift well currently producing **51 BOPD** — **45.5% below its type-curve expected rate of 93.5 BOPD** — with a rising water cut (67.2%, +12.3%/yr) and rising GOR (2,302 scf/bbl, +184 scf/bbl/yr), pointing to a combination of lift-system degradation (plunger/wax) and potential reservoir dewatering/depletion. Remaining EUR is estimated at **~197,100 bbl** to a 5 BOPD economic limit.

---

## Current State Diagnosis

- **Severe underperformance vs. type curve:** Actual 51 BOPD vs. type-curve 93.5 BOPD today (−45.5%); cumulative deferred production estimated at **10,315 bbl (~$547K** of unrecovered value). The hyperbolic fit is solid (R² = 0.964), and the −23% fit residual on the last data point confirms current production is not noise — this is a persistent, worsening gap.
- **Rising GOR (2,302 scf/bbl, +184 scf/bbl/yr) is a primary lift concern:** On a plunger-lift well, escalating GOR combined with underperformance is the canonical signature of either (a) paraffin/wax accumulation restricting plunger travel, or (b) plunger seal/pad degradation allowing gas slippage and liquid fallback. Both manifest as degraded cycle efficiency and declining oil recovery per cycle.
- **Water cut 67.2%, accelerating at +12.3%/yr:** This materially increases gross fluid load on the plunger and shrinks the net oil margin per barrel lifted. At this trajectory, WC crosses ~80% within ~12 months, which will stress current plunger sizing and shift the economic limit upward. Lift design and economic limit should be re-run at 75% and 80% WC scenarios.
- **Remaining recoverable EUR ~197,100 bbl** at current decline; at the type-curve rate, the well should have substantially more productive life ahead — the underperformance gap is largely a **recoverable lift/wellbore problem**, not irreversible depletion.
- **No ESP, no rod string** — dynamometer card not applicable. Plunger cycle data and arrival frequency logs are the primary downhole diagnostic, and those are not in the current data package (see Open Questions).

---

## Ranked Recommendations

| Rank | Intervention | NPV @ 10% | Payout | Profitability Index | Rationale |
|------|-------------|-----------|--------|-------------------|-----------|
| **1** | **Paraffin Treatment — Hot Oil Flush + Wireline Plunger Inspection/Swap** | **$420K** | **2 months** | **9.4×** | First intervention, lowest risk, least deferral (2 days). Addresses the most probable primary cause of cycle degradation. Wireline pull gives definitive plunger condition (worn pads, damaged seal) and wax buildup data. If plunger arrives healthy and tubing is clean, this rules in reservoir/skin as the dominant issue and gates the stim decision. Cost ~$45–50K. P(success) ~75%; risked NPV still >$400K. |
| **2** | **Matrix Acid Stimulation (Diverted)** — *contingent on plunger inspection confirming skin/reservoir component* | **$440K det. / $706K P50 MC** | **5 months** | **3.5× det.** | Monte Carlo (10,000 trials) confirms **99.9% probability of payout within 24 months**; P90 (conservative) NPV = $333K. Tornado: incremental rate ($677K swing) and oil price ($529K swing) are dominant sensitivities — downside is protected even at P90. Recommended only after Rec. 1 is executed and results interpreted; do not stim if plunger swap alone restores to type curve. Cost ~$160K, 5-day deferral. |
| **3** | **Plunger Lift Re-optimization (cycle timer / GLR-matched plunger resizing)** — *concurrent with Rec. 1 or as standalone if Rec. 1 resolves paraffin but WC-driven sizing mismatch persists* | TBD | TBD | TBD | Rising WC (+12.3%/yr) likely means the current plunger size and cycle parameters were designed for an earlier, lower-WC operating point. Re-engineering cycles and plunger weight to match today's GLR and fluid load is a no-cost/low-cost optimization that should accompany any mechanical work. Requires cycle data (see Open Questions). |

> **Sequencing note:** Execute **Rec. 1 first**, evaluate 30-day production response, then gate **Rec. 2**. Do not run both simultaneously — you lose diagnostic clarity. Combined path (treat + stim on same wellsite mobilization) is acceptable if Rec. 1 inspection confirms both paraffin AND skin damage, saving a second mobilization (~$20–30K).

---

## Confidence & Open Questions

| Item | Why It Matters | Data Needed |
|------|---------------|-------------|
| **Plunger arrival log / cycle frequency history** | Direct measure of lift degradation — declining arrivals or missed cycles confirm mechanical cause of underperformance before committing to stim | Last 6–12 months of SCADA cycle records |
| **Wellhead flowing pressure & tubing pressure trend** | Distinguishes reservoir pressure depletion from wellbore/tubing restriction; needed to correctly interpret the GOR rise | Continuous or monthly FWHP/FTPH |
| **Water cut source confirmation (formation water vs. condensate water)** | Determines whether WC rise is reservoir dewatering (manageable) or casing integrity issue (requires different intervention) | Water chemistry / chloride trend; casing pressure log |
| **Bottomhole temperature survey** | Confirms paraffin deposition risk (pour-point proximity); validates hot-oil treatment design vs. chemical inhibitor squeeze | Single wireline BHT or memory gauge run |
| **Skin estimate (pressure transient or rate-transient analysis)** | Separates lift efficiency loss from near-wellbore damage — critical to sizing the acid job and setting realistic uplift expectations for Rec. 2 | 24–72 hr buildup or rate-transient analysis on existing production data |
| **Current plunger type, weight, and last inspection date** | Baseline for wireline inspection comparison; if last swap >18 months ago on a 67% WC well, pad wear is almost certain | Completion/workover AFE history |

> **Confidence level on primary diagnosis (lift degradation + paraffin):** **Moderate-High.** The GOR trend, type-curve deviation magnitude, and 8-year plunger run time are consistent; the absence of cycle data prevents certainty. Confidence on the stim recommendation is **Moderate** pending Rec. 1 results — the Monte Carlo supports the economics even at conservative inputs, but physical justification for skin removal requires pressure data not yet in hand.