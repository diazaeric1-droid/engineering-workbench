"""Nodal analysis — IPR, VLP, and the operating point (pure numpy/scipy).

Self-contained reimplementations of the **standard, textbook** petroleum-engineering
correlations used in nodal (systems) analysis. Nothing here is proprietary: the IPR
(Vogel) and the multiphase tubing-pressure-traverse correlations (Hagedorn–Brown,
Beggs–Brill) are the canonical methods taught in every production-engineering text
(Beggs, *Production Optimization*; Brown, *The Technology of Artificial Lift*; Economides
et al., *Petroleum Production Systems*).

The three pieces of a nodal analysis at the bottom-hole node:

* **IPR** (inflow performance relationship) — what the *reservoir* can deliver: liquid
  rate ``q`` vs. flowing bottom-hole pressure ``pwf``. Below the bubble point we use the
  **Vogel (1968)** dimensionless reference curve; above it the flow is single-phase and
  the productivity index ``J`` is constant (straight-line PI). A pure straight-line PI
  option is also provided.
* **VLP** (vertical lift performance, a.k.a. tubing performance / outflow) — what the
  *tubing* requires: the ``pwf`` needed to lift a given ``q`` up the tubing to a fixed
  wellhead pressure, found by integrating the multiphase pressure gradient down the
  string. We segment the tubing and march the pressure with **Hagedorn–Brown** (default)
  or **Beggs–Brill**.
* **Operating point** — the intersection IPR ∩ VLP (the only ``(q, pwf)`` that satisfies
  both the reservoir and the tubing simultaneously). Found by a 1-D root-find on the
  pressure difference ``pwf_IPR(q) − pwf_VLP(q)``.

Units are oilfield throughout: pressure psia, rate STB/d (liquid) and scf/d (gas),
depth ft, diameter in., temperature °F, density lbm/ft³, viscosity cP.

Deterministic, no I/O, no bluebonnet dependency.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import brentq

# --------------------------------------------------------------------------- constants
_G = 32.174  # gravitational acceleration, ft/s^2 (= g_c numerically in oilfield lbf/lbm)
_PSI_PER_PSF = 1.0 / 144.0  # lbf/ft^2 -> psi
WATER_DENSITY_SC = 62.4  # lbm/ft^3, fresh water at standard conditions
AIR_MW = 28.97  # lbm/lbmol


# ============================================================================ IPR
@dataclass
class IPRResult:
    """An inflow performance relationship sampled as a (pwf, q) curve."""

    pwf: np.ndarray  # flowing bottom-hole pressure, psia (descending)
    q: np.ndarray  # corresponding liquid rate, STB/d (ascending)
    aof: float  # absolute open flow potential (q at pwf = 0), STB/d
    j: float  # productivity index used above the bubble point, STB/d/psi
    p_res: float  # reservoir (static) pressure, psia
    pb: float  # bubble-point pressure, psia
    method: str  # 'vogel' | 'pi'

    def q_at(self, pwf: float) -> float:
        """Liquid rate (STB/d) the reservoir delivers at a given pwf (psia)."""
        return float(_vogel_q_of_pwf(float(pwf), self.p_res, self.pb, self.j))


def _vogel_q_of_pwf(pwf: float, p_res: float, pb: float, j: float) -> float:
    """Liquid rate from pwf for a Vogel-below-Pb / linear-above-Pb composite IPR.

    Vogel (1968) dimensionless IPR below the bubble point:
        q/qb_max = 1 - 0.2 (pwf/pb) - 0.8 (pwf/pb)^2      (referenced to pb)
    The undersaturated (pwf >= pb) part is the straight line q = J (p_res - pwf).
    The two pieces are joined at pb so the curve and its rate are continuous, using
    the standard composite (Vogel below Pb, linear above) construction in which the
    Vogel maximum increment is qb_max = J * pb / 1.8 (Economides et al., §3).
    """
    pwf = max(pwf, 0.0)
    if p_res <= pb:
        # fully saturated reservoir: reference Vogel to the static reservoir pressure
        x = pwf / p_res
        qmax = j * p_res / 1.8
        return qmax * (1.0 - 0.2 * x - 0.8 * x * x)
    # undersaturated reservoir, composite IPR
    qb = j * (p_res - pb)  # rate at pwf = pb (top of the linear part)
    if pwf >= pb:
        return j * (p_res - pwf)
    qb_max = j * pb / 1.8  # Vogel increment below pb
    x = pwf / pb
    return qb + qb_max * (1.0 - 0.2 * x - 0.8 * x * x)


def _pi_from_test(
    p_res: float, pb: float, q_test: float, pwf_test: float
) -> float:
    """Back out the productivity index J (STB/d/psi) from a single flow test.

    Inverts the composite Vogel/linear IPR at the test point so the supplied
    ``(q_test, pwf_test)`` lies exactly on the returned curve.
    """
    if pwf_test >= pb or p_res <= pb and pwf_test >= p_res:
        # test point in the single-phase (straight-line) region
        dp = max(p_res - pwf_test, 1e-9)
        return q_test / dp
    if p_res <= pb:
        x = pwf_test / p_res
        vog = 1.0 - 0.2 * x - 0.8 * x * x
        # q_test = (J p_res / 1.8) * vog  ->  J
        return q_test * 1.8 / (p_res * max(vog, 1e-9))
    # undersaturated, test below pb:  q = J(p_res-pb) + (J pb/1.8)(vogel)
    x = pwf_test / pb
    vog = 1.0 - 0.2 * x - 0.8 * x * x
    coeff = (p_res - pb) + pb * vog / 1.8
    return q_test / max(coeff, 1e-9)


def vogel_ipr(
    p_res: float,
    pb: float,
    q_test: float | None = None,
    pwf_test: float | None = None,
    j: float | None = None,
    n: int = 80,
) -> IPRResult:
    """Composite **Vogel (below Pb) / linear-PI (above Pb)** inflow performance.

    Provide the productivity index either directly (``j``) or implicitly via a single
    flow test (``q_test`` at ``pwf_test``); the test point is then guaranteed to lie on
    the returned curve. Returns a (pwf, q) curve descending in pwf from ``p_res`` to 0
    and the absolute open-flow potential (AOF = q at pwf = 0).

    Reference: Vogel, *Inflow Performance Relationships for Solution-Gas Drive Wells*,
    JPT 1968; composite construction per Economides et al., *Petroleum Production
    Systems*, 2nd ed., §3.4.
    """
    p_res = float(p_res)
    pb = float(min(pb, p_res)) if pb > 0 else float(pb)
    if j is None:
        if q_test is None or pwf_test is None:
            raise ValueError("Provide either j or both q_test and pwf_test.")
        j = _pi_from_test(p_res, pb, float(q_test), float(pwf_test))
    j = float(j)
    if j <= 0:
        raise ValueError("Productivity index J must be positive.")

    pwf = np.linspace(p_res, 0.0, int(n))
    q = np.array([_vogel_q_of_pwf(float(p), p_res, pb, j) for p in pwf], dtype=float)
    aof = float(_vogel_q_of_pwf(0.0, p_res, pb, j))
    return IPRResult(pwf=pwf, q=q, aof=aof, j=j, p_res=p_res, pb=pb, method="vogel")


def straight_line_ipr(p_res: float, j: float, n: int = 80) -> IPRResult:
    """Single-phase straight-line PI inflow: ``q = J (p_res - pwf)``.

    Valid when the whole flowing range stays above the bubble point (no free gas in the
    reservoir). AOF = J * p_res.
    """
    p_res = float(p_res)
    j = float(j)
    if j <= 0:
        raise ValueError("Productivity index J must be positive.")
    pwf = np.linspace(p_res, 0.0, int(n))
    q = j * (p_res - pwf)
    return IPRResult(
        pwf=pwf, q=q, aof=float(j * p_res), j=j, p_res=p_res, pb=0.0, method="pi"
    )


# ============================================================================ VLP
@dataclass
class VLPInputs:
    """Tubing / fluid inputs for a vertical-lift-performance (outflow) curve.

    All standard surface/black-oil descriptors a production engineer would have for a
    single well. Densities default to representative black-oil values; override for a
    specific fluid.
    """

    tubing_id_in: float = 2.441  # tubing inner diameter, in. (2-7/8" tubing ID)
    depth_ft: float = 8000.0  # measured/vertical depth to the node, ft
    wellhead_pressure: float = 150.0  # tubing-head pressure, psia
    glr_scf_stb: float = 400.0  # producing gas-liquid ratio, scf/STB
    water_cut: float = 0.30  # fraction of liquid that is water (0-1)
    oil_api: float = 35.0  # stock-tank oil gravity, deg API
    gas_sg: float = 0.70  # gas specific gravity (air = 1)
    water_sg: float = 1.05  # water specific gravity (water = 1 at SC)
    temp_surface_f: float = 100.0  # flowing wellhead temperature, deg F
    temp_bottom_f: float = 200.0  # flowing bottom-hole temperature, deg F
    roughness_in: float = 0.0006  # absolute pipe roughness, in.
    correlation: str = "hagedorn_brown"  # 'hagedorn_brown' | 'beggs_brill'
    n_segments: int = 40  # tubing segments for the pressure march
    angle_deg: float = 90.0  # inclination from horizontal (90 = vertical)


def _oil_sg(api: float) -> float:
    """Stock-tank oil specific gravity from API gravity (water = 1)."""
    return 141.5 / (131.5 + float(api))


def _z_factor(p_psia: float, t_f: float, gas_sg: float) -> float:
    """Gas z-factor via the Standing–Katz fit of Brill & Beggs (1974).

    A compact, widely used explicit correlation for the compressibility factor — good to
    a few percent over the normal production envelope. Uses Standing's pseudo-criticals.
    """
    t_pc = 168.0 + 325.0 * gas_sg - 12.5 * gas_sg ** 2  # deg R
    p_pc = 677.0 + 15.0 * gas_sg - 37.5 * gas_sg ** 2  # psia
    t_r = (float(t_f) + 460.0) / t_pc
    p_r = float(p_psia) / p_pc
    t_r = max(t_r, 1.05)  # keep the fit in its valid band
    a = 1.39 * (t_r - 0.92) ** 0.5 - 0.36 * t_r - 0.101
    e = 9.0 * (t_r - 1.0)
    # Brill & Beggs (1974) B term. The high-pressure term is 0.32 * Ppr^6 / 10^(9(Tpr-1)),
    # NOT Ppr^2 -- this Ppr^6 term produces the z upturn at high pseudo-reduced pressure
    # (verbatim per the published correlation; cf. f0nzie/zFactor R/Beggs-Brill.R, Pengtools).
    b = (0.62 - 0.23 * t_r) * p_r + (
        0.066 / (t_r - 0.86) - 0.037
    ) * p_r ** 2 + 0.32 * p_r ** 6 / (10.0 ** e)
    c = 0.132 - 0.32 * np.log10(t_r)
    d = 10.0 ** (0.3106 - 0.49 * t_r + 0.1824 * t_r ** 2)
    z = a + (1.0 - a) * np.exp(-b) + c * p_r ** d
    return float(min(max(z, 0.25), 1.3))


def _rs_standing(p_psia: float, t_f: float, api: float, gas_sg: float) -> float:
    """Solution gas–oil ratio Rs (scf/STB), Standing (1947) correlation."""
    x = 0.0125 * float(api) - 0.00091 * float(t_f)
    return float(gas_sg) * ((float(p_psia) / 18.2 + 1.4) * 10.0 ** x) ** 1.2048


def _bo_standing(rs: float, t_f: float, api: float, gas_sg: float) -> float:
    """Oil formation volume factor Bo (rb/STB), Standing (1947) correlation."""
    sg_o = _oil_sg(api)
    cbob = rs * (gas_sg / sg_o) ** 0.5 + 1.25 * float(t_f)
    return 0.9759 + 12e-5 * cbob ** 1.2


def _live_oil_visc(p_psia: float, t_f: float, api: float, gas_sg: float) -> float:
    """Live-oil viscosity (cP) via Beggs–Robinson dead-oil + saturated correction."""
    # dead-oil viscosity, Beggs & Robinson (1975)
    z = 3.0324 - 0.02023 * float(api)
    y = 10.0 ** z
    x = y * float(t_f) ** (-1.163)
    mu_od = 10.0 ** x - 1.0
    rs = _rs_standing(p_psia, t_f, api, gas_sg)
    a = 10.715 * (rs + 100.0) ** (-0.515)
    b = 5.44 * (rs + 150.0) ** (-0.338)
    return float(a * mu_od ** b)


def _surface_tension(p_psia: float, t_f: float, api: float) -> float:
    """Gas–oil interfacial tension (dyne/cm), Baker–Swerdloff style dead-oil + p decay."""
    # dead-oil IFT at 68/100 F bracketed and interpolated on temperature
    s68 = 39.0 - 0.2571 * float(api)
    s100 = 37.5 - 0.2571 * float(api)
    t = float(t_f)
    if t <= 68.0:
        s = s68
    elif t >= 100.0:
        s = s100
    else:
        s = s68 - (t - 68.0) / 32.0 * (s68 - s100)
    # pressure correction factor (dissolved gas lowers IFT)
    c = 1.0 - 0.024 * float(p_psia) ** 0.45
    return float(max(s * max(c, 0.0), 1.0))


@dataclass
class _LocalProps:
    """In-situ properties at one tubing segment (computed black-oil flash)."""

    rho_l: float  # liquid (oil+water) in-situ density, lbm/ft^3
    rho_g: float  # gas in-situ density, lbm/ft^3
    mu_l: float  # liquid viscosity, cP
    mu_g: float  # gas viscosity, cP
    sigma_l: float  # liquid surface tension, dyne/cm
    vsl: float  # superficial liquid velocity, ft/s
    vsg: float  # superficial gas velocity, ft/s
    lambda_l: float  # no-slip liquid holdup (input volume fraction)
    p_psia: float  # local segment pressure, psia (for the HB pressure-ratio group)


def _segment_props(
    p_psia: float, t_f: float, q_liq_stb_d: float, inp: VLPInputs
) -> _LocalProps:
    """In-situ phase properties + superficial velocities at one node.

    Black-oil flash: dissolves Rs(p,T) into the oil, computes in-situ oil/water/gas
    densities and the free-gas rate (produced GLR minus what stays in solution), then
    superficial velocities from the tubing cross-section.
    """
    p = max(float(p_psia), 14.7)
    fw = float(np.clip(inp.water_cut, 0.0, 0.999))
    api = inp.oil_api
    gas_sg = inp.gas_sg

    area_ft2 = np.pi / 4.0 * (float(inp.tubing_id_in) / 12.0) ** 2

    # --- liquid (oil + water) in-situ density ---
    rs = _rs_standing(p, t_f, api, gas_sg)
    rs = min(rs, float(inp.glr_scf_stb) / max(1.0 - fw, 1e-6))  # cannot exceed produced
    bo = _bo_standing(rs, t_f, api, gas_sg)
    sg_o = _oil_sg(api)
    # In-situ (live/saturated) oil density, lbm/ft^3. Stock-tank-oil mass per reservoir
    # volume is (sg_o * 62.4) / Bo; the dissolved-gas mass per STB is rs*gas_sg*MW_air/379.4
    # [lbm/STB], which must be divided by the reservoir volume per STB = Bo * 5.615 ft^3/STB
    # (the bbl->ft^3 conversion). Algebraically identical to the textbook standard form
    #   rho_o = (62.4*gamma_o + 0.0136*Rs*gamma_g) / Bo      [lbm/ft^3]
    # since MW_air/379.4/5.615 = 0.01360 (the published 0.0136 already bundles the 5.615).
    # Validated: API=35, Rs=600 scf/STB, gamma_g=0.75, Bo=1.30 -> 45.50 lbm/ft^3, matching
    # the textbook formula (McCain, *The Properties of Petroleum Fluids* 2nd ed.; Standing).
    rho_o = (sg_o * WATER_DENSITY_SC + rs * gas_sg * AIR_MW / 379.4 / 5.615) / bo
    rho_w = float(inp.water_sg) * WATER_DENSITY_SC
    rho_l = (1.0 - fw) * rho_o + fw * rho_w

    mu_o = _live_oil_visc(p, t_f, api, gas_sg)
    mu_w = 0.5  # cP, representative produced-water viscosity
    mu_l = (1.0 - fw) * mu_o + fw * mu_w
    sigma_l = _surface_tension(p, t_f, api)

    # --- gas in-situ density and free-gas rate ---
    z = _z_factor(p, t_f, gas_sg)
    t_r = float(t_f) + 460.0
    rho_g = 28.97 * gas_sg * p / (z * 10.732 * t_r)  # lbm/ft^3, real-gas law

    # liquid & free-gas volumetric rates at in-situ conditions
    q_oil_stb = q_liq_stb_d * (1.0 - fw)
    q_wat_stb = q_liq_stb_d * fw
    q_liq_res = (q_oil_stb * bo + q_wat_stb * 1.0)  # rb/d (Bw ~ 1.0)
    free_gas_scf_d = max(q_oil_stb * (float(inp.glr_scf_stb) / max(1.0 - fw, 1e-6) - rs), 0.0)
    bg = z * 14.7 / 519.67 * t_r / p  # rcf/scf (real-gas, SC = 14.7 psia, 60F)
    q_gas_res = free_gas_scf_d * bg  # rcf/d

    # convert res-bbl/d and rcf/d -> ft^3/s
    q_liq_ft3_s = q_liq_res * 5.615 / 86400.0
    q_gas_ft3_s = q_gas_res / 86400.0
    vsl = q_liq_ft3_s / area_ft2
    vsg = q_gas_ft3_s / area_ft2
    vm = vsl + vsg
    lambda_l = vsl / vm if vm > 0 else 1.0

    # gas viscosity: a representative 0.02 cP constant. The friction term is dominated by
    # the liquid phase at these holdups, so a fixed light-gas viscosity is an acceptable
    # standard simplification (Lee's correlation would refine it but barely moves dP/dz).
    mu_g = 0.02
    return _LocalProps(
        rho_l=rho_l, rho_g=rho_g, mu_l=mu_l, mu_g=mu_g,
        sigma_l=sigma_l, vsl=vsl, vsg=vsg, lambda_l=float(np.clip(lambda_l, 0.0, 1.0)),
        p_psia=p,
    )


def _friction_factor(re: float, eps_d: float) -> float:
    """Darcy friction factor — laminar below Re=2000, else explicit Chen (1979)."""
    if re < 1e-6:
        return 0.0
    if re < 2000.0:
        return 64.0 / re
    # Chen (1979) explicit approximation to Colebrook
    a = eps_d / 3.7065 - 5.0452 / re * np.log10(
        eps_d ** 1.1098 / 2.8257 + (7.149 / re) ** 0.8981
    )
    return float((-2.0 * np.log10(a)) ** -2)


def _grad_hagedorn_brown(lp: _LocalProps, inp: VLPInputs) -> float:
    """Pressure gradient dP/dz (psi/ft) by **Hagedorn–Brown (1965)**.

    A widely used vertical-multiphase correlation that correlates the slip (in-situ)
    liquid holdup against four dimensionless groups (liquid-velocity, gas-velocity,
    pipe-diameter and liquid-viscosity numbers) and forms the mixture density from the
    slip holdup. We implement the standard Hagedorn–Brown holdup correlation (with the
    Griffith bubble-flow check) plus the friction term on the two-phase mixture.

    Reference: Hagedorn & Brown, *Experimental Study of Pressure Gradients...*, JPT 1965;
    Brown, *The Technology of Artificial Lift*, Vol. 1.
    """
    d_ft = float(inp.tubing_id_in) / 12.0
    vsl, vsg = lp.vsl, lp.vsg
    vm = vsl + vsg
    if vm <= 0:
        # static liquid column
        return lp.rho_l * _PSI_PER_PSF

    # dimensionless numbers (field-unit forms, Hagedorn-Brown)
    nlv = 1.938 * vsl * (lp.rho_l / lp.sigma_l) ** 0.25
    ngv = 1.938 * vsg * (lp.rho_l / lp.sigma_l) ** 0.25
    nd = 120.872 * d_ft * (lp.rho_l / lp.sigma_l) ** 0.5
    nl = 0.15726 * lp.mu_l * (1.0 / (lp.rho_l * lp.sigma_l ** 3)) ** 0.25

    # Griffith bubble-flow boundary; below it use Griffith's simple holdup
    lb = max(1.071 - 0.2218 * vm ** 2 / d_ft, 0.13)
    if vsg / vm < lb:
        # Griffith (1961) bubble-flow holdup
        vs = 0.8  # ft/s slip velocity
        hl = 1.0 - 0.5 * (1.0 + vm / vs - np.sqrt((1.0 + vm / vs) ** 2 - 4.0 * vsg / vs))
        hl = float(np.clip(hl, lp.lambda_l, 1.0))
    else:
        # Hagedorn-Brown holdup correlation via the two standard fitted curves
        cnl = (
            0.0019 + 0.0322 * nl - 0.6642 * nl ** 2 + 4.9951 * nl ** 3
        ) / (
            1.0 - 10.0147 * nl + 33.8696 * nl ** 2 + 277.2817 * nl ** 3
        )
        cnl = float(np.clip(cnl, 0.0, 0.10))
        # Hagedorn-Brown primary holdup group (Brown, *The Technology of Artificial Lift*,
        # Vol. 1; Pengtools/Economides):
        #   X1 = (Nlv / Ngv^0.575) * (p / 14.7)^0.10 * (CNL / Nd)
        # The (p/14.7)^0.10 factor is the LOCAL pressure normalized to standard pressure
        # (14.7 psia); it must use the segment pressure, not the bare constant 14.7^0.10
        # (which would ignore pressure entirely). At p = 14.7 psia this factor is 1.0.
        p_ratio = (lp.p_psia / 14.7) ** 0.10
        x1 = nlv / ngv ** 0.575 * p_ratio * cnl / nd
        x1 = max(x1, 1e-12)
        # HL/psi correlating group (Brown's curve fit)
        hl_psi = np.sqrt(
            (0.0047 + 1123.32 * x1 + 729489.64 * x1 ** 2)
            / (1.0 + 1097.1566 * x1 + 722153.97 * x1 ** 2)
        )
        x2 = ngv * nl ** 0.38 / nd ** 2.14
        if x2 < 0.01:
            psi = 1.0
        else:
            psi = (
                1.0719 + 0.1554 * x2 - 0.0408 * x2 ** 2
            )  # secondary correction factor
        psi = float(np.clip(psi, 1.0, 2.0))
        hl = float(np.clip(hl_psi * psi, lp.lambda_l, 1.0))

    rho_s = lp.rho_l * hl + lp.rho_g * (1.0 - hl)  # slip mixture density
    # elevation (hydrostatic) component
    dpdz_elev = rho_s * np.sin(np.radians(inp.angle_deg)) * _PSI_PER_PSF
    # friction on the two-phase mixture (HB uses no-slip density, slip-based mass rate)
    rho_ns = lp.rho_l * lp.lambda_l + lp.rho_g * (1.0 - lp.lambda_l)
    mu_ns = lp.mu_l * lp.lambda_l + lp.mu_g * (1.0 - lp.lambda_l)
    re = 1488.0 * rho_ns * vm * d_ft / max(mu_ns, 1e-6)
    f = _friction_factor(re, float(inp.roughness_in) / float(inp.tubing_id_in))
    # HB friction term uses mass flux: rho_ns^2 / rho_s
    dpdz_fric = (
        f * rho_ns ** 2 * vm ** 2 / (2.0 * _G * d_ft * max(rho_s, 1e-6))
    ) * _PSI_PER_PSF
    return float(dpdz_elev + dpdz_fric)


def _grad_beggs_brill(lp: _LocalProps, inp: VLPInputs) -> float:
    """Pressure gradient dP/dz (psi/ft) by **Beggs–Brill (1973)**.

    The classic *all-inclination* mechanistic-empirical correlation: classify the no-slip
    flow pattern (segregated / intermittent / distributed / transition), compute the
    horizontal holdup, then apply the inclination correction to get the in-situ holdup
    and mixture density, plus a two-phase friction multiplier.

    Reference: Beggs & Brill, *A Study of Two-Phase Flow in Inclined Pipes*, JPT 1973.
    """
    d_ft = float(inp.tubing_id_in) / 12.0
    vsl, vsg = lp.vsl, lp.vsg
    vm = vsl + vsg
    if vm <= 0:
        return lp.rho_l * _PSI_PER_PSF
    lam = float(np.clip(lp.lambda_l, 1e-9, 1.0))
    nfr = vm ** 2 / (_G * d_ft)  # Froude number

    # flow-pattern boundaries (Beggs-Brill)
    l1 = 316.0 * lam ** 0.302
    l2 = 0.0009252 * lam ** -2.4684
    l3 = 0.10 * lam ** -1.4516
    l4 = 0.5 * lam ** -6.738

    def _hl_horiz(a, b, c):
        h = a * lam ** b / nfr ** c
        return float(np.clip(max(h, lam), 0.0, 1.0))

    if (lam < 0.01 and nfr < l1) or (lam >= 0.01 and nfr < l2):
        pattern = "segregated"
        hl0 = _hl_horiz(0.98, 0.4846, 0.0868)
    elif lam >= 0.01 and l2 <= nfr <= l3:
        pattern = "transition"
        hl_seg = _hl_horiz(0.98, 0.4846, 0.0868)
        hl_int = _hl_horiz(0.845, 0.5351, 0.0173)
        aa = (l3 - nfr) / (l3 - l2)
        hl0 = aa * hl_seg + (1.0 - aa) * hl_int
    elif (0.01 <= lam < 0.4 and l3 < nfr <= l1) or (lam >= 0.4 and l3 < nfr <= l4):
        pattern = "intermittent"
        hl0 = _hl_horiz(0.845, 0.5351, 0.0173)
    else:
        pattern = "distributed"
        hl0 = _hl_horiz(1.065, 0.5824, 0.0609)

    # inclination correction
    nlv = 1.938 * vsl * (lp.rho_l / lp.sigma_l) ** 0.25
    if pattern == "segregated":
        d, e, f, g = 0.011, -3.768, 3.539, -1.614
    elif pattern == "intermittent":
        d, e, f, g = 2.96, 0.305, -0.4473, 0.0978
    elif pattern == "distributed":
        d = e = f = g = 0.0  # C = 0, no correction (psi factor -> 1)
    else:  # transition: blend seg & int corrections same as holdup
        d, e, f, g = 0.011, -3.768, 3.539, -1.614

    if pattern == "distributed":
        cc = 0.0
    else:
        cc = (1.0 - lam) * np.log(max(d * lam ** e * nlv ** f * nfr ** g, 1e-12))
        cc = max(cc, 0.0)
    angle = np.radians(inp.angle_deg)
    psi = 1.0 + cc * (np.sin(1.8 * angle) - 0.333 * np.sin(1.8 * angle) ** 3)
    hl = float(np.clip(hl0 * psi, lam, 1.0))

    rho_s = lp.rho_l * hl + lp.rho_g * (1.0 - hl)
    dpdz_elev = rho_s * np.sin(angle) * _PSI_PER_PSF

    # two-phase friction (Beggs-Brill normalized friction multiplier)
    rho_ns = lp.rho_l * lam + lp.rho_g * (1.0 - lam)
    mu_ns = lp.mu_l * lam + lp.mu_g * (1.0 - lam)
    re = 1488.0 * rho_ns * vm * d_ft / max(mu_ns, 1e-6)
    fn = _friction_factor(re, float(inp.roughness_in) / float(inp.tubing_id_in))
    y = lam / max(hl ** 2, 1e-9)
    if 1.0 < y < 1.2:
        s = np.log(2.2 * y - 1.2)
    else:
        ln_y = np.log(max(y, 1e-9))
        s = ln_y / (
            -0.0523 + 3.182 * ln_y - 0.8725 * ln_y ** 2 + 0.01853 * ln_y ** 4
        )
    ftp = fn * np.exp(s)
    dpdz_fric = (ftp * rho_ns * vm ** 2 / (2.0 * _G * d_ft)) * _PSI_PER_PSF
    return float(dpdz_elev + dpdz_fric)


def _grad(lp: _LocalProps, inp: VLPInputs) -> float:
    if inp.correlation == "beggs_brill":
        return _grad_beggs_brill(lp, inp)
    return _grad_hagedorn_brown(lp, inp)


def pwf_from_vlp(q_liq_stb_d: float, inp: VLPInputs) -> float:
    """Required flowing bottom-hole pressure (psia) to lift ``q_liq_stb_d`` up the tubing.

    Marches the multiphase pressure gradient from the wellhead (known THP) down the
    tubing in ``n_segments`` steps, recomputing in-situ properties at each node. Returns
    the bottom-hole pressure — i.e. one point on the VLP (outflow) curve.
    """
    q = max(float(q_liq_stb_d), 1e-6)
    n = int(inp.n_segments)
    depths = np.linspace(0.0, float(inp.depth_ft), n + 1)
    temps = np.linspace(
        float(inp.temp_surface_f), float(inp.temp_bottom_f), n + 1
    )
    p = float(inp.wellhead_pressure)
    for i in range(n):
        dz = depths[i + 1] - depths[i]
        # evaluate gradient at the midpoint temperature using current p (explicit march)
        t_mid = 0.5 * (temps[i] + temps[i + 1])
        lp = _segment_props(p, t_mid, q, inp)
        dpdz = _grad(lp, inp)
        # one corrector pass: re-evaluate at the half-step pressure
        lp2 = _segment_props(p + 0.5 * dpdz * dz, t_mid, q, inp)
        dpdz = 0.5 * (dpdz + _grad(lp2, inp))
        p += dpdz * dz
    return float(p)


@dataclass
class VLPResult:
    """A vertical-lift-performance (outflow) curve sampled as (q, pwf)."""

    q: np.ndarray  # liquid rate, STB/d (ascending)
    pwf: np.ndarray  # required flowing bottom-hole pressure, psia
    inputs: VLPInputs = field(default_factory=VLPInputs)

    def pwf_at(self, q: float) -> float:
        """Interpolate the required pwf (psia) at a liquid rate (STB/d)."""
        return float(np.interp(float(q), self.q, self.pwf))


def vlp_curve(inp: VLPInputs, q_max: float = 4000.0, n: int = 28) -> VLPResult:
    """Sample the VLP (tubing outflow) curve over a rate range.

    Returns required pwf vs. liquid rate. The curve is characteristically J-shaped:
    high at low rate (liquid loading / heavy hydrostatic column) and rising again at high
    rate (friction-dominated).
    """
    q = np.linspace(max(q_max / n, 1.0), float(q_max), int(n))
    pwf = np.array([pwf_from_vlp(float(qi), inp) for qi in q], dtype=float)
    return VLPResult(q=q, pwf=pwf, inputs=inp)


# ============================================================================ operating point
@dataclass
class OperatingPoint:
    """The IPR ∩ VLP solution: the rate/pressure the well actually flows at."""

    q_op: float  # operating liquid rate, STB/d
    pwf_op: float  # operating flowing bottom-hole pressure, psia
    converged: bool


def operating_point(
    ipr: IPRResult, vlp: VLPResult | VLPInputs, q_lo: float = 1.0,
    q_hi: float | None = None,
) -> OperatingPoint:
    """Find the nodal operating point = intersection of the IPR and VLP curves.

    Solves ``pwf_IPR(q) − pwf_VLP(q) = 0`` for the liquid rate ``q`` by Brent's method.
    At a rate ``q`` the IPR gives the pwf the reservoir produces and the VLP gives the
    pwf the tubing demands; the well stabilizes where they're equal. ``vlp`` may be a
    pre-sampled :class:`VLPResult` (fast, interpolated) or :class:`VLPInputs` (re-marched
    at each trial rate, more accurate).

    A J-shaped VLP can cross the IPR twice: a low-rate **unstable** (liquid-loading)
    intersection and a high-rate **stable** operating point. We always return the
    *rightmost* (highest-rate) crossing — the physically stable point a well settles at,
    per the standard nodal-stability convention (Brown / Economides).

    Returns ``converged=False`` (with the best/clamped estimate) if no sign change is
    bracketed — e.g. the well cannot flow (VLP everywhere above IPR).
    """
    # invert the IPR: pwf as a function of q (monotone decreasing q in pwf -> invertible).
    # vogel_ipr returns q ascending (0 -> AOF) and pwf descending (p_res -> 0), so q is
    # already a valid ascending xp for np.interp(q -> pwf); no reversal needed.
    pwf_grid = ipr.pwf
    q_grid = ipr.q

    def pwf_ipr_of_q(qq: float) -> float:
        return float(np.interp(qq, q_grid, pwf_grid))

    if isinstance(vlp, VLPResult):
        def pwf_vlp_of_q(qq: float) -> float:
            return vlp.pwf_at(qq)
        q_hi = q_hi if q_hi is not None else float(vlp.q.max())
    else:
        def pwf_vlp_of_q(qq: float) -> float:
            return pwf_from_vlp(qq, vlp)
        q_hi = q_hi if q_hi is not None else float(ipr.aof) * 0.999

    q_hi = min(q_hi, float(ipr.aof) * 0.999)
    if q_hi <= q_lo:
        return OperatingPoint(float(q_lo), float(pwf_ipr_of_q(q_lo)), False)

    def diff(qq: float) -> float:
        return pwf_ipr_of_q(qq) - pwf_vlp_of_q(qq)

    # Scan the whole feasible rate range and take the RIGHTMOST sign change (stable point).
    qs = np.linspace(q_lo, q_hi, 120)
    ds = np.array([diff(q) for q in qs])
    sign_change = np.where(np.sign(ds[:-1]) != np.sign(ds[1:]))[0]
    if len(sign_change) == 0:
        # no intersection at all: report the closest approach, flag not-converged
        j = int(np.argmin(np.abs(ds)))
        return OperatingPoint(float(qs[j]), float(pwf_ipr_of_q(qs[j])), False)

    i = int(sign_change[-1])  # rightmost / highest-rate crossing = stable operating point
    q_op = float(brentq(diff, qs[i], qs[i + 1], xtol=1e-3, rtol=1e-6, maxiter=200))
    pwf_op = 0.5 * (pwf_ipr_of_q(q_op) + pwf_vlp_of_q(q_op))
    return OperatingPoint(q_op, float(pwf_op), True)
