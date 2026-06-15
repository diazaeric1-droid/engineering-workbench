"""Shared light + navy UI theme for the Upstream Copilot Suite.

Vendored identically into every app (next to the Streamlit entrypoint) so all
demos share one look:

- light background, navy ``#1F3A5F`` brand accent (professional, modern)
- standardized ``set_page_config`` + injected CSS (KPI cards, tabs, chips)
- a flex header with title / subtitle / right-aligned chips
- ``style_fig`` — one Plotly light template + suite colorway for every chart
- ``references`` / ``source_note`` — consistent, sourced annotations
- ``data_badge`` / ``flag`` — provenance + status chrome

In the consolidated products, page chrome (set_page_config, masthead, context bar,
KPI rows, product switcher) lives in ``product_theme`` — views import THAT. This
module keeps only the shared brand tokens, CSS, Plotly styling, citations, and the
provenance/annotation helpers product_theme re-exports.

Pure presentation: depends only on ``streamlit`` (and Plotly figures passed to
``style_fig``). Importing it has no side effects beyond defining helpers.

Usage
-----
    import product_theme as pt
    pt.masthead("workbench", "Nodal Analysis", "Operating point at the node")
    ...
    st.plotly_chart(theme.style_fig(fig, height=340), width="stretch")
"""
from __future__ import annotations

from html import escape

import streamlit as st

# ---- brand tokens ----------------------------------------------------------
NAVY = "#1F3A5F"   # primary brand / totals
BLUE = "#4F81BD"   # secondary / positive series
RED = "#C0504D"    # loss / downside
GREEN = "#2ca02c"  # funded / healthy
AMBER = "#E8A33D"  # warning
PURPLE = "#9467bd"
TEAL = "#56c3c9"
GREY = "#9b9b9b"   # neutral / non-recoverable

# light surface tokens (aligned with .streamlit/config.toml — light, modern, professional)
BG = "#ffffff"
PANEL = "#ffffff"
BORDER = "#e5e7eb"
TEXT = "#1f2937"
MUTED = "#6b7280"
GRID = "#eef1f5"

# ordered colorway for multi-series charts
COLORWAY = [BLUE, AMBER, RED, GREEN, PURPLE, TEAL, GREY, "#d6c14e"]

# one font family for the whole suite (UI + charts)
FONT = "-apple-system, Segoe UI, Roboto, sans-serif"

_CHIP_STYLE = {
    "ver": "background:#e7eef7; color:#1F3A5F; border:1px solid #cfe0f5;",
    "eval": "background:#e7f6ec; color:#1b7a3d; border:1px solid #b7e0c4;",
    "info": "background:#e8f0fb; color:#1c4f8a; border:1px solid #c7dcf5;",
    "warn": "background:#fdf3e2; color:#9a6a16; border:1px solid #f0d9a8;",
}

CSS = f"""
<style>
    /* NOTE: block-container sizing (padding-top / -bottom / max-width) is owned by
       product_theme.ENTERPRISE_CSS (loaded AFTER this) so there is a SINGLE source of
       truth for the top clearance — two competing padding-top rules used to fight by
       load order. This sheet only handles header transparency + component styling. */

    /* The fixed top header bar: make it transparent and click-through so it never
       renders as a leftover dark/opaque bar over the light page, regardless of the
       build's header height. Title content sits safely below via the padding above. */
    [data-testid="stHeader"],
    [data-testid="stAppHeader"],
    header[data-testid] {{background: transparent !important; box-shadow: none !important;
                          border-bottom: none !important;}}

    /* KPI cards */
    [data-testid="stMetric"] {{
        background: {PANEL}; border: 1px solid {BORDER}; border-radius: 10px;
        padding: 0.6rem 0.85rem; box-shadow: 0 1px 2px rgba(16,24,40,0.05);
    }}
    [data-testid="stMetricValue"] {{font-size: 1.3rem; line-height: 1.2;}}
    [data-testid="stMetricLabel"] {{font-size: 0.75rem; font-weight: 600; opacity: 0.85;}}
    [data-testid="stMetricDelta"] {{font-size: 0.75rem;}}

    /* tabs */
    .stTabs [data-baseweb="tab-list"] {{gap: 8px;}}
    .stTabs [data-baseweb="tab"] {{padding: 0.4rem 1.1rem; font-weight: 600;}}
    hr {{margin: 0.4rem 0 !important;}}

    /* masthead chips (theme._chip_html, used by product_theme.masthead) */
    .suite-chip {{padding: 0.22rem 0.7rem; border-radius: 10px; font-size: 0.75rem;
                  font-weight: 600; white-space: nowrap;}}

    /* inline status flags */
    div.flag-high {{background:#fdeaea; color:#b42318; padding:0.3rem 0.7rem;
                    border-radius:6px; display:inline-block; margin:0.15rem;
                    font-size:0.8rem; font-weight:600; border:1px solid #f4c7c2;}}
    div.flag-ok {{background:#e7f6ec; color:#1b7a3d; padding:0.3rem 0.7rem;
                  border-radius:6px; display:inline-block; margin:0.15rem;
                  font-size:0.8rem; font-weight:600; border:1px solid #b7e0c4;}}
    div.flag-warn {{background:#fdf3e2; color:#9a6a16; padding:0.3rem 0.7rem;
                    border-radius:6px; display:inline-block; margin:0.15rem;
                    font-size:0.8rem; font-weight:600; border:1px solid #f0d9a8;}}

    /* data-provenance badge (real vs synthetic) */
    .data-badge {{display:inline-block; padding:0.25rem 0.7rem; border-radius:8px;
                  font-size:0.72rem; font-weight:700; letter-spacing:0.03em;
                  margin:0.1rem 0 0.7rem 0;}}
</style>
"""

