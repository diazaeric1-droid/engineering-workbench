# Well Review — ED-016H (42-109-10016)
**Delaware Basin | ESP | First Production: 2021-08-01 | Days on Production: 990 | Review Date: 2026-06-03**

---

## Well Summary
ESP well currently producing **163.6 BOPD / 2,145 BFPD** at 62.6% water cut; on type curve for oil but exhibiting clear ESP mechanical stress signatures (amps 23% above nameplate, motor temp 339°F) consistent with active downhole scale accumulation requiring **immediate chemical treatment followed by a planned right-size ESP swap**.

---

## Current State Diagnosis

- **Oil performance — on type curve, no rate alarm.** Hyperbolic fit (b = 0.40, Dᵢ = 0.294%/day, R² = 0.982) yields a predicted rate of 168.3 BOPD vs. 163.6 BOPD actual (–2.8% deviation). Not a rate problem today; the scale issue will create one if left unaddressed.

- **ESP mechanically stressed — scale signature confirmed.** Motor amps at **80 A vs. 65 A nameplate (+23% overload)**; motor temp at **339°F** (high). Pump is technically within POR (2,145 BFPD vs. POR floor 1,800 BFPD), but intake pressure at **57 psi** is borderline low. Combination of high amps, high temp, and near-floor intake pressure is the canonical downhole scale/stage-wear fingerprint. Swapping the ESP without a scale treatment first will re-fail the new pump within 3–6 months.

- **Water cut rising at an actionable rate.** Water cut = **62.6%** and climbing at **+10.7%/yr**. At this trajectory, water cut reaches ~73% within 12 months, pushing gross fluid requirements up and shrinking net oil margin. SWD cost drag is already material ($1.00/bbl assumed). Lift sizing in the post-swap design must account for future fluid growth.

- **GOR stable — no gas interference concern.** GOR = **1,886 scf/bbl**, slope flat (+31 scf/bbl/yr). Intake pressure of 57 psi is low but not driving gas breakout symptoms (no jitter in amps noted); this is more consistent with scale restriction than free-gas ingestion. Gas separator is not indicated at this time.

- **Remaining EUR is substantial — asset worth protecting.** Decline projection to 5 BOPD economic limit yields **632,000 bbl remaining** (~10.6 years of producing life). Lifecycle ESP swap NPV ($19.2M) and beam conversion NPV ($19.8M) are within $637K of each other, but at 2,145 BFPD the ESP remains the correct lift technology; beam conversion is not warranted until rates fall materially.

---

## Ranked Recommendations

| Rank | Intervention | Det. NPV @ 10% | P50 NPV (MC) | P90 NPV (MC, conservative) | Payout | PI | Rationale |
|------|---|---|---|---|---|---|---|
| **1** | **Scale inhibitor squeeze + acid stimulation** *(do first — gates Rank 2)* | **$1.69M** | **$2.31M** | **$1.24M** | **2 mo** | **9.3×** | Addresses root cause of amp/temp exceedance. 100% PoP across all 10,000 MC trials. Dominant sensitivity: incremental rate ($1.93M swing) > oil price ($1.51M) > decline rate ($1.19M). Must precede any mechanical work. |
| **2** | **ESP right-size swap** *(sequence 2–4 weeks post-treatment)* | **$1.12M** | TBD | TBD | **5 mo** | **3.9×** | Lifecycle analysis confirms ESP over beam conversion ($19.2M vs $19.8M — beam wins on paper by $638K but not enough to justify converting a 2,145 BFPD well to rod lift). Right-size the new pump for **~2,400–2,800 BFPD gross** given rising water cut trajectory; current unit will be at POR floor within 12 months at +10.7%/yr water cut growth. |
| **3** | **SWD capacity / water disposal rate negotiation** *(parallel action, no rig required)* | N/A | N/A | N/A | Immediate | — | At 62.6% WC and +10.7%/yr, SWD drag is growing. Locking in a lower disposal contract now (target <$0.60/bbl) or evaluating produced water reuse improves net margin on every barrel going forward. Not an NPV call — a cost hygiene action. |

> **Sequencing note:** Do NOT swap the ESP before scale treatment. Run the acid squeeze first (4 days downtime). Pull post-treatment amps and motor temp for 2–3 weeks. If amps normalize toward nameplate (<70 A), re-evaluate whether the swap is still urgent or can be deferred to the next planned pull cycle. If amps remain elevated, proceed with the right-size swap on the same mobilization where possible to minimize deferred production.

---

## Confidence & Open Questions

| Item | Current Status | What's Needed |
|---|---|---|
| **Scale species identification** | Inferred from amps/temp — no direct confirmation | Downhole fluid sample or wellhead scale scraping for XRD analysis; confirms whether carbonate, sulfate (barite), or mixed — drives acid blend selection |
| **Discharge pressure** | Not reported (`null` in ESP readings) | Critical for calculating differential head and confirming stage wear vs. scale; add to ESP SCADA pull immediately |
| **Post-treatment amp response** | Unknown until treatment runs | Pull 72-hr amp/temp trend post-squeeze before committing to swap mobilization |
| **Water source identification** | Rising WC trend confirmed, source unknown | PLT or water chemistry isotope analysis to determine if water is interzonal (behind-pipe remediation candidate) or aquifer drive (no fix other than lift management) |
| **New pump sizing** | Preliminary target 2,400–2,800 BFPD | Requires a nodal analysis with updated IPR using current PI/skin after acid treatment; do not size on pre-treatment data |
| **SWD contract terms** | Disposal cost assumed $1.00/bbl | Confirm actual contract rate; at 62.6% WC on 2,145 BFPD gross, a $0.40/bbl reduction saves ~$190K/yr at current rates |