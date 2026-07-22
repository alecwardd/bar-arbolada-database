"""
Dashboard 13: COGS Deep Dive
==============================
Granular cost-of-goods analysis: COGS trends, category breakdown,
item-level margins, vendor spend, shrinkage/variance, and data health.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import date

from src.analytics.queries import (
    get_cogs_trend,
    get_cogs_vs_purchases,
    get_cogs_by_category_trend,
    get_category_profitability,
    get_top_cost_items,
    get_worst_margin_items,
    get_cost_coverage_gaps,
    get_vendor_spend_trend,
    get_vendor_spend_detail,
    get_invoice_totals,
    get_vendor_names,
    get_shrinkage_summary,
    get_high_variance_items,
    get_adjustment_summary,
    get_adjustment_trend,
    get_cost_data_health,
    get_cost_outlier_items,
)
from dashboards.data import get_sales_date_range, get_full_pnl  # cached
from dashboards.period import period_selector

st.set_page_config(page_title="COGS Deep Dive | Bar Arbolada", page_icon="📉", layout="wide")
st.title("📉 COGS Deep Dive")


# ── Date Range ────────────────────────────────────────────────────────────

min_date, max_date = get_sales_date_range()

# Shared, session-scoped period selector (same default across all pages).
_period = period_selector(min_date, max_date)
start, end = _period.start, _period.end

num_days = (end - start).days + 1


# ── Load P&L for headline KPIs ───────────────────────────────────────────

pnl = get_full_pnl(start, end)
total_cogs = pnl["cogs"]
net_sales = pnl["net_sales"]
cogs_pct = (total_cogs / net_sales * 100) if net_sales > 0 else 0

# Actual purchases from invoices for the period
cvp = get_cogs_vs_purchases(start, end)
total_purchases = float(cvp["actual_purchases"].sum()) if not cvp.empty else 0
theo_vs_actual_gap = total_purchases - total_cogs

avg_daily_cogs = total_cogs / num_days if num_days > 0 else 0

health = get_cost_data_health(start, end)
coverage_pct = (
    health["items_with_cost"] / health["total_items"] * 100
    if health["total_items"] > 0 else 0
)


# ═══════════════════════════════════════════════════════════════════════════
# KPIs
# ═══════════════════════════════════════════════════════════════════════════

st.markdown("---")

k1, k2, k3, k4, k5, k6 = st.columns(6)
with k1:
    st.metric("Total COGS", f"${total_cogs:,.0f}")
    st.caption("Theoretical (product mix)")
with k2:
    st.metric(
        "COGS %",
        f"{cogs_pct:.1f}%",
        delta=f"{'Good' if cogs_pct < 30 else 'High'}" if cogs_pct > 0 else None,
        delta_color="normal" if cogs_pct < 30 else "inverse",
    )
    st.caption("Target: < 30%")
with k3:
    st.metric("Total Purchases", f"${total_purchases:,.0f}")
    st.caption("Actual invoice spend")
with k4:
    st.metric(
        "Purchase Gap",
        f"${theo_vs_actual_gap:,.0f}",
        delta="Under" if theo_vs_actual_gap < 0 else "Over",
        delta_color="normal" if theo_vs_actual_gap <= 0 else "inverse",
    )
    st.caption("Purchases − Theo COGS")
with k5:
    st.metric("Avg Daily COGS", f"${avg_daily_cogs:,.0f}")
with k6:
    st.metric(
        "Cost Coverage",
        f"{coverage_pct:.0f}%",
        delta=f"{health['items_with_cost']}/{health['total_items']} items",
    )
    st.caption("Items with cost data")

st.markdown("---")


# ═══════════════════════════════════════════════════════════════════════════
# TABS
# ═══════════════════════════════════════════════════════════════════════════

tab_overview, tab_category, tab_items, tab_vendor, tab_shrinkage, tab_health = st.tabs([
    "📊 COGS Overview",
    "📂 Category Breakdown",
    "🔍 Item-Level Analysis",
    "🚚 Vendor Spend",
    "📐 Shrinkage & Variance",
    "🩺 Cost Data Health",
])


# ═══════════════════════════════════════════════════════════════════════════
# TAB 1: COGS OVERVIEW
# ═══════════════════════════════════════════════════════════════════════════

with tab_overview:
    st.subheader("COGS Trend")

    freq = st.radio("Aggregation", ["Daily", "Weekly", "Monthly"], horizontal=True, key="cogs_freq")
    freq_map = {"Daily": "daily", "Weekly": "weekly", "Monthly": "monthly"}
    trend_df = get_cogs_trend(start, end, freq=freq_map[freq])

    if trend_df.empty:
        st.info("No COGS data available for this period.")
    else:
        trend_df["total_cogs"] = trend_df["total_cogs"].astype(float)
        trend_df["net_revenue"] = trend_df["net_revenue"].astype(float)
        trend_df["cogs_pct"] = trend_df["cogs_pct"].astype(float)

        fig = make_subplots(specs=[[{"secondary_y": True}]])

        fig.add_trace(
            go.Bar(
                x=trend_df["period"],
                y=trend_df["total_cogs"],
                name="COGS ($)",
                marker_color="#ef4444",
                opacity=0.7,
            ),
            secondary_y=False,
        )
        fig.add_trace(
            go.Scatter(
                x=trend_df["period"],
                y=trend_df["cogs_pct"],
                name="COGS %",
                mode="lines+markers",
                marker=dict(size=6),
                line=dict(color="#f59e0b", width=2),
            ),
            secondary_y=True,
        )

        fig.add_hline(
            y=30, line_dash="dash", line_color="orange",
            annotation_text="30% target", secondary_y=True,
        )
        fig.update_yaxes(title_text="COGS ($)", secondary_y=False)
        fig.update_yaxes(title_text="COGS %", secondary_y=True)
        fig.update_layout(
            height=450,
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig, use_container_width=True)

    # COGS vs Purchases comparison
    st.subheader("Theoretical COGS vs Actual Purchases (Monthly)")

    if cvp.empty or (cvp["theoretical_cogs"].sum() == 0 and cvp["actual_purchases"].sum() == 0):
        st.info(
            "Not enough data to compare. Theoretical COGS requires cost data on POS items; "
            "actual purchases require entered invoices."
        )
    else:
        cvp_plot = cvp.copy()
        cvp_plot["theoretical_cogs"] = cvp_plot["theoretical_cogs"].astype(float)
        cvp_plot["actual_purchases"] = cvp_plot["actual_purchases"].astype(float)

        fig2 = go.Figure()
        fig2.add_trace(go.Bar(
            x=cvp_plot["month"],
            y=cvp_plot["theoretical_cogs"],
            name="Theoretical COGS",
            marker_color="#3b82f6",
        ))
        fig2.add_trace(go.Bar(
            x=cvp_plot["month"],
            y=cvp_plot["actual_purchases"],
            name="Actual Purchases",
            marker_color="#ef4444",
        ))
        fig2.update_layout(
            height=400,
            barmode="group",
            yaxis_title="Amount ($)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig2, use_container_width=True)

        st.caption(
            "When purchases consistently exceed theoretical COGS, investigate "
            "over-ordering, shrinkage, or missing recipe linkages."
        )


# ═══════════════════════════════════════════════════════════════════════════
# TAB 2: CATEGORY BREAKDOWN
# ═══════════════════════════════════════════════════════════════════════════

with tab_category:
    st.subheader("COGS by Category")

    cat_df = get_category_profitability(start, end)

    if cat_df.empty:
        st.info("No category data for this date range.")
    else:
        cat_df["net_revenue"] = cat_df["net_revenue"].astype(float)
        cat_df["total_cost"] = cat_df["total_cost"].astype(float).fillna(0)
        cat_df["gross_profit"] = cat_df["gross_profit"].astype(float).fillna(0)
        cat_df["total_qty"] = cat_df["total_qty"].astype(int)

        cats_with_cost = cat_df[cat_df["total_cost"] > 0].copy()

        if cats_with_cost.empty:
            st.warning("No categories have cost data populated yet.")
        else:
            cats_with_cost["pour_cost_pct"] = (
                cats_with_cost["total_cost"] / cats_with_cost["net_revenue"] * 100
            ).round(1)

            # Color by pour cost %
            def _cost_color(pct):
                if pct > 33:
                    return "#ef4444"
                elif pct > 25:
                    return "#f59e0b"
                return "#22c55e"

            cats_with_cost["color"] = cats_with_cost["pour_cost_pct"].apply(_cost_color)

            cats_sorted = cats_with_cost.sort_values("total_cost", ascending=True)

            fig = go.Figure(go.Bar(
                y=cats_sorted["category_name"],
                x=cats_sorted["total_cost"],
                orientation="h",
                marker_color=cats_sorted["color"],
                text=cats_sorted["total_cost"].apply(lambda x: f"${x:,.0f}"),
                textposition="outside",
            ))
            fig.update_layout(
                height=max(350, len(cats_sorted) * 35 + 80),
                xaxis_title="COGS ($)",
                yaxis_title="",
            )
            st.plotly_chart(fig, use_container_width=True)

            # Donut chart: category share of COGS
            col_pie, col_table = st.columns([1, 1])

            with col_pie:
                st.subheader("COGS Share by Category")
                fig_pie = px.pie(
                    cats_with_cost,
                    values="total_cost",
                    names="category_name",
                    color_discrete_sequence=px.colors.qualitative.Set2,
                    hole=0.4,
                )
                fig_pie.update_traces(textposition="inside", textinfo="percent+label")
                fig_pie.update_layout(height=400, showlegend=False)
                st.plotly_chart(fig_pie, use_container_width=True)

            with col_table:
                st.subheader("Category Detail")
                display = cats_with_cost.copy()
                display["margin_pct"] = display.apply(
                    lambda r: f"{(r['gross_profit'] / r['net_revenue'] * 100):.1f}%"
                    if r["net_revenue"] > 0 else "—",
                    axis=1,
                )
                display["pour_cost_pct"] = display["pour_cost_pct"].apply(lambda x: f"{x:.1f}%")
                for col in ["net_revenue", "total_cost", "gross_profit"]:
                    display[col] = display[col].apply(lambda x: f"${x:,.2f}" if x != 0 else "—")
                display = display[[
                    "category_name", "total_qty", "net_revenue",
                    "total_cost", "gross_profit", "pour_cost_pct", "margin_pct",
                ]]
                display.columns = [
                    "Category", "Qty Sold", "Net Revenue",
                    "COGS", "Gross Profit", "Pour Cost %", "Margin %",
                ]
                st.dataframe(display, hide_index=True, use_container_width=True)

        # Category COGS trend (stacked area)
        st.markdown("---")
        st.subheader("Category COGS Over Time")

        cat_trend = get_cogs_by_category_trend(start, end)
        if cat_trend.empty:
            st.info("No category trend data available.")
        else:
            cat_trend["total_cogs"] = cat_trend["total_cogs"].astype(float)
            fig_area = px.area(
                cat_trend,
                x="month",
                y="total_cogs",
                color="category_name",
                labels={"total_cogs": "COGS ($)", "month": "Month", "category_name": "Category"},
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            fig_area.update_layout(
                height=400,
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
            )
            st.plotly_chart(fig_area, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════
# TAB 3: ITEM-LEVEL ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════

with tab_items:
    # Top cost items
    st.subheader("Top 20 Highest-Cost Items")

    top_items = get_top_cost_items(start, end, limit=20)

    if top_items.empty:
        st.info("No items with cost data for this period.")
    else:
        top_items["total_cost"] = top_items["total_cost"].astype(float)
        top_items["net_revenue"] = top_items["net_revenue"].astype(float)
        top_items["pour_cost_pct"] = top_items["pour_cost_pct"].astype(float)

        top_sorted = top_items.sort_values("total_cost", ascending=True)

        fig = go.Figure()
        fig.add_trace(go.Bar(
            y=top_sorted["item_name"],
            x=top_sorted["total_cost"],
            name="COGS",
            orientation="h",
            marker_color="#ef4444",
        ))
        fig.add_trace(go.Bar(
            y=top_sorted["item_name"],
            x=top_sorted["net_revenue"],
            name="Revenue",
            orientation="h",
            marker_color="#3b82f6",
            opacity=0.5,
        ))
        fig.update_layout(
            height=max(500, len(top_sorted) * 30 + 80),
            barmode="overlay",
            xaxis_title="Amount ($)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig, use_container_width=True)

    # Worst margin items
    st.markdown("---")
    st.subheader("Worst Margin Items (Highest Pour Cost %)")

    worst = get_worst_margin_items(start, end, limit=20)

    if worst.empty:
        st.info("No items with cost data for this period.")
    else:
        worst["total_cost"] = worst["total_cost"].astype(float)
        worst["net_revenue"] = worst["net_revenue"].astype(float)
        worst["pour_cost_pct"] = worst["pour_cost_pct"].astype(float)
        worst["total_qty"] = worst["total_qty"].astype(int)

        display_worst = worst.copy()
        display_worst["flag"] = display_worst["pour_cost_pct"].apply(
            lambda x: "🔴" if x > 40 else ("🟡" if x > 30 else "🟢")
        )
        display_worst["pour_cost_pct"] = display_worst["pour_cost_pct"].apply(lambda x: f"{x:.1f}%")
        for col in ["total_cost", "net_revenue"]:
            display_worst[col] = display_worst[col].apply(lambda x: f"${x:,.2f}")

        display_worst = display_worst[[
            "flag", "item_name", "category_name", "total_qty",
            "net_revenue", "total_cost", "pour_cost_pct",
        ]]
        display_worst.columns = [
            "", "Item", "Category", "Qty Sold",
            "Net Revenue", "COGS", "Pour Cost %",
        ]
        st.dataframe(display_worst, hide_index=True, use_container_width=True)

    # Cost coverage gaps
    st.markdown("---")
    st.subheader("Cost Coverage Gaps")
    st.caption("Top revenue items with NO cost data -- these are your biggest blind spots.")

    gaps = get_cost_coverage_gaps(start, end)

    if gaps.empty:
        st.success("All items with revenue have cost data populated.")
    else:
        revenue_with_cost = health["revenue_with_cost"]
        revenue_without = health["total_revenue"] - revenue_with_cost
        rev_coverage = (revenue_with_cost / health["total_revenue"] * 100) if health["total_revenue"] > 0 else 0

        g1, g2, g3 = st.columns(3)
        with g1:
            st.metric("Items Missing Cost", f"{len(gaps):,}")
        with g2:
            st.metric("Revenue Uncovered", f"${revenue_without:,.0f}")
        with g3:
            st.metric("Revenue Coverage", f"{rev_coverage:.1f}%")

        display_gaps = gaps.head(25).copy()
        display_gaps["net_revenue"] = display_gaps["net_revenue"].astype(float).apply(lambda x: f"${x:,.2f}")
        display_gaps["total_qty"] = display_gaps["total_qty"].astype(int)
        display_gaps.columns = ["Item", "Category", "Net Revenue", "Qty Sold"]
        st.dataframe(display_gaps, hide_index=True, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════
# TAB 4: VENDOR SPEND
# ═══════════════════════════════════════════════════════════════════════════

with tab_vendor:
    st.subheader("Vendor Spend Over Time")

    vst = get_vendor_spend_trend(start, end)

    if vst.empty:
        st.info("No invoice data for this period. Enter invoices in the Invoices tab.")
    else:
        vst["total_spend"] = vst["total_spend"].astype(float)

        fig_vs = px.bar(
            vst,
            x="month",
            y="total_spend",
            color="vendor_name",
            labels={"total_spend": "Spend ($)", "month": "Month", "vendor_name": "Vendor"},
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        fig_vs.update_layout(
            height=450,
            barmode="stack",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig_vs, use_container_width=True)

        # Vendor summary table + concentration donut
        col_donut, col_vtable = st.columns([1, 1])

        vendor_totals = get_invoice_totals()

        with col_donut:
            st.subheader("Vendor Concentration")
            if not vendor_totals.empty:
                vendor_totals["total_spend"] = vendor_totals["total_spend"].astype(float)
                fig_vd = px.pie(
                    vendor_totals,
                    values="total_spend",
                    names="vendor_name",
                    color_discrete_sequence=px.colors.qualitative.Set2,
                    hole=0.45,
                )
                fig_vd.update_traces(textposition="inside", textinfo="percent+label")
                fig_vd.update_layout(height=400, showlegend=False)
                st.plotly_chart(fig_vd, use_container_width=True)

        with col_vtable:
            st.subheader("Vendor Summary")
            if not vendor_totals.empty:
                vt_display = vendor_totals.copy()
                vt_display["invoice_count"] = vt_display["invoice_count"].astype(int)
                vt_display["total_spend"] = vt_display["total_spend"].astype(float)
                vt_display["avg_invoice"] = vt_display["total_spend"] / vt_display["invoice_count"]
                vt_display["avg_invoice"] = vt_display["avg_invoice"].apply(lambda x: f"${x:,.2f}")
                vt_display["total_spend"] = vt_display["total_spend"].apply(lambda x: f"${x:,.2f}")
                vt_display = vt_display[[
                    "vendor_name", "invoice_count", "total_spend",
                    "avg_invoice", "first_invoice", "last_invoice",
                ]]
                vt_display.columns = [
                    "Vendor", "Invoices", "Total Spend",
                    "Avg Invoice", "First", "Last",
                ]
                st.dataframe(vt_display, hide_index=True, use_container_width=True)

        # Single-vendor drill-down
        st.markdown("---")
        st.subheader("Vendor Detail")

        vendor_names = get_vendor_names()
        if vendor_names:
            selected_vendor = st.selectbox("Select Vendor", vendor_names, key="cogs_vendor")
            vd = get_vendor_spend_detail(selected_vendor, start, end)

            if vd.empty:
                st.info(f"No invoices from {selected_vendor} in this period.")
            else:
                vd["total_spend"] = vd["total_spend"].astype(float)
                vd["invoice_count"] = vd["invoice_count"].astype(int)

                fig_vdl = go.Figure()
                fig_vdl.add_trace(go.Bar(
                    x=vd["month"],
                    y=vd["total_spend"],
                    name="Monthly Spend",
                    marker_color="#3b82f6",
                    text=vd["total_spend"].apply(lambda x: f"${x:,.0f}"),
                    textposition="outside",
                ))
                fig_vdl.update_layout(
                    height=350,
                    yaxis_title="Spend ($)",
                    title=f"{selected_vendor} — Monthly Spend",
                )
                st.plotly_chart(fig_vdl, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════
# TAB 5: SHRINKAGE & VARIANCE
# ═══════════════════════════════════════════════════════════════════════════

with tab_shrinkage:
    st.subheader("Inventory Count Variance by Category")

    shrink_df = get_shrinkage_summary(start, end)

    if shrink_df.empty:
        st.info(
            "No inventory count data available for this period. "
            "Conduct physical counts and enter them in the Inventory Dashboard."
        )
    else:
        shrink_df["total_variance_dollars"] = shrink_df["total_variance_dollars"].astype(float)
        shrink_df["total_variance_units"] = shrink_df["total_variance_units"].astype(float)

        fig_sh = px.bar(
            shrink_df,
            x="category",
            y="total_variance_dollars",
            color="total_variance_dollars",
            color_continuous_scale=["#ef4444", "#f59e0b", "#22c55e"],
            labels={"total_variance_dollars": "Variance ($)", "category": "Category"},
        )
        fig_sh.update_layout(height=400, xaxis_tickangle=-45)
        st.plotly_chart(fig_sh, use_container_width=True)

        st.caption("Negative variance = missing inventory (shrinkage). Positive = surplus.")

    # High-variance items
    st.markdown("---")
    st.subheader("Highest-Variance Items")

    hv = get_high_variance_items(start, end, limit=20)

    if hv.empty:
        st.info("No variance data available.")
    else:
        hv_display = hv.copy()
        hv_display["variance_dollars"] = hv_display["variance_dollars"].astype(float)
        hv_display["variance"] = hv_display["variance"].astype(float)
        hv_display["counted_qty"] = hv_display["counted_qty"].astype(float)
        hv_display["theoretical_qty"] = hv_display["theoretical_qty"].astype(float)

        hv_display["flag"] = hv_display["variance_dollars"].apply(
            lambda x: "🔴" if x < -10 else ("🟡" if x < 0 else "🟢")
        )
        hv_display["variance_dollars"] = hv_display["variance_dollars"].apply(lambda x: f"${x:,.2f}")
        hv_display["unit_cost"] = hv_display["unit_cost"].astype(float).apply(lambda x: f"${x:,.2f}")
        hv_display["counted_qty"] = hv_display["counted_qty"].apply(lambda x: f"{x:.1f}")
        hv_display["theoretical_qty"] = hv_display["theoretical_qty"].apply(lambda x: f"{x:.1f}")
        hv_display["variance"] = hv_display["variance"].apply(lambda x: f"{x:+.1f}")
        hv_display["variance_pct"] = hv_display["variance_pct"].astype(float).apply(
            lambda x: f"{x:+.1f}%" if pd.notna(x) else "—"
        )

        hv_display = hv_display[[
            "flag", "item_name", "category", "count_date",
            "counted_qty", "theoretical_qty", "variance",
            "variance_pct", "unit_cost", "variance_dollars",
        ]]
        hv_display.columns = [
            "", "Item", "Category", "Count Date",
            "Counted", "Theoretical", "Variance (units)",
            "Variance %", "Unit Cost", "Variance ($)",
        ]
        st.dataframe(hv_display, hide_index=True, use_container_width=True)

    # Adjustment breakdown
    st.markdown("---")
    st.subheader("Inventory Adjustments")

    adj = get_adjustment_summary(start, end)

    if adj.empty:
        st.info("No inventory adjustments recorded for this period.")
    else:
        adj["total_dollars"] = adj["total_dollars"].astype(float)
        adj["total_units"] = adj["total_units"].astype(float)
        adj["adjustment_count"] = adj["adjustment_count"].astype(int)

        ADJUSTMENT_LABELS = {
            "waste": "Waste",
            "spillage": "Spillage",
            "staff_drink": "Staff Drinks",
            "comp": "Comps",
            "breakage": "Breakage",
            "vendor_credit": "Vendor Credits",
            "transfer": "Transfers",
            "other": "Other",
        }
        adj["label"] = adj["adjustment_type"].map(ADJUSTMENT_LABELS).fillna(adj["adjustment_type"])

        col_adj_pie, col_adj_table = st.columns([1, 1])

        with col_adj_pie:
            fig_adj = px.pie(
                adj,
                values=adj["total_dollars"].abs(),
                names="label",
                color_discrete_sequence=px.colors.qualitative.Set2,
                hole=0.4,
            )
            fig_adj.update_traces(textposition="inside", textinfo="percent+label")
            fig_adj.update_layout(height=350, showlegend=False, title="Adjustments by Type")
            st.plotly_chart(fig_adj, use_container_width=True)

        with col_adj_table:
            adj_display = adj.copy()
            adj_display["total_dollars"] = adj_display["total_dollars"].apply(lambda x: f"${x:,.2f}")
            adj_display["total_units"] = adj_display["total_units"].apply(lambda x: f"{x:,.1f}")
            adj_display = adj_display[["label", "adjustment_count", "total_units", "total_dollars"]]
            adj_display.columns = ["Type", "Count", "Total Units", "Total ($)"]
            st.dataframe(adj_display, hide_index=True, use_container_width=True)

        # Adjustment trend
        adj_trend = get_adjustment_trend(start, end)
        if not adj_trend.empty:
            adj_trend["total_dollars"] = adj_trend["total_dollars"].astype(float)
            adj_trend["label"] = adj_trend["adjustment_type"].map(ADJUSTMENT_LABELS).fillna(
                adj_trend["adjustment_type"]
            )
            fig_at = px.bar(
                adj_trend,
                x="month",
                y="total_dollars",
                color="label",
                labels={"total_dollars": "Amount ($)", "month": "Month", "label": "Type"},
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            fig_at.update_layout(
                height=350,
                barmode="stack",
                title="Adjustment Trend Over Time",
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
            )
            st.plotly_chart(fig_at, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════
# TAB 6: COST DATA HEALTH
# ═══════════════════════════════════════════════════════════════════════════

with tab_health:
    st.subheader("Cost Data Coverage")

    total_items = health["total_items"]
    items_with = health["items_with_cost"]
    items_without = total_items - items_with
    rev_total = health["total_revenue"]
    rev_with = health["revenue_with_cost"]
    rev_without = rev_total - rev_with
    rev_pct = (rev_with / rev_total * 100) if rev_total > 0 else 0

    h1, h2, h3, h4 = st.columns(4)
    with h1:
        st.metric("Total POS Items", f"{total_items:,}")
    with h2:
        st.metric("Items With Cost", f"{items_with:,}")
        st.caption(f"{coverage_pct:.1f}% of items")
    with h3:
        st.metric("Revenue Covered", f"${rev_with:,.0f}")
        st.caption(f"{rev_pct:.1f}% of revenue")
    with h4:
        st.metric("Revenue Gap", f"${rev_without:,.0f}")
        st.caption(f"No cost data")

    st.markdown("---")

    # Category-level coverage
    st.subheader("Coverage by Category")

    cat_health = health["by_category"]
    if not cat_health.empty:
        cat_health["total_items"] = cat_health["total_items"].astype(int)
        cat_health["items_with_cost"] = cat_health["items_with_cost"].astype(int)
        cat_health["total_revenue"] = cat_health["total_revenue"].astype(float)
        cat_health["revenue_with_cost"] = cat_health["revenue_with_cost"].astype(float)
        cat_health["item_coverage_pct"] = (
            cat_health["items_with_cost"] / cat_health["total_items"] * 100
        ).round(1)
        cat_health["revenue_coverage_pct"] = cat_health.apply(
            lambda r: round(r["revenue_with_cost"] / r["total_revenue"] * 100, 1)
            if r["total_revenue"] > 0 else 0,
            axis=1,
        )

        # Coverage bar chart
        fig_cov = go.Figure()
        fig_cov.add_trace(go.Bar(
            x=cat_health["category_name"],
            y=cat_health["item_coverage_pct"],
            name="Item Coverage %",
            marker_color="#3b82f6",
        ))
        fig_cov.add_trace(go.Bar(
            x=cat_health["category_name"],
            y=cat_health["revenue_coverage_pct"],
            name="Revenue Coverage %",
            marker_color="#22c55e",
        ))
        fig_cov.update_layout(
            height=400,
            barmode="group",
            yaxis_title="Coverage %",
            xaxis_tickangle=-45,
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        fig_cov.add_hline(y=100, line_dash="dash", line_color="gray", annotation_text="100%")
        st.plotly_chart(fig_cov, use_container_width=True)

        # Coverage table
        ch_display = cat_health.copy()
        ch_display["total_revenue"] = ch_display["total_revenue"].apply(lambda x: f"${x:,.0f}")
        ch_display["revenue_with_cost"] = ch_display["revenue_with_cost"].apply(lambda x: f"${x:,.0f}")
        ch_display["item_coverage_pct"] = ch_display["item_coverage_pct"].apply(lambda x: f"{x:.1f}%")
        ch_display["revenue_coverage_pct"] = ch_display["revenue_coverage_pct"].apply(lambda x: f"{x:.1f}%")
        ch_display = ch_display[[
            "category_name", "total_items", "items_with_cost",
            "item_coverage_pct", "total_revenue", "revenue_with_cost",
            "revenue_coverage_pct",
        ]]
        ch_display.columns = [
            "Category", "Total Items", "With Cost",
            "Item Coverage", "Total Revenue", "Revenue Covered",
            "Revenue Coverage",
        ]
        st.dataframe(ch_display, hide_index=True, use_container_width=True)

    # Priority list
    st.markdown("---")
    st.subheader("Priority: Top Revenue Items Missing Cost")
    st.caption("Fill cost data for these items first to improve your COGS accuracy.")

    priority_gaps = get_cost_coverage_gaps(start, end)
    if priority_gaps.empty:
        st.success("All items have cost data.")
    else:
        pg = priority_gaps.head(15).copy()
        pg["net_revenue"] = pg["net_revenue"].astype(float)
        pg["total_qty"] = pg["total_qty"].astype(int)

        fig_pg = go.Figure(go.Bar(
            y=pg.sort_values("net_revenue")["item_name"],
            x=pg.sort_values("net_revenue")["net_revenue"],
            orientation="h",
            marker_color="#ef4444",
            text=pg.sort_values("net_revenue")["net_revenue"].apply(lambda x: f"${x:,.0f}"),
            textposition="outside",
        ))
        fig_pg.update_layout(
            height=max(350, len(pg) * 28 + 80),
            xaxis_title="Revenue ($) — Missing Cost Data",
            yaxis_title="",
            title="Revenue at Risk (No Cost Data)",
        )
        st.plotly_chart(fig_pg, use_container_width=True)

    # Cost outliers
    st.markdown("---")
    st.subheader("Data Quality Alerts")

    outliers = get_cost_outlier_items(start, end)
    if outliers.empty:
        st.success("No cost ratio outliers detected.")
    else:
        outliers["pour_cost_pct"] = outliers["pour_cost_pct"].astype(float)
        outliers["total_cost"] = outliers["total_cost"].astype(float)
        outliers["net_revenue"] = outliers["net_revenue"].astype(float)

        high_outliers = outliers[outliers["pour_cost_pct"] > 60]
        low_outliers = outliers[outliers["pour_cost_pct"] < 5]

        if not high_outliers.empty:
            st.warning(f"**{len(high_outliers)} item(s) with pour cost > 60%** — likely data errors or unprofitable items.")
            ho = high_outliers.copy()
            ho["pour_cost_pct"] = ho["pour_cost_pct"].apply(lambda x: f"{x:.1f}%")
            ho["total_cost"] = ho["total_cost"].apply(lambda x: f"${x:,.2f}")
            ho["net_revenue"] = ho["net_revenue"].apply(lambda x: f"${x:,.2f}")
            ho = ho[["item_name", "category_name", "net_revenue", "total_cost", "pour_cost_pct"]]
            ho.columns = ["Item", "Category", "Revenue", "COGS", "Pour Cost %"]
            st.dataframe(ho, hide_index=True, use_container_width=True)

        if not low_outliers.empty:
            st.info(f"**{len(low_outliers)} item(s) with pour cost < 5%** — verify cost data is correct.")
            lo = low_outliers.copy()
            lo["pour_cost_pct"] = lo["pour_cost_pct"].apply(lambda x: f"{x:.1f}%")
            lo["total_cost"] = lo["total_cost"].apply(lambda x: f"${x:,.2f}")
            lo["net_revenue"] = lo["net_revenue"].apply(lambda x: f"${x:,.2f}")
            lo = lo[["item_name", "category_name", "net_revenue", "total_cost", "pour_cost_pct"]]
            lo.columns = ["Item", "Category", "Revenue", "COGS", "Pour Cost %"]
            st.dataframe(lo, hide_index=True, use_container_width=True)


st.markdown("---")
st.caption("COGS Deep Dive | Bar Arbolada Analytics")
