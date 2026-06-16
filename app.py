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
# reload from the CURRENT commit's source. Streamlit re-runs this whole script on
# EVERY interaction, so gate the heal to ONCE per session — re-running rmtree on
# every rerun just defeats bytecode caching for no benefit (audit: infra perf).
if "pytest" not in sys.modules and not st.session_state.get("_workbench_healed"):
    import shutil as _sh_heal
    # 1) drop ALL stale bytecode under the app (top-level AND views/ and any package
    #    dirs) — a single HERE/__pycache__ rmtree left views/__pycache__ behind.
    for _pyc in HERE.rglob("__pycache__"):
        _sh_heal.rmtree(_pyc, ignore_errors=True)
    # 2) evict EVERY first-party module cached in the warm container, not just the three
    #    top-level shared ones. A redeploy reuses the process, so a stale `views._common`
    #    (or any view) from the previous commit keeps serving an OLD module that lacks
    #    symbols added since — e.g. `vc.well_choices_for` → AttributeError at import use.
    #    The imports below then reload every one of them from THIS commit's source.
    _OWN = ("core", "product_theme", "theme", "fleet_registry",
            "wps", "pec", "esp", "gla", "views", "src")
    for _name in list(sys.modules):
        if any(_name == p or _name.startswith(p + ".") for p in _OWN):
            sys.modules.pop(_name, None)
    st.session_state["_workbench_healed"] = True

import product_theme as pt  # noqa: E402

pt.setup_product("workbench")

import core  # noqa: E402  (loads the four component aliases)
from views import PAGES  # noqa: E402
from views import _common as vc  # noqa: E402  (cached well-id lists, shared plumbing)


# ---- workspace readiness (silent on a warm / committed checkout) ---------------
# The synthetic SCADA + injection fleets and the trained ESP model are COMMITTED to
# the repo (see .gitignore), so on a normal checkout they already exist and this is
# a no-op — no banner, no ~30 s training on load. Only a cold environment that is
# genuinely missing the artifacts (or a model that fails to load under a different
# sklearn/xgboost) regenerates them, once, behind a quiet spinner.
@st.cache_resource(show_spinner=False)
def _ensure_workspace() -> bool:
    ready = (core.ESP_MODEL.exists() and core.ESP_TRAINING_REPORT.exists()
             and any(core.ESP_DATA.glob("well_*.csv"))
             and core.GLA_FLEET_DIR.exists()
             and any(core.GLA_FLEET_DIR.glob("well_*.csv")))
    if ready:
        try:  # the committed artifact must actually load on this runtime
            core.esp_model.ESPRiskModel.load(core.ESP_MODEL)
        except Exception:  # noqa: BLE001 — stale/incompatible artifact: self-heal below
            ready = False
    if not ready:
        with st.spinner("Preparing the workbench (first run on this environment, "
                        "~30 s, one time)…"):
            core.bootstrap(log=lambda *_a, **_k: None)
    return True


_ensure_workspace()


# ---- session-state contract -----------------------------------------------------
ss = st.session_state
ss.setdefault("oil_price", 70.0)
ss.setdefault("nri", 0.80)
ss.setdefault("discount", 0.10)
ss.setdefault("gas_cost", 1.50)            # shared so Gas-Lift + Case File agree
ss.setdefault("data_source", "synthetic")  # synthetic demo fleet is the default universe
ss.setdefault("anthropic_key", "")
# Open on the flagship synthetic well (production + SCADA + injection) so every page
# has data on first load; real Colorado is one toggle away.
ss.setdefault("well_id", "well_013")

# The data source SCOPES the well list (synthetic well_0NN vs real Colorado ids).
_choices = vc.well_choices_for(ss["data_source"])
if ss["well_id"] not in _choices:
    ss["well_id"] = _choices[0] if _choices else ss["well_id"]


def _snap_well_to_source() -> None:
    """When the data-source toggle flips, snap the selection to that source's lead
    well so the (now scoped) Well selectbox always has a valid value: the synthetic
    case-file hero well_013, or the first real Colorado API id."""
    if st.session_state["data_source"] == "real":
        co = vc.colorado_well_ids()
        st.session_state["well_id"] = co[0] if co else st.session_state["well_id"]
    else:
        synth = vc.synthetic_well_ids()
        st.session_state["well_id"] = ("well_013" if "well_013" in synth
                                       else (synth[0] if synth else
                                             st.session_state["well_id"]))


# ---- global sidebar ----------------------------------------------------------------
with st.sidebar:
    st.radio(
        "Production Data Source", ("synthetic", "real"),
        format_func=lambda s: ("Synthetic — demo fleet (full coverage)"
                               if s == "synthetic"
                               else "Real — Colorado DJ Basin (ECMC)"),
        key="data_source", on_change=_snap_well_to_source,
        help="Synthetic = the well_0NN demo fleets with known ground truth and FULL "
             "coverage (production + SCADA + injection surveys) — every page works on "
             "every well. Real = FREE Colorado ECMC public monthly records (DJ Basin "
             "Niobrara/Codell horizontals) under real state API ids — production only "
             "(no SCADA, no injection surveys).")
    st.caption(
        f"This source scopes the Well list below ({len(_choices)} wells). Synthetic "
        "wells carry production + SCADA + injection; real Colorado wells carry monthly "
        "production only, so the Failure-Risk and Gas-Lift lenses stay honestly "
        "unavailable for them.")

    st.selectbox("Well", _choices, key="well_id", format_func=core.well_label,
                 help="Drives every page — Decline & EUR, Failure Risk, Gas-Lift "
                      "Optimum, and the Case File all follow this selection. Pick any "
                      "well here, in the Well Browser, or on the per-lens pages.")

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
    """Build a nav page whose view module is imported LAZILY — only when that page is
    the active one. Passing ``view.render`` directly would import every view module
    (plotly + each page's deps) on every cold server start; this closure defers each
    import until first navigation to that page (audit: 'app.py eagerly imports every
    view module'). Title/icon/url are explicit so st.Page needs nothing from the
    callable's source."""
    def _run(_m=module_name):
        import importlib
        importlib.import_module(f"views.{_m}").render()

    _run.__name__ = module_name
    return st.Page(_run, title=title, icon=icon, url_path=module_name, default=default)


_nav: dict[str, list[st.Page]] = {}
_first = True
for _section, _entries in PAGES.items():
    _nav[_section] = []
    for _title, _icon, _module in _entries:
        _nav[_section].append(_page(_title, _icon, _module, default=_first))
        _first = False

st.navigation(_nav).run()
