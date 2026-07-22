"""
Dashboard 2: Profitability & Cost Control
============================================
- Prime Cost analysis (Revenue - COGS - Labor)
- Pour cost by category
- Labor % of sales and SPLH trends
- Daily profitability trends
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import date, timedelta

from src.analytics.queries import (
    get_sales_date_range,
    get_prime_cost_data,
    get_category_profitability,
    get_pour_cost_by_category,
    get_splh_trend,
    get_daily_labor,
    get_full_pnl,
    get_expenses_by_type,
    get_untrusted_labor_rows,
    get_untrusted_labor_details,
)

st.title("💰 Profitability & Cost Control")


# ── Date Range ────────────────────────────────────────────────────────────

min_date, max_date = get_sales_date_range()

# Default to YTD (year of most recent data), or full range if data spans < 1 year
ytd_start = date(max_date.year, 1, 1)
default_start = max(min_date, ytd_start)
default_end = max_date

col_d1, col_d2, _ = st.columns([1, 1, 2])
with col_d1:
    start = st.date_input("Start Date", value=default_start, min_value=min_date, max_value=max_date)
with col_d2:
    end = st.date_input("End Date", value=default_end, min_value=min_date, max_value=max_date)


# ── Load Data ─────────────────────────────────────────────────────────────

prime_df = get_prime_cost_data(start, end)
untrusted_labor_df = get_untrusted_labor_rows(start, end)
untrusted_labor_detail_df = get_untrusted_labor_details(start, end)

if prime_df.empty:
    st.warning("No sales data found for this date range.")
    st.stop()

if not untrusted_labor_df.empty:
    untrusted_rows = int(untrusted_labor_df["row_count"].sum())
    untrusted_pay = float(untrusted_labor_df["total_pay"].sum())
    st.warning(
        f"Excluded {untrusted_rows} labor row(s) (${untrusted_pay:,.2f}) that are not from "
        "successful Lightspeed labor CSV imports. Review import logs if this looks unexpected."
    )
    with st.expander("View excluded labor audit"):
        audit_chart_df = untrusted_labor_df.copy()
        audit_chart_df["trading_day"] = pd.to_datetime(audit_chart_df["trading_day"])
        audit_chart_df["total_pay"] = audit_chart_df["total_pay"].astype(float)

        fig_audit = px.bar(
            audit_chart_df,
            x="trading_day",
            y="total_pay",
            text="row_count",
            title="Excluded labor dollars by day",
            labels={"trading_day": "Date", "total_pay": "Excluded Labor ($)", "row_count": "Rows"},
        )
        fig_audit.update_traces(marker_color="#f97316")
        fig_audit.update_layout(height=320)
        st.plotly_chart(fig_audit, use_container_width=True)

        if not untrusted_labor_detail_df.empty:
            detail = untrusted_labor_detail_df.copy()
            detail["total_pay"] = detail["total_pay"].fillna(0).astype(float)
            detail["trading_day"] = pd.to_datetime(detail["trading_day"]).dt.strftime("%Y-%m-%d")
            if "shift_start" in detail.columns:
                detail["shift_start"] = pd.to_datetime(detail["shift_start"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M")
            if "shift_end" in detail.columns:
                detail["shift_end"] = pd.to_datetime(detail["shift_end"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M")

            detail["employee"] = (
                detail["last_name"].fillna("").str.strip()
                + ", "
                + detail["first_name"].fillna("").str.strip()
            ).str.strip(", ")
            detail["total_pay"] = detail["total_pay"].apply(lambda x: f"${x:,.2f}")
            detail["import_status"] = detail["import_status"].fillna("missing")
            detail["import_type"] = detail["import_type"].fillna("missing")
            detail["import_filename"] = detail["import_filename"].fillna("missing")

            st.caption("Rows excluded from labor KPIs/charts because import metadata is missing or invalid.")
            st.dataframe(
                detail[
                    [
                        "trading_day",
                        "employee",
                        "role",
                        "shift_start",
                        "shift_end",
                        "total_pay",
                        "import_log_id",
                        "import_type",
                        "import_status",
                        "import_filename",
                    ]
                ].rename(
                    columns={
                        "trading_day": "Date",
                        "employee": "Employee",
                        "role": "Role",
                        "shift_start": "Shift Start",
                        "shift_end": "Shift End",
                        "total_pay": "Excluded Pay",
                        "import_log_id": "Import Log ID",
                        "import_type": "Import Type",
                        "import_status": "Import Status",
                        "import_filename": "Import Filename",
                    }
                ),
                hide_index=True,
                use_container_width=True,
            )


# ── Compute Metrics ───────────────────────────────────────────────────────

prime_df["net_sales"] = prime_df["net_sales"].astype(float)
prime_df["labor_cost"] = prime_df["labor_cost"].astype(float)
prime_df["pos_labor_cost"] = prime_df["pos_labor_cost"].astype(float)
prime_df["fixed_labor_cost"] = prime_df["fixed_labor_cost"].astype(float)
prime_df["labor_hours"] = prime_df["labor_hours"].astype(float)
prime_df["total_comps"] = prime_df["total_comps"].astype(float).fillna(0)
prime_df["total_voids"] = prime_df["total_voids"].astype(float).fillna(0)

total_revenue = prime_df["net_sales"].sum()
total_labor = prime_df["labor_cost"].sum()
total_gm_pay = prime_df["fixed_labor_cost"].sum()
total_hours = prime_df["labor_hours"].sum()
total_comps = prime_df["total_comps"].sum()
total_voids = prime_df["total_voids"].sum()
num_days = len(prime_df)

avg_daily_revenue = total_revenue / num_days if num_days > 0 else 0
avg_daily_labor = total_labor / num_days if num_days > 0 else 0
labor_pct = (total_labor / total_revenue * 100) if total_revenue > 0 else 0
splh = (total_revenue / total_hours) if total_hours > 0 else 0
comp_pct = (total_comps / total_revenue * 100) if total_revenue > 0 else 0


# ═══════════════════════════════════════════════════════════════════════════
# KPIs
# ═══════════════════════════════════════════════════════════════════════════

st.markdown("---")

k1, k2, k3, k4, k5, k6 = st.columns(6)
with k1:
    st.metric("Total Revenue", f"${total_revenue:,.0f}")
with k2:
    st.metric("Total Labor", f"${total_labor:,.0f}")
    st.caption(f"Includes GM Fixed Pay: ${total_gm_pay:,.0f}")
with k3:
    st.metric("Labor %", f"{labor_pct:.1f}%",
              delta=f"{'Good' if labor_pct < 20 else 'High'}" if labor_pct > 0 else None,
              delta_color="normal" if labor_pct < 20 else "inverse")
with k4:
    st.metric("Avg SPLH", f"${splh:,.0f}")
with k5:
    st.metric("Avg Daily Sales", f"${avg_daily_revenue:,.0f}")
with k6:
    st.metric("Comp %", f"{comp_pct:.1f}%")

st.markdown("---")


# ═══════════════════════════════════════════════════════════════════════════
# TABS
# ═══════════════════════════════════════════════════════════════════════════

tab_pnl, tab_prime, tab_labor, tab_pour, tab_category = st.tabs([
    "📋 Full P&L",
    "📊 Prime Cost Trend",
    "👷 Labor Analysis",
    "🥃 Pour Cost",
    "📂 Category P&L",
])


# ═══════════════════════════════════════════════════════════════════════════
# TAB 0: FULL P&L STATEMENT
# ═══════════════════════════════════════════════════════════════════════════

EXPENSE_TYPE_LABELS = {
    "occupancy": "Occupancy (Rent)",
    "energy_utility": "Energy Utilities",
    "internet_telecom": "Internet / Telecom",
    "pos_technology": "POS & Technology",
    "cc_processing": "Credit Card Processing",
    "cleaning": "Cleaning",
    "insurance": "Business Insurance",
    "licensing": "Licensing & Permits",
    "trash_waste": "Trash & Waste",
    "repairs_maintenance": "Repairs & Maintenance",
    "marketing": "Marketing",
    "professional_services": "Professional Services",
    "supplies_non_inventory": "Supplies (Non-Inventory)",
    "miscellaneous": "Miscellaneous",
}

with tab_pnl:
    st.subheader("Restaurant P&L Statement")
    st.caption(f"Period: {start} to {end}")

    pnl = get_full_pnl(start, end)

    # ── Waterfall Chart ──────────────────────────────────────────────────

    waterfall_labels = [
        "Net Sales",
        "COGS",
        "Gross Profit",
        "Labor",
        "Prime Cost Profit",
    ]
    waterfall_measures = ["absolute", "relative", "total", "relative", "total"]
    waterfall_values = [
        pnl["net_sales"],
        -pnl["cogs"],
        pnl["gross_profit"],
        -pnl["labor_cost"],
        pnl["prime_cost_profit"],
    ]

    # Add each OpEx type
    for item in pnl["opex_by_type"]:
        label = EXPENSE_TYPE_LABELS.get(item["expense_type"], item["expense_type"])
        waterfall_labels.append(label)
        waterfall_measures.append("relative")
        waterfall_values.append(-float(item["total_amount"]))

    # Net Operating Income
    waterfall_labels.append("Net Operating Income")
    waterfall_measures.append("total")
    waterfall_values.append(pnl["net_operating_income"])

    # Distributions (if any)
    if pnl["distributions"] > 0:
        waterfall_labels.append("Distributions")
        waterfall_measures.append("relative")
        waterfall_values.append(-pnl["distributions"])

        waterfall_labels.append("Retained Cash")
        waterfall_measures.append("total")
        waterfall_values.append(pnl["retained_cash"])

    fig_wf = go.Figure(go.Waterfall(
        orientation="v",
        measure=waterfall_measures,
        x=waterfall_labels,
        y=waterfall_values,
        connector={"line": {"color": "rgb(63, 63, 63)"}},
        increasing={"marker": {"color": "#22c55e"}},
        decreasing={"marker": {"color": "#ef4444"}},
        totals={"marker": {"color": "#3b82f6"}},
        textposition="outside",
        text=[f"${abs(v):,.0f}" for v in waterfall_values],
    ))
    fig_wf.update_layout(
        height=500,
        showlegend=False,
        xaxis_tickangle=-45,
        yaxis_title="Amount ($)",
        title="P&L Waterfall",
    )
    st.plotly_chart(fig_wf, use_container_width=True)

    # ── P&L Table ────────────────────────────────────────────────────────

    st.markdown("---")

    def pnl_row(label, amount, pct=None, indent=0, bold=False, separator=False):
        """Helper to format a P&L row."""
        prefix = "&nbsp;&nbsp;&nbsp;&nbsp;" * indent
        amt_str = f"${amount:,.2f}" if amount >= 0 else f"(${abs(amount):,.2f})"
        pct_str = f"{pct:.1f}%" if pct is not None else ""
        if bold:
            return f"| **{prefix}{label}** | **{amt_str}** | **{pct_str}** |"
        return f"| {prefix}{label} | {amt_str} | {pct_str} |"

    ns = pnl["net_sales"]
    lines = [
        "| Line Item | Amount | % of Sales |",
        "| :--- | ---: | ---: |",
        pnl_row("Net Sales", ns, 100.0, bold=True),
        pnl_row("Cost of Goods Sold", -pnl["cogs"],
                 pnl["cogs"] / ns * 100 if ns > 0 else 0, indent=1),
        pnl_row("**Gross Profit**", pnl["gross_profit"],
                 pnl["gross_margin_pct"], bold=True),
        pnl_row("Labor Cost (All-In)", -pnl["labor_cost"], pnl["labor_pct"], indent=1),
        pnl_row("Clocked Labor (POS)", -pnl["labor_cost_pos"],
                 (pnl["labor_cost_pos"] / ns * 100) if ns > 0 else 0, indent=2),
        pnl_row("GM Fixed Pay", -pnl["labor_cost_fixed"],
                 (pnl["labor_cost_fixed"] / ns * 100) if ns > 0 else 0, indent=2),
        pnl_row("Payroll Tax", -pnl["payroll_tax"],
                 (pnl["payroll_tax"] / ns * 100) if ns > 0 else 0, indent=2),
        pnl_row("Payroll Service Fees", -pnl["payroll_fee"],
                 (pnl["payroll_fee"] / ns * 100) if ns > 0 else 0, indent=2),
        pnl_row("**Prime Cost Profit**", pnl["prime_cost_profit"],
                 pnl["prime_cost_profit"] / ns * 100 if ns > 0 else 0, bold=True),
        "| | | |",
        "| **Operating Expenses** | | |",
    ]

    for item in pnl["opex_by_type"]:
        label = EXPENSE_TYPE_LABELS.get(item["expense_type"], item["expense_type"])
        amt = float(item["total_amount"])
        lines.append(pnl_row(label, -amt, amt / ns * 100 if ns > 0 else 0, indent=1))

    lines.append(pnl_row("**Total Operating Expenses**", -pnl["total_opex"],
                          pnl["opex_pct"], bold=True))
    lines.append("| | | |")
    lines.append(pnl_row("**Net Operating Income**", pnl["net_operating_income"],
                          pnl["noi_pct"], bold=True))

    if pnl["distributions"] > 0:
        lines.append("| | | |")
        lines.append(pnl_row("Owner/Investor Distributions",
                              -pnl["distributions"],
                              pnl["distributions"] / ns * 100 if ns > 0 else 0,
                              indent=1))
        lines.append(pnl_row("**Retained Cash**", pnl["retained_cash"],
                              pnl["retained_cash"] / ns * 100 if ns > 0 else 0,
                              bold=True))

    st.markdown("\n".join(lines))

    # ── KPI Cards ────────────────────────────────────────────────────────

    st.markdown("---")
    st.subheader("Key Ratios")

    r1, r2, r3, r4 = st.columns(4)
    with r1:
        st.metric(
            "Prime Cost %",
            f"{pnl['prime_cost_pct']:.1f}%",
            delta="Good" if pnl["prime_cost_pct"] < 65 else "High",
            delta_color="normal" if pnl["prime_cost_pct"] < 65 else "inverse",
        )
        st.caption("Target: < 65%")
    with r2:
        st.metric(
            "OpEx %",
            f"{pnl['opex_pct']:.1f}%" if pnl["opex_pct"] > 0 else "—",
        )
        st.caption("Target: 15-25%")
    with r3:
        st.metric(
            "NOI Margin",
            f"{pnl['noi_pct']:.1f}%",
            delta="Healthy" if pnl["noi_pct"] > 10 else "Low",
            delta_color="normal" if pnl["noi_pct"] > 10 else "inverse",
        )
        st.caption("Target: > 10%")
    with r4:
        if ns > 0:
            # Break-even daily sales
            daily_fixed = pnl["total_opex"] / max(num_days, 1)
            daily_labor = pnl["labor_cost"] / max(num_days, 1)
            breakeven = daily_fixed + daily_labor
            st.metric("Daily Break-Even", f"${breakeven:,.0f}")
            st.caption("OpEx + Labor per day")
        else:
            st.metric("Daily Break-Even", "—")

    if pnl["total_opex"] == 0:
        st.info(
            "💡 No operating expenses recorded yet for this period. "
            "Go to **Operating Expenses** to enter rent, utilities, insurance, etc. "
            "to see the full P&L picture."
        )


# ═══════════════════════════════════════════════════════════════════════════
# TAB 1: PRIME COST TREND
# ═══════════════════════════════════════════════════════════════════════════

with tab_prime:
    st.subheader("Daily Revenue vs Labor Cost")

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        go.Bar(
            x=prime_df["trading_day"],
            y=prime_df["net_sales"],
            name="Net Sales",
            marker_color="#22c55e",
            opacity=0.7,
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Bar(
            x=prime_df["trading_day"],
            y=prime_df["labor_cost"],
            name="Labor Cost",
            marker_color="#ef4444",
            opacity=0.7,
        ),
        secondary_y=False,
    )

    # Labor % line
    prime_df["labor_pct_day"] = prime_df.apply(
        lambda r: (r["labor_cost"] / r["net_sales"] * 100)
        if r["net_sales"] > 0 else 0,
        axis=1,
    )
    fig.add_trace(
        go.Scatter(
            x=prime_df["trading_day"],
            y=prime_df["labor_pct_day"],
            name="Labor %",
            mode="lines+markers",
            marker=dict(size=6),
            line=dict(color="#f59e0b", width=2),
        ),
        secondary_y=True,
    )

    fig.update_yaxes(title_text="Amount ($)", secondary_y=False)
    fig.update_yaxes(title_text="Labor %", secondary_y=True)
    fig.update_layout(
        height=450,
        barmode="group",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )

    # Add 20% target line
    fig.add_hline(y=20, line_dash="dash", line_color="orange",
                  annotation_text="20% target", secondary_y=True)

    st.plotly_chart(fig, use_container_width=True)

    # Daily detail table
    with st.expander("Daily Detail"):
        display = prime_df[["trading_day", "net_sales", "pos_labor_cost", "fixed_labor_cost", "labor_cost",
                             "labor_hours", "labor_pct_day"]].copy()
        display["splh"] = display.apply(
            lambda r: r["net_sales"] / r["labor_hours"]
            if r["labor_hours"] > 0 else 0,
            axis=1,
        )
        display["net_sales"] = display["net_sales"].apply(lambda x: f"${x:,.2f}")
        display["pos_labor_cost"] = display["pos_labor_cost"].apply(lambda x: f"${x:,.2f}")
        display["fixed_labor_cost"] = display["fixed_labor_cost"].apply(lambda x: f"${x:,.2f}")
        display["labor_cost"] = display["labor_cost"].apply(lambda x: f"${x:,.2f}")
        display["labor_hours"] = display["labor_hours"].apply(lambda x: f"{x:.1f}")
        display["labor_pct_day"] = display["labor_pct_day"].apply(lambda x: f"{x:.1f}%")
        display["splh"] = display["splh"].apply(lambda x: f"${x:,.0f}")
        display.columns = ["Date", "Net Sales", "Clocked Labor", "Fixed Labor", "Total Labor", "Hours", "Labor %", "SPLH"]
        st.dataframe(display, hide_index=True, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════
# TAB 2: LABOR ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════

with tab_labor:
    st.subheader("Sales Per Labor Hour Trend")

    splh_df = get_splh_trend(start, end)

    if not splh_df.empty:
        splh_df["splh"] = splh_df["splh"].astype(float)
        splh_df["labor_pct"] = splh_df["labor_pct"].astype(float)
        splh_df["net_sales"] = splh_df["net_sales"].astype(float)
        splh_df["total_hours"] = splh_df["total_hours"].astype(float)

        # SPLH chart
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=splh_df["trading_day"],
            y=splh_df["splh"],
            mode="lines+markers",
            name="SPLH",
            line=dict(color="#3b82f6", width=2),
            marker=dict(size=8),
        ))

        avg_splh = splh_df["splh"].mean()
        fig.add_hline(y=avg_splh, line_dash="dash", line_color="gray",
                      annotation_text=f"Avg: ${avg_splh:.0f}")

        fig.update_layout(
            height=350,
            yaxis_title="$/Labor Hour",
            xaxis_title="Date",
        )
        st.plotly_chart(fig, use_container_width=True)

        # Labor % chart
        st.subheader("Labor % of Sales")

        fig2 = go.Figure()
        fig2.add_trace(go.Bar(
            x=splh_df["trading_day"],
            y=splh_df["labor_pct"],
            marker_color=splh_df["labor_pct"].apply(
                lambda x: "#ef4444" if x > 25 else "#f59e0b" if x > 20 else "#22c55e"
            ),
        ))
        fig2.add_hline(y=20, line_dash="dash", line_color="orange",
                       annotation_text="20% target")
        fig2.update_layout(
            height=300,
            yaxis_title="Labor %",
        )
        st.plotly_chart(fig2, use_container_width=True)

        # Day-of-week analysis
        st.subheader("Labor Efficiency by Day of Week")
        splh_df["dow"] = pd.to_datetime(splh_df["trading_day"]).dt.day_name()
        dow_stats = splh_df.groupby("dow").agg(
            avg_splh=("splh", "mean"),
            avg_labor_pct=("labor_pct", "mean"),
            avg_sales=("net_sales", "mean"),
            avg_hours=("total_hours", "mean"),
        ).reindex(["Monday", "Tuesday", "Wednesday", "Thursday",
                   "Friday", "Saturday", "Sunday"])
        dow_stats = dow_stats.dropna()

        if not dow_stats.empty:
            fig3 = go.Figure()
            fig3.add_trace(go.Bar(
                x=dow_stats.index,
                y=dow_stats["avg_splh"],
                marker_color="#3b82f6",
            ))
            fig3.update_layout(
                height=300,
                yaxis_title="Avg SPLH ($)",
            )
            st.plotly_chart(fig3, use_container_width=True)

            display = dow_stats.reset_index()
            display.columns = ["Day", "Avg SPLH", "Avg Labor %", "Avg Sales", "Avg Hours"]
            display["Avg SPLH"] = display["Avg SPLH"].apply(lambda x: f"${x:.0f}")
            display["Avg Labor %"] = display["Avg Labor %"].apply(lambda x: f"{x:.1f}%")
            display["Avg Sales"] = display["Avg Sales"].apply(lambda x: f"${x:,.0f}")
            display["Avg Hours"] = display["Avg Hours"].apply(lambda x: f"{x:.1f}")
            st.dataframe(display, hide_index=True, use_container_width=True)
    else:
        st.info("No labor data for this date range.")


# ═══════════════════════════════════════════════════════════════════════════
# TAB 3: POUR COST
# ═══════════════════════════════════════════════════════════════════════════

with tab_pour:
    st.subheader("Pour Cost by Category")
    st.caption(
        "Pour cost = cost of goods / net revenue. "
        "Only shows categories with cost data populated in the product mix."
    )

    pour_df = get_pour_cost_by_category(start, end)

    if pour_df.empty:
        st.info(
            "No cost data available yet. Pour cost analysis requires cost data "
            "on POS items. Populate costs in Lightspeed for your Tier A items."
        )
    else:
        pour_df["pour_cost_pct"] = pour_df["pour_cost_pct"].astype(float)
        pour_df["net_revenue"] = pour_df["net_revenue"].astype(float)
        pour_df["total_cost"] = pour_df["total_cost"].astype(float)

        # Pour cost bar chart
        fig = px.bar(
            pour_df,
            x="category_name",
            y="pour_cost_pct",
            color="pour_cost_pct",
            color_continuous_scale=["#22c55e", "#f59e0b", "#ef4444"],
            labels={"pour_cost_pct": "Pour Cost %", "category_name": "Category"},
        )
        fig.add_hline(y=25, line_dash="dash", line_color="orange",
                      annotation_text="25% target (spirits)")
        fig.add_hline(y=33, line_dash="dash", line_color="red",
                      annotation_text="33% target (food)")
        fig.update_layout(height=400, xaxis_tickangle=-45)
        st.plotly_chart(fig, use_container_width=True)

        # Table
        display = pour_df.copy()
        display["net_revenue"] = display["net_revenue"].apply(lambda x: f"${x:,.2f}")
        display["total_cost"] = display["total_cost"].apply(lambda x: f"${x:,.2f}")
        display["pour_cost_pct"] = display["pour_cost_pct"].apply(lambda x: f"{x:.1f}%")
        display.columns = ["Category", "Net Revenue", "Total Cost", "Pour Cost %"]
        st.dataframe(display, hide_index=True, use_container_width=True)

        st.markdown("""
        **Industry benchmarks:**
        - Spirits: 18-25%
        - Wine: 25-35%
        - Beer: 20-28%
        - Food: 28-35%
        - Overall: 25-30%
        """)


# ═══════════════════════════════════════════════════════════════════════════
# TAB 4: CATEGORY P&L
# ═══════════════════════════════════════════════════════════════════════════

with tab_category:
    st.subheader("Category Profitability")

    cat_df = get_category_profitability(start, end)

    if cat_df.empty:
        st.info("No category data for this date range.")
    else:
        cat_df["net_revenue"] = cat_df["net_revenue"].astype(float)
        cat_df["total_cost"] = cat_df["total_cost"].astype(float).fillna(0)
        cat_df["gross_profit"] = cat_df["gross_profit"].astype(float).fillna(0)
        cat_df["total_qty"] = cat_df["total_qty"].astype(int)

        # Revenue by category chart
        fig = px.bar(
            cat_df,
            x="category_name",
            y=["net_revenue", "total_cost"],
            barmode="group",
            labels={"value": "Amount ($)", "category_name": "Category"},
            color_discrete_sequence=["#3b82f6", "#ef4444"],
        )
        fig.update_layout(
            height=400,
            xaxis_tickangle=-45,
            legend_title="Metric",
        )
        st.plotly_chart(fig, use_container_width=True)

        # Pie chart: revenue share
        fig2 = px.pie(
            cat_df.head(10),
            values="net_revenue",
            names="category_name",
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        fig2.update_traces(textposition="inside", textinfo="percent+label")
        fig2.update_layout(height=350, showlegend=False,
                           title="Revenue Share by Category")
        st.plotly_chart(fig2, use_container_width=True)

        # Table
        display = cat_df.copy()
        display["margin_pct"] = display.apply(
            lambda r: f"{(r['gross_profit'] / r['net_revenue'] * 100):.1f}%"
            if r["net_revenue"] > 0 and r["gross_profit"] != 0 else "—",
            axis=1,
        )
        for col in ["net_revenue", "total_cost", "gross_profit", "total_comps"]:
            display[col] = display[col].apply(
                lambda x: f"${x:,.2f}" if x != 0 else "—"
            )
        display = display[["category_name", "unique_items", "total_qty",
                            "net_revenue", "total_cost", "gross_profit",
                            "margin_pct", "total_comps"]]
        display.columns = ["Category", "Items", "Qty Sold",
                           "Net Revenue", "COGS", "Gross Profit",
                           "Margin %", "Comps"]
        st.dataframe(display, hide_index=True, use_container_width=True)


st.markdown("---")
st.caption("Profitability & Cost Control | Bar Arbolada Analytics")
