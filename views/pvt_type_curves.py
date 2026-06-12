"""Design → PVT & Type Curves — black-oil PVT, bluebonnet physics production
curves, and rate-transient analysis.

bluebonnet is imported LAZILY inside this view (via core.wps_physics) so the rest
of the workbench keeps working when the physics engine is unavailable — this page
then renders an empty state instead of crashing the product.
"""
from __future__ import annotations

import dataclasses

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import core
import product_theme as pt
import theme

from views import _common


def _hash_inputs(obj) -> tuple:
    return dataclasses.astuple(obj)


@st.cache_data(show_spinner=False, hash_funcs={"wps.pvt.PVTInputs": _hash_inputs})
def _pvt_table(inp):
    pvt, _curves, _rta = core.wps_physics()
    return pvt.pvt_table(inp)


@st.cache_data(show_spinner=False, hash_funcs={"wps.pvt.PVTInputs": _hash_inputs})
def _bubble_point(inp) -> float:
    pvt, _curves, _rta = core.wps_physics()
    return pvt.bubble_point(inp)


@st.cache_data(show_spinner=False, hash_funcs={"wps.curves.CurveInputs": _hash_inputs})
def _production_curve(inp):
    _pvt, curves, _rta = core.wps_physics()
    return curves.production_curve(inp)


def _hash_series(df: pd.DataFrame) -> bytes:
    return pd.util.hash_pandas_object(df, index=True).values.tobytes()


@st.cache_data(show_spinner=False, hash_funcs={pd.DataFrame: _hash_series})
def _fit_rta(series: pd.DataFrame, horizon_years: float = 15.0):
    _pvt, _curves, rta = core.wps_physics()
    return rta.fit_rta(series, horizon_years=horizon_years)