def _chip_html(text: str, kind: str = "ver") -> str:
    style = _CHIP_STYLE.get(kind, _CHIP_STYLE["ver"])
    return f'<span class="suite-chip" style="{style}">{escape(str(text))}</span>'


def style_fig(fig, height: int | None = None, legend: bool = True):
    """Apply the suite's light Plotly template, colorway, and spacing.

    Spacing is tuned so a chart **title never overlaps the legend or the axis
    labels**: the title sits top-left, the (horizontal) legend sits top-right in the
    same band, the top margin grows when either is present, and both axes use
    ``automargin`` + a title standoff so axis titles can't collide with tick labels.

    Returns the same figure for chaining into ``st.plotly_chart``.
    """
    has_title = bool(getattr(getattr(fig.layout, "title", None), "text", None))
    top = 56 if (has_title or legend) else 30
    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=TEXT, size=12, family=FONT),
        colorway=COLORWAY,
        margin=dict(l=14, r=18, t=top, b=14),
        hoverlabel=dict(font_size=12),
    )
    if has_title:
        # title top-left, in its own band above the plot
        fig.update_layout(title=dict(
            x=0.0, xanchor="left", y=0.98, yanchor="top",
            font=dict(size=14, color=TEXT, family=FONT)))
    if legend:
        # legend top-RIGHT so it shares the top band with the title without overlap
        fig.update_layout(legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
            bgcolor="rgba(0,0,0,0)",
        ))
    # automargin + standoff keep axis titles clear of tick labels
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=GRID, automargin=True, title_standoff=10)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID, automargin=True, title_standoff=10)
    if height:
        fig.update_layout(height=height)
    return fig


def data_badge(source: str = "synthetic", detail: str = "") -> None:
    """Render a data-provenance badge under the header.

    source: 'real' → green "REAL DATA", anything else → amber "SYNTHETIC DATA".
    detail: short provenance note, e.g. "North Dakota (NDIC) public filings — Bakken"
    or "modeled fleet with known ground truth". Keeps every app honest about what a
    visitor is actually looking at.
    """
    if source == "real":
        label = "🟢 REAL DATA"
        style = "background:#e7f6ec; color:#1b7a3d; border:1px solid #b7e0c4;"
    else:
        label = "🟡 SYNTHETIC DATA"
        style = "background:#fdf3e2; color:#9a6a16; border:1px solid #f0d9a8;"
    d = f" — {escape(detail)}" if detail else ""
    st.markdown(f'<div class="data-badge" style="{style}">{label}{d}</div>',
                unsafe_allow_html=True)


def flag(text: str, kind: str = "ok") -> None:
    """Render an inline status flag. kind ∈ {ok, high, warn}."""
    cls = {"ok": "flag-ok", "high": "flag-high", "warn": "flag-warn"}.get(kind, "flag-ok")
    st.markdown(f'<div class="{cls}">{escape(str(text))}</div>', unsafe_allow_html=True)


