"""
Bar Arbolada Analytics — Streamlit entry point.

Defines the grouped sidebar navigation via ``st.navigation``:

    Overview → Sales → Labor → Cost → Data Entry → System

Page scripts live in ``dashboards/views/`` (deliberately NOT a ``pages/`` folder,
so Streamlit does not also auto-list them). Because ``st.navigation`` runs the
selected page inside this script's run, ``set_page_config`` and the base CSS are
set here exactly once; the individual pages no longer call ``set_page_config``.

Run with:
    streamlit run dashboards/app.py
"""

import sys
from pathlib import Path

# Project root on path so `dashboards.*` and `src.*` imports resolve.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from dashboards.theme import inject_base_css

st.set_page_config(
    page_title="Bar Arbolada Analytics",
    page_icon="\U0001F333",  # 🌳
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_base_css()

# Grouped navigation. Section labels (dict keys) render as sidebar headers.
NAV = {
    "Overview": [
        st.Page("Home.py", title="Overview", icon="\U0001F3E0", default=True),  # 🏠
    ],
    "Sales": [
        st.Page("views/daily_sales.py", title="Daily Sales", icon="\U0001F4CA"),
        st.Page("views/product_mix.py", title="Product Mix", icon="\U0001F379"),
        st.Page("views/comps_leakage.py", title="Comps & Leakage", icon="\U0001F50D"),
    ],
    "Labor": [
        st.Page("views/staffing_rush.py", title="Staffing & Rush", icon="\U0001F465"),
        st.Page("views/scheduling.py", title="Scheduling", icon="\U0001F4C5"),
        st.Page("views/payroll.py", title="Payroll", icon="\U0001F4B5"),
    ],
    "Cost": [
        st.Page("views/profitability.py", title="Profitability", icon="\U0001F4B0"),
        st.Page("views/cogs_deep_dive.py", title="COGS Deep Dive", icon="\U0001F4C9"),
        st.Page("views/inventory.py", title="Inventory", icon="\U0001F4CB"),
    ],
    "Data Entry": [
        st.Page("views/invoices.py", title="Invoices", icon="\U0001F9FE"),
        st.Page("views/operating_expenses.py", title="Operating Expenses", icon="\U0001F3E2"),
        st.Page("views/inventory_items.py", title="Inventory Items", icon="\U0001F4E6"),
        st.Page("views/recipes.py", title="Recipes", icon="\U0001F378"),
    ],
    "System": [
        st.Page("views/import_operations.py", title="Import Operations", icon="\U0001F4E5"),
    ],
}

st.navigation(NAV).run()
