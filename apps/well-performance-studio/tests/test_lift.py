"""Deterministic artificial-lift tests: ESP returns sane positive stages/frequency/power
and meets a feasible target; gas-lift increases the rate; pump-curve physics holds."""
import numpy as np

from src.lift import (
    PumpModel,
    design_esp,
    gas_lift_sweep,
)
from src.nodal import VLPInputs, operating_point, vogel_ipr


def _ref_system():
    """A weak-ish well that under-delivers naturally so lift has work to do."""
    ipr = vogel_ipr(p_res=3000.0, pb=3000.0, q_test=600.0, pwf_test=2200.0)
    vlp = VLPInputs(
        tubing_id_in=2.441, depth_ft=8000.0, wellhead_pressure=150.0,
        glr_scf_stb=300.0, water_cut=0.40,
    )
    return ipr, vlp


# --------------------------------------------------------------------------- pump model
def test_pump_head_decreases_with_rate():
    pm = PumpModel()
    assert pm.head_per_stage(1000.0) > pm.head_per_stage(2000.0) > pm.head_per_stage(3000.0)


def test_pump_affinity_head_scales_with_frequency():
    pm = PumpModel()
    # head at a fixed rate is lower at lower frequency (affinity ~ f^2 at referred flow)
    assert pm.head_per_stage(2000.0, 50.0) < pm.head_per_stage(2000.0, 60.0)


def test_pump_efficiency_peaks_near_bep():
    pm = PumpModel()
    e_bep = pm.efficiency(pm.q_bep_bpd)
    assert pm.efficiency(pm.q_bep_bpd * 0.5) < e_bep
    assert pm.efficiency(pm.q_bep_bpd * 1.5) < e_bep
    assert 0.0 < e_bep <= pm.eff_bep + 1e-9


# --------------------------------------------------------------------------- ESP design
def test_esp_design_returns_positive_sane_values():
    ipr, vlp = _ref_system()
    d = design_esp(ipr, vlp, target_q_stb_d=1200.0, fluid_viscosity_cp=5.0)
    assert d.stages > 0 and d.stages < 1000          # positive, sane count
    assert 30.0 <= d.frequency_hz <= 90.0            # sane drive frequency
    assert d.bhp > 0 and np.isfinite(d.bhp)          # positive power
    assert d.tdh_ft > 0 and np.isfinite(d.tdh_ft)    # positive head
    assert d.head_per_stage_ft > 0
    assert 0.0 < d.efficiency <= 1.0


def test_esp_meets_feasible_target():
    # A target the reservoir can support once the pump removes the lift constraint.
    ipr, vlp = _ref_system()
    natural = operating_point(ipr, vlp)
    target = 1200.0
    assert natural.q_op < target  # the well does NOT make this rate naturally
    d = design_esp(ipr, vlp, target_q_stb_d=target, fluid_viscosity_cp=5.0)
    assert d.meets_target
    assert d.op_q_stb_d >= 0.98 * target  # boosted operating point reaches the target


def test_esp_more_viscous_fluid_needs_more_stages_lower_eff():
    ipr, vlp = _ref_system()
    d_light = design_esp(ipr, vlp, 1200.0, fluid_viscosity_cp=5.0)
    d_heavy = design_esp(ipr, vlp, 1200.0, fluid_viscosity_cp=120.0)
    assert d_heavy.stages >= d_light.stages
    assert d_heavy.efficiency < d_light.efficiency


def test_esp_higher_frequency_fewer_stages():
    ipr, vlp = _ref_system()
    d50 = design_esp(ipr, vlp, 1200.0, frequency_hz=50.0)
    d60 = design_esp(ipr, vlp, 1200.0, frequency_hz=60.0)
    # higher frequency => more head per stage => fewer stages for the same TDH
    assert d60.stages < d50.stages


def test_esp_design_is_deterministic():
    ipr, vlp = _ref_system()
    a = design_esp(ipr, vlp, 1200.0)
    b = design_esp(ipr, vlp, 1200.0)
    assert a.stages == b.stages
    assert np.isclose(a.bhp, b.bhp) and np.isclose(a.op_q_stb_d, b.op_q_stb_d)


# --------------------------------------------------------------------------- gas lift
def test_gas_lift_increases_rate_over_natural():
    ipr, vlp = _ref_system()
    natural = operating_point(ipr, vlp)
    gl = gas_lift_sweep(ipr, vlp, inj_glr_max_scf_stb=1500.0, n=12)
    # injecting gas lightens the column => the optimum rate beats the no-injection rate
    assert gl.best.q_op_stb_d > natural.q_op
    assert gl.inj_rate_mscf_d_at_best > 0


def test_gas_lift_sweep_shape_and_bounds():
    ipr, vlp = _ref_system()
    gl = gas_lift_sweep(ipr, vlp, inj_glr_max_scf_stb=1200.0, n=10)
    assert len(gl.points) == 10
    assert gl.points[0].inj_glr_scf_stb == 0.0           # sweep starts at no injection
    assert all(np.isfinite(p.q_op_stb_d) for p in gl.points)
    assert all(p.q_op_stb_d >= 0 for p in gl.points)
    # the optimum is the max of the swept rates
    assert gl.best.q_op_stb_d == max(p.q_op_stb_d for p in gl.points)
