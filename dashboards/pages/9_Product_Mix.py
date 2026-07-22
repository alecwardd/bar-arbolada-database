"""
Dashboard 4: Product Mix & Menu Engineering
==============================================
- Top sellers by quantity and revenue
- Contribution margin per item
- Menu engineering matrix (Stars, Puzzles, Plow Horses, Dogs)
- Category mix breakdown
- Item trending analysis
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, timedelta

from src.analytics.queries import (
    get_sales_date_range,
    get_full_product_mix,
    get_top_sellers,
    get_category_mix_summary,
    get_product_mix_trend,
)
from dashboards.period import period_selector

st.set_page_config(page_title="Product Mix | Bar Arbolada", page_icon="🍔", layout="wide")
st.title("🍔 Product Mix & Menu Engineering")


# ── Date Range ────────────────────────────────────────────────────────────

try:
    min_date, max_date = get_sales_date_range()
except Exception:
    st.warning("No data available.")
    st.stop()

# Shared, session-scoped period selector (same default across all pages).
_period = period_selector(min_date, max_date)
start, end = _period.start, _period.end


# ── Load Data ─────────────────────────────────────────────────────────────

mix_df = get_full_product_mix(start, end)

if mix_df.empty:
    st.warning("No product mix data for this date range.")
    st.stop()


# ── Prep Data ─────────────────────────────────────────────────────────────

for col in ["total_sold", "net_revenue", "total_cost", "gross_profit",
            "avg_price", "revenue_per_unit", "margin_per_unit", "cost_pct"]:
    if col in mix_df.columns:
        mix_df[col] = pd.to_numeric(mix_df[col], errors="coerce").fillna(0)

mix_df["total_sold"] = mix_df["total_sold"].astype(int)


# ═══════════════════════════════════════════════════════════════════════════
# KPIs
# ═══════════════════════════════════════════════════════════════════════════

st.markdown("---")

total_items_sold = mix_df["total_sold"].sum()
total_revenue = mix_df["net_revenue"].sum()
unique_items = len(mix_df)
avg_item_price = total_revenue / total_items_sold if total_items_sold > 0 else 0
top_item = mix_df.iloc[0]["item_name"] if len(mix_df) > 0 else "N/A"
top_item_rev = mix_df.iloc[0]["net_revenue"] if len(mix_df) > 0 else 0

k1, k2, k3, k4 = st.columns(4)
with k1:
    st.metric("Items Sold", f"{total_items_sold:,}")
with k2:
    st.metric("Revenue", f"${total_revenue:,.0f}")
with k3:
    st.metric("Unique Items", unique_items)
with k4:
    st.metric("Top Seller", top_item)

st.markdown("---")


# ═══════════════════════════════════════════════════════════════════════════
# TABS
# ═══════════════════════════════════════════════════════════════════════════

tab_top, tab_matrix, tab_category, tab_detail = st.tabs([
    "🏆 Top Sellers",
    "📐 Menu Matrix",
    "📂 Category Mix",
    "🔍 Item Detail",
])


# ═══════════════════════════════════════════════════════════════════════════
# TAB 1: TOP SELLERS
# ═══════════════════════════════════════════════════════════════════════════

with tab_top:
    col_metric, col_limit = st.columns([2, 1])
    with col_metric:
        sort_by = st.radio("Rank by:", ["Quantity Sold", "Revenue"],
                           horizontal=True)
    with col_limit:
        top_n = st.slider("Show top N items:", 10, 50, 20)

    sort_col = "total_sold" if sort_by == "Quantity Sold" else "net_revenue"
    top_df = mix_df.nlargest(top_n, sort_col)

    # Bar chart
    fig = px.bar(
        top_df,
        x="item_name",
        y=sort_col,
        color="category_name",
        labels={sort_col: sort_by, "item_name": "Item", "category_name": "Category"},
        color_discrete_sequence=px.colors.qualitative.Set2,
    )
    fig.update_layout(
        height=500,
        xaxis_tickangle=-45,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(b=150),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Table
    display = top_df[["item_name", "category_name", "total_sold",
                       "net_revenue", "avg_price", "revenue_per_unit"]].copy()
    display["net_revenue"] = display["net_revenue"].apply(lambda x: f"${x:,.2f}")
    display["avg_price"] = display["avg_price"].apply(lambda x: f"${x:.2f}")
    display["revenue_per_unit"] = display["revenue_per_unit"].apply(lambda x: f"${x:.2f}")
    display.columns = ["Item", "Category", "Qty Sold", "Net Revenue",
                        "Avg Price", "Rev/Unit"]
    st.dataframe(display, hide_index=True, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════
# TAB 2: MENU ENGINEERING MATRIX
# ═══════════════════════════════════════════════════════════════════════════

with tab_matrix:
    st.subheader("Menu Engineering Matrix")
    st.caption(
        "Classic Boston Consulting Group matrix adapted for restaurants. "
        "Items are classified by popularity (volume) and profitability (margin)."
    )

    # Filter to items with meaningful data
    matrix_df = mix_df[
        (mix_df["total_sold"] > 0) & (mix_df["net_revenue"] > 0)
    ].copy()

    if len(matrix_df) < 3:
        st.info("Need more items with sales data to build the matrix.")
    else:
        # Category filter
        cat_options = sorted(matrix_df["category_name"].dropna().unique())
        selected_cats = st.multiselect("Filter categories:", cat_options, default=[])
        if selected_cats:
            matrix_df = matrix_df[matrix_df["category_name"].isin(selected_cats)]

        # Calculate medians for quadrant lines
        median_qty = matrix_df["total_sold"].median()
        median_margin = matrix_df["revenue_per_unit"].median()

        # Classify items
        def classify(row):
            high_pop = row["total_sold"] >= median_qty
            high_margin = row["revenue_per_unit"] >= median_margin
            if high_pop and high_margin:
                return "⭐ Star"
            elif not high_pop and high_margin:
                return "🧩 Puzzle"
            elif high_pop and not high_margin:
                return "🐴 Plow Horse"
            else:
                return "🐕 Dog"

        matrix_df["quadrant"] = matrix_df.apply(classify, axis=1)

        color_map = {
            "⭐ Star": "#22c55e",
            "🧩 Puzzle": "#3b82f6",
            "🐴 Plow Horse": "#f59e0b",
            "🐕 Dog": "#ef4444",
        }

        fig = px.scatter(
            matrix_df,
            x="total_sold",
            y="revenue_per_unit",
            color="quadrant",
            size="net_revenue",
            hover_name="item_name",
            hover_data=["category_name", "net_revenue", "avg_price"],
            color_discrete_map=color_map,
            labels={
                "total_sold": "Popularity (Qty Sold)",
                "revenue_per_unit": "Revenue per Unit ($)",
            },
        )

        # Add median lines
        fig.add_vline(x=median_qty, line_dash="dash", line_color="gray",
                      annotation_text=f"Median qty: {median_qty:.0f}")
        fig.add_hline(y=median_margin, line_dash="dash", line_color="gray",
                      annotation_text=f"Median rev/unit: ${median_margin:.2f}")

        fig.update_layout(
            height=550,
            legend=dict(orientation="h", yanchor="bottom", y=1.02,
                        title="Quadrant"),
        )
        st.plotly_chart(fig, use_container_width=True)

        # Quadrant summary
        st.markdown("#### Quadrant Summary")
        quad_cols = st.columns(4)
        for i, (quad_name, desc) in enumerate([
            ("⭐ Star", "High volume, high margin — **protect & promote**"),
            ("🧩 Puzzle", "Low volume, high margin — **market harder**"),
            ("🐴 Plow Horse", "High volume, low margin — **raise prices or reduce cost**"),
            ("🐕 Dog", "Low volume, low margin — **consider removing**"),
        ]):
            quad_items = matrix_df[matrix_df["quadrant"] == quad_name]
            with quad_cols[i]:
                st.markdown(f"**{quad_name}**")
                st.caption(desc)
                st.metric("Items", len(quad_items))
                if not quad_items.empty:
                    top_3 = quad_items.nlargest(3, "net_revenue")["item_name"].tolist()
                    for item in top_3:
                        st.markdown(f"- {item}")


# ═══════════════════════════════════════════════════════════════════════════
# TAB 3: CATEGORY MIX
# ═══════════════════════════════════════════════════════════════════════════

with tab_category:
    st.subheader("Sales Mix by Category")

    # Category revenue breakdown
    cat_revenue = mix_df.groupby("category_name").agg(
        items=("item_name", "count"),
        total_qty=("total_sold", "sum"),
        net_revenue=("net_revenue", "sum"),
        avg_price=("avg_price", "mean"),
    ).reset_index().sort_values("net_revenue", ascending=False)

    if not cat_revenue.empty:
        cat_revenue["revenue_pct"] = (
            cat_revenue["net_revenue"] / cat_revenue["net_revenue"].sum() * 100
        ).round(1)

        c1, c2 = st.columns(2)

        with c1:
            fig = px.pie(
                cat_revenue,
                values="net_revenue",
                names="category_name",
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            fig.update_traces(textposition="inside", textinfo="percent+label")
            fig.update_layout(height=400, showlegend=False,
                              title="Revenue Share")
            st.plotly_chart(fig, use_container_width=True)

        with c2:
            fig2 = px.pie(
                cat_revenue,
                values="total_qty",
                names="category_name",
                color_discrete_sequence=px.colors.qualitative.Pastel,
            )
            fig2.update_traces(textposition="inside", textinfo="percent+label")
            fig2.update_layout(height=400, showlegend=False,
                              title="Volume Share")
            st.plotly_chart(fig2, use_container_width=True)

        # Table
        display = cat_revenue.copy()
        display["net_revenue"] = display["net_revenue"].apply(lambda x: f"${x:,.2f}")
        display["avg_price"] = display["avg_price"].apply(lambda x: f"${x:.2f}")
        display["revenue_pct"] = display["revenue_pct"].apply(lambda x: f"{x:.1f}%")
        display.columns = ["Category", "Unique Items", "Qty Sold",
                           "Net Revenue", "Avg Price", "% of Revenue"]
        st.dataframe(display, hide_index=True, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════
# TAB 4: ITEM DETAIL
# ═══════════════════════════════════════════════════════════════════════════

with tab_detail:
    st.subheader("Item Deep Dive")

    item_names = mix_df["item_name"].tolist()
    selected_item = st.selectbox("Select an item:", item_names)

    if selected_item:
        item_row = mix_df[mix_df["item_name"] == selected_item].iloc[0]

        # Item KPIs
        ik1, ik2, ik3, ik4 = st.columns(4)
        with ik1:
            st.metric("Qty Sold", f"{int(item_row['total_sold']):,}")
        with ik2:
            st.metric("Net Revenue", f"${item_row['net_revenue']:,.2f}")
        with ik3:
            st.metric("Avg Price", f"${item_row['avg_price']:.2f}")
        with ik4:
            if item_row["cost_pct"] > 0:
                st.metric("Cost %", f"{item_row['cost_pct']:.1f}%")
            else:
                st.metric("Cost %", "N/A")

        st.markdown(f"**Category:** {item_row['category_name']}")

        # Daily trend (if single-day data exists)
        trend_df = get_product_mix_trend(selected_item, start, end)
        if not trend_df.empty:
            trend_df["qty_sold"] = trend_df["qty_sold"].astype(int)
            trend_df["net_sales"] = trend_df["net_sales"].astype(float)

            st.markdown("---")
            st.markdown("#### Daily Sales Trend")

            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=trend_df["trading_day"],
                y=trend_df["qty_sold"],
                name="Qty Sold",
                marker_color="#3b82f6",
            ))
            fig.update_layout(height=300, yaxis_title="Qty Sold")
            st.plotly_chart(fig, use_container_width=True)

            # Trend table
            display = trend_df[["trading_day", "qty_sold", "net_sales"]].copy()
            display["net_sales"] = display["net_sales"].apply(lambda x: f"${x:,.2f}")
            display.columns = ["Date", "Qty", "Net Sales"]
            st.dataframe(display, hide_index=True, use_container_width=True)
        else:
            st.info("Daily trend data not available (requires single-day product mix reports).")

    # Full product mix table
    st.markdown("---")
    st.subheader("Full Product Mix Table")

    display = mix_df[["item_name", "category_name", "total_sold", "net_revenue",
                       "avg_price", "revenue_per_unit", "cost_pct"]].copy()
    display["net_revenue"] = display["net_revenue"].apply(lambda x: f"${x:,.2f}")
    display["avg_price"] = display["avg_price"].apply(lambda x: f"${x:.2f}")
    display["revenue_per_unit"] = display["revenue_per_unit"].apply(lambda x: f"${x:.2f}")
    display["cost_pct"] = display["cost_pct"].apply(
        lambda x: f"{x:.1f}%" if x > 0 else "—"
    )
    display.columns = ["Item", "Category", "Qty Sold", "Net Revenue",
                        "Avg Price", "Rev/Unit", "Cost %"]
    st.dataframe(display, hide_index=True, use_container_width=True, height=400)


st.markdown("---")
st.caption("Product Mix & Menu Engineering | Bar Arbolada Analytics")
