# Well Review — 15/9-F-12 H (Volve, Equinor Open Data)
**Date:** 2026-06-04 | **Lift:** ESP | **Age:** ~18 yr | **Days on Production:** 699 (24 data points)

---

## Well Summary
Producing ~1,889 BOPD on type curve, but ESP is operating severely below its Preferred Operating Range (POR), creating sustained downthrust risk and imminent mechanical failure exposure; rising water cut (+13%/yr, now 53.8%) is accelerating economic-limit encroachment and eroding net margin on every lifted barrel.

---

## Current State Diagnosis

- **Production performance on track — for now:** Hyperbolic decline fit (b = 0.30, R² = 0.86) shows actual rate of **1,889 BOPD is +3.1% above type curve** (1,832 BOPD predicted); the well is not underperforming the decline model. Remaining EUR to 5 BOPD economic limit: **~4.2 MMbbl over ~6.1 years**.
- **ESP critically below POR:** Current total fluid rate **4,094 BFPD vs. POR floor of 8,000 BFPD** — the pump is running at barely 50% of its minimum designed throughput. The diagnostic flags **sustained downthrust**, which degrades thrust bearings and seals; industry ESP MTBF data shows below-POR operation cuts expected run-life by 40–60% vs. in-range operation.
- **Rising water cut is the structural threat:** Water cut at **53.8%, climbing +13.0%/yr**. At this trajectory, water cut reaches ~67% in 1 year and ~80% in 2 years. This directly widens the gap between total fluid rate and the POR floor — the ESP will fall further out of range even if oil rate holds, not closer to it. Re-sizing to a smaller ESP today will require another pull in <2 years as WC continues to rise.
- **GOR stable, no gas interference signal:** GOR flat at **1,048 scf/bbl (−2 scf/bbl/yr)**; intake pressure at **2,650 psi** — no gas slugging, no liquid-loading flag. Amps reading is absent from the ESP data set (motor amps = 0 reported), which limits confidence in the thermal/electrical health assessment.
- **Lifecycle economics favour beam conversion over ESP swap:** At 18 years and 4.2 MMbbl remaining, the ESP re-fail cadence (~$325K/pull every ~2.5 yr) destroys value relative to beam lift. Lifecycle NPV beam: **$166.06M** vs. ESP swap: **$165.71M** — marginal dollar difference, but beam avoids ~2–3 pulls over the remaining 6-year well life.

---

## Ranked Recommendations

| Rank | Intervention | Risked NPV (10%) | DPI | Payout | Rationale |
|------|-------------|-----------------|-----|--------|-----------|
| 1 | **ESP-to-Beam Conversion** | **$200K** (deterministic) / **$1.05M P50** (MC) | 1.21 | 28 mo | Eliminates downthrust failure risk; avoids 2–3 ESP pulls ($650K–$975K) over remaining well life; beam lift viable at declining fluid volumes as WC rises. Lifecycle NPV ~$350K higher than swap. Monte Carlo: P(payout) = **99.7%**, P90 NPV = $455K — **ROBUST** across all price/rate scenarios. Primary driver of NPV swing is incremental rate ($1.04M tornado), then decline ($0.9M), then price ($0.8M). |
| 2 | **Continue ESP + Aggressive Surveillance** (contingency if conversion deferred) | TBD | — | — | If conversion is deferred for operational reasons, immediately audit motor amps (currently unreported — data gap), reduce VSD frequency to shift operating point closer to POR, and schedule 90-day pull decision gate. Does NOT solve the structural below-POR problem. |

> **Note:** An ESP right-size swap was evaluated and rejected as primary. While nominally cheaper upfront, the rising water cut means a right-sized unit for today's 4,094 BFPD will be over-sized within 12–18 months as WC pushes total fluid toward 3,500–3,800 BFPD — triggering another pull. Beam conversion is size-agnostic to fluid decline.

---

## Confidence & Open Questions

| Item | Gap | Impact |
|------|-----|--------|
| **Motor amps = 0 (unreported)** | Cannot confirm electrical health or winding degradation. Pull the VFD/surface panel log to validate. | HIGH — a degraded motor changes conversion timing; pull sooner if trending high. |
| **No discharge pressure reading** | Cannot compute differential head or verify pump staging efficiency. | MEDIUM — needed to confirm downthrust is the only mechanical stress mode vs. off-curve operation on a worn stage. |
| **Water cut trajectory** | +13%/yr trend is linear extrapolation. If WC acceleration steepens (e.g., coning breakthrough), economic limit arrives earlier than 6.1 yr model. Recommend full waterflood/material balance check against reservoir pressure. | HIGH — EUR sensitivity to WC is the biggest value lever remaining on this well. |
| **Well age / casing integrity** | 18-year-old North Sea well — pre-conversion, confirm casing ID, deviation survey, and rod-string clearance for beam pump installation. | MEDIUM — could add cost or render beam conversion impractical if deviation >10–15° in the lifted interval. |
| **Beam pump surface constraints** | Volve is an offshore platform (Mærsk Inspirer jack-up). Confirm deck load and structural capacity for surface unit installation. Platform-mounted beam pumps exist in North Sea but require structural sign-off. | HIGH — if platform cannot accommodate a surface unit, an electric submersible rod pump (ESRP) or progressing cavity pump (PCP) is the offshore-appropriate rod-lift analogue; economics directionally similar. |

---

**Bottom line for VP review:** The well is on type curve and has 4.2 MMbbl remaining, but the ESP is in a structural failure-risk posture (below POR floor, rising WC pushing it further out of range). The lifecycle analysis supports conversion to rod lift / PCP to eliminate the ESP re-fail drag on value. Beam/PCP conversion is ROBUST (P90 NPV positive, 99.7% payout probability). Primary action: **scope beam/PCP conversion for next available rig slot; close the motor amps data gap within 30 days.**