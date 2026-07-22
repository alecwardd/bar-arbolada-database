"""
Dashboard: Operating Expenses & Owner Distributions
=====================================================
- Manage expense categories (rent, utilities, insurance, etc.)
- Enter and track monthly operating expenses
- Set up recurring expenses that auto-generate across months
- Record owner/investor distributions (below the line)
- View expense trends and budget vs actual
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import text
from src.config import engine
from src.analytics.queries import (
    get_expense_categories,
    get_active_expense_categories,
    get_expenses,
    get_distributions,
    get_recurring_expenses,
    get_recurring_expense_stats,
    generate_recurring_expenses,
    ensure_recurring_generated,
    end_recurring_expense,
)
from dashboards.data import (
    get_expenses_by_type,
    get_expenses_by_category,
    get_sales_date_range,
)
from dashboards.period import period_selector

st.title("🏢 Operating Expenses")

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

FREQUENCY_OPTIONS = ["monthly", "weekly", "quarterly", "annual", "as_needed"]
RECURRING_FREQUENCY_OPTIONS = ["monthly", "quarterly", "annual"]
PAYMENT_METHODS = ["check", "ach", "auto_pay", "cash", "credit_card"]
DISTRIBUTION_TYPES = ["owner_draw", "investor_payout", "loan_payment", "interest"]


# ═══════════════════════════════════════════════════════════════════════════
# AUTO-GENERATE RECURRING EXPENSES ON PAGE LOAD
# ═══════════════════════════════════════════════════════════════════════════

new_generated = ensure_recurring_generated()
if new_generated > 0:
    st.toast(f"Auto-generated {new_generated} recurring expense(s) for this month.")


# ═══════════════════════════════════════════════════════════════════════════
# TABS
# ═══════════════════════════════════════════════════════════════════════════

tab_enter, tab_recurring, tab_view, tab_categories, tab_distributions = st.tabs([
    "📝 Enter Expense",
    "🔄 Recurring Expenses",
    "📊 Expense Overview",
    "⚙️ Manage Categories",
    "💸 Owner Distributions",
])


# ═══════════════════════════════════════════════════════════════════════════
# TAB 1: ENTER EXPENSE
# ═══════════════════════════════════════════════════════════════════════════

with tab_enter:
    st.subheader("Record an Operating Expense")

    cat_df = get_active_expense_categories()

    if cat_df.empty:
        st.warning(
            "No expense categories set up yet. Go to the **Manage Categories** "
            "tab to add categories first."
        )
    else:
        cat_options = dict(zip(cat_df["name"], cat_df["id"]))

        with st.form("expense_form", clear_on_submit=True):
            col1, col2 = st.columns(2)

            with col1:
                selected_cat = st.selectbox(
                    "Expense Category",
                    options=list(cat_options.keys()),
                    help="Select the type of operating expense",
                )
                expense_date = st.date_input("Date Paid / Incurred", value=date.today())
                amount = st.number_input(
                    "Amount ($)", min_value=0.01, step=0.01, format="%.2f"
                )

            with col2:
                col_ps, col_pe = st.columns(2)
                with col_ps:
                    period_start = st.date_input(
                        "Period Start",
                        value=date.today().replace(day=1),
                        help="Start of the billing period this covers",
                    )
                with col_pe:
                    period_end = st.date_input(
                        "Period End",
                        value=date.today(),
                        help="End of the billing period this covers",
                    )
                payment_method = st.selectbox(
                    "Payment Method",
                    options=[""] + PAYMENT_METHODS,
                    format_func=lambda x: x.replace("_", " ").title() if x else "— Select —",
                )
                reference_number = st.text_input(
                    "Reference # (check #, confirmation #, etc.)",
                )

            notes = st.text_area("Notes", height=68)

            submitted = st.form_submit_button("💾 Save Expense", use_container_width=True)

            if submitted:
                try:
                    with engine.begin() as conn:
                        conn.execute(
                            text("""
                                INSERT INTO op_expenses
                                (expense_category_id, expense_date, period_start,
                                 period_end, amount, payment_method, reference_number, notes)
                                VALUES (:cat_id, :exp_date, :ps, :pe, :amt, :pm, :ref, :notes)
                            """),
                            {
                                "cat_id": int(cat_options[selected_cat]),
                                "exp_date": expense_date,
                                "ps": period_start,
                                "pe": period_end,
                                "amt": amount,
                                "pm": payment_method if payment_method else None,
                                "ref": reference_number if reference_number else None,
                                "notes": notes if notes else None,
                            },
                        )
                    st.success(
                        f"Saved: **{selected_cat}** — ${amount:,.2f} on {expense_date}"
                    )
                except Exception as e:
                    st.error(f"Error saving expense: {e}")

    # Recent entries
    st.markdown("---")
    st.subheader("Recent Entries")
    recent = get_expenses()
    if not recent.empty:
        display = recent.head(20).copy()
        display["amount"] = display["amount"].apply(lambda x: f"${float(x):,.2f}")
        display["source"] = display["recurring_expense_id"].apply(
            lambda x: "Recurring" if pd.notna(x) and x else "Manual"
        )
        display = display[["expense_date", "category_name", "expense_type",
                           "amount", "payment_method", "reference_number", "source", "notes"]]
        display.columns = ["Date", "Category", "Type", "Amount",
                           "Payment", "Reference", "Source", "Notes"]
        st.dataframe(display, hide_index=True, use_container_width=True)
    else:
        st.info("No expenses recorded yet.")


# ═══════════════════════════════════════════════════════════════════════════
# TAB 2: RECURRING EXPENSES
# ═══════════════════════════════════════════════════════════════════════════

with tab_recurring:
    st.subheader("Recurring Expenses")
    st.caption(
        "Set up expenses that repeat every month, quarter, or year. "
        "The system auto-generates entries in the expenses table — "
        "backfilling history and adding new months automatically."
    )

    cat_df_rec = get_active_expense_categories()

    if cat_df_rec.empty:
        st.warning(
            "No expense categories set up yet. Go to the **Manage Categories** "
            "tab to add categories first."
        )
    else:
        cat_options_rec = dict(zip(cat_df_rec["name"], cat_df_rec["id"]))

        # ── Create Recurring Expense ──────────────────────────────────────

        with st.expander("➕ Add Recurring Expense", expanded=False):
            with st.form("recurring_form", clear_on_submit=True):
                col1, col2 = st.columns(2)

                with col1:
                    rec_cat = st.selectbox(
                        "Expense Category",
                        options=list(cat_options_rec.keys()),
                        key="rec_cat",
                        help="Which expense category this recurring charge belongs to",
                    )
                    rec_amount = st.number_input(
                        "Amount ($)", min_value=0.01, step=0.01, format="%.2f",
                        key="rec_amount",
                    )
                    rec_freq = st.selectbox(
                        "Frequency",
                        options=RECURRING_FREQUENCY_OPTIONS,
                        format_func=lambda x: x.title(),
                        help="How often this expense recurs",
                    )

                with col2:
                    rec_day = st.number_input(
                        "Day of Month (expense date)",
                        min_value=1, max_value=28, value=1,
                        help="Which day of the month the expense is dated (1-28)",
                    )
                    rec_start = st.date_input(
                        "Start Date (1st of month)",
                        value=date.today().replace(day=1),
                        help="First month this recurring expense applies. Will backfill from here.",
                    )
                    rec_payment = st.selectbox(
                        "Payment Method",
                        options=[""] + PAYMENT_METHODS,
                        format_func=lambda x: x.replace("_", " ").title() if x else "— Select —",
                        key="rec_payment",
                    )

                rec_notes = st.text_area("Notes", height=68, key="rec_notes")

                rec_submitted = st.form_submit_button(
                    "💾 Create Recurring Expense", use_container_width=True
                )

                if rec_submitted:
                    # Normalize start to 1st of month
                    start_normalized = rec_start.replace(day=1)
                    try:
                        with engine.begin() as conn:
                            result = conn.execute(
                                text("""
                                    INSERT INTO recurring_expenses
                                    (expense_category_id, amount, frequency, day_of_month,
                                     start_date, payment_method, notes)
                                    VALUES (:cat_id, :amt, :freq, :dom, :start, :pm, :notes)
                                    RETURNING id
                                """),
                                {
                                    "cat_id": int(cat_options_rec[rec_cat]),
                                    "amt": rec_amount,
                                    "freq": rec_freq,
                                    "dom": rec_day,
                                    "start": start_normalized,
                                    "pm": rec_payment if rec_payment else None,
                                    "notes": rec_notes if rec_notes else None,
                                },
                            )
                            new_id = result.fetchone()[0]

                        # Generate all expense rows from start through current month
                        count = generate_recurring_expenses(new_id)
                        st.success(
                            f"Created recurring **{rec_cat}** — ${rec_amount:,.2f}/{rec_freq}. "
                            f"Generated **{count}** expense entries (backfilled + current month)."
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error creating recurring expense: {e}")

        # ── Active Recurring Expenses ─────────────────────────────────────

        st.markdown("---")
        st.subheader("Active Recurring Expenses")

        active_rec = get_recurring_expenses(active_only=True)
        stats = get_recurring_expense_stats()

        if not active_rec.empty:
            # Merge stats
            if not stats.empty:
                active_rec = active_rec.merge(stats, left_on="id", right_on="recurring_id", how="left")
                active_rec["generated_count"] = active_rec["generated_count"].fillna(0).astype(int)
            else:
                active_rec["generated_count"] = 0

            for _, row in active_rec.iterrows():
                end_label = row["end_date"].strftime("%b %Y") if pd.notna(row["end_date"]) else "Ongoing"
                col_info, col_action = st.columns([4, 1])

                with col_info:
                    st.markdown(
                        f"**{row['category_name']}** — "
                        f"${float(row['amount']):,.2f} / {row['frequency']} | "
                        f"Started {row['start_date'].strftime('%b %Y')} | "
                        f"{end_label} | "
                        f"{row['generated_count']} entries generated"
                    )
                    if row["notes"]:
                        st.caption(row["notes"])

                with col_action:
                    if pd.isna(row["end_date"]):
                        if st.button("End", key=f"end_{row['id']}", type="secondary"):
                            # End as of current month
                            today = date.today()
                            end_date = today.replace(day=1)
                            deleted = end_recurring_expense(int(row["id"]), end_date)
                            st.success(
                                f"Ended **{row['category_name']}** recurring. "
                                f"Removed {deleted} future entries."
                            )
                            st.rerun()

                st.divider()
        else:
            st.info(
                "No active recurring expenses. Use the form above to set one up — "
                "it will backfill history and auto-generate future months."
            )

        # ── Inactive (Ended) Recurring ────────────────────────────────────

        all_rec = get_recurring_expenses(active_only=False)
        ended_rec = all_rec[all_rec["end_date"].notna()] if not all_rec.empty else pd.DataFrame()
        # Filter to only truly ended ones (end_date in the past)
        if not ended_rec.empty:
            today_month = date.today().replace(day=1)
            ended_rec = ended_rec[ended_rec["end_date"].apply(
                lambda x: x.replace(day=1) if hasattr(x, 'replace') else x
            ) < today_month]

        if not ended_rec.empty:
            with st.expander(f"Ended Recurring Expenses ({len(ended_rec)})"):
                display = ended_rec.copy()
                display["amount"] = display["amount"].apply(lambda x: f"${float(x):,.2f}")
                display["start_date"] = display["start_date"].apply(
                    lambda x: x.strftime("%b %Y") if hasattr(x, 'strftime') else str(x)
                )
                display["end_date"] = display["end_date"].apply(
                    lambda x: x.strftime("%b %Y") if hasattr(x, 'strftime') else str(x)
                )
                display["frequency"] = display["frequency"].apply(lambda x: x.title())
                display = display[["category_name", "amount", "frequency",
                                   "start_date", "end_date", "payment_method"]]
                display.columns = ["Category", "Amount", "Frequency",
                                   "Started", "Ended", "Payment"]
                st.dataframe(display, hide_index=True, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════
# TAB 3: EXPENSE OVERVIEW
# ═══════════════════════════════════════════════════════════════════════════

with tab_view:
    st.subheader("Expense Overview")

    try:
        min_date, max_date = get_sales_date_range()
    except Exception:
        min_date = date.today().replace(day=1)
        max_date = date.today()

    _period = period_selector(min_date, max_date)
    view_start, view_end = _period.start, _period.end

    type_df = get_expenses_by_type(view_start, view_end)
    cat_detail_df = get_expenses_by_category(view_start, view_end)

    if type_df.empty:
        st.info("No expenses recorded for this period.")
    else:
        total = float(type_df["total_amount"].sum())
        st.metric("Total Operating Expenses", f"${total:,.2f}")

        # By type bar chart
        type_df["label"] = type_df["expense_type"].map(EXPENSE_TYPE_LABELS).fillna(
            type_df["expense_type"]
        )
        type_df["total_amount"] = type_df["total_amount"].astype(float)

        fig = px.bar(
            type_df,
            x="label",
            y="total_amount",
            color="total_amount",
            color_continuous_scale=["#3b82f6", "#ef4444"],
            labels={"total_amount": "Amount ($)", "label": "Expense Type"},
        )
        fig.update_layout(
            height=400,
            xaxis_tickangle=-45,
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)

        # Pie chart
        fig2 = px.pie(
            type_df,
            values="total_amount",
            names="label",
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        fig2.update_traces(textposition="inside", textinfo="percent+label")
        fig2.update_layout(height=350, showlegend=False,
                           title="Expense Distribution")
        st.plotly_chart(fig2, use_container_width=True)

    # Detailed category table with budget comparison
    if not cat_detail_df.empty:
        st.subheader("By Category (with Budget)")
        display = cat_detail_df.copy()
        display["total_amount"] = display["total_amount"].fillna(0).astype(float)
        display["budget_amount"] = display["budget_amount"].fillna(0).astype(float)
        display["variance"] = display["budget_amount"] - display["total_amount"]
        display["type_label"] = display["expense_type"].map(EXPENSE_TYPE_LABELS).fillna(
            display["expense_type"]
        )

        for col in ["total_amount", "budget_amount", "variance"]:
            display[col] = display[col].apply(
                lambda x: f"${x:,.2f}" if x != 0 else "—"
            )
        display = display[["category_name", "type_label", "total_amount",
                           "budget_amount", "variance", "entry_count"]]
        display.columns = ["Category", "Type", "Actual", "Budget", "Variance", "Entries"]
        st.dataframe(display, hide_index=True, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════
# TAB 4: MANAGE CATEGORIES
# ═══════════════════════════════════════════════════════════════════════════

with tab_categories:
    st.subheader("Expense Categories")

    existing = get_expense_categories()

    # Add new category form
    with st.expander("➕ Add New Category", expanded=existing.empty):
        with st.form("new_category_form", clear_on_submit=True):
            col1, col2 = st.columns(2)

            with col1:
                cat_name = st.text_input("Category Name")
                cat_type = st.selectbox(
                    "Expense Type",
                    options=list(EXPENSE_TYPE_LABELS.keys()),
                    format_func=lambda x: EXPENSE_TYPE_LABELS[x],
                )
                cat_freq = st.selectbox(
                    "Typical Frequency",
                    options=FREQUENCY_OPTIONS,
                    format_func=lambda x: x.replace("_", " ").title(),
                )

            with col2:
                cat_fixed = st.checkbox("Fixed Cost?", value=True,
                                        help="Fixed = predictable amount each period")
                cat_budget = st.number_input(
                    "Monthly Budget ($)", min_value=0.0, step=10.0, format="%.2f",
                    help="Optional: expected monthly cost for budget tracking",
                )
                cat_desc = st.text_input("Description (optional)")

            cat_notes = st.text_area("Notes", height=68, key="cat_notes")

            cat_submitted = st.form_submit_button("💾 Save Category", use_container_width=True)

            if cat_submitted:
                if not cat_name:
                    st.error("Category name is required.")
                else:
                    try:
                        with engine.begin() as conn:
                            conn.execute(
                                text("""
                                    INSERT INTO op_expense_categories
                                    (name, expense_type, description, typical_frequency,
                                     is_fixed, budget_amount, notes)
                                    VALUES (:name, :type, :desc, :freq, :fixed, :budget, :notes)
                                """),
                                {
                                    "name": cat_name,
                                    "type": cat_type,
                                    "desc": cat_desc if cat_desc else None,
                                    "freq": cat_freq,
                                    "fixed": cat_fixed,
                                    "budget": cat_budget if cat_budget > 0 else None,
                                    "notes": cat_notes if cat_notes else None,
                                },
                            )
                        st.success(f"Category **{cat_name}** created!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")

    # Existing categories table
    if not existing.empty:
        display = existing.copy()
        display["type_label"] = display["expense_type"].map(EXPENSE_TYPE_LABELS).fillna(
            display["expense_type"]
        )
        display["budget_amount"] = display["budget_amount"].apply(
            lambda x: f"${float(x):,.2f}" if pd.notna(x) and float(x) > 0 else "—"
        )
        display["is_fixed"] = display["is_fixed"].apply(
            lambda x: "Fixed" if x else "Variable"
        )
        display["typical_frequency"] = display["typical_frequency"].apply(
            lambda x: x.replace("_", " ").title() if x else "—"
        )
        display = display[["name", "type_label", "typical_frequency",
                           "is_fixed", "budget_amount", "status"]]
        display.columns = ["Category", "Type", "Frequency",
                           "Fixed/Var", "Monthly Budget", "Status"]
        st.dataframe(display, hide_index=True, use_container_width=True)
    else:
        st.info("No categories set up yet. Add your first one above!")


# ═══════════════════════════════════════════════════════════════════════════
# TAB 5: OWNER DISTRIBUTIONS
# ═══════════════════════════════════════════════════════════════════════════

with tab_distributions:
    st.subheader("Owner / Investor Distributions")
    st.caption(
        "These are tracked separately from operating expenses. "
        "They appear **below the line** on the P&L — they represent "
        "profit distribution, not operating cost."
    )

    # Entry form
    with st.form("distribution_form", clear_on_submit=True):
        col1, col2 = st.columns(2)

        with col1:
            dist_date = st.date_input("Distribution Date", value=date.today())
            dist_recipient = st.text_input("Recipient (name)")
            dist_amount = st.number_input(
                "Amount ($)", min_value=0.01, step=0.01, format="%.2f",
                key="dist_amount",
            )

        with col2:
            dist_type = st.selectbox(
                "Type",
                options=DISTRIBUTION_TYPES,
                format_func=lambda x: x.replace("_", " ").title(),
            )
            dist_method = st.selectbox(
                "Payment Method",
                options=[""] + PAYMENT_METHODS,
                format_func=lambda x: x.replace("_", " ").title() if x else "— Select —",
                key="dist_method",
            )
            dist_ref = st.text_input("Reference #", key="dist_ref")

        dist_notes = st.text_area("Notes", height=68, key="dist_notes")

        dist_submitted = st.form_submit_button(
            "💾 Save Distribution", use_container_width=True
        )

        if dist_submitted:
            if not dist_recipient:
                st.error("Recipient name is required.")
            else:
                try:
                    with engine.begin() as conn:
                        conn.execute(
                            text("""
                                INSERT INTO owner_distributions
                                (distribution_date, recipient, amount, distribution_type,
                                 payment_method, reference_number, notes)
                                VALUES (:dt, :recip, :amt, :dtype, :pm, :ref, :notes)
                            """),
                            {
                                "dt": dist_date,
                                "recip": dist_recipient,
                                "amt": dist_amount,
                                "dtype": dist_type,
                                "pm": dist_method if dist_method else None,
                                "ref": dist_ref if dist_ref else None,
                                "notes": dist_notes if dist_notes else None,
                            },
                        )
                    st.success(
                        f"Saved: **{dist_recipient}** — ${dist_amount:,.2f} "
                        f"({dist_type.replace('_', ' ')}) on {dist_date}"
                    )
                except Exception as e:
                    st.error(f"Error: {e}")

    # Recent distributions
    st.markdown("---")
    st.subheader("Distribution History")
    dist_df = get_distributions()
    if not dist_df.empty:
        display = dist_df.copy()
        display["amount"] = display["amount"].apply(lambda x: f"${float(x):,.2f}")
        display["distribution_type"] = display["distribution_type"].apply(
            lambda x: x.replace("_", " ").title() if x else "—"
        )
        display = display[["distribution_date", "recipient", "amount",
                           "distribution_type", "payment_method", "notes"]]
        display.columns = ["Date", "Recipient", "Amount", "Type", "Payment", "Notes"]
        st.dataframe(display, hide_index=True, use_container_width=True)
    else:
        st.info("No distributions recorded yet.")


st.markdown("---")
st.caption("Operating Expenses & Distributions | Bar Arbolada Analytics")
