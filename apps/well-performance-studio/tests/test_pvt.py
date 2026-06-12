"""Deterministic PVT wrapper tests: properties finite and physically positive."""
import numpy as np

from src.pvt import PVTInputs, bubble_point, props_at_pressure, pvt_table


def test_pvt_table_finite_and_positive():
    df = pvt_table(PVTInputs())
    arr = df.to_numpy()
    assert np.isfinite(arr).all(), "PVT table has non-finite values"
    for col in ["Bo", "oil_viscosity", "Bg", "gas_viscosity", "z_factor",
                "Bw", "water_viscosity"]:
        assert (df[col] > 0).all(), f"{col} should be strictly positive"
    assert len(df) == PVTInputs().n_points


def test_oil_fvf_increases_toward_bubble_point():
    # Below Pb, Bo rises with pressure as more gas dissolves (Standing).
    inp = PVTInputs(pressure_min=500.0, pressure_max=3000.0, n_points=20)
    df = pvt_table(inp)
    assert df["Bo"].iloc[-1] > df["Bo"].iloc[0]


def test_z_factor_in_physical_range():
    df = pvt_table(PVTInputs())
    # gas z-factor stays in a sane band for these conditions
    assert (df["z_factor"] > 0.2).all() and (df["z_factor"] < 1.6).all()


def test_bubble_point_positive_and_finite():
    pb = bubble_point(PVTInputs())
    assert np.isfinite(pb) and pb > 0


def test_props_at_pressure_matches_keys_and_finite():
    props = props_at_pressure(PVTInputs(), 3000.0)
    expected = {"pressure", "Bo", "oil_viscosity", "Bg", "gas_viscosity",
                "z_factor", "Bw", "water_viscosity"}
    assert set(props) == expected
    assert all(np.isfinite(v) and v > 0 for v in props.values())
    assert props["pressure"] == 3000.0


def test_pvt_is_deterministic():
    a = pvt_table(PVTInputs())
    b = pvt_table(PVTInputs())
    assert np.allclose(a.to_numpy(), b.to_numpy())
