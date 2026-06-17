"""
Bar Arbolada Analytics Dashboard
================================
Executive homepage — owner/investor command center.

Run with:
    streamlit run dashboards/Home.py
"""

import sys
from pathlib import Path

# Add project root to path so imports work
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date, timedelta

from src.analytics.queries import (
    get_daily_sales,
    get_sales_date_range,
    get_full_pnl,
    get_reorder_items,
)

# ── Page Config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Bar Arbolada Analytics",
    page_icon="\U0001F333",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ───────────────────────────────────────────────────────────────

st.markdown("""
<style>
    .block-container { padding-top: 1rem; }

    /* KPI metric cards — inherit theme colors */
    .stMetric {
        border-radius: 10px;
        padding: 14px 16px;
        border-left: 4px solid #2d6a4f;
    }
    div[data-testid="stMetricValue"] {
        font-size: 1.6rem !important;
        font-weight: 700 !important;
    }
    div[data-testid="stMetricDelta"] {
        font-size: 0.85rem !important;
    }

    /* Typography */
    h1 { font-weight: 800; letter-spacing: -0.02em; }
    h2 { font-weight: 700; color: #1a1a2e; margin-top: 0.5rem; }
    h3 { font-weight: 600; color: #16213e; }

    /* Section dividers */
    .section-divider {
        border: none;
        border-top: 2px solid #e9ecef;
        margin: 1.5rem 0;
    }
</style>
""", unsafe_allow_html=True)

# ── Header ───────────────────────────────────────────────────────────────────

st.title("\U0001F330 Bar Arbolada")
st.caption("Executive Dashboard")

# ── Data Load & Period Selection ─────────────────────────────────────────────

try:
    min_date, max_date = get_sales_date_range()
except Exception as e:
    st.error(f"Database connection error: {e}")
    st.info("Make sure PostgreSQL is running and .env is configured correctly.")
    st.stop()

# Sidebar period selector
st.sidebar.header("Period")
period_options = {
    "Last 30 Days": 30,
    "Last 60 Days": 60,
    "Last 90 Days": 90,
    "Year to Date": None,
    "All Time": -1,
    "Custom Range": 0,
}
selected_period = st.sidebar.radio(
    "Select period",
    list(period_options.keys()),
    index=0,
    label_visibility="collapsed",
)

if selected_period == "Custom Range":
    start_date = st.sidebar.date_input("Start", value=min_date, min_value=min_date, max_value=max_date)
    end_date = st.sidebar.date_input("End", value=max_date, min_value=min_date, max_value=max_date)
elif selected_period == "All Time":
    start_date = min_date
    end_date = max_date
elif selected_period == "Year to Date":
    start_date = date(max_date.year, 1, 1)
    if start_date < min_date:
        start_date = min_date
    end_date = max_date
else:
    days_back = period_options[selected_period]
    end_date = max_date
    start_date = max_date - timedelta(days=days_back - 1)
    if start_date < min_date:
        start_date = min_date

# Compute prior period (same length, immediately before)
period_length = (end_date - start_date).days + 1
prior_end = start_date - timedelta(days=1)
prior_start = prior_end - timedelta(days=period_length - 1)
if prior_start < min_date:
    prior_start = min_date

# Load data
df = get_daily_sales(start_date, end_date)
df_prior = get_daily_sales(prior_start, prior_end)

if df.empty:
    st.warning("No sales data for the selected period. Try a different date range or import data first.")
    st.stop()

full_data = df[df["net_sales"].notna()]
full_prior = df_prior[df_prior["net_sales"].notna()] if not df_prior.empty else pd.DataFrame()

# ── Sidebar Data Info ────────────────────────────────────────────────────────

st.sidebar.markdown("---")
st.sidebar.markdown(f"**Data range:** {min_date.strftime('%b %d, %Y')} to {max_date.strftime('%b %d, %Y')}")
st.sidebar.markdown(f"**Viewing:** {start_date.strftime('%b %d, %Y')} to {end_date.strftime('%b %d, %Y')}")
st.sidebar.markdown(f"**Trading days:** {len(full_data)}")

