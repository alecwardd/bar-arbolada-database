"""
Dashboard 1: Daily Sales Overview
==================================
- Single-day deep dive with comparisons
- Sales by category (pie + bar)
- Day-part breakdown (Happy Hour vs Close)
- Hourly sales bar chart
- Top sellers
- Comp/void summary
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, timedelta
import pandas as pd

from dashboards.data import (
    get_daily_sales,
    get_all_trading_days,
    get_daypart_sales,
    get_category_sales,
    get_hourly_sales,
    get_top_sellers,
    get_comp_daily_trend,
    get_void_daily_trend,
)

st.title("📊 Daily Sales Overview")

# ── Date Selection ───────────────────────────────────────────────────────────
# Single-day deep dive (not the shared range selector). Prefer the shared
# period's end date as the default when one is already chosen elsewhere.

available_days = get_all_trading_days()
if not available_days:
    st.warning("No sales data available. Import some CSVs first.")
    st.stop()

_default_idx = 0
_shared_end = st.session_state.get("shared_period_end")
if _shared_end in available_days:
    _default_idx = available_days.index(_shared_end)

selected_day = st.sidebar.selectbox(
    "Trading Day",
    available_days,
    index=_default_idx,
    format_func=lambda d: d.strftime("%a %b %d, %Y"),
)

# Get data for selected day
daily_df = get_daily_sales(selected_day, selected_day)
if daily_df.empty or daily_df.iloc[0]["net_sales"] is None:
    st.warning(f"No full sales data for {selected_day}. This day may only have check metrics from a multi-day report.")
    st.stop()

day = daily_df.iloc[0]

# ── Comparison: find same day last week ──────────────────────────────────────

compare_day = selected_day - timedelta(days=7)
compare_df = get_daily_sales(compare_day, compare_day)
has_compare = not compare_df.empty and compare_df.iloc[0]["net_sales"] is not None
compare = compare_df.iloc[0] if has_compare else None


def delta_str(current, previous, fmt="money"):
    """Format a delta comparison."""
    if previous is None or current is None:
        return None
    diff = float(current) - float(previous)
    if fmt == "money":
        sign = "-" if diff < 0 else ""
        return f"{sign}${abs(diff):,.0f} vs last week"
    elif fmt == "pct":
        pct = (diff / float(previous) * 100) if float(previous) != 0 else 0
        return f"{pct:+.1f}% vs last week"
    return f"{diff:+,.0f} vs last week"


# ── KPI Row ──────────────────────────────────────────────────────────────────

st.markdown("### Key Metrics")
c1, c2, c3, c4, c5 = st.columns(5)

with c1:
    st.metric(
        "Net Sales",
        f"${float(day['net_sales']):,.0f}",
        delta=delta_str(day["net_sales"], compare["net_sales"] if compare is not None else None) if has_compare else None,
    )

with c2:
    st.metric(
        "Gross Sales",
        f"${float(day['gross_sales']):,.0f}",
        delta=delta_str(day["gross_sales"], compare["gross_sales"] if compare is not None else None) if has_compare else None,
    )

with c3:
    st.metric(
        "Checks",
        f"{int(day['total_checks'] or 0):,}",
        delta=delta_str(day["total_checks"], compare["total_checks"] if compare is not None else None, "int") if has_compare else None,
    )

with c4:
    st.metric(
        "Total Tips",
        f"${float(day['total_tips'] or 0):,.0f}",
        delta=delta_str(day["total_tips"], compare["total_tips"] if compare is not None else None) if has_compare else None,
    )

with c5:
    st.metric(
        "Avg Check",
        f"${float(day['check_avg'] or 0):,.2f}",
        delta=delta_str(day["check_avg"], compare["check_avg"] if compare is not None else None, "pct") if has_compare else None,
    )

# ── Second KPI Row ──────────────────────────────────────────────────────────

c1, c2, c3, c4, c5 = st.columns(5)

with c1:
    st.metric("Total Tax", f"${float(day['total_tax'] or 0):,.2f}")

with c2:
    st.metric("Cash Payments", f"${float(day['cash_payments'] or 0):,.0f}")

with c3:
    st.metric("Credit Payments", f"${float(day['credit_payments'] or 0):,.0f}")

with c4:
    comps = float(day['total_comps'] or 0)
    voids = float(day['total_voids'] or 0)
    st.metric("Comps / Voids", f"${comps:,.0f} / ${voids:,.0f}")

with c5:
    tip_pct = (float(day['total_tips'] or 0) / float(day['net_sales'])) * 100 if float(day['net_sales'] or 0) > 0 else 0
    st.metric("Tip %", f"{tip_pct:.1f}%")

st.markdown("---")

# ── Charts Row 1: Categories + Dayparts ──────────────────────────────────────

col_left, col_right = st.columns(2)

with col_left:
    st.subheader("Sales by Category")
    cat_df = get_category_sales(selected_day)
    if not cat_df.empty:
        # Filter out "Total" rows and zero-sales categories
        cat_df = cat_df[~cat_df["category_name"].str.contains("Total", na=False)]
        cat_df = cat_df[cat_df["net_sales"] > 0]
        cat_df["net_sales"] = cat_df["net_sales"].astype(float)

        fig = px.pie(
            cat_df, values="net_sales", names="category_name",
            hole=0.4,
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        fig.update_traces(textposition="inside", textinfo="label+percent")
        fig.update_layout(
            showlegend=False,
            margin=dict(t=10, b=10, l=10, r=10),
            height=350,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No category data for this day.")

with col_right:
    st.subheader("Day-Part Breakdown")
    dp_df = get_daypart_sales(selected_day)
    if not dp_df.empty:
        dp_df = dp_df[dp_df["day_part"] != "None"]
        dp_df["net_sales"] = dp_df["net_sales"].astype(float)
        dp_df["checks"] = dp_df["checks"].fillna(0).astype(int)

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=dp_df["day_part"], y=dp_df["net_sales"],
            name="Net Sales", marker_color="#2d6a4f",
            text=[f"${v:,.0f}" for v in dp_df["net_sales"]],
            textposition="outside",
        ))
        fig.update_layout(
            yaxis_title="Net Sales ($)",
            height=350,
            margin=dict(t=10, b=10),
        )
        st.plotly_chart(fig, use_container_width=True)

        # Day-part detail table
        dp_display = dp_df[["day_part", "net_sales", "checks", "check_avg"]].copy()
        dp_display.columns = ["Day Part", "Net Sales", "Checks", "Check Avg"]
        dp_display["Net Sales"] = dp_display["Net Sales"].apply(lambda x: f"${x:,.2f}")
        dp_display["Check Avg"] = dp_display["Check Avg"].apply(lambda x: f"${float(x):,.2f}" if x else "—")
        st.dataframe(dp_display, hide_index=True, use_container_width=True)
    else:
        st.info("No day-part data for this day.")

st.markdown("---")

# ── Charts Row 2: Hourly Sales ───────────────────────────────────────────────

st.subheader("Hourly Sales Breakdown")
hourly_df = get_hourly_sales(selected_day)

if not hourly_df.empty:
    hourly_df["net_sales"] = hourly_df["net_sales"].astype(float)
    hourly_df["check_count"] = hourly_df["check_count"].astype(int)
    hourly_df["hour_label"] = hourly_df["hour_of_day"].apply(
        lambda h: f"{h % 12 or 12}{'am' if h < 12 else 'pm'}"
    )

    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=hourly_df["hour_label"],
        y=hourly_df["net_sales"],
        name="Net Sales",
        marker_color="#2d6a4f",
        yaxis="y",
    ))

    fig.add_trace(go.Scatter(
        x=hourly_df["hour_label"],
        y=hourly_df["check_count"],
        name="Checks",
        mode="lines+markers",
        marker=dict(color="#e76f51", size=8),
        line=dict(color="#e76f51", width=2),
        yaxis="y2",
    ))

    fig.update_layout(
        yaxis=dict(title="Net Sales ($)", side="left"),
        yaxis2=dict(title="Check Count", side="right", overlaying="y"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=400,
        margin=dict(t=30, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No hourly data for this day.")

st.markdown("---")

# ── Top Sellers ──────────────────────────────────────────────────────────────

st.subheader("Top Sellers")
top_df = get_top_sellers(trading_day=selected_day, limit=15)

if not top_df.empty:
    top_df["total_sold"] = top_df["total_sold"].astype(int)
    top_df["total_revenue"] = top_df["total_revenue"].astype(float)

    fig = px.bar(
        top_df.head(15),
        x="total_sold", y="item_name",
        orientation="h",
        color="category_name",
        text="total_sold",
        color_discrete_sequence=px.colors.qualitative.Set2,
    )
    fig.update_layout(
        yaxis=dict(autorange="reversed", title=""),
        xaxis_title="Quantity Sold",
        legend_title="Category",
        height=max(350, len(top_df) * 28),
        margin=dict(t=10, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No product mix data for this day.")

st.markdown("---")
st.caption(f"Data for {selected_day.strftime('%A, %B %d, %Y')}")
