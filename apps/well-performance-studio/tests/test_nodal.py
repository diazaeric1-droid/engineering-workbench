"""Deterministic nodal-analysis tests: IPR/VLP monotonicity, a unique operating point,
and a validation against a published Vogel worked example."""
import numpy as np

from src.nodal import (
    VLPInputs,
    operating_point,
    pwf_from_vlp,
    straight_line_ipr,
    vlp_curve,
    vogel_ipr,
)


# --------------------------------------------------------------------------- IPR
def test_vogel_ipr_monotone_decreasing_in_pwf():
    # q must rise monotonically as pwf falls (more drawdown -> more rate).
    ipr = vogel_ipr(p_res=3000.0, pb=2500.0, q_test=500.0, pwf_test=2000.0)
    # pwf is descending p_res->0, so q should be non-decreasing along the array
    assert (np.diff(ipr.q) >= -1e-9).all()
    # and strictly: rate at high pwf < rate at low pwf
    assert ipr.q_at(2500.0) < ipr.q_at(500.0)
    assert ipr.aof > 0 and np.isfinite(ipr.aof)


def test_vogel_ipr_honors_test_point():
    # The supplied flow test must lie exactly on the returned curve.
    ipr = vogel_ipr(p_res=3000.0, pb=2500.0, q_test=500.0, pwf_test=2000.0)
    assert abs(ipr.q_at(2000.0) - 500.0) < 1e-3


def test_vogel_dimensionless_reference_curve():
    # Saturated reservoir (p_res = pb) must reproduce Vogel's dimensionless curve
    #   q/qmax = 1 - 0.2(pwf/pr) - 0.8(pwf/pr)^2  exactly.
    pr = 2000.0
    ipr = vogel_ipr(p_res=pr, pb=pr, j=1.0, n=2001)
    qmax = ipr.aof
    for frac in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
        expected = 1.0 - 0.2 * frac - 0.8 * frac ** 2
        assert abs(ipr.q_at(frac * pr) / qmax - expected) < 1e-6


def test_vogel_validation_published_worked_example():
    # VALIDATION (Beggs, *Production Optimization Using Nodal Analysis*; also Guo et al.,
    # *Petroleum Production Engineering*, Ch.3): saturated well, p_res = 2085 psia, a flow
    # test of q = 282 STB/d at pwf = 1765 psia. Vogel gives the absolute open-flow:
    #   (pwf/pr) = 1765/2085 = 0.8465
    #   qmax = q / [1 - 0.2(0.8465) - 0.8(0.8465)^2] = 282 / 0.2575 = 1095 STB/d.
    # Published AOF for this example is ~1095 STB/d; require within 1%.
    ipr = vogel_ipr(p_res=2085.0, pb=2085.0, q_test=282.0, pwf_test=1765.0, n=400)
    assert abs(ipr.aof - 1095.0) / 1095.0 < 0.01
    assert abs(ipr.q_at(1765.0) - 282.0) < 1e-2  # test point honored


def test_straight_line_ipr_linear_and_aof():
    ipr = straight_line_ipr(p_res=4000.0, j=2.0)
    assert abs(ipr.aof - 8000.0) < 1e-6  # AOF = J * p_res
    # exactly linear: q = J (p_res - pwf)
    assert abs(ipr.q_at(3000.0) - 2.0 * (4000.0 - 3000.0)) < 1e-6
    assert (np.diff(ipr.q) >= -1e-9).all()


def test_ipr_is_deterministic():
    a = vogel_ipr(p_res=3000.0, pb=2500.0, q_test=500.0, pwf_test=2000.0)
    b = vogel_ipr(p_res=3000.0, pb=2500.0, q_test=500.0, pwf_test=2000.0)
    assert np.allclose(a.q, b.q) and np.isclose(a.aof, b.aof)


# --------------------------------------------------------------------------- VLP
def _ref_vlp(correlation="hagedorn_brown"):
    return VLPInputs(
        tubing_id_in=2.441, depth_ft=8000.0, wellhead_pressure=150.0,
        glr_scf_stb=400.0, water_cut=0.30, correlation=correlation,
    )


