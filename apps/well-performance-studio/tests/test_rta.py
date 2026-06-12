"""Deterministic RTA tests: fit returns finite params on the synthetic series."""
import io

import numpy as np
import pandas as pd

from src.rta import fit_rta, parse_rate_csv, synthetic_series


def test_synthetic_series_shape():
    s = synthetic_series()
    assert {"date", "rate_mscf_d"}.issubset(s.columns)
    assert len(s) > 100
    assert (s["rate_mscf_d"] >= 0).all()
    assert np.isfinite(s["rate_mscf_d"].to_numpy()).all()


def test_fit_returns_finite_params():
    res = fit_rta(synthetic_series())
    assert np.isfinite(res.m_mscf) and res.m_mscf > 0
    assert np.isfinite(res.tau_years) and res.tau_years > 0
    assert np.isfinite(res.eur_mmscf) and res.eur_mmscf > 0
    assert np.isfinite(res.rmse_mmscf) and res.rmse_mmscf >= 0


def test_fit_recovers_known_truth_within_tolerance():
    # synthetic_series is built at M=3.2e6 Mscf, tau=2.4 yr; an honest fit
    # should land within a loose band despite the multiplicative noise.
    res = fit_rta(synthetic_series(m_mscf=3.2e6, tau_years=2.4))
    assert 0.7 * 3.2e6 <= res.m_mscf <= 1.3 * 3.2e6
    assert 0.5 * 2.4 <= res.tau_years <= 1.5 * 2.4


def test_forecast_frames_present_and_consistent():
    res = fit_rta(synthetic_series(), horizon_years=12.0)
    assert {"years", "cum_mmscf"}.issubset(res.history.columns)
    assert {"years", "cum_mmscf", "rate_mscf_d"}.issubset(res.forecast.columns)
    # forecast cumulative is monotone non-decreasing and ends near the EUR
    assert (res.forecast["cum_mmscf"].diff().fillna(0.0) >= -1e-6).all()
    assert abs(res.forecast["cum_mmscf"].iloc[-1] - res.eur_mmscf) < 1e-6


def test_fit_is_deterministic_on_seeded_series():
    a = fit_rta(synthetic_series(seed=7))
    b = fit_rta(synthetic_series(seed=7))
    assert np.isclose(a.m_mscf, b.m_mscf) and np.isclose(a.tau_years, b.tau_years)


def test_parse_rate_csv_flexible_columns():
    s = synthetic_series().rename(columns={"rate_mscf_d": "Gas Rate (Mscf/d)"})
    parsed = parse_rate_csv(io.StringIO(s.to_csv(index=False)))
    assert {"date", "rate_mscf_d"}.issubset(parsed.columns)
    assert len(parsed) == len(s)


def test_parse_rate_csv_rejects_too_few_rows():
    bad = pd.DataFrame({"date": ["2023-01-01", "2023-01-02"], "rate": [1.0, 2.0]})
    try:
        parse_rate_csv(io.StringIO(bad.to_csv(index=False)))
        raised = False
    except ValueError:
        raised = True
    assert raised
