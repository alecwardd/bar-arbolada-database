"""
Dashboard: Scheduling Suite & Demand Forecast
==============================================
Master scheduling tool for the GM.  Five tabs:
  1. Schedule Builder    — weekly shift calendar with auto-fill
  2. Employee Roster     — manage employees, availability, preferences
  3. Demand Forecast     — forward-looking demand with event overlays
  4. Staffing Advisor    — SPLH targeting, shift cut recs, labor budget
  5. Shift Templates     — reusable scheduling patterns
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import numpy as np
from datetime import date, datetime, time, timedelta
from sqlalchemy import text

from src.config import engine, get_session
from src.analytics.queries import (
    get_employees,
    get_employee_availability,
    get_schedule_entries,
    get_schedule_templates,
    get_template_shifts,
    get_external_events,
    get_upcoming_events,
    get_scheduling_settings,
)
from src.analytics.demand_forecast import (
    forecast_day,
    forecast_range,
    forecast_week_summary,
    recommend_staffing,
    get_shift_cut_recommendations,
    get_baseline_matrix,
    get_event_multipliers_historical,
)

st.title("📅 Scheduling Suite")
st.caption(
    "**Forward-looking**: build shifts, forecast demand, and set SPLH staffing "
    "targets. Historical staffing/productivity lives on **Staffing & Rush**; the "
    "labor-cost lens lives on **Profitability**."
)

# ── Tabs ─────────────────────────────────────────────────────────────────────

tab_builder, tab_roster, tab_forecast, tab_advisor, tab_templates = st.tabs([
    "Schedule Builder",
    "Employee Roster & Availability",
    "Demand Forecast",
    "Staffing Advisor",
    "Shift Templates",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: SCHEDULE BUILDER
# ══════════════════════════════════════════════════════════════════════════════

with tab_builder:
    st.subheader("Weekly Schedule Builder")

    col_date, col_actions = st.columns([2, 3])
    with col_date:
        today = date.today()
        next_monday = today + timedelta(days=(7 - today.weekday()) % 7)
        if next_monday == today and today.weekday() != 0:
            next_monday = today + timedelta(days=(7 - today.weekday()))
        week_start = st.date_input(
            "Week starting (Monday)",
            value=next_monday,
        )

    week_dates = [week_start + timedelta(days=i) for i in range(7)]
    week_end = week_dates[-1]
    dow_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    # Load forecast & events for context
    week_forecast = forecast_week_summary(week_start)
    events_df = get_external_events(week_start, week_end)
    schedule_df = get_schedule_entries(week_start, week_end)
    employees_df = get_employees(active_only=True)

    # ── Week overview KPIs ──
    st.markdown("---")
    st.caption("**Week Forecast Overview**")

    kpi_cols = st.columns(7)
    for i, (_, row) in enumerate(week_forecast.iterrows()):
        d = row["date"]
        with kpi_cols[i]:
            label = f"{dow_labels[i]}\n{d.strftime('%m/%d')}"
            event_badge = ""
            if row["event_names"]:
                event_badge = " ⚡"
            st.metric(
                label=f"{dow_labels[i]} {d.strftime('%m/%d')}{event_badge}",
                value=f"${row['predicted_sales']:,.0f}",
                delta=f"{int(row['rec_bartenders'])}BT + {int(row['rec_barbacks'])}BB",
                delta_color="off",
            )

    # ── Event alerts ──
    if not events_df.empty:
        st.markdown("#### ⚡ Events This Week")
        for _, ev in events_df.iterrows():
            impact_emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "massive": "🔴"}.get(
                ev["expected_impact"], "🟡"
            )
            time_str = ev["event_time"].strftime("%I:%M %p") if ev["event_time"] else ""
            st.info(
                f"{impact_emoji} **{ev['event_name']}** — "
                f"{ev['event_date'].strftime('%a %m/%d')} {time_str} "
                f"at {ev['venue'].replace('_', ' ').title()} "
                f"(Impact: {ev['expected_impact'].title()})"
            )

    # ── Current schedule grid ──
    st.markdown("---")
    st.markdown("#### Current Schedule")

    if schedule_df.empty:
        st.info("No shifts scheduled for this week yet. Use **Add Shift** below or **Auto-Fill** to generate.")
    else:
        for d, day_label in zip(week_dates, dow_labels):
            day_entries = schedule_df[schedule_df["schedule_date"] == d]
            if day_entries.empty:
                continue
            with st.expander(f"**{day_label} {d.strftime('%m/%d')}** — {len(day_entries)} shifts", expanded=True):
                display = day_entries[["first_name", "last_name", "role", "shift_start", "shift_end", "status"]].copy()
                display["Employee"] = display["first_name"] + " " + display["last_name"]
                display["Shift"] = display["shift_start"].apply(
                    lambda t: t.strftime("%I:%M %p") if isinstance(t, time) else str(t)
                ) + " - " + display["shift_end"].apply(
                    lambda t: t.strftime("%I:%M %p") if isinstance(t, time) else str(t)
                )
                display = display[["Employee", "role", "Shift", "status"]]
                display.columns = ["Employee", "Role", "Shift", "Status"]
                st.dataframe(display, hide_index=True, use_container_width=True)

    # ── Add shift form ──
    st.markdown("---")
    st.markdown("#### Add Shift")

    if employees_df.empty:
        st.warning("No active employees found. Add employees in the **Employee Roster** tab first.")
    else:
        with st.form("add_shift_form"):
            fc1, fc2, fc3 = st.columns(3)
            with fc1:
                emp_options = {
                    f"{r['first_name']} {r['last_name']}": int(r["id"])
                    for _, r in employees_df.iterrows()
                }
                emp_name = st.selectbox("Employee", options=list(emp_options.keys()))
            with fc2:
                shift_date = st.date_input("Date", value=week_start, min_value=week_start, max_value=week_end)
            with fc3:
                role = st.selectbox("Role", ["Bartender", "Bar Back"])

            tc1, tc2 = st.columns(2)
            with tc1:
                shift_start_time = st.time_input("Shift Start", value=time(16, 0))
            with tc2:
                shift_end_time = st.time_input("Shift End", value=time(23, 0))

            submitted = st.form_submit_button("Add Shift", type="primary")
            if submitted and emp_name:
                emp_id = emp_options[emp_name]
                with engine.begin() as conn:
                    conn.execute(text("""
                        INSERT INTO schedule_entries
                            (employee_id, schedule_date, role, shift_start, shift_end, status)
                        VALUES (:eid, :sd, :role, :ss, :se, 'scheduled')
                        ON CONFLICT (employee_id, schedule_date)
                        DO UPDATE SET role = :role, shift_start = :ss, shift_end = :se,
                                      updated_at = NOW()
                    """), {
                        "eid": emp_id,
                        "sd": shift_date,
                        "role": role,
                        "ss": shift_start_time,
                        "se": shift_end_time,
                    })
                st.success(f"Shift added for {emp_name} on {shift_date.strftime('%m/%d')}.")
                st.rerun()

    # ── Auto-fill ──
    st.markdown("---")
    if st.button("🤖 Auto-Fill Week from Forecast", type="secondary"):
        avail_df = get_employee_availability()
        active_emps = employees_df[employees_df["status"] == "active"]
        if active_emps.empty:
            st.warning("No active employees to schedule.")
        else:
            added = 0
            for d in week_dates:
                rec = recommend_staffing(d)
                py_dow = d.weekday()  # Mon=0..Sun=6

                available = []
                for _, emp in active_emps.iterrows():
                    if not avail_df.empty:
                        emp_avail = avail_df[
                            (avail_df["employee_id"] == emp["id"]) &
                            (avail_df["day_of_week"] == py_dow)
                        ]
                        if not emp_avail.empty and emp_avail.iloc[0]["preference"] == "unavailable":
                            continue
                    available.append(emp)

                bt_needed = rec["recommended_bartenders"]
                bb_needed = rec["recommended_barbacks"]

                bartenders = [e for e in available if e["primary_role"] == "Bartender"]
                barbacks = [e for e in available if e["primary_role"] == "Bar Back"]
                others = [e for e in available if e["primary_role"] not in ("Bartender", "Bar Back")]

                assignments = []
                for emp in bartenders[:bt_needed]:
                    assignments.append((emp, "Bartender"))
                if len(assignments) < bt_needed:
                    for emp in others[:bt_needed - len(assignments)]:
                        assignments.append((emp, "Bartender"))

                for emp in barbacks[:bb_needed]:
                    assignments.append((emp, "Bar Back"))
                if len([a for a in assignments if a[1] == "Bar Back"]) < bb_needed:
                    remaining = [e for e in others if not any(a[0]["id"] == e["id"] for a in assignments)]
                    for emp in remaining[:bb_needed - len([a for a in assignments if a[1] == "Bar Back"])]:
                        assignments.append((emp, "Bar Back"))

                with engine.begin() as conn:
                    for emp, role in assignments:
                        conn.execute(text("""
                            INSERT INTO schedule_entries
                                (employee_id, schedule_date, role, shift_start, shift_end, status)
                            VALUES (:eid, :sd, :role, :ss, :se, 'scheduled')
                            ON CONFLICT (employee_id, schedule_date) DO NOTHING
                        """), {
                            "eid": int(emp["id"]),
                            "sd": d,
                            "role": role,
                            "ss": time(16, 0),
                            "se": time(0, 0),
                        })
                        added += 1

            st.success(f"Auto-filled {added} shifts across the week based on demand forecast.")
            st.rerun()

    # ── Labor cost projection ──
    st.markdown("---")
    st.markdown("#### Week Labor Projection")
    total_pred = week_forecast["predicted_sales"].sum()
    total_labor = week_forecast["projected_labor_cost"].sum()
    pct = (total_labor / total_pred * 100) if total_pred > 0 else 0

    lc1, lc2, lc3 = st.columns(3)
    with lc1:
        st.metric("Projected Sales", f"${total_pred:,.0f}")
    with lc2:
        st.metric("Projected Labor Cost", f"${total_labor:,.0f}")
    with lc3:
        st.metric("Projected Labor %", f"{pct:.1f}%")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: EMPLOYEE ROSTER & AVAILABILITY
# ══════════════════════════════════════════════════════════════════════════════

with tab_roster:
    st.subheader("Employee Roster & Availability")

    roster_tab, avail_tab, add_emp_tab = st.tabs([
        "Roster",
        "Availability",
        "Add / Edit Employee",
    ])

    # ── Roster ──
    with roster_tab:
        emp_df = get_employees(active_only=False)
        if emp_df.empty:
            st.info("No employees found. Run `python scripts/seed_employees.py` to seed from POS data.")
        else:
            status_filter = st.multiselect(
                "Filter by status", ["active", "inactive", "terminated"],
                default=["active"],
            )
            filtered = emp_df[emp_df["status"].isin(status_filter)] if status_filter else emp_df

            display_roster = filtered[[
                "first_name", "last_name", "primary_role", "status",
                "hire_date", "max_hours_per_week", "phone",
            ]].copy()
            display_roster.columns = ["First", "Last", "Role", "Status", "Hire Date", "Max Hrs/Wk", "Phone"]
            st.dataframe(display_roster, hide_index=True, use_container_width=True)

            st.caption(f"{len(filtered)} employee(s) shown.")

    # ── Availability ──
    with avail_tab:
        st.caption("Set weekly availability per employee. This replaces the iCloud notes workflow.")
        emp_df = get_employees(active_only=True)
        if emp_df.empty:
            st.info("No active employees.")
        else:
            emp_names = {f"{r['first_name']} {r['last_name']}": int(r["id"]) for _, r in emp_df.iterrows()}
            selected_emp = st.selectbox("Select Employee", list(emp_names.keys()), key="avail_emp")
            sel_emp_id = emp_names[selected_emp]

            avail = get_employee_availability(sel_emp_id)
            day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

            # Show current availability
            if avail.empty:
                st.info(f"No availability set for {selected_emp}. Use the form below to add.")
            else:
                avail_display = avail[["day_of_week", "preference", "available_from", "available_until", "notes"]].copy()
                avail_display["Day"] = avail_display["day_of_week"].apply(lambda d: day_names[d] if 0 <= d <= 6 else "?")
                avail_display["From"] = avail_display["available_from"].apply(
                    lambda t: t.strftime("%I:%M %p") if t else "Open"
                )
                avail_display["Until"] = avail_display["available_until"].apply(
                    lambda t: t.strftime("%I:%M %p") if t else "Close"
                )
                avail_display = avail_display[["Day", "preference", "From", "Until", "notes"]]
                avail_display.columns = ["Day", "Preference", "From", "Until", "Notes"]
                st.dataframe(avail_display, hide_index=True, use_container_width=True)

            # Add/update availability form
            st.markdown("**Set Availability**")
            with st.form("set_availability"):
                ac1, ac2, ac3 = st.columns(3)
                with ac1:
                    sel_day = st.selectbox("Day of Week", day_names)
                    sel_dow = day_names.index(sel_day)
                with ac2:
                    pref = st.selectbox("Preference", ["available", "preferred", "unavailable"])
                with ac3:
                    avail_notes = st.text_input("Notes", placeholder="e.g., class until 3pm")

                at1, at2 = st.columns(2)
                with at1:
                    avail_from = st.time_input("Available From (leave 12:00 AM for all day)", value=time(0, 0),
                                               key="avail_from")
                with at2:
                    avail_until = st.time_input("Available Until (leave 12:00 AM for all day)", value=time(0, 0),
                                                key="avail_until")

                avail_submit = st.form_submit_button("Save Availability")
                if avail_submit:
                    from_val = avail_from if avail_from != time(0, 0) else None
                    until_val = avail_until if avail_until != time(0, 0) else None
                    if pref == "unavailable":
                        from_val = None
                        until_val = None

                    with engine.begin() as conn:
                        conn.execute(text("""
                            DELETE FROM employee_availability
                            WHERE employee_id = :eid AND day_of_week = :dow
                              AND (end_date IS NULL OR end_date >= CURRENT_DATE)
                        """), {"eid": sel_emp_id, "dow": sel_dow})

                        conn.execute(text("""
                            INSERT INTO employee_availability
                                (employee_id, day_of_week, available_from, available_until,
                                 preference, effective_date, notes)
                            VALUES (:eid, :dow, :af, :au, :pref, CURRENT_DATE, :notes)
                        """), {
                            "eid": sel_emp_id,
                            "dow": sel_dow,
                            "af": from_val,
                            "au": until_val,
                            "pref": pref,
                            "notes": avail_notes or None,
                        })
                    st.success(f"Availability saved for {selected_emp} on {sel_day}.")
                    st.rerun()

    # ── Add/Edit Employee ──
    with add_emp_tab:
        st.markdown("**Add New Employee**")
        with st.form("add_employee"):
            ne1, ne2 = st.columns(2)
            with ne1:
                new_first = st.text_input("First Name")
            with ne2:
                new_last = st.text_input("Last Name")
            ne3, ne4 = st.columns(2)
            with ne3:
                new_role = st.selectbox("Primary Role", ["Bartender", "Bar Back"])
            with ne4:
                new_max_hrs = st.number_input("Max Hours/Week", min_value=0, max_value=60, value=40)
            ne5, ne6 = st.columns(2)
            with ne5:
                new_phone = st.text_input("Phone (optional)")
            with ne6:
                new_email = st.text_input("Email (optional)")

            add_sub = st.form_submit_button("Add Employee", type="primary")
            if add_sub and new_first and new_last:
                with engine.begin() as conn:
                    conn.execute(text("""
                        INSERT INTO employees
                            (pos_employee_id, first_name, last_name, primary_role,
                             max_hours_per_week, phone, email, status)
                        VALUES ('', :fn, :ln, :role, :mh, :phone, :email, 'active')
                        ON CONFLICT (pos_employee_id, first_name, last_name) DO NOTHING
                    """), {
                        "fn": new_first.strip(),
                        "ln": new_last.strip(),
                        "role": new_role,
                        "mh": new_max_hrs,
                        "phone": new_phone.strip() or None,
                        "email": new_email.strip() or None,
                    })
                st.success(f"Employee {new_first} {new_last} added.")
                st.rerun()

        # Deactivate employee
        st.markdown("---")
        st.markdown("**Deactivate Employee**")
        emp_df_all = get_employees(active_only=True)
        if not emp_df_all.empty:
            deact_names = {f"{r['first_name']} {r['last_name']}": int(r["id"]) for _, r in emp_df_all.iterrows()}
            deact_sel = st.selectbox("Select employee to deactivate", list(deact_names.keys()), key="deact_emp")
            if st.button("Deactivate", type="secondary"):
                with engine.begin() as conn:
                    conn.execute(text("""
                        UPDATE employees SET status = 'inactive', updated_at = NOW()
                        WHERE id = :eid
                    """), {"eid": deact_names[deact_sel]})
                st.success(f"{deact_sel} has been deactivated.")
                st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: DEMAND FORECAST
# ══════════════════════════════════════════════════════════════════════════════

with tab_forecast:
    st.subheader("Demand Forecast")
    st.caption("Forward-looking demand predictions with event overlays.")

    fc_start = st.date_input("Forecast start", value=date.today(), key="fc_start")
    fc_days = st.slider("Days to forecast", min_value=7, max_value=30, value=14, key="fc_days")
    fc_end = fc_start + timedelta(days=fc_days - 1)

    forecasts = forecast_range(fc_start, fc_end)

    # ── Daily forecast table ──
    daily_rows = []
    for f in forecasts:
        event_str = ", ".join(e["name"] for e in f["events"]) if f["events"] else ""
        daily_rows.append({
            "Date": f["date"].strftime("%a %m/%d"),
            "Predicted Sales": f"${f['predicted_daily_sales']:,.0f}",
            "Predicted Checks": f"{f['predicted_checks']:.0f}",
            "Event Mult": f"{f['event_multiplier']:.2f}x" if f["event_multiplier"] != 1.0 else "—",
            "Seasonal": f"{f['seasonal_factor']:.2f}x",
            "Trend": f"{f['trend_factor']:.2f}x",
            "Events": event_str,
        })
    st.dataframe(pd.DataFrame(daily_rows), hide_index=True, use_container_width=True)

    # ── Predicted sales chart ──
    st.markdown("#### Predicted Daily Sales")
    chart_data = pd.DataFrame([{
        "date": f["date"],
        "predicted_sales": f["predicted_daily_sales"],
        "has_event": len(f["events"]) > 0,
    } for f in forecasts])

    if not chart_data.empty:
        colors = ["#e76f51" if ev else "#2d6a4f" for ev in chart_data["has_event"]]
        fig = go.Figure(data=go.Bar(
            x=chart_data["date"],
            y=chart_data["predicted_sales"],
            marker_color=colors,
            text=chart_data["predicted_sales"].apply(lambda x: f"${x:,.0f}"),
            textposition="outside",
        ))
        fig.update_layout(
            yaxis_title="Predicted Net Sales ($)",
            height=400,
            margin=dict(t=30, b=10),
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption("🟩 Normal day  |  🟧 Event day")

    # ── Hourly detail for a selected day ──
    st.markdown("---")
    st.markdown("#### Hourly Demand Detail")
    detail_date = st.date_input("Select day for hourly breakdown", value=fc_start, key="detail_date")
    detail_fc = forecast_day(detail_date)

    if detail_fc["hourly"]:
        hr_df = pd.DataFrame(detail_fc["hourly"])
        biz_hours = list(range(11, 24)) + [0, 1, 2]
        hour_order = {h: i for i, h in enumerate(biz_hours)}
        hr_df["sort_key"] = hr_df["hour"].map(hour_order)
        hr_df = hr_df.sort_values("sort_key")
        hr_df["hour_label"] = hr_df["hour"].apply(lambda h: f"{h % 12 or 12}{'am' if h < 12 else 'pm'}")

        fig_h = go.Figure()
        fig_h.add_trace(go.Bar(
            x=hr_df["hour_label"],
            y=hr_df["predicted_sales"],
            name="Predicted",
            marker_color="#2d6a4f",
        ))
        fig_h.add_trace(go.Scatter(
            x=hr_df["hour_label"],
            y=hr_df["baseline_sales"],
            name="Baseline (no events)",
            mode="lines+markers",
            marker=dict(color="#999", size=6),
            line=dict(color="#999", dash="dash"),
        ))
        fig_h.update_layout(
            yaxis_title="Predicted Sales ($)",
            height=400,
            margin=dict(t=30, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig_h, use_container_width=True)

        if detail_fc["events"]:
            for ev in detail_fc["events"]:
                st.info(f"⚡ **{ev['name']}** ({ev['type']}) at {ev['venue'].replace('_', ' ').title()} — "
                        f"Impact: {ev['impact'].title()}")

    # ── Event multiplier analysis ──
    st.markdown("---")
    st.markdown("#### Historical Event Impact")
    st.caption("How much do events boost sales compared to normal same-day-of-week averages?")

    hist_mult = get_event_multipliers_historical()
    if hist_mult.empty:
        st.info("No historical event data yet. Import Thunder games or events to see impact analysis.")
    else:
        hist_mult["avg_event_sales"] = hist_mult["avg_event_sales"].astype(float)
        hist_mult["avg_normal_sales"] = hist_mult["avg_normal_sales"].astype(float)
        hist_mult["multiplier"] = hist_mult["multiplier"].astype(float)
        hist_display = hist_mult.copy()
        hist_display["Avg Event Sales"] = hist_display["avg_event_sales"].apply(lambda x: f"${x:,.0f}")
        hist_display["Avg Normal Sales"] = hist_display["avg_normal_sales"].apply(lambda x: f"${x:,.0f}")
        hist_display["Multiplier"] = hist_display["multiplier"].apply(lambda x: f"{x:.2f}x")
        hist_display["Sample Size"] = hist_display["sample_size"].astype(int)
        hist_display = hist_display[["event_type", "Avg Event Sales", "Avg Normal Sales", "Multiplier", "Sample Size"]]
        hist_display.columns = ["Event Type", "Avg Event Sales", "Avg Normal Sales", "Multiplier", "Sample Size"]
        st.dataframe(hist_display, hide_index=True, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4: STAFFING ADVISOR
# ══════════════════════════════════════════════════════════════════════════════

with tab_advisor:
    st.subheader("Staffing Advisor")
    st.caption("Data-driven staffing recommendations balancing service quality and labor cost.")

    # ── Settings ──
    sched_settings = get_scheduling_settings()
    current_splh = float(sched_settings.iloc[0]["target_splh"]) if not sched_settings.empty else 55.0

    adv_c1, adv_c2 = st.columns([1, 3])
    with adv_c1:
        target_splh = st.slider(
            "Target SPLH ($)",
            min_value=30, max_value=100, value=int(current_splh),
            step=5,
            help="Higher = fewer staff (lower cost, higher risk of bad service). "
                 "Lower = more staff (better service, higher labor cost).",
        )

    # ── Daily recommendations for next 7 days ──
    st.markdown("#### Next 7 Days — Staffing Recommendations")

    adv_start = date.today()
    rec_rows = []
    for i in range(7):
        d = adv_start + timedelta(days=i)
        rec = recommend_staffing(d, target_splh=float(target_splh))
        events = forecast_day(d)["events"]
        event_str = ", ".join(e["name"] for e in events) if events else ""
        dow_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        rec_rows.append({
            "Day": f"{dow_names[d.weekday()]} {d.strftime('%m/%d')}",
            "Predicted Sales": f"${rec['predicted_sales']:,.0f}",
            "Labor Hours": f"{rec['required_labor_hours']:.1f}",
            "Bartenders": rec["recommended_bartenders"],
            "Bar Backs": rec["recommended_barbacks"],
            "Est. Labor Cost": f"${rec['projected_labor_cost']:,.0f}",
            "Labor %": f"{rec['projected_labor_pct']:.1f}%",
            "Events": event_str,
        })
    st.dataframe(pd.DataFrame(rec_rows), hide_index=True, use_container_width=True)

    # ── Shift cut recommendations ──
    st.markdown("---")
    st.markdown("#### Shift Cut Recommendations by Day of Week")
    st.caption(
        "Based on rolling 8-week averages, when does demand drop enough to cut a bartender? "
        f"Current threshold: ${int(current_splh)}/hr per bartender."
    )

    cuts_df = get_shift_cut_recommendations()
    if cuts_df.empty:
        st.info("No baseline data available for shift cut analysis.")
    else:
        cuts_with_action = cuts_df[cuts_df["action"] != ""].copy()
        if cuts_with_action.empty:
            st.success("No cut recommendations — demand stays consistent through service hours on all days.")
        else:
            cuts_with_action["hour_label"] = cuts_with_action["hour"].apply(
                lambda h: f"{h % 12 or 12}:00 {'AM' if h < 12 else 'PM'}"
            )
            display_cuts = cuts_with_action[["dow_name", "hour_label", "avg_sales", "recommended_bartenders", "action"]].copy()
            display_cuts.columns = ["Day", "Time", "Avg Hourly Sales", "Rec. Bartenders", "Action"]
            display_cuts["Avg Hourly Sales"] = display_cuts["Avg Hourly Sales"].apply(lambda x: f"${x:,.0f}")
            st.dataframe(display_cuts, hide_index=True, use_container_width=True)

    # ── Hourly staffing detail for a selected day ──
    st.markdown("---")
    st.markdown("#### Hourly Staffing Detail")
    adv_detail_date = st.date_input("Select day", value=date.today(), key="adv_detail")
    adv_rec = recommend_staffing(adv_detail_date, target_splh=float(target_splh))

    if adv_rec["hourly_staffing"]:
        hs_df = pd.DataFrame(adv_rec["hourly_staffing"])
        biz_hours = list(range(11, 24)) + [0, 1, 2]
        hour_order = {h: i for i, h in enumerate(biz_hours)}
        hs_df["sort_key"] = hs_df["hour"].map(hour_order)
        hs_df = hs_df.sort_values("sort_key")
        hs_df["hour_label"] = hs_df["hour"].apply(lambda h: f"{h % 12 or 12}{'am' if h < 12 else 'pm'}")

        fig_staff = go.Figure()
        fig_staff.add_trace(go.Bar(
            x=hs_df["hour_label"],
            y=hs_df["predicted_sales"],
            name="Predicted Sales",
            marker_color="#2d6a4f",
            opacity=0.5,
            yaxis="y",
        ))
        fig_staff.add_trace(go.Scatter(
            x=hs_df["hour_label"],
            y=hs_df["bartenders"],
            name="Bartenders",
            mode="lines+markers",
            marker=dict(color="#e76f51", size=10),
            line=dict(color="#e76f51", width=3),
            yaxis="y2",
        ))
        fig_staff.add_trace(go.Scatter(
            x=hs_df["hour_label"],
            y=hs_df["barbacks"],
            name="Bar Backs",
            mode="lines+markers",
            marker=dict(color="#264653", size=8),
            line=dict(color="#264653", width=2, dash="dot"),
            yaxis="y2",
        ))
        fig_staff.update_layout(
            yaxis=dict(title="Predicted Sales ($)", side="left"),
            yaxis2=dict(title="Staff Count", side="right", overlaying="y",
                        dtick=1, rangemode="tozero"),
            height=450,
            margin=dict(t=30, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig_staff, use_container_width=True)

        if adv_rec["shift_cuts"]:
            st.markdown("**Recommended Cuts:**")
            for cut in adv_rec["shift_cuts"]:
                hour_label = f"{cut['hour'] % 12 or 12}:00 {'AM' if cut['hour'] < 12 else 'PM'}"
                st.warning(f"⏱️ **{hour_label}**: {cut['action']} — {cut['reason']}")

    # ── Labor budget calculator ──
    st.markdown("---")
    st.markdown("#### Weekly Labor Budget Calculator")
    st.caption("Set a weekly labor budget and see how it should be allocated across days.")

    budget = st.number_input("Weekly Labor Budget ($)", min_value=500, max_value=10000, value=3000, step=100)
    week_fc = forecast_week_summary(date.today())
    if not week_fc.empty:
        total_pred = week_fc["predicted_sales"].sum()
        if total_pred > 0:
            week_fc["sales_share"] = week_fc["predicted_sales"] / total_pred
            week_fc["budget_allocation"] = (week_fc["sales_share"] * budget).round(0)

            budget_display = week_fc[["date", "dow_name", "predicted_sales", "sales_share", "budget_allocation"]].copy()
            budget_display["date"] = budget_display["date"].apply(lambda d: d.strftime("%m/%d"))
            budget_display["predicted_sales"] = budget_display["predicted_sales"].apply(lambda x: f"${x:,.0f}")
            budget_display["sales_share"] = budget_display["sales_share"].apply(lambda x: f"{x:.0%}")
            budget_display["budget_allocation"] = budget_display["budget_allocation"].apply(lambda x: f"${x:,.0f}")
            budget_display.columns = ["Date", "Day", "Predicted Sales", "Share", "Budget Allocation"]
            st.dataframe(budget_display, hide_index=True, use_container_width=True)

    # ── Upcoming events alert ──
    st.markdown("---")
    st.markdown("#### Upcoming Events (Next 14 Days)")
    upcoming = get_upcoming_events(days=14)
    if upcoming.empty:
        st.info(
            "No events in the next 14 days. Import Thunder games with "
            "`python scripts/fetch_events.py thunder` or add events manually below."
        )
    else:
        for _, ev in upcoming.iterrows():
            impact_emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "massive": "🔴"}.get(
                ev["expected_impact"], "🟡"
            )
            time_str = ev["event_time"].strftime("%I:%M %p") if ev["event_time"] else ""
            st.write(
                f"{impact_emoji} **{ev['event_date'].strftime('%a %m/%d')}** {time_str} — "
                f"{ev['event_name']} ({ev['venue'].replace('_', ' ').title()})"
            )

    # ── Manual event entry ──
    st.markdown("---")
    st.markdown("#### Add Event Manually")
    with st.form("add_event"):
        ev1, ev2, ev3 = st.columns(3)
        with ev1:
            ev_date = st.date_input("Event Date", value=date.today(), key="ev_date")
        with ev2:
            ev_time = st.time_input("Event Time", value=time(19, 0), key="ev_time")
        with ev3:
            ev_venue = st.selectbox("Venue", ["paycom_center", "civic_center", "other"], key="ev_venue")

        ev4, ev5, ev6 = st.columns(3)
        with ev4:
            ev_type = st.selectbox("Event Type", ["thunder_home", "concert", "show", "convention"], key="ev_type")
        with ev5:
            ev_name = st.text_input("Event Name", key="ev_name")
        with ev6:
            ev_impact = st.selectbox("Expected Impact", ["low", "medium", "high", "massive"], index=2, key="ev_impact")

        ev_attendance = st.number_input("Estimated Attendance (optional)", min_value=0, value=0, key="ev_att")

        ev_submit = st.form_submit_button("Add Event", type="primary")
        if ev_submit and ev_name:
            with engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO external_events
                        (event_date, event_time, venue, event_type, event_name,
                         expected_impact, estimated_attendance)
                    VALUES (:ed, :et, :v, :etype, :en, :ei, :ea)
                    ON CONFLICT (event_date, venue, event_name) DO NOTHING
                """), {
                    "ed": ev_date,
                    "et": ev_time,
                    "v": ev_venue,
                    "etype": ev_type,
                    "en": ev_name.strip(),
                    "ei": ev_impact,
                    "ea": ev_attendance if ev_attendance > 0 else None,
                })
            st.success(f"Event '{ev_name}' added for {ev_date.strftime('%m/%d')}.")
            st.rerun()

    # ── Update scheduling settings ──
    st.markdown("---")
    with st.expander("⚙️ Scheduling Engine Settings"):
        ss = get_scheduling_settings()
        if not ss.empty:
            row = ss.iloc[0]
            with st.form("sched_settings"):
                ss1, ss2, ss3 = st.columns(3)
                with ss1:
                    new_splh = st.number_input("Target SPLH", value=float(row["target_splh"]), step=5.0)
                    new_min_bt = st.number_input("Min Bartenders", value=int(row["min_bartenders"]), min_value=1)
                with ss2:
                    new_min_bb = st.number_input("Min Bar Backs", value=int(row["min_barbacks"]), min_value=0)
                    new_shift_len = st.number_input("Default Shift Length (hrs)", value=float(row["default_shift_length_hours"]), step=0.5)
                with ss3:
                    new_cut = st.number_input("Cut Threshold ($/hr per BT)", value=float(row["cut_threshold_per_bartender"]), step=10.0)
                    new_bt_ratio = st.number_input("Bartender Hour Ratio", value=float(row["bartender_hour_ratio"]), step=0.05, min_value=0.3, max_value=0.9)

                st.markdown("**Event Multiplier Defaults** (used before enough historical data)")
                em1, em2, em3, em4 = st.columns(4)
                with em1:
                    new_m_thunder = st.number_input("Thunder", value=float(row["event_multiplier_thunder"]), step=0.1)
                with em2:
                    new_m_concert = st.number_input("Concert", value=float(row["event_multiplier_concert"]), step=0.1)
                with em3:
                    new_m_show = st.number_input("Show", value=float(row["event_multiplier_show"]), step=0.1)
                with em4:
                    new_m_conv = st.number_input("Convention", value=float(row["event_multiplier_convention"]), step=0.1)

                save_settings = st.form_submit_button("Save Settings", type="primary")
                if save_settings:
                    with engine.begin() as conn:
                        conn.execute(text("""
                            UPDATE scheduling_settings SET
                                target_splh = :splh, min_bartenders = :mbt, min_barbacks = :mbb,
                                default_shift_length_hours = :sl, bartender_hour_ratio = :btr,
                                cut_threshold_per_bartender = :ct,
                                event_multiplier_thunder = :mt, event_multiplier_concert = :mc,
                                event_multiplier_show = :ms, event_multiplier_convention = :mv,
                                updated_at = NOW()
                            WHERE id = 1
                        """), {
                            "splh": new_splh, "mbt": new_min_bt, "mbb": new_min_bb,
                            "sl": new_shift_len, "btr": new_bt_ratio, "ct": new_cut,
                            "mt": new_m_thunder, "mc": new_m_concert,
                            "ms": new_m_show, "mv": new_m_conv,
                        })
                    st.success("Settings saved.")
                    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 5: SHIFT TEMPLATES