def test_vlp_required_pwf_finite_and_positive():
    inp = _ref_vlp()
    for q in (100.0, 500.0, 1500.0):
        p = pwf_from_vlp(q, inp)
        assert np.isfinite(p) and p > 0


def test_vlp_increases_with_rate_in_friction_branch():
    # On the right (friction-dominated) branch of the J-shaped VLP, required pwf rises
    # with rate. Sample well above the loading minimum.
    inp = _ref_vlp()
    res = vlp_curve(inp, q_max=3000.0, n=24)
    # take the post-minimum portion and assert overall upward trend
    i_min = int(np.argmin(res.pwf))
    hi = res.pwf[i_min:]
    assert hi[-1] > hi[0]
    # rate at the high end demands more pwf than at the curve minimum
    assert pwf_from_vlp(3000.0, inp) > res.pwf.min()


def test_vlp_both_correlations_run_and_are_sane():
    for corr in ("hagedorn_brown", "beggs_brill"):
        p = pwf_from_vlp(800.0, _ref_vlp(corr))
        assert np.isfinite(p) and 200.0 < p < 8000.0


def test_vlp_is_deterministic():
    inp = _ref_vlp()
    a = pwf_from_vlp(900.0, inp)
    b = pwf_from_vlp(900.0, inp)
    assert np.isclose(a, b)


# --------------------------------------------------------------------------- operating point
def test_operating_point_unique_and_satisfies_both_curves():
    # A sane, flowing case: moderate reservoir, ordinary 2-7/8" tubing.
    ipr = vogel_ipr(p_res=3500.0, pb=3500.0, q_test=800.0, pwf_test=2500.0)
    inp = _ref_vlp()
    op = operating_point(ipr, inp)
    assert op.converged
    assert 0.0 < op.q_op < ipr.aof
    # the operating point lies on BOTH curves: IPR pwf(q_op) == VLP pwf(q_op)
    pwf_ipr = float(np.interp(op.q_op, ipr.q, ipr.pwf))
    pwf_vlp = pwf_from_vlp(op.q_op, inp)
    assert abs(pwf_ipr - pwf_vlp) < 5.0  # psi
    assert abs(op.pwf_op - pwf_vlp) < 5.0


def test_operating_point_interp_and_remarch_agree():
    # Pre-sampled VLP (interpolated) and re-marched VLP must find the same point.
    ipr = vogel_ipr(p_res=3500.0, pb=3500.0, q_test=800.0, pwf_test=2500.0)
    inp = _ref_vlp()
    op_interp = operating_point(ipr, vlp_curve(inp, q_max=ipr.aof * 0.99, n=30))
    op_remarch = operating_point(ipr, inp)
    assert op_interp.converged and op_remarch.converged
    assert abs(op_interp.q_op - op_remarch.q_op) < 25.0  # STB/d


def test_operating_point_picks_stable_rightmost_root():
    # The J-shaped VLP crosses the IPR twice; we must return the high-rate stable point,
    # not the low-rate (liquid-loading) unstable one.
    ipr = vogel_ipr(p_res=3500.0, pb=3500.0, q_test=800.0, pwf_test=2500.0)
    inp = _ref_vlp()
    op = operating_point(ipr, inp)
    # the stable point for this system is several hundred STB/d, not a near-zero loading rate
    assert op.q_op > 500.0


def test_operating_point_no_intersection_flagged():
    # A very weak reservoir against a deep, heavy column may not flow: must not raise and
    # must report converged == False.
    ipr = vogel_ipr(p_res=900.0, pb=900.0, q_test=40.0, pwf_test=700.0)
    inp = VLPInputs(tubing_id_in=2.441, depth_ft=12000.0, wellhead_pressure=300.0,
                    glr_scf_stb=50.0, water_cut=0.8)
    op = operating_point(ipr, inp)
    assert op.converged is False
    assert np.isfinite(op.q_op) and np.isfinite(op.pwf_op)
