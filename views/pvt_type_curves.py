"""Design → PVT & Type Curves — black-oil PVT, bluebonnet physics production
curves, and rate-transient analysis.

bluebonnet is imported LAZILY inside this view (via core.wps_physics) so the rest
of the workbench keeps working when the physics engine is unavailable — this page
then renders an empty state instead of crashing the product.

The PVT tab is anchored to the SELECTED well: its fluid inputs (oil API, gas SG,
solution GOR/Rs, reservoir temperature) are seeded from ``_common.design_seed_cached``
so the black-oil model describes the chosen well's fluid, not generic constants. The
physics-curve and RTA tabs are forward / uploaded-series tools — they are intentionally
independent of the selected well, and their captions say so to avoid implying the
curve is that well's history.
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


@st.cache_data(show_spinner=False, hash_funcs={"wps.pvt.PVTInputs": _hash_inputs})
def _props_at_pressure(inp, pressure: float) -> dict:
    """Single-pressure PVT properties (e.g. Bo at the bubble point). Cached so the
    headline 'Bo @ Pb' KPI never triggers an extra uncached fluid build on rerun —
    matching the caching discipline of _pvt_table / _bubble_point."""
    pvt, _curves, _rta = core.wps_physics()
    return pvt.props_at_pressure(inp, float(pressure))


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


@st.cache_data(show_spinner=False)
def _synthetic_series():
    """The built-in RTA demo series — a ~6 s bluebonnet reservoir solve. It is
    deterministic (fixed seed), so cache it: otherwise every rerun (any slider drag
    or global sidebar change) re-ran the full solve on the RTA tab (perf #0). Combined
    with the cached _fit_rta, the default RTA path solves once then is near-instant."""
    _pvt, _curves, rta = core.wps_physics()
    return rta.synthetic_series()


# Slider bounds, declared once so the per-well seed can be clamped into range before it
# is written to session_state (a seed outside the slider's [min,max] raises in Streamlit).
_API_MIN, _API_MAX = 15.0, 55.0
_SG_MIN, _SG_MAX = 0.55, 1.10
_GOR_MIN, _GOR_MAX = 100.0, 3000.0
_TEMP_MIN, _TEMP_MAX = 120.0, 320.0


def _clamp(v: float, lo: float, hi: float) -> float:
    return float(min(max(float(v), lo), hi))


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

    wid = _common.current_well()
    seed = _common.design_seed_cached(wid)

    tab_pvt, tab_curve, tab_rta = st.tabs(
        ["PVT Properties", "Physics Production Curve", "Rate-Transient Analysis"])

    # ------------------------------------------------------------------ PVT
    with tab_pvt:
        pvt_mod, _curves_mod, rta_mod = core.wps_physics()
        # This tab IS the selected well's fluid — provenance reflects the chosen well.
        theme.data_badge(
            "real" if seed.source == "real" else "synthetic",
            f"Black-oil PVT (bluebonnet) seeded from {seed.well_id} · {seed.name} "
            f"({seed.formation}). Edit any input to run a what-if.")

        pt.section("Fluid Properties Vs. Pressure",
                   "Standing oil FVF/Rs/viscosity; Dranchuk–Abou-Kassem gas z-factor "
                   "with Sutton pseudo-criticals; McCain water properties.")

        # --- seed the four fluid inputs from the selected well's design seed ---------
        # Set the key-backed value BEFORE the widget instantiates, gated on a per-well
        # sentinel, so changing the well re-seeds without the "cannot set a widget value
        # after instantiation" error. After seeding the user can edit freely.
        api_seed = _clamp(seed.oil_api, _API_MIN, _API_MAX)
        sg_seed = _clamp(seed.gas_sg, _SG_MIN, _SG_MAX)
        gor_seed = _clamp(seed.gor_scf_stb, _GOR_MIN, _GOR_MAX)
        temp_seed = _clamp(seed.temp_bottom_f, _TEMP_MIN, _TEMP_MAX)
        if st.session_state.get("pvt_seeded_well") != wid:
            st.session_state["pvt_api"] = api_seed
            st.session_state["pvt_sg"] = sg_seed
            st.session_state["pvt_gor"] = gor_seed
            st.session_state["pvt_temp"] = temp_seed
            st.session_state["pvt_seeded_well"] = wid

        prov = seed.provenance
        st.caption(
            f"Inputs seeded from **{seed.well_id} · {seed.name}** "
            f"({'real — Colorado ECMC' if seed.source == 'real' else 'synthetic fleet'}): "
            f"oil API {api_seed:.0f}° ({prov.get('oil_api', 'assumed')}), "
            f"gas SG {sg_seed:.2f} ({prov.get('gas_sg', 'assumed')}), "
            f"Rs {gor_seed:,.0f} scf/STB ({prov.get('gor_scf_stb', 'derived')}), "
            f"BHT {temp_seed:.0f}°F ({prov.get('temp_bottom_f', 'derived')}). "
            "Editable — measured > derived > assumed; see the well's Case File for the "
            "full provenance map.")

        c1, c2, c3 = st.columns(3)
        with c1:
            api = st.slider("Oil Gravity (°API)", _API_MIN, _API_MAX, step=0.5,
                            key="pvt_api")
            sg = st.slider("Gas Specific Gravity (air=1)", _SG_MIN, _SG_MAX, step=0.01,
                           key="pvt_sg")
        with c2:
            gor = st.slider("Solution GOR, Rs (scf/STB)", _GOR_MIN, _GOR_MAX, step=50.0,
                            key="pvt_gor")
            temp = st.slider("Reservoir Temperature (°F)", _TEMP_MIN, _TEMP_MAX,
                             step=5.0, key="pvt_temp")
        with c3:
            p_lo, p_hi = st.slider("Pressure Range (psia)", 200, 10000, (500, 6000), 100,
                                   key="pvt_prange")
            dryness = st.selectbox("Gas Dryness", ("wet gas", "dry gas"), index=0,
                                   key="pvt_dry")

        pvt_in = pvt_mod.PVTInputs(
            api_gravity=api, gas_specific_gravity=sg, solution_gor=gor,
            temperature=temp, pressure_min=float(p_lo), pressure_max=float(p_hi),
            n_points=48, gas_dryness=dryness)
        df = _pvt_table(pvt_in)
        pb = _bubble_point(pvt_in)

        # Bo at the bubble point (Bob) is the canonical reservoir-engineering reference;
        # above Pb the undersaturated oil compresses and Bo DECLINES, so the last-row
        # value at Pmax is neither the max nor the standard reference. Report both,
        # each labelled with the pressure it is quoted at.
        bob = float(_props_at_pressure(pvt_in, pb)["Bo"])
        bo_pmax = float(df["Bo"].iloc[-1])
        rs_bob = gor  # at/above Pb the oil is saturated at the initial solution Rs
        pt.kpi_row([
            {"label": "Bubble Point (Pb)", "value": f"{pb:,.0f} psia",
             "help": "Standing correlation at the seeded Rs / API / SG / temperature."},
            {"label": "Bo @ Pb (Bob)", "value": f"{bob:.3f} rb/stb",
             "help": f"Oil FVF at the bubble point ({pb:,.0f} psia) — the conventional "
                     f"reference Bo, at the initial solution Rs of {rs_bob:,.0f} scf/STB."},
            {"label": f"Bo @ Pmax ({p_hi:,} psia)", "value": f"{bo_pmax:.3f} rb/stb",
             "help": "Undersaturated oil FVF at the top of the chosen pressure range — "
                     "lower than Bob because the oil compresses above the bubble point."},
            {"label": "Oil μ @ Pmin", "value": f"{df['oil_viscosity'].iloc[0]:.3f} cP",
             "help": f"Live-oil viscosity (Standing) at {p_lo:,} psia."},
        ])

        cL, cR = st.columns(2)
        with cL:
            fig = go.Figure()
            fig.add_scatter(x=df["pressure"], y=df["Bo"], name="Bo (oil FVF, rb/stb)",
                            line=dict(color=theme.BLUE))
            fig.add_scatter(x=df["pressure"], y=df["Bw"], name="Bw (water FVF, rb/stb)",
                            line=dict(color=theme.TEAL))
            if p_lo <= pb <= p_hi:
                fig.add_vline(x=pb, line_dash="dot", line_color=theme.AMBER)
                # annotate the bubble-point peak so the Bo rollover reads clearly
                fig.add_scatter(x=[pb], y=[bob], mode="markers+text",
                                marker=dict(color=theme.AMBER, size=9, symbol="diamond"),
                                text=[f"Bob {bob:.3f} @ Pb"], textposition="top center",
                                name="Bob (at bubble point)")
            fig.update_layout(title="Formation Volume Factors",
                              xaxis_title="Pressure (psia)", yaxis_title="FVF (rb/stb)")
            st.plotly_chart(theme.style_fig(fig, height=300), width="stretch")
        with cR:
            figv = go.Figure()
            figv.add_scatter(x=df["pressure"], y=df["oil_viscosity"], name="μ_oil (cP)",
                             line=dict(color=theme.BLUE))
            figv.add_scatter(x=df["pressure"], y=df["water_viscosity"],
                             name="μ_water (cP)", line=dict(color=theme.TEAL))
            figv.update_layout(title="Oil & Water Viscosity",
                               xaxis_title="Pressure (psia)", yaxis_title="Viscosity (cP)")
            st.plotly_chart(theme.style_fig(figv, height=300), width="stretch")

        # --- gas PVT: Bg (gas FVF) and gas viscosity were computed but never shown ---
        cZ, cG = st.columns(2)
        with cZ:
            figz = go.Figure()
            figz.add_scatter(x=df["pressure"], y=df["z_factor"], name="z-factor",
                             line=dict(color=theme.PURPLE))
            figz.update_layout(title="Gas Z-Factor (Dranchuk–Abou-Kassem)",
                               xaxis_title="Pressure (psia)", yaxis_title="z (-)")
            st.plotly_chart(theme.style_fig(figz, height=280), width="stretch")
        with cG:
            # Bg (gas FVF, rcf/scf) and gas viscosity (cP) on twin axes — both are in
            # the PVT table the engine returns and a PE expects to see them on a
            # black-oil/gas lens.
            figg = go.Figure()
            figg.add_scatter(x=df["pressure"], y=df["Bg"], name="Bg (gas FVF, rcf/scf)",
                             line=dict(color=theme.GREEN), yaxis="y1")
            figg.add_scatter(x=df["pressure"], y=df["gas_viscosity"],
                             name="μ_gas (cP)", line=dict(color=theme.AMBER, dash="dot"),
                             yaxis="y2")
            figg.update_layout(
                title="Gas FVF (Bg) & Gas Viscosity",
                xaxis_title="Pressure (psia)",
                yaxis=dict(title="Bg (rcf/scf)"),
                yaxis2=dict(title="μ_gas (cP)", overlaying="y", side="right",
                            showgrid=False))
            st.plotly_chart(theme.style_fig(figg, height=280), width="stretch")

        # Downloadable PVT table — PEs export PVT into nodal/sim tools.
        show_cols = ["pressure", "Bo", "oil_viscosity", "Bg", "gas_viscosity",
                     "z_factor", "Bw", "water_viscosity"]
        st.download_button(
            "Download PVT Table (CSV)",
            data=df[show_cols].to_csv(index=False),
            file_name=f"pvt_{seed.well_id}.csv", mime="text/csv",
            key="pvt_dl")

        theme.source_note(
            f"Black-oil & gas PVT for {seed.well_id} via bluebonnet: oil Bo/Rs/viscosity "
            "by Standing; gas z-factor by Dranchuk–Abou-Kassem with Sutton "
            "pseudo-criticals (Bg & μ_gas from the same gas model); water by McCain. "
            "Pressure psia; FVF rb/stb (Bg rcf/scf); viscosity cP; Rs scf/STB. Inputs "
            "seeded from the selected well, then editable.")
        theme.references(["pvt", "bluebonnet"])

    # ----------------------------------------------------- physics production curve
    with tab_curve:
        _pvt_mod, curves_mod, _ = core.wps_physics()
        theme.data_badge(
            "synthetic",
            "Forward what-if forecast on the inputs below — a general gas-well "
            "scaling solution, NOT a fit to the selected well's history.")
        pt.section("Scaling-Solution Forecast",
                   "1-D pseudopressure-diffusion solve scaled by movable gas in "
                   "place (M) and time-to-BDF (τ); optional Arps overlay. Independent "
                   "of the selected well — set the inputs for the case you want.")
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
        recovery = (eur / float(c_res) * 100.0) if c_res else 0.0

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
             "help": f"≈ {eur/1000:,.2f} Bcf over the {c_yrs:,.0f}-year horizon"},
            {"label": "Recovery Factor", "value": f"{recovery:,.0f}%",
             "help": "EUR ÷ movable gas in place (M) over the horizon."},
            {"label": "Peak Rate", "value": f"{curve['rate_mscf_d'].max():,.0f} Mscf/d"},
            {"label": "Rate @ Horizon",
             "value": f"{curve['rate_mscf_d'].iloc[-1]:,.0f} Mscf/d"},
        ])

        cL, cR = st.columns(2)
        with cL:
            figr = go.Figure()
            figr.add_scatter(x=curve["years"], y=curve["rate_mscf_d"],
                             name="Physics (bluebonnet)", line=dict(color=theme.BLUE))
            if arps is not None:
                figr.add_scatter(x=arps["years"], y=arps["rate_mscf_d"],
                                 name="Arps overlay",
                                 line=dict(dash="dash", color=theme.AMBER))
            figr.update_layout(title="Gas Rate Vs. Time", xaxis_title="Years",
                               yaxis_title="Rate (Mscf/d)")
            st.plotly_chart(theme.style_fig(figr, height=320), width="stretch")
        with cR:
            figc = go.Figure()
            figc.add_scatter(x=curve["years"], y=curve["cum_mmscf"],
                             name="Physics cumulative", line=dict(color=theme.BLUE))
            if arps is not None:
                figc.add_scatter(x=arps["years"], y=arps["cum_mmscf"],
                                 name="Arps cumulative",
                                 line=dict(dash="dash", color=theme.AMBER))
            figc.update_layout(title="Cumulative Production", xaxis_title="Years",
                               yaxis_title="Cumulative (MMscf)")
            st.plotly_chart(theme.style_fig(figc, height=320), width="stretch")
        theme.source_note(
            "bluebonnet 1-D scaling-solution forecast, scaled by movable gas in place "
            "(M) and time-to-BDF (τ); optional Arps overlay (Arps 1945). Rate Mscf/d, "
            "cumulative & EUR MMscf. A forward what-if, not the selected well's history.")
        theme.references(["bluebonnet", "arps"])

    # ------------------------------------------------------------------- RTA
    with tab_rta:
        _pvt_mod, _curves_mod, rta_mod = core.wps_physics()
        pt.section("Fit The Physics Model To A Rate Series",
                   "Back out resource-in-place (M) and time-to-BDF (τ), then "
                   "forecast EUR. Fits the chosen series below — not automatically the "
                   "selected well.")
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
            series = _synthetic_series()

        # ONE provenance badge on this tab, reflecting the chosen series only (no longer
        # a second, page-level amber badge that contradicts a real-CSV upload).
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
                             marker=dict(size=4, color=theme.GREY))
            figh.add_scatter(x=res.forecast["years"], y=res.forecast["cum_mmscf"],
                             name="Physics fit + forecast", line=dict(color=theme.BLUE))
            figh.update_layout(title="RTA Cumulative Fit & Forecast",
                               xaxis_title="Years", yaxis_title="Cumulative (MMscf)")
            st.plotly_chart(theme.style_fig(figh, height=330), width="stretch")
            theme.source_note(
                "Rate-transient fit of bluebonnet's scaling solution; fitted M and EUR "
                "in MMscf, τ in years, RMSE on cumulative in MMscf.")
        theme.references(["bluebonnet"])
