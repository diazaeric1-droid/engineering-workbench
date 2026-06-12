# Well Review: ED-008H (42-109-10008) | Midland Basin | 2026-06-03

**Well Summary:** 17-year-old ESP producer, currently making 71.3 BOPD / 871 BFPD at 80.8% water cut, running 26% above type curve on oil rate but severely below ESP Preferred Operating Range (POR) at 41 Hz with active downthrust — the pump is oversized for the well's depleted inflow and is destroying mechanical reliability. Lifecycle economics favor ESP-to-Beam conversion.

---

## Current State Diagnosis

- **Outperforming type curve on oil, but the pump is killing itself:** Oil rate of 71.3 BOPD vs. 56.5 BOPD type-curve prediction (+26.3%). Decline fit is tight (R² = 0.987). The apparent "outperformance" is fragile — the pump is operating at 871 BFPD against a POR floor of 1,500 BFPD, running in chronic downthrust at 41 Hz with no further VSD headroom to slow. Pump failure is the proximate risk, not production decline.
- **ESP in downthrust, below POR with no recovery path:** Current 871 BFPD is 42% below the 1,500 BFPD POR floor. VSD is already at 41 Hz — at or near minimum functional frequency. This is a mechanical constraint (undersized / depleted inflow for the installed pump curve), not a setpoint fix. Motor temp at 309°F and amps at 47A are not yet at alarm, but downthrust under these conditions drives bearing wear and premature failure.
- **Water cut high and accelerating — economic limit is compressing:** Water cut at 80.8% and rising at +11.5%/yr. At this trajectory, water cut reaches ~90% within ~9 months. Net oil revenue per barrel of gross fluid produced is ~$14–16 net (at $70 WTI, assuming ~$1/bbl SWD). Lift cost and SWD drag must be revisited in the AFE for any ESP intervention.
- **GOR rising (+117 scf/bbl/yr, currently 829 scf/bbl):** Rising GOR is not yet at gas-interference threshold for the ESP (~1,000–1,200 scf/bbl) but is trending that way. No intake pressure flag for gas breakout (intake at 71 psi), but this warrants monitoring. If GOR crosses ~1,000 scf/bbl the beam conversion case strengthens further.
- **Remaining EUR ~227 MBbl over ~8.7 years:** Sufficient reserve tail to justify a lift conversion. Lifecycle NPV of beam conversion ($7.50M) beats ESP swap ($6.99M) by ~$510K — the difference is the eliminated ESP re-pull cadence (~$325K/pull every 2–3 years on a 17-year-old well in a depleted inflow environment).

---

## Ranked Recommendations

| Rank | Intervention | Job NPV (@ 10%) | Lifecycle NPV | Payout | PI | Rationale |
|------|-------------|----------------|---------------|--------|----|-----------|
| **1** | **ESP-to-Beam Conversion** | $711K (P50: $886K) | **$7.50M** | **8 mo** | **3.37** | Lifecycle winner per `evaluate_esp_economic_life`. Eliminates ~$325K/pull ESP re-fail cadence on a 17-yr well below POR. P90 Monte Carlo NPV still +$364K — ROBUST. 99.4% payout probability within 24 months. Primary recommendation. |
| **2** | ESP Right-Size Swap | $881K | $6.99M | 6 mo | 3.57 | Single-job NPV is marginally higher, but lifecycle NPV is $510K lower than beam due to expected re-fail cadence. Appropriate fallback *only* if wellbore survey or rod clearance precludes beam unit installation. |
| 3 | No intervention / continue on current ESP | — | Destruction of value | — | — | Current downthrust condition will drive an unplanned pull within 6–18 months at emergency cost. Not recommended. |

> **Primary path:** Execute ESP-to-Beam Conversion. If wellbore survey confirms rod-string clearance and tubing integrity, proceed to engineering. Sequence: pull ESP on next planned intervention window → set tubing packer → install beam unit sized for ~150–200 BFPD gross at current WC. Do **not** delay to attempt a VSD frequency tweak — there is no headroom and the inflow problem is reservoir-driven.

---

## Confidence & Open Questions

| Item | Status | Action Required |
|------|--------|----------------|
| **Wellbore/tubing integrity for rod string** | **Unknown** | Mandatory before conversion AFE. Run a calliper/tubing inspection log; confirm no doglegs >8°/100ft that preclude rod clearance. |
| **Motor temp / amps trending toward failure?** | Only 2 ESP readings available | Pull time-series ESP telemetry (at minimum last 90 days) to determine rate of motor temp rise. If >2°F/day trend, pull is urgent. |
| **Beam unit sizing** | TBD | Requires nodal analysis at current reservoir pressure. With 80.8% WC and ~871 BFPD current gross, expect net oil throughput ~140–170 BFPD gross post-conversion. Size accordingly. |
| **GOR trajectory** | Rising +117 scf/bbl/yr | If GOR hits ~1,000 scf/bbl before conversion, evaluate gas anchor on the beam pump completion to prevent gas interference. |
| **SWD capacity / cost** | Assumed $1.00/bbl | Confirm SWD contract rate at current volume. At 80.8% WC and ~870 BFPD, the well is disposing ~700+ BWPD — SWD drag is material to net margin. |
| **Perforations / zonal contribution** | Not available | If conversion is approved, consider a PLT or tracer survey on the workover trip to confirm zonal allocation and rule out behind-pipe opportunity. |