st.caption(f"Data through {max_date.strftime('%b %d, %Y')}")

# ── Section 1: KPI Cards ────────────────────────────────────────────────────

# Current period stats
net_sales = float(full_data["net_sales"].sum())
days_count = len(full_data)
avg_daily = net_sales / days_count if days_count > 0 else 0
avg_check = float(full_data["check_avg"].mean()) if not full_data.empty else 0
total_checks = int(full_data["total_checks"].sum())
total_tips = float(full_data["total_tips"].sum()) if "total_tips" in full_data.columns else 0

# Prior period stats for deltas
if not full_prior.empty and len(full_prior) > 0:
    prior_net = float(full_prior["net_sales"].sum())
    prior_days = len(full_prior)
    prior_avg_daily = prior_net / prior_days if prior_days > 0 else 0
    prior_avg_check = float(full_prior["check_avg"].mean())
    prior_checks = int(full_prior["total_checks"].sum())

    delta_sales = net_sales - prior_net
    delta_avg_daily = avg_daily - prior_avg_daily
    delta_avg_check = avg_check - prior_avg_check
    delta_checks = total_checks - prior_checks
else:
    delta_sales = delta_avg_daily = delta_avg_check = delta_checks = None

# P&L data for cost ratios
try:
    pnl = get_full_pnl(start_date, end_date)
    pnl_prior = get_full_pnl(prior_start, prior_end) if not full_prior.empty else None
    prime_cost_pct = pnl["prime_cost_pct"]
    labor_pct = pnl["labor_pct"]
    cogs_pct = (pnl["cogs"] / pnl["net_sales"] * 100) if pnl["net_sales"] > 0 else 0
    delta_prime = (prime_cost_pct - pnl_prior["prime_cost_pct"]) if pnl_prior else None
    delta_labor = (labor_pct - pnl_prior["labor_pct"]) if pnl_prior else None
    delta_cogs = (
        cogs_pct - (pnl_prior["cogs"] / pnl_prior["net_sales"] * 100)
        if pnl_prior and pnl_prior["net_sales"] > 0 else None
    )
except Exception:
    pnl = None
    prime_cost_pct = labor_pct = cogs_pct = delta_prime = delta_labor = delta_cogs = None

# Render KPI row
col1, col2, col3, col4, col5, col6 = st.columns(6)

with col1:
    st.metric(
        "Net Sales",
        f"${net_sales:,.0f}",
        delta=f"{'-' if delta_sales < 0 else ''}${abs(delta_sales):,.0f}" if delta_sales is not None else None,
        help="Total net sales for the selected period",
    )
with col2:
    st.metric(
        "Avg / Day",
        f"${avg_daily:,.0f}",
        delta=f"{'-' if delta_avg_daily < 0 else ''}${abs(delta_avg_daily):,.0f}" if delta_avg_daily is not None else None,
        help="Average net sales per trading day",
    )
with col3:
    st.metric(
        "Avg Check",
        f"${avg_check:,.2f}",
        delta=f"{'-' if delta_avg_check < 0 else ''}${abs(delta_avg_check):,.2f}" if delta_avg_check is not None else None,
        help="Average check size",
    )
with col4:
    if prime_cost_pct is not None:
        st.metric(
            "Prime Cost %",
            f"{prime_cost_pct:.1f}%",
            delta=f"{delta_prime:+.1f}pp" if delta_prime is not None else None,
            delta_color="inverse",
            help="(COGS + Labor) / Revenue — lower is better",
        )
    else:
        st.metric("Prime Cost %", "N/A")
with col5:
    if labor_pct is not None:
        st.metric(
            "Labor %",
            f"{labor_pct:.1f}%",
            delta=f"{delta_labor:+.1f}pp" if delta_labor is not None else None,
            delta_color="inverse",
            help="Total labor cost / Revenue — lower is better",
        )
    else:
        st.metric("Labor %", "N/A")
