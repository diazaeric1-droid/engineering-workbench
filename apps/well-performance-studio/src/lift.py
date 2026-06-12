"""Artificial-lift design — ESP sizing and gas-lift (pure numpy/scipy).

Standard textbook artificial-lift design methods (Takacs, *Electrical Submersible Pumps
Manual*; Brown, *The Technology of Artificial Lift*; Economides et al.). Nothing here is
proprietary — these are the canonical design equations every production engineer uses.

Two lift methods are provided:

* **ESP (electrical submersible pump)** — the workhorse for high-rate Permian/GoM oil
  wells. Design flow: (1) compute the **total dynamic head (TDH)** the pump must add to
  move the target rate against the well's hydrostatic + friction + surface back-pressure;
  (2) read **head-per-stage** from a representative single-stage pump performance curve at
  the target rate; (3) divide to get the **stage count**; (4) trim with the **affinity
  laws** to a drive frequency; (5) apply a basic **viscosity correction** to head/efficiency
  and compute brake horsepower. The design is checked against the nodal operating point.
* **Gas lift** — inject gas down the annulus to lighten the tubing column. We sweep
  injection GLR and find the rate gain vs. the nodal operating point, returning the
  injection rate that maximizes (or plateaus) production — the classic gas-lift
  performance curve.

Units oilfield throughout: head ft, rate STB/d (or bpd of total fluid), pressure psia,
power hp, frequency Hz.

Deterministic, no I/O, no bluebonnet dependency. Reuses :mod:`src.nodal` for the
well-system physics so the lift design is consistent with the nodal analysis tab.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .nodal import (
    IPRResult,
    VLPInputs,
    operating_point,
    pwf_from_vlp,
)

WATER_DENSITY_SC = 62.4  # lbm/ft^3
PSI_PER_FT_WATER = 0.433  # psi per ft of fresh-water head


# ============================================================================ pump curve
@dataclass
class PumpModel:
    """A representative single-stage centrifugal-ESP performance curve at 60 Hz.

    The head-per-stage vs. flow curve is modeled as a downward parabola (the standard
    shape of a centrifugal-pump H–Q curve): head is maximum at shut-in and falls to zero
    near runout. Efficiency is a parabola peaking at the best-efficiency point (BEP).
    Coefficients here describe a mid-range 60-Hz pump (BEP ~2200 bpd, ~25 ft/stage at BEP),
    representative of e.g. a 540-series pump; documented as illustrative, not a vendor curve.

    head_stage(q)  = h0 * (1 - (q/q_runout)^2)               [ft/stage]
    eff(q)         = eff_bep * (1 - ((q-q_bep)/q_bep)^2)      [-]
    """

    h0_ft: float = 40.0          # shut-in head per stage at 60 Hz, ft
    q_runout_bpd: float = 4200.0  # flow at which head -> 0, bpd
    q_bep_bpd: float = 2200.0     # best-efficiency-point flow, bpd
    eff_bep: float = 0.68         # peak stage efficiency
    freq_base_hz: float = 60.0    # curve reference frequency

    def head_per_stage(self, q_bpd: float, freq_hz: float | None = None) -> float:
        """Head per stage (ft) at total-fluid rate ``q_bpd`` and drive frequency.

        Applies the centrifugal **affinity laws**: at frequency f the flow scales as
        f/f0 and head as (f/f0)^2. We evaluate the base 60-Hz parabola at the
        affinity-referred flow ``q*(f0/f)`` and scale the result by ``(f/f0)^2``.
        """
        f0 = self.freq_base_hz
        f = f0 if freq_hz is None else float(freq_hz)
        r = f / f0
        q_ref = float(q_bpd) / max(r, 1e-6)  # flow referred back to 60 Hz
        h_ref = self.h0_ft * (1.0 - (q_ref / self.q_runout_bpd) ** 2)
        return float(max(h_ref, 0.0) * r ** 2)

    def efficiency(self, q_bpd: float, freq_hz: float | None = None) -> float:
        """Stage hydraulic efficiency (0-1) at the affinity-referred flow."""
        f0 = self.freq_base_hz
        f = f0 if freq_hz is None else float(freq_hz)
        r = f / f0
        q_ref = float(q_bpd) / max(r, 1e-6)
        e = self.eff_bep * (1.0 - ((q_ref - self.q_bep_bpd) / self.q_bep_bpd) ** 2)
        return float(np.clip(e, 0.05, self.eff_bep))


def _visc_correction(mu_cp: float) -> tuple[float, float]:
    """Basic viscosity de-rating factors (head, efficiency) for a centrifugal pump.

    A compact stand-in for the standard pump viscosity-correction charts (Hydraulic
    Institute / vendor): below ~10 cP the pump behaves as on water (factors ~1); as
    viscosity rises, head and especially efficiency fall. Smooth, monotone, bounded.
    """
    mu = max(float(mu_cp), 1.0)
    if mu <= 10.0:
        return 1.0, 1.0
    # logistic-style decay anchored to typical chart behavior
    ch = float(np.clip(1.0 - 0.10 * np.log10(mu / 10.0), 0.70, 1.0))
    ce = float(np.clip(1.0 - 0.30 * np.log10(mu / 10.0), 0.45, 1.0))
    return ch, ce


# ============================================================================ ESP design
@dataclass
class ESPDesign:
    """Result of an ESP design pass."""

    target_q_stb_d: float       # design liquid target, STB/d
    total_fluid_bpd: float      # total fluid incl. water + FVF, bpd (pump sees this)
    tdh_ft: float               # total dynamic head required, ft
    pump_intake_psia: float     # computed pump-intake (suction) pressure, psia
    head_per_stage_ft: float    # head/stage at design rate & frequency
    stages: int                 # number of stages
    frequency_hz: float         # selected drive frequency
    bhp: float                  # brake horsepower at the shaft
    efficiency: float           # stage efficiency at design point
    meets_target: bool          # does the design deliver >= target at the operating point
    op_q_stb_d: float           # achieved operating-point rate with the pump installed
    op_pwf_psia: float          # operating-point flowing BHP with the pump installed
    notes: str = ""


def _total_fluid_bpd(target_q_stb_d: float, vlp: VLPInputs) -> float:
    """Total in-situ-ish surface fluid the pump must move (oil*Bo + water), bpd.

    A design approximation: oil at a representative Bo plus produced water. (Free gas is
    assumed largely separated at the intake / handled by the pump's gas tolerance — the
    standard simplifying assumption for a first-pass ESP sizing.)
    """
    fw = float(np.clip(vlp.water_cut, 0.0, 0.999))
    bo = 1.25  # representative oil FVF at intake; conservative for sizing
    q_oil = target_q_stb_d * (1.0 - fw)
    q_wat = target_q_stb_d * fw
    return float(q_oil * bo + q_wat)


def _fluid_gradient_psi_ft(vlp: VLPInputs) -> float:
    """Average produced-fluid pressure gradient (psi/ft) for the head conversion."""
    fw = float(np.clip(vlp.water_cut, 0.0, 0.999))
    sg_o = 141.5 / (131.5 + vlp.oil_api)
    grad_o = sg_o * PSI_PER_FT_WATER
    grad_w = vlp.water_sg * PSI_PER_FT_WATER
    return float((1.0 - fw) * grad_o + fw * grad_w)


def design_esp(
    ipr: IPRResult,
    vlp: VLPInputs,
    target_q_stb_d: float,
    pump_depth_ft: float | None = None,
    pump: PumpModel | None = None,
    frequency_hz: float = 60.0,
    fluid_viscosity_cp: float = 5.0,
    motor_eff: float = 0.85,
) -> ESPDesign:
    """Size an ESP to lift ``target_q_stb_d`` against the well system.

    Steps (standard ESP design, Takacs Ch. 6 / Economides §7):

    1. **Pump-intake pressure** = the flowing BHP the IPR produces at the target rate,
       de-rated down to the pump setting depth by the static fluid gradient (the pump is
       set above the perfs).
    2. **TDH** = the head the pump must add = (discharge head to surface at the required
       wellhead pressure) − (intake head available). Equivalently
       ``TDH = (P_wh - P_intake)/grad + (depth above pump as friction allowance)``; we use
       the head form ``TDH = (P_discharge_req - P_intake)/grad`` with ``P_discharge_req``
       the pressure needed at pump depth to deliver the fluid to surface at ``P_wh``.
    3. **Stages** = TDH / head-per-stage (from :class:`PumpModel` at the design rate &
       frequency, viscosity-corrected).
    4. **Power** = hydraulic power / (stage eff × motor eff), via the standard
       ``hp = q[bpd] · TDH[ft] · SG / (135771 · eff)`` brake-horsepower formula.
    5. **Check**: rebuild the VLP with the pump's head added and confirm the new operating
       point meets or exceeds the target.

    Returns an :class:`ESPDesign`. ``meets_target`` is the bottom line.
    """
    pump = pump or PumpModel()
    target_q_stb_d = float(target_q_stb_d)
    depth = float(pump_depth_ft) if pump_depth_ft else float(vlp.depth_ft) - 500.0
    depth = max(depth, 100.0)

    # 1. pump-intake pressure: IPR pwf at target, projected to pump depth (above perfs)
    grad = _fluid_gradient_psi_ft(vlp)
    pwf_at_target = float(np.interp(target_q_stb_d, ipr.q, ipr.pwf))
    setting_above_perfs = max(float(vlp.depth_ft) - depth, 0.0)
    p_intake = max(pwf_at_target - grad * setting_above_perfs, 25.0)

    # 2. discharge pressure required at pump depth to deliver fluid to surface at P_wh.
    #    Use the multiphase VLP from surface down to the pump depth at the target rate.
    vlp_above = VLPInputs(**{**vlp.__dict__, "depth_ft": depth})
    p_discharge_req = pwf_from_vlp(target_q_stb_d, vlp_above)
    tdh_ft = max((p_discharge_req - p_intake) / grad, 0.0)

    # 3. stages from the (viscosity-corrected) pump curve at the design total-fluid rate
    q_fluid = _total_fluid_bpd(target_q_stb_d, vlp)
    ch, ce = _visc_correction(fluid_viscosity_cp)
    h_stage = pump.head_per_stage(q_fluid, frequency_hz) * ch
    h_stage = max(h_stage, 1e-3)
    stages = int(np.ceil(tdh_ft / h_stage))
    stages = max(stages, 1)

    # 4. power: brake hp from the standard field formula, motor-de-rated
    eff = max(pump.efficiency(q_fluid, frequency_hz) * ce, 0.05)
    sg_fluid = grad / PSI_PER_FT_WATER  # specific gravity of the produced fluid
    hyd_hp = q_fluid * tdh_ft * sg_fluid / 135771.0  # hydraulic hp (HI formula)
    bhp = float(hyd_hp / (eff * motor_eff))

    # 5. check against the nodal operating point WITH the pump's boost added.
    #    Model the pump as a constant head boost over the design band: the pump lowers the
    #    pwf the *reservoir* must overcome by (stages * head/stage * grad) at this rate.
    boost_psi = stages * h_stage * grad

    # operating point with boost: solve pwf_ipr(q) == pwf_vlp(q) - boost
    op = _operating_point_with_boost(ipr, vlp, boost_psi)
    meets = op.q_op >= 0.98 * target_q_stb_d and op.converged

    note = (
        f"Pump curve: illustrative 60-Hz centrifugal (BEP {pump.q_bep_bpd:.0f} bpd, "
        f"{pump.head_per_stage(pump.q_bep_bpd):.1f} ft/stage at BEP). "
        f"Viscosity de-rate: head x{ch:.2f}, eff x{ce:.2f} at {fluid_viscosity_cp:.0f} cP."
    )
    return ESPDesign(
        target_q_stb_d=target_q_stb_d,
        total_fluid_bpd=q_fluid,
        tdh_ft=float(tdh_ft),
        pump_intake_psia=float(p_intake),
        head_per_stage_ft=float(h_stage),
        stages=stages,
        frequency_hz=float(frequency_hz),
        bhp=bhp,
        efficiency=float(eff),
        meets_target=bool(meets),
        op_q_stb_d=float(op.q_op),
        op_pwf_psia=float(op.pwf_op),
        notes=note,
    )


def _operating_point_with_boost(ipr: IPRResult, vlp: VLPInputs, boost_psi: float):
    """Operating point when an ESP adds a constant pressure boost to the tubing.

    The pump reduces the bottom-hole pressure the reservoir must supply, so the effective
    VLP demand is ``pwf_vlp(q) - boost``. We reuse :func:`operating_point` by sampling a
    boosted VLP curve.
    """
    from .nodal import VLPResult, vlp_curve

    q_max = float(ipr.aof) * 0.999
    base = vlp_curve(vlp, q_max=q_max, n=30)
    boosted = VLPResult(q=base.q, pwf=base.pwf - float(boost_psi), inputs=vlp)
    return operating_point(ipr, boosted)


# ============================================================================ gas lift
@dataclass
class GasLiftPoint:
    """One point on a gas-lift performance curve."""

    inj_glr_scf_stb: float   # injection gas-liquid ratio added, scf/STB
    total_glr_scf_stb: float  # formation + injected GLR
    q_op_stb_d: float        # resulting nodal operating-point rate
    pwf_psia: float          # resulting operating-point flowing BHP


@dataclass
class GasLiftResult:
    """Gas-lift injection sweep + the optimum."""

    points: list  # list[GasLiftPoint]
    best: GasLiftPoint
    inj_rate_mscf_d_at_best: float  # injection gas rate at optimum, Mscf/d


def gas_lift_sweep(
    ipr: IPRResult,
    vlp: VLPInputs,
    inj_glr_max_scf_stb: float = 1200.0,
    n: int = 16,
) -> GasLiftResult:
    """Sweep gas-lift injection GLR and find the operating point at each level.

    Injecting gas raises the tubing GLR, lightening the column and lowering the required
    pwf — so the IPR∩VLP operating-point rate rises. Past an optimum, added gas increases
    friction and the column starts to load with gas, so production plateaus or declines —
    the classic gas-lift performance curve. Returns the sweep and the optimum injection
    GLR. Injection gas rate (Mscf/d) at the optimum = inj_GLR × oil-equivalent liquid.
    """
    inj_glrs = np.linspace(0.0, float(inj_glr_max_scf_stb), int(n))
    formation_glr = float(vlp.glr_scf_stb)
    points: list[GasLiftPoint] = []
    for inj in inj_glrs:
        v = VLPInputs(**{**vlp.__dict__, "glr_scf_stb": formation_glr + float(inj)})
        op = operating_point(ipr, v)
        points.append(
            GasLiftPoint(
                inj_glr_scf_stb=float(inj),
                total_glr_scf_stb=formation_glr + float(inj),
                q_op_stb_d=float(op.q_op if op.converged else 0.0),
                pwf_psia=float(op.pwf_op),
            )
        )
    best = max(points, key=lambda p: p.q_op_stb_d)
    inj_rate = best.inj_glr_scf_stb * best.q_op_stb_d / 1000.0  # Mscf/d
    return GasLiftResult(points=points, best=best, inj_rate_mscf_d_at_best=float(inj_rate))
