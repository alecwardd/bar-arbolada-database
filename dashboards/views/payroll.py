"""
Dashboard: Payroll (Tip Pool + Wages)
=====================================
- Employee View: wages, hours, allocated tips, total gross by date range
- Tip Pool (Daily): per-day pool math and allocations by employee
- Cash Tips Entry: manual cash tips per trading day
- Settings: food category, kitchen tip-out %, employee inclusion and multipliers
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import text
from src.config import engine
from src.analytics.queries import (
    get_payroll_date_range,
    get_payroll_settings,
    get_payroll_daily_inputs,
    get_payroll_daily_allocations,
    get_payroll_employees_list,
    get_payroll_employee_roles,
    get_payroll_employee_wages,
    get_payroll_cash_tips,
    get_payroll_employee_settings,
)

st.title("💰 Payroll")

# Same styling as app.py
st.markdown("""
<style>
    .block-container { padding-top: 1.5rem; }
    .stMetric { border-radius: 8px; padding: 12px; border: 1px solid rgba(128, 128, 128, 0.2); }
    h2 { font-weight: 700; }
    h3 { font-weight: 600; }
</style>
""", unsafe_allow_html=True)

tab_employee, tab_pool, tab_cash, tab_settings = st.tabs([
    "👤 Employee View",
    "📊 Tip Pool (Daily)",
    "💵 Cash Tips Entry",
    "⚙️ Settings",
])

min_date, max_date = get_payroll_date_range()
default_start = max(min_date, max_date - timedelta(days=14))


# ═══════════════════════════════════════════════════════════════════════════
# TAB 1: EMPLOYEE VIEW
# ═══════════════════════════════════════════════════════════════════════════

with tab_employee:
    st.subheader("Employee Pay Summary")
    st.caption("Select an employee and date range to see wages, allocated tips, and total gross across all roles.")

    show_all = st.checkbox("Include former employees", value=False, key="emp_show_all")
    employees_df = get_payroll_employees_list(active_days=None if show_all else 90)
    if employees_df.empty:
        st.warning("No labor data. Import labor report CSVs first.")
    else:
        # Build display as "Last, First" -- one entry per unique person
        employees_df["display"] = (
            employees_df["last_name"].str.strip() + ", " + employees_df["first_name"].str.strip()
        )
        # Deduplicate display names (shouldn't happen, but safety)
        options = list(employees_df["display"].unique())
        selected = st.selectbox("Employee", options, key="emp_select")
        idx = employees_df[employees_df["display"] == selected].iloc[0]
        emp_id = str(idx["employee_id"]) if pd.notna(idx["employee_id"]) else ""
        emp_first = str(idx["first_name"]).strip()
        emp_last = str(idx["last_name"]).strip()

        col_s, col_e, _ = st.columns([1, 1, 2])
        with col_s:
            start_emp = st.date_input("From", value=default_start, min_value=min_date, max_value=max_date, key="emp_start")
        with col_e:
            end_emp = st.date_input("To", value=max_date, min_value=min_date, max_value=max_date, key="emp_end")

        # Fetch ALL shifts for this person (across all roles)
        wages_df = get_payroll_employee_wages(start_emp, end_emp, employee_id=emp_id or None, first_name=emp_first, last_name=emp_last)
        alloc_df = get_payroll_daily_allocations(start_emp, end_emp)
        if not alloc_df.empty:
            alloc_df = alloc_df[
                (alloc_df["employee_id"].astype(str) == (emp_id or ""))
                & (alloc_df["first_name"].str.strip() == emp_first)
                & (alloc_df["last_name"].str.strip() == emp_last)
            ]
        else:
            alloc_df = pd.DataFrame()

        if wages_df.empty and alloc_df.empty:
            st.info("No wages or tip allocations for this employee in the selected range.")
        else:
            wages_df = wages_df.copy() if not wages_df.empty else pd.DataFrame()
            if not wages_df.empty:
                wages_df["total_hours"] = wages_df["total_hours"].fillna(0).astype(float)
                wages_df["total_pay"] = wages_df["total_pay"].fillna(0).astype(float)
                wages_df["role"] = wages_df["role"].fillna("Unknown")

            # Classify roles: tip-eligible vs hourly-only
            tip_eligible_roles = {"Bartender", "Bar Back"}
            all_roles = sorted(wages_df["role"].unique()) if not wages_df.empty else []
            tip_roles = [r for r in all_roles if r.strip() in tip_eligible_roles]
            hourly_only_roles = [r for r in all_roles if r.strip() not in tip_eligible_roles]

            # Aggregate totals
            total_wages = float(wages_df["total_pay"].sum()) if not wages_df.empty else 0.0
            total_tips = float(alloc_df["allocated_tips"].sum()) if not alloc_df.empty else 0.0
            total_hours = float(wages_df["total_hours"].sum()) if not wages_df.empty else 0.0
            tip_hours = float(wages_df[wages_df["role"].str.strip().isin(tip_eligible_roles)]["total_hours"].sum()) if not wages_df.empty else 0.0
            hourly_hours = float(wages_df[~wages_df["role"].str.strip().isin(tip_eligible_roles)]["total_hours"].sum()) if not wages_df.empty else 0.0

            # ── Top-line metrics ──
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.metric("Total Wages", f"${total_wages:,.2f}")
            with c2:
                st.metric("Allocated Tips", f"${total_tips:,.2f}")
            with c3:
                st.metric("Total Gross", f"${total_wages + total_tips:,.2f}")
            with c4:
                st.metric("Total Hours", f"{total_hours:.1f}")

            # ── Role Summary ──
            if len(all_roles) > 1:
                st.subheader("Role Breakdown")
                role_summary_rows = []
                for role in all_roles:
                    role_data = wages_df[wages_df["role"] == role]
                    role_hours = float(role_data["total_hours"].sum())
                    role_wages = float(role_data["total_pay"].sum())
                    is_tip = role.strip() in tip_eligible_roles
                    # Get tip allocation for this role if tip-eligible
                    role_tips = 0.0
                    if is_tip and not alloc_df.empty:
                        role_alloc = alloc_df[alloc_df["role"] == role]
                        role_tips = float(role_alloc["allocated_tips"].sum())
                    role_summary_rows.append({
                        "Role": role.strip(),
                        "Hours": f"{role_hours:.2f}",
                        "Wages": f"${role_wages:,.2f}",
                        "Tips": f"${role_tips:,.2f}" if is_tip else "—",
                        "Gross": f"${role_wages + role_tips:,.2f}",
                        "Tip Pool": "✓" if is_tip else "—",
                    })
                role_summary = pd.DataFrame(role_summary_rows)
                st.dataframe(role_summary, hide_index=True, use_container_width=True)
            elif len(all_roles) == 1:
                st.caption(f"Role: **{all_roles[0].strip()}**"
                           + (" (tip pool eligible)" if all_roles[0].strip() in tip_eligible_roles else " (hourly only)"))

            # ── Daily Breakdown (all roles combined per day) ──
            st.subheader("Daily Breakdown")

            if not wages_df.empty:
                # Tip allocations by day (summed across tip-eligible roles)
                if not alloc_df.empty:
                    alloc_by_day = alloc_df.groupby("trading_day")["allocated_tips"].sum().reset_index()
                    alloc_by_day.columns = ["trading_day", "allocated_tips"]
                else:
                    alloc_by_day = pd.DataFrame(columns=["trading_day", "allocated_tips"])

                # Group wages by day (combine all roles)
                day_groups = wages_df.groupby("trading_day").agg(
                    total_hours=("total_hours", "sum"),
                    total_pay=("total_pay", "sum"),
                    roles=("role", lambda x: ", ".join(sorted(set(r.strip() for r in x)))),
                ).reset_index()

                merge_df = day_groups.merge(alloc_by_day, on="trading_day", how="left")
                merge_df["allocated_tips"] = merge_df["allocated_tips"].fillna(0)
                merge_df["gross"] = merge_df["total_pay"] + merge_df["allocated_tips"]
                merge_df["Date"] = pd.to_datetime(merge_df["trading_day"]).dt.strftime("%a %b %d, %Y")
                merge_df["Hours"] = merge_df["total_hours"].apply(lambda x: f"{x:.2f}")
                merge_df["Wages"] = merge_df["total_pay"].apply(lambda x: f"${x:,.2f}")
                merge_df["Tips"] = merge_df["allocated_tips"].apply(lambda x: f"${x:,.2f}")
                merge_df["Gross"] = merge_df["gross"].apply(lambda x: f"${x:,.2f}")
                merge_df["Roles"] = merge_df["roles"]
                st.dataframe(
                    merge_df[["Date", "Roles", "Hours", "Wages", "Tips", "Gross"]],
                    hide_index=True,
                    use_container_width=True,
                )

                # ── Detailed Shift Log (expandable) ──
                if len(all_roles) > 1:
                    with st.expander("📋 Detailed Shift Log (by role)"):
                        shift_df = wages_df.copy()
                        if not alloc_df.empty:
                            # Merge per-shift tip allocations for tip-eligible roles
                            shift_df = shift_df.merge(
                                alloc_df[["trading_day", "role", "allocated_tips"]],
                                on=["trading_day", "role"],
                                how="left",
                            )
                        else:
                            shift_df["allocated_tips"] = 0.0
                        shift_df["allocated_tips"] = shift_df["allocated_tips"].fillna(0)
                        shift_df["gross"] = shift_df["total_pay"] + shift_df["allocated_tips"]
                        shift_df["Date"] = pd.to_datetime(shift_df["trading_day"]).dt.strftime("%a %b %d, %Y")
                        shift_df["Role"] = shift_df["role"].str.strip()
                        shift_df["Hours"] = shift_df["total_hours"].apply(lambda x: f"{x:.2f}")
                        shift_df["Wages"] = shift_df["total_pay"].apply(lambda x: f"${x:,.2f}")
                        shift_df["Tips"] = shift_df["allocated_tips"].apply(lambda x: f"${x:,.2f}")
                        shift_df["Gross"] = shift_df["gross"].apply(lambda x: f"${x:,.2f}")
                        st.dataframe(
                            shift_df[["Date", "Role", "Hours", "Wages", "Tips", "Gross"]],
                            hide_index=True,
                            use_container_width=True,
                        )
            else:
                st.info("No wage rows for this employee in range.")


# ═══════════════════════════════════════════════════════════════════════════
# TAB 2: TIP POOL (DAILY)
# ═══════════════════════════════════════════════════════════════════════════

with tab_pool:
    st.subheader("Tip Pool by Day")
    st.caption("Per-day pool (CC tips + cash tips − kitchen tip-out) and allocation by employee.")

    col_ps, col_pe, _ = st.columns([1, 1, 2])
    with col_ps:
        start_pool = st.date_input("From", value=default_start, min_value=min_date, max_value=max_date, key="pool_start")
    with col_pe:
        end_pool = st.date_input("To", value=max_date, min_value=min_date, max_value=max_date, key="pool_end")

    inputs_df = get_payroll_daily_inputs(start_pool, end_pool)
    alloc_df_pool = get_payroll_daily_allocations(start_pool, end_pool)

    if inputs_df.empty:
        st.info("No labor days in range; no pool data.")
    else:
        inputs_df = inputs_df.copy()
        inputs_df["trading_day"] = pd.to_datetime(inputs_df["trading_day"])
        for col in ["credit_tips", "net_food_sales", "cash_tips", "kitchen_tipout", "foh_pool"]:
            inputs_df[col] = inputs_df[col].fillna(0).astype(float)

        st.subheader("Daily Pool Summary")
        display_inputs = inputs_df.copy()
        display_inputs["Date"] = display_inputs["trading_day"].dt.strftime("%a %b %d, %Y")
        display_inputs["CC Tips"] = display_inputs["credit_tips"].apply(lambda x: f"${x:,.2f}")
        display_inputs["Net Food"] = display_inputs["net_food_sales"].apply(lambda x: f"${x:,.2f}")
        display_inputs["Cash Tips"] = display_inputs["cash_tips"].apply(lambda x: f"${x:,.2f}")
        display_inputs["Kitchen Tip-Out"] = display_inputs["kitchen_tipout"].apply(lambda x: f"${x:,.2f}")
        display_inputs["FOH Pool"] = display_inputs["foh_pool"].apply(lambda x: f"${x:,.2f}")
        st.dataframe(
            display_inputs[["Date", "CC Tips", "Net Food", "Cash Tips", "Kitchen Tip-Out", "FOH Pool"]],
            hide_index=True,
            use_container_width=True,
        )

        if not alloc_df_pool.empty:
            st.subheader("Allocations by Employee (per day)")
            alloc_display = alloc_df_pool.copy()
            alloc_display["Date"] = pd.to_datetime(alloc_display["trading_day"]).dt.strftime("%a %b %d, %Y")
            alloc_display["Employee"] = (
                alloc_display["last_name"].str.strip() + ", " + alloc_display["first_name"].str.strip()
            )
            alloc_display["Hours"] = alloc_display["hours"].apply(lambda x: f"{x:.2f}")
            alloc_display["Tip Eligible Hrs"] = alloc_display["tip_eligible_hours"].apply(lambda x: f"{x:.2f}")
            alloc_display["Allocated Tips"] = alloc_display["allocated_tips"].apply(lambda x: f"${x:,.2f}")
            st.dataframe(
                alloc_display[["Date", "Employee", "role", "Hours", "Tip Eligible Hrs", "Allocated Tips"]],
                hide_index=True,
                use_container_width=True,
            )


# ═══════════════════════════════════════════════════════════════════════════
# TAB 3: CASH TIPS ENTRY
# ═══════════════════════════════════════════════════════════════════════════

with tab_cash:
    st.subheader("Enter Cash Tips")
    st.caption("Cash tips added to the FOH pool for the selected trading day.")

    with st.form("cash_tips_form", clear_on_submit=True):
        cash_day = st.date_input("Trading Day", value=date.today(), key="cash_day")
        cash_amount = st.number_input("Amount ($)", min_value=0.0, step=1.0, format="%.2f", key="cash_amt")
        cash_notes = st.text_area("Notes (optional)", key="cash_notes")
        submitted = st.form_submit_button("💾 Save", use_container_width=True)

        if submitted:
            try:
                with engine.begin() as conn:
                    conn.execute(
                        text("""
                            INSERT INTO payroll_cash_tips (trading_day, amount, notes)
                            VALUES (:day, :amt, :notes)
                            ON CONFLICT (trading_day) DO UPDATE SET
                                amount = EXCLUDED.amount,
                                notes = EXCLUDED.notes
                        """),
                        {"day": cash_day, "amt": cash_amount, "notes": cash_notes if cash_notes else None},
                    )
                st.success(f"Saved: ${cash_amount:,.2f} cash tips for {cash_day}")
            except Exception as e:
                st.error(f"Error: {e}")

    st.markdown("---")
    st.subheader("Recent Cash Tip Entries")
    cash_list = get_payroll_cash_tips()
    if not cash_list.empty:
        cash_list = cash_list.head(30).copy()
        cash_list["amount"] = cash_list["amount"].apply(lambda x: f"${float(x):,.2f}")
        cash_list["trading_day"] = pd.to_datetime(cash_list["trading_day"]).dt.strftime("%Y-%m-%d")
        st.dataframe(
            cash_list[["trading_day", "amount", "notes"]],
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info("No cash tip entries yet.")


# ═══════════════════════════════════════════════════════════════════════════
# TAB 4: SETTINGS
# ═══════════════════════════════════════════════════════════════════════════

with tab_settings:
    st.subheader("Payroll Settings")
    settings_df = get_payroll_settings()

    if settings_df.empty:
        st.warning("Payroll settings not found. Run migrations.")
    else:
        row = settings_df.iloc[0]
        with st.form("settings_form"):
            food_cat = st.text_input(
                "Food category name (for net food sales / kitchen tip-out)",
                value=str(row["food_category_name"]) if pd.notna(row["food_category_name"]) else "Food",
                key="food_cat",
            )
            kitchen_pct = st.number_input(
                "Kitchen tip-out %",
                min_value=0.0,
                max_value=100.0,
                value=float(row["kitchen_tipout_pct"] or 0.05) * 100,
                step=0.5,
                format="%.2f",
                key="kitchen_pct",
            )
            barback_mult = st.number_input(
                "Barback tip pool multiplier",
                min_value=0.0,
                max_value=2.0,
                value=float(row["barback_multiplier"] or 0.5),
                step=0.1,
                format="%.2f",
                key="barback_mult",
            )
            if st.form_submit_button("💾 Save settings", use_container_width=True):
                try:
                    with engine.begin() as conn:
                        conn.execute(
                            text("""
                                UPDATE payroll_settings
                                SET food_category_name = :food_cat,
                                    kitchen_tipout_pct = :pct,
                                    barback_multiplier = :mult
                                WHERE id = 1
                            """),
                            {
                                "food_cat": food_cat,
                                "pct": kitchen_pct / 100.0,
                                "mult": barback_mult,
                            },
                        )
                    st.success("Settings saved.")
                except Exception as e:
                    st.error(f"Error: {e}")

    st.subheader("Employee Tip Pool (FOH)")
    st.caption("Sync employees from labor, then toggle inclusion and multiplier. Exclude placeholders (e.g. BAR 2).")

    if st.button("Sync employees from labor", use_container_width=True):
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO payroll_employee_settings
                        (employee_id, first_name, last_name, include_in_tip_pool, tip_pool_multiplier)
                        SELECT
                            COALESCE(employee_id, ''),
                            TRIM(first_name),
                            TRIM(last_name),
                            CASE
                                WHEN UPPER(TRIM(first_name)) = 'BAR 2' AND UPPER(TRIM(last_name)) = 'BAR 2' THEN FALSE
                                ELSE TRUE
                            END,
                            CASE
                                WHEN role = 'Bar Back' THEN (
                                    SELECT barback_multiplier
                                    FROM payroll_settings
                                    ORDER BY id
                                    LIMIT 1
                                )
                                ELSE 1.0
                            END
                        FROM pos_labor
                        WHERE role IN ('Bartender', 'Bar Back')
                        ON CONFLICT (employee_id, first_name, last_name) DO NOTHING
                    """)
                )
            st.success("Synced. New FOH employees added with default multiplier.")
        except Exception as e:
            st.error(f"Error: {e}")

    emp_settings = get_payroll_employee_settings()
    if emp_settings.empty:
        st.info("No employee settings. Click **Sync employees from labor** first.")
    else:
        for _, r in emp_settings.iterrows():
            with st.expander(f"{r['last_name']}, {r['first_name']} ({r['employee_id'] or '—'})"):
                inc = st.checkbox("Include in tip pool", value=bool(r["include_in_tip_pool"]), key=f"inc_{r['id']}")
                mult = st.number_input(
                    "Tip pool multiplier",
                    min_value=0.0,
                    max_value=2.0,
                    value=float(r["tip_pool_multiplier"] or 1.0),
                    step=0.1,
                    format="%.2f",
                    key=f"mult_{r['id']}",
                )
                if st.button("Update", key=f"upd_{r['id']}"):
                    try:
                        with engine.begin() as conn:
                            conn.execute(
                                text("""
                                    UPDATE payroll_employee_settings
                                    SET include_in_tip_pool = :inc, tip_pool_multiplier = :mult
                                    WHERE id = :id
                                """),
                                {"id": int(r["id"]), "inc": inc, "mult": mult},
                            )
                        st.success("Updated.")
                    except Exception as ex:
                        st.error(str(ex))

st.markdown("---")
st.caption("Payroll | Bar Arbolada Analytics")
