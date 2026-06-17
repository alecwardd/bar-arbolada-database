"""
Dashboard 5: Comp & Leakage Tracking
======================================
- Comp $ by reason (bar chart + pie)
- Comp trend over time
- High-comp days flagged
- Comp by employee (who's authorizing)
- Void tracking with reasons
- Detailed drill-down tables
- Toggle: Revenue Lost vs True Cost (COGS)
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from datetime import date, timedelta

from src.analytics.queries import (
    get_sales_date_range,
    get_daily_sales,
    get_comp_summary_with_cost,
    get_comp_daily_trend_with_cost,
    get_comp_by_employee_with_cost,
    get_comps_with_cost,
    get_void_summary_with_cost,
    get_void_daily_trend_with_cost,
    get_voids_with_cost,
)

st.set_page_config(page_title="Comps & Leakage | Bar Arbolada", page_icon="🔍", layout="wide")
st.title("🔍 Comp & Leakage Tracking")

# ── Date Range ───────────────────────────────────────────────────────────────

try:
    min_date, max_date = get_sales_date_range()
except Exception:
    st.warning("No data available.")
    st.stop()

ROLLING_DAYS = 90
default_end = max_date
default_start = max(min_date, max_date - timedelta(days=ROLLING_DAYS - 1))

st.sidebar.markdown("### Date Range")
start = st.sidebar.date_input("Start", value=default_start, min_value=min_date, max_value=max_date)
end = st.sidebar.date_input("End", value=default_end, min_value=min_date, max_value=max_date)

# ── View Mode Toggle ─────────────────────────────────────────────────────────

st.sidebar.markdown("### View Mode")
view_mode = st.sidebar.radio(
    "Amount shown in charts & KPIs",
    ["Revenue Lost", "True Cost (COGS)"],
    help=(
        "**Revenue Lost** = menu price of comped items (what you gave away). "
        "**True Cost (COGS)** = actual ingredient/pour cost (what it cost you to make)."
    ),
)
use_true_cost = view_mode == "True Cost (COGS)"
amt_col = "total_true_cost" if use_true_cost else "total_amount"
amt_label = "True Cost" if use_true_cost else "Comp Amount"
void_amt_label = "True Cost" if use_true_cost else "Void Amount"

# ── Fetch Data (cost-aware variants) ─────────────────────────────────────────

comp_summary = get_comp_summary_with_cost(start, end)
void_summary = get_void_summary_with_cost(start, end)
comps_trend = get_comp_daily_trend_with_cost(start, end)
voids_trend = get_void_daily_trend_with_cost(start, end)
sales_df = get_daily_sales(start, end)
sales_with_data = sales_df[sales_df["net_sales"].notna()]

# ── KPI Row ──────────────────────────────────────────────────────────────────

total_comps_menu = float(comp_summary["total_amount"].sum()) if not comp_summary.empty else 0
total_comps_cost = float(comp_summary["total_true_cost"].sum()) if not comp_summary.empty else 0
total_voids_menu = float(void_summary["total_amount"].sum()) if not void_summary.empty else 0
total_voids_cost = float(void_summary["total_true_cost"].sum()) if not void_summary.empty else 0
comp_count = int(comp_summary["comp_count"].sum()) if not comp_summary.empty else 0
void_count = int(void_summary["void_count"].sum()) if not void_summary.empty else 0
total_net_sales = float(sales_with_data["net_sales"].sum()) if not sales_with_data.empty else 0

total_comps_display = total_comps_cost if use_true_cost else total_comps_menu
total_voids_display = total_voids_cost if use_true_cost else total_voids_menu
comp_pct = (total_comps_display / total_net_sales * 100) if total_net_sales > 0 else 0

comp_items_with_cost = int(comp_summary["items_with_cost"].sum()) if not comp_summary.empty else 0
comp_coverage_pct = (comp_items_with_cost / comp_count * 100) if comp_count > 0 else 0

c1, c2, c3, c4, c5, c6 = st.columns(6)
with c1:
    label = "Total Comps (COGS)" if use_true_cost else "Total Comps"
    st.metric(label, f"${total_comps_display:,.0f}")
with c2:
    st.metric("Comp Count", f"{comp_count:,}")
with c3:
    st.metric("Comp % of Sales", f"{comp_pct:.1f}%",
              help="Industry target: < 3%")
with c4:
    label = "Total Voids (COGS)" if use_true_cost else "Total Voids"
    st.metric(label, f"${total_voids_display:,.0f}")
with c5:
    st.metric("Void Count", f"{void_count:,}")
with c6:
    st.metric("COGS Coverage", f"{comp_coverage_pct:.0f}%",
              help=f"{comp_items_with_cost} of {comp_count} comp records have a known item cost in pos_items.")

if use_true_cost:
    st.info(
        f"**True Cost mode**: Amounts reflect the actual cost of goods (COGS) for each comped item. "
        f"Items without a known cost contribute $0, so totals represent a **floor estimate**. "
        f"Currently {comp_coverage_pct:.0f}% of comp records have COGS data. "
        f"(Revenue Lost view total: ${total_comps_menu:,.0f})"
    )

st.markdown("---")

# ── Tabs: Comps / Voids ─────────────────────────────────────────────────────

tab_comps, tab_voids = st.tabs(["🎫 Comps", "❌ Voids"])

# ════════════════════════════════════════════════════════════════════════════
# COMPS TAB
# ════════════════════════════════════════════════════════════════════════════

with tab_comps:
    if not comp_summary.empty:
        comp_summary["total_amount"] = comp_summary["total_amount"].astype(float)
        comp_summary["total_true_cost"] = comp_summary["total_true_cost"].astype(float)
        comp_summary["comp_count"] = comp_summary["comp_count"].astype(int)

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Comps by Reason")
            fig = px.bar(
                comp_summary,
                x=amt_col, y="comp_reason",
                orientation="h",
                text=comp_summary[amt_col].apply(lambda x: f"${x:,.0f}"),
                color=amt_col,
                color_continuous_scale="Reds",
            )
            fig.update_layout(
                yaxis=dict(autorange="reversed", title=""),
                xaxis_title=f"Total {amt_label} ($)",
                showlegend=False,
                coloraxis_showscale=False,
                height=max(300, len(comp_summary) * 35),
                margin=dict(t=10, b=10, l=10, r=10),
            )
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            st.subheader("Comp Distribution")
            fig2 = px.pie(
                comp_summary, values=amt_col, names="comp_reason",
                hole=0.4,
                color_discrete_sequence=px.colors.qualitative.Pastel,
            )
            fig2.update_traces(textposition="inside", textinfo="percent+label")
            fig2.update_layout(
                showlegend=False,
                height=350,
                margin=dict(t=10, b=10, l=10, r=10),
            )
            st.plotly_chart(fig2, use_container_width=True)

        st.markdown("---")

        # ── Comp Trend ───────────────────────────────────────────────────────

        st.subheader("Daily Comp Trend")
        if not comps_trend.empty:
            comps_trend["total_amount"] = comps_trend["total_amount"].astype(float)
            comps_trend["total_true_cost"] = comps_trend["total_true_cost"].astype(float)
            comps_trend["trading_day"] = pd.to_datetime(comps_trend["trading_day"])

            trend_vals = comps_trend[amt_col]
            avg_comp = trend_vals.mean()
            comps_trend["is_high"] = trend_vals > avg_comp * 2

            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=comps_trend["trading_day"],
                y=trend_vals,
                marker_color=comps_trend["is_high"].map({True: "#e63946", False: "#457b9d"}),
                text=trend_vals.apply(lambda x: f"${x:,.0f}"),
                textposition="outside",
            ))
            fig.add_hline(
                y=avg_comp, line_dash="dash", line_color="orange",
                annotation_text=f"Avg: ${avg_comp:,.0f}",
            )
            if avg_comp > 0:
                fig.add_hline(
                    y=avg_comp * 2, line_dash="dot", line_color="red",
                    annotation_text=f"Alert: ${avg_comp * 2:,.0f}",
                )
            fig.update_layout(
                yaxis_title=f"{amt_label} ($)",
                showlegend=False,
                height=350,
                margin=dict(t=10, b=10),
            )
            st.plotly_chart(fig, use_container_width=True)

            high_days = comps_trend[comps_trend["is_high"]]
            if not high_days.empty:
                st.warning(
                    f"**{len(high_days)} high-comp day(s) detected** (> 2x average of ${avg_comp:,.0f}): "
                    + ", ".join(high_days["trading_day"].dt.strftime("%b %d").tolist())
                )

        st.markdown("---")

        # ── Comp by Employee ─────────────────────────────────────────────────

        st.subheader("Comps by Authorizing Employee")
        emp_df = get_comp_by_employee_with_cost(start, end)
        if not emp_df.empty:
            emp_df["total_amount"] = emp_df["total_amount"].astype(float)
            emp_df["total_true_cost"] = emp_df["total_true_cost"].astype(float)
            emp_df["comp_count"] = emp_df["comp_count"].astype(int)

            fig = px.bar(
                emp_df, x="authorized_by", y=amt_col,
                text=emp_df[amt_col].apply(lambda x: f"${x:,.0f}"),
                color="comp_count",
                color_continuous_scale="Blues",
            )
            fig.update_layout(
                xaxis_title="Employee",
                yaxis_title=f"Total {amt_label} ($)",
                coloraxis_colorbar_title="# Comps",
                height=350,
                margin=dict(t=10, b=10),
            )
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("---")

        # ── Detailed Comp Table ──────────────────────────────────────────────

        st.subheader("All Comp Records")
        all_comps = get_comps_with_cost(start, end)
        if not all_comps.empty:
            display_comps = all_comps[["trading_day", "comp_reason", "item_name",
                                       "amount", "true_cost", "check_owner",
                                       "authorized_by", "check_number"]].copy()
            display_comps["amount"] = display_comps["amount"].astype(float)
            display_comps["true_cost"] = pd.to_numeric(display_comps["true_cost"], errors="coerce")
            display_comps.columns = ["Date", "Reason", "Item", "Menu Price",
                                     "True Cost", "Server", "Auth By", "Check #"]
            st.dataframe(
                display_comps,
                hide_index=True,
                use_container_width=True,
                height=400,
            )
    else:
        st.info("No comp data for this date range.")

# ════════════════════════════════════════════════════════════════════════════
# VOIDS TAB
# ════════════════════════════════════════════════════════════════════════════

with tab_voids:
    if not void_summary.empty:
        void_summary["total_amount"] = void_summary["total_amount"].astype(float)
        void_summary["total_true_cost"] = void_summary["total_true_cost"].astype(float)
        void_summary["void_count"] = void_summary["void_count"].astype(int)

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Voids by Reason")
            fig = px.bar(
                void_summary,
                x=amt_col, y="void_reason",
                orientation="h",
                text=void_summary[amt_col].apply(lambda x: f"${x:,.0f}"),
                color=amt_col,
                color_continuous_scale="Oranges",
            )
            fig.update_layout(
                yaxis=dict(autorange="reversed", title=""),
                xaxis_title=f"Total {void_amt_label} ($)",
                showlegend=False,
                coloraxis_showscale=False,
                height=max(250, len(void_summary) * 40),
                margin=dict(t=10, b=10, l=10, r=10),
            )
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            st.subheader("Void Distribution")
            fig2 = px.pie(
                void_summary, values=amt_col, names="void_reason",
                hole=0.4,
                color_discrete_sequence=px.colors.qualitative.Pastel2,
            )
            fig2.update_traces(textposition="inside", textinfo="percent+label")
            fig2.update_layout(
                showlegend=False,
                height=350,
                margin=dict(t=10, b=10, l=10, r=10),
            )
            st.plotly_chart(fig2, use_container_width=True)

        st.markdown("---")

        # ── Void Trend ───────────────────────────────────────────────────────

        st.subheader("Daily Void Trend")
        if not voids_trend.empty:
            voids_trend["total_amount"] = voids_trend["total_amount"].astype(float)
            voids_trend["total_true_cost"] = voids_trend["total_true_cost"].astype(float)
            voids_trend["trading_day"] = pd.to_datetime(voids_trend["trading_day"])

            void_trend_vals = voids_trend[amt_col]

            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=voids_trend["trading_day"],
                y=void_trend_vals,
                marker_color="#e76f51",
                text=void_trend_vals.apply(lambda x: f"${x:,.0f}"),
                textposition="outside",
            ))
            avg_void = void_trend_vals.mean()
            fig.add_hline(
                y=avg_void, line_dash="dash", line_color="orange",
                annotation_text=f"Avg: ${avg_void:,.0f}",
            )
            fig.update_layout(
                yaxis_title=f"{void_amt_label} ($)",
                showlegend=False,
                height=350,
                margin=dict(t=10, b=10),
            )
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("---")

        # ── Detailed Void Table ──────────────────────────────────────────────

        st.subheader("All Void Records")
        all_voids = get_voids_with_cost(start, end)
        if not all_voids.empty:
            display_voids = all_voids[["trading_day", "void_reason", "item_name",
                                       "amount", "true_cost", "check_owner",
                                       "authorized_by", "check_number"]].copy()
            display_voids["amount"] = display_voids["amount"].astype(float)
            display_voids["true_cost"] = pd.to_numeric(display_voids["true_cost"], errors="coerce")
            display_voids.columns = ["Date", "Reason", "Item", "Menu Price",
                                     "True Cost", "Server", "Auth By", "Check #"]
            st.dataframe(
                display_voids,
                hide_index=True,
                use_container_width=True,
                height=400,
            )
    else:
        st.info("No void data for this date range.")

st.markdown("---")
st.caption("Comp & Leakage Tracking | Bar Arbolada Analytics")
