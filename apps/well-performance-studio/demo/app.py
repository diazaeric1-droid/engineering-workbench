"""Well Performance Studio — the suite's forward-modeling "Design" app.

PVT, physics-based production curves, rate-transient analysis (RTA), nodal (systems)
analysis, and artificial-lift design for oil & gas wells. The PVT/curve/RTA tabs are
powered by the ``bluebonnet`` physics engine; the Nodal and Artificial-Lift tabs use
self-contained standard petroleum correlations (Vogel, Hagedorn–Brown, Beggs–Brill, ESP
affinity laws) in pure numpy/scipy. Everything is deterministic and runs with ZERO API
key; the LLM narrative is BYOK-optional.

Built by an ex-OXY / ex-Shell Staff Production Engineer.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Make both this file's dir (for the vendored `theme`) and the repo root (for `src`)
# importable, regardless of launch CWD. `streamlit run` adds the script dir to sys.path,
# but AppTest.from_file does not — so add both explicitly.
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)
for _p in (_HERE, _REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# --- warm-container module self-heal (vendored top-level modules) -----------
# Streamlit Cloud reuses the container across redeploys; a cached OLD `theme` /
# `fleet_registry` in sys.modules (or a stale .pyc) lacks symbols added in a newer
# commit -> AttributeError (e.g. theme.how_to). Drop their bytecode + evict the cached
# modules so the imports below reload from the CURRENT commit's source.
import shutil as _sh_heal
_sh_heal.rmtree(os.path.join(_HERE, "__pycache__"), ignore_errors=True)
for _stale in ("theme", "fleet_registry"):
    sys.modules.pop(_stale, None)

import dataclasses

import theme  # vendored, next to this file
from src import __version__
from src.curves import CurveInputs, arps_overlay
from src.curves import production_curve as _production_curve
from src.lift import design_esp, gas_lift_sweep
from src.nodal import (
    VLPInputs,
    operating_point,
    straight_line_ipr,
    vogel_ipr,
)
from src.nodal import vlp_curve as _vlp_curve
from src.pvt import PVTInputs
from src.pvt import bubble_point as _bubble_point
from src.pvt import props_at_pressure as _props_at_pressure
from src.pvt import pvt_table as _pvt_table
from src.rta import fit_rta as _fit_rta
from src.rta import parse_rate_csv, synthetic_series

# --------------------------------------------------------------------------- caching
# The expensive deterministic computations (bluebonnet PVT/curve/RTA builds and the
# multiphase VLP pressure march) recompute on every Streamlit rerun — e.g. each slider
# nudge. Wrap them in `st.cache_data` so identical inputs are served from cache.
#
# The input dataclasses (PVTInputs, CurveInputs, VLPInputs) are NOT hashable (default
# @dataclass sets __hash__ = None), and the RTA input is a mutable DataFrame, so Streamlit
# cannot key on them directly. We register `hash_funcs` that map each input type to a
# hashable, value-based representation (dataclasses.astuple / a pandas content hash) so the
# cache key tracks the ACTUAL input values — never object identity or a mutable arg. The
# wrapped functions are pure (deterministic, no I/O), so results are identical to uncached.
def _hash_inputs(obj) -> tuple:
    """Value-based hash key for the (frozen-in-spirit) input dataclasses."""
    return dataclasses.astuple(obj)


def _hash_series(df: pd.DataFrame) -> bytes:
    """Content hash for a rate-series DataFrame (so identical data -> cache hit)."""
    return pd.util.hash_pandas_object(df, index=True).values.tobytes()


@st.cache_data(show_spinner=False, hash_funcs={PVTInputs: _hash_inputs})
def pvt_table(inp: PVTInputs) -> pd.DataFrame:
    return _pvt_table(inp)


@st.cache_data(show_spinner=False, hash_funcs={PVTInputs: _hash_inputs})
def bubble_point(inp: PVTInputs) -> float:
    return _bubble_point(inp)


@st.cache_data(show_spinner=False, hash_funcs={PVTInputs: _hash_inputs})
def props_at_pressure(inp: PVTInputs, pressure: float) -> dict:
    return _props_at_pressure(inp, pressure)


@st.cache_data(show_spinner=False, hash_funcs={CurveInputs: _hash_inputs})
def production_curve(inp: CurveInputs) -> pd.DataFrame:
    return _production_curve(inp)


@st.cache_data(show_spinner=False, hash_funcs={VLPInputs: _hash_inputs})
def vlp_curve(inp: VLPInputs, q_max: float = 4000.0, n: int = 28):
    return _vlp_curve(inp, q_max=q_max, n=n)


@st.cache_data(show_spinner=False, hash_funcs={pd.DataFrame: _hash_series})
def fit_rta(series: pd.DataFrame, horizon_years: float = 15.0):
    return _fit_rta(series, horizon_years=horizon_years)


theme.setup_page("Well Performance Studio", icon="🧪")
theme.suite_nav("wps")
theme.header(
    "Well Performance Studio",
    subtitle=(
        "Forward well-performance modeling — PVT, physics-based production curves, "
        "and rate-transient analysis (bluebonnet). Built by an ex-OXY/ex-Shell Staff PE."
    ),
    chips=[(f"v{__version__}", "ver"), ("physics: bluebonnet", "info")],
)


# ----------------------------------------------------------------------------- sidebar
def _byok_sidebar() -> str | None:
    """Optional Anthropic key for the LLM narrative. Never stored. Deterministic w/o it."""
    st.sidebar.markdown("---")
    st.sidebar.markdown("**LLM narrative (optional, BYOK)**")
    key = st.sidebar.text_input(
        "Anthropic API key",
        type="password",
        help=(
            "Bring your own key for an optional plain-English summary. Never stored; "
            "used only for this session. Every chart and number is computed "
            "deterministically by bluebonnet with no key."
        ),
        placeholder="sk-ant-...",
    )
    return key.strip() or os.environ.get("ANTHROPIC_API_KEY") or None


def _maybe_narrate(api_key: str | None, prompt: str, label: str = "AI summary") -> None:
    """Render an optional Claude narrative if a key is present. Silent no-op otherwise."""
    if not api_key:
        return
    if not st.button(f"📝 {label} (uses your key)"):
        return
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-3-5-haiku-latest",
            max_tokens=350,
            messages=[{"role": "user", "content": prompt}],
        )
        st.info("".join(b.text for b in msg.content if getattr(b, "type", "") == "text"))
    except Exception as exc:  # pragma: no cover - network/credential dependent
        st.warning(f"LLM narrative unavailable: {exc}")


# data-provenance badge (synthetic by default; RTA flips to real on upload)
theme.data_badge(
    "synthetic",
    "Physics-modeled (bluebonnet) on illustrative reservoir/fluid inputs — not "
    "real-well data. RTA can ingest a real rate series.",
)

theme.how_to(
    "- **PVT** — set fluid inputs (oil °API, gas SG, solution GOR, temperature, "
    "pressure range) to chart Bo, Rs, viscosity, and z-factor vs. pressure.\n"
    "- **Physics Production Curve** — set reservoir/fluid/completion inputs (initial & "
    "flowing pressure, movable gas in place, τ) for a bluebonnet rate-time & cumulative "
    "forecast + EUR, with an optional Arps overlay.\n"
    "- **RTA** — load a rate series (synthetic or your own CSV) to fit the physics model "
    "and back out resource-in-place (M) and time-to-BDF (τ), then forecast EUR.\n"
    "- **Nodal** — set reservoir, tubing, and fluid inputs; the operating point is where "
    "the IPR (inflow) meets the VLP (outflow).\n"
    "- **Artificial Lift** — set a target rate the well can't reach naturally to size an "
    "ESP (stages, frequency, TDH, power) and sweep gas-lift injection."
)

with st.expander("What Is This?"):
    st.markdown(
        """