with col6:
    if cogs_pct is not None:
        st.metric(
            "COGS %",
            f"{cogs_pct:.1f}%",
            delta=f"{delta_cogs:+.1f}pp" if delta_cogs is not None else None,
            delta_color="inverse",
            help="Cost of Goods Sold / Revenue — lower is better. See COGS Deep Dive for details.",
        )
    else:
        st.metric("COGS %", "N/A")

if delta_sales is not None:
    st.caption(
        f"Compared to prior {period_length} days "
        f"({prior_start.strftime('%b %d')} \u2013 {prior_end.strftime('%b %d, %Y')})"
    )

st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

# ── Shared Chart Theme ───────────────────────────────────────────────────────
# Matches the aesthetic of Profitability & Daily Sales pages

CHART_LAYOUT = dict(
    margin=dict(l=10, r=10, t=30, b=10),
)

# ── Section 2: Sales Trend ───────────────────────────────────────────────────

st.subheader("Sales Trend")

chart_df = full_data[["trading_day", "net_sales"]].copy()
chart_df["net_sales"] = chart_df["net_sales"].astype(float)
chart_df["day_name"] = pd.to_datetime(chart_df["trading_day"]).dt.day_name()
chart_df["rolling_7d"] = chart_df["net_sales"].rolling(window=7, min_periods=1).mean()

fig = go.Figure()

# Clean single-color bars
fig.add_trace(go.Bar(
    x=chart_df["trading_day"],
    y=chart_df["net_sales"],
    name="Daily Sales",
    marker=dict(color="#2d6a4f", opacity=0.75),
    hovertemplate="<b>%{x|%a %b %d, %Y}</b><br>Net Sales: $%{y:,.0f}<extra></extra>",
))

# 7-day rolling average — prominent trend line
fig.add_trace(go.Scatter(
    x=chart_df["trading_day"],
    y=chart_df["rolling_7d"],
    name="7-Day Average",
    mode="lines",
    line=dict(color="#e76f51", width=3, shape="spline"),
    hovertemplate="<b>%{x|%a %b %d}</b><br>7-Day Avg: $%{y:,.0f}<extra></extra>",
))

fig.update_layout(
    **CHART_LAYOUT,
    height=400,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                font=dict(size=12)),
    xaxis=dict(
        title="",
        showgrid=False,
        tickformat="%b %d",
        dtick="M1" if period_length > 120 else None,
    ),
    yaxis=dict(
        title="Net Sales",
        tickprefix="$",
        tickformat=",",
    ),
    bargap=0.15,
    hovermode="x unified",
)

st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

# ── Section 3: Two-Column Insights ───────────────────────────────────────────

col_left, col_right = st.columns(2)

# Left: P&L Waterfall — matches Profitability page style
with col_left:
    st.subheader("P&L Snapshot")

    if pnl and pnl["net_sales"] > 0:
        wf_labels = ["Net Sales", "COGS", "Gross Profit", "Labor", "OpEx", "NOI"]
        wf_measures = ["absolute", "relative", "total", "relative", "relative", "total"]
        wf_values = [
            pnl["net_sales"], -pnl["cogs"], pnl["gross_profit"],
            -pnl["labor_cost"], -pnl["total_opex"], pnl["net_operating_income"],
        ]

        fig_pnl = go.Figure(go.Waterfall(
            orientation="v",
            measure=wf_measures,
            x=wf_labels,
            y=wf_values,
            text=[f"${abs(v):,.0f}" for v in wf_values],
            textposition="outside",
            textfont=dict(size=11),
            connector={"line": {"width": 1}},
            increasing={"marker": {"color": "#22c55e"}},
            decreasing={"marker": {"color": "#ef4444"}},
            totals={"marker": {"color": "#3b82f6"}},
        ))
        fig_pnl.update_layout(
            **CHART_LAYOUT,
            height=400,
            showlegend=False,
            xaxis=dict(title="", tickfont=dict(size=11)),
            yaxis=dict(
                title="Amount ($)",
                tickprefix="$",
                tickformat=",",
            ),
        )
        st.plotly_chart(fig_pnl, use_container_width=True, config={"displayModeBar": False})

        # Key ratios below the waterfall
        r1, r2, r3 = st.columns(3)
        with r1:
            gm_delta = f'{pnl["gross_margin_pct"] - pnl_prior["gross_margin_pct"]:+.1f}pp' if pnl_prior else None
            st.metric("Gross Margin", f'{pnl["gross_margin_pct"]:.1f}%', delta=gm_delta)
        with r2:
            pc_delta = f'{pnl["prime_cost_pct"] - pnl_prior["prime_cost_pct"]:+.1f}pp' if pnl_prior else None
            st.metric("Prime Cost", f'{pnl["prime_cost_pct"]:.1f}%', delta=pc_delta, delta_color="inverse")
        with r3:
            noi_delta = f'{pnl["noi_pct"] - pnl_prior["noi_pct"]:+.1f}pp' if pnl_prior else None
            st.metric("NOI Margin", f'{pnl["noi_pct"]:.1f}%', delta=noi_delta)
    else:
        st.info("P&L data not available for this period.")

