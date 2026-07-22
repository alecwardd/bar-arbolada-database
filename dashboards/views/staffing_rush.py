"""
Dashboard 1B: Staffing & Rush Analysis
========================================
- Hourly heatmap by day-of-week (avg revenue, checks)
- Rush prediction: rolling average vs actuals
- Labor vs sales overlay
- SPLH (Sales Per Labor Hour) by hour
- Shift cut recommendations
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import numpy as np
from datetime import date, timedelta

from src.analytics.queries import (
    get_sales_date_range,
    get_hourly_heatmap_data,
    get_hourly_trend,
    get_daily_labor,
    get_daily_sales,
    get_hourly_labor,
)

st.title("👥 Staffing & Rush Analysis")
st.caption(
    "**Historical** view: when you were busy and how productive labor was "
    "(sales per labor hour). Forward staffing plans live on **Scheduling**; the "
    "labor-cost lens lives on **Profitability**."
)

# ── Date Range ───────────────────────────────────────────────────────────────

try:
    min_date, max_date = get_sales_date_range()
except Exception:
    st.warning("No data available.")
    st.stop()

# Default to rolling 90 days (or full range if data spans < 90 days)
ROLLING_DAYS = 90
default_end = max_date
default_start = max(min_date, max_date - timedelta(days=ROLLING_DAYS - 1))

st.sidebar.markdown("### Date Range")
start = st.sidebar.date_input("Start", value=default_start, min_value=min_date, max_value=max_date)
end = st.sidebar.date_input("End", value=default_end, min_value=min_date, max_value=max_date)

# ── Hourly Heatmap by Day of Week ────────────────────────────────────────────

st.subheader("Hourly Sales Heatmap by Day of Week")
st.caption("Average net sales per hour, grouped by day of week. Brighter = busier.")

heatmap_df = get_hourly_heatmap_data(start, end)

if not heatmap_df.empty:
    # Build pivot table: rows = day of week, cols = hour
    dow_order = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    heatmap_df["dow_name"] = heatmap_df["dow_name"].str.strip()

    metric = st.radio(
        "Heatmap metric",
        ["Avg Net Sales", "Avg Checks"],
        horizontal=True,
    )

    metric_col = {
        "Avg Net Sales": "avg_net_sales",
        "Avg Checks": "avg_checks",
    }[metric]

    # Filter to business hours only (11am - 2am = hours 11-23, 0-1)
    biz_hours = list(range(11, 24)) + [0, 1, 2]
    hm = heatmap_df[heatmap_df["hour_of_day"].isin(biz_hours)].copy()
    hm[metric_col] = hm[metric_col].astype(float).round(0)

    pivot = hm.pivot_table(
        index="dow_name", columns="hour_of_day",
        values=metric_col, aggfunc="mean",
    )

    # Reindex to proper day order (only include days that exist)
    existing_days = [d for d in dow_order if d in pivot.index]
    pivot = pivot.reindex(existing_days)

    # Reindex columns to business hours order
    existing_hours = [h for h in biz_hours if h in pivot.columns]
    pivot = pivot[existing_hours]

    hour_labels = [f"{h % 12 or 12}{'a' if h < 12 else 'p'}" for h in existing_hours]

    fig = go.Figure(data=go.Heatmap(
        z=pivot.values,
        x=hour_labels,
        y=pivot.index.tolist(),
        colorscale="YlOrRd",
        text=pivot.values.round(0),
        texttemplate="%{text:.0f}",
        textfont={"size": 10},
        hovertemplate="Day: %{y}<br>Hour: %{x}<br>Value: %{z:.1f}<extra></extra>",
    ))
    fig.update_layout(
        xaxis_title="Hour of Day",
        yaxis_title="",
        height=300,
        margin=dict(t=10, b=30, l=50, r=10),
        yaxis=dict(autorange="reversed"),
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No hourly data available for this range.")

st.markdown("---")

# ── Rush Prediction: Rolling Average vs Recent ───────────────────────────────

st.subheader("Rush Prediction: Rolling Average by Hour")
st.caption("Shows average sales velocity by hour across the selected range. Use this to predict busy periods.")

if not heatmap_df.empty:
    # Aggregate all days into avg by hour
    hourly_avg = heatmap_df.groupby("hour_of_day").agg(
        avg_sales=("avg_net_sales", "mean"),
        avg_checks=("avg_checks", "mean"),
        days_sampled=("num_days", "sum"),
    ).reset_index()

    # Filter to business hours
    hourly_avg = hourly_avg[hourly_avg["hour_of_day"].isin(biz_hours)]
    # Sort by business hour order
    hour_order_map = {h: i for i, h in enumerate(biz_hours)}
    hourly_avg["sort_key"] = hourly_avg["hour_of_day"].map(hour_order_map)
    hourly_avg = hourly_avg.sort_values("sort_key")

    hourly_avg["hour_label"] = hourly_avg["hour_of_day"].apply(
        lambda h: f"{h % 12 or 12}{'am' if h < 12 else 'pm'}"
    )
    hourly_avg["avg_sales"] = hourly_avg["avg_sales"].astype(float)
    hourly_avg["avg_checks"] = hourly_avg["avg_checks"].astype(float)

    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=hourly_avg["hour_label"],
        y=hourly_avg["avg_sales"].round(0),
        name="Avg Net Sales",
        marker_color="#2d6a4f",
        text=hourly_avg["avg_sales"].round(0).astype(int),
        textposition="outside",
    ))

    fig.add_trace(go.Scatter(
        x=hourly_avg["hour_label"],
        y=hourly_avg["avg_checks"].round(1),
        name="Avg Checks",
        mode="lines+markers",
        marker=dict(color="#e76f51", size=8),
        line=dict(color="#e76f51", width=2.5),
        yaxis="y2",
    ))

    fig.update_layout(
        yaxis=dict(title="Avg Net Sales ($)", side="left"),
        yaxis2=dict(title="Avg Check Count", side="right", overlaying="y"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=400,
        margin=dict(t=30, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)

st.markdown("---")

# ── SPLH: Sales Per Labor Hour ───────────────────────────────────────────────

st.subheader("Sales Per Labor Hour (SPLH)")
st.caption("How efficiently is revenue being generated relative to labor scheduled?")

labor_df = get_daily_labor(start, end)
sales_df = get_daily_sales(start, end)

if not labor_df.empty and not sales_df.empty:
    sales_with_data = sales_df[sales_df["net_sales"].notna()].copy()
    sales_with_data["trading_day"] = pd.to_datetime(sales_with_data["trading_day"])
    labor_df["trading_day"] = pd.to_datetime(labor_df["trading_day"])

    merged = pd.merge(
        sales_with_data[["trading_day", "net_sales"]],
        labor_df[["trading_day", "total_hours", "total_labor_cost"]],
        on="trading_day", how="inner",
    )

    if not merged.empty:
        merged["net_sales"] = merged["net_sales"].astype(float)
        merged["total_hours"] = merged["total_hours"].astype(float)
        merged["total_labor_cost"] = merged["total_labor_cost"].astype(float)
        # Exclude closed days (zero sales) from all SPLH calculations and charts
        merged = merged[merged["net_sales"] > 0].copy()
        if merged.empty:
            st.info("No open days (all days had zero sales) in this range.")
        else:
            merged["labor_pct"] = (merged["total_labor_cost"] / merged["net_sales"] * 100).round(1)
            # SPLH: only defined when total_hours > 0
            merged["splh"] = np.where(
                merged["total_hours"] > 0,
                (merged["net_sales"] / merged["total_hours"]).round(2),
                np.nan,
            )

            # KPI row (open days only; SPLH mean skips any NaN from zero-hours days)
            splh_mean = merged["splh"].mean()
            labor_pct_mean = merged["labor_pct"].mean()
            splh_str = f"${splh_mean:,.0f}" if pd.notna(splh_mean) and not np.isinf(splh_mean) else "—"
            labor_pct_str = f"{labor_pct_mean:.1f}%" if pd.notna(labor_pct_mean) and not np.isinf(labor_pct_mean) else "—"

            st.caption("Metrics and charts exclude closed days (zero sales).")
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.metric("Avg SPLH", splh_str)
            with c2:
                st.metric("Avg Labor Cost/Day", f"${merged['total_labor_cost'].mean():,.0f}")
            with c3:
                st.metric("Avg Hours/Day", f"{merged['total_hours'].mean():,.1f}")
            with c4:
                st.metric("Avg Labor %", labor_pct_str)

            # SPLH chart (open days only; NaN SPLH when hours=0 omitted from bars)
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=merged["trading_day"],
                y=merged["splh"],
                name="SPLH",
                marker_color="#2d6a4f",
            ))
            if pd.notna(splh_mean) and not np.isinf(splh_mean):
                fig.add_hline(
                    y=float(splh_mean),
                    line_dash="dash", line_color="red",
                    annotation_text=f"Avg: ${splh_mean:,.0f}",
                )
            fig.update_layout(
                yaxis_title="Sales Per Labor Hour ($)",
                xaxis_title="Trading Day",
                height=350,
                margin=dict(t=10, b=10),
            )
            st.plotly_chart(fig, use_container_width=True)

            # Sales vs Labor overlay (open days only)
            st.subheader("Net Sales vs Labor Cost")
            fig2 = go.Figure()
            fig2.add_trace(go.Bar(
                x=merged["trading_day"], y=merged["net_sales"],
                name="Net Sales", marker_color="#2d6a4f", opacity=0.7,
            ))
            fig2.add_trace(go.Bar(
                x=merged["trading_day"], y=merged["total_labor_cost"],
                name="Labor Cost", marker_color="#e76f51", opacity=0.7,
            ))
            fig2.update_layout(
                barmode="group",
                yaxis_title="Amount ($)",
                height=350,
                margin=dict(t=10, b=10),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("No overlapping sales + labor data found.")
else:
    st.info("Labor or sales data not available for this range.")

st.markdown("---")

# ── Peak Hours Summary Table ─────────────────────────────────────────────────

st.subheader("Peak Hours Summary")
st.caption("Busiest hours based on average checks and revenue.")

if not heatmap_df.empty:
    summary = heatmap_df.copy()
    summary["avg_net_sales"] = summary["avg_net_sales"].astype(float)
    summary["avg_checks"] = summary["avg_checks"].astype(float)

    # Top 10 busiest (dow, hour) combos
    top_combos = summary.nlargest(10, "avg_net_sales")
    top_combos["hour_label"] = top_combos["hour_of_day"].apply(
        lambda h: f"{h % 12 or 12}:00 {'AM' if h < 12 else 'PM'}"
    )

    display = top_combos[["dow_name", "hour_label", "avg_net_sales", "avg_checks"]].copy()
    display.columns = ["Day", "Hour", "Avg Sales", "Avg Checks"]
    display["Avg Sales"] = display["Avg Sales"].apply(lambda x: f"${x:,.0f}")
    display["Avg Checks"] = display["Avg Checks"].apply(lambda x: f"{x:.1f}")

    st.dataframe(display, hide_index=True, use_container_width=True)

st.markdown("---")
st.caption("Staffing & Rush Analysis | Bar Arbolada Analytics")