# ---- sourced methods + instructions ----------------------------------------
# Canonical references for the deterministic engineering/ML methods used across the
# suite. Authored once HERE so every app cites identically and correctly — a PE or
# recruiter sees the math is annotated and sourced, not hand-waved. Use via
# ``theme.references([...keys...])``.
CITATIONS = {
    "arps": "Arps, J.J. (1945). “Analysis of Decline Curves.” Trans. AIME, 160, 228–247. "
            "(Exponential / hyperbolic / harmonic rate-decline models.)",
    "fetkovich": "Fetkovich, M.J. (1980). “Decline Curve Analysis Using Type Curves.” "
                 "JPT, 32(6), 1065–1077.",
    "dca_lib": "Decline-curve fitting implemented with prodpy (open-source DCA library, "
               "MIT-licensed): non-linear least-squares fit of the Arps models.",
    "monte_carlo": "Probabilistic forecast: Monte-Carlo sampling of the decline-fit "
                   "parameter uncertainty to produce a P90/P50/P10 rate fan and EUR.",
    "prms": "Reserves percentiles P90 (proved) / P50 / P10 follow the SPE-PRMS Petroleum "
            "Resources Management System (SPE/WPC/AAPG/SPEE, rev. 2018): P90 = 90% probability "
            "of ≥ that volume (conservative), P10 = optimistic.",
    "npv": "Discounted-cash-flow NPV = Σ CFₜ / (1+i)ᵗ. Standard petroleum project economics "
           "(e.g., Mian, M.A., “Project Economics and Decision Analysis,” PennWell, 2011).",
    "vogel": "Vogel, J.V. (1968). “Inflow Performance Relationships for Solution-Gas-Drive "
             "Wells.” JPT, 20(1), 83–92. (Dimensionless IPR curve.)",
    "hagedorn_brown": "Hagedorn, A.R. & Brown, K.E. (1965). “Experimental Study of Pressure "
                      "Gradients … in Small-Diameter Vertical Conduits.” JPT, 17(4). (VLP / "
                      "multiphase vertical-lift correlation.)",
    "beggs_brill": "Beggs, H.D. & Brill, J.P. (1973). “A Study of Two-Phase Flow in Inclined "
                   "Pipes.” JPT, 25(5), 607–617. (Flow-regime-based pressure-gradient model.)",
    "nodal": "Nodal (systems) analysis: the operating point is the intersection of inflow "
             "(IPR) and outflow (VLP/tubing) curves at the bottom-hole node. See Brown, K.E. "
             "(1984), “The Technology of Artificial Lift Methods,” and Beggs (1991), "
             "“Production Optimization Using Nodal Analysis.”",
    "esp_affinity": "ESP sizing via centrifugal-pump affinity laws (Q ∝ N, H ∝ N², P ∝ N³) "
                    "and total-dynamic-head staging. See Takács, G. (2017), “Electrical "
                    "Submersible Pumps Manual,” 2nd ed., Gulf Professional.",
    "pvt": "PVT (black-oil) correlations for Bo, Rs, μ, Z. See Standing (1947), Vázquez & "
           "Beggs (1980), and McCain, “The Properties of Petroleum Fluids” (1990).",
    "bluebonnet": "PVT, scaling-solution production curves, and rate-transient analysis via "
                  "bluebonnet (F. Male et al.; open-source, BSD-licensed).",
    "milp": "Capital selection as a 0/1 mixed-integer linear program (maximize risked NPV "
            "s.t. per-period budget + rig-day limits), solved by branch-and-bound (CBC) via "
            "PuLP; an LP relaxation gives the optimality-gap bound.",
    "shap": "Model explanations via SHAP. Lundberg, S.M. & Lee, S.-I. (2017). “A Unified "
            "Approach to Interpreting Model Predictions.” NeurIPS 30.",
    "survival": "Run-life / remaining-useful-life from survival (time-to-event) analysis. "
                "Foundational: Kaplan & Meier (1958), JASA 53; Cox (1972), J. R. Stat. Soc. B.",
    "gas_lift": "Gas-lift performance curve (GLPC) and injection optimization. Model: "
                "q_liq = q_sl + (q_max−q_sl)·(1−exp(−a·Qinj)); optimum from dNet/dQinj=0. "
                "Brown, K.E. (1984), “The Technology of Artificial Lift Methods,” Vol. 4; "
                "Takács, G. (2005), “Gas Lift Manual,” PennWell; "
                "Golan & Whitson (1991), “Well Performance,” 2nd ed.",
    "pareto": "Loss attribution ranked by the Pareto principle (the vital-few causes that "
              "drive most deferred volume); cause split via a deterministic keyword classifier.",
    "deferment": "Deferment = well potential − actual. Potential is modeled from the well’s "
                 "full-uptime months (P75, decline-aware); the gap is split into downtime "
                 "(from days-produced / runtime) vs. underperformance (rate).",
}


def references(keys, title: str = "Methods & References") -> None:
    """Render a collapsible 'Methods & References' panel citing the canonical sources
    for the calculations on the page. ``keys`` are CITATIONS keys (unknown keys are
    skipped). Keeps sourcing consistent and correct across every app."""
    items = [CITATIONS[k] for k in keys if k in CITATIONS]
    if not items:
        return
    with st.expander(f"📚 {title}"):
        for c in items:
            st.markdown(f"- {c}")


def source_note(text: str) -> None:
    """A small annotation/source caption to sit directly under a chart or table
    (e.g., the method + units + data provenance for that specific graph)."""
    st.caption(f"📐 {text}")
