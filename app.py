"""Engineering Workbench — the per-well engineering console of the Upstream
Copilot Suite: design → diagnose → predict → optimize, condensed to one
application with a one-page Well Case File.

Four production-grade components run in ONE process via core.py's alias loader
(wps · pec · esp · gla — see VENDORING.md); this file is only the shell: product
chrome (product_theme), the GLOBAL sidebar (data source, well, price deck, BYOK
key, product switcher), and st.navigation over the views/ pages.
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

# --- warm-container module self-heal (vendored top-level modules) -----------
# Streamlit Cloud reuses the container across redeploys; a cached OLD `theme` /
# `fleet_registry` in sys.modules (or a stale .pyc) can lack symbols added in a
# newer commit. Drop bytecode + evict the cached modules so the imports below
# reload from the CURRENT commit's source.
import shutil as _sh_heal
_sh_heal.rmtree(HERE / "__pycache__", ignore_errors=True)
for _stale in ("theme", "fleet_registry", "product_theme"):
    sys.modules.pop(_stale, None)

import product_theme as pt  # noqa: E402

pt.setup_product("workbench")

import core  # noqa: E402  (loads the four component aliases)
from views import PAGES  # noqa: E402


# ---- first-run bootstrap (gitignored synthetic data + the ESP model) ----------
@st.cache_resource(show_spinner=False)
def _bootstrap_once() -> bool:
    msgs: list[str] = []
    with st.status("First-time setup: regenerating synthetic data + training the "
                   "ESP model (~30 s, one time)…", expanded=False) as status:
        core.bootstrap(log=lambda m: (msgs.append(str(m)), status.write(str(m))))
        status.update(label="Workspace ready.", state="complete")
    return True


_bootstrap_once()


# ---- session-state contract -----------------------------------------------------
ss = st.session_state
ss.setdefault("oil_price", 70.0)
ss.setdefault("nri", 0.80)
ss.setdefault("discount", 0.10)
ss.setdefault("data_source", "real")
ss.setdefault("anthropic_key", "")
_choices = core.well_choices()
if not ss.get("well_id") or ss["well_id"] not in _choices:
    # Default to the first REAL Colorado well so the diagnose pages open on real
    # data (green badge); synthetic well_0NN wells are one pick away.
    ss["well_id"] = _choices[0] if _choices else ""


def _snap_well_to_source() -> None:
    """When the data-source toggle flips, snap the selection to that source's
    first well (real CO API id, or the synthetic case-file hero well_013)."""
    if st.session_state["data_source"] == "real":
        co = sorted(core.colorado_wells())
        st.session_state["well_id"] = co[0] if co else st.session_state["well_id"]
    else:
        synth = [w for w in core.well_choices() if not core.is_real_well(w)]
        st.session_state["well_id"] = ("well_013" if "well_013" in synth
                                       else (synth[0] if synth else
                                             st.session_state["well_id"]))


# ---- global sidebar ----------------------------------------------------------------
with st.sidebar:
    st.radio(
        "Production Data Source", ("real", "synthetic"),
        format_func=lambda s: ("Real — Colorado DJ Basin (ECMC)" if s == "real"
                               else "Synthetic (demo fleets)"),
        key="data_source", on_change=_snap_well_to_source,
        help="Real = FREE Colorado ECMC public monthly records (DJ Basin "
             "Niobrara/Codell horizontals) under real state API ids — production "
             "only. Synthetic = the well_0NN demo fleets with known ground truth "
             "(production + SCADA + injection surveys).")
    st.caption(
        "Provenance: real Colorado wells carry monthly production ONLY — no SCADA, "
        "no injection surveys. The SCADA (esp) and injection (gla) fleets are "
        "synthetic well_0NN wells sharing the registry identity.")

    st.selectbox("Well", _choices, key="well_id", format_func=core.well_label,
                 help="Drives every page — Decline & EUR, Failure Risk, Gas-Lift "
                      "Optimum, and the Case File all follow this selection.")

    st.markdown("**Price Deck**")
    st.number_input("Oil Price ($/bbl)", min_value=0.0, max_value=500.0, step=5.0,
                    key="oil_price")
    st.number_input("Net Revenue Interest", min_value=0.0, max_value=1.0, step=0.05,
                    key="nri")
    st.number_input("Discount Rate (annual)", min_value=0.0, max_value=1.0,
                    step=0.01, key="discount")

    st.markdown("**AI Well Review (optional, BYOK)**")
    st.text_input("Anthropic API Key", type="password", key="anthropic_key",
                  placeholder="sk-ant-…",
                  help="Session-only; never stored. Powers Diagnose → AI Well "
                       "Review. Every chart and number on every page is "
                       "deterministic and needs no key.")

    pt.product_switcher("workbench")


# ---- navigation ----------------------------------------------------------------------
def _page(title: str, icon: str, module_name: str, default: bool = False) -> st.Page:
    import importlib

    view = importlib.import_module(f"views.{module_name}")
    return st.Page(view.render, title=title, icon=icon,
                   url_path=module_name, default=default)


_nav: dict[str, list[st.Page]] = {}
_first = True
for _section, _entries in PAGES.items():
    _nav[_section] = []
    for _title, _icon, _module in _entries:
        _nav[_section].append(_page(_title, _icon, _module, default=_first))
        _first = False

st.navigation(_nav).run()
