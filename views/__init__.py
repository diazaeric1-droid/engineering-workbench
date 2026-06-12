"""Engineering Workbench views — one module per page, plus the navigation spec.

``PAGES`` is pure data (no streamlit import at module scope) so tests can assert
the navigation structure without executing any UI code. app.py turns it into
``st.Page`` objects; every entry is ``(title, material_icon, module_name)`` and
each ``views.<module_name>`` exposes a zero-argument ``render()``.
"""
from __future__ import annotations

# section -> [(page title, material icon, views module name)]
PAGES: dict[str, list[tuple[str, str, str]]] = {
    "Fleet": [
        ("Well Browser", ":material/table_view:", "well_browser"),
    ],
    "Design": [
        ("Nodal Analysis", ":material/design_services:", "nodal_analysis"),
        ("PVT & Type Curves", ":material/science:", "pvt_type_curves"),
        ("Artificial Lift Design", ":material/construction:", "lift_design"),
    ],
    "Diagnose": [
        ("Decline & EUR", ":material/trending_down:", "decline_eur"),
        ("AI Well Review", ":material/troubleshoot:", "ai_well_review"),
    ],
    "Predict": [
        ("Failure Risk", ":material/online_prediction:", "failure_risk"),
        ("Run-Life", ":material/schedule:", "run_life"),
    ],
    "Optimize": [
        ("Gas-Lift Optimum", ":material/tune:", "gas_lift_optimum"),
        ("Injection Allocation", ":material/account_tree:", "injection_allocation"),
    ],
    "Case File": [
        ("Well Case File", ":material/folder_open:", "case_file"),
    ],
    "Data": [
        ("Sources & BYOD", ":material/database:", "data_sources"),
    ],
}