# ══════════════════════════════════════════════════════════════════════════════

with tab_templates:
    st.subheader("Shift Templates")
    st.caption(
        "Create reusable templates for different day types. "
        "Define what roles and shifts are needed for Weekday Normal, Weekend, Thunder Game Day, etc."
    )

    templates_df = get_schedule_templates()

    if templates_df.empty:
        st.info("No templates created yet. Use the form below to create your first template.")
    else:
        for _, tmpl in templates_df.iterrows():
            with st.expander(
                f"**{tmpl['name']}** ({tmpl['day_type']}) — "
                f"{int(tmpl['total_headcount'])} staff across {int(tmpl['shift_count'])} shifts"
            ):
                shifts = get_template_shifts(int(tmpl["id"]))
                if shifts.empty:
                    st.info("No shifts defined for this template.")
                else:
                    shift_display = shifts.copy()
                    shift_display["Shift"] = shift_display["shift_start"].apply(
                        lambda t: t.strftime("%I:%M %p") if isinstance(t, time) else str(t)
                    ) + " - " + shift_display["shift_end"].apply(
                        lambda t: t.strftime("%I:%M %p") if isinstance(t, time) else str(t)
                    )
                    shift_display = shift_display[["role", "Shift", "headcount"]]
                    shift_display.columns = ["Role", "Shift Time", "Headcount"]
                    st.dataframe(shift_display, hide_index=True, use_container_width=True)

                # Add shift to template
                with st.form(f"add_shift_tmpl_{tmpl['id']}"):
                    ts1, ts2, ts3, ts4 = st.columns(4)
                    with ts1:
                        ts_role = st.selectbox("Role", ["Bartender", "Bar Back"], key=f"ts_role_{tmpl['id']}")
                    with ts2:
                        ts_start = st.time_input("Start", value=time(16, 0), key=f"ts_start_{tmpl['id']}")
                    with ts3:
                        ts_end = st.time_input("End", value=time(0, 0), key=f"ts_end_{tmpl['id']}")
                    with ts4:
                        ts_hc = st.number_input("Headcount", min_value=1, max_value=10, value=1, key=f"ts_hc_{tmpl['id']}")

                    ts_sub = st.form_submit_button("Add Shift to Template")
                    if ts_sub:
                        with engine.begin() as conn:
                            conn.execute(text("""
                                INSERT INTO schedule_template_shifts
                                    (template_id, role, shift_start, shift_end, headcount)
                                VALUES (:tid, :role, :ss, :se, :hc)
                            """), {
                                "tid": int(tmpl["id"]),
                                "role": ts_role,
                                "ss": ts_start,
                                "se": ts_end,
                                "hc": ts_hc,
                            })
                        st.success("Shift added to template.")
                        st.rerun()

                # Delete template
                if st.button(f"🗑️ Delete Template", key=f"del_tmpl_{tmpl['id']}"):
                    with engine.begin() as conn:
                        conn.execute(text("DELETE FROM schedule_template_shifts WHERE template_id = :tid"),
                                     {"tid": int(tmpl["id"])})
                        conn.execute(text("DELETE FROM schedule_templates WHERE id = :tid"),
                                     {"tid": int(tmpl["id"])})
                    st.success(f"Template '{tmpl['name']}' deleted.")
                    st.rerun()

    # ── Create new template ──
    st.markdown("---")
    st.markdown("#### Create New Template")
    with st.form("create_template"):
        ct1, ct2 = st.columns(2)
        with ct1:
            tmpl_name = st.text_input("Template Name", placeholder="e.g., Thunder Game Day")
        with ct2:
            tmpl_type = st.selectbox("Day Type", ["weekday", "weekend", "event"])
        tmpl_notes = st.text_input("Notes (optional)", placeholder="e.g., Used for Thunder home games")

        ct_sub = st.form_submit_button("Create Template", type="primary")
        if ct_sub and tmpl_name:
            with engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO schedule_templates (name, day_type, notes)
                    VALUES (:name, :dtype, :notes)
                    ON CONFLICT (name) DO NOTHING
                """), {
                    "name": tmpl_name.strip(),
                    "dtype": tmpl_type,
                    "notes": tmpl_notes.strip() or None,
                })
            st.success(f"Template '{tmpl_name}' created. Expand it above to add shifts.")
            st.rerun()


# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption("Scheduling Suite | Bar Arbolada Analytics")
