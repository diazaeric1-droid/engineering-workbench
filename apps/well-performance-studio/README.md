# Well Performance Studio 🧪

**Forward well-performance modeling — PVT, physics-based production curves, and
rate-transient analysis (RTA) for unconventional wells.** The "Design" app of the
[Upstream Copilot Suite](https://pe-copilot.streamlit.app). Built by an ex-OXY /
ex-Shell Staff Production Engineer.

**Live demo:** https://well-performance-studio.streamlit.app

Where the suite's other apps *diagnose*, *monitor*, and *predict* on existing wells,
this one **designs forward** — it turns reservoir / fluid / completion inputs into
first-principles fluid properties and production forecasts, and fits that same physics
back to measured rate data.

Everything is **deterministic** and runs with **zero API key**. An optional Claude
narrative is bring-your-own-key.

---

## The engine: `bluebonnet`

The physics comes from **[bluebonnet](https://pypi.org/project/bluebonnet/)** (open
source; PVT + scaling-solution flow + RTA for unconventional / tight wells). This app is
a thin Streamlit + Plotly UI over it:

| Tab | bluebonnet API used | What you get |
|-----|--------------------|--------------|
| **PVT** | `fluids.Fluid` (`oil_FVF`, `oil_viscosity`, `gas_FVF`, `gas_viscosity`, `water_FVF`, `water_viscosity`, `pressure_bubblepoint`) + `fluids.gas` pseudo-criticals | Bo, Bg, oil/gas/water viscosity, z-factor, bubble point vs. pressure; props at a chosen pressure |
| **Physics production curve** | `fluids.build_pvt_gas` → `flow.FlowProperties` → `flow.SinglePhaseReservoir.simulate` / `recovery_factor_interpolator` | Gas rate(t), cumulative, and EUR from a 1-D scaling-solution solve; optional Arps overlay |
| **RTA** | `forecast.ForecasterOnePhase.fit` / `forecast_cum` (bounded by `forecast.Bounds`) | Fits the scaling model to a rate series → resource-in-place **M** and time-to-BDF **τ**, then forecasts EUR |

**The scaling solution in one line:** bluebonnet solves a *dimensionless* recovery
curve `rf(t_scaled)`, and a real well is `Q(t) = M · rf(t/τ)` — so two constants (M in
Mscf, τ in years) scale one physics curve to any well. RTA simply regresses those two
constants against measured cumulative.

---

## Run locally

> **Python 3.11 required.** bluebonnet supports **Python 3.8–3.11** (it does **not**
> support 3.12+ / 3.14). The CI smoke test and the hosted deploy both pin 3.11.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run demo/app.py
```

Run the tests:

```bash
pytest -q
```

---

## Deploy on Streamlit Community Cloud with Python 3.11

This app is hosted on **Streamlit Community Cloud** (auto-deploys from GitHub `main`).
When you create / configure the app:

1. **Repository:** this repo · **Branch:** `main` · **Main file path:** `demo/app.py`
2. **Advanced settings → Python version: select `3.11`.** This is required — bluebonnet
   will not install on the default newer interpreter. (Community Cloud also reads
   `runtime.txt` / a pinned version if present.)
3. Sharing → **Public** (no login) once deployed.

No secrets are needed for the deterministic app. To enable the optional LLM narrative
for *all* visitors you could set `ANTHROPIC_API_KEY` in the app's **Secrets**, but the
intended pattern is **BYOK** (below) so you never expose your own key.

---

## BYOK (bring your own key)

The sidebar has an **Anthropic API key** field. It is used only for the optional
plain-English narrative on each tab, **never stored**, and only lives for your session.
Every chart, table, and number — PVT, the physics curve, the RTA fit — is computed
deterministically by bluebonnet **with no key at all**.

---

## Project layout

```
demo/app.py            Streamlit entry (presentation only)
demo/theme.py          vendored shared suite theme (dark + navy)
.streamlit/config.toml vendored shared Streamlit theme config
src/__init__.py        __version__
src/pvt.py             PVT wrapper around bluebonnet.fluids
src/curves.py          physics production curve (bluebonnet.flow scaling solution)
src/rta.py             RTA fit/forecast (bluebonnet.forecast)
tests/                 deterministic pytest suite for the wrappers
.github/workflows/     Python-3.11 smoke CI (pytest + Streamlit AppTest render)
```

---

## Honest framing

The PVT and production curves are **physics-modeled on illustrative reservoir/fluid
inputs — not real-well data**. The RTA tab ships a synthetic series at a known
(M, τ) so an honest fit visibly recovers the truth, **and** accepts a real
date/rate CSV upload (the provenance badge flips to *real data* when you do). The
scaling solution is single-phase gas; it is a forward *design* / screening tool, not a
full numerical reservoir simulator.

## License

MIT — see [LICENSE](LICENSE).
