"""
Dashboard 3: Inventory & Ordering
====================================
- Reorder alerts with urgency tiers (RED / YELLOW / GREEN)
- Current stock levels vs par
- Vendor deadlines and order scheduling
- Theoretical inventory trends
- Invoice spend tracking
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, timedelta

from src.analytics.queries import (
    get_inv_items,
    get_ledger_current,
    get_reorder_items,
    get_invoices,
    get_invoice_totals,
    get_vendors,
    get_recipes,
)

st.set_page_config(page_title="Inventory | Bar Arbolada", page_icon="📊", layout="wide")
st.title("📊 Inventory & Ordering Dashboard")


# ── Check if we have data ─────────────────────────────────────────────────

items_df = get_inv_items()
vendors_df = get_vendors()
ledger_df = get_ledger_current()
recipes_df = get_recipes()


# ════════════════════════════════════════════════════════════════════════════
# SETUP STATUS PANEL (shown when system needs data)
# ════════════════════════════════════════════════════════════════════════════

setup_complete = len(items_df) > 0

if not setup_complete:
    st.info("Welcome to the Inventory Dashboard! Let's get your system set up.")

    st.markdown("""
    ### Setup Checklist

    The inventory system needs a few things to start working:
    """)

    checks = {
        "Vendors added": len(vendors_df) > 0,
        "Inventory items cataloged": len(items_df) > 0,
        "Recipes defined": len(recipes_df) > 0 if not recipes_df.empty else False,
    }

    for label, done in checks.items():
        icon = "✅" if done else "⬜"
        st.markdown(f"{icon} **{label}**")

    st.markdown("""
    ---
    **How to get started:**
    1. **Invoices page** → Add your vendors (beverage distributor, food distributor, etc.)
    2. **Inventory Items page** → Add your Tier A items (top 20 by cost)
    3. **Recipes page** → Map your top cocktails to ingredients
    4. Come back here — the dashboard will light up!

    *Your GM can help with: vendor order deadlines, item costs, par levels, and recipe specs.*
    """)

else:
    # ════════════════════════════════════════════════════════════════════════
    # MAIN DASHBOARD
    # ════════════════════════════════════════════════════════════════════════

    # ── KPIs ──────────────────────────────────────────────────────────────

    k1, k2, k3, k4, k5 = st.columns(5)

    with k1:
        tier_a = len(items_df[items_df["inventory_tier"] == "A"])
        st.metric("Tier A Items", tier_a)
    with k2:
        st.metric("Total Items Tracked", len(items_df))
    with k3:
        st.metric("Vendors", len(vendors_df))
    with k4:
        recipe_count = len(recipes_df) if not recipes_df.empty else 0
        st.metric("Recipes", recipe_count)
    with k5:
        invoices_df = get_invoices()
        inv_count = len(invoices_df) if not invoices_df.empty else 0
        st.metric("Invoices", inv_count)

    st.markdown("---")

    # ── Tabs ──────────────────────────────────────────────────────────────

    tab_alerts, tab_stock, tab_spend, tab_coverage = st.tabs([
        "🚨 Reorder Alerts",
        "📦 Stock Levels",
        "💰 Spend Analysis",
        "📈 Coverage & Trends",
    ])


    # ═══════════════════════════════════════════════════════════════════════
    # TAB 1: REORDER ALERTS
    # ═══════════════════════════════════════════════════════════════════════

    with tab_alerts:
        reorder_df = get_reorder_items()

        if reorder_df.empty and ledger_df.empty:
            st.info(
                "No ledger data yet. The reorder engine activates once you:\n"
                "1. Add inventory items with par levels and reorder points\n"
                "2. Enter a physical count or opening inventory\n"
                "3. Run the daily ledger calculation\n\n"
                "The system will then track theoretical inventory daily and flag "
                "items that need reordering."
            )
        elif reorder_df.empty:
            st.success("All items are above reorder points. No orders needed right now.")
        else:
            st.warning(f"**{len(reorder_df)} items need reordering**")

            # Color-code by urgency
            def urgency_color(row):
                closing = float(row.get("closing_qty", 0) or 0)
                reorder_pt = float(row.get("reorder_point", 0) or 0)
                cover = float(row["days_of_cover"]) if pd.notna(row.get("days_of_cover")) else None
                lead = int(row.get("lead_time_days", 2) or 2)

                if reorder_pt > 0 and closing <= reorder_pt:
                    return "🔴 ORDER NOW"
                if cover is not None and cover <= lead:
                    return "🔴 ORDER NOW"
                if cover is not None and cover <= lead + 2:
                    return "🟡 ORDER SOON"
                return "🟡 ORDER SOON"

            reorder_df["urgency"] = reorder_df.apply(urgency_color, axis=1)

            # Group by vendor
            for vendor in reorder_df["vendor_name"].dropna().unique():
                vendor_items = reorder_df[reorder_df["vendor_name"] == vendor]
                with st.expander(f"**{vendor}** — {len(vendor_items)} items", expanded=True):
                    display = vendor_items[[
                        "urgency", "item_name", "category", "closing_qty",
                        "par_level", "reorder_point", "days_of_cover", "unit_of_measure",
                    ]].copy()
                    display.columns = [
                        "Status", "Item", "Category", "On Hand",
                        "Par", "Reorder Pt", "Days Cover", "Unit",
                    ]

                    for col in ["On Hand", "Par", "Reorder Pt", "Days Cover"]:
                        display[col] = display[col].apply(
                            lambda x: f"{float(x):.1f}" if pd.notna(x) else "—"
                        )

                    st.dataframe(display, hide_index=True, use_container_width=True)

            # Unassigned vendor items
            no_vendor = reorder_df[reorder_df["vendor_name"].isna()]
            if not no_vendor.empty:
                with st.expander(f"**No Vendor Assigned** — {len(no_vendor)} items"):
                    display = no_vendor[[
                        "urgency", "item_name", "category", "closing_qty",
                        "par_level", "reorder_point", "days_of_cover", "unit_of_measure",
                    ]].copy()
                    display.columns = [
                        "Status", "Item", "Category", "On Hand",
                        "Par", "Reorder Pt", "Days Cover", "Unit",
                    ]
                    st.dataframe(display, hide_index=True, use_container_width=True)


    # ═══════════════════════════════════════════════════════════════════════
    # TAB 2: STOCK LEVELS
    # ═══════════════════════════════════════════════════════════════════════

    with tab_stock:
        if ledger_df.empty:
            st.info(
                "No stock data yet. Once inventory items have ledger entries "
                "(from physical counts or daily ledger runs), stock levels will appear here."
            )

            # Show items with their par levels even without ledger data
            st.markdown("#### Items Ready for Tracking")
            items_with_par = items_df[items_df["par_level"].notna() & (items_df["par_level"] > 0)]
            if not items_with_par.empty:
                display = items_with_par[[
                    "name", "category", "inventory_tier", "par_level",
                    "reorder_point", "vendor_name",
                ]].copy()
                display.columns = ["Item", "Category", "Tier", "Par", "Reorder Pt", "Vendor"]
                st.dataframe(display, hide_index=True, use_container_width=True)
            else:
                st.caption("Set par levels on your inventory items to enable tracking.")
        else:
            # Stock vs Par chart
            st.subheader("Current Stock vs Par Level")

            chart_data = ledger_df[ledger_df["par_level"].notna()].copy()
            if not chart_data.empty:
                chart_data["on_hand"] = chart_data["closing_qty"].astype(float)
                chart_data["par"] = chart_data["par_level"].astype(float)
                chart_data["pct_of_par"] = (chart_data["on_hand"] / chart_data["par"] * 100).round(1)

                # Color based on % of par
                chart_data["status_color"] = chart_data["pct_of_par"].apply(
                    lambda x: "🔴 Critical" if x <= 25
                    else "🟡 Low" if x <= 50
                    else "🟢 Good" if x <= 100
                    else "🔵 Overstocked"
                )

                fig = go.Figure()
                fig.add_trace(go.Bar(
                    x=chart_data["item_name"],
                    y=chart_data["on_hand"],
                    name="On Hand",
                    marker_color="#3b82f6",
                ))
                fig.add_trace(go.Scatter(
                    x=chart_data["item_name"],
                    y=chart_data["par"],
                    name="Par Level",
                    mode="markers+lines",
                    marker=dict(size=8, color="#ef4444"),
                    line=dict(dash="dash", color="#ef4444"),
                ))
                fig.update_layout(
                    height=400,
                    xaxis_tickangle=-45,
                    legend=dict(orientation="h", yanchor="bottom", y=1.02),
                    margin=dict(b=120),
                )
                st.plotly_chart(fig, use_container_width=True)

            # Full stock table
            st.markdown("#### Detailed Stock Levels")
            display = ledger_df[[
                "item_name", "category", "closing_qty", "par_level",
                "reorder_point", "days_of_cover", "reorder_alert",
                "vendor_name", "unit_of_measure",
            ]].copy()
            display.columns = [
                "Item", "Category", "On Hand", "Par",
                "Reorder Pt", "Days Cover", "Alert",
                "Vendor", "Unit",
            ]
            for col in ["On Hand", "Par", "Reorder Pt", "Days Cover"]:
                display[col] = display[col].apply(
                    lambda x: f"{float(x):.1f}" if pd.notna(x) else "—"
                )
            display["Alert"] = display["Alert"].apply(lambda x: "🔴" if x else "✅")

            st.dataframe(display, hide_index=True, use_container_width=True, height=400)


    # ═══════════════════════════════════════════════════════════════════════
    # TAB 3: SPEND ANALYSIS
    # ═══════════════════════════════════════════════════════════════════════

    with tab_spend:
        totals_df = get_invoice_totals()

        if totals_df.empty:
            st.info(
                "No invoice data yet. Enter invoices in the **Invoices** page "
                "to see spending analysis here."
            )
        else:
            # Spend by vendor pie chart
            st.subheader("Spend by Vendor")
            totals_df["total_spend"] = totals_df["total_spend"].astype(float)

            fig = px.pie(
                totals_df,
                values="total_spend",
                names="vendor_name",
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            fig.update_traces(textposition="inside", textinfo="percent+label")
            fig.update_layout(height=350, showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

            # Invoice timeline
            invoices_all = get_invoices()
            if not invoices_all.empty:
                st.subheader("Invoice Timeline")
                invoices_all["total_amount"] = invoices_all["total_amount"].astype(float)
                invoices_all["invoice_date"] = pd.to_datetime(invoices_all["invoice_date"])

                fig2 = px.scatter(
                    invoices_all,
                    x="invoice_date",
                    y="total_amount",
                    color="vendor_name",
                    size="total_amount",
                    hover_data=["invoice_number", "line_count"],
                    labels={"total_amount": "Amount ($)", "invoice_date": "Date"},
                )
                fig2.update_layout(height=350)
                st.plotly_chart(fig2, use_container_width=True)

            # Spend summary table
            st.subheader("Vendor Spend Summary")
            display = totals_df.copy()
            display["total_spend"] = display["total_spend"].apply(lambda x: f"${x:,.2f}")
            display.columns = [
                "Vendor", "Invoices", "Total Spend", "First Invoice", "Last Invoice",
            ]
            st.dataframe(display, hide_index=True, use_container_width=True)


    # ═══════════════════════════════════════════════════════════════════════
    # TAB 4: COVERAGE & TRENDS
    # ═══════════════════════════════════════════════════════════════════════

    with tab_coverage:
        if ledger_df.empty:
            st.info(
                "Coverage data will appear once the daily ledger engine has been running. "
                "This requires inventory items, recipes, and product mix data."
            )
        else:
            # Days of cover summary
            st.subheader("Days of Cover by Item")

            cover_data = ledger_df[ledger_df["days_of_cover"].notna()].copy()
            if not cover_data.empty:
                cover_data["cover"] = cover_data["days_of_cover"].astype(float)

                # Sort by days of cover (lowest first = most urgent)
                cover_data = cover_data.sort_values("cover")

                fig = px.bar(
                    cover_data,
                    x="item_name",
                    y="cover",
                    color="cover",
                    color_continuous_scale=["#ef4444", "#f59e0b", "#22c55e"],
                    labels={"cover": "Days of Cover", "item_name": "Item"},
                )
                fig.update_layout(
                    height=400,
                    xaxis_tickangle=-45,
                    margin=dict(b=120),
                    coloraxis_showscale=True,
                )
                st.plotly_chart(fig, use_container_width=True)

                # Add vendor deadline context
                st.markdown("#### Vendor Order Windows")
                vendors_with_deadlines = vendors_df[
                    vendors_df["order_deadline_day"].notna()
                ]
                if not vendors_with_deadlines.empty:
                    display = vendors_with_deadlines[[
                        "name", "order_deadline_day", "order_deadline_time",
                        "lead_time_days", "delivery_days",
                    ]].copy()
                    display.columns = [
                        "Vendor", "Order By (Day)", "Order By (Time)",
                        "Lead Time (days)", "Delivery Days",
                    ]
                    st.dataframe(display, hide_index=True, use_container_width=True)
                else:
                    st.caption(
                        "Set order deadlines on your vendors to see scheduling info here."
                    )
            else:
                st.info("Days of cover data not yet available. Needs usage history from recipes + sales.")

            # Ledger movement summary
            st.markdown("---")
            st.subheader("Daily Ledger Summary")

            if not ledger_df.empty:
                st.caption(f"As of: {ledger_df['ledger_date'].iloc[0]}")

                summary = ledger_df.groupby("category").agg(
                    items=("item_name", "count"),
                    total_on_hand=("closing_qty", lambda x: x.astype(float).sum()),
                    alerts=("reorder_alert", "sum"),
                ).reset_index()
                summary.columns = ["Category", "Items", "Total On Hand", "Alerts"]
                summary["Total On Hand"] = summary["Total On Hand"].apply(lambda x: f"{x:.1f}")
                summary["Alerts"] = summary["Alerts"].astype(int)

                st.dataframe(summary, hide_index=True, use_container_width=True)


st.markdown("---")
st.caption("Inventory & Ordering Dashboard | Bar Arbolada Analytics")