def render() -> None:
    _common.ensure_state()
    pt.masthead("workbench", "PVT & Type Curves",
                "Black-oil fluid properties, physics-based production curves, and "
                "rate-transient analysis (bluebonnet)")
    _common.context()

    try:
        core.wps_physics()
    except Exception as exc:  # noqa: BLE001 — bluebonnet absent / broken
        pt.empty_state(
            "The physics engine (bluebonnet) is unavailable in this environment, so "
            "the PVT, physics-curve, and RTA lenses cannot render. Every other "
            f"workbench page is unaffected. ({type(exc).__name__}: {exc})",
            "pip install bluebonnet (Python <= 3.11) to enable this page.")
        return

    theme.data_badge(
        "synthetic",
        "Physics-modeled (bluebonnet) on illustrative reservoir/fluid inputs; the RTA "
        "tab can ingest a real rate series.")

    tab_pvt, tab_curve, tab_rta = st.tabs(
        ["PVT Properties", "Physics Production Curve", "Rate-Transient Analysis"])

    # ------------------------------------------------------------------ PVT
    with tab_pvt:
        pvt_mod, _curves_mod, rta_mod = core.wps_physics()
        pt.section("Fluid Properties Vs. Pressure",
                   "Standing / Vázquez-Beggs / Dranchuk–Abou-Kassem correlations.")
        c1, c2, c3 = st.columns(3)
        with c1:
            api = st.slider("Oil Gravity (°API)", 15.0, 55.0, 38.0, 0.5)
            sg = st.slider("Gas Specific Gravity (air=1)", 0.55, 1.10, 0.75, 0.01)
        with c2:
            gor = st.slider("Solution GOR, Rs (scf/bbl)", 100.0, 3000.0, 900.0, 50.0)
            temp = st.slider("Reservoir Temperature (°F)", 120.0, 320.0, 210.0, 5.0)
        with c3:
            p_lo, p_hi = st.slider("Pressure Range (psia)", 200, 10000, (500, 6000), 100)
            dryness = st.selectbox("Gas Dryness", ("wet gas", "dry gas"), index=0)

        pvt_in = pvt_mod.PVTInputs(
            api_gravity=api, gas_specific_gravity=sg, solution_gor=gor,
            temperature=temp, pressure_min=float(p_lo), pressure_max=float(p_hi),
            n_points=48, gas_dryness=dryness)
        df = _pvt_table(pvt_in)
        pb = _bubble_point(pvt_in)

        pt.kpi_row([
            {"label": "Bubble Point", "value": f"{pb:,.0f} psia"},
            {"label": "Bo @ Pmax", "value": f"{df['Bo'].iloc[-1]:.3f} rb/stb"},
            {"label": "Oil Viscosity @ Pmin", "value": f"{df['oil_viscosity'].iloc[0]:.3f} cP"},
        ])

        cL, cR = st.columns(2)
        with cL:
            fig = go.Figure()
            fig.add_scatter(x=df["pressure"], y=df["Bo"], name="Bo (oil FVF, rb/stb)")
            fig.add_scatter(x=df["pressure"], y=df["Bw"], name="Bw (water FVF, rb/stb)")
            if p_lo <= pb <= p_hi:
                fig.add_vline(x=pb, line_dash="dot", line_color=theme.AMBER)
            fig.update_layout(title="Formation Volume Factors",
                              xaxis_title="Pressure (psia)", yaxis_title="FVF (rb/stb)")
            st.plotly_chart(theme.style_fig(fig, height=300), width="stretch")
        with cR:
            figv = go.Figure()
            figv.add_scatter(x=df["pressure"], y=df["oil_viscosity"], name="μ_oil (cP)")
            figv.add_scatter(x=df["pressure"], y=df["water_viscosity"], name="μ_water (cP)")
            figv.update_layout(title="Oil & Water Viscosity",
                               xaxis_title="Pressure (psia)", yaxis_title="Viscosity (cP)")
            st.plotly_chart(theme.style_fig(figv, height=300), width="stretch")

        figz = go.Figure()
        figz.add_scatter(x=df["pressure"], y=df["z_factor"], name="z-factor")
        figz.update_layout(title="Gas Z-Factor (Dranchuk–Abou-Kassem)",
                           xaxis_title="Pressure (psia)", yaxis_title="z (-)")
        st.plotly_chart(theme.style_fig(figz, height=260), width="stretch")
        theme.source_note(
            "Black-oil & gas PVT correlations (Standing; Vázquez–Beggs; DAK z-factor) "
            "via bluebonnet. Pressure psia; FVF rb/stb; viscosity cP; Rs scf/bbl.")
        theme.references(["pvt", "bluebonnet"])

    # ----------------------------------------------------- physics production curve
    with tab_curve:
        _pvt_mod, curves_mod, _ = core.wps_physics()
        pt.section("Scaling-Solution Forecast",
                   "1-D pseudopressure-diffusion solve scaled by movable gas in "
                   "place (M) and time-to-BDF (τ); optional Arps overlay.")
        c1, c2, c3 = st.columns(3)
        with c1:
            c_sg = st.slider("Gas Specific Gravity", 0.55, 1.00, 0.70, 0.01, key="c_sg")
            c_temp = st.slider("Reservoir Temp (°F)", 120.0, 320.0, 230.0, 5.0, key="c_t")
        with c2:
            c_pi = st.slider("Initial Pressure (psia)", 2000, 10000, 6500, 100)
            c_pf = st.slider("Flowing BHP (psia)", 200, 4000, 1200, 50)
        with c3:
            c_res = st.slider("Movable Gas In Place (MMscf)", 200, 12000, 4000, 100)
            c_tau = st.slider("Time-To-BDF, τ (years)", 0.3, 12.0, 3.0, 0.1)
            c_yrs = st.slider("Forecast Horizon (years)", 2.0, 40.0, 20.0, 1.0)

        curve_in = curves_mod.CurveInputs(
            gas_specific_gravity=c_sg, temperature=c_temp, gas_dryness="dry gas",
            pressure_initial=float(c_pi),
            pressure_fracface=float(min(c_pf, c_pi - 50)),
            resource_mmscf=float(c_res), tau_years=float(c_tau), years=float(c_yrs))
        curve = _production_curve(curve_in)
        eur = float(curve["cum_mmscf"].iloc[-1])

        show_arps = st.checkbox("Overlay Empirical Arps Decline", value=False)
        arps = None
        if show_arps:
            a1, a2, a3 = st.columns(3)
            qi = a1.number_input("Arps qi (Mscf/d)", 100.0, 1e5,
                                 float(max(curve["rate_mscf_d"].iloc[1], 1000.0)), 100.0)
            di = a2.slider("Arps Di (1/yr)", 0.05, 2.5, 0.7, 0.05)
            bexp = a3.slider("Arps b", 0.0, 1.5, 1.0, 0.1)
            arps = curves_mod.arps_overlay(qi, di, bexp, c_yrs)

        pt.kpi_row([
            {"label": "EUR (physics)", "value": f"{eur:,.0f} MMscf",
             "help": f"≈ {eur/1000:,.2f} Bcf over the horizon"},
            {"label": "Peak Rate", "value": f"{curve['rate_mscf_d'].max():,.0f} Mscf/d"},
            {"label": "Rate @ Horizon", "value": f"{curve['rate_mscf_d'].iloc[-1]:,.0f} Mscf/d"},
        ])

        cL, cR = st.columns(2)
        with cL:
            figr = go.Figure()
            figr.add_scatter(x=curve["years"], y=curve["rate_mscf_d"],
                             name="Physics (bluebonnet)")
            if arps is not None:
                figr.add_scatter(x=arps["years"], y=arps["rate_mscf_d"],
                                 name="Arps overlay", line=dict(dash="dash"))
            figr.update_layout(title="Gas Rate Vs. Time", xaxis_title="Years",
                               yaxis_title="Rate (Mscf/d)")
            st.plotly_chart(theme.style_fig(figr, height=320), width="stretch")
        with cR:
            figc = go.Figure()
            figc.add_scatter(x=curve["years"], y=curve["cum_mmscf"],
                             name="Physics cumulative")
            if arps is not None:
                figc.add_scatter(x=arps["years"], y=arps["cum_mmscf"],
                                 name="Arps cumulative", line=dict(dash="dash"))
            figc.update_layout(title="Cumulative Production", xaxis_title="Years",
                               yaxis_title="Cumulative (MMscf)")
            st.plotly_chart(theme.style_fig(figc, height=320), width="stretch")
        theme.source_note(
            "bluebonnet 1-D scaling-solution forecast, scaled by movable gas in place "
            "(M) and time-to-BDF (τ); optional Arps overlay (Arps 1945). Rate Mscf/d, "
            "cumulative & EUR MMscf.")
        theme.references(["bluebonnet", "arps"])

    # ------------------------------------------------------------------- RTA
    with tab_rta:
        _pvt_mod, _curves_mod, rta_mod = core.wps_physics()
        pt.section("Fit The Physics Model To A Rate Series",
                   "Back out resource-in-place (M) and time-to-BDF (τ), then "
                   "forecast EUR.")
        source = st.radio("Rate Series",
                          ("Built-in synthetic series", "Upload a CSV (date, rate)"),
                          horizontal=True)
        series = None
        is_real = False
        if source == "Upload a CSV (date, rate)":
            up = st.file_uploader("CSV with a date column and a gas-rate column (Mscf/d)",
                                  type=["csv"])
            if up is not None:
                try:
                    series = rta_mod.parse_rate_csv(up)
                    is_real = True
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Could not parse CSV: {exc}")
            else:
                st.info("Upload a CSV, or switch to the built-in synthetic series. "
                        "Nothing is stored server-side.")
        else:
            series = rta_mod.synthetic_series()

        if is_real:
            theme.data_badge("real", "User-supplied rate series — RTA fit (bluebonnet).")
        else:
            theme.data_badge("synthetic",
                             "Built-in synthetic rate series at a known (M, τ) — the "
                             "fit should recover the truth.")

        if series is not None:
            horizon = st.slider("Forecast Horizon (years)", 3.0, 40.0, 15.0, 1.0,
                                key="rta_h")
            res = _fit_rta(series, horizon_years=float(horizon))
            pt.kpi_row([
                {"label": "Fitted M (resource)", "value": f"{res.m_mscf/1e3:,.0f} MMscf"},
                {"label": "Fitted τ (time-to-BDF)", "value": f"{res.tau_years:.2f} yr"},
                {"label": "Forecast EUR", "value": f"{res.eur_mmscf:,.0f} MMscf"},
                {"label": "Fit RMSE", "value": f"{res.rmse_mmscf:,.2f} MMscf"},
            ])
            figh = go.Figure()
            figh.add_scatter(x=res.history["years"], y=res.history["cum_mmscf"],
                             name="Observed cumulative", mode="markers",
                             marker=dict(size=4))
            figh.add_scatter(x=res.forecast["years"], y=res.forecast["cum_mmscf"],
                             name="Physics fit + forecast")
            figh.update_layout(title="RTA Cumulative Fit & Forecast",
                               xaxis_title="Years", yaxis_title="Cumulative (MMscf)")
            st.plotly_chart(theme.style_fig(figh, height=330), width="stretch")
            theme.source_note(
                "Rate-transient fit of bluebonnet's scaling solution; fitted M and EUR "
                "in MMscf, τ in years, RMSE on cumulative in MMscf.")
        theme.references(["bluebonnet"])
