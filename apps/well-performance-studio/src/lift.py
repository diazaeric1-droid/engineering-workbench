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

    def runout_bpd(self, freq_hz: float | None = None) -> float:
        """Flow at which head per stage reaches zero, scaled to ``freq_hz``.

        By the affinity laws flow scales linearly with frequency, so the zero-head
        runout shifts from the 60-Hz value ``q_runout_bpd`` to ``q_runout_bpd·f/f0``.
        The view uses this to (a) bound the plotted pump-curve x-range to the *selected*
        frequency and (b) detect a design rate that exceeds the pump's capacity.
        """
        f0 = self.freq_base_hz
        f = f0 if freq_hz is None else float(freq_hz)
        return float(self.q_runout_bpd * max(f, 1e-6) / f0)

    def head_per_stage_visc(self, q_bpd: float, freq_hz: float | None = None,
                            visc_cp: float = 1.0) -> float:
        """Viscosity-corrected head per stage (ft) — the curve the design point lands on.

        Identical to :meth:`head_per_stage` but with the simplified viscosity head
        de-rate ``ch`` applied (see :func:`_visc_correction` — illustrative, not the
        full HI 9.6.7 chart), so the plotted curve and the design-point marker share one
        correction (audit: 'design point floats off its own curve at high viscosity').
        """
        ch, _ = _visc_correction(visc_cp)
        return float(self.head_per_stage(q_bpd, freq_hz) * ch)