# Right: Day-of-Week Performance
with col_right:
    st.subheader("Day-of-Week Performance")

    dow_df = full_data[["trading_day", "net_sales"]].copy()
    dow_df["net_sales"] = dow_df["net_sales"].astype(float)
    dow_df["day_name"] = pd.to_datetime(dow_df["trading_day"]).dt.day_name()
    dow_df["day_num"] = pd.to_datetime(dow_df["trading_day"]).dt.dayofweek

    dow_avg = dow_df.groupby(["day_name", "day_num"]).agg(
        avg_sales=("net_sales", "mean"),
        count=("net_sales", "count"),
    ).reset_index().sort_values("day_num")

    if not dow_avg.empty:
        overall_avg = dow_df["net_sales"].mean()

        # Gradient: below avg = muted, above avg = vivid green
        max_sales = dow_avg["avg_sales"].max()
        min_sales = dow_avg["avg_sales"].min()
        colors = []
        for _, row in dow_avg.iterrows():
            if row["avg_sales"] >= overall_avg:
                # Green scale based on how far above average
                intensity = (row["avg_sales"] - overall_avg) / (max_sales - overall_avg + 1)
                r_val = int(45 - intensity * 20)
                g_val = int(106 + intensity * 50)
                b_val = int(79 - intensity * 20)
                colors.append(f"rgb({r_val},{g_val},{b_val})")
            else:
                # Slate/muted for below average
                intensity = (overall_avg - row["avg_sales"]) / (overall_avg - min_sales + 1)
                gray = int(148 + intensity * 40)
                colors.append(f"rgb({gray},{gray},{gray})")

        fig_dow = go.Figure()

        fig_dow.add_trace(go.Bar(
            x=dow_avg["day_name"],
            y=dow_avg["avg_sales"],
            marker=dict(color=colors, line=dict(width=0)),
            text=[f"${v:,.0f}" for v in dow_avg["avg_sales"]],
            textposition="outside",
            textfont=dict(size=12),
            hovertemplate=(
                "<b>%{x}</b><br>"
                "Avg Sales: $%{y:,.0f}<br>"
                "<extra></extra>"
            ),
            customdata=dow_avg["count"].values,
        ))

        # Average reference line
        fig_dow.add_hline(
            y=overall_avg,
            line_dash="dash",
            line_color="#94a3b8",
            line_width=1.5,
            annotation_text=f"Avg: ${overall_avg:,.0f}",
            annotation_position="top right",
            annotation_font=dict(size=11),
        )

        fig_dow.update_layout(
            **CHART_LAYOUT,
            height=400,
            showlegend=False,
            xaxis=dict(title="", tickfont=dict(size=12)),
            yaxis=dict(
                title="Avg Net Sales",
                tickprefix="$",
                tickformat=",",
            ),
            bargap=0.25,
        )
        st.plotly_chart(fig_dow, use_container_width=True, config={"displayModeBar": False})

        # Day counts below the chart
        day_counts = " · ".join(
            [f"**{row['day_name'][:3]}** ({int(row['count'])}d)" for _, row in dow_avg.iterrows()]
        )
        st.caption(f"Sample sizes: {day_counts}")