**Well Performance Studio** is the *Design* (forward-modeling) app of the Upstream
Copilot Suite. Where the other apps *diagnose* and *monitor* existing wells, this one
**predicts** how a well should behave from first-principles reservoir physics.

It wraps **[bluebonnet](https://pypi.org/project/bluebonnet/)** — an open-source
PVT + scaling-solution + rate-transient library for unconventional (shale / tight)
wells:

- **PVT** — black-oil & gas fluid properties (Standing, Dranchuk–Abou-Kassem, Sutton)
  vs. pressure: oil/gas/water FVF, viscosities, z-factor, density.
- **Physics production curve** — bluebonnet's 1-D scaling-solution reservoir simulator
  turns reservoir/fluid/completion inputs into a rate–time and cumulative profile +
  EUR (with an optional empirical Arps overlay).
- **RTA** — fits the physics model to a measured (or synthetic) rate stream to back out
  the resource-in-place and time-to-boundary-dominated-flow, then forecasts EUR.

Everything is **deterministic** and needs **no API key**. An optional Claude narrative
(bring-your-own-key) just translates the numbers into plain English.
        """
    )

_api_key = _byok_sidebar()

tab_pvt, tab_curve, tab_rta, tab_nodal, tab_lift = st.tabs(
    ["PVT", "Physics Production Curve", "RTA", "Nodal", "Artificial Lift"]
)

# ============================================================================ PVT tab
with tab_pvt:
    st.subheader("PVT — Fluid Properties vs. Pressure")
    theme.how_to(
        "- Black-oil & gas fluid properties vs. pressure from standard correlations.\n"
        "- Set the oil gravity (°API), gas specific gravity, solution GOR (Rs), reservoir "
        "temperature, pressure range, and gas dryness in the controls below.\n"
        "- Charts give the oil/water/gas FVF, viscosities, and z-factor; the bubble point "
        "is marked, and the table reports every property at a pressure you pick."
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        api = st.slider("Oil gravity (°API)", 15.0, 55.0, 38.0, 0.5)
        sg = st.slider("Gas specific gravity (air=1)", 0.55, 1.10, 0.75, 0.01)
    with c2:
        gor = st.slider("Solution GOR, Rs (scf/bbl)", 100.0, 3000.0, 900.0, 50.0)
        temp = st.slider("Reservoir temperature (°F)", 120.0, 320.0, 210.0, 5.0)
    with c3:
        p_lo, p_hi = st.slider(
            "Pressure range (psia)", 200, 10000, (500, 6000), 100
        )
        dryness = st.selectbox("Gas dryness", ("wet gas", "dry gas"), index=0)

    pvt_in = PVTInputs(
        api_gravity=api,
        gas_specific_gravity=sg,
        solution_gor=gor,
        temperature=temp,
        pressure_min=float(p_lo),
        pressure_max=float(p_hi),
        n_points=48,
        gas_dryness=dryness,
    )
    df = pvt_table(pvt_in)
    pb = bubble_point(pvt_in)

    k1, k2, k3 = st.columns(3)
    k1.metric("Bubble point", f"{pb:,.0f} psia")
    k2.metric("Bo @ Pmax", f"{df['Bo'].iloc[-1]:.3f} rb/stb")
    k3.metric("μ_oil @ Pmin", f"{df['oil_viscosity'].iloc[0]:.3f} cP")

    # FVF + viscosity figures
    cL, cR = st.columns(2)
    with cL:
        fig = go.Figure()
        fig.add_scatter(x=df["pressure"], y=df["Bo"], name="Bo (oil FVF, rb/stb)")
        fig.add_scatter(
            x=df["pressure"], y=df["Bw"], name="Bw (water FVF, rb/stb)", yaxis="y"
        )
        if pb >= p_lo and pb <= p_hi:
            fig.add_vline(x=pb, line_dash="dot", line_color=theme.AMBER)
        fig.update_layout(
            title="Formation Volume Factors", xaxis_title="Pressure (psia)",
            yaxis_title="FVF (rb/stb)",
        )
        st.plotly_chart(theme.style_fig(fig, height=320), width="stretch")

        figz = go.Figure()
        figz.add_scatter(x=df["pressure"], y=df["z_factor"], name="z-factor")
        figz.update_layout(
            title="Gas Z-Factor (DAK)", xaxis_title="Pressure (psia)",
            yaxis_title="z (-)",
        )
        st.plotly_chart(theme.style_fig(figz, height=300), width="stretch")
    with cR:
        figv = go.Figure()
        figv.add_scatter(
            x=df["pressure"], y=df["oil_viscosity"], name="μ_oil (cP)"
        )
        figv.add_scatter(
            x=df["pressure"], y=df["water_viscosity"], name="μ_water (cP)"
        )
        figv.update_layout(
            title="Oil & Water Viscosity", xaxis_title="Pressure (psia)",
            yaxis_title="Viscosity (cP)",
        )
        st.plotly_chart(theme.style_fig(figv, height=320), width="stretch")

        figg = go.Figure()
        figg.add_scatter(x=df["pressure"], y=df["gas_viscosity"], name="μ_gas (cP)")
        figg.add_scatter(
            x=df["pressure"], y=df["Bg"], name="Bg (gas FVF, rcf/scf)", yaxis="y2"
        )
        figg.update_layout(
            title="Gas Viscosity & FVF", xaxis_title="Pressure (psia)",
            yaxis_title="μ_gas (cP)",
            yaxis2=dict(title="Bg (rcf/scf)", overlaying="y", side="right"),
        )
        st.plotly_chart(theme.style_fig(figg, height=300), width="stretch")

    st.markdown("**Properties at a Chosen Pressure**")
    p_at = st.slider(
        "Evaluate at pressure (psia)", int(p_lo), int(p_hi),
        int((p_lo + p_hi) / 2), 50,
    )
    props = props_at_pressure(pvt_in, p_at)
    prop_df = pd.DataFrame(
        {
            "Property": [
                "Pressure (psia)", "Bo (rb/stb)", "μ_oil (cP)", "Bg (rcf/scf)",
                "μ_gas (cP)", "z-factor (-)", "Bw (rb/stb)", "μ_water (cP)",
            ],
            "Value": [
                props["pressure"], props["Bo"], props["oil_viscosity"], props["Bg"],
                props["gas_viscosity"], props["z_factor"], props["Bw"],
                props["water_viscosity"],
            ],
        }
    )
    st.dataframe(
        prop_df.style.format({"Value": "{:,.4f}"}),
        width="stretch", hide_index=True,
    )
    theme.source_note(
        "Black-oil & gas PVT correlations (Standing; Vázquez–Beggs; Dranchuk–Abou-Kassem "
        "z-factor) via bluebonnet. Pressure in psia; FVF in rb/stb (Bg in rcf/scf); "
        "viscosity in cP; Rs in scf/bbl."
    )

    _maybe_narrate(
        _api_key,
        f"In 4 sentences, interpret these PVT properties for a production engineer. "
        f"Oil {api} API, gas SG {sg}, Rs {gor} scf/bbl, T {temp} F, bubble point "
        f"{pb:.0f} psia. At {p_at} psia: Bo={props['Bo']:.3f}, mu_oil="
        f"{props['oil_viscosity']:.3f} cP, z={props['z_factor']:.3f}.",
        "Interpret PVT",
    )

    theme.references(["pvt", "bluebonnet"])

# ============================================================ Physics production curve
with tab_curve:
    st.subheader("Physics Production Curve — bluebonnet Scaling Solution")
    st.caption(
        "1-D pseudopressure-diffusion solve for a fracture-dominated gas well. The "
        "dimensionless recovery curve is scaled to a real well by the movable gas in "
        "place (M) and time-to-boundary-dominated-flow (τ)."
    )
    theme.how_to(
        "- A first-principles rate-time & cumulative forecast from bluebonnet's scaling "
        "solution — no decline fit required.\n"
        "- Set the fluid (gas SG, temperature, dryness), initial & flowing-BHP pressures, "
        "movable gas in place, time-to-BDF (τ), and forecast horizon below.\n"
        "- Read off EUR, peak rate, and rate at horizon; optionally overlay an empirical "
        "Arps decline to compare the physics curve against a classic decline."
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        c_sg = st.slider("Gas specific gravity", 0.55, 1.00, 0.70, 0.01, key="c_sg")
        c_temp = st.slider("Reservoir temp (°F)", 120.0, 320.0, 230.0, 5.0, key="c_t")
        c_dry = st.selectbox(
            "Gas dryness", ("dry gas", "wet gas"), index=0, key="c_dry"
        )
    with c2:
        c_pi = st.slider("Initial pressure (psia)", 2000, 10000, 6500, 100)
        c_pf = st.slider("Flowing BHP / frac-face (psia)", 200, 4000, 1200, 50)
    with c3:
        c_res = st.slider("Movable gas in place (MMscf)", 200, 12000, 4000, 100)
        c_tau = st.slider("Time-to-BDF, τ (years)", 0.3, 12.0, 3.0, 0.1)
        c_yrs = st.slider("Forecast horizon (years)", 2.0, 40.0, 20.0, 1.0)

    if c_pf >= c_pi:
        st.warning("Flowing pressure should be below initial reservoir pressure.")

    curve_in = CurveInputs(
        gas_specific_gravity=c_sg,
        temperature=c_temp,
        gas_dryness=c_dry,
        pressure_initial=float(c_pi),
        pressure_fracface=float(min(c_pf, c_pi - 50)),
        resource_mmscf=float(c_res),
        tau_years=float(c_tau),
        years=float(c_yrs),
    )
    curve = production_curve(curve_in)
    eur = float(curve["cum_mmscf"].iloc[-1])

    show_arps = st.checkbox("Overlay empirical Arps decline", value=False)
    arps = None
    if show_arps:
        a1, a2, a3 = st.columns(3)
        qi = a1.number_input(
            "Arps qi (Mscf/d)", 100.0, 1e5,
            float(max(curve["rate_mscf_d"].iloc[1], 1000.0)), 100.0,
        )
        di = a2.slider("Arps Di (1/yr)", 0.05, 2.5, 0.7, 0.05)
        bexp = a3.slider("Arps b", 0.0, 1.5, 1.0, 0.1)
        arps = arps_overlay(qi, di, bexp, c_yrs)

    k1, k2, k3 = st.columns(3)
    k1.metric("EUR (physics)", f"{eur:,.0f} MMscf")
    k1.caption(f"≈ {eur/1000:,.2f} Bcf")
    k2.metric("Peak rate", f"{curve['rate_mscf_d'].max():,.0f} Mscf/d")
    k3.metric("Rate @ horizon", f"{curve['rate_mscf_d'].iloc[-1]:,.0f} Mscf/d")

    cL, cR = st.columns(2)
    with cL:
        figr = go.Figure()
        figr.add_scatter(
            x=curve["years"], y=curve["rate_mscf_d"], name="Physics (bluebonnet)"
        )
        if arps is not None:
            figr.add_scatter(
                x=arps["years"], y=arps["rate_mscf_d"], name="Arps overlay",
                line=dict(dash="dash"),
            )
        figr.update_layout(
            title="Gas Rate vs. Time", xaxis_title="Years",
            yaxis_title="Rate (Mscf/d)",
        )
        st.plotly_chart(theme.style_fig(figr, height=340), width="stretch")
    with cR:
        figc = go.Figure()
        figc.add_scatter(
            x=curve["years"], y=curve["cum_mmscf"], name="Physics cumulative"
        )
        if arps is not None:
            figc.add_scatter(
                x=arps["years"], y=arps["cum_mmscf"], name="Arps cumulative",
                line=dict(dash="dash"),
            )
        figc.update_layout(
            title="Cumulative Production", xaxis_title="Years",
            yaxis_title="Cumulative (MMscf)",
        )
        st.plotly_chart(theme.style_fig(figc, height=340), width="stretch")

    theme.source_note(
        "bluebonnet 1-D scaling-solution forecast, scaled by movable gas in place (M) and "
        "time-to-BDF (τ); optional Arps overlay (Arps 1945). Rate in Mscf/d, cumulative & "
        "EUR in MMscf, time in years."
    )

    _maybe_narrate(
        _api_key,
        f"In 3-4 sentences, summarize this physics forecast for a gas well: initial "
        f"pressure {c_pi} psia, flowing BHP {c_pf} psia, movable gas {c_res} MMscf, "
        f"tau {c_tau} yr. Peak rate {curve['rate_mscf_d'].max():,.0f} Mscf/d, "
        f"{c_yrs:.0f}-yr EUR {eur:,.0f} MMscf.",
        "Interpret curve",
    )

    theme.references(["bluebonnet"])

# ============================================================================ RTA tab
with tab_rta:
    st.subheader("Rate-Transient Analysis — Fit the Physics Model to a Rate Series")
    st.caption(
        "Fit bluebonnet's scaling-solution forecaster to a daily rate stream to back "
        "out the resource-in-place (M) and time-to-BDF (τ), then forecast EUR."
    )
    theme.how_to(
        "- Inverts the physics curve: fit bluebonnet to a measured rate stream to estimate "
        "resource-in-place (M) and time-to-BDF (τ), then forecast EUR.\n"
        "- Pick the built-in synthetic series (known truth — the fit should recover it) or "
        "upload your own CSV with a date column and a gas-rate column (Mscf/d).\n"
        "- Set the forecast horizon; review the fitted M, τ, EUR, and fit RMSE plus the "
        "cumulative- and rate-fit charts."
    )

    source = st.radio(
        "Rate series",
        ("Built-in synthetic series", "Upload a CSV (date, rate)"),
        horizontal=True,
    )

    series = None
    is_real = False
    if source == "Upload a CSV (date, rate)":
        up = st.file_uploader(
            "CSV with a date column and a gas-rate column (Mscf/d)", type=["csv"]
        )
        if up is not None:
            try:
                series = parse_rate_csv(up)
                is_real = True
            except Exception as exc:
                st.error(f"Could not parse CSV: {exc}")
        else:
            st.info("Upload a CSV, or switch to the built-in synthetic series.")
    else:
        series = synthetic_series()

    # provenance badge specific to this tab
    if is_real:
        theme.data_badge(
            "real", "User-supplied rate series — RTA fit (bluebonnet)."
        )
    else:
        theme.data_badge(
            "synthetic",
            "Built-in synthetic rate series at a known (M, τ) — the fit should "
            "recover the truth.",
        )

    if series is not None:
        horizon = st.slider("Forecast horizon (years)", 3.0, 40.0, 15.0, 1.0, key="rta_h")
        res = fit_rta(series, horizon_years=float(horizon))

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Fitted M (resource)", f"{res.m_mscf/1e3:,.0f} MMscf")
        k2.metric("Fitted τ (time-to-BDF)", f"{res.tau_years:.2f} yr")
        k3.metric("Forecast EUR", f"{res.eur_mmscf:,.0f} MMscf")
        k4.metric("Fit RMSE", f"{res.rmse_mmscf:,.2f} MMscf")

        figh = go.Figure()
        figh.add_scatter(
            x=res.history["years"], y=res.history["cum_mmscf"],
            name="Observed cumulative", mode="markers",
            marker=dict(size=4),
        )
        figh.add_scatter(
            x=res.forecast["years"], y=res.forecast["cum_mmscf"],
            name="Physics fit + forecast",
        )
        figh.update_layout(
            title="RTA Cumulative Fit & Forecast", xaxis_title="Years",
            yaxis_title="Cumulative (MMscf)",
        )
        st.plotly_chart(theme.style_fig(figh, height=340), width="stretch")

        # observed daily rate
        rate_obs = series.copy()
        figr = go.Figure()
        figr.add_scatter(
            x=(rate_obs["date"] - rate_obs["date"].iloc[0]).dt.days / 365.25,
            y=rate_obs["rate_mscf_d"], name="Observed rate", mode="markers",
            marker=dict(size=3),
        )
        figr.add_scatter(
            x=res.forecast["years"], y=res.forecast["rate_mscf_d"],
            name="Forecast rate",
        )
        figr.update_layout(
            title="Rate: Observed vs. Forecast", xaxis_title="Years",
            yaxis_title="Rate (Mscf/d)",
        )
        st.plotly_chart(theme.style_fig(figr, height=320), width="stretch")
        theme.source_note(
            "Rate-transient fit of bluebonnet's scaling solution to the rate series; "
            "fitted M and EUR in MMscf, τ in years, rate in Mscf/d, RMSE on cumulative "
            "in MMscf."
        )

        _maybe_narrate(
            _api_key,
            f"In 3-4 sentences, interpret this rate-transient analysis: fitted "
            f"resource M={res.m_mscf/1e3:,.0f} MMscf, time-to-BDF tau="
            f"{res.tau_years:.2f} yr, forecast EUR {res.eur_mmscf:,.0f} MMscf, "
            f"cumulative-fit RMSE {res.rmse_mmscf:.2f} MMscf "
            f"({'real uploaded' if is_real else 'synthetic'} series).",
            "Interpret RTA",
        )

    theme.references(["bluebonnet"])

# ========================================================================== Nodal tab
with tab_nodal:
    st.subheader("Nodal Analysis — IPR ∩ VLP Operating Point")
    st.caption(
        "Systems (nodal) analysis at the bottom-hole node. The IPR (what the reservoir "
        "delivers) is Vogel below the bubble point + a straight-line PI above; the VLP "
        "(what the tubing requires) is a multiphase pressure traverse (Hagedorn–Brown or "
        "Beggs–Brill). Their intersection is the well's operating point."
    )
    theme.data_badge(
        "synthetic",
        "Physics-modeled — standard nodal correlations (Vogel / Hagedorn-Brown / "
        "Beggs-Brill) on illustrative inputs.",
    )
    theme.how_to(
        "- Finds the well's natural operating point where inflow (IPR) meets outflow "
        "(VLP) at the bottom-hole node.\n"
        "- Set the reservoir (pressure, bubble point, IPR model & flow test or PI), the "
        "tubing (ID, depth, VLP correlation), and fluid (GLR, water cut, wellhead "
        "pressure) inputs.\n"
        "- Read the operating rate, operating BHP, and AOF; if the IPR and VLP don't "
        "intersect, the well needs artificial lift — see the Artificial Lift tab."
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        n_pres = st.slider("Reservoir pressure (psia)", 800, 8000, 3500, 50, key="n_pres")
        n_pb = st.slider("Bubble point (psia)", 200, 8000, 3500, 50, key="n_pb")
        n_ipr_mode = st.radio(
            "IPR model", ("Vogel (test point)", "Straight-line PI"),
            key="n_ipr_mode",
        )
    with c2:
        if n_ipr_mode == "Vogel (test point)":
            n_qtest = st.slider(
                "Flow-test rate (STB/d)", 50, 5000, 800, 25, key="n_qtest"
            )
            n_pwftest = st.slider(
                "Flow-test pwf (psia)", 100, int(n_pres),
                min(2500, int(n_pres) - 100), 25, key="n_pwftest",
            )
        else:
            n_j = st.slider(
                "Productivity index J (STB/d/psi)", 0.1, 10.0, 1.0, 0.1, key="n_j"
            )
        n_id = st.slider("Tubing ID (in.)", 1.0, 5.0, 2.441, 0.001, key="n_id")
        n_depth = st.slider("Tubing depth (ft)", 2000, 16000, 8000, 100, key="n_depth")
    with c3:
        n_glr = st.slider("Producing GLR (scf/STB)", 0, 3000, 400, 25, key="n_glr")
        n_wc = st.slider("Water cut (fraction)", 0.0, 0.99, 0.30, 0.01, key="n_wc")
        n_whp = st.slider("Wellhead pressure (psia)", 30, 1500, 150, 10, key="n_whp")
        n_corr = st.selectbox(
            "VLP correlation",
            ("hagedorn_brown", "beggs_brill"),
            format_func=lambda s: {"hagedorn_brown": "Hagedorn–Brown",
                                   "beggs_brill": "Beggs–Brill"}[s],
            key="n_corr",
        )

    if n_ipr_mode == "Vogel (test point)":
        if n_pwftest >= n_pres:
            st.warning("Flow-test pwf should be below reservoir pressure.")
        ipr = vogel_ipr(
            p_res=float(n_pres), pb=float(min(n_pb, n_pres)),
            q_test=float(n_qtest), pwf_test=float(min(n_pwftest, n_pres - 1)),
        )
    else:
        ipr = straight_line_ipr(p_res=float(n_pres), j=float(n_j))

    vlp_in = VLPInputs(
        tubing_id_in=float(n_id), depth_ft=float(n_depth),
        wellhead_pressure=float(n_whp), glr_scf_stb=float(n_glr),
        water_cut=float(n_wc), correlation=n_corr,
    )
    vlp = vlp_curve(vlp_in, q_max=float(ipr.aof) * 0.98, n=26)
    op = operating_point(ipr, vlp)

    k1, k2, k3 = st.columns(3)
    if op.converged:
        k1.metric("Operating rate q_op", f"{op.q_op:,.0f} STB/d")
        k2.metric("Operating pwf", f"{op.pwf_op:,.0f} psia")
    else:
        k1.metric("Operating rate q_op", "no flow")
        k2.metric("Operating pwf", "—")
    k3.metric("AOF (abs. open flow)", f"{ipr.aof:,.0f} STB/d")
    if not op.converged:
        theme.flag(
            "No IPR∩VLP intersection — the reservoir cannot lift this column "
            "(needs artificial lift). See the Artificial Lift tab.",
            "warn",
        )

    fig = go.Figure()
    fig.add_scatter(
        x=ipr.q, y=ipr.pwf, name="IPR (inflow — reservoir)",
        line=dict(color=theme.BLUE),
    )
    fig.add_scatter(
        x=vlp.q, y=vlp.pwf, name="VLP (outflow — tubing)",
        line=dict(color=theme.AMBER),
    )
    if op.converged:
        fig.add_scatter(
            x=[op.q_op], y=[op.pwf_op], name="Operating point", mode="markers",
            marker=dict(size=13, color=theme.GREEN, symbol="x",
                        line=dict(width=2)),
        )
    fig.update_layout(
        title="Nodal Plot — Pressure vs. Rate at the Bottom-Hole Node",
        xaxis_title="Liquid rate q (STB/d)", yaxis_title="Flowing BHP, pwf (psia)",
    )
    st.plotly_chart(theme.style_fig(fig, height=420), width="stretch")
    _nodal_df = pd.DataFrame({
        "rate_stb_d_ipr": ipr.q, "pwf_psia_ipr": ipr.pwf,
        "rate_stb_d_vlp": list(vlp.q) + [None] * max(0, len(ipr.q) - len(vlp.q)),
        "pwf_psia_vlp": list(vlp.pwf) + [None] * max(0, len(ipr.q) - len(vlp.q)),
    })
    st.download_button("⬇ Download results (CSV)", data=_nodal_df.to_csv(index=False),
                       file_name="wps_results.csv", mime="text/csv")
    st.caption(
        f"IPR: {'Vogel (below Pb) + linear PI (above)' if ipr.method == 'vogel' else 'straight-line PI'} "
        f"· VLP: {('Hagedorn–Brown' if n_corr == 'hagedorn_brown' else 'Beggs–Brill')} "
        "multiphase pressure traverse, segmented over the tubing. Correlations are "
        "standard textbook forms (Vogel 1968; Hagedorn–Brown 1965; Beggs–Brill 1973) on "
        "illustrative single-well inputs — not a tuned field match."
    )
    theme.source_note(
        "Operating point = intersection of the Vogel IPR (inflow) and Hagedorn-Brown / "
        "Beggs-Brill VLP (outflow); BHP in psia, liquid rate in STB/d."
    )

    _maybe_narrate(
        _api_key,
        f"In 3-4 sentences, interpret this nodal analysis for a production engineer. "
        f"Reservoir P {n_pres} psia, AOF {ipr.aof:.0f} STB/d, tubing {n_id} in. x "
        f"{n_depth} ft, GLR {n_glr} scf/STB, water cut {n_wc:.0%}, WHP {n_whp} psia. "
        f"Operating point: "
        f"{('q=%.0f STB/d at pwf=%.0f psia' % (op.q_op, op.pwf_op)) if op.converged else 'no natural flow (needs lift)'}.",
        "Interpret nodal",
    )

    theme.references(["vogel", "hagedorn_brown", "beggs_brill", "nodal"])

# ============================================================== Artificial Lift tab
with tab_lift:
    st.subheader("Artificial-Lift Design — ESP Sizing & Gas-Lift")
    st.caption(
        "Design a lift system to hit a target rate the well can't reach naturally. ESP: "
        "total dynamic head, stages from a representative pump curve, drive frequency via "
        "the affinity laws, viscosity-corrected power. Plus a gas-lift injection sweep."
    )
    theme.data_badge(
        "synthetic",
        "Physics-modeled — standard nodal correlations (Vogel / Hagedorn-Brown / "
        "Beggs-Brill) on illustrative inputs.",
    )
    theme.how_to(
        "- Sizes a lift system to reach a target rate the well can't make naturally.\n"
        "- Set the reservoir & flow test (IPR), the tubing (ID, depth), the fluid (water "
        "cut, GLR, viscosity, wellhead pressure), and the target rate, ESP drive "
        "frequency, and fluid viscosity below.\n"
        "- The ESP design returns stages, frequency, total dynamic head (TDH), and brake "
        "power; the gas-lift sweep finds the injection GLR that maximizes rate."
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        l_pres = st.slider("Reservoir pressure (psia)", 800, 8000, 3000, 50, key="l_pres")
        l_qtest = st.slider("Flow-test rate (STB/d)", 50, 5000, 600, 25, key="l_qtest")
        l_pwftest = st.slider(
            "Flow-test pwf (psia)", 100, int(l_pres),
            min(2200, int(l_pres) - 100), 25, key="l_pwftest",
        )
    with c2:
        l_id = st.slider("Tubing ID (in.)", 1.0, 5.0, 2.441, 0.001, key="l_id")
        l_depth = st.slider("Tubing depth (ft)", 2000, 16000, 8000, 100, key="l_depth")
        l_wc = st.slider("Water cut (fraction)", 0.0, 0.99, 0.40, 0.01, key="l_wc")
        l_glr = st.slider("Formation GLR (scf/STB)", 0, 3000, 300, 25, key="l_glr")
    with c3:
        l_target = st.slider("Target liquid rate (STB/d)", 100, 5000, 1200, 25, key="l_target")
        l_freq = st.slider("ESP drive frequency (Hz)", 40.0, 70.0, 60.0, 1.0, key="l_freq")
        l_visc = st.slider("Fluid viscosity (cP)", 1.0, 300.0, 5.0, 1.0, key="l_visc")
        l_whp = st.slider("Wellhead pressure (psia)", 30, 1500, 150, 10, key="l_whp")

    if l_pwftest >= l_pres:
        st.warning("Flow-test pwf should be below reservoir pressure.")
    ipr_l = vogel_ipr(
        p_res=float(l_pres), pb=float(l_pres),
        q_test=float(l_qtest), pwf_test=float(min(l_pwftest, l_pres - 1)),
    )
    vlp_l = VLPInputs(
        tubing_id_in=float(l_id), depth_ft=float(l_depth),
        wellhead_pressure=float(l_whp), glr_scf_stb=float(l_glr), water_cut=float(l_wc),
    )
    op_nat = operating_point(ipr_l, vlp_l)
    nat_q = op_nat.q_op if op_nat.converged else 0.0

    esp = design_esp(
        ipr_l, vlp_l, target_q_stb_d=float(l_target),
        frequency_hz=float(l_freq), fluid_viscosity_cp=float(l_visc),
    )

    st.markdown("**ESP Design**")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Stages", f"{esp.stages:,d}")
    k2.metric("Frequency", f"{esp.frequency_hz:.0f} Hz")
    k3.metric("Total dynamic head", f"{esp.tdh_ft:,.0f} ft")
    k4.metric("Brake power", f"{esp.bhp:,.0f} hp")
    k5, k6, k7, k8 = st.columns(4)
    k5.metric("Natural rate", f"{nat_q:,.0f} STB/d")
    k6.metric("Rate with ESP", f"{esp.op_q_stb_d:,.0f} STB/d")
    k7.metric("Pump intake P", f"{esp.pump_intake_psia:,.0f} psia")
    k8.metric("Stage efficiency", f"{esp.efficiency:.0%}")
    if esp.meets_target:
        theme.flag(f"Design meets the {l_target:,.0f} STB/d target.", "ok")
    else:
        theme.flag(
            f"Design falls short of {l_target:,.0f} STB/d "
            f"(reaches {esp.op_q_stb_d:,.0f}). Raise frequency/stages or check the IPR.",
            "high",
        )

    # gas-lift sweep
    gl = gas_lift_sweep(ipr_l, vlp_l, inj_glr_max_scf_stb=1500.0, n=14)

    cL, cR = st.columns(2)
    with cL:
        # pump head-per-stage curve vs the per-stage TDH requirement
        from src.lift import PumpModel

        pm = PumpModel()
        q_curve = np.linspace(200.0, pm.q_runout_bpd * 0.98, 60)
        h_curve = np.array(
            [pm.head_per_stage(q, esp.frequency_hz) for q in q_curve]
        )
        figp = go.Figure()
        figp.add_scatter(
            x=q_curve, y=h_curve, name=f"Pump head/stage @ {esp.frequency_hz:.0f} Hz",
            line=dict(color=theme.BLUE),
        )
        figp.add_scatter(
            x=[esp.total_fluid_bpd], y=[esp.head_per_stage_ft],
            name="Design point", mode="markers",
            marker=dict(size=12, color=theme.GREEN, symbol="x", line=dict(width=2)),
        )
        figp.update_layout(
            title="ESP Pump Curve (Representative)",
            xaxis_title="Total fluid (bpd)", yaxis_title="Head per stage (ft)",
        )
        st.plotly_chart(theme.style_fig(figp, height=340), width="stretch")
    with cR:
        figg = go.Figure()
        figg.add_scatter(
            x=[p.inj_glr_scf_stb for p in gl.points],
            y=[p.q_op_stb_d for p in gl.points],
            name="Gas-lift performance", line=dict(color=theme.AMBER),
        )
        figg.add_scatter(
            x=[gl.best.inj_glr_scf_stb], y=[gl.best.q_op_stb_d],
            name="Optimum injection", mode="markers",
            marker=dict(size=12, color=theme.GREEN, symbol="x", line=dict(width=2)),
        )
        figg.update_layout(
            title="Gas-Lift Injection Sweep",
            xaxis_title="Injection GLR added (scf/STB)",
            yaxis_title="Operating rate q (STB/d)",
        )
        st.plotly_chart(theme.style_fig(figg, height=340), width="stretch")

    st.caption(
        f"ESP: {esp.notes} Total dynamic head and brake horsepower per the standard "
        "Hydraulic-Institute / Takacs design equations; stages = TDH ÷ head-per-stage. "
        f"Gas lift: best added GLR {gl.best.inj_glr_scf_stb:,.0f} scf/STB lifts the well "
        f"to {gl.best.q_op_stb_d:,.0f} STB/d (~{gl.inj_rate_mscf_d_at_best:,.0f} Mscf/d "
        "injection). Illustrative pump curve and fluid — not a vendor catalog match."
    )
    theme.source_note(
        "ESP staging via centrifugal-pump affinity laws (Q∝N, H∝N², P∝N³) on TDH; design "
        "point = total fluid (bpd) vs. head-per-stage (ft). Stages count, TDH in ft, brake "
        "power in hp, rate in STB/d."
    )

    _maybe_narrate(
        _api_key,
        f"In 3-4 sentences, summarize this artificial-lift design for a production "
        f"engineer. Target {l_target:.0f} STB/d; natural rate {nat_q:.0f} STB/d. ESP: "
        f"{esp.stages} stages at {esp.frequency_hz:.0f} Hz, {esp.tdh_ft:.0f} ft TDH, "
        f"{esp.bhp:.0f} hp, reaches {esp.op_q_stb_d:.0f} STB/d "
        f"({'meets' if esp.meets_target else 'short of'} target). Gas-lift optimum adds "
        f"{gl.best.inj_glr_scf_stb:.0f} scf/STB for {gl.best.q_op_stb_d:.0f} STB/d.",
        "Interpret lift design",
    )

    theme.references(["esp_affinity"])

st.markdown("---")
st.caption(
    f"Well Performance Studio v{__version__} · physics by bluebonnet + standard nodal "
    "correlations · deterministic, no API key required · part of the Upstream Copilot Suite."
)
