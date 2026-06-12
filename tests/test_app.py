"""UI tests — navigation structure, full-app render smoke, and per-view
execution coverage via AppTest. Zero exceptions tolerated on any page.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import core  # noqa: E402
from views import PAGES  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def bootstrapped():
    core.bootstrap(log=lambda *_a, **_k: None)
    return True


# ---------------------------------------------------------------- navigation spec
def test_navigation_page_list_matches_design():
    assert list(PAGES) == ["Fleet", "Design", "Diagnose", "Predict",
                           "Optimize", "Case File", "Data"]
    titles = {section: [t for t, _i, _m in entries]
              for section, entries in PAGES.items()}
    assert titles == {
        "Fleet": ["Well Browser"],
        "Design": ["Nodal Analysis", "PVT & Type Curves", "Artificial Lift Design"],
        "Diagnose": ["Decline & EUR", "AI Well Review"],
        "Predict": ["Failure Risk", "Run-Life"],
        "Optimize": ["Gas-Lift Optimum", "Injection Allocation"],
        "Case File": ["Well Case File"],
        "Data": ["Sources & BYOD"],
    }
    # material icons only — never emoji — and every module exists
    import importlib
    for entries in PAGES.values():
        for _title, icon, module in entries:
            assert icon.startswith(":material/") and icon.endswith(":")
            assert importlib.import_module(f"views.{module}").render


# ---------------------------------------------------------------- full app smoke
def test_app_renders_without_exceptions():
    at = AppTest.from_file(str(REPO_ROOT / "app.py"), default_timeout=600).run()
    assert not at.exception, at.exception


# ---------------------------------------------------------------- per-view coverage
def _run_view(module_name: str, well_id: str, repo: str, extra_state: dict):
    """AppTest script body: render ONE view with the session contract pre-set."""
    import sys as _sys
    if repo not in _sys.path:
        _sys.path.insert(0, repo)
    import streamlit as st
    import importlib

    st.session_state.setdefault("oil_price", 70.0)
    st.session_state.setdefault("nri", 0.80)
    st.session_state.setdefault("discount", 0.10)
    st.session_state.setdefault("data_source", "real")
    st.session_state.setdefault("anthropic_key", "")
    st.session_state["well_id"] = well_id
    for k, v in (extra_state or {}).items():
        st.session_state[k] = v

    view = importlib.import_module(f"views.{module_name}")
    view.render()


_ALL_VIEWS = [m for entries in PAGES.values() for _t, _i, m in entries]


@pytest.mark.parametrize("module_name", _ALL_VIEWS)
def test_each_view_renders_on_hero_well(module_name):
    """well_013 exists in all three synthetic fleets → every lens has data."""
    at = AppTest.from_function(
        _run_view, args=(module_name, "well_013", str(REPO_ROOT), {}),
        default_timeout=600).run()
    assert not at.exception, f"{module_name}: {at.exception}"


@pytest.mark.parametrize("module_name", _ALL_VIEWS)
def test_each_view_renders_on_real_colorado_well(module_name):
    """Real wells lack SCADA/injection — views must show empty states, not crash."""
    co = sorted(core.colorado_wells())[0]
    at = AppTest.from_function(
        _run_view, args=(module_name, co, str(REPO_ROOT), {}),
        default_timeout=600).run()
    assert not at.exception, f"{module_name}: {at.exception}"


@pytest.mark.parametrize("module_name", _ALL_VIEWS)
def test_each_view_renders_on_scada_only_well(module_name):
    """well_085 has SCADA only (no production, no injection) — pages must degrade
    to empty states for the missing lenses without raising."""
    at = AppTest.from_function(
        _run_view, args=(module_name, "well_085", str(REPO_ROOT), {}),
        default_timeout=600).run()
    assert not at.exception, f"{module_name}: {at.exception}"


def test_app_well_switch_and_source_toggle_interaction():
    """Switching the global well and flipping the data-source radio must rerun
    cleanly; the source toggle snaps the selection to that source's lead well."""
    at = AppTest.from_file(str(REPO_ROOT / "app.py"), default_timeout=600).run()
    assert not at.exception
    at.selectbox(key="well_id").select("well_013")
    at.run()
    assert not at.exception
    assert at.session_state["well_id"] == "well_013"
    at.radio(key="data_source").set_value("synthetic")
    at.run()
    assert not at.exception
    assert at.session_state["well_id"] == "well_013"  # hero default for synthetic
    at.radio(key="data_source").set_value("real")
    at.run()
    assert not at.exception
    assert str(at.session_state["well_id"]).startswith("05-")  # first CO well


def test_case_file_design_lens_renders_after_nodal_session():
    """Case File picks up the stored nodal result for the selected well."""
    nodal = {"q_op": 1234.0, "pwf_op": 1500.0, "converged": True,
             "aof": 3000.0, "correlation": "hagedorn_brown"}
    at = AppTest.from_function(
        _run_view,
        args=("case_file", "well_013", str(REPO_ROOT),
              {"nodal::well_013": nodal}),
        default_timeout=600).run()
    assert not at.exception, at.exception


def test_case_file_markdown_honest_on_real_well():
    """The downloadable case file for a REAL well must mark SCADA/injection lenses
    unavailable — never imply a real Colorado well has synthetic-fleet data."""
    sys.path.insert(0, str(REPO_ROOT)) if str(REPO_ROOT) not in sys.path else None
    from views import case_file as cf

    co = sorted(core.colorado_wells())[0]
    md = cf._markdown_case_file(
        co,
        {"name": "x", "basin_formation": "DJ Basin (CO) · Niobrara",
         "lift": "—", "source": "REAL — Colorado ECMC"},
        (70.0, 0.80, 0.10),
        cf._decline_lens(co), None, None, None)
    assert "Lens unavailable — needs fleet SCADA" in md
    assert "Lens unavailable — needs an injection survey" in md
    assert "REAL — Colorado ECMC" in md