def _visc_correction(mu_cp: float) -> tuple[float, float]:
    """Simplified illustrative viscosity de-rate factors (head, efficiency).

    A compact, smooth, monotone stand-in that captures the *direction* of the standard
    pump viscosity-correction charts — NOT the full ANSI/HI 9.6.7 procedure. In
    particular it returns only head (Ch) and efficiency (Ceta) de-rates and OMITS the
    rate correction (Cq); it is not keyed off the pump BEP/rpm B-parameter. Below ~10 cP
    the pump behaves as on water (factors ~1); as viscosity rises, head and especially
    efficiency fall. Treat the factors as indicative for sizing, not a chart lookup.
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
    # ---- feasibility / curve-consistency fields (added for the workbench view) ----
    head_visc_factor: float = 1.0   # viscosity head de-rate ch applied to head/stage
    eff_visc_factor: float = 1.0    # viscosity efficiency de-rate ce
    runout_bpd: float = 0.0         # pump runout (zero-head flow) at the chosen frequency
    feasible: bool = True           # False when design fluid rate >= pump runout
    stages_capped: bool = False     # True when stage count was clamped at MAX_STAGES
    meets_target_tol: float = 0.98  # tolerance the meets_target check uses (fraction)
    # ---- inflow + operating-window checks (added for the PE peer review) ----
    aof_stb_d: float = 0.0          # the IPR's absolute open-flow potential, STB/d
    inflow_limited: bool = False    # target >= ~0.95*AOF: reservoir, not the pump, is the cap
    q_bep_at_freq_bpd: float = 0.0  # best-efficiency-point flow at the selected frequency
    bep_ratio: float = 1.0          # design total-fluid rate / q_bep_at_freq
    bep_ok: bool = True             # design sits inside the ~0.70-1.25x BEP recommended window
    notes: str = ""


# A real ESP string is rarely more than a few hundred stages; beyond this the design is
# physically meaningless (the target rate has exceeded what this pump series can lift).
MAX_STAGES = 400


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

    # 0. INFLOW feasibility: the reservoir cannot deliver more than its AOF no matter how
    #    much lift is installed. If the target is at/above ~95% of AOF the IPR pwf collapses
    #    toward 0 and the TDH/stage/BHP sizing below is meaningless — this is an inflow
    #    limit, not a lift limit, and must be flagged distinctly (PE review #8).
    aof = float(ipr.aof) if np.isfinite(ipr.aof) else 0.0
    inflow_limited = bool(aof > 0 and target_q_stb_d >= 0.95 * aof)

    # 1. pump-intake pressure: IPR pwf at target, projected to pump depth (above perfs).
    #    Clamp the interpolation explicitly so a target beyond AOF cannot silently read a
    #    fabricated pwf=0 off np.interp's default right-edge behaviour.
    grad = _fluid_gradient_psi_ft(vlp)
    pwf_at_target = float(np.interp(target_q_stb_d, ipr.q, ipr.pwf,
                                    left=float(ipr.pwf[0]), right=float(ipr.pwf[-1])))
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
    runout = pump.runout_bpd(frequency_hz)
    h_stage_true = pump.head_per_stage(q_fluid, frequency_hz) * ch
    # Feasibility: at/above runout the head per stage collapses to ~0 and the naive
    # stage = ceil(TDH / h_stage) explodes to millions. Detect this and present a sane
    # capped count + a clear infeasible flag instead of a nonsense KPI (audit: 'runaway
    # stage count when target exceeds pump runout').
    feasible = q_fluid < runout and h_stage_true > 1e-2
    h_stage = max(h_stage_true, 1e-3)
    raw_stages = int(np.ceil(tdh_ft / h_stage)) if tdh_ft > 0 else 1
    raw_stages = max(raw_stages, 1)
    stages_capped = (not feasible) or raw_stages > MAX_STAGES
    stages = min(raw_stages, MAX_STAGES)

    # BEP operating-window check: a centrifugal ESP should run within roughly 0.70-1.25x of
    # its best-efficiency point (downthrust below, upthrust/erosion above). "Below runout"
    # is necessary but NOT sufficient — a 1.6x-BEP design wears out fast even though it is
    # technically feasible. Flag it distinctly so a bare green "meets target" can't hide it
    # (PE review #6). BEP flow scales linearly with frequency (affinity law).
    q_bep_at_freq = float(pump.q_bep_bpd * max(frequency_hz, 1e-6) / pump.freq_base_hz)
    bep_ratio = float(q_fluid / q_bep_at_freq) if q_bep_at_freq > 0 else 0.0
    bep_ok = bool(0.70 <= bep_ratio <= 1.25)

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
    meets = bool(op.q_op >= 0.98 * target_q_stb_d and op.converged
                 and feasible and not inflow_limited)

    if inflow_limited:
        note = (
            f"Target {target_q_stb_d:,.0f} STB/d is at/above the reservoir's AOF "
            f"({aof:,.0f} STB/d): this is INFLOW-limited, not lift-limited — no ESP can "
            f"pull more than the IPR delivers. TDH/stages/BHP are not meaningful here; "
            f"lower the target below AOF or improve inflow (stimulation) first."
        )
    elif not feasible:
        note = (
            f"Target total fluid {q_fluid:,.0f} bpd exceeds this pump's runout "
            f"({runout:,.0f} bpd at {frequency_hz:.0f} Hz): head per stage collapses to "
            f"~0 and the stage count is unbounded. Select a larger pump series or raise "
            f"the drive frequency. Stage count shown is capped at {MAX_STAGES}."
        )
    else:
        bep_msg = ""
        if not bep_ok:
            where = "below" if bep_ratio < 0.70 else "above"
            wear = ("downthrust / low efficiency" if bep_ratio < 0.70
                    else "upthrust / accelerated wear & erosion")
            bep_msg = (
                f" Design runs at {bep_ratio:.2f}x BEP ({where} the 0.70-1.25x "
                f"recommended window) → {wear}; resize the pump series or trim frequency.")
        note = (
            f"Pump curve: illustrative 60-Hz centrifugal (BEP {pump.q_bep_bpd:.0f} bpd, "
            f"{pump.head_per_stage(pump.q_bep_bpd):.1f} ft/stage at BEP; runout "
            f"{runout:,.0f} bpd at {frequency_hz:.0f} Hz). "
            f"Viscosity de-rate: head x{ch:.2f}, eff x{ce:.2f} at "
            f"{fluid_viscosity_cp:.0f} cP." + bep_msg
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
        meets_target=meets,
        op_q_stb_d=float(op.q_op),
        op_pwf_psia=float(op.pwf_op),
        head_visc_factor=float(ch),
        eff_visc_factor=float(ce),
        runout_bpd=float(runout),
        feasible=bool(feasible),
        stages_capped=bool(stages_capped),
        meets_target_tol=0.98,
        aof_stb_d=float(aof),
        inflow_limited=bool(inflow_limited),
        q_bep_at_freq_bpd=float(q_bep_at_freq),
        bep_ratio=float(bep_ratio),
        bep_ok=bool(bep_ok),
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
    best: GasLiftPoint  # technical optimum: argmax(q_op) over the sweep
    inj_rate_mscf_d_at_best: float  # injection gas rate at technical optimum, Mscf/d
    # ---- honesty / economics fields (added for the workbench view) ----
    rollover: bool = False          # True if an interior production max exists in-range
    econ: GasLiftPoint | None = None  # economic optimum (max net $) if prices supplied
    econ_net_usd_d: float = 0.0     # net $/d at the economic optimum
    inj_rate_mscf_d_at_econ: float = 0.0  # injection gas rate at the economic optimum


def gas_lift_sweep(
    ipr: IPRResult,
    vlp: VLPInputs,
    inj_glr_max_scf_stb: float = 1200.0,
    n: int = 16,
    oil_price: float | None = None,
    gas_cost: float | None = None,
    nri: float = 1.0,
) -> GasLiftResult:
    """Sweep gas-lift injection GLR and find the operating point at each level.

    Injecting gas raises the tubing GLR, lightening the column and lowering the required
    pwf — so the IPR∩VLP operating-point rate rises. Past an optimum, added gas increases
    friction and the column starts to load with gas, so production plateaus or declines —
    the classic gas-lift performance curve. Returns the sweep and the optimum injection
    GLR. Injection gas rate (Mscf/d) at the optimum = inj_GLR × oil-equivalent liquid.

    ``best`` is the *technical* optimum (max rate). ``rollover`` is True only when that
    maximum is interior to the swept range (a genuine rate rollover); when the maximum is
    at the last swept point the rate is still climbing and ``best`` is a sweep-boundary
    artifact, not a physical optimum (audit fix). If ``oil_price`` and ``gas_cost`` are
    supplied the *economic* optimum is also returned as ``econ`` — the injection rate that
    maximizes net daily revenue (incremental oil revenue − gas cost), where the
    diminishing-returns knee, not the rate peak, is the real operating choice.

    The signature is backward compatible: ``oil_price``/``gas_cost``/``nri`` default such
    that economics are skipped (existing callers and numeric-invariant tests are
    unaffected).
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
    best_idx = int(np.argmax([p.q_op_stb_d for p in points]))
    best = points[best_idx]
    # an interior maximum (not the first or last swept point) is a real rollover
    rollover = 0 < best_idx < len(points) - 1
    inj_rate = best.inj_glr_scf_stb * best.q_op_stb_d / 1000.0  # Mscf/d

    econ: GasLiftPoint | None = None
    econ_net = 0.0
    econ_inj_rate = 0.0
    if oil_price is not None and gas_cost is not None and points:
        # economic optimum: maximize net $/d = incremental oil revenue - lift-gas cost,
        # measured against the no-injection (inj=0) base rate. Oil split is liquid * (1-wc).
        base = points[0]
        oil_frac = 1.0 - float(np.clip(vlp.water_cut, 0.0, 0.999))
        best_net = -1e30
        for p in points:
            d_oil = (p.q_op_stb_d - base.q_op_stb_d) * oil_frac  # incremental oil, STB/d
            inj_mscf_d = p.inj_glr_scf_stb * p.q_op_stb_d / 1000.0
            net = d_oil * float(oil_price) * float(nri) - inj_mscf_d * float(gas_cost)
            if net > best_net:
                best_net = net
                econ = p
                econ_inj_rate = inj_mscf_d
        econ_net = float(best_net)

    return GasLiftResult(
        points=points, best=best, inj_rate_mscf_d_at_best=float(inj_rate),
        rollover=bool(rollover), econ=econ, econ_net_usd_d=float(econ_net),
        inj_rate_mscf_d_at_econ=float(econ_inj_rate),
    )