st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

# ── Section 4: Quick Navigation ──────────────────────────────────────────────

st.subheader("Dashboards")

nav_items = [
    ("pages/1_Daily_Sales.py", "Daily Sales", "Single-day deep dive with category and hourly breakdowns", "\U0001F4CA"),
    ("pages/2_Staffing_Rush.py", "Staffing & Rush", "Hourly heatmaps, rush prediction, SPLH analysis", "\U0001F465"),
    ("pages/3_Comps_Leakage.py", "Comps & Leakage", "Comp and void tracking by reason and employee", "\U0001F50D"),
    ("pages/4_Invoices.py", "Invoices", "Invoice entry, PDF parsing, vendor spend tracking", "\U0001F9FE"),
    ("pages/5_Inventory_Items.py", "Inventory Items", "Item catalog with par levels, costs, and vendors", "\U0001F4E6"),
    ("pages/6_Recipes.py", "Recipes", "Menu item recipes for theoretical inventory depletion", "\U0001F4D6"),
    ("pages/7_Inventory_Dashboard.py", "Inventory", "Reorder alerts, stock levels, vendor deadlines", "\U0001F4CB"),
    ("pages/8_Profitability.py", "Profitability", "Prime cost, pour cost, labor %, and full P&L", "\U0001F4B0"),
    ("pages/9_Product_Mix.py", "Product Mix", "Top sellers, menu engineering matrix, category mix", "\U0001F379"),
    ("pages/10_Operating_Expenses.py", "Operating Expenses", "Fixed costs, recurring expenses, budget tracking", "\U0001F3E2"),
    ("pages/11_Payroll.py", "Payroll", "Tip pool calculations, wages, and employee allocations", "\U0001F4B5"),
    ("pages/12_Import_Operations.py", "Import Operations", "Email import health, logs, and missing trading-day checks", "\U0001F4E5"),
    ("pages/13_COGS_Deep_Dive.py", "COGS Deep Dive", "COGS trends, margins, vendor spend, shrinkage, and cost data health", "\U0001F4C9"),
    ("pages/14_Scheduling.py", "Scheduling", "Weekly builder, roster, demand forecast, staffing advisor, templates", "\U0001F4C5"),
]

# 4 columns per row
rows = [nav_items[i:i + 4] for i in range(0, len(nav_items), 4)]
for row in rows:
    cols = st.columns(4)
    for i, item in enumerate(row):
        with cols[i]:
            with st.container(border=True):
                st.page_link(item[0], label=f"{item[3]} **{item[1]}**")
                st.caption(item[2])

st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

# ── Section 5: Alerts & Data Health ──────────────────────────────────────────

col_alerts, col_health = st.columns(2)

with col_alerts:
    st.subheader("Inventory Alerts")
    try:
        reorder_df = get_reorder_items()
        if not reorder_df.empty:
            st.warning(f"{len(reorder_df)} item(s) flagged for reorder")
            st.dataframe(
                reorder_df[["item_name", "category", "closing_qty", "par_level", "days_of_cover"]].head(10),
                hide_index=True,
                width="stretch",
            )
        else:
            st.success("All inventory levels OK")
    except Exception:
        st.info("Inventory ledger not yet populated")

with col_health:
    st.subheader("Data Coverage")
    st.markdown(f"""
| | |
|---|---|
| **Full Data Range** | {min_date.strftime('%b %d, %Y')} to {max_date.strftime('%b %d, %Y')} |
| **Selected Period** | {start_date.strftime('%b %d, %Y')} to {end_date.strftime('%b %d, %Y')} |
| **Trading Days** | {len(full_data)} |
""")

st.markdown("---")
st.caption("Bar Arbolada Analytics")
