# Well Review — ED-017H (42-109-10017)
**Delaware Basin | ESP | First Prod: 2022-03-15 | Days on Production: 990 | Review Date: 2026-06-03**

---

## Well Summary
ED-017H is a ~4-year-old Delaware Basin ESP well producing **171 BOPD / 1,636 BFPD** at **60.4% water cut**, running **31% below its type-curve rate** and operating **outside its ESP's Preferred Operating Range (below floor)** with three concurrent equipment-health red flags pointing to scale accumulation as the primary driver of underperformance.

---

## Current State Diagnosis

- **Underperforming type curve by 31.4%:** Last actual = 171 BOPD vs. type-curve expectation of 249.6 BOPD today. Cumulative deferred oil vs. type curve = **17,568 bbl (~$931K**). Hyperbolic fit is clean (R² = 0.988, b = 0.747, Dᵢ = 0.374%/day), so the shortfall is mechanical/lift-driven, not reservoir.
- **ESP below POR with a scale-consistent signature:** Current throughput is **1,636 BFPD vs. POR floor of 1,800 BFPD**. Motor amps are **81 A vs. 65 A nameplate (+25% overload)** while intake pressure has dropped to **32 psi** — the combination of elevated amps + low intake pressure + ~4 years without documented scale treatment is the textbook scale/fouling fingerprint. Mechanical load increase from worn/scaled stages is the highest-probability root cause; gas interference is secondary.
- **Motor temperature at 305 °F:** Running hot under overload conditions. Continued operation without intervention raises MTBF risk; a burn-out pull at current trajectory would cost $325K+ with no productivity gain.
- **Rising water cut accelerating economic-limit shift:** WC = 60.4% and climbing at **+9.9 %/yr**. At current trajectory WC reaches ~70% within 12 months, compressing net oil margin and potentially shifting the economic limit upward — relevant to lift-sizing for any ESP right-size decision.
- **GOR flat at 1,717 scf/bbl (−30 scf/bbl/yr):** No gas-interference escalation trend; gas separator replacement is not the priority driver here. Low intake pressure (32 psi) is more consistent with restricted inflow (scale) than with free gas ingestion.

---

## Ranked Recommendations

| Rank | Intervention | Det. NPV (@10%) | PI | Payout | P90 NPV (MC) | Prob. Payout | Rationale |
|------|---|---|---|---|---|---|---|
| **1** | **Scale inhibitor squeeze + acid stimulation** *(do first, before any mechanical work)* | **$1.68M** | **9.0×** | **2 mo** | **$1.23M** | **100%** | Addresses root cause. Amps overloaded + intake at 32 psi + 4 yr without treatment = high-confidence scale diagnosis. Swapping an unfouled ESP into a scaled completion yields re-failure in 3–6 months. P90 NPV $1.23M across 10K MC trials; tornado dominated by incremental rate uncertainty — robust at any realistic rate outcome. Cost risk-adjusted to ~$210K. |
| **2** | **ESP right-size swap** *(sequence after acid stim, combined workover trip)* | **$1.55M** | **5.0×** | **4 mo** | — | — | After stim restores inflow, a right-sized pump (targeting ~2,200–2,600 BFPD mid-POR) eliminates downthrust risk and recovers the remaining 31% rate gap vs. type curve. Lifecycle ESP NPV = **$22.6M** vs. beam conversion **$23.2M** — lifecycle model marginally favors beam, but the **661 bbl/d current rate and 871K bbl remaining EUR** over 13.9 years do not support conversion to a slower rod system at this production stage. Right-size swap is correct mechanical path; revisit beam conversion if rates fall below ~400 BFPD or WC exceeds 80%. Combine with the acid job on a single rig mobilization to eliminate a second set of deferred production (~$108K/day in net oil value). |
| **3** | **Beam conversion** *(hold; revisit in ~3–4 yr)* | $23.2M lifecycle | — | — | — | — | Lifecycle model shows beam NPV ~$648K higher than ESP swap over 13.9 yr — a narrow margin that does not overcome the rate sacrifice at today's 171 BOPD. Flag for re-evaluation when gross rates fall below 400 BFPD or WC > 80%, where ESP re-fail cadence ($325K/pull every 2–3 yr) begins to destroy value relative to beam OPEX. |

**Recommended execution path:** Single well intervention — (1) pump workover pull, (2) scale inhibitor squeeze + matrix acid stimulation downhole, (3) re-complete with right-sized ESP targeting mid-POR at post-stim inflow. Combined mobilization eliminates redundant deferred production and rig costs.

---

## Remaining Reserves

| Parameter | Value |
|---|---|
| Hyperbolic model (b = 0.747) | — |
| Remaining EUR to 5 BOPD econ limit | **871,159 bbl** |
| Projected productive life | **~13.9 years** |

---

## Confidence & Open Questions

1. **Scale confirmation needed:** Pull a fluid sample for scale/ion analysis (Ba²⁺, Sr²⁺, Ca²⁺) before committing to treatment type. If barium sulfate (barite) is dominant, acid alone is insufficient — a dedicated chelant/DTPA squeeze is required and cost increases ~$40–60K. This changes the Rank 1 economics but not the sequencing logic.
2. **Discharge pressure gap:** No discharge pressure reported in ESP readings — needed to confirm pump differential and stage count assessment for right-size selection. Request SCADA historian pull.
3. **Casing pressure / annular gas data:** Intake at 32 psi is consistent with scale but could also reflect reservoir depletion outpacing inflow. Static BHP survey or PBU would de-risk whether the low intake is lift-driven (scale/pump) or reservoir-driven (drainage, compartmentalization). If reservoir-driven, stim uplift estimate of +120 BOPD is optimistic.
4. **Water disposal capacity & SWD costs:** WC rising at +9.9%/yr. Confirm SWD line capacity and contract rate at current and projected water volumes — at 70% WC on 1,636 BFPD, gross water approaches ~1,300 BWPD, which may stress takeaway. Modeled at $1.00/bbl; verify against actual contract.
5. **Last scale/inhibitor treatment date:** Not present in data package. If a squeeze was performed within the past 12 months and scale is still confirmed, this points toward an accelerated scale environment or incompatible inhibitor chemistry — escalate to a chemistry specialist before designing the squeeze